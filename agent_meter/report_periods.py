"""Calendar week/month comparisons on the same daily rollups (E3).

Rolling 7d/30d windows cannot stand in for natural weeks/months: this module
sums each ledger's daily_models rows inside calendar boundaries (Asia/
Shanghai, week starts Monday) and compares the current partial period with
the previous complete one. Costs use the price table's base (off-peak) rate
because daily rows keep no request time; the basis is declared, never
hidden. Sources without daily_models are listed as gaps, not counted as 0.
"""
from datetime import datetime, time as datetime_time, timedelta
from decimal import Decimal

from .applications import app_id
from .model import DISPLAY_ZONE, SourceError, timestamp
from .prices import FX_FALLBACK


def calendar_bounds(now, kind, zone=DISPLAY_ZONE):
    """(previous_start, current_start, current_end) epochs."""
    local = datetime.fromtimestamp(now, zone)
    if kind == "week":
        start = datetime.combine(local.date() - timedelta(days=local.weekday()), datetime_time(), zone)
        return (start - timedelta(days=7)).timestamp(), start.timestamp(), now
    if kind == "month":
        start = datetime.combine(local.date().replace(day=1), datetime_time(), zone)
        previous_last = start - timedelta(days=1)
        previous_start = datetime.combine(previous_last.date().replace(day=1), datetime_time(), zone)
        return previous_start.timestamp(), start.timestamp(), now
    raise SourceError("invalid_period_kind")


def _date(epoch, zone):
    return datetime.fromtimestamp(epoch, zone).date().isoformat()


def _window(rows, start_date, end_date, table, app_default):
    totals = {"tokens": 0, "requests": 0, "fresh_input": 0, "output": 0, "reasoning": 0,
              "cache_read": 0, "cache_write": 0}
    by_app, by_model, days = {}, {}, set()
    cost = Decimal(0)
    unmatched = set()
    for row in rows:
        date = row.get("date")
        if not isinstance(date, str) or not (start_date <= date <= end_date):
            continue
        days.add(date)
        app = row.get("app") or app_default
        model = row.get("model") or "unknown"
        tokens = row.get("total_tokens", 0)
        totals["tokens"] += tokens
        totals["requests"] += row.get("requests", 0)
        for key in ("fresh_input", "output", "reasoning", "cache_read", "cache_write"):
            totals[key] += row.get(key, 0)
        a = by_app.setdefault(app, {"tokens": 0, "requests": 0})
        a["tokens"] += tokens
        a["requests"] += row.get("requests", 0)
        m = by_model.setdefault(model, {"tokens": 0, "requests": 0, "amount": Decimal(0)})
        m["tokens"] += tokens
        m["requests"] += row.get("requests", 0)
        pattern = table.match(model) if table is not None else None
        if pattern is not None:
            amount = table.cost_for(row, pattern)
            cost += amount
            m["amount"] += amount
        else:
            unmatched.add(model)
    denominator = totals["fresh_input"] + totals["cache_read"] + totals["cache_write"]
    cny = cost if table is not None and table.currency == "CNY" else cost * FX_FALLBACK
    models_out = {m: {"tokens": v["tokens"], "requests": v["requests"],
                      "amount_cny": format(v["amount"] if table is not None and table.currency == "CNY"
                                           else v["amount"] * FX_FALLBACK, "f")}
                  for m, v in sorted(by_model.items(), key=lambda x: -x[1]["tokens"])}
    return {"tokens": totals["tokens"], "requests": totals["requests"],
            "fields": {k: totals[k] for k in ("fresh_input", "output", "reasoning", "cache_read", "cache_write")},
            "days_with_data": len(days),
            "cache_hit_rate": totals["cache_read"] / denominator if denominator else None,
            "cost_cny": format(cny, "f"),
            "by_app": dict(sorted(by_app.items(), key=lambda x: -x[1]["tokens"])),
            "by_model": models_out,
            "unmatched_models": sorted(unmatched)}


def _pct(current, previous):
    if not previous:
        return None
    return round((current - previous) / previous * 100, 2)


def compute_period_report(snapshot, table, now, kind="week", zone=DISPLAY_ZONE):
    previous_start, current_start, current_end = calendar_bounds(now, kind, zone)
    prev_date, cur_date, end_date = (_date(previous_start, zone), _date(current_start, zone),
                                     _date(current_end, zone))
    current_rows, previous_rows, gaps = [], [], []
    for src in snapshot.get("sources", []):
        tokens = src.get("metrics", {}).get("tokens") or {}
        if tokens.get("status") not in {"available", "partial", "stale"}:
            continue
        value = tokens.get("value") or {}
        if "periods" not in value:
            continue
        rows = value.get("daily_models")
        if not isinstance(rows, list):
            gaps.append(src["id"])
            continue
        app = app_id(src["id"])
        for row in rows:
            row = dict(row)
            row.setdefault("app", app)
            if prev_date <= row.get("date", "") < cur_date:
                previous_rows.append(row)
            if cur_date <= row.get("date", "") <= end_date:
                current_rows.append(row)
    current = _window(current_rows, cur_date, end_date, table, None)
    previous = _window(previous_rows, prev_date, _date(current_start - 86400, zone), table, None)
    movers = []
    for model, data in current["by_model"].items():
        before = previous["by_model"].get(model, {}).get("tokens", 0)
        movers.append({"model": model, "tokens": data["tokens"],
                       "delta_tokens": data["tokens"] - before})
    for model, data in previous["by_model"].items():
        if model not in current["by_model"]:
            movers.append({"model": model, "tokens": 0, "delta_tokens": -data["tokens"]})
    movers.sort(key=lambda m: -abs(m["delta_tokens"]))
    return {
        "schema_version": 1,
        "kind": kind,
        "timezone": str(zone),
        "generated_at": timestamp(now),
        "current": {"start": timestamp(current_start), "end": timestamp(current_end), **current},
        "previous": {"start": timestamp(previous_start), "end": timestamp(current_start), **previous},
        "delta": {"tokens_pct": _pct(current["tokens"], previous["tokens"]),
                  "requests_pct": _pct(current["requests"], previous["requests"]),
                  "cost_pct": _pct(float(current["cost_cny"]), float(previous["cost_cny"])),
                  "cache_hit_rate_change": (round(current["cache_hit_rate"] - previous["cache_hit_rate"], 4)
                                            if current["cache_hit_rate"] is not None
                                            and previous["cache_hit_rate"] is not None else None)},
        "top_movers": movers[:10],
        "sources_without_daily_detail": sorted(gaps),
        "basis": "daily_rollup_base_price_no_peak_split",
        "note": "Current period is partial (up to now); previous period is complete. "
                "Costs are API-equivalent estimates at base prices, not bills.",
    }