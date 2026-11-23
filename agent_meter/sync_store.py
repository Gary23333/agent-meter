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
# Row sections of a device's bucket. A bucket written before a section existed
# simply lacks it, so every reader goes through ``section()``.
SECTIONS = ("rows", "quota", "quota_history", "accounts", "rewards", "images", "credits")


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
        "devices": {device: bucket for device, bucket in (devices or {}).items()
                    if isinstance(device, str) and isinstance(bucket, dict)} if isinstance(devices, dict) else {},
    }


def save_store(runtime_dir, store):
    # Deferred like prices.py and model_catalog.py: collector pulls in the
    # whole source registry, and this module must stay cheap to import.
    from .collector import atomic_json

    atomic_json(store_path(runtime_dir), store)
    return store


def section(bucket, name):
    """One row section of a device's bucket; always a list."""
    rows = (bucket or {}).get(name)
    return rows if isinstance(rows, list) else []


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
    bucket = {name: list(record.get(name) or []) for name in SECTIONS}
    bucket.update({
        "cards": dict(record.get("cards") or {}),
        "settings": dict(record.get("settings") or {}),
        "settings_times": dict(record.get("settings_times") or {}),
        "name": record.get("name") or "",
        "app_version": record.get("app_version") or "",
        "generated_at": record.get("generated_at"),
        "updated_at": record.get("updated_at"),
    })
    store["devices"][device] = bucket
    return save_store(runtime_dir, store)


def forget_device(runtime_dir, device, local_device=None):
    """Drop one remote device (the user removed it from the space)."""
    store = load_store(runtime_dir)
    if local_device and device == local_device:
        raise ValueError("own_device")
    store["devices"].pop(device, None)
    return save_store(runtime_dir, store)


def reset(runtime_dir):
    """Forget every remote device (the user turned sync off).

    The local device id stays: it is who this installation is, not something
    another device may repoint.
    """
    store = load_store(runtime_dir)
    store["devices"] = {}
    return save_store(runtime_dir, store)


def remote_rows(store, name):
    """(device, row) for every row of one section, over every remote device."""
    local = store.get("local_device") or ""
    for device in sorted(store.get("devices") or {}):
        if device == local:
            continue
        bucket = store["devices"][device] or {}
        for row in section(bucket, name):
            if isinstance(row, dict):
                yield device, row


def device_names(store):
    """{device: name} as each device announced itself."""
    return {device: (bucket or {}).get("name") or ""
            for device, bucket in (store.get("devices") or {}).items()}


def history(store, local_rows=None):
    """Local rows plus every remote device's rows, one flat list.

    Rows are per device and add up across devices: they are what each machine
    spent. Two devices that read the same local ledger would count it twice;
    that is the user's own setup, not something the store can detect.
    """
    rows = list(local_rows or [])
    for device, row in remote_rows(store, "rows"):
        rows.append(row)
    return rows


def _quota_key(row):
    return (row.get("account"), row.get("bucket"), row.get("window"), row.get("day"))


def quota_history(store, local_quota=None):
    """One quota observation per account, window and day.

    The same account seen from two devices is still one quota, so the most
    recent observation wins instead of the two adding up.
    """
    latest = {}
    for row in list(local_quota or []):
        if isinstance(row, dict):
            latest[_quota_key(row)] = row
    for device, row in remote_rows(store, "quota"):
        # Tag the winner with its device so the UI can tell a local
        # observation from a remote one. The stored row itself stays
        # device-independent; this is a projection-only field.
        entry = dict(row, device=device)
        previous = latest.get(_quota_key(entry))
        if previous is None or (entry.get("observed_at") or 0) >= (previous.get("observed_at") or 0):
            latest[_quota_key(entry)] = entry
    return [latest[key] for key in sorted(latest, key=lambda k: tuple(str(x) for x in k))]


def remote_quota_history(store):
    """Latest remote quota rows, even when a newer local observation wins.

    `quota_history` collapses every account/window/day to one winner for the
    account cards. That is right for the displayed percentage, but it makes a
    successful sync invisible whenever this Mac observed the same account
    later. Keep a separate remote-only view so the UI can say "another device
    also reported this window" without changing which value is authoritative.
    """
    latest = {}
    for device, row in remote_rows(store, "quota"):
        entry = dict(row, device=device)
        previous = latest.get(_quota_key(entry))
        if previous is None or (entry.get("observed_at") or 0) >= (previous.get("observed_at") or 0):
            latest[_quota_key(entry)] = entry
    return [latest[key] for key in sorted(latest, key=lambda k: tuple(str(x) for x in k))]


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def quota_series(store, local_series=None):
    """Every known day of every account window: last value and the day's peak.

    The other values come from the latest observation, which is tagged with
    its device when it came from another machine. The peak is the highest
    usage any device saw in that window that day.
    """
    latest, peaks = {}, {}

    def offer(row, tagged):
        key = _quota_key(row)
        previous = latest.get(key)
        if previous is None or (row.get("observed_at") or 0) >= (previous.get("observed_at") or 0):
            latest[key] = row if tagged else dict(row)

    for device, row in remote_rows(store, "quota_history"):
        offer(dict(row, device=device), tagged=True)
    for row in list(local_series or []):
        if isinstance(row, dict):
            offer(row, tagged=False)
    for _device, row in remote_rows(store, "quota_history"):
        if _is_number(row.get("peak_used_percent")):
            key = _quota_key(row)
            peaks[key] = max(peaks.get(key, float("-inf")), row["peak_used_percent"])
    for key, entry in latest.items():
        peak = peaks.get(key)
        if peak is not None and (not _is_number(entry.get("peak_used_percent")) or peak > entry["peak_used_percent"]):
            entry["peak_used_percent"] = peak
    return [latest[key] for key in sorted(latest, key=lambda k: tuple(str(x) for x in k))]


def account_history(store):
    """The latest account facts each device reported, newest per account.

    Remote only: a device's own accounts are read live. Every row is tagged
    with the device that saw it.
    """
    latest = {}
    for device, row in remote_rows(store, "accounts"):
        entry = dict(row, device=device)
        previous = latest.get(entry.get("account"))
        if previous is None or (entry.get("observed_at") or 0) >= (previous.get("observed_at") or 0):
            latest[entry.get("account")] = entry
    return [latest[key] for key in sorted(latest, key=lambda k: str(k))]


def reward_history(store):
    """The check-in and claim days other devices reported."""
    return [dict(row, device=device) for device, row in remote_rows(store, "rewards")]


def day_history(store, name):
    """The per-day rows (images, credits) other devices reported."""
    return [dict(row, device=device) for device, row in remote_rows(store, name)]


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
        rows = section(bucket, "rows")
        days = {row.get("date") for row in rows if isinstance(row, dict)}
        windows = {(row.get("account"), row.get("bucket"), row.get("window"))
                   for row in section(bucket, "quota") if isinstance(row, dict)}
        out.append({
            "device": device,
            "name": bucket.get("name") or "",
            "app_version": bucket.get("app_version") or "",
            "rows": len(rows),
            "days": len([d for d in days if isinstance(d, str)]),
            "cards": len(bucket.get("cards") or {}),
            "quota": len(windows),
            "accounts": len(section(bucket, "accounts")),
            "rewards": len(section(bucket, "rewards")),
            "images": sum(row.get("images", 0) for row in section(bucket, "images") if isinstance(row, dict)
                          and isinstance(row.get("images"), int)),
            "generated_at": bucket.get("generated_at"),
            "updated_at": bucket.get("updated_at"),
        })
    return out
