import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from agent_meter.codex_images import (codex_image_metric, estimate_cost_usd, find_history_db,
                                      read_history_statuses, resolve_quality, scan_image_files)
from agent_meter.model import SourceError, source, timestamp
from agent_meter.verify import verify_snapshot

ZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 10, 29, 12, 0, tzinfo=ZONE).timestamp()


def png_header(width, height):
    """最小 PNG 头（签名 + IHDR 宽高 + 4 字节 CRC 占位），够头部解析器用。"""
    ihdr = width.to_bytes(4, "big") + height.to_bytes(4, "big") + b"\x08\x06\x00\x00\x00"
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0d" + b"IHDR" + ihdr + b"\x00\x00\x00\x00"


def write_png(path, width, height, mtime):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png_header(width, height))
    os.utime(path, (mtime, mtime))


def make_history(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript("CREATE TABLE thread_items (item_type TEXT, created_at_ms INTEGER, item_json TEXT);")
    for created_ms, status in rows:
        conn.execute("INSERT INTO thread_items VALUES ('imageGeneration',?,?)",
                     (created_ms, '{"status":"%s","result":"base64-placeholder"}' % status))
    conn.execute("INSERT INTO thread_items VALUES ('message',0,'{\"status\":\"completed\"}')")
    conn.commit()
    conn.close()
    return path


def day_at(days_ago, hour):
    base = datetime(2026, 10, 29, tzinfo=ZONE) - timedelta(days=days_ago)
    return base.replace(hour=hour).timestamp()


class CostFormulaTests(unittest.TestCase):
    def test_high_square_and_wide_exact_values(self):
        self.assertEqual(estimate_cost_usd(1024, 1024), Decimal("0.052680"))
        self.assertEqual(estimate_cost_usd(1536, 1024), Decimal("0.041160"))
        # 2048x2048 是 1024x1024 的 4 倍面积。
        self.assertEqual(estimate_cost_usd(2048, 2048), Decimal("0.210720"))

    def test_area_scaling_inside_square_band(self):
        # 1100x1000 比例 1.1，仍按方形基准按面积缩放。
        tokens = Decimal(1756) * Decimal(1100 * 1000) / Decimal(1024 * 1024)
        expected = (tokens * Decimal(30) / Decimal(1000000)).quantize(Decimal("0.000001"))
        self.assertEqual(estimate_cost_usd(1100, 1000), expected)

    def test_quality_table_and_invalid_fallback(self):
        self.assertEqual(estimate_cost_usd(1024, 1024, "low"), Decimal("0.005880"))
        self.assertEqual(estimate_cost_usd(1024, 1024, "max"), Decimal("0.210720"))
        self.assertEqual(resolve_quality("MAX"), "max")
        self.assertNotEqual(resolve_quality("ultra"), "ultra")
        self.assertEqual(estimate_cost_usd(1024, 1024, "ultra"), estimate_cost_usd(1024, 1024, "high"))

    def test_invalid_dimensions_rejected(self):
        for args in ((0, 1024), (1024, -1), (True, 1024)):
            with self.assertRaises(SourceError):
                estimate_cost_usd(*args)


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_scan_reads_headers_and_reports_unreadable(self):
        write_png(self.root / "thread-a" / "exec-1.png", 1024, 1024, day_at(0, 9))
        write_png(self.root / "thread-a" / "exec-2.png", 1536, 1024, day_at(0, 10))
        (self.root / "thread-b").mkdir()
        (self.root / "thread-b" / "ig_1.png").write_bytes(b"not a png at all")
        os.utime(self.root / "thread-b" / "ig_1.png", (day_at(0, 11),) * 2)
        (self.root / "thread-b" / "note.txt").write_text("ignored")
        records = scan_image_files(self.root)
        self.assertEqual(len(records), 3)
        self.assertIn((None, None), [(w, h) for _, w, h in records])
        epochs = sorted(epoch for epoch, _, _ in records)
        for actual, expected in zip(epochs, sorted([day_at(0, 9), day_at(0, 10), day_at(0, 11)])):
            self.assertAlmostEqual(actual, expected, places=3)

    def test_scan_cache_uses_mtime_and_size(self):
        path = self.root / "thread-a" / "exec-1.png"
        write_png(path, 1024, 1024, day_at(0, 9))
        first = scan_image_files(self.root)
        write_png(path, 2048, 2048, day_at(0, 10))
        second = scan_image_files(self.root)
        self.assertEqual(first[0][1:], (1024, 1024))
        self.assertEqual(second[0][1:], (2048, 2048))


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_find_latest_thread_history_with_glob(self):
        older = make_history(self.root / "thread_history_1.sqlite", [])
        newer = make_history(self.root / "thread_history_7.sqlite", [])
        os.utime(older, (1000, 1000))
        os.utime(newer, (2000, 2000))
        (self.root / "thread_history_7.sqlite-wal").write_bytes(b"x")
        os.utime(self.root / "thread_history_7.sqlite-wal", (5000, 5000))
        self.assertEqual(find_history_db(self.root), newer)

    def test_read_statuses_filters_item_type(self):
        db = make_history(self.root / "thread_history_1.sqlite",
                          [(1000, "completed"), (2000, "failed")])
        statuses = read_history_statuses(db)
        self.assertEqual(statuses, [(1000, "completed"), (2000, "failed")])

    def test_unreadable_db_returns_none(self):
        bad = self.root / "thread_history_1.sqlite"
        bad.write_bytes(b"this is not sqlite")
        self.assertIsNone(read_history_statuses(bad))


class MetricTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.images = self.root / ".codex" / "generated_images"
        self.images.mkdir(parents=True)
        write_png(self.images / "t1" / "exec-1.png", 1024, 1024, day_at(0, 9))
        write_png(self.images / "t1" / "exec-2.png", 1536, 1024, day_at(0, 10))
        write_png(self.images / "t2" / "exec-3.png", 1024, 1024, day_at(3, 10))
        write_png(self.images / "t3" / "ig_1.png", 1024, 1024, day_at(20, 10))
        write_png(self.images / "t4" / "ig_2.png", 1024, 1024, day_at(40, 10))
        (self.images / "t5").mkdir()
        (self.images / "t5" / "exec-4.png").write_bytes(b"corrupted")
        os.utime(self.images / "t5" / "exec-4.png", (day_at(0, 11),) * 2)
        self.db = make_history(self.root / ".codex" / "thread_history_1.sqlite", [
            (int(day_at(0, 8) * 1000), "completed"),
            (int(day_at(0, 9) * 1000), "failed"),
            (int(day_at(3, 9) * 1000), "generating"),
            (int(day_at(20, 9) * 1000), "completed"),
            (int(day_at(40, 9) * 1000), "completed"),
        ])

    def tearDown(self):
        self.tmp.cleanup()

    def test_period_counts_costs_and_calls(self):
        out = codex_image_metric(self.images, self.db, NOW)
        self.assertEqual(out["status"], "available")
        self.assertEqual(out["value"]["basis"], "codex_builtin_image_gen_files")
        self.assertEqual(out["value"]["quality_assumption"], "high")
        self.assertEqual(out["value"]["currency"], "USD")
        self.assertFalse(out["value"]["converted_from_usd"])
        self.assertIsNone(out["value"]["fx_note"])
        self.assertEqual(out["value"]["coverage"], "codex_generated_images_and_thread_history")
        self.assertEqual(out["value"]["unreadable_images"], 1)
        self.assertEqual(out["value"]["timezone"], "Asia/Shanghai")
        periods = out["value"]["periods"]
        self.assertEqual(periods["today"],
                         {"images": 3, "calls": 2, "failed_calls": 1, "generating_calls": 0,
                          "estimated_cost": "0.093840"})
        # 坏 PNG 计入张数、成本跳过。
        self.assertEqual(periods["7d"],
                         {"images": 4, "calls": 3, "failed_calls": 1, "generating_calls": 1,
                          "estimated_cost": "0.146520"})
        self.assertEqual(periods["30d"],
                         {"images": 5, "calls": 4, "failed_calls": 1, "generating_calls": 1,
                          "estimated_cost": "0.199200"})
        self.assertEqual(periods["all"],
                         {"images": 6, "calls": 5, "failed_calls": 1, "generating_calls": 1,
                          "estimated_cost": "0.251880"})

    def test_daily_buckets_sorted_and_complete(self):
        out = codex_image_metric(self.images, self.db, NOW)
        buckets = out["value"]["daily_buckets"]
        dates = [b["date"] for b in buckets]
        self.assertEqual(dates, sorted(dates))
        self.assertEqual(len(buckets), 4)
        today = next(b for b in buckets if b["date"] == "2026-10-29")
        self.assertEqual(today, {"date": "2026-10-29", "images": 3, "estimated_cost": "0.093840"})

    def test_cny_conversion(self):
        out = codex_image_metric(self.images, self.db, NOW, currency="CNY")
        self.assertEqual(out["value"]["currency"], "CNY")
        self.assertTrue(out["value"]["converted_from_usd"])
        self.assertEqual(out["value"]["fx_note"], "converted_at_7.25")
        # 0.05268 * 7.25 = 0.381930
        self.assertEqual(out["value"]["periods"]["today"]["estimated_cost"],
                         format(Decimal("0.09384") * Decimal("7.25"), ".6f"))

    def test_history_unavailable_degrades_to_partial(self):
        out = codex_image_metric(self.images, self.root / "missing" / "thread_history_1.sqlite", NOW)
        self.assertEqual(out["status"], "partial")
        self.assertEqual(out["reason"], "codex_history_unavailable")
        self.assertFalse(out["value"]["call_counts_available"])
        self.assertEqual(out["value"]["coverage"], "codex_generated_images")
        for period in out["value"]["periods"].values():
            self.assertEqual((period["calls"], period["failed_calls"], period["generating_calls"]), (0, 0, 0))
        self.assertEqual(out["value"]["periods"]["all"]["images"], 6)

    def test_missing_images_dir_raises(self):
        with self.assertRaises(SourceError) as ctx:
            codex_image_metric(self.root / "nope", self.db, NOW)
        self.assertEqual(ctx.exception.code, "codex_images_not_found")

    def test_empty_dir_is_available_with_zero_images(self):
        empty = self.root / "empty"
        empty.mkdir()
        out = codex_image_metric(empty, self.db, NOW)
        self.assertEqual(out["status"], "available")
        self.assertEqual(out["value"]["periods"]["all"]["images"], 0)
        self.assertEqual(out["value"]["periods"]["all"]["estimated_cost"], "0.000000")
        self.assertEqual(out["value"]["daily_buckets"], [])

    def test_quality_config_changes_cost(self):
        low = codex_image_metric(self.images, self.db, NOW, quality="low")
        self.assertEqual(low["value"]["quality_assumption"], "low")
        self.assertEqual(low["value"]["periods"]["today"]["estimated_cost"], "0.010620")

    def test_verify_recomputes_both_file_and_call_counts(self):
        out = codex_image_metric(self.images, self.db, NOW)
        src = source("codex", "account", NOW)
        src["metrics"]["image_generation"] = out
        snapshot = {"collected_at": timestamp(NOW), "sources": [src], "coverage": []}
        report = verify_snapshot(snapshot, {"codex_images_dir": str(self.images),
                                            "codex_history_db": str(self.db)})
        names = {c["name"] for c in report["checks"]}
        self.assertIn("codex.image_generation.all.images", names)
        self.assertIn("codex.image_generation.all.estimated_cost", names)
        self.assertIn("codex.image_generation.all.calls", names)
        self.assertEqual(report["failed_checks"], 0)

    def test_resolve_history_db_falls_back_to_glob(self):
        from agent_meter.codex_images import resolve_history_db
        moved = self.root / ".codex" / "thread_history_9.sqlite"
        os.replace(self.db, moved)
        self.assertEqual(resolve_history_db(self.root / ".codex" / "thread_history_1.sqlite"), moved)


if __name__ == "__main__":
    unittest.main()
