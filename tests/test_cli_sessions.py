"""Hermetic tests for the direct CLI session-history readers.

Fixtures mirror the real formats (validated against historical imports on
2026-10-09); nothing here touches the real home directories.
"""
import json
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from agent_meter import zstd_io
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


def write_zstd(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = ("\n".join(json.dumps(x) for x in lines) + "\n").encode()
    if zstd_io.HAS_STDLIB_ZSTD:
        path.write_bytes(zstd_io._zstd.compress(data))
    else:
        with open(path, "wb") as handle:
            subprocess.run([shutil.which("zstd"), "-zc"], input=data, stdout=handle, check=True)


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
            value = codex_tokens_metric(root, archives, NOW, ZONE)["value"]
            allp = value["periods"]["all"]["totals"]
            # deltas: (100,10,2,50) + (160,15,3,70) + reset (30,4,0,10) + archive (40,5,0,20)
            self.assertEqual((allp["requests"], allp["fresh_input"], allp["output"], allp["reasoning"],
                              allp["cache_read"], allp["cache_write"]), (4, 180, 34, 5, 150, 0))
            models = {g["model"]: g for g in value["periods"]["all"]["groups"]}
            self.assertEqual(models["gpt-6-astra"]["requests"], 3)
            self.assertEqual(models["unknown"]["requests"], 1)   # archive without session_meta model

    def test_compressed_rollouts_are_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, archives = self.dir(tmp)
            write_zstd(root / "2026" / "10" / "09" / "rollout-compressed.jsonl.zst", [
                {"timestamp": ts(9), "type": "session_meta", "payload": {"model": "gpt-6-astra"}},
                codex_event(ts(9, 10), TOTAL(100, 10, 2, 50)),
                codex_event(ts(9, 11), TOTAL(260, 25, 5, 120)),
            ])
            value = codex_tokens_metric(root, archives, NOW, ZONE)["value"]
            allp = value["periods"]["all"]["totals"]
            # Existing plain files plus the compressed deltas (100,10,2,50) + (160,15,3,70).
            self.assertEqual((allp["requests"], allp["fresh_input"], allp["output"], allp["reasoning"],
                              allp["cache_read"], allp["cache_write"]), (6, 320, 59, 10, 270, 0))
            models = {g["model"]: g for g in value["periods"]["all"]["groups"]}
            self.assertEqual(models["gpt-6-astra"]["requests"], 5)

    def test_plain_rollout_wins_over_compressed_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "sessions"
            lines = [
                {"timestamp": ts(9), "type": "session_meta", "payload": {"model": "gpt-6-astra"}},
                codex_event(ts(9, 10), TOTAL(100, 10, 2, 50)),
            ]
            write(root / "same.jsonl", lines)
            write_zstd(root / "same.jsonl.zst", lines)
            value = codex_tokens_metric(root, Path(tmp) / "archives", NOW, ZONE)["value"]
            self.assertEqual(value["periods"]["all"]["totals"]["requests"], 1)

    def test_compressed_only_directory_without_zstd_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "sessions"
            write_zstd(root / "only.jsonl.zst", [
                {"timestamp": ts(9), "type": "session_meta", "payload": {"model": "gpt-6-astra"}},
                codex_event(ts(9, 10), TOTAL(100, 10, 2, 50)),
            ])
            with patch.object(zstd_io, "HAS_STDLIB_ZSTD", False):
                with self.assertRaises(SourceError) as failure:
                    codex_tokens_metric(root, Path(tmp) / "archive", NOW, zstd_binary=None)
            self.assertEqual(failure.exception.code, "zstd_unavailable")

    def test_inherited_baseline_reasoning_and_turn_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = dict(TOTAL(1000, 100, 40, 400), total_tokens=1100)
            last = dict(TOTAL(100, 20, 5, 40), total_tokens=120)
            archive = root / "archived"
            path = root / "sessions" / "copy.jsonl"
            lines = [{"type": "session_meta", "payload": {"model": "default"}},
                     {"type": "turn_context", "payload": {"model": "model-a"}},
                     codex_event(ts(9, 10), first, last),
                     codex_event(ts(9, 10, 1), first, last),
                     {"type": "turn_context", "payload": {"model": "model-b"}},
                     codex_event(ts(9, 11), dict(TOTAL(1200, 130, 50, 500), total_tokens=1330))]
            write(path, lines)
            write_zstd(archive / "copy.jsonl.zst", lines)
            metric = codex_tokens_metric(path.parent, archive, NOW, ZONE)
            window = metric["value"]["periods"]["today"]
            self.assertEqual(window["totals"]["requests"], 2)
            self.assertEqual(window["totals"]["total_tokens"], 350)
            self.assertEqual({g["model"]: (g["output"], g["reasoning"]) for g in window["groups"]},
                             {"model-a": (15, 5), "model-b": (20, 10)})

    def test_reported_total_without_components_is_counted_but_unpriced(self):
        from agent_meter.prices import PriceTable, estimate_source_cost
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "fork.jsonl", [
                {"type": "turn_context", "payload": {"model": "priced"}},
                codex_event(ts(9), dict(TOTAL(900, 100), total_tokens=1000),
                            dict(TOTAL(0), total_tokens=77))])
            result = codex_tokens_metric(root, root/"archive", NOW)
            totals = result["value"]["periods"]["all"]["totals"]
            self.assertEqual((totals["total_tokens"], totals["unclassified"], totals["requests"]), (77,77,1))
            self.assertEqual(totals["peak"]["total_tokens"],77)
            self.assertIsNone(estimate_source_cost(result, PriceTable("USD", {"priced": (1,1,1,1)}, set())))

    def test_compressed_gap_is_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, archive = self.dir(tmp)
            (root / "broken.jsonl.zst").write_bytes(b"invalid")
            result = codex_tokens_metric(root, archive, NOW, ZONE)
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["value"]["scan"]["rollouts_skipped"], 1)
            self.assertEqual(result["value"]["periods"]["all"]["totals"]["requests"], 4)

    def test_missing_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, archives = self.dir(tmp)
            value = codex_tokens_metric(root, archives, NOW, ZONE)["value"]
            self.assertEqual(value["periods"]["all"]["totals"]["requests"], 4)
            with self.assertRaises(SourceError) as ctx:
                codex_tokens_metric(Path(tmp) / "x", Path(tmp) / "y", NOW, ZONE)
            self.assertEqual(ctx.exception.code, "codex_sessions_not_found")


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

    def test_desktop_local_agent_sessions_are_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli = Path(tmp) / "projects"
            cli.mkdir()
            desktop = Path(tmp) / "desktop"
            session = desktop / "org" / "user" / "local_x" / ".claude" / "projects" / "-p"
            write(session / "s.jsonl", [
                {"timestamp": ts(8, 10), "requestId": "d1",
                 "message": {"model": "claude-opus-5", "usage": {"input_tokens": 5, "output_tokens": 50,
                                                                "cache_read_input_tokens": 1000,
                                                                "cache_creation_input_tokens": 200}}},
                {"timestamp": ts(8, 11), "requestId": "d1",          # streaming update wins
                 "message": {"model": "claude-opus-5", "usage": {"input_tokens": 5, "output_tokens": 80,
                                                                "cache_read_input_tokens": 1000,
                                                                "cache_creation_input_tokens": 200}}},
                {"timestamp": ts(8, 12), "requestId": "d2",
                 "message": {"model": "claude-fable-5", "usage": {"input_tokens": 7, "output_tokens": 9,
                                                                 "cache_read_input_tokens": 0,
                                                                 "cache_creation_input_tokens": 0}}},
            ])
            # Audit logs outside .claude/projects are never token ledgers.
            write(desktop / "org" / "user" / "local_x" / "audit.jsonl", [
                {"timestamp": ts(8, 13), "requestId": "audit",
                 "message": {"model": "claude-opus-5", "usage": {"input_tokens": 99, "output_tokens": 99}}},
            ])
            value = claude_tokens_metric(cli, NOW, ZONE, desktop_root=desktop)["value"]
            allp = value["periods"]["all"]["totals"]
            self.assertEqual((allp["requests"], allp["fresh_input"], allp["output"], allp["cache_read"],
                              allp["cache_write"]), (2, 12, 89, 1000, 200))
            self.assertEqual({g["model"] for g in value["periods"]["all"]["groups"]},
                             {"claude-opus-5", "claude-fable-5"})

    def test_missing_desktop_root_is_harmless(self):
        with tempfile.TemporaryDirectory() as tmp:
            value = claude_tokens_metric(self.records(tmp), NOW, ZONE,
                                         desktop_root=Path(tmp) / "none")["value"]
            self.assertEqual(value["periods"]["all"]["totals"]["requests"], 3)

    def test_last_record_per_request_id_globally(self):
        with tempfile.TemporaryDirectory() as tmp:
            value = claude_tokens_metric(self.records(tmp), NOW, ZONE)["value"]
            allp = value["periods"]["all"]["totals"]
            # r1 latest (out 300, from file b) + r2 + the requestId-less record
            self.assertEqual((allp["requests"], allp["fresh_input"], allp["output"], allp["cache_read"],
                              allp["cache_write"]), (3, 13, 306, 5000, 300))
            models = {g["model"] for g in value["periods"]["all"]["groups"]}
            self.assertEqual(models, {"claude-opus-5-5", "claude-haiku", "unknown"})
            with self.assertRaises(SourceError):
                claude_tokens_metric(Path(tmp) / "none", NOW, ZONE)


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
            out = collect_gemini_sessions(root, NOW, ZONE)
            self.assertEqual(out["scope"], "local_session_history")
            allp = out["metrics"]["tokens"]["value"]["periods"]["all"]["totals"]
            # g1 latest: fresh 1200, output 27, read 800; g2: fresh 50, output 5
            self.assertEqual((allp["requests"], allp["fresh_input"], allp["output"], allp["cache_read"]),
                             (2, 1250, 32, 800))
            with self.assertRaises(SourceError):
                collect_gemini_sessions(Path(tmp) / "none", NOW, ZONE)


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

    def test_wal_append_invalidates_cached_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = self.db(tmp)
            with sqlite3.connect(db) as writer:
                writer.execute("PRAGMA journal_mode=WAL")
                writer.execute("PRAGMA wal_autocheckpoint=0")
                self.assertEqual(len(load_mcode(db)), 1)
                writer.execute("INSERT INTO local_runtime_token_usage(session_id,model,ts,input_tokens,output_tokens,"
                               "reasoning_tokens,cache_read_tokens,cache_write_tokens) VALUES('s','m',1000,1,2,0,0,0)")
                writer.commit()
                self.assertEqual(len(load_mcode(db)), 2)

    def test_turn_telemetry_supplies_missing_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = self.db(tmp, rows=3)
            conn = sqlite3.connect(db)
            conn.execute("UPDATE local_runtime_token_usage SET model=NULL, turn_id='t' || id")
            conn.execute("CREATE TABLE local_runtime_message_rows(id INTEGER PRIMARY KEY, session_id TEXT,"
                         " turn_id TEXT, role TEXT, data_json TEXT)")
            conn.executemany("INSERT INTO local_runtime_message_rows(session_id,turn_id,role,data_json)"
                             " VALUES('s',?,'assistant',?)",
                             [("t1", json.dumps({"context_usage_telemetry": {"model": "MiniMax-M3.1-Flash"}})),
                              ("t2", json.dumps({"context_usage_telemetry": {"model": "MiniMax-M3.1-Flash-Preview"}}))])
            conn.commit()
            conn.close()
            models = [r[1] for r in load_mcode(db)]
            self.assertEqual(models, ["MiniMax-M3.1-Flash", "MiniMax-M3.1-Flash-Preview", "unknown"])

    def test_rows_as_is_and_schema_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = self.db(tmp, rows=3)
            value = mcode_tokens_metric(db, NOW, ZONE)["value"]
            allp = value["periods"]["all"]["totals"]
            self.assertEqual((allp["requests"], allp["fresh_input"], allp["output"], allp["cache_read"]),
                             (3, 3 * 26043 + 3, 384, 3 * 4257))
            empty = Path(tmp) / "empty.sqlite"
            sqlite3.connect(empty).close()
            with self.assertRaises(SourceError) as ctx:
                mcode_tokens_metric(empty, NOW, ZONE)
            self.assertEqual(ctx.exception.code, "unsupported_mcode_schema")
            with self.assertRaises(SourceError) as ctx:
                mcode_tokens_metric(Path(tmp) / "none.db", NOW, ZONE)
            self.assertEqual(ctx.exception.code, "mcode_db_not_found")


