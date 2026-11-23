"""All-device usage projection built from the synced rows.

The sync store keeps one bucket per *remote* device; the live snapshot is the
authority for this machine. This module only sums the remote buckets, so the
UI can add them to its local usage without ever counting a local row twice.

Rows are per day, app and model. Costs are estimated with the same local price
table as the local ledgers, at the off-peak base price: a synced row carries no
request time, so the peak split of the device that measured it cannot travel.
Models the table cannot match are named so the UI can say the cost is a lower
bound. One price-table pass also prices each device on its own, so the usage
page can show what every machine spent. Image counts and local credit spend
are summed the same way, per period.
"""
from datetime import datetime, timedelta
from decimal import Decimal

from .model import DISPLAY_ZONE

PERIODS = (("today", 0), ("7d", 6), ("30d", 29), ("all", None))
TOKEN_FIELDS = ("fresh_input", "output", "reasoning", "cache_read", "cache_write")
EMPTY_TOTALS = {"requests": 0, "reasoning": 0, "unclassified": 0, "fresh_input": 0,
                "output": 0, "cache_read": 0, "cache_write": 0, "total_tokens": 0}


def _day(now):
    return datetime.fromtimestamp(float(now), DISPLAY_ZONE).date()


def _remote(store, name):
    """(device, row) for one section of every remote device's bucket."""
    local = store.get("local_device") or ""
    out = []
    for device, bucket in sorted((store.get("devices") or {}).items()):
        if device == local or not isinstance(bucket, dict):
            continue
        for row in bucket.get(name) or []:
            if isinstance(row, dict):
                out.append((device, row))
    return out


def _rows(store):
    """Remote usage rows only, newest first irrelevant: callers filter by date."""
    local = store.get("local_device") or ""
    rows = []
    for device, row in _remote(store, "rows"):
        # The header's device is authoritative; a row that claims another one
        # (or this machine) is not counted.
        if row.get("device") == local:
            continue
        date, model = row.get("date"), row.get("model")
        if not isinstance(date, str) or len(date) != 10 or not isinstance(model, str) or not model:
            continue
        rows.append((device, row))
    return rows


def _start(period, today):
    offset = dict(PERIODS)[period]
    return None if offset is None else (today - timedelta(days=offset)).isoformat()


def _in(date, start):
    return start is None or (date or "") >= start


def _aggregate(rows, start):
    groups = {}
    totals = dict(EMPTY_TOTALS)
    devices = set()
    for device, row in rows:
        if not _in(row.get("date"), start):
            continue
        devices.add(device)
        app = row.get("app") or "其他"
        model = row.get("model") or "未知模型"
        key = (app, model)
        group = groups.get(key)
        if group is None:
            group = {"app": app, "model": model, "source": "sync", "requests": 0, "reasoning": 0,
                     "fresh_input": 0, "output": 0, "cache_read": 0, "cache_write": 0,
                     "total_tokens": 0}
            groups[key] = group
        for key_name in TOKEN_FIELDS:
            value = _number(row.get(key_name))
            group[key_name] += value
            totals[key_name] += value
        requests = _number(row.get("requests"))
        group["requests"] += requests
        totals["requests"] += requests
        # The row's total may carry tokens without a breakdown; keep them so
        # the group total never disagrees with the row sum.
        total = _number(row.get("total_tokens"))
        known = sum(_number(row.get(k)) for k in TOKEN_FIELDS)
        unknown = _number(row.get("unclassified"))
        if unknown == 0:
            unknown = max(0, total - known)
        group["total_tokens"] += total
        totals["total_tokens"] += total
        group["unclassified"] = group.get("unclassified", 0) + unknown
        totals["unclassified"] += unknown
    denominator = totals["fresh_input"] + totals["cache_read"] + totals["cache_write"]
    totals["cache_hit_rate"] = totals["cache_read"] / denominator if denominator else None
    totals["peak_tokens"] = 0
    totals["offpeak_tokens"] = totals["total_tokens"]
    return {"totals": totals, "groups": [groups[k] for k in sorted(groups)],
            "devices": sorted(devices)}


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def _images(store, start, table):
    """Remote image_gen counts in a window, priced in the local table's currency."""
    count, amounts = 0, {}
    for _device, row in _remote(store, "images"):
        if not _in(row.get("date"), start):
            continue
        count += int(_number(row.get("images")))
        cost, currency = _number(row.get("estimated_cost")), row.get("currency")
        if cost and currency in {"USD", "CNY"}:
            amounts[currency] = amounts.get(currency, Decimal(0)) + Decimal(str(cost))
    cost = None
    if table is not None and amounts:
        # Rows were priced on the device that made the image, in its own
        # table currency; the local rate brings them onto one scale.
        rate = Decimal(str(table.fx_rate))
        total = sum((amount if currency == table.currency else
                     amount * rate if currency == "USD" else amount / rate)
                    for currency, amount in amounts.items())
        cost = {"unit": table.currency, "amount": float(total)}
    return {"count": count, "cost": cost}


