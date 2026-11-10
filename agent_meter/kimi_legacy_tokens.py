"""Old Kimi CLI token history from ~/.kimi/sessions (read-only).

Pre-migration ledger: each wire.jsonl line is {message:{payload:{...}},
timestamp}; usage lives in message.payload.token_usage with snake_case
fields input_other / output / input_cache_read / input_cache_creation.
The top-level timestamp is epoch seconds (float), unlike kimi-code's
millisecond integers. Records carry no model field, so every row is
attributed to "unknown" and cannot be priced. Writes stopped at the
2026-06-17 migration to kimi-code; verified on this machine 2026-11-08:
80 wire files, 3,971 records / 396,282,036 tokens, zero session overlap
with ~/.kimi-code/sessions. Only token fields and message ids are read,
never message text.
"""
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .kimi_tokens import summarize
from . import daily as daily_mod
from .model import SourceError, metric, period_bounds, source
from .record_cache import records_cache as _cache

FIELDS = ("input_other", "output", "input_cache_read", "input_cache_creation")
MARKER = b'"token_usage"'


def _parse_file(path):
    records, excluded = [], 0
    with open(path, "rb") as handle:
        for index, line in enumerate(handle):
            if MARKER not in line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if not isinstance(o, dict):
                continue
            message = o.get("message")
            payload = message.get("payload") if isinstance(message, dict) else None
            usage = payload.get("token_usage") if isinstance(payload, dict) else None
            if not isinstance(usage, dict):
                continue
            values = [usage.get(k, 0) for k in FIELDS]
            t = o.get("timestamp")
            if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in values) \
                    or isinstance(t, bool) or not isinstance(t, (int, float)):
                excluded += 1
                continue
            message_id = payload.get("message_id")
            key = ("m", message_id) if isinstance(message_id, str) and message_id else ("l", str(path), index)
            records.append((float(t), *values, key))
    return records, excluded


def load_records(root):
    root = Path(root)
    if not root.is_dir():
        raise SourceError("kimi_legacy_sessions_not_found")
    records, excluded, seen, keys = [], 0, set(), set()
    for path in sorted(root.glob("**/wire.jsonl")):
        seen.add(str(path))
        try:
            parsed, skipped = _cache.read(path, _parse_file, ("kimi_legacy", str(root)))
        except OSError:
            continue
        excluded += skipped
        for t, fresh, out, read, write, key in parsed:
            if key in keys:
                excluded += 1
                continue
            keys.add(key)
            records.append((t, "unknown", fresh, out, read, write))
    _cache.prune(seen, ("kimi_legacy", str(root)))
    return records, excluded


def collect_kimi_legacy_tokens(root, now, zone=ZoneInfo("Asia/Shanghai")):
    records, excluded = load_records(root)
    periods = {p: summarize(records, *period_bounds(now, p, zone), app="kimi_legacy")
               for p in ("today", "7d", "30d", "all")}
    for p in periods.values():
        p["timezone"] = str(zone)
    daily = defaultdict(int)
    dm = {}
    for t, model, fresh, out, read, write in records:
        if t > now:
            continue
        day = datetime.fromtimestamp(t, zone).date().isoformat()
        daily[day] += fresh + out + read + write
        daily_mod.add(dm, day, model, {"fresh_input": fresh, "output": out,
                                       "cache_read": read, "cache_write": write})
    out = source("kimi_legacy", "local_session_history", now)
    out["metrics"]["tokens"] = metric({
        "periods": periods,
        "peak_split": "request_timestamp",
        "daily_buckets": [{"date": d, "tokens": n} for d, n in sorted(daily.items())],
        "daily_models": daily_mod.rows(dm, "kimi_legacy"),
        "coverage": "kimi_legacy_local_sessions",
        "dedup_rule": "message_id_or_file_line",
        "model_attribution": "unknown_no_model_field",
        "excluded_duplicate_records": excluded,
    })
    return out