"""Direct local session-history readers for Codex CLI, Claude Code, Gemini CLI
and MiniMax Code, each owning its own usage ledger.

Dedup and field semantics were verified against this machine's historical
imports (2026-10-09, exact match on shared days). Codex rollouts may be
zstd-compressed (`.jsonl.zst`); both forms are read with the same cumulative
token_count diff rule.

- Codex: one jsonl rollout per session under ~/.codex/sessions and
  ~/.codex/archived_sessions; event_msg/token_count events carry cumulative
  info.total_token_usage, so each event's contribution is the diff of the
  series (a repeated event adds zero; a decreasing total is a reset that
  restarts the series). input includes cached_input_tokens (fresh = input −
  cached); reported total_tokens disambiguates whether reasoning is included
  in output. Each turn_context updates the model for subsequent usage.
- Claude Code: ~/.claude/projects/**/*.jsonl; streaming appends several
  records per requestId and the latest holds the final usage. Keep the last
  record per requestId globally across files; sidechain (subagent) records
  are real usage and are included. usage.input_tokens is already fresh.
- Gemini CLI: ~/.gemini/tmp/*/chats/session-*.jsonl; repeated ids keep the
  last record; fresh = input − cached; output = output + thoughts.
- MiniMax Code: ~/.minimax/v2/sqlite/runtime-state.sqlite table
  local_runtime_token_usage; one row per request, input already fresh.

Only token fields are read, never message text.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import peak
from . import daily as daily_mod
from .model import SourceError, metric, period_bounds, source, timestamp
from .zstd_io import ZSTD_ERRORS as _ZSTD_ERRORS, decompressed, is_compressed, route as _zstd_route

from .record_cache import records_cache as _cache, wal_stamp

TOKEN_KEYS = ("requests", "fresh_input", "output", "reasoning", "cache_read", "cache_write")


def _file_records(path, parser, namespace=None):
    try:
        return _cache.read(path, parser, namespace or parser.__name__)
    except OSError:
        return []


def _prune(seen, namespace):
    _cache.prune(seen, namespace)


def _epoch(ts):
    if isinstance(ts, (int, float)) and not isinstance(ts, bool):
        seconds = ts / 1000 if ts > 253402271999 else ts
        return seconds if 0 <= seconds <= 253402271999 else None
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
# cache_read, cache_write[, unclassified]). The optional last column is
# used only when the recorded total exceeds the available breakdown.

def _close(bucket_values):
    """Attach total_tokens to a peak/off-peak accumulator."""
    bucket_values["total_tokens"] = peak.total(bucket_values)
    return bucket_values


def _summarize(records, start, end, zone, app):
    totals = dict.fromkeys(TOKEN_KEYS, 0)
    split = {"peak": peak.bucket(), "offpeak": peak.bucket()}
    models = {}
    model_splits = {}
    for t, model, fresh, output, reasoning, cache_read, cache_write, *unknown in records:
        if (start is not None and t < start) or t > end:
            continue
        totals["requests"] += 1
        target = models.setdefault(model, dict.fromkeys(TOKEN_KEYS, 0))
        target["requests"] += 1
        values = {"fresh_input": fresh, "output": output, "reasoning": reasoning,
                  "cache_read": cache_read, "cache_write": cache_write}
        if unknown:
            values["unclassified"] = unknown[0]
        for name, value in values.items():
            totals[name] = totals.get(name, 0) + value
            target[name] = target.get(name, 0) + value
        side = "offpeak" if peak.is_offpeak(t) else "peak"
        peak.add(split[side], values)
        peak.add(model_splits.setdefault(model, {"peak": peak.bucket(), "offpeak": peak.bucket()})[side], values)
    totals["total_tokens"] = peak.total(totals)
    totals["peak"] = _close(split["peak"])
    totals["offpeak"] = _close(split["offpeak"])
    denominator = totals["fresh_input"] + totals["cache_read"] + totals["cache_write"]
    totals["cache_hit_rate"] = totals["cache_read"] / denominator if denominator else None
    return {"start": timestamp(start) if start is not None else None, "end": timestamp(end),
            "totals": totals,
            "groups": [{"app": app, "model": m, **v, "total_tokens": peak.total(v),
                        "peak": _close(model_splits[m]["peak"]),
                        "offpeak": _close(model_splits[m]["offpeak"])}
                       for m, v in sorted(models.items(), key=lambda x: -x[1]["fresh_input"])]}


def _metric_value(records, now, zone, app, coverage, dedup_rule):
    periods = {p: _summarize(records, *period_bounds(now, p, zone), zone, app)
               for p in ("today", "7d", "30d", "all")}
    for p in periods.values():
        p["timezone"] = str(zone)
    daily = {}
    dm = {}
    for row in records:
        if row[0] <= now:
            day = datetime.fromtimestamp(row[0], zone).date().isoformat()
            daily[day] = daily.get(day, 0) + sum(row[2:])
            t, model, fresh, output, reasoning, cache_read, cache_write, *unknown = row
            daily_mod.add(dm, day, model,
                          {"fresh_input": fresh, "output": output, "reasoning": reasoning,
                           "cache_read": cache_read, "cache_write": cache_write,
                           "unclassified": unknown[0] if unknown else 0})
    return {"peak_split": "request_timestamp",
            "periods": periods,
            "daily_buckets": [{"date": d, "tokens": n} for d, n in sorted(daily.items())],
            "daily_models": daily_mod.rows(dm, app),
            "coverage": coverage, "dedup_rule": dedup_rule}


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
        for index, line in enumerate(handle):
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
            key = key or message.get("id") or o.get("uuid")
            if not isinstance(key, str) or not key:
                key = (str(path), index)
            out.append((key, t, _model(message.get("model")) if isinstance(message, dict) else "unknown",
                        _nonneg(usage.get("input_tokens")), _nonneg(usage.get("output_tokens")),
                        _nonneg(usage.get("cache_read_input_tokens")),
                        _nonneg(usage.get("cache_creation_input_tokens"))))
    return out


def _claude_paths(root, desktop_root):
    """CLI transcripts plus Claude Desktop's local-agent session transcripts."""
    paths = list(sorted(root.glob("**/*.jsonl"))) if root.is_dir() else []
    if desktop_root is not None and Path(desktop_root).is_dir():
        paths += [p for p in sorted(Path(desktop_root).rglob("*.jsonl"))
                  if "/.claude/projects/" in str(p)]
    return paths


