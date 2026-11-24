import json
import tempfile
import threading
import unittest
import unittest.mock
import urllib.error
import urllib.request
from pathlib import Path

from agent_meter import sync_payload, sync_store
from agent_meter.collector import SnapshotService
from agent_meter.model import SourceError, source, timestamp
from agent_meter.server import load_or_create_token, make_server
from agent_meter.sync_payload import build_payload, clean_settings, parse_payload, usage_row

NOW = 1794211200  # 2026-11-09 08:00 Asia/Shanghai
DEVICE = "a" * 32


def token_source(sid, rows, scope="local_session_history", status="available"):
    return {"id": sid, "scope": scope, "status": status,
            "metrics": {"tokens": {"status": status, "value": {"daily_models": rows}}}}


def daily(date, model, tokens=10, app=None):
    row = {"date": date, "model": model, "requests": 2, "fresh_input": 1, "output": 2,
           "reasoning": 3, "cache_read": 4, "cache_write": 0, "total_tokens": tokens}
    if app is not None:
        row["app"] = app
    return row


def snapshot(sources=None, collection=None):
    return {"sources": sources or [], "collection": collection or {}}


class PayloadTests(unittest.TestCase):
    def test_rows_carry_day_app_model_and_device(self):
        data = snapshot([token_source("codex", [daily("2026-11-09", "gpt-5.3-codex")])])
        payload = build_payload(data, DEVICE, now=NOW)
        self.assertEqual(payload["schema"], 1)
        self.assertEqual(payload["device"], DEVICE)
        row = payload["usage"][0]
        self.assertEqual(row["date"], "2026-11-09")
        self.assertEqual(row["app"], "codex")
        self.assertEqual(row["model"], "gpt-5.3-codex")
        self.assertEqual(row["device"], DEVICE)
        self.assertEqual(row["total_tokens"], 10)

    def test_source_ids_map_to_their_application(self):
        data = snapshot([token_source("dsh", [daily("2026-11-09", "m2.7")])])
        payload = build_payload(data, DEVICE, now=NOW)
        self.assertEqual(payload["usage"][0]["app"], "deepseek_harness")

    def test_payload_never_carries_paths_or_labels(self):
        source = token_source("codex", [daily("2026-11-09", "gpt-5.3-codex")])
        source["diagnostics"] = {"reason": None, "store": "/Users/someone/.codex/sessions"}
        source["account_label"] = "工作账号"
        source["account_key"] = "abc123"
        data = snapshot([source])
        data["projects"] = [{"path": "/Users/someone/code/private-repo"}]
        blob = json.dumps(build_payload(data, DEVICE, now=NOW), ensure_ascii=False)
        self.assertNotIn("someone", blob)
        self.assertNotIn("/Users", blob)
        self.assertNotIn("private-repo", blob)
        self.assertNotIn("工作账号", blob)
        self.assertNotIn("abc123", blob)

    def test_payload_drops_per_device_settings(self):
        settings = {"theme": "aurora", "low_quota_threshold": 20, "menu_bar_mode": "flip",
                    "alerts_enabled": True, "source_order": ["codex", "claude"],
                    "budget": {"daily_cny": 50, "anomaly_multiplier": "2.5"},
                    "claim_time": "08:00", "disabled_sources": ["claude"], "low_resource_mode": True,
                    "skip_ledgers_low_resource": ["dsh"], "project_aliases": {"a": "b"}}
        clean = clean_settings(settings)
        self.assertEqual(sorted(clean), ["alerts_enabled", "budget", "low_quota_threshold", "menu_bar_mode",
                                         "source_order", "theme"])
        self.assertNotIn("disabled_sources", clean)
        self.assertNotIn("low_resource_mode", clean)
        self.assertNotIn("claim_time", clean)   # claiming is no longer a setting

    def test_settings_out_of_range_are_dropped(self):
        clean = clean_settings({"low_quota_threshold": 400, "claim_time": "25:00",
                                "source_order": "codex", "theme": "", "menu_bar_mode": "hologram",
                                "alerts_enabled": "yes", "budget": {"daily_cny": "abc"}})
        self.assertEqual(clean, {})

    def test_budget_settings_carry_only_what_is_set(self):
        # An absent key means "no budget"; a present one must be a positive number.
        self.assertEqual(clean_settings({"budget": {"daily_cny": 30}}), {"budget": {"daily_cny": 30.0}})
        self.assertEqual(clean_settings({"budget": {"anomaly_multiplier": 2}}),
                         {"budget": {"anomaly_multiplier": 2.0}})
        for bad in [{"weekly_cny": None}, {"anomaly_multiplier": 0}, {"daily_cny": -5}, {"eur": 1}, "x"]:
            self.assertEqual(clean_settings({"budget": bad}), {})
        # An empty budget means "none" and travels, so clearing it propagates.
        self.assertEqual(clean_settings({"budget": {}}), {"budget": {}})

    def test_quota_keeps_one_observation_per_source_and_window(self):
        source = {"id": "codex", "scope": "account", "status": "available",
                  "account_key": "acct-1",
                  "metrics": {"quota": {"status": "available", "value": [
                      {"bucket": "primary", "window": "primary", "used_percent": 62.0,
                       "remaining_percent": 38.0, "window_minutes": 300,
                       "resets_at": {"epoch_seconds": NOW + 3600}}]}}}
        payload = build_payload(snapshot([source]), DEVICE, now=NOW)
        self.assertEqual(len(payload["quota"]), 1)
        row = payload["quota"][0]
        self.assertEqual(row["account"], "acct-1")
        self.assertEqual(row["day"], "2026-11-09")
        self.assertEqual(row["remaining_percent"], 38.0)
        self.assertEqual(row["resets_at"], NOW + 3600)

    def test_the_quota_source_does_not_leak_the_account_count(self):
        source = {"id": "qoder#3", "scope": "account", "status": "available",
                  "metrics": {"quota": {"status": "available", "value": [
                      {"bucket": "primary", "window": "primary", "used_percent": 10.0}]}}}
        payload = build_payload(snapshot([source]), DEVICE, now=NOW)
        self.assertEqual(payload["quota"][0]["account"], "qoder")

    def test_card_tally_is_counts_only(self):
        data = snapshot(collection={"cards": {"cd_5h": {"count": 3, "first_at": {"epoch_seconds": 1}},
                                              "cd_week": {"count": 1}}})
        payload = build_payload(data, DEVICE, now=NOW)
        self.assertEqual(payload["cards"], {"cd_5h": 3, "cd_week": 1})

    def test_device_must_be_present(self):
        with self.assertRaises(SourceError):
            build_payload(snapshot(), "", now=NOW)
        with self.assertRaises(SourceError):
            build_payload(snapshot(), "x" * 65, now=NOW)


