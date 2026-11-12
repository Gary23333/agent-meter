import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_meter import rewards
from agent_meter.model import SourceError
from agent_meter.rewards import RewardsService, day_of

NOW = 1794211200  # 2026-11-09 16:00 Asia/Shanghai
DAY = 86400

TRAE_OPEN = {"checked_in": False, "code": 0, "credits": 200, "did_checked_in": False,
             "enable": True, "extra_credits": 100, "message": "success"}

# MiniMax signin shapes from the public CreditDaddy client (src/minimaxClient.js),
# values synthetic. status 1 = unclaimed, 3 = claimed; claim_result 1 = new, 2 = already.
MM_OPEN = {"base_resp": {"status_code": 0, "status_msg": "ok"}, "data": {"days": [
    {"is_today": False, "status": 3, "day_no": 1, "points": 400, "bonus_points": 0},
    {"is_today": True, "status": 1, "day_no": 2, "points": 400, "bonus_points": 0}]}}
MM_SIGNED = {"base_resp": {"status_code": 0}, "data": {"days": [
    {"is_today": True, "status": 3, "day_no": 2, "points": 400, "bonus_points": 0}]}}
MM_CLAIM_OK = {"base_resp": {"status_code": 0}, "data": {"claim_result": 1, "points": 400, "day_no": 2}}
MM_CLAIM_AGAIN = {"base_resp": {"status_code": 0}, "data": {"claim_result": 2, "points": 400, "day_no": 2}}


class Fake:
    def __init__(self, statuses, claims=None):
        self.statuses, self.claims = list(statuses), list(claims or [])
        self.calls = []

    def status(self, session, timeout):
        self.calls.append(("status", session.get("cookie") or session.get("token")))
        value = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        if isinstance(value, SourceError):
            raise value
        return value

    def claim(self, session, item, timeout):
        self.calls.append(("claim", item))
        value = self.claims.pop(0) if self.claims else {"result": "ok", "credits": 400}
        if isinstance(value, SourceError):
            raise value
        return value


def trae_post(url, body, timeout=None, headers=None):
    return TRAE_OPEN if url.endswith("/checkin_credits/status") else {"code": 0}


class TraeBonusTests(unittest.TestCase):
    def test_birthday_normalization_keeps_amount_unknown(self):
        item = rewards.normalize_trae_birthday({"code": 0, "whatever": 1})
        self.assertEqual(item["item"], "birthday_bonus")
        self.assertIsNone(item["credits"])
        self.assertEqual((item["state"], item["reason"]), ("unknown", "trae_birthday_contract_unknown"))
        for bad in [{"code": 1}, [], None]:
            with self.assertRaises(SourceError) as ctx:
                rewards.normalize_trae_birthday(bad)
            self.assertEqual(ctx.exception.code, "trae_birthday_api_error")

    def test_bonus_items_are_never_claimable(self):
        status = rewards.normalize_trae_status(TRAE_OPEN)
        self.assertEqual([c["item"] for c in status["claimable"]], ["daily_checkin"])
        with mock.patch.object(rewards, "post_json", side_effect=trae_post) as post:
            full = rewards.trae_status({"token": "T"}, 5)
        self.assertEqual([b["item"] for b in full["bonus_items"]], ["birthday_bonus", "work_lottery"])
        self.assertTrue(all(b["credits"] is None for b in full["bonus_items"]))
        self.assertEqual([c["item"] for c in full["claimable"]], ["daily_checkin"])
        self.assertEqual(post.call_args_list[1][0][0],
                         "https://api.trae.cn/trae/api/v2/pay/query_birthday_bonus")

    def test_birthday_query_failure_stays_local(self):
        def post(url, body, timeout=None, headers=None):
            if url.endswith("/checkin_credits/status"):
                return TRAE_OPEN
            raise SourceError("http_404")
        with mock.patch.object(rewards, "post_json", side_effect=post):
            status = rewards.trae_status({"token": "T"}, 5)
        self.assertTrue(status["claimable"])
        birthday, lottery = status["bonus_items"]
        self.assertEqual((birthday["state"], birthday["reason"]), ("error", "http_404"))
        self.assertIsNone(birthday["credits"])
        self.assertEqual((lottery["state"], lottery["reason"]), ("unknown", "trae_lottery_endpoint_unknown"))

    def test_lottery_endpoint_is_not_invented(self):
        with mock.patch.object(rewards, "post_json", side_effect=trae_post) as post:
            rewards.trae_status({"token": "T"}, 5)
        urls = [c[0][0] for c in post.call_args_list]
        self.assertEqual(len(urls), 2)
        self.assertFalse(any("lottery" in u for u in urls))

    def test_bonus_claims_are_refused(self):
        for item in ["birthday_bonus", "work_lottery"]:
            with self.assertRaises(SourceError) as ctx:
                rewards.trae_claim({"token": "T"}, item, 5)
            self.assertEqual(ctx.exception.code, "trae_bonus_claim_not_supported")
        with self.assertRaises(SourceError) as ctx:
            rewards.trae_claim({"token": "T"}, "task:x", 5)
        self.assertEqual(ctx.exception.code, "unknown_reward_item")


