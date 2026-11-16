"""Windows 预算适配：仅使用本机 API 等价估算，默认关闭且不上传。"""
import json
import math
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from agent_meter.budget import _collect_period, clean_config, compute_budget, load_history, save_history
from agent_meter.model import DISPLAY_ZONE

CONFIG_NAME = "budget-windows.json"
HISTORY_NAME = "budget-history.json"


def load_settings(directory):
    """无设置时关闭；已有设置损坏时拒绝计算，不覆盖用户文件。"""
    path = Path(directory) / CONFIG_NAME
    try:
        if path.stat().st_size > 16384:
            raise ValueError("invalid_config")
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict) or set(data) != {"schema", "enabled", "alerts_enabled", "daily_cny", "weekly_cny", "anomaly_multiplier"}:
            raise ValueError("invalid_config")
        if data["schema"] != 1 or type(data["schema"]) is not int or type(data["enabled"]) is not bool or type(data["alerts_enabled"]) is not bool:
            raise ValueError("invalid_config")
        config = clean_config({key: data[key] for key in ("daily_cny", "weekly_cny", "anomaly_multiplier")})
        return {"status": "enabled" if data["enabled"] else "disabled", "alerts_enabled": data["alerts_enabled"], "config": config}
    except FileNotFoundError:
        return {"status": "disabled", "alerts_enabled": False}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {"status": "invalid", "alerts_enabled": False}


def _valid_history(path):
    """损坏的预算历史不能静默当作空文件并覆盖。"""
    try:
        if path.stat().st_size > 1024 * 1024:
            return False
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict) or data.get("schema") != 1 or not isinstance(data.get("days"), dict):
            return False
        for day, row in data["days"].items():
            if not isinstance(day, str) or datetime.strptime(day, "%Y-%m-%d").strftime("%Y-%m-%d") != day or not isinstance(row, dict):
                return False
            amount = Decimal(str(row.get("spent_cny")))
            if not amount.is_finite() or amount < 0 or not isinstance(row.get("apps", {}), dict) or not isinstance(row.get("models", {}), dict) or type(row.get("partial", False)) is not bool:
                return False
            for amounts in (row.get("apps", {}), row.get("models", {})):
                for name, raw in amounts.items():
                    value = Decimal(str(raw))
                    if not isinstance(name, str) or len(name) > 120 or not value.is_finite() or value < 0:
                        return False
        return True
    except FileNotFoundError:
        return True
    except (OSError, ValueError, TypeError, InvalidOperation, json.JSONDecodeError):
        return False


def _snapshot(compact):
    """复用已校验的周期估算，不将账户余额或本机积分混入预算。"""
    sources, incomplete = [], False
    history = compact.get("history")
    if not isinstance(history, dict):
        return {"sources": []}, True
    for name, item in history.items():
        if not isinstance(item, dict):
            incomplete = True
            continue
        state, reason = item.get("status"), item.get("reason") if isinstance(item.get("reason"), str) else ""
        if state == "error" or state == "partial" or state == "unavailable" and not reason.endswith("_not_found"):
            incomplete = True
        if state not in ("available", "partial"):
            continue
        value = item.get("value") if isinstance(item.get("value"), dict) else {}
        periods = value.get("periods") if isinstance(value.get("periods"), dict) else {}
        today_period = periods.get("today") if isinstance(periods.get("today"), dict) else {}
        today = today_period.get("totals") if isinstance(today_period.get("totals"), dict) else {}
        total = today.get("total_tokens")
        if type(total) not in (int, float) or not math.isfinite(total) or total < 0:
            incomplete = True
        estimates = item.get("estimates") if isinstance(item.get("estimates"), dict) else {}
        costs = {}
        for period in ("today", "30d"):
            estimate = estimates.get(period) or (item.get("estimate") if period == "today" else None)
            if not isinstance(estimate, dict):
                continue
            try:
                amount = Decimal(str(estimate.get("amount_usd")))
                if not amount.is_finite() or amount < 0 or amount > Decimal("1000000000000000"):
                    continue
            except (InvalidOperation, ValueError, TypeError):
                continue
            costs[period] = {"amount": str(amount), "unmatched_models": ["partial"] if estimate.get("partial") is True else []}
        cost = {"status": "partial" if state == "partial" else "available", "value": {
            "unit": "USD", "basis": "local_price_table", "periods": costs}}
        sources.append({"id": name, "metrics": {"tokens": {"status": state, "value": {"periods": periods}}, "cost": cost}})
    return {"sources": sources}, incomplete


def budget_from_compact(compact, directory):
    """以北京时间自然日和自然周计算；只在用户启用后写入每日估算。"""
    settings = load_settings(directory)
    if settings["status"] != "enabled":
        return {"status": settings["status"]}
    path = Path(directory) / HISTORY_NAME
    if not _valid_history(path):
        return {"status": "error", "reason": "budget_history_invalid"}
    snapshot, incomplete = _snapshot(compact)
    now = compact.get("observed_at")
    if type(now) not in (int, float) or not math.isfinite(now) or not 0 <= now <= 253402300799:
        return {"status": "error", "reason": "budget_timestamp_invalid"}
    history = load_history(directory)
    payload, entry = compute_budget(snapshot, settings["config"], now, history)
    if incomplete:
        payload["daily"]["partial"] = True
        payload["weekly"]["partial"] = True
        payload["weekly"]["complete"] = False
        if entry is not None:
            entry["partial"] = True
    baseline_partial = False
    if payload["anomaly"]["baseline_basis"] == "daily_history_7d":
        today = datetime.fromtimestamp(now, DISPLAY_ZONE).date()
        baseline_partial = any(history.get((today - timedelta(days=i)).isoformat(), {}).get("partial", True) for i in range(1, 8))
    elif payload["anomaly"]["baseline_basis"] == "rolling_30d_average":
        baseline = _collect_period(snapshot, "30d")
        baseline_partial = baseline["partial"] or bool(baseline["unknown_sources"])
        for source in snapshot["sources"]:
            periods = source["metrics"]["tokens"]["value"]["periods"]
            if not isinstance(periods.get("30d"), dict) or not isinstance(periods["30d"].get("totals"), dict) or "total_tokens" not in periods["30d"]["totals"]:
                baseline_partial = True
    if incomplete or payload["daily"]["partial"] or baseline_partial:
        payload["anomaly"]["triggered"] = False
        payload["anomaly"]["reason"] = "incomplete_data"
        payload["events"] = [event for event in payload["events"] if event.get("kind") != "anomaly"]
    payload["alerts_enabled"] = settings["alerts_enabled"]
    payload["fx_source"] = "fixed_fallback"
    # 用户在扫描期间修改预算时，丢弃旧结果并等待下一轮刷新。
    if load_settings(directory) != settings:
        return {"status": "loading"}
    if entry is not None and history.get(payload["date"]) != entry:
        history[payload["date"]] = entry
        save_history(directory, history)
    return payload
