import base64
import json
import tempfile
import unittest
from unittest import mock

from agent_meter import stepfun
from agent_meter.collector import collect, safe_collect
from agent_meter.model import SourceError
from agent_meter.web_sources import validate_sessions

NOW = 1791532800  # 2026-10-09 08:00 UTC


def _jwt(claims):
    def segment(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
    # 43 signature characters, as the console's own tokens carry.
    return segment({"alg": "HS256"}) + "." + segment(claims) + "." + "s" * 43


# Oasis-Token is access-JWT + "..." + device-JWT; the console sends other
# cookies alongside it that the Dashboard RPC rejects.
OASIS = _jwt({"oasis_id": "private-account-id", "exp": 1791534600}) + "..." + \
        _jwt({"device_id": "private-device-id", "oasis_id": "private-account-id"})
COOKIE = "INGRESSCOOKIE=leak; Oasis-Webid=private-device-id; Oasis-Token=" + OASIS + "; _wafdytokenv1=leak"


def coding_plan_rate():
    return {"status": "1", "desc": "", "plan_family": "1",
            "five_hour_usage_left_rate": 0.99781543, "five_hour_usage_reset_time": "1792002472",
            "weekly_usage_left_rate": "0.42", "weekly_usage_reset_time": 1792600000}


def token_plan_rate():
    # A Token Plan reports the rolling windows as 0 — "no window configured",
    # which must not be rendered as an exhausted quota.
    return {"status": "1", "desc": "", "plan_family": "2",
            "five_hour_usage_left_rate": "0", "five_hour_usage_reset_time": "0",
            "weekly_usage_left_rate": "0", "weekly_usage_reset_time": "0",
            "plan_credit_rate_limit": {
                "subscription_credit_left_rate": 0.87, "subscription_credit_reset_time": "1794153600",
                "credit_buckets": [{"credit_total": "2000000000", "credit_residual": "1800000000",
                                    "expire_at": "0", "next_reset_at": "1794153600"}]}}


class SessionTests(unittest.TestCase):
    def test_only_oasis_token_is_forwarded(self):
        token, webid, oasis_id = stepfun.console_session(COOKIE)
        self.assertEqual(token, OASIS)
        self.assertEqual(webid, "private-device-id")
        self.assertEqual(oasis_id, "private-account-id")
        for missing in ("", "Oasis-Webid=x", "other=1; another=2"):
            with self.assertRaises(SourceError) as e:
                stepfun.console_session(missing)
            self.assertEqual(e.exception.code, "stepfun_not_authenticated")

    def test_a_single_jwt_still_yields_its_claims(self):
        token, webid, _ = stepfun.console_session("Oasis-Token=" + _jwt({"device_id": "d1"}))
        self.assertEqual((token, webid), (_jwt({"device_id": "d1"}), "d1"))

    def test_unreadable_token_keeps_the_session_without_identity(self):
        token, webid, oasis_id = stepfun.console_session("Oasis-Token=not-a-jwt")
        self.assertEqual((token, webid, oasis_id), ("not-a-jwt", None, None))


class BalanceTests(unittest.TestCase):
    def test_console_amounts_are_fen(self):
        row = stepfun.normalize_balance({"status": "1", "balance": "1500", "payment": "9900",
                                         "voucher": "2600", "credit": "0", "cost_month": "123"})
        self.assertEqual((row["unit"], row["balance"], row["cash"], row["topped_up"], row["granted"]),
                         ("CNY", "15", "99", "99", "26"))
        self.assertEqual(stepfun.normalize_balance({"status": "1", "balance": "-150"})["balance"], "-1.5")

    def test_missing_balance_is_not_zero(self):
        with self.assertRaises(SourceError) as e:
            stepfun.normalize_balance({"status": "1", "payment": "0"})
        self.assertEqual(e.exception.code, "unsupported_stepfun_balance_contract")

    def test_open_platform_amounts_are_yuan(self):
        row, kind = stepfun.normalize_account({"object": "account", "type": "prepaid", "balance": 0.0,
                                               "total_cash_balance": 0.0, "total_voucher_balance": 26.0})
        self.assertEqual((row["balance"], row["cash"], row["granted"], kind), ("0.0", "0.0", "26.0", "prepaid"))
        with self.assertRaises(SourceError):
            stepfun.normalize_account({"object": "account", "total_voucher_balance": 1})


class StepPlanTests(unittest.TestCase):
    def test_rolling_windows_keep_the_service_rates(self):
        rows, resets, metering = stepfun.normalize_rate_limit(coding_plan_rate())
        self.assertEqual(metering, "coding_plan")
        five, week = rows
        self.assertEqual((five["bucket"], five["window_minutes"]), ("limit5h", 300))
        self.assertAlmostEqual(five["remaining_percent"], 99.781543)
        self.assertAlmostEqual(week["used_percent"], 58)
        self.assertEqual(week["resets_at"]["epoch_seconds"], 1792600000)
        self.assertEqual([r["bucket"] for r in resets], ["limit5h", "limit7d"])
        # Rates only: no token counts are invented.
        self.assertNotIn("limit", five)

    def test_zero_windows_are_absent_not_exhausted(self):
        rows, resets, metering = stepfun.normalize_rate_limit(token_plan_rate())
        self.assertEqual(metering, "token_plan")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row["bucket"], row["unit"]), ("stepPlanCredits", "stepfun_credits"))
        self.assertEqual((row["used"], row["limit"]), (1800000000.0, 2000000000.0))
        self.assertAlmostEqual(row["remaining_percent"], 90)
        self.assertEqual(row["resets_at"]["epoch_seconds"], 1794153600)
        self.assertEqual(resets, [{"bucket": "stepPlanCredits", "resets_at": row["resets_at"]}])

    def test_credit_pool_without_buckets_falls_back_to_the_primary_rate(self):
        payload = token_plan_rate()
        payload["plan_credit_rate_limit"] = {"subscription_credit_left_rate": "0.5"}
        rows, _, metering = stepfun.normalize_rate_limit(payload)
        self.assertEqual(metering, "token_plan")
        self.assertEqual((rows[0]["remaining_percent"], rows[0]["unit"], rows[0]["resets_at"]), (50, "percent", None))

    def test_partial_buckets_do_not_get_summed(self):
        payload = token_plan_rate()
        payload["plan_credit_rate_limit"]["credit_buckets"] = [{"credit_total": "100", "credit_residual": "50"},
                                                               {"credit_total": "0", "credit_residual": "0"}]
        payload["plan_credit_rate_limit"]["subscription_credit_left_rate"] = 0.4
        rows, _, _ = stepfun.normalize_rate_limit(payload)
        self.assertEqual(rows[0]["remaining_percent"], 40)

    def test_pay_as_you_go_reports_no_usage(self):
        rows, resets, metering = stepfun.normalize_rate_limit(
            {"status": "1", "desc": "", "five_hour_usage_left_rate": "0", "five_hour_usage_reset_time": "0",
             "weekly_usage_left_rate": "0", "weekly_usage_reset_time": "0"})
        self.assertEqual((rows, resets, metering), ([], [], "no_usage_reported"))

    def test_expired_session_is_reported_as_unauthenticated(self):
        for payload in ({"code": "unauthenticated", "message": "auth failed: token is expired"},
                        {"code": "permission_denied"}):
            with self.assertRaises(SourceError) as e:
                stepfun.normalize_rate_limit(payload)
            self.assertEqual(e.exception.code, "stepfun_not_authenticated")
        with self.assertRaises(SourceError) as e:
            stepfun.normalize_rate_limit({"status": "0", "desc": "internal error"})
        self.assertEqual(e.exception.code, "stepfun_api_error")
        # A bare status without an explanation is not turned into a failure.
        self.assertEqual(stepfun.normalize_rate_limit({"status": "0"})[2], "no_usage_reported")

    def test_plan_name_and_expiry_day(self):
        plan = stepfun.normalize_plan_status(
            {"status": "1", "subscription": {"name": " Plus ", "expired_at": "1794153600", "auto_renew": True},
             "plan_definition": {"price": "9900"}})
        self.assertEqual(plan, {"plan": "Plus", "ends_on": "2026-11-09", "auto_renew": True})
        self.assertIsNone(stepfun.normalize_plan_status({"status": "1"}))
        self.assertIsNone(stepfun.normalize_plan_status({"status": "1", "subscription": {"name": "  "}}))


