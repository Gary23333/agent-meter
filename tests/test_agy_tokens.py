"""Hermetic tests for the Antigravity CLI/desktop token reader.

Fixtures build protobuf blobs with a tiny hand-rolled encoder, mirroring
the shapes decoded from the real databases (agy 1.3.2, 2026-10-09).
"""
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from agent_meter.agy_tokens import collect_antigravity_sessions, load_antigravity_roots
from agent_meter.model import SourceError

NOW = int(datetime(2026, 10, 9, 4, 0, tzinfo=timezone.utc).timestamp())
ZONE = ZoneInfo("Asia/Shanghai")


def pv(value):
    """Encode a varint."""
    out = bytearray()
    while True:
        b = value & 0x7F
        value >>= 7
        if value:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def varint_field(fn, value):
    return pv(fn << 3) + pv(value)


def bytes_field(fn, payload):
    return pv(fn << 3 | 2) + pv(len(payload)) + payload


def timestamp(seconds):
    return bytes_field(1, varint_field(1, seconds))


def usage(total_input, output, thinking=None, cache_read=None):
    body = varint_field(1, 1319) + varint_field(2, total_input) + varint_field(3, output)
    body += varint_field(6, 24)  # the unidentified constant
    if cache_read is not None:
        body += varint_field(5, cache_read)
    if thinking is not None:
        body += varint_field(9, thinking)
    return bytes_field(9, body)


def step_metadata(seconds, usage_blob):
    return timestamp(seconds) + usage_blob


def gen_metadata(model):
    return bytes_field(1, bytes_field(19, model.encode()))


def conversation(db_path, steps, models):
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE steps(idx INTEGER PRIMARY KEY, step_type INTEGER, status INTEGER,"
                 " has_subtrajectory NUMERIC, metadata BLOB, error_details BLOB, permissions BLOB,"
                 " task_details BLOB, render_info BLOB, step_payload BLOB, step_format INTEGER)")
    conn.execute("CREATE TABLE gen_metadata(idx INTEGER PRIMARY KEY, data BLOB, size INTEGER)")
    seq = 0
    for idx, meta in steps:
        conn.execute("INSERT INTO steps(idx, step_type, status, metadata) VALUES(?, 15, 3, ?)", (idx, meta))
        model = models[seq] if seq < len(models) else None
        blob = gen_metadata(model) if model else None
        conn.execute("INSERT INTO gen_metadata(idx, data, size) VALUES(?, ?, ?)",
                     (seq, blob, len(blob) if blob else 0))
        seq += 1
    conn.commit()
    conn.close()