class MinimaxNormalizeTests(unittest.TestCase):
    def test_open_day_is_claimable(self):
        status = rewards.normalize_minimax_code_status(MM_OPEN)
        self.assertEqual(status["kind"], "daily_checkin")
        self.assertFalse(status["signed_in"])
        self.assertEqual(status["streak_days"], 2)
        self.assertEqual(status["claimable"], [{"item": "daily_checkin", "title": "每日签到", "credits": 400}])

    def test_signed_day_has_nothing_to_claim(self):
        status = rewards.normalize_minimax_code_status(MM_SIGNED)
        self.assertTrue(status["signed_in"])
        self.assertEqual(status["claimable"], [])

    def test_unknown_bonus_is_not_summed_as_zero(self):
        payload = {"base_resp": {"status_code": 0}, "data": {"days": [
            {"is_today": True, "status": 1, "day_no": 2, "points": 400}]}}
        status = rewards.normalize_minimax_code_status(payload)
        self.assertIsNone(status["claimable"][0]["credits"])

    def test_missing_today_is_unknown(self):
        payload = {"base_resp": {"status_code": 0}, "data": {"days": [
            {"is_today": False, "status": 3, "day_no": 1, "points": 400}]}}
        status = rewards.normalize_minimax_code_status(payload)
        self.assertIsNone(status["signed_in"])
        self.assertEqual(status["claimable"], [])

    def test_bad_envelope_and_shape(self):
        with self.assertRaises(SourceError) as ctx:
            rewards.normalize_minimax_code_status({"base_resp": {"status_code": 5}, "data": {}})
        self.assertEqual(ctx.exception.code, "minimax_code_api_error")
        for bad in [{"base_resp": {"status_code": 0}, "data": {"days": None}},
                    {"base_resp": {"status_code": 0}, "data": {}},
                    {"base_resp": {"status_code": 0}, "data": {"days": [{"is_today": True, "status": 9}]}},
                    [], None]:
            with self.assertRaises(SourceError) as ctx:
                rewards.normalize_minimax_code_status(bad)
            self.assertEqual(ctx.exception.code, "unsupported_minimax_code_contract")

    def test_claim_results(self):
        self.assertEqual(rewards.normalize_minimax_code_claim(MM_CLAIM_OK), {"result": "ok", "credits": 400})
        self.assertEqual(rewards.normalize_minimax_code_claim(MM_CLAIM_AGAIN), {"result": "already"})
        for bad in [{"base_resp": {"status_code": 0}, "data": {"claim_result": 7}},
                    {"base_resp": {"status_code": 1}, "data": {}},
                    {"base_resp": {"status_code": 0}, "data": None}]:
            with self.assertRaises(SourceError):
                rewards.normalize_minimax_code_claim(bad)


