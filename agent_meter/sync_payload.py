"""Cloud-sync payload: a redacted projection of the local snapshot.

The sync stream carries aggregates only, assembled field by field so nothing
else can leak into it by accident:

- ``usage``: per-day per-model token rollups of every local ledger;
- ``images``: per-day Codex built-in image_gen counts, and ``credits``: the
  per-day spend of a local credit ledger (Qoder);
- ``quota``: today's observation per account and window, plus
  ``quota_history``: the same for each recent day, with that day's peak;
- ``accounts``: what another device may not read for itself — balances,
  reset cards, renewal and plan of an account;
- ``rewards``: which days were checked in or claimed, per provider;
- ``cards``: the card tally, ``settings``: device-independent preferences;
- a device name and app version, so the other devices can list this one.

Per-request token detail, absolute paths, project paths, session activity,
account labels and credentials are never read here.

Schema 1 grows by addition only. A device on an older build reads the keys it
knows and ignores the rest, so the hosted service and those devices keep
working with a payload from this build, and this build reads theirs.

Synced rows describe other machines. They never enter the local ledgers, the
coverage matrix or the snapshot schema; they live in their own store
(`agent_meter/sync_store.py`) and are served as a separate projection.
"""

import math
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation

from .applications import app_id
from .model import DISPLAY_ZONE, SourceError

SYNC_SCHEMA = 1
# Token fields carried per row. "requests" is a count; the rest are tokens.
TOKEN_KEYS = ("fresh_input", "output", "reasoning", "cache_read", "cache_write")
USAGE_KEYS = ("requests",) + TOKEN_KEYS
# Settings that describe the user rather than the machine. Per-device switches
# (disabled sources, low-resource mode, skipped ledgers, project aliases) are
# deliberately absent: they are true of one computer and false of another.
SETTINGS_KEYS = ("theme", "low_quota_threshold", "source_order", "alerts_enabled", "menu_bar_mode", "budget")
MENU_BAR_MODES = ("ticker", "flip", "tightest", "todayTokens", "iconOnly")
TOKEN_STATUSES = {"available", "partial", "stale"}
QUOTA_STATUSES = {"available", "partial"}
USABLE = {"available", "partial", "stale"}
# Scopes that stand for an account, as opposed to a local ledger or a feature.
NON_ACCOUNT_SCOPES = {"external_forecast"}
# Credit fields a balance row may carry. Anything else a provider returns
# stays on the device that read it.
CREDIT_TEXT = ("bucket", "kind", "unit")
CREDIT_NUMBERS = ("balance", "total", "used", "remaining", "frozen", "granted", "topped_up", "cash")
# Local credit ledgers that keep a per-day series, by provider.
CREDIT_LEDGERS = {"qoder": "qoder_credits"}
MAX_DEVICE = 64
MAX_NAME = 60
MAX_VERSION = 24
# A year of daily rows for a dozen ledgers is well under this; the cap keeps a
# payload inside the service's 8 MB blob limit.
MAX_ROWS = 20000
MAX_QUOTA_ROWS = 500
MAX_QUOTA_HISTORY = 4000
MAX_ACCOUNTS = 60
MAX_REWARD_ROWS = 2000
MAX_DAY_ROWS = 2000
MAX_CREDIT_ROWS = 30
MAX_CARD_EXPIRIES = 20
QUOTA_DAYS = 35
REWARD_DAYS = 35
CURRENCIES = {"USD", "CNY"}


def _count(value):
    """A non-negative integer, or 0. Never raises on a malformed source row."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _number(value, negative=False):
    """A finite number from a number or a Decimal string, or None."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        out = float(Decimal(value)) if isinstance(value, str) else float(value)
    except (ValueError, TypeError, InvalidOperation):
        return None
    if not math.isfinite(out) or (out < 0 and not negative):
        return None
    return out


