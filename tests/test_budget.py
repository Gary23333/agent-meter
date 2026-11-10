"""Budget & anomaly alerts: fixed fixtures, no network, no real ledgers."""
import copy
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agent_meter.budget import (DEFAULT_MULTIPLIER, budget_state, clean_config,
                                compute_budget, default_config, load_budget,
                                load_history, save_budget, save_history)
from agent_meter.collector import SnapshotService
from agent_meter.server import load_or_create_token, make_server

ZONE = ZoneInfo("Asia/Shanghai")
# 2026-11-08 is a Sunday; its natural week starts Monday 2026-11-02.
NOON = datetime(2026, 11, 8, 12, tzinfo=ZONE).timestamp()
EARLY = datetime(2026, 11, 8, 1, tzinfo=ZONE).timestamp()
MONDAY_NOON = datetime(2026, 11, 9, 12, tzinfo=ZONE).timestamp()
TODAY = "2026-11-08"
WEEK_START = "2026-11-02"


def cost_period(amount, models=None, app_models=None, unmatched=None):
    return {"amount": amount, "peak_amount": "0",
            "offpeak_amount": amount if amount is not None else "0",
            "models": models or {}, "app_models": app_models or {},
            "unmatched_models": unmatched or [], "unsplit_models": []}


def local_source(sid, unit="CNY", today="0", today_models=None, today_apps=None,
                 d30=None, tokens_today=0, cost_status="available", unmatched=None):
    periods = {"today": cost_period(today, today_models, today_apps, unmatched)}
    if d30 is not None:
        periods["30d"] = cost_period(d30)
    return {"id": sid, "scope": "local_session_history", "status": "available", "metrics": {
        "tokens": {"status": "available", "reason": None, "value": {
            "periods": {"today": {"totals": {"total_tokens": tokens_today}}}}},
        "cost": {"status": cost_status, "reason": None, "value": {
            "unit": unit, "kind": "estimate", "basis": local_price_basis(),
            "periods": periods}}}}


def local_price_basis():
    return "local_price_table"


def unpriced_source(sid, tokens_today=100):
    return {"id": sid, "scope": "local_session_history", "status": "available", "metrics": {
        "tokens": {"status": "available", "reason": None, "value": {
            "periods": {"today": {"totals": {"total_tokens": tokens_today}}}}},
        "cost": {"status": "not_provided", "reason": None, "value": None}}}


def snapshot(*sources):
    return {"schema_version": 5, "sources": list(sources)}


def config(daily=None, weekly=None, multiplier=DEFAULT_MULTIPLIER):
    return {"schema": 1, "daily_cny": daily, "weekly_cny": weekly,
            "anomaly_multiplier": multiplier}


def history_days(values):
    return {d: {"spent_cny": v, "apps": {}, "models": {}, "partial": False}
            for d, v in values.items()}


