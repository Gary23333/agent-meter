import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from agent_meter import rewards
from agent_meter.collector import SnapshotService
from agent_meter.model import SourceError
from agent_meter.rewards import RewardsService, day_of
from agent_meter.server import load_or_create_token, make_server

NOW = 1794211200  # 2026-11-09 16:00 Asia/Shanghai
DAY = 86400

# Shapes of the 2026-11-09 read-only probes, values synthetic.
TRAE_SIGNED = {"checked_in": True, "code": 0, "credits": 200, "did_checked_in": False, "enable": True,
               "extra_credits": 100, "message": "success"}
TRAE_OPEN = dict(TRAE_SIGNED, checked_in=False)
WB_STREAK = {"code": 0, "msg": "OK", "data": {
    "streak": {"days": 1, "month_total_days": 4, "month_consumed_days": 0, "next_tier": "7d", "next_tier_remaining": 5,
               "makeup_dates": []},
    "makeup_cards": {"balance": 0, "max": 4},
    "redemption_status": {"tier_7d_status": "locked", "tier_14d_status": "locked", "tier_28d_status": "locked",
                          "tiers": [{"tier": "7d", "days": 7, "credit": 0}, {"tier": "14d", "days": 14, "credit": 50},
                                    {"tier": "28d", "days": 28, "credit": 150}]},
    "timezone": "Asia/Shanghai"}}


QODER_OPEN = {"kind": "campaign", "enabled": True, "signed_in": None, "campaigns": [
    {"campaign_id": "act-1", "title": "daily_100_credits", "credits": 100, "status": "CLAIMABLE", "active": True}],
    "claimable": [{"item": "campaign:act-1", "title": "daily_100_credits", "credits": 100}]}


def wb_tasks(*states):
    return {"code": 0, "msg": "OK", "data": {"tasks": [
        {"task_code": code, "title": "任务 " + code, "accept_status": state, "reward_credit": 100}
        for code, state in states]}}


class Fake:
    """Adapter pair recording every status read and claim."""

    def __init__(self, statuses, claims=None):
        self.statuses, self.claims = list(statuses), list(claims or [])
        self.calls = []

    def status(self, session, timeout):
        self.calls.append(("status", session.get("token") or session.get("cookie")))
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


def trae_open():
    return rewards.normalize_trae_status(TRAE_OPEN)


def trae_signed():
    return rewards.normalize_trae_status(TRAE_SIGNED)


