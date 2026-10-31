"""Hermetic tests for the Antigravity language_server quota reader.

Synthetic JSON mirrors the decoded RPC contract; no real process, token or
account data is used.
"""
import json
import unittest
import urllib.error
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import mock

from agent_meter.agy_quota import (WINDOW_MINUTES, _parse_listening_ports, _server_candidates,
                                   collect_antigravity_quota, model_quota_rows, quota_rows)
from agent_meter.model import SourceError

NOW = int(datetime(2026, 10, 31, 4, 0, tzinfo=timezone.utc).timestamp())

SUMMARY = {"response": {"groups": [
    {"displayName": "Gemini Models", "description": "fixed group text", "buckets": [
        {"bucketId": "gemini-weekly", "displayName": "Weekly Limit Remaining",
         "description": "weekly bucket text", "window": "weekly",
         "remainingFraction": 0.9841846, "resetTime": "2026-11-06T22:25:10Z"},
        {"bucketId": "gemini-5h", "displayName": "Five Hour Limit Remaining",
         "description": "5h bucket text", "window": "5h",
         "remainingFraction": 0.95964605, "resetTime": "2026-10-31T03:25:10Z"},
    ]},
    {"displayName": "Claude and GPT models", "description": "fixed group text", "buckets": [
        {"bucketId": "3p-weekly", "displayName": "Weekly Limit Remaining",
         "description": "weekly bucket text", "window": "weekly",
         "remainingFraction": 0.677588, "resetTime": "2026-11-06T22:20:24Z"},
        {"bucketId": "3p-5h", "displayName": "Five Hour Limit Remaining",
         "description": "5h bucket text", "window": "5h",
         "remainingFraction": 0.365176, "resetTime": "2026-10-31T03:20:24Z"},
    ]},
    {"displayName": "Gemini 4 Argon", "description": "fixed group text", "buckets": [
        {"bucketId": "gemini-argon-wtu-weekly", "displayName": "Gemini 4 Argon Weekly Limit",
         "window": "weekly", "remainingFraction": 1, "resetTime": "2026-11-06T22:56:29Z"},
    ]},
]}}

# The personal fields are deliberately present to prove they are never copied.
STATUS = {"userStatus": {
    "name": "Private Person", "email": "private@example.com",
    "cascadeModelConfigData": {"clientModelConfigs": [
        {"modelId": "model-with-reset", "label": "Model With Reset",
         "quotaInfo": {"remainingFraction": 0.5, "resetTime": "2026-10-31T06:00:00Z"}},
        {"modelId": "model-without-reset", "label": "Model Without Reset",
         "quotaInfo": {"remainingFraction": 0.25}},
    ]}}}

PS_TEXT = "\n".join([
    " 100 /opt/cli/bin/language_server --standalone --override_ide_name antigravity"
    " --override_ide_version 1.0.0 --csrf_token cli-token --app_data_dir antigravity-cli",
    " 200 /Applications/Antigravity.app/Contents/Resources/bin/language_server --standalone"
    " --override_ide_name antigravity --override_ide_version 2.28.2"
    " --csrf_token=desktop-token --app_data_dir=antigravity",
    " 300 /usr/bin/other --app_data_dir antigravity --csrf_token ignored-token",
    " 400 /opt/cli/bin/language_server --app_data_dir antigravity",
])

LSOF_TEXT = "\n".join([
    "COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME",
    "language_ 200 u 7u IPv4 0x1 0t0 TCP 127.0.0.1:53427 (LISTEN)",
    "language_ 200 u 8u IPv4 0x2 0t0 TCP 127.0.0.1:53428 (LISTEN)",
    "language_ 200 u 8u IPv6 0x3 0t0 TCP [::1]:53428 (LISTEN)",
    "language_ 200 u 9u IPv4 0x4 0t0 TCP 10.0.0.5:8080 (ESTABLISHED)",
])


class FakeResponse:
    def __init__(self, body):
        self._body = body

    def read(self, _limit=None):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _ps_output(stdout):
    return SimpleNamespace(returncode=0, stdout=stdout, stderr="")


def _lsof_output(stdout):
    return SimpleNamespace(returncode=0, stdout=stdout, stderr="")