class ParseTests(unittest.TestCase):
    def test_parsed_rows_take_the_device_from_the_payload(self):
        payload = {"schema": 1, "device": "b" * 32, "generated_at": NOW,
                   "usage": [daily("2026-11-09", "gpt-5.3-codex", app="codex")],
                   "quota": [], "cards": {}, "settings": {}}
        record = parse_payload(payload)
        self.assertEqual(record["device"], "b" * 32)
        # A row may not claim to be another device.
        self.assertEqual(record["rows"][0]["device"], "b" * 32)

    def test_a_malformed_row_refuses_the_whole_payload(self):
        # Strict on purpose: a partial record would replace a device's history.
        payload = {"schema": 1, "device": "b" * 32, "usage": [{"model": "x"}]}
        with self.assertRaises(SourceError):
            parse_payload(payload)

    def test_wrong_schema_is_rejected(self):
        with self.assertRaises(SourceError):
            parse_payload({"schema": 2, "device": "b" * 32})
        with self.assertRaises(SourceError):
            parse_payload("not a payload")

    def test_the_quota_timestamps_survive_the_round_trip(self):
        data = snapshot([{"id": "codex", "scope": "account", "status": "available",
                          "account_key": "acct-1",
                          "metrics": {"quota": {"status": "available", "value": [
                              {"bucket": "primary", "window": "primary", "used_percent": 62.0,
                               "remaining_percent": 38.0, "window_minutes": 300,
                               "resets_at": {"epoch_seconds": NOW + 3600}}]}}}])
        payload = build_payload(data, DEVICE, now=NOW)
        record = parse_payload(payload)
        self.assertEqual(record["quota"][0]["observed_at"], float(NOW))
        self.assertEqual(record["quota"][0]["resets_at"], float(NOW + 3600))
        self.assertEqual(record["quota"][0]["account"], "acct-1")

    def test_the_total_is_not_inflated_by_the_request_count(self):
        row = usage_row({"date": "2026-11-09", "model": "m", "requests": 42,
                          "fresh_input": 1, "output": 2, "reasoning": 3,
                          "cache_read": 4, "cache_write": 5}, "codex", DEVICE)
        self.assertEqual(row["total_tokens"], 15)

    def test_an_unclassified_bucket_still_adds_up(self):
        row = usage_row({"date": "2026-11-09", "model": "m", "fresh_input": 1, "output": 1,
                          "unclassified": 7}, "codex", DEVICE)
        self.assertEqual(row["total_tokens"], 9)
        self.assertEqual(row["unclassified"], 7)

    def test_the_payload_keeps_the_most_recent_rows(self):
        rows = [daily("2026-%02d-01" % (month + 1), "m") for month in range(6)]
        data = snapshot([token_source("codex", rows)])
        with unittest.mock.patch.object(sync_payload, "MAX_ROWS", 2):
            payload = build_payload(data, DEVICE, now=NOW)
        self.assertEqual(len(payload["usage"]), 2)
        # The newest days survive the cap.
        self.assertEqual([r["date"] for r in payload["usage"]], ["2026-05-01", "2026-06-01"])

    def test_the_settings_survive_the_round_trip(self):
        payload = {"schema": 1, "device": "b" * 32, "usage": [],
                   "settings": {"theme": "aurora", "low_quota_threshold": 20.0}}
        record = parse_payload(payload)
        self.assertEqual(record["settings"], {"theme": "aurora", "low_quota_threshold": 20.0})


