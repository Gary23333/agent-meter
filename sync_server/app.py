"""Development sync service: encrypted blob storage for AgentMeter.

Clients encrypt their payload before it gets here, so this service only ever
stores ciphertext. It cannot read what it stores, and that is the point: the
operator of the service learns nothing about which agents the user runs.

M0 scope: spaces, per-device blobs and the space manifest. Membership,
licences and payment are deliberately not part of this file yet.

The service listens on loopback by default. Exposing it to a network is a
deployment decision, and the transport in front of it must be https.
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MAX_BLOB = 8 * 1024 * 1024
MAX_DEVICES_PER_SPACE = 10
MAX_SPACE_BYTES = 64 * 1024 * 1024
MAX_PAIR_SLOTS_PER_SPACE = 3
PAIR_TTL = 300.0
PAIR_ATTEMPTS = 5
PAIR_RATE_LIMIT = 10
PAIR_MAX_BODY = 8 * 1024
# Identifiers are opaque hex; anything else is a path-traversal probe.
ID_RE = re.compile(r"^[0-9a-f]{32}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
# A 32-byte X25519 public key in unpadded base64url is exactly 43 chars.
PUBLIC_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
CODE_RE = re.compile(r"^[0-9]{6}$")
CIPHERTEXT_RE = re.compile(r"^[A-Za-z0-9_-]{40,5462}$")


def b64url_bytes(value):
    """Decode unpadded base64url, or None when it is not valid."""
    if not isinstance(value, str):
        return None
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, TypeError):
        return None


def valid_public_key(value):
    if not isinstance(value, str) or not PUBLIC_KEY_RE.match(value):
        return False
    raw = b64url_bytes(value)
    return raw is not None and len(raw) == 32


def valid_ciphertext(value):
    if not isinstance(value, str) or not CIPHERTEXT_RE.match(value):
        return False
    raw = b64url_bytes(value)
    return raw is not None and 48 <= len(raw) <= 4096

SCHEMA = """
CREATE TABLE IF NOT EXISTS spaces (
    space_id TEXT PRIMARY KEY,
    auth_hash TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS blobs (
    space_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    ciphertext BLOB NOT NULL,
    size INTEGER NOT NULL,
    version INTEGER NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (space_id, device_id)
);
CREATE INDEX IF NOT EXISTS blobs_by_space ON blobs(space_id);
CREATE TABLE IF NOT EXISTS pair_slots (
    slot_id TEXT PRIMARY KEY,
    space_id TEXT NOT NULL,
    code_hash TEXT NOT NULL,
    pub_a TEXT NOT NULL,
    pub_b TEXT,
    ciphertext TEXT,
    join_hash TEXT,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    consumed_at REAL,
    attempts INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS pair_slots_code
    ON pair_slots(code_hash) WHERE consumed_at IS NULL;
CREATE INDEX IF NOT EXISTS pair_slots_by_space ON pair_slots(space_id);
"""


class Store:
    """SQLite-backed blob storage.

    One connection guarded by one lock. The service is read-mostly and
    low-traffic, and a per-thread connection would leave a file handle behind
    for every request the server handles.
    """

    def __init__(self, path):
        self.path = str(path)
        self._lock = threading.RLock()
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.executescript(SCHEMA)
        self._connection.commit()
        # The database holds ciphertext, but it is still the user's data.
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(self.path + suffix)
            if candidate.exists():
                os.chmod(candidate, 0o600)

    def close(self):
        with self._lock:
            self._connection.close()

    def create_space(self, space_id, auth_hash):
        """Create the space, or return False when the id is taken."""
        now = time.time()
        with self._lock:
            row = self._connection.execute(
                "SELECT auth_hash FROM spaces WHERE space_id=?", (space_id,)).fetchone()
            if row is not None:
                # The same client may retry; a different token may not take over.
                return row[0] == auth_hash
            self._connection.execute(
                "INSERT INTO spaces(space_id,auth_hash,created_at) VALUES(?,?,?)",
                (space_id, auth_hash, now))
            self._connection.commit()
        return True

    def space_auth(self, space_id):
        with self._lock:
            row = self._connection.execute(
                "SELECT auth_hash FROM spaces WHERE space_id=?", (space_id,)).fetchone()
        return row[0] if row else None

    def count_spaces(self):
        with self._lock:
            return self._connection.execute("SELECT COUNT(*) FROM spaces").fetchone()[0]

    def put_blob(self, space_id, device_id, ciphertext):
        now = time.time()
        size = len(ciphertext)
        with self._lock:
            connection = self._connection
            devices = connection.execute(
                "SELECT COUNT(*) FROM blobs WHERE space_id=?", (space_id,)).fetchone()[0]
            row = connection.execute(
                "SELECT size,version FROM blobs WHERE space_id=? AND device_id=?",
                (space_id, device_id)).fetchone()
            known = row is not None
            total = connection.execute(
                "SELECT COALESCE(SUM(size),0) FROM blobs WHERE space_id=?", (space_id,)).fetchone()[0]
            if not known and devices >= MAX_DEVICES_PER_SPACE:
                raise ValueError("too_many_devices")
            if total - (row[0] if known else 0) + size > MAX_SPACE_BYTES:
                raise ValueError("space_too_large")
            version = (row[1] + 1) if known else 1
            connection.execute(
                "INSERT INTO blobs(space_id,device_id,ciphertext,size,version,updated_at) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(space_id,device_id) DO UPDATE SET "
                "ciphertext=excluded.ciphertext,size=excluded.size,version=excluded.version,"
                "updated_at=excluded.updated_at",
                (space_id, device_id, ciphertext, size, version, now))
            connection.commit()
        return {"device_id": device_id, "size": size, "version": version, "updated_at": now}

    def manifest(self, space_id):
        with self._lock:
            rows = self._connection.execute(
                "SELECT device_id,size,version,updated_at FROM blobs WHERE space_id=? ORDER BY device_id",
                (space_id,)).fetchall()
        return [{"device_id": r[0], "size": r[1], "version": r[2], "updated_at": r[3]} for r in rows]

    def get_blob(self, space_id, device_id):
        with self._lock:
            row = self._connection.execute(
                "SELECT ciphertext FROM blobs WHERE space_id=? AND device_id=?",
                (space_id, device_id)).fetchone()
        return row[0] if row else None

    def delete_blob(self, space_id, device_id):
        with self._lock:
            self._connection.execute("DELETE FROM blobs WHERE space_id=? AND device_id=?",
                                     (space_id, device_id))
            self._connection.commit()
        return True

    # Pair slots are the short-code handoff. The code only locates a slot;
    # the master key is sealed with a key both devices derive from an
    # ephemeral X25519 exchange, so the service never sees it.

    def _purge_pair_slots_locked(self, now):
        self._connection.execute(
            "DELETE FROM pair_slots WHERE expires_at <= ? "
            "OR (consumed_at IS NOT NULL AND consumed_at <= ?)",
            (now, now - 3600))

    def create_pair_slot(self, space_id, pub_a, ttl=PAIR_TTL):
        now = time.time()
        with self._lock:
            self._purge_pair_slots_locked(now)
            active = self._connection.execute(
                "SELECT COUNT(*) FROM pair_slots "
                "WHERE space_id=? AND consumed_at IS NULL AND expires_at>?",
                (space_id, now)).fetchone()[0]
            if active >= MAX_PAIR_SLOTS_PER_SPACE:
                raise ValueError("too_many_pair_slots")
            for _ in range(8):
                code = "%06d" % secrets.randbelow(1_000_000)
                code_hash = hashlib.sha256(code.encode()).hexdigest()
                slot_id = secrets.token_hex(16)
                try:
                    self._connection.execute(
                        "INSERT INTO pair_slots(slot_id,space_id,code_hash,pub_a,created_at,expires_at) "
                        "VALUES(?,?,?,?,?,?)",
                        (slot_id, space_id, code_hash, pub_a, now, now + ttl))
                    self._connection.commit()
                    return {"slot_id": slot_id, "code": code,
                            "expires_at": now + ttl, "ttl": ttl}
                except sqlite3.IntegrityError:
                    self._connection.rollback()
        raise ValueError("pair_code_unavailable")

    def lookup_pair_slot(self, code):
        now = time.time()
        code_hash = hashlib.sha256(code.encode()).hexdigest()
        with self._lock:
            self._purge_pair_slots_locked(now)
            row = self._connection.execute(
                "SELECT slot_id,space_id,pub_a,attempts,expires_at FROM pair_slots "
                "WHERE code_hash=? AND consumed_at IS NULL AND expires_at>?",
                (code_hash, now)).fetchone()
            if row is None:
                return None
            slot_id, space_id, pub_a, attempts, expires_at = row
            attempts += 1
            if attempts > PAIR_ATTEMPTS:
                self._connection.execute("DELETE FROM pair_slots WHERE slot_id=?", (slot_id,))
                self._connection.commit()
                return {"error": "pair_attempts_exceeded"}
            join_token = secrets.token_urlsafe(32)
            join_hash = hashlib.sha256(join_token.encode()).hexdigest()
            self._connection.execute(
                "UPDATE pair_slots SET attempts=?, join_hash=? WHERE slot_id=?",
                (attempts, join_hash, slot_id))
            self._connection.commit()
            return {"slot_id": slot_id, "space_id": space_id, "pub_a": pub_a,
                    "join_token": join_token, "expires_at": expires_at,
                    "attempts_left": PAIR_ATTEMPTS - attempts}

    def pair_slot(self, slot_id):
        with self._lock:
            row = self._connection.execute(
                "SELECT slot_id,space_id,pub_a,pub_b,ciphertext,expires_at,consumed_at "
                "FROM pair_slots WHERE slot_id=?", (slot_id,)).fetchone()
        if row is None:
            return None
        return {"slot_id": row[0], "space_id": row[1], "pub_a": row[2],
                "pub_b": row[3], "ciphertext": row[4], "expires_at": row[5],
                "consumed_at": row[6]}

    def set_pair_public_key(self, slot_id, join_token, pub_b):
        now = time.time()
        join_hash = hashlib.sha256(join_token.encode()).hexdigest()
        with self._lock:
            row = self._connection.execute(
                "SELECT join_hash,expires_at,consumed_at,pub_b FROM pair_slots "
                "WHERE slot_id=?", (slot_id,)).fetchone()
            if row is None:
                return "not_found"
            stored_join, expires_at, consumed_at, existing_b = row
            if consumed_at is not None:
                return "consumed"
            if expires_at <= now:
                return "expired"
            if not stored_join or not hmac.compare_digest(join_hash, stored_join):
                return "forbidden"
            if existing_b is not None:
                return "already_paired"
            self._connection.execute(
                "UPDATE pair_slots SET pub_b=? WHERE slot_id=?", (pub_b, slot_id))
            self._connection.commit()
        return "ok"

    def set_pair_ciphertext(self, slot_id, ciphertext):
        now = time.time()
        with self._lock:
            row = self._connection.execute(
                "SELECT expires_at,consumed_at,ciphertext FROM pair_slots "
                "WHERE slot_id=?", (slot_id,)).fetchone()
            if row is None:
                return "not_found"
            expires_at, consumed_at, existing = row
            if consumed_at is not None:
                return "consumed"
            if expires_at <= now:
                return "expired"
            if existing is not None:
                return "already_sealed"
            self._connection.execute(
                "UPDATE pair_slots SET ciphertext=? WHERE slot_id=?", (ciphertext, slot_id))
            self._connection.commit()
        return "ok"

    def pair_ciphertext(self, slot_id, join_token):
        """What the joining device is allowed to see: the sealed bytes only."""
        now = time.time()
        join_hash = hashlib.sha256(join_token.encode()).hexdigest()
        with self._lock:
            row = self._connection.execute(
                "SELECT join_hash,expires_at,consumed_at,ciphertext,space_id "
                "FROM pair_slots WHERE slot_id=?", (slot_id,)).fetchone()
        if row is None:
            return {"status": "not_found"}
        stored_join, expires_at, consumed_at, ciphertext, space_id = row
        if consumed_at is not None:
            return {"status": "consumed"}
        if expires_at <= now:
            return {"status": "expired"}
        if not stored_join or not hmac.compare_digest(join_hash, stored_join):
            return {"status": "forbidden"}
        if ciphertext is None:
            return {"status": "pending", "space_id": space_id, "expires_at": expires_at}
        return {"status": "ready", "space_id": space_id, "ciphertext": ciphertext,
                "expires_at": expires_at}

    def consume_pair_slot(self, space_id, slot_id):
        with self._lock:
            cursor = self._connection.execute(
                "UPDATE pair_slots SET consumed_at=? WHERE slot_id=? AND space_id=? "
                "AND consumed_at IS NULL", (time.time(), slot_id, space_id))
            self._connection.commit()
            return cursor.rowcount


def make_handler(store, clock=time.time):
    class Handler(BaseHTTPRequestHandler):
        server_version = "AgentMeterSync/1"
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            # Never log request bodies: they are ciphertext today, but the
            # habit is what keeps it that way.
            pass

        def send_json(self, status, payload):
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def send_bytes(self, status, body):
            self.send_response(status)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def browser_rejected(self):
            """Keep browsers out: no Origin, and only the expected Host.

            A cross-origin page could otherwise reach the service with a
            "simple" request that needs no preflight.
            """
            if self.headers.get("Origin"):
                self.send_json(403, {"error": "origin_rejected"})
                return True
            allowed = getattr(self.server, "allowed_hosts", None)
            if allowed is not None and self.headers.get("Host", "") not in allowed:
                self.send_json(403, {"error": "host_rejected"})
                return True
            return False

        def bearer(self):
            provided = self.headers.get("Authorization", "")
            if not provided.startswith("Bearer "):
                return None
            return provided[len("Bearer "):].strip()

        def authorize(self, space_id):
            """The space holds the hash of the bearer token, never the token."""
            expected = store.space_auth(space_id)
            if not expected:
                self.send_json(404, {"error": "not_found"})
                return False
            token = self.bearer()
            if not token:
                self.send_json(401, {"error": "authentication_required"})
                return False
            digest = hashlib.sha256(token.encode()).hexdigest()
            if not hmac.compare_digest(digest, expected):
                self.send_json(403, {"error": "authentication_failed"})
                return False
            return True

        def read_json(self, limit=64 * 1024):
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                self.send_json(415, {"error": "json_body_required"})
                self.close_connection = True
                return None
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                length = -1
            if not 0 < length <= limit:
                self.send_json(400, {"error": "invalid_body_length"})
                self.close_connection = True
                return None
            try:
                value = json.loads(self.rfile.read(length))
            except (ValueError, UnicodeDecodeError):
                self.send_json(400, {"error": "invalid_json"})
                self.close_connection = True
                return None
            return value

        def read_bytes(self, limit=MAX_BLOB):
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                length = -1
            if length <= 0:
                self.send_json(400, {"error": "invalid_body_length"})
                self.close_connection = True
                return None
            if length > limit:
                # Refuse without reading: the client must not be able to make
                # the service buffer an unbounded body. The unread body would
                # corrupt a kept-alive stream, so the connection ends here.
                self.send_json(413, {"error": "blob_too_large"})
                self.close_connection = True
                return None
            data = self.rfile.read(length)
            if len(data) != length:
                self.send_json(400, {"error": "invalid_body_length"})
                self.close_connection = True
                return None
            return data

        def pair_rate_limited(self):
            """A per-IP budget for the only unauthenticated lookup endpoint."""
            ip = self.client_address[0]
            now = time.time()
            with self.server.pair_rate_lock:
                bucket = [stamp for stamp in self.server.pair_rate.get(ip, ())
                          if now - stamp < 60]
                if len(bucket) >= PAIR_RATE_LIMIT:
                    self.server.pair_rate[ip] = bucket
                    return True
                bucket.append(now)
                self.server.pair_rate[ip] = bucket
            return False

        def route(self):
            path = self.path.split("?", 1)[0]
            parts = [p for p in path.split("/") if p]
            if not parts or parts[0] != "v1":
                return None
            return parts[1:]

        def do_GET(self):
            if self.browser_rejected():
                return
            parts = self.route()
            if parts == ["health"]:
                self.send_json(200, {"status": "ok", "spaces": store.count_spaces()})
                return
            if parts and parts[0] == "pair" and len(parts) == 4 and parts[3] == "sealed":
                # The joining device polls for the sealed master key. The
                # join token is scoped to this slot and nothing else.
                slot_id = parts[2]
                if not ID_RE.match(slot_id):
                    self.send_json(400, {"error": "invalid_slot_id"})
                    return
                token = self.bearer()
                if not token:
                    self.send_json(401, {"error": "authentication_required"})
                    return
                result = store.pair_ciphertext(slot_id, token)
                status = result["status"]
                if status == "ready":
                    self.send_json(200, {"slot_id": slot_id, "ready": True,
                                         "space_id": result["space_id"],
                                         "ciphertext": result["ciphertext"],
                                         "expires_at": result["expires_at"]})
                elif status == "pending":
                    self.send_json(200, {"slot_id": slot_id, "ready": False,
                                         "expires_at": result["expires_at"]})
                elif status == "not_found":
                    self.send_json(404, {"error": "not_found"})
                elif status == "forbidden":
                    self.send_json(403, {"error": "authentication_failed"})
                else:
                    self.send_json(410, {"error": "pair_slot_" + status})
                return
            if parts and parts[0] == "pair" and len(parts) == 3:
                # The first device polls for the second device's public key
                # and sealed master key. The slot is scoped to its space.
                slot_id = parts[2]
                if not ID_RE.match(slot_id):
                    self.send_json(400, {"error": "invalid_slot_id"})
                    return
                slot = store.pair_slot(slot_id)
                if slot is None:
                    self.send_json(404, {"error": "not_found"})
                    return
                if not self.authorize(slot["space_id"]):
                    return
                if slot["consumed_at"] is not None:
                    self.send_json(410, {"error": "pair_slot_consumed"})
                    return
                if slot["expires_at"] <= clock():
                    self.send_json(410, {"error": "pair_slot_expired"})
                    return
                if slot["pub_b"] is None:
                    self.send_json(200, {"slot_id": slot_id, "ready": False,
                                         "expires_at": slot["expires_at"]})
                    return
                self.send_json(200, {"slot_id": slot_id, "ready": True,
                                     "space_id": slot["space_id"],
                                     "pub_a": slot["pub_a"], "pub_b": slot["pub_b"],
                                     "ciphertext": slot["ciphertext"],
                                     "expires_at": slot["expires_at"]})
                return
            if parts and parts[0] == "sync" and len(parts) in (2, 3):
                space_id = parts[1]
                if not ID_RE.match(space_id):
                    self.send_json(400, {"error": "invalid_space_id"})
                    return
                if not self.authorize(space_id):
                    return
                if len(parts) == 2:
                    self.send_json(200, {"space_id": space_id, "devices": store.manifest(space_id)})
                    return
                device_id = parts[2]
                if not ID_RE.match(device_id):
                    self.send_json(400, {"error": "invalid_device_id"})
                    return
                blob = store.get_blob(space_id, device_id)
                if blob is None:
                    self.send_json(404, {"error": "not_found"})
                    return
                self.send_bytes(200, blob)
                return
            self.send_json(404, {"error": "not_found"})

        def do_POST(self):
            if self.browser_rejected():
                return
            parts = self.route()
            if parts == ["pair", "slots"]:
                # The first device asks for a short code and proves it owns
                # the space. The code is shown once, then never returned.
                body = self.read_json(PAIR_MAX_BODY)
                if body is None:
                    return
                if not isinstance(body, dict):
                    self.send_json(400, {"error": "invalid_body"})
                    return
                space_id = body.get("space_id")
                pub_a = body.get("pub_a")
                if not isinstance(space_id, str) or not ID_RE.match(space_id):
                    self.send_json(400, {"error": "invalid_space_id"})
                    return
                if not valid_public_key(pub_a):
                    self.send_json(400, {"error": "invalid_public_key"})
                    return
                if not self.authorize(space_id):
                    return
                try:
                    slot = store.create_pair_slot(space_id, pub_a)
                except ValueError as exc:
                    self.send_json(409, {"error": str(exc)})
                    return
                self.send_json(201, slot)
                return
            if parts == ["pair", "lookup"]:
                # The only unauthenticated endpoint. It is rate-limited per
                # IP and every slot burns after PAIR_ATTEMPTS tries.
                if self.pair_rate_limited():
                    self.send_json(429, {"error": "rate_limited"})
                    return
                body = self.read_json(PAIR_MAX_BODY)
                if body is None:
                    return
                if not isinstance(body, dict):
                    self.send_json(400, {"error": "invalid_body"})
                    return
                code = body.get("code")
                if not isinstance(code, str) or not CODE_RE.match(code):
                    self.send_json(400, {"error": "invalid_pair_code"})
                    return
                slot = store.lookup_pair_slot(code)
                if slot is None:
                    self.send_json(404, {"error": "pair_code_not_found"})
                    return
                if slot.get("error"):
                    self.send_json(429, {"error": slot["error"]})
                    return
                self.send_json(200, slot)
                return
            if parts == ["sync", "spaces"]:
                # The client generates the space id, so it can derive the
                # token before the space exists. Creating a space needs that
                # token: an unauthenticated caller must not be able to fill
                # the service with spaces.
                body = self.read_json()
                if body is None:
                    return
                if not isinstance(body, dict):
                    self.send_json(400, {"error": "invalid_body"})
                    return
                space_id = body.get("space_id")
                auth_hash = body.get("auth_hash")
                if not isinstance(space_id, str) or not ID_RE.match(space_id):
                    self.send_json(400, {"error": "invalid_space_id"})
                    return
                if not isinstance(auth_hash, str) or not HASH_RE.match(auth_hash):
                    self.send_json(400, {"error": "invalid_auth_hash"})
                    return
                token = self.bearer()
                if not token:
                    self.send_json(401, {"error": "authentication_required"})
                    return
                digest = hashlib.sha256(token.encode()).hexdigest()
                if not hmac.compare_digest(digest, auth_hash):
                    self.send_json(403, {"error": "authentication_failed"})
                    return
                if not store.create_space(space_id, auth_hash):
                    self.send_json(409, {"error": "space_taken"})
                    return
                self.send_json(201, {"space_id": space_id, "created_at": clock()})
                return
            self.send_json(404, {"error": "not_found"})

        def do_PUT(self):
            if self.browser_rejected():
                return
            parts = self.route()
            if parts and parts[0] == "pair" and len(parts) == 3:
                # The joining device publishes its ephemeral public key.
                # The first device will seal the master key to it next.
                slot_id = parts[2]
                if not ID_RE.match(slot_id):
                    self.send_json(400, {"error": "invalid_slot_id"})
                    return
                token = self.bearer()
                if not token:
                    self.send_json(401, {"error": "authentication_required"})
                    return
                body = self.read_json(PAIR_MAX_BODY)
                if body is None:
                    return
                if not isinstance(body, dict):
                    self.send_json(400, {"error": "invalid_body"})
                    return
                pub_b = body.get("pub_b")
                if not valid_public_key(pub_b):
                    self.send_json(400, {"error": "invalid_public_key"})
                    return
                result = store.set_pair_public_key(slot_id, token, pub_b)
                if result == "ok":
                    self.send_json(200, {"slot_id": slot_id, "public_key_received": True})
                elif result == "not_found":
                    self.send_json(404, {"error": "not_found"})
                elif result == "forbidden":
                    self.send_json(403, {"error": "authentication_failed"})
                elif result == "already_paired":
                    self.send_json(409, {"error": "pair_slot_already_paired"})
                else:
                    self.send_json(410, {"error": "pair_slot_" + result})
                return
            if parts and parts[0] == "pair" and len(parts) == 4 and parts[3] == "sealed":
                # The first device seals the master key under the shared
                # secret and stores only the sealed bytes.
                slot_id = parts[2]
                if not ID_RE.match(slot_id):
                    self.send_json(400, {"error": "invalid_slot_id"})
                    return
                slot = store.pair_slot(slot_id)
                if slot is None:
                    self.send_json(404, {"error": "not_found"})
                    return
                if not self.authorize(slot["space_id"]):
                    return
                body = self.read_json(PAIR_MAX_BODY)
                if body is None:
                    return
                if not isinstance(body, dict):
                    self.send_json(400, {"error": "invalid_body"})
                    return
                ciphertext = body.get("ciphertext")
                if not valid_ciphertext(ciphertext):
                    self.send_json(400, {"error": "invalid_ciphertext"})
                    return
                result = store.set_pair_ciphertext(slot_id, ciphertext)
                if result == "ok":
                    self.send_json(200, {"slot_id": slot_id, "sealed": True})
                elif result == "not_found":
                    self.send_json(404, {"error": "not_found"})
                elif result == "already_sealed":
                    self.send_json(409, {"error": "pair_slot_already_sealed"})
                else:
                    self.send_json(410, {"error": "pair_slot_" + result})
                return
            if parts and parts[0] == "sync" and len(parts) == 3:
                space_id, device_id = parts[1], parts[2]
                if not ID_RE.match(space_id):
                    self.send_json(400, {"error": "invalid_space_id"})
                    return
                if not ID_RE.match(device_id):
                    self.send_json(400, {"error": "invalid_device_id"})
                    return
                if not self.authorize(space_id):
                    return
                data = self.read_bytes()
                if data is None:
                    return
                try:
                    info = store.put_blob(space_id, device_id, data)
                except ValueError as exc:
                    code = str(exc)
                    self.send_json(409 if code == "too_many_devices" else 413, {"error": code})
                    return
                self.send_json(200, info)
                return
            self.send_json(404, {"error": "not_found"})

        def do_DELETE(self):
            if self.browser_rejected():
                return
            parts = self.route()
            if parts and parts[0] == "pair" and len(parts) == 3:
                slot_id = parts[2]
                if not ID_RE.match(slot_id):
                    self.send_json(400, {"error": "invalid_slot_id"})
                    return
                slot = store.pair_slot(slot_id)
                if slot is None:
                    self.send_json(404, {"error": "not_found"})
                    return
                if not self.authorize(slot["space_id"]):
                    return
                store.consume_pair_slot(slot["space_id"], slot_id)
                self.send_json(200, {"slot_id": slot_id, "deleted": True})
                return
            if parts and parts[0] == "sync" and len(parts) == 3:
                space_id, device_id = parts[1], parts[2]
                if not ID_RE.match(space_id) or not ID_RE.match(device_id):
                    self.send_json(400, {"error": "invalid_identifier"})
                    return
                if not self.authorize(space_id):
                    return
                store.delete_blob(space_id, device_id)
                self.send_json(200, {"device_id": device_id, "deleted": True})
                return
            self.send_json(404, {"error": "not_found"})

    return Handler


def default_allowed_hosts(host, port, extra=()):
    """The Host values the service answers to.

    A deployment behind a reverse proxy passes its public name through
    ``--allowed-host``; loopback names are always allowed for development.
    """
    hosts = {f"{host}:{port}", f"127.0.0.1:{port}", f"localhost:{port}"}
    hosts.update(extra)
    return hosts


def make_server(store, port=8899, host="127.0.0.1", extra_hosts=()):
    server = ThreadingHTTPServer((host, port), make_handler(store))
    server.daemon_threads = True
    bound_host, bound_port = server.server_address[0], server.server_address[1]
    server.allowed_hosts = default_allowed_hosts(bound_host, bound_port, extra_hosts)
    server.pair_rate = {}
    server.pair_rate_lock = threading.Lock()
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description="AgentMeter development sync service")
    parser.add_argument("--db", default=".runtime/sync-server.db", help="SQLite file")
    parser.add_argument("--port", type=int, default=8899)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--allowed-host", action="append", default=[],
                        help="extra Host value to answer to (repeatable)")
    args = parser.parse_args(argv)
    store = Store(args.db)
    server = make_server(store, args.port, args.host, args.allowed_host)
    print(json.dumps({"listening": "http://%s:%d" % (args.host, server.server_address[1]),
                      "database": str(Path(args.db).resolve())}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
