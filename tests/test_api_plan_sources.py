import unittest
from unittest import mock

from agent_meter import mimo, volcengine, zcode
from agent_meter.collector import collect, safe_collect
from agent_meter.model import SourceError
from agent_meter.web_sources import validate_sessions

NOW = 1791532800  # 2026-10-09 08:00 UTC


def zcode_payload():
    # Shape of the 2026-10-09 read-only probe (docs/research), values synthetic.
    return {"code": 200, "success": True, "data": {"level": "pro", "limits": [
        {"type": "CREDIT_LIMIT", "unit": 3, "number": 5, "usage": 2000, "currentValue": 0, "remaining": 2000, "percentage": 0},
        {"type": "CREDIT_LIMIT", "unit": 6, "number": 1, "usage": 10000, "currentValue": 579, "remaining": 9420,
         "percentage": 5, "nextResetTime": 1792002472974},
        {"type": "TIME_LIMIT", "unit": 5, "number": 1, "usage": 1000, "currentValue": 20, "remaining": 980, "percentage": 2},
        {"type": "UNKNOWN_LIMIT", "usage": 1},
    ]}}


class ZCodeTests(unittest.TestCase):
    def test_windows_keep_service_values(self):
        rows, plan = zcode.normalize_quota(zcode_payload())
        self.assertEqual(plan, "pro")
        five, week, mcp = rows
        self.assertEqual(five["window_minutes"], 300)
        self.assertIsNone(five["resets_at"])  # not returned, not invented
        self.assertEqual(week["window_minutes"], 10080)
        self.assertEqual((week["used"], week["limit"], week["remaining"]), (579, 10000, 9420))
        self.assertAlmostEqual(week["remaining_percent"], 94.2)
        self.assertEqual(week["provider_percentage"], 5)
        self.assertAlmostEqual(week["resets_at"]["epoch_seconds"], 1792002472.974)
        self.assertEqual(mcp["bucket"], "mcp")
        self.assertNotIn("window_minutes", mcp)  # 1-minute marker is not the real window

    def test_errors_are_not_empty_quota(self):
        with self.assertRaises(SourceError) as e:
            zcode.normalize_quota({"code": 1001, "success": False, "msg": "token expired"})
        self.assertEqual(e.exception.code, "not_authenticated")
        with self.assertRaises(SourceError):
            zcode.normalize_quota({"code": 200, "data": {}})

    def test_collect_without_key_is_not_connected(self):
        out = safe_collect("zcode", "account", NOW, lambda: zcode.collect_zcode(None, NOW))
        self.assertEqual(out["status"], "not_connected")

    def test_collect_sends_key_only_to_bigmodel(self):
        with mock.patch.object(zcode, "get_json", return_value=zcode_payload()) as get:
            out = zcode.collect_zcode({"api_key": "secret-key"}, NOW)
        url, token = get.call_args.args[:2]
        self.assertEqual(url, "https://open.bigmodel.cn/api/monitor/usage/quota/limit")
        self.assertEqual(token, "secret-key")
        self.assertNotIn("secret-key", repr(out))
        self.assertEqual(out["metrics"]["reset_cards"]["status"], "not_connected")
        self.assertEqual(out["subscription"]["plan"], "GLM Coding Pro")

    def test_console_token_replayed_only_to_its_allowlisted_host(self):
        with mock.patch.object(zcode, "get_json", return_value=zcode_payload()) as get:
            out = zcode.collect_zcode({"token": "Bearer console-jwt", "origin": "https://bigmodel.cn"}, NOW)
        self.assertEqual(get.call_args.args[0], "https://bigmodel.cn/api/monitor/usage/quota/limit")
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer console-jwt")
        self.assertEqual(out["diagnostics"]["transport"], "bigmodel_console_session")
        with self.assertRaises(SourceError):
            zcode.collect_zcode({"token": "t", "origin": "https://evil.example"}, NOW)


