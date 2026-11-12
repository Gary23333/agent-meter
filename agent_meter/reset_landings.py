"""Local verification layer for the global-reset forecast (B4).

Two honest, local-only channels that never write `reset_time`, never join an
account card / menu-bar scroll / local consumption, and never let a probability
raise a notification:

* Landing verification: when the existing reset signal (the same rule the pet
  uses in ``pet.recent_landing``) reports a confident global reset, freeze the
  forecast that was on screen and the observed landing time into a 0600 ledger,
  then score history against it. Announcement, observed landing and the official
  window stay three separate facts; a deviation is a derived difference, never an
  average of the facts.
* Manual announcement entry: the user can record an announcement time the
  trackers missed. It only adds the announcement-time fact (origin="manual"),
  carries no probability and no confidence, so it can never trigger a landing or
  a notification.

Both stores refuse to write when the existing file is corrupt, mirroring the
project's "a rejected import writes nothing" posture.
"""

import hashlib
import json
import math
import time
from pathlib import Path

from .model import SourceError, timestamp
from .reset_forecast import _text, merge_history

LANDINGS_NAME = "reset-forecast-landings.json"
MANUAL_NAME = "reset-forecast-manual.json"
# Local file-format marker, independent of the snapshot SCHEMA_VERSION.
STORE_SCHEMA = 1
# Same default window as pet.recent_landing.
LANDING_WINDOW_SECONDS = 86400
LANDINGS_LIMIT = 400
NOTE_LIMIT = 240