class StoreTests(unittest.TestCase):
    def test_a_remote_device_is_kept_in_its_own_bucket(self):
        with tempfile.TemporaryDirectory() as home:
            record = {"device": "b" * 32, "rows": [daily("2026-11-09", "m2.7")], "cards": {}, "quota": []}
            sync_store.replace_device(home, record)
            store = sync_store.load_store(home)
            self.assertEqual(list(store["devices"]), ["b" * 32])
            self.assertEqual(len(store["devices"]["b" * 32]["rows"]), 1)

    def test_a_device_replaces_its_own_bucket(self):
        with tempfile.TemporaryDirectory() as home:
            sync_store.replace_device(home, {"device": "b" * 32, "rows": [daily("2026-11-09", "m2.7")]})
            sync_store.replace_device(home, {"device": "b" * 32, "rows": [daily("2026-11-10", "m2.7")]})
            store = sync_store.load_store(home)
            rows = store["devices"]["b" * 32]["rows"]
            self.assertEqual([r["date"] for r in rows], ["2026-11-10"])

    def test_our_own_payload_is_not_stored(self):
        with tempfile.TemporaryDirectory() as home:
            sync_store.replace_device(home, {"device": DEVICE, "rows": [daily("2026-11-09", "m2.7")]},
                                      local_device=DEVICE)
            self.assertEqual(sync_store.load_store(home)["devices"], {})

    def test_history_puts_local_rows_first(self):
        store = {"devices": {"b" * 32: {"rows": [daily("2026-11-08", "m2.7")]}}}
        rows = sync_store.history(store, [daily("2026-11-09", "gpt-5.3-codex")])
        self.assertEqual([r["date"] for r in rows], ["2026-11-09", "2026-11-08"])

    def test_reset_forgets_every_device(self):
        with tempfile.TemporaryDirectory() as home:
            sync_store.replace_device(home, {"device": "b" * 32, "rows": []})
            sync_store.reset(home)
            self.assertEqual(sync_store.load_store(home)["devices"], {})

    def test_reset_keeps_who_this_installation_is(self):
        with tempfile.TemporaryDirectory() as home:
            sync_store.set_local_device(home, DEVICE)
            sync_store.reset(home)
            self.assertEqual(sync_store.load_store(home)["local_device"], DEVICE)

    def test_the_same_account_seen_twice_is_one_quota(self):
        with tempfile.TemporaryDirectory() as home:
            row = {"account": "acct-1", "bucket": "primary", "window": "primary",
                   "day": "2026-11-09", "observed_at": 100.0, "used_percent": 40.0}
            newer = dict(row, observed_at=200.0, used_percent=55.0)
            sync_store.replace_device(home, {"device": "b" * 32, "rows": [], "quota": [row]})
            sync_store.replace_device(home, {"device": "c" * 32, "rows": [], "quota": [newer]})
            store = sync_store.load_store(home)
            quota = sync_store.quota_history(store)
            self.assertEqual(len(quota), 1)
            self.assertEqual(quota[0]["used_percent"], 55.0)
            self.assertEqual(quota[0]["device"], "c" * 32)

    def test_remote_quota_survives_a_newer_local_observation(self):
        with tempfile.TemporaryDirectory() as home:
            old = {"account": "acct-1", "bucket": "primary", "window": "primary",
                   "day": "2026-11-09", "observed_at": 100.0, "used_percent": 40.0}
            local = dict(old, observed_at=300.0, used_percent=60.0)
            sync_store.replace_device(home, {"device": "b" * 32, "rows": [], "quota": [old]})
            store = sync_store.load_store(home)
            self.assertIsNone(sync_store.quota_history(store, [local])[0].get("device"))
            remote = sync_store.remote_quota_history(store)
            self.assertEqual(len(remote), 1)
            self.assertEqual(remote[0]["used_percent"], 40.0)
            self.assertEqual(remote[0]["device"], "b" * 32)

    def test_the_card_tally_is_the_highest_any_device_reports(self):
        with tempfile.TemporaryDirectory() as home:
            sync_store.replace_device(home, {"device": "b" * 32, "rows": [], "cards": {"cd": 3}})
            sync_store.replace_device(home, {"device": "c" * 32, "rows": [], "cards": {"cd": 1}})
            store = sync_store.load_store(home)
            self.assertEqual(sync_store.card_history(store), {"cd": 3})

    def test_a_damaged_file_reads_as_empty(self):
        with tempfile.TemporaryDirectory() as home:
            path = Path(home) / sync_store.STORE_NAME
            path.write_text("{not json")
            self.assertEqual(sync_store.load_store(home)["devices"], {})

    def test_the_store_is_written_private(self):
        with tempfile.TemporaryDirectory() as home:
            sync_store.replace_device(home, {"device": "b" * 32, "rows": []})
            mode = (Path(home) / sync_store.STORE_NAME).stat().st_mode & 0o777
            self.assertEqual(mode, 0o600)