class AntigravityTests(unittest.TestCase):
    def fixture(self, tmp):
        root = Path(tmp) / "conversations"
        root.mkdir()
        t = lambda d, h=10: int(datetime(2026, 10, d, h, tzinfo=ZONE).timestamp())
        conversation(root / "a.db", [
            (1, step_metadata(t(9), usage(12000, 100, cache_read=3000))),
            (3, step_metadata(t(9, 11), usage(15000, 200, thinking=80, cache_read=5000))),
            (5, step_metadata(t(8), usage(500, 5))),
        ], ["gemini-3.8-flash", "gemini-3.8-flash", "gemini-3.7-flash"])
        # A non-LLM step must be ignored; a usage-less LLM step too.
        conn = sqlite3.connect(root / "a.db")
        conn.execute("INSERT INTO steps(idx, step_type, status, metadata) VALUES(2, 132, 3, NULL)")
        conn.execute("INSERT INTO steps(idx, step_type, status, metadata) VALUES(7, 15, 3, ?)",
                     (timestamp(t(9, 12)),))  # no usage blob
        conn.commit()
        conn.close()
        # An unparseable db is skipped, not fatal.
        (root / "broken.db").write_bytes(b"not a database")
        return root

    def test_usage_thinking_model_and_dedup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.fixture(tmp)
            out = collect_antigravity_sessions(root, Path(tmp) / "none.db", NOW, ZONE)
            self.assertEqual(out["scope"], "account")
            value = out["metrics"]["tokens"]["value"]
            allp = value["periods"]["all"]["totals"]
            self.assertEqual((allp["requests"], allp["fresh_input"], allp["output"],
                              allp["reasoning"], allp["cache_read"]),
                             (3, 27500, 305, 80, 8000))
            self.assertAlmostEqual(allp["cache_hit_rate"], 8000 / 35500)
            self.assertEqual(value["cache_semantics"], "f5_cache_read_verified_cache_write_absent")
            groups = {g["model"]: g for g in value["periods"]["all"]["groups"]}
            self.assertEqual(groups["gemini-3.8-flash"]["requests"], 2)
            self.assertEqual(groups["gemini-3.8-flash"]["cache_read"], 8000)
            self.assertEqual(groups["gemini-3.7-flash"]["requests"], 1)
            self.assertEqual(value["skipped_conversation_dbs"], 1)
            self.assertEqual(value["ccswitch_overlap"]["state"], "ccswitch_absent")
            self.assertEqual(out["diagnostics"]["roots_declared"], 1)
            self.assertEqual(out["diagnostics"]["roots_present"], 1)
            self.assertEqual(out["diagnostics"]["duplicate_conversation_ids"], 0)
            # Period split: day 8 record is outside "today".
            self.assertEqual(value["periods"]["today"]["totals"]["requests"], 2)
            self.assertEqual([b["tokens"] for b in value["daily_buckets"]],
                             [505, 12000 + 100 + 3000 + 15000 + 200 + 80 + 5000])
            # Re-collect uses the per-file cache without changing results.
            again = collect_antigravity_sessions(root, Path(tmp) / "none.db", NOW, ZONE)
            self.assertEqual(again["metrics"]["tokens"]["value"]["periods"]["all"]["totals"], allp)

    def test_missing_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SourceError) as ctx:
                collect_antigravity_sessions(Path(tmp) / "none", Path(tmp) / "none.db", NOW, ZONE)
            self.assertEqual(ctx.exception.code, "agy_conversations_not_found")

    def test_all_roots_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SourceError) as ctx:
                load_antigravity_roots([Path(tmp) / "cli", Path(tmp) / "desktop"])
            self.assertEqual(ctx.exception.code, "agy_conversations_not_found")

    def test_dual_roots_dedupe_by_conversation_uuid(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli, desktop = Path(tmp) / "cli", Path(tmp) / "desktop"
            cli.mkdir()
            desktop.mkdir()
            t = lambda d, h=10: int(datetime(2026, 10, d, h, tzinfo=ZONE).timestamp())
            conversation(cli / "same-uuid.db",
                         [(1, step_metadata(t(9), usage(1000, 10)))], ["gemini-3.8-flash"])
            conversation(desktop / "same-uuid.db",
                         [(1, step_metadata(t(9), usage(2000, 20))),
                          (3, step_metadata(t(9, 11), usage(3000, 30)))],
                         ["gemini-3.8-flash", "gemini-3.8-flash"])
            os.utime(cli / "same-uuid.db", (1000, 1000))
            os.utime(desktop / "same-uuid.db", (2000, 2000))
            records, skipped, diagnostics = load_antigravity_roots([cli, desktop])
            self.assertEqual(len(records), 2)  # the newer, larger desktop copy
            self.assertEqual(skipped, 0)
            self.assertEqual(diagnostics, {"roots_declared": 2, "roots_present": 2,
                                           "duplicate_conversation_ids": 1})

    def test_dedupe_prefers_newer_then_larger(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli, desktop = Path(tmp) / "cli", Path(tmp) / "desktop"
            cli.mkdir()
            desktop.mkdir()
            t = lambda d, h=10: int(datetime(2026, 10, d, h, tzinfo=ZONE).timestamp())
            conversation(cli / "same.db", [(1, step_metadata(t(9), usage(1000, 10)))],
                         ["gemini-3.8-flash"])
            conversation(desktop / "same.db",
                         [(7, step_metadata(t(9), usage(2000, 20))),
                          (9, step_metadata(t(9, 11), usage(3000, 30)))],
                         ["gemini-3.8-flash", "gemini-3.8-flash"])
            os.utime(cli / "same.db", (3000, 3000))  # newer but smaller copy wins
            os.utime(desktop / "same.db", (2000, 2000))
            records, _skipped, diagnostics = load_antigravity_roots([cli, desktop])
            self.assertEqual(len(records), 1)
            self.assertEqual(diagnostics["duplicate_conversation_ids"], 1)

    def test_missing_desktop_root_still_reads_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.fixture(tmp)
            records, skipped, diagnostics = load_antigravity_roots([Path(tmp) / "none", root])
            self.assertTrue(records)
            self.assertEqual(diagnostics["roots_present"], 1)
            self.assertEqual(diagnostics["duplicate_conversation_ids"], 0)
            self.assertEqual(skipped, 2)  # the missing root + the broken db

    def test_collect_with_desktop_root_and_legacy_overlap_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.fixture(tmp)
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            t = lambda d, h=10: int(datetime(2026, 10, d, h, tzinfo=ZONE).timestamp())
            conversation(desktop / "b.db", [(1, step_metadata(t(9), usage(4000, 40)))],
                         ["gemini-3.8-flash"])
            db = Path(tmp) / "ccswitch.db"
            conn = sqlite3.connect(db)
            conn.execute("CREATE TABLE proxy_request_logs(created_at REAL, app_type TEXT)")
            conn.execute("PRAGMA user_version=24")
            conn.execute("INSERT INTO proxy_request_logs VALUES(?, 'agy')", (t(9),))
            conn.execute("INSERT INTO proxy_request_logs VALUES(?, 'antigravity')", (t(8),))
            conn.commit()
            conn.close()

            plain = collect_antigravity_sessions(root, db, NOW, ZONE, desktop_root=desktop)
            self.assertEqual(plain["diagnostics"]["roots_present"], 2)
            value = plain["metrics"]["tokens"]["value"]
            # Direct-primary: CC Switch's partial agy import must not hide
            # the complete conversation ledger.
            self.assertEqual(value["periods"]["all"]["totals"]["requests"], 4)
            self.assertEqual(value["ccswitch_overlap"]["state"], "checked")
            self.assertEqual(value["ccswitch_overlap"]["excluded_days"], [])
            self.assertTrue(value["ccswitch_overlap"]["direct_primary"])
            self.assertEqual(value["ccswitch_overlap"]["observed_imported_days"],
                             ["2026-10-08", "2026-10-09"])


if __name__ == "__main__":
    unittest.main()