def load_claude(root, desktop_root=None):
    root = Path(root)
    paths = _claude_paths(root, desktop_root)
    if not paths and not root.is_dir():
        raise SourceError("claude_projects_not_found")
    seen = set()
    def entries():
        order = 0
        for path in paths:
            seen.add(str(path))
            for key, t, model, fresh, output, cache_read, cache_write in _file_records(path, _parse_claude_file):
                yield (key, (t, order), (t, model, fresh, output, 0, cache_read, cache_write))
                order += 1
    records = _last_per_key(entries())
    _prune(seen, "_parse_claude_file")
    return records


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
            t = _epoch(o.get("timestamp")) if isinstance(o, dict) else None
            if not isinstance(tokens, dict) or not isinstance(tokens.get("input"), int) or t is None:
                continue
            key = o.get("id")
            key = key if isinstance(key, str) and key else (str(path), index)
            total_input, cached = _nonneg(tokens.get("input")), _nonneg(tokens.get("cached"))
            out.append((key, t, _model(o.get("model")), max(0, total_input - cached),
                        _nonneg(tokens.get("output")) + _nonneg(tokens.get("thoughts")), cached))
    return out


def load_gemini(root):
    root = Path(root)
    if not root.is_dir():
        raise SourceError("gemini_chats_not_found")
    seen = set()
    def entries():
        order = 0
        for path in sorted(root.glob("tmp/*/chats/session-*.jsonl")):
            seen.add(str(path))
            for key, t, model, fresh, output, cached in _file_records(path, _parse_gemini_file):
                yield (key, (t, order), (t, model, fresh, output, 0, cached, 0))
                order += 1
    records = _last_per_key(entries())
    _prune(seen, "_parse_gemini_file")
    return records


def _codex_counts(total):
    raw_input = _nonneg(total.get("input_tokens"))
    raw_output = _nonneg(total.get("output_tokens"))
    reasoning = _nonneg(total.get("reasoning_output_tokens"))
    cached = min(raw_input, _nonneg(total.get("cached_input_tokens")))
    write = _nonneg(total.get("cache_write_input_tokens"))
    # Older ledgers lack an authoritative total. Preserve their
    # established exclusive-output convention in that case.
    if total.get("total_tokens") == raw_input + raw_output:
        reasoning = min(raw_output, reasoning)
        raw_output -= reasoning
    fields = (raw_input - cached, raw_output, reasoning, cached, write)
    # Some first observations carry only last_token_usage.total_tokens,
    # with every component absent/zero. Keep that usage unpriced.
    unclassified = max(0, _nonneg(total.get("total_tokens")) - sum(fields))
    return (*fields, unclassified)


