import json
import tempfile
import unittest
from pathlib import Path

from agent_meter import pet
from agent_meter import reset_forecast as rf
from agent_meter import reset_landings as rl
from agent_meter.model import SourceError, timestamp

from tests import test_reset_forecast as forecast_tests

# 2026-10-15 10:00:00 UTC
NOW = 1792058400.0


def reset_event(post_id="100", announced=None, effective=None, confidence="high",
                kind="reset", window=None, sources=None):
    return {"post_id": post_id, "kind": kind, "confidence": confidence,
            "announced_at": timestamp(NOW - 3600 if announced is None else announced),
            "effective_at": timestamp(effective) if effective is not None else None,
            "official_window": window, "summary": "Done and dusted",
            "sources": ["willreset", "codex_reset"] if sources is None else sources}


def window(opened, close):
    return {"open_at": timestamp(opened), "close_at": timestamp(close)}


def ensemble(median24=25.0, median48=40.0):
    return {"status": "available", "horizons": {
        "24h": {"min": 18.0, "max": 83.0, "spread": 65.0, "n": 3, "weighted_median": median24,
                "agreement": "split",
                "values": [{"source": "codex_reset", "percent": 18.0, "basis": "published_answer"}]},
        "48h": {"min": 33.0, "max": 88.0, "spread": 55.0, "n": 3, "weighted_median": median48,
                "agreement": "split", "values": []}}}


def source_row(name="willreset", headline24=83.0):
    return {"source": name, "name": name, "status": "available", "headline_24h": headline24,
            "headline_48h": 88.0, "band_24h": [30.0, 60.0], "band_48h": [50.0, 85.0], "weight": 0.7}


def forecast(events=None, ens=None, sources=None):
    return {"history_events": [reset_event()] if events is None else events,
            "ensemble": ensemble() if ens is None else ens,
            "sources": [source_row()] if sources is None else sources, "promises": []}


class DetectLandingTests(unittest.TestCase):
    def test_matches_pet_recent_landing_verbatim(self):
        cases = [forecast(), forecast(events=[]),
                 forecast(events=[reset_event(confidence="low")]),
                 forecast(events=[reset_event(confidence=None)]),
                 forecast(events=[reset_event(kind="banked")]),
                 forecast(events=[reset_event(announced=NOW + 60)]),
                 forecast(events=[reset_event(announced=NOW - 2 * 86400)]),
                 forecast(events=[reset_event(announced=NOW - 2 * 86400, confidence="medium")])]
        for case in cases:
            for within in (86400, 3 * 86400):
                self.assertEqual(rl.detect_landing(case, NOW, within),
                                 pet.recent_landing(case, NOW, within))

    def test_confident_reset_within_window_is_a_landing(self):
        event = reset_event(confidence="medium")
        self.assertEqual(rl.detect_landing(forecast(events=[event]), NOW), event)

    def test_unknown_confidence_is_not_a_landing(self):
        self.assertIsNone(rl.detect_landing(forecast(events=[reset_event(confidence=None)]), NOW))

    def test_only_the_newest_event_counts(self):
        old = reset_event(post_id="old", announced=NOW - 3600)
        newest = reset_event(post_id="new", announced=NOW - 60, kind="banked")
        self.assertIsNone(rl.detect_landing(forecast(events=[newest, old]), NOW))


