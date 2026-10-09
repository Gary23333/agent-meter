"""Xiaomi MiMo API platform: wallet balance and Token Plan, read with the
console login made in the app's own login window (Cookie in Keychain →
local API memory). MiMo's inference keys (sk-…) are rejected by the billing
routes, so the API key cannot be used here.

Contract follows token-monitor c62544e (mimo/limits.js, docs/providers/mimo.md,
MIT): GET platform.xiaomimimo.com/api/v1/{balance,tokenPlan/detail,tokenPlan/usage}.
Only the console's own cookies are forwarded; redirects (an expired login)
are refused by the transport instead of followed.
"""
import re
from datetime import datetime

from .model import DISPLAY_ZONE, SourceError, account_key, decimal_string, metric, number, shape, source, timestamp
from .transport import get_json

ORIGIN = "https://platform.xiaomimimo.com"
API = ORIGIN + "/api/v1"
COOKIES = {"api-platform_serviceToken", "userId", "api-platform_ph", "api-platform_slh"}
NO_PLAN = {"", "default", "none", "no_plan", "not_subscribed", "unsubscribed"}
SAFARI_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/18.0 Safari/605.1.15")


def console_cookie(raw):
    """Keeps only the console cookies; returns (header, userId)."""
    pairs = {}
    for part in (raw or "").split(";"):
        name, sep, value = part.strip().partition("=")
        if sep and name in COOKIES and value:
            pairs[name] = value
    if "api-platform_serviceToken" not in pairs or "userId" not in pairs:
        raise SourceError("mimo_not_authenticated")
    return "; ".join("%s=%s" % kv for kv in sorted(pairs.items())), pairs["userId"]


def _data(payload):
    if not isinstance(payload, dict):
        raise SourceError("invalid_mimo_response")
    code = payload.get("code")
    if code in (401, 403):
        raise SourceError("mimo_not_authenticated")
    if code not in (None, 0):
        raise SourceError("mimo_api_error")
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        raise SourceError("invalid_mimo_response")
    return data


def _money(value):
    return None if value in (None, "") else decimal_string(value, allow_negative=True)


def normalize_balance(payload):
    data = _data(payload)
    if data.get("balance") in (None, ""):
        raise SourceError("unsupported_mimo_balance_contract")
    currency = str(data.get("currency") or "CNY").upper()
    if currency not in {"CNY", "USD"}:
        raise SourceError("unknown_balance_currency")
    out = {"unit": currency, "balance": _money(data["balance"]),
           "cash": _money(data.get("cashBalance", data.get("cash_balance"))),
           "granted": _money(data.get("giftBalance", data.get("gift_balance")))}
    if out["cash"] is not None:
        out["topped_up"] = out["cash"]
    return out


def _instant(raw):
    """Epoch (number or digit string), ISO with zone, or a zone-less console
    time, which is read as Beijing time like the console displays it."""
    if raw in (None, ""):
        return None
    if isinstance(raw, str) and re.fullmatch(r"\d{9,13}", raw.strip()):
        raw = int(raw.strip())
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return timestamp(raw, unit="milliseconds" if raw > 1e11 else "seconds")
    if not isinstance(raw, str):
        raise SourceError("invalid_timestamp")
    text = raw.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text.replace(" ", "T", 1) if len(text) > 10 else text)
    except ValueError:
        raise SourceError("invalid_timestamp") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=DISPLAY_ZONE)
    return timestamp(parsed.timestamp())


def _first(obj, *keys):
    for k in keys:
        if isinstance(obj, dict) and obj.get(k) not in (None, ""):
            return obj[k]
    return None