def _epoch(value):
    """Seconds since the epoch, from a float or from a backend timestamp."""
    if isinstance(value, dict):
        value = value.get("epoch_seconds")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _text(value, limit):
    """A short single-line string, or None. Control characters never travel."""
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned[:limit] if cleaned else None


def _id(value, limit):
    return isinstance(value, str) and 0 < len(value) <= limit


def _day(value):
    """A real calendar day in "YYYY-MM-DD" form (not just the shape of one)."""
    if not isinstance(value, str) or len(value) != 10 or value[4] != "-" or value[7] != "-":
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def _local_day(epoch):
    return datetime.fromtimestamp(float(epoch), DISPLAY_ZONE).date().isoformat()


def _sources(snapshot):
    return [src for src in (snapshot or {}).get("sources") or [] if isinstance(src, dict)]


def _metric(src, name):
    """A metric's value when it carries data (a dict), else None."""
    entry = (src.get("metrics") or {}).get(name) or {}
    value = entry.get("value")
    if entry.get("status") not in USABLE or not isinstance(value, dict):
        return None
    return value


# --- usage -----------------------------------------------------------------

def usage_rows(snapshot, device):
    """Per-day per-model token rollups for every local ledger that has them."""
    rows = []
    for src in snapshot.get("sources") or []:
        if not isinstance(src, dict):
            continue
        metrics = src.get("metrics") or {}
        tokens = metrics.get("tokens") or {}
        if not isinstance(tokens, dict) or tokens.get("status") not in TOKEN_STATUSES:
            continue
        value = tokens.get("value") or {}
        if not isinstance(value, dict):
            continue
        daily = value.get("daily_models")
        if not isinstance(daily, list):
            continue
        app = app_id(src.get("id") or "")
        for raw in daily:
            row = usage_row(raw, app, device)
            if row is not None:
                rows.append(row)
    return rows


def usage_row(raw, app, device):
    """One normalized rollup row, or None when the row is unusable."""
    if not isinstance(raw, dict):
        return None
    date = raw.get("date")
    model = raw.get("model")
    if not isinstance(date, str) or len(date) != 10 or date[4] != "-" or date[7] != "-":
        return None
    if not isinstance(model, str) or not model or len(model) > 200:
        return None
    if not isinstance(app, str) or not app or len(app) > 64:
        return None
    row = {"date": date, "app": app, "model": model, "device": device}
    for key in USAGE_KEYS:
        row[key] = _count(raw.get(key))
    # "unclassified" is part of the day's total but has no token field of its
    # own; carry it so the row's total still adds up.
    unclassified = _count(raw.get("unclassified"))
    if unclassified:
        row["unclassified"] = unclassified
    total = raw.get("total_tokens")
    row["total_tokens"] = (_count(total) if total is not None
                           else sum(row[k] for k in TOKEN_KEYS) + unclassified)
    return row


def image_rows(snapshot):
    """Per-day image_gen counts (Codex's built-in generator)."""
    out = []
    for src in _sources(snapshot):
        value = _metric(src, "image_generation")
        if value is None or not isinstance(value.get("daily_buckets"), list):
            continue
        app = app_id(str(src.get("id") or "").split("#", 1)[0])
        currency = value.get("currency")
        for raw in value["daily_buckets"]:
            if not isinstance(raw, dict) or not _day(raw.get("date")):
                continue
            images = _count(raw.get("images"))
            if not images:
                continue
            row = {"date": raw["date"], "app": app, "images": images}
            # Priced on the device that made the image, in its table currency.
            cost = _number(raw.get("estimated_cost"))
            if cost is not None and currency in CURRENCIES:
                row["estimated_cost"], row["currency"] = cost, currency
            out.append(row)
    # Oldest day first, whatever order the ledger listed them in.
    return sorted(out, key=lambda row: (row["date"], row["app"]))[:MAX_DAY_ROWS]