class RowTests(unittest.TestCase):
    def test_a_malformed_row_becomes_zero_rather_than_breaking(self):
        row = usage_row({"date": "2026-11-09", "model": "m", "requests": -4, "fresh_input": "x"},
                        "codex", DEVICE)
        self.assertEqual(row["requests"], 0)
        self.assertEqual(row["fresh_input"], 0)
        self.assertEqual(row["total_tokens"], 0)

    def test_total_tokens_survives_an_unclassified_bucket(self):
        row = usage_row({"date": "2026-11-09", "model": "m", "fresh_input": 1, "output": 1,
                          "total_tokens": 9}, "codex", DEVICE)
        self.assertEqual(row["total_tokens"], 9)


def sync_sample(now=NOW):
    """A snapshot with one ledger that has daily rows and one quota window."""
    src = source("codex", "account", now)
    src["metrics"]["tokens"] = {"status": "available", "value": {
        "daily_models": [daily("2026-11-09", "gpt-5.3-codex")]}}
    src["metrics"]["quota"] = {"status": "available", "value": [
        {"bucket": "primary", "window": "primary", "used_percent": 62.0,
         "remaining_percent": 38.0, "window_minutes": 300,
         "resets_at": timestamp(now + 3600)}]}
    return {"schema_version": 5, "collected_at": timestamp(now), "sources": [src],
            "coverage": [], "coverage_summary": {"applications": 1}}


