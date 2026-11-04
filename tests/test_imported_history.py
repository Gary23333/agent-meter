"""Hermetic tests for the project-owned imported-history source."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from agent_meter.imported_history import collect_imported_history, load_store
from agent_meter.model import SourceError
from agent_meter.prices import PriceTable, estimate_source_cost

NOW = int(datetime(2026, 10, 9, 4, 0, tzinfo=timezone.utc).timestamp())
ZONE = ZoneInfo("Asia/Shanghai")


def epoch(day, hour, minute=0):
    return int(datetime(2026, 10, day, hour, minute, tzinfo=ZONE).timestamp())


def write_store(path, detail=None, daily=None, schema=1):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": schema, "imported_at": NOW,
                                "detail": detail or [], "daily": daily or [],
                                "apps": {"codex": {"days": 2}}}))
    return path


class ImportedHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "imported-history.json"

    def test_detail_rows_split_peak_and_offpeak(self):
        write_store(self.path, detail=[
            ["codex", "deepseek-v4-pro", epoch(9, 10), 100, 10, 50, 0],
            ["codex", "deepseek-v4-pro", epoch(9, 8), 200, 20, 60, 0],
        ])
        value = collect_imported_history(self.path, NOW, ZONE)["metrics"]["tokens"]["value"]
        today = value["periods"]["today"]
        self.assertEqual(today["totals"]["requests"], 2)
        self.assertEqual(today["totals"]["total_tokens"], 440)
        self.assertEqual((today["totals"]["peak"]["total_tokens"],
                          today["totals"]["offpeak"]["total_tokens"]), (160, 280))
        group = today["groups"][0]
        self.assertEqual(group["model"], "deepseek-v4-pro")
        self.assertEqual(group["peak"]["total_tokens"], 160)
        self.assertEqual(group["offpeak"]["total_tokens"], 280)
        self.assertEqual(value["daily_buckets"], [{"date": "2026-10-09", "tokens": 440}])
        self.assertEqual(value["coverage"], "imported_history_store")

    def test_mixed_groups_preserve_known_and_undated_usage(self):
        write_store(self.path,
                    detail=[["codex", "gpt-6-astra", epoch(9, 10), 100, 10, 50, 0],
                            ["codex", "gpt-6-astra", epoch(9, 8), 200, 20, 60, 0]],
                    daily=[["claude", "claude-opus-5", "2026-10-01", 5, 1000, 100, 500, 0],
                           ["codex", "gpt-6-astra", "2026-10-03", 2, 300, 30, 100, 0]])
        value = collect_imported_history(self.path, NOW, ZONE)["metrics"]["tokens"]["value"]
        self.assertEqual(value["periods"]["today"]["groups"][0]["total_tokens"], 440)
        self.assertIn("peak", value["periods"]["today"]["groups"][0])
        seven = value["periods"]["7d"]
        group = next(g for g in seven["groups"] if g["model"] == "gpt-6-astra")
        self.assertEqual(group["total_tokens"], 870)
        self.assertEqual([group[k]["total_tokens"] for k in ("peak", "offpeak", "unsplit")], [160, 280, 430])
        self.assertEqual(seven["mixed_split_models"], ["gpt-6-astra"])
        claude = next(g for g in value["periods"]["30d"]["groups"] if g["model"] == "claude-opus-5")
        self.assertNotIn("peak", claude)
        self.assertEqual(value["daily_buckets"],
                         [{"date": "2026-10-01", "tokens": 1600},
                          {"date": "2026-10-03", "tokens": 430},
                          {"date": "2026-10-09", "tokens": 440}])

    def test_price_table_bills_split_part_at_peak_multiplier(self):
        write_store(self.path, detail=[
            ["codex", "deepseek-v4-pro", epoch(9, 10), 100, 10, 50, 0],
            ["codex", "deepseek-v4-pro", epoch(9, 8), 200, 20, 60, 0],
        ])
        tokens = collect_imported_history(self.path, NOW, ZONE)["metrics"]["tokens"]
        cost = estimate_source_cost(tokens, PriceTable("USD", {}, set()))
        today = cost["value"]["periods"]["today"]
        self.assertEqual(today["peak_amount"], "0.0001738")
        self.assertEqual(today["offpeak_amount"], "0.00017292")
        self.assertEqual(today["unsplit_models"], [])

    def test_missing_and_malformed_store(self):
        with self.assertRaises(SourceError) as ctx:
            load_store(self.path)
        self.assertEqual(ctx.exception.code, "history_store_not_found")
        write_store(self.path, schema=2)
        with self.assertRaises(SourceError) as ctx:
            load_store(self.path)
        self.assertEqual(ctx.exception.code, "unsupported_history_schema")
        write_store(self.path, detail=[["codex", "m", 1, -1, 0, 0, 0]])
        with self.assertRaises(SourceError) as ctx:
            load_store(self.path)
        self.assertEqual(ctx.exception.code, "history_store_read_failed")

    def test_empty_store_is_available_with_zero_periods(self):
        write_store(self.path)
        out = collect_imported_history(self.path, NOW, ZONE)
        self.assertEqual((out["id"], out["scope"]), ("imported_history", "local_imported_history"))
        self.assertEqual(out["metrics"]["tokens"]["status"], "available")
        self.assertEqual(out["metrics"]["tokens"]["value"]["periods"]["all"]["totals"]["total_tokens"], 0)
