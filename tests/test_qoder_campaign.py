import json
import os
import plistlib
import subprocess
import urllib.error
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_meter import qoder_campaign
from agent_meter.model import SourceError
from agent_meter.qoder_campaign import (CAMPAIGN_BASE, CAMPAIGNS_PATH, CLAIM_PATH, normalize_campaign_claim,
                                        normalize_campaigns)

NOW = 1794211200  # 2026-11-09 16:00 Asia/Shanghai

# Shape of the 2026-11-10 read-only probe (openapi.qoder.com.cn), values synthetic.
CAMPAIGNS_OPEN = {"campaigns": [
    {"campaignId": "act-20261013-146", "campaignKey": "daily_100_credits", "actionType": "CLAIM_BENEFIT",
     "claimStatus": "CLAIMABLE", "startAt": NOW - 86400, "endAt": NOW + 86400,
     "benefit": {"amount": 100, "validity": {"mode": "RELATIVE_DAYS", "days": 30}}}]}
CAMPAIGNS_CLAIMED = {"campaigns": [dict(CAMPAIGNS_OPEN["campaigns"][0], claimStatus="CLAIMED")]}


class NormalizeTests(unittest.TestCase):
    def test_claimable_campaign(self):
        status = normalize_campaigns(CAMPAIGNS_OPEN, NOW)
        self.assertEqual(status["kind"], "campaign")
        self.assertEqual(len(status["claimable"]), 1)
        item = status["claimable"][0]
        self.assertEqual(item["item"], "campaign:act-20261013-146")
        self.assertEqual(item["credits"], 100)
        self.assertEqual(status["campaigns"][0]["active"], True)

    def test_claimed_campaign_is_not_claimable(self):
        status = normalize_campaigns(CAMPAIGNS_CLAIMED, NOW)
        self.assertEqual(status["claimable"], [])
        self.assertEqual(status["campaigns"][0]["status"], "CLAIMED")

    def test_campaign_outside_its_window_is_not_claimable(self):
        row = dict(CAMPAIGNS_OPEN["campaigns"][0], endAt=NOW - 10)
        status = normalize_campaigns({"campaigns": [row]}, NOW)
        self.assertEqual(status["claimable"], [])
        self.assertEqual(status["campaigns"][0]["active"], False)

    def test_campaign_that_has_not_started_is_not_claimable(self):
        row = dict(CAMPAIGNS_OPEN["campaigns"][0], startAt=NOW + 10)
        status = normalize_campaigns({"campaigns": [row]}, NOW)
        self.assertEqual(status["claimable"], [])

    def test_other_action_types_are_ignored(self):
        rows = [dict(CAMPAIGNS_OPEN["campaigns"][0], actionType="LINK_CLICK")]
        self.assertEqual(normalize_campaigns({"campaigns": rows}, NOW)["campaigns"], [])

    def test_daily_refresh_moment_is_reported(self):
        status = normalize_campaigns(CAMPAIGNS_OPEN, NOW)
        self.assertEqual(status["daily_refresh"], "16:00")

    def test_empty_campaign_list_is_valid(self):
        status = normalize_campaigns({"campaigns": []}, NOW)
        self.assertEqual((status["campaigns"], status["claimable"]), ([], []))

    def test_broken_contract_is_rejected(self):
        for payload in [None, [], {"campaigns": "no"}, {"data": {}}]:
            with self.assertRaises(SourceError):
                normalize_campaigns(payload, NOW)

    def test_claim_result_shapes(self):
        # The live body is flat: status, replayed and benefit sit at the top.
        ok = normalize_campaign_claim({"status": "CLAIMED", "benefit": {"amount": 100}})
        self.assertEqual((ok["result"], ok["credits"]), ("ok", 100))
        replayed = normalize_campaign_claim({"status": "CLAIMED", "replayed": True,
                                             "benefit": {"amount": 100}})
        self.assertTrue(replayed["replayed"])
        self.assertEqual(replayed["result"], "ok")
        self.assertEqual(replayed["credits"], 100)
        rejected = normalize_campaign_claim({"status": "NOT_ELIGIBLE"})
        self.assertEqual(rejected["result"], "rejected")
        self.assertEqual(rejected["status"], "NOT_ELIGIBLE")

    def test_claim_needs_the_http_status(self):
        # A body that says CLAIMED but an HTTP error is not a success.
        result = normalize_campaign_claim({"status": "CLAIMED", "benefit": {"amount": 100}}, http_status=500)
        self.assertEqual(result["result"], "rejected")

    def test_claim_credits_fall_back_to_the_campaign_row(self):
        result = normalize_campaign_claim({"status": "CLAIMED"},
                                           fallback={"benefit": {"amount": 100}})
        self.assertEqual(result["credits"], 100)