def _num(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    return None


def _epoch(stamp):
    if isinstance(stamp, dict):
        return _num(stamp.get("epoch_seconds"))
    return _num(stamp)


def _read_store(path, list_key, corrupt_code):
    p = Path(path)
    if not p.exists():
        return {"schema": STORE_SCHEMA, list_key: []}
    try:
        data = json.loads(p.read_text())
    except (OSError, ValueError):
        raise SourceError(corrupt_code) from None
    if not isinstance(data, dict) or data.get("schema") != STORE_SCHEMA \
            or not isinstance(data.get(list_key), list):
        raise SourceError(corrupt_code)
    id_key = "event_id" if list_key == "records" else "post_id"
    for row in data[list_key]:
        if not isinstance(row, dict) or not isinstance(row.get(id_key), str) or not row.get(id_key):
            raise SourceError(corrupt_code)
        if _epoch(row.get("announced_at")) is None:
            raise SourceError(corrupt_code)
    return data


def _write_store(path, payload):
    from .collector import atomic_json
    atomic_json(Path(path), payload)


# --------------------------------------------------------------------------- landing

def detect_landing(forecast, now, within=LANDING_WINDOW_SECONDS):
    # Mirrors pet.recent_landing verbatim so the pet and this ledger agree on
    # what counts as a landing; pet.py is owned elsewhere and must not change.
    events = forecast.get("history_events") if isinstance(forecast, dict) \
        and isinstance(forecast.get("history_events"), list) else []
    latest = events[0] if events and isinstance(events[0], dict) else None
    if latest and latest.get("kind") == "reset" and latest.get("confidence") in ("high", "medium"):
        at = _epoch(latest.get("announced_at"))
        if at is not None and at <= now and now - at < within:
            return latest
    return None


def forecast_snapshot(forecast, now):
    ensemble = forecast.get("ensemble") if isinstance(forecast, dict) \
        and isinstance(forecast.get("ensemble"), dict) else {}
    horizons = ensemble.get("horizons") if isinstance(ensemble.get("horizons"), dict) else {}
    bands = {}
    for horizon in ("24h", "48h"):
        band = horizons.get(horizon)
        if isinstance(band, dict):
            bands[horizon] = {"min": band.get("min"), "max": band.get("max"),
                              "weighted_median": band.get("weighted_median"), "n": band.get("n"),
                              "agreement": band.get("agreement"), "values": band.get("values")}
    sources = []
    for row in (forecast.get("sources") if isinstance(forecast, dict) else None) or []:
        if isinstance(row, dict) and row.get("status") in ("available", "stale"):
            sources.append({"source": row.get("source"), "headline_24h": row.get("headline_24h"),
                            "headline_48h": row.get("headline_48h"), "band_24h": row.get("band_24h"),
                            "band_48h": row.get("band_48h"), "weight": row.get("weight")})
    return {"captured_at": timestamp(now), "ensemble": bands, "sources": sources}


def _deviation(event, observed_epoch, observed_basis):
    window = event.get("official_window") if isinstance(event.get("official_window"), dict) else {}
    close, opened = _epoch(window.get("close_at")), _epoch(window.get("open_at"))
    announced = _epoch(event.get("announced_at"))
    within = None
    if opened is not None and close is not None and observed_epoch is not None:
        within = opened <= observed_epoch <= close
    if close is not None and observed_epoch is not None:
        return {"seconds": round(observed_epoch - close, 1),
                "expected_basis": "official_window_close", "within_official_window": within}
    if observed_basis == "effective_at" and announced is not None and observed_epoch is not None:
        return {"seconds": round(observed_epoch - announced, 1),
                "expected_basis": "announced_at", "within_official_window": within}
    return {"seconds": None, "expected_basis": None, "within_official_window": within}


def record_landing(store_path, forecast, now, within=LANDING_WINDOW_SECONDS):
    """Freeze one landing record; the first observation of an event wins."""
    event = detect_landing(forecast, now, within)
    if event is None:
        return None
    event_id = event.get("post_id")
    if not isinstance(event_id, str) or not event_id:
        return None
    store = _read_store(store_path, "records", "landing_store_corrupt")
    for existing in store["records"]:
        if existing.get("event_id") == event_id:
            return existing
    effective_epoch = _epoch(event.get("effective_at"))
    observed = event.get("effective_at") if effective_epoch is not None else event.get("announced_at")
    observed_basis = "effective_at" if effective_epoch is not None else "announced_at"
    record = {"event_id": event_id, "announced_at": event.get("announced_at"),
              "observed_at": observed, "observed_basis": observed_basis,
              "forecast": forecast_snapshot(forecast, now),
              "deviation": _deviation(event, _epoch(observed), observed_basis),
              "sources": event.get("sources") if isinstance(event.get("sources"), list) else [],
              "recorded_at": timestamp(now)}
    store["records"].append(record)
    store["records"].sort(key=lambda r: _epoch(r.get("announced_at")) or 0, reverse=True)
    del store["records"][LANDINGS_LIMIT:]
    _write_store(store_path, store)
    return record


def _distribution(values):
    if not values:
        return {"count": 0, "min": None, "max": None, "median": None, "mean": None}
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    median = ordered[mid] if n % 2 else round((ordered[mid - 1] + ordered[mid]) / 2, 4)
    return {"count": n, "min": ordered[0], "max": ordered[-1],
            "median": median, "mean": round(sum(ordered) / n, 4)}


def landing_scorecard(store_path):
    store = _read_store(store_path, "records", "landing_store_corrupt")
    records = store["records"]
    deviations, lag, med24, med48, flags = [], [], [], [], []
    for record in records:
        deviation = record.get("deviation") if isinstance(record.get("deviation"), dict) else {}
        if isinstance(deviation.get("seconds"), (int, float)) and not isinstance(deviation.get("seconds"), bool):
            deviations.append(deviation["seconds"])
        if isinstance(deviation.get("within_official_window"), bool):
            flags.append(deviation["within_official_window"])
        if record.get("observed_basis") == "effective_at":
            announced, observed = _epoch(record.get("announced_at")), _epoch(record.get("observed_at"))
            if announced is not None and observed is not None:
                lag.append(round(observed - announced, 1))
        snapshot = record.get("forecast") if isinstance(record.get("forecast"), dict) else {}
        ensemble = snapshot.get("ensemble") if isinstance(snapshot.get("ensemble"), dict) else {}
        for horizon, bucket in (("24h", med24), ("48h", med48)):
            band = ensemble.get(horizon)
            if isinstance(band, dict) and isinstance(band.get("weighted_median"), (int, float)) \
                    and not isinstance(band.get("weighted_median"), bool):
                bucket.append(band["weighted_median"])
    hits = sum(1 for flag in flags if flag)
    return {"schema": STORE_SCHEMA, "n_records": len(records), "window_hits": hits,
            "n_with_window": len(flags), "window_hit_rate": round(hits / len(flags), 4) if flags else None,
            "deviation_seconds": _distribution(deviations),
            "announcement_to_landing_seconds": _distribution(lag),
            "weighted_median_24h": _distribution(med24), "weighted_median_48h": _distribution(med48),
            "records": records}


# --------------------------------------------------------------------------- manual

def _manual_event(stamp, note, added_at):
    # No X status ID exists for a manual fact, so identity is the announcement
    # instant plus the note; identical time+note is the same entry.
    epoch = float(stamp["epoch_seconds"])
    digest = hashlib.sha256(("%r|%s" % (epoch, note or "")).encode("utf-8")).hexdigest()[:16]
    return {"post_id": "manual:" + digest, "origin": "manual", "kind": "reset",
            "announced_at": stamp, "effective_at": None, "official_window": None,
            "scope": None, "confidence": None, "confirmed": None, "banked_grant": None,
            "summary": note, "url": None, "sources": ["manual"], "added_at": added_at}


def add_manual_announcement(store_path, announced_at, note):
    """Record an announcement time (epoch seconds); adds no probability or clock."""
    try:
        stamp = timestamp(announced_at)
    except SourceError:
        raise SourceError("manual_announcement_invalid") from None
    if stamp is None:
        raise SourceError("manual_announcement_invalid")
    clean_note = _text(note, NOTE_LIMIT)
    store = _read_store(store_path, "announcements", "manual_store_corrupt")
    event = _manual_event(stamp, clean_note, timestamp(time.time()))
    for existing in store["announcements"]:
        if existing.get("post_id") == event["post_id"]:
            return existing
    store["announcements"].append(event)
    store["announcements"].sort(key=lambda e: _epoch(e.get("announced_at")) or 0, reverse=True)
    _write_store(store_path, store)
    return event


def load_manual_announcements(store_path):
    return list(_read_store(store_path, "announcements", "manual_store_corrupt")["announcements"])


def merge_manual_history(per_source, manual_events):
    combined = dict(per_source or {})
    if manual_events:
        combined["manual"] = list(manual_events)
    return merge_history(combined)