class CollectorIntegrationTests(unittest.TestCase):
    ALL = ["codex", "claude", "kimi", "qoder", "minimax_code", "dreamina", "minimax_design",
           "deepseek_api", "workbuddy", "trae_cn", "zcode", "opencode", "gemini", "antigravity", "kimi_desktop", "reset_forecast",
           "deepseek_harness", "volcengine", "mimo", "stepfun", "imported_history"]

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

    def test_local_only_preserves_codex_and_skips_account_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, archive = CodexTests().dir(tmp)
            config = {"runtime_dir": tmp, "local_only": True, "app_roots": [],
                      "codex_sessions_dir": str(root), "codex_archives_dir": str(archive),
                      "codex_history_db": str(Path(tmp)/"absent"), "codex_images_dir": str(Path(tmp)/"images"),
                      "disabled_sources": [key for key in self.ALL if key != "codex"]}
            with patch("agent_meter.collector.collect_codex") as remote, \
                 patch("agent_meter.collector.claude_tokens_metric", side_effect=SourceError("claude_projects_not_found")):
                snap = collect(config, now=NOW)
            remote.assert_not_called()
            self.assertEqual(snap["application_usage"]["codex"]["all"]["direct"]["requests"], 4)
            codex = next(src for src in snap["sources"] if src["id"]=="codex")
            self.assertIsNone(codex["metrics"]["quota"]["value"])

    def test_user_switch_gates_local_parses(self):
        import tempfile as tf
        from unittest.mock import patch
        from agent_meter.collector import collect
        with tf.TemporaryDirectory() as tmp:
            config = {"runtime_dir": tmp, "app_roots": [],
                      "preferences": {"disabled_sources": ["codex", "claude"]},
                      "disabled_sources": [x for x in self.ALL if x not in ("codex", "claude")]}
            with patch("agent_meter.collector.codex_tokens_metric") as codex, \
                    patch("agent_meter.collector.claude_tokens_metric",
                          side_effect=lambda *a, **kw: metric({"periods": {"all": {"totals": {"requests": 1}},
                                                                           "daily_buckets": []}})) as claude:
                snap = collect(config, now=NOW)
            codex.assert_not_called()
            claude.assert_called_once()   # local Claude history is independent of the quota switch
            by_id = {s["id"]: s for s in snap["sources"]}
            self.assertEqual(by_id["codex"]["metrics"]["tokens"]["reason"], "disabled_by_user")
            self.assertEqual(by_id["claude"]["metrics"]["tokens"]["status"], "available")


if __name__ == "__main__":
    unittest.main()
