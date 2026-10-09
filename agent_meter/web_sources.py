"""Account usage read with a website login supplied by the menu bar app.

Sessions arrive over the authenticated local API (PUT /v1/web-sessions),
live only in memory and never enter snapshots, logs or files. Each provider
has one fixed origin and query path; nothing here buys, redeems or writes.
Contracts follow CodexBar b0aa7fe (qoder.js, workbuddy.ts) and token-monitor
c62544e (trae/limits.js), all MIT.
"""
from .model import SourceError, account_key, decimal_string, metric, number, source, timestamp
from .transport import get_json, post_json

QODER_ORIGIN = "https://qoder.com.cn"
WORKBUDDY_ORIGIN = "https://www.workbuddy.cn"
TRAE_URL = "https://api.trae.cn/trae/api/v2/pay/ide_user_ent_usage"
SAFARI_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/18.0 Safari/605.1.15")

# Which fields each provider's session may carry.
SESSION_FIELDS = {
    # API keys entered in the app use the same in-memory channel.
    "deepseek_api": {"api_key"},
    "minimax_code": {"api_key"},
    "zcode": {"api_key", "token", "origin", "user_agent"},
    "volcengine": {"access_key_id", "secret_access_key"},
    "mimo": {"cookie", "user_agent"},
    "claude": {"cookie", "user_agent"},
    "qoder": {"cookie", "user_agent"},
    "workbuddy": {"cookie", "user_agent"},
    "trae_cn": {"token", "device_id", "user_agent"},
}
MAX_FIELD = 16 * 1024
MAX_ACCOUNTS = 5
MAX_LABEL = 40


def _clean_session(provider, session):
    if not isinstance(session, dict) or set(session) - SESSION_FIELDS[provider] - {"label"}:
        raise ValueError("unknown session field")
    fields = {}
    for key, value in session.items():
        if not isinstance(value, str) or not value or len(value) > MAX_FIELD or "\r" in value or "\n" in value:
            raise ValueError("invalid session value")
        if key == "label" and len(value) > MAX_LABEL:
            raise ValueError("label too long")
        fields[key] = value
    return fields


def validate_sessions(payload):
    """Returns {provider: [session, ...]} (several accounts per provider) or raises ValueError.

    A provider may map to one session object (single account), a list of up
    to MAX_ACCOUNTS sessions each with an optional display "label", or null.
    """
    if not isinstance(payload, dict):
        raise ValueError("sessions must be an object")
    clean = {}
    for provider, value in payload.items():
        if provider not in SESSION_FIELDS:
            raise ValueError("unknown provider")
        if value is None:
            continue
        sessions = value if isinstance(value, list) else [value]
        if not 0 < len(sessions) <= MAX_ACCOUNTS:
            raise ValueError("invalid account count")
        clean[provider] = [_clean_session(provider, s) for s in sessions]
    return clean


def as_account_lists(web):
    """Accepts {provider: session} or {provider: [sessions]} (both in use)."""
    return {p: (v if isinstance(v, list) else [v]) for p, v in (web or {}).items() if v}


def require(session, field):
    value = (session or {}).get(field)
    if not value:
        raise SourceError("web_session_missing")
    return value


def _quota_summary(raw):
    if not isinstance(raw, dict):
        raise SourceError("invalid_qoder_quota")
    pick = lambda camel, snake: raw.get(camel, raw.get(snake))
    used = number(pick("usedValue", "used_value"))
    total = number(pick("limitValue", "limit_value"))
    remaining = pick("remainingValue", "remaining_value")
    remaining = max(0, total - used) if remaining is None else number(remaining)
    percent = pick("usagePercentage", "usage_percentage")
    percent = number(percent) if percent is not None else (used / total * 100 if total > 0 else None)
    return used, total, remaining, percent


def normalize_qoder_web(payload, now):
    if not isinstance(payload, dict):
        raise SourceError("unsupported_qoder_web_contract")
    pick = lambda camel, snake: payload.get(camel, payload.get(snake))
    containers = [("totalQuota", pick("totalQuota", "total_quota")), ("sharedQuota", pick("sharedQuota", "shared_quota"))]
    if not isinstance(containers[0][1], dict):
        raise SourceError("unsupported_qoder_web_contract")
    reset_raw = pick("nextResetAt", "next_reset_at")
    unit = "milliseconds" if isinstance(reset_raw, (int, float)) and reset_raw > 1e10 else "seconds"
    reset = timestamp(reset_raw, unit=unit) if reset_raw not in (None, "") else None
    out = source("qoder", "account", now)
    if reset is not None and reset["epoch_seconds"] < now:
        # Live value was the cycle start (10/01 while sampled 10/09); its meaning is
        # unconfirmed, so keep it as evidence rather than presenting a past "next reset".
        out["diagnostics"]["reported_reset_at_in_past"] = reset
        reset = None
    quotas, wallets = [], []
    for name, container in containers:
        if container is None:
            continue
        if not isinstance(container, dict):
            raise SourceError("invalid_qoder_quota")
        summary = container.get("quotaSummary", container.get("quota_summary"))
        used, total, remaining, percent = _quota_summary(summary)
        if percent is not None:
            percent = min(100, max(0, percent))
            quotas.append({"bucket": name, "used_percent": percent, "remaining_percent": 100 - percent,
                           "used": used, "limit": total, "unit": "qoder_credits", "resets_at": reset})
        wallets.append({"bucket": name, "total": decimal_string(total), "used": decimal_string(used),
                        "remaining": decimal_string(remaining), "unit": "qoder_credits"})
    out["metrics"]["quota"] = metric(quotas or None)
    out["metrics"]["reset_time"] = metric([{"bucket": "totalQuota", "resets_at": reset}] if reset else None)
    out["metrics"]["credits"] = metric(wallets or None)
    out["diagnostics"]["transport"] = "qoder_cn_web_session"
    return out


