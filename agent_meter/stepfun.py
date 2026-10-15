"""阶跃星辰 (StepFun) 开放平台：账户余额与 STEP plan 用量。

两条只读路线，与 ZCode、火山方舟同构：
- 控制台网页登录（Cookie 只保留 Oasis-Token）→ 平台自己的 Dashboard RPC
  QueryAccountBalance / GetStepPlanStatus / QueryStepPlanRateLimit。
- 开放平台 API Key → 官方文档接口 GET /v1/accounts（只有余额，没有 plan 用量）。

契约来源：公开 API 文档 platform.stepfun.com/docs/zh/api-reference/accounts/get；
控制台 RPC 的字段与「0 表示没有配额、不是已用完」的行为取自 stepfun-cli 的逆向
记录（2026-09）与 CodexBar 的 StepFun 实现，两者一致。只读，不买入、不兑换、
不改套餐，也不把套餐刊例价当成下一笔扣款金额。
"""
import base64
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from .billing import renewal_date
from .model import DISPLAY_ZONE, SourceError, account_key, decimal_string, metric, source, timestamp
from .transport import get_json, post_json

CONSOLE = "https://platform.stepfun.com"
DASHBOARD = CONSOLE + "/api/step.openapi.devcenter.Dashboard/"
OPENAPI = "https://api.stepfun.com/v1"
COOKIE_NAME = "Oasis-Token"
# The Dashboard RPCs identify the caller by the cookie alone, but the console
# always sends these alongside it.
CONSOLE_HEADERS = {"oasis-appid": "10300", "oasis-platform": "web"}
# Rolling windows of the grandfathered Coding Plan; the current Token Plan
# meters a monthly credit pool through plan_credit_rate_limit instead.
WINDOW_MINUTES = {"limit5h": 300, "limit7d": 10080}
SAFARI_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/18.0 Safari/605.1.15")


def _fen(value):
    """Console amounts are integer 分; the public API reference uses 元."""
    if value in (None, ""):
        return None
    try:
        return decimal_string(Decimal(str(value)) / 100, allow_negative=True)
    except (InvalidOperation, ValueError, TypeError):
        raise SourceError("invalid_stepfun_amount") from None


def _amount(value):
    """Amount already expressed in 元 (the open-platform route)."""
    if value in (None, ""):
        return None
    return decimal_string(value, allow_negative=True)


def _rate(value):
    """A 0–1 remaining fraction, sent as a number or as a string."""
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise SourceError("invalid_stepfun_rate") from None
    if parsed != parsed:
        raise SourceError("invalid_stepfun_rate")
    return min(1.0, max(0.0, parsed))


def _count(value):
    """Credit counts are integers without a decimal point (often as strings)."""
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise SourceError("invalid_stepfun_credits") from None


def _instant(raw):
    """Epoch seconds, or None. A configured-but-zero reset time means the
    window does not exist, so it must not become 1970."""
    if raw in (None, "", 0, "0"):
        return None
    if isinstance(raw, str) and not re.fullmatch(r"\d{9,13}", raw.strip()):
        raise SourceError("invalid_timestamp")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise SourceError("invalid_timestamp") from None
    if value <= 0:
        return None
    return timestamp(value, unit="milliseconds" if value > 1e11 else "seconds")


def _day(raw):
    stamp = _instant(raw)
    if stamp is None:
        return None
    return datetime.fromtimestamp(stamp["epoch_seconds"], DISPLAY_ZONE).date().isoformat()


def _jwt_payload(chunk):
    parts = chunk.split(".")
    if len(parts) != 3 or not parts[1]:
        return None
    try:
        decoded = base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4))
        claims = json.loads(decoded)
    except (ValueError, TypeError):
        return None
    return claims if isinstance(claims, dict) else None


def _oasis_claims(token):
    """Oasis-Token is access-JWT + "..." + device-JWT, so splitting on "."
    yields eight segments with two empty ones between the two tokens."""
    parts = token.split(".")
    chunks = [parts[0:3], parts[5:8]] if len(parts) == 8 else [parts]
    return [claims for claims in (_jwt_payload(".".join(chunk)) for chunk in chunks) if claims]


def _claim(claims, name):
    for payload in claims:
        value = payload.get(name)
        if isinstance(value, bool):
            continue
        if isinstance(value, (str, int)) and str(value):
            return str(value)
    return None


