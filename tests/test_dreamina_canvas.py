import json
import subprocess
import unittest
from unittest import mock

from agent_meter.collector import collect_dreamina_route
from agent_meter.dreamina import collect_dreamina_canvas
from agent_meter.model import SourceError

NOW = 1762600000.0
ENVELOPE = {"schemaVersion": "1", "ok": True,
            "data": {"userId": 123456789, "isVip": True, "vipLevel": "maestro"},
            "meta": {"requestId": "x"}}


def completed(stdout=b"", stderr=b"", returncode=0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class DreaminaCanvasTests(unittest.TestCase):
    def test_contract(self):
        with mock.patch("agent_meter.dreamina.subprocess.run",
                        return_value=completed(json.dumps(ENVELOPE).encode())) as run:
            out = collect_dreamina_canvas("/bin/true", NOW)
        self.assertEqual(run.call_args[0][0],
                         ["/bin/true", "auth", "account", "--format", "json", "--non-interactive"])
        self.assertEqual((out["id"], out["scope"], out["status"]), ("dreamina", "creative_account", "available"))
        self.assertEqual(out["subscription"], {"plan": "maestro"})
        self.assertEqual(out["metrics"]["credits"]["status"], "not_provided")
        self.assertEqual(out["metrics"]["credits"]["reason"], "dreamina_canvas_cli_no_credit_query")
        self.assertEqual(out["diagnostics"]["transport"], "dreamina_canvas_auth_account")
        self.assertTrue(out["account_key"])

    def test_not_authenticated(self):
        with mock.patch("agent_meter.dreamina.subprocess.run",
                        return_value=completed(stderr="请先登录".encode(), returncode=1)):
            with self.assertRaises(SourceError) as raised:
                collect_dreamina_canvas("/bin/true", NOW)
        self.assertEqual(raised.exception.code, "dreamina_not_authenticated")

    def test_timeout(self):
        with mock.patch("agent_meter.dreamina.subprocess.run",
                        side_effect=subprocess.TimeoutExpired(cmd="x", timeout=1)):
            with self.assertRaises(SourceError) as raised:
                collect_dreamina_canvas("/bin/true", NOW)
        self.assertEqual(raised.exception.code, "dreamina_cli_timeout")

    def test_bad_json(self):
        with mock.patch("agent_meter.dreamina.subprocess.run", return_value=completed(b"not json")):
            with self.assertRaises(SourceError) as raised:
                collect_dreamina_canvas("/bin/true", NOW)
        self.assertEqual(raised.exception.code, "invalid_dreamina_json")

    def test_unsupported_envelope(self):
        with mock.patch("agent_meter.dreamina.subprocess.run",
                        return_value=completed(json.dumps({"ok": False}).encode())):
            with self.assertRaises(SourceError) as raised:
                collect_dreamina_canvas("/bin/true", NOW)
        self.assertEqual(raised.exception.code, "unsupported_dreamina_contract")

    def test_missing_binary(self):
        with self.assertRaises(SourceError) as raised:
            collect_dreamina_canvas(None, NOW)
        self.assertEqual(raised.exception.code, "dreamina_cli_not_available")

    def test_route_prefers_legacy_then_canvas(self):
        config = {"enable_dreamina_cli": True, "billing_overrides": {},
                  "dreamina_binary": "/old/dreamina", "dreamina_canvas_binary": "/new/dreamina-canvas"}
        with mock.patch("agent_meter.collector.collect_dreamina", return_value="legacy") as legacy:
            self.assertEqual(collect_dreamina_route(config, NOW, 20), "legacy")
            legacy.assert_called_once()
        config["dreamina_binary"] = None
        with mock.patch("agent_meter.collector.collect_dreamina_canvas", return_value="canvas") as canvas:
            self.assertEqual(collect_dreamina_route(config, NOW, 20), "canvas")
            canvas.assert_called_once()
        config["dreamina_canvas_binary"] = None
        with self.assertRaises(SourceError) as raised:
            collect_dreamina_route(config, NOW, 20)
        self.assertEqual(raised.exception.code, "dreamina_cli_not_available")
        config["enable_dreamina_cli"] = False
        with self.assertRaises(SourceError) as raised:
            collect_dreamina_route(config, NOW, 20)
        self.assertEqual(raised.exception.code, "web_session_missing")


if __name__ == "__main__":
    unittest.main()