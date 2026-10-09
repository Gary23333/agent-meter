"""Hermetic tests for the Antigravity CLI (agy) token reader.

Fixtures build protobuf blobs with a tiny hand-rolled encoder, mirroring
the shapes decoded from the real databases (agy 1.3.2, 2026-10-09).
"""
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from agent_meter.agy_tokens import collect_antigravity_sessions
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


def usage(total_input, output, thinking=None):
    body = varint_field(1, 1319) + varint_field(2, total_input) + varint_field(3, output)
    body += varint_field(6, 24)  # the unidentified constant
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
            (1, step_metadata(t(9), usage(12000, 100))),
            (3, step_metadata(t(9, 11), usage(15000, 200, thinking=80))),
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
            self.assertEqual(out["scope"], "local_session_history")
            value = out["metrics"]["tokens"]["value"]
            allp = value["periods"]["all"]["totals"]
            self.assertEqual((allp["requests"], allp["fresh_input"], allp["output"], allp["reasoning"]),
                             (3, 27500, 305, 80))
            self.assertIsNone(allp["cache_hit_rate"])
            groups = {g["model"]: g for g in value["periods"]["all"]["groups"]}
            self.assertEqual(groups["gemini-3.8-flash"]["requests"], 2)
            self.assertEqual(groups["gemini-3.7-flash"]["requests"], 1)
            self.assertEqual(value["skipped_conversation_dbs"], 1)
            self.assertEqual(value["ccswitch_overlap"]["state"], "ccswitch_absent")
            # Period split: day 8 record is outside "today".
            self.assertEqual(value["periods"]["today"]["totals"]["requests"], 2)
            self.assertEqual([b["tokens"] for b in value["daily_buckets"]],
                             [505, 12000 + 100 + 15000 + 200 + 80])
            # Re-collect uses the per-file cache without changing results.
            again = collect_antigravity_sessions(root, Path(tmp) / "none.db", NOW, ZONE)
            self.assertEqual(again["metrics"]["tokens"]["value"]["periods"]["all"]["totals"], allp)

    def test_missing_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SourceError) as ctx:
                collect_antigravity_sessions(Path(tmp) / "none", Path(tmp) / "none.db", NOW, ZONE)
            self.assertEqual(ctx.exception.code, "agy_conversations_not_found")


if __name__ == "__main__":
    unittest.main()