def credit_rows(snapshot):
    """Per-day credit spend of the local credit ledgers that record one."""
    out = []
    for src in _sources(snapshot):
        provider = str(src.get("id") or "").split("#", 1)[0]
        unit = CREDIT_LEDGERS.get(provider)
        usage = (_metric(src, "credits") or {}).get("usage")
        if unit is None or not isinstance(usage, dict) or not isinstance(usage.get("daily_buckets"), list):
            continue
        for raw in usage["daily_buckets"]:
            if not isinstance(raw, dict) or not _day(raw.get("date")):
                continue
            credits = _number(raw.get("credits"))
            if not credits:
                continue
            row = {"date": raw["date"], "app": provider, "unit": unit, "credits": credits}
            requests = _count(raw.get("requests"))
            if requests:
                row["requests"] = requests
            out.append(row)
    return sorted(out, key=lambda row: (row["date"], row["app"]))[:MAX_DAY_ROWS]


# --- accounts --------------------------------------------------------------

def account_of(src):
    """A stable, non-revealing key for the account behind a source.

    The account key is already a truncated hash (never a raw user id), so it
    is safe to carry and it lets two devices recognize the same account. The
    fallback drops the "#N" account slot: the slot index would leak how many
    accounts a provider has.
    """
    key = src.get("account_key")
    if isinstance(key, str) and key:
        return key
    source = src.get("id")
    if not isinstance(source, str) or not source:
        return None
    return source.split("#", 1)[0].split(":", 1)[0]


def provider_of(src):
    """The provider behind a source, without the account slot."""
    source = src.get("id")
    return source.split("#", 1)[0].split(":", 1)[0] if isinstance(source, str) else ""


def quota_row(raw, account, day, now):
    """One quota observation, or None when the window is unusable."""
    if not isinstance(raw, dict):
        return None
    bucket = raw.get("bucket")
    window = raw.get("window")
    if not isinstance(bucket, str) or not bucket or len(bucket) > 64:
        return None
    if not isinstance(window, str) or not window or len(window) > 32:
        return None
    row = {"account": account, "bucket": bucket, "window": window,
           "day": day, "observed_at": float(now)}
    for key in ("used_percent", "remaining_percent", "window_minutes"):
        number = raw.get(key)
        if isinstance(number, bool) or not isinstance(number, (int, float)) or number < 0:
            row[key] = None
        else:
            row[key] = number
    row["resets_at"] = _epoch(raw.get("resets_at"))
    return row


def quota_rows(snapshot, now):
    """One quota observation per account per window, dated to the local day."""
    day = _local_day(now)
    rows = []
    for src in _sources(snapshot):
        entry = (src.get("metrics") or {}).get("quota") or {}
        if entry.get("status") not in QUOTA_STATUSES:
            continue
        value = entry.get("value")
        if not isinstance(value, list):
            continue
        account = account_of(src)
        if not account:
            continue
        for raw in value:
            row = quota_row(raw, account, day, now)
            if row is not None:
                rows.append(row)
    return rows[:MAX_QUOTA_ROWS]


def _credit_row(raw):
    """A balance row reduced to the known fields, or None when it has none."""
    if not isinstance(raw, dict):
        return None
    out = {}
    for key in CREDIT_TEXT:
        text = _text(raw.get(key), 64)
        if text is not None:
            out[key] = text
    for key in CREDIT_NUMBERS:
        # A provider balance may be overdrawn; the rest are amounts spent or held.
        number = _number(raw.get(key), negative=(key == "balance"))
        if number is not None:
            out[key] = number
    if raw.get("unlimited") is True:
        out["unlimited"] = True
    buckets = []
    for bucket in (raw.get("buckets") or [])[:20]:
        balance = _number(bucket.get("balance")) if isinstance(bucket, dict) else None
        if balance is None:
            continue
        entry = {"balance": balance}
        kind = _text(bucket.get("type"), 16)
        if kind is not None:
            entry["type"] = kind
        expiry = _epoch(bucket.get("expires_at"))
        if expiry is not None:
            entry["expires_at"] = expiry
        buckets.append(entry)
    if buckets:
        out["buckets"] = buckets
    return out or None


