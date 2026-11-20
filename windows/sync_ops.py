"""Windows side of the cloud-sync protocol.

The master key never reaches this module from disk: the C# shell reads it from
Windows Credential Manager and passes it on stdin for the one operation that
needs it. The service only stores ciphertext.

Payloads reuse `agent_meter.sync_payload`: the same redaction rules, the same
caps and the same validation as the Mac client. Remote rows land in
`agent_meter.sync_store` and never enter the local snapshot or ledgers.
"""

import json
import time
from pathlib import Path

from agent_meter.sync_crypto import (PairingCode, PairingCrypto, SyncCryptoError, SyncKeys,
                                     b64_standard_decode, b64_standard_encode, is_space_id)
from agent_meter.sync_payload import build_payload, clean_settings, parse_payload
from agent_meter.sync_remote import SyncRemoteError, SyncService
from agent_meter.sync_store import replace_device, reset, set_local_device

MAX_INPUT = 64 * 1024
PAIR_POLL_SECONDS = 1.0
# The server's slots live five minutes; stop a little early so the UI can say
# "expired" before the next poll starts.
PAIR_DEADLINE_SLACK = 2.0

# Windows history keys are display names; sync rows use the canonical ids the
# Mac collectors emit, so both machines compare the same application.
APP_IDS = {
    "Codex": "codex",
    "Claude Code": "claude",
    "Gemini CLI": "gemini",
    "WorkBuddy": "workbuddy",
    "ZCode": "zcode",
    "DeepSeek Harness": "dsh",
    "Kimi Code": "kimi",
    "Kimi CLI (旧版)": "kimi_legacy",
    "OpenCode": "opencode",
    "MiniMax Code": "mcode",
    "MiMo Code": "mimo_code",
    "DevECo": "deveco",
}


def runtime_dir():
    import os

    local = os.environ.get("LOCALAPPDATA")
    if not local or not Path(local).is_absolute():
        return None
    return Path(local) / "AgentMeter"


def _text(value, limit, allow_empty=False):
    if not isinstance(value, str) or len(value) > limit or (not allow_empty and not value):
        return None
    return value


def _int(value, default=0):
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value else default


def _master_key(value):
    raw = b64_standard_decode(value)
    if raw is None or len(raw) != 32:
        raise SyncCryptoError("invalid_master_key")
    return raw


def parse_request(raw):
    """Strict-ish input: only the fields a command uses, bounded in size."""
    if not isinstance(raw, str) or len(raw) > MAX_INPUT:
        raise ValueError("sync input too large")
    value = json.loads(raw.lstrip("\ufeff"))
    if not isinstance(value, dict):
        raise ValueError("invalid sync input")
    return value


def _keys(request):
    space = request.get("space_id")
    if not is_space_id(space):
        raise SyncCryptoError("invalid_space_id")
    return SyncKeys(_master_key(request.get("master_key")), space)


def _device(request):
    device = request.get("device_id")
    if not is_space_id(device):
        raise SyncCryptoError("invalid_device")
    return device


def _service(request):
    return SyncService(_text(request.get("base_url"), 200) or "")


