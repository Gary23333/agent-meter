import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from agent_meter.collector import SnapshotService, collect
from agent_meter.model import SourceError
from agent_meter.server import load_or_create_token, make_server
from agent_meter.web_sources import (collect_qoder_web, collect_trae, collect_workbuddy, normalize_qoder_web,
                                     normalize_trae, normalize_workbuddy, validate_sessions)
from tests.test_service import sample

NOW = datetime(2026, 10, 9, 3, 0, tzinfo=timezone.utc).timestamp()
QODER = {"totalQuota": {"quotaSummary": {"usedValue": 1200, "limitValue": 2000, "remainingValue": 800,
                                         "usagePercentage": 60, "unit": "credits"}},
         "nextResetAt": 1792034493000}
WORKBUDDY = {"code": 0, "data": {"SubscriptionPackageName": "Pro", "Packages": [
    {"CapacityUnit": "credits", "CycleTotalCapacity": "500", "CycleRemainCapacity": "120.5", "CycleFrozenCapacity": "10"},
    {"CapacityUnit": "credits", "CycleTotalCapacity": "100", "CycleRemainCapacity": "100"},
    {"CapacityUnit": "requests", "CycleTotalCapacity": "9", "CycleRemainCapacity": "9"}]}}
TRAE = {"user_entitlement_pack_list": [
    {"entitlement_base_info": {"quota": {"credits_limit": 600}}, "usage": {"credits_amount": 150}},
    {"entitlement_base_info": {"quota": {"credits_limit": 400}}, "usage": {}},
    {"entitlement_base_info": {"quota": {"solo_enabled": True}}},
    {"entitlement_base_info": {"quota": {"credits_limit": 0}}, "usage": {"credits_amount": 0}}]}


class ParserTests(unittest.TestCase):
    def test_qoder_web(self):
        out = normalize_qoder_web(QODER, NOW)
        q = out["metrics"]["quota"]["value"][0]
        self.assertEqual((q["remaining_percent"], q["limit"]), (40, 2000))
        self.assertEqual(q["resets_at"]["display"], "2026-10-15T11:21:33+08:00")
        self.assertEqual(out["metrics"]["credits"]["value"][0]["remaining"], "800")
        past = normalize_qoder_web(dict(QODER, nextResetAt=NOW * 1000 - 86400000), NOW)
        self.assertIsNone(past["metrics"]["quota"]["value"][0]["resets_at"])
        self.assertIsNone(past["metrics"]["reset_time"]["value"])
        self.assertIn("reported_reset_at_in_past", past["diagnostics"])
        # snake_case and computed percentage
        snake = {"total_quota": {"quota_summary": {"used_value": 5, "limit_value": 10}}}
        self.assertEqual(normalize_qoder_web(snake, NOW)["metrics"]["quota"]["value"][0]["remaining_percent"], 50)
        for bad in [{}, {"totalQuota": {"quotaSummary": {"usedValue": -1, "limitValue": 1}}}, []]:
            with self.assertRaises(SourceError):
                normalize_qoder_web(bad, NOW)

    def test_workbuddy_sums_only_credit_packages(self):
        out = normalize_workbuddy(WORKBUDDY, NOW)
        credits = out["metrics"]["credits"]["value"]
        self.assertEqual((credits["balance"], credits["total"], credits["frozen"]), ("220.5", "600.0", "10.0"))
        self.assertAlmostEqual(out["metrics"]["quota"]["value"][0]["remaining_percent"], 36.75)
        self.assertEqual(out["subscription"], {"plan": "Pro"})
        with self.assertRaises(SourceError):
            normalize_workbuddy({"code": 10001, "data": {}}, NOW)
        empty = normalize_workbuddy({"code": 0, "data": {"Packages": []}}, NOW)
        self.assertIsNone(empty["metrics"]["credits"]["value"])

    def test_trae_skips_feature_and_zero_packs(self):
        out = normalize_trae(TRAE, NOW, "PRIVATE_JWT")
        self.assertEqual(out["metrics"]["credits"]["value"]["balance"], "850.0")
        self.assertEqual(out["metrics"]["credits"]["value"]["packs"], 2)
        self.assertEqual(out["metrics"]["quota"]["value"][0]["remaining_percent"], 85)
        self.assertNotIn("PRIVATE_JWT", json.dumps(out))
        with self.assertRaises(SourceError):
            normalize_trae({"user_entitlement_pack_list": [{"usage": {"credits_amount": 1}}]}, NOW)