def collect_qoder_web(session, now, timeout=15):
    cookie = require(session, "cookie")
    payload = get_json(QODER_ORIGIN + "/api/v2/me/usages/big_model_credits", timeout=timeout, headers={
        "Cookie": cookie, "User-Agent": session.get("user_agent") or SAFARI_UA,
        "Accept": "application/json, text/plain, */*", "Origin": QODER_ORIGIN,
        "Referer": QODER_ORIGIN + "/account/usage", "X-Requested-With": "XMLHttpRequest"})
    return normalize_qoder_web(payload, now)


def normalize_workbuddy(payload, now):
    if not isinstance(payload, dict) or payload.get("code") != 0 or not isinstance(payload.get("data"), dict):
        raise SourceError("workbuddy_api_error")
    data = payload["data"]
    packages = data.get("Packages")
    if not isinstance(packages, list):
        raise SourceError("unsupported_workbuddy_contract")
    total = remaining = frozen = 0.0
    counted = 0
    for item in packages:
        if not isinstance(item, dict):
            raise SourceError("invalid_workbuddy_package")
        if item.get("CapacityUnit") != "credits":
            continue
        counted += 1
        total += float(decimal_string(item.get("CycleTotalCapacity")))
        remaining += float(decimal_string(item.get("CycleRemainCapacity")))
        if item.get("CycleFrozenCapacity") is not None:
            frozen += float(decimal_string(item.get("CycleFrozenCapacity")))
    out = source("workbuddy", "account", now)
    if counted == 0:
        out["metrics"]["credits"] = metric(reason="workbuddy_no_credit_packages")
        return out
    if total > 0:
        used = max(0.0, total - remaining)
        out["metrics"]["quota"] = metric([{"bucket": "credits", "used_percent": used / total * 100,
                                           "remaining_percent": remaining / total * 100,
                                           "used": used, "limit": total, "unit": "workbuddy_credits"}])
    out["metrics"]["credits"] = metric({"balance": decimal_string(remaining), "total": decimal_string(total),
                                        "frozen": decimal_string(frozen), "unit": "workbuddy_credits"})
    plan = data.get("SubscriptionPackageName")
    if isinstance(plan, str) and 0 < len(plan) < 80:
        out["subscription"] = {"plan": plan}
    out["diagnostics"]["transport"] = "workbuddy_web_session"
    return out


def collect_workbuddy(session, now, timeout=15):
    cookie = require(session, "cookie")
    # WorkBuddy binds the session to the User-Agent of the browser that signed in.
    payload = post_json(WORKBUDDY_ORIGIN + "/billing/meter/get-user-resource-summary", {}, timeout=timeout, headers={
        "Cookie": cookie, "User-Agent": session.get("user_agent") or SAFARI_UA,
        "Origin": WORKBUDDY_ORIGIN, "Referer": WORKBUDDY_ORIGIN + "/profile/plans-usage"})
    return normalize_workbuddy(payload, now)


def normalize_trae(payload, now, token=None):
    packs = None
    if isinstance(payload, dict):
        packs = payload.get("user_entitlement_pack_list", payload.get("userEntitlementPackList"))
    if not isinstance(packs, list):
        raise SourceError("unsupported_trae_contract")
    limit = used = 0.0
    active = 0
    for pack in packs:
        if not isinstance(pack, dict):
            raise SourceError("invalid_trae_pack")
        base = pack.get("entitlement_base_info", pack.get("entitlementBaseInfo")) or {}
        quota = base.get("quota") if isinstance(base, dict) else None
        usage = pack.get("usage") or {}
        raw_limit = quota.get("credits_limit", quota.get("creditsLimit")) if isinstance(quota, dict) else None
        raw_used = usage.get("credits_amount", usage.get("creditsAmount")) if isinstance(usage, dict) else None
        if raw_limit is None:
            # Feature entitlements without a credit limit are not balances.
            if isinstance(quota, dict) and raw_used is None:
                continue
            raise SourceError("invalid_trae_pack")
        pack_limit = number(raw_limit)
        pack_used = 0 if raw_used is None else number(raw_used)
        if pack_limit == 0 and pack_used == 0:
            continue
        active += 1
        limit += pack_limit
        used += pack_used
    out = source("trae_cn", "account", now)
    out["account_key"] = account_key("trae_cn", token) if token else None
    if active == 0 or limit <= 0:
        out["metrics"]["credits"] = metric(reason="trae_no_credit_packs")
        return out
    percent = min(100.0, used / limit * 100)
    out["metrics"]["quota"] = metric([{"bucket": "credits", "used_percent": percent, "remaining_percent": 100 - percent,
                                       "used": used, "limit": limit, "unit": "trae_credits"}])
    out["metrics"]["credits"] = metric({"balance": decimal_string(max(0.0, limit - used)), "total": decimal_string(limit),
                                        "unit": "trae_credits", "packs": active})
    out["diagnostics"]["transport"] = "trae_cn_cloud_ide_jwt"
    return out


def collect_trae(session, now, timeout=15):
    token = require(session, "token")
    if token.lower().startswith("cloud-ide-jwt "):
        token = token[len("cloud-ide-jwt "):].strip()
    headers = {"Authorization": "Cloud-IDE-JWT " + token, "X-User-Region": "CN",
               "User-Agent": session.get("user_agent") or SAFARI_UA}
    if session.get("device_id"):
        headers["X-Device-Id"] = session["device_id"]
    return normalize_trae(post_json(TRAE_URL, {}, timeout=timeout, headers=headers), now, token)
