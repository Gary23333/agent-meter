import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from agent_meter import reset_forecast as rf
from agent_meter.collector import collect
from agent_meter.model import METRICS, SourceError
from agent_meter.transport import get_text

# 2026-10-15 10:00:00 UTC
NOW = 1792058400.0
# The next 3-6 UTC announcement band after NOW.
NEXT_BAND_OPEN = 1792119600.0


def willreset_payload():
    # raw_24 is the cadence model; prob_24 is the same site's promise floor.
    return {"computed_at": "2026-10-15T10:00:00.123456789Z", "model_version": "cadence-v1",
            "prob_24": 83, "prob_48": 88, "raw_24": 0.3944119973223973, "raw_48": 0.6332631710129518,
            "range_24": [30, 60], "range_48": [50, 85], "confidence": "medium",
            "confidence_note": "Tibo promised a future global reset without a clock.",
            "last_reset_at": "2026-10-15T06:28:13Z", "last_reset_id": "2110618732666257557",
            "last_reset_url": "https://x.com/thsottiaux/status/2110618732666257557",
            "last_reset_text": "Done and dusted", "age_days": 0.14,
            "mean_gap_days": 6.34, "median_gap_days": 2.97, "longest_gap_days": 67.74, "sample": 62,
            "peak_hour_utc": 4, "peak_label": "4 AM–7 AM UTC",
            "promise": {"active": True, "percent": 83, "label": "Explicit future reset, no clock",
                        "quote": "Done and dusted", "url": "https://x.com/thsottiaux/status/2110618732666257557",
                        "at": "2026-10-15T06:28:13Z"},
            "did_reset_today": True, "answer": "yes"}


def codex_reset_payload():
    return {"mode": "model", "updated_at": "2026-10-15T10:00:00.000Z",
            "probabilities": {"raw_24h": 0.1841749019564571, "raw_48h": 0.33442940940224364,
                              "rounded_24h": 18, "rounded_48h": 33, "model_24h": 18, "model_48h": 33,
                              "tease_floor_24h": None, "commitment_floor_percent": None,
                              "range_24h": {"lower": 0.098, "upper": 0.32},
                              "range_48h": {"lower": 0.215, "upper": 0.48}},
            "confidence": "low",
            "confidence_note": "Experimental: walk-forward backtest has not beaten both baselines yet.",
            "last_reset_at": "2026-10-15T06:13:01.000Z", "age_days": 0.2,
            "official_signal": None, "teased_window": None,
            "time_window": {"start_hour": 3, "end_hour": 6, "label": "3 AM - 6 AM", "timezone": "UTC"},
            "cadence": {"recent_median_days": 4, "recent_sample": 5, "weighted_mean_days": 4.9, "accelerating": False},
            "wait_comparison": {"sample": 8, "median_days": 4.3, "mean_days": 5.6, "longest_days": 14.4},
            "context": {"state": "QUIET",
                        "primary_post": {"id": "2109045220411351517", "at": "2026-10-10T22:15:39.000Z",
                                         "url": "https://x.com/thsottiaux/status/2109045220411351517",
                                         "quote": "Day 6/ Reset", "signal": "DONE"}},
            "latest_alert": {"id": "2110595554036400151", "kind": "reset", "state": "confirmed",
                             "source_at": "2026-10-15T06:13:01.000Z", "observed_at": "2026-10-15T06:13:01.000Z",
                             "summary": "Reset observed by operator; awaiting Tibo's confirmation.",
                             "url": "https://x.com/thsottiaux/status/2110595554036400151",
                             "confirmation_source": "operator_observed"},
            "backtest": {"sample_size": 353, "brier": 0.124, "baseline_brier": 0.125, "status": "experimental"},
            "model": {"version": "rate-v3", "base_daily_rate": 0.184}}


ORG_HEAD = ('forecast:$R[256]={activeFeatures:$R[257]=[$R[258]={evidenceKind:"reset-signal",'
            'historicalOccurrences:27,hits24h:17,hits48h:21}],algorithmVersion:"gpt-5.6-medium-hybrid-v2",'
            'baseScore24h:27,baseScore48h:47,calculationBreakdown:$R[259]={method:"gpt-direct",'
            'previousScore24h:20,previousScore48h:38},calibrationSampleSize:81,calibrationState:"experimental",'
            'horizonCalibration:$R[260]={"24h":$R[261]={brierScore:0.178,calibrationSampleSize:82,'
            'calibrationState:"calibrated"},"48h":$R[262]={brierScore:0.270,calibrationSampleSize:81,'
            'calibrationState:"experimental"}},forecastConfidence:"medium",model:"gpt-5.6-sol",'
            'nextReassessmentAt:"2026-10-15T17:01:06.654Z",reasoningEffort:"medium",score24h:25,score48h:40,'
            'semanticSignals:$R[263]=[{score24h:99,score48h:99}]}')

