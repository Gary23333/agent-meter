import copy
import csv
import io
import json
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from agent_meter.export_data import CSV_COLUMNS, export_csv, export_payload
from agent_meter.model import timestamp

ZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 11, 12, 12, 0, tzinfo=ZONE).timestamp()
OBSERVED = timestamp(NOW - 3600)


def daily_row(date="2026-11-10", model="model-x", app=None, **fields):
    row = {"date": date, "model": model, "requests": 2, "fresh_input": 100, "output": 20,
           "reasoning": 5, "cache_read": 30, "cache_write": 4, "total_tokens": 159}
    row.update(fields)
    if app is not None:
        row["app"] = app
    return row


def metric(value, status="available"):
    return {"status": status, "value": value, "reason": None}


def source(sid, scope="local_session_history", tokens=None, quota=None, account_key=None):
    src = {"id": sid, "scope": scope, "status": "available", "observed_at": OBSERVED,
           "metrics": {"tokens": tokens if tokens is not None else metric(None, "not_provided"),
                       "quota": quota if quota is not None else metric(None, "not_provided")}}
    if account_key is not None:
        src["account_key"] = account_key
    return src


def snapshot(*sources, collection=None):
    out = {"schema_version": 5, "sources": list(sources)}
    if collection is not None:
        out["collection"] = collection
    return out


def usage(snapshot_like):
    return export_payload(snapshot_like, NOW)["usage_daily"]