class MinimaxAdapterTests(unittest.TestCase):
    def test_status_requires_cookie_and_reports_unsupported(self):
        with mock.patch.object(rewards, "get_json") as get, mock.patch.object(rewards, "post_json") as post:
            with self.assertRaises(SourceError) as ctx:
                rewards.minimax_code_status({}, 5)
            self.assertEqual(ctx.exception.code, "minimax_code_not_authenticated")
            with self.assertRaises(SourceError) as ctx:
                rewards.minimax_code_status({"cookie": "C"}, 5)
            self.assertEqual(ctx.exception.code, "minimax_code_not_supported")
        get.assert_not_called()
        post.assert_not_called()

    def test_claim_is_gated_and_unsupported(self):
        with self.assertRaises(SourceError) as ctx:
            rewards.minimax_code_claim({"cookie": "C"}, "task:x", 5)
        self.assertEqual(ctx.exception.code, "unknown_reward_item")
        with self.assertRaises(SourceError) as ctx:
            rewards.minimax_code_claim({}, "daily_checkin", 5)
        self.assertEqual(ctx.exception.code, "minimax_code_not_authenticated")
        with mock.patch.object(rewards, "post_json") as post:
            with self.assertRaises(SourceError) as ctx:
                rewards.minimax_code_claim({"cookie": "C"}, "daily_checkin", 5)
        self.assertEqual(ctx.exception.code, "minimax_code_not_supported")
        post.assert_not_called()

    def test_endpoint_contract_is_pinned(self):
        self.assertEqual(rewards.MINIMAX_CODE_SIGNIN, "https://agent.minimax.cn/minimax-cloud/api/v1/signin")


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def service(self, adapters):
        return RewardsService(self.tmp.name, adapters)

    def test_minimax_without_cookie_is_not_connected(self):
        svc = self.service(rewards.ADAPTERS)
        out = svc.tick({"minimax_code": {"user_agent": "UA"}}, NOW)
        account = out["accounts"][0]
        self.assertEqual((account["id"], account["status"], account["reason"]),
                         ("minimax_code", "not_connected", "minimax_code_not_authenticated"))
        self.assertFalse(account["auto_claim"])

    def test_minimax_with_cookie_is_unsupported_not_available(self):
        svc = self.service(rewards.ADAPTERS)
        out = svc.tick({"minimax_code": {"cookie": "C"}}, NOW, auto_claim={"minimax_code"})
        account = out["accounts"][0]
        self.assertEqual((account["status"], account["reason"]), ("error", "minimax_code_not_supported"))
        self.assertIsNone(account["today"])
        self.assertEqual(account["claims_today"], [])

    def test_minimax_absent_session_is_skipped(self):
        svc = self.service(rewards.ADAPTERS)
        out = svc.tick({}, NOW)
        self.assertEqual(out["accounts"], [])

    def test_minimax_claim_only_when_switched_on(self):
        open_status = rewards.normalize_minimax_code_status(MM_OPEN)
        signed_status = rewards.normalize_minimax_code_status(MM_SIGNED)
        fake = Fake([open_status])
        svc = self.service({"minimax_code": (fake.status, fake.claim)})
        svc.tick({"minimax_code": {"cookie": "C"}}, NOW)
        self.assertEqual([c[0] for c in fake.calls], ["status"])
        fake.statuses = [open_status, signed_status]
        out = svc.tick({"minimax_code": {"cookie": "C"}}, NOW + rewards.STATUS_EVERY,
                       auto_claim={"minimax_code"})
        self.assertEqual([c[0] for c in fake.calls[1:]], ["status", "claim", "status"])
        self.assertEqual(out["accounts"][0]["claimed_credits_today"], 400)

    def test_minimax_claim_failure_keeps_snapshot(self):
        fake = Fake([rewards.normalize_minimax_code_status(MM_OPEN)],
                    [SourceError("minimax_code_not_supported")])
        svc = self.service({"minimax_code": (fake.status, fake.claim)})
        out = svc.tick({"minimax_code": {"cookie": "C"}}, NOW, auto_claim={"minimax_code"})
        account = out["accounts"][0]
        self.assertEqual(account["status"], "available")
        self.assertEqual(account["claims_today"][0]["result"], "error")
        self.assertEqual(account["claims_today"][0]["reason"], "minimax_code_not_supported")
        self.assertEqual(account["claimed_credits_today"], 0)
        self.assertTrue(account["today"]["claimable"])

    def test_trae_bonus_never_auto_claimed(self):
        status = rewards.normalize_trae_status(TRAE_OPEN)
        status["bonus_items"] = [{"item": "birthday_bonus", "title": "生日奖励", "credits": None,
                                  "state": "unknown", "reason": "trae_birthday_contract_unknown"},
                                 {"item": "work_lottery", "title": "Work 抽奖", "credits": None,
                                  "state": "unknown", "reason": "trae_lottery_endpoint_unknown"}]
        fake = Fake([status])
        svc = self.service({"trae_cn": (fake.status, fake.claim)})
        out = svc.tick({"trae_cn": {"token": "T"}}, NOW, auto_claim={"trae_cn"})
        self.assertEqual([c for c in fake.calls if c[0] == "claim"], [("claim", "daily_checkin")])
        self.assertEqual(out["accounts"][0]["today"]["claimable"][0]["item"], "daily_checkin")
        self.assertEqual(len(out["accounts"][0]["today"]["bonus_items"]), 2)

    def test_existing_providers_unaffected_by_new_provider(self):
        trae = Fake([rewards.normalize_trae_status(TRAE_OPEN)])
        svc = self.service({"trae_cn": (trae.status, trae.claim)})
        out = svc.tick({"trae_cn": {"token": "T"}}, NOW)
        self.assertEqual([a["id"] for a in out["accounts"]], ["trae_cn"])
        self.assertEqual(out["accounts"][0]["status"], "available")


if __name__ == "__main__":
    unittest.main()