def _month_quota(u, ends):
    """This month's token quota from /tokenPlan/usage, tolerant of the
    spellings seen across console versions; None when it has no total."""
    month = _first(u, "monthUsage", "month_usage", "tokenUsage", "token_usage", "usage") or u
    items = month.get("items") if isinstance(month, dict) else (month if isinstance(month, list) else None)
    item = month if isinstance(month, dict) else None
    if isinstance(items, list) and items:
        named = [i for i in items if isinstance(i, dict)]
        item = next((i for i in named if str(i.get("name", "")).lower() == "month_total_token"), None) \
            or next((i for i in named if "total" in str(i.get("name", "")).lower()), None) \
            or (named[0] if len(named) == 1 else None)
    if not isinstance(item, dict):
        return None
    limit = _first(item, "limit", "total", "quota", "limitAmount", "totalAmount", "limit_amount")
    used = _first(item, "used", "usage", "usedAmount", "consumed", "used_amount")
    percent = _first(item, "percent", "usedPercent", "used_percent")
    try:
        limit = None if limit is None else number(float(limit))
        used = None if used is None else number(float(used))
        percent = None if percent is None else number(float(percent))
    except (TypeError, ValueError):
        raise SourceError("invalid_mimo_token_plan") from None
    if limit and used is not None:
        pct = min(100.0, used / limit * 100)
    elif percent is not None:
        # Console percent is the used share, 0–100.
        pct = min(100.0, percent)
    else:
        return None
    return {"bucket": "monthTotal", "used_percent": pct, "remaining_percent": 100 - pct,
            "used": used, "limit": limit, "unit": "tokens", "resets_at": ends}


def normalize_plan(detail, usage):
    """Token Plan name/end and this month's token quota; (None, None) without a plan."""
    d = _data(detail)
    code = str(d.get("planCode", d.get("plan_code")) or d.get("planName", d.get("plan_name")) or "").strip()
    status = str(d.get("planStatus", d.get("status")) or "").strip().lower()
    if code.lower() in NO_PLAN or status in {"expired", "ended"}:
        return None, None
    name = code[:1].upper() + code[1:]
    try:
        ends = _instant(d.get("currentPeriodEnd", d.get("current_period_end")))
    except SourceError:
        # An unreadable period end must not hide the plan and its usage.
        ends = None
    quota = _month_quota(_data(usage), ends)
    return {"plan": "Token Plan " + name, "ends_at": ends}, quota


def collect_mimo(session, now, timeout=15):
    cookie, user_id = console_cookie((session or {}).get("cookie"))
    headers = {"Cookie": cookie, "User-Agent": (session or {}).get("user_agent") or SAFARI_UA,
               "Accept": "application/json, text/plain, */*", "Origin": ORIGIN, "Referer": ORIGIN + "/"}

    def get(path):
        try:
            return get_json(API + path, timeout=timeout, headers=headers)
        except SourceError as e:
            # An expired login answers with a redirect to the Xiaomi account page.
            raise SourceError("mimo_not_authenticated" if e.code in ("redirect_rejected", "not_authenticated") else e.code) from None

    out = source("mimo", "api_account", now)
    out["account_key"] = account_key("mimo", user_id)
    out["metrics"]["credits"] = metric([normalize_balance(get("/balance"))])
    try:
        usage_body = get("/tokenPlan/usage")
        plan, quota = normalize_plan(get("/tokenPlan/detail"), usage_body)
    except SourceError as e:
        if e.code == "mimo_not_authenticated":
            raise
        plan, quota = None, None
        out["metrics"]["quota"] = metric(status="error", reason=e.code)
    else:
        out["metrics"]["quota"] = metric([quota] if quota else None,
                                         reason=None if quota or not plan else "mimo_token_plan_usage_unrecognized")
        if plan and not quota:
            out["diagnostics"]["token_plan_usage_shape"] = shape(usage_body)
        if quota and quota["resets_at"]:
            out["metrics"]["reset_time"] = metric([{"bucket": "monthTotal", "resets_at": quota["resets_at"]}])
    out["subscription"] = {"plan": plan["plan"]} if plan else {"plan": "按量付费"}
    out["diagnostics"]["transport"] = "mimo_console_web_session"
    return out