def _parse_codex_file(path, route_name=None, zstd_binary=None):
    """Per-request deltas from one session's cumulative total series."""
    records = []
    model = "unknown"
    prev = None
    try:
        with _codex_log(path, route_name, zstd_binary) as handle:
            for line in handle:
                if not any(marker in line for marker in (b'"token_count"', b'"turn_context"', b'"session_meta"')):
                    continue
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                payload = o.get("payload") if isinstance(o, dict) else None
                if not isinstance(payload, dict):
                    continue
                if o.get("type") in {"session_meta", "turn_context"}:
                    if "model" in payload:
                        model = _model(payload["model"])
                    continue
                info = payload.get("info") if payload.get("type") == "token_count" else None
                total = info.get("total_token_usage") if isinstance(info, dict) else None
                t = _epoch(o.get("timestamp"))
                if not isinstance(total, dict) or t is None:
                    continue
                state = _codex_counts(total)
                if state == prev:
                    continue
                # A reset restarts the entire cumulative series. A component
                # correction within a growing series must not replay its history.
                delta = state if prev is None or sum(state) < sum(prev) else tuple(
                    max(0, v - p) for v, p in zip(state, prev))
                # The first observed cumulative snapshot can include a parent
                # thread or a pre-rollout baseline. Only the explicit last
                # request is attributable to this file at that timestamp.
                last = info.get("last_token_usage")
                if prev is None and isinstance(last, dict) and ("total_tokens" in last or {"input_tokens", "output_tokens"} <= last.keys()):
                    delta = _codex_counts(last)
                prev = state
                if any(delta):
                    records.append((t, model, *(delta if delta[-1] else delta[:-1])))
    except _ZSTD_ERRORS:
        raise OSError("unreadable zstd session file") from None
    return records


@contextmanager
def _codex_log(path, route_name, zstd_binary):
    """Plain or zstd-compressed rollout as a binary line iterator."""
    if is_compressed(path):
        with decompressed(path, route_name, zstd_binary) as handle:
            yield handle
    else:
        with open(path, "rb") as handle:
            yield handle


def _codex_logs(root):
    return (path for path in root.rglob("*.jsonl*")
            if path.name.endswith((".jsonl", ".jsonl.zst", ".jsonl.zstd")))


def _rollout_priority(path):
    try:
        return (not is_compressed(path), path.stat().st_mtime_ns, str(path))
    except OSError:
        return (False, 0, str(path))


def load_codex(*roots, zstd_binary=None, diagnostics=None):
    records = []
    present = [Path(root) for root in roots if root and Path(root).is_dir()]
    if not present:
        raise SourceError("codex_sessions_not_found")
    # The same rollout may be copied between active and archive roots.
    # Prefer plain over compressed and, within one format, the newest copy.
    paths = {}
    for root in present:
        for path in _codex_logs(root):
            base = path.stem if is_compressed(path) else path.name
            paths.setdefault(base, []).append(path)
    seen = set()
    skipped = 0
    reason = None
    for copies in paths.values():
        for path in sorted(copies, key=_rollout_priority, reverse=True):
            try:
                route = _zstd_route(zstd_binary) if is_compressed(path) else None
                # The byte representation fits many more cold rollouts in the
                # shared bounded cache than lists of Python numbers/tuples.
                def pack_rollout(p):
                    return json.dumps(_parse_codex_file(p, route, zstd_binary), separators=(",", ":")).encode()
                packed = _cache.read(path, pack_rollout, "codex_rollout")
                rows = (tuple(row) for row in json.loads(packed))
            except SourceError as exc:
                reason = exc.code
                continue
            except (OSError, EOFError):
                reason = "codex_rollout_unreadable"
                continue
            seen.add(str(path))
            records.extend(rows)
            break
        else:
            skipped += 1
    _prune(seen, "codex_rollout")
    if diagnostics is not None:
        diagnostics.update(rollouts_read=len(seen), rollouts_skipped=skipped,
                           duplicate_copies=sum(len(copies)-1 for copies in paths.values()))
        if skipped:
            diagnostics["reason"] = reason
    if skipped and not seen:
        raise SourceError(reason)
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


