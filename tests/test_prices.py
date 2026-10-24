"""Price table, cost estimates and the DeepSeek web-usage collector."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from agent_meter.deepseek import collect_deepseek, normalize_web_usage
from agent_meter.model import metric, source
from agent_meter.prices import DEFAULTS_USD, PriceTable, estimate_source_cost, load_prices, save_prices

NOW = int(datetime(2026, 10, 9, 4, 0, tzinfo=timezone.utc).timestamp())


class PriceTableTests(unittest.TestCase):
    def test_matching_and_cny_conversion(self):
        with tempfile.TemporaryDirectory() as tmp:
            table = load_prices(tmp)
            self.assertEqual(table.currency, "USD")
            self.assertEqual(table.match("builtin:bigmodel-coding-plan/GLM-5.3-Flash"), "glm-5.3-flash")
            # Longest pattern wins over the shorter glm-5.3.
            self.assertEqual(table.match("glm-5.3"), "glm-5.3")
            self.assertEqual(table.match("kimi-code/k3-256k"), "k3")
            # Coding-plan-only models have no per-token list price.
            self.assertIsNone(table.match("kimi-code/kimi-for-coding"))
            saved = save_prices(tmp, "CNY", {"kimi-for-coding": {"input": 1, "output": 2}})
            self.assertEqual(saved["currency"], "CNY")
            cny = load_prices(tmp)
            self.assertEqual(cny.currency, "CNY")
            self.assertEqual(cny.match("kimi-code/kimi-for-coding"), "kimi-for-coding")
            self.assertIn("k3", cny.converted)          # FX fallback flagged
            self.assertNotIn("glm-5.3-flash", cny.converted)  # published CNY price
            # A user edit removes the converted flag.
            save_prices(tmp, "CNY", {"k3": {"input": 20, "output": 100}})
            self.assertNotIn("k3", load_prices(tmp).converted)

    def test_estimate_partial_unmatched_and_no_breakdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            table = load_prices(tmp)
            tokens = metric({"periods": {"all": {"groups": [
                {"model": "builtin:bigmodel-coding-plan/GLM-5.3-Flash", "fresh_input": 1_000_000,
                 "output": 1_000_000, "cache_read": 2_000_000, "cache_write": 0},
                {"model": "kimi-code/kimi-for-coding", "fresh_input": 100, "output": 100,
                 "cache_read": 0, "cache_write": 0},
            ]}}})
            cost = estimate_source_cost(tokens, table)
            # flash: 1M*0.15 + 2M*0.03 + 1M*0.50 = 0.71
            self.assertEqual(cost["value"]["periods"]["all"]["amount"], "0.71")
            # Per-model amounts add up to the period amount.
            self.assertEqual(cost["value"]["periods"]["all"]["models"],
                             {"builtin:bigmodel-coding-plan/GLM-5.3-Flash": "0.71"})
            self.assertEqual(cost["status"], "partial")
            self.assertEqual(cost["value"]["periods"]["all"]["unmatched_models"],
                             ["kimi-code/kimi-for-coding"])
            # Groups without a component breakdown (archived totals) stay unpriced.
            totals_only = metric({"periods": {"all": {"groups": [{"model": "kimi-code/k3", "total_tokens": 5}]}}})
            self.assertIsNone(estimate_source_cost(totals_only, table))

    def test_model_name_normalization(self):
        from agent_meter.prices import normalize_model
        with tempfile.TemporaryDirectory() as tmp:
            table = load_prices(tmp)
            # Vendor prefix is dropped: only the id after the last "/" is priced.
            self.assertEqual(normalize_model("account:bigmodel-individual-coding-plan/GLM-5.3"),
                             "glm-5-3")
            self.assertEqual(normalize_model("kimi-code/k3"), "k3")
            self.assertEqual(normalize_model("custom_provider:provider-48cad9/mimo-v2.5-pro"),
                             "mimo-v2-5-pro")
            # "-" and "." are the same separator: WorkBuddy writes glm-5-3-flash
            # for the model the price table lists as glm-5.3-flash.
            self.assertEqual(table.match("glm-5-3-flash"), "glm-5.3-flash")
            self.assertEqual(table.match("account:bigmodel-start-plan/GLM-5.3-Flash"), "glm-5.3-flash")
            self.assertEqual(table.match("GLM-5.3.Flash"), "glm-5.3-flash")
            # The user's own pattern wins over a default on the same key.
            save_prices(tmp, "USD", {"GLM-5.3-Flash": {"input": 9, "output": 9}})
            self.assertEqual(load_prices(tmp).match("glm-5-3-flash"), "GLM-5.3-Flash")
            # Unification must not invent matches: v4.1-flash is not v4-flash,
            # and a "-free" tier is not the priced model.
            self.assertEqual(table.match("deepseek-v4.1-flash"), "deepseek-v4.1-flash")
            self.assertEqual(table.match("deepseek-v4-flash"), "deepseek-v4-flash")
            self.assertIsNone(table.match("mimo-v2.5"))
            self.assertIsNone(table.match("x-preview-f-free"))
            # 2026-10-15 survey additions: Hunyuan/Step/MiMo publish CNY list
            # prices only, so the USD table carries them as FX conversions
            # (flagged), the same rule USD-only models get in CNY tables.
            self.assertEqual(table.match("hy4-preview"), "hy4-preview")
            self.assertIn("hy4-preview", table.converted)
            self.assertEqual(table.match("step-5-preview"), "step-5-preview")
            cny = PriceTable("CNY", {}, set())
            self.assertEqual(cny.match("hy4-preview"), "hy4-preview")
            self.assertEqual(cny.match("hy3"), "hy3")
            self.assertEqual(cny.match("step-5-preview"), "step-5-preview")
            self.assertEqual(cny.match("mimo-v2.6-flash"), "mimo-v2.6-flash")
            self.assertNotIn("hy4-preview", cny.converted)   # official CNY price
            # USD-published additions match in both currencies.
            self.assertEqual(table.match("claude-opus-4-8"), "claude-opus-4-8")
            self.assertEqual(table.match("claude-fable-5-1"), "claude-fable-5-1")
            self.assertEqual(table.match("MiniMax-M2.7"), "minimax-m2.7")
            # M3.1 Flash has official list prices in both currencies, and the
            # longer pattern wins over the older minimax-m3 substring.
            self.assertEqual(table.match("MiniMax-M3.1-Flash"), "minimax-m3.1-flash")
            self.assertEqual(table.match("minimax/MiniMax-M3.1-Flash-Preview"), "minimax-m3.1-flash")
            self.assertEqual(cny.match("MiniMax-M3.1-Flash"), "minimax-m3.1-flash")
            self.assertNotIn("minimax-m3.1-flash", cny.converted)
            self.assertNotIn("minimax-m3.1-flash", table.converted)
            self.assertEqual(cny.match("claude-fable-5-1"), "claude-fable-5-1")

    def test_preview_model_binding_and_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            save_prices(tmp, "USD", {}, {"kimi-k3.1-pro-preview": "kimi-k3.1-pro"})
            table = load_prices(tmp)
            self.assertEqual(table.match("kimi-code/kimi-k3.1-pro-preview"), "kimi-k3.1-pro")
            self.assertEqual(table.binding_for("kimi-code/kimi-k3.1-pro-preview"), "kimi-k3.1-pro")
            tokens = metric({"periods": {"all": {"groups": [
                {"model": "kimi-k3.1-pro-preview", "fresh_input": 1_000_000,
                 "cache_read": 1_000_000, "cache_write": 0, "output": 1_000_000}
            ]}}})
            cost = estimate_source_cost(tokens, table)
            self.assertEqual(cost["status"], "available")
            self.assertEqual(cost["value"]["periods"]["all"]["amount"], "12.2")
            self.assertEqual(cost["value"]["bound_models"],
                             {"kimi-k3.1-pro-preview": "kimi-k3.1-pro"})
            # Legacy saves retain bindings instead of silently deleting them.
            save_prices(tmp, "USD", {"custom": {"input": 1, "output": 2}})
            self.assertIn("kimi-k3-1-pro-preview", load_prices(tmp).aliases)

    def test_latest_builtin_models(self):
        table = PriceTable("USD", {}, set())
        self.assertEqual(table.match("gpt-6.1-sol-2026-09-29"), "gpt-6.1-sol")
        self.assertEqual(table.match("claude-sonnet-5-5"), "claude-sonnet-5-5")
        self.assertEqual(table.match("claude-haiku-5-5"), "claude-haiku-5-5")
        self.assertEqual(table.match("kimi-k3.1-pro"), "kimi-k3.1-pro")
        self.assertEqual(table.models["gpt-6.1-sol"], (2.0, 0.1, 2.5, 10.0))
        self.assertEqual(table.models["claude-sonnet-5-5"], (2, 0.1, 2.5, 10))

    def test_collector_attaches_estimates(self):
        from agent_meter.collector import collect
        with tempfile.TemporaryDirectory() as tmp:
            def fake_zcode(*a, **kw):
                return metric({"periods": {"all": {"totals": {"requests": 1}, "groups": [
                    {"model": "builtin:x/GLM-5.3-Flash", "fresh_input": 2_000_000, "output": 0,
                     "cache_read": 0, "cache_write": 0}]}}})
            with patch("agent_meter.collector.zcode_tokens_metric", side_effect=fake_zcode), \
                    patch("agent_meter.collector.collect_gemini_sessions",
                          side_effect=__import__("agent_meter.model", fromlist=["SourceError"]).SourceError("gemini_chats_not_found")), \
                    patch("agent_meter.collector.collect_antigravity_sessions",
                          side_effect=__import__("agent_meter.model", fromlist=["SourceError"]).SourceError("agy_conversations_not_found")), \
                    patch("agent_meter.collector.collect_opencode_tokens",
                          side_effect=__import__("agent_meter.model", fromlist=["SourceError"]).SourceError("opencode_db_not_found")):
                snap = collect({"runtime_dir": tmp, "app_roots": [], "disabled_sources": [
                    "ccswitch", "codex", "claude", "kimi", "qoder", "minimax_code", "deepseek_api",
                    "dreamina", "minimax_design", "workbuddy", "trae_cn", "gemini", "antigravity", "opencode"]}, now=NOW)
            zc = next(s for s in snap["sources"] if s["id"] == "zcode")
            self.assertEqual(zc["metrics"]["cost"]["status"], "available")
            self.assertEqual(zc["metrics"]["cost"]["value"]["periods"]["all"]["amount"], "0.30")


def web_payloads():
    amount = {"data": {"biz_data": {"series": [{"api_key": "sk-1", "model": "deepseek-v4-pro", "buckets": [
        {"time": 1791312000 - 0, "usage": {"PROMPT_TOKEN": 1000000, "PROMPT_CACHE_HIT_TOKEN": 2000000,
                                           "PROMPT_CACHE_MISS_TOKEN": 0, "RESPONSE_TOKEN": 500000, "REQUEST": 3}},
        {"time": 1791312000 - 86400, "usage": {"PROMPT_TOKEN": 10, "REQUEST": 1}}]}]}}}
    cost = {"data": {"biz_data": {"data": [
        {"currency": "USD", "series": [{"buckets": [{"time": 1791312000, "cost": 99}]}]},
        {"currency": "CNY", "series": [{"buckets": [{"time": 1791312000, "cost": 4.32},
                                                    {"time": 1791312000 - 86400, "cost": 0.01}]}]}]}}}
    return amount, cost


class DeepSeekWebTests(unittest.TestCase):
    def test_normalize_prefers_account_currency(self):
        amount, cost = web_payloads()
        usage = normalize_web_usage(amount, cost, NOW)
        self.assertEqual(usage["currency"], "CNY")     # CNY bucket preferred over the first USD group
        self.assertEqual(usage["total_amount"], "4.33")
        self.assertEqual(usage["total_tokens"], 3500010)
        self.assertEqual(len(usage["daily"]), 2)
        by_date = {d["date"]: d for d in usage["daily"]}
        main = max(by_date, key=lambda d: by_date[d]["tokens"])
        self.assertEqual(by_date[main]["amount"], "4.32")

    def test_collect_attaches_usage_without_breaking_balance(self):
        amount, cost = web_payloads()
        balance = {"balance_infos": [{"currency": "CNY", "total_balance": "12.5",
                                      "granted_balance": "0", "topped_up_balance": "12.5"}]}
        calls = []
        def fake(url, token=None, timeout=15):
            calls.append(url)
            if url.endswith("/user/balance"): return balance
            return amount if "amount" in url else cost
        with patch("agent_meter.deepseek.get_json", side_effect=fake):
            out = collect_deepseek(NOW, key="sk-x", user_token="PRIVATE_TOKEN")
        self.assertEqual(len(calls), 3)
        self.assertTrue(all("PRIVATE_TOKEN" not in json.dumps(c) for c in [out]))
        self.assertEqual(out["metrics"]["credits"]["value"][0]["total"], "12.5")
        self.assertEqual(out["metrics"]["cost"]["value"]["total_amount"], "4.33")
        self.assertEqual(out["diagnostics"]["usage_transport"], "platform_web_session")
        # Without a web token the source keeps balance-only behaviour.
        with patch("agent_meter.deepseek.get_json", return_value=balance) as get:
            out = collect_deepseek(NOW, key="sk-x")
        self.assertEqual(out["metrics"]["cost"]["value"], None)
        self.assertEqual(out["metrics"]["cost"]["status"], "not_provided")
        # Web failures degrade to a reason, never failing the balance.
        def failing(url, token=None, timeout=15):
            if url.endswith("/user/balance"): return balance
            raise __import__("agent_meter.model", fromlist=["SourceError"]).SourceError("not_authenticated")
        with patch("agent_meter.deepseek.get_json", side_effect=failing):
            out = collect_deepseek(NOW, key="sk-x", user_token="t")
        self.assertEqual(out["metrics"]["credits"]["status"], "available")
        self.assertEqual(out["metrics"]["cost"]["reason"], "not_authenticated")


if __name__ == "__main__":
    unittest.main()
