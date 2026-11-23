"""Hermetic tests for the Doubao work session activity view.

The trajectory files carry no usage ledger, so these tests pin the contract:
rows aggregate per session (rounds/tool calls), tokens stay null, and the
status stays recency-only.
"""
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agent_meter import activity as activity_module
from agent_meter.model import SourceError

NOW = int(datetime(2026, 10, 9, 4, 0, tzinfo=timezone.utc).timestamp())
IDLE = 15 * 60
WINDOW_START = NOW - 24 * 3600


def assistant(tool_calls=0, text="本轮回复正文不应被读取"):
    return {"role": "assistant", "content": text,
            "tool_calls": [{"name": "shell", "arguments": {"cmd": "ls"}}] * tool_calls}


class DoubaoWorkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / ".sessions"

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, session, agent, messages, mtime_ago):
        path = self.root / session / "agents" / agent / "system" / "trajectory.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(json.dumps(m) for m in messages) + "\n")
        stamp = NOW - mtime_ago
        os.utime(path, (stamp, stamp))
        return path

    def test_sessions_aggregate_as_activity_only(self):
        self.add("session_live", "main", [
            {"role": "user", "content": "提问正文不应被读取"},
            assistant(tool_calls=2),
            assistant(),
        ], mtime_ago=120)
        self.add("session_live", "worker", [assistant(tool_calls=1)], mtime_ago=60)
        idle_path = self.add("session_idle", "main", [
            {"role": "user", "content": "hi"},
            assistant(),
        ], mtime_ago=7200)
        # A broken sibling must not poison the session it sits in.
        broken = idle_path.parent.parent.parent / "broken" / "system" / "trajectory.jsonl"
        broken.parent.mkdir(parents=True)
        broken.write_bytes(b"not json at all\n")
        os.utime(broken, (NOW - 7200, NOW - 7200))
        # Empty file and out-of-window session are both skipped.
        self.add("session_blank", "main", [], mtime_ago=60).write_text("")
        self.add("session_old", "main", [assistant()], mtime_ago=3 * 24 * 3600)

        rows = activity_module.doubao_work_activities(self.root, WINDOW_START, IDLE, NOW)
        self.assertEqual(len(rows), 2)
        by_id = {row["session_id"]: row for row in rows}
        live = by_id["session_live"]
        self.assertEqual(live["app"], "doubao_work")
        self.assertEqual(live["granularity"], "recent_activity")
        self.assertEqual(live["status"], "running")
        self.assertEqual(live["status_basis"], "recency")
        self.assertEqual(live["requests"], 3)
        self.assertEqual(live["tool_calls"], 3)
        self.assertEqual(live["counts_scope"], "session_lifetime")
        self.assertIsNone(live["tokens"])
        self.assertEqual(live["notes"], "activity_only_no_token_ledger")
        self.assertIsNone(live["last_model"])
        self.assertIsNone(live["project_path"])
        self.assertFalse(live["subagent"])
        self.assertIsNotNone(live["started_at"])
        self.assertIsNotNone(live["last_event_at"])
        idle = by_id["session_idle"]
        self.assertEqual(idle["status"], "suspected_ended")
        self.assertEqual(idle["requests"], 1)
        self.assertEqual(idle["tool_calls"], 0)
        self.assertIsNone(idle["tokens"])
        payload = json.dumps(rows, ensure_ascii=False)
        self.assertNotIn("不应被读取", payload)

    def test_zero_rounds_keeps_null_tokens(self):
        self.add("session_user_only", "main", [{"role": "user", "content": "x"}], mtime_ago=60)
        rows = activity_module.doubao_work_activities(self.root, WINDOW_START, IDLE, NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["requests"], 0)
        self.assertIsNone(rows[0]["tokens"])

    def test_missing_root_raises(self):
        with self.assertRaises(SourceError) as ctx:
            activity_module.doubao_work_activities(self.root, WINDOW_START, IDLE, NOW)
        self.assertEqual(ctx.exception.code, "doubao_work_sessions_not_found")


if __name__ == "__main__":
    unittest.main()
