import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo
import stat

from agent_meter.model import SourceError
from windows.codex_image_files import image_files
from windows.backend import local_medals, compact_history

NOW = int(datetime(2026, 11, 16, 12, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp())


class CodexImageFileTests(unittest.TestCase):
    def test_counts_files_by_modification_time_without_contents_or_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "PRIVATE_SESSION").mkdir()
            image = root / "PRIVATE_SESSION" / "PRIVATE_NAME.png"
            image.write_bytes(b"not read as image")
            os.utime(image, (NOW - 60, NOW - 60))
            (root / "ignore.jpg").write_bytes(b"ignored")
            with mock.patch("builtins.open", side_effect=AssertionError("不应读取图片内容")):
                result = image_files(root, NOW)
            self.assertEqual(result["status"], "available")
            self.assertEqual(result["value"]["periods"]["today"]["files"], 1)
            self.assertEqual(result["value"]["daily_buckets"], [{"date": "2026-11-16", "images": 1}])
            self.assertNotIn("PRIVATE_", json.dumps(result))
            self.assertNotIn("not read as image", json.dumps(result))

    def test_future_and_scan_limit_mark_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); path = root / "future.png"; path.write_bytes(b"")
            os.utime(path, (NOW + 100, NOW + 100))
            result = image_files(root, NOW)
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["value"]["periods"]["all"]["files"], 0)
            os.utime(path, (NOW - 1, NOW - 1))
            self.assertEqual(image_files(root, NOW, max_files=1)["status"], "partial")
            (root / "nested").mkdir()
            self.assertEqual(image_files(root, NOW, max_dirs=1)["status"], "partial")
        with self.assertRaises(SourceError): image_files(Path(tmp) / "absent", NOW)

    def test_redirected_root_is_not_scanned(self):
        info = SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        with mock.patch.object(Path, "is_dir", return_value=True), mock.patch("windows.codex_image_files.os.stat", return_value=info):
            with self.assertRaises(SourceError) as error:
                image_files(Path("synthetic"), NOW)
        self.assertEqual(error.exception.code, "codex_images_redirected")

    def test_image_only_medals_and_private_projection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index in range(12):
                path = root / ("PRIVATE_" + str(index) + ".png")
                path.write_bytes(b"synthetic-content")
                os.utime(path, (NOW - 60, NOW - 60))
            images = image_files(root, NOW)
            snapshot = {"version": 1, "observed_at": NOW, "account": {"status": "disabled"}, "history": {}, "image_files": images}
            medals = local_medals(snapshot)
            self.assertEqual(medals["image_status"], "available")
            self.assertTrue(next(row for row in medals["medals"] if row["id"] == "img_day_10")["earned"])
            self.assertFalse(any(row["category"].startswith("cost_") for row in medals["medals"]))
            compact = compact_history(snapshot)
            self.assertEqual(compact["image_files"]["value"]["periods"]["all"]["files"], 12)
            self.assertNotIn("PRIVATE_", json.dumps(compact))
            self.assertNotIn("synthetic-content", json.dumps(compact))

    def test_partial_image_scan_never_awards_image_medals(self):
        token = {"status": "available", "value": {"periods": {"all": {"totals": {"requests": 1, "total_tokens": 10}}},
                 "daily_buckets": [{"date": "2026-11-16", "tokens": 10}]}}
        image = {"status": "partial", "value": {"basis": "codex_generated_images_png_files",
                 "periods": {"all": {"files": 99}}, "daily_buckets": [{"date": "2026-11-16", "images": 99}]}}
        result = local_medals({"observed_at": NOW, "history": {"Codex": token}, "image_files": image})
        self.assertEqual(result["image_status"], "incomplete")
        self.assertFalse(any(row["category"].startswith("img_") for row in result["medals"]))
