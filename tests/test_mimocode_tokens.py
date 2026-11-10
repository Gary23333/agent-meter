import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agent_meter.activity import opencode_activities
from agent_meter.collector import collect
from agent_meter.mimocode_tokens import collect_deveco_tokens, collect_mimocode_tokens
from agent_meter.model import SourceError

NOW = datetime(2026, 11, 8, 6, 0, tzinfo=timezone.utc).timestamp()   # 14:00 Beijing
TODAY_MS = int((NOW - 3600) * 1000)
TEN_DAYS_MS = int((NOW - 10 * 86400) * 1000)
FUTURE_MS = int((NOW + 3600) * 1000)


def message(role="assistant", model="mimo-x-pro-preview", tokens=None, total=None):
    data = {"role": role, "modelID": model}
    if tokens is not None:
        data["tokens"] = dict(tokens, total=total if total is not None else
                              tokens["input"] + tokens["output"] + tokens["cache"]["read"] + tokens["cache"]["write"])
    return json.dumps(data)


def tokens(i, o, r=0, read=0, write=0):
    return {"input": i, "output": o, "reasoning": r, "cache": {"read": read, "write": write}}


def make_db(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE message (id TEXT, session_id TEXT, time_created INTEGER, data TEXT)")
    conn.execute("CREATE TABLE session (id TEXT, directory TEXT)")
    conn.execute("INSERT INTO session VALUES ('s1', '/tmp/project-a')")
    conn.executemany("INSERT INTO message VALUES (?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()


class MimocodeTokenTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "mimocode.db"
        make_db(self.db, [
            # reasoning inside output: total matches fresh+output+cache, split it
            ("m1", "s1", TODAY_MS, message(tokens=tokens(100, 50, r=10, read=5, write=2))),
            ("m2", "s1", TODAY_MS, message(model="deepseek-flash", tokens=tokens(10, 5))),
            ("m3", "s1", TEN_DAYS_MS, message(model="mimo-v2.6-pro", tokens=tokens(7, 3))),
            ("m4", "s1", TODAY_MS, message(role="user", tokens=tokens(999, 999))),
            ("m5", "s1", TODAY_MS, message(tokens={"input": -1, "output": 5, "reasoning": 0, "cache": {"read": 0, "write": 0}})),
            ("m6", "s1", FUTURE_MS, message(tokens=tokens(500, 500))),
            ("m7", "s1", TODAY_MS, '{"role":"assistant","tokens": broken'),
        ])

    def tearDown(self):
        self.tmp.cleanup()

    def test_source_contract(self):
        out = collect_mimocode_tokens(self.db, NOW)
        self.assertEqual((out["id"], out["scope"], out["status"]),
                         ("mimo_code", "local_session_history", "available"))
        value = out["metrics"]["tokens"]["value"]
        self.assertEqual(value["coverage"], "mimocode_local_message_db")
        self.assertEqual(value["dedup_rule"], "one_assistant_message_per_response")
        self.assertEqual(value["malformed_token_rows"], 3)
        self.assertEqual(value["peak_split"], "request_timestamp")
        self.assertEqual({g["app"] for g in value["periods"]["all"]["groups"]}, {"mimo_code"})

    def test_totals_and_reasoning_split(self):
        value = collect_mimocode_tokens(self.db, NOW)["metrics"]["tokens"]["value"]
        today = value["periods"]["today"]["totals"]
        self.assertEqual(today["requests"], 2)
        self.assertEqual((today["fresh_input"], today["output"], today["reasoning"],
                          today["cache_read"], today["cache_write"]), (110, 45, 10, 5, 2))
        self.assertEqual(today["total_tokens"], 172)

    def test_period_boundaries(self):
        value = collect_mimocode_tokens(self.db, NOW)["metrics"]["tokens"]["value"]
        self.assertEqual(value["periods"]["7d"]["totals"]["requests"], 2)
        self.assertEqual(value["periods"]["30d"]["totals"]["requests"], 3)
        self.assertEqual(value["periods"]["all"]["totals"]["requests"], 3)
        self.assertEqual(value["periods"]["all"]["totals"]["total_tokens"], 182)

    def test_peak_split_sums_to_parent(self):
        value = collect_mimocode_tokens(self.db, NOW)["metrics"]["tokens"]["value"]
        for period in value["periods"].values():
            totals = period["totals"]
            for field in ("fresh_input", "output", "reasoning", "cache_read", "cache_write", "total_tokens"):
                self.assertEqual(totals["peak"][field] + totals["offpeak"][field], totals[field])

    def test_daily_buckets(self):
        value = collect_mimocode_tokens(self.db, NOW)["metrics"]["tokens"]["value"]
        self.assertEqual(sum(b["tokens"] for b in value["daily_buckets"]), 182)
        self.assertEqual([b["date"] for b in value["daily_buckets"]],
                         sorted(b["date"] for b in value["daily_buckets"]))

    def test_missing_database(self):
        with self.assertRaises(SourceError) as raised:
            collect_mimocode_tokens(Path(self.tmp.name) / "absent.db", NOW)
        self.assertEqual(raised.exception.code, "mimocode_db_not_found")
        with self.assertRaises(SourceError) as raised:
            collect_deveco_tokens(Path(self.tmp.name) / "absent.db", NOW)
        self.assertEqual(raised.exception.code, "deveco_db_not_found")

    def test_unsupported_schema(self):
        bad = Path(self.tmp.name) / "bad.db"
        conn = sqlite3.connect(bad)
        conn.execute("CREATE TABLE message (id TEXT)")
        conn.commit()
        conn.close()
        with self.assertRaises(SourceError) as raised:
            collect_mimocode_tokens(bad, NOW)
        self.assertEqual(raised.exception.code, "unsupported_mimocode_schema")

    def test_deveco_identity(self):
        out = collect_deveco_tokens(self.db, NOW)
        self.assertEqual((out["id"], out["metrics"]["tokens"]["value"]["coverage"]),
                         ("deveco", "deveco_local_message_db"))
        self.assertEqual({g["app"] for g in out["metrics"]["tokens"]["value"]["periods"]["all"]["groups"]},
                         {"deveco"})

    def test_activity_adapter(self):
        rows = opencode_activities(self.db, NOW - 86400, 900, NOW, app="mimo_code",
                                   schema_code="unsupported_mimocode_schema",
                                   missing_code="mimocode_db_not_found",
                                   read_code="mimocode_db_read_failed")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["app"], "mimo_code")
        self.assertEqual(rows[0]["project_path"], "/tmp/project-a")
        self.assertEqual(rows[0]["requests"], 2)
        self.assertEqual(rows[0]["status"], "suspected_ended")

    def _isolated_config(self):
        empty = str(Path(self.tmp.name) / "absent")
        config = {"local_only": True, "app_roots": [], "runtime_dir": str(Path(self.tmp.name) / "runtime"),
                  "mimocode_db": str(self.db), "deveco_db": str(self.db),
                  "enable_reset_forecast": False}
        for key in ("opencode_db", "zcode_usage_db", "workbuddy_projects_dir", "codex_sessions_dir",
                    "codex_archives_dir", "codex_images_dir", "codex_history_db", "codex_state_db",
                    "claude_projects_dir", "gemini_dir", "claude_desktop_sessions_dir", "mcode_db",
                    "agy_conversations_dir", "agy_desktop_conversations_dir", "dsh_sessions_dir",
                    "design_opencode_db", "kimi_desktop_sessions_dir", "qoder_projects_dir", "history_store"):
            config[key] = empty
        return config

    def test_collector_integration_and_switch(self):
        config = self._isolated_config()
        snapshot = collect(config, now=NOW)
        by_id = {s["id"]: s for s in snapshot["sources"]}
        self.assertEqual(by_id["mimo_code"]["status"], "available")
        self.assertEqual(by_id["deveco"]["status"], "available")
        self.assertIn("mimo_code", snapshot["application_usage"])
        rows = {r["application"]["application_id"] for r in snapshot["coverage"]}
        self.assertIn("mimo_code", rows)
        self.assertIn("deveco", rows)
        off = collect(dict(config, disabled_sources=["mimo_code"]), now=NOW)
        src = next(s for s in off["sources"] if s["id"] == "mimo_code")
        self.assertEqual(src["diagnostics"]["reason"], "disabled_in_config")
        user_off = collect(dict(config, preferences={"disabled_sources": ["deveco"]}), now=NOW)
        src = next(s for s in user_off["sources"] if s["id"] == "deveco")
        self.assertEqual(src["diagnostics"]["reason"], "disabled_by_user")

    def test_verify_independent_recompute(self):
        from agent_meter.verify import verify_snapshot
        config = self._isolated_config()
        snapshot = collect(config, now=NOW)
        report = verify_snapshot(snapshot, config)
        checks = [c for c in report["checks"] if c["name"].startswith(("mimo_code.", "deveco."))]
        self.assertTrue(checks)
        self.assertTrue(all(c["status"] == "pass" for c in checks), checks)


if __name__ == "__main__":
    unittest.main()