class RequestTests(unittest.TestCase):
    def test_missing_session_is_not_connected(self):
        for fn in (collect_qoder_web, collect_workbuddy, collect_trae):
            with self.assertRaises(SourceError) as ctx:
                fn(None, NOW)
            self.assertEqual(ctx.exception.code, "web_session_missing")

    def test_request_shapes(self):
        with patch("agent_meter.web_sources.get_json", return_value=QODER) as get:
            collect_qoder_web({"cookie": "a=1", "user_agent": "UA"}, NOW)
        self.assertEqual(get.call_args.args[0], "https://qoder.com.cn/api/v2/me/usages/big_model_credits")
        self.assertEqual(get.call_args.kwargs["headers"]["Cookie"], "a=1")
        with patch("agent_meter.web_sources.post_json", return_value=WORKBUDDY) as post:
            collect_workbuddy({"cookie": "b=2", "user_agent": "UA-WB"}, NOW)
        self.assertEqual(post.call_args.args[:2], ("https://www.workbuddy.cn/billing/meter/get-user-resource-summary", {}))
        self.assertEqual(post.call_args.kwargs["headers"]["User-Agent"], "UA-WB")
        with patch("agent_meter.web_sources.post_json", return_value=TRAE) as post:
            collect_trae({"token": "Cloud-IDE-JWT abc"}, NOW)
        headers = post.call_args.kwargs["headers"]
        self.assertEqual((headers["Authorization"], headers["X-User-Region"]), ("Cloud-IDE-JWT abc", "CN"))

    def test_session_validation(self):
        self.assertEqual(validate_sessions({"qoder": {"cookie": "x"}, "trae_cn": None}), {"qoder": [{"cookie": "x"}]})
        two = validate_sessions({"qoder": [{"cookie": "a", "label": "主号"}, {"cookie": "b", "label": "小号"}]})
        self.assertEqual([s["label"] for s in two["qoder"]], ["主号", "小号"])
        for bad in [[], {"evil": {}}, {"qoder": {"token": "x"}}, {"qoder": {"cookie": "a\r\nX: y"}},
                    {"qoder": {"cookie": 3}}, {"qoder": {"cookie": "x" * 20000}},
                    {"qoder": []}, {"qoder": [{"cookie": "x"}] * 6}, {"qoder": {"cookie": "x", "label": "L" * 41}}]:
            with self.assertRaises(ValueError):
                validate_sessions(bad)

    def test_qoder_web_replaces_sdk_and_sessions_stay_out_of_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = {"runtime_dir": tmp, "app_roots": [], "web_sessions": {"qoder": {"cookie": "PRIVATE_COOKIE"}},
                      "disabled_sources": ["ccswitch", "codex", "claude", "kimi", "minimax_code", "dreamina",
                                           "minimax_design", "deepseek_api", "workbuddy", "trae_cn"]}
            with patch("agent_meter.collector.collect_qoder") as sdk, \
                    patch("agent_meter.web_sources.get_json", return_value=QODER):
                snap = collect(config, now=NOW)
            sdk.assert_not_called()
            qoder = next(s for s in snap["sources"] if s["id"] == "qoder")
            self.assertEqual(qoder["diagnostics"]["transport"], "qoder_cn_web_session")
            self.assertNotIn("PRIVATE_COOKIE", json.dumps(snap))


class MultiAccountTests(unittest.TestCase):
    def test_each_account_is_its_own_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = {"runtime_dir": tmp, "app_roots": [],
                      "web_sessions": {"workbuddy": [{"cookie": "A", "label": "主号"}, {"cookie": "B", "label": "小号"}]},
                      "disabled_sources": ["ccswitch", "codex", "claude", "kimi", "qoder", "minimax_code", "dreamina",
                                           "minimax_design", "deepseek_api", "trae_cn"]}
            other = json.loads(json.dumps(WORKBUDDY))
            other["data"]["Packages"] = [{"CapacityUnit": "credits", "CycleTotalCapacity": "50", "CycleRemainCapacity": "5"}]
            def fake(url, body, timeout, headers):
                return WORKBUDDY if headers["Cookie"] == "A" else other
            with patch("agent_meter.web_sources.post_json", side_effect=fake):
                snap = collect(config, now=NOW)
            wb = {s["id"]: s for s in snap["sources"] if s["id"].startswith("workbuddy")}
            self.assertEqual(set(wb), {"workbuddy", "workbuddy#2"})
            self.assertEqual(wb["workbuddy"]["account_label"], "主号")
            self.assertEqual(wb["workbuddy#2"]["account_label"], "小号")
            self.assertEqual(wb["workbuddy#2"]["metrics"]["credits"]["value"]["balance"], "5.0")
            # Coverage still attributes the WorkBuddy app to the first account only.
            self.assertNotIn('"A"', json.dumps(snap))

    def test_failed_extra_account_keeps_its_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = {"runtime_dir": tmp, "app_roots": [],
                      "web_sessions": {"trae_cn": [{"token": "ok"}, {"token": "expired", "label": "旧号"}]},
                      "disabled_sources": ["ccswitch", "codex", "claude", "kimi", "qoder", "minimax_code", "dreamina",
                                           "minimax_design", "deepseek_api", "workbuddy"]}
            def fake(url, body, timeout, headers):
                if headers["Authorization"].endswith("expired"):
                    raise SourceError("not_authenticated")
                return TRAE
            with patch("agent_meter.web_sources.post_json", side_effect=fake):
                snap = collect(config, now=NOW)
            ids = {s["id"]: s["status"] for s in snap["sources"] if s["id"].startswith("trae")}
            self.assertEqual(ids, {"trae_cn": "available", "trae_cn#2": "not_connected"})


