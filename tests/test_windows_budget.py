"""Windows 预算：仅使用虚构账本和临时目录。"""
import json
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from windows.budget import CONFIG_NAME, HISTORY_NAME, budget_from_compact
from agent_meter.budget import compute_budget


NOW = datetime(2026, 11, 9, 12, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()


def settings(directory, **changes):
    data = {"schema": 1, "enabled": True, "alerts_enabled": False, "daily_cny": "2", "weekly_cny": "10", "anomaly_multiplier": "2"}
    data.update(changes)
    (Path(directory) / CONFIG_NAME).write_text(json.dumps(data), encoding="utf-8")


def sample(partial=False):
    return {"observed_at": NOW, "history": {"Codex": {"status": "available", "value": {"periods": {
        "today": {"totals": {"total_tokens": 100}}, "30d": {"totals": {"total_tokens": 3000}}}},
        "estimates": {"today": {"amount_usd": "0.5", "partial": partial}, "30d": {"amount_usd": "3", "partial": False}}}}}


class WindowsBudgetTests(unittest.TestCase):
    def test_disabled_does_not_create_history(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(budget_from_compact(sample(), directory)["status"], "disabled")
            self.assertFalse((Path(directory) / HISTORY_NAME).exists())

    def test_cny_estimate_and_natural_week(self):
        with tempfile.TemporaryDirectory() as directory:
            settings(directory)
            out = budget_from_compact(sample(), directory)
            self.assertEqual(out["daily"]["spent_cny"], "3.625000")
            self.assertTrue(out["daily"]["exceeded"])
            self.assertEqual(out["weekly"]["spent_cny"], "3.625000")
            self.assertTrue(out["weekly"]["complete"])
            self.assertEqual(out["fx_rate"], "7.25")
            self.assertFalse(out["alerts_enabled"])
            self.assertEqual(out["basis"], "local_api_equivalent_estimate")
            self.assertTrue((Path(directory) / HISTORY_NAME).exists())

    def test_incomplete_amount_is_lower_bound_and_no_anomaly(self):
        with tempfile.TemporaryDirectory() as directory:
            settings(directory, alerts_enabled=True)
            data = sample(partial=True)
            data["history"]["Unknown"] = {"status": "available", "value": {"periods": {"today": {"totals": {"total_tokens": 10}}}}}
            out = budget_from_compact(data, directory)
            self.assertEqual(out["daily"]["spent_cny"], "3.625000")
            self.assertTrue(out["daily"]["partial"])
            self.assertFalse(out["anomaly"]["triggered"])
            self.assertEqual(out["anomaly"]["reason"], "incomplete_data")
            self.assertNotIn("anomaly", [event["kind"] for event in out["events"]])

    def test_incomplete_baseline_cannot_trigger_anomaly(self):
        with tempfile.TemporaryDirectory() as directory:
            settings(directory, alerts_enabled=True)
            data = sample()
            data["history"]["Codex"]["estimates"]["30d"]["partial"] = True
            out = budget_from_compact(data, directory)
            self.assertFalse(out["anomaly"]["triggered"])
            self.assertEqual(out["anomaly"]["reason"], "incomplete_data")
        with tempfile.TemporaryDirectory() as directory:
            settings(directory, alerts_enabled=True)
            today = datetime.fromtimestamp(NOW, ZoneInfo("Asia/Shanghai")).date()
            days = {(today - timedelta(days=i)).isoformat(): {"spent_cny": "1", "apps": {}, "models": {}, "partial": i == 1} for i in range(1, 8)}
            (Path(directory) / HISTORY_NAME).write_text(json.dumps({"schema": 1, "days": days}), encoding="utf-8")
            out = budget_from_compact(sample(), directory)
            self.assertFalse(out["anomaly"]["triggered"])
            self.assertEqual(out["anomaly"]["reason"], "incomplete_data")

    def test_invalid_config_and_history_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / CONFIG_NAME
            path.write_text("invalid", encoding="utf-8")
            self.assertEqual(budget_from_compact(sample(), directory)["status"], "invalid")
            self.assertEqual(path.read_text(encoding="utf-8"), "invalid")
            settings(directory)
            history = Path(directory) / HISTORY_NAME
            history.write_text("invalid", encoding="utf-8")
            self.assertEqual(budget_from_compact(sample(), directory)["reason"], "budget_history_invalid")
            self.assertEqual(history.read_text(encoding="utf-8"), "invalid")

    def test_settings_change_during_calculation_discards_result(self):
        with tempfile.TemporaryDirectory() as directory:
            settings(directory)
            def change_settings(*args):
                result = compute_budget(*args)
                settings(directory, enabled=False)
                return result
            with patch("windows.budget.compute_budget", side_effect=change_settings):
                self.assertEqual(budget_from_compact(sample(), directory)["status"], "loading")
            self.assertFalse((Path(directory) / HISTORY_NAME).exists())

    def test_missing_days_and_invalid_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            settings(directory)
            data = sample()
            data["observed_at"] = datetime(2026, 11, 11, 12, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()
            out = budget_from_compact(data, directory)
            self.assertFalse(out["weekly"]["complete"])
            self.assertEqual(len(out["weekly"]["days_missing"]), 2)
            data["observed_at"] = float("nan")
            self.assertEqual(budget_from_compact(data, directory)["reason"], "budget_timestamp_invalid")


if __name__ == "__main__":
    unittest.main()
