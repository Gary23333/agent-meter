"""Daily / weekly budgets and abnormal-consumption alerts (E1).

Scope: 本机 API 等价估算 (the local price table's cost metrics), never a real
bill. Account balances, credits and provider-billed amounts (basis other than
local_price_table) never enter a budget. Windows are Beijing calendar windows:
today = Asia/Shanghai natural day, this week = Monday-start natural week.

The snapshot only carries rolling 7d/30d cost windows, so natural-week totals
cannot be read from it directly. This module keeps a small per-day ledger
(<runtime>/budget-history.json): every computation records today's estimated
CNY total; once the day passes, its last recorded value is final. Days without
a record stay missing (unknown ≠ 0) and the weekly section says so.

Alert dedup: events carry stable ids keyed by the calendar day (or the week's
Monday), so a collection recovery that back-fills tokens later never produces
a second event for the same day/week. Amounts are Decimal fixed-point strings;
USD cost metrics convert at the project's fixed FX_FALLBACK (7.25), any other
unit is left unknown instead of mixed in.
"""
import copy
import json
import threading
from datetime import datetime, time as datetime_time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .model import DISPLAY_ZONE, timestamp
from .prices import FX_FALLBACK

SCHEMA = 1
CONFIG_NAME = "budget.json"
HISTORY_NAME = "budget-history.json"
DEFAULT_MULTIPLIER = "2.0"
MAX_BUDGET = Decimal("1000000000")
MAX_MULTIPLIER = Decimal("100")
HISTORY_DAYS = 40
TOP_COUNT = 5
MIN_ANOMALY_HOURS = Decimal(2)
_Q = Decimal("0.000001")
_USABLE = {"available", "partial", "stale"}
_CONFIG_KEYS = {"daily_cny", "weekly_cny", "anomaly_multiplier"}
# Serializes history read-modify-write across concurrent GET /v1/budget calls.
_history_lock = threading.Lock()


def default_config():
    return {"schema": SCHEMA, "daily_cny": None, "weekly_cny": None,
            "anomaly_multiplier": DEFAULT_MULTIPLIER}


def _fmt(value):
    return format(value.quantize(_Q), "f")


def _decimal(value):
    """Parse a Decimal string/number; None for anything unusable (never 0)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() else None


def _clean_amount(value):
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("invalid_budget")
    d = _decimal(value)
    if d is None or d < 0 or d > MAX_BUDGET:
        raise ValueError("invalid_budget")
    return format(d, "f")


def clean_config(body, current=None):
    """Merge a PUT body over the current config; reject anything invalid."""
    if not isinstance(body, dict) or set(body) - _CONFIG_KEYS:
        raise ValueError("invalid_budget")
    out = dict(current or default_config())
    for key in ("daily_cny", "weekly_cny"):
        if key in body:
            out[key] = _clean_amount(body[key])
    if "anomaly_multiplier" in body:
        raw = body["anomaly_multiplier"]
        m = _clean_amount(raw)
        if m is None or not Decimal(0) < Decimal(m) <= MAX_MULTIPLIER:
            raise ValueError("invalid_budget")
        out["anomaly_multiplier"] = m
    out["schema"] = SCHEMA
    return out


def load_budget(runtime_dir):
    try:
        data = json.loads((Path(runtime_dir) / CONFIG_NAME).read_text())
        if not isinstance(data, dict) or data.get("schema") != SCHEMA:
            raise ValueError()
        return clean_config({k: v for k, v in data.items() if k != "schema"})
    except (OSError, ValueError, json.JSONDecodeError):
        return default_config()


def save_budget(runtime_dir, body):
    from .collector import atomic_json
    config = clean_config(body, load_budget(runtime_dir))
    atomic_json(Path(runtime_dir) / CONFIG_NAME, config)
    return config


def load_history(runtime_dir):
    """{date: {spent_cny, apps, models, partial}} — invalid rows are dropped."""
    try:
        data = json.loads((Path(runtime_dir) / HISTORY_NAME).read_text())
        days = data.get("days") if isinstance(data, dict) and data.get("schema") == SCHEMA else None
        if not isinstance(days, dict):
            return {}
        clean = {}
        for day, entry in days.items():
            try:
                datetime.strptime(day, "%Y-%m-%d")
            except (TypeError, ValueError):
                continue
            if isinstance(entry, dict) and _decimal(entry.get("spent_cny")) is not None:
                clean[day] = entry
        return clean
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def save_history(runtime_dir, days):
    from .collector import atomic_json
    kept = {d: days[d] for d in sorted(days)[-HISTORY_DAYS:]}
    atomic_json(Path(runtime_dir) / HISTORY_NAME, {"schema": SCHEMA, "days": kept})


def _period_amount(period):
    """One cost period's amount as Decimal; None means unknown, never zero."""
    if not isinstance(period, dict):
        return None
    if "amount" in period:
        return _decimal(period["amount"])
    # Older/alternate shapes only carry the peak/off-peak split.
    peak, off = _decimal(period.get("peak_amount")), _decimal(period.get("offpeak_amount"))
    if peak is None and off is None:
        return None
    return (peak or Decimal(0)) + (off or Decimal(0))