class DreaminaWebOnlyTests(unittest.TestCase):
    def test_cli_not_run_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = {"runtime_dir": tmp, "app_roots": [], "dreamina_binary": "/fake/dreamina",
                      "disabled_sources": ["ccswitch", "codex", "claude", "kimi", "qoder", "minimax_code",
                                           "minimax_design", "deepseek_api", "workbuddy", "trae_cn"]}
            with patch("agent_meter.collector.collect_dreamina") as cli:
                snap = collect(config, now=NOW)
            cli.assert_not_called()
            src = next(s for s in snap["sources"] if s["id"] == "dreamina")
            self.assertEqual((src["status"], src["diagnostics"]["reason"]), ("not_connected", "web_session_missing"))
            self.assertFalse(any(r["application"]["name"] == "即梦 CLI" for r in snap["coverage"]))


class AppSettingsTests(unittest.TestCase):
    ALL = ["ccswitch", "codex", "claude", "kimi", "qoder", "minimax_code", "dreamina", "minimax_design",
           "deepseek_api", "workbuddy", "trae_cn"]

    def test_app_api_key_reaches_deepseek(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = {"runtime_dir": tmp, "app_roots": [], "web_sessions": {"deepseek_api": [{"api_key": "sk-PRIVATE"}]},
                      "disabled_sources": [x for x in self.ALL if x != "deepseek_api"]}
            balance = {"balance_infos": [{"currency": "CNY", "total_balance": "12.5", "granted_balance": "0",
                                          "topped_up_balance": "12.5"}]}
            with patch("agent_meter.deepseek.get_json", return_value=balance) as get:
                snap = collect(config, now=NOW)
            self.assertEqual(get.call_args.args[1], "sk-PRIVATE")
            ds = next(s for s in snap["sources"] if s["id"] == "deepseek_api")
            self.assertEqual(ds["metrics"]["credits"]["value"][0]["total"], "12.5")
            self.assertNotIn("sk-PRIVATE", json.dumps(snap))

    def test_user_switch_skips_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = {"runtime_dir": tmp, "app_roots": [], "preferences": {"disabled_sources": ["claude"]},
                      "disabled_sources": [x for x in self.ALL if x != "claude"]}
            with patch("agent_meter.collector.collect_claude") as claude:
                snap = collect(config, now=NOW)
            claude.assert_not_called()
            src = next(s for s in snap["sources"] if s["id"] == "claude")
            self.assertEqual((src["status"], src["diagnostics"]["reason"]), ("not_connected", "disabled_by_user"))


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.token = load_or_create_token(Path(self.tmp.name) / "api.token")
        self.seen = []
        self.service = SnapshotService({"runtime_dir": self.tmp.name},
                                       lambda config, now: (self.seen.append(dict(config.get("web_sessions") or {})), sample(now))[1])
        self.server = make_server(self.service, self.token, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:" + str(self.server.server_address[1])

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.tmp.cleanup()

    def put(self, body, auth=True, **headers):
        headers.setdefault("Content-Type", "application/json")
        if auth:
            headers["Authorization"] = "Bearer " + self.token
        req = urllib.request.Request(self.url + "/v1/web-sessions", data=body, headers=headers, method="PUT")
        return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=3)

    def test_sessions_accepted_in_memory_and_not_echoed(self):
        body = json.dumps({"workbuddy": {"cookie": "PRIVATE_COOKIE", "user_agent": "UA"}}).encode()
        with self.put(body) as r:
            text = r.read().decode()
        self.assertEqual(json.loads(text), {"providers": ["workbuddy"]})
        self.assertNotIn("PRIVATE_COOKIE", text)
        self.service.get()
        self.assertEqual(self.seen[-1]["workbuddy"][0]["cookie"], "PRIVATE_COOKIE")
        snapshot_file = Path(self.tmp.name) / "snapshot.json"
        self.assertNotIn("PRIVATE_COOKIE", snapshot_file.read_text())

    def test_preferences(self):
        def put(body):
            req = urllib.request.Request(self.url + "/v1/preferences", data=json.dumps(body).encode(), method="PUT",
                                         headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.token})
            return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=3)
        with put({"disabled_sources": ["claude"]}) as r:
            self.assertEqual(json.loads(r.read()), {"disabled_sources": ["claude"]})
        self.service.get()
        self.assertEqual(self.service.config["preferences"], {"disabled_sources": ["claude"]})
        for bad in [{"disabled_sources": ["ccswitch"]}, {"disabled_sources": "claude"}, {"other": []}]:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                put(bad)
            self.assertEqual(ctx.exception.code, 400)

    def test_rejections(self):
        cases = [(b"{}", {"auth": False}, 401), (b"{}", {"Origin": "https://evil.example"}, 403),
                 (b"{\"evil\": {}}", {}, 400), (b"not json", {}, 400), (b"{}", {"Content-Type": "text/plain"}, 400)]
        for body, opts, code in cases:
            auth = opts.pop("auth", True)
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.put(body, auth=auth, **opts)
            self.assertEqual(ctx.exception.code, code)


if __name__ == "__main__":
    unittest.main()