class MimoTests(unittest.TestCase):
    session = {"cookie": "api-platform_serviceToken=tok; userId=42; other_site=leak; api-platform_ph=p",
               "user_agent": "UA"}

    def test_only_console_cookies_are_forwarded(self):
        header, user = mimo.console_cookie(self.session["cookie"])
        self.assertEqual(user, "42")
        self.assertNotIn("other_site", header)
        with self.assertRaises(SourceError):
            mimo.console_cookie("userId=42")

    def test_balance_keeps_money_and_negative(self):
        row = mimo.normalize_balance({"code": 0, "data": {"balance": "-1.50", "currency": "cny",
                                                          "cashBalance": "0", "giftBalance": 3.5}})
        self.assertEqual((row["unit"], row["balance"], row["granted"], row["cash"]), ("CNY", "-1.50", "3.5", "0"))
        with self.assertRaises(SourceError):
            mimo.normalize_balance({"code": 0, "data": {"currency": "CNY"}})
        with self.assertRaises(SourceError) as e:
            mimo.normalize_balance({"code": 401, "message": "login"})
        self.assertEqual(e.exception.code, "mimo_not_authenticated")

    def test_token_plan_and_no_plan(self):
        detail = {"code": 0, "data": {"planCode": "standard", "planStatus": "active", "currentPeriodEnd": 1793000000000}}
        usage = {"code": 0, "data": {"monthUsage": {"items": [{"name": "month_total_token", "used": 250, "limit": 1000}]}}}
        plan, quota = mimo.normalize_plan(detail, usage)
        self.assertEqual(plan["plan"], "Token Plan Standard")
        self.assertEqual((quota["bucket"], quota["remaining_percent"]), ("monthTotal", 75))
        self.assertEqual(mimo.normalize_plan({"code": 0, "data": {"planCode": "none"}}, usage), (None, None))

    def test_usage_spellings_and_shape_diagnostics(self):
        detail = {"code": 0, "data": {"planCode": "pro", "planStatus": "active"}}
        for usage in ({"code": 0, "data": {"monthUsage": {"used": 30, "limit": 120}}},
                      {"code": 0, "data": {"usage": {"items": [{"name": "total", "usedAmount": "30", "totalAmount": "120"}]}}},
                      {"code": 0, "data": {"tokenUsage": [{"name": "month", "used": 30, "quota": 120}]}}):
            self.assertEqual(mimo.normalize_plan(detail, usage)[1]["remaining_percent"], 75, usage)
        answers = {"/balance": {"code": 0, "data": {"balance": "1", "currency": "CNY"}},
                   "/tokenPlan/detail": detail,
                   "/tokenPlan/usage": {"code": 0, "data": {"weird": [{"secret": "v", "n": 3}]}}}
        with mock.patch.object(mimo, "get_json", side_effect=lambda url, **kw: answers[url[len(mimo.API):]]):
            out = mimo.collect_mimo(self.session, NOW)
        self.assertEqual(out["metrics"]["quota"]["reason"], "mimo_token_plan_usage_unrecognized")
        self.assertEqual(out["diagnostics"]["token_plan_usage_shape"]["data"]["weird"], [1, {"secret": "str", "n": "int"}])
        self.assertNotIn("'v'", repr(out["diagnostics"]))

    def test_plan_end_formats(self):
        usage = {"code": 0, "data": {"monthUsage": {"used": 1, "limit": 4}}}
        for raw, expected in (("2026-11-09 00:00:00", 1794153600), ("2026-11-09T00:00:00", 1794153600),
                              ("2026-11-09", 1794153600), ("1794153600000", 1794153600),
                              ("2026-11-08T16:00:00Z", 1794153600)):
            plan, quota = mimo.normalize_plan({"code": 0, "data": {"planCode": "lite", "currentPeriodEnd": raw}}, usage)
            self.assertEqual(plan["ends_at"]["epoch_seconds"], expected, raw)
        plan, quota = mimo.normalize_plan({"code": 0, "data": {"planCode": "lite", "currentPeriodEnd": "下月"}}, usage)
        self.assertIsNone(plan["ends_at"])
        self.assertEqual(quota["remaining_percent"], 75)

    def test_collect_pay_as_you_go_account(self):
        answers = {"/balance": {"code": 0, "data": {"balance": "12.30", "currency": "CNY"}},
                   "/tokenPlan/detail": {"code": 0, "data": {"planCode": "default"}},
                   "/tokenPlan/usage": {"code": 0, "data": {}}}
        with mock.patch.object(mimo, "get_json", side_effect=lambda url, **kw: answers[url[len(mimo.API):]]) as get:
            out = mimo.collect_mimo(self.session, NOW)
        self.assertEqual(out["metrics"]["credits"]["value"][0]["balance"], "12.30")
        self.assertEqual(out["metrics"]["quota"]["status"], "not_provided")
        self.assertEqual(out["subscription"]["plan"], "按量付费")
        sent = get.call_args.kwargs["headers"]["Cookie"]
        self.assertNotIn("other_site", sent)

    def test_expired_login_redirect_is_not_connected(self):
        with mock.patch.object(mimo, "get_json", side_effect=SourceError("redirect_rejected")):
            out = safe_collect("mimo", "api_account", NOW, lambda: mimo.collect_mimo(self.session, NOW))
        self.assertEqual((out["status"], out["diagnostics"]["reason"]), ("not_connected", "mimo_not_authenticated"))