def _mcode_turn_models(conn):
    """Model per (session, turn) for the MiniMax Code desktop runtime.

    Its usage table leaves `model` NULL; each assistant message row records the
    model that answered in `context_usage_telemetry.model`. Only that per-turn
    evidence is used — the session-level effective model is skipped because it
    reflects the current selection, not what a past row actually ran.
    """
    models = {}
    try:
        # JSON1 在 SQLite 里解析，避免把整条消息（含工具输出）搬进 Python。
        rows = conn.execute("SELECT session_id, turn_id,"
                            " json_extract(data_json,'$.context_usage_telemetry.model') AS model"
                            " FROM local_runtime_message_rows WHERE turn_id IS NOT NULL")
        for row in rows:
            model = row["model"]
            if isinstance(model, str) and 0 < len(model) < 120:
                models[(row["session_id"], row["turn_id"])] = model
        return models
    except sqlite3.OperationalError:
        pass   # 该 SQLite 未编译 JSON1，退回 Python 解析
    try:
        rows = conn.execute("SELECT session_id, turn_id, data_json FROM local_runtime_message_rows"
                            " WHERE turn_id IS NOT NULL AND data_json LIKE '%context_usage_telemetry%'")
    except sqlite3.OperationalError:
        return {}
    for row in rows:
        raw = row["data_json"]
        if not isinstance(raw, str) or "context_usage_telemetry" not in raw:
            continue
        try:
            telemetry = json.loads(raw).get("context_usage_telemetry")
        except (AttributeError, ValueError):
            continue
        model = telemetry.get("model") if isinstance(telemetry, dict) else None
        if isinstance(model, str) and 0 < len(model) < 120:
            models[(row["session_id"], row["turn_id"])] = model
    return models


_mcode_cache = {}   # path -> ((mtime_ns, size), (turn_models, rows))


def _mcode_snapshot(path):
    """Parse the runtime db once per file version.

    The token metric needs the same 3k message rows; caching by mtime+size
    avoids decoding the JSON payloads twice in one collection cycle.
    """
    p = Path(path).expanduser()
    try:
        st = p.stat()
    except OSError:
        raise SourceError("mcode_db_not_found") from None
    stamp = (st.st_ino, st.st_mtime_ns, st.st_size, wal_stamp(p))
    cached = _mcode_cache.get(str(p))
    if cached is not None and cached[0] == stamp:
        return cached[1]
    with _readonly_sqlite(p, "mcode_db_not_found", "mcode_db_read_failed") as conn:
        columns = {r[1] for r in conn.execute("PRAGMA table_info(local_runtime_token_usage)")}
        if not MCODE_COLUMNS <= columns:
            raise SourceError("unsupported_mcode_schema")
        turn_models = _mcode_turn_models(conn)
        columns_sql = "id, session_id, turn_id, model, ts, input_tokens, output_tokens," \
                      " reasoning_tokens, cache_read_tokens, cache_write_tokens" if "id" in columns else \
                      "NULL, session_id, turn_id, model, ts, input_tokens, output_tokens," \
                      " reasoning_tokens, cache_read_tokens, cache_write_tokens"
        rows = [tuple(row) for row in conn.execute(
            "SELECT " + columns_sql + " FROM local_runtime_token_usage")]
    parsed = (turn_models, rows)
    _mcode_cache[str(p)] = (stamp, parsed)
    if len(_mcode_cache) > 4:
        _mcode_cache.pop(next(iter(_mcode_cache)))
    return parsed


def load_mcode(path):
    turn_models, rows = _mcode_snapshot(path)
    records = []
    for _, session_id, turn_id, model, ts, fresh, output, reasoning, cache_read, cache_write in rows:
        name = _model(model)
        if name == "unknown":
            name = turn_models.get((session_id, turn_id), "unknown")
        records.append((ts / 1000, name, fresh, output, reasoning, cache_read, cache_write))
    if any(t < 0 for t, *_ in records) or any(v < 0 for r in records for v in r[2:]):
        raise SourceError("invalid_mcode_token_counts")
    return records


# ---------------------------------------------------------------- collectors

def claude_tokens_metric(root, now, zone=ZoneInfo("Asia/Shanghai"), desktop_root=None):
    return metric(_metric_value(load_claude(root, desktop_root), now, zone, "claude",
                                "claude_code_and_desktop_local_sessions", "last_record_per_request_id"))


def codex_tokens_metric(sessions_dir, archives_dir, now, zone=ZoneInfo("Asia/Shanghai"),
                        zstd_binary=None):
    diagnostics = {}
    records = load_codex(sessions_dir, archives_dir, zstd_binary=zstd_binary, diagnostics=diagnostics)
    value = _metric_value(records, now, zone, "codex", "codex_cli_local_rollouts",
                          "cumulative_total_diff_per_session")
    value["scan"] = diagnostics
    return metric(value, status="partial" if diagnostics["rollouts_skipped"] else "available",
                  reason=diagnostics.get("reason"))



def mcode_tokens_metric(db, now, zone=ZoneInfo("Asia/Shanghai")):
    return metric(_metric_value(load_mcode(db), now, zone, "mcode",
                                "minimax_code_local_runtime_db", "one_row_per_request"))


def collect_gemini_sessions(root, now, zone=ZoneInfo("Asia/Shanghai")):
    records = load_gemini(root)
    out = source("gemini", "local_session_history", now)
    out["metrics"]["tokens"] = metric(_metric_value(records, now, zone, "gemini",
                                                    "gemini_cli_local_chats", "last_record_per_message_id"))
    return out
