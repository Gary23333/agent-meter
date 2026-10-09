import sqlite3
from contextlib import contextmanager
from datetime import datetime, time as datetime_time, timedelta
from decimal import Decimal
from pathlib import Path

from .ccswitch_sql import effective_filter, folded_app, fresh_input_sql
from .model import DISPLAY_ZONE, SourceError, account_key, decimal_string, integer, metric, source, timestamp

SUPPORTED_SCHEMA = {20}
TOKEN_COLUMNS = {"app_type", "provider_id", "model", "pricing_model", "input_tokens", "output_tokens",
                 "cache_read_tokens", "cache_creation_tokens", "input_token_semantics", "total_cost_usd"}


class DecimalSum:
    def __init__(self):
        self.total = Decimal(0)

    def step(self, value):
        self.total += Decimal(decimal_string(value))

    def finalize(self):
        return format(self.total, "f")


@contextmanager
def readonly_database(path):
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise SourceError("database_not_found")
    try:
        conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=3)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.create_aggregate("decimal_sum", 1, DecimalSum)
        conn.execute("BEGIN")
        yield conn
    except sqlite3.Error:
        raise SourceError("database_read_failed") from None
    finally:
        if "conn" in locals():
            conn.rollback()
            conn.close()


def validate_schema(conn):
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version not in SUPPORTED_SCHEMA:
        raise SourceError("unsupported_ccswitch_schema")
    requirements = {
        "proxy_request_logs": TOKEN_COLUMNS | {"request_id", "created_at", "data_source", "status_code", "cost_multiplier"},
        "usage_daily_rollups": TOKEN_COLUMNS | {"date", "request_count", "success_count"},
        "session_log_sync": {"last_synced_at"},
    }
    for table, expected in requirements.items():
        columns = {r[1] for r in conn.execute("PRAGMA table_info(" + table + ")")}
        if not expected <= columns:
            raise SourceError("incompatible_ccswitch_columns")
    for table in ("proxy_request_logs", "usage_daily_rollups"):
        if conn.execute("SELECT 1 FROM " + table + " WHERE input_token_semantics NOT IN (0,1,2) LIMIT 1").fetchone():
            raise SourceError("unknown_token_semantics")
        if conn.execute("SELECT 1 FROM " + table + " WHERE input_tokens < 0 OR output_tokens < 0 OR cache_read_tokens < 0 OR cache_creation_tokens < 0 LIMIT 1").fetchone():
            raise SourceError("invalid_token_counts")
    return version


def period_bounds(now, period, zone=DISPLAY_ZONE):
    end = int(now)
    local = datetime.fromtimestamp(end, zone)
    if period == "all":
        return None, end
    if period == "today":
        return int(datetime.combine(local.date(), datetime_time(), zone).timestamp()), end
    days = {"7d": 7, "30d": 30}.get(period)
    if days is None:
        raise SourceError("invalid_period")
    return end - days * 86400, end


def app_imported_days(path, zone, app):
    """Local days CC Switch recorded for an app (any data source, folded).

    CC Switch stays primary for those days, so direct readers of the same
    CLI's local logs must skip them or the two would add up. Returns
    (days, state) with state in {checked, ccswitch_absent, ccswitch_read_failed}.
    """
    path = Path(path).expanduser()
    if not path.is_file():
        return set(), "ccswitch_absent"
    apps = {"claude": ("claude", "claude-desktop")}.get(app, (app,))
    marks = ",".join("?" * len(apps))
    try:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=3)
        try:
            conn.execute("PRAGMA query_only=ON")
            rows = conn.execute("SELECT created_at FROM proxy_request_logs WHERE app_type IN (" + marks + ")", apps).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return set(), "ccswitch_read_failed"
    return {datetime.fromtimestamp(r[0], zone).date().isoformat() for r in rows}, "checked"


