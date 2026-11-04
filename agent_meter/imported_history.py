"""Project-owned historical usage imported once from the retired local ledger.

The file is written by the one-off migration before the legacy ledger reader
is removed, then read here on every collection. Detail rows carry a request
timestamp and are split into peak / off-peak buckets; daily rows are
aggregated history without a request time and stay unsplit (priced at the
off-peak base). Totals are the same field convention as the direct CLI
readers: (epoch, model, fresh_input, output, reasoning, cache_read,
cache_write).
"""
import json
from datetime import date as calendar_date, datetime, time as datetime_time
from pathlib import Path
from zoneinfo import ZoneInfo

from . import peak
from .model import SourceError, metric, period_bounds, source, timestamp

TOKEN_KEYS = ("requests", "fresh_input", "output", "reasoning", "cache_read", "cache_write")
_cache = {}   # path -> ((mtime_ns, size), store)


def _nonneg_int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _text(value, limit=120):
    return value if isinstance(value, str) and 0 < len(value) < limit else None


def load_store(path):
    """Normalised store; raises SourceError with a fixed code."""
    p = Path(path).expanduser()
    try:
        st = p.stat()
        stamp = (st.st_ino, st.st_mtime_ns, st.st_size)
    except OSError:
        raise SourceError("history_store_not_found") from None
    cached = _cache.get(str(p))
    if cached is not None and cached[0] == stamp:
        return cached[1]
    try:
        data = json.loads(p.read_text())
    except (OSError, ValueError):
        raise SourceError("history_store_read_failed") from None
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise SourceError("unsupported_history_schema")
    if any(not isinstance(data.get(key, []), list) for key in ("detail", "daily")):
        raise SourceError("history_store_read_failed")
    detail, daily = [], []
    for row in data.get("detail") or []:
        if not isinstance(row, list) or len(row) != 7:
            raise SourceError("history_store_read_failed")
        app, model, t, fresh, output, cache_read, cache_write = row
        values = [_text(app), _text(model)] + [_nonneg_int(v) for v in (t, fresh, output, cache_read, cache_write)]
        if None in values or t > 253402271999:
            raise SourceError("history_store_read_failed")
        detail.append((values[0], values[1], values[2], values[3], values[4], values[5], values[6]))
    for row in data.get("daily") or []:
        if not isinstance(row, list) or len(row) != 8:
            raise SourceError("history_store_read_failed")
        app, model, date, requests, fresh, output, cache_read, cache_write = row
        if not (_text(app) and _text(model) and isinstance(date, str)):
            raise SourceError("history_store_read_failed")
        try:
            parsed_date = calendar_date.fromisoformat(date)
            if parsed_date.isoformat() != date:
                raise ValueError()
        except ValueError:
            raise SourceError("history_store_read_failed") from None
        values = [_nonneg_int(v) for v in (requests, fresh, output, cache_read, cache_write)]
        if None in values:
            raise SourceError("history_store_read_failed")
        daily.append((app, model, date, *values))
    store = {"imported_at": data.get("imported_at"), "detail": tuple(detail), "daily": tuple(daily),
             "apps": data.get("apps") if isinstance(data.get("apps"), dict) else {}}
    _cache[str(p)] = (stamp, store)
    if len(_cache) > 4:
        _cache.pop(next(iter(_cache)))
    return store


def _group(groups, app, model):
    g = groups.get((app, model))
    if g is None:
        g = groups[(app, model)] = {
            "app": app, "model": model, "requests": 0,
            **dict.fromkeys(TOKEN_KEYS[1:], 0),
            "peak": peak.bucket(), "offpeak": peak.bucket(),
            "detail": False, "daily": False,
        }
    return g


