import json
import os
import plistlib
import tempfile
import time
import unittest
from pathlib import Path

from agent_meter.qoder_watch import app_version, sample_qoder_usage, watch

NOW = 1762600000.0


def assistant(usage=None, role="assistant"):
    return {"type": role, "message": {"role": role, "usage": usage}}


class QoderWatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "projects"
        self.root.mkdir()
        self.state = Path(self.tmp.name) / "state.json"
        self.app = Path(self.tmp.name) / "Qoder CN.app"
        (self.app / "Contents").mkdir(parents=True)
        (self.app / "Contents/Info.plist").write_bytes(
            plistlib.dumps({"CFBundleShortVersionString": "0.5.6"}))
        f = self.root / "a.jsonl"
        f.write_text("\n".join(json.dumps(r) for r in [
            assistant({"credits": "1.5", "input_tokens": 0, "output_tokens": 0}),
            assistant({"credits": "2.0", "input_tokens": 0, "output_tokens": 0}),
            assistant(role="user"),
            {"type": "assistant", "message": {"role": "assistant"}},
        ]) + "\n")
        os.utime(f, (NOW - 3600, NOW - 3600))
        old = self.root / "old.jsonl"
        old.write_text(json.dumps(assistant({"credits": "9", "input_tokens": 999})) + "\n")
        os.utime(old, (NOW - 10 * 86400, NOW - 10 * 86400))

    def tearDown(self):
        self.tmp.cleanup()

    def test_sample_aggregates_only(self):
        stats = sample_qoder_usage(self.root, days=3, now=NOW)
        self.assertEqual(stats["files"], 1)
        self.assertEqual(stats["assistant"], 3)
        self.assertEqual(stats["with_usage"], 2)
        self.assertEqual(stats["with_credits"], 2)
        self.assertEqual(stats["usage_nonzero_tokens"], 0)
        self.assertEqual(stats["token_keys_seen"], ["input_tokens", "output_tokens"])

    def test_missing_dir(self):
        stats = sample_qoder_usage(Path(self.tmp.name) / "absent", now=NOW)
        self.assertTrue(stats["projects_dir_missing"])

    def test_app_version(self):
        self.assertEqual(app_version(self.app), "0.5.6")
        self.assertIsNone(app_version(Path(self.tmp.name) / "nope.app"))

    def test_first_run_no_drift_and_state_saved(self):
        report = watch(self.root, self.app, self.state, now=NOW)
        self.assertEqual(report["drift"], [])
        self.assertIsNone(report["previous"])
        self.assertTrue(self.state.is_file())
        self.assertEqual(json.loads(self.state.read_text())["app_version"], "0.5.6")

    def test_version_change_drift(self):
        watch(self.root, self.app, self.state, now=NOW)
        (self.app / "Contents/Info.plist").write_bytes(
            plistlib.dumps({"CFBundleShortVersionString": "0.6.0"}))
        report = watch(self.root, self.app, self.state, now=NOW)
        self.assertIn("app_version_changed", report["drift"])

    def test_tokens_appeared_drift(self):
        watch(self.root, self.app, self.state, now=NOW)
        f = self.root / "a.jsonl"
        f.write_text(json.dumps(assistant({"credits": "1", "input_tokens": 123})) + "\n")
        os.utime(f, (NOW - 60, NOW - 60))
        report = watch(self.root, self.app, self.state, now=NOW)
        self.assertIn("tokens_appeared", report["drift"])
        self.assertEqual(report["current"]["usage_nonzero_tokens"], 1)

    def test_usage_field_missing_drift(self):
        watch(self.root, self.app, self.state, now=NOW)
        f = self.root / "a.jsonl"
        f.write_text(json.dumps(assistant()) + "\n")
        os.utime(f, (NOW - 60, NOW - 60))
        report = watch(self.root, self.app, self.state, now=NOW)
        self.assertIn("usage_field_missing", report["drift"])


if __name__ == "__main__":
    unittest.main()