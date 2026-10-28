"""Hermetic tests for the MiniMax Design agent token reader.

Fixtures mirror the embedded opencode database observed on this machine
(2026-10-15): message(time_created, session_id, data JSON) with assistant
rows carrying tokens{input,output,reasoning,cache{read,write}}, plus a
standalone opencode db whose session table holds the copied session ids.
"""
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agent_meter.design_tokens import collect_design_tokens
from agent_meter.model import SourceError

ZONE = ZoneInfo("Asia/Shanghai")
NOW = int(datetime(2026, 10, 15, 2, 0, tzinfo=ZONE).timestamp())
TODAY = int(datetime(2026, 10, 15, 1, 0, tzinfo=ZONE).timestamp())
OLD = int(datetime(2026, 9, 1, 10, 0, tzinfo=ZONE).timestamp())


def assistant(when, session, tokens, model, agent):
    # The real db stores message.time_created in epoch milliseconds.
    return (when * 1000, session, json.dumps({"role": "assistant", "modelID": model, "agent": agent, "tokens": tokens}))


def design_db(path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE message(time_created INTEGER, session_id TEXT, data TEXT)")
    conn.execute("CREATE TABLE session(id TEXT PRIMARY KEY, directory TEXT)")
    return conn


def reference_db(path, ids):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE session(id TEXT PRIMARY KEY)")
    conn.executemany("INSERT INTO session VALUES(?)", [(i,) for i in ids])
    conn.commit()
    conn.close()


def fixture(tmp, copied=("s-copy",)):
    design = Path(tmp) / "hilo.db"
    reference = Path(tmp) / "standalone.db"
    reference_db(reference, copied)
    conn = design_db(design)
    # The design agent's own sessions.
    conn.execute("INSERT INTO message VALUES(?,?,?)",
                 assistant(TODAY, "s-design",
                           {"input": 100, "output": 20, "reasoning": 5, "cache": {"read": 300, "write": 10}},
                           "mimo-v2.5-pro", "media-agent"))
    conn.execute("INSERT INTO message VALUES(?,?,?)",
                 assistant(OLD, "s-design",
                           {"input": 50, "output": 8, "reasoning": 0, "cache": {"read": 70, "write": 0}},
                           "deepseek-v4-pro", "build"))
    # A copied session already owned by the standalone db: must be excluded.
    conn.execute("INSERT INTO message VALUES(?,?,?)",
                 assistant(TODAY, "s-copy",
                           {"input": 500, "output": 60, "reasoning": 2, "cache": {"read": 900, "write": 30}},
                           "mimo-v2.5-pro", "build"))
    # Non-assistant rows and a malformed token payload stay out of the sums.
    conn.execute("INSERT INTO message VALUES(?,?,?)",
                 (TODAY * 1000, "s-design", json.dumps({"role": "user"})))
    conn.execute("INSERT INTO message VALUES(?,?,?)",
                 (TODAY * 1000, "s-design", json.dumps({"role": "assistant", "tokens": {"input": -1}})))
    conn.commit()
    conn.close()
    return design, reference


class DesignTokensTests(unittest.TestCase):
    def test_tokens_agent_breakdown_and_copy_exclusion(self):
        with tempfile.TemporaryDirectory() as tmp:
            design, reference = fixture(tmp)
            out = collect_design_tokens(design, reference, NOW, ZONE)
            value = out["value"]
            self.assertEqual(value["coverage"], "minimax_design_embedded_opencode_message_db")
            self.assertEqual(value["opencode_overlap"], {"state": "checked", "excluded_sessions": 1})
            self.assertEqual(value["malformed_token_rows"], 1)
            allp = value["periods"]["all"]
            self.assertEqual(allp["totals"],
                             {"requests": 2, "fresh_input": 150, "output": 28, "reasoning": 5,
                              "cache_read": 370, "cache_write": 10, "total_tokens": 563,
                              "cache_hit_rate": 370 / 530,
                              # 10:00 peak vs 01:00 off-peak request timestamps.
                              "peak": {"requests": 1, "fresh_input": 50, "output": 8, "reasoning": 0,
                                       "cache_read": 70, "cache_write": 0, "total_tokens": 128},
                              "offpeak": {"requests": 1, "fresh_input": 100, "output": 20, "reasoning": 5,
                                          "cache_read": 300, "cache_write": 10, "total_tokens": 435}})
            # Only today's record falls in today/7d/30d; the 09-01 one is "all" only.
            for period in ("today", "7d", "30d"):
                self.assertEqual(value["periods"][period]["totals"]["requests"], 1)
                self.assertEqual(value["periods"][period]["totals"]["total_tokens"], 435)
            groups = {g["model"]: g for g in allp["groups"]}
            self.assertEqual(set(groups), {"mimo-v2.5-pro", "deepseek-v4-pro"})
            self.assertEqual(groups["mimo-v2.5-pro"]["app"], "minimax_design")
            self.assertEqual(groups["mimo-v2.5-pro"]["fresh_input"], 100)
            self.assertEqual(groups["deepseek-v4-pro"]["requests"], 1)
            agents = {g["agent"]: g["requests"] for g in allp["agent_groups"]}
            self.assertEqual(agents, {"media-agent": 1, "build": 1})
            self.assertEqual(value["daily_buckets"],
                             [{"date": "2026-09-01", "tokens": 128}, {"date": "2026-10-15", "tokens": 435}])
            again = collect_design_tokens(design, reference, NOW, ZONE)
            self.assertEqual(again["value"]["periods"]["all"]["totals"], allp["totals"])

    def test_reference_absent_counts_everything(self):
        with tempfile.TemporaryDirectory() as tmp:
            design, reference = fixture(tmp)
            reference.unlink()
            out = collect_design_tokens(design, reference, NOW, ZONE)
            value = out["value"]
            self.assertEqual(value["opencode_overlap"], {"state": "opencode_absent", "excluded_sessions": 0})
            self.assertEqual(value["periods"]["all"]["totals"]["requests"], 3)
            self.assertEqual(value["periods"]["all"]["totals"]["total_tokens"], 563 + 1492)

    def test_unreadable_reference_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            design, reference = fixture(tmp)
            reference.write_bytes(b"not a database")
            with self.assertRaises(SourceError) as ctx:
                collect_design_tokens(design, reference, NOW, ZONE)
            self.assertEqual(ctx.exception.code, "design_opencode_reference_unreadable")

    def test_missing_design_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SourceError) as ctx:
                collect_design_tokens(Path(tmp) / "none.db", Path(tmp) / "none2.db", NOW, ZONE)
            self.assertEqual(ctx.exception.code, "design_opencode_db_not_found")

    def test_schema_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            design = Path(tmp) / "hilo.db"
            reference = Path(tmp) / "standalone.db"
            reference_db(reference, [])
            conn = sqlite3.connect(design)
            conn.execute("CREATE TABLE message(time_created INTEGER, data TEXT)")
            conn.commit()
            conn.close()
            with self.assertRaises(SourceError) as ctx:
                collect_design_tokens(design, reference, NOW, ZONE)
            self.assertEqual(ctx.exception.code, "unsupported_design_opencode_schema")


if __name__ == "__main__":
    unittest.main()
