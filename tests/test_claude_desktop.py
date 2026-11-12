import base64
import json
import os
import plistlib
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_meter import claude_desktop
from agent_meter.claude_code import collect_claude_web
from agent_meter.model import SourceError, account_key

NOW = 1794211200.0
NODE = shutil.which("node")
HELPER = Path(claude_desktop.__file__).parent / "helpers/claude_auth.mjs"
PASSWORD = "synthetic-safe-storage-value"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Claude/5.1231.2 Chrome/156.0.8078.75 Electron/45.2.1 Safari/537.36")
BUNDLE = ("Claude", "5.1231.2", "45.2.1", "156.0.8078.75")
ORGS = [{"uuid": "11111111-api", "capabilities": ["api"]},
        {"uuid": "22222222-aaaa", "capabilities": ["chat", "claude_max"]}]
USAGE = {"five_hour": {"utilization": 37.0, "resets_at": "2026-11-09T05:00:00.123+00:00"},
         "seven_day": {"utilization": 12, "resets_at": "2026-11-13T00:00:00Z"},
         "seven_day_opus": None,
         "extra_usage": {"is_enabled": False}}
SESSION = {"cookie": "sessionKey=PRIVATE_SK; cf_clearance=PRIVATE_CF", "user_agent": UA}


def encrypt_cookie(value, host_key, password=PASSWORD, db_version=24):
    """Build a Chromium v10 blob the way the desktop app does (synthetic key)."""
    script = """
const crypto=require('crypto');
const [password,host,version,payload]=process.argv.slice(1);
const key=crypto.pbkdf2Sync(password,'saltysalt',1003,16,'sha1');
let plain=Buffer.from(payload,'utf8');
if(Number(version)>=24)plain=Buffer.concat([crypto.createHash('sha256').update(host).digest(),plain]);
const c=crypto.createCipheriv('aes-128-cbc',key,Buffer.alloc(16,0x20));
process.stdout.write(Buffer.concat([Buffer.from('v10'),c.update(plain),c.final()]).toString('base64'));
"""
    result = subprocess.run([NODE, "-e", script, password, host_key, str(db_version), value],
                            stdout=subprocess.PIPE, check=True, timeout=30)
    return base64.b64decode(result.stdout)


def make_bundle(root, name="Claude", version="5.1231.2", electron="45.2.1", chrome=b"156.0.8078.75"):
    app = Path(root) / "Claude.app"
    (app / "Contents").mkdir(parents=True)
    (app / "Contents/Info.plist").write_bytes(plistlib.dumps(
        {"CFBundleName": name, "CFBundleShortVersionString": version, "CFBundleExecutable": "Claude"}))
    framework = app / "Contents/Frameworks/Electron Framework.framework/Versions/A"
    (framework / "Resources").mkdir(parents=True)
    (framework / "Resources/Info.plist").write_bytes(plistlib.dumps({"CFBundleVersion": electron}))
    (framework / "Electron Framework").write_bytes(
        b"noise " + b"Chrome/" + chrome + b" middle " + b"Chrome/" + chrome + b" tail")
    return app


def make_cookies_db(home, rows, version=24):
    path = Path(home) / "Library/Application Support/Claude/Cookies"
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    if version is not None:
        db.execute("INSERT INTO meta VALUES ('version', ?)", (str(version),))
    db.execute("CREATE TABLE cookies (host_key TEXT, name TEXT, path TEXT, value TEXT, "
               "encrypted_value BLOB, expires_utc INTEGER)")
    for row in rows:
        db.execute("INSERT INTO cookies VALUES (?, ?, ?, ?, ?, ?)",
                   (row.get("host_key", ".claude.ai"), row["name"], row.get("path", "/"),
                    row.get("value"), row.get("encrypted_value"), row.get("expires_utc", 0)))
    db.commit()
    db.close()
    return path


def plain_row(name, value, **extra):
    return dict({"name": name, "value": value, "encrypted_value": b""}, **extra)


def run_helper(request):
    result = subprocess.run([NODE, str(HELPER)], input=json.dumps(request).encode(),
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30, check=False)
    return result.returncode, json.loads(result.stdout.decode())


def helper_request(cookies, password=PASSWORD, db_version=24, user_agent=UA):
    return {"password": password, "dbVersion": db_version, "userAgent": user_agent, "cookies": cookies}