def console_session(raw):
    """Keeps only Oasis-Token. The Dashboard RPC rejects a cookie carrying any
    other field — it then parses the whole value as a single JWT and answers
    401 — so the app's full cookie jar is narrowed here. Returns the token
    plus the device id and account id the two JWT segments claim."""
    token = None
    for part in (raw or "").split(";"):
        name, sep, value = part.strip().partition("=")
        if sep and name == COOKIE_NAME and value:
            token = value
    if not token:
        raise SourceError("stepfun_not_authenticated")
    claims = _oasis_claims(token)
    return token, _claim(claims, "device_id"), _claim(claims, "oasis_id")


def _rpc(payload):
    """Connect-style envelope. A non-empty string `code` is a transport error;
    a `status` other than 1 is only treated as a failure when it explains
    itself, so a benign status on an account without a plan still parses."""
    if not isinstance(payload, dict):
        raise SourceError("invalid_stepfun_response")
    code = payload.get("code")
    if isinstance(code, str) and code:
        raise SourceError("stepfun_not_authenticated"
                          if code in {"unauthenticated", "permission_denied", "token_expired"}
                          else "stepfun_api_error")
    if code not in (None, 0, "0"):
        raise SourceError("stepfun_api_error")
    status = payload.get("status")
    if status is not None and str(status) != "1" and (payload.get("desc") or payload.get("message")):
        raise SourceError("stepfun_api_error")
    return payload


def normalize_balance(payload):
    """QueryAccountBalance → one wallet row, with the console's 分→元 done."""
    data = _rpc(payload)
    balance = _fen(data.get("balance"))
    if balance is None:
        raise SourceError("unsupported_stepfun_balance_contract")
    row = {"bucket": "stepfun", "unit": "CNY", "balance": balance,
           "cash": _fen(data.get("payment")), "granted": _fen(data.get("voucher"))}
    if row["cash"] is not None:
        row["topped_up"] = row["cash"]
    return row


def normalize_account(payload):
    """GET /v1/accounts (documented): the same three numbers, already in 元."""
    if not isinstance(payload, dict) or payload.get("object") not in (None, "account"):
        raise SourceError("unsupported_stepfun_balance_contract")
    if payload.get("balance") is None:
        raise SourceError("unsupported_stepfun_balance_contract")
    row = {"bucket": "stepfun", "unit": "CNY", "balance": _amount(payload["balance"]),
           "cash": _amount(payload.get("total_cash_balance")),
           "granted": _amount(payload.get("total_voucher_balance"))}
    if row["cash"] is not None:
        row["topped_up"] = row["cash"]
    kind = payload.get("type")
    return row, kind if kind in {"prepaid", "postpaid"} else None


def normalize_plan_status(payload):
    """GetStepPlanStatus → plan name, expiry day and auto-renew, or None."""
    data = _rpc(payload)
    sub = data.get("subscription")
    if not isinstance(sub, dict):
        return None
    name = sub.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    renew = sub.get("auto_renew")
    return {"plan": name.strip(), "ends_on": _day(sub.get("expired_at")),
            "auto_renew": renew if isinstance(renew, bool) else None}


def _credit_row(pool):
    """Token Plan meters one monthly credit pool. Subscription and top-up are
    independent fractions, so they are never added: absolute bucket balances
    are preferred, and only when any of them is unusable does the primary rate
    stand in — labelled as a percentage rather than a count."""
    resets_at = _instant(pool.get("subscription_credit_reset_time"))
    buckets = pool.get("credit_buckets")
    if isinstance(buckets, list) and buckets:
        pairs = []
        for bucket in buckets:
            total = residual = None
            if isinstance(bucket, dict):
                total, residual = _count(bucket.get("credit_total")), _count(bucket.get("credit_residual"))
            if total is None or residual is None or total <= 0 or residual > total:
                pairs = []
                break
            pairs.append((total, residual))
        if pairs:
            total, residual = sum(p[0] for p in pairs), sum(p[1] for p in pairs)
            return {"bucket": "stepPlanCredits", "used_percent": (1 - residual / total) * 100,
                    "remaining_percent": residual / total * 100, "used": residual, "limit": total,
                    "unit": "stepfun_credits", "resets_at": resets_at}
    left = _rate(pool.get("subscription_credit_left_rate"))
    if left is None:
        left = _rate(pool.get("topup_credit_left_rate"))
    if left is None:
        return None
    return {"bucket": "stepPlanCredits", "used_percent": (1 - left) * 100,
            "remaining_percent": left * 100, "unit": "percent", "resets_at": resets_at}