def _to_cny(amount, unit):
    if amount is None:
        return None
    if unit == "CNY":
        return amount
    if unit == "USD":
        return amount * FX_FALLBACK
    return None   # any other unit stays unknown; currencies are never mixed


def _top(mapping):
    rows = sorted(mapping.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_COUNT]
    return [{"name": name, "amount_cny": _fmt(amount)} for name, amount in rows if amount > 0]


def _collect_period(snapshot, period_key):
    """Sum one cost period across sources into CNY, with app/model breakdown.

    spent=None when nothing is known (unknown ≠ 0). A readable ledger with a
    measured zero yields 0. Sources with local token usage but no priced
    amount make the sum a flagged lower bound, never a silent zero.
    """
    total = None
    apps, models = {}, {}
    unknown = []
    partial = False
    readable = 0
    for src in snapshot.get("sources", []):
        sid = str(src.get("id", ""))
        if sid.startswith("codexbar:"):
            continue   # CodexBar keeps its own estimate basis
        metrics = src.get("metrics") or {}
        tokens = metrics.get("tokens") or {}
        tval = tokens.get("value") if tokens.get("status") in _USABLE else None
        used = None
        if isinstance(tval, dict) and isinstance(tval.get("periods"), dict):
            period = tval["periods"].get(period_key)
            if isinstance(period, dict):
                readable += 1
                n = (period.get("totals") or {}).get("total_tokens")
                used = n if isinstance(n, (int, float)) and not isinstance(n, bool) else None
        cost = metrics.get("cost") or {}
        cval = cost.get("value")
        contributed = False
        if cost.get("status") in _USABLE and isinstance(cval, dict) \
                and cval.get("basis") == "local_price_table":
            cp = (cval.get("periods") or {}).get(period_key)
            amount = _to_cny(_period_amount(cp), cval.get("unit"))
            if amount is not None:
                total = (total or Decimal(0)) + amount
                contributed = True
                if cost.get("status") != "available" or (isinstance(cp, dict) and cp.get("unmatched_models")):
                    partial = True
                factor = FX_FALLBACK if cval.get("unit") == "USD" else Decimal(1)
                per_app = cp.get("app_models") if isinstance(cp, dict) else None
                pairs = []
                if isinstance(per_app, dict) and per_app:
                    for app, mmap in per_app.items():
                        for model, raw in (mmap if isinstance(mmap, dict) else {}).items():
                            pairs.append((app or sid, model, raw))
                else:
                    mmap = cp.get("models") if isinstance(cp, dict) else None
                    for model, raw in (mmap if isinstance(mmap, dict) else {}).items():
                        pairs.append((sid, model, raw))
                for app, model, raw in pairs:
                    v = _decimal(raw)
                    if v is None:
                        continue
                    v *= factor
                    apps[app] = apps.get(app, Decimal(0)) + v
                    models[model] = models.get(model, Decimal(0)) + v
        if not contributed and used is not None and used > 0:
            unknown.append(sid)
            partial = True
    if total is None and not unknown and readable:
        total = Decimal(0)   # every readable ledger measured zero this period
    return {"spent": total, "apps": apps, "models": models,
            "unknown_sources": sorted(unknown), "partial": partial}