class RecordLandingTests(unittest.TestCase):
    def test_snapshot_deviation_and_window_hit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / rl.LANDINGS_NAME
            event = reset_event(effective=NOW - 2000,
                                window=window(NOW - 5400, NOW - 1800))
            record = rl.record_landing(str(path), forecast(events=[event]), NOW)
            self.assertEqual(record["event_id"], "100")
            self.assertEqual(record["observed_basis"], "effective_at")
            self.assertEqual(record["deviation"]["expected_basis"], "official_window_close")
            self.assertEqual(record["deviation"]["seconds"], -200.0)
            self.assertTrue(record["deviation"]["within_official_window"])
            self.assertEqual(record["forecast"]["ensemble"]["24h"]["weighted_median"], 25.0)
            self.assertEqual(record["forecast"]["sources"][0]["headline_24h"], 83.0)
            self.assertNotIn("reset_time", record)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(len(json.loads(path.read_text())["records"]), 1)

    def test_no_effective_falls_back_to_announced_and_deviation_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / rl.LANDINGS_NAME
            record = rl.record_landing(str(path), forecast(events=[reset_event()]), NOW)
            self.assertEqual(record["observed_basis"], "announced_at")
            self.assertEqual(record["observed_at"], record["announced_at"])
            self.assertIsNone(record["deviation"]["seconds"])
            self.assertIsNone(record["deviation"]["expected_basis"])

    def test_landing_lag_without_window_uses_announced_basis(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / rl.LANDINGS_NAME
            event = reset_event(effective=NOW - 1800)
            record = rl.record_landing(str(path), forecast(events=[event]), NOW)
            self.assertEqual(record["deviation"]["expected_basis"], "announced_at")
            self.assertEqual(record["deviation"]["seconds"], 1800.0)
            self.assertIsNone(record["deviation"]["within_official_window"])

    def test_first_observation_wins_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / rl.LANDINGS_NAME
            first = rl.record_landing(str(path), forecast(events=[reset_event()]), NOW)
            again = rl.record_landing(str(path), forecast(events=[reset_event()], ens=ensemble(99.0)), NOW + 60)
            self.assertEqual(again, first)
            self.assertEqual(len(json.loads(path.read_text())["records"]), 1)

    def test_no_landing_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / rl.LANDINGS_NAME
            self.assertIsNone(rl.record_landing(str(path), forecast(events=[reset_event(confidence="low")]), NOW))
            self.assertFalse(path.exists())

    def test_event_without_id_is_not_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / rl.LANDINGS_NAME
            self.assertIsNone(rl.record_landing(str(path), forecast(events=[reset_event(post_id=None)]), NOW))
            self.assertFalse(path.exists())

    def test_corrupt_store_refuses_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / rl.LANDINGS_NAME
            path.write_text("this is not json")
            with self.assertRaisesRegex(SourceError, "landing_store_corrupt"):
                rl.record_landing(str(path), forecast(), NOW)
            self.assertEqual(path.read_text(), "this is not json")

    def test_wrong_schema_is_corrupt(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / rl.LANDINGS_NAME
            path.write_text(json.dumps({"schema": 2, "records": []}))
            with self.assertRaisesRegex(SourceError, "landing_store_corrupt"):
                rl.record_landing(str(path), forecast(), NOW)


class ScorecardTests(unittest.TestCase):
    def build(self, path):
        a = reset_event(post_id="A", effective=NOW - 2000, window=window(NOW - 5400, NOW - 1800))
        b = reset_event(post_id="B", effective=NOW - 1000, window=window(NOW - 5400, NOW - 1800))
        c = reset_event(post_id="C", effective=NOW - 1800)
        for event in (a, b, c):
            rl.record_landing(str(path), forecast(events=[event]), NOW)

    def test_empty_store_is_unknown_not_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            card = rl.landing_scorecard(str(Path(tmp) / rl.LANDINGS_NAME))
            self.assertEqual(card["n_records"], 0)
            self.assertIsNone(card["window_hit_rate"])
            self.assertEqual(card["deviation_seconds"]["count"], 0)
            self.assertIsNone(card["deviation_seconds"]["median"])

    def test_hit_rate_and_deviation_distribution(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / rl.LANDINGS_NAME
            self.build(path)
            card = rl.landing_scorecard(str(path))
            self.assertEqual(card["n_records"], 3)
            self.assertEqual((card["window_hits"], card["n_with_window"]), (1, 2))
            self.assertEqual(card["window_hit_rate"], 0.5)
            dev = card["deviation_seconds"]
            self.assertEqual((dev["count"], dev["min"], dev["max"], dev["median"], dev["mean"]),
                             (3, -200.0, 1800.0, 800.0, 800.0))
            lag = card["announcement_to_landing_seconds"]
            self.assertEqual((lag["count"], lag["min"], lag["max"], lag["median"]),
                             (3, 1600.0, 2600.0, 1800.0))
            self.assertEqual(card["weighted_median_24h"]["median"], 25.0)
            self.assertEqual(len(card["records"]), 3)

    def test_corrupt_store_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / rl.LANDINGS_NAME
            path.write_text("{broken")
            with self.assertRaisesRegex(SourceError, "landing_store_corrupt"):
                rl.landing_scorecard(str(path))


class ManualTests(unittest.TestCase):
    def test_add_writes_a_fact_only_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / rl.MANUAL_NAME
            event = rl.add_manual_announcement(str(path), NOW - 7200, "Tibo said soon")
            self.assertEqual(event["origin"], "manual")
            self.assertEqual(event["kind"], "reset")
            self.assertEqual(event["sources"], ["manual"])
            self.assertEqual(event["summary"], "Tibo said soon")
            self.assertEqual(event["announced_at"]["epoch_seconds"], NOW - 7200)
            self.assertIsNone(event["confidence"])
            self.assertIsNone(event["effective_at"])
            self.assertIsNone(event["official_window"])
            self.assertTrue(event["post_id"].startswith("manual:"))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_same_time_and_note_dedups(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / rl.MANUAL_NAME
            first = rl.add_manual_announcement(str(path), NOW - 7200, "soon")
            again = rl.add_manual_announcement(str(path), NOW - 7200, "soon")
            self.assertEqual(again["post_id"], first["post_id"])
            self.assertEqual(len(json.loads(path.read_text())["announcements"]), 1)

    def test_different_note_or_time_is_a_new_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / rl.MANUAL_NAME
            rl.add_manual_announcement(str(path), NOW - 7200, "soon")
            rl.add_manual_announcement(str(path), NOW - 7200, "later")
            rl.add_manual_announcement(str(path), NOW - 3600, "soon")
            self.assertEqual(len(json.loads(path.read_text())["announcements"]), 3)

    def test_invalid_time_is_rejected_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / rl.MANUAL_NAME
            for bad in (True, "abc", -1, None, 1e18):
                with self.assertRaisesRegex(SourceError, "manual_announcement_invalid"):
                    rl.add_manual_announcement(str(path), bad, "note")
            self.assertFalse(path.exists())

    def test_non_string_note_stays_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / rl.MANUAL_NAME
            event = rl.add_manual_announcement(str(path), NOW - 7200, 123)
            self.assertIsNone(event["summary"])

    def test_corrupt_store_refuses_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / rl.MANUAL_NAME
            path.write_text("garbage")
            with self.assertRaisesRegex(SourceError, "manual_store_corrupt"):
                rl.add_manual_announcement(str(path), NOW - 7200, "note")
            self.assertEqual(path.read_text(), "garbage")

    def test_row_missing_announced_at_is_corrupt(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / rl.MANUAL_NAME
            path.write_text(json.dumps({"schema": 1, "announcements": [{"post_id": "manual:x"}]}))
            with self.assertRaisesRegex(SourceError, "manual_store_corrupt"):
                rl.add_manual_announcement(str(path), NOW - 7200, "note")

    def test_manual_is_never_a_landing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / rl.MANUAL_NAME
            event = rl.add_manual_announcement(str(path), NOW - 7200, "soon")
            self.assertIsNone(rl.detect_landing(forecast(events=[event]), NOW))


class MergeTests(unittest.TestCase):
    def test_manual_merges_keeping_origin(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / rl.MANUAL_NAME
            rl.add_manual_announcement(str(path), NOW - 7200, "soon")
            manual = rl.load_manual_announcements(str(path))
            per_source = {"willreset": rf.normalize_history("willreset", {
                "events": [{"id": "1", "kind": "reset", "announced_at": "2026-10-15T06:28:13Z",
                            "summary": "Done", "confidence": "high"}]})}
            merged = rl.merge_manual_history(per_source, manual)
            origins = {e["post_id"]: e.get("origin") for e in merged}
            self.assertEqual(origins["1"], None)
            self.assertIn("manual", [e.get("origin") for e in merged])
            self.assertEqual(len(merged), 2)

    def test_manual_and_tracker_at_same_time_stay_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / rl.MANUAL_NAME
            rl.add_manual_announcement(str(path), NOW - 3600, "soon")
            manual = rl.load_manual_announcements(str(path))
            tracker = [reset_event(post_id="1", announced=NOW - 3600)]
            merged = rl.merge_manual_history({"willreset": tracker}, manual)
            self.assertEqual(len(merged), 2)
            self.assertEqual(sorted(e["post_id"] for e in merged)[0], "1")

    def test_collect_hook_includes_manual_without_regression(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / rl.MANUAL_NAME
            rl.add_manual_announcement(str(path), NOW - 7200, "soon")
            out = rf.collect_reset_forecast(now=NOW, fetchers=forecast_tests.CollectTests().fetchers(),
                                            manual_store_path=str(path))
            value = out["metrics"]["reset_forecast"]["value"]
            self.assertIn("manual", [e.get("origin") for e in value["history_events"]])
            self.assertIn("manual", value["history_sources"])
            self.assertEqual(out["diagnostics"]["manual_announcements"], 1)
            self.assertEqual(out["metrics"]["reset_time"]["status"], "not_provided")

    def test_collect_hook_corrupt_manual_degrades_gracefully(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / rl.MANUAL_NAME
            path.write_text("garbage")
            out = rf.collect_reset_forecast(now=NOW, fetchers=forecast_tests.CollectTests().fetchers(),
                                            manual_store_path=str(path))
            self.assertEqual(out["metrics"]["reset_forecast"]["status"], "available")
            self.assertEqual(out["diagnostics"]["manual_store_state"], "manual_store_corrupt")
            self.assertNotIn("manual", [e.get("origin") for e in
                                        out["metrics"]["reset_forecast"]["value"]["history_events"]])

    def test_collect_default_has_no_manual_keys(self):
        out = rf.collect_reset_forecast(now=NOW, fetchers=forecast_tests.CollectTests().fetchers())
        self.assertNotIn("manual_announcements", out["diagnostics"])
        self.assertNotIn("manual", out["metrics"]["reset_forecast"]["value"]["history_sources"])


if __name__ == "__main__":
    unittest.main()