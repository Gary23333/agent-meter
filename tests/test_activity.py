"""Hermetic tests for the recent session/turn activity view.

Fixtures live in temporary directories; nothing reads the real home. The
status rules under test: running needs fresh evidence, terminal statuses
come only from explicit events, and recency-only sources never claim
success.
"""
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from agent_meter import activity as activity_module
# The real zstd binary; activity decompression uses the shared zstd module.
from agent_meter.activity import collect_activity
from agent_meter.collector import SnapshotService, default_config
from agent_meter.model import SourceError
from agent_meter.prices import PriceTable
from agent_meter.server import load_or_create_token, make_server

# 2026-10-09 12:00 +08:00 — same convention as the other suites.
NOW = int(datetime(2026, 10, 9, 4, 0, tzinfo=timezone.utc).timestamp())
ZONE = ZoneInfo("Asia/Shanghai")
IDLE = 15 * 60
WINDOW_START = NOW - 24 * 3600
# The real zstd binary; activity decompression goes through dsh_tokens.
ZSTD = shutil.which("zstd")

MODEL_USAGE_DDL = """
CREATE TABLE model_usage (
  id text primary key, logical_request_id text, attempt_index integer default 0,
  session_id text, turn_id text, query_source text, provider_id text, model_id text,
  status text, started_at integer, completed_at integer,
  input_tokens integer default 0, output_tokens integer default 0,
  reasoning_tokens integer default 0, cache_creation_input_tokens integer default 0,
  cache_read_input_tokens integer default 0)
"""
SESSION_DDL = "CREATE TABLE session (id text primary key, directory text)"


def ms_ago(seconds):
    return int((NOW - seconds) * 1000)


def iso_ago(seconds):
    return datetime.fromtimestamp(NOW - seconds, timezone.utc).isoformat().replace("+00:00", "Z")


def zcode_db(path, usage_rows, session_rows=None):
    conn = sqlite3.connect(path)
    conn.executescript(MODEL_USAGE_DDL)
    if session_rows is not None:
        conn.execute(SESSION_DDL)
        conn.executemany("INSERT INTO session(id, directory) VALUES(?, ?)", session_rows)
    conn.executemany(
        "INSERT INTO model_usage(id, session_id, turn_id, provider_id, model_id, status,"
        " started_at, completed_at, input_tokens, output_tokens, reasoning_tokens,"
        " cache_creation_input_tokens, cache_read_input_tokens)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", usage_rows)
    conn.commit()
    conn.close()


