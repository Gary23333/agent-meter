import tempfile
import unittest
from pathlib import Path

from agent_meter.collector import SnapshotService, collect
from agent_meter.status import collection_status

NOW = 1762600000.0


def isolated_config(tmp, **extra):
    empty = str(Path(tmp) / "absent")
    config = {"local_only": True, "app_roots": [], "runtime_dir": str(Path(tmp) / "runtime"),
              "enable_reset_forecast": False}
    for key in ("opencode_db", "mimocode_db", "deveco_db", "zcode_usage_db", "workbuddy_projects_dir",
                "codex_sessions_dir", "codex_archives_dir", "codex_images_dir", "codex_history_db",
                "codex_state_db", "claude_projects_dir", "gemini_dir", "claude_desktop_sessions_dir",
                "mcode_db", "agy_conversations_dir", "agy_desktop_conversations_dir", "dsh_sessions_dir",
                "design_opencode_db", "kimi_desktop_sessions_dir", "kimi_legacy_sessions_dir",
                "qoder_projects_dir", "history_store"):
        config[key] = empty
    config.update(extra)
    return config


class LowResourceTests(unittest.TestCase):
    def test_skip_ledgers_only_in_low_resource_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefs = {"low_resource_mode": True, "skip_ledgers_low_resource": ["opencode", "gemini"]}
            snapshot = collect(isolated_config(tmp, preferences=prefs), now=NOW)
            by_id = {s["id"]: s for s in snapshot["sources"]}
            self.assertEqual(by_id["opencode"]["diagnostics"]["reason"], "skipped_low_resource")
            self.assertEqual(by_id["gemini"]["diagnostics"]["reason"], "skipped_low_resource")
            self.assertEqual(by_id["mimo_code"]["diagnostics"]["reason"], "mimocode_db_not_found")
            prefs_off = {"low_resource_mode": False, "skip_ledgers_low_resource": ["opencode"]}
            snapshot2 = collect(isolated_config(tmp, preferences=prefs_off), now=NOW)
            by_id2 = {s["id"]: s for s in snapshot2["sources"]}
            self.assertEqual(by_id2["opencode"]["diagnostics"]["reason"], "opencode_db_not_found")

    def test_disabled_wins_over_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefs = {"low_resource_mode": True, "skip_ledgers_low_resource": ["opencode"],
                     "disabled_sources": ["opencode"]}
            snapshot = collect(isolated_config(tmp, preferences=prefs), now=NOW)
            src = next(s for s in snapshot["sources"] if s["id"] == "opencode")
            self.assertEqual(src["diagnostics"]["reason"], "disabled_by_user")

    def test_ttl_tripled_in_low_resource(self):
        clock = [NOW]
        calls = []

        def fake_collect(config, now=None):
            calls.append(now)
            return {"schema_version": 5, "collected_at": {"epoch_seconds": now}, "sources": [],
                    "coverage": [], "coverage_summary": {}, "application_usage": {}}

        with tempfile.TemporaryDirectory() as tmp:
            service = SnapshotService(isolated_config(tmp, cache_ttl_seconds=100,
                                                      preferences={"low_resource_mode": True}),
                                      collect_fn=fake_collect, clock=lambda: clock[0])
            service.get()
            clock[0] = NOW + 150
            service.get()
            self.assertEqual(len(calls), 1)   # 150 < 300 TTL: still cached
            clock[0] = NOW + 350
            service.get()
            self.assertEqual(len(calls), 2)


class StatusPayloadTests(unittest.TestCase):
    def test_projection(self):
        snapshot = {"collected_at": {"epoch_seconds": NOW}, "served_from_cache": True, "sources": [
            {"id": "codex", "scope": "account", "status": "stale",
             "observed_at": {"epoch_seconds": NOW - 60},
             "diagnostics": {"reason": "rpc_timeout", "last_error": "rpc_timeout"},
             "metrics": {"cost": {"value": {"periods": {"today": {"unmatched_models": ["mystery-x"]}}}}}},
            {"id": "opencode", "scope": "local_session_history", "status": "available",
             "observed_at": {"epoch_seconds": NOW}, "diagnostics": {"reason": None}, "metrics": {}},
        ]}
        config = {"cache_ttl_seconds": 120, "disabled_sources": ["claude"],
                  "preferences": {"low_resource_mode": True, "skip_ledgers_low_resource": ["gemini"],
                                  "disabled_sources": ["forecast"]}}
        out = collection_status(snapshot, config, NOW)
        self.assertTrue(out["low_resource_mode"])
        self.assertEqual(out["skipped_ledgers"], ["gemini"])
        self.assertEqual(out["stale_sources"], ["codex"])
        self.assertEqual(out["unpriced_models"], ["mystery-x"])
        self.assertEqual(out["disabled_sources"], ["claude", "forecast"])
        self.assertTrue(out["served_from_cache"])
        self.assertEqual(len(out["sources"]), 2)

    def test_skip_list_hidden_when_mode_off(self):
        out = collection_status({"sources": []}, {"preferences": {"skip_ledgers_low_resource": ["gemini"]}}, NOW)
        self.assertFalse(out["low_resource_mode"])
        self.assertEqual(out["skipped_ledgers"], [])


if __name__ == "__main__":
    unittest.main()