def rollup_bounds(start, end, zone=DISPLAY_ZONE):
    # Mirrors v4.0.5: only fully covered local days, with its 23:59 rule.
    lo = hi = None
    if start is not None:
        dt = datetime.fromtimestamp(start, zone)
        lo = dt.date() if dt.hour == dt.minute == dt.second == 0 else dt.date() + timedelta(days=1)
    if end is not None:
        dt = datetime.fromtimestamp(end, zone)
        hi = dt.date() if dt.hour == 23 and dt.minute == 59 else dt.date() - timedelta(days=1)
    return lo, hi


def summarize(conn, start=None, end=None, zone=DISPLAY_ZONE):
    detail_conditions = [effective_filter("l")]
    params = []
    for expr, value in (("l.created_at >= ?", start), ("l.created_at <= ?", end)):
        if value is not None:
            detail_conditions.append(expr)
            params.append(value)
    detail_where = " AND ".join(detail_conditions)
    raw_conditions = [x for x in detail_conditions[1:]]
    raw_where = " AND ".join(raw_conditions) or "1=1"
    raw_count = conn.execute("SELECT COUNT(*) FROM proxy_request_logs l WHERE " + raw_where, params).fetchone()[0]
    retained_count = conn.execute("SELECT COUNT(*) FROM proxy_request_logs l WHERE " + detail_where, params).fetchone()[0]
    lower, upper = rollup_bounds(start, end, zone)
    roll_conditions, roll_params = [], []
    if lower is not None:
        roll_conditions.append("r.date >= ?")
        roll_params.append(lower.isoformat())
    if upper is not None:
        roll_conditions.append("r.date <= ?")
        roll_params.append(upper.isoformat())
    if lower is not None and upper is not None and lower > upper:
        roll_conditions.append("1=0")
    roll_where = " AND ".join(roll_conditions) or "1=1"
    group = "app, provider_id, model"
    detail_sql = f"""SELECT {folded_app('l')} AS app, l.provider_id,
       COALESCE(NULLIF(l.pricing_model,''),l.model) AS model,
       COUNT(*) AS requests, SUM(CASE WHEN l.status_code BETWEEN 200 AND 299 THEN 1 ELSE 0 END) AS successes,
       SUM({fresh_input_sql('l')}) AS fresh_input, SUM(l.output_tokens) AS output,
       SUM(l.cache_read_tokens) AS cache_read, SUM(l.cache_creation_tokens) AS cache_write,
       decimal_sum(l.total_cost_usd) AS cost,
       SUM(CASE WHEN l.status_code BETWEEN 200 AND 299 AND CAST(l.total_cost_usd AS REAL)=0
           AND CAST(l.cost_multiplier AS REAL)<>0
           AND (l.input_tokens+l.output_tokens+l.cache_read_tokens+l.cache_creation_tokens)>0 THEN 1 ELSE 0 END) AS unpriced
       FROM proxy_request_logs l WHERE {detail_where} GROUP BY {group}"""
    roll_sql = f"""SELECT {folded_app('r')} AS app, r.provider_id,
       COALESCE(NULLIF(r.pricing_model,''),r.model) AS model,
       SUM(r.request_count) AS requests, SUM(r.success_count) AS successes,
       SUM({fresh_input_sql('r')}) AS fresh_input, SUM(r.output_tokens) AS output,
       SUM(r.cache_read_tokens) AS cache_read, SUM(r.cache_creation_tokens) AS cache_write,
       decimal_sum(r.total_cost_usd) AS cost, 0 AS unpriced
       FROM usage_daily_rollups r WHERE {roll_where} GROUP BY {group}"""
    groups = {}
    for kind, query, values in (("detail", detail_sql, params), ("rollup", roll_sql, roll_params)):
        for row in conn.execute(query, values):
            key = (row["app"], row["provider_id"], row["model"])
            target = groups.setdefault(key, {
                "app": key[0], "provider_key": account_key("ccswitch_provider", str(key[1])), "model": key[2],
                "requests": 0, "successful_requests": 0, "fresh_input": 0, "output": 0,
                "cache_read": 0, "cache_write": 0, "estimated_cost_usd": Decimal(0),
                "unpriced_detail_requests": 0, "detail_requests": 0, "rollup_requests": 0,
            })
            for dest, src in (("requests", "requests"), ("successful_requests", "successes"), ("fresh_input", "fresh_input"),
                              ("output", "output"), ("cache_read", "cache_read"), ("cache_write", "cache_write"),
                              ("unpriced_detail_requests", "unpriced")):
                target[dest] += integer(row[src])
            target[kind + "_requests"] += row["requests"]
            target["estimated_cost_usd"] += Decimal(row["cost"])
    totals = {k: sum(r[k] for r in groups.values()) for k in
              ("requests", "successful_requests", "fresh_input", "output", "cache_read", "cache_write", "unpriced_detail_requests")}
    totals["estimated_cost_usd"] = format(sum((r["estimated_cost_usd"] for r in groups.values()), Decimal(0)), "f")
    for row in list(groups.values()) + [totals]:
        row["total_tokens"] = row["fresh_input"] + row["output"] + row["cache_read"] + row["cache_write"]
        denominator = row["fresh_input"] + row["cache_read"] + row["cache_write"]
        row["cache_hit_rate"] = row["cache_read"] / denominator if denominator else None
        row["success_rate"] = row["successful_requests"] / row["requests"] if row["requests"] else None
        row["estimated_cost_usd"] = str(row["estimated_cost_usd"])
    sources = [dict(r) for r in conn.execute(
        f"SELECT COALESCE(l.data_source,'proxy') AS source, {folded_app('l')} AS app, COUNT(*) AS records FROM proxy_request_logs l WHERE {detail_where} GROUP BY source, app", params)]
    # Partial old days cannot be reconstructed from daily rollups.
    excluded_days = []
    for day in sorted({datetime.fromtimestamp(x, zone).date().isoformat() for x in (start, end) if x is not None}):
        inside = (lower is None or day >= lower.isoformat()) and (upper is None or day <= upper.isoformat())
        if not inside and conn.execute("SELECT 1 FROM usage_daily_rollups WHERE date=? LIMIT 1", (day,)).fetchone():
            excluded_days.append(day)
    return {"start": timestamp(start), "end": timestamp(end), "timezone": str(zone),
            "totals": totals, "groups": sorted(groups.values(), key=lambda r: (r["app"], str(r["provider_key"]), r["model"])),
            "sources": sources, "raw_detail_records": raw_count,
            "deduplicated_detail_records": retained_count, "suppressed_duplicate_records": raw_count - retained_count,
            "excluded_partial_rollup_days": excluded_days,
            "period_status": "partial" if excluded_days else "available",
            "total_is_lower_bound": bool(excluded_days),
            "coverage": "ccswitch_imported_local_history", "dedup_rule": "ccswitch_v4.0.5_600_second_heuristic",
            "cost_kind": "api_equivalent_estimate_not_bill"}


def collect_ccswitch(path, now, zone=DISPLAY_ZONE):
    with readonly_database(path) as conn:
        version = validate_schema(conn)
        periods = {p: summarize(conn, *period_bounds(now, p, zone), zone=zone) for p in ("today", "7d", "30d", "all")}
        last_sync = conn.execute("SELECT MAX(last_synced_at) FROM session_log_sync").fetchone()[0]
        out = source("ccswitch", "local_imported_history", now)
        out["metrics"]["tokens"] = metric({"periods": periods})
        out["metrics"]["cost"] = metric({"unit": "USD", "kind": "estimate",
            "periods": {p: {"amount": data["totals"]["estimated_cost_usd"],
                           "unpriced_detail_requests": data["totals"]["unpriced_detail_requests"],
                           "rollup_pricing_completeness": "unknown"} for p, data in periods.items()}},
            status="partial" if any(p["totals"]["unpriced_detail_requests"] for p in periods.values()) else "available")
        out["diagnostics"].update({"schema_version": version, "reference_version": "4.0.5",
                                  "last_import_at": timestamp(last_sync), "read_only": True,
                                  "source_timezone": str(zone), "coverage_complete": False})
        return out
