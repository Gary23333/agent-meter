"""只在逐日模型与 Token 拆分完整时，计算本机 API 等价价格。"""
from datetime import date, datetime

from agent_meter.model import DISPLAY_ZONE
from agent_meter.prices import estimate_daily_cost

TOKEN_FIELDS = ("fresh_input", "output", "reasoning", "cache_read", "cache_write")


def daily_cost_metric(item, now, table):
    """返回可用于徽章的美元逐日估算；任何不完整信息均返回 None。"""
    if table is None or not isinstance(item, dict) or item.get("status") != "available":
        return None
    value = item.get("value")
    if not isinstance(value, dict):
        return None
    buckets, models = value.get("daily_buckets"), value.get("daily_models")
    if not isinstance(buckets, list) or not isinstance(models, list):
        return None
    today = datetime.fromtimestamp(now, DISPLAY_ZONE).date()
    def valid_day(raw):
        try:
            parsed = date.fromisoformat(raw)
        except (ValueError, TypeError):
            return None
        return raw if parsed <= today and parsed.isoformat() == raw else None
    def nonnegative(raw):
        return isinstance(raw, int) and not isinstance(raw, bool) and 0 <= raw <= 2**63 - 1
    expected = {}
    for row in buckets:
        if not isinstance(row, dict): return None
        day, tokens = valid_day(row.get("date")), row.get("tokens")
        if day is None or not nonnegative(tokens): return None
        expected[day] = expected.get(day, 0) + tokens
    actual = {}
    for row in models:
        if not isinstance(row, dict): return None
        day, model = valid_day(row.get("date")), row.get("model")
        if day is None or not isinstance(model, str) or not model or table.match(model) is None: return None
        if any(not nonnegative(row.get(field)) for field in TOKEN_FIELDS): return None
        unclassified = row.get("unclassified", 0)
        if not nonnegative(unclassified) or unclassified != 0: return None
        count = sum(row[field] for field in TOKEN_FIELDS)
        if not nonnegative(row.get("total_tokens")) or count != row["total_tokens"]: return None
        actual[day] = actual.get(day, 0) + count
    if {day: n for day, n in expected.items() if n} != {day: n for day, n in actual.items() if n}:
        return None
    periods = value.get("periods", {})
    totals = periods.get("all", {}).get("totals", {}) if isinstance(periods, dict) else {}
    expected_total = totals.get("total_tokens") if isinstance(totals, dict) else None
    if not nonnegative(expected_total) or sum(expected.values()) != expected_total:
        return None
    daily = estimate_daily_cost(item, table)
    return {"status": "available", "value": {"basis": "local_price_table", "unit": "USD", "daily": daily}}