def _credits(src):
    entry = (src.get("metrics") or {}).get("credits") or {}
    value = entry.get("value")
    if entry.get("status") not in USABLE or value is None:
        return []
    if isinstance(value, dict) and isinstance(value.get("rows"), list):
        value = value["rows"]
    raws = value if isinstance(value, list) else [value]
    out = []
    for raw in raws[:MAX_CREDIT_ROWS]:
        row = _credit_row(raw)
        if row is not None:
            out.append(row)
    return out


def _reset_cards(src):
    value = _metric(src, "reset_cards")
    if value is None:
        return None
    cards = [card for card in value.get("cards") or [] if isinstance(card, dict)]
    count = value.get("available_count")
    count = _count(count) if isinstance(count, int) and not isinstance(count, bool) else len(cards)
    expiries = sorted(expiry for expiry in (_epoch(card.get("expires_at")) for card in cards
                                            if card.get("status", "available") == "available")
                     if expiry is not None)
    out = {"count": count, "expiries": expiries[:MAX_CARD_EXPIRIES]}
    state = _text(value.get("details_state"), 16)
    if state is not None:
        out["details"] = state
    return out


def _account_row(src, account, observed):
    row = {"account": account, "provider": provider_of(src), "status": src.get("status"),
           "observed_at": observed}
    subscription = src.get("subscription")
    subscription = subscription if isinstance(subscription, dict) else {}
    plan = _text(subscription.get("plan"), 80)
    if plan is not None:
        row["plan"] = plan
    if _day(subscription.get("ends_on")):
        row["ends_on"] = subscription["ends_on"]
    if isinstance(subscription.get("auto_renew"), bool):
        row["auto_renew"] = subscription["auto_renew"]
    renewal = _metric(src, "renewal_time") or {}
    if _day(renewal.get("date")):
        row["renewal_date"] = renewal["date"]
    amount = _metric(src, "renewal_amount") or {}
    number = _number(amount.get("amount"))
    if number is not None:
        row["renewal_amount"] = number
        currency = amount.get("currency")
        if currency in CURRENCIES:
            row["renewal_currency"] = currency
    refresh = _metric(src, "credit_refresh_time") or {}
    if _day(refresh.get("date")):
        row["credit_refresh_date"] = refresh["date"]
    credits = _credits(src)
    if credits:
        row["credits"] = credits
    cards = _reset_cards(src)
    if cards is not None:
        row["reset_cards"] = cards
    return row


# Fields another device can show for an account it cannot read itself.
ACCOUNT_FACTS = ("plan", "ends_on", "renewal_date", "renewal_amount", "credit_refresh_date", "credits", "reset_cards")


def account_rows(snapshot, now):
    """The account facts of every account source, newest observation per field.

    Two slots of one provider can be the same account (a website login next to
    a desktop login). Their rows are folded into one, field by field, in
    observation order, so the value seen last wins and nothing is dropped.
    """
    merged = {}
    rows = []
    for src in _sources(snapshot):
        scope = str(src.get("scope") or "")
        if scope.startswith("local_") or scope in NON_ACCOUNT_SCOPES or src.get("status") not in USABLE:
            continue
        account = account_of(src)
        if not account:
            continue
        observed = _epoch(src.get("observed_at")) or float(now)
        row = _account_row(src, account, observed)
        if not any(key in row for key in ACCOUNT_FACTS):
            continue
        rows.append(row)
    for row in sorted(rows, key=lambda r: r["observed_at"]):
        target = merged.setdefault(row["account"], {})
        # The header is refreshed with every fact-carrying row.
        target.update(row)
    return [merged[key] for key in sorted(merged)][:MAX_ACCOUNTS]


# --- rewards ---------------------------------------------------------------