def _section(budget, spent, apps, models, partial, unknown):
    exceeded = budget is not None and spent is not None and spent > budget
    remaining = budget - spent if budget is not None and spent is not None else None
    return {"budget_cny": _fmt(budget) if budget is not None else None,
            "spent_cny": _fmt(spent) if spent is not None else None,
            "remaining_cny": _fmt(remaining) if remaining is not None else None,
            "exceeded": exceeded, "partial": partial, "unknown_sources": unknown,
            "top_apps": _top(apps), "top_models": _top(models)}


def compute_budget(snapshot, config, now, history=None):
    """Budget view for one snapshot. Returns (payload, today_entry).

    today_entry is the row to persist into the day ledger (None when today's
    spend is unknown — a known earlier value is never overwritten by null).
    """
    history = history or {}
    local = datetime.fromtimestamp(now, DISPLAY_ZONE)
    today = local.date()
    midnight = datetime.combine(today, datetime_time(), DISPLAY_ZONE)
    week_start = today - timedelta(days=today.weekday())
    today_key, week_key = today.isoformat(), week_start.isoformat()

    agg = _collect_period(snapshot, "today")
    spent = agg["spent"]
    entry = None
    if spent is not None:
        entry = {"spent_cny": _fmt(spent),
                 "apps": {a: _fmt(v) for a, v in agg["apps"].items()},
                 "models": {m: _fmt(v) for m, v in agg["models"].items()},
                 "partial": agg["partial"]}
    daily_budget = _decimal(config.get("daily_cny"))
    daily = _section(daily_budget, spent, agg["apps"], agg["models"],
                     agg["partial"], agg["unknown_sources"])

    # Natural week: recorded days Mon..yesterday plus today's fresh estimate.
    week_total = None
    week_apps, week_models = {}, {}
    missing = []
    week_partial = False
    for i in range((today - week_start).days + 1):
        key = (week_start + timedelta(days=i)).isoformat()
        row = entry if key == today_key else history.get(key)
        if key == today_key and row is None:
            row = history.get(key)          # last known today value (stale)
            if row is not None:
                week_partial = True
        value = _decimal((row or {}).get("spent_cny"))
        if value is None:
            missing.append(key)
            week_partial = True
            continue
        week_total = (week_total or Decimal(0)) + value
        week_partial = week_partial or bool(row.get("partial"))
        for field, target in (("apps", week_apps), ("models", week_models)):
            for name, raw in (row.get(field) or {}).items():
                v = _decimal(raw)
                if v is not None:
                    target[name] = target.get(name, Decimal(0)) + v
    weekly_budget = _decimal(config.get("weekly_cny"))
    weekly = _section(weekly_budget, week_total, week_apps, week_models, week_partial, [])
    weekly["week_start"] = week_key
    weekly["days_missing"] = missing
    weekly["complete"] = not missing and not week_partial

    # Anomaly: today's hourly rate against the recent daily average.
    multiplier = _decimal(config.get("anomaly_multiplier")) or Decimal(DEFAULT_MULTIPLIER)
    hours = (Decimal(str(now)) - Decimal(str(midnight.timestamp()))) / Decimal(3600)
    anomaly = {"triggered": False, "reason": None, "multiplier": _fmt(multiplier),
               "hours_elapsed": format(hours.quantize(Decimal("0.01")), "f"),
               "rate_cny_per_hour": None, "baseline_daily_cny": None, "baseline_basis": None}
    baseline = None
    past = [history.get((today - timedelta(days=i)).isoformat()) for i in range(1, 8)]
    known = [_decimal((row or {}).get("spent_cny")) for row in past]
    known = [v for v in known if v is not None]
    if len(known) == 7:
        baseline = sum(known) / Decimal(7)
        anomaly["baseline_basis"] = "daily_history_7d"
    else:
        # No complete per-day history: approximate from the rolling 30d cost
        # total and label the basis, as the estimate contract requires.
        rolling = _collect_period(snapshot, "30d")["spent"]
        if rolling is not None and rolling > 0:
            baseline = rolling / Decimal(30)
            anomaly["baseline_basis"] = "rolling_30d_average"
    if baseline is not None:
        anomaly["baseline_daily_cny"] = _fmt(baseline)
    if spent is None:
        anomaly["reason"] = "no_cost_data"
    elif hours < MIN_ANOMALY_HOURS:
        anomaly["reason"] = "too_early"
    elif baseline is None or baseline <= 0:
        anomaly["reason"] = "no_baseline"
    else:
        rate = spent / hours
        anomaly["rate_cny_per_hour"] = _fmt(rate)
        if spent > 0 and rate > baseline / Decimal(24) * multiplier:
            anomaly["triggered"] = True
        else:
            anomaly["reason"] = "below_threshold"

    events = []
    if daily["exceeded"]:
        events.append({"id": "budget_daily_exceeded:" + today_key, "kind": "daily_exceeded",
                       "date": today_key, "budget_cny": daily["budget_cny"],
                       "spent_cny": daily["spent_cny"],
                       "excess_cny": _fmt(spent - daily_budget),
                       "top_apps": daily["top_apps"], "top_models": daily["top_models"]})
    if weekly["exceeded"]:
        events.append({"id": "budget_weekly_exceeded:" + week_key, "kind": "weekly_exceeded",
                       "date": week_key, "budget_cny": weekly["budget_cny"],
                       "spent_cny": weekly["spent_cny"],
                       "excess_cny": _fmt(week_total - weekly_budget),
                       "top_apps": weekly["top_apps"], "top_models": weekly["top_models"]})
    if anomaly["triggered"]:
        events.append({"id": "budget_anomaly:" + today_key, "kind": "anomaly", "date": today_key,
                       "spent_cny": daily["spent_cny"],
                       "rate_cny_per_hour": anomaly["rate_cny_per_hour"],
                       "baseline_daily_cny": anomaly["baseline_daily_cny"],
                       "baseline_basis": anomaly["baseline_basis"],
                       "multiplier": anomaly["multiplier"],
                       "top_apps": daily["top_apps"], "top_models": daily["top_models"]})

    payload = {"status": "ok", "schema": SCHEMA, "config": dict(config),
               "basis": "local_api_equivalent_estimate", "currency": "CNY",
               "fx_rate": format(FX_FALLBACK, "f"), "timezone": str(DISPLAY_ZONE),
               "generated_at": timestamp(now), "date": today_key, "week_start": week_key,
               "daily": daily, "weekly": weekly, "anomaly": anomaly, "events": events}
    return payload, entry


def budget_state(service, now=None):
    """GET /v1/budget: config + current snapshot, without triggering collection.

    Also advances the day ledger, so natural-week totals accumulate even though
    the snapshot itself only exposes rolling windows.
    """
    with service.lock:
        runtime = service.config["runtime_dir"]
        snapshot = copy.deepcopy(service.snapshot)
    config = load_budget(runtime)
    if snapshot is None:
        return {"status": "not_collected", "schema": SCHEMA, "config": config,
                "basis": "local_api_equivalent_estimate", "currency": "CNY"}
    current = service.clock() if now is None else now
    with _history_lock:
        history = load_history(runtime)
        payload, entry = compute_budget(snapshot, config, current, history)
        if entry is not None and history.get(payload["date"]) != entry:
            history[payload["date"]] = entry
            save_history(runtime, history)
    return payload