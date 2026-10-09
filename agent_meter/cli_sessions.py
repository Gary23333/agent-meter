"""Direct local session-history readers for Codex CLI, Claude Code, Gemini CLI
and MiniMax Code, for machines (or date ranges) CC Switch does not cover.

Dedup and field semantics were aligned against this machine's CC Switch 4.0.5
imports (verified 2026-10-09, exact match on shared days):

- Codex: one jsonl rollout per session under ~/.codex/sessions and
  ~/.codex/archived_sessions; event_msg/token_count events carry cumulative
  info.total_token_usage, so each event's contribution is the diff of the
  series (a repeated event adds zero; a decreasing total is a reset that
  restarts the series). input includes cached_input_tokens (fresh = input −
  cached); output excludes reasoning (matches codex's own total_tokens and
  the imported rows); model attribution is per-file session_meta.model —
  mixed sessions (e.g. auto-review turns) count toward the session's primary
  model, which only affects the model split, not the totals.
- Claude Code: ~/.claude/projects/**/*.jsonl; streaming appends several
  records per requestId and the latest holds the final usage. Keep the last
  record per requestId globally across files; sidechain (subagent) records
  are real usage and are included. usage.input_tokens is already fresh.
- Gemini CLI: ~/.gemini/tmp/*/chats/session-*.jsonl; repeated ids keep the
  last record; fresh = input − cached; output = output + thoughts (the way
  CC Switch stores it).
- MiniMax Code: ~/.minimax/v2/sqlite/runtime-state.sqlite table
  local_runtime_token_usage; one row per request, input already fresh.

Days CC Switch already recorded for the app are excluded here (CC Switch
stays primary), so the two never add up. Only token fields are read, never
message text.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .ccswitch import app_imported_days, period_bounds
from .model import SourceError, metric, source, timestamp

_cache = {}   # path -> ((mtime_ns, size), parsed)

TOKEN_KEYS = ("requests", "fresh_input", "output", "reasoning", "cache_read", "cache_write")


def _file_records(path, parser):
    """Incremental per-file parse cache (mtime+size); parser(path) -> parsed."""
    path = Path(path)
    try:
        st = path.stat()
    except OSError:
        return []
    stamp = (st.st_mtime_ns, st.st_size)
    cached = _cache.get(str(path))
    if cached is None or cached[0] != stamp:
        try:
            cached = (stamp, parser(path))
        except OSError:
            return []
        _cache[str(path)] = cached
    return cached[1]


def _prune(seen):
    for gone in set(_cache) - seen:
        del _cache[gone]


def _epoch(ts):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return None


def _model(value):
    return value if isinstance(value, str) and 0 < len(value) < 120 else "unknown"


def _nonneg(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


# ---------------------------------------------------------------- aggregation
# Record shape everywhere: (epoch, model, fresh_input, output, reasoning,
# cache_read, cache_write). Keyed variants carry the dedup key up front.

def _summarize(records, start, end, excluded, zone, app):
    totals = dict.fromkeys(TOKEN_KEYS, 0)
    models = {}
    excluded_here = set()
    for t, model, fresh, output, reasoning, cache_read, cache_write in records:
        day = datetime.fromtimestamp(t, zone).date().isoformat()
        if day in excluded:
            excluded_here.add(day)
            continue
        if (start is not None and t < start) or t > end:
            continue
        totals["requests"] += 1
        target = models.setdefault(model, dict.fromkeys(TOKEN_KEYS, 0))
        target["requests"] += 1
        for name, value in (("fresh_input", fresh), ("output", output), ("reasoning", reasoning),
                            ("cache_read", cache_read), ("cache_write", cache_write)):
            totals[name] += value
            target[name] += value
    totals["total_tokens"] = sum(totals[k] for k in TOKEN_KEYS[1:])
    denominator = totals["fresh_input"] + totals["cache_read"] + totals["cache_write"]
    totals["cache_hit_rate"] = totals["cache_read"] / denominator if denominator else None
    return {"start": timestamp(start) if start is not None else None, "end": timestamp(end),
            "totals": totals,
            "groups": [{"app": app, "model": m, **v, "total_tokens": sum(v[k] for k in TOKEN_KEYS[1:])}
                       for m, v in sorted(models.items(), key=lambda x: -x[1]["fresh_input"])],
            "excluded_ccswitch_days": sorted(excluded_here)}


def _metric_value(records, now, zone, excluded, app, coverage, dedup_rule, overlap_state):
    periods = {p: _summarize(records, *period_bounds(now, p, zone), excluded, zone, app)
               for p in ("today", "7d", "30d", "all")}
    for p in periods.values():
        p["timezone"] = str(zone)
    daily = {}
    for t, model, fresh, output, reasoning, cache_read, cache_write in records:
        day = datetime.fromtimestamp(t, zone).date().isoformat()
        if day in excluded:
            continue
        daily[day] = daily.get(day, 0) + fresh + output + reasoning + cache_read + cache_write
    return {"periods": periods,
            "daily_buckets": [{"date": d, "tokens": n} for d, n in sorted(daily.items())],
            "coverage": coverage, "dedup_rule": dedup_rule,
            "ccswitch_overlap": {"state": overlap_state, "excluded_days": sorted(excluded)}}


def _last_per_key(keyed):
    """[(key, sort, record)] -> records, keeping the maximum sort per key."""
    best = {}
    for key, sort, record in keyed:
        if key not in best or sort >= best[key][0]:
            best[key] = (sort, record)
    return [record for _, record in best.values()]


# ------------------------------------------------------------------- parsers

def _parse_claude_file(path):
    """[(key, epoch, model, fresh, output, read, write)] — one entry per record."""
    out = []
    with open(path, "rb") as handle:
        for line in handle:
            if b'"usage"' not in line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            message = o.get("message") if isinstance(o, dict) else None
            usage = message.get("usage") if isinstance(message, dict) else None
            if not isinstance(usage, dict) or not isinstance(usage.get("input_tokens"), int):
                continue
            t = _epoch(o.get("timestamp"))
            if t is None:
                continue
            key = o.get("requestId")
            key = key if isinstance(key, str) and key else "uuid:" + str(o.get("uuid") or id(line))
            out.append((key, t, _model(message.get("model")) if isinstance(message, dict) else "unknown",
                        _nonneg(usage.get("input_tokens")), _nonneg(usage.get("output_tokens")),
                        _nonneg(usage.get("cache_read_input_tokens")),
                        _nonneg(usage.get("cache_creation_input_tokens"))))
    return out


def load_claude(root):
    root = Path(root)
    if not root.is_dir():
        raise SourceError("claude_projects_not_found")
    keyed = []
    seen = set()
    order = 0
    for path in sorted(root.glob("**/*.jsonl")):
        seen.add(str(path))
        for key, t, model, fresh, output, cache_read, cache_write in _file_records(path, _parse_claude_file):
            keyed.append((key, (t, order), (t, model, fresh, output, 0, cache_read, cache_write)))
            order += 1
    _prune(seen)
    return _last_per_key(keyed)


def _parse_gemini_file(path):
    """[(key, epoch, model, fresh, output_with_thoughts, cache_read)]."""
    out = []
    with open(path, "rb") as handle:
        for index, line in enumerate(handle):
            if b'"tokens"' not in line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            tokens = o.get("tokens") if isinstance(o, dict) else None
            t = _epoch(o.get("timestamp"))
            if not isinstance(tokens, dict) or not isinstance(tokens.get("input"), int) or t is None:
                continue
            key = o.get("id")
            key = key if isinstance(key, str) and key else "line:%d" % index
            total_input, cached = _nonneg(tokens.get("input")), _nonneg(tokens.get("cached"))
            out.append((key, t, _model(o.get("model")), max(0, total_input - cached),
                        _nonneg(tokens.get("output")) + _nonneg(tokens.get("thoughts")), cached))
    return out


def load_gemini(root):
    root = Path(root)
    if not root.is_dir():
        raise SourceError("gemini_chats_not_found")
    keyed = []
    seen = set()
    order = 0
    for path in sorted(root.glob("tmp/*/chats/session-*.jsonl")):
        seen.add(str(path))
        for key, t, model, fresh, output, cached in _file_records(path, _parse_gemini_file):
            keyed.append((key, (t, order), (t, model, fresh, output, 0, cached, 0)))
            order += 1
    _prune(seen)
    return _last_per_key(keyed)


def _parse_codex_file(path):
    """Per-request deltas from one session's cumulative total series."""
    records = []
    model = "unknown"
    prev = None
    with open(path, "rb") as handle:
        first = handle.readline()
        try:
            meta = json.loads(first)
            payload = meta.get("payload") if isinstance(meta, dict) else None
            if isinstance(payload, dict):
                model = _model(payload.get("model"))
        except ValueError:
            pass
        for line in handle:
            if b"token_count" not in line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            payload = o.get("payload") if isinstance(o, dict) else None
            info = payload.get("info") if isinstance(payload, dict) and payload.get("type") == "token_count" else None
            total = info.get("total_token_usage") if isinstance(info, dict) else None
            t = _epoch(o.get("timestamp"))
            if not isinstance(total, dict) or t is None:
                continue
            state = (_nonneg(total.get("input_tokens")), _nonneg(total.get("output_tokens")),
                     _nonneg(total.get("reasoning_output_tokens")), _nonneg(total.get("cached_input_tokens")),
                     _nonneg(total.get("cache_write_input_tokens")))
            if state == prev:
                continue  # streamed duplicate of the previous event
            delta = state if prev is None else tuple(v - p if v >= p else v for v, p in zip(state, prev))
            prev = state
            total_input, output, reasoning, cached, write = delta
            records.append((t, model, max(0, total_input - cached), output, reasoning, cached, write))
    return records


