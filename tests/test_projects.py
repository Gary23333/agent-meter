import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agent_meter.collector import collect
from agent_meter.projects import project_usage

NOW = datetime(2026, 11, 8, 6, 0, tzinfo=timezone.utc).timestamp()
TS_MS = int((NOW - 3600) * 1000)


def make_opencode_db(path, directory):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE message (id TEXT, session_id TEXT, time_created INTEGER, data TEXT)")
    conn.execute("CREATE TABLE session (id TEXT, directory TEXT)")
    conn.execute("INSERT INTO session VALUES ('s1', ?)", (directory,))
    data = json.dumps({"role": "assistant", "modelID": "glm-5.3-flash",
                       "tokens": {"input": 100, "output": 20, "reasoning": 0,
                                  "cache": {"read": 5, "write": 0}, "total": 125}})
    conn.execute("INSERT INTO message VALUES ('m1', 's1', ?, ?)", (TS_MS, data))
    conn.execute("INSERT INTO message VALUES ('m2', 'no-dir', ?, ?)", (TS_MS, data))
    conn.commit()
    conn.close()


def make_zcode_db(path, directory):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE model_usage (session_id TEXT, provider_id TEXT, model_id TEXT,"
                 " input_tokens INT, output_tokens INT, reasoning_tokens INT,"
                 " cache_creation_input_tokens INT, cache_read_input_tokens INT)")
    conn.execute("CREATE TABLE session (id TEXT, directory TEXT)")
    conn.execute("INSERT INTO session VALUES ('s1', ?)", (directory,))
    conn.execute("INSERT INTO model_usage VALUES ('s1', 'bigmodel', 'GLM-5.3-Flash', 10, 5, 0, 0, 50)")
    conn.commit()
    conn.close()


class ProjectUsageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.oc_db = root / "opencode.db"
        self.zcode_db = root / "zcode.db"
        make_opencode_db(self.oc_db, "/projects/alpha")
        make_zcode_db(self.zcode_db, "/projects/beta")
        empty = str(root / "absent")
        self.config = {"local_only": True, "app_roots": [], "runtime_dir": str(root / "runtime"),
                       "opencode_db": str(self.oc_db), "zcode_usage_db": str(self.zcode_db),
                       "enable_reset_forecast": False}
        for key in ("mimocode_db", "deveco_db", "workbuddy_projects_dir", "codex_sessions_dir",
                    "codex_archives_dir", "codex_images_dir", "codex_history_db", "codex_state_db",
                    "claude_projects_dir", "gemini_dir", "claude_desktop_sessions_dir", "mcode_db",
                    "agy_conversations_dir", "agy_desktop_conversations_dir", "dsh_sessions_dir",
                    "design_opencode_db", "kimi_desktop_sessions_dir", "kimi_legacy_sessions_dir",
                    "qoder_projects_dir", "history_store"):
            self.config[key] = empty

    def tearDown(self):
        self.tmp.cleanup()

    def test_attribution_and_invariant(self):
        snapshot = collect(self.config, now=NOW)
        report = project_usage(self.config, snapshot)
        by_path = {p["project_path"]: p for p in report["projects"]}
        self.assertEqual(set(by_path), {"/projects/alpha", "/projects/beta"})
        # alpha: one attributed message (125); the session-less message stays unattributed
        self.assertEqual(by_path["/projects/alpha"]["tokens"], 125)
        self.assertEqual(by_path["/projects/alpha"]["apps"]["opencode"]["tokens"], 125)
        self.assertEqual(by_path["/projects/beta"]["tokens"], 65)
        self.assertEqual(report["attributed_tokens"], 190)
        self.assertEqual(report["attributed_tokens"] + report["unattributed"]["tokens"],
                         report["total_tokens"])
        self.assertEqual(report["unattributed"]["by_app"]["opencode"]["tokens"], 125)
        self.assertIn("zcode", report["sources_scanned"])
        self.assertIn("opencode", report["sources_scanned"])
        self.assertTrue(any(g["source"] == "deepseek_harness" for g in report["source_gaps"]))

    def test_missing_ledgers_are_gaps_not_zero(self):
        self.config["opencode_db"] = str(Path(self.tmp.name) / "gone.db")
        snapshot = collect(self.config, now=NOW)
        report = project_usage(self.config, snapshot)
        self.assertTrue(any(g["source"] == "opencode" and g["reason"] == "opencode_db_not_found"
                            for g in report["source_gaps"]))
        self.assertEqual(report["attributed_tokens"], 65)


if __name__ == "__main__":
    unittest.main()