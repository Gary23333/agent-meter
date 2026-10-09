"""Regression tests for the three local token-history collectors.

All fixtures live in temporary directories; nothing reads the real home.
"""
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from agent_meter.collector import collect, coverage_matrix
from agent_meter.model import SourceError, metric, source
from agent_meter.opencode_tokens import collect_opencode_tokens
from agent_meter.workbuddy_tokens import collect_workbuddy_tokens
from agent_meter.zcode_local import collect_zcode_local

# 2026-10-09 12:00 +08:00 — same convention as the other suites.
NOW = int(datetime(2026, 10, 9, 4, 0, tzinfo=timezone.utc).timestamp())
ZONE = ZoneInfo("Asia/Shanghai")
LOCAL_TODAY = "2026-10-09"

MODEL_USAGE_DDL = """
CREATE TABLE model_usage (
  id text primary key, logical_request_id text, attempt_index integer default 0,
  session_id text, turn_id text, query_source text, provider_id text, model_id text,
  status text, started_at integer, input_tokens integer default 0, output_tokens integer default 0,
  reasoning_tokens integer default 0, cache_creation_input_tokens integer default 0,
  cache_read_input_tokens integer default 0)
"""


def zcode_db(path, rows):
    conn = sqlite3.connect(path)
    conn.executescript(MODEL_USAGE_DDL)
    conn.executemany("INSERT INTO model_usage(id,provider_id,model_id,status,started_at,attempt_index,"
                     "input_tokens,output_tokens,reasoning_tokens,cache_creation_input_tokens,cache_read_input_tokens)"
                     " VALUES(?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()


class ZCodeTests(unittest.TestCase):
    def test_periods_models_and_daily(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "db.sqlite"
            day_ms = lambda d, h=0: int(datetime(2026, 10, d, h, tzinfo=ZONE).timestamp() * 1000)
            zcode_db(db, [
                ("1", "p", "m1", "completed", day_ms(9, 10), 0, 100, 5, 2, 10, 200),    # today
                ("2", "p", "m1", "completed", day_ms(8), 0, 50, 5, 0, 0, 0),            # yesterday
                ("3", "p", "m2", "error", day_ms(2), 0, 0, 0, 0, 0, 0),                 # failed, zero tokens
                ("4", "p", "m1", "completed", day_ms(2), 1, 7, 1, 0, 0, 0),             # retry attempt
            ])
            value = collect_zcode_local(db, NOW, ZONE)["metrics"]["tokens"]["value"]
            today = value["periods"]["today"]["totals"]
            self.assertEqual((today["requests"], today["fresh_input"], today["output"],
                              today["reasoning"], today["cache_read"], today["cache_write"]),
                             (1, 100, 5, 2, 200, 10))
            self.assertEqual(today["total_tokens"], 317)
            allp = value["periods"]["all"]["totals"]
            self.assertEqual((allp["requests"], allp["total_tokens"]), (4, 380))
            self.assertEqual(allp["cache_hit_rate"], 200 / (157 + 200 + 10))
            models = {g["model"]: g for g in value["periods"]["all"]["groups"]}
            self.assertEqual(models["p/m1"]["total_tokens"], 380)
            self.assertEqual(value["retry_attempt_rows"], 1)
            self.assertEqual(value["periods"]["all"]["requests_by_status"], {"completed": 3, "error": 1})
            self.assertEqual(value["daily_buckets"][-1]["date"], LOCAL_TODAY)
            self.assertEqual(value["daily_buckets"][-1]["tokens"], 317)

    def test_missing_db_and_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SourceError) as ctx:
                collect_zcode_local(Path(tmp) / "none.sqlite", NOW, ZONE)
            self.assertEqual(ctx.exception.code, "zcode_db_not_found")
            db = Path(tmp) / "db.sqlite"
            sqlite3.connect(db).close()  # empty db, no model_usage table
            with self.assertRaises(SourceError) as ctx:
                collect_zcode_local(db, NOW, ZONE)
            self.assertEqual(ctx.exception.code, "unsupported_zcode_usage_schema")


def opencode_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE message(id text primary key, session_id text, time_created integer, time_updated integer, data text)")
    conn.executemany("INSERT INTO message(id,time_created,data) VALUES(?,?,?)", rows)
    conn.commit()
    conn.close()


def message(ts_ms, model="m", role="assistant", **tokens):
    data = {"role": role, "modelID": model, "time": {"created": ts_ms, "started": ts_ms},
            "tokens": dict({"total": 0, "input": 1, "output": 2, "reasoning": 0, "cache": {"write": 0, "read": 0}}, **tokens)}
    return json.dumps(data, ensure_ascii=False)


class OpenCodeTests(unittest.TestCase):
    def test_excludes_days_ccswitch_already_imported(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "opencode.db"
            ms = lambda d: int(datetime(2026, 10, d, 12, tzinfo=ZONE).timestamp() * 1000)
            opencode_db(db, [
                ("a", ms(9), message(ms(9), input=100, output=10, cache={"write": 0, "read": 50})),
                ("b", ms(8), message(ms(8), input=30, output=3)),
                ("c", ms(8), message(ms(8), model="other", input=5, output=1, reasoning=2)),
                ("d", ms(8), message(ms(8), role="user", input=99, output=99)),   # never counted
            ])
            cc = Path(tmp) / "cc.db"
            conn = sqlite3.connect(cc)
            conn.execute("CREATE TABLE proxy_request_logs(id integer primary key, created_at integer, data_source text, app_type text)")
            conn.execute("INSERT INTO proxy_request_logs(created_at,data_source,app_type) VALUES(?, 'opencode_session', 'opencode')",
                         [int(datetime(2026, 10, 8, 12, tzinfo=ZONE).timestamp())])
            conn.commit(); conn.close()
            value = collect_opencode_tokens(db, cc, NOW, ZONE)["metrics"]["tokens"]["value"]
            # 10-08 is CC Switch's day; only 10-09 remains here.
            allp = value["periods"]["all"]["totals"]
            self.assertEqual((allp["requests"], allp["fresh_input"], allp["cache_read"], allp["total_tokens"]),
                             (1, 100, 50, 160))
            self.assertEqual(value["periods"]["all"]["excluded_ccswitch_days"], ["2026-10-08"])
            self.assertEqual(value["ccswitch_overlap"], {"state": "checked", "excluded_days": ["2026-10-08"]})
            self.assertEqual([b["date"] for b in value["daily_buckets"]], [LOCAL_TODAY])
            groups = {g["model"]: g for g in value["periods"]["all"]["groups"]}
            self.assertNotIn("other", groups)

    def test_missing_ccswitch_means_no_exclusion(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "opencode.db"
            ms = lambda d: int(datetime(2026, 10, d, 12, tzinfo=ZONE).timestamp() * 1000)
            opencode_db(db, [("a", ms(8), message(ms(8), input=10, output=1))])
            value = collect_opencode_tokens(db, Path(tmp) / "none.db", NOW, ZONE)["metrics"]["tokens"]["value"]
            self.assertEqual(value["ccswitch_overlap"]["state"], "ccswitch_absent")
            self.assertEqual(value["periods"]["all"]["totals"]["requests"], 1)
            with self.assertRaises(SourceError):
                collect_opencode_tokens(Path(tmp) / "none.db", Path(tmp) / "none.db", NOW, ZONE)


def workbuddy_file(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n")


def usage_record(rid, ts_ms, **raw):
    full = {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110,
            "prompt_tokens_details": {"cached_tokens": 90}, "prompt_cache_hit_tokens": 90,
            "prompt_cache_miss_tokens": 10, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
            "credit": 1.5}
    full.update(raw)
    return {"id": rid, "type": "function_call", "sessionId": "s", "timestamp": ts_ms,
            "providerData": {"rawUsage": full}}


class WorkBuddyTests(unittest.TestCase):
    def test_cache_dialects_credit_and_incremental_reparse(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "projects" / "proj"
            ms = lambda d, h=10: int(datetime(2026, 10, d, h, tzinfo=ZONE).timestamp() * 1000)
            workbuddy_file(root / "a.jsonl", [
                usage_record("r1", ms(9), prompt_cache_hit_tokens=90, prompt_cache_miss_tokens=10),
                usage_record("r2", ms(9), prompt_cache_hit_tokens=0, prompt_cache_miss_tokens=100),  # no cache
                # anthropic dialect: prompt 80 = fresh 60 + read 20 (rule, unseen locally)
                usage_record("r3", ms(9), prompt_tokens=80, prompt_cache_hit_tokens=None, prompt_cache_miss_tokens=None,
                             cache_read_input_tokens=20, cache_creation_input_tokens=5),
            ])
            value = collect_workbuddy_tokens(Path(tmp) / "projects", NOW, ZONE)["value"]
            allp = value["periods"]["all"]["totals"]
            # r1: fresh 10 read 90, r2: fresh 100, r3: fresh 55 (80-20-5) read 20 write 5
            self.assertEqual((allp["requests"], allp["fresh_input"], allp["cache_read"],
                              allp["cache_write"], allp["output"]), (3, 165, 110, 5, 30))
            self.assertEqual(value["periods"]["all"]["credit_charged"], "4.5")
            self.assertEqual(value["anthropic_style_records"], 1)
            # Incremental cache: rewriting the file must be picked up.
            workbuddy_file(root / "a.jsonl", [usage_record("r1", ms(9), prompt_cache_hit_tokens=0, prompt_cache_miss_tokens=100)])
            value = collect_workbuddy_tokens(Path(tmp) / "projects", NOW, ZONE)["value"]
            self.assertEqual(value["periods"]["all"]["totals"]["requests"], 1)

    def test_malformed_lines_and_missing_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "projects"
            f = root / "p" / "a.jsonl"
            f.parent.mkdir(parents=True)
            f.write_text('broken "rawUsage" not json\n' + json.dumps({"id": "x", "type": "message", "timestamp": 1791480000000,
                                                    "providerData": {"rawUsage": {"prompt_tokens": 7, "completion_tokens": 1}}}) + "\n")
            value = collect_workbuddy_tokens(root, NOW, ZONE)["value"]
            self.assertEqual(value["periods"]["all"]["totals"]["requests"], 1)
            self.assertEqual(value["skipped_malformed"], 1)
            with self.assertRaises(SourceError) as ctx:
                collect_workbuddy_tokens(Path(tmp) / "none", NOW, ZONE)
            self.assertEqual(ctx.exception.code, "workbuddy_projects_not_found")


class CollectorIntegrationTests(unittest.TestCase):
    ALL = ["ccswitch", "codex", "claude", "kimi", "qoder", "minimax_code", "dreamina", "minimax_design",
           "deepseek_api", "workbuddy", "trae_cn", "zcode", "opencode"]

    def local_sources(self, enabled):
        """Patch the local collectors; enabled entries get real-looking metrics."""
        def fake(source_id):
            def fn(*a, **kw):
                out = source(source_id, "local_session_history", NOW) if source_id != "zcode" else source(source_id, "account", NOW)
                out["metrics"]["tokens"] = metric({"periods": {"all": {"totals": {"requests": 1}}}, "daily_buckets": []})
                return out
            return fn
        def missing(code):
            def fn(*a, **kw):
                raise SourceError(code)
            return fn
        patches = {}
        for name, mod in [("zcode", "zcode_tokens_metric"), ("opencode", "collect_opencode_tokens"),
                          ("workbuddy", "collect_workbuddy_tokens")]:
            side = fake(name) if name in enabled else missing(name + "_db_not_found")
            patches[name] = patch("agent_meter.collector." + mod, side_effect=side)
        return patches

    def test_local_sources_appear_with_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = {"runtime_dir": tmp, "app_roots": [],
                      "disabled_sources": [x for x in self.ALL if x not in ("zcode", "opencode")]}
            # zcode: local tokens attach to its (failed) account source.
            patches = self.local_sources(["zcode", "opencode"])
            for p_ in patches.values(): p_.start()
            try: snap = collect(config, now=NOW)
            finally:
                for p_ in patches.values(): p_.stop()
            by_id = {s["id"]: s for s in snap["sources"]}
            self.assertEqual(by_id["zcode"]["scope"], "account")
            self.assertEqual(by_id["zcode"]["metrics"]["tokens"]["status"], "available")
            self.assertEqual(by_id["opencode"]["metrics"]["tokens"]["status"], "available")

    def test_missing_db_maps_to_not_connected(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = {"runtime_dir": tmp, "app_roots": [],
                      "disabled_sources": [x for x in self.ALL if x not in ("zcode",)]}
            patches = self.local_sources(["none"])
            for p_ in patches.values(): p_.start()
            try: snap = collect(config, now=NOW)
            finally:
                for p_ in patches.values(): p_.stop()
            zc = next(s for s in snap["sources"] if s["id"] == "zcode")
            # Account collector failed (no web login); local tokens carry their own reason.
            self.assertEqual(zc["metrics"]["tokens"]["status"], "not_connected")
            self.assertEqual(zc["metrics"]["tokens"]["reason"], "zcode_db_not_found")

    def test_workbuddy_tokens_attach_even_without_web_login(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = {"runtime_dir": tmp, "app_roots": [],
                      "disabled_sources": [x for x in self.ALL if x != "workbuddy"]}
            patches = self.local_sources(["workbuddy"])
            patches["zcode"].side_effect = None
            for p_ in patches.values(): p_.start()
            try: snap = collect(config, now=NOW)
            finally:
                for p_ in patches.values(): p_.stop()
            wb = next(s for s in snap["sources"] if s["id"] == "workbuddy")
            self.assertEqual(wb["diagnostics"]["reason"], "web_session_missing")
            self.assertEqual(wb["metrics"]["tokens"]["status"], "available")
            # The second account never gets machine-wide local history.
            self.assertFalse(any(s["id"] == "workbuddy#2" for s in snap["sources"]))

    def test_user_switch_skips_workbuddy_local_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = {"runtime_dir": tmp, "app_roots": [],
                      "preferences": {"disabled_sources": ["workbuddy"]},
                      "disabled_sources": [x for x in self.ALL if x != "workbuddy"]}
            patches = self.local_sources(["workbuddy"])
            for p_ in patches.values(): p_.start()
            try: snap = collect(config, now=NOW)
            finally:
                for p_ in patches.values(): p_.stop()
            wb = next(s for s in snap["sources"] if s["id"] == "workbuddy")
            self.assertEqual(wb["metrics"]["tokens"]["reason"], "disabled_by_user")

    def test_dedicated_local_source_wins_coverage_attribution(self):
        def history_source(apps):
            cc = source("ccswitch", "local_imported_history", NOW)
            cc["metrics"]["tokens"] = metric({"periods": {p: {"groups": [{"app": a, "total_tokens": 1} for a in apps]}
                                                          for p in ("today", "7d", "30d", "all")}})
            return cc
        local = source("opencode", "local_session_history", NOW)
        local["metrics"]["tokens"] = metric({"periods": {}, "daily_buckets": []})
        app = {"name": "OpenCode", "provider": "opencode", "installed": True}
        fields = coverage_matrix([app], [history_source(["opencode"]), local])[0]["fields"]
        self.assertEqual((fields["tokens"]["source"], fields["tokens"]["scope"]), ("opencode", "local_session_history"))
        self.assertEqual(fields["cost"]["source"], "ccswitch")
        # Unavailable local source falls back to CC Switch attribution.
        down = source("opencode", "local_session_history", NOW)
        fields = coverage_matrix([app], [history_source(["opencode"]), down])[0]["fields"]
        self.assertEqual(fields["tokens"]["source"], "ccswitch")


if __name__ == "__main__":
    unittest.main()
