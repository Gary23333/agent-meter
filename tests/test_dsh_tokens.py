"""Hermetic tests for the DeepSeek Harness (dsh) local token reader.

Fixtures are zstd-compressed JSONL in temporary directories; nothing reads
the real ~/.dsh. Compression uses the same route the reader prefers on this
machine (stdlib compression.zstd, else the zstd CLI).
"""
import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from agent_meter import dsh_tokens
from agent_meter.collector import collect
from agent_meter.dsh_tokens import collect_dsh_sessions
from agent_meter.model import SourceError

# 2026-10-09 12:00 +08:00 — same convention as the other suites.
NOW = int(datetime(2026, 10, 9, 4, 0, tzinfo=timezone.utc).timestamp())
ZONE = ZoneInfo("Asia/Shanghai")
LOCAL_TODAY = "2026-10-09"
ROUTE = dsh_tokens._route(shutil.which("zstd"))


def write_zstd(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = ("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n").encode()
    if dsh_tokens._HAS_STDLIB_ZSTD:
        path.write_bytes(dsh_tokens._zstd.compress(data))
    else:
        with open(path, "wb") as handle:
            subprocess.run([shutil.which("zstd"), "-zc"], input=data, stdout=handle, check=True)


def v3_message(ms, turn, step, model, inp, out, reasoning=0, cache_read=0, stream_copy=False):
    usage = {"inputTokens": inp, "outputTokens": out, "cacheReadTokens": cache_read,
             "reasoningTokens": reasoning, "totalTokens": inp + out + cache_read}
    data = {"turn": turn, "step": step, "usage": usage,
            "message": {"source": {"model": model}}}
    if stream_copy:
        data["stream"] = [{"type": "usage", "usage": dict(usage)}]
    return {"type": "assistant/message", "time": ms, "data": data}


def legacy_chunk(ms, turn, step, inp, out, reasoning=0, cache_read=0):
    return {"type": "assistant/chunk", "time": ms,
            "data": {"turn": turn, "step": step,
                     "chunk": {"usage": {"inputTokens": inp, "outputTokens": out,
                                          "cacheReadTokens": cache_read, "reasoningTokens": reasoning}}}}


def legacy_final(ms, turn, step, inp, out, reasoning=0, cache_read=0):
    return {"type": "assistant/message", "time": ms,
            "data": {"turn": turn, "step": step,
                     "usage": {"inputTokens": inp, "outputTokens": out,
                               "cacheReadTokens": cache_read, "reasoningTokens": reasoning}}}


def legacy_header(ms, model):
    return {"type": "request/header", "time": ms,
            "data": {"header": {"config": {"model": model}}}}


def ms_at(day, hour=10, minute=0):
    return int(datetime(2026, 10, day, hour, minute, tzinfo=ZONE).timestamp() * 1000)


def sessions_root(tmp, name="sessions"):
    return Path(tmp) / name


def totals(out, period="all"):
    return out["metrics"]["tokens"]["value"]["periods"][period]["totals"]


class DshTokenTests(unittest.TestCase):
    def test_v3_totals_models_and_stream_not_double_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = sessions_root(tmp) / "proj" / "s1"
            write_zstd(root / "session.v3.jsonl.zstd", [
                v3_message(ms_at(9), 1, 1, "mimo-v2.5-pro", 100, 40, reasoning=10, cache_read=200),
                v3_message(ms_at(9, 11), 1, 2, "mimo-v2.5-pro", 50, 30, reasoning=5, stream_copy=True),
                v3_message(ms_at(8), 2, 1, "deepseek-v4-flash", 10, 3, reasoning=1, cache_read=7),
            ])
            out = collect_dsh_sessions(sessions_root(tmp), Path(tmp) / "none.db", NOW, ZONE)
            self.assertEqual((out["id"], out["scope"]), ("deepseek_harness", "local_session_history"))
            allp = totals(out)
            # fresh 160; output (40-10)+(30-5)+(3-1)=57; reasoning 16; read 207 — stream copy not re-counted.
            self.assertEqual((allp["requests"], allp["fresh_input"], allp["output"],
                              allp["reasoning"], allp["cache_read"], allp["cache_write"]),
                             (3, 160, 57, 16, 207, 0))
            self.assertEqual(allp["total_tokens"], 440)
            groups = {g["model"]: g for g in out["metrics"]["tokens"]["value"]["periods"]["all"]["groups"]}
            self.assertTrue(all(g["app"] == "dsh" for g in groups.values()))
            self.assertEqual((groups["mimo-v2.5-pro"]["requests"], groups["mimo-v2.5-pro"]["total_tokens"]),
                             (2, 420))
            self.assertEqual(groups["deepseek-v4-flash"]["total_tokens"], 20)
            diag = out["diagnostics"]
            self.assertEqual((diag["v3_session_files"], diag["legacy_session_files"],
                              diag["skipped_session_files"]), (1, 0, 0))
            self.assertEqual(diag["decompression_route"], ROUTE)
            self.assertEqual(out["metrics"]["tokens"]["value"]["dedup_rule"], "last_usage_per_turn_step")
            self.assertEqual(out["metrics"]["tokens"]["value"]["coverage"], "dsh_local_session_logs")
            self.assertEqual(totals(out, "today")["requests"], 2)
            self.assertEqual([b["tokens"] for b in out["metrics"]["tokens"]["value"]["daily_buckets"]],
                             [20, 420])

    def test_v3_dedup_keeps_last_usage_per_turn_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = sessions_root(tmp) / "p" / "s"
            write_zstd(root / "session.v3.jsonl.zstd", [
                v3_message(ms_at(9, 10), 1, 1, "m", 100, 40, reasoning=10, cache_read=200),
                v3_message(ms_at(9, 11), 1, 1, "m", 150, 45, reasoning=5, cache_read=210),  # later wins
            ])
            out = collect_dsh_sessions(sessions_root(tmp), Path(tmp) / "none.db", NOW, ZONE)
            allp = totals(out)
            self.assertEqual((allp["requests"], allp["fresh_input"], allp["cache_read"]), (1, 150, 210))

    def test_v3_model_falls_back_to_request_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = sessions_root(tmp) / "p" / "s"
            write_zstd(root / "session.v3.jsonl.zstd", [
                legacy_header(ms_at(9, 9), "deepseek-v4-pro"),
                {"type": "assistant/message", "time": ms_at(9),
                 "data": {"turn": 1, "step": 1,
                          "usage": {"inputTokens": 1, "outputTokens": 2, "cacheReadTokens": 0,
                                    "reasoningTokens": 0, "totalTokens": 3}}},  # no message.source
            ])
            out = collect_dsh_sessions(sessions_root(tmp), Path(tmp) / "none.db", NOW, ZONE)
            model_groups = out["metrics"]["tokens"]["value"]["periods"]["all"]["groups"]
            self.assertEqual([g["model"] for g in model_groups], ["deepseek-v4-pro"])

    def test_legacy_chunk_message_dedup_and_progressive_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = sessions_root(tmp) / "p" / "s"
            write_zstd(root / "session.jsonl.zstd", [
                legacy_header(ms_at(9, 9), "deepseek-v4-flash"),
                legacy_chunk(ms_at(9, 10), 1, 1, 0, 0),                                  # early progressive zero
                legacy_final(ms_at(9, 10, 1), 1, 1, 50, 20, reasoning=5, cache_read=80),  # final wins
                legacy_chunk(ms_at(9, 11), 2, 1, 10, 2),
                legacy_final(ms_at(9, 11), 2, 1, 12, 3, reasoning=1),                     # same ts, later line wins
            ])
            out = collect_dsh_sessions(sessions_root(tmp), Path(tmp) / "none.db", NOW, ZONE)
            allp = totals(out)
            self.assertEqual((allp["requests"], allp["fresh_input"], allp["output"],
                              allp["reasoning"], allp["cache_read"]), (2, 62, 17, 6, 80))
            models = {g["model"]: g["requests"] for g in out["metrics"]["tokens"]["value"]["periods"]["all"]["groups"]}
            self.assertEqual(models, {"deepseek-v4-flash": 2})
            diag = out["diagnostics"]
            self.assertEqual((diag["v3_session_files"], diag["legacy_session_files"]), (0, 1))

    def test_legacy_model_scopes_to_closest_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = sessions_root(tmp) / "p" / "s"
            write_zstd(root / "session.jsonl.zstd", [
                legacy_final(ms_at(9, 10), 1, 1, 1, 1),            # before any header → unknown
                legacy_header(ms_at(9, 10, 10), "model-a"),
                legacy_final(ms_at(9, 10, 20), 1, 2, 2, 2),
                legacy_header(ms_at(9, 10, 30), "model-b"),
                legacy_final(ms_at(9, 10, 40), 1, 3, 3, 3),
            ])
            out = collect_dsh_sessions(sessions_root(tmp), Path(tmp) / "none.db", NOW, ZONE)
            models = {g["model"]: g["requests"] for g in out["metrics"]["tokens"]["value"]["periods"]["all"]["groups"]}
            self.assertEqual(models, {"unknown": 1, "model-a": 1, "model-b": 1})

    def test_millisecond_timestamps_bucket_by_local_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = sessions_root(tmp) / "p" / "s"
            write_zstd(root / "session.v3.jsonl.zstd", [
                v3_message(ms_at(9), 1, 1, "m", 1, 1),               # today
                v3_message(ms_at(8), 1, 2, "m", 2, 2),               # yesterday (7d, 30d)
                v3_message(int(datetime(2026, 9, 27, 10, tzinfo=ZONE).timestamp() * 1000),
                           1, 3, "m", 4, 4),                                      # 2026-09-27 (30d only)
                v3_message(int(datetime(2026, 8, 20, 10, tzinfo=ZONE).timestamp() * 1000),
                           1, 4, "m", 8, 8),                          # outside 30d
            ])
            value = collect_dsh_sessions(sessions_root(tmp), Path(tmp) / "none.db", NOW, ZONE)["metrics"]["tokens"]["value"]
            self.assertEqual([value["periods"][p]["totals"]["requests"] for p in ("today", "7d", "30d", "all")],
                             [1, 2, 3, 4])
            self.assertEqual([b["date"] for b in value["daily_buckets"]],
                             ["2026-08-20", "2026-09-27", "2026-10-08", LOCAL_TODAY])

    def test_corrupt_file_skipped_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = sessions_root(tmp) / "p"
            write_zstd(root / "s1" / "session.v3.jsonl.zstd",
                       [v3_message(ms_at(9), 1, 1, "m", 100, 10)])
            write_zstd(root / "s2" / "session.v3.jsonl.zstd",
                       [v3_message(ms_at(9), 1, 1, "m", 999, 999)])
            (root / "s2" / "session.v3.jsonl.zstd").write_bytes(b"corrupt-not-zstd")
            out = collect_dsh_sessions(sessions_root(tmp), Path(tmp) / "none.db", NOW, ZONE)
            self.assertEqual(out["diagnostics"]["skipped_session_files"], 1)
            self.assertEqual(totals(out)["fresh_input"], 100)

    def test_missing_dir_and_no_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SourceError) as ctx:
                collect_dsh_sessions(Path(tmp) / "none", Path(tmp) / "none.db", NOW, ZONE)
            self.assertEqual(ctx.exception.code, "dsh_sessions_not_found")
            empty = Path(tmp) / "empty"
            empty.mkdir()
            with self.assertRaises(SourceError) as ctx:
                collect_dsh_sessions(empty, Path(tmp) / "none.db", NOW, ZONE)
            self.assertEqual(ctx.exception.code, "dsh_sessions_not_found")

    def test_zstd_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = sessions_root(tmp) / "p" / "s"
            write_zstd(root / "session.v3.jsonl.zstd", [v3_message(ms_at(9), 1, 1, "m", 1, 1)])
            with patch.object(dsh_tokens, "_HAS_STDLIB_ZSTD", False):
                with self.assertRaises(SourceError) as ctx:
                    collect_dsh_sessions(sessions_root(tmp), Path(tmp) / "none.db", NOW, ZONE, zstd_binary=None)
                self.assertEqual(ctx.exception.code, "zstd_unavailable")

    def test_zstd_cli_route_when_stdlib_missing(self):
        binary = shutil.which("zstd")
        if binary is None:
            self.skipTest("no zstd CLI on this machine")
        with tempfile.TemporaryDirectory() as tmp:
            root = sessions_root(tmp) / "p" / "s"
            write_zstd(root / "session.jsonl.zstd", [
                legacy_header(ms_at(9, 9), "m"),
                legacy_final(ms_at(9, 10), 1, 1, 7, 3, reasoning=1, cache_read=5),
            ])
            with patch.object(dsh_tokens, "_HAS_STDLIB_ZSTD", False):
                out = collect_dsh_sessions(sessions_root(tmp), Path(tmp) / "none.db", NOW, ZONE, zstd_binary=binary)
            self.assertEqual(out["diagnostics"]["decompression_route"], "zstd_cli")
            allp = totals(out)
            self.assertEqual((allp["requests"], allp["fresh_input"], allp["output"],
                              allp["reasoning"], allp["cache_read"]), (1, 7, 2, 1, 5))


