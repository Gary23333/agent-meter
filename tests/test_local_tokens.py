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
from agent_meter.qoder_tokens import collect_qoder_credits, merge_credits_metric
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


def usage_record(rid, ts_ms, model="deepseek-v4.1-flash", **raw):
    full = {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110,
            "prompt_tokens_details": {"cached_tokens": 90}, "prompt_cache_hit_tokens": 90,
            "prompt_cache_miss_tokens": 10, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
            "prompt_cache_write_tokens": 0, "completion_thinking_tokens": 0, "credit": 1.5}
    full.update(raw)
    provider = {"rawUsage": full}
    if model is not None:
        provider["model"] = model
    return {"id": rid, "type": "function_call", "sessionId": "s", "timestamp": ts_ms,
            "providerData": provider}


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
            self.assertEqual(value["thinking_in_output"], True)
            # Incremental cache: rewriting the file must be picked up.
            workbuddy_file(root / "a.jsonl", [usage_record("r1", ms(9), prompt_cache_hit_tokens=0, prompt_cache_miss_tokens=100)])
            value = collect_workbuddy_tokens(Path(tmp) / "projects", NOW, ZONE)["value"]
            self.assertEqual(value["periods"]["all"]["totals"]["requests"], 1)

    def test_groups_carry_model_and_thinking_stays_inside_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "projects"
            ms = lambda d: int(datetime(2026, 10, d, 10, tzinfo=ZONE).timestamp() * 1000)
            workbuddy_file(root / "a.jsonl", [
                usage_record("r1", ms(9), model="hy4-preview", prompt_cache_hit_tokens=0,
                             prompt_cache_miss_tokens=100, completion_tokens=40, completion_thinking_tokens=30),
                usage_record("r2", ms(9), model="glm-5-3-flash", prompt_cache_miss_tokens=7,
                             prompt_cache_hit_tokens=93, completion_tokens=5),
                # no model field: falls back to requestModelName, then "unknown"
                usage_record("r3", ms(8), model=None, prompt_cache_hit_tokens=0,
                             prompt_cache_miss_tokens=1, completion_tokens=1),
            ])
            value = collect_workbuddy_tokens(root, NOW, ZONE)["value"]
            allp = value["periods"]["all"]
            groups = {g["model"]: g for g in allp["groups"]}
            self.assertEqual(set(groups), {"hy4-preview", "glm-5-3-flash", "unknown"})
            self.assertEqual((groups["hy4-preview"]["fresh_input"], groups["hy4-preview"]["output"],
                              groups["hy4-preview"]["total_tokens"]), (100, 40, 140))
            # thinking is a sub-part of output, never an extra total
            self.assertEqual(groups["hy4-preview"]["thinking_tokens"], 30)
            self.assertEqual(allp["totals"]["thinking_tokens"], 30)
            self.assertEqual(allp["totals"]["total_tokens"], sum(
                allp["totals"][f] for f in ("fresh_input", "output", "cache_read", "cache_write")))
            self.assertEqual(value["unknown_model_records"], 1)
            # The per-model split reproduces the period totals exactly.
            for field in ("requests", "fresh_input", "output", "cache_read", "cache_write"):
                self.assertEqual(sum(g[field] for g in allp["groups"]), allp["totals"][field])
            self.assertEqual(value["periods"]["today"]["totals"]["requests"], 2)

    def test_request_model_name_is_the_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "projects"
            record = usage_record("r1", 1791480000000, model=None)
            record["providerData"]["requestModelName"] = "Hy4 preview"
            workbuddy_file(root / "a.jsonl", [record])
            value = collect_workbuddy_tokens(root, NOW, ZONE)["value"]
            self.assertEqual([g["model"] for g in value["periods"]["all"]["groups"]], ["Hy4 preview"])

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
            self.assertEqual(value["unknown_model_records"], 1)
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


