import hashlib
import http.client
import json
import secrets
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from sync_server.app import MAX_BLOB, Store, make_server

SPACE = "1" * 32
DEVICE = "2" * 32
OTHER = "3" * 32


def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


class ServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "sync.db")
        self.server = make_server(self.store, port=0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02},
                                       daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:%d" % self.port
        self.token = "test-token"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.store.close()
        self.tmp.cleanup()

    def call(self, method, path, body=None, token=None, content_type=None, headers=None):
        url = self.base + path
        data = None
        request_headers = dict(headers or {})
        if body is not None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            request_headers["Content-Type"] = content_type or "application/json"
        if token:
            request_headers["Authorization"] = "Bearer " + token
        request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read()
            exc.close()
            return exc.code, body

    def create_space(self, token=None):
        token = token or self.token
        space_id = secrets.token_hex(16)
        status, body = self.call("POST", "/v1/sync/spaces",
                                 {"space_id": space_id, "auth_hash": hash_token(token)},
                                 token=token)
        self.assertEqual(status, 201)
        return space_id


class HealthTests(ServiceTestCase):
    def test_health_answers(self):
        status, body = self.call("GET", "/v1/health")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["status"], "ok")

    def test_an_unknown_path_is_not_found(self):
        status, body = self.call("GET", "/v1/nope")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["error"], "not_found")


class SpaceTests(ServiceTestCase):
    def test_a_space_has_a_hex_identifier(self):
        space = self.create_space()
        self.assertEqual(len(space), 32)
        self.assertTrue(all(c in "0123456789abcdef" for c in space))

    def test_the_service_keeps_the_token_hash_not_the_token(self):
        space = self.create_space()
        stored = self.store.space_auth(space)
        self.assertEqual(len(stored), 64)
        self.assertNotIn(self.token, stored)

    def test_a_malformed_auth_hash_is_rejected(self):
        status, body = self.call("POST", "/v1/sync/spaces",
                                 {"space_id": secrets.token_hex(16), "auth_hash": "short"},
                                 token=self.token)
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["error"], "invalid_auth_hash")

    def test_a_malformed_space_id_is_rejected(self):
        status, body = self.call("POST", "/v1/sync/spaces",
                                 {"space_id": "nope", "auth_hash": hash_token(self.token)},
                                 token=self.token)
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["error"], "invalid_space_id")

    def test_creating_a_space_needs_a_token(self):
        status, body = self.call("POST", "/v1/sync/spaces",
                                 {"space_id": secrets.token_hex(16),
                                  "auth_hash": hash_token(self.token)})
        self.assertEqual(status, 401)
        self.assertEqual(json.loads(body)["error"], "authentication_required")

    def test_the_token_must_match_the_claimed_hash(self):
        status, body = self.call("POST", "/v1/sync/spaces",
                                 {"space_id": secrets.token_hex(16),
                                  "auth_hash": hash_token(self.token)}, token="a-different-token")
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body)["error"], "authentication_failed")

    def test_a_body_that_is_not_json_is_refused(self):
        status, body = self.call("POST", "/v1/sync/spaces",
                                 json.dumps({"space_id": secrets.token_hex(16)}).encode(),
                                 token=self.token, content_type="text/plain")
        self.assertEqual(status, 415)
        self.assertEqual(json.loads(body)["error"], "json_body_required")

    def test_a_taken_space_cannot_be_hijacked(self):
        space = self.create_space()
        status, body = self.call("POST", "/v1/sync/spaces",
                                 {"space_id": space, "auth_hash": hash_token("another-token")},
                                 token="another-token")
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(body)["error"], "space_taken")

    def test_creating_the_same_space_again_is_allowed(self):
        space = self.create_space()
        status, _ = self.call("POST", "/v1/sync/spaces",
                              {"space_id": space, "auth_hash": hash_token(self.token)},
                              token=self.token)
        self.assertEqual(status, 201)


