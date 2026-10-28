"""Peak/off-peak split tests: Beijing weekday 09:00-12:00 / 14:00-18:00 peak."""
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agent_meter import peak
from agent_meter.cli_sessions import _summarize
from agent_meter.kimi_tokens import summarize as kimi_summarize
from agent_meter.zcode_local import collect_zcode_local

ZONE = ZoneInfo("Asia/Shanghai")
SPLIT_FIELDS = ("requests", "fresh_input", "output", "reasoning", "cache_read", "cache_write")

MODEL_USAGE_DDL = """
CREATE TABLE model_usage (
  id text primary key, logical_request_id text, attempt_index integer default 0,
  session_id text, turn_id text, query_source text, provider_id text, model_id text,
  status text, started_at integer, input_tokens integer default 0, output_tokens integer default 0,
  reasoning_tokens integer default 0, cache_creation_input_tokens integer default 0,
  cache_read_input_tokens integer default 0)
"""


def at(day, hour, minute, second=0):
    return datetime(2026, 10, day, hour, minute, second, tzinfo=ZONE).timestamp()


class WindowTests(unittest.TestCase):
    def test_is_offpeak_boundaries(self):
        # 2026-10-05 is a Monday: peak is 09:00-12:00 and 14:00-18:00.
        self.assertTrue(peak.is_offpeak(at(5, 8, 59)))    # before the morning peak
        self.assertFalse(peak.is_offpeak(at(5, 9, 0)))    # morning peak start
        self.assertFalse(peak.is_offpeak(at(5, 11, 59)))  # still morning peak
        self.assertTrue(peak.is_offpeak(at(5, 12, 0)))    # lunch break
        self.assertTrue(peak.is_offpeak(at(5, 13, 59)))   # still lunch break
        self.assertFalse(peak.is_offpeak(at(5, 14, 0)))   # afternoon peak start
        self.assertFalse(peak.is_offpeak(at(5, 17, 59)))  # still afternoon peak
        self.assertTrue(peak.is_offpeak(at(5, 18, 0)))    # after the afternoon peak
        # 2026-10-10 / 11 are Saturday / Sunday: off-peak all day.
        self.assertTrue(peak.is_offpeak(at(10, 10, 0)))
        self.assertTrue(peak.is_offpeak(at(11, 15, 0)))
        # An explicit holiday set also counts as off-peak.
        self.assertTrue(peak.is_offpeak(at(5, 10, 0), holidays={"2026-10-05"}))

    def test_bucket_and_total(self):
        values = peak.bucket()
        peak.add(values, {"fresh_input": 10, "output": 5, "reasoning": 2,
                          "cache_read": 100, "cache_write": 1})
        self.assertEqual(values["requests"], 1)
        self.assertEqual(peak.total(values), 118)


class CliSummarizeSplitTests(unittest.TestCase):
    def test_peak_plus_offpeak_equals_totals(self):
        records = [
            (at(9, 10, 0), "m", 100, 10, 3, 200, 4),   # 10:00 → peak
            (at(9, 3, 0), "m", 50, 7, 0, 30, 1),       # 03:00 → off-peak
        ]
        period = _summarize(records, None, at(10, 0, 0), set(), ZONE, "codex")
        totals = period["totals"]
        for field in SPLIT_FIELDS:
            self.assertEqual(totals["peak"][field] + totals["offpeak"][field], totals[field], field)
        self.assertEqual(totals["peak"]["total_tokens"], 100 + 10 + 3 + 200 + 4)
        self.assertEqual(totals["offpeak"]["total_tokens"], 50 + 7 + 0 + 30 + 1)
        self.assertEqual(totals["peak"]["total_tokens"] + totals["offpeak"]["total_tokens"],
                         totals["total_tokens"])
        self.assertEqual(totals["peak"]["requests"], 1)
        group = period["groups"][0]
        for field in SPLIT_FIELDS:
            self.assertEqual(group["peak"][field] + group["offpeak"][field], group[field], field)
        self.assertEqual(group["peak"]["total_tokens"] + group["offpeak"]["total_tokens"],
                         group["total_tokens"])


class KimiSummarizeSplitTests(unittest.TestCase):
    def test_split_keeps_source_fields_only(self):
        # (epoch, model, inputOther, output, cache_read, cache_write)
        records = [(at(9, 2, 0), "kimi-code/k3", 10, 5, 100, 0),     # off-peak
                   (at(9, 15, 0), "kimi-code/k3", 1, 2, 3, 4)]       # peak
        totals = kimi_summarize(records, None, at(10, 0, 0))["totals"]
        self.assertNotIn("reasoning", totals["peak"])
        self.assertNotIn("reasoning", totals["offpeak"])
        self.assertEqual(totals["peak"]["total_tokens"], 10)
        self.assertEqual(totals["offpeak"]["total_tokens"], 115)
        for field in ("requests", "fresh_input", "output", "cache_read", "cache_write"):
            self.assertEqual(totals["peak"][field] + totals["offpeak"][field], totals[field], field)
        self.assertEqual(totals["peak"]["total_tokens"] + totals["offpeak"]["total_tokens"],
                         totals["total_tokens"])


class ZCodeCollectorSplitTests(unittest.TestCase):
    def test_collector_splits_by_request_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "db.sqlite"
            day_ms = lambda d, h, m=0: int(at(d, h, m) * 1000)
            conn = sqlite3.connect(db)
            conn.executescript(MODEL_USAGE_DDL)
            conn.executemany(
                "INSERT INTO model_usage(id,provider_id,model_id,status,started_at,attempt_index,"
                "input_tokens,output_tokens,reasoning_tokens,cache_creation_input_tokens,"
                "cache_read_input_tokens) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                [("1", "p", "m1", "completed", day_ms(9, 10), 0, 100, 5, 2, 10, 200),   # peak
                 ("2", "p", "m1", "completed", day_ms(9, 4), 0, 50, 7, 0, 0, 300)])     # off-peak
            conn.commit()
            conn.close()
            value = collect_zcode_local(db, at(9, 20, 0), ZONE)["metrics"]["tokens"]["value"]
            self.assertEqual(value["peak_split"], "request_timestamp")
            totals = value["periods"]["all"]["totals"]
            for field in SPLIT_FIELDS:
                self.assertEqual(totals["peak"][field] + totals["offpeak"][field], totals[field], field)
            self.assertEqual(totals["peak"]["total_tokens"], 317)
            self.assertEqual(totals["offpeak"]["total_tokens"], 357)
            self.assertEqual(totals["peak"]["total_tokens"] + totals["offpeak"]["total_tokens"],
                             totals["total_tokens"])
            group = value["periods"]["all"]["groups"][0]
            self.assertEqual(group["peak"]["total_tokens"], 317)
            self.assertEqual(group["offpeak"]["total_tokens"], 357)


if __name__ == "__main__":
    unittest.main()