class SyncRouteTests(unittest.TestCase):
    """The local API the sync client talks to."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.token = load_or_create_token(Path(self.tmp.name) / "api.token")
        self.service = SnapshotService({"runtime_dir": self.tmp.name},
                                       lambda config, now: sync_sample(now), lambda: NOW)
        self.server = make_server(self.service, self.token, 0)
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": 0.02}, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:" + str(self.server.server_address[1])

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.tmp.cleanup()

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Authorization": "Bearer " + self.token}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.url + path, data=data, headers=headers, method=method)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            body = exc.read()
            exc.close()
            return exc.code, json.loads(body)

    def test_the_payload_route_returns_a_redacted_projection(self):
        status, payload = self.call("POST", "/v1/sync/payload", {"device": DEVICE})
        self.assertEqual(status, 200)
        self.assertEqual(payload["schema"], 1)
        self.assertEqual(payload["device"], DEVICE)
        self.assertEqual(payload["usage"][0]["date"], "2026-11-09")

    def test_the_payload_route_needs_a_device(self):
        status, body = self.call("POST", "/v1/sync/payload", {"device": ""})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "invalid_sync_payload")

    def test_a_remote_payload_lands_in_the_history(self):
        remote = {"schema": 1, "device": "b" * 32, "generated_at": NOW,
                  "usage": [daily("2026-11-08", "m2.7", app="deepseek_harness")],
                  "quota": [], "cards": {"cd_5h": 2}, "settings": {}}
        status, body = self.call("PUT", "/v1/sync/import",
                                  {"local_device": DEVICE, "payload": remote})
        self.assertEqual(status, 200)
        self.assertEqual(body["rows"], 1)
        self.assertTrue(body["stored"])

        status, history = self.call("GET", "/v1/sync/history")
        self.assertEqual(status, 200)
        self.assertEqual([r["date"] for r in history["rows"]], ["2026-11-09", "2026-11-08"])
        self.assertEqual(history["devices"][0]["device"], "b" * 32)
        self.assertEqual(history["cards"]["cd_5h"], 2)

    def test_our_own_payload_is_not_stored_as_a_remote_device(self):
        status, payload = self.call("POST", "/v1/sync/payload", {"device": DEVICE})
        self.assertEqual(status, 200)
        status, body = self.call("PUT", "/v1/sync/import",
                                  {"local_device": DEVICE, "payload": payload})
        self.assertEqual(status, 200)
        self.assertFalse(body["stored"])
        status, history = self.call("GET", "/v1/sync/history")
        self.assertEqual(history["devices"], [])
        self.assertEqual(len(history["rows"]), 1)

    def test_a_malformed_payload_is_refused(self):
        status, body = self.call("PUT", "/v1/sync/import",
                                  {"local_device": DEVICE, "payload": {"schema": 9}})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "invalid_sync_payload")

    def test_a_refused_import_does_not_repoint_this_installation(self):
        status, _ = self.call("POST", "/v1/sync/payload", {"device": DEVICE})
        self.assertEqual(status, 200)
        status, _ = self.call("PUT", "/v1/sync/import",
                               {"local_device": "f" * 32, "payload": {"schema": 9}})
        self.assertEqual(status, 400)
        status, history = self.call("GET", "/v1/sync/history")
        self.assertEqual(history["local_device"], DEVICE)

    def test_a_payload_with_bad_rows_cannot_wipe_a_device(self):
        good = {"schema": 1, "device": "b" * 32,
                "usage": [daily("2026-11-08", "m2.7", app="deepseek_harness")]}
        self.call("PUT", "/v1/sync/import", {"local_device": DEVICE, "payload": good})
        bad = {"schema": 1, "device": "b" * 32, "usage": [{"model": "x"}]}
        status, _ = self.call("PUT", "/v1/sync/import", {"local_device": DEVICE, "payload": bad})
        self.assertEqual(status, 400)
        status, history = self.call("GET", "/v1/sync/history")
        self.assertEqual(len(history["rows"]), 2)

    def test_reset_forgets_the_remote_devices(self):
        remote = {"schema": 1, "device": "b" * 32, "usage": [daily("2026-11-08", "m2.7")]}
        self.call("PUT", "/v1/sync/import", {"local_device": DEVICE, "payload": remote})
        status, _ = self.call("POST", "/v1/sync/reset", {"device": DEVICE})
        self.assertEqual(status, 200)
        status, history = self.call("GET", "/v1/sync/history")
        self.assertEqual(history["devices"], [])
        self.assertEqual(len(history["rows"]), 1)

    def test_the_sync_routes_need_the_local_token(self):
        request = urllib.request.Request(self.url + "/v1/sync/history")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            opener.open(request, timeout=5)
        self.assertEqual(ctx.exception.code, 401)
        ctx.exception.close()

    def test_the_history_never_leaks_into_the_snapshot(self):
        remote = {"schema": 1, "device": "b" * 32, "usage": [daily("2026-11-08", "m2.7")]}
        self.call("PUT", "/v1/sync/import", {"device": DEVICE, "payload": remote})
        status, snapshot = self.call("GET", "/v1/snapshot")
        self.assertEqual(status, 200)
        self.assertNotIn("sync", snapshot)
        self.assertEqual(len(snapshot["sources"]), 1)


def quota_source(sid, rows, key=None):
    out = {"id": sid, "scope": "account", "status": "available",
           "metrics": {"quota": {"status": "available", "value": rows}}}
    if key:
        out["account_key"] = key
    return out


class QuotaWindowTests(unittest.TestCase):
    def test_every_provider_window_shape_is_carried(self):
        snapshot = {"sources": [
            quota_source("codex", [{"bucket": "codex", "window": "primary", "window_minutes": 10080,
                                    "remaining_percent": 80}], "k1"),
            quota_source("claude", [{"bucket": "five_hour", "window_minutes": 300, "remaining_percent": 70},
                                    {"bucket": "seven_day", "window_minutes": 10080, "remaining_percent": 60}], "k2"),
            quota_source("kimi", [{"bucket": "limit5h", "window": {"duration": 5, "unit": "hour"},
                                   "remaining_percent": 50}]),
            quota_source("workbuddy", [{"bucket": "credits", "remaining_percent": 40}]),
            quota_source("zcode", [{"bucket": "quota", "window_minutes": 300, "remaining_percent": 30},
                                   {"bucket": "quota", "window_minutes": 10080, "remaining_percent": 20}]),
        ]}
        rows = sync_payload.quota_rows(snapshot, NOW)
        self.assertEqual([(r["account"], r["bucket"], r["window"]) for r in rows], [
            ("k1", "codex", "primary"), ("k2", "five_hour", "300m"), ("k2", "seven_day", "10080m"),
            ("kimi", "limit5h", "5hour"), ("workbuddy", "credits", "all"),
            ("zcode", "quota", "300m"), ("zcode", "quota", "10080m")])
        parsed = parse_payload(build_payload(snapshot, DEVICE, now=NOW))
        self.assertEqual(len(parsed["quota"]), 7)

    def test_same_account_on_two_devices_is_one_row_with_the_newest_value(self):
        day = sync_payload.quota_rows({"sources": [quota_source("kimi", [{"bucket": "5h", "remaining_percent": 90}])]},
                                      NOW)[0]
        older, newer = dict(day, remaining_percent=90, observed_at=NOW - 60), dict(day, remaining_percent=35, observed_at=NOW)
        store = {"local_device": DEVICE, "devices": {"b" * 32: {"quota": [newer]}, "c" * 32: {"quota": [older]}}}
        rows = sync_store.quota_history(store, [dict(day, remaining_percent=70, observed_at=NOW - 30)])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["remaining_percent"], 35)
        self.assertEqual(rows[0]["device"], "b" * 32)

    def test_different_accounts_stay_separate(self):
        snapshot = {"sources": [quota_source("claude", [{"bucket": "five_hour", "window_minutes": 300}], "k1"),
                                quota_source("claude#2", [{"bucket": "five_hour", "window_minutes": 300}], "k2")]}
        self.assertEqual({r["account"] for r in sync_payload.quota_rows(snapshot, NOW)}, {"k1", "k2"})

    def test_two_logins_without_an_account_id_are_not_merged(self):
        snapshot = {"sources": [quota_source("kimi", [{"bucket": "limit5h", "remaining_percent": 90}]),
                                quota_source("kimi#2", [{"bucket": "limit5h", "remaining_percent": 10}])]}
        self.assertEqual(sync_payload.quota_rows(snapshot, NOW), [])


def seen(account, used, reset=NOW + 3600, observed=NOW, provider="kimi", bucket="5h"):
    return {"account": account, "provider": provider, "bucket": bucket, "window": "300m", "day": "2026-11-09",
            "observed_at": observed, "used_percent": used, "remaining_percent": 100 - used,
            "window_minutes": 300, "resets_at": reset}


class KeylessAccountTests(unittest.TestCase):
    def resolve(self, local, *remote):
        store = {"local_device": DEVICE, "devices": {
            chr(ord("b") + i) * 32: {"quota": rows} for i, rows in enumerate(remote)}}
        view = sync_store.resolve_accounts(store, local)
        return [row["account"] for device in sorted(view["devices"]) for row in view["devices"][device]["quota"]]

    def test_matching_reset_and_usage_is_one_account(self):
        self.assertEqual(self.resolve([seen("kimi", 40)], [seen("kimi", 37, NOW + 3650, NOW - 300)]), ["kimi"])

    def test_different_reset_time_is_another_account(self):
        self.assertEqual(self.resolve([seen("kimi", 40)], [seen("kimi", 40, NOW + 9000)]), ["kimi~" + "b" * 8])

    def test_usage_one_account_could_not_produce_is_another_account(self):
        self.assertEqual(self.resolve([seen("kimi", 80)], [seen("kimi", 20)]), ["kimi~" + "b" * 8])

    def test_keyless_joins_the_keyed_account_of_its_provider(self):
        key = "a" * 24
        self.assertEqual(self.resolve([seen(key, 40, provider="claude")], [seen("claude", 41, provider="claude")]), [key])

    def test_two_keyed_accounts_are_never_merged(self):
        one, two = "a" * 24, "b" * 24
        self.assertEqual(self.resolve([seen(one, 40, provider="claude")], [seen(two, 40, provider="claude")]), [two])

    def test_windows_and_mac_names_of_one_provider_match(self):
        self.assertEqual(self.resolve([seen("minimax_code", 40, provider="minimax_code")],
                                      [seen("mcode", 40, provider="mcode")]), ["minimax_code"])

    def test_a_finished_window_does_not_split_an_account(self):
        old = seen("kimi", 90, NOW - 60, NOW - 7200)
        self.assertEqual(self.resolve([seen("kimi", 5)], [old]), ["kimi"])

    def test_no_shared_window_stays_separate(self):
        self.assertEqual(self.resolve([seen("kimi", 40)], [seen("kimi", 40, bucket="week")]), ["kimi~" + "b" * 8])

    def test_the_stored_rows_are_not_rewritten(self):
        rows = [seen("kimi", 20)]
        store = {"local_device": DEVICE, "devices": {"b" * 32: {"quota": rows}}}
        sync_store.resolve_accounts(store, [seen("kimi", 80)])
        self.assertEqual(rows[0]["account"], "kimi")


if __name__ == "__main__":
    unittest.main()