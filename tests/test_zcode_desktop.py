import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_meter import zcode_desktop
from agent_meter.collector import collect_zcode_route
from agent_meter.model import SourceError
from agent_meter.zcode_desktop import (collect_zcode_desktop, credential_secret,
                                       decrypt_entries, load_desktop_credentials,
                                       parse_reset_status)

NOW = 1762600000.0
NODE = shutil.which("node")


def card(days=30, **extra):
    row = {"expires_at": int((NOW + days * 86400) * 1000)}
    row.update(extra)
    return row


class ParseResetStatusTests(unittest.TestCase):
    def test_keeps_all_cards_without_truncation(self):
        payload = {"code": 0, "data": {
            "available_five_hour_resets": [card(1) for _ in range(4)],
            "available_week_resets": [card(20) for _ in range(7)],
        }}
        out = parse_reset_status(payload, NOW)
        self.assertEqual(out["available_count"], 11)   # reference impl truncates to 6; we must not
        self.assertEqual(out["details_state"], "returned")
        self.assertEqual({c["reset_type"] for c in out["cards"]}, {"five_hour", "week"})
        self.assertEqual(out["cards"][0]["reset_type"], "five_hour")   # sorted by expiry
        self.assertAlmostEqual(out["next_known_expiry"]["epoch_seconds"], NOW + 86400, places=3)

    def test_expired_cards_dropped(self):
        payload = {"data": {"available_week_resets": [card(-2), card(10)]}}
        out = parse_reset_status(payload, NOW)
        self.assertEqual(out["available_count"], 1)

    def test_missing_expiry_is_not_expired(self):
        payload = {"data": {"available_week_resets": [{}]}}
        out = parse_reset_status(payload, NOW)
        self.assertEqual(out["cards"][0]["expiration_state"], "no_expiry_reported")
        self.assertIsNone(out["next_known_expiry"])

    def test_business_and_auth_errors(self):
        with self.assertRaises(SourceError) as raised:
            parse_reset_status({"code": 401}, NOW)
        self.assertEqual(raised.exception.code, "not_authenticated")
        with self.assertRaises(SourceError) as raised:
            parse_reset_status({"code": 500}, NOW)
        self.assertEqual(raised.exception.code, "zcode_reset_api_error")

    def test_unsupported_contract(self):
        with self.assertRaises(SourceError) as raised:
            parse_reset_status({"data": {"something_else": []}}, NOW)
        self.assertEqual(raised.exception.code, "unsupported_zcode_reset_contract")
        with self.assertRaises(SourceError) as raised:
            parse_reset_status({"data": {"available_week_resets": "nope"}}, NOW)
        self.assertEqual(raised.exception.code, "unsupported_zcode_reset_contract")


class CredentialTests(unittest.TestCase):
    def test_secret_fallback_shape(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch("agent_meter.zcode_desktop.getpass.getuser", return_value="tester"), \
                mock.patch("agent_meter.zcode_desktop.sys.platform", "darwin"):
            secret = credential_secret("/Users/tester")
        self.assertEqual(secret, "zcode-credential-fallback:darwin:/Users/tester:tester")
        with mock.patch.dict(os.environ, {"ZCODE_CREDENTIAL_SECRET": " explicit "}):
            self.assertEqual(credential_secret("/Users/tester"), "explicit")

    def test_missing_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SourceError) as raised:
                load_desktop_credentials(tmp, NODE)
            self.assertEqual(raised.exception.code, "zcode_desktop_not_installed")

    def test_unreadable_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "credentials.json").write_text("not json")
            with self.assertRaises(SourceError) as raised:
                load_desktop_credentials(tmp, NODE)
            self.assertEqual(raised.exception.code, "zcode_desktop_credentials_unreadable")

    def test_current_family_selection_and_identity(self):
        plain = {"zcodejwttoken": "jwt-x", "oauth:active_provider": "bigmodel",
                 "oauth:bigmodel:access_token": "coding-big", "oauth:zai:access_token": "coding-zai",
                 "oauth:bigmodel:user_info": json.dumps({"id": 42, "displayName": "x"})}
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "credentials.json").write_text(json.dumps({k: "enc:v1:x" for k in plain}))
            with mock.patch("agent_meter.zcode_desktop.decrypt_entries", return_value=plain):
                creds = load_desktop_credentials(tmp, NODE)
        self.assertEqual((creds["jwt"], creds["coding"], creds["family"], creds["identity"]),
                         ("jwt-x", "coding-big", "bigmodel", "42"))
        plain["oauth:active_provider"] = "zai"
        plain["oauth:zai:user_info"] = json.dumps({"user_id": "z-9"})
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "credentials.json").write_text(json.dumps({k: "enc:v1:x" for k in plain}))
            with mock.patch("agent_meter.zcode_desktop.decrypt_entries", return_value=plain):
                creds = load_desktop_credentials(tmp, NODE)
        self.assertEqual((creds["coding"], creds["identity"]), ("coding-zai", "z-9"))

    def test_missing_jwt(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "credentials.json").write_text(json.dumps({"zcodejwttoken": "enc:v1:x"}))
            with mock.patch("agent_meter.zcode_desktop.decrypt_entries",
                            return_value={"zcodejwttoken": None}):
                with self.assertRaises(SourceError) as raised:
                    load_desktop_credentials(tmp, NODE)
            self.assertEqual(raised.exception.code, "zcode_desktop_credentials_unreadable")

    def test_node_missing(self):
        with self.assertRaises(SourceError) as raised:
            decrypt_entries(None, "secret", {})
        self.assertEqual(raised.exception.code, "zcode_desktop_node_missing")

    @unittest.skipUnless(NODE, "node not installed")
    def test_node_roundtrip(self):
        # Encrypt with the same envelope layout, then decrypt through the helper.
        script = """
const crypto=require('crypto');
const key=crypto.createHash('sha256').update('roundtrip-secret').digest();
const iv=crypto.randomBytes(12);
const c=crypto.createCipheriv('aes-256-gcm',key,iv);
const ct=Buffer.concat([c.update(Buffer.from('你好 token-abc','utf8')),c.final()]);
const enc='enc:v1:'+iv.toString('base64url')+'.'+c.getAuthTag().toString('base64url')+'.'+ct.toString('base64url');
process.stdout.write(JSON.stringify({entry:enc}));
"""
        made = json.loads(subprocess.run([NODE, "-e", script], stdout=subprocess.PIPE, check=True).stdout)
        out = decrypt_entries(NODE, "roundtrip-secret", made)
        self.assertEqual(out["entry"], "你好 token-abc")
        wrong = decrypt_entries(NODE, "wrong-secret", made)
        self.assertIsNone(wrong["entry"])


