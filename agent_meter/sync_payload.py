"""Cloud-sync payload: a redacted projection of the local snapshot.

The sync stream carries aggregates only — per-day per-model token rollups, one
quota observation per source per day, the card tally and device-independent
settings. Per-request token detail, absolute paths, project paths, account
labels and credentials are never read here: the payload is assembled field by
field, so nothing else can leak into it by accident.

Synced rows describe other machines. They never enter the local ledgers, the
coverage matrix or the snapshot schema; they live in their own store
(`agent_meter/sync_store.py`) and are served as a separate projection.
"""

import time
from datetime import datetime

from .applications import app_id
from .model import DISPLAY_ZONE, SourceError
from .rewards import CLAIM_TIME

SYNC_SCHEMA = 1
# Token fields carried per row. "requests" is a count; the rest are tokens.
TOKEN_KEYS = ("fresh_input", "output", "reasoning", "cache_read", "cache_write")
USAGE_KEYS = ("requests",) + TOKEN_KEYS
# Settings that describe the user rather than the machine. Per-device switches
# (disabled sources, low-resource mode, skipped ledgers, project aliases) are
# deliberately absent: they are true of one computer and false of another.
SETTINGS_KEYS = ("theme", "low_quota_threshold", "source_order", "claim_time", "alerts_enabled")
TOKEN_STATUSES = {"available", "partial", "stale"}
QUOTA_STATUSES = {"available", "partial"}
MAX_DEVICE = 64
# A year of daily rows for a dozen ledgers is well under this; the cap keeps a
# payload inside the service's 8 MB blob limit.
MAX_ROWS = 20000
MAX_QUOTA_ROWS = 500


def _count(value):
    """A non-negative integer, or 0. Never raises on a malformed source row."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _epoch(value):
    """Seconds since the epoch, from a float or from a backend timestamp."""
    if isinstance(value, dict):
        value = value.get("epoch_seconds")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


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


def quota_rows(snapshot, now):
    """One quota observation per account per window, dated to the local day."""
    local = datetime.fromtimestamp(now, DISPLAY_ZONE)
    day = local.date().isoformat()
    rows = []
    for src in snapshot.get("sources") or []:
        if not isinstance(src, dict):
            continue
        metrics = src.get("metrics") or {}
        quota = metrics.get("quota") or {}
        if not isinstance(quota, dict) or quota.get("status") not in QUOTA_STATUSES:
            continue
        value = quota.get("value")
        if not isinstance(value, list):
            continue
        account = account_of(src)
        if not account:
            continue
        for raw in value:
            if not isinstance(raw, dict):
                continue
            bucket = raw.get("bucket")
            window = raw.get("window")
            if not isinstance(bucket, str) or not bucket or len(bucket) > 64:
                continue
            if not isinstance(window, str) or not window or len(window) > 32:
                continue
            row = {"account": account, "bucket": bucket, "window": window,
                   "day": day, "observed_at": float(now)}
            for key in ("used_percent", "remaining_percent", "window_minutes"):
                number = raw.get(key)
                if isinstance(number, bool) or not isinstance(number, (int, float)) or number < 0:
                    row[key] = None
                else:
                    row[key] = number
            row["resets_at"] = _epoch(raw.get("resets_at"))
            rows.append(row)
    return rows[:MAX_QUOTA_ROWS]


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
    claim_time = settings.get("claim_time")
    if isinstance(claim_time, str) and CLAIM_TIME.match(claim_time):
        out["claim_time"] = claim_time
    alerts = settings.get("alerts_enabled")
    if isinstance(alerts, bool):
        out["alerts_enabled"] = alerts
    return out


def build_payload(snapshot, device, settings=None, now=None):
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
    return {
        "schema": SYNC_SCHEMA,
        "device": device,
        "generated_at": float(now),
        "usage": rows,
        "quota": quota_rows(snapshot, now),
        "cards": card_tally(snapshot),
        "settings": clean_settings(settings),
    }


def parse_payload(payload):
    """Validate a decrypted payload from another device.

    Strict on purpose. A payload is machine-generated, so a malformed row
    means corruption; refusing it is safer than silently storing a partial
    record that would replace a device's whole history.

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
    quota = payload.get("quota")
    quota_out = []
    if quota is not None:
        if not isinstance(quota, list) or len(quota) > MAX_QUOTA_ROWS:
            raise SourceError("invalid_sync_payload")
        for raw in quota:
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
            quota_out.append(entry)
    cards = payload.get("cards")
    cards_out = {}
    if cards is not None:
        if not isinstance(cards, dict) or len(cards) > 500:
            raise SourceError("invalid_sync_payload")
        for card_id, count in cards.items():
            if not isinstance(card_id, str) or not card_id or len(card_id) > 64:
                raise SourceError("invalid_sync_payload")
            cards_out[card_id] = _count(count)
    return {"device": device, "rows": rows, "quota": quota_out, "cards": cards_out,
            "settings": clean_settings(payload.get("settings"))}