NORMALIZE = {"willreset": lambda: rf.normalize_willreset(willreset_payload(), NOW),
             "codex_reset": lambda: rf.normalize_codex_reset(codex_reset_payload(), NOW),
             "codexreset_org": lambda: rf.normalize_codexreset_org(ORG_HEAD, NOW)}


def rows(*names):
    out = []
    for name in names:
        row = NORMALIZE[name]()
        row.update({"status": "available", "provenance": "https://example.invalid"})
        out.append(row)
    return out


class NormalizeTests(unittest.TestCase):
    def test_nine_digit_fraction_still_parses(self):
        row = rf.normalize_willreset(willreset_payload(), NOW)
        self.assertEqual(row["updated_at"]["utc"], "2026-10-15T10:00:00.123456+00:00")

    def test_cadence_and_promise_floor_stay_separate(self):
        row = rf.normalize_willreset(willreset_payload(), NOW)
        self.assertEqual((row["raw_24h"], row["headline_24h"]), (39.44, 83.0))
        self.assertFalse(row["promise"]["has_clock"])
        self.assertEqual(row["band_24h"], [30.0, 60.0])

    def test_fraction_units_are_converted_per_source(self):
        row = rf.normalize_codex_reset(codex_reset_payload(), NOW)
        self.assertEqual((row["raw_24h"], row["band_24h"]), (18.42, [9.8, 32.0]))
        self.assertEqual(row["self_reported"]["backtest"]["24h"]["state"], "experimental")
        self.assertEqual(row["signal_state"], "QUIET")

    def test_org_reads_only_the_live_forecast_object(self):
        row = rf.normalize_codexreset_org(ORG_HEAD, NOW)
        # The repeated score24h:99 inside semanticSignals must not be picked up.
        self.assertEqual((row["raw_24h"], row["raw_48h"], row["base_24h"]), (25.0, 40.0, 27))
        self.assertEqual(row["self_reported"]["calibration"]["24h"]["state"], "calibrated")
        self.assertIsNone(row["updated_at"])

    def test_org_contract_change_raises_without_guessing(self):
        for page in ("no forecast here", ORG_HEAD.replace("score24h:25,", ""),
                     ORG_HEAD.split("semanticSignals")[0]):
            with self.assertRaises(SourceError):
                rf.normalize_codexreset_org(page, NOW)

    def test_zero_is_a_measurement_not_an_absence(self):
        self.assertEqual(rf._percent(0.0), 0.0)
        self.assertEqual(rf._pair([0, 0]), [0.0, 0.0])

    def test_new_metrics_belong_to_the_contract(self):
        for name in ("reset_forecast", "known_reset_countdown"):
            self.assertIn(name, METRICS)