class VolcengineTests(unittest.TestCase):
    def test_signature_matches_reference_implementation(self):
        # Same inputs through token-monitor c62544e signVolcengineRequest.
        headers = volcengine.sign(volcengine.URL, b"", "AKLTexample", "c2VjcmV0", NOW)
        self.assertEqual(headers["X-Date"], "20261009T080000Z")
        self.assertTrue(headers["Authorization"].endswith(
            "Signature=e1d401c07b805029b93ce0e6d2bae0028145bb4335e9f45543390460de451639"))

    def test_levels_map_to_windows(self):
        rows, plan, status = volcengine.normalize_usage({"Result": {"Status": "Running", "PlanName": "PLAN_TIER_LITE",
            "QuotaUsage": [{"Level": "session", "Percent": 12.5, "ResetTimestamp": 1791550800},
                           {"Level": "weekly", "Percent": 40, "ResetTimestamp": 1792000000000},
                           {"Level": "monthly", "Percent": 3},
                           {"Level": "daily-unknown", "Percent": 1}]}})
        self.assertEqual([r["window_minutes"] for r in rows], [300, 10080, 43200])
        self.assertEqual(rows[0]["remaining_percent"], 87.5)
        self.assertEqual(rows[1]["resets_at"]["epoch_seconds"], 1792000000)
        self.assertIsNone(rows[2]["resets_at"])
        self.assertEqual((plan, status), ("Lite", "Running"))

    def test_auth_error_and_missing_plan(self):
        with self.assertRaises(SourceError) as e:
            volcengine.normalize_usage({"ResponseMetadata": {"Error": {"Code": "SignatureDoesNotMatch"}}})
        self.assertEqual(e.exception.code, "not_authenticated")
        with self.assertRaises(SourceError) as e:
            volcengine.normalize_usage({"Result": {}})
        self.assertEqual(e.exception.code, "volcengine_no_coding_plan")

    def test_collect_posts_signed_empty_body(self):
        payload = {"Result": {"QuotaUsage": [{"Level": "session", "Percent": 0}]}}
        with mock.patch.object(volcengine, "get_json", return_value=payload) as get:
            out = volcengine.collect_volcengine({"access_key_id": "AKLTx", "secret_access_key": "sk"}, NOW)
        self.assertEqual(get.call_args.kwargs["body"], b"")
        self.assertIn("HMAC-SHA256", get.call_args.kwargs["headers"]["Authorization"])
        self.assertNotIn("'sk'", repr(out))
        self.assertEqual(out["metrics"]["quota"]["value"][0]["remaining_percent"], 100)


    def test_unknown_values_do_not_fail_the_card(self):
        rows, _, _ = volcengine.normalize_usage({"Result": {"QuotaUsage": [
            {"Level": "session", "Percent": "8.5", "ResetTimestamp": -1},
            {"Level": "weekly", "Percent": -1, "ResetTimestamp": 0},
            {"Level": "monthly", "Percent": 2, "ResetTimestamp": "1792000000"}]}})
        self.assertEqual([(r["bucket"], r["used_percent"]) for r in rows], [("session", 8.5), ("monthly", 2)])
        self.assertIsNone(rows[0]["resets_at"])
        self.assertEqual(rows[1]["resets_at"]["epoch_seconds"], 1792000000)

    def test_unparseable_console_answer_keeps_value_free_shape(self):
        with mock.patch.object(volcengine, "get_json", return_value={"Result": {"QuotaUsage": "x", "Secret": "v"}}):
            out = volcengine.collect_volcengine({"cookie": "csrfToken=abcdefgh"}, NOW)
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["diagnostics"]["usage_shape"], {"Result": {"QuotaUsage": "str", "Secret": "str"}})
        self.assertNotIn("'v'", repr(out["diagnostics"]))

    def test_ark_api_key_in_access_key_field_is_explained(self):
        out = safe_collect("volcengine", "account", NOW, lambda: volcengine.collect_volcengine(
            {"access_key_id": "6f1c2d3e-ark-api-key", "secret_access_key": "x"}, NOW))
        self.assertEqual((out["status"], out["diagnostics"]["reason"]), ("not_connected", "volcengine_ark_key_not_supported"))

    def test_console_session_replays_only_the_allowlisted_action(self):
        payload = {"Result": {"QuotaUsage": [{"Level": "weekly", "Percent": 10}]}}
        session = {"cookie": "csrfToken=abc123xyz; session=s", "user_agent": "UA",
                   "usage_url": "https://console.volcengine.com/api/top/ark/cn-beijing/2024-01-01/GetCodingPlanUsage"}
        with mock.patch.object(volcengine, "get_json", return_value=payload) as get:
            out = volcengine.collect_volcengine(session, NOW)
        url, kw = get.call_args.args[0], get.call_args.kwargs
        self.assertEqual(url, session["usage_url"])
        self.assertEqual(kw["headers"]["x-csrf-token"], "abc123xyz")  # falls back to the csrfToken cookie
        self.assertEqual(kw["body"], {})
        self.assertEqual(out["diagnostics"]["transport"], "volcengine_console_session")
        for bad in ("https://evil.example/api/top/ark/cn-beijing/2024-01-01/GetCodingPlanUsage",
                    "https://console.volcengine.com/api/top/iam/cn-beijing/2024-01-01/DeleteUser"):
            with self.assertRaises(SourceError):
                volcengine.collect_volcengine(dict(session, usage_url=bad), NOW)

    def test_expired_console_login_is_not_connected(self):
        with mock.patch.object(volcengine, "get_json", side_effect=SourceError("redirect_rejected")):
            out = safe_collect("volcengine", "account", NOW, lambda: volcengine.collect_volcengine(
                {"cookie": "csrfToken=abcdefgh"}, NOW))
        self.assertEqual((out["status"], out["diagnostics"]["reason"]), ("not_connected", "volcengine_not_authenticated"))