class NormalizeTests(unittest.TestCase):
    def test_trae_status(self):
        signed = trae_signed()
        self.assertTrue(signed["signed_in"])
        self.assertEqual(signed["claimable"], [])
        self.assertEqual((signed["daily_credits"], signed["extra_credits"]), (200, 100))
        self.assertEqual(trae_open()["claimable"], [{"item": "daily_checkin", "title": "每日签到", "credits": 300}])
        disabled = rewards.normalize_trae_status(dict(TRAE_OPEN, enable=False))
        self.assertEqual(disabled["claimable"], [])
        for bad in [{"code": 1}, {"code": 0}, [], None]:
            with self.assertRaises(SourceError):
                rewards.normalize_trae_status(bad)

    def test_trae_claim_results(self):
        self.assertEqual(rewards.normalize_trae_claim({"code": 0})["result"], "ok")
        self.assertEqual(rewards.normalize_trae_claim({"code": 9004}), {"result": "already", "code": 9004})
        self.assertEqual(rewards.normalize_trae_claim({"code": 9095}), {"result": "rejected", "code": 9095})
        with self.assertRaises(SourceError):
            rewards.normalize_trae_claim({"message": "no code"})

    def test_workbuddy_status_only_offers_completed_tasks(self):
        status = rewards.normalize_workbuddy_status(WB_STREAK, wb_tasks(
            ("skill_1", "completed"), ("done", "claimed"), ("new", "not_accepted"), ("busy", "in_progress"),
            ("bad code!", "completed")))
        self.assertEqual(status["claimable"], [{"item": "task:skill_1", "title": "任务 skill_1", "credits": 100}])
        self.assertEqual((status["streak_days"], status["next_tier"], status["next_tier_remaining"]), (1, "7d", 5))
        self.assertEqual((status["makeup_cards"], status["makeup_cards_max"], status["open_tasks"]), (0, 4, 1))
        self.assertEqual(status["tiers"][1], {"tier": "14d", "days": 14, "credits": 50, "status": "locked"})
        self.assertIsNone(status["signed_in"])
        with self.assertRaises(SourceError):
            rewards.normalize_workbuddy_status({"code": 0, "data": {}}, {"code": 0, "data": {"tasks": None}})

    def test_workbuddy_claim(self):
        ok = rewards.normalize_workbuddy_claim({"code": 0, "data": {"already_claimed": False, "credit": 100,
                                                                    "badge": {"name": "尝鲜达人", "url": "u"}}})
        self.assertEqual(ok, {"result": "ok", "credits": 100, "badge": "尝鲜达人"})
        self.assertEqual(rewards.normalize_workbuddy_claim({"code": 0, "data": {"already_claimed": True}}),
                         {"result": "already"})

    def test_claim_paths_reject_unknown_items(self):
        with self.assertRaises(SourceError):
            rewards.workbuddy_claim({"cookie": "c"}, "task:../../pay", 5)
        with self.assertRaises(SourceError):
            rewards.trae_claim({"token": "t"}, "task:x", 5)

    def test_requests_use_fixed_endpoints(self):
        with mock.patch.object(rewards, "post_json", return_value={"code": 0}) as post:
            rewards.trae_claim({"token": "Cloud-IDE-JWT abc", "user_agent": "UA"}, "daily_checkin", 5)
        url, body = post.call_args[0]
        self.assertEqual(url, "https://api.trae.cn/trae/api/v2/ug/checkin_credits/claim")
        self.assertEqual(body, {"req_source": 1})
        self.assertEqual(post.call_args[1]["headers"]["Authorization"], "Cloud-IDE-JWT abc")
        with mock.patch.object(rewards, "post_json", return_value={"code": 0, "data": {"credit": 1}}) as post:
            rewards.workbuddy_claim({"cookie": "c"}, "task:skill_1", 5)
        self.assertEqual(post.call_args[0][0], "https://www.workbuddy.cn/activity/growth/tasks/skill_1/claim")


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def service(self, trae=None, workbuddy=None):
        self.trae = trae or Fake([trae_signed()])
        self.wb = workbuddy or Fake([rewards.normalize_workbuddy_status(WB_STREAK, wb_tasks())])
        return RewardsService(self.tmp.name, {"trae_cn": (self.trae.status, self.trae.claim),
                                              "workbuddy": (self.wb.status, self.wb.claim)})

    def test_a_plain_read_never_claims(self):
        svc = self.service(trae=Fake([trae_open()]))
        out = svc.tick({"trae_cn": {"token": "T"}}, NOW)
        self.assertEqual(self.trae.calls, [("status", "T")])
        account = out["accounts"][0]
        self.assertEqual((account["id"], account["status"]), ("trae_cn", "available"))
        # No switch and no schedule travel with the summary any more.
        for gone in ("auto_claim", "claim_time", "next_claim_at"):
            self.assertNotIn(gone, account)
        self.assertEqual(account["today"]["claimable"][0]["item"], "daily_checkin")

    def test_no_hour_of_the_day_claims_on_its_own(self):
        # The daily claim time is gone: around the clock a read stays a read.
        tasks = lambda: rewards.normalize_workbuddy_status(WB_STREAK, wb_tasks(("skill_1", "completed")))
        trae, wb = Fake([trae_open()]), Fake([tasks()])
        svc = RewardsService(self.tmp.name, {"trae_cn": (trae.status, trae.claim),
                                             "workbuddy": (wb.status, wb.claim)})
        sessions = {"trae_cn": {"token": "T"}, "workbuddy": {"cookie": "C"}}
        for offset in (0, 10, DAY - 300, DAY - 290, DAY + 300, DAY + 7 * 3600 + 50 * 60):
            svc.tick(sessions, NOW + offset)
        self.assertEqual([c for c in trae.calls + wb.calls if c[0] == "claim"], [])
        self.assertEqual(svc.ledger["accounts"]["trae_cn"]["days"][day_of(NOW + DAY)].get("claims"), [])

    def test_claim_now_claims_once_then_rechecks(self):
        svc = self.service(trae=Fake([trae_open(), trae_signed()]))
        out = svc.tick({"trae_cn": {"token": "T"}}, NOW, only="trae_cn")
        self.assertEqual([c[0] for c in self.trae.calls], ["status", "claim", "status"])
        account = out["accounts"][0]
        self.assertEqual(account["claimed_credits_today"], 300)
        self.assertTrue(account["today"]["signed_in"])
        self.assertEqual(account["streak_days"], 1)
        # The settled item is not claimed again, and later reads stay throttled.
        svc.tick({"trae_cn": {"token": "T"}}, NOW + 10, only="trae_cn")
        self.assertEqual([c[0] for c in self.trae.calls[3:]], ["status"])
        svc.tick({"trae_cn": {"token": "T"}}, NOW + 60)
        self.assertEqual(len(self.trae.calls), 4)
        svc.tick({"trae_cn": {"token": "T"}}, NOW + 10 + rewards.STATUS_EVERY)
        self.assertEqual([c[0] for c in self.trae.calls[4:]], ["status"])

    def test_desktop_provider_is_one_account_without_a_web_session(self):
        svc = self.service()
        svc.adapters["qoder"] = (lambda session, timeout: QODER_OPEN,
                                  lambda session, item, timeout: {"result": "ok", "credits": 100})
        out = svc.tick({}, NOW, desktop={"qoder": "/Applications/Qoder CN.app"})
        account = out["accounts"][0]
        self.assertEqual(account["id"], "qoder")
        self.assertEqual(account["status"], "available")
        self.assertEqual(account["today"]["claimable"][0]["item"], "campaign:act-1")
        self.assertEqual(account["streak_days"], None)

    def test_desktop_provider_is_skipped_when_disabled(self):
        svc = self.service()
        svc.adapters["qoder"] = (lambda session, timeout: QODER_OPEN,
                                  lambda session, item, timeout: {"result": "ok", "credits": 100})
        out = svc.tick({}, NOW, disabled={"qoder"}, desktop={"qoder": "/Applications/Qoder CN.app"})
        account = out["accounts"][0]
        self.assertEqual((account["id"], account["status"], account["reason"]), ("qoder", "not_connected", "disabled_by_user"))

    def test_desktop_provider_claims_on_request(self):
        svc = self.service()
        calls = []

        def claim(session, item, timeout):
            calls.append(item)
            return {"result": "ok", "credits": 100}

        svc.adapters["qoder"] = (lambda session, timeout: QODER_OPEN, claim)
        desktop = {"qoder": "/Applications/Qoder CN.app"}
        svc.tick({}, NOW, desktop=desktop)
        self.assertEqual(calls, [])   # a plain read leaves the campaign alone
        out = svc.tick({}, NOW + 5, desktop=desktop, claim_all=True)
        self.assertEqual(calls, ["campaign:act-1"])
        self.assertEqual(out["accounts"][0]["claimed_credits_today"], 100)

    def test_desktop_credential_survives_an_expired_website_login(self):
        # A Qoder website login cannot claim campaigns. When it expires it must
        # not hide the desktop credential that can.
        svc = self.service()
        seen = []

        def status(session, timeout):
            seen.append(session)
            if not session.get("desktop_app"):
                raise SourceError("qoder_desktop_not_installed")
            return QODER_OPEN

        svc.adapters["qoder"] = (status, lambda session, item, timeout: {"result": "ok", "credits": 100})
        out = svc.tick({"qoder": {"cookie": "EXPIRED"}}, NOW, desktop={"qoder": "/Applications/Qoder CN.app"},
                       claim_all=True)
        account = out["accounts"][0]
        self.assertEqual((account["id"], account["status"], account["reason"]), ("qoder", "available", None))
        self.assertEqual(account["claimed_credits_today"], 100)
        self.assertEqual(seen[0], {"desktop_app": "/Applications/Qoder CN.app"})

    def test_trae_device_id_comes_from_the_client_key_name(self):
        home = Path(self.tmp.name)
        storage = home / "Library/Application Support/Trae CN/User/globalStorage/storage.json"
        storage.parent.mkdir(parents=True)
        storage.write_text(json.dumps({"iCubeAuthInfo://icube-dc:631551464320604": "encrypted",
                                       "iCubeAuthInfo://icube-dc:not-a-number": "x",
                                       "telemetry.machineId": "ab"}))
        self.assertEqual(rewards.trae_device_id(home), "631551464320604")
        storage.write_text("{not json")
        self.assertIsNone(rewards.trae_device_id(home))
        self.assertIsNone(rewards.trae_device_id(home / "missing"))

    def test_tick_attaches_the_client_device_id_to_trae_claims(self):
        seen = []

        def status(session, timeout):
            seen.append(session)
            return trae_open()

        def claim(session, item, timeout):
            seen.append(session)
            return {"result": "ok", "credits": 300}

        svc = RewardsService(self.tmp.name, {"trae_cn": (status, claim)})
        with mock.patch.object(rewards, "trae_device_id", return_value="631551464320604"):
            svc.tick({"trae_cn": {"token": "T"}}, NOW, claim_all=True)
        self.assertEqual([s.get("device_id") for s in seen], ["631551464320604"] * 3)
        seen.clear()
        with mock.patch.object(rewards, "trae_device_id", return_value="631551464320604"):
            svc.tick({"trae_cn": {"token": "T", "device_id": "123456789012345"}}, NOW + DAY, claim_all=True)
        self.assertEqual({s.get("device_id") for s in seen}, {"123456789012345"})

    def test_a_failed_claim_is_retried_on_the_next_request(self):
        # Nothing runs in the background, so an hourly back-off or a daily cap
        # would only ignore the user's next press. The press is the retry.
        svc = self.service(trae=Fake([trae_open()], [SourceError("connection_failed")] * 5))
        for offset in (0, 5, 10):
            svc.tick({"trae_cn": {"token": "T"}}, NOW + offset, only="trae_cn")
        self.assertEqual([c for c in self.trae.calls if c[0] == "claim"], [("claim", "daily_checkin")] * 3)
        record = svc.ledger["accounts"]["trae_cn"]["days"][day_of(NOW)]
        self.assertEqual([c["result"] for c in record["claims"]], ["error"] * 3)
        self.assertEqual(record["claims"][0]["reason"], "connection_failed")
        # A later plain read still claims nothing by itself.
        svc.tick({"trae_cn": {"token": "T"}}, NOW + rewards.STATUS_EVERY)
        self.assertEqual(len([c for c in self.trae.calls if c[0] == "claim"]), 3)

    def test_already_stops_retries_but_is_not_a_signed_day(self):
        svc = self.service(trae=Fake([trae_open()], [{"result": "already", "code": 9004}]))
        out = svc.tick({"trae_cn": {"token": "T"}}, NOW, claim_all=True)
        svc.tick({"trae_cn": {"token": "T"}}, NOW + 5, claim_all=True)
        self.assertEqual(len([c for c in self.trae.calls if c[0] == "claim"]), 1)
        self.assertEqual(out["accounts"][0]["streak_days"], 0)

    def test_already_but_still_open_is_a_final_refusal(self):
        # TRAE answers 9004 to a web-only claim it refuses; status stays open.
        svc = self.service(trae=Fake([trae_open()], [{"result": "already", "code": 9004}]))
        out = svc.tick({"trae_cn": {"token": "T"}}, NOW, claim_all=True)
        claim = out["accounts"][0]["claims_today"][0]
        self.assertEqual((claim["result"], claim["final"], claim["reason"]), ("rejected", True, "claim_refused_from_web"))
        svc.tick({"trae_cn": {"token": "T"}}, NOW + 5, claim_all=True)
        self.assertEqual(len([c for c in self.trae.calls if c[0] == "claim"]), 1)

    def test_streak_counts_consecutive_days(self):
        svc = self.service(trae=Fake([trae_signed()]))
        for offset in (3, 2, 1):
            svc.tick({"trae_cn": {"token": "T"}}, NOW - offset * DAY)
        self.trae.statuses = [trae_open()]
        out = svc.tick({"trae_cn": {"token": "T"}}, NOW)
        self.assertEqual(out["accounts"][0]["streak_days"], 3)  # today still open
        self.assertEqual(len(out["accounts"][0]["history"]), 4)

    def test_workbuddy_claims_completed_tasks_only(self):
        wb = Fake([rewards.normalize_workbuddy_status(WB_STREAK, wb_tasks(("skill_1", "completed"), ("x", "not_accepted"))),
                   rewards.normalize_workbuddy_status(WB_STREAK, wb_tasks(("skill_1", "claimed")))],
                  [{"result": "ok", "credits": 100, "badge": "尝鲜达人"}])
        svc = self.service(workbuddy=wb)
        out = svc.tick({"workbuddy": [{"cookie": "C1"}]}, NOW, claim_all=True)
        self.assertEqual([c for c in wb.calls if c[0] == "claim"], [("claim", "task:skill_1")])
        account = out["accounts"][0]
        self.assertEqual(account["claims_today"][0]["badge"], "尝鲜达人")
        self.assertEqual(account["claimed_credits_total"], 100)
        self.assertIsNone(account["streak_days"])

    def test_claim_now_reads_and_claims_one_slot_only(self):
        svc = self.service(trae=Fake([trae_open(), trae_open(), trae_open(), trae_signed()]))
        sessions = {"trae_cn": [{"token": "A"}, {"token": "B", "label": "小号"}]}
        svc.tick(sessions, NOW)
        out = svc.tick(sessions, NOW + 10, only="trae_cn#2")
        self.assertEqual(self.trae.calls[-3:], [("status", "B"), ("claim", "daily_checkin"), ("status", "B")])
        self.assertEqual([a["id"] for a in out["accounts"]], ["trae_cn", "trae_cn#2"])
        self.assertEqual(out["accounts"][1]["account_label"], "小号")
        # The other account was neither re-read nor claimed.
        self.assertEqual(out["accounts"][0]["claims_today"], [])
        self.assertEqual(self.trae.calls[2:], [("status", "B"), ("claim", "daily_checkin"), ("status", "B")])

    def test_claim_all_reads_and_claims_every_account(self):
        svc = self.service(trae=Fake([trae_open(), trae_open(), trae_signed()]),
                           workbuddy=Fake([rewards.normalize_workbuddy_status(WB_STREAK, wb_tasks(("skill_1", "completed")))],
                                          [{"result": "ok", "credits": 100}]))
        sessions = {"trae_cn": {"token": "T"}, "workbuddy": {"cookie": "C"}}
        # A plain read claims nothing; the request then claims every account.
        svc.tick(sessions, NOW)
        self.assertEqual([c[0] for c in self.trae.calls], ["status"])
        out = svc.tick(sessions, NOW + 10, claim_all=True)
        self.assertEqual([c[0] for c in self.trae.calls[1:]], ["status", "claim", "status"])
        self.assertEqual([c[0] for c in self.wb.calls], ["status", "status", "claim", "status"])
        self.assertEqual([a["claimed_credits_today"] for a in out["accounts"]], [300, 100])

    def test_claim_all_skips_disabled_accounts(self):
        svc = self.service(trae=Fake([trae_open()]))
        out = svc.tick({"trae_cn": {"token": "T"}}, NOW, disabled={"trae_cn"}, claim_all=True)
        self.assertEqual(out["accounts"][0]["reason"], "disabled_by_user")
        self.assertEqual(self.trae.calls, [])

    def test_errors_disabled_and_local_only(self):
        svc = self.service(trae=Fake([SourceError("not_authenticated")]))
        out = svc.tick({"trae_cn": {"token": "T"}, "workbuddy": {"cookie": "C"}}, NOW, disabled={"workbuddy"})
        trae, wb = out["accounts"]
        self.assertEqual((trae["status"], trae["reason"]), ("not_connected", "not_authenticated"))
        self.assertEqual((wb["status"], wb["reason"]), ("not_connected", "disabled_by_user"))
        self.assertEqual(self.wb.calls, [])
        out = svc.tick({"trae_cn": {"token": "T"}}, NOW + DAY, local_only=True)
        self.assertEqual(out["accounts"][0]["reason"], "local_only_mode")

    def test_ledger_is_private_and_holds_no_credentials(self):
        svc = self.service(trae=Fake([trae_open(), trae_signed()]))
        svc.tick({"trae_cn": {"token": "SECRET_TOKEN"}}, NOW, claim_all=True)
        path = Path(self.tmp.name) / "rewards.json"
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn("SECRET_TOKEN", path.read_text())
        self.assertNotIn("auto_claim", path.read_text())
        reloaded = RewardsService(self.tmp.name, {"trae_cn": (self.trae.status, self.trae.claim)})
        self.assertIn(day_of(NOW), reloaded.ledger["accounts"]["trae_cn"]["days"])

    def test_corrupt_ledger_starts_fresh(self):
        (Path(self.tmp.name) / "rewards.json").write_text("{not json")
        self.assertEqual(rewards.load_ledger(Path(self.tmp.name) / "rewards.json")["accounts"], {})


