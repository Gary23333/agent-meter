import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from agent_meter.model import SourceError
from agent_meter.prices import load_prices
from agent_meter.report_periods import calendar_bounds, compute_period_report

ZONE = ZoneInfo("Asia/Shanghai")
# 2026-11-08 is a Sunday; 2026-11-04 a Wednesday, 2026-11-01 a Sunday.
NOW = datetime(2026, 11, 4, 12, 0, tzinfo=ZONE).timestamp()


def row(date, model, tokens, app=None, requests=1, **fields):
    out = {"date": date, "model": model, "total_tokens": tokens, "requests": requests,
           "fresh_input": fields.get("fresh_input", tokens), "output": fields.get("output", 0),
           "reasoning": 0, "cache_read": fields.get("cache_read", 0), "cache_write": 0}
    if app:
        out["app"] = app
    return out


def source(sid, rows=None, with_detail=True):
    value = {"periods": {"all": {"totals": {"total_tokens": 1}}}}
    if with_detail:
        value["daily_models"] = rows or []
    return {"id": sid, "metrics": {"tokens": {"status": "available", "value": value}}}


class CalendarBoundsTests(unittest.TestCase):
    def test_week_starts_monday(self):
        prev, cur, end = calendar_bounds(NOW, "week", ZONE)
        self.assertEqual(datetime.fromtimestamp(cur, ZONE).strftime("%Y-%m-%d %H:%M"), "2026-11-02 00:00")
        self.assertEqual(datetime.fromtimestamp(prev, ZONE).strftime("%Y-%m-%d"), "2026-10-26")
        self.assertEqual(end, NOW)

    def test_month_starts_first(self):
        prev, cur, end = calendar_bounds(NOW, "month", ZONE)
        self.assertEqual(datetime.fromtimestamp(cur, ZONE).strftime("%Y-%m-%d"), "2026-11-01")
        self.assertEqual(datetime.fromtimestamp(prev, ZONE).strftime("%Y-%m-%d"), "2026-10-01")

    def test_invalid_kind(self):
        with self.assertRaises(SourceError):
            calendar_bounds(NOW, "rolling7d", ZONE)


class PeriodReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.table = load_prices(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_windows_delta_and_gaps(self):
        snapshot = {"sources": [
            source("codex", [
                row("2026-10-28", "gpt-5.3-codex", 100),          # previous week
                row("2026-11-02", "gpt-5.3-codex", 150),          # current week
                row("2026-11-04", "gpt-5.3-codex", 50),
            ]),
            source("imported_history", [
                row("2026-10-29", "glm-5.3-flash", 40, app="claude"),
                row("2026-11-03", "glm-5.3-flash", 60, app="claude"),
            ]),
            source("mystery_ledger", with_detail=False),
        ]}
        report = compute_period_report(snapshot, self.table, NOW, "week", ZONE)
        self.assertEqual(report["current"]["tokens"], 260)
        self.assertEqual(report["previous"]["tokens"], 140)
        self.assertEqual(report["delta"]["tokens_pct"], round(120 / 140 * 100, 2))
        self.assertEqual(report["sources_without_daily_detail"], ["mystery_ledger"])
        self.assertEqual(report["current"]["by_app"]["codex"]["tokens"], 200)
        self.assertEqual(report["current"]["by_app"]["claude"]["tokens"], 60)
        self.assertEqual(report["top_movers"][0]["model"], "gpt-5.3-codex")
        self.assertEqual(report["basis"], "daily_rollup_base_price_no_peak_split")
        self.assertGreater(float(report["current"]["cost_cny"]), 0)   # priced models exist
        self.assertEqual(report["current"]["days_with_data"], 3)
        self.assertEqual(report["previous"]["days_with_data"], 2)

    def test_empty_previous_delta_is_null(self):
        snapshot = {"sources": [source("codex", [row("2026-11-02", "unknown-model-x", 10)])]}
        report = compute_period_report(snapshot, self.table, NOW, "week", ZONE)
        self.assertIsNone(report["delta"]["tokens_pct"])
        self.assertIsNone(report["delta"]["cost_pct"])
        self.assertIn("unknown-model-x", report["current"]["unmatched_models"])
        self.assertEqual(float(report["current"]["cost_cny"]), 0.0)

    def test_no_table_no_cost(self):
        snapshot = {"sources": [source("codex", [row("2026-11-02", "glm-5.3-flash", 10)])]}
        report = compute_period_report(snapshot, None, NOW, "week", ZONE)
        self.assertEqual(float(report["current"]["cost_cny"]), 0.0)

    def test_daily_models_match_daily_buckets(self):
        import json
        import sqlite3
        from agent_meter.mimocode_tokens import collect_mimocode_tokens
        db = Path(self.tmp.name) / "m.db"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE message (id TEXT, session_id TEXT, time_created INTEGER, data TEXT)")
        ts = int((NOW - 3600) * 1000)
        data = json.dumps({"role": "assistant", "modelID": "mimo-x-pro-preview",
                           "tokens": {"input": 10, "output": 5, "reasoning": 0,
                                      "cache": {"read": 1, "write": 0}, "total": 16}})
        conn.execute("INSERT INTO message VALUES ('a','s',?,?)", (ts, data))
        conn.commit()
        conn.close()
        value = collect_mimocode_tokens(db, NOW)["metrics"]["tokens"]["value"]
        self.assertEqual(sum(r["total_tokens"] for r in value["daily_models"]),
                         sum(b["tokens"] for b in value["daily_buckets"]))
        self.assertEqual(value["daily_models"][0]["app"], "mimo_code")


if __name__ == "__main__":
    unittest.main()