class UsageDailyTests(unittest.TestCase):
    def test_each_ledger_signed_and_never_merged(self):
        # Same day/app/model in two independent ledgers must stay two rows.
        row = daily_row(app="codex", total_tokens=159)
        snap = snapshot(
            source("codex", scope="account", tokens=metric({"daily_models": [row]})),
            source("imported_history", scope="local_imported_history",
                   tokens=metric({"daily_models": [dict(row, total_tokens=159, output=25)]})),
        )
        rows = usage(snap)
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["ledger"] for r in rows}, {"codex", "imported_history"})
        by_ledger = {r["ledger"]: r for r in rows}
        self.assertEqual(by_ledger["codex"]["output"], 20)
        self.assertEqual(by_ledger["imported_history"]["output"], 25)
        self.assertEqual(by_ledger["imported_history"]["app"], "codex")

    def test_account_scope_local_ledgers_included(self):
        # Real snapshots attach local ledgers to account-scope sources (codex/claude/kimi/zcode).
        snap = snapshot(
            source("zcode", scope="account", tokens=metric({"daily_models": [daily_row(app="zcode")]})),
            source("opencode", tokens=metric({"daily_models": [daily_row(app="opencode")]})),
        )
        self.assertEqual({r["ledger"] for r in usage(snap)}, {"zcode", "opencode"})

    def test_full_row_projection(self):
        row = daily_row(app="kimi", unclassified=7, total_tokens=166)
        out = usage(snapshot(source("kimi", scope="account", tokens=metric({"daily_models": [row]}))))[0]
        self.assertEqual(out, {"date": "2026-11-10", "ledger": "kimi", "app": "kimi", "model": "model-x",
                               "requests": 2, "fresh_input": 100, "output": 20, "reasoning": 5,
                               "cache_read": 30, "cache_write": 4, "unclassified": 7, "total_tokens": 166})

    def test_missing_fields_are_null_not_zero(self):
        sparse = {"date": "2026-11-10", "model": "m", "total_tokens": 42}
        out = usage(snapshot(source("kimi_legacy", tokens=metric({"daily_models": [sparse]}))))[0]
        for field in ("requests", "fresh_input", "output", "reasoning", "cache_read", "cache_write", "unclassified"):
            self.assertIsNone(out[field], field)
        self.assertEqual(out["total_tokens"], 42)
        self.assertEqual(out["app"], "kimi_legacy")

    def test_missing_total_is_not_derived(self):
        row = daily_row()
        del row["total_tokens"]
        out = usage(snapshot(source("kimi", tokens=metric({"daily_models": [row]}))))[0]
        self.assertIsNone(out["total_tokens"])

    def test_unavailable_tokens_skipped_stale_kept(self):
        for status in ("not_provided", "not_connected", "error", "not_supported"):
            snap = snapshot(source("kimi", tokens=metric({"daily_models": [daily_row()]}, status)))
            self.assertEqual(usage(snap), [], status)
        snap = snapshot(source("kimi", tokens=metric({"daily_models": [daily_row()]}, "stale")))
        self.assertEqual(len(usage(snap)), 1)

    def test_bucket_fallback_when_no_model_detail(self):
        snap = snapshot(source("gemini", tokens=metric({"daily_buckets": [{"date": "2026-11-10", "tokens": 900}]})))
        rows = usage(snap)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["ledger"], "gemini")
        self.assertEqual(row["app"], "gemini")
        self.assertEqual(row["date"], "2026-11-10")
        self.assertEqual(row["total_tokens"], 900)
        for field in ("model", "requests", "fresh_input", "output", "reasoning", "cache_read", "cache_write"):
            self.assertIsNone(row[field], field)

    def test_buckets_not_double_counted_with_models(self):
        value = {"daily_models": [daily_row(app="kimi")],
                 "daily_buckets": [{"date": "2026-11-10", "tokens": 159}]}
        rows = usage(snapshot(source("kimi", tokens=metric(value))))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["model"], "model-x")

    def test_imported_history_bucket_app_unknown(self):
        snap = snapshot(source("imported_history", scope="local_imported_history",
                               tokens=metric({"daily_buckets": [{"date": "2026-11-10", "tokens": 5}]})))
        self.assertIsNone(usage(snap)[0]["app"])

    def test_multi_account_slot_keeps_signature(self):
        snap = snapshot(source("kimi#2", scope="account", tokens=metric({"daily_models": [daily_row()]})))
        row = usage(snap)[0]
        self.assertEqual(row["ledger"], "kimi#2")
        self.assertEqual(row["app"], "kimi")

    def test_sorted_by_date_ledger_app_model(self):
        rows = [daily_row(date="2026-11-11", model="a", app="zapp"),
                daily_row(date="2026-11-10", model="b", app="app"),
                daily_row(date="2026-11-10", model="a", app="app")]
        snap = snapshot(source("zled", tokens=metric({"daily_models": rows[:2]})),
                        source("aled", tokens=metric({"daily_models": rows[2:]})))
        keys = [(r["date"], r["ledger"], r["app"], r["model"]) for r in usage(snap)]
        self.assertEqual(keys, [("2026-11-10", "aled", "app", "a"),
                                ("2026-11-10", "zled", "app", "b"),
                                ("2026-11-11", "zled", "zapp", "a")])

    def test_no_amount_fields_exported(self):
        snap = snapshot(source("kimi", tokens=metric({"daily_models": [daily_row()]})))
        for row in usage(snap):
            for key in row:
                self.assertNotIn("cost", key)
                self.assertNotIn("amount", key)
                self.assertNotIn("price", key)