def sample(now):
    return {"schema_version": 5, "collected_at": None, "sources": [], "coverage": [],
            "application_usage": {}, "coverage_summary": {}}


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.token = load_or_create_token(Path(self.tmp.name) / "api.token")
        self.service = SnapshotService({"runtime_dir": self.tmp.name}, lambda config, now: sample(now), clock=lambda: NOW)
        self.fake = Fake([trae_open(), trae_signed()])
        self.service.rewards = RewardsService(self.tmp.name, {"trae_cn": (self.fake.status, self.fake.claim),
                                                              "workbuddy": (self.fake.status, self.fake.claim)})
        self.service.set_web_sessions({"trae_cn": [{"token": "T"}]})
        self.server = make_server(self.service, self.token, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:" + str(self.server.server_address[1])

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.tmp.cleanup()

    def open(self, path, method="GET"):
        req = urllib.request.Request(self.url + path, method=method, headers={"Authorization": "Bearer " + self.token})
        return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=3)

    def test_snapshot_carries_rewards_without_claiming(self):
        with self.open("/v1/snapshot") as r:
            data = json.load(r)
        self.assertEqual(data["rewards"]["accounts"][0]["id"], "trae_cn")
        self.assertNotIn(("claim", "daily_checkin"), self.fake.calls)

    def test_claim_endpoint(self):
        with self.open("/v1/rewards/claim/trae_cn", "POST") as r:
            data = json.load(r)
        self.assertEqual(data["accounts"][0]["claimed_credits_today"], 300)
        for bad in ["/v1/rewards/claim/claude", "/v1/rewards/claim/trae_cn%239", "/v1/rewards/claim/trae_cn%23x"]:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.open(bad, "POST")
            self.assertEqual(ctx.exception.code, 404)

    def test_claim_all_endpoint(self):
        # No slot: the panel's button claims every account, and nothing else does.
        with self.open("/v1/rewards/claim", "POST") as r:
            data = json.load(r)
        self.assertEqual(data["accounts"][0]["claimed_credits_today"], 300)
        self.assertIn(("claim", "daily_checkin"), self.fake.calls)


if __name__ == "__main__":
    unittest.main()
