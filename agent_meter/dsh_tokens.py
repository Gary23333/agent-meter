"""DeepSeek Harness (dsh) local token ledger from its zstd session files.

~/.dsh/sessions/<encoded project path>/<session id>/ holds one compressed
JSONL per session: session.v3.jsonl.zstd (v3), session.v4.jsonl.zstd (v4)
or the legacy session.jsonl.zstd. Only usage fields are read, never
conversation text. Field semantics were verified against this machine's
files (2026-10-18 v3/legacy, 2026-10-31 v4, 20,578+ usage records):

- v3 / v4: type "assistant/message" carries data.usage {inputTokens,
  outputTokens, cacheReadTokens, reasoningTokens, totalTokens}; v4 adds
  cacheWriteTokens (zero on every checked record) and omits reasoningTokens.
  The model sits in data.message.source.model. data.stream may embed a copy
  of the same usage chunk — only data.usage is read, so it is never counted
  twice.
- legacy: type "assistant/chunk" carries progressive data.chunk.usage values
  (early ones may be 0) and the following "assistant/message" record holds
  the final data.usage for the same (turn, step); the model is the closest
  preceding request/header (data.header.config.model), "unknown" without one.
- inputTokens is fresh (cache-miss) input; cacheReadTokens is independent;
  cacheWriteTokens is recorded separately (0 when absent); reasoningTokens is
  a subset of outputTokens, so output is split as outputTokens − reasoningTokens.

Dedup: within one file keep the record with the largest timestamp per
(turn, step) — covers identical chunk/message pairs and progressive values.
Files are independent sessions; no cross-file dedup. Timestamps are
milliseconds and are converted to seconds before bucketing.
"""
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from .cli_sessions import _file_records, _last_per_key, _metric_value, _model, _nonneg, _prune
from .model import SourceError, metric, source
from .zstd_io import ZSTD_ERRORS as _ZSTD_ERRORS, decompressed, route as _route


def _key_part(value):
    return value if isinstance(value, (int, str)) and not isinstance(value, bool) else None


def _usage_fields(usage):
    """(fresh, output, reasoning, cache_read, cache_write); None when absent."""
    if not isinstance(usage, dict):
        return None
    fresh = _nonneg(usage.get("inputTokens"))
    output = _nonneg(usage.get("outputTokens"))
    reasoning = _nonneg(usage.get("reasoningTokens"))
    return (fresh, max(0, output - reasoning), reasoning,
            _nonneg(usage.get("cacheReadTokens")), _nonneg(usage.get("cacheWriteTokens")))


def _parse_dsh_file(path, route, zstd_binary):
    """(records, schema) for one session file; raises OSError when unreadable."""
    if ".v4." in path.name:
        schema = "v4"
    elif ".v3." in path.name:
        schema = "v3"
    else:
        schema = "legacy"
    is_message_schema = schema in {"v3", "v4"}
    header_model = "unknown"
    keyed = []
    try:
        with decompressed(path, route, zstd_binary) as handle:
            for line in handle:
                if b'"usage"' not in line and b'"request/header"' not in line:
                    continue
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(o, dict) or not isinstance(o.get("data"), dict):
                    continue
                kind, data = o.get("type"), o["data"]
                if kind == "request/header":
                    header = data.get("header")
                    config = header.get("config") if isinstance(header, dict) else None
                    if isinstance(config, dict) and config.get("model") is not None:
                        header_model = _model(config.get("model"))
                    continue
                if kind == "assistant/chunk":
                    chunk = data.get("chunk")
                    usage = chunk.get("usage") if isinstance(chunk, dict) else None
                elif kind == "assistant/message":
                    # data.stream may embed the same usage; only data.usage counts.
                    usage = data.get("usage")
                else:
                    continue
                fields = _usage_fields(usage)
                if fields is None:
                    continue
                when = o.get("time")
                if isinstance(when, bool) or not isinstance(when, (int, float)) or when < 0:
                    continue
                model = header_model
                if is_message_schema:
                    message = data.get("message")
                    origin = message.get("source") if isinstance(message, dict) else None
                    if isinstance(origin, dict) and isinstance(origin.get("model"), str) and origin["model"]:
                        model = _model(origin["model"])
                t = when / 1000
                key = (_key_part(data.get("turn")), _key_part(data.get("step")))
                keyed.append((key, t, (t, model, *fields)))
    except _ZSTD_ERRORS:
        raise OSError("unreadable zstd session file") from None
    return tuple(_last_per_key(keyed)), schema


def load_dsh_sessions(root, zstd_binary=None):
    """(records, v3, v4, legacy, skipped, route) from one sessions tree.

    Record shape matches cli_sessions: (epoch_seconds, model, fresh_input,
    output, reasoning, cache_read, cache_write).
    """
    root = Path(root)
    paths = sorted(root.glob("**/session*.jsonl.zstd")) if root.is_dir() else []
    if not paths:
        raise SourceError("dsh_sessions_not_found")
    route = _route(zstd_binary)

    def parse(path):
        return _parse_dsh_file(path, route, zstd_binary)

    records = []
    seen = set()
    v3_files = v4_files = legacy_files = skipped = 0
    for path in paths:
        seen.add(str(path))
        parsed = _file_records(path, parse, "dsh")
        if not parsed:
            skipped += 1
            continue
        file_records, schema = parsed
        if schema == "v3":
            v3_files += 1
        elif schema == "v4":
            v4_files += 1
        else:
            legacy_files += 1
        records.extend(file_records)
    _prune(seen, "dsh")
    return records, v3_files, v4_files, legacy_files, skipped, route


def collect_dsh_sessions(sessions_dir, now,
                         zone=ZoneInfo("Asia/Shanghai"), zstd_binary=None):
    records, v3_files, v4_files, legacy_files, skipped, route = load_dsh_sessions(sessions_dir, zstd_binary)
    if skipped and not (v3_files or v4_files or legacy_files):
        raise SourceError("dsh_sessions_unreadable")
    status = "partial" if skipped else "available"
    reason = "dsh_sessions_unreadable" if skipped else None
    out = source("deepseek_harness", "local_session_history", now, status=status, reason=reason)
    out["metrics"]["tokens"] = metric(
        _metric_value(records, now, zone, "dsh", "dsh_local_session_logs",
                      "last_usage_per_turn_step"), status=status, reason=reason)
    out["diagnostics"]["v3_session_files"] = v3_files
    out["diagnostics"]["v4_session_files"] = v4_files
    out["diagnostics"]["legacy_session_files"] = legacy_files
    out["diagnostics"]["skipped_session_files"] = skipped
    out["diagnostics"]["decompression_route"] = route
    return out