class QuotaObservationTests(unittest.TestCase):
    def quota_row(self, **fields):
        row = {"bucket": "quota", "used_percent": 42.73, "remaining_percent": 57.27,
               "used": 4272, "limit": 10000, "remaining": 5727, "unit": "zcode_credits",
               "window_minutes": 10080, "resets_at": OBSERVED}
        row.update(fields)
        return row

    def test_list_rows_projected_with_signature(self):
        snap = snapshot(source("zcode", scope="account", account_key="abc123",
                               quota=metric([self.quota_row(), self.quota_row(bucket="other", used_percent=0.0)])))
        obs = export_payload(snap, NOW)["quota_observations"]
        self.assertEqual(len(obs), 2)
        first = obs[0]
        self.assertEqual(first["account"], "zcode")
        self.assertEqual(first["account_key"], "abc123")
        self.assertEqual(first["observed_at"], OBSERVED)
        self.assertEqual(first["status"], "available")
        self.assertEqual(first["used_percent"], 42.73)
        self.assertEqual(first["resets_at"], OBSERVED)
        self.assertEqual(obs[1]["used_percent"], 0.0)

    def test_dict_rows_variant(self):
        snap = snapshot(source("codex", scope="account", quota=metric({"rows": [self.quota_row()]})))
        obs = export_payload(snap, NOW)["quota_observations"]
        self.assertEqual(len(obs), 1)
        self.assertEqual(obs[0]["account"], "codex")

    def test_unavailable_or_empty_quota_is_empty_array(self):
        for entry in (metric(None, "not_connected"), metric(None, "error"),
                      metric(None, "available"), metric([], "available")):
            snap = snapshot(source("zcode", scope="account", quota=entry))
            self.assertEqual(export_payload(snap, NOW)["quota_observations"], [])

    def test_missing_fields_not_fabricated(self):
        snap = snapshot(source("stepfun", scope="account", quota=metric([{"bucket": "limit5h"}])))
        obs = export_payload(snap, NOW)["quota_observations"][0]
        self.assertNotIn("used_percent", obs)
        self.assertNotIn("window", obs)
        self.assertIsNone(obs["account_key"])

    def test_stale_quota_kept_with_status(self):
        snap = snapshot(source("codex", scope="account", quota=metric([self.quota_row()], "stale")))
        obs = export_payload(snap, NOW)["quota_observations"]
        self.assertEqual(obs[0]["status"], "stale")
        self.assertEqual(obs[0]["observed_at"], OBSERVED)

    def test_local_sources_without_quota_contribute_nothing(self):
        snap = snapshot(source("opencode", tokens=metric({"daily_models": [daily_row()]})))
        self.assertEqual(export_payload(snap, NOW)["quota_observations"], [])


class CardsTests(unittest.TestCase):
    def collection(self):
        return {"schema_version": 1,
                "cards": {"sp_welcome": {"count": 1, "first_at": OBSERVED, "last_at": OBSERVED, "sources": []},
                          "q5_50": {"count": 3, "first_at": OBSERVED, "last_at": OBSERVED, "sources": ["zcode"]}},
                "stats": {"total_cards": 4, "distinct_cards": 2, "catalog_size": 16,
                          "by_rarity": {"common": 3, "rare": 1, "epic": 0, "legendary": 0, "faded": 0}}}

    def test_cards_projection(self):
        cards = export_payload(snapshot(collection=self.collection()), NOW)["cards"]
        self.assertEqual(cards["total_cards"], 4)
        self.assertEqual(cards["distinct_cards"], 2)
        self.assertEqual(cards["catalog_size"], 16)
        self.assertEqual(cards["by_rarity"]["common"], 3)
        self.assertEqual(cards["cards"], {"q5_50": 3, "sp_welcome": 1})

    def test_missing_collection_is_null(self):
        self.assertIsNone(export_payload(snapshot(), NOW)["cards"])
        self.assertIsNone(export_payload({}, NOW)["cards"])

    def test_empty_collection_no_zeros(self):
        cards = export_payload(snapshot(collection={}), NOW)["cards"]
        self.assertIsNone(cards["total_cards"])
        self.assertIsNone(cards["distinct_cards"])
        self.assertIsNone(cards["by_rarity"])
        self.assertEqual(cards["cards"], {})

    def test_empty_binder_is_measured_empty(self):
        coll = {"cards": {}, "stats": {"total_cards": 0, "distinct_cards": 0}}
        cards = export_payload(snapshot(collection=coll), NOW)["cards"]
        self.assertEqual(cards["total_cards"], 0)
        self.assertEqual(cards["cards"], {})


