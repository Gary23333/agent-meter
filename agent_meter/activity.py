"""Recent session/turn activity across local harness ledgers (read-only).

A lightweight view beside the full snapshot: it scans only a recent window
(default 24 h) of local ledgers and aggregates per session/thread, so the
panel can show what is running right now without re-running full account
collection or full-history parsing. Only usage, status and path metadata
are read; prompts, conversation text, tool output and session titles are
never read.

Status vocabulary (deliberately narrow; unknown never means failed):
- running:         explicit recent activity evidence (last event within
                   activity_idle_minutes);
- suspected_ended: no new events for longer than the idle threshold; no
                   completion is claimed;
- completed/failed/cancelled: accepted only from explicit status events;
- unknown:         truncated logs, unrecognized statuses, thin coverage.

Per-source granularity and what a row can NOT claim:
- zcode / deepseek_harness / kimi / kimi_desktop: the row is a session;
  its own status is recency-based, while explicit turn-level outcomes
  surface as turn_statuses / last_turn_status / recent_turns (回合完成 ≠
  整个会话完成, 子代理完成 ≠ 根任务完成);
- codex_images: the row is one generation thread; call statuses are
  explicit (completed/failed/generating);
- claude / gemini / opencode: recent_activity rows are recency-only
  (停止写入不能算成功, 应用退出也不能算失败).
"""
import json
import time
from pathlib import Path, PurePath

from . import opencode_tokens, peak, zcode_local
from .applications import app_id
from .cli_sessions import _readonly_sqlite, _claude_paths
from .codex_images import history_threads, resolve_history_db
from .dsh_tokens import _key_part
from .zstd_io import ZSTD_ERRORS as _ZSTD_ERRORS, decompressed as _decompressed, route as _route
from .model import DISPLAY_ZONE, SourceError, timestamp
from .record_cache import RecordCache

# Small dedicated cache: activity polling must never evict the token
# ledger's shared 16 MB record cache.
activity_cache = RecordCache(max_bytes=4 * 1024 * 1024, max_entries=256)

STATUS_RANK = {"running": 0, "suspected_ended": 1, "completed": 2,
               "cancelled": 3, "failed": 4, "unknown": 5}
TOKEN_KEYS = ("fresh_input", "output", "reasoning", "cache_read", "cache_write")
# Explicit terminal vocabulary: anything else maps to unknown.
TERMINAL_MAP = {"completed": "completed", "ok": "completed", "error": "failed",
                "failed": "failed", "aborted": "cancelled", "cancelled": "cancelled",
                "canceled": "cancelled"}
RECENT_TURNS_LIMIT = 5

NOTE_TURN_NOT_SESSION = "turn_status_not_session_status"
NOTE_RECENCY_ONLY = "recency_only_no_terminal_events"
NOTE_CALL_NOT_SESSION = "call_status_not_whole_session"


def _tokens_dict(**values):
    clean = {key: _nonneg(values.get(key, 0)) for key in TOKEN_KEYS}
    clean["total_tokens"] = sum(clean.values())
    return clean


