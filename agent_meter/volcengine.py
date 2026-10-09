"""火山引擎方舟 Coding Plan quota through the action GetCodingPlanUsage, by
one of two routes, both read-only (no model call, no quota spent):

- console login: the app's login window watches the Coding Plan page's own
  GetCodingPlanUsage request and keeps its URL and CSRF header with the login
  cookie; the backend replays that one allowlisted request;
- AccessKey pair (访问控制 → API 访问密钥) signing the OpenAPI call.

The Ark console's API key only authorizes model calls and is refused here.
Credentials live in the Keychain and reach the backend only through local
API memory.

Contract follows token-monitor c62544e (volcengine/limits.js, MIT):
Result.QuotaUsage[] with Level (session/weekly/monthly), Percent (used) and
ResetTimestamp. Signing is Volcengine's HMAC-SHA256 V4 scheme for service
"ark" in cn-beijing.
"""
import hashlib
import hmac
import re
import time
from urllib.parse import quote, urlsplit, parse_qsl

from .model import SourceError, account_key, failed_source, metric, shape, source, timestamp
from .transport import get_json

URL = "https://open.volcengineapi.com/?Action=GetCodingPlanUsage&Version=2024-01-01"
REGION = "cn-beijing"
SERVICE = "ark"
CONTENT_TYPE = "application/x-www-form-urlencoded; charset=utf-8"
SIGNED_HEADERS = "content-type;host;x-content-sha256;x-date"
LEVELS = {"session": 300, "5-hour": 300, "five_hour": 300, "5h": 300,
          "weekly": 10080, "week": 10080, "monthly": 43200, "month": 43200}
CONSOLE = "https://console.volcengine.com"
CONSOLE_USAGE_URL = CONSOLE + "/api/top/ark/cn-beijing/2024-01-01/GetCodingPlanUsage"
CONSOLE_PATH = re.compile(r"^/api/top/ark/[a-z0-9-]+/\d{4}-\d{2}-\d{2}/GetCodingPlanUsage$")
CONSOLE_PAGE = CONSOLE + "/ark/region:cn-beijing/subscription/coding-plan"
SAFARI_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/18.0 Safari/605.1.15")
AUTH_ERRORS = {"InvalidAccessKey", "SignatureDoesNotMatch", "InvalidCredential", "AccessDenied",
               "InvalidSecretToken", "MissingAuthenticationToken", "Unauthorized", "NotLogin", "LoginRequired",
               "InvalidCsrfToken", "CsrfTokenInvalid"}


def _enc(value):
    return quote(value, safe="-_.~")