def reward_rows(ledger, now, days=REWARD_DAYS):
    """Per provider and day: whether the account was checked in and what was claimed.

    The rows carry no account slot, so they cannot say how many accounts a
    provider has. ``single`` marks a provider this device holds exactly one
    account of: only then can another device tell whose day a row describes.
    """
    accounts = (ledger or {}).get("accounts") or {}
    accounts = {slot: account for slot, account in accounts.items()
                if isinstance(slot, str) and isinstance(account, dict)}
    holders = {}
    for slot in accounts:
        provider = slot.split("#", 1)[0]
        holders[provider] = holders.get(provider, 0) + 1
    cutoff = _local_day(float(now) - (days - 1) * 86400)
    out = []
    for slot in sorted(accounts):
        account = accounts[slot]
        provider = slot.split("#", 1)[0]
        checked = _epoch(account.get("checked_at"))
        days_of = account.get("days")
        for day in sorted(days_of) if isinstance(days_of, dict) else []:
            record = days_of[day]
            if day < cutoff or not isinstance(record, dict):
                continue
            claims = [claim for claim in record.get("claims") or []
                      if isinstance(claim, dict) and claim.get("result") == "ok" and _id(claim.get("item"), 80)]
            status = record.get("status") if isinstance(record.get("status"), dict) else {}
            signed = status.get("signed_in") is True or any(claim["item"] == "daily_checkin" for claim in claims)
            if not signed and not claims:
                continue   # nothing happened that day
            row = {"provider": provider, "day": day, "signed_in": signed,
                   "claimed_credits": sum(_number(claim.get("credits")) or 0 for claim in claims),
                   "single": holders[provider] == 1}
            if checked is not None:
                row["observed_at"] = checked
            items = []
            for claim in claims[:50]:
                item = {"item": claim["item"]}
                for key in ("title", "badge"):
                    text = _text(claim.get(key), 60 if key == "title" else 40)
                    if text is not None:
                        item[key] = text
                items.append(item)
            if items:
                row["claims"] = items
            out.append(row)
    return out[:MAX_REWARD_ROWS]


# --- cards and settings ----------------------------------------------------

def card_tally(snapshot):
    """How many of each card this device owns.

    Display only. The drop ledger stays local: a device that saw another
    device's tally must not conclude that a tier already dropped today.
    """
    collection = snapshot.get("collection") or {}
    cards = collection.get("cards")
    if not isinstance(cards, dict):
        return {}
    out = {}
    for card_id, entry in cards.items():
        if not isinstance(card_id, str) or not card_id or len(card_id) > 64:
            continue
        if not isinstance(entry, dict):
            continue
        out[card_id] = _count(entry.get("count"))
    return out


def clean_budget(value):
    """The budget amounts as plain numbers, or None when the shape is off.

    An empty object means "no budget" and travels too, so clearing a budget
    on one device clears it everywhere. A key that is present must be a
    positive number.
    """
    if not isinstance(value, dict) or set(value) - {"daily_cny", "weekly_cny", "anomaly_multiplier"}:
        return None
    out = {}
    for key in ("daily_cny", "weekly_cny", "anomaly_multiplier"):
        if key not in value:
            continue
        number = _number(value[key])
        if number is None or (key == "anomaly_multiplier" and number <= 0):
            return None
        out[key] = number
    return out


def clean_settings(settings):
    """Keep only the recognized, in-range device-independent settings."""
    if not isinstance(settings, dict):
        return {}
    out = {}
    theme = settings.get("theme")
    if isinstance(theme, str) and 0 < len(theme) <= 40:
        out["theme"] = theme
    threshold = settings.get("low_quota_threshold")
    if not isinstance(threshold, bool) and isinstance(threshold, (int, float)) and 0 <= threshold <= 100:
        out["low_quota_threshold"] = float(threshold)
    order = settings.get("source_order")
    if isinstance(order, list) and len(order) <= 200 and all(isinstance(x, str) and x for x in order):
        out["source_order"] = list(order)
    alerts = settings.get("alerts_enabled")
    if isinstance(alerts, bool):
        out["alerts_enabled"] = alerts
    mode = settings.get("menu_bar_mode")
    if mode in MENU_BAR_MODES:
        out["menu_bar_mode"] = mode
    budget = clean_budget(settings.get("budget"))
    if budget is not None:
        out["budget"] = budget
    return out