class RequestTests(unittest.TestCase):
    """The request shape: paths, headers and body of the real endpoints.

    Every case carries its own auth directory: the desktop lookup must not
    depend on this machine having Qoder CN installed, or the suite would
    only pass on the maintainer's computer.
    """

    def setUp(self):
        self.captured = {}

    def fake_api(self, payload, status=200):
        def call(path, token, headers, timeout, method="GET"):
            self.captured.update({"path": path, "token": token, "headers": headers,
                                   "timeout": timeout, "method": method})
            return status, payload
        return call

    def patch(self, payload, status=200):
        return mock.patch.object(qoder_campaign, "_api", self.fake_api(payload, status))

    def test_status_uses_the_campaign_list_endpoint(self):
        session = {"desktop_app": "/Applications/Qoder CN.app", "auth_dir": "/tmp/qoder-auth"}
        with mock.patch.object(qoder_campaign, "desktop_token", lambda s, t=15: "TOK"), \
             self.patch(CAMPAIGNS_OPEN):
            # The fixture's window is anchored to NOW; pass it in so the
            # assertion does not rot when the wall clock leaves that window.
            status = qoder_campaign.qoder_campaigns_status(session, 15, NOW)
        self.assertEqual(self.captured["path"], CAMPAIGNS_PATH)
        self.assertEqual(self.captured["token"], "TOK")
        self.assertEqual(self.captured["method"], "GET")
        self.assertEqual(self.captured["headers"]["Cosy-ClientType"], "10")
        self.assertEqual(len(status["claimable"]), 1)

    def test_api_sends_the_bearer_token(self):
        captured = {}

        class FakeResponse:
            status = 200

            def read(self, limit):
                return json.dumps({"campaigns": []}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        class FakeOpener:
            def open(self, request, timeout=None):
                captured["headers"] = dict(request.headers)
                captured["method"] = request.get_method()
                captured["url"] = request.full_url
                return FakeResponse()

        with mock.patch.object(qoder_campaign, "build_opener", lambda url, local=False: FakeOpener()):
            status, payload = qoder_campaign._api(CAMPAIGNS_PATH, "TOK", {"Cosy-ClientType": "10"}, 15)
        self.assertEqual(status, 200)
        self.assertEqual(payload["campaigns"], [])
        self.assertEqual(captured["url"], CAMPAIGN_BASE + CAMPAIGNS_PATH)
        self.assertEqual(captured["method"], "GET")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer TOK")
        self.assertEqual(captured["headers"]["Cosy-clienttype"], "10")

    def test_api_maps_http_errors(self):
        class FakeOpener:
            def open(self, request, timeout=None):
                raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", None, None)

        with mock.patch.object(qoder_campaign, "build_opener", lambda url, local=False: FakeOpener()):
            with self.assertRaises(SourceError) as ctx:
                qoder_campaign._api(CAMPAIGNS_PATH, "TOK", {}, 15)
        self.assertEqual(ctx.exception.code, "qoder_campaigns_unauthorized")

    def test_claim_posts_to_the_campaign_endpoint(self):
        session = {"desktop_app": "/Applications/Qoder CN.app", "auth_dir": "/tmp/qoder-auth"}
        with mock.patch.object(qoder_campaign, "desktop_token", lambda s, t=15: "TOK"), \
             self.patch({"status": "CLAIMED", "benefit": {"amount": 100}}):
            result = qoder_campaign.qoder_campaigns_claim(session, "campaign:act-1", 15)
        self.assertEqual(self.captured["path"], CLAIM_PATH % "act-1")
        self.assertEqual(self.captured["method"], "POST")
        self.assertEqual(result["result"], "ok")

    def test_claim_rejects_foreign_items(self):
        session = {"desktop_app": "/Applications/Qoder CN.app", "auth_dir": "/tmp/qoder-auth"}
        for item in ["daily_checkin", "campaign:", "campaign:../other", ""]:
            with self.assertRaises(SourceError):
                qoder_campaign.qoder_campaigns_claim(session, item, 15)


class DesktopCredentialTests(unittest.TestCase):
    def test_auth_dirs_need_the_credential_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            support = home / "Library" / "Application Support"
            support.mkdir(parents=True)
            (support / "com.qodercn.app.stable").mkdir()
            self.assertEqual(qoder_campaign.auth_dirs(home), [])
            (support / "com.qodercn.app.stable" / "auth.v1.dat").write_bytes(b"v10")
            found = qoder_campaign.auth_dirs(home)
            self.assertEqual([p.name for p in found], ["com.qodercn.app.stable"])

    def test_keychain_password_is_read_through_a_pipe(self):
        with mock.patch.object(subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, stdout=b"secret\n")
            self.assertEqual(qoder_campaign.keychain_password(), "secret")
        command = run.call_args[0][0]
        self.assertEqual(command[:3], ["/usr/bin/security", "find-generic-password", "-s"])
        self.assertIn(qoder_campaign.KEYCHAIN_SERVICE, command)

    def test_missing_keychain_item_means_no_desktop_login(self):
        with mock.patch.object(subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess([], 44, stdout=b"")
            with self.assertRaises(SourceError) as ctx:
                qoder_campaign.keychain_password()
        self.assertEqual(ctx.exception.code, "qoder_desktop_not_logged_in")

    def test_token_is_cached_in_memory_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            session = {"desktop_app": "/Applications/Qoder CN.app", "auth_dir": str(directory)}
            with mock.patch.object(qoder_campaign, "decrypt_token", return_value="TOK") as decrypt, \
                 mock.patch.object(qoder_campaign, "keychain_password", return_value="pw"):
                self.assertEqual(qoder_campaign.desktop_token(session), "TOK")
                self.assertEqual(qoder_campaign.desktop_token(session), "TOK")
            self.assertEqual(decrypt.call_count, 1)

    def test_helper_reason_maps_to_an_error_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "Qoder CN.app"
            (app / "Contents/MacOS").mkdir(parents=True)
            (app / "Contents/MacOS/Qoder CN").write_text("#!/bin/sh\n")
            (app / "Contents/Info.plist").write_bytes(plistlib.dumps({"CFBundleExecutable": "Qoder CN"}))
            directory = Path(tmp)
            with mock.patch.object(subprocess, "run") as run:
                run.return_value = subprocess.CompletedProcess([], 1, stdout=b'{"ok":false,"reason":"decrypt_failed"}')
                with self.assertRaises(SourceError) as ctx:
                    qoder_campaign.decrypt_token(app, directory, "pw")
        self.assertEqual(ctx.exception.code, "qoder_desktop_auth_failed")

    def test_helper_round_trip_decrypts_a_real_envelope(self):
        """Encrypt a token the way the desktop app does, then read it back."""
        node = shutil_which()
        if not node:
            self.skipTest("node is not available")
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            payload = json.dumps({"token": "TOKEN-VALUE", "expiresAt": "2026-11-10T00:00:00Z"})
            (directory / "auth.v1.dat").write_bytes(encrypt_v10(payload, node))
            script = Path(qoder_campaign.__file__).parent / "helpers/qoder_auth.mjs"
            request = json.dumps({"password": "pw", "authFile": str(directory / "auth.v1.dat")}).encode()
            result = subprocess.run([node, str(script)], input=request, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, timeout=30, check=False)
            reply = json.loads(result.stdout.decode("utf-8"))
            self.assertTrue(reply["ok"], reply)
            self.assertEqual(reply["session"]["token"], "TOKEN-VALUE")

    def test_helper_refuses_a_wrong_password(self):
        node = shutil_which()
        if not node:
            self.skipTest("node is not available")
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            payload = json.dumps({"token": "TOKEN-VALUE"})
            (directory / "auth.v1.dat").write_bytes(encrypt_v10(payload, node))
            script = Path(qoder_campaign.__file__).parent / "helpers/qoder_auth.mjs"
            request = json.dumps({"password": "wrong", "authFile": str(directory / "auth.v1.dat")}).encode()
            result = subprocess.run([node, str(script)], input=request, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, timeout=30, check=False)
            reply = json.loads(result.stdout.decode("utf-8"))
            self.assertFalse(reply["ok"])
            self.assertEqual(reply["reason"], "decrypt_failed")


def shutil_which():
    import shutil
    return shutil.which("node")


def encrypt_v10(payload, node):
    """Build a Chromium "v10" envelope: AES-128-CBC under the saltysalt key."""
    script = """
const crypto=require('crypto');
const key=crypto.pbkdf2Sync('pw','saltysalt',1003,16,'sha1');
const c=crypto.createCipheriv('aes-128-cbc',key,Buffer.alloc(16,0x20));
const out=Buffer.concat([c.update(Buffer.from(process.argv[1],'utf8')),c.final()]);
process.stdout.write(Buffer.concat([Buffer.from('v10'),out]).toString('base64'));
"""
    result = subprocess.run([node, "-e", script, payload], stdout=subprocess.PIPE, check=True)
    import base64
    return base64.b64decode(result.stdout)


if __name__ == "__main__":
    unittest.main()
