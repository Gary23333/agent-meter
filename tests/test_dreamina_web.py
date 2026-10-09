import json
import unittest
from datetime import datetime, timezone

from agent_meter.dreamina import normalize_dreamina
from agent_meter.dreamina_web import merge_dreamina, validate_observations
from agent_meter.model import failed_source

NOW = int(datetime(2026, 10, 9, 7, 0, tzinfo=timezone.utc).timestamp())
CLI = normalize_dreamina({"total_credit": 6086, "user_id": 1234567890, "vip_level": "maestro"}, NOW)
KEY = CLI["account_key"]


def observation(**over):
    obs = {"account_key": KEY, "observed_at": NOW - 60,
           "credit": {"gift": 120, "purchase": 0, "vip": 5966,
                      "details": [{"kind": "vip", "balance": 5966, "expires_at": NOW + 11 * 86400, "level": "maestro"},
                                  {"kind": "gift", "balance": 120, "expires_at": NOW + 2 * 86400}]},
           "subscription": {"level": "maestro", "end_time": NOW + 200 * 86400, "next_renewal_time": NOW + 200 * 86400,
                            "is_cancel_subscribe": False, "cycle_unit": "month", "subscribe_cycle": 12}}
    obs.update(over)
    return obs


class DreaminaWebTests(unittest.TestCase):
    def merged(self, obs, sources=None):
        clean = validate_observations({"dreamina": obs})
        return merge_dreamina(sources if sources is not None else [CLI], clean, NOW)

    def test_failed_first_login_keeps_its_place(self):
        # Web-only setup (CLI off): account 1's page gave nothing, account 2 read fine.
        off = failed_source("dreamina", "creative_account", NOW, "web_session_missing", "not_connected")
        other = "b" * 24
        out = self.merged([{"observed_at": NOW, "failed": True}, observation(account_key=other, label="小号")], [off])
        self.assertEqual([(s["id"], s["status"], s.get("account_label")) for s in out],
                         [("dreamina", "not_connected", None), ("dreamina#2", "available", "小号")])
        self.assertEqual(out[0]["diagnostics"]["reason"], "dreamina_web_no_data")

    def test_failed_observation_cannot_carry_data(self):
        with self.assertRaises(ValueError):
            validate_observations({"dreamina": [observation(failed=True)]})
        with self.assertRaises(ValueError):
            validate_observations({"dreamina": [{"observed_at": NOW, "failed": False}]})

    def test_two_web_logins_two_cards(self):
        off = failed_source("dreamina", "creative_account", NOW, "web_session_missing", "not_connected")
        out = self.merged([observation(), observation(account_key="c" * 24)], [off])
        self.assertEqual([s["id"] for s in out], ["dreamina", "dreamina#2"])

    def test_same_account_enriches_cli_source(self):
        out = self.merged([observation()])
        self.assertEqual(len(out), 1)
        s = out[0]
        credits = s["metrics"]["credits"]["value"]
        self.assertEqual(credits["balance"], "6086")          # CLI total stays authoritative
        self.assertEqual(credits["split"], {"vip": "5966", "gift": "120", "purchase": "0"})
        self.assertEqual([b["type"] for b in credits["buckets"]], ["vip", "gift"])
        self.assertEqual(s["metrics"]["renewal_time"]["value"]["date"], "2027-04-27")
        self.assertTrue(s["subscription"]["auto_renew"])
        self.assertEqual(s["subscription"]["ends_on"], "2027-04-27")

    def test_no_renewal_and_cancelled(self):
        sub = dict(observation()["subscription"], next_renewal_time=0, is_cancel_subscribe=True)
        s = self.merged([observation(subscription=sub)])[0]
        self.assertIsNone(s["metrics"]["renewal_time"]["value"])
        self.assertEqual(s["metrics"]["renewal_time"]["reason"], "dreamina_subscription_cancelled")
        self.assertFalse(s["subscription"]["auto_renew"])

    def test_other_account_becomes_its_own_source(self):
        out = self.merged([observation(), observation(account_key="b" * 24, label="小号")])
        self.assertEqual([s["id"] for s in out], ["dreamina", "dreamina#2"])
        self.assertEqual(out[1]["account_label"], "小号")
        self.assertEqual(out[1]["metrics"]["credits"]["value"]["balance"], "6086")
        unlabeled = self.merged([observation(), observation(account_key="c" * 24)])
        self.assertEqual(unlabeled[1]["account_label"], "账号 2")

    def test_web_only_ids_follow_login_order(self):
        missing = failed_source("dreamina", "creative_account", NOW, "web_session_missing", "not_connected")
        out = self.merged([observation(account_key="a" * 24, label="主号"), observation(account_key="b" * 24)], [missing])
        self.assertEqual([(s["id"], s.get("account_label")) for s in out], [("dreamina", "主号"), ("dreamina#2", "账号 2")])

    def test_web_only_when_cli_failed(self):
        failed = failed_source("dreamina", "creative_account", NOW, "dreamina_not_authenticated", "not_connected")
        s = self.merged([observation()], [failed])[0]
        self.assertEqual(s["status"], "available")
        self.assertEqual(s["metrics"]["credits"]["value"]["balance"], "6086")

    def test_old_observation_is_stale(self):
        s = self.merged([observation(observed_at=NOW - 7 * 3600)], [failed_source("dreamina", "creative_account", NOW, "x")])[0]
        self.assertEqual(s["metrics"]["credits"]["status"], "stale")

    def test_validation_rejects_unexpected_fields(self):
        bad = [{"dreamina": [observation(uid="123")]}, {"other": []},
               {"dreamina": [observation(account_key="UPPER" * 5)]},
               {"dreamina": [observation(credit={"gift": -1, "purchase": 0, "vip": 0})]},
               {"dreamina": [observation(subscription={"level": "x", "token": "secret"})]},
               {"dreamina": [observation(observed_at=0)]}]
        for payload in bad:
            with self.assertRaises(ValueError):
                validate_observations(payload)
        self.assertNotIn("1234567890", json.dumps(self.merged([observation()])))


if __name__ == "__main__":
    unittest.main()