class CollectDesktopTests(unittest.TestCase):
    CREDS = {"jwt": "jwt-x", "coding": "coding-x", "family": "bigmodel", "identity": "42"}
    RESET = {"code": 0, "data": {"available_week_resets": [card(10)]}}
    QUOTA = {"code": 0, "data": {"limits": [
        {"type": "CREDIT_LIMIT", "usage": 100, "currentValue": 40, "unit": 3, "number": 5,
         "nextResetTime": int((NOW + 3600) * 1000)}], "level": "pro"}}

    def test_contract_and_cards(self):
        with mock.patch("agent_meter.zcode_desktop.load_desktop_credentials", return_value=self.CREDS), \
                mock.patch("agent_meter.zcode_desktop.get_json",
                           side_effect=[self.RESET, self.QUOTA]) as gj:
            out = collect_zcode_desktop("/unused", NODE, NOW)
        self.assertEqual((out["id"], out["scope"], out["status"]), ("zcode", "account", "available"))
        self.assertEqual(out["metrics"]["reset_cards"]["value"]["available_count"], 1)
        self.assertEqual(out["metrics"]["quota"]["status"], "available")
        self.assertTrue(out["account_key"])
        headers = gj.call_args_list[0].kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer jwt-x")
        self.assertEqual(headers["X-Bigmodel-Authorization"], "coding-x")
        self.assertEqual(headers["Bigmodel-Target-Type"], "PERSONAL")

    def test_quota_failure_keeps_cards(self):
        with mock.patch("agent_meter.zcode_desktop.load_desktop_credentials", return_value=self.CREDS), \
                mock.patch("agent_meter.zcode_desktop.get_json",
                           side_effect=[self.RESET, SourceError("not_authenticated")]):
            out = collect_zcode_desktop("/unused", NODE, NOW)
        self.assertEqual(out["metrics"]["reset_cards"]["status"], "available")
        self.assertEqual(out["metrics"]["quota"]["reason"], "zcode_desktop_quota_unavailable")

    def test_route_priority_and_fallback(self):
        config = {"zcode_v2_dir": "/unused", "node_binary": NODE}
        web = {"token": "console-token"}
        web_out = {"metrics": {"reset_cards": {"status": "not_connected"}}, "diagnostics": {}}
        desk_out = {"metrics": {"reset_cards": {"status": "available", "value": {"available_count": 3}}}}
        with mock.patch("agent_meter.collector.collect_zcode_desktop", return_value=desk_out), \
                mock.patch("agent_meter.collector.collect_zcode", return_value=web_out):
            out = collect_zcode_route(config, web, NOW, 15)
        self.assertEqual(out["metrics"]["reset_cards"]["value"]["available_count"], 3)
        self.assertEqual(out["diagnostics"]["cards_transport"], "zcode_desktop_login")
        with mock.patch("agent_meter.collector.collect_zcode_desktop", return_value=desk_out), \
                mock.patch("agent_meter.collector.collect_zcode", side_effect=SourceError("not_authenticated")):
            self.assertIs(collect_zcode_route(config, web, NOW, 15), desk_out)
        with mock.patch("agent_meter.collector.collect_zcode_desktop",
                        side_effect=SourceError("zcode_desktop_not_installed")):
            with self.assertRaises(SourceError) as raised:
                collect_zcode_route(config, None, NOW, 15)
            self.assertEqual(raised.exception.code, "zcode_credential_not_connected")


if __name__ == "__main__":
    unittest.main()