class ZCodeTests(unittest.TestCase):
    def test_statuses_projects_and_subagents(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "db.sqlite"
            zcode_db(db, [
                # session A: fresh completed turn -> running, real directory.
                ("1", "sess_a", "t1", "p", "m1", "completed", ms_ago(60), ms_ago(30), 100, 10, 5, 20, 300),
                # session B: idle for 2 h -> suspected_ended; an error turn -> failed.
                ("2", "sess_b", "t1", "p", "m1", "error", ms_ago(7200), ms_ago(7100), 0, 0, 0, 0, 0),
                # session C: subagent session, cancelled turn.
                ("3", "sess_subagent_x", "t1", "p", "m2", "cancelled", ms_ago(3600), ms_ago(3500), 0, 0, 0, 0, 0),
                # outside the window: ignored.
                ("4", "sess_a", "t0", "p", "m1", "completed", ms_ago(25 * 3600), ms_ago(25 * 3600), 1, 1, 0, 0, 0),
            ], [("sess_a", "/Users/u/项目/A")])
            rows = activity_module.zcode_activities(db, WINDOW_START, IDLE, NOW)
            by_id = {row["session_id"]: row for row in rows}
            a = by_id["sess_a"]
            self.assertEqual(a["status"], "running")
            self.assertEqual(a["status_basis"], "recency")
            self.assertEqual(a["project_alias"], "A")
            self.assertEqual(a["project_path"], "/Users/u/项目/A")
            self.assertEqual(a["requests"], 1)
            self.assertEqual(a["tokens"]["fresh_input"], 100)
            self.assertEqual(a["last_turn_status"], "completed")
            self.assertFalse(a["subagent"])
            b = by_id["sess_b"]
            self.assertEqual(b["status"], "suspected_ended")
            self.assertEqual(b["last_turn_status"], "failed")
            self.assertEqual(b["turn_statuses"], {"failed": 1})
            self.assertIsNone(b["project_path"])
            c = by_id["sess_subagent_x"]
            self.assertTrue(c["subagent"])
            self.assertEqual(c["last_turn_status"], "cancelled")
            # Rows sort running first, newest activity first.
            statuses = [row["status"] for row in rows]
            self.assertEqual(statuses[0], "running")

    def test_unsupported_schema_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "db.sqlite"
            conn = sqlite3.connect(db)
            conn.execute("CREATE TABLE model_usage (started_at integer)")
            conn.commit()
            conn.close()
            with self.assertRaises(SourceError):
                activity_module.zcode_activities(db, WINDOW_START, IDLE, NOW)

    def test_missing_db_raises(self):
        with self.assertRaises(SourceError):
            activity_module.zcode_activities(Path("/nonexistent/db.sqlite"), WINDOW_START, IDLE, NOW)


class CodexImageTests(unittest.TestCase):
    def test_explicit_call_statuses_and_recency(self):
        threads = [
            ("thread-running", ms_ago(120), "generating"),
            ("thread-failed", ms_ago(7200), "failed"),
            ("thread-done", ms_ago(7200), "completed"),
            ("thread-recent", ms_ago(60), "completed"),   # explicit terminal evidence
            ("thread-stale-unknown", ms_ago(7200), None),  # unrecognized -> unknown
        ]
        with patch.object(activity_module, "history_threads", return_value=threads), \
                patch.object(activity_module, "resolve_history_db", return_value=Path("/h.db")):
            rows = activity_module.codex_image_activities(Path("/h.db"), WINDOW_START, IDLE, NOW)
        by_id = {row["session_id"]: row for row in rows}
        self.assertEqual(by_id["thread-running"]["status"], "running")
        self.assertEqual(by_id["thread-running"]["status_basis"], "explicit_event")
        self.assertEqual(by_id["thread-running"]["generating_calls"], 1)
        self.assertEqual(by_id["thread-failed"]["status"], "failed")
        self.assertEqual(by_id["thread-done"]["status"], "completed")
        self.assertEqual(by_id["thread-recent"]["status"], "completed")
        self.assertEqual(by_id["thread-recent"]["status_basis"], "explicit_event")
        self.assertEqual(by_id["thread-stale-unknown"]["status"], "unknown")
        self.assertEqual(by_id["thread-done"]["calls"], 1)

    def test_history_unavailable_is_source_error(self):
        with patch.object(activity_module, "resolve_history_db", return_value=None):
            with self.assertRaises(SourceError):
                activity_module.codex_image_activities(Path("/none.db"), WINDOW_START, IDLE, NOW)


def kimi_wire(records):
    return "\n".join(json.dumps(r) for r in records) + "\n"


class KimiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "sessions"

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, workspace, session, agent, records, mtime_ago=60):
        path = self.root / workspace / session / "agents" / agent / "wire.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(kimi_wire(records))
        stamp = (NOW - mtime_ago)
        os.utime(path, (stamp, stamp))

    def test_running_idle_and_subagent(self):
        self.add("wd_demo", "session_live", "main", [
            {"type": "agent.turn.started", "turnId": 1, "time": ms_ago(300)},
            {"type": "usage.record", "usageScope": "turn", "model": "k3", "time": ms_ago(60),
             "usage": {"inputOther": 1000, "output": 100, "inputCacheRead": 2000, "inputCacheCreation": 0}},
            # session-scope records are excluded from the ledger.
            {"type": "usage.record", "usageScope": "session", "model": "k3", "time": ms_ago(40),
             "usage": {"inputOther": 999999, "output": 0, "inputCacheRead": 0, "inputCacheCreation": 0}},
        ])
        self.add("wd_demo", "session_idle", "main", [
            {"type": "usage.record", "usageScope": "turn", "model": "k3", "time": ms_ago(7200),
             "usage": {"inputOther": 10, "output": 1, "inputCacheRead": 0, "inputCacheCreation": 0}},
            {"type": "turn.ended", "turnId": 1, "reason": "completed", "time": ms_ago(7000)},
        ])
        self.add("wd_demo", "session_live", "worker", [
            {"type": "usage.record", "usageScope": "turn", "model": "k3", "time": ms_ago(50),
             "usage": {"inputOther": 5, "output": 5, "inputCacheRead": 0, "inputCacheCreation": 0}},
        ])
        rows = activity_module._kimi_session_activities(self.root, "kimi", WINDOW_START, IDLE, NOW)
        by_id = {row["session_id"]: row for row in rows}
        live = by_id["session_live"]
        self.assertEqual(live["status"], "running")
        self.assertEqual(live["app"], "kimi")
        self.assertEqual(live["granularity"], "steps")
        self.assertEqual(live["requests"], 2)
        self.assertEqual(live["tokens"]["fresh_input"], 1005)
        self.assertEqual(live["project_alias"], "wd_demo")
        self.assertFalse(live["subagent"])  # the session includes its root agent
        idle = by_id["session_idle"]
        self.assertEqual(idle["status"], "suspected_ended")
        self.assertEqual(idle["last_turn_status"], "completed")
        self.assertEqual(idle["turn_statuses"], {"completed": 1})
        self.assertFalse(idle["subagent"])

    def test_missing_root_raises(self):
        with self.assertRaises(SourceError):
            activity_module._kimi_session_activities(self.root, "kimi", WINDOW_START, IDLE, NOW)