def clean_settings_times(times, settings):
    """When each carried setting last changed on the sending device.

    Only keys the settings actually carry get a stamp. A device decides with
    these stamps whether a remote value is newer than its own (last writer
    wins); an older build sends none, and then its settings are left alone.
    """
    if not isinstance(times, dict):
        return {}
    return {key: float(value) for key, value in times.items()
            if key in settings and _is_number(value) and value >= 0}


# --- assembly --------------------------------------------------------------

def build_payload(snapshot, device, settings=None, now=None, *, device_name=None, app_version=None,
                  quota_history=None, rewards_ledger=None, settings_times=None):
    """The redacted payload this device is willing to upload."""
    if not isinstance(device, str) or not device or len(device) > MAX_DEVICE:
        raise SourceError("invalid_device")
    if now is None:
        now = time.time()
    rows = usage_rows(snapshot, device)
    if len(rows) > MAX_ROWS:
        # Keep the most recent days: an old day is worth less than a payload
        # the service will accept.
        rows = sorted(rows, key=lambda r: (r["date"], r["app"], r["model"]))[-MAX_ROWS:]
    payload = {
        "schema": SYNC_SCHEMA,
        "device": device,
        "generated_at": float(now),
        "usage": rows,
        "quota": quota_rows(snapshot, now),
        "cards": card_tally(snapshot),
        "settings": clean_settings(settings),
    }
    # Added after the first release of schema 1; left out while empty so a
    # payload stays as small as the data in it.
    for key, value in (("device_name", _text(device_name, MAX_NAME)),
                       ("app_version", _text(app_version, MAX_VERSION))):
        if value is not None:
            payload[key] = value
    times = clean_settings_times(settings_times, payload["settings"])
    if times:
        payload["settings_times"] = times
    history = quota_history_rows(quota_history)
    if history:
        payload["quota_history"] = history
    for key, value in (("accounts", account_rows(snapshot, now)),
                       ("rewards", reward_rows(rewards_ledger, now)),
                       ("images", image_rows(snapshot)),
                       ("credits", credit_rows(snapshot))):
        if value:
            payload[key] = value
    return payload


def quota_history_rows(rows):
    """The journal's day series, newest-last order kept, capped for the payload."""
    out = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        day = row.get("day")
        peak = row.get("peak_used_percent")
        entry = dict(row)
        if not _is_number(peak):
            entry["peak_used_percent"] = row.get("used_percent")
        entry["observations"] = _count(row.get("observations"))
        if _day(day):
            out.append(entry)
    return out[:MAX_QUOTA_HISTORY]


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _parse_quota(raw):
    if not isinstance(raw, dict):
        raise SourceError("invalid_sync_payload")
    account = raw.get("account")
    bucket = raw.get("bucket")
    window = raw.get("window")
    day = raw.get("day")
    if not all(isinstance(x, str) and x for x in (account, bucket, window, day)):
        raise SourceError("invalid_sync_payload")
    if len(day) != 10 or len(account) > 128:
        raise SourceError("invalid_sync_payload")
    entry = {"account": account, "bucket": bucket, "window": window, "day": day,
             "observed_at": _epoch(raw.get("observed_at")) or 0.0}
    for key in ("used_percent", "remaining_percent", "window_minutes"):
        number = raw.get(key)
        entry[key] = number if not isinstance(number, bool) and isinstance(number, (int, float)) else None
    entry["resets_at"] = _epoch(raw.get("resets_at"))
    return entry


