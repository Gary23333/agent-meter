import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agent_meter.kimi_tokens import collect_kimi_tokens
from agent_meter.model import SourceError

NOW = datetime(2026, 10, 9, 6, 0, tzinfo=timezone.utc).timestamp()   # 14:00 Beijing
TODAY_MS = int((NOW - 3600) * 1000)
OLD_MS = int((NOW - 10 * 86400) * 1000)


def usage(i, o, r, w):
    return {"inputOther": i, "output": o, "inputCacheRead": r, "inputCacheCreation": w}


def write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


class KimiTokenTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        session = Path(self.tmp.name) / ".kimi-code/sessions/wd_x/ses_1/agents"
        u1, u2, sub = usage(10, 5, 100, 0), usage(1, 2, 3, 4), usage(7, 7, 7, 7)
        write(session / "main/wire.jsonl", [
            {"type": "usage.record", "usageScope": "turn", "model": "kimi-code/k3", "time": TODAY_MS, "usage": u1},
            # the same step again as step.end and message metadata: must not count
            {"type": "context.append_loop_event", "event": {"type": "step.end", "usage": u1}},
            {"type": "agent.message.appended", "message": {"meta": {"usage": u1}}},
            {"type": "usage.record", "usageScope": "turn", "model": "kimi-code/k3", "time": OLD_MS, "usage": u2},
            # sub-agent summary duplicates the sub-agent's own file
            {"type": "subagent.completed", "agentId": "agent-0", "usage": sub},
            # session scope: unconfirmed meaning, excluded but counted
            {"type": "usage.record", "usageScope": "session", "model": "kimi-code/k3", "time": TODAY_MS, "usage": usage(999, 999, 0, 0)},
            "not json",
            {"type": "usage.record", "usageScope": "turn", "time": TODAY_MS, "usage": {"inputOther": -1}},
        ])
        write(session / "agent-0/wire.jsonl", [
            {"type": "usage.record", "usageScope": "turn", "model": "kimi-code/kimi-for-coding", "time": TODAY_MS, "usage": sub},
        ])

    def tearDown(self):
        self.tmp.cleanup()

    def test_counts_turn_records_once(self):
        value = collect_kimi_tokens(self.tmp.name, NOW)["value"]
        today = value["periods"]["today"]["totals"]
        self.assertEqual(today["requests"], 2)
        self.assertEqual(today["total_tokens"], 115 + 28)
        self.assertEqual(today["cache_read"], 107)
        self.assertEqual(value["periods"]["all"]["totals"]["total_tokens"], 115 + 28 + 10)
        self.assertEqual(value["periods"]["7d"]["totals"]["requests"], 2)
        self.assertEqual(value["excluded_session_scope_records"], 1)
        self.assertEqual({g["model"] for g in value["periods"]["all"]["groups"]},
                         {"kimi-code/k3", "kimi-code/kimi-for-coding"})
        self.assertEqual(sum(b["tokens"] for b in value["daily_buckets"]), 153)

    def test_cache_follows_file_changes(self):
        collect_kimi_tokens(self.tmp.name, NOW)
        main = Path(self.tmp.name) / ".kimi-code/sessions/wd_x/ses_1/agents/main/wire.jsonl"
        with open(main, "a") as f:
            f.write(json.dumps({"type": "usage.record", "usageScope": "turn", "model": "kimi-code/k3",
                                "time": TODAY_MS, "usage": usage(1, 1, 1, 1)}) + "\n")
        os.utime(main, ns=(os.stat(main).st_atime_ns, os.stat(main).st_mtime_ns + 1_000_000))
        value = collect_kimi_tokens(self.tmp.name, NOW)["value"]
        self.assertEqual(value["periods"]["today"]["totals"]["requests"], 3)

    def test_missing_directory(self):
        with tempfile.TemporaryDirectory() as empty:
            with self.assertRaises(SourceError):
                collect_kimi_tokens(empty, NOW)


if __name__ == "__main__":
    unittest.main()