class DshCollectorIntegrationTests(unittest.TestCase):
    ALL = ["ccswitch", "codex", "claude", "kimi", "qoder", "minimax_code", "dreamina", "minimax_design",
           "deepseek_api", "workbuddy", "trae_cn", "zcode", "opencode", "gemini", "antigravity", "mimo",
           "stepfun", "volcengine", "reset_forecast"]

    def test_dsh_source_available_and_missing_maps_to_not_connected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = sessions_root(tmp) / "p" / "s"
            write_zstd(root / "session.v3.jsonl.zstd",
                       [v3_message(ms_at(9), 1, 1, "mimo-v2.5-pro", 100, 40, reasoning=10, cache_read=200)])
            config = {"runtime_dir": tmp, "app_roots": [],
                      "dsh_sessions_dir": str(sessions_root(tmp)), "zstd_binary": shutil.which("zstd"),
                      "disabled_sources": list(self.ALL)}
            snap = collect(config, now=NOW)
            dsh = next(s for s in snap["sources"] if s["id"] == "deepseek_harness")
            self.assertEqual(dsh["scope"], "local_session_history")
            self.assertEqual(dsh["metrics"]["tokens"]["status"], "available")
            self.assertEqual(totals(dsh)["total_tokens"], 340)
            self.assertEqual(dsh["diagnostics"]["decompression_route"], ROUTE)
            config["dsh_sessions_dir"] = str(Path(tmp) / "none")
            snap = collect(config, now=NOW)
            dsh = next(s for s in snap["sources"] if s["id"] == "deepseek_harness")
            self.assertEqual((dsh["status"], dsh["metrics"]["tokens"]["reason"]),
                             ("not_connected", "dsh_sessions_not_found"))


if __name__ == "__main__":
    unittest.main()