class CombineTests(unittest.TestCase):
    def test_published_answers_are_pooled_and_internals_stay_metadata(self):
        pooled = rf.combine(rows("willreset", "codex_reset", "codexreset_org"), NOW)
        band = pooled["horizons"]["24h"]
        # willreset publishes 83 while its cadence internals say 39.44; the site's
        # own answer is what a reader of that site sees, so it is what we pool.
        self.assertEqual((band["min"], band["max"], band["n"]), (18.0, 83.0, 3))
        self.assertEqual(pooled["pooled_field"], "each site's own published answer")
        self.assertEqual([item["basis"] for item in band["values"]], ["published_answer"] * 3)
        self.assertEqual(rows("willreset")[0]["raw_24h"], 39.44)

    def test_a_source_without_a_published_answer_falls_back_to_its_model(self):
        row = rows("willreset")[0]
        row["headline_24h"] = row["headline_48h"] = None
        pooled = rf.combine([row], NOW)
        band = pooled["horizons"]["24h"]
        self.assertEqual((band["min"], band["values"][0]["basis"]), (39.44, "cadence_model_fallback"))

    def test_weighted_median_follows_self_reported_quality(self):
        pooled = rf.combine(rows("willreset", "codex_reset", "codexreset_org"), NOW)
        self.assertEqual(pooled["horizons"]["24h"]["weighted_median"], 25.0)
        by = rows("willreset", "codex_reset", "codexreset_org")
        rf.combine(by, NOW)
        scored = {row["source"]: row for row in by}
        self.assertGreater(scored["codexreset_org"]["weight_components"]["weight"],
                           scored["codex_reset"]["weight_components"]["weight"])
        self.assertIn("updated_at_unreported", scored["codexreset_org"]["weight_components"]["notes"])
        self.assertEqual(scored["codex_reset"]["weight_components"]["sample_basis"], "recent_completed_intervals")
        self.assertEqual(scored["codexreset_org"]["weight_components"]["sample_basis"], "calibration_backtest_sample")

    def test_two_sources_are_labelled_split(self):
        pooled = rf.combine(rows("willreset", "codex_reset"), NOW)
        self.assertEqual(pooled["horizons"]["24h"]["agreement"], "split")
        self.assertEqual(pooled["horizons"]["24h"]["n"], 2)

    def test_close_agreement_and_no_usable_source(self):
        self.assertEqual(rf.combine(rows("codex_reset", "codexreset_org"), NOW)["horizons"]["24h"]["agreement"], "close")
        dead = [{"source": "willreset", "status": "error", "reason": "connection_failed", "raw_24h": None}]
        self.assertEqual(rf.combine(dead, NOW)["status"], "no_usable_source")

    def test_stale_source_is_dropped_not_zero_weighted(self):
        row = rf.normalize_willreset(willreset_payload(), NOW)
        row.update({"status": "available", "updated_at": rf.timestamp(NOW - 60 * 3600)})
        self.assertIsNone(rf.score_source(row, NOW)[0])
        self.assertEqual(rf.score_source(row, NOW)[1]["excluded"], "forecast_source_stale")


class CountdownTests(unittest.TestCase):
    def test_unclocked_promise_gives_no_seconds(self):
        targets = rf.countdown_targets(rows("willreset"), NOW)
        self.assertEqual([t["precision"] for t in targets], ["label_only"])
        self.assertTrue(all(t["seconds_remaining_close"] is None for t in targets))

    def test_machine_readable_window_counts_down(self):
        row = rows("codex_reset")[0]
        row["promise"] = {"label": "Landing within the next 2 hours", "quote": "q",
                          "url": "https://x.com/thsottiaux/status/1", "at": rf.timestamp(NOW),
                          "has_clock": True, "floor_percent": 93,
                          "open_at": rf.timestamp(NOW), "close_at": rf.timestamp(NOW + 7200),
                          "basis": "third_party_announced_window"}
        announced = [t for t in rf.countdown_targets([row], NOW) if t["kind"] == "promised_reset"]
        self.assertEqual(len(announced), 1)
        self.assertEqual(announced[0]["state"], "inside_window")
        self.assertEqual(announced[0]["seconds_remaining_close"], 7200.0)

    def test_elapsed_announcement_waits_for_landing_instead_of_hiding(self):
        row = rows("codex_reset")[0]
        row["promise"] = {"has_clock": True, "open_at": rf.timestamp(NOW - 7200),
                          "close_at": rf.timestamp(NOW - 60), "basis": "third_party_announced_window"}
        target = [t for t in rf.countdown_targets([row], NOW) if t["kind"] == "promised_reset"][0]
        self.assertEqual(target["state"], "elapsed_awaiting_landing")
        self.assertLess(target["seconds_remaining_close"], 0)

    def test_next_occurrence_rolls_to_tomorrow(self):
        target = [t for t in rf.countdown_targets(rows("codex_reset"), NOW) if t["precision"] == "window"][0]
        self.assertEqual((target["open_at"]["utc"], target["close_at"]["utc"]),
                         ("2026-10-16T03:00:00+00:00", "2026-10-16T06:00:00+00:00"))
        self.assertEqual(target["seconds_remaining_open"], NEXT_BAND_OPEN - NOW)

    def test_same_band_from_two_sources_is_one_target_not_two(self):
        pair = rows("codex_reset", "codex_reset")
        pair[1].update({"source": "willreset", "name": "Will Codex Reset"})
        bands = [t for t in rf.countdown_targets(pair, NOW) if t["precision"] == "window"]
        self.assertEqual(len(bands), 1)
        self.assertEqual(bands[0]["sources"], ["codex_reset", "willreset"])