def write_zstd(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = ("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n").encode()
    from agent_meter import zstd_io
    if zstd_io.HAS_STDLIB_ZSTD:
        path.write_bytes(zstd_io._zstd.compress(data))
    else:
        with open(path, "wb") as handle:
            subprocess.run(["zstd", "-zc"], input=data, stdout=handle, check=True)


def dsh_session(ms_created, cwd, turn, steps, model="deepseek-chat", fresh=100, output=10):
    records = [{"type": "session", "version": 4, "id": "session-x", "createdAt": ms_created, "cwd": cwd}]
    for step in range(1, steps + 1):
        records.append({"type": "step/start", "time": ms_created + step, "data": {"turn": turn, "step": step}})
        records.append({"type": "request/header", "time": ms_created + step,
                        "data": {"header": {"config": {"model": model}}}})
        records.append({"type": "assistant/message", "time": ms_created + step + 5,
                        "data": {"turn": turn, "step": step,
                                 "usage": {"inputTokens": fresh, "outputTokens": output,
                                           "cacheReadTokens": 7, "reasoningTokens": 2},
                                 "message": {"source": {"model": model}}}})
        records.append({"type": "step/end", "time": ms_created + step + 6, "data": {"turn": turn, "step": step}})
    return records


class DshTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "sessions"

    def tearDown(self):
        self.tmp.cleanup()

    def test_explicit_turn_endings_and_dedup(self):
        done_dir = self.root / "proj-done" / "session-a"
        write_zstd(done_dir / "session.v4.jsonl.zstd",
                   dsh_session(ms_ago(7200), "/Users/u/proj-done", 1, 2)
                   + [{"type": "turn/start", "time": ms_ago(7200), "data": {"turn": 1}},
                      {"type": "turn/end", "time": ms_ago(7000), "data": {"turn": 1, "reason": {"kind": "completed"}}}])
        # A chunk/message pair for one (turn, step): last-wins dedup.
        aborted_dir = self.root / "proj-aborted" / "session-b"
        records = dsh_session(ms_ago(7200), "/Users/u/proj-aborted", 1, 1)
        records += [
            {"type": "assistant/chunk", "time": ms_ago(7000), "data": {"turn": 2, "step": 1,
             "chunk": {"usage": {"inputTokens": 50, "outputTokens": 5, "cacheReadTokens": 0, "reasoningTokens": 0}}}},
            {"type": "assistant/message", "time": ms_ago(6900), "data": {"turn": 2, "step": 1,
             "usage": {"inputTokens": 60, "outputTokens": 6, "cacheReadTokens": 0, "reasoningTokens": 0},
             "message": {"source": {"model": "deepseek-chat"}}}},
            {"type": "turn/start", "time": ms_ago(6950), "data": {"turn": 2}},
            {"type": "turn/end", "time": ms_ago(6800), "data": {"turn": 2, "reason": {"kind": "aborted"}}},
        ]
        write_zstd(aborted_dir / "session.v4.jsonl.zstd", records)
        # Outside the window: file never parsed.
        old_dir = self.root / "proj-old" / "session-c"
        write_zstd(old_dir / "session.v3.jsonl.zstd", dsh_session(ms_ago(3 * 24 * 3600), "/old", 1, 1))
        os.utime(old_dir / "session.v3.jsonl.zstd", (NOW - 3 * 24 * 3600, NOW - 3 * 24 * 3600))
        rows = activity_module.dsh_activities(self.root, ZSTD, WINDOW_START, IDLE, NOW)
        self.assertEqual(len(rows), 2)
        by_alias = {row["project_alias"]: row for row in rows}
        done = by_alias["proj-done"]
        self.assertEqual(done["status"], "suspected_ended")
        self.assertEqual(done["last_turn_status"], "completed")
        self.assertEqual(done["turn_statuses"], {"completed": 1})
        self.assertEqual(done["requests"], 2)
        self.assertEqual(done["tokens"]["fresh_input"], 200)
        self.assertEqual(done["tokens"]["cache_read"], 14)
        self.assertEqual(done["tokens"]["reasoning"], 4)
        self.assertEqual(done["tokens"]["output"], 16)  # (10-2) per record
        self.assertEqual(len(done["recent_turns"]), 1)
        self.assertEqual(done["recent_turns"][0]["steps"], 2)
        aborted = by_alias["proj-aborted"]
        self.assertEqual(aborted["last_turn_status"], "cancelled")
        self.assertEqual(aborted["requests"], 2)  # chunk+message deduped per (turn, step)
        self.assertEqual(aborted["tokens"]["fresh_input"], 100 + 60)

    def test_truncated_file_counts_as_skipped(self):
        path = self.root / "proj" / "session-bad" / "session.v4.jsonl.zstd"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x28\xb5\x2f\xfd-not-really-zstd")
        rows = activity_module.dsh_activities(self.root, ZSTD, WINDOW_START, IDLE, NOW)
        self.assertEqual(rows, [])

    def test_missing_root_raises(self):
        with self.assertRaises(SourceError):
            activity_module.dsh_activities(self.root, ZSTD, WINDOW_START, IDLE, NOW)


class ClaudeTests(unittest.TestCase):
    def test_usage_rows_cwd_and_sidechain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "projects"
            session_dir = root / "-Users-u-demo"
            session_dir.mkdir(parents=True)
            line = lambda body: json.dumps(body)
            transcript = "\n".join([
                line({"type": "user", "message": {"content": "prompt text never read"}}),
                line({"type": "assistant", "cwd": "/Users/u/demo", "sessionId": "s1",
                      "timestamp": iso_ago(600), "isSidechain": False,
                      "message": {"model": "priced-model", "usage": {
                          "input_tokens": 100, "cache_creation_input_tokens": 20,
                          "cache_read_input_tokens": 300, "output_tokens": 50,
                          "output_tokens_details": {"thinking_tokens": 10}}}}),
                line({"type": "assistant", "cwd": "/Users/u/demo", "sessionId": "s1",
                      "timestamp": iso_ago(60), "isSidechain": False,
                      "message": {"model": "priced-model", "usage": {
                          "input_tokens": 1, "cache_creation_input_tokens": 0,
                          "cache_read_input_tokens": 0, "output_tokens": 2}}}),
            ]) + "\n"
            (session_dir / "s1.jsonl").write_text(transcript)
            rows = activity_module.claude_activities(root, WINDOW_START, IDLE, NOW)
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["app"], "claude")
            self.assertEqual(row["granularity"], "recent_activity")
            self.assertEqual(row["status"], "running")
            self.assertEqual(row["project_alias"], "demo")
            self.assertEqual(row["requests"], 2)
            self.assertEqual(row["tokens"]["fresh_input"], 101)
            self.assertEqual(row["tokens"]["cache_write"], 20)
            self.assertEqual(row["tokens"]["cache_read"], 300)
            self.assertEqual(row["tokens"]["output"], 42)
            self.assertEqual(row["tokens"]["reasoning"], 10)
            self.assertEqual(row["notes"], activity_module.NOTE_RECENCY_ONLY)

    def test_idle_session_is_suspected_ended(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "projects"
            session_dir = root / "-Users-u-old"
            session_dir.mkdir(parents=True)
            path = session_dir / "s2.jsonl"
            path.write_text(json.dumps({
                "type": "assistant", "cwd": "/Users/u/old", "timestamp": iso_ago(7200),
                "message": {"model": "m", "usage": {"input_tokens": 1, "output_tokens": 1}}}) + "\n")
            stamp = NOW - 7200
            os.utime(path, (stamp, stamp))
            rows = activity_module.claude_activities(root, WINDOW_START, IDLE, NOW)
            self.assertEqual(rows[0]["status"], "suspected_ended")

    def test_missing_root_raises(self):
        with self.assertRaises(SourceError):
            activity_module.claude_activities(Path("/nonexistent"), WINDOW_START, IDLE, NOW)


class GeminiTests(unittest.TestCase):
    def test_tokens_and_header_session_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / ".gemini"
            chat = root / "tmp" / "proj" / "chats" / "session-2026-10-09.jsonl"
            chat.parent.mkdir(parents=True)
            chat.write_text("\n".join([
                json.dumps({"sessionId": "g1", "projectHash": "abc", "startTime": iso_ago(600)}),
                json.dumps({"tokens": {"input": 1000, "cached": 400, "output": 50, "thoughts": 20},
                            "model": "gemini-x", "timestamp": ms_ago(120)}),
            ]) + "\n")
            rows = activity_module.gemini_activities(root, WINDOW_START, IDLE, NOW)
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["session_id"], "g1")
            self.assertEqual(row["tokens"]["fresh_input"], 600)
            self.assertEqual(row["tokens"]["cache_read"], 400)
            self.assertEqual(row["tokens"]["output"], 70)
            self.assertEqual(row["last_model"], "gemini-x")
            self.assertIsNone(row["project_path"])

    def test_missing_root_raises(self):
        with self.assertRaises(SourceError):
            activity_module.gemini_activities(Path("/nonexistent"), WINDOW_START, IDLE, NOW)