def sign(url, body, access_key_id, secret_access_key, now, region=REGION):
    """Headers for a signed POST of exactly `body` (bytes)."""
    parts = urlsplit(url)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now))
    day = stamp[:8]
    payload_hash = hashlib.sha256(body).hexdigest()
    query = "&".join("%s=%s" % kv for kv in sorted((_enc(k), _enc(v)) for k, v in parse_qsl(parts.query, keep_blank_values=True)))
    canonical = "\n".join(["POST", quote(parts.path or "/", safe="/-_.~"), query,
                           "content-type:" + CONTENT_TYPE, "host:" + parts.netloc,
                           "x-content-sha256:" + payload_hash, "x-date:" + stamp, "",
                           SIGNED_HEADERS, payload_hash])
    scope = "%s/%s/%s/request" % (day, region, SERVICE)
    to_sign = "\n".join(["HMAC-SHA256", stamp, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    key = secret_access_key.encode()
    for part in (day, region, SERVICE, "request"):
        key = hmac.new(key, part.encode(), hashlib.sha256).digest()
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    return {"Content-Type": CONTENT_TYPE, "X-Date": stamp, "X-Content-Sha256": payload_hash,
            "Authorization": "HMAC-SHA256 Credential=%s/%s, SignedHeaders=%s, Signature=%s"
                             % (access_key_id, scope, SIGNED_HEADERS, signature)}


def _instant(raw):
    """Epoch seconds or milliseconds, possibly as a string; 0 / negative mean "no reset yet"."""
    if isinstance(raw, str) and raw.strip().lstrip("-").isdigit():
        raw = int(raw.strip())
    if raw in (None, "") or (isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw <= 0):
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return timestamp(raw, unit="milliseconds" if raw > 2e10 else "seconds")
    return timestamp(raw)


def _percent(raw):
    """Used percent 0–100; None when absent, negative (unknown) or not a number."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value != value or value < 0:
        return None
    return min(100.0, value)


def normalize_usage(payload):
    if not isinstance(payload, dict):
        raise SourceError("invalid_volcengine_response")
    error = (payload.get("ResponseMetadata") or {}).get("Error")
    if isinstance(error, dict):
        raise SourceError("not_authenticated" if error.get("Code") in AUTH_ERRORS else "volcengine_api_error")
    result = payload.get("Result", payload.get("result"))
    if not isinstance(result, dict):
        raise SourceError("unsupported_volcengine_contract")
    quotas = result.get("QuotaUsage", result.get("quotaUsage"))
    if quotas is None:
        raise SourceError("volcengine_no_coding_plan")
    if not isinstance(quotas, list):
        raise SourceError("unsupported_volcengine_contract")
    rows = []
    for q in quotas:
        if not isinstance(q, dict):
            raise SourceError("invalid_volcengine_quota")
        level = str(q.get("Level", q.get("level")) or "").strip().lower()
        used = _percent(q.get("Percent", q.get("percent")))
        if level not in LEVELS or used is None:
            continue
        rows.append({"bucket": level, "window_minutes": LEVELS[level], "used_percent": used,
                     "remaining_percent": 100 - used,
                     "resets_at": _instant(q.get("ResetTimestamp", q.get("resetTimestamp")))})
    plan = next((str(result[k]).strip() for k in ("PlanName", "PlanTier", "ProductName", "PackageName")
                 if isinstance(result.get(k), str) and result[k].strip()), None)
    if plan:
        plan = plan.replace("PLAN_TIER_", "").replace("_", " ").title()
    return rows, plan, str(result.get("Status") or "").strip() or None


def console_usage_url(raw):
    """The page's own request URL, only if it is the allowlisted console action."""
    if not raw:
        return CONSOLE_USAGE_URL
    parts = urlsplit(raw)
    if parts.scheme != "https" or parts.netloc != "console.volcengine.com" or not CONSOLE_PATH.match(parts.path) \
            or parts.username or parts.password or parts.fragment:
        raise SourceError("invalid_endpoint")
    return raw


def _cookie_value(cookie, name):
    for part in cookie.split(";"):
        key, sep, value = part.strip().partition("=")
        if sep and key == name:
            return value
    return None


def _console(session, now, timeout):
    cookie = session["cookie"]
    csrf = session.get("csrf_token") or _cookie_value(cookie, "csrfToken")
    if not csrf:
        raise SourceError("volcengine_not_authenticated")
    url = console_usage_url(session.get("usage_url"))
    try:
        return get_json(url, timeout=timeout, body={}, headers={
            "Cookie": cookie, "x-csrf-token": csrf, "User-Agent": session.get("user_agent") or SAFARI_UA,
            "Accept": "application/json, text/plain, */*", "Origin": CONSOLE, "Referer": CONSOLE_PAGE})
    except SourceError as e:
        # An expired console login answers with a redirect to the sign-in page.
        raise SourceError("volcengine_not_authenticated" if e.code in ("redirect_rejected", "not_authenticated") else e.code) from None


def collect_volcengine(session, now, timeout=15):
    session = session or {}
    ak, sk = session.get("access_key_id"), session.get("secret_access_key")
    if session.get("cookie"):
        payload = _console(session, now, timeout)
        try:
            rows, plan, status = normalize_usage(payload)
        except SourceError as e:
            if e.code == "not_authenticated":
                raise SourceError("volcengine_not_authenticated") from None
            # Keep the response's structure (names and types, never values) to fix the parser.
            out = failed_source("volcengine", "account", now, e.code)
            out["diagnostics"]["usage_shape"] = shape(payload)
            return out
        transport, key = "volcengine_console_session", None
    elif ak and sk:
        if not ak.upper().startswith("AK"):
            # An Ark API key pasted into the AccessKey field.
            raise SourceError("volcengine_ark_key_not_supported")
        body = b""
        rows, plan, status = normalize_usage(get_json(URL, timeout=timeout, body=body, headers=sign(URL, body, ak, sk, now)))
        transport, key = "volcengine_openapi_signed", account_key("volcengine", ak)
    else:
        raise SourceError("volcengine_credential_not_connected")
    out = source("volcengine", "account", now)
    out["account_key"] = key
    out["metrics"]["quota"] = metric(rows or None, reason=None if rows else "volcengine_no_quota_windows")
    resets = [{"bucket": r["bucket"], "resets_at": r["resets_at"]} for r in rows if r["resets_at"]]
    out["metrics"]["reset_time"] = metric(resets or None)
    out["subscription"] = {"plan": "Coding Plan " + plan if plan else "Coding Plan"}
    if status:
        out["subscription"]["status"] = status
    out["diagnostics"]["transport"] = transport
    return out