def _credits(store, start):
    """Remote local-credit spend in a window, kept apart per unit."""
    out = {}
    for _device, row in _remote(store, "credits"):
        if not _in(row.get("date"), start):
            continue
        unit = row.get("unit")
        if not isinstance(unit, str) or not unit:
            continue
        entry = out.setdefault(unit, {"credits": 0.0, "requests": 0})
        entry["credits"] += _number(row.get("credits"))
        entry["requests"] += int(_number(row.get("requests")))
    return out


def usage_periods(store, runtime_dir, now):
    """Per-period remote totals/groups plus a price-table estimate, or None."""
    rows = _rows(store)
    has_media = any(_remote(store, name) for name in ("images", "credits"))
    if not rows and not has_media:
        return None
    from .prices import estimate_source_cost, load_prices

    table = load_prices(runtime_dir)
    today = _day(now)
    starts = {period: _start(period, today) for period, _ in PERIODS}
    windows = {period: _aggregate(rows, starts[period]) for period, _ in PERIODS}
    # Every device's own groups per period, priced in the same pass.
    per_device = {}
    for period, _ in PERIODS:
        for device in windows[period]["devices"]:
            per_device[(device, period)] = _aggregate(
                [pair for pair in rows if pair[0] == device and _in(pair[1].get("date"), starts[period])],
                None)["groups"]

    def device_key(device, period):
        return "device:" + device + ":" + period

    tokens_metric = {"status": "available",
                     "value": {"periods": {**{p: {"groups": w["groups"]} for p, w in windows.items()},
                                          **{device_key(d, p): {"groups": g} for (d, p), g in per_device.items()}}}}
    cost = estimate_source_cost(tokens_metric, table) if table is not None else None
    cost_value = (cost or {}).get("value") or {}
    cost_periods = cost_value.get("periods") or {}
    peak_window = cost_value.get("peak_window")
    unit = cost_value.get("unit")

    def amount(key):
        raw = (cost_periods.get(key) or {}).get("amount")
        return float(raw) if raw is not None else None

    out = {}
    for period, _ in PERIODS:
        window = windows[period]
        start = starts[period]
        group_cost = cost_periods.get(period) or {}
        priced = amount(period)
        own = [pair for pair in rows if _in(pair[1].get("date"), start)]
        out[period] = {
            "totals": window["totals"],
            "groups": window["groups"],
            "devices": window["devices"],
            "device_count": len(window["devices"]),
            "rows": len(own),
            "cost": {"unit": unit, "amount": priced,
                     "models": group_cost.get("models") or {},
                     "app_models": group_cost.get("app_models") or {},
                     "unmatched_models": group_cost.get("unmatched_models") or [],
                     "unsplit_models": group_cost.get("unsplit_models") or [],
                     "peak_window": peak_window} if cost is not None and priced is not None else None,
            "by_device": [{"device": device,
                           "total_tokens": sum(_number(row.get("total_tokens")) for d, row in own if d == device),
                           "requests": sum(int(_number(row.get("requests"))) for d, row in own if d == device),
                           "amount": amount(device_key(device, period))}
                          for device in window["devices"]],
            "images": _images(store, start, table),
            "credits": _credits(store, start),
        }
    return {"schema": 1, "device_count": len({device for device, _ in rows}), "periods": out}
