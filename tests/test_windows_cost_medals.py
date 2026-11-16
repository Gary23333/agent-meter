import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from agent_meter.prices import PriceTable
from windows.cost_medals import daily_cost_metric
from windows.backend import local_medals

NOW = int(datetime(2026, 11, 15, 12, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp())


def fixture():
    return {"status": "available", "value": {"periods": {"all": {"totals": {"total_tokens": 1_000_000}}},
        "daily_buckets": [{"date": "2026-11-15", "tokens": 1_000_000}],
        "daily_models": [{"date": "2026-11-15", "model": "synthetic-model", "fresh_input": 1_000_000,
                          "output": 0, "reasoning": 0, "cache_read": 0, "cache_write": 0, "total_tokens": 1_000_000}]}}


class DailyCostMedalTests(unittest.TestCase):
    def test_uses_complete_model_rows_and_local_prices(self):
        table = PriceTable("USD", {"synthetic-model": (3, 0, 0, 0)}, set())
        result = daily_cost_metric(fixture(), NOW, table)
        self.assertEqual(result["value"]["daily"], [{"date": "2026-11-15", "amount": "3.0000"}])
        self.assertEqual(result["value"]["unit"], "USD")

    def test_unknown_or_incomplete_data_never_becomes_zero_cost(self):
        table = PriceTable("USD", {"synthetic-model": (3, 0, 0, 0)}, set())
        for change in ("unknown", "missing", "mismatch", "unclassified", "partial", "future"):
            item = fixture()
            if change == "unknown": item["value"]["daily_models"][0]["model"] = "unpriced-model"
            if change == "missing": item["value"]["daily_models"] = None
            if change == "mismatch": item["value"]["daily_models"][0]["total_tokens"] = 999
            if change == "unclassified": item["value"]["daily_models"][0]["unclassified"] = 1
            if change == "partial": item["status"] = "partial"
            if change == "future": item["value"]["daily_buckets"][0]["date"] = "2099-01-01"
            self.assertIsNone(daily_cost_metric(item, NOW, table), change)
        self.assertIsNone(daily_cost_metric(fixture(), NOW, None))

    def test_cost_medals_use_complete_local_estimate_and_fallback_rate(self):
        table = PriceTable("USD", {"synthetic-model": (20, 0, 0, 0)}, set())
        result = local_medals({"observed_at": NOW, "history": {"synthetic": fixture()}}, table)
        self.assertEqual(result["cost_status"], "available")
        medal = next(row for row in result["medals"] if row["id"] == "cost_day_100")
        self.assertEqual(medal["value"], 145)
        self.assertTrue(medal["earned"])

    def test_any_missing_price_or_source_hides_all_cost_medals(self):
        table = PriceTable("USD", {"synthetic-model": (20, 0, 0, 0)}, set())
        unknown = fixture(); unknown["value"]["daily_models"][0]["model"] = "unpriced-model"
        for history in ({"synthetic": unknown}, {"synthetic": fixture(), "failed": {"status": "error", "reason": "broken"}}):
            result = local_medals({"observed_at": NOW, "history": history}, table)
            self.assertEqual(result["cost_status"], "incomplete")
            self.assertFalse(any(row["category"].startswith("cost_") for row in result["medals"]))