class OpencodeTests(unittest.TestCase):
    MESSAGE_DDL = ("CREATE TABLE message (id text primary key, session_id text,"
                   " time_created integer, time_updated integer, data text)")
    SESSION_DDL = "CREATE TABLE session (id text primary key, directory text)"

    def test_project_join_and_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "opencode.db"
            conn = sqlite3.connect(db)
            conn.executescript(self.MESSAGE_DDL + ";" + self.SESSION_DDL)
            conn.execute("INSERT INTO session(id, directory) VALUES('s1', '/Users/u/oc')")
            message = {"role": "assistant", "modelID": "priced-model",
                       "tokens": {"input": 100, "output": 20, "reasoning": 5,
                                  "cache": {"read": 30, "write": 10}}}
            conn.execute("INSERT INTO message(id, session_id, time_created, time_updated, data)"
                         " VALUES('m1', 's1', ?, ?, ?)", (ms_ago(120), ms_ago(100), json.dumps(message)))
            conn.commit()
            conn.close()
            rows = activity_module.opencode_activities(db, WINDOW_START, IDLE, NOW)
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["project_path"], "/Users/u/oc")
            self.assertEqual(row["project_alias"], "oc")
            self.assertEqual(row["tokens"]["fresh_input"], 100)
            self.assertEqual(row["tokens"]["reasoning"], 5)
            self.assertEqual(row["last_model"], "priced-model")

    def test_missing_db_raises(self):
        with self.assertRaises(SourceError):
            activity_module.opencode_activities(Path("/nonexistent.db"), WINDOW_START, IDLE, NOW)