def encrypted_row(name, value, host_key=".claude.ai", password=PASSWORD, db_version=24):
    blob = encrypt_cookie(value, host_key, password, db_version)
    return {"host_key": host_key, "name": name, "value": "",
            "encrypted_value": base64.b64encode(blob).decode()}


class AppBundleTests(unittest.TestCase):
    def setUp(self):
        claude_desktop._BUNDLE_CACHE.clear()

    def test_versions_and_user_agent(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_bundle(tmp)
            self.assertEqual(claude_desktop.app_bundle(app), BUNDLE)
        self.assertEqual(claude_desktop.user_agent(BUNDLE), UA)

    def test_framework_binary_is_cached_until_it_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_bundle(tmp)
            reads = []
            real_read = Path.read_bytes

            def counting_read(self):
                if self.name == "Electron Framework":
                    reads.append(self)
                return real_read(self)

            with mock.patch.object(Path, "read_bytes", counting_read):
                first = claude_desktop.app_bundle(app)
                second = claude_desktop.app_bundle(app)
            self.assertEqual(first, second)
            self.assertEqual(len(reads), 1)

    def test_most_common_chrome_version_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_bundle(tmp, chrome=b"1.2.3.4")
            binary = app / "Contents/Frameworks/Electron Framework.framework/Versions/A/Electron Framework"
            binary.write_bytes(binary.read_bytes() + b" Chrome/9.9.9.9 Chrome/9.9.9.9 Chrome/9.9.9.9")
            self.assertEqual(claude_desktop.app_bundle(app)[3], "9.9.9.9")

    def test_missing_or_broken_bundle_is_not_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            cases = []
            cases.append(Path(tmp) / "Absent.app")
            broken = make_bundle(Path(tmp) / "broken")
            (broken / "Contents/Info.plist").write_bytes(b"not a plist")
            cases.append(broken)
            nameless = make_bundle(Path(tmp) / "nameless")
            (nameless / "Contents/Info.plist").write_bytes(plistlib.dumps({"CFBundleShortVersionString": "1"}))
            cases.append(nameless)
            versionless = make_bundle(Path(tmp) / "versionless")
            (versionless / "Contents/Info.plist").write_bytes(plistlib.dumps({"CFBundleName": "Claude"}))
            cases.append(versionless)
            frameworkless = make_bundle(Path(tmp) / "frameworkless")
            binary = frameworkless / "Contents/Frameworks/Electron Framework.framework/Versions/A/Electron Framework"
            binary.unlink()
            cases.append(frameworkless)
            chromeless = make_bundle(Path(tmp) / "chromeless")
            binary = chromeless / "Contents/Frameworks/Electron Framework.framework/Versions/A/Electron Framework"
            binary.write_bytes(b"no version strings here")
            cases.append(chromeless)
            electronless = make_bundle(Path(tmp) / "electronless", electron="")
            cases.append(electronless)
            for app in cases:
                with self.assertRaises(SourceError) as ctx:
                    claude_desktop.app_bundle(app)
                self.assertEqual(ctx.exception.code, "claude_desktop_not_installed")


class KeychainTests(unittest.TestCase):
    def test_password_is_read_through_a_pipe(self):
        with mock.patch.object(subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, stdout=b"secret\n")
            self.assertEqual(claude_desktop.keychain_password(), "secret")
        command = run.call_args.args[0]
        self.assertEqual(command, ["/usr/bin/security", "find-generic-password", "-s",
                                   "Claude Safe Storage", "-a", "Claude Key", "-w"])
        self.assertEqual(run.call_args.kwargs["stderr"], subprocess.DEVNULL)
        self.assertEqual(run.call_args.kwargs["stdin"], subprocess.DEVNULL)
        self.assertFalse(run.call_args.kwargs.get("shell", False))

    def test_missing_item_falls_back_then_reports_no_login(self):
        with mock.patch.object(subprocess, "run") as run:
            run.side_effect = [subprocess.CompletedProcess([], 44), subprocess.CompletedProcess([], 44)]
            with self.assertRaises(SourceError) as ctx:
                claude_desktop.keychain_password()
        self.assertEqual(ctx.exception.code, "claude_desktop_not_logged_in")
        self.assertNotIn("-a", run.call_args_list[1].args[0])

    def test_account_fallback_can_still_succeed(self):
        with mock.patch.object(subprocess, "run") as run:
            run.side_effect = [subprocess.CompletedProcess([], 44),
                               subprocess.CompletedProcess([], 0, stdout=b"pw")]
            self.assertEqual(claude_desktop.keychain_password(), "pw")

    def test_denied_empty_and_transport_states(self):
        with mock.patch.object(subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess([], 128)
            with self.assertRaises(SourceError) as ctx:
                claude_desktop.keychain_password()
            self.assertEqual(ctx.exception.code, "claude_desktop_keychain_denied")
            run.side_effect = [subprocess.CompletedProcess([], 0, stdout=b"\n"),
                               subprocess.CompletedProcess([], 44)]
            with self.assertRaises(SourceError) as ctx:
                claude_desktop.keychain_password()
            self.assertEqual(ctx.exception.code, "claude_desktop_not_logged_in")
            run.side_effect = subprocess.TimeoutExpired("security", 1)
            with self.assertRaises(SourceError) as ctx:
                claude_desktop.keychain_password()
            self.assertEqual(ctx.exception.code, "claude_desktop_keychain_timeout")
            run.side_effect = OSError("no security binary")
            with self.assertRaises(SourceError) as ctx:
                claude_desktop.keychain_password()
            self.assertEqual(ctx.exception.code, "claude_desktop_keychain_unavailable")


class CookieRowTests(unittest.TestCase):
    def test_reads_version_and_claude_rows_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_cookies_db(tmp, [plain_row("sessionKey", "SK"),
                                  plain_row("device", "D", host_key="claude.ai"),
                                  plain_row("foreign", "X", host_key=".example.com")])
            version, rows = claude_desktop.cookie_rows(tmp)
        self.assertEqual(version, 24)
        self.assertEqual([r["name"] for r in rows], ["sessionKey", "device"])
        self.assertEqual(rows[0]["value"], "SK")
        self.assertEqual(rows[0]["encrypted_value"], b"")
        self.assertEqual(rows[0]["path"], "/")

    def test_null_columns_normalize(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_cookies_db(tmp, [{"name": "sessionKey", "value": None,
                                   "encrypted_value": None, "expires_utc": None, "path": None}])
            _, rows = claude_desktop.cookie_rows(tmp)
        self.assertEqual((rows[0]["value"], rows[0]["encrypted_value"], rows[0]["expires_utc"], rows[0]["path"]),
                         ("", b"", 0, "/"))

    def test_home_path_with_spaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home with space"
            make_cookies_db(home, [plain_row("sessionKey", "SK")])
            _, rows = claude_desktop.cookie_rows(home)
        self.assertEqual(rows[0]["value"], "SK")

    def test_missing_version_row_means_legacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_cookies_db(tmp, [plain_row("sessionKey", "SK")], version=None)
            version, _ = claude_desktop.cookie_rows(tmp)
        self.assertEqual(version, 0)

    def test_missing_and_unreadable_stores(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SourceError) as ctx:
                claude_desktop.cookie_rows(tmp)
            self.assertEqual(ctx.exception.code, "claude_desktop_cookies_missing")
            path = Path(tmp) / "Library/Application Support/Claude/Cookies"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"this is not a database")
            with self.assertRaises(SourceError) as ctx:
                claude_desktop.cookie_rows(tmp)
            self.assertEqual(ctx.exception.code, "claude_desktop_cookies_unreadable")
            path.unlink()
            db = sqlite3.connect(path)
            db.execute("CREATE TABLE meta (key TEXT, value TEXT)")
            db.commit()
            db.close()
            with self.assertRaises(SourceError) as ctx:
                claude_desktop.cookie_rows(tmp)
            self.assertEqual(ctx.exception.code, "claude_desktop_cookies_unreadable")


@unittest.skipUnless(NODE, "node is not available")
class HelperCryptoTests(unittest.TestCase):
    """The real helper decrypts blobs encrypted with a known synthetic key."""

    def test_v24_round_trip_with_full_jar(self):
        cookies = [encrypted_row("sessionKey", "sk-ant-sid02-SYNTHETIC"),
                   encrypted_row("cf_clearance", "CF-SYNTHETIC"),
                   {"host_key": "claude.ai", "name": "anthropic-device-id", "value": "DEVICE",
                    "encrypted_value": ""}]
        code, reply = run_helper(helper_request(cookies))
        self.assertEqual(code, 0)
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(reply["user_agent"], UA)
        self.assertEqual([c["value"] for c in reply["cookies"]],
                         ["sk-ant-sid02-SYNTHETIC", "CF-SYNTHETIC", "DEVICE"])
        self.assertEqual([c["name"] for c in reply["cookies"]],
                         ["sessionKey", "cf_clearance", "anthropic-device-id"])

    def test_legacy_db_without_host_prefix(self):
        cookies = [encrypted_row("sessionKey", "LEGACY", db_version=23)]
        code, reply = run_helper(helper_request(cookies, db_version=23))
        self.assertEqual(code, 0)
        self.assertEqual(reply["cookies"][0]["value"], "LEGACY")

    def test_unicode_value_round_trip(self):
        cookies = [encrypted_row("pref", "värde-中文")]
        _, reply = run_helper(helper_request(cookies))
        self.assertEqual(reply["cookies"][0]["value"], "värde-中文")

    def test_wrong_password_is_rejected(self):
        cookies = [encrypted_row("sessionKey", "SK")]
        code, reply = run_helper(helper_request(cookies, password="wrong-password"))
        self.assertEqual(code, 1)
        self.assertEqual(reply, {"ok": False, "reason": "decrypt_failed"})

    def test_host_prefix_mismatch_is_rejected(self):
        cookies = [encrypted_row("sessionKey", "SK", host_key=".claude.ai")]
        cookies[0]["host_key"] = "claude.ai"
        _, reply = run_helper(helper_request(cookies))
        self.assertEqual(reply, {"ok": False, "reason": "decrypt_failed"})

    def test_non_v10_envelope_is_unsupported(self):
        blob = base64.b64encode(b"v11" + b"x" * 32).decode()
        cookies = [{"host_key": ".claude.ai", "name": "sessionKey", "value": "", "encrypted_value": blob}]
        _, reply = run_helper(helper_request(cookies))
        self.assertEqual(reply, {"ok": False, "reason": "unsupported_format"})

    def test_corrupted_ciphertext_is_rejected(self):
        blob = bytearray(encrypt_cookie("SK", ".claude.ai"))
        blob[-1] ^= 0xFF
        cookies = [{"host_key": ".claude.ai", "name": "sessionKey", "value": "",
                    "encrypted_value": base64.b64encode(bytes(blob)).decode()}]
        _, reply = run_helper(helper_request(cookies))
        self.assertEqual(reply, {"ok": False, "reason": "decrypt_failed"})

    def test_empty_jar_is_valid(self):
        code, reply = run_helper(helper_request([]))
        self.assertEqual(code, 0)
        self.assertEqual(reply["cookies"], [])

    def test_malformed_requests(self):
        good = helper_request([encrypted_row("sessionKey", "SK")])
        bad_requests = [
            dict(good, password=""),
            {k: v for k, v in good.items() if k != "password"},
            {k: v for k, v in good.items() if k != "userAgent"},
            dict(good, userAgent=""),
            dict(good, dbVersion="24"),
            dict(good, dbVersion=-1),
            dict(good, cookies={}),
            helper_request([{"name": "sessionKey", "value": "x", "encrypted_value": ""}]),
            helper_request([{"host_key": ".claude.ai", "value": "x", "encrypted_value": ""}]),
            helper_request([{"host_key": ".claude.ai", "name": "sessionKey"}]),
        ]
        for request in bad_requests:
            code, reply = run_helper(request)
            self.assertEqual(code, 1, request)
            self.assertEqual(reply, {"ok": False, "reason": "invalid_format"}, request)

    def test_garbage_and_oversized_stdin(self):
        for payload in [b"not json", b"a" * (1024 * 1024 + 1)]:
            result = subprocess.run([NODE, str(HELPER)], input=payload, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, timeout=30, check=False)
            self.assertEqual(json.loads(result.stdout), {"ok": False, "reason": "invalid_format"})


class DecryptSessionTests(unittest.TestCase):
    ROWS = [{"host_key": ".claude.ai", "name": "sessionKey", "path": "/", "value": "",
             "encrypted_value": b"v10-session", "expires_utc": 0},
            {"host_key": ".claude.ai", "name": "cf_clearance", "path": "/", "value": "",
             "encrypted_value": b"v10-cf", "expires_utc": 0},
            {"host_key": "claude.ai", "name": "lastActiveOrg", "path": "/settings", "value": "ORG",
             "encrypted_value": b"", "expires_utc": 0}]

    def reply(self, values=("SK", "CF", "ORG"), ua=UA):
        cookies = [{"name": row["name"], "value": value} for row, value in zip(self.ROWS, values)]
        return {"ok": True, "user_agent": ua, "cookies": cookies}

    def call(self, reply=None, rows=None, node="node", **kwargs):
        stdout = json.dumps(reply if reply is not None else self.reply()).encode()
        with mock.patch.object(subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, stdout=stdout)
            session = claude_desktop.decrypt_session(node, PASSWORD, rows or self.ROWS, 24, UA, **kwargs)
        return session, run

    def test_jar_assembly_and_request_shape(self):
        with mock.patch.dict(os.environ, {"NODE_OPTIONS": "--require evil", "ELECTRON_RUN_AS_NODE": "0",
                                          "KEEP_ME": "1"}):
            session, run = self.call()
        self.assertEqual(session["cookie"], "lastActiveOrg=ORG; sessionKey=SK; cf_clearance=CF")
        self.assertEqual(session["user_agent"], UA)
        command = run.call_args.args[0]
        self.assertEqual(command, ["node", str(HELPER)])
        kwargs = run.call_args.kwargs
        request = json.loads(kwargs["input"])
        self.assertEqual(request["password"], PASSWORD)
        self.assertEqual(request["dbVersion"], 24)
        self.assertEqual(request["userAgent"], UA)
        self.assertEqual(request["cookies"][0]["encrypted_value"], base64.b64encode(b"v10-session").decode())
        self.assertEqual(request["cookies"][2]["value"], "ORG")
        self.assertNotIn("NODE_OPTIONS", kwargs["env"])
        self.assertEqual(kwargs["env"]["ELECTRON_RUN_AS_NODE"], "1")
        self.assertEqual(kwargs["env"]["KEEP_ME"], "1")
        self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)

    def test_missing_session_key_means_no_login(self):
        rows = [dict(r, name="other_" + r["name"]) for r in self.ROWS]
        cookies = [{"name": r["name"], "value": "x"} for r in rows]
        with self.assertRaises(SourceError) as ctx:
            self.call(reply={"ok": True, "user_agent": UA, "cookies": cookies}, rows=rows)
        self.assertEqual(ctx.exception.code, "claude_desktop_not_logged_in")

    def test_helper_reasons_map_to_error_codes(self):
        for reason, expected in [("decrypt_failed", "claude_desktop_decrypt_failed"),
                                 ("unsupported_format", "claude_desktop_cookies_unsupported"),
                                 ("invalid_format", "claude_desktop_helper_failed"),
                                 ("helper_protocol", "claude_desktop_helper_failed"),
                                 ("mystery", "claude_desktop_helper_failed")]:
            with self.assertRaises(SourceError) as ctx:
                self.call(reply={"ok": False, "reason": reason})
            self.assertEqual(ctx.exception.code, expected, reason)

    def test_malformed_replies_are_rejected(self):
        bad = [{"ok": True, "user_agent": UA, "cookies": []},
               {"ok": True, "cookies": self.reply()["cookies"]},
               {"ok": True, "user_agent": "", "cookies": self.reply()["cookies"]},
               {"ok": True, "user_agent": UA,
                "cookies": [{"name": "wrong", "value": "x"}] + self.reply()["cookies"][1:]},
               {"ok": True, "user_agent": UA,
                "cookies": [{"name": "sessionKey", "value": 5}] + self.reply()["cookies"][1:]},
               {"ok": True, "user_agent": UA, "cookies": ["x"] * 3},
               ["not", "a", "dict"]]
        for reply in bad:
            with self.assertRaises(SourceError) as ctx:
                self.call(reply=reply)
            self.assertEqual(ctx.exception.code, "claude_desktop_helper_failed", reply)
        with mock.patch.object(subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, stdout=b"not json")
            with self.assertRaises(SourceError) as ctx:
                claude_desktop.decrypt_session("node", PASSWORD, self.ROWS, 24, UA)
        self.assertEqual(ctx.exception.code, "claude_desktop_helper_failed")
        with mock.patch.object(subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, stdout=b"x" * (8 * 1024 * 1024 + 1))
            with self.assertRaises(SourceError) as ctx:
                claude_desktop.decrypt_session("node", PASSWORD, self.ROWS, 24, UA)
        self.assertEqual(ctx.exception.code, "claude_desktop_helper_failed")

    def test_runtime_failures(self):
        with mock.patch.object(subprocess, "run") as run:
            run.side_effect = subprocess.TimeoutExpired("node", 1)
            with self.assertRaises(SourceError) as ctx:
                claude_desktop.decrypt_session("node", PASSWORD, self.ROWS, 24, UA)
            self.assertEqual(ctx.exception.code, "claude_desktop_helper_timeout")
            run.side_effect = OSError("missing")
            with self.assertRaises(SourceError) as ctx:
                claude_desktop.decrypt_session("node", PASSWORD, self.ROWS, 24, UA)
            self.assertEqual(ctx.exception.code, "claude_desktop_node_missing")
        with mock.patch.object(subprocess, "run") as run:
            with self.assertRaises(SourceError) as ctx:
                claude_desktop.decrypt_session(None, PASSWORD, self.ROWS, 24, UA)
            self.assertEqual(ctx.exception.code, "claude_desktop_node_missing")
            run.assert_not_called()


class CollectTests(unittest.TestCase):
    """Wiring: credential chain order, contract parity with the web route."""

    def setUp(self):
        self.rows = [{"host_key": ".claude.ai", "name": "sessionKey", "path": "/", "value": "",
                      "encrypted_value": b"v10", "expires_utc": 0},
                     {"host_key": ".claude.ai", "name": "cf_clearance", "path": "/", "value": "",
                      "encrypted_value": b"v10", "expires_utc": 0}]

    def collect(self, rows=None, get_json=None, timeout=20):
        with mock.patch.object(claude_desktop, "app_bundle", return_value=BUNDLE), \
             mock.patch.object(claude_desktop, "cookie_rows", return_value=(24, rows if rows is not None else self.rows)) as cookie_rows, \
             mock.patch.object(claude_desktop, "keychain_password", return_value=PASSWORD) as keychain, \
             mock.patch.object(claude_desktop, "decrypt_session", return_value=SESSION) as decrypt, \
             mock.patch("agent_meter.claude_code.get_json", side_effect=get_json or [ORGS, USAGE]) as get:
            out = claude_desktop.collect_claude_desktop("/home", NOW, timeout, "node")
        return out, {"cookie_rows": cookie_rows, "keychain": keychain, "decrypt": decrypt, "get": get}

    def test_happy_path_contract_and_headers(self):
        out, calls = self.collect()
        self.assertEqual(out["id"], "claude")
        self.assertEqual(out["diagnostics"]["credential_route"], "desktop_session")
        self.assertEqual(out["diagnostics"]["transport"], "claude_ai_web_session")
        self.assertEqual(out["account_key"], account_key("claude", "22222222-aaaa"))
        quota = out["metrics"]["quota"]["value"]
        self.assertEqual([q["bucket"] for q in quota], ["five_hour", "seven_day"])
        self.assertEqual(quota[0]["remaining_percent"], 63.0)
        self.assertEqual(calls["get"].call_args_list[0].args[0], "https://claude.ai/api/organizations")
        self.assertEqual(calls["get"].call_args_list[1].args[0],
                         "https://claude.ai/api/organizations/22222222-aaaa/usage")
        headers = calls["get"].call_args.kwargs["headers"]
        self.assertEqual(headers["Cookie"], SESSION["cookie"])
        self.assertEqual(headers["User-Agent"], UA)
        self.assertEqual(headers["Referer"], "https://claude.ai/settings/usage")
        calls["keychain"].assert_called_once_with(timeout=30)
        self.assertNotIn("PRIVATE", json.dumps(out))
        self.assertNotIn("22222222-aaaa", json.dumps(out))

    def test_output_matches_the_web_route_contract(self):
        with mock.patch("agent_meter.claude_code.get_json", side_effect=[ORGS, USAGE]):
            web = collect_claude_web(SESSION, NOW)
        desktop, _ = self.collect()
        route = desktop["diagnostics"].pop("credential_route")
        self.assertEqual(route, "desktop_session")
        self.assertEqual(desktop, web)

    def test_short_timeout_still_allows_the_keychain_prompt(self):
        _, calls = self.collect(timeout=5)
        calls["keychain"].assert_called_once_with(timeout=30)
        self.assertEqual(calls["get"].call_args.kwargs["timeout"], 5)

    def test_expired_cookies_are_dropped_before_decryption(self):
        expired = dict(self.rows[1], expires_utc=int((NOW - 10 + claude_desktop.CHROMIUM_EPOCH) * 1_000_000))
        _, calls = self.collect(rows=[self.rows[0], expired])
        sent = calls["decrypt"].call_args.args[2]
        self.assertEqual([r["name"] for r in sent], ["sessionKey"])

    def test_no_session_key_fails_before_the_keychain_prompt(self):
        for rows in [[dict(self.rows[0], name="cf_clearance")], []]:
            with mock.patch.object(claude_desktop, "app_bundle", return_value=BUNDLE), \
                 mock.patch.object(claude_desktop, "cookie_rows", return_value=(24, rows)), \
                 mock.patch.object(claude_desktop, "keychain_password") as keychain, \
                 mock.patch("agent_meter.claude_code.get_json") as get:
                with self.assertRaises(SourceError) as ctx:
                    claude_desktop.collect_claude_desktop("/home", NOW, 20, "node")
            self.assertEqual(ctx.exception.code, "claude_desktop_not_logged_in")
            keychain.assert_not_called()
            get.assert_not_called()

    def test_all_cookies_expired_means_no_login(self):
        expired = [dict(r, expires_utc=int((NOW - 10 + claude_desktop.CHROMIUM_EPOCH) * 1_000_000))
                   for r in self.rows]
        with mock.patch.object(claude_desktop, "app_bundle", return_value=BUNDLE), \
             mock.patch.object(claude_desktop, "cookie_rows", return_value=(24, expired)), \
             mock.patch.object(claude_desktop, "keychain_password") as keychain:
            with self.assertRaises(SourceError) as ctx:
                claude_desktop.collect_claude_desktop("/home", NOW, 20, "node")
        self.assertEqual(ctx.exception.code, "claude_desktop_not_logged_in")
        keychain.assert_not_called()

    def test_credential_errors_stop_the_chain(self):
        for stage, code in [("app_bundle", "claude_desktop_not_installed"),
                            ("cookie_rows", "claude_desktop_cookies_missing"),
                            ("keychain_password", "claude_desktop_keychain_denied"),
                            ("decrypt_session", "claude_desktop_node_missing")]:
            with mock.patch.object(claude_desktop, "app_bundle", return_value=BUNDLE), \
                 mock.patch.object(claude_desktop, "cookie_rows", return_value=(24, self.rows)), \
                 mock.patch.object(claude_desktop, "keychain_password", return_value=PASSWORD), \
                 mock.patch.object(claude_desktop, "decrypt_session", return_value=SESSION), \
                 mock.patch("agent_meter.claude_code.get_json") as get:
                with mock.patch.object(claude_desktop, stage, side_effect=SourceError(code)):
                    with self.assertRaises(SourceError) as ctx:
                        claude_desktop.collect_claude_desktop("/home", NOW, 20, "node")
            self.assertEqual(ctx.exception.code, code)
            get.assert_not_called()

    def test_api_auth_failure_means_the_desktop_session_expired(self):
        with self.assertRaises(SourceError) as ctx:
            self.collect(get_json=SourceError("not_authenticated"))
        self.assertEqual(ctx.exception.code, "claude_desktop_session_expired")

    def test_other_transport_errors_pass_through(self):
        for code in ["connection_failed", "http_500", "invalid_json", "claude_web_no_organization"]:
            with self.assertRaises(SourceError) as ctx:
                self.collect(get_json=SourceError(code))
            self.assertEqual(ctx.exception.code, code)


class CollectFixtureTests(unittest.TestCase):
    """End-to-end with a synthetic cookie DB; no keychain, network or app."""

    def setUp(self):
        claude_desktop._BUNDLE_CACHE.clear()

    def test_plaintext_jar_through_a_mocked_helper(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            make_cookies_db(home, [plain_row("sessionKey", "PRIVATE_SK"),
                                   plain_row("cf_clearance", "PRIVATE_CF"),
                                   plain_row("anthropic-device-id", "PRIVATE_DEVICE", host_key="claude.ai")])
            app = make_bundle(tmp)
            captured = {}

            def fake_run(command, **kwargs):
                if command[0] == "/usr/bin/security":
                    return subprocess.CompletedProcess(command, 0, stdout=PASSWORD.encode() + b"\n")
                request = json.loads(kwargs["input"])
                captured["request"] = request
                cookies = [{"name": r["name"], "value": r["value"]} for r in request["cookies"]]
                reply = {"ok": True, "user_agent": request["userAgent"], "cookies": cookies}
                return subprocess.CompletedProcess(command, 0, stdout=json.dumps(reply).encode())

            with mock.patch.object(claude_desktop, "APP_PATH", app), \
                 mock.patch.object(subprocess, "run", side_effect=fake_run), \
                 mock.patch("agent_meter.claude_code.get_json", side_effect=[ORGS, USAGE]) as get:
                out = claude_desktop.collect_claude_desktop(home, NOW, 20, "node")
            self.assertEqual(captured["request"]["password"], PASSWORD)
            self.assertEqual(captured["request"]["userAgent"], UA)
            headers = get.call_args.kwargs["headers"]
            self.assertEqual(headers["Cookie"],
                             "sessionKey=PRIVATE_SK; cf_clearance=PRIVATE_CF; anthropic-device-id=PRIVATE_DEVICE")
            self.assertEqual(headers["User-Agent"], UA)
            self.assertEqual(out["diagnostics"]["credential_route"], "desktop_session")
            self.assertNotIn("PRIVATE", json.dumps(out))

    @unittest.skipUnless(NODE, "node is not available")
    def test_encrypted_jar_through_the_real_helper(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            make_cookies_db(home, [
                {"name": "sessionKey", "value": "",
                 "encrypted_value": encrypt_cookie("PRIVATE_SK", ".claude.ai")},
                {"name": "cf_clearance", "value": "",
                 "encrypted_value": encrypt_cookie("PRIVATE_CF", ".claude.ai")},
                {"name": "__cf_bm", "value": "",
                 "encrypted_value": encrypt_cookie("PRIVATE_BM", ".claude.ai")},
                plain_row("anthropic-device-id", "PRIVATE_DEVICE", host_key="claude.ai"),
                plain_row("lastActiveOrg", "22222222-aaaa")])
            app = make_bundle(tmp)
            before = {p for p in Path(tmp).rglob("*") if p.is_file()}
            with mock.patch.object(claude_desktop, "APP_PATH", app), \
                 mock.patch.object(claude_desktop, "keychain_password", return_value=PASSWORD) as keychain, \
                 mock.patch("agent_meter.claude_code.get_json", side_effect=[ORGS, USAGE]) as get:
                out = claude_desktop.collect_claude_desktop(home, NOW, 20, NODE)
            after = {p for p in Path(tmp).rglob("*") if p.is_file()}
            self.assertEqual(before, after)
            keychain.assert_called_once_with(timeout=30)
            headers = get.call_args.kwargs["headers"]
            for pair in ["sessionKey=PRIVATE_SK", "cf_clearance=PRIVATE_CF", "__cf_bm=PRIVATE_BM",
                         "anthropic-device-id=PRIVATE_DEVICE", "lastActiveOrg=22222222-aaaa"]:
                self.assertIn(pair, headers["Cookie"])
            self.assertEqual(headers["User-Agent"], UA)
            self.assertEqual(out["metrics"]["quota"]["value"][0]["used_percent"], 37.0)
            self.assertEqual(out["diagnostics"]["credential_route"], "desktop_session")
            self.assertNotIn("PRIVATE", json.dumps(out))

    @unittest.skipUnless(NODE, "node is not available")
    def test_wrong_keychain_value_fails_decryption(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            make_cookies_db(home, [{"name": "sessionKey", "value": "",
                                    "encrypted_value": encrypt_cookie("PRIVATE_SK", ".claude.ai")}])
            app = make_bundle(tmp)
            with mock.patch.object(claude_desktop, "APP_PATH", app), \
                 mock.patch.object(claude_desktop, "keychain_password", return_value="wrong"), \
                 mock.patch("agent_meter.claude_code.get_json") as get:
                with self.assertRaises(SourceError) as ctx:
                    claude_desktop.collect_claude_desktop(home, NOW, 20, NODE)
            self.assertEqual(ctx.exception.code, "claude_desktop_decrypt_failed")
            get.assert_not_called()


if __name__ == "__main__":
    unittest.main()