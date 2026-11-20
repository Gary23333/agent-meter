"""HTTP client for the AgentMeter sync service.

Only ciphertext and bearer tokens travel here. Plain http is allowed solely
for loopback, exactly like the Mac client: a payload or token must never go
over the wire in the clear.
"""

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request

MAX_BLOB = 8 * 1024 * 1024
MAX_JSON = 256 * 1024
TIMEOUT = 30


class SyncRemoteError(Exception):
    """Stable code for the UI; never carries a server body or a URL."""

    def __init__(self, code, status=0):
        super().__init__(code)
        self.code = code
        self.status = status


def _identifier(value):
    """Server and client both use 32 lowercase hex for spaces, devices and slots."""
    from .sync_crypto import is_space_id

    if not is_space_id(value):
        raise SyncRemoteError("invalid_identifier")
    return value


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_base_url(value):
    """https, or http only on loopback; no credentials in the URL."""
    if not isinstance(value, str) or not value or len(value) > 200:
        raise SyncRemoteError("not_configured")
    parsed = urllib.parse.urlsplit(value)
    if parsed.username or parsed.password:
        raise SyncRemoteError("not_configured")
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    loopback = host in ("127.0.0.1", "localhost", "::1")
    if scheme == "https":
        return value.rstrip("/")
    if scheme == "http" and loopback:
        return value.rstrip("/")
    raise SyncRemoteError("not_configured")


