"""Windows sync bridge against a real (local) sync server."""
import base64
import json
import os
import tempfile
import threading
import time
import unittest
import unittest.mock
from pathlib import Path

from agent_meter.sync_crypto import SyncKeys, random_identifier, random_master_key
from sync_server.app import Store, make_server
from windows import sync_ops


def run(fn, request):
    out = []
    fn(request, lambda value: out.append(json.loads(value)))
    return out


def snapshot(tokens=120, day="2026-11-20"):
    return {"sources": [{
        "id": "codex",
        "metrics": {"tokens": {"status": "available", "value": {"daily_models": [{
            "date": day, "model": "gpt-5", "fresh_input": max(tokens - 20, 0),
            "output": min(tokens, 20), "reasoning": 0, "cache_read": 0,
            "cache_write": 0, "requests": 2, "total_tokens": tokens,
        }]}}},
    }]}


class ServerCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = unittest.mock.patch.dict(os.environ, {"LOCALAPPDATA": self.temp.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.store = Store(str(Path(self.temp.name) / "sync.db"))
        self.server = make_server(self.store, 0, "127.0.0.1", ())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def _stop(self):
        self.server.shutdown()
        self.thread.join(5)
        self.server.server_close()
        self.store.close()

    def request(self, space, master, device, **extra):
        value = {"base_url": self.base, "space_id": space, "device_id": device,
                 "master_key": base64.b64encode(master).decode("ascii")}
        value.update(extra)
        return value


class SpaceTests(ServerCase):
    def test_create_push_pull_devices(self):
        space, master = random_identifier(), random_master_key()
        a, b = random_identifier(), random_identifier()
        self.assertEqual(run(sync_ops.create_space,
                             self.request(space, master, a))[0]["status"], "ok")
        pushed = run(lambda req, emit: sync_ops.push(req, emit, snapshot=snapshot()),
                     self.request(space, master, a))[0]
        self.assertTrue(pushed["uploaded"])
        self.assertEqual(pushed["devices"], 1)
        pulled = run(sync_ops.pull, self.request(space, master, b))[0]
        self.assertEqual(pulled["imported"], [a])
        self.assertEqual(pulled["failed"], [])
        self.assertEqual(run(sync_ops.devices, self.request(space, master, b))[0]["devices"][0]["device_id"], a)
        stored = json.loads((Path(self.temp.name) / "AgentMeter" / "synced-history.json").read_text())
        self.assertEqual(stored["local_device"], b)
        self.assertEqual(stored["devices"][a]["rows"][0]["app"], "codex")
        self.assertEqual(stored["devices"][a]["rows"][0]["total_tokens"], 120)

    def test_repeat_push_is_idempotent(self):
        space, master, a = random_identifier(), random_master_key(), random_identifier()
        sync_ops.create_space(self.request(space, master, a), lambda value: None)
        for _ in range(2):
            run(lambda req, emit: sync_ops.push(req, emit, snapshot=snapshot()),
                self.request(space, master, a))
        self.assertEqual(len(run(sync_ops.devices, self.request(space, master, a))[0]["devices"]), 1)

    def test_one_bad_blob_does_not_stop_round(self):
        space, master = random_identifier(), random_master_key()
        a, b, broken = random_identifier(), random_identifier(), random_identifier()
        sync_ops.create_space(self.request(space, master, a), lambda value: None)
        run(lambda req, emit: sync_ops.push(req, emit, snapshot=snapshot()),
            self.request(space, master, a))
        # A third device's blob is valid base64 but not this space's ciphertext.
        keys = SyncKeys(master, space)
        from agent_meter.sync_remote import SyncService
        SyncService(self.base).put(space, broken, keys.auth_token, b"x" * 64)
        pulled = run(sync_ops.pull, self.request(space, master, b))[0]
        self.assertIn(a, pulled["imported"])
        self.assertIn(broken, pulled["failed"])
        self.assertFalse(pulled["uploaded"])

    def test_remove_device_and_disconnect_clear_remote_rows(self):
        space, master = random_identifier(), random_master_key()
        a, b = random_identifier(), random_identifier()
        sync_ops.create_space(self.request(space, master, a), lambda value: None)
        for device in (a, b):
            run(lambda req, emit: sync_ops.push(req, emit, snapshot=snapshot()),
                self.request(space, master, device))
        removed = run(sync_ops.remove_device,
                      self.request(space, master, a, remote_device_id=b))[0]
        self.assertEqual(removed["removed"], b)
        listed = run(sync_ops.devices, self.request(space, master, a))[0]
        self.assertEqual([entry["device_id"] for entry in listed["devices"]], [a])
        sync_ops.reset_local(self.request(space, master, a), lambda value: None)
        stored = json.loads((Path(self.temp.name) / "AgentMeter" / "synced-history.json").read_text())
        self.assertEqual(stored["devices"], {})

    def test_wrong_base_url_is_refused(self):
        for value in ("http://example.com", "ftp://127.0.0.1", "https://user:pass@example.com"):
            with self.assertRaises(Exception):
                from agent_meter.sync_remote import validate_base_url
                validate_base_url(value)

    def test_bad_remote_device_id_is_ignored(self):
        space, master, a = random_identifier(), random_master_key(), random_identifier()
        sync_ops.create_space(self.request(space, master, a), lambda value: None)
        run(lambda req, emit: sync_ops.push(req, emit, snapshot=snapshot()),
            self.request(space, master, a))
        # A malformed row in the manifest must not reach a URL path or the UI.
        self.store.put_blob(space, "../not-a-device", b"x" * 64)
        listed = run(sync_ops.devices, self.request(space, master, a))[0]
        self.assertEqual([entry["device_id"] for entry in listed["devices"]], [a])


class PairingTests(ServerCase):
    def test_pair_hands_off_master_key_and_same_sas(self):
        space, master, a = random_identifier(), random_master_key(), random_identifier()
        events = []
        sync_ops.create_space(self.request(space, master, a), lambda value: None)
        creator = threading.Thread(target=lambda: sync_ops.pair_create(
            self.request(space, master, a), lambda value: events.append(json.loads(value))))
        creator.start()
        deadline = time.time() + 5
        while not any(event.get("event") == "code" for event in events) and time.time() < deadline:
            time.sleep(0.05)
        code = next(event["code"] for event in events if event.get("event") == "code")
        joined = []
        sync_ops.pair_join({"base_url": self.base, "code": code},
                           lambda value: joined.append(json.loads(value)))
        creator.join(10)
        final = joined[-1]
        self.assertEqual(final["event"], "joined")
        self.assertEqual(SyncKeys(base64.b64decode(final["master_key"]), final["space_id"]).master_key, master)
        self.assertEqual(final["sas"], next(event["sas"] for event in events if event.get("event") == "paired"))

    def test_bad_code(self):
        with self.assertRaises(Exception):
            sync_ops.pair_join({"base_url": self.base, "code": "12345"}, lambda value: None)


class SnapshotTests(unittest.TestCase):
    def test_daily_buckets_become_one_aggregate_row(self):
        result = {
            "history": {"WorkBuddy": {"status": "available", "value": {
                "daily_buckets": [{"date": "2026-11-19", "tokens": 42},
                                  {"date": "2026-11-20", "tokens": 8}]}}},
            "account": {"quota": {"status": "available", "value": [
                {"bucket": "codex", "window": "5h", "used_percent": 10,
                 "remaining_percent": 90, "window_minutes": 300}]}},
        }
        value = sync_ops.windows_snapshot(result)
        tokens = next(source for source in value["sources"] if source["id"] == "workbuddy")
        rows = tokens["metrics"]["tokens"]["value"]["daily_models"]
        self.assertEqual([row["model"] for row in rows], ["(all)", "(all)"])
        self.assertEqual([row["total_tokens"] for row in rows], [42, 8])
        quota = next(source for source in value["sources"] if source["id"] == "codex")
        self.assertEqual(quota["metrics"]["quota"]["value"][0]["bucket"], "codex")

    def test_model_rows_are_kept(self):
        result = {"history": {"Codex": {"status": "available", "value": {
            "daily_models": [{"date": "2026-11-20", "model": "gpt-5", "total_tokens": 9}]}}}}
        rows = sync_ops.windows_snapshot(result)["sources"][0]["metrics"]["tokens"]["value"]["daily_models"]
        self.assertEqual(rows[0]["model"], "gpt-5")


if __name__ == "__main__":
    unittest.main()
