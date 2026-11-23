"""This device's own quota history, kept so sync can carry it.

A snapshot only holds the latest quota observation. Without a journal every
upload would replace the previous one and no device would ever see more than
today's numbers. The journal keeps one row per account, window and day: the
latest observation of that day plus the day's peak usage.

It is written only once this installation has paired. The file is created by
the first sync payload and removed when sync is reset, so a device that never
syncs keeps no extra file and the collection hook stays a no-op.
"""
import json
import threading
from datetime import datetime
from pathlib import Path

from .model import DISPLAY_ZONE

JOURNAL_NAME = "quota-history.json"
JOURNAL_SCHEMA = 1
DAYS = 35
# The payload route and the collection hook can fold observations at the same
# time; one lock keeps each read-modify-write atomic.
_lock = threading.Lock()


def journal_path(runtime_dir):
    return Path(runtime_dir) / JOURNAL_NAME


def day_of(epoch):
    return datetime.fromtimestamp(float(epoch), DISPLAY_ZONE).date().isoformat()


def _load(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    days = data.get("days") if isinstance(data, dict) and data.get("schema") == JOURNAL_SCHEMA else None
    if not isinstance(days, dict):
        return {}
    # {day: {row key: entry}}; anything that is not a day of entries is dropped.
    return {day: entries for day, entries in days.items()
            if isinstance(day, str) and isinstance(entries, dict)}


def _save(path, days):
    # Deferred like sync_store: collector pulls in the whole source registry.
    from .collector import atomic_json

    atomic_json(path, {"schema": JOURNAL_SCHEMA, "days": days})


def _series(journal):
    """Every journal row as a plain sync row, oldest day first."""
    out = []
    for day in sorted(journal):
        entries = journal[day] or {}
        for key in sorted(entries):
            entry = entries[key]
            if isinstance(entry, dict):
                out.append({field: value for field, value in entry.items() if field != "observations"})
    return out


def record(runtime_dir, rows, now, days=DAYS, create=False):
    """Fold one observation set into the journal and return the day series.

    ``rows`` are today's quota observations (``sync_payload.quota_rows``). The
    latest values replace the day's earlier ones; the peak only ever rises.
    Without a journal (never paired) nothing is written and the series is
    empty, unless ``create`` says this call builds the first sync payload.
    """
    with _lock:
        path = journal_path(runtime_dir)
        existed = path.exists()
        if not existed and not create:
            return []
        journal = _load(path)
        today = day_of(now)
        cutoff = day_of(float(now) - (days - 1) * 86400)
        kept = {day: entries for day, entries in journal.items() if day >= cutoff}
        # A day outside the window is dropped, and a new journal starts here.
        changed = len(kept) != len(journal) or not existed
        bucket = kept.setdefault(today, {})
        for row in rows or []:
            account, name, window = row.get("account"), row.get("bucket"), row.get("window")
            if not all(isinstance(value, str) and value for value in (account, name, window)):
                continue
            key = "%s|%s|%s" % (account, name, window)
            entry = bucket.get(key)
            observed = row.get("observed_at") or 0.0
            if entry is None:
                used = row.get("used_percent")
                bucket[key] = dict(row, day=today, peak_used_percent=used, observations=1)
                changed = True
                continue
            if observed >= (entry.get("observed_at") or 0.0):
                for field in ("observed_at", "used_percent", "remaining_percent", "window_minutes", "resets_at"):
                    entry[field] = row.get(field)
                entry["observations"] = _count(entry.get("observations")) + 1
                changed = True
            used = row.get("used_percent")
            if _is_number(used):
                peak = entry.get("peak_used_percent")
                if not _is_number(peak) or used > peak:
                    entry["peak_used_percent"] = used
                    changed = True
        if changed:
            _save(path, kept)
        return _series(kept)


def series(runtime_dir):
    """The stored day series, without touching the file."""
    with _lock:
        return _series(_load(journal_path(runtime_dir)))


def clear(runtime_dir):
    """Forget the history (the user left the sync space)."""
    with _lock:
        try:
            journal_path(runtime_dir).unlink()
        except OSError:
            pass


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _count(value):
    return value if _is_number(value) and isinstance(value, int) and value >= 0 else 0