class HistoryTests(unittest.TestCase):
    WILL = {"events": [{"id": "1", "kind": "reset", "announced_at": "2026-10-15T06:28:13Z",
                        "summary": "Done and dusted", "body": "Done and dusted https://t.co/x",
                        "source_url": "https://x.com/thsottiaux/status/1", "scope": "global",
                        "confidence": "high"},
                       {"id": "2", "kind": "banked", "announced_at": "2026-10-13T05:06:10Z",
                        "summary": "Side order", "body": "leak", "source_url": "https://x.com/thsottiaux/status/2"}]}
    RADAR = {"events": [{"id": "1", "group": "reset", "announced_at": "2026-10-15T06:13:01.000Z",
                         "effective_at": None,
                         "official_window": {"start": "2026-10-15T04:56:07.000Z", "end": "2026-10-15T06:56:07.000Z"},
                         "summary": "Day 10 of the 28-day series",
                         "url": "https://x.com/thsottiaux/status/1", "scope": "global",
                         "confidence": "high", "confirmed": True, "banked_grant": False},
                        {"id": "3", "group": "credits", "announced_at": "not-a-time", "summary": "no usable time"}]}

    def test_ids_merge_and_bodies_stay_out(self):
        merged = rf.merge_history({"willreset": rf.normalize_history("willreset", self.WILL),
                                   "codex_reset": rf.normalize_history("codex_reset", self.RADAR)})
        first = [e for e in merged if e["post_id"] == "1"][0]
        self.assertEqual(first["sources"], ["codex_reset", "willreset"])
        # The earlier of the two reports of the same event wins the announced time.
        self.assertEqual(first["announced_at"]["utc"], "2026-10-15T06:13:01+00:00")
        self.assertTrue(all("body" not in event for event in merged))
        self.assertEqual(first["official_window"]["close_at"]["utc"], "2026-10-15T06:56:07+00:00")
        # The third radar event has an unparseable time and must not become a row.
        self.assertEqual([e["post_id"] for e in merged], ["1", "2"])

    def test_history_without_any_usable_event_fails(self):
        with self.assertRaises(SourceError):
            rf.normalize_history("willreset", {"events": [{"id": None}]})
        with self.assertRaises(SourceError):
            rf.normalize_history("willreset", {"nope": 1})


class CollectTests(unittest.TestCase):
    def fetchers(self, available=("willreset", "codex_reset", "codexreset_org"), with_history=True, calls=None):
        def forecast(key):
            def run(now):
                if calls is not None:
                    calls.append(key)
                if key not in available:
                    raise SourceError("connection_failed")
                return NORMALIZE[key]()
            return run

        def history(key):
            def run():
                return rf.normalize_history(key, HistoryTests.WILL if key == "willreset" else HistoryTests.RADAR)
            return run

        return {key: {"forecast": forecast(key),
                      "history": history(key) if (key in available and key != "codexreset_org" and with_history) else None}
                for key in rf.SOURCES}

    def test_three_sources_available_and_reset_time_stays_untouched(self):
        out = rf.collect_reset_forecast(now=NOW, fetchers=self.fetchers())
        self.assertEqual(out["status"], "available")
        self.assertEqual(out["scope"], "external_forecast")
        self.assertEqual(out["metrics"]["reset_time"]["status"], "not_provided")
        self.assertEqual(out["metrics"]["reset_forecast"]["status"], "available")
        self.assertEqual(out["metrics"]["known_reset_countdown"]["status"], "available")
        self.assertEqual(out["diagnostics"]["sources_available"], 3)
        self.assertEqual(len(out["metrics"]["reset_forecast"]["value"]["history_events"]), 2)

    def test_one_source_down_is_partial_not_silent(self):
        out = rf.collect_reset_forecast(now=NOW, fetchers=self.fetchers(available=("willreset", "codex_reset")))
        self.assertEqual(out["status"], "partial")
        self.assertEqual(out["diagnostics"]["sources_available"], 2)
        failed = [r for r in out["metrics"]["reset_forecast"]["value"]["sources"] if r["source"] == "codexreset_org"][0]
        self.assertEqual(failed["reason"], "connection_failed")

    def test_no_countdown_is_not_provided_never_zero(self):
        # Only the HTML source answers: it publishes neither a band nor a promise.
        out = rf.collect_reset_forecast(now=NOW, fetchers=self.fetchers(available=("codexreset_org",)))
        self.assertEqual(out["metrics"]["reset_forecast"]["status"], "available")
        self.assertEqual(out["metrics"]["known_reset_countdown"]["status"], "not_provided")
        self.assertIsNone(out["metrics"]["known_reset_countdown"]["value"])
        self.assertEqual(out["metrics"]["known_reset_countdown"]["reason"], "no_machine_readable_reset_time")

    def test_no_cache_and_no_network_raises_one_safe_code(self):
        with self.assertRaisesRegex(SourceError, "reset_forecast_sources_unavailable"):
            rf.collect_reset_forecast(now=NOW, fetchers=self.fetchers(available=()))

    def test_cache_throttles_and_stale_values_survive_a_total_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp)/"reset-forecast.json")
            first = rf.collect_reset_forecast(now=NOW, fetchers=self.fetchers(), cache_path=path)
            self.assertEqual(first["metrics"]["reset_forecast"]["value"]["cache_state"], "fresh")
            calls = []
            dead = self.fetchers(available=(), calls=calls)
            second = rf.collect_reset_forecast(now=NOW + 60, fetchers=dead, cache_path=path)
            self.assertEqual(calls, [])
            self.assertEqual(second["metrics"]["reset_forecast"]["value"]["cache_state"], "served_from_cache")
            third = rf.collect_reset_forecast(now=NOW + 46 * 60, fetchers=dead, cache_path=path)
            self.assertEqual(third["metrics"]["reset_forecast"]["status"], "stale")
            self.assertEqual(len(third["metrics"]["reset_forecast"]["value"]["sources"]), 3)
            self.assertEqual(third["status"], "partial")

    def test_a_failed_source_is_retried_before_the_full_throttle(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp)/"reset-forecast.json")
            rf.collect_reset_forecast(now=NOW, fetchers=self.fetchers(available=("willreset",), with_history=False),
                                      cache_path=path)
            calls = []
            rf.collect_reset_forecast(now=NOW + 6 * 60, fetchers=self.fetchers(with_history=False, calls=calls),
                                      cache_path=path)
            self.assertEqual(len(calls), 3)
            calls.clear()
            rf.collect_reset_forecast(now=NOW + 8 * 60, fetchers=self.fetchers(with_history=False, calls=calls),
                                      cache_path=path)
            self.assertEqual(calls, [])

    def test_countdowns_recount_on_every_read(self):
        out = rf.collect_reset_forecast(now=NOW, fetchers=self.fetchers())
        snapshot = rf.refresh_forecast_countdowns({"sources": [out]}, NOW + 3600)
        target = snapshot["sources"][0]["metrics"]["known_reset_countdown"]["value"]["targets"][0]
        self.assertEqual(target["seconds_remaining_open"], NEXT_BAND_OPEN - NOW - 3600)