def normalize_rate_limit(payload):
    """QueryStepPlanRateLimit → (quota rows, reset rows, metering model).

    A plan meters either rolling 5-hour / weekly windows or one monthly credit
    pool. The window fields come back as 0 for a credit plan, which means "no
    window configured", not "exhausted" — so a window only becomes real once it
    reports a live reset time."""
    data = _rpc(payload)
    rows, resets = [], []
    for bucket, reset_key, rate_key in (("limit5h", "five_hour_usage_reset_time", "five_hour_usage_left_rate"),
                                        ("limit7d", "weekly_usage_reset_time", "weekly_usage_left_rate")):
        reset, left = _instant(data.get(reset_key)), _rate(data.get(rate_key))
        if reset is None or left is None:
            continue
        rows.append({"bucket": bucket, "used_percent": (1 - left) * 100, "remaining_percent": left * 100,
                     "unit": "percent", "window_minutes": WINDOW_MINUTES[bucket], "resets_at": reset})
        resets.append({"bucket": bucket, "resets_at": reset})
    if rows:
        return rows, resets, "coding_plan"
    pool = data.get("plan_credit_rate_limit")
    if isinstance(pool, dict):
        row = _credit_row(pool)
        if row is not None:
            rows.append(row)
            if row["resets_at"]:
                resets.append({"bucket": row["bucket"], "resets_at": row["resets_at"]})
            return rows, resets, "token_plan"
    return rows, resets, "no_usage_reported"


def _rpc_post(method, token, webid, session, timeout):
    headers = {"Cookie": COOKIE_NAME + "=" + token, "Origin": CONSOLE,
               "Referer": CONSOLE + "/plan-subscribe",
               "User-Agent": (session or {}).get("user_agent") or SAFARI_UA}
    headers.update(CONSOLE_HEADERS)
    if webid:
        headers["oasis-webid"] = webid
    try:
        return post_json(DASHBOARD + method, {}, timeout=timeout, headers=headers)
    except SourceError as e:
        # An expired session answers as a connect error or a redirect to login.
        raise SourceError("stepfun_not_authenticated"
                          if e.code in ("not_authenticated", "redirect_rejected") else e.code) from None


def collect_stepfun(session, now, timeout=15):
    session = session or {}
    cookie, api_key = session.get("cookie"), session.get("api_key")
    if not cookie and not api_key:
        raise SourceError("stepfun_credential_not_connected")
    out = source("stepfun", "account", now)
    if not cookie:
        # The open-platform API key reaches the documented balance endpoint
        # only; the Step Plan is metered on the console's own RPCs.
        row, kind = normalize_account(get_json(OPENAPI + "/accounts", api_key, timeout=timeout))
        out["metrics"]["credits"] = metric([row])
        out["metrics"]["quota"] = metric(status="not_connected", reason="stepfun_step_plan_needs_console_login")
        out["subscription"] = {"plan": "按量付费"}
        out["diagnostics"]["transport"] = "stepfun_open_platform_api_key"
        out["diagnostics"]["account_type"] = kind
        return out
    token, webid, oasis_id = console_session(cookie)
    if oasis_id:
        out["account_key"] = account_key("stepfun", oasis_id)
    out["metrics"]["credits"] = metric([normalize_balance(_rpc_post("QueryAccountBalance", token, webid, session, timeout))])
    out["diagnostics"]["transport"] = "stepfun_console_web_session"
    try:
        status_body = _rpc_post("GetStepPlanStatus", token, webid, session, timeout)
        rate_body = _rpc_post("QueryStepPlanRateLimit", token, webid, session, timeout)
    except SourceError as e:
        if e.code == "stepfun_not_authenticated":
            raise
        out["metrics"]["quota"] = metric(status="error", reason=e.code)
        return out
    plan = normalize_plan_status(status_body)
    rows, resets, metering = normalize_rate_limit(rate_body)
    out["metrics"]["quota"] = metric(rows or None, reason=None if rows else
                                     ("stepfun_no_step_plan" if plan is None else "stepfun_step_plan_usage_unrecognized"))
    out["metrics"]["reset_time"] = metric(resets or None)
    if plan:
        out["subscription"] = {"plan": plan["plan"], "ends_on": plan["ends_on"], "auto_renew": plan["auto_renew"]}
        if plan["ends_on"]:
            out["metrics"]["renewal_time"] = metric(renewal_date(plan["ends_on"]))
    else:
        out["subscription"] = {"plan": "按量付费"}
    out["diagnostics"]["step_plan_metering"] = metering
    return out
