import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

from agent_meter import doubao
from agent_meter.collector import safe_collect
from agent_meter.model import SourceError
from agent_meter.server import make_server
from agent_meter.web_sources import validate_sessions

NOW = 1791532800  # 2026-10-09 08:00 UTC


def summary_payload(start=1791475200000, end=1794153600000, active=True):
    return {"code": 0, "data": {
        "member_info": {"hasActiveSubscription": active},
        "current_subscription": {"merchant_user_id": "mu_100", "subscription_id": "sub_1",
                                 "end_time": 1794153600000,
                                 "display": {"name": "豆包 Pro 会员"}},
        "window_limit_section": {"window_limit_groups": [{"window_limits": [{
            "feature_group": "monthly_quota", "start_time": start, "end_time": end,
            "total_amount": "1000", "used_amount": "250", "used_percent": 25,
            "less_than_one_percent": False, "item_type": "points", "window_type": "monthly"}]}]},
        "incentive_quota_section": {},
        "enterprise_window_limit_section": {}}}


def balance_payload():
    return {"code": 0, "data": {
        "total_remaining_amount": "800",
        "summaries": [{"category": "points", "remaining_amount": "750", "title": "积分"}],
        "groups": []}}


def query_answers(summary=None, balance=None):
    answers = {doubao.SUMMARY_PATH: summary if summary is not None else summary_payload(),
               doubao.BALANCE_PATH: balance if balance is not None else balance_payload()}

    def fake(url, body, **kwargs):
        return answers[url[len(doubao.BASE):].split("?", 1)[0]]
    return fake


class DoubaoCollectTests(unittest.TestCase):
    session = {"cookie": "sessionid=abc; sid_guard=def", "user_agent": "UA"}

    def test_month_window_and_balance(self):
        with mock.patch.object(doubao, "post_json", side_effect=query_answers()) as post:
            out = doubao.collect_doubao(self.session, NOW)
        row = out["metrics"]["quota"]["value"][0]
        self.assertEqual(row["bucket"], "monthly_quota")
        self.assertEqual((row["used"], row["limit"]), ("250", "1000"))
        self.assertEqual((row["used_percent"], row["remaining_percent"]), (25, 75))
        self.assertEqual(row["unit"], "doubao_points")
        self.assertEqual(row["window_minutes"], 44640)
        self.assertEqual(row["resets_at"]["epoch_seconds"], 1794153600)
        self.assertIs(row["less_than_one_percent"], False)
        self.assertEqual(out["metrics"]["credits"]["value"],
                         [{"bucket": "积分", "unit": "doubao_points", "balance": "750"}])
        self.assertEqual(out["metrics"]["reset_time"]["value"][0]["bucket"], "monthly_quota")
        # 豆包不按 token 计量：tokens 只能是空值，不能凭空产出。
        self.assertIsNone(out["metrics"]["tokens"]["value"])
        self.assertEqual(out["subscription"], {"plan": "豆包 Pro 会员", "ends_on": "2026-11-09"})
        self.assertEqual(out["diagnostics"]["transport"], "doubao_web_session")
        self.assertEqual(out["diagnostics"]["product_line"], "membership")
        url, body = post.call_args_list[0].args[:2]
        self.assertEqual(url, doubao.BASE + doubao.SUMMARY_PATH + "?aid=582478")
        self.assertEqual(body, {"product_line": "membership"})
        headers = post.call_args_list[0].kwargs["headers"]
        self.assertEqual(headers["Agw-Js-Conv"], "str")
        self.assertEqual(headers["Referer"], doubao.BASE + "/member/quota-management")
        self.assertEqual(headers["Cookie"], self.session["cookie"])

    def test_zero_start_does_not_invent_window(self):
        with mock.patch.object(doubao, "post_json", side_effect=query_answers(summary_payload(start=0))):
            out = doubao.collect_doubao(self.session, NOW)
        self.assertNotIn("window_minutes", out["metrics"]["quota"]["value"][0])

    def test_group_feature_and_thousands_separator(self):
        # 真实响应：feature_group 在 group 上，金额带千分位。
        payload = summary_payload()
        group = payload["data"]["window_limit_section"]["window_limit_groups"][0]
        group["feature_group"] = "monthly_quota"
        group["window_limits"][0]["feature_group"] = None
        group["window_limits"][0]["total_amount"] = "18,000"
        group["window_limits"][0]["used_amount"] = "425"
        with mock.patch.object(doubao, "post_json", side_effect=query_answers(summary=payload)):
            out = doubao.collect_doubao(self.session, NOW)
        row = out["metrics"]["quota"]["value"][0]
        self.assertEqual((row["bucket"], row["used"], row["limit"]), ("monthly_quota", "425", "18000"))

    def test_no_windows_reports_reason(self):
        payload = summary_payload()
        payload["data"]["window_limit_section"]["window_limit_groups"] = []
        with mock.patch.object(doubao, "post_json", side_effect=query_answers(summary=payload)):
            out = doubao.collect_doubao(self.session, NOW)
        self.assertEqual(out["metrics"]["quota"]["status"], "not_provided")
        self.assertEqual(out["metrics"]["quota"]["reason"], "doubao_no_quota_windows")

    def test_balance_total_fallback(self):
        with mock.patch.object(doubao, "post_json", side_effect=query_answers(
                balance={"code": 0, "data": {"total_remaining_amount": "800"}})):
            out = doubao.collect_doubao(self.session, NOW)
        self.assertEqual(out["metrics"]["credits"]["value"],
                         [{"bucket": "doubao", "unit": "doubao_points", "balance": "800"}])

    def test_balance_failure_keeps_quota(self):
        def fake(url, body, **kwargs):
            if doubao.BALANCE_PATH in url:
                raise SourceError("http_500")
            return summary_payload()
        with mock.patch.object(doubao, "post_json", side_effect=fake):
            out = doubao.collect_doubao(self.session, NOW)
        self.assertEqual(out["metrics"]["quota"]["status"], "available")
        self.assertEqual((out["metrics"]["credits"]["status"], out["metrics"]["credits"]["reason"]),
                         ("error", "http_500"))

    def test_no_active_subscription(self):
        with self.assertRaises(SourceError) as e:
            doubao.normalize_summary(summary_payload(active=False))
        self.assertEqual(e.exception.code, "doubao_no_active_subscription")

    def test_enterprise_window_is_a_fallback(self):
        payload = summary_payload()
        personal = payload["data"]["window_limit_section"]
        enterprise = payload["data"]["enterprise_window_limit_section"]
        enterprise["window_limit_groups"] = personal["window_limit_groups"]
        personal["window_limit_groups"] = []
        parsed = doubao.normalize_summary(payload)
        self.assertEqual(parsed["section"], "enterprise_window_limit_section")
        self.assertEqual(parsed["rows"][0]["used_percent"], 25)

    def test_missing_cookie_is_not_connected(self):
        with self.assertRaises(SourceError) as e:
            doubao.collect_doubao({}, NOW)
        self.assertEqual(e.exception.code, "doubao_credential_not_connected")
        out = safe_collect("doubao", "account", NOW, lambda: doubao.collect_doubao(None, NOW))
        self.assertEqual((out["status"], out["diagnostics"]["reason"]),
                         ("not_connected", "doubao_credential_not_connected"))

    def test_expired_login_maps_to_not_authenticated(self):
        with mock.patch.object(doubao, "post_json", side_effect=SourceError("not_authenticated")):
            with self.assertRaises(SourceError) as e:
                doubao.collect_doubao(self.session, NOW)
            self.assertEqual(e.exception.code, "doubao_not_authenticated")
            out = safe_collect("doubao", "account", NOW, lambda: doubao.collect_doubao(self.session, NOW))
        self.assertEqual(out["status"], "not_connected")

    def test_nonzero_code_and_unsupported_shape(self):
        with mock.patch.object(doubao, "post_json", side_effect=query_answers(summary={"code": 1001, "data": {}})):
            with self.assertRaises(SourceError) as e:
                doubao.collect_doubao(self.session, NOW)
        self.assertEqual(e.exception.code, "doubao_quota_unavailable")
        with self.assertRaises(SourceError) as e:
            doubao.normalize_summary({"code": 0, "data": {}})
        self.assertEqual(e.exception.code, "unsupported_doubao_contract")