class WiringTests(unittest.TestCase):
    def test_session_fields_are_allow_listed(self):
        validate_sessions({"volcengine": {"access_key_id": "a", "secret_access_key": "b"},
                           "zcode": [{"api_key": "k"}, {"token": "t", "origin": "https://bigmodel.cn", "label": "小号"}],
                           "mimo": [{"cookie": "x=y", "label": "主号"}]})
        with self.assertRaises(ValueError):
            validate_sessions({"volcengine": {"password": "x"}})

    def test_unconnected_sources_report_not_connected(self):
        with mock.patch("agent_meter.collector.discover", return_value=[]):
            snap = collect({"disabled_sources": ["ccswitch", "codex", "claude", "kimi", "qoder", "workbuddy", "trae_cn",
                                                 "minimax_code", "dreamina", "minimax_design", "deepseek_api"],
                            "runtime_dir": self.tmp}, now=NOW)
        by_id = {s["id"]: s for s in snap["sources"]}
        for sid in ("zcode", "mimo", "volcengine"):
            self.assertEqual(by_id[sid]["status"], "not_connected", sid)

    def setUp(self):
        import tempfile
        self._dir = tempfile.TemporaryDirectory()
        self.tmp = self._dir.name

    def tearDown(self):
        self._dir.cleanup()


if __name__ == "__main__":
    unittest.main()