def _period(store, start, end, zone):
    totals = dict.fromkeys(TOKEN_KEYS, 0)
    groups = {}
    boundary_days = set()
    for app, model, t, fresh, output, cache_read, cache_write in store["detail"]:
        if (start is not None and t < start) or t > end:
            continue
        values = {"fresh_input": fresh, "output": output, "reasoning": 0,
                  "cache_read": cache_read, "cache_write": cache_write}
        g = _group(groups, app, model)
        g["detail"] = True
        g["requests"] += 1
        for name, value in values.items():
            g[name] += value
            totals[name] += value
        totals["requests"] += 1
        side = "offpeak" if peak.is_offpeak(t) else "peak"
        peak.add(g[side], values)
    for app, model, date, requests, fresh, output, cache_read, cache_write in store["daily"]:
        t = int(datetime.combine(datetime.fromisoformat(date).date(), datetime_time(), zone).timestamp())
        if start is not None and t < start and date == datetime.fromtimestamp(start, zone).date().isoformat():
            boundary_days.add(date)
        if (start is not None and t < start) or t > end:
            continue
        values = {"fresh_input": fresh, "output": output, "reasoning": 0,
                  "cache_read": cache_read, "cache_write": cache_write}
        g = _group(groups, app, model)
        g["daily"] = True
        g["requests"] += requests
        for name, value in values.items():
            g[name] += value
            totals[name] += value
        totals["requests"] += requests
        unsplit = g.setdefault("unsplit", peak.bucket())
        unsplit["requests"] += requests
        for name, n in values.items():
            unsplit[name] += n
        unsplit["total_tokens"] = peak.total(unsplit)
    out_groups = []
    mixed = []
    for (app, model), g in sorted(groups.items()):
        if g["daily"] and g["detail"]:
            mixed.append(model)
        if not g["detail"]:
            g.pop("peak")
            g.pop("offpeak")
        else:
            g["peak"]["total_tokens"] = peak.total(g["peak"])
            g["offpeak"]["total_tokens"] = peak.total(g["offpeak"])
        g.pop("detail")
        g.pop("daily")
        g["total_tokens"] = sum(g[name] for name in TOKEN_KEYS[1:])
        out_groups.append(g)
    totals["total_tokens"] = sum(totals[name] for name in TOKEN_KEYS[1:])
    totals["peak"] = {**peak.bucket(), "total_tokens": 0}
    totals["offpeak"] = {**peak.bucket(), "total_tokens": 0}
    totals["unsplit"] = {**peak.bucket(), "total_tokens": 0}
    for g in out_groups:
        for side in ("peak", "offpeak", "unsplit"):
            for name, value in g.get(side, {}).items():
                totals[side][name] += value
    denominator = totals["fresh_input"] + totals["cache_read"] + totals["cache_write"]
    totals["cache_hit_rate"] = totals["cache_read"] / denominator if denominator else None
    return {"start": timestamp(start) if start is not None else None, "end": timestamp(end),
            "totals": totals, "groups": out_groups, "boundary_days_omitted": sorted(boundary_days),
            "period_status": "partial" if boundary_days else "complete", "mixed_split_models": sorted(set(mixed))}


def _metric_value(store, now, zone):
    periods = {p: _period(store, *period_bounds(now, p, zone), zone)
               for p in ("today", "7d", "30d", "all")}
    for p in periods.values():
        p["timezone"] = str(zone)
    buckets = {}
    for row in store["detail"]:
        t = row[2]
        if t > now:
            continue
        day = datetime.fromtimestamp(t, zone).date().isoformat()
        buckets[day] = buckets.get(day, 0) + row[3] + row[4] + row[5] + row[6]
    end_date = datetime.fromtimestamp(now, zone).date().isoformat()
    for app, model, date, requests, fresh, output, cache_read, cache_write in store["daily"]:
        if date > end_date:
            continue
        buckets[date] = buckets.get(date, 0) + fresh + output + cache_read + cache_write
    return {"peak_split": "request_timestamp_and_daily_rollups",
            "periods": periods,
            "daily_buckets": [{"date": d, "tokens": n} for d, n in sorted(buckets.items())],
            "coverage": "imported_history_store",
            "dedup_rule": "one_time_import_before_local_ledgers",
            "history": {"imported_at": timestamp(store["imported_at"]) if isinstance(store["imported_at"], (int, float)) else None,
                        "detail_records": len(store["detail"]), "daily_records": len(store["daily"])}}


def collect_imported_history(store_path, now, zone=ZoneInfo("Asia/Shanghai")):
    store = load_store(store_path)
    out = source("imported_history", "local_imported_history", now)
    out["metrics"]["tokens"] = metric(_metric_value(store, now, zone))
    out["diagnostics"].update({"store": str(Path(store_path).expanduser()),
                               "detail_records": len(store["detail"]),
                               "daily_records": len(store["daily"]),
                               "apps": sorted(store["apps"])})
    return out