class PayloadTests(unittest.TestCase):
    def test_envelope(self):
        payload = export_payload(snapshot(), NOW)
        self.assertEqual(set(payload), {"schema", "generated_at", "timezone",
                                        "usage_daily", "quota_observations", "cards"})
        self.assertEqual(payload["schema"], 1)
        self.assertEqual(payload["generated_at"], timestamp(NOW))
        self.assertEqual(payload["timezone"], "Asia/Shanghai")
        self.assertEqual(payload["usage_daily"], [])
        self.assertEqual(payload["quota_observations"], [])
        self.assertIsNone(payload["cards"])

    def test_empty_and_none_snapshots(self):
        for empty in ({}, {"sources": []}, None):
            payload = export_payload(empty, NOW)
            self.assertEqual(payload["usage_daily"], [])
            self.assertEqual(payload["quota_observations"], [])
            self.assertIsNone(payload["cards"])
            self.assertEqual(export_csv(empty), ",".join(CSV_COLUMNS) + "\r\n")

    def test_json_serializable_and_deterministic(self):
        snap = snapshot(source("kimi", tokens=metric({"daily_models": [daily_row()]})),
                        collection={"cards": {"sp_welcome": {"count": 1}}})
        first = export_payload(snap, NOW)
        self.assertEqual(json.loads(json.dumps(first)), first)
        self.assertEqual(export_payload(snap, NOW), first)
        self.assertEqual(export_csv(snap), export_csv(snap))

    def test_inputs_not_mutated(self):
        snap = snapshot(source("zcode", scope="account",
                               tokens=metric({"daily_models": [daily_row()]}),
                               quota=metric([{"bucket": "quota", "used_percent": 1.0, "resets_at": OBSERVED}])),
                        collection={"cards": {"sp_welcome": {"count": 1}},
                                    "stats": {"total_cards": 1, "by_rarity": {"rare": 1}}})
        before = copy.deepcopy(snap)
        export_payload(snap, NOW)
        export_csv(snap)
        self.assertEqual(snap, before)

    def test_malformed_entries_skipped(self):
        snap = {"sources": [None, "junk", {"id": "x"},
                            source("kimi", tokens=metric({"daily_models": [None, "junk", daily_row()]}))]}
        rows = usage(snap)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ledger"], "kimi")


class CsvTests(unittest.TestCase):
    def test_header_and_rfc4180_line_endings(self):
        text = export_csv(snapshot(source("kimi", tokens=metric({"daily_models": [daily_row()]}))))
        lines = text.split("\r\n")
        self.assertEqual(lines[0], ",".join(CSV_COLUMNS))
        self.assertEqual(lines[-1], "")
        self.assertNotIn("\n", text.replace("\r\n", ""))

    def test_escaping_comma_quote_newline(self):
        nasty = 'gpt,"x"\nline'
        row = daily_row(model=nasty, app="a,b")
        text = export_csv(snapshot(source("kimi", tokens=metric({"daily_models": [row]}))))
        parsed = list(csv.reader(io.StringIO(text)))
        self.assertEqual(parsed[0], list(CSV_COLUMNS))
        self.assertEqual(parsed[1][CSV_COLUMNS.index("model")], nasty)
        self.assertEqual(parsed[1][CSV_COLUMNS.index("app")], "a,b")
        self.assertIn('"gpt,""x""\nline"', text)

    def test_null_cells_empty_not_zero(self):
        sparse = {"date": "2026-11-10", "model": "m", "total_tokens": 42}
        text = export_csv(snapshot(source("kimi", tokens=metric({"daily_models": [sparse]}))))
        parsed = list(csv.reader(io.StringIO(text)))
        cells = dict(zip(CSV_COLUMNS, parsed[1]))
        self.assertEqual(cells["requests"], "")
        self.assertEqual(cells["reasoning"], "")
        self.assertEqual(cells["unclassified"], "")
        self.assertEqual(cells["total_tokens"], "42")

    def test_sorted_and_matches_json_rows(self):
        snap = snapshot(source("zled", tokens=metric({"daily_models": [daily_row(date="2026-11-11"),
                                                                          daily_row(date="2026-11-10")]})),
                        source("aled", tokens=metric({"daily_models": [daily_row(date="2026-11-10")]})))
        text = export_csv(snap)
        parsed = list(csv.reader(io.StringIO(text)))[1:]
        keys = [(r[0], r[1], r[2], r[3]) for r in parsed]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(keys, [(r["date"], r["ledger"], r["app"], r["model"])
                                for r in export_payload(snap, NOW)["usage_daily"]])
        for cells, row in zip(parsed, export_payload(snap, NOW)["usage_daily"]):
            expected = ["" if row[name] is None else str(row[name]) for name in CSV_COLUMNS]
            self.assertEqual(cells, expected)

    def test_empty_snapshot_header_only(self):
        self.assertEqual(export_csv({}), ",".join(CSV_COLUMNS) + "\r\n")


if __name__ == "__main__":
    unittest.main()