class QuotaRowsTests(unittest.TestCase):
    def test_rows_fields_math_and_window_minutes(self):
        rows = quota_rows(SUMMARY)
        self.assertEqual(len(rows), 5)
        gemini_weekly, gemini_5h = rows[0], rows[1]
        self.assertEqual(gemini_weekly["bucket"], "gemini-weekly")
        self.assertEqual(gemini_weekly["group"], "Gemini Models")
        self.assertEqual(gemini_weekly["window"], "weekly")
        self.assertEqual(gemini_weekly["window_minutes"], WINDOW_MINUTES["weekly"])
        self.assertAlmostEqual(gemini_weekly["remaining_fraction"], 0.9841846)
        self.assertAlmostEqual(gemini_weekly["remaining_percent"], 98.41846)
        self.assertAlmostEqual(gemini_weekly["used_percent"], 1.58154)
        self.assertEqual(gemini_weekly["description"], "weekly bucket text")
        self.assertEqual(gemini_weekly["source"], "agy_language_server")
        self.assertEqual(gemini_5h["window_minutes"], 300)
        self.assertEqual(gemini_weekly["resets_at"]["epoch_seconds"],
                         datetime(2026, 11, 6, 22, 25, 10, tzinfo=timezone.utc).timestamp())

    def test_rows_preserve_group_order(self):
        rows = quota_rows(SUMMARY)
        self.assertEqual([r["group"] for r in rows],
                         ["Gemini Models", "Gemini Models", "Claude and GPT models",
                          "Claude and GPT models", "Gemini 4 Argon"])
        self.assertEqual([r["bucket"] for r in rows],
                         ["gemini-weekly", "gemini-5h", "3p-weekly", "3p-5h",
                          "gemini-argon-wtu-weekly"])

    def test_accepts_unwrapped_groups(self):
        self.assertEqual(len(quota_rows({"groups": SUMMARY["response"]["groups"]})), 5)

    def test_malformed_summary_is_unreadable(self):
        for payload in ({"response": {"groups": "nope"}}, {"response": {}},
                        {"response": {"groups": [{"buckets": [{"bucketId": "x"}]}]}}):
            with self.assertRaises(SourceError) as ctx:
                quota_rows(payload)
            self.assertEqual(ctx.exception.code, "antigravity_quota_unreadable")

    def test_no_personal_fields_in_rows(self):
        rendered = json.dumps(quota_rows(SUMMARY))
        self.assertNotIn("Private Person", rendered)
        self.assertNotIn("private@example.com", rendered)

    def test_model_fallback_only_models_with_reset(self):
        rows = model_quota_rows(STATUS)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["bucket"], "model-with-reset")
        self.assertEqual(rows[0]["source"], "agy_language_server_models")
        self.assertIsNone(rows[0]["window_minutes"])
        self.assertEqual(rows[0]["remaining_percent"], 50)
        rendered = json.dumps(rows)
        self.assertNotIn("Private Person", rendered)
        self.assertNotIn("private@example.com", rendered)


class ProcessDiscoveryTests(unittest.TestCase):
    def test_desktop_server_is_preferred(self):
        candidates = _server_candidates(PS_TEXT)
        self.assertEqual([c["pid"] for c in candidates], [200, 100])
        self.assertEqual(candidates[0]["csrf_token"], "desktop-token")
        self.assertEqual(candidates[0]["ide_version"], "2.28.2")
        self.assertEqual(candidates[0]["app_data_dir"], "antigravity")

    def test_listening_ports_are_deduplicated(self):
        self.assertEqual(_parse_listening_ports(LSOF_TEXT), [53427, 53428])


class CollectTests(unittest.TestCase):
    def test_no_running_server(self):
        with mock.patch("agent_meter.agy_quota.subprocess.run",
                        return_value=_ps_output("1 /usr/bin/python -m http.server\n")):
            with self.assertRaises(SourceError) as ctx:
                collect_antigravity_quota(NOW)
        self.assertEqual(ctx.exception.code, "antigravity_language_server_not_running")

    def test_rpc_failure_is_unreadable(self):
        with mock.patch("agent_meter.agy_quota.subprocess.run",
                        side_effect=[_ps_output(PS_TEXT), _lsof_output(LSOF_TEXT)]), \
                mock.patch("agent_meter.agy_quota.urllib.request.urlopen",
                           side_effect=urllib.error.URLError("blocked")):
            with self.assertRaises(SourceError) as ctx:
                collect_antigravity_quota(NOW)
        self.assertEqual(ctx.exception.code, "antigravity_quota_unreadable")

    def test_https_port_skipped_http_port_used(self):
        calls = []
        seen_headers = {}

        def fake_urlopen(request, timeout=None):
            calls.append(request.full_url)
            seen_headers.update(request.headers)
            if ":53427" in request.full_url:
                raise urllib.error.URLError("not an HTTP endpoint")
            payload = SUMMARY if "RetrieveUserQuotaSummary" in request.full_url else STATUS
            return FakeResponse(json.dumps(payload).encode())

        with mock.patch("agent_meter.agy_quota.subprocess.run",
                        side_effect=[_ps_output(PS_TEXT), _lsof_output(LSOF_TEXT)]), \
                mock.patch("agent_meter.agy_quota.urllib.request.urlopen", side_effect=fake_urlopen):
            rows = collect_antigravity_quota(NOW)
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0]["source"], "agy_language_server")
        self.assertTrue(any(":53427" in url for url in calls))
        self.assertTrue(any(":53428" in url for url in calls))
        csrf = [value for key, value in seen_headers.items()
                if key.lower() == "x-codeium-csrf-token"]
        self.assertEqual(csrf, ["desktop-token"])
        self.assertNotIn("private@example.com", json.dumps(rows))

    def test_model_fallback_when_summary_unavailable(self):
        def fake_urlopen(request, timeout=None):
            if "RetrieveUserQuotaSummary" in request.full_url:
                raise urllib.error.URLError("summary unavailable")
            return FakeResponse(json.dumps(STATUS).encode())

        with mock.patch("agent_meter.agy_quota.subprocess.run",
                        side_effect=[_ps_output(PS_TEXT), _lsof_output(LSOF_TEXT)]), \
                mock.patch("agent_meter.agy_quota.urllib.request.urlopen", side_effect=fake_urlopen):
            rows = collect_antigravity_quota(NOW)
        self.assertEqual([r["bucket"] for r in rows], ["model-with-reset"])
        self.assertEqual(rows[0]["source"], "agy_language_server_models")
        self.assertNotIn("Private Person", json.dumps(rows))


if __name__ == "__main__":
    unittest.main()