def qoder_file(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for record in records:
            handle.write((record if isinstance(record, str) else json.dumps(record, ensure_ascii=False)) + "\n")


def qoder_record(rid, ts, credits, model="qfmodel", billable=False, sidechain=False):
    return {"type": "assistant", "uuid": rid, "timestamp": ts, "sessionId": "s1", "isSidechain": sidechain,
            "message": {"model": model, "usage": {
                "input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0, "credits": credits, "original_credits": credits,
                "billable": billable, "request_id": rid, "context_usage_ratio": 0.01}}}


class QoderCreditsTests(unittest.TestCase):
    """Qoder CN logs carry per-request credits; token fields are always zero."""

    def test_periods_models_billable_sidechain_and_daily(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "projects"
            qoder_file(root / "p1" / "a.jsonl", [
                qoder_record("r1", "2026-10-09T03:00:00.000Z", 1.5, model="qfmodel"),
                qoder_record("r2", "2026-10-09T03:30:00.000Z", 2.5, model="dfmodel", billable=True),
                qoder_record("r3", "2026-10-01T04:00:00.000Z", 10, model="qmodel_38max"),
                qoder_record("r4", "2026-08-01T04:00:00.000Z", 100, model=None, billable=True),  # outside 30d, no model
                qoder_record("r5", "2026-10-09T02:00:00.000Z", 0.25, sidechain=True),
            ])
            value = collect_qoder_credits(root, NOW, ZONE)
            self.assertEqual(value["unit"], "qoder_credits")
            self.assertEqual(value["token_fields"], "not_provided")
            self.assertEqual(value["usage_records_seen"], 5)
            self.assertEqual(value["excluded_usage_records"], 0)
            allp = value["periods"]["all"]["totals"]
            self.assertEqual((allp["requests"], allp["billable_requests"]), (5, 2))
            self.assertEqual((allp["credits"], allp["billable_credits"]), ("114.25", "102.5"))
            today = value["periods"]["today"]["totals"]
            self.assertEqual((today["requests"], today["credits"]), (3, "4.25"))
            month = value["periods"]["30d"]["totals"]
            self.assertEqual((month["requests"], month["credits"]), (4, "14.25"))
            week = value["periods"]["7d"]["totals"]
            self.assertEqual(week["requests"], 3)
            models = {g["model"]: g for g in value["periods"]["all"]["groups"]}
            self.assertEqual(set(models), {"qfmodel", "dfmodel", "qmodel_38max", "unknown"})
            self.assertEqual(models["dfmodel"]["credits"], "2.5")
            self.assertEqual(value["sidechain"], {"requests": 1, "credits": "0.25"})
            self.assertEqual([(b["date"], b["requests"], b["credits"]) for b in value["daily_buckets"]],
                             [("2026-08-01", 1, "100"), ("2026-10-01", 1, "10"),
                              ("2026-10-09", 3, "4.25")])

    def test_dedup_malformed_and_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "projects"
            qoder_file(root / "p1" / "a.jsonl", [
                qoder_record("r1", "2026-10-09T04:00:00.000Z", 1.5),
                qoder_record("r1", "2026-10-09T04:30:00.000Z", 9),          # duplicate request_id
                "not json at all",
                json.dumps({"type": "assistant", "message": {"usage": {"credits": 3}}, "timestamp": "2026-10-09T04:00:00Z"}),  # no request_id
                json.dumps({"type": "assistant", "message": {"usage": {"credits": 3, "request_id": "r9"}},
                            "timestamp": "nope"}),                          # bad timestamp
                json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": 5, "request_id": "r8"}},
                            "timestamp": "2026-10-09T04:00:00Z"}),          # usage without credits
            ])
            value = collect_qoder_credits(root, NOW, ZONE)
            self.assertEqual(value["periods"]["all"]["totals"]["requests"], 1)
            self.assertEqual(value["periods"]["all"]["totals"]["credits"], "1.5")
            self.assertEqual(value["excluded_usage_records"], 4)
            self.assertEqual(value["usage_records_seen"], 5)
            # Every usage object lost its credits: the private format drifted.
            drift = Path(tmp) / "drift"
            qoder_file(drift / "a.jsonl", [
                json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": 5, "request_id": "r8"}},
                            "timestamp": "2026-10-09T04:00:00Z"}),
            ])
            with self.assertRaises(SourceError) as ctx:
                collect_qoder_credits(drift, NOW, ZONE)
            self.assertEqual(ctx.exception.code, "unsupported_qoder_usage_schema")
            with self.assertRaises(SourceError) as ctx:
                collect_qoder_credits(Path(tmp) / "none", NOW, ZONE)
            self.assertEqual(ctx.exception.code, "qoder_sessions_not_found")

    def test_merge_credits_metric_keeps_wallet_rows(self):
        wallets = [{"bucket": "totalQuota", "total": "100", "used": "10", "remaining": "90",
                    "unit": "qoder_credits"}]
        ledger = {"unit": "qoder_credits", "periods": {}}
        merged = merge_credits_metric(metric(wallets), ledger)
        self.assertEqual(merged["value"]["rows"], wallets)
        self.assertEqual(merged["value"]["usage"], ledger)
        self.assertEqual(merged["status"], "available")
        empty = merge_credits_metric(metric(), ledger)
        self.assertEqual(empty["value"]["rows"], [])
        kept = merge_credits_metric(metric({"rows": wallets, "usage": {}}), ledger)
        self.assertEqual(kept["value"]["rows"], wallets)