class ServiceTests(unittest.TestCase):
    def config(self, tmp, **extra):
        out = {"app_roots": [], "runtime_dir": tmp, "ccswitch_db": str(Path(tmp)/"none.db")}
        out.update(extra)
        return out

    def test_collector_runs_the_source_offline_and_keeps_it_out_of_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(rf, "default_fetchers",
                                   lambda with_history: CollectTests().fetchers(with_history=with_history)):
                service = collect(self.config(tmp), now=NOW)
            src = [s for s in service["sources"] if s["id"] == "reset_forecast"]
            self.assertEqual(len(src), 1)
            self.assertEqual(src[0]["metrics"]["reset_forecast"]["status"], "available")
            self.assertTrue((Path(tmp)/"reset-forecast.json").is_file())
            self.assertNotIn("reset_forecast", [r["application"]["provider"] for r in service["coverage"]])

    def test_config_switch_stops_the_network_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = collect(self.config(tmp, enable_reset_forecast=False), now=NOW)
            src = [s for s in service["sources"] if s["id"] == "reset_forecast"][0]
            self.assertEqual(src["status"], "not_connected")
            self.assertEqual(src["metrics"]["reset_forecast"]["reason"], "disabled_in_config")

    def test_the_app_preference_switch_stops_it_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(rf, "default_fetchers", lambda with_history: {}):
                service = collect(self.config(tmp, preferences={"disabled_sources": ["reset_forecast"]}), now=NOW)
            src = [s for s in service["sources"] if s["id"] == "reset_forecast"][0]
            self.assertEqual(src["status"], "not_connected")


class TransportTests(unittest.TestCase):
    def test_text_route_keeps_the_same_url_guards(self):
        for url in ("http://example.com/page", "https://user:secret@example.com/page"):
            with self.assertRaises(SourceError):
                get_text(url)
        with self.assertRaisesRegex(SourceError, "non_loopback_endpoint"):
            get_text("http://example.com/page", local=True)

    def test_oversized_page_is_rejected_not_truncated(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = b"<html>" + b"x" * 4096 + b"</html>"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = "http://127.0.0.1:" + str(server.server_address[1]) + "/"
            self.assertEqual(len(get_text(url, local=True)), 6 + 4096 + 7)
            with self.assertRaisesRegex(SourceError, "response_too_large"):
                get_text(url, local=True, max_bytes=1024)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