def load_codex(*roots):
    records = []
    seen = set()
    any_dir = False
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        any_dir = True
        for path in sorted(root.glob("**/*.jsonl")):
            seen.add(str(path))
            records.extend(_file_records(path, _parse_codex_file))
    if not any_dir:
        raise SourceError("codex_sessions_not_found")
    _prune(seen)
    return records


@contextmanager
def _readonly_sqlite(path, missing_code, read_code):
    path = Path(path).expanduser()
    if not path.is_file():
        raise SourceError(missing_code)
    conn = None
    try:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=3)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        yield conn
    except sqlite3.Error:
        raise SourceError(read_code) from None
    finally:
        if conn is not None:
            conn.rollback()
            conn.close()


MCODE_COLUMNS = {"ts", "model", "input_tokens", "output_tokens", "reasoning_tokens",
                 "cache_read_tokens", "cache_write_tokens"}


def load_mcode(path):
    with _readonly_sqlite(path, "mcode_db_not_found", "mcode_db_read_failed") as conn:
        columns = {r[1] for r in conn.execute("PRAGMA table_info(local_runtime_token_usage)")}
        if not MCODE_COLUMNS <= columns:
            raise SourceError("unsupported_mcode_schema")
        records = [(row["ts"] / 1000, _model(row["model"]), row["input_tokens"], row["output_tokens"],
                    row["reasoning_tokens"], row["cache_read_tokens"], row["cache_write_tokens"])
                   for row in conn.execute("SELECT ts, model, input_tokens, output_tokens, reasoning_tokens,"
                                           " cache_read_tokens, cache_write_tokens FROM local_runtime_token_usage")]
    if any(t < 0 for t, *_ in records) or any(v < 0 for r in records for v in r[2:]):
        raise SourceError("invalid_mcode_token_counts")
    return records