class DoubaoSessionsTests(unittest.TestCase):
    def test_session_fields_are_allow_listed(self):
        clean = validate_sessions({"doubao": [{"cookie": "a=b", "user_agent": "UA", "label": "主号"}]})
        self.assertEqual(clean["doubao"][0]["cookie"], "a=b")
        with self.assertRaises(ValueError):
            validate_sessions({"doubao": {"api_key": "x"}})


class DoubaoImportTests(unittest.TestCase):
    def test_missing_cookie_db(self):
        with tempfile.TemporaryDirectory() as home:
            with self.assertRaises(SourceError) as e:
                doubao.import_doubao_app_cookies({"home": home})
        self.assertEqual(e.exception.code, "doubao_app_cookies_not_found")

    def test_unreadable_cookie_db(self):
        with tempfile.TemporaryDirectory() as home:
            root = os.path.join(home, "Library/Application Support/Doubao/Default")
            os.makedirs(root)
            with open(os.path.join(root, "Cookies"), "w", encoding="utf-8") as handle:
                handle.write("not a database")
            with self.assertRaises(SourceError) as e:
                doubao.import_doubao_app_cookies({"home": home})
        self.assertEqual(e.exception.code, "doubao_app_cookies_unreadable")


class DoubaoEndpointTests(unittest.TestCase):
    """本地导入接口只回 cookie；错误码原样交给 App 显示。"""

    class Service:
        config = {}

    def setUp(self):
        self.server = make_server(self.Service(), "t" * 40, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:%d/v1/doubao/import-app-cookies" % self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def post(self, body=None):
        request = urllib.request.Request(self.url, data=body, method="POST",
                                         headers={"Authorization": "Bearer " + "t" * 40})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=5) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    def test_returns_cookie_without_echoing_it_elsewhere(self):
        with mock.patch.object(doubao, "import_doubao_app_cookies", return_value="sessionid=abc"):
            status, payload = self.post()
        self.assertEqual((status, payload), (200, {"cookie": "sessionid=abc"}))

    def test_error_code_is_returned(self):
        with mock.patch.object(doubao, "import_doubao_app_cookies",
                               side_effect=SourceError("doubao_keychain_denied")):
            status, payload = self.post()
        self.assertEqual((status, payload), (400, {"error": "doubao_keychain_denied"}))


if __name__ == "__main__":
    unittest.main()