def _parse_history(raw):
    entry = _parse_quota(raw)
    peak = raw.get("peak_used_percent")
    entry["peak_used_percent"] = peak if _is_number(peak) else entry["used_percent"]
    entry["observations"] = _count(raw.get("observations"))
    return entry


def _parse_credit(raw):
    # A row is accepted only in its normal form, so a stored row is always
    # exactly what this build would have sent.
    if not isinstance(raw, dict) or _credit_row(raw) != raw:
        raise SourceError("invalid_sync_payload")
    return dict(raw)


def _parse_account(raw):
    if not isinstance(raw, dict):
        raise SourceError("invalid_sync_payload")
    account, provider = raw.get("account"), raw.get("provider")
    observed = _epoch(raw.get("observed_at"))
    if not _id(account, 128) or not _id(provider, 64) or observed is None:
        raise SourceError("invalid_sync_payload")
    row = {"account": account, "provider": provider, "observed_at": observed,
           "status": _text(raw.get("status"), 16) or "available"}
    plan = _text(raw.get("plan"), 80)
    if plan is not None:
        row["plan"] = plan
    for key in ("ends_on", "renewal_date", "credit_refresh_date"):
        if raw.get(key) is None:
            continue
        if not _day(raw[key]):
            raise SourceError("invalid_sync_payload")
        row[key] = raw[key]
    if raw.get("auto_renew") is not None:
        if not isinstance(raw["auto_renew"], bool):
            raise SourceError("invalid_sync_payload")
        row["auto_renew"] = raw["auto_renew"]
    amount = _number(raw.get("renewal_amount"))
    if amount is not None:
        row["renewal_amount"] = amount
        if raw.get("renewal_currency") in CURRENCIES:
            row["renewal_currency"] = raw["renewal_currency"]
    if raw.get("credits") is not None:
        if not isinstance(raw["credits"], list) or len(raw["credits"]) > MAX_CREDIT_ROWS:
            raise SourceError("invalid_sync_payload")
        row["credits"] = [_parse_credit(item) for item in raw["credits"]]
    if raw.get("reset_cards") is not None:
        cards = raw["reset_cards"]
        expiries = cards.get("expiries") if isinstance(cards, dict) else None
        if not isinstance(expiries, list) or len(expiries) > MAX_CARD_EXPIRIES \
                or any(not _is_number(x) for x in expiries) \
                or not _is_number(cards.get("count")):
            raise SourceError("invalid_sync_payload")
        row["reset_cards"] = {"count": _count(cards["count"]), "expiries": sorted(expiries)}
        details = _text(cards.get("details"), 16)
        if details is not None:
            row["reset_cards"]["details"] = details
    return row


def _parse_reward(raw):
    if not isinstance(raw, dict) or not _id(raw.get("provider"), 64) or not _day(raw.get("day")) \
            or not isinstance(raw.get("signed_in"), bool) or not isinstance(raw.get("single"), bool):
        raise SourceError("invalid_sync_payload")
    row = {"provider": raw["provider"], "day": raw["day"], "signed_in": raw["signed_in"], "single": raw["single"],
           "claimed_credits": _number(raw.get("claimed_credits")) or 0}
    observed = _epoch(raw.get("observed_at"))
    if observed is not None:
        row["observed_at"] = observed
    if raw.get("claims") is not None:
        claims = raw["claims"]
        if not isinstance(claims, list) or len(claims) > 50:
            raise SourceError("invalid_sync_payload")
        row["claims"] = []
        for claim in claims:
            if not isinstance(claim, dict) or not _id(claim.get("item"), 80):
                raise SourceError("invalid_sync_payload")
            item = {"item": claim["item"]}
            for key, limit in (("title", 60), ("badge", 40)):
                if claim.get(key) is not None:
                    text = _text(claim.get(key), limit)
                    if text is None or text != claim[key]:
                        raise SourceError("invalid_sync_payload")
                    item[key] = text
            row["claims"].append(item)
    return row