def _emit(emit, value):
    emit(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def create_space(request, emit):
    keys = _keys(request)
    device = _device(request)
    space = _service(request).create_space(keys.space_id, keys.auth_token, keys.auth_hash)
    if space != keys.space_id:
        raise SyncRemoteError("invalid_response")
    _emit(emit, {"status": "ok", "space_id": space, "device_id": device,
                 "space_short": space[:8]})
    return 0


def devices(request, emit):
    keys = _keys(request)
    entries = _service(request).manifest(keys.space_id, keys.auth_token)
    _emit(emit, {"status": "ok", "space_id": keys.space_id, "devices": entries})
    return 0


def _import_blobs(service, keys, device, manifest):
    imported, failed = [], []
    for entry in manifest:
        remote = entry.get("device_id")
        if not isinstance(remote, str) or remote == device:
            continue
        try:
            sealed = service.blob(keys.space_id, remote, keys.auth_token)
            plain = json.loads(keys.open(sealed))
            record = parse_payload(plain)
            record["updated_at"] = time.time()
            replace_device(runtime_dir(), record, device)
            imported.append(remote)
        except (SyncCryptoError, SyncRemoteError, ValueError, UnicodeDecodeError, OSError):
            failed.append(remote)
    return imported, failed


def _report(space, manifest, imported, failed, uploaded):
    return {"status": "ok", "space_id": space, "uploaded": uploaded,
            "devices": len(manifest), "imported": imported, "failed": failed}


def push(request, emit, snapshot=None):
    keys = _keys(request)
    device = _device(request)
    directory = runtime_dir()
    if directory is None:
        raise OSError("sync_directory_unavailable")
    service = _service(request)
    settings = clean_settings(request.get("settings"))
    if snapshot is None:
        from windows.backend import collect

        snapshot = windows_snapshot(collect(False))
    payload = build_payload(snapshot, device, settings)
    sealed = keys.seal(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    service.put(keys.space_id, device, keys.auth_token, sealed)
    set_local_device(directory, device)
    manifest = service.manifest(keys.space_id, keys.auth_token)
    imported, failed = _import_blobs(service, keys, device, manifest)
    _emit(emit, _report(keys.space_id, manifest, imported, failed, True))
    return 0


def pull(request, emit):
    keys = _keys(request)
    device = _device(request)
    directory = runtime_dir()
    if directory is None:
        raise OSError("sync_directory_unavailable")
    service = _service(request)
    set_local_device(directory, device)
    manifest = service.manifest(keys.space_id, keys.auth_token)
    imported, failed = _import_blobs(service, keys, device, manifest)
    _emit(emit, _report(keys.space_id, manifest, imported, failed, False))
    return 0


def remove_device(request, emit):
    keys = _keys(request)
    local = _device(request)
    remote = request.get("remote_device_id")
    if not is_space_id(remote) or remote == local:
        raise SyncCryptoError("invalid_device")
    _service(request).delete(keys.space_id, remote, keys.auth_token)
    _emit(emit, {"status": "ok", "space_id": keys.space_id, "removed": remote})
    return 0


def reset_local(request, emit):
    directory = runtime_dir()
    if directory is None:
        raise OSError("sync_directory_unavailable")
    reset(directory)
    _emit(emit, {"status": "ok", "reset": True})
    return 0


def pair_create(request, emit):
    keys = _keys(request)
    device = _device(request)
    service = _service(request)
    private, public = PairingCrypto.new_key_pair()
    slot = service.create_slot(keys.space_id, keys.auth_token, public)
    code = PairingCode.normalize(slot.get("code"))
    if code is None:
        raise SyncRemoteError("invalid_response")
    _emit(emit, {"event": "code", "code": code, "slot_id": slot["slot_id"],
                 "expires_at": slot["expires_at"], "device_id": device})
    deadline = float(slot["expires_at"]) - PAIR_DEADLINE_SLACK
    while True:
        if time.time() >= deadline:
            _emit(emit, {"event": "expired", "code": code})
            return 0
        try:
            state = service.slot_state(slot["slot_id"], keys.auth_token)
        except SyncRemoteError as error:
            if error.code in ("not_found", "expired"):
                _emit(emit, {"event": "expired", "code": code})
                return 0
            raise
        public_b = state.get("pub_b")
        if isinstance(public_b, bytes) and len(public_b) == 32:
            shared = PairingCrypto.shared_secret(private, public_b)
            wrap = PairingCrypto.wrap_key(shared, slot["slot_id"])
            if not isinstance(state.get("ciphertext"), (bytes, bytearray)):
                ciphertext = PairingCrypto.seal(keys.space_id, keys.master_key, wrap)
                try:
                    service.seal(slot["slot_id"], keys.auth_token, ciphertext)
                except SyncRemoteError as error:
                    if error.code in ("not_found", "expired"):
                        _emit(emit, {"event": "expired", "code": code})
                        return 0
                    raise
            sas = PairingCrypto.sas(shared, slot["slot_id"])
            _emit(emit, {"event": "paired", "code": code, "sas": sas})
            # Do not consume the slot here: the joining device may still be
            # polling for the sealed key. It expires on its own shortly.
            return 0
        time.sleep(PAIR_POLL_SECONDS)


def pair_join(request, emit):
    code = PairingCode.normalize(request.get("code"))
    if code is None:
        raise SyncCryptoError("invalid_code")
    service = _service(request)
    lookup = service.lookup(code)
    space = lookup.get("space_id")
    if not is_space_id(space):
        raise SyncRemoteError("invalid_response")
    public_a = _decode_public(lookup.get("pub_a"))
    private, public = PairingCrypto.new_key_pair()
    shared = PairingCrypto.shared_secret(private, public_a)
    try:
        service.join(lookup["slot_id"], lookup["join_token"], public)
    except SyncRemoteError as error:
        if error.code in ("not_found", "expired"):
            _emit(emit, {"event": "expired", "space_id": space})
            return 0
        raise
    _emit(emit, {"event": "joining", "space_id": space, "slot_id": lookup["slot_id"],
                 "expires_at": lookup["expires_at"]})
    deadline = float(lookup["expires_at"]) - PAIR_DEADLINE_SLACK
    while True:
        if time.time() >= deadline:
            _emit(emit, {"event": "expired", "space_id": space})
            return 0
        try:
            state = service.sealed_state(lookup["slot_id"], lookup["join_token"])
        except SyncRemoteError as error:
            if error.code in ("not_found", "expired"):
                _emit(emit, {"event": "expired", "space_id": space})
                return 0
            raise
        ciphertext = state.get("ciphertext")
        if isinstance(ciphertext, (bytes, bytearray)):
            wrap = PairingCrypto.wrap_key(shared, lookup["slot_id"])
            opened_space, master = PairingCrypto.open(ciphertext, wrap)
            if opened_space != space:
                raise SyncCryptoError("crypto_failed")
            sas = PairingCrypto.sas(shared, lookup["slot_id"])
            _emit(emit, {"event": "joined", "space_id": opened_space,
                         "master_key": b64_standard_encode(master), "sas": sas})
            return 0
        time.sleep(PAIR_POLL_SECONDS)


def _decode_public(value):
    if not isinstance(value, str):
        raise SyncRemoteError("invalid_response")
    from agent_meter.sync_crypto import b64url_decode

    raw = b64url_decode(value)
    if raw is None or len(raw) != 32:
        raise SyncRemoteError("invalid_response")
    return raw


def _quota_sources(result):
    """Account quota rows, with a provider-level account key.

    Windows currently has at most one signed-in account per provider; the Mac
    hashes the real identity. A provider key is the honest fallback: it lets
    the Mac show the same quota without inventing an account label.
    """
    sources = []
    account = result.get("account")
    if isinstance(account, dict) and isinstance(account.get("quota"), dict):
        sources.append(("codex", account["quota"]))
    for name, value in sorted((result.get("other_accounts") or {}).items()):
        if isinstance(value, dict) and isinstance(value.get("quota"), dict):
            sources.append((APP_IDS.get(name, name), value["quota"]))
    out = []
    for name, quota in sources:
        if not isinstance(quota.get("value"), list):
            continue
        if quota.get("status") not in ("available", "partial"):
            continue
        out.append({"id": name, "metrics": {"quota": {"status": quota["status"],
                                                      "value": quota["value"]}}})
    return out


def windows_snapshot(result):
    """Project the Windows compact snapshot into the Mac payload shape.

    Several Windows collectors keep per-model daily rows; when they do, they
    are carried as-is. The rest only have per-day totals, which travel as one
    aggregate row per day so the Mac still gets the right daily total.
    """
    sources = []
    for name, item in sorted((result.get("history") or {}).items()):
        if not isinstance(item, dict):
            continue
        value = item.get("value")
        if not isinstance(value, dict):
            continue
        app = APP_IDS.get(name, name)
        daily = value.get("daily_models")
        if isinstance(daily, list) and daily:
            token_value = {"daily_models": daily}
        else:
            buckets = value.get("daily_buckets")
            if not isinstance(buckets, list) or not buckets:
                continue
            rows = []
            for row in buckets:
                if not isinstance(row, dict):
                    continue
                day, tokens = row.get("date"), row.get("tokens")
                if not isinstance(day, str) or len(day) != 10:
                    continue
                if isinstance(tokens, bool) or not isinstance(tokens, int) or tokens < 0:
                    continue
                rows.append({"date": day, "model": "(all)", "total_tokens": tokens,
                             "requests": row.get("requests") if isinstance(row.get("requests"), int) else 0})
            token_value = {"daily_models": rows}
        status = "available" if item.get("status") == "available" else "partial"
        sources.append({"id": app, "account_key": app,
                        "metrics": {"tokens": {"status": status, "value": token_value}}})
    sources.extend(_quota_sources(result))
    return {"sources": sources}
