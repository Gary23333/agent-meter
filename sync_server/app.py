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
# Identifiers are opaque hex; anything else is a path-traversal probe.
ID_RE = re.compile(r"^[0-9a-f]{32}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")

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
