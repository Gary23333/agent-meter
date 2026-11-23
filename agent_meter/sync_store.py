"""Local store for what other devices sent us.

Synced rows live here, not in the snapshot: they describe other machines, so
they must not enter the local ledgers, the coverage matrix or the snapshot
schema. One bucket per remote device, replaced wholesale when that device
pushes a new payload — a device's own rows are always read from the live
snapshot, never from this file.
"""

import json
from pathlib import Path

STORE_NAME = "synced-history.json"
STORE_SCHEMA = 1


def store_path(runtime_dir):
    return Path(runtime_dir) / STORE_NAME


def _empty():
    return {"schema": STORE_SCHEMA, "local_device": "", "devices": {}}


def load_store(runtime_dir):
    """The stored remote buckets; a missing or damaged file reads as empty."""
    try:
        value = json.loads(store_path(runtime_dir).read_text())
    except (OSError, ValueError):
        return _empty()
    if not isinstance(value, dict) or value.get("schema") != STORE_SCHEMA:
        return _empty()
    devices = value.get("devices")
    local = value.get("local_device")
    return {
        "schema": STORE_SCHEMA,
        "local_device": local if isinstance(local, str) else "",
        "devices": devices if isinstance(devices, dict) else {},
    }


def save_store(runtime_dir, store):
    # Deferred like prices.py and model_catalog.py: collector pulls in the
    # whole source registry, and this module must stay cheap to import.
    from .collector import atomic_json

    atomic_json(store_path(runtime_dir), store)
    return store


def set_local_device(runtime_dir, device):
    """Remember which device this installation is."""
    if not isinstance(device, str) or not device:
        return load_store(runtime_dir)
    store = load_store(runtime_dir)
    if store["local_device"] != device:
        store["local_device"] = device
        try:
            save_store(runtime_dir, store)
        except OSError:
            pass
    return store


def replace_device(runtime_dir, record, local_device=None):
    """Store one remote device's payload, replacing whatever it had before.

    A payload from this device is dropped: the local snapshot is authoritative
    for it, and storing it would let a stale copy shadow the live numbers.
    """
    store = load_store(runtime_dir)
    device = record.get("device")
    if not isinstance(device, str) or not device:
        raise ValueError("invalid_device")
    if local_device and device == local_device:
        return store
    store["devices"][device] = {
        "rows": record.get("rows") or [],
        "quota": record.get("quota") or [],
        "cards": record.get("cards") or {},
        "settings": record.get("settings") or {},
        "updated_at": record.get("updated_at"),
    }
    return save_store(runtime_dir, store)


def reset(runtime_dir):
    """Forget every remote device (the user turned sync off).

    The local device id stays: it is who this installation is, not something
    another device may repoint.
    """
    store = load_store(runtime_dir)
    store["devices"] = {}
    return save_store(runtime_dir, store)


def history(store, local_rows=None):
    """Local rows plus every remote device's rows, one flat list.

    Rows are per device and add up across devices: they are what each machine
    spent. Two devices that read the same local ledger would count it twice;
    that is the user's own setup, not something the store can detect.
    """
    rows = list(local_rows or [])
    devices = store.get("devices") or {}
    for device in sorted(devices):
        bucket = devices[device] or {}
        for row in bucket.get("rows") or []:
            rows.append(row)
    return rows


def quota_history(store, local_quota=None):
    """One quota observation per account, window and day.

    The same account seen from two devices is still one quota, so the most
    recent observation wins instead of the two adding up.
    """
    latest = {}
    for row in list(local_quota or []):
        key = (row.get("account"), row.get("bucket"), row.get("window"), row.get("day"))
        latest[key] = row
    for device in sorted(store.get("devices") or {}):
        bucket = store["devices"][device] or {}
        for row in bucket.get("quota") or []:
            # Tag the winner with its device so the UI can tell a local
            # observation from a remote one. The stored row itself stays
            # device-independent; this is a projection-only field.
            entry = dict(row, device=device)
            key = (entry.get("account"), entry.get("bucket"), entry.get("window"), entry.get("day"))
            previous = latest.get(key)
            if previous is None or (entry.get("observed_at") or 0) >= (previous.get("observed_at") or 0):
                latest[key] = entry
    return [latest[key] for key in sorted(latest, key=lambda k: tuple(str(x) for x in k))]


def card_history(store, local_cards=None):
    """The card counts the known devices report, as an upper bound.

    The drop ledger stays local, so this is a display figure: it never feeds
    back into whether a tier already dropped today.
    """
    counts = dict(local_cards or {})
    for device in sorted(store.get("devices") or {}):
        bucket = store["devices"][device] or {}
        for card_id, count in (bucket.get("cards") or {}).items():
            if isinstance(count, int) and not isinstance(count, bool):
                counts[card_id] = max(counts.get(card_id, 0), count)
    return counts


def device_summaries(store):
    """What each remote device last sent, for the sync status view."""
    out = []
    for device, bucket in sorted((store.get("devices") or {}).items()):
        bucket = bucket or {}
        rows = bucket.get("rows") or []
        days = {row.get("date") for row in rows if isinstance(row, dict)}
        out.append({
            "device": device,
            "rows": len(rows),
            "days": len([d for d in days if isinstance(d, str)]),
            "cards": len(bucket.get("cards") or {}),
            "updated_at": bucket.get("updated_at"),
        })
    return out
