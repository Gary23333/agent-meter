"""Hermetic tests for the direct CLI session-history readers.

Fixtures mirror the real formats (validated against CC Switch imports on
2026-10-09); nothing here touches the real home directories.
"""
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from agent_meter.ccswitch import app_imported_days
from agent_meter.cli_sessions import (claude_tokens_metric, codex_tokens_metric, collect_gemini_sessions,
                                      load_claude, load_codex, load_gemini, load_mcode, mcode_tokens_metric)
from agent_meter.collector import collect
from agent_meter.model import SourceError, metric
from unittest.mock import patch
from agent_meter.model import SourceError

NOW = int(datetime(2026, 10, 9, 4, 0, tzinfo=timezone.utc).timestamp())
ZONE = ZoneInfo("Asia/Shanghai")


def ts(d, h=10, m=0):
    return datetime(2026, 10, d, h, m, tzinfo=ZONE).isoformat()


def write(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n")


def codex_event(timestamp, total, last=None):
    info = {"total_token_usage": total}
    if last is not None:
        info["last_token_usage"] = last
    return {"timestamp": timestamp, "type": "event_msg", "payload": {"type": "token_count", "info": info}}


TOTAL = lambda i, o=0, r=0, c=0, w=0: {"input_tokens": i, "output_tokens": o, "reasoning_output_tokens": r,
                                       "cached_input_tokens": c, "cache_write_input_tokens": w}


class CodexTests(unittest.TestCase):
    def dir(self, tmp):
        root = Path(tmp) / "sessions"
        write(root / "a.jsonl", [
            {"timestamp": ts(9), "type": "session_meta", "payload": {"model": "gpt-6-astra"}},
            codex_event(ts(9, 10), TOTAL(100, 10, 2, 50), TOTAL(100, 10, 2, 50)),
            codex_event(ts(9, 10, 1), TOTAL(100, 10, 2, 50)),          # streamed duplicate
            codex_event(ts(9, 11), TOTAL(260, 25, 5, 120), TOTAL(160, 15, 3, 70)),
            codex_event(ts(9, 12), TOTAL(30, 4, 0, 10), TOTAL(30, 4, 0, 10)),   # reset series
        ])
        archives = Path(tmp) / "archived"
        write(archives / "old.jsonl", [
            {"timestamp": ts(2), "type": "session_meta", "payload": {}},
            codex_event(ts(2), TOTAL(40, 5, 0, 20)),
        ])
        return root, archives

    def test_diff_of_cumulative_series(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, archives = self.dir(tmp)
            value = codex_tokens_metric(root, archives, Path(tmp) / "none.db", NOW, ZONE)["value"]
            allp = value["periods"]["all"]["totals"]
            # deltas: (100,10,2,50) + (160,15,3,70) + reset (30,4,0,10) + archive (40,5,0,20)
            self.assertEqual((allp["requests"], allp["fresh_input"], allp["output"], allp["reasoning"],
                              allp["cache_read"], allp["cache_write"]), (4, 180, 34, 5, 150, 0))
            models = {g["model"]: g for g in value["periods"]["all"]["groups"]}
            self.assertEqual(models["gpt-6-astra"]["requests"], 3)
            self.assertEqual(models["unknown"]["requests"], 1)   # archive without session_meta model
            self.assertEqual(value["ccswitch_overlap"]["state"], "ccswitch_absent")

    def test_excluded_days_and_missing_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, archives = self.dir(tmp)
            cc = self.ccswitch_db(tmp, [(int(datetime(2026, 10, 9, tzinfo=ZONE).timestamp()), "codex_session", "codex")])
            value = codex_tokens_metric(root, archives, cc, NOW, ZONE)["value"]
            allp = value["periods"]["all"]["totals"]
            self.assertEqual(allp["requests"], 1)               # only the archive day remains
            self.assertEqual(value["ccswitch_overlap"]["excluded_days"], ["2026-10-09"])
            with self.assertRaises(SourceError) as ctx:
                codex_tokens_metric(Path(tmp) / "x", Path(tmp) / "y", cc, NOW, ZONE)
            self.assertEqual(ctx.exception.code, "codex_sessions_not_found")

    @staticmethod
    def ccswitch_db(tmp, rows):
        db = Path(tmp) / "cc.db"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE proxy_request_logs(id INTEGER PRIMARY KEY, created_at INTEGER, data_source TEXT, app_type TEXT)")
        conn.executemany("INSERT INTO proxy_request_logs(created_at,data_source,app_type) VALUES(?,?,?)", rows)
        conn.commit()
        conn.close()
        return db


class ClaudeTests(unittest.TestCase):
    def records(self, tmp):
        root = Path(tmp) / "projects" / "p1"
        write(root / "a.jsonl", [
            {"timestamp": ts(9, 10), "requestId": "r1", "isSidechain": False,
             "message": {"model": "claude-opus-5-5", "usage": {"input_tokens": 2, "output_tokens": 100,
                                                              "cache_read_input_tokens": 5000, "cache_creation_input_tokens": 300}}},
            {"timestamp": ts(9, 10, 1), "requestId": "r1",                     # streaming update wins
             "message": {"model": "claude-opus-5-5", "usage": {"input_tokens": 2, "output_tokens": 244,
                                                              "cache_read_input_tokens": 5000, "cache_creation_input_tokens": 300}}},
            {"timestamp": ts(9, 11), "requestId": "r2", "isSidechain": True,   # subagent usage counts
             "message": {"model": "claude-haiku", "usage": {"input_tokens": 10, "output_tokens": 5,
                                                           "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}}},
            "not json at all",
            {"timestamp": ts(9, 12), "message": {"usage": {"input_tokens": 1, "output_tokens": 1}}},   # no requestId
        ])
        write(root / "b.jsonl", [
            {"timestamp": ts(9, 10, 2), "requestId": "r1",                    # same request in a resumed file
             "message": {"model": "claude-opus-5-5", "usage": {"input_tokens": 2, "output_tokens": 300,
                                                              "cache_read_input_tokens": 5000, "cache_creation_input_tokens": 300}}},
        ])
        return Path(tmp) / "projects"

    def test_last_record_per_request_id_globally(self):
        with tempfile.TemporaryDirectory() as tmp:
            value = claude_tokens_metric(self.records(tmp), Path(tmp) / "none.db", NOW, ZONE)["value"]
            allp = value["periods"]["all"]["totals"]
            # r1 latest (out 300, from file b) + r2 + the requestId-less record
            self.assertEqual((allp["requests"], allp["fresh_input"], allp["output"], allp["cache_read"],
                              allp["cache_write"]), (3, 13, 306, 5000, 300))
            models = {g["model"] for g in value["periods"]["all"]["groups"]}
            self.assertEqual(models, {"claude-opus-5-5", "claude-haiku", "unknown"})
            with self.assertRaises(SourceError):
                claude_tokens_metric(Path(tmp) / "none", Path(tmp) / "none.db", NOW, ZONE)

    def test_exclusion_uses_folded_claude_desktop_days(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.records(tmp)
            cc = CodexTests.ccswitch_db(tmp, [
                (int(datetime(2026, 10, 9, tzinfo=ZONE).timestamp()), "proxy", "claude-desktop")])
            value = claude_tokens_metric(root, cc, NOW, ZONE)["value"]
            self.assertEqual(value["periods"]["all"]["totals"]["requests"], 0)
            self.assertEqual(value["ccswitch_overlap"]["excluded_days"], ["2026-10-09"])


class GeminiTests(unittest.TestCase):
    def test_last_per_id_thoughts_and_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "gemini"
            write(root / "tmp/h/chats/session-x.jsonl", [
                {"id": "g1", "timestamp": "2026-10-09T02:00:00.000Z", "type": "gemini", "model": "gemini-3-flash",
                 "tokens": {"input": 1000, "output": 10, "cached": 0, "thoughts": 5, "total": 1015}},
                {"id": "g1", "timestamp": "2026-10-09T02:00:30.000Z",
                 "tokens": {"input": 2000, "output": 20, "cached": 800, "thoughts": 7, "total": 2027}},
                {"id": "g2", "timestamp": "2026-10-08T02:00:00.000Z",
                 "tokens": {"input": 50, "output": 5, "cached": 0, "thoughts": 0, "total": 55}},
            ])
            out = collect_gemini_sessions(root, Path(tmp) / "none.db", NOW, ZONE)
            self.assertEqual(out["scope"], "local_session_history")
            allp = out["metrics"]["tokens"]["value"]["periods"]["all"]["totals"]
            # g1 latest: fresh 1200, output 27, read 800; g2: fresh 50, output 5
            self.assertEqual((allp["requests"], allp["fresh_input"], allp["output"], allp["cache_read"]),
                             (2, 1250, 32, 800))
            with self.assertRaises(SourceError):
                collect_gemini_sessions(Path(tmp) / "none", Path(tmp) / "none.db", NOW, ZONE)


class McodeTests(unittest.TestCase):
    def db(self, tmp, rows=1):
        db = Path(tmp) / "runtime-state.sqlite"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE local_runtime_token_usage(id INTEGER PRIMARY KEY, session_id TEXT, agent_name TEXT,"
                     " framework_type TEXT, turn_id TEXT, model TEXT, ts INTEGER, input_tokens INTEGER,"
                     " output_tokens INTEGER, reasoning_tokens INTEGER, cache_read_tokens INTEGER,"
                     " cache_write_tokens INTEGER, cost_usd REAL, raw TEXT)")
        ms = int(datetime(2026, 10, 2, 12, 53, 44, tzinfo=ZONE).timestamp() * 1000)
        data = [("custom_provider:deepseek/x", ms + i * 5000, 26043 + i, 128, 0, 4257, 0) for i in range(rows)]
        conn.executemany("INSERT INTO local_runtime_token_usage(session_id,agent_name,framework_type,model,ts,"
                         "input_tokens,output_tokens,reasoning_tokens,cache_read_tokens,cache_write_tokens)"
                         " VALUES('s','mavis','pi-agent',?,?,?,?,?,?,?)", data)
        conn.commit()
        conn.close()
        return db

    def test_rows_as_is_and_schema_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = self.db(tmp, rows=3)
            value = mcode_tokens_metric(db, Path(tmp) / "none.db", NOW, ZONE)["value"]
            allp = value["periods"]["all"]["totals"]
            self.assertEqual((allp["requests"], allp["fresh_input"], allp["output"], allp["cache_read"]),
                             (3, 3 * 26043 + 3, 384, 3 * 4257))
            empty = Path(tmp) / "empty.sqlite"
            sqlite3.connect(empty).close()
            with self.assertRaises(SourceError) as ctx:
                mcode_tokens_metric(empty, Path(tmp) / "none.db", NOW, ZONE)
            self.assertEqual(ctx.exception.code, "unsupported_mcode_schema")
            with self.assertRaises(SourceError) as ctx:
                mcode_tokens_metric(Path(tmp) / "none.db", Path(tmp) / "none.db", NOW, ZONE)
            self.assertEqual(ctx.exception.code, "mcode_db_not_found")


class CollectorIntegrationTests(unittest.TestCase):
    ALL = ["ccswitch", "codex", "claude", "kimi", "qoder", "minimax_code", "dreamina", "minimax_design",
           "deepseek_api", "workbuddy", "trae_cn", "zcode", "opencode", "gemini", "antigravity"]

    def test_attach_and_standalone_sources(self):
        import tempfile as tf
        from unittest.mock import patch
        from agent_meter.collector import collect
        from agent_meter.model import metric
        with tf.TemporaryDirectory() as tmp:
            config = {"runtime_dir": tmp, "app_roots": [],
                      "disabled_sources": [x for x in self.ALL if x not in ("codex", "claude", "minimax_code", "gemini")]}
            # A failed account source still carries its local tokens.
            def fake_metric(*a, **kw):
                return metric({"periods": {"all": {"totals": {"requests": 7}}}, "daily_buckets": []})
            def dead(*a, **kw):
                raise SourceError("connection_failed")
            with patch("agent_meter.collector.collect_codex", side_effect=dead), \
                    patch("agent_meter.collector.collect_claude", side_effect=dead), \
                    patch("agent_meter.collector.collect_minimax", side_effect=dead), \
                    patch("agent_meter.collector.codex_tokens_metric", side_effect=fake_metric), \
                    patch("agent_meter.collector.claude_tokens_metric", side_effect=fake_metric), \
                    patch("agent_meter.collector.mcode_tokens_metric", side_effect=fake_metric), \
                    patch("agent_meter.collector.collect_gemini_sessions",
                          side_effect=SourceError("gemini_chats_not_found")):
                snap = collect(config, now=NOW)
            by_id = {s["id"]: s for s in snap["sources"]}
            self.assertEqual(by_id["codex"]["metrics"]["tokens"]["value"]["periods"]["all"]["totals"]["requests"], 7)
            self.assertEqual(by_id["claude"]["metrics"]["tokens"]["status"], "available")
            self.assertEqual(by_id["minimax_code"]["metrics"]["tokens"]["status"], "available")
            self.assertEqual((by_id["gemini"]["status"], by_id["gemini"]["diagnostics"]["reason"]),
                             ("not_connected", "gemini_chats_not_found"))
            self.assertEqual(by_id["gemini"]["scope"], "local_session_history")

    def test_user_switch_gates_local_parses(self):
        import tempfile as tf
        from unittest.mock import patch
        from agent_meter.collector import collect
        with tf.TemporaryDirectory() as tmp:
            config = {"runtime_dir": tmp, "app_roots": [],
                      "preferences": {"disabled_sources": ["codex", "claude"]},
                      "disabled_sources": [x for x in self.ALL if x not in ("codex", "claude")]}
            with patch("agent_meter.collector.codex_tokens_metric") as codex, \
                    patch("agent_meter.collector.claude_tokens_metric") as claude:
                snap = collect(config, now=NOW)
            codex.assert_not_called(); claude.assert_not_called()
            by_id = {s["id"]: s for s in snap["sources"]}
            self.assertEqual(by_id["codex"]["metrics"]["tokens"]["reason"], "disabled_by_user")
            self.assertEqual(by_id["claude"]["metrics"]["tokens"]["reason"], "disabled_by_user")


class ImportedDaysTests(unittest.TestCase):
    def test_state_matrix(self):
        with tempfile.TemporaryDirectory() as tmp:
            days, state = app_imported_days(Path(tmp) / "none.db", ZONE, "codex")
            self.assertEqual((days, state), (set(), "ccswitch_absent"))
            broken = Path(tmp) / "broken.db"
            broken.write_text("not a database")
            days, state = app_imported_days(broken, ZONE, "codex")
            self.assertEqual(state, "ccswitch_read_failed")
            cc = CodexTests.ccswitch_db(tmp, [
                (int(datetime(2026, 10, 8, tzinfo=ZONE).timestamp()), "codex_session", "codex"),
                (int(datetime(2026, 10, 8, 23, 30, tzinfo=ZONE).timestamp()), "session_log", "claude"),
            ])
            self.assertEqual(app_imported_days(cc, ZONE, "codex")[0], {"2026-10-08"})
            self.assertEqual(app_imported_days(cc, ZONE, "claude")[0], {"2026-10-08"})


if __name__ == "__main__":
    unittest.main()