class ComputeTests(unittest.TestCase):
    def compute(self, snap, cfg=None, now=NOON, history=None):
        payload, entry = compute_budget(snap, cfg or config(), now, history)
        return payload, entry

    def test_daily_exceeded_and_event_details(self):
        snap = snapshot(local_source("zcode", today="12.5", tokens_today=1000,
                                     today_models={"glm-5.3": "12.5"},
                                     today_apps={"zcode": {"glm-5.3": "12.5"}}))
        out, entry = self.compute(snap, config(daily="10"))
        self.assertEqual(out["daily"]["spent_cny"], "12.500000")
        self.assertEqual(out["daily"]["budget_cny"], "10.000000")
        self.assertEqual(out["daily"]["remaining_cny"], "-2.500000")
        self.assertTrue(out["daily"]["exceeded"])
        self.assertEqual(out["daily"]["top_apps"], [{"name": "zcode", "amount_cny": "12.500000"}])
        self.assertEqual(out["daily"]["top_models"], [{"name": "glm-5.3", "amount_cny": "12.500000"}])
        ids = [e["id"] for e in out["events"]]
        self.assertIn("budget_daily_exceeded:" + TODAY, ids)
        event = out["events"][ids.index("budget_daily_exceeded:" + TODAY)]
        self.assertEqual(event["excess_cny"], "2.500000")
        self.assertEqual(entry["spent_cny"], "12.500000")

    def test_not_exceeded_no_event(self):
        snap = snapshot(local_source("zcode", today="12.5", tokens_today=1000))
        out, _ = self.compute(snap, config(daily="100"))
        self.assertFalse(out["daily"]["exceeded"])
        self.assertEqual(out["daily"]["remaining_cny"], "87.500000")
        self.assertEqual(out["events"], [])

    def test_unset_budget_never_alerts(self):
        snap = snapshot(local_source("zcode", today="99999", tokens_today=1000))
        out, _ = self.compute(snap, config())
        self.assertIsNone(out["daily"]["budget_cny"])
        self.assertIsNone(out["daily"]["remaining_cny"])
        self.assertFalse(out["daily"]["exceeded"])
        self.assertFalse(out["weekly"]["exceeded"])
        self.assertEqual([e for e in out["events"] if e["kind"] != "anomaly"], [])

    def test_no_cost_data_is_null_not_zero(self):
        out, entry = self.compute(snapshot(unpriced_source("kimi")), config(daily="1"))
        self.assertIsNone(out["daily"]["spent_cny"])
        self.assertFalse(out["daily"]["exceeded"])
        self.assertEqual(out["daily"]["unknown_sources"], ["kimi"])
        self.assertTrue(out["daily"]["partial"])
        self.assertIsNone(entry)
        self.assertEqual(out["anomaly"]["reason"], "no_cost_data")

    def test_empty_snapshot_is_null(self):
        out, _ = self.compute(snapshot(), config(daily="1"))
        self.assertIsNone(out["daily"]["spent_cny"])
        self.assertIsNone(out["weekly"]["spent_cny"])

    def test_measured_zero_is_zero(self):
        out, entry = self.compute(snapshot(local_source("kimi", today="0", tokens_today=0)),
                                  config(daily="1"))
        self.assertEqual(out["daily"]["spent_cny"], "0.000000")
        self.assertFalse(out["daily"]["partial"])
        self.assertEqual(entry["spent_cny"], "0.000000")

    def test_ledger_without_cost_but_zero_usage_today_is_zero(self):
        src = unpriced_source("kimi", tokens_today=0)
        out, _ = self.compute(snapshot(src), config(daily="1"))
        self.assertEqual(out["daily"]["spent_cny"], "0.000000")

    def test_usd_converts_at_fixed_fx(self):
        snap = snapshot(local_source("codex", unit="USD", today="2", tokens_today=100,
                                     today_models={"gpt-6-sol": "2"}))
        out, _ = self.compute(snap, config(daily="10"))
        self.assertEqual(out["daily"]["spent_cny"], "14.500000")
        self.assertTrue(out["daily"]["exceeded"])
        self.assertEqual(out["fx_rate"], "7.25")
        self.assertEqual(out["daily"]["top_models"][0]["amount_cny"], "14.500000")

    def test_mixed_currencies_sum_in_cny(self):
        snap = snapshot(local_source("codex", unit="USD", today="2", tokens_today=100),
                        local_source("dsh", unit="CNY", today="3", tokens_today=100))
        out, _ = self.compute(snap)
        self.assertEqual(out["daily"]["spent_cny"], "17.500000")

    def test_unknown_currency_never_mixed_in(self):
        snap = snapshot(local_source("x", unit="EUR", today="2", tokens_today=100),
                        local_source("dsh", unit="CNY", today="3", tokens_today=100))
        out, _ = self.compute(snap)
        self.assertEqual(out["daily"]["spent_cny"], "3.000000")
        self.assertEqual(out["daily"]["unknown_sources"], ["x"])
        self.assertTrue(out["daily"]["partial"])

    def test_partial_pricing_flags_lower_bound_but_can_still_exceed(self):
        snap = snapshot(local_source("zcode", today="12", tokens_today=100,
                                     cost_status="partial", unmatched=["mystery-model"]))
        out, _ = self.compute(snap, config(daily="10"))
        self.assertTrue(out["daily"]["partial"])
        self.assertTrue(out["daily"]["exceeded"])

    def test_provider_billed_cost_is_not_a_local_estimate(self):
        src = local_source("deepseek_api", today="50", tokens_today=100)
        src["metrics"]["cost"]["value"]["basis"] = "platform_web_usage"
        out, _ = self.compute(snapshot(src), config(daily="1"))
        self.assertIsNone(out["daily"]["spent_cny"])
        self.assertEqual(out["daily"]["unknown_sources"], ["deepseek_api"])

    def test_peak_offpeak_only_shape(self):
        src = local_source("dsh", today="7", tokens_today=100)
        period = src["metrics"]["cost"]["value"]["periods"]["today"]
        del period["amount"]
        period["peak_amount"], period["offpeak_amount"] = "4", "3"
        out, _ = self.compute(snapshot(src))
        self.assertEqual(out["daily"]["spent_cny"], "7.000000")

    def test_week_boundary_monday_excludes_last_week(self):
        hist = history_days({"2026-11-08": "500",   # last Sunday: outside this week
                             "2026-11-02": "900"})  # last Monday: also outside
        snap = snapshot(local_source("zcode", today="3", tokens_today=100))
        out, _ = compute_budget(snap, config(weekly="10"), MONDAY_NOON, hist)
        self.assertEqual(out["week_start"], "2026-11-09")
        self.assertEqual(out["date"], "2026-11-09")
        self.assertEqual(out["weekly"]["spent_cny"], "3.000000")
        self.assertFalse(out["weekly"]["exceeded"])
        self.assertTrue(out["weekly"]["complete"])
        self.assertEqual(out["weekly"]["days_missing"], [])

    def test_weekly_sums_recorded_days_and_flags_gaps(self):
        hist = history_days({WEEK_START: "20", "2026-11-03": "30"})
        snap = snapshot(local_source("zcode", today="12", tokens_today=100))
        out, _ = self.compute(snap, config(weekly="60"), history=hist)
        self.assertEqual(out["week_start"], WEEK_START)
        self.assertEqual(out["weekly"]["spent_cny"], "62.000000")
        self.assertTrue(out["weekly"]["exceeded"])
        self.assertFalse(out["weekly"]["complete"])
        self.assertEqual(out["weekly"]["days_missing"],
                         ["2026-11-04", "2026-11-05", "2026-11-06", "2026-11-07"])
        event = [e for e in out["events"] if e["kind"] == "weekly_exceeded"][0]
        self.assertEqual(event["id"], "budget_weekly_exceeded:" + WEEK_START)
        self.assertEqual(event["excess_cny"], "2.000000")

    def test_event_ids_stable_across_recomputation(self):
        snap = snapshot(local_source("zcode", today="12", tokens_today=100))
        out1, _ = self.compute(snap, config(daily="10", weekly="10"))
        snap2 = snapshot(local_source("zcode", today="30", tokens_today=200))
        out2, _ = self.compute(snap2, config(daily="10", weekly="10"),
                               now=NOON + 3600, history=history_days({TODAY: "12"}))
        self.assertEqual([e["id"] for e in out1["events"]], [e["id"] for e in out2["events"]])

    def test_anomaly_requires_two_hours(self):
        hist = history_days({f"2026-11-0{i}": "10" for i in range(1, 8)})
        snap = snapshot(local_source("zcode", today="50", tokens_today=100))
        out, _ = self.compute(snap, now=EARLY, history=hist)
        self.assertFalse(out["anomaly"]["triggered"])
        self.assertEqual(out["anomaly"]["reason"], "too_early")

    def test_anomaly_triggers_on_full_history(self):
        hist = history_days({f"2026-11-0{i}": "10" for i in range(1, 8)})
        snap = snapshot(local_source("zcode", today="50", tokens_today=100,
                                     today_apps={"zcode": {"glm-5.3": "50"}}))
        out, _ = self.compute(snap, history=hist)
        a = out["anomaly"]
        self.assertTrue(a["triggered"])
        self.assertEqual(a["baseline_basis"], "daily_history_7d")
        self.assertEqual(a["baseline_daily_cny"], "10.000000")
        self.assertEqual(a["hours_elapsed"], "12.00")
        event = [e for e in out["events"] if e["kind"] == "anomaly"][0]
        self.assertEqual(event["id"], "budget_anomaly:" + TODAY)
        self.assertEqual(event["top_apps"], [{"name": "zcode", "amount_cny": "50.000000"}])

    def test_anomaly_below_threshold_and_no_baseline(self):
        hist = history_days({f"2026-11-0{i}": "10" for i in range(1, 8)})
        snap = snapshot(local_source("zcode", today="5", tokens_today=100))
        out, _ = self.compute(snap, history=hist)
        self.assertFalse(out["anomaly"]["triggered"])
        self.assertEqual(out["anomaly"]["reason"], "below_threshold")
        out, _ = self.compute(snapshot(local_source("zcode", today="50", tokens_today=100)))
        self.assertFalse(out["anomaly"]["triggered"])
        self.assertEqual(out["anomaly"]["reason"], "no_baseline")

    def test_anomaly_falls_back_to_rolling_30d_with_basis(self):
        hist = history_days({"2026-11-06": "10", "2026-11-07": "10"})  # incomplete week
        snap = snapshot(local_source("zcode", today="50", tokens_today=100, d30="300"))
        out, _ = self.compute(snap, history=hist)
        a = out["anomaly"]
        self.assertTrue(a["triggered"])
        self.assertEqual(a["baseline_basis"], "rolling_30d_average")
        self.assertEqual(a["baseline_daily_cny"], "10.000000")

    def test_anomaly_multiplier_from_config(self):
        hist = history_days({f"2026-11-0{i}": "10" for i in range(1, 8)})
        snap = snapshot(local_source("zcode", today="50", tokens_today=100))
        out, _ = self.compute(snap, config(multiplier="20"), history=hist)
        self.assertFalse(out["anomaly"]["triggered"])
        self.assertEqual(out["anomaly"]["reason"], "below_threshold")


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_defaults_and_roundtrip_permissions(self):
        self.assertEqual(load_budget(self.tmp.name), default_config())
        saved = save_budget(self.tmp.name, {"daily_cny": "10.50", "weekly_cny": None,
                                            "anomaly_multiplier": "3"})
        self.assertEqual(saved, {"schema": 1, "daily_cny": "10.50", "weekly_cny": None,
                                 "anomaly_multiplier": "3"})
        self.assertEqual(load_budget(self.tmp.name), saved)
        path = Path(self.tmp.name) / "budget.json"
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(path.read_text())["schema"], 1)

    def test_partial_put_merges_over_saved(self):
        save_budget(self.tmp.name, {"daily_cny": "10"})
        saved = save_budget(self.tmp.name, {"weekly_cny": "50"})
        self.assertEqual(saved["daily_cny"], "10")
        self.assertEqual(saved["weekly_cny"], "50")
        saved = save_budget(self.tmp.name, {"daily_cny": None})
        self.assertIsNone(saved["daily_cny"])

    def test_invalid_values_rejected(self):
        for body in [{"daily_cny": "-1"}, {"daily_cny": True}, {"daily_cny": "abc"},
                     {"daily_cny": "NaN"}, {"daily_cny": "Infinity"}, {"daily_cny": []},
                     {"weekly_cny": "-0.5"}, {"anomaly_multiplier": "0"},
                     {"anomaly_multiplier": None}, {"anomaly_multiplier": "101"},
                     {"anomaly_multiplier": "-2"}, {"unknown_key": 1}, [], None]:
            with self.assertRaises(ValueError, msg=repr(body)):
                clean_config(body)

    def test_corrupt_file_falls_back_to_defaults(self):
        (Path(self.tmp.name) / "budget.json").write_text('{"schema":9,"daily_cny":"x"}')
        self.assertEqual(load_budget(self.tmp.name), default_config())

    def test_history_roundtrip_and_pruning(self):
        days = history_days({f"2026-10-{i:02d}": "1" for i in range(1, 31)})
        days["bad-date"] = {"spent_cny": "5"}
        days["2026-11-01"] = {"spent_cny": None}
        save_history(self.tmp.name, days)
        loaded = load_history(self.tmp.name)
        self.assertNotIn("bad-date", loaded)
        self.assertNotIn("2026-11-01", loaded)
        self.assertLessEqual(len(loaded), 40)
        path = Path(self.tmp.name) / "budget-history.json"
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)


class StateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.now = NOON

    def tearDown(self):
        self.tmp.cleanup()

    def service(self, snap):
        return SnapshotService({"runtime_dir": self.tmp.name},
                               lambda config, now: copy.deepcopy(snap), lambda: self.now)

    def test_not_collected(self):
        out = budget_state(self.service(snapshot()))
        self.assertEqual(out["status"], "not_collected")
        self.assertEqual(out["config"], default_config())

    def test_state_records_day_ledger_and_recovers(self):
        save_budget(self.tmp.name, {"daily_cny": "10"})
        service = self.service(snapshot(local_source("zcode", today="12", tokens_today=100)))
        service.get()
        out = budget_state(service)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["daily"]["spent_cny"], "12.000000")
        hist = load_history(self.tmp.name)
        self.assertEqual(hist[TODAY]["spent_cny"], "12.000000")
        # Collection outage: today's spend unknown, but the ledger keeps the
        # last known value and the event id never changes.
        service2 = self.service(snapshot(unpriced_source("zcode")))
        service2.get()
        out2 = budget_state(service2)
        self.assertIsNone(out2["daily"]["spent_cny"])
        self.assertEqual(load_history(self.tmp.name)[TODAY]["spent_cny"], "12.000000")
        self.assertEqual(out2["weekly"]["spent_cny"], "12.000000")
        self.assertFalse(out2["weekly"]["complete"])

    def test_week_accumulates_across_days(self):
        snap = snapshot(local_source("zcode", today="3", tokens_today=100))
        service = self.service(snap)
        service.get()
        budget_state(service)  # records Sunday 2026-11-08
        self.now = MONDAY_NOON
        out = budget_state(service)
        self.assertEqual(out["date"], "2026-11-09")
        self.assertEqual(out["weekly"]["spent_cny"], "3.000000")  # Monday only, new week


class HTTPBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.token = load_or_create_token(Path(self.tmp.name) / "api.token")
        self.now = NOON
        self.snap = snapshot(local_source("zcode", today="12", tokens_today=100,
                                          today_apps={"zcode": {"glm-5.3": "12"}}))
        self.service = SnapshotService({"runtime_dir": self.tmp.name},
                                       lambda config, now: copy.deepcopy(self.snap),
                                       lambda: self.now)
        self.server = make_server(self.service, self.token, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:" + str(self.server.server_address[1])

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def request(self, path, method="GET", body=None, auth=True):
        headers = {}
        if auth:
            headers["Authorization"] = "Bearer " + self.token
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        req = urllib.request.Request(self.url + path, headers=headers, data=data, method=method)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return opener.open(req, timeout=3)

    def test_get_requires_auth(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.request("/v1/budget", auth=False)
        self.assertEqual(ctx.exception.code, 401)

    def test_get_not_collected_then_ok(self):
        with self.request("/v1/budget") as r:
            self.assertEqual(json.load(r)["status"], "not_collected")
        with self.request("/v1/snapshot") as r:
            json.load(r)
        with self.request("/v1/budget") as r:
            out = json.load(r)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["daily"]["spent_cny"], "12.000000")
        self.assertEqual(out["date"], TODAY)

    def test_put_validates_and_persists(self):
        with self.request("/v1/budget", "PUT", {"daily_cny": "10", "anomaly_multiplier": "2.5"}) as r:
            saved = json.load(r)
        self.assertEqual(saved["daily_cny"], "10")
        self.assertEqual(load_budget(self.tmp.name)["anomaly_multiplier"], "2.5")
        for bad in [{"daily_cny": "-1"}, {"daily_cny": "abc"}, {"anomaly_multiplier": "0"},
                    {"nope": 1}, []]:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.request("/v1/budget", "PUT", bad)
            self.assertEqual(ctx.exception.code, 400)
            self.assertEqual(json.loads(ctx.exception.read())["error"], "invalid_budget")

    def test_budget_alert_end_to_end(self):
        self.request("/v1/budget", "PUT", {"daily_cny": "10"}).close()
        self.request("/v1/snapshot").close()
        with self.request("/v1/budget") as r:
            out = json.load(r)
        self.assertTrue(out["daily"]["exceeded"])
        self.assertEqual([e["id"] for e in out["events"]], ["budget_daily_exceeded:" + TODAY])
        # A later read the same day yields the identical event id (dedup key).
        with self.request("/v1/budget") as r:
            again = json.load(r)
        self.assertEqual([e["id"] for e in again["events"]], ["budget_daily_exceeded:" + TODAY])


if __name__ == "__main__":
    unittest.main()