class BlobTests(ServiceTestCase):
    def test_a_blob_makes_the_round_trip(self):
        space = self.create_space()
        payload = b"ciphertext-bytes"
        status, body = self.call("PUT", "/v1/sync/%s/%s" % (space, DEVICE),
                                 payload, token=self.token, content_type="application/octet-stream")
        self.assertEqual(status, 200)
        info = json.loads(body)
        self.assertEqual(info["size"], len(payload))
        self.assertEqual(info["version"], 1)

        status, body = self.call("GET", "/v1/sync/%s/%s" % (space, DEVICE), token=self.token)
        self.assertEqual(status, 200)
        self.assertEqual(body, payload)

    def test_the_stored_bytes_are_exactly_what_was_uploaded(self):
        space = self.create_space()
        payload = b"\x00\x01opaque ciphertext\xff"
        self.call("PUT", "/v1/sync/%s/%s" % (space, DEVICE), payload,
                  token=self.token, content_type="application/octet-stream")
        self.assertEqual(self.store.get_blob(space, DEVICE), payload)

    def test_the_manifest_lists_devices_without_their_content(self):
        space = self.create_space()
        self.call("PUT", "/v1/sync/%s/%s" % (space, DEVICE), b"one",
                  token=self.token, content_type="application/octet-stream")
        self.call("PUT", "/v1/sync/%s/%s" % (space, OTHER), b"two",
                  token=self.token, content_type="application/octet-stream")
        status, body = self.call("GET", "/v1/sync/%s" % space, token=self.token)
        self.assertEqual(status, 200)
        manifest = json.loads(body)
        self.assertEqual([d["device_id"] for d in manifest["devices"]], [DEVICE, OTHER])
        self.assertNotIn(b"one", body)
        self.assertNotIn(b"two", body)

    def test_re_uploading_bumps_the_version(self):
        space = self.create_space()
        for _ in range(2):
            status, body = self.call("PUT", "/v1/sync/%s/%s" % (space, DEVICE), b"x",
                                      token=self.token, content_type="application/octet-stream")
        self.assertEqual(json.loads(body)["version"], 2)

    def test_a_missing_blob_is_not_found(self):
        space = self.create_space()
        status, body = self.call("GET", "/v1/sync/%s/%s" % (space, DEVICE), token=self.token)
        self.assertEqual(status, 404)

    def test_a_blob_can_be_deleted(self):
        space = self.create_space()
        self.call("PUT", "/v1/sync/%s/%s" % (space, DEVICE), b"x",
                  token=self.token, content_type="application/octet-stream")
        status, _ = self.call("DELETE", "/v1/sync/%s/%s" % (space, DEVICE), token=self.token)
        self.assertEqual(status, 200)
        status, body = self.call("GET", "/v1/sync/%s" % space, token=self.token)
        self.assertEqual(json.loads(body)["devices"], [])


class AuthorizationTests(ServiceTestCase):
    def test_a_request_without_a_token_is_unauthorized(self):
        space = self.create_space()
        status, body = self.call("GET", "/v1/sync/%s" % space)
        self.assertEqual(status, 401)
        self.assertEqual(json.loads(body)["error"], "authentication_required")

    def test_the_wrong_token_is_refused(self):
        space = self.create_space()
        status, body = self.call("GET", "/v1/sync/%s" % space, token="not-the-token")
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body)["error"], "authentication_failed")

    def test_a_token_from_another_space_does_not_open_it(self):
        space = self.create_space()
        other = self.create_space("other-token")
        status, _ = self.call("GET", "/v1/sync/%s" % space, token="other-token")
        self.assertEqual(status, 403)
        self.assertTrue(other)

    def test_an_unknown_space_is_not_found(self):
        status, _ = self.call("GET", "/v1/sync/%s" % ("f" * 32), token=self.token)
        self.assertEqual(status, 404)


class BoundaryTests(ServiceTestCase):
    def test_a_malformed_identifier_is_refused(self):
        status, body = self.call("GET", "/v1/sync/not-a-valid-id", token=self.token)
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["error"], "invalid_space_id")

    def test_a_path_traversal_identifier_is_refused(self):
        status, body = self.call("GET", "/v1/sync/..%2F..%2Fetc", token=self.token)
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["error"], "invalid_space_id")

    def test_a_malformed_device_identifier_is_refused(self):
        space = self.create_space()
        status, body = self.call("GET", "/v1/sync/%s/..%%2F..%%2Fetc" % space, token=self.token)
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["error"], "invalid_device_id")

    def test_a_browser_origin_is_refused(self):
        space = self.create_space()
        status, body = self.call("GET", "/v1/sync/%s" % space, token=self.token,
                                 headers={"Origin": "https://example.com"})
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body)["error"], "origin_rejected")

    def test_a_foreign_host_is_refused(self):
        space = self.create_space()
        status, body = self.call("GET", "/v1/sync/%s" % space, token=self.token,
                                 headers={"Host": "attacker.invalid"})
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body)["error"], "host_rejected")

    def test_an_oversized_body_is_refused_without_buffering_it(self):
        space = self.create_space()
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        connection.putrequest("PUT", "/v1/sync/%s/%s" % (space, DEVICE))
        connection.putheader("Authorization", "Bearer " + self.token)
        connection.putheader("Content-Type", "application/octet-stream")
        connection.putheader("Content-Length", str(MAX_BLOB + 1))
        connection.endheaders()
        connection.send(b"x")
        response = connection.getresponse()
        self.assertEqual(response.status, 413)
        self.assertEqual(json.loads(response.read())["error"], "blob_too_large")
        connection.close()

    def test_a_space_keeps_at_most_a_handful_of_devices(self):
        space = self.create_space()
        for index in range(10):
            status, _ = self.call("PUT", "/v1/sync/%s/%s" % (space, "%032x" % index), b"x",
                                  token=self.token, content_type="application/octet-stream")
            self.assertEqual(status, 200)
        status, body = self.call("PUT", "/v1/sync/%s/%s" % (space, "f" * 32), b"x",
                                 token=self.token, content_type="application/octet-stream")
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(body)["error"], "too_many_devices")

    def test_the_database_is_not_world_readable(self):
        path = Path(self.tmp.name) / "sync.db"
        self.assertTrue(path.exists())
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
