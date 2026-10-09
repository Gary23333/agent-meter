"""ZCode local token usage from its own CLI database (read-only).

~/.zcode/cli/db/db.sqlite (WAL, live) holds one model_usage row per model
request with token columns already split into fresh input, reasoning and
cache read/write. Verified on this machine (2026-10-09): computed_total =
input+output+reasoning (cache tracked separately); cancelled/error rows
carry zero tokens; turn_usage totals match the per-turn subset of
model_usage within ~0.0001% (28 of 213 completed turns differ by 2,924
tokens in total), so turn_usage is a tolerance check, not the ledger.
Only usage columns are read; message bodies live in other tables and are
never selected.
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .ccswitch import period_bounds
from .model import SourceError, metric, source, timestamp

COLUMNS = {"started_at", "provider_id", "model_id", "status", "attempt_index",
           "input_tokens", "output_tokens", "reasoning_tokens",
           "cache_creation_input_tokens", "cache_read_input_tokens"}
# Order matches the SELECT in collect_zcode_local.
TOKEN_FIELDS = ("fresh_input", "output", "reasoning", "cache_write", "cache_read")


@contextmanager
def readonly_database(path):
    path = Path(path).expanduser()
    if not path.is_file():
        raise SourceError("zcode_db_not_found")
    conn = None
    try:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=3)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        yield conn
    except sqlite3.Error:
        raise SourceError("zcode_db_read_failed") from None
    finally:
        if conn is not None:
            conn.rollback()
            conn.close()


def validate_schema(conn):
    columns = {r[1] for r in conn.execute("PRAGMA table_info(model_usage)")}
    if not COLUMNS <= columns:
        raise SourceError("unsupported_zcode_usage_schema")


def summarize(rows, start, end):
    """One pass over (ts_ms, model, status, tokens...) rows for a period."""
    totals = dict.fromkeys(("requests", *TOKEN_FIELDS), 0)
    models = {}
    statuses = {}
    for ts_ms, model, status, *values in rows:
        if (start is not None and ts_ms < start * 1000) or (ts_ms > end * 1000):
            continue
        totals["requests"] += 1
        statuses[status] = statuses.get(status, 0) + 1
        target = models.setdefault(model, dict.fromkeys(("requests", *TOKEN_FIELDS), 0))
        for name, value in zip(TOKEN_FIELDS, values):
            totals[name] += value
            target[name] += value
        target["requests"] += 1
    totals["total_tokens"] = sum(totals[f] for f in TOKEN_FIELDS)
    denominator = totals["fresh_input"] + totals["cache_read"] + totals["cache_write"]
    totals["cache_hit_rate"] = totals["cache_read"] / denominator if denominator else None
    return {"start": timestamp(start) if start is not None else None, "end": timestamp(end),
            "totals": totals,
            "groups": [{"app": "zcode", "model": m, **v,
                        "total_tokens": sum(v[f] for f in TOKEN_FIELDS)}
                       for m, v in sorted(models.items(), key=lambda x: -x[1]["fresh_input"])],
            "requests_by_status": statuses}


def zcode_tokens_metric(path, now, zone=ZoneInfo("Asia/Shanghai")):
    """Tokens metric only, attached to the ZCode account source."""
    out = collect_zcode_local(path, now, zone)
    return out["metrics"]["tokens"]


def collect_zcode_local(path, now, zone=ZoneInfo("Asia/Shanghai")):
    with readonly_database(path) as conn:
        validate_schema(conn)
        rows = [tuple(r) for r in conn.execute(
            "SELECT started_at, provider_id || '/' || model_id, status, input_tokens, output_tokens,"
            " reasoning_tokens, cache_creation_input_tokens, cache_read_input_tokens FROM model_usage")]
        retry_rows = conn.execute("SELECT COUNT(*) FROM model_usage WHERE attempt_index > 0").fetchone()[0]
    negative = sum(1 for r in rows if any(isinstance(v, int) and v < 0 for v in r[3:]))
    if negative:
        raise SourceError("invalid_zcode_token_counts")
    out = source("zcode", "local_session_history", now)
    out["metrics"]["tokens"] = metric({
        "periods": periods_value(rows, now, zone),
        "daily_buckets": daily_value(rows, zone),
        "coverage": "zcode_local_model_usage_db",
        "dedup_rule": "one_row_per_model_request_attempt",
        "retry_attempt_rows": retry_rows,
    })
    return out


def periods_value(rows, now, zone):
    periods = {p: summarize(rows, *period_bounds(now, p, zone)) for p in ("today", "7d", "30d", "all")}
    for p in periods.values():
        p["timezone"] = str(zone)
    return periods


def daily_value(rows, zone):
    daily = {}
    for row in rows:
        day = datetime.fromtimestamp(row[0] / 1000, zone).date().isoformat()
        daily[day] = daily.get(day, 0) + sum(row[3:])
    return [{"date": d, "tokens": n} for d, n in sorted(daily.items())]