class SyncService:
    def __init__(self, base_url):
        self.base_url = validate_base_url(base_url)
        self._opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl.create_default_context()),
                                                   _NoRedirect())

    def _url(self, path):
        return self.base_url + "/" + path.lstrip("/")

    def _send(self, path, method="GET", token=None, body=None, raw=False, limit=MAX_JSON):
        url = self._url(path)
        data = None
        headers = {"Accept": "application/json", "User-Agent": "AgentMeter-Windows"}
        if token:
            headers["Authorization"] = "Bearer " + token
        if body is not None:
            data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif method in ("POST", "PUT"):
            data = b"{}"
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self._opener.open(request, timeout=TIMEOUT) as response:
                status = response.status
                payload = response.read(limit + 1)
        except urllib.error.HTTPError as error:
            status = error.code
            try:
                payload = error.read(MAX_JSON)
            except Exception:
                payload = b""
            code = _error_code(payload)
            if status in (401, 403):
                raise SyncRemoteError("unauthorized", status) from None
            if status == 404:
                raise SyncRemoteError("not_found", status) from None
            if status == 410:
                raise SyncRemoteError("expired", status) from None
            raise SyncRemoteError(code or f"http_{status}", status) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise SyncRemoteError("transport") from None
        if status < 200 or status >= 300:
            raise SyncRemoteError(_error_code(payload) or f"http_{status}", status)
        if len(payload) > limit:
            raise SyncRemoteError("invalid_response", status)
        return payload

    # ---- spaces and blobs ------------------------------------------------

    def create_space(self, space_id, token, auth_hash):
        _identifier(space_id)
        data = self._send("v1/sync/spaces", "POST", token, {"space_id": space_id, "auth_hash": auth_hash})
        value = _object(data)
        space = value.get("space_id")
        if not isinstance(space, str):
            raise SyncRemoteError("invalid_response")
        return _identifier(space)

    def manifest(self, space_id, token):
        _identifier(space_id)
        data = self._send(f"v1/sync/{space_id}", "GET", token)
        value = _object(data)
        devices = value.get("devices")
        if not isinstance(devices, list):
            raise SyncRemoteError("invalid_response")
        out = []
        for entry in devices:
            if not isinstance(entry, dict):
                continue
            device = entry.get("device_id")
            size = entry.get("size")
            version = entry.get("version")
            updated = entry.get("updated_at")
            if not isinstance(device, str) or not isinstance(size, int) or not isinstance(version, int):
                continue
            try:
                device = _identifier(device)
            except SyncRemoteError:
                continue
            out.append({"device_id": device, "size": size, "version": version,
                        "updated_at": float(updated) if isinstance(updated, (int, float)) else None})
        return out

    def put(self, space_id, device_id, token, ciphertext):
        self._send_raw(f"v1/sync/{_identifier(space_id)}/{_identifier(device_id)}", "PUT", token, ciphertext)

    def blob(self, space_id, device_id, token):
        path = f"v1/sync/{_identifier(space_id)}/{_identifier(device_id)}"
        return self._send(path, "GET", token, limit=MAX_BLOB)

    def delete(self, space_id, device_id, token):
        self._send(f"v1/sync/{_identifier(space_id)}/{_identifier(device_id)}", "DELETE", token)

    # ---- pairing ---------------------------------------------------------

    def create_slot(self, space_id, token, public_key):
        from .sync_crypto import b64url_encode

        _identifier(space_id)
        data = self._send("v1/pair/slots", "POST", token,
                          {"space_id": space_id, "pub_a": b64url_encode(public_key)})
        value = _object(data)
        slot = value.get("slot_id")
        code = value.get("code")
        expires = value.get("expires_at")
        if not isinstance(slot, str) or not isinstance(code, str) or not isinstance(expires, (int, float)):
            raise SyncRemoteError("invalid_response")
        return {"slot_id": _identifier(slot), "code": code, "expires_at": float(expires)}

    def lookup(self, code):
        data = self._send("v1/pair/lookup", "POST", None, {"code": code})
        value = _object(data)
        slot = value.get("slot_id")
        space = value.get("space_id")
        pub_a = value.get("pub_a")
        join_token = value.get("join_token")
        expires = value.get("expires_at")
        if not isinstance(slot, str) or not isinstance(space, str) or not isinstance(pub_a, str) or \
                not isinstance(join_token, str) or not isinstance(expires, (int, float)):
            raise SyncRemoteError("invalid_response")
        return {"slot_id": _identifier(slot), "space_id": _identifier(space), "pub_a": pub_a,
                "join_token": join_token, "expires_at": float(expires),
                "attempts_left": int(value.get("attempts_left") or 0)}

    def join(self, slot_id, join_token, public_key):
        from .sync_crypto import b64url_encode

        self._send(f"v1/pair/slots/{_identifier(slot_id)}", "PUT", join_token,
                   {"pub_b": b64url_encode(public_key)})

    def seal(self, slot_id, token, ciphertext):
        from .sync_crypto import b64url_encode

        self._send(f"v1/pair/slots/{_identifier(slot_id)}/sealed", "PUT", token,
                   {"ciphertext": b64url_encode(ciphertext)})

    def slot_state(self, slot_id, token):
        data = self._send(f"v1/pair/slots/{_identifier(slot_id)}", "GET", token)
        return _pair_state(_object(data))

    def sealed_state(self, slot_id, join_token):
        data = self._send(f"v1/pair/slots/{_identifier(slot_id)}/sealed", "GET", join_token)
        return _pair_state(_object(data))

    def consume(self, slot_id, token):
        self._send(f"v1/pair/slots/{_identifier(slot_id)}", "DELETE", token)

    # urllib takes bytes bodies outside the JSON helper; keep the same gate.
    def _send_raw(self, path, method, token, payload):
        url = self._url(path)
        headers = {"Accept": "application/json", "User-Agent": "AgentMeter-Windows",
                   "Content-Type": "application/octet-stream"}
        if token:
            headers["Authorization"] = "Bearer " + token
        request = urllib.request.Request(url, data=payload, headers=headers, method=method)
        try:
            with self._opener.open(request, timeout=TIMEOUT) as response:
                status = response.status
                body = response.read(MAX_JSON)
        except urllib.error.HTTPError as error:
            status = error.code
            try:
                body = error.read(MAX_JSON)
            except Exception:
                body = b""
            code = _error_code(body)
            if status in (401, 403):
                raise SyncRemoteError("unauthorized", status) from None
            if status == 404:
                raise SyncRemoteError("not_found", status) from None
            raise SyncRemoteError(code or f"http_{status}", status) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise SyncRemoteError("transport") from None
        if status < 200 or status >= 300:
            raise SyncRemoteError(_error_code(body) or f"http_{status}", status)
        return body


def _object(data):
    try:
        value = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        raise SyncRemoteError("invalid_response") from None
    if not isinstance(value, dict):
        raise SyncRemoteError("invalid_response")
    return value


def _error_code(data):
    try:
        value = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    code = value.get("error")
    return code if isinstance(code, str) and 0 < len(code) <= 80 else None


def _pair_state(value):
    ready = value.get("ready")
    expires = value.get("expires_at")
    if not isinstance(ready, bool) or not isinstance(expires, (int, float)):
        raise SyncRemoteError("invalid_response")
    state = {"ready": ready, "expires_at": float(expires)}
    for key in ("pub_b", "ciphertext"):
        encoded = value.get(key)
        if isinstance(encoded, str):
            from .sync_crypto import b64url_decode

            raw = b64url_decode(encoded)
            if raw is not None:
                state[key] = raw
    space = value.get("space_id")
    if isinstance(space, str):
        state["space_id"] = space
    return state