class CollectTests(unittest.TestCase):
    def _answers(self):
        return {"QueryAccountBalance": {"status": "1", "balance": "1500", "payment": "9900", "voucher": "2600"},
                "GetStepPlanStatus": {"status": "1", "subscription": {"name": "Plus", "expired_at": "1794153600",
                                                                     "auto_renew": True}},
                "QueryStepPlanRateLimit": token_plan_rate()}

    def test_console_session_reads_balance_and_step_plan(self):
        answers = self._answers()
        with mock.patch.object(stepfun, "post_json", side_effect=lambda url, body, **kw: answers[url.rsplit("/", 1)[-1]]) as post:
            out = stepfun.collect_stepfun({"cookie": COOKIE, "user_agent": "UA"}, NOW)
        url, body, kw = post.call_args.args[0], post.call_args.args[1], post.call_args.kwargs
        self.assertTrue(url.startswith("https://platform.stepfun.com/api/step.openapi.devcenter.Dashboard/"))
        self.assertEqual(kw["headers"]["Cookie"], "Oasis-Token=" + OASIS)  # the rest of the jar is dropped
        self.assertEqual(kw["headers"]["oasis-webid"], "private-device-id")
        self.assertEqual((kw["headers"]["oasis-appid"], kw["headers"]["oasis-platform"]), ("10300", "web"))
        self.assertEqual(body, {})
        self.assertEqual(out["metrics"]["credits"]["value"][0]["balance"], "15")
        self.assertEqual(out["metrics"]["quota"]["value"][0]["remaining_percent"], 90)
        self.assertEqual(out["metrics"]["reset_time"]["value"][0]["bucket"], "stepPlanCredits")
        self.assertEqual(out["metrics"]["renewal_time"]["value"]["date"], "2026-11-09")
        self.assertEqual(out["metrics"]["renewal_time"]["value"]["origin"], "provider")
        self.assertEqual(out["subscription"], {"plan": "Plus", "ends_on": "2026-11-09", "auto_renew": True})
        self.assertEqual(out["diagnostics"]["step_plan_metering"], "token_plan")
        self.assertIsNotNone(out["account_key"])
        # No cookie, token or account id may reach the snapshot.
        for secret in (OASIS, "private-account-id", "private-device-id", "leak"):
            self.assertNotIn(secret, json.dumps(out, ensure_ascii=False))

    def test_api_key_reads_balance_only(self):
        payload = {"object": "account", "type": "postpaid", "balance": 12.5,
                   "total_cash_balance": 10.0, "total_voucher_balance": 2.5}
        with mock.patch.object(stepfun, "get_json", return_value=payload) as get:
            out = stepfun.collect_stepfun({"api_key": "sk-secret"}, NOW)
        self.assertEqual(get.call_args.args[:2], ("https://api.stepfun.com/v1/accounts", "sk-secret"))
        self.assertEqual(out["metrics"]["credits"]["value"][0]["balance"], "12.5")
        self.assertEqual(out["metrics"]["quota"]["status"], "not_connected")
        self.assertEqual(out["metrics"]["quota"]["reason"], "stepfun_step_plan_needs_console_login")
        self.assertEqual(out["subscription"]["plan"], "按量付费")
        self.assertEqual(out["diagnostics"]["account_type"], "postpaid")
        self.assertNotIn("sk-secret", repr(out))

    def test_account_without_a_step_plan_says_so(self):
        answers = {"QueryAccountBalance": {"status": "1", "balance": "0"},
                   "GetStepPlanStatus": {"status": "1"},
                   "QueryStepPlanRateLimit": {"status": "1", "desc": "", "five_hour_usage_left_rate": "0",
                                              "five_hour_usage_reset_time": "0"}}
        with mock.patch.object(stepfun, "post_json", side_effect=lambda url, body, **kw: answers[url.rsplit("/", 1)[-1]]):
            out = stepfun.collect_stepfun({"cookie": COOKIE}, NOW)
        self.assertEqual(out["metrics"]["credits"]["value"][0]["balance"], "0")
        self.assertEqual(out["metrics"]["quota"]["reason"], "stepfun_no_step_plan")
        self.assertIsNone(out["metrics"]["renewal_time"]["value"])
        self.assertEqual(out["subscription"]["plan"], "按量付费")

    def test_unrecognized_plan_usage_is_not_silent(self):
        answers = {"QueryAccountBalance": {"status": "1", "balance": "0"},
                   "GetStepPlanStatus": {"status": "1", "subscription": {"name": "Plus"}},
                   "QueryStepPlanRateLimit": {"status": "1", "desc": "", "plan_credit_rate_limit": {"weird": "x"}}}
        with mock.patch.object(stepfun, "post_json", side_effect=lambda url, body, **kw: answers[url.rsplit("/", 1)[-1]]):
            out = stepfun.collect_stepfun({"cookie": COOKIE}, NOW)
        self.assertEqual(out["metrics"]["quota"]["reason"], "stepfun_step_plan_usage_unrecognized")

    def test_missing_credentials_and_expired_login(self):
        out = safe_collect("stepfun", "account", NOW, lambda: stepfun.collect_stepfun(None, NOW))
        self.assertEqual((out["status"], out["diagnostics"]["reason"]),
                         ("not_connected", "stepfun_credential_not_connected"))
        with mock.patch.object(stepfun, "post_json", side_effect=SourceError("redirect_rejected")):
            out = safe_collect("stepfun", "account", NOW, lambda: stepfun.collect_stepfun({"cookie": COOKIE}, NOW))
        self.assertEqual((out["status"], out["diagnostics"]["reason"]),
                         ("not_connected", "stepfun_not_authenticated"))

    def test_balance_survives_a_failing_plan_query(self):
        with mock.patch.object(stepfun, "post_json", side_effect=[{"status": "1", "balance": "1500"},
                                                                 SourceError("http_500"), SourceError("http_500")]):
            out = stepfun.collect_stepfun({"cookie": COOKIE}, NOW)
        self.assertEqual(out["metrics"]["credits"]["value"][0]["balance"], "15")
        self.assertEqual(out["metrics"]["quota"]["reason"], "http_500")


class WiringTests(unittest.TestCase):
    def test_session_fields_are_allow_listed(self):
        validate_sessions({"stepfun": [{"cookie": "Oasis-Token=x", "label": "主号"}, {"api_key": "sk-1"}]})
        with self.assertRaises(ValueError):
            validate_sessions({"stepfun": {"password": "x"}})

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.tmp = self._dir.name

    def tearDown(self):
        self._dir.cleanup()

    def test_unconnected_source_reports_not_connected(self):
        with mock.patch("agent_meter.collector.discover", return_value=[]):
            snap = collect({"disabled_sources": ["ccswitch", "codex", "claude", "kimi", "qoder", "workbuddy",
                                                 "trae_cn", "minimax_code", "dreamina", "minimax_design",
                                                 "deepseek_api", "mimo", "volcengine", "zcode"],
                            "runtime_dir": self.tmp}, now=NOW)
        by_id = {s["id"]: s for s in snap["sources"]}
        self.assertEqual(by_id["stepfun"]["status"], "not_connected")
        self.assertEqual(by_id["stepfun"]["scope"], "account")


if __name__ == "__main__":
    unittest.main()
