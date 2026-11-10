import json
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agent_meter.activity import kimi_legacy_activities
from agent_meter.collector import collect
from agent_meter.kimi_legacy_tokens import collect_kimi_legacy_tokens, load_records
from agent_meter.model import SourceError

NOW = datetime(2026, 11, 8, 6, 0, tzinfo=timezone.utc).timestamp()   # 14:00 Beijing
TODAY = NOW - 3600
TEN_DAYS = NOW - 10 * 86400
FUTURE = NOW + 3600


def usage(i, o, r=0, w=0):
    return {"input_other": i, "output": o, "input_cache_read": r, "input_cache_creation": w}


def line(t, u, message_id=None):
    payload = {"token_usage": u, "context_tokens": 999}
    if message_id is not None:
        payload["message_id"] = message_id
    return {"message": {"type": "assistant", "payload": payload}, "timestamp": t}


def write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) if not isinstance(r, str) else r for r in rows) + "\n")


class KimiLegacyTokenTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "sessions"
        write(self.root / "proj-a" / "sess1" / "wire.jsonl", [
            line(TODAY, usage(10, 5, 100, 0), "m1"),
            line(TODAY, usage(1, 2, 3, 4), "m2"),
            line(TEN_DAYS, usage(7, 7, 7, 7), "m3"),
            line(FUTURE, usage(500, 500), "m4"),
            line(TODAY, {"input_other": -1, "output": 5}, "m5"),
            "not json",
            {"message": {"payload": {"context_tokens": 1}}, "timestamp": TODAY},
        ])
        # sub-agent deep path; same message id as m1: counted once globally
        write(self.root / "proj-a" / "sess1" / "subagents" / "agent-0" / "wire.jsonl", [
            line(TODAY, usage(10, 5, 100, 0), "m1"),
            line(TODAY, usage(2, 2, 0, 0)),   # no message id: file+line key
        ])

    def tearDown(self):
        self.tmp.cleanup()

    def test_source_contract(self):
        out = collect_kimi_legacy_tokens(self.root, NOW)
        self.assertEqual((out["id"], out["scope"], out["status"]),
                         ("kimi_legacy", "local_session_history", "available"))
        value = out["metrics"]["tokens"]["value"]
        self.assertEqual(value["coverage"], "kimi_legacy_local_sessions")
        self.assertEqual(value["dedup_rule"], "message_id_or_file_line")
        self.assertEqual(value["model_attribution"], "unknown_no_model_field")
        self.assertEqual(value["excluded_duplicate_records"], 2)   # duplicate m1 + invalid m5
        self.assertEqual({g["model"] for g in value["periods"]["all"]["groups"]}, {"unknown"})
        self.assertEqual({g["app"] for g in value["periods"]["all"]["groups"]}, {"kimi_legacy"})

    def test_totals_and_periods(self):
        value = collect_kimi_legacy_tokens(self.root, NOW)["metrics"]["tokens"]["value"]
        today = value["periods"]["today"]["totals"]
        self.assertEqual(today["requests"], 3)
        self.assertEqual((today["fresh_input"], today["output"], today["cache_read"], today["cache_write"]),
                         (13, 9, 103, 4))
        self.assertEqual(today["total_tokens"], 129)
        self.assertEqual(value["periods"]["7d"]["totals"]["requests"], 3)
        self.assertEqual(value["periods"]["30d"]["totals"]["requests"], 4)
        self.assertEqual(value["periods"]["all"]["totals"]["requests"], 4)   # future never counted
        self.assertEqual(value["periods"]["all"]["totals"]["total_tokens"], 157)

    def test_peak_split_sums_to_parent(self):
        value = collect_kimi_legacy_tokens(self.root, NOW)["metrics"]["tokens"]["value"]
        for period in value["periods"].values():
            totals = period["totals"]
            for field in ("fresh_input", "output", "cache_read", "cache_write", "total_tokens"):
                self.assertEqual(totals["peak"][field] + totals["offpeak"][field], totals[field])

    def test_daily_buckets(self):
        value = collect_kimi_legacy_tokens(self.root, NOW)["metrics"]["tokens"]["value"]
        self.assertEqual(sum(b["tokens"] for b in value["daily_buckets"]), 157)

    def test_missing_directory(self):
        with self.assertRaises(SourceError) as raised:
            collect_kimi_legacy_tokens(Path(self.tmp.name) / "absent", NOW)
        self.assertEqual(raised.exception.code, "kimi_legacy_sessions_not_found")

    def test_activity_adapter(self):
        now = time.time()
        root = Path(self.tmp.name) / "recent"
        write(root / "proj-x" / "sess-live" / "wire.jsonl", [
            line(now - 60, usage(4, 6, 10, 0), "live-1"),
        ])
        rows = kimi_legacy_activities(root, now - 86400, 900, now)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["app"], "kimi_legacy")
        self.assertEqual(rows[0]["session_id"], "sess-live")
        self.assertIsNone(rows[0]["project_path"])
        self.assertEqual(rows[0]["status"], "running")
        self.assertEqual(rows[0]["requests"], 1)

    def _isolated_config(self):
        empty = str(Path(self.tmp.name) / "absent")
        config = {"local_only": True, "app_roots": [], "runtime_dir": str(Path(self.tmp.name) / "runtime"),
                  "kimi_legacy_sessions_dir": str(self.root), "enable_reset_forecast": False}
        for key in ("opencode_db", "mimocode_db", "deveco_db", "zcode_usage_db", "workbuddy_projects_dir",
                    "codex_sessions_dir", "codex_archives_dir", "codex_images_dir", "codex_history_db",
                    "codex_state_db", "claude_projects_dir", "gemini_dir", "claude_desktop_sessions_dir",
                    "mcode_db", "agy_conversations_dir", "agy_desktop_conversations_dir", "dsh_sessions_dir",
                    "design_opencode_db", "kimi_desktop_sessions_dir", "qoder_projects_dir", "history_store"):
            config[key] = empty
        return config

    def test_collector_integration_and_verify(self):
        from agent_meter.verify import verify_snapshot
        config = self._isolated_config()
        snapshot = collect(config, now=NOW)
        src = next(s for s in snapshot["sources"] if s["id"] == "kimi_legacy")
        self.assertEqual(src["status"], "available")
        self.assertIn("kimi_legacy", snapshot["application_usage"])
        report = verify_snapshot(snapshot, config)
        checks = [c for c in report["checks"] if c["name"].startswith("kimi_legacy.")]
        self.assertTrue(checks)
        self.assertTrue(all(c["status"] == "pass" for c in checks),
                        [c for c in checks if c["status"] != "pass"])


if __name__ == "__main__":
    unittest.main()