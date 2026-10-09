"""OpenCode local token usage from its own message database (read-only).

~/.local/share/opencode/opencode.db keeps one row per message; assistant
messages carry data.tokens {total, input, output, reasoning,
cache:{write,read}} where input is fresh (cache separate). Verified on
this machine (2026-10-09): 12,324 token-bearing rows, all assistant, one
per response. CC Switch imports the same OpenCode sessions
(opencode_session rows, 94 records on 2026-09-29 vs 95 here): days CC
Switch already imported are excluded from this source and stay counted
by CC Switch, so the two never add up. Only token/model fields are
selected; message text stays in the database.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .ccswitch import app_imported_days, period_bounds
from .model import SourceError, metric, source, timestamp

COLUMNS = {"time_created", "data"}


@contextmanager
def readonly_database(path):
    path = Path(path).expanduser()
    if not path.is_file():
        raise SourceError("opencode_db_not_found")
    conn = None
    try:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=3)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        yield conn
    except sqlite3.Error:
        raise SourceError("opencode_db_read_failed") from None
    finally:
        if conn is not None:
            conn.rollback()
            conn.close()


def validate_schema(conn):
    columns = {r[1] for r in conn.execute("PRAGMA table_info(message)")}
    if not COLUMNS <= columns:
        raise SourceError("unsupported_opencode_schema")


def ccswitch_imported_days(path, zone):
    """Local days CC Switch already imported for OpenCode (it stays primary)."""
    return app_imported_days(path, zone, "opencode")


def summarize(rows, start, end, excluded):
    """rows are (day, ts_ms, model, fresh, output, reasoning, read, write)."""
    out = {"requests": 0, "fresh_input": 0, "output": 0, "reasoning": 0, "cache_read": 0, "cache_write": 0}
    models = {}
    excluded_here = set()
    for day, t, model, fresh, output, reasoning, cache_read, cache_write in rows:
        if day in excluded:
            excluded_here.add(day)
            continue
        if (start is not None and t < start * 1000) or t > end * 1000:
            continue
        out["requests"] += 1
        out["fresh_input"] += fresh
        out["output"] += output
        out["reasoning"] += reasoning
        out["cache_read"] += cache_read
        out["cache_write"] += cache_write
        target = models.setdefault(model, {"requests": 0, "fresh_input": 0, "output": 0,
                                           "reasoning": 0, "cache_read": 0, "cache_write": 0})
        for name, value in (("requests", 1), ("fresh_input", fresh), ("output", output),
                            ("reasoning", reasoning), ("cache_read", cache_read), ("cache_write", cache_write)):
            target[name] += value
    out["total_tokens"] = sum(out[k] for k in ("fresh_input", "output", "reasoning", "cache_read", "cache_write"))
    denominator = out["fresh_input"] + out["cache_read"] + out["cache_write"]
    out["cache_hit_rate"] = out["cache_read"] / denominator if denominator else None
    return {"start": timestamp(start) if start is not None else None, "end": timestamp(end),
            "totals": out,
            "groups": [{"app": "opencode", "model": m, **v,
                        "total_tokens": sum(v[k] for k in ("fresh_input", "output", "reasoning", "cache_read", "cache_write"))}
                       for m, v in sorted(models.items(), key=lambda x: -x[1]["fresh_input"])],
            "excluded_ccswitch_days": sorted(excluded_here)}


def _tokens(data):
    """Extract (model, fresh, output, reasoning, read, write) from a message row."""
    try:
        o = json.loads(data)
    except (ValueError, TypeError):
        return None
    if not isinstance(o, dict) or o.get("role") != "assistant":
        return None
    tokens = o.get("tokens")
    if not isinstance(tokens, dict):
        return None
    def nonneg(v):
        return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None
    cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}
    values = (nonneg(tokens.get("input")), nonneg(tokens.get("output")), nonneg(tokens.get("reasoning")),
              nonneg(cache.get("read")), nonneg(cache.get("write")))
    if any(v is None for v in values):
        return None
    model = o.get("modelID")
    model = model if isinstance(model, str) and 0 < len(model) < 120 else "unknown"
    return (model, *values)


def collect_opencode_tokens(path, ccswitch_db, now, zone=ZoneInfo("Asia/Shanghai")):
    excluded, overlap_state = ccswitch_imported_days(ccswitch_db, zone)
    with readonly_database(path) as conn:
        validate_schema(conn)
        rows = []
        malformed = 0
        for time_created, data in conn.execute("SELECT time_created, data FROM message"):
            parsed = _tokens(data)
            if parsed is None:
                if '"tokens"' in (data or ""):
                    malformed += 1
                continue
            day = datetime.fromtimestamp(time_created / 1000, zone).date().isoformat()
            rows.append((day, time_created, *parsed))
    periods = {p: summarize(rows, *period_bounds(now, p, zone), excluded) for p in ("today", "7d", "30d", "all")}
    for p in periods.values():
        p["timezone"] = str(zone)
    daily = {}
    for day, t, model, fresh, output, reasoning, cache_read, cache_write in rows:
        if day in excluded:
            continue
        daily[day] = daily.get(day, 0) + fresh + output + reasoning + cache_read + cache_write
    out = source("opencode", "local_session_history", now)
    out["metrics"]["tokens"] = metric({
        "periods": periods,
        "daily_buckets": [{"date": d, "tokens": n} for d, n in sorted(daily.items())],
        "coverage": "opencode_local_message_db",
        "dedup_rule": "one_assistant_message_per_response",
        "ccswitch_overlap": {"state": overlap_state, "excluded_days": sorted(excluded)},
        "malformed_token_rows": malformed,
    })
    return out
