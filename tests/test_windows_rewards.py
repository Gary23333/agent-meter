"""Windows 每日积分适配层测试：只用合成响应，不访问真实账户。"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_meter.model import SourceError
from agent_meter.rewards import STATUS_EVERY
from windows import rewards as windows_rewards

NOW = 1794211200  # 2026-11-09 16:00 Asia/Shanghai
DAY = 86400
TOKEN = "synthetic-trae-token-0001"
COOKIE = "session=synthetic-value"
UA = "Synthetic/1.0"


def trae_session():
    return {"token": TOKEN, "user_agent": UA, "device_id": None}


def workbuddy_session():
    return {"cookie": COOKIE, "user_agent": UA}


def trae_open():
    return {"kind": "daily_checkin", "enabled": True, "signed_in": False, "daily_credits": 200,
            "extra_credits": 100, "claimable": [{"item": "daily_checkin", "title": "每日签到", "credits": 300}]}


def trae_signed():
    return {"kind": "daily_checkin", "enabled": True, "signed_in": True, "daily_credits": 200,
            "extra_credits": 100, "claimable": []}


class Fake:
    def __init__(self, statuses, claims=None):
        self.statuses, self.claims, self.calls = list(statuses), list(claims or []), []

    def status(self, session, timeout):
        self.calls.append("status")
        value = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        if isinstance(value, SourceError):
            raise value
        return value

    def claim(self, session, item, timeout):
        self.calls.append(("claim", item))
        value = self.claims.pop(0) if self.claims else {"result": "ok", "credits": 300}
        if isinstance(value, SourceError):
            raise value
        return value


class ParseTests(unittest.TestCase):
    def test_accepts_the_documented_shape(self):
        request = windows_rewards.parse_request({
            "sessions": {"trae_cn": [trae_session()], "workbuddy": [workbuddy_session()]},
            "auto_claim": ["workbuddy", "trae_cn"], "claim_time": "08:30",
            "claim_all": False, "only": "trae_cn"})
        self.assertEqual(request["auto_claim"], ["trae_cn", "workbuddy"])
        self.assertEqual(request["claim_time"], "08:30")
        self.assertEqual(len(request["sessions"]["trae_cn"]), 1)

    def test_rejects_unknown_fields_and_providers(self):
        for data in [
            {"sessions": {"qoder": [{"cookie": COOKIE, "user_agent": UA}]}},
            {"auto_claim": ["qoder"]},
            {"only": "qoder"},
            {"only": "trae_cn#6"},
            {"claim_time": "8:00"},
            {"claim_all": "yes"},
            {"sessions": {"trae_cn": [dict(trae_session(), extra="x")]}},
            {"sessions": {"trae_cn": [{"token": "short", "user_agent": UA, "device_id": None}]}},
            {"unknown": True},
            [],
        ]:
            with self.assertRaises(ValueError, msg=repr(data)):
                windows_rewards.parse_request(data)

    def test_runtime_dir_requires_an_absolute_local_app_data(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(windows_rewards.runtime_dir(root), Path(root) / "AgentMeter")
            self.assertIsNone(windows_rewards.runtime_dir("relative/path"))
            self.assertIsNone(windows_rewards.runtime_dir(""))


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def request(self, auto=("trae_cn",), claim_time="08:00", **extra):
        return windows_rewards.parse_request({"sessions": {"trae_cn": [trae_session()]},
                                             "auto_claim": list(auto), "claim_time": claim_time, **extra})

    def adapters(self, trae):
        return {"trae_cn": (trae.status, trae.claim)}

    def test_claim_once_then_rechecks_without_second_claim(self):
        trae = Fake([trae_open(), trae_signed()])
        out = windows_rewards.claim(self.dir, self.request(), NOW, adapters=self.adapters(trae))
        self.assertEqual(trae.calls, ["status", ("claim", "daily_checkin"), "status"])
        account = out["accounts"][0]
        self.assertEqual(account["id"], "trae_cn")
        self.assertEqual(account["claimed_credits_today"], 300)
        self.assertEqual(account["claim_time"], "08:00")
        self.assertTrue(account["today"]["signed_in"])
        self.assertEqual([item["provider"] for item in out["unsupported"]], ["qoder", "minimax_code"])

        out = windows_rewards.claim(self.dir, self.request(), NOW + STATUS_EVERY, adapters=self.adapters(trae))
        self.assertEqual(trae.calls, ["status", ("claim", "daily_checkin"), "status", "status"])
        self.assertEqual(out["accounts"][0]["claimed_credits_today"], 300)

    def test_status_is_ledger_only_and_never_calls_the_network(self):
        trae = Fake([trae_open(), trae_signed()])
        windows_rewards.claim(self.dir, self.request(), NOW, adapters=self.adapters(trae))
        calls = len(trae.calls)
        out = windows_rewards.status(self.dir, windows_rewards.parse_request({"auto_claim": ["trae_cn"]}), NOW)
        self.assertEqual(len(trae.calls), calls)
        self.assertEqual(out["source"], "ledger")
        self.assertEqual(out["accounts"][0]["id"], "trae_cn")
        self.assertEqual(out["accounts"][0]["status"], "available")
        self.assertEqual(out["accounts"][1]["id"], "workbuddy")
        self.assertEqual(out["accounts"][1]["reason"], "not_checked_yet")

    def test_auth_failure_is_reported_not_raised(self):
        trae = Fake([SourceError("not_authenticated")])
        out = windows_rewards.claim(self.dir, self.request(), NOW, adapters=self.adapters(trae))
        account = out["accounts"][0]
        self.assertEqual((account["status"], account["reason"]), ("not_connected", "not_authenticated"))

    def test_claim_waits_for_the_daily_moment(self):
        trae = Fake([trae_open()])
        out = windows_rewards.claim(self.dir, self.request(claim_time="17:00"), NOW, adapters=self.adapters(trae))
        self.assertEqual(trae.calls, ["status"])
        self.assertEqual(out["accounts"][0]["next_claim_at"]["epoch_seconds"], NOW + 3600)

    def test_unknown_slot_does_not_touch_a_session(self):
        trae = Fake([trae_open()])
        windows_rewards.claim(self.dir, self.request(only="workbuddy#2"), NOW, adapters=self.adapters(trae))
        self.assertEqual(trae.calls, [])


class CliTests(unittest.TestCase):
    def test_status_mode_reads_stdin_and_writes_json(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as local:
            env = dict(os.environ, LOCALAPPDATA=local)
            result = subprocess.run(
                [sys.executable, "-m", "windows.backend", "--rewards-status"],
                input=json.dumps({"auto_claim": ["trae_cn"], "claim_time": "08:00"}),
                capture_output=True, text=True, cwd=root, env=env, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["source"], "ledger")
            self.assertEqual([row["id"] for row in payload["accounts"]], ["trae_cn", "workbuddy"])
            self.assertNotIn(TOKEN, result.stdout)

    def test_invalid_input_exits_without_echoing_it(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as local:
            env = dict(os.environ, LOCALAPPDATA=local)
            result = subprocess.run(
                [sys.executable, "-m", "windows.backend", "--rewards-status"],
                input='{"auto_claim":["qoder"]}', capture_output=True, text=True, cwd=root, env=env, timeout=60)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, "")
            self.assertNotIn("qoder", result.stderr)


if __name__ == "__main__":
    unittest.main()