def service_config(tmp):
    """All sources pointed at a fixture tree; only the given one exists."""
    cfg = default_config()
    cfg.update({
        "home": str(tmp), "runtime_dir": str(Path(tmp) / ".runtime"),
        "zcode_usage_db": str(Path(tmp) / "none-zcode.sqlite"),
        "codex_history_db": str(Path(tmp) / "none-history.sqlite"),
        "codex_state_db": str(Path(tmp) / "state.sqlite"),
        "claude_desktop_sessions_dir": str(Path(tmp) / "none-agent"),
        "kimi_desktop_sessions_dir": str(Path(tmp) / "none-desktop"),
        "dsh_sessions_dir": str(Path(tmp) / "none-dsh"),
        "claude_projects_dir": str(Path(tmp) / "none-claude"),
        "gemini_dir": str(Path(tmp) / "none-gemini"),
        "opencode_db": str(Path(tmp) / "none-opencode.db"),
        "kimi_home": str(tmp),
    })
    return cfg


class CollectActivityTests(unittest.TestCase):
    def test_assembly_sorting_costs_and_meta(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            # One kimi fixture under the configured home.
            wire = tmp / ".kimi-code" / "sessions" / "wd_cost" / "session_1" / "agents" / "main" / "wire.jsonl"
            wire.parent.mkdir(parents=True)
            wire.write_text(kimi_wire([
                {"type": "usage.record", "usageScope": "turn", "model": "priced-model", "time": ms_ago(60),
                 "usage": {"inputOther": 1000, "output": 100, "inputCacheRead": 2000, "inputCacheCreation": 0}},
            ]))
            cfg = service_config(tmp)
            table = PriceTable("USD", {"priced-model": (1.0, 0.5, 0.5, 2.0)}, set())
            payload = collect_activity(cfg, now=NOW, table=table)
            self.assertEqual(payload["schema_version"], 1)
            self.assertEqual(payload["window_hours"], 24)
            self.assertEqual(payload["idle_after_minutes"], 15)
            self.assertEqual(len(payload["activities"]), 1)
            row = payload["activities"][0]
            self.assertEqual(row["app"], "kimi")
            # (1000*1.0 + 100*2.0 + 2000*0.5) / 1e6
            self.assertAlmostEqual(row["estimated_cost_usd"], 0.0022)
            # Sources with no data on disk degrade to not_connected, never error.
            self.assertEqual(payload["sources_meta"]["zcode"], {"status": "not_connected", "reason": "zcode_db_not_found", "activities": 0})
            self.assertEqual(payload["sources_meta"]["kimi"]["status"], "available")
            self.assertEqual(payload["sources_meta"]["kimi"]["activities"], 1)

    def test_codex_index_reads_recency_and_honors_disabled_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = service_config(tmp)
            with sqlite3.connect(config["codex_state_db"]) as db:
                db.execute("CREATE TABLE threads(id,cwd,created_at,updated_at,recency_at,title,tokens_used)")
                db.execute("INSERT INTO threads VALUES('t','/project',?,?,?,'private',900000)",
                           (NOW-3000, NOW, NOW-2000))
            feed = collect_activity(config, now=NOW)
            row = feed["activities"][0]
            self.assertEqual((row["application_id"], row["status"]), ("codex", "suspected_ended"))
            self.assertIsNone(row["tokens"])
            self.assertNotIn("private", json.dumps(feed))
            config["preferences"] = {"disabled_sources": ["codex"]}
            with patch.object(activity_module, "codex_activities") as scan:
                feed = collect_activity(config, now=NOW)
                scan.assert_not_called()
                self.assertEqual(feed["activities"], [])
                self.assertEqual(feed["sources_meta"]["codex_images"]["reason"], "disabled_by_user")

    def test_unpriced_models_cost_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            wire = tmp / ".kimi-code" / "sessions" / "wd" / "session_1" / "agents" / "main" / "wire.jsonl"
            wire.parent.mkdir(parents=True)
            wire.write_text(kimi_wire([
                {"type": "usage.record", "usageScope": "turn", "model": "unknown-model", "time": ms_ago(60),
                 "usage": {"inputOther": 10, "output": 1, "inputCacheRead": 0, "inputCacheCreation": 0}},
            ]))
            payload = collect_activity(service_config(tmp), now=NOW, table=PriceTable("USD", {}, set()))
            self.assertIsNone(payload["activities"][0]["estimated_cost_usd"])

    def test_running_sorts_before_terminal_regardless_of_age(self):
        rows = [
            {"status": "completed", "last_event_at": {"epoch_seconds": NOW - 60}},
            {"status": "running", "last_event_at": {"epoch_seconds": NOW - 3600}},
            {"status": "suspected_ended", "last_event_at": {"epoch_seconds": NOW - 30}},
        ]
        ranked = sorted(rows, key=activity_module._sort_key)
        self.assertEqual([row["status"] for row in ranked],
                         ["running", "suspected_ended", "completed"])


class ServiceActivityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.now = NOW

    def tearDown(self):
        self.tmp.cleanup()

    def test_cache_ttl_and_defensive_copy(self):
        cfg = service_config(self.tmp.name)
        service = SnapshotService(cfg, lambda config, now: {}, lambda: self.now)
        with patch("agent_meter.activity.collect_activity", wraps=activity_module.collect_activity) as spy:
            first = service.activity()
            first["activities"] = "corrupted"          # a mutated copy must not poison the cache
            second = service.activity()
            self.now += 1                              # TTL is 3 s: still cached
            third = service.activity()
            self.now += 4                              # beyond TTL: recomputed
            fourth = service.activity()
        self.assertEqual(second["activities"], [])
        self.assertEqual(third["generated_at"]["epoch_seconds"], NOW)
        self.assertEqual(fourth["generated_at"]["epoch_seconds"], NOW + 5)
        self.assertEqual(spy.call_count, 2)

    def test_generation_bump_invalidates_within_ttl(self):
        cfg = service_config(self.tmp.name)
        service = SnapshotService(cfg, lambda config, now: {}, lambda: self.now)
        with patch("agent_meter.activity.collect_activity", wraps=activity_module.collect_activity) as spy:
            service.activity()
            service.reload_prices()                    # any config change re-costs rows
            service.activity()
        self.assertEqual(spy.call_count, 2)

    def test_activity_never_triggers_full_collection(self):
        cfg = service_config(self.tmp.name)
        calls = []
        service = SnapshotService(cfg, lambda config, now: calls.append(1) or {}, lambda: self.now)
        service.activity()
        service.activity()
        self.assertEqual(calls, [])


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.token = load_or_create_token(Path(self.tmp.name) / "api.token")
        cfg = service_config(self.tmp.name)
        self.service = SnapshotService(cfg, lambda config, now: {}, lambda: NOW)
        self.server = make_server(self.service, self.token, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:" + str(self.server.server_address[1])

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def request(self, path, auth=True):
        headers = {"Authorization": "Bearer " + self.token} if auth else {}
        req = urllib.request.Request(self.url + path, headers=headers)
        return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=5)

    def test_activity_endpoint_contract(self):
        with self.request("/v1/activity") as response:
            self.assertEqual(response.status, 200)
            payload = json.load(response)
        self.assertEqual(payload["schema_version"], 1)
        self.assertIn("activities", payload)
        self.assertIn("sources_meta", payload)
        self.assertEqual(payload["window_hours"], 24)

    def test_activity_rejects_query_and_missing_auth(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.request("/v1/activity?x=1", auth=False)
        self.assertEqual(ctx.exception.code, 401)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.request("/v1/activity?x=1")
        self.assertEqual(ctx.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
