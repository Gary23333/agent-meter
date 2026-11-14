"""Windows 预测页的数据投影：复用上游算法，只传递展示所需的公开字段。"""

import math
import time

from agent_meter.reset_forecast import combine, pooled_value


NAMES = {"willreset": "WillReset", "codex_reset": "Tibo Radar", "codexreset_org": "Reset Monitor"}
KINDS = {"reset", "reset_preview", "preview", "banked", "credits", "limits", "boost", "milestone"}


def _number(value, maximum=100):
    return value if (not isinstance(value, bool) and isinstance(value, (int, float))
                     and math.isfinite(value) and 0 <= value <= maximum) else None


def _epoch(value):
    value = _number(value.get("epoch_seconds") if isinstance(value, dict) else None, 253402300799)
    return int(value) if value is not None else None


def _sources(value):
    return list(dict.fromkeys(NAMES[item] for item in value if isinstance(item, str) and item in NAMES)) if isinstance(value, list) else []


def _rows(value):
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def forecast_summary(source, now=None):
    """不把未给出时间的文字承诺变成倒计时，也不转发第三方自由文本。"""
    now = time.time() if now is None else now
    metrics = source.get("metrics", {})
    value = metrics.get("reset_forecast", {}).get("value")
    if not isinstance(value, dict):
        return {"status": "unavailable", "reason": "reset_forecast_sources_unavailable", "sources": []}
    rows, ensemble_rows, seen = [], [], set()
    for item in _rows(value.get("sources")):
        key = item.get("source")
        if not isinstance(key, str) or key not in NAMES or key in seen:
            continue
        seen.add(key)
        state = item.get("status") if item.get("status") in ("available", "stale") else "unavailable"
        row = {"name": NAMES[key], "status": state}
        normalized = {"source": key, "status": state}
        updated = _epoch(item.get("updated_at"))
        if updated is not None:
            row["updated_at"] = updated
            normalized["updated_at"] = {"epoch_seconds": updated}
        for horizon in ("24h", "48h"):
            number, basis = pooled_value(item, horizon)
            number = _number(number)
            if state in ("available", "stale") and number is not None:
                row[horizon], row[horizon + "_basis"] = number, basis
                normalized[("headline_" if basis == "published_answer" else "raw_") + horizon] = number
        reported = item.get("self_reported")
        reported = reported if isinstance(reported, dict) else {}
        calibration = reported.get("calibration") or reported.get("backtest") or {}
        calibration = calibration.get("24h", {}) if isinstance(calibration, dict) else {}
        calibration = calibration if isinstance(calibration, dict) else {}
        normalized["self_reported"] = {
            "confidence": reported.get("confidence") if reported.get("confidence") in ("high", "medium", "low") else None,
            "calibration": {"24h": {"state": calibration.get("state") if calibration.get("state") in ("calibrated", "experimental") else None}}}
        cadence = item.get("cadence")
        sample = cadence.get("interval_sample") if isinstance(cadence, dict) else None
        normalized["cadence"] = {"interval_sample": sample if type(sample) is int and sample >= 0 else None}
        rows.append(row)
        ensemble_rows.append(normalized)
    # 使用相同的加权中位数；超过 48 小时的站点不参与合并，缺失的时段保持缺失。
    pooled = combine(ensemble_rows, now)
    horizons = {}
    for horizon, item in pooled["horizons"].items():
        horizons[horizon] = {key: item[key] for key in ("min", "max", "weighted_median", "n", "agreement")}
        horizons[horizon]["has_model"] = any(row["basis"] == "cadence_model_fallback" for row in item["values"])

    countdown = metrics.get("known_reset_countdown", {}).get("value")
    targets = []
    for item in _rows(countdown.get("targets") if isinstance(countdown, dict) else None):
        kind, close, opened = item.get("kind"), _epoch(item.get("close_at")), _epoch(item.get("open_at"))
        names = _sources(item.get("sources"))
        if (kind not in ("promised_reset", "typical_window") or item.get("precision") != "window"
                or close is None or not names or (opened is not None and opened > close)):
            continue
        targets.append({"kind": kind, "open_at": opened, "close_at": close, "sources": names})
    targets.sort(key=lambda row: (row["kind"] != "promised_reset", row["close_at"]))

    history = []
    for item in _rows(value.get("history_events")):
        announced, effective = _epoch(item.get("announced_at")), _epoch(item.get("effective_at"))
        names = _sources(item.get("sources"))
        if announced is None or not names:
            continue
        history.append({"kind": item.get("kind") if isinstance(item.get("kind"), str) and item.get("kind") in KINDS else "event",
                        "announced_at": announced, "effective_at": effective,
                        "confirmed": item.get("confirmed") is True, "sources": names})
    history.sort(key=lambda row: row["announced_at"], reverse=True)
    return {"status": source.get("status") if source.get("status") in ("available", "partial", "stale") else "unavailable",
            "cache_state": value.get("cache_state") if value.get("cache_state") in ("fresh", "stale", "served_from_cache") else None,
            "sources": rows, "ensemble": horizons, "targets": targets[:6], "history": history[:40]}