class QoderCollectorIntegrationTests(unittest.TestCase):
    ALL = ["ccswitch", "codex", "claude", "kimi", "qoder", "minimax_code", "dreamina", "minimax_design",
           "deepseek_api", "workbuddy", "trae_cn", "zcode", "opencode"]

    def qoder_root(self, tmp):
        root = Path(tmp) / "qoder-projects"
        qoder_file(root / "p1" / "a.jsonl", [
            qoder_record("r1", "2026-10-09T03:00:00.000Z", 1.5, billable=True),
            qoder_record("r2", "2026-10-09T03:30:00.000Z", 2.5),
        ])
        return root

    def test_credits_attach_to_account_source_never_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = {"runtime_dir": tmp, "app_roots": [], "qoder_projects_dir": str(self.qoder_root(tmp)),
                      "disabled_sources": [x for x in self.ALL if x != "qoder"]}
            with patch("agent_meter.collector.collect_qoder", side_effect=SourceError("qoder_sdk_not_installed")):
                snap = collect(config, now=NOW)
            qoder = next(s for s in snap["sources"] if s["id"] == "qoder")
            self.assertEqual(qoder["scope"], "account")
            # Account query failed, but the local credits ledger still shows.
            self.assertEqual(qoder["metrics"]["credits"]["status"], "available")
            usage = qoder["metrics"]["credits"]["value"]["usage"]
            self.assertEqual(usage["periods"]["all"]["totals"],
                             {"requests": 2, "credits": "4.0", "billable_requests": 1, "billable_credits": "1.5"})
            self.assertEqual(qoder["metrics"]["credits"]["value"]["rows"], [])
            # Never a tokens metric: the local-consumption sum cannot see it.
            self.assertIsNone(qoder["metrics"]["tokens"]["value"])
            self.assertNotIn("periods", qoder["metrics"]["tokens"]["value"] or {})
            # Second web-login accounts never get the machine-wide ledger.
            self.assertFalse(any(s["id"] == "qoder#2" for s in snap["sources"]))

    def test_user_switch_skips_qoder_credits(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = {"runtime_dir": tmp, "app_roots": [], "qoder_projects_dir": str(self.qoder_root(tmp)),
                      "preferences": {"disabled_sources": ["qoder"]},
                      "disabled_sources": [x for x in self.ALL if x != "qoder"]}
            with patch("agent_meter.collector.collect_qoder", side_effect=SourceError("qoder_sdk_not_installed")):
                snap = collect(config, now=NOW)
            qoder = next(s for s in snap["sources"] if s["id"] == "qoder")
            self.assertEqual(qoder["metrics"]["credits"]["reason"], "disabled_by_user")
            self.assertIsNone(qoder["metrics"]["credits"]["value"])

    def test_web_wallets_and_ledger_merge(self):
        wallets = [{"bucket": "totalQuota", "total": "1000", "used": "100", "remaining": "900",
                    "unit": "qoder_credits"}]

        def fake_web(session, now, timeout=15):
            out = source("qoder", "account", NOW)
            out["metrics"]["quota"] = metric([{"bucket": "totalQuota", "used_percent": 10,
                                               "remaining_percent": 90, "unit": "qoder_credits"}])
            out["metrics"]["credits"] = metric(wallets)
            return out

        with tempfile.TemporaryDirectory() as tmp:
            config = {"runtime_dir": tmp, "app_roots": [], "qoder_projects_dir": str(self.qoder_root(tmp)),
                      "web_sessions": {"qoder": [{"cookie": "a=1", "user_agent": "UA"}]},
                      "disabled_sources": [x for x in self.ALL if x != "qoder"]}
            with patch("agent_meter.collector.collect_qoder_web", side_effect=fake_web):
                snap = collect(config, now=NOW)
            qoder = next(s for s in snap["sources"] if s["id"] == "qoder")
            credits = qoder["metrics"]["credits"]["value"]
            self.assertEqual(credits["rows"], wallets)
            self.assertEqual(credits["usage"]["periods"]["today"]["totals"]["requests"], 2)


if __name__ == "__main__":
    unittest.main()
