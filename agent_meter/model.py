"""Small JSON contract: absent measurements are never numeric zero."""

import hashlib
import math
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

SCHEMA_VERSION = 3
METRICS = ("quota", "reset_time", "reset_cards", "credits", "tokens", "cost", "renewal_time", "renewal_countdown", "renewal_amount", "credit_refresh_time", "credit_refresh_countdown")
STATUSES = {"available", "partial", "not_provided", "not_connected", "not_supported", "error", "stale"}
DISPLAY_ZONE = ZoneInfo("Asia/Shanghai")


class SourceError(Exception):
    """Only a safe fixed error code may cross the public API."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def integer(value, optional=False):
    if optional and value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SourceError("invalid_integer")
    return value


def number(value, optional=False):
    if optional and value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise SourceError("invalid_number")
    return value


def decimal_string(value, optional=False, allow_negative=False):
    if optional and value is None:
        return None
    if isinstance(value, bool):
        raise SourceError("invalid_decimal")
    try:
        d = Decimal(str(value))
        if not d.is_finite() or (d < 0 and not allow_negative):
            raise ValueError()
        return format(d, "f")
    except (ValueError, InvalidOperation, TypeError):
        raise SourceError("invalid_decimal") from None


def timestamp(value, unit="seconds"):
    if value is None:
        return None
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                raise ValueError()
            seconds = dt.timestamp()
        except ValueError:
            raise SourceError("invalid_timestamp") from None
    else:
        seconds = number(value)
        if unit == "milliseconds":
            seconds /= 1000
        elif unit != "seconds":
            raise SourceError("unknown_timestamp_unit")
    # Reject accidental epoch milliseconds in a seconds contract.
    if not 0 <= seconds <= 253402271999:
        raise SourceError("invalid_timestamp")
    try:
        dt = datetime.fromtimestamp(seconds, timezone.utc)
        return {"epoch_seconds": seconds, "utc": dt.isoformat(), "display": dt.astimezone(DISPLAY_ZONE).isoformat()}
    except (ValueError, OverflowError, OSError):
        raise SourceError("invalid_timestamp") from None


def metric(value=None, status=None, reason=None):
    status = status or ("available" if value is not None else "not_provided")
    if status not in STATUSES:
        raise ValueError("unknown metric status")
    return {"status": status, "value": value, "reason": reason}


def source(source_id, scope, now, status="available", reason=None):
    return {
        "id": source_id, "scope": scope, "status": status,
        "observed_at": timestamp(now),
        "metrics": {name: metric(status="not_provided", reason="source_does_not_return_field") for name in METRICS},
        "diagnostics": {"reason": reason},
    }


def failed_source(source_id, scope, now, code, status="error"):
    out = source(source_id, scope, now, status, code)
    out["metrics"] = {name: metric(status=status, reason=code) for name in METRICS}
    return out


def account_key(provider, identity):
    if not isinstance(identity, str) or not identity:
        return None
    return hashlib.sha256((provider + ":" + identity).encode()).hexdigest()[:24]
