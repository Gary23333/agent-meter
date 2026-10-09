"""火山引擎方舟 Coding Plan quota through the signed OpenAPI action
GetCodingPlanUsage, using an AccessKey pair entered in the app (Keychain →
local API memory, never written). A query only: no model call is made, so
no plan quota is spent to observe it.

Contract follows token-monitor c62544e (volcengine/limits.js, MIT):
Result.QuotaUsage[] with Level (session/weekly/monthly), Percent (used) and
ResetTimestamp. Signing is Volcengine's HMAC-SHA256 V4 scheme for service
"ark" in cn-beijing.
"""
import hashlib
import hmac
import time
from urllib.parse import quote, urlsplit, parse_qsl

from .model import SourceError, account_key, metric, number, source, timestamp
from .transport import get_json

URL = "https://open.volcengineapi.com/?Action=GetCodingPlanUsage&Version=2024-01-01"
REGION = "cn-beijing"
SERVICE = "ark"
CONTENT_TYPE = "application/x-www-form-urlencoded; charset=utf-8"
SIGNED_HEADERS = "content-type;host;x-content-sha256;x-date"
LEVELS = {"session": 300, "5-hour": 300, "five_hour": 300, "5h": 300,
          "weekly": 10080, "week": 10080, "monthly": 43200, "month": 43200}
AUTH_ERRORS = {"InvalidAccessKey", "SignatureDoesNotMatch", "InvalidCredential", "AccessDenied",
               "InvalidSecretToken", "MissingAuthenticationToken", "Unauthorized"}


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
    if raw in (None, "", 0):
        return None
    return timestamp(raw, unit="milliseconds" if raw > 2e10 else "seconds") if isinstance(raw, (int, float)) else timestamp(raw)


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
        raw = q.get("Percent", q.get("percent"))
        if level not in LEVELS or raw is None:
            continue
        used = min(100.0, number(float(raw)))
        rows.append({"bucket": level, "window_minutes": LEVELS[level], "used_percent": used,
                     "remaining_percent": 100 - used,
                     "resets_at": _instant(q.get("ResetTimestamp", q.get("resetTimestamp")))})
    plan = next((str(result[k]).strip() for k in ("PlanName", "PlanTier", "ProductName", "PackageName")
                 if isinstance(result.get(k), str) and result[k].strip()), None)
    if plan:
        plan = plan.replace("PLAN_TIER_", "").replace("_", " ").title()
    return rows, plan, str(result.get("Status") or "").strip() or None


def collect_volcengine(now, timeout=15, session=None):
    session = session or {}
    ak, sk = session.get("access_key_id"), session.get("secret_access_key")
    if not ak or not sk:
        raise SourceError("volcengine_credential_not_connected")
    body = b""
    rows, plan, status = normalize_usage(get_json(URL, timeout=timeout, body=body, headers=sign(URL, body, ak, sk, now)))
    out = source("volcengine", "account", now)
    out["account_key"] = account_key("volcengine", ak)
    out["metrics"]["quota"] = metric(rows or None, reason=None if rows else "volcengine_no_quota_windows")
    resets = [{"bucket": r["bucket"], "resets_at": r["resets_at"]} for r in rows if r["resets_at"]]
    out["metrics"]["reset_time"] = metric(resets or None)
    out["subscription"] = {"plan": "Coding Plan " + plan if plan else "Coding Plan"}
    if status:
        out["subscription"]["status"] = status
    out["diagnostics"]["transport"] = "volcengine_openapi_signed"
    return out
