import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agent_meter.kimi_desktop_tokens import collect_kimi_desktop_tokens
from agent_meter.model import SourceError

NOW = datetime(2026, 10, 26, 6, 0, tzinfo=timezone.utc).timestamp()   # 14:00 Beijing
TODAY_MS = int((NOW - 3600) * 1000)
TEN_DAYS_MS = int((NOW - 10 * 86400) * 1000)
FUTURE_MS = int((NOW + 3600) * 1000)


def usage(i, o, r, w):
    return {"inputOther": i, "output": o, "inputCacheRead": r, "inputCacheCreation": w}


def write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


class KimiDesktopTokenTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name) / "sessions"
        self.root = root
        main = root / "wd_x/ses_1/agents/main"
        u1, u2, sub = usage(10, 5, 100, 0), usage(1, 2, 3, 4), usage(7, 7, 7, 7)
        write(main / "wire.jsonl", [
            {"type": "usage.record", "usageScope": "turn", "model": "k3-agent-swarm", "time": TODAY_MS, "usage": u1},
            # the same step again as step.end and message metadata: must not count
            {"type": "context.append_loop_event", "event": {"type": "step.end", "usage": u1}},
            {"type": "agent.message.appended", "message": {"meta": {"usage": u1}}},
            {"type": "usage.record", "usageScope": "turn", "model": "k3-agent-swarm", "time": TEN_DAYS_MS, "usage": u2},
            # session scope: unconfirmed meaning, excluded but counted
            {"type": "usage.record", "usageScope": "session", "model": "k3-agent-swarm", "time": TODAY_MS, "usage": usage(999, 999, 0, 0)},
            # beyond the collection end: never counted
            {"type": "usage.record", "usageScope": "turn", "model": "k3-agent-swarm", "time": FUTURE_MS, "usage": u1},
            "not json",
            {"type": "usage.record", "usageScope": "turn", "time": TODAY_MS, "usage": {"inputOther": -1}},
        ])
        # sub-agent and auto-titled sessions both count
        write(root / "ctitle-x/ses_2/agents/agent-0" / "wire.jsonl", [
            {"type": "usage.record", "usageScope": "turn", "model": "kimi-for-coding", "time": TODAY_MS, "usage": sub},
        ])

    def tearDown(self):
        self.tmp.cleanup()

    def test_source_contract(self):
        out = collect_kimi_desktop_tokens(self.root, NOW)
        self.assertEqual((out["id"], out["scope"], out["status"]),
                         ("kimi_desktop", "local_session_history", "available"))
        value = out["metrics"]["tokens"]["value"]
        self.assertEqual(value["coverage"], "kimi_desktop_local_sessions")
        self.assertEqual(value["dedup_rule"], "usage.record_turn_only")
        self.assertEqual(value["excluded_session_scope_records"], 1)
        self.assertEqual(value["periods"]["today"]["timezone"], "Asia/Shanghai")
        self.assertEqual({g["app"] for g in value["periods"]["all"]["groups"]}, {"kimi_desktop"})

    def test_counts_turn_records_once(self):
        value = collect_kimi_desktop_tokens(self.root, NOW)["metrics"]["tokens"]["value"]
        today = value["periods"]["today"]["totals"]
        self.assertEqual(today["requests"], 2)
        self.assertEqual(today["total_tokens"], 115 + 28)
        self.assertEqual(today["cache_read"], 107)
        self.assertEqual(value["periods"]["all"]["totals"]["total_tokens"], 115 + 28 + 10)

    def test_period_boundaries(self):
        value = collect_kimi_desktop_tokens(self.root, NOW)["metrics"]["tokens"]["value"]
        # The ten-day-old record is outside 7d but inside 30d.
        self.assertEqual(value["periods"]["7d"]["totals"]["requests"], 2)
        self.assertEqual(value["periods"]["30d"]["totals"]["requests"], 3)
        self.assertEqual(value["periods"]["30d"]["totals"]["total_tokens"], 115 + 28 + 10)
        # The future-dated record never reaches even "all".
        self.assertEqual(value["periods"]["all"]["totals"]["requests"], 3)

    def test_model_groups(self):
        value = collect_kimi_desktop_tokens(self.root, NOW)["metrics"]["tokens"]["value"]
        groups = {g["model"]: g for g in value["periods"]["all"]["groups"]}
        self.assertEqual(set(groups), {"k3-agent-swarm", "kimi-for-coding"})
        self.assertEqual((groups["k3-agent-swarm"]["requests"], groups["k3-agent-swarm"]["fresh_input"],
                          groups["k3-agent-swarm"]["output"], groups["k3-agent-swarm"]["cache_read"],
                          groups["k3-agent-swarm"]["cache_write"], groups["k3-agent-swarm"]["total_tokens"]),
                         (2, 11, 7, 103, 4, 125))
        self.assertEqual(groups["kimi-for-coding"]["total_tokens"], 28)
        for field in ("requests", "fresh_input", "output", "cache_read", "cache_write"):
            self.assertEqual(sum(g[field] for g in value["periods"]["all"]["groups"]),
                             value["periods"]["all"]["totals"][field])

    def test_daily_buckets(self):
        value = collect_kimi_desktop_tokens(self.root, NOW)["metrics"]["tokens"]["value"]
        # Daily buckets cover every parsed turn record (same as the CLI
        # source), including the ones outside a period's bounds.
        self.assertEqual(sum(b["tokens"] for b in value["daily_buckets"]), 153 + 115)
        self.assertEqual([b["date"] for b in value["daily_buckets"]],
                         sorted(b["date"] for b in value["daily_buckets"]))
        self.assertEqual([b["tokens"] for b in value["daily_buckets"]], [10, 258])

    def test_missing_directory(self):
        with tempfile.TemporaryDirectory() as empty:
            with self.assertRaises(SourceError) as raised:
                collect_kimi_desktop_tokens(Path(empty) / "sessions", NOW)
            self.assertEqual(raised.exception.code, "kimi_desktop_sessions_not_found")


if __name__ == "__main__":
    unittest.main()
