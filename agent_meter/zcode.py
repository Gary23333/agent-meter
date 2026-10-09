"""ZCode / 智谱 GLM Coding Plan quota, read either with the query credential
the BigModel console page itself sends (captured in the app's login window)
or with a Coding Plan API key pasted in the app. Both live in the Keychain
and reach the backend only through local API memory.

Contract follows token-monitor c62544e (zai/limits.js, MIT) and the earlier
read-only probe in docs/research: GET /api/monitor/usage/quota/limit on the
China-region host answers data.limits[] with CREDIT_LIMIT/TOKENS_LIMIT
windows (unit/number) and a monthly MCP TIME_LIMIT. Values are kept as the
service returns them; nothing is derived for windows it does not describe.
Reset cards need ZCode's own desktop login and are not read on this route.
"""
from .model import SourceError, account_key, metric, number, source, timestamp
from .transport import get_json

QUOTA_PATH = "/api/monitor/usage/quota/limit"
DEFAULT_ORIGIN = "https://open.bigmodel.cn"
# A captured console token is only ever replayed to the host it was sent to.
ORIGINS = {DEFAULT_ORIGIN, "https://bigmodel.cn"}
# unit codes in the quota response: 5 minute, 3 hour, 1 day, 6 week.
UNIT_MINUTES = {5: 1, 3: 60, 1: 1440, 6: 10080}
LIMIT_UNITS = {"CREDIT_LIMIT": "zcode_credits", "TOKENS_LIMIT": "tokens", "TIME_LIMIT": "calls"}


def _instant(raw):
    if raw in (None, ""):
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return timestamp(raw, unit="milliseconds" if raw > 1e11 else "seconds")
    return timestamp(raw)


def _optional(value):
    return None if value is None else number(value)


def normalize_quota(payload):
    if not isinstance(payload, dict) or payload.get("success") is False or payload.get("code") not in (None, 0, 200):
        raise SourceError("not_authenticated" if isinstance(payload, dict) and payload.get("code") in (401, 1000, 1001, 1002)
                          else "zcode_quota_api_error")
    data = payload.get("data")
    limits = data.get("limits") if isinstance(data, dict) else None
    if not isinstance(limits, list):
        raise SourceError("unsupported_zcode_quota_contract")
    rows = []
    for item in limits:
        if not isinstance(item, dict):
            raise SourceError("invalid_zcode_limit")
        kind = item.get("type")
        if kind not in LIMIT_UNITS:
            continue
        total = _optional(item.get("usage"))
        used = _optional(item.get("currentValue", item.get("current_value")))
        remaining = _optional(item.get("remaining"))
        percent = _optional(item.get("percentage"))
        if total and remaining is not None:
            remaining_percent = min(100.0, remaining / total * 100)
        elif total and used is not None:
            remaining_percent = max(0.0, 100 - used / total * 100)
        elif percent is not None:
            remaining_percent = 100 - min(100.0, percent)
        else:
            continue
        if used is None and total is not None and remaining is not None:
            used = max(0, total - remaining)
        row = {"bucket": "mcp" if kind == "TIME_LIMIT" else "quota", "limit_type": kind,
               "used_percent": 100 - remaining_percent, "remaining_percent": remaining_percent,
               "used": used, "limit": total, "remaining": remaining, "provider_percentage": percent,
               "unit": LIMIT_UNITS[kind], "resets_at": _instant(item.get("nextResetTime", item.get("next_reset_time")))}
        minutes, count = UNIT_MINUTES.get(item.get("unit")), item.get("number")
        # The MCP bucket is monthly but encoded as a 1-minute marker; leave it windowless.
        if kind != "TIME_LIMIT" and minutes and isinstance(count, int) and not isinstance(count, bool) and count > 0:
            row["window_minutes"] = minutes * count
        rows.append(row)
    plan = data.get("level") if isinstance(data.get("level"), str) else None
    return rows, plan


def collect_zcode(session, now, timeout=15):
    session = session or {}
    token, key = session.get("token"), session.get("api_key")
    if not token and not key:
        raise SourceError("zcode_credential_not_connected")
    origin = session.get("origin") or DEFAULT_ORIGIN
    if origin not in ORIGINS:
        raise SourceError("invalid_endpoint")
    headers = {"Accept-Language": "zh-CN,zh"}
    if token:
        # Replayed exactly as the console sent it (with or without "Bearer").
        headers["Authorization"] = token
        headers["Origin"], headers["Referer"] = "https://bigmodel.cn", "https://bigmodel.cn/coding-plan/personal/usage"
        headers["User-Agent"] = session.get("user_agent") or ""
        payload = get_json(origin + QUOTA_PATH, timeout=timeout, headers={k: v for k, v in headers.items() if v})
    else:
        payload = get_json(DEFAULT_ORIGIN + QUOTA_PATH, key, timeout, headers=headers)
    rows, plan = normalize_quota(payload)
    out = source("zcode", "account", now)
    out["account_key"] = account_key("zcode", key) if key else None
    out["metrics"]["quota"] = metric(rows or None)
    resets = [{"bucket": "window_%d" % r["window_minutes"], "resets_at": r["resets_at"]}
              for r in rows if r.get("window_minutes") and r["resets_at"]]
    out["metrics"]["reset_time"] = metric(resets or None)
    out["metrics"]["reset_cards"] = metric(status="not_connected", reason="zcode_cards_need_desktop_login")
    out["subscription"] = {"plan": "GLM Coding " + plan.capitalize() if plan else "GLM Coding Plan"}
    out["diagnostics"]["transport"] = "bigmodel_console_session" if token else "bigmodel_coding_plan_api_key"
    return out