# ---------------------------------------------------------------- collectors

def claude_tokens_metric(root, ccswitch_db, now, zone=ZoneInfo("Asia/Shanghai")):
    excluded, state = app_imported_days(ccswitch_db, zone, "claude")
    return metric(_metric_value(load_claude(root), now, zone, excluded, "claude",
                                "claude_code_local_projects", "last_record_per_request_id", state))


def codex_tokens_metric(sessions_dir, archives_dir, ccswitch_db, now, zone=ZoneInfo("Asia/Shanghai")):
    excluded, state = app_imported_days(ccswitch_db, zone, "codex")
    return metric(_metric_value(load_codex(sessions_dir, archives_dir), now, zone, excluded, "codex",
                                "codex_cli_local_rollouts", "cumulative_total_diff_per_session", state))


def mcode_tokens_metric(db, ccswitch_db, now, zone=ZoneInfo("Asia/Shanghai")):
    excluded, state = app_imported_days(ccswitch_db, zone, "mcode")
    return metric(_metric_value(load_mcode(db), now, zone, excluded, "mcode",
                                "minimax_code_local_runtime_db", "one_row_per_request", state))


def collect_gemini_sessions(root, ccswitch_db, now, zone=ZoneInfo("Asia/Shanghai")):
    excluded, state = app_imported_days(ccswitch_db, zone, "gemini")
    records = load_gemini(root)
    out = source("gemini", "local_session_history", now)
    out["metrics"]["tokens"] = metric(_metric_value(records, now, zone, excluded, "gemini",
                                                    "gemini_cli_local_chats", "last_record_per_message_id", state))
    return out