def _nonneg(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _alias_of(path):
    if not isinstance(path, str) or not path:
        return None
    return PurePath(path).name or None


def _terminal_status(reason):
    """Map an explicit event reason onto the status vocabulary."""
    if not isinstance(reason, str):
        return "unknown"
    return TERMINAL_MAP.get(reason.strip().lower(), "unknown")


def _activity(app, granularity, *, status, status_basis, session_id, project_path=None,
              project_alias=None, started_at=None, last_event_at=None, last_model=None,
              requests=None, tokens=None, subagent=False, notes=None, extra=None):
    row = {
        "app": app, "granularity": granularity, "status": status,
        "status_basis": status_basis,
        "project_alias": project_alias or _alias_of(project_path), "project_path": project_path,
        "session_id": session_id, "subagent": bool(subagent),
        "started_at": timestamp(started_at) if started_at else None,
        "last_event_at": timestamp(last_event_at) if last_event_at else None,
        "last_model": last_model, "requests": requests, "tokens": tokens,
        "estimated_cost_usd": None, "notes": notes,
    }
    if extra:
        row.update(extra)
    return row


def _recency_status(last_event_at, now, idle_seconds):
    """running with fresh evidence, else suspected_ended; never a claim of success."""
    if last_event_at is not None and now - last_event_at <= idle_seconds:
        return "running", "recency"
    return "suspected_ended", "recency"


def _sort_key(row):
    stamp = row["last_event_at"]["epoch_seconds"] if row["last_event_at"] else 0
    return (STATUS_RANK.get(row["status"], 5), -stamp)


def _cost_record(buckets, model, when, fresh, output, reasoning, read, write):
    key = (model, not peak.is_offpeak(when))
    bucket = buckets.setdefault(key, dict.fromkeys(TOKEN_KEYS, 0))
    for field, value in zip(TOKEN_KEYS, (fresh, output, reasoning, read, write)):
        bucket[field] += _nonneg(value)


def _cost_usd(table, buckets):
    if table is None or not buckets:
        return None
    total = 0
    for (model, at_peak), counts in buckets.items():
        pattern = table.match(model)
        if not pattern:
            return None
        total += table.cost_for(counts, pattern, peak=at_peak)
    return float(round(total, 6))


def codex_activities(db_path, window_start, idle_seconds, now):
    # Only thread metadata. The index's tokens_used is lifetime usage and
    # cannot be attributed to this activity window.
    with _readonly_sqlite(db_path, "codex_state_not_found", "codex_state_unreadable") as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(threads)")}
        if not {"id", "cwd", "created_at", "updated_at"} <= cols:
            raise SourceError("unsupported_codex_state_schema")
        recency = "coalesce(recency_at,updated_at)" if "recency_at" in cols else "updated_at"
        model = "model" if "model" in cols else "NULL"
        subagent = "agent_role IS NOT NULL" if "agent_role" in cols else "0"
        rows = conn.execute(f"SELECT id,cwd,created_at,{recency},{model},{subagent} FROM threads "
                            f"WHERE {recency} BETWEEN ? AND ?", (window_start, now))
        return [_activity("codex", "recent_activity", status=_recency_status(last, now, idle_seconds)[0],
                          status_basis="recency", session_id=sid, project_path=cwd,
                          started_at=start, last_event_at=last, last_model=name, subagent=sub,
                          notes=NOTE_RECENCY_ONLY)
                for sid, cwd, start, last, name, sub in rows]


# ---------------------------------------------------------------------------
# ZCode: model_usage rows grouped by session; directory from the session table.


def zcode_activities(db_path, window_start, idle_seconds, now):
    with zcode_local.readonly_database(db_path) as conn:
        columns = {r[1] for r in conn.execute("PRAGMA table_info(model_usage)")}
        required = {"started_at", "completed_at", "session_id", "turn_id", "model_id", "status",
                    "input_tokens", "output_tokens", "reasoning_tokens",
                    "cache_creation_input_tokens", "cache_read_input_tokens"}
        if not required <= columns:
            raise SourceError("unsupported_zcode_usage_schema")
        rows = conn.execute(
            "SELECT started_at, COALESCE(completed_at, started_at), session_id, turn_id,"
            " model_id, status, input_tokens, output_tokens, reasoning_tokens,"
            " cache_creation_input_tokens, cache_read_input_tokens"
            " FROM model_usage WHERE started_at BETWEEN ? AND ? ORDER BY started_at",
            (int(window_start * 1000), int(now * 1000))).fetchall()
        directories = {}
        if {"id", "directory"} <= {r[1] for r in conn.execute("PRAGMA table_info(session)")}:
            directories = {r[0]: r[1] for r in conn.execute("SELECT id, directory FROM session")
                           if isinstance(r[1], str) and r[1]}
    sessions = {}
    for started_ms, ended_ms, session_id, turn_id, model_id, status, fresh, output, \
            reasoning, cache_write, cache_read in rows:
        state = sessions.setdefault(session_id, {
            "started": None, "last": None, "requests": 0,
            "tokens": dict.fromkeys(TOKEN_KEYS, 0), "costs": {}, "models": {}, "turns": {}})
        state["started"] = started_ms if state["started"] is None else min(state["started"], started_ms)
        state["last"] = ended_ms if state["last"] is None else max(state["last"], ended_ms)
        state["requests"] += 1
        for key, value in zip(TOKEN_KEYS, (fresh, output, reasoning, cache_read, cache_write)):
            state["tokens"][key] += _nonneg(value)
        _cost_record(state["costs"], model_id, started_ms/1000, fresh, output, reasoning, cache_read, cache_write)
        state["models"][model_id] = ended_ms
        if turn_id:
            turn = state["turns"].setdefault(turn_id, {"start": None, "end": None,
                                                       "status": "unknown", "model": model_id,
                                                       "tokens": 0})
            turn["start"] = started_ms if turn["start"] is None else min(turn["start"], started_ms)
            turn["end"] = ended_ms if turn["end"] is None else max(turn["end"], ended_ms)
            turn["tokens"] += sum(_nonneg(v) for v in (fresh, output, reasoning, cache_read, cache_write))
            turn["status"] = _terminal_status(status)
    out = []
    for session_id, state in sorted(sessions.items()):
        last_event = state["last"] / 1000 if state["last"] else None
        status, basis = _recency_status(last_event, now, idle_seconds)
        turn_statuses = {}
        for turn in state["turns"].values():
            turn_statuses[turn["status"]] = turn_statuses.get(turn["status"], 0) + 1
        last_turn = max(state["turns"].values(), key=lambda t: t["end"] or 0) if state["turns"] else None
        recent = [{"turn": turn_id, "started_at": timestamp(turn["start"] / 1000) if turn["start"] else None,
                   "ended_at": timestamp(turn["end"] / 1000) if turn["end"] else None,
                   "status": turn["status"], "model": turn["model"], "tokens": turn["tokens"]}
                  for turn_id, turn in sorted(state["turns"].items(), key=lambda kv: kv[1]["end"] or 0)
                  [-RECENT_TURNS_LIMIT:]]
        out.append(_activity(
            "zcode", "turn", status=status, status_basis=basis, session_id=session_id,
            project_path=directories.get(session_id), started_at=state["started"] / 1000,
            last_event_at=last_event,
            last_model=max(state["models"], key=state["models"].get) if state["models"] else None,
            requests=state["requests"], tokens=_tokens_dict(**state["tokens"]),
            subagent=session_id.startswith("sess_subagent"), notes=NOTE_TURN_NOT_SESSION,
            extra={"_costs": state["costs"], "turn_statuses": turn_statuses,
                   "last_turn_status": last_turn["status"] if last_turn else None,
                   "turns": len(state["turns"]) or None, "recent_turns": recent}))
    return out


# ---------------------------------------------------------------------------
# Codex built-in image generation: one row per thread, explicit call statuses.


def codex_image_activities(history_db, window_start, idle_seconds, now):
    db = resolve_history_db(history_db)
    threads = history_threads(db, now) if db is not None else None
    if threads is None:
        raise SourceError("codex_history_unavailable")
    per_thread = {}
    for thread_id, created_ms, status in threads:
        seconds = created_ms / 1000
        if not window_start <= seconds <= now:
            continue
        state = per_thread.setdefault(thread_id, {
            "started": seconds, "last": seconds, "calls": 0, "failed": 0, "generating": 0,
            "last_status": "unknown"})
        state["started"] = min(state["started"], seconds)
        state["last"] = max(state["last"], seconds)
        state["calls"] += 1
        if status == "failed":
            state["failed"] += 1
        elif status == "generating":
            state["generating"] += 1
        if seconds == state["last"]:
            state["last_status"] = status if isinstance(status, str) else "unknown"
    out = []
    for thread_id, state in sorted(per_thread.items()):
        generating = state["generating"] > 0
        if generating:
            status, basis = "running", "explicit_event"
        elif state["last_status"] == "failed":
            status, basis = "failed", "explicit_event"
        elif state["last_status"] == "completed":
            status, basis = "completed", "explicit_event"
        else:
            status, basis = "unknown", "explicit_event"
        out.append(_activity(
            "codex_images", "image_call", status=status, status_basis=basis,
            session_id=thread_id, started_at=state["started"], last_event_at=state["last"],
            requests=state["calls"], notes=NOTE_CALL_NOT_SESSION,
            extra={"calls": state["calls"], "failed_calls": state["failed"],
                   "generating_calls": state["generating"]}))
    return out


# ---------------------------------------------------------------------------
# Kimi Code / Kimi desktop: wire.jsonl per agent, aggregated per session dir.


KIMI_MARKERS = (b'"usage.record"', b'"turn.ended"', b'"agent.turn.started"')


def _parse_kimi_wire(path):
    """(usage rows, turns) for one agent wire log; never message text."""
    usage, turns = [], {}
    with open(path, "rb") as handle:
        for line in handle:
            if not any(marker in line for marker in KIMI_MARKERS):
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if not isinstance(o, dict):
                continue
            kind, when = o.get("type"), o.get("time")
            if isinstance(when, bool) or not isinstance(when, int) or when < 0:
                continue
            if kind == "usage.record":
                if o.get("usageScope") != "turn" or not isinstance(o.get("usage"), dict):
                    continue
                u = o["usage"]
                model = o.get("model") if isinstance(o.get("model"), str) and o["model"] else "unknown"
                usage.append((when / 1000, model, _nonneg(u.get("inputOther")),
                              _nonneg(u.get("output")), _nonneg(u.get("inputCacheRead")),
                              _nonneg(u.get("inputCacheCreation"))))
            elif kind == "agent.turn.started":
                turn_id = _key_part(o.get("turnId"))
                if turn_id is not None:
                    turns.setdefault(turn_id, {"start": when, "end": None, "reason": None})
            elif kind == "turn.ended":
                turn_id = _key_part(o.get("turnId"))
                if turn_id is not None:
                    turn = turns.setdefault(turn_id, {"start": None, "end": None, "reason": None})
                    turn["end"] = when
                    turn["reason"] = o.get("reason") if isinstance(o.get("reason"), str) else None
    return usage, turns


def _kimi_session_activities(root, app, window_start, idle_seconds, now):
    root = Path(root)
    if not root.is_dir():
        raise SourceError("kimi_sessions_not_found" if app == "kimi" else "kimi_desktop_sessions_not_found")
    paths = []
    for path in root.glob("**/agents/*/wire.jsonl"):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime >= window_start:
            paths.append(path)
    sessions = {}
    for path in paths:
        # <root>/<workspace>/<session>/agents/<agent>/wire.jsonl
        agent_dir = path.parent.name
        session_dir = path.parent.parent.parent
        try:
            parsed = activity_cache.read(path, _parse_kimi_wire, ("activity_kimi", str(root)))
        except OSError:
            continue
        if not parsed:
            continue
        usage, turns = parsed
        state = sessions.setdefault(str(session_dir), {
            "workspace": session_dir.parent.name, "started": None, "last": None,
            "requests": 0, "tokens": dict.fromkeys(TOKEN_KEYS, 0),
            "models": {}, "costs": {}, "reasons": [], "turns": {}, "agents": {agent_dir}})
        state["agents"].add(agent_dir)
        for when, model, fresh, output, cache_read, cache_write in usage:
            if not window_start <= when <= now:
                continue
            state["requests"] += 1
            state["tokens"]["fresh_input"] += fresh
            state["tokens"]["output"] += output
            state["tokens"]["cache_read"] += cache_read
            state["tokens"]["cache_write"] += cache_write
            _cost_record(state["costs"], model, when, fresh, output, 0, cache_read, cache_write)
            state["models"][model] = max(state["models"].get(model, 0), when)
            state["started"] = when if state["started"] is None else min(state["started"], when)
            state["last"] = when if state["last"] is None else max(state["last"], when)
        for turn_id, turn in turns.items():
            existing = state["turns"].get(turn_id)
            if existing is None or (turn["end"] or 0) >= (existing["end"] or 0):
                state["turns"][turn_id] = turn
    out = []
    for session_dir, state in sorted(sessions.items()):
        visible_turns = {}
        for turn_id, turn in state["turns"].items():
            times = [t/1000 for t in (turn["start"], turn["end"]) if t and window_start <= t/1000 <= now]
            if not times:
                continue
            visible_turns[turn_id] = turn
            state["started"] = min([*times, state["started"]] if state["started"] else times)
            state["last"] = max([*times, state["last"]] if state["last"] else times)
            if turn["end"] and window_start <= turn["end"]/1000 <= now:
                state["reasons"].append((turn["end"], turn["reason"]))
        last_event = state["last"]
        if last_event is None:
            continue
        status, basis = _recency_status(last_event, now, idle_seconds)
        turn_statuses = {}
        for _, reason in state["reasons"]:
            mapped = _terminal_status(reason)
            turn_statuses[mapped] = turn_statuses.get(mapped, 0) + 1
        last_reason = max(state["reasons"], key=lambda item: item[0])[1] if state["reasons"] else None
        subagent = "main" not in state["agents"]
        out.append(_activity(
            app, "steps", status=status, status_basis=basis,
            session_id=Path(session_dir).name, project_path=None,
            # The workspace directory name is the only project hint this
            # ledger carries; it is opaque but stable.
            project_alias=state["workspace"] or None,
            started_at=state["started"], last_event_at=last_event,
            last_model=max(state["models"], key=state["models"].get) if state["models"] else None,
            requests=state["requests"] or None, tokens=_tokens_dict(**state["tokens"]) if state["requests"] else None,
            subagent=subagent, notes=NOTE_TURN_NOT_SESSION,
            extra={"_costs": state["costs"], "workspace": state["workspace"], "turn_statuses": turn_statuses,
                   "last_turn_status": _terminal_status(last_reason) if last_reason else None,
                   "turns": len(visible_turns) or None}))
    return out


# ---------------------------------------------------------------------------
# DeepSeek Harness (dsh): one zstd JSONL per session; explicit turn/end events.


DSH_MARKERS = (b'"request/header"', b'"assistant/message"', b'"assistant/chunk"',
               b'"turn/start"', b'"turn/end"', b'"step/end"')


def _parse_dsh_session(path, route, zstd_binary):
    """(header, turns, usage) for one session file; never conversation text."""
    header, usage, turns = {}, [], {}
    with _decompressed(path, route, zstd_binary) as handle:
        first = handle.readline()
        if b'"type":"session"' in first or b'"type": "session"' in first:
            try:
                o = json.loads(first)
                if isinstance(o, dict):
                    header = {"id": o.get("id") if isinstance(o.get("id"), str) else None,
                              "created_at": o.get("createdAt") if isinstance(o.get("createdAt"), int) else None,
                              "cwd": o.get("cwd") if isinstance(o.get("cwd"), str) else None}
            except ValueError:
                header = {}
        for line in handle:
            if not any(marker in line for marker in DSH_MARKERS):
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if not isinstance(o, dict) or not isinstance(o.get("data"), dict):
                continue
            kind, data = o.get("type"), o["data"]
            when = o.get("time")
            if isinstance(when, bool) or not isinstance(when, (int, float)) or when < 0:
                when = None
            if kind == "turn/start":
                turn = _key_part(data.get("turn"))
                if turn is not None:
                    turns.setdefault(turn, {"start": when, "end": None, "reason": None, "steps": 0})
            elif kind == "turn/end":
                turn = _key_part(data.get("turn"))
                if turn is not None:
                    state = turns.setdefault(turn, {"start": None, "end": None, "reason": None, "steps": 0})
                    state["end"] = when
                    reason = data.get("reason")
                    state["reason"] = reason.get("kind") if isinstance(reason, dict) else None
            elif kind == "step/end":
                turn = _key_part(data.get("turn"))
                if turn is not None:
                    state = turns.setdefault(turn, {"start": None, "end": None, "reason": None, "steps": 0})
                    state["steps"] += 1
                    if when:
                        state["end"] = when if state["end"] is None else max(state["end"], when)
            elif kind == "request/header":
                header_config = data.get("header")
                config = header_config.get("config") if isinstance(header_config, dict) else None
                if isinstance(config, dict) and config.get("model") is not None and "model" not in header:
                    header["model"] = config.get("model")
                continue
            elif kind in ("assistant/message", "assistant/chunk"):
                if kind == "assistant/chunk":
                    chunk = data.get("chunk")
                    raw = chunk.get("usage") if isinstance(chunk, dict) else None
                else:
                    raw = data.get("usage")
                if not isinstance(raw, dict):
                    continue
                turn = _key_part(data.get("turn"))
                step = _key_part(data.get("step"))
                message = data.get("message")
                origin = message.get("source") if isinstance(message, dict) else None
                model = origin.get("model") if isinstance(origin, dict) and isinstance(origin.get("model"), str) \
                    else header.get("model")
                usage.append({
                    "key": (turn, step), "time": when,
                    "model": model if isinstance(model, str) and model else "unknown",
                    "fresh": _nonneg(raw.get("inputTokens")),
                    "output": _nonneg(raw.get("outputTokens")),
                    "reasoning": _nonneg(raw.get("reasoningTokens")),
                    "cache_read": _nonneg(raw.get("cacheReadTokens")),
                    "cache_write": _nonneg(raw.get("cacheWriteTokens"))})
    # Last-wins per (turn, step), matching the token ledger's dedup rule.
    dedup = {}
    for record in usage:
        dedup[record["key"]] = record
    return header, turns, list(dedup.values())


def dsh_activities(sessions_dir, zstd_binary, window_start, idle_seconds, now):
    root = Path(sessions_dir)
    paths = sorted(root.glob("**/session*.jsonl.zstd")) if root.is_dir() else []
    if not paths:
        raise SourceError("dsh_sessions_not_found")
    route = _route(zstd_binary)
    sessions = {}
    skipped = 0
    for path in paths:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime < window_start:
            continue
        try:
            parsed = activity_cache.read(path, lambda p: _parse_dsh_session(p, route, zstd_binary),
                                         ("activity_dsh", route))
        except _ZSTD_ERRORS:
            skipped += 1
            continue
        if not parsed:
            skipped += 1
            continue
        header, turns, records = parsed
        session_id = header.get("id") or path.parent.name
        state = sessions.setdefault(str(path.parent), {
            "id": session_id, "cwd": header.get("cwd"), "created": header.get("created_at"),
            "turns": {}, "records": [], "files": 0})
        state["files"] += 1
        for turn_id, turn in turns.items():
            existing = state["turns"].get(turn_id)
            if existing is None or (turn["end"] or 0) >= (existing["end"] or 0):
                state["turns"][turn_id] = turn
        state["records"].extend(records)
    out = []
    for session_dir, state in sorted(sessions.items()):
        records = [r for r in state["records"] if r["time"] and window_start <= r["time"] / 1000 <= now]
        tokens = dict.fromkeys(TOKEN_KEYS, 0)
        models, costs = {}, {}
        started = state["created"] / 1000 if state["created"] else None
        last = None
        for record in records:
            when = record["time"] / 1000
            fresh, output, reasoning = record["fresh"], record["output"], record["reasoning"]
            tokens["fresh_input"] += fresh
            tokens["output"] += max(0, output - reasoning)
            tokens["reasoning"] += reasoning
            tokens["cache_read"] += record["cache_read"]
            tokens["cache_write"] += record["cache_write"]
            _cost_record(costs, record["model"], when, fresh, max(0, output-reasoning), reasoning, record["cache_read"], record["cache_write"])
            models[record["model"]] = when
            started = when if started is None else min(started, when)
            last = when if last is None else max(last, when)
        turn_statuses = {}
        recent = []
        for turn_id, turn in sorted(state["turns"].items(), key=lambda kv: kv[1]["end"] or 0):
            if turn["end"] is None or turn["end"] / 1000 < window_start:
                continue
            mapped = _terminal_status(turn["reason"]) if turn["reason"] else "unknown"
            turn_statuses[mapped] = turn_statuses.get(mapped, 0) + 1
        for turn in state["turns"].values():
            for stamp in (turn["start"], turn["end"]):
                if stamp and window_start <= stamp / 1000 <= now:
                    last = max(last or 0, stamp / 1000)
        if last is None:
            continue
        recent_turns = sorted(state["turns"].items(), key=lambda kv: kv[1]["end"] or 0)[-RECENT_TURNS_LIMIT:]
        for turn_id, turn in recent_turns:
            recent.append({"turn": turn_id, "started_at": timestamp(turn["start"] / 1000) if turn["start"] else None,
                           "ended_at": timestamp(turn["end"] / 1000) if turn["end"] else None,
                           "status": _terminal_status(turn["reason"]) if turn["reason"] else "unknown",
                           "steps": turn["steps"] or None})
        last_turn = None
        if state["turns"]:
            top = max(state["turns"].values(), key=lambda t: t["end"] or 0)
            if top["end"] is not None:
                last_turn = _terminal_status(top["reason"]) if top["reason"] else "unknown"
        status, basis = _recency_status(last, now, idle_seconds)
        out.append(_activity(
            "deepseek_harness", "turn_steps", status=status, status_basis=basis,
            session_id=state["id"], project_path=state["cwd"], started_at=started,
            last_event_at=last, last_model=max(models, key=models.get) if models else None,
            requests=len(records) or None, tokens=_tokens_dict(**tokens) if records else None,
            notes=NOTE_TURN_NOT_SESSION,
            extra={"_costs": costs, "turn_statuses": turn_statuses, "last_turn_status": last_turn,
                   "turns": len(state["turns"]) or None, "recent_turns": recent}))
    return out


# ---------------------------------------------------------------------------
# Claude Code: per-session JSONL transcripts (assistant usage lines only).


def _parse_claude_session(path):
    """(cwd, usage rows) for one transcript; message text never kept."""
    rows, cwd = {}, None
    with open(path, "rb") as handle:
        for line in handle:
            if b'"usage"' not in line or b'"message"' not in line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if not isinstance(o, dict) or o.get("type") != "assistant":
                continue
            message = o.get("message")
            usage = message.get("usage") if isinstance(message, dict) else None
            if not isinstance(usage, dict):
                continue
            when = o.get("timestamp")
            if isinstance(when, str):
                try:
                    seconds = timestamp(when)["epoch_seconds"]
                except SourceError:
                    continue
            else:
                continue
            if cwd is None and isinstance(o.get("cwd"), str):
                cwd = o["cwd"]
            details = usage.get("output_tokens_details")
            thinking = details.get("thinking_tokens") if isinstance(details, dict) else 0
            model = message.get("model")
            key = o.get("requestId") or message.get("id") or o.get("uuid") or len(rows)
            rows[key] = {
                "time": seconds,
                "model": model if isinstance(model, str) and model else "unknown",
                "fresh": _nonneg(usage.get("input_tokens")),
                "write": _nonneg(usage.get("cache_creation_input_tokens")),
                "read": _nonneg(usage.get("cache_read_input_tokens")),
                "output": max(0, _nonneg(usage.get("output_tokens")) - _nonneg(thinking)),
                "reasoning": min(_nonneg(usage.get("output_tokens")), _nonneg(thinking)),
                "sidechain": bool(o.get("isSidechain"))}
    return cwd, list(rows.values())


def claude_activities(projects_dir, window_start, idle_seconds, now, desktop_root=None):
    root = Path(projects_dir)
    paths = _claude_paths(root, desktop_root)
    if not paths and not root.is_dir():
        raise SourceError("claude_projects_not_found")
    out = []
    for path in paths:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime < window_start:
            continue
        try:
            cwd, rows = activity_cache.read(path, _parse_claude_session, ("activity_claude",))
        except OSError:
            continue
        rows = [row for row in rows if window_start <= row["time"] <= now]
        if not rows:
            continue
        tokens = dict.fromkeys(TOKEN_KEYS, 0)
        models, costs = {}, {}
        sidechain = True
        for row in rows:
            tokens["fresh_input"] += row["fresh"]
            tokens["cache_write"] += row["write"]
            tokens["cache_read"] += row["read"]
            tokens["output"] += row["output"]
            tokens["reasoning"] += row["reasoning"]
            models[row["model"]] = row["time"]
            _cost_record(costs, row["model"], row["time"], row["fresh"], row["output"], row["reasoning"], row["read"], row["write"])
            sidechain = sidechain and row["sidechain"]
        times = [row["time"] for row in rows]
        status, basis = _recency_status(max(times), now, idle_seconds)
        out.append(_activity(
            "claude", "recent_activity", status=status, status_basis=basis,
            session_id=path.stem, project_path=cwd, started_at=min(times),
            last_event_at=max(times), last_model=max(models, key=models.get),
            requests=len(rows), tokens=_tokens_dict(**tokens),
            subagent=sidechain, notes=NOTE_RECENCY_ONLY, extra={"_costs": costs}))
    return out


# ---------------------------------------------------------------------------
# Gemini CLI: chats/session-*.jsonl with per-message token lines.


def _parse_gemini_chat(path):
    """(session_id, usage rows); conversation text never kept."""
    rows, session_id = [], None
    with open(path, "rb") as handle:
        for index, line in enumerate(handle):
            if b'"tokens"' not in line and b'"sessionId"' not in line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if not isinstance(o, dict):
                continue
            if session_id is None and isinstance(o.get("sessionId"), str):
                session_id = o["sessionId"]
                continue
            tokens = o.get("tokens")
            when = o.get("timestamp")
            if not isinstance(tokens, dict) or not isinstance(tokens.get("input"), int):
                continue
            if isinstance(when, (int, float)) and not isinstance(when, bool):
                seconds = when / 1000 if when > 253402271999 else when
            elif isinstance(when, str):
                try:
                    seconds = timestamp(when)["epoch_seconds"]
                except SourceError:
                    continue
            else:
                continue
            total_input, cached = _nonneg(tokens.get("input")), _nonneg(tokens.get("cached"))
            model = o.get("model")
            rows.append({
                "time": seconds,
                "model": model if isinstance(model, str) and model else "unknown",
                "fresh": max(0, total_input - cached), "output": _nonneg(tokens.get("output")) + _nonneg(tokens.get("thoughts")),
                "read": cached})
    return session_id, rows


def gemini_activities(gemini_dir, window_start, idle_seconds, now):
    root = Path(gemini_dir)
    if not root.is_dir():
        raise SourceError("gemini_chats_not_found")
    out = []
    for path in root.glob("tmp/*/chats/session-*.jsonl"):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime < window_start:
            continue
        try:
            session_id, rows = activity_cache.read(path, _parse_gemini_chat, ("activity_gemini",))
        except OSError:
            continue
        rows = [row for row in rows if window_start <= row["time"] <= now]
        if not rows:
            continue
        tokens = dict.fromkeys(TOKEN_KEYS, 0)
        models, costs = {}, {}
        for row in rows:
            tokens["fresh_input"] += row["fresh"]
            tokens["output"] += row["output"]
            tokens["cache_read"] += row["read"]
            models[row["model"]] = row["time"]
            _cost_record(costs, row["model"], row["time"], row["fresh"], row["output"], 0, row["read"], 0)
        times = [row["time"] for row in rows]
        status, basis = _recency_status(max(times), now, idle_seconds)
        out.append(_activity(
            "gemini", "recent_activity", status=status, status_basis=basis,
            session_id=session_id or path.stem, project_path=None, started_at=min(times),
            last_event_at=max(times), last_model=max(models, key=models.get),
            requests=len(rows), tokens=_tokens_dict(**tokens), notes=NOTE_RECENCY_ONLY, extra={"_costs": costs}))
    return out


# ---------------------------------------------------------------------------
# OpenCode: message db grouped by session; directory from the session table.


def opencode_activities(db_path, window_start, idle_seconds, now, *, app="opencode",
                        schema_code="unsupported_opencode_schema",
                        missing_code="opencode_db_not_found", read_code="opencode_db_read_failed"):
    with opencode_tokens.readonly_database(db_path, missing_code=missing_code, read_code=read_code) as conn:
        columns = {r[1] for r in conn.execute("PRAGMA table_info(message)")}
        if not {"time_created", "data", "session_id"} <= columns:
            raise SourceError(schema_code)
        directories = {}
        if {"id", "directory"} <= {r[1] for r in conn.execute("PRAGMA table_info(session)")}:
            directories = {r[0]: r[1] for r in conn.execute("SELECT id, directory FROM session")
                           if isinstance(r[1], str) and r[1]}
        sessions = {}
        for time_created, session_id, data in conn.execute(
                "SELECT time_created, session_id, data FROM message WHERE time_created BETWEEN ? AND ?",
                (int(window_start * 1000), int(now * 1000))):
            parsed = opencode_tokens._tokens(data)
            if parsed is None:
                continue
            model, fresh, output, reasoning, cache_read, cache_write = parsed
            state = sessions.setdefault(session_id, {
                "started": None, "last": None, "requests": 0,
                "tokens": dict.fromkeys(TOKEN_KEYS, 0), "costs": {}, "models": {}})
            when = time_created / 1000
            state["requests"] += 1
            state["tokens"]["fresh_input"] += fresh
            state["tokens"]["output"] += output
            state["tokens"]["reasoning"] += reasoning
            state["tokens"]["cache_read"] += cache_read
            state["tokens"]["cache_write"] += cache_write
            _cost_record(state["costs"], model, when, fresh, output, reasoning, cache_read, cache_write)
            state["models"][model] = when
            state["started"] = when if state["started"] is None else min(state["started"], when)
            state["last"] = when if state["last"] is None else max(state["last"], when)
    out = []
    for session_id, state in sorted(sessions.items()):
        status, basis = _recency_status(state["last"], now, idle_seconds)
        out.append(_activity(
            app, "recent_activity", status=status, status_basis=basis,
            session_id=session_id, project_path=directories.get(session_id),
            started_at=state["started"], last_event_at=state["last"],
            last_model=max(state["models"], key=state["models"].get),
            requests=state["requests"], tokens=_tokens_dict(**state["tokens"]),
            notes=NOTE_RECENCY_ONLY, extra={"_costs": state["costs"]}))
    return out


# ---------------------------------------------------------------------------
# Old Kimi CLI: pre-migration wire.jsonl ledgers (stopped 2026-06-17). No cwd
# or model fields exist in this format; sessions are identified by directory.


def kimi_legacy_activities(root, window_start, idle_seconds, now):
    from . import kimi_legacy_tokens
    root = Path(root)
    if not root.is_dir():
        raise SourceError("kimi_legacy_sessions_not_found")
    out = []
    for path in sorted(root.glob("**/wire.jsonl")):
        try:
            if path.stat().st_mtime < window_start:
                continue
            records, _ = kimi_legacy_tokens._parse_file(path)
        except OSError:
            continue
        rows = [r for r in records if window_start <= r[0] <= now]
        if not rows:
            continue
        tokens = dict.fromkeys(TOKEN_KEYS, 0)
        costs = {}
        for t, fresh, output, read, write, _key in rows:
            tokens["fresh_input"] += fresh
            tokens["output"] += output
            tokens["cache_read"] += read
            tokens["cache_write"] += write
            _cost_record(costs, "unknown", t, fresh, output, 0, read, write)
        times = [r[0] for r in rows]
        status, basis = _recency_status(max(times), now, idle_seconds)
        out.append(_activity(
            "kimi_legacy", "recent_activity", status=status, status_basis=basis,
            session_id=path.parent.name, project_path=None,
            started_at=min(times), last_event_at=max(times), last_model="unknown",
            requests=len(rows), tokens=_tokens_dict(**tokens),
            notes=NOTE_RECENCY_ONLY, extra={"_costs": costs}))
    return out


# ---------------------------------------------------------------------------


def collect_activity(config, now=None, table=None):
    """Build the activity payload; one failing source never fails the endpoint."""
    now = float(now if now is not None else time.time())
    zone = DISPLAY_ZONE
    window_hours = config.get("activity_window_hours", 24)
    idle_minutes = config.get("activity_idle_minutes", 15)
    try:
        window_hours = max(1, int(window_hours))
    except (TypeError, ValueError):
        window_hours = 24
    try:
        idle_minutes = max(1, int(idle_minutes))
    except (TypeError, ValueError):
        idle_minutes = 15
    window_start = now - window_hours * 3600
    idle_seconds = idle_minutes * 60

    entries = []

    disabled = set(config.get("disabled_sources", [])) | set((config.get("preferences") or {}).get("disabled_sources", []))

    def run(name, fn):
        if app_id(name) in disabled and name != "claude":
            entries.append((name, [], {"status": "not_connected", "reason": "disabled_by_user", "activities": 0}))
            return
        try:
            rows = fn()
            meta = {"status": "available", "activities": len(rows)}
        except SourceError as error:
            rows, meta = [], {"status": "not_connected", "reason": error.code, "activities": 0}
        except Exception:
            rows, meta = [], {"status": "error", "reason": "unexpected_source_error", "activities": 0}
        entries.append((name, rows, meta))

    run("zcode", lambda: zcode_activities(config["zcode_usage_db"], window_start, idle_seconds, now))
    run("codex", lambda: codex_activities(config["codex_state_db"], window_start, idle_seconds, now))
    run("codex_images", lambda: codex_image_activities(config["codex_history_db"], window_start, idle_seconds, now))
    run("kimi", lambda: _kimi_session_activities(Path(config["home"]) / ".kimi-code/sessions",
                                                 "kimi", window_start, idle_seconds, now))
    run("kimi_desktop", lambda: _kimi_session_activities(config["kimi_desktop_sessions_dir"],
                                                         "kimi_desktop", window_start, idle_seconds, now))
    run("deepseek_harness", lambda: dsh_activities(config["dsh_sessions_dir"], config.get("zstd_binary"),
                                                   window_start, idle_seconds, now))
    run("claude", lambda: claude_activities(config["claude_projects_dir"], window_start, idle_seconds, now,
                                             config.get("claude_desktop_sessions_dir")))
    run("gemini", lambda: gemini_activities(config["gemini_dir"], window_start, idle_seconds, now))
    run("opencode", lambda: opencode_activities(config["opencode_db"], window_start, idle_seconds, now))
    run("mimo_code", lambda: opencode_activities(config["mimocode_db"], window_start, idle_seconds, now,
                                                 app="mimo_code", schema_code="unsupported_mimocode_schema",
                                                 missing_code="mimocode_db_not_found", read_code="mimocode_db_read_failed"))
    run("deveco", lambda: opencode_activities(config["deveco_db"], window_start, idle_seconds, now,
                                              app="deveco", schema_code="unsupported_deveco_schema",
                                              missing_code="deveco_db_not_found", read_code="deveco_db_read_failed"))
    run("kimi_legacy", lambda: kimi_legacy_activities(config["kimi_legacy_sessions_dir"],
                                                      window_start, idle_seconds, now))

    activities, sources_meta = [], {}
    for name, rows, meta in entries:
        activities.extend(rows)
        sources_meta[name] = meta
    for row in activities:
        row["application_id"] = app_id(row["app"])
        row["estimated_cost_usd"] = _cost_usd(table, row.pop("_costs", {}))
    activities.sort(key=_sort_key)
    return {
        "schema_version": 1,
        "generated_at": timestamp(now),
        "window_hours": window_hours,
        "idle_after_minutes": idle_minutes,
        "window_start": timestamp(window_start),
        "timezone": str(zone),
        "activities": activities,
        "sources_meta": sources_meta,
    }