def _parse_day_row(raw):
    if not isinstance(raw, dict) or not _day(raw.get("date")) or not _id(raw.get("app"), 64):
        raise SourceError("invalid_sync_payload")
    return raw


def _parse_image(raw):
    row = _parse_day_row(raw)
    if not _is_number(row.get("images")):
        raise SourceError("invalid_sync_payload")
    out = {"date": row["date"], "app": row["app"], "images": _count(row["images"])}
    cost = _number(row.get("estimated_cost"))
    if row.get("currency") in CURRENCIES and cost is not None:
        out["estimated_cost"], out["currency"] = cost, row["currency"]
    return out


def _parse_credit_usage(raw):
    row = _parse_day_row(raw)
    credits = _number(row.get("credits"))
    if credits is None or not credits or row.get("unit") not in CREDIT_LEDGERS.values():
        raise SourceError("invalid_sync_payload")
    out = {"date": row["date"], "app": row["app"], "unit": row["unit"], "credits": credits}
    requests = _count(row.get("requests"))
    if requests:
        out["requests"] = requests
    return out


def _parse_list(payload, key, limit, parse):
    """Every entry of an optional list section, parsed; a bad entry refuses all."""
    value = payload.get(key)
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > limit:
        raise SourceError("invalid_sync_payload")
    return [parse(raw) for raw in value]


def parse_payload(payload):
    """Validate a decrypted payload from another device.

    Strict on purpose. A payload is machine-generated, so a malformed row
    means corruption; refusing it is safer than silently storing a partial
    record that would replace a device's whole history. A section the sender
    did not include (an older build, or nothing to report) simply stays empty.

    Returns the record to store for that device. The device id is taken from
    the payload, never from a row, so a row cannot claim to be another device.
    """
    if not isinstance(payload, dict) or payload.get("schema") != SYNC_SCHEMA:
        raise SourceError("invalid_sync_payload")
    device = payload.get("device")
    if not isinstance(device, str) or not device or len(device) > MAX_DEVICE:
        raise SourceError("invalid_device")
    usage = payload.get("usage")
    if not isinstance(usage, list) or len(usage) > MAX_ROWS:
        raise SourceError("invalid_sync_payload")
    rows = []
    for raw in usage:
        app = raw.get("app") if isinstance(raw, dict) else None
        row = usage_row(raw, app if isinstance(app, str) else "", device)
        if row is None:
            raise SourceError("invalid_sync_payload")
        rows.append(row)
    cards = payload.get("cards")
    cards_out = {}
    if cards is not None:
        if not isinstance(cards, dict) or len(cards) > 500:
            raise SourceError("invalid_sync_payload")
        for card_id, count in cards.items():
            if not isinstance(card_id, str) or not card_id or len(card_id) > 64:
                raise SourceError("invalid_sync_payload")
            cards_out[card_id] = _count(count)
    record = {"device": device, "rows": rows,
              "quota": _parse_list(payload, "quota", MAX_QUOTA_ROWS, _parse_quota),
              "cards": cards_out, "settings": clean_settings(payload.get("settings"))}
    record["settings_times"] = clean_settings_times(payload.get("settings_times"), record["settings"])
    for key, limit, parse in (("quota_history", MAX_QUOTA_HISTORY, _parse_history),
                              ("accounts", MAX_ACCOUNTS, _parse_account),
                              ("rewards", MAX_REWARD_ROWS, _parse_reward),
                              ("images", MAX_DAY_ROWS, _parse_image),
                              ("credits", MAX_DAY_ROWS, _parse_credit_usage)):
        record[key] = _parse_list(payload, key, limit, parse)
    name = _text(payload.get("device_name"), MAX_NAME)
    version = _text(payload.get("app_version"), MAX_VERSION)
    if name is not None:
        record["name"] = name
    if version is not None:
        record["app_version"] = version
    record["generated_at"] = _epoch(payload.get("generated_at"))
    return record
