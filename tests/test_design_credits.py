"""Hermetic tests for the Design media credit estimator.

Fixtures mirror the shapes verified read-only on this machine (2026-11-12):
the gateway pricing table (image[].imageCosts / video[].videoCosts with
realCost, costPerSecond, costPerBlock, resolutions, durations) and the Hub
project ledger {"schemaVersion": 1, "entries": [{cloudTaskId, mediaType,
assetPath, recordedAt(ms), result{ok,duration}, summary{assetInfo{model_id,
params{resolution,duration},duration}}}]}. No network, no real ledger.
"""
import json
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from agent_meter.design_credits import (collect_design_media_credits, load_ledger,
                                        normalize_pricing, price_task, pricing_query)
from agent_meter.model import SourceError

ZONE = ZoneInfo("Asia/Shanghai")
NOW = int(datetime(2026, 11, 12, 12, 0, tzinfo=ZONE).timestamp())
TODAY_START = int(datetime(2026, 11, 12, 0, 0, tzinfo=ZONE).timestamp())
HOUR = 3600
DAY = 86400
GATEWAY = "http://127.0.0.1:8001"


def pricing_table():
    return {
        "enabled": True,
        "promotionEndUnix": 1794450584,
        "text": [{"modelID": "chat-model", "defaultCost": 1}],
        "music": {"once_price": 30},
        "image": [
            {"modelID": "test-image-flat", "defaultCost": 20},
            {"modelID": "test-image-tier", "defaultCost": 48, "imageCosts": [
                {"rawCost": 0, "realCost": 48, "resolutions": ["1K", "2K"]},
                {"rawCost": 0, "realCost": 80, "resolutions": ["4K"]}]},
            {"modelID": "test-image-quality", "imageCosts": [
                {"rawCost": 0, "realCost": 40, "refCountPrice": 10, "qualities": ["low"], "resolutions": ["2K"]},
                {"rawCost": 0, "realCost": 160, "refCountPrice": 10, "qualities": ["high"], "resolutions": ["2K"]}]},
            {"modelID": "test-image-noprice", "imageCosts": [{"rawCost": 0, "realCost": 0, "resolutions": ["2K"]}]},
        ],
        "video": [
            {"modelID": "test-video-second", "videoCosts": [
                {"costPerSecond": 32, "durations": None, "rawCost": 0, "realCost": 0, "resolutions": ["480p"]},
                {"costPerSecond": 56, "durations": None, "rawCost": 0, "realCost": 0, "resolutions": ["720p"]}]},
            {"modelID": "test-video-flat", "defaultCost": 250, "videoCosts": [
                {"durations": [5], "rawCost": 0, "realCost": 250, "resolutions": ["720P"]},
                {"durations": [10], "rawCost": 0, "realCost": 500, "resolutions": ["720P"]}]},
            {"modelID": "test-video-block", "videoCosts": [
                {"blockSeconds": 60, "costPerBlock": 10, "durations": None, "rawCost": 0, "realCost": 0,
                 "resolutions": None}]},
            {"modelID": "test-video-noprice", "videoCosts": []},
        ],
    }


def entry(cid, media, when, model=None, resolution=None, seconds=None, requested=None,
          ok=True, asset_info=True, summary=True):
    """One ledger entry in the real shape; metadata only where the real ledger has it."""
    name = cid + (".mp4" if media == "video" else ".png")
    out = {"cloudTaskId": cid, "mediaType": media, "assetPath": name, "recordedAt": when,
           "nodeId": "00000000-0000-4000-8000-000000000000",
           "result": {"ok": ok, "path": name, "width": 1280, "height": 720}}
    if seconds is not None:
        out["result"]["duration"] = seconds
    if summary:
        params = {}
        if resolution is not None:
            params["resolution"] = resolution
        if requested is not None:
            params["duration"] = str(requested)
        if model is not None:
            params["model_name"] = model
        meta = {"model_id": model, "model": "display name", "params": params, "duration": seconds,
                "width": 1280, "height": 720, "path": name, "prompt": "redacted", "status": "active"}
        out["summary"] = {"assetId": "asset-" + cid, "cloudTaskId": cid, "mediaType": media,
                          "model_id": model, "params": params, "duration": seconds,
                          "assetInfo": meta} if asset_info else dict(meta, assetId="asset-" + cid)
    return out


def write_ledger(root, entries, project="project-a", schema=1):
    directory = Path(root) / project / ".hilo"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "completed-results.json"
    path.write_text(json.dumps({"schemaVersion": schema, "entries": entries}), encoding="utf-8")
    return path


def normal_entries():
    return [
        entry("img-4k", "image", (NOW - HOUR) * 1000, "test-image-tier", "4K"),
        entry("img-2k", "image", (NOW - 2 * HOUR) * 1000, "test-image-tier", "2K"),
        entry("img-flat", "image", (NOW - 8 * DAY) * 1000, "test-image-flat"),
        entry("vid-480", "video", (NOW - 3 * HOUR) * 1000, "test-video-second", "480p", seconds=5.184),
        entry("vid-720", "video", (NOW - DAY) * 1000, "test-video-second", "720p", seconds=10),
        entry("vid-flat", "video", (NOW - 9 * DAY) * 1000, "test-video-flat", "720P", seconds=5.04, requested=5),
        entry("vid-block", "video", (NOW - 31 * DAY) * 1000, "test-video-block", seconds=61),
    ]


class DesignMediaCreditsTests(unittest.TestCase):
    def collect(self, entries=(), pricing=None, now=NOW, path=None, error=None, gateway=GATEWAY):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) if path == "ROOT" else (
                Path(path) if path is not None else write_ledger(tmp, list(entries)))
            with patch("agent_meter.design_credits.get_json",
                       return_value=pricing_table() if pricing is None else pricing,
                       side_effect=error) as query:
                out = collect_design_media_credits(gateway, target, now, 5, node_binary="/nonexistent/node")
            return out, query

    def value(self, entries=(), **kwargs):
        out, _ = self.collect(entries, **kwargs)
        self.assertIsNotNone(out["value"], out["reason"])
        return out["value"]

    def test_normal_estimate_contract(self):
        out, query = self.collect(normal_entries())
        self.assertEqual(out["status"], "available")
        self.assertIsNone(out["reason"])
        value = out["value"]
        self.assertEqual(value["basis"], "local_price_table")
        self.assertEqual(value["unit"], "minimax_credits")
        self.assertTrue(value["reference_only"])
        self.assertEqual(value["wallet_reconciliation"], "never")
        self.assertEqual(value["dedup_rule"], "cloud_task_id_unique_across_project_ledgers")
        self.assertEqual(value["pricing"]["endpoint"], "/api/v1/billing/pricing")
        self.assertEqual(value["ledger"]["files"], 1)
        self.assertEqual(value["ledger"]["entries_seen"], 7)
        self.assertEqual(query.call_count, 1)
        self.assertEqual(query.call_args.args[0], GATEWAY + "/api/v1/billing/pricing")
        self.assertTrue(query.call_args.kwargs["local"])
        self.assertEqual(query.call_args.kwargs["timeout"], 5)
        periods = value["periods"]
        self.assertEqual(sorted(periods), ["30d", "7d", "all", "today"])
        self.assertEqual(periods["today"]["totals"],
                         {"tasks": 3, "priced_tasks": 3, "unpriced_tasks": 0, "credits": "293.888"})
        self.assertEqual(periods["7d"]["totals"]["credits"], "853.888")
        self.assertEqual(periods["30d"]["totals"]["credits"], "1123.888")
        self.assertEqual(periods["all"]["totals"],
                         {"tasks": 7, "priced_tasks": 7, "unpriced_tasks": 0, "credits": "1143.888"})
        self.assertEqual(periods["all"]["timezone"], "Asia/Shanghai")
        self.assertEqual(periods["all"]["start"], None)
        self.assertEqual(periods["today"]["start"]["epoch_seconds"], TODAY_START)
        self.assertEqual(periods["all"]["end"]["epoch_seconds"], NOW)

    def test_breakdown_sums_equal_totals(self):
        entries = normal_entries() + [
            entry("img-unknown", "image", (NOW - HOUR) * 1000),
            entry("vid-unknown", "video", (NOW - HOUR) * 1000, "absent-model", "480p", seconds=4),
            entry("vid-ambiguous", "video", (NOW - HOUR) * 1000, "test-video-flat", "720P", seconds=7, requested=7),
        ]
        periods = self.value(entries)["periods"]
        for name, period in periods.items():
            totals = period["totals"]
            groups = period["groups"]
            media = period["media_types"]
            self.assertEqual(sum(Decimal(g["credits"]) for g in groups), Decimal(totals["credits"]), name)
            self.assertEqual(sum(Decimal(m["credits"]) for m in media), Decimal(totals["credits"]), name)
            self.assertEqual(sum(g["tasks"] for g in groups), totals["priced_tasks"], name)
            self.assertEqual(sum(m["tasks"] for m in media), totals["tasks"], name)
            self.assertEqual(sum(m["priced_tasks"] for m in media), totals["priced_tasks"], name)
            self.assertEqual(sum(m["unpriced_tasks"] for m in media), totals["unpriced_tasks"], name)
            self.assertEqual(totals["priced_tasks"] + totals["unpriced_tasks"], totals["tasks"], name)
            self.assertEqual(period["unpriced"]["tasks"], totals["unpriced_tasks"], name)
            self.assertEqual(sum(period["unpriced"]["by_reason"].values()), totals["unpriced_tasks"], name)
            self.assertEqual(sum(period["unpriced"]["by_model"].values()), totals["unpriced_tasks"], name)
        all_period = periods["all"]
        self.assertEqual(all_period["totals"]["tasks"], 10)
        self.assertEqual(all_period["totals"]["priced_tasks"], 7)
        self.assertEqual(all_period["totals"]["credits"], "1143.888")
        self.assertEqual(all_period["unpriced"]["by_reason"],
                         {"duration_not_priced": 1, "model_not_in_price_table": 1, "model_unknown": 1})
        self.assertEqual([m["media_type"] for m in all_period["media_types"]], ["image", "video"])
        image = all_period["media_types"][0]
        self.assertEqual((image["tasks"], image["priced_tasks"], image["credits"]), (4, 3, "148"))
        video = all_period["media_types"][1]
        self.assertEqual((video["tasks"], video["priced_tasks"], video["credits"]), (6, 4, "995.888"))

    def test_group_fields_and_ordering(self):
        groups = self.value(normal_entries())["periods"]["all"]["groups"]
        self.assertEqual([(g["media_type"], g["model"], g["resolution"]) for g in groups],
                         [("image", "test-image-flat", None), ("image", "test-image-tier", "2k"),
                          ("image", "test-image-tier", "4k"), ("video", "test-video-block", None),
                          ("video", "test-video-flat", "720p"), ("video", "test-video-second", "480p"),
                          ("video", "test-video-second", "720p")])
        flat = groups[0]
        self.assertEqual((flat["price_rule"], flat["price_unit"], flat["unit_price"], flat["credits"]),
                         ("model_default", "per_image", "20", "20"))
        self.assertIsNone(flat["seconds"])
        block = groups[3]
        self.assertEqual((block["price_unit"], block["unit_price"], block["block_seconds"],
                          block["tasks"], block["credits"], block["seconds"]),
                         ("per_block", "10", "60", 1, "20", "61"))
        second = groups[5]
        self.assertEqual((second["price_rule"], second["price_unit"], second["unit_price"],
                          second["credits"], second["seconds"]),
                         ("price_table_tier", "per_second", "32", "165.888", "5.184"))
        tiered = groups[4]
        self.assertEqual((tiered["price_unit"], tiered["unit_price"], tiered["credits"]),
                         ("per_task", "250", "250"))

    def test_video_billing_rules(self):
        entries = [
            entry("v1", "video", NOW * 1000, "test-video-second", "480p", seconds=5.184),
            entry("v2", "video", NOW * 1000, "test-video-flat", "720P", seconds=5.04, requested=5),
            entry("v3", "video", NOW * 1000, "test-video-flat", "720P", seconds=10.2, requested=10),
            entry("v4", "video", NOW * 1000, "test-video-block", seconds=60),
            entry("v5", "video", NOW * 1000, "test-video-block", seconds=61),
            entry("v6", "video", NOW * 1000, "test-video-second", "480p", requested=6),
        ]
        totals = self.value(entries)["periods"]["all"]["totals"]
        # 165.888 + 250 + 500 + 10 + 20 + 192
        self.assertEqual(totals["credits"], "1137.888")
        self.assertEqual(totals["priced_tasks"], 6)

    def test_video_missing_duration_is_unpriced(self):
        value = self.value([entry("v1", "video", NOW * 1000, "test-video-second", "480p")])
        self.assertEqual(value["periods"]["all"]["totals"]["credits"], "0")
        self.assertEqual(value["periods"]["all"]["unpriced"]["by_reason"], {"duration_unknown": 1})

    def test_image_resolution_tiers_and_default(self):
        entries = [
            entry("i1", "image", NOW * 1000, "test-image-tier", "4K"),
            entry("i2", "image", NOW * 1000, "test-image-tier", "1K"),
            entry("i3", "image", NOW * 1000, "test-image-tier"),
            entry("i4", "image", NOW * 1000, "test-image-flat", "4K"),
            entry("i5", "image", NOW * 1000, "test-image-tier", "8K"),
            entry("i6", "image", NOW * 1000, "test-image-noprice", "2K"),
        ]
        value = self.value(entries)
        period = value["periods"]["all"]
        # 80 + 48 + 48 (published default) + 20 (model without tiers)
        self.assertEqual(period["totals"]["credits"], "196")
        self.assertEqual(period["totals"]["priced_tasks"], 4)
        self.assertEqual(period["unpriced"]["by_reason"],
                         {"model_price_unavailable": 1, "resolution_not_priced": 1})

    def test_ambiguous_quality_tier_is_not_guessed(self):
        out, _ = self.collect([entry("i1", "image", NOW * 1000, "test-image-quality", "2K")])
        self.assertEqual(out["status"], "partial")
        self.assertEqual(out["reason"], "design_media_tasks_unpriced")
        period = out["value"]["periods"]["all"]
        self.assertEqual(period["totals"]["credits"], "0")
        self.assertEqual(period["unpriced"]["by_reason"], {"price_tier_ambiguous": 1})
        self.assertEqual(period["unpriced"]["by_model"], {"test-image-quality": 1})

    def test_unknown_model_is_unpriced_not_zero(self):
        out, _ = self.collect([entry("i1", "image", NOW * 1000),
                               entry("i2", "image", NOW * 1000, "test-image-tier", "2K")])
        self.assertEqual(out["status"], "partial")
        period = out["value"]["periods"]["all"]
        self.assertEqual(period["totals"], {"tasks": 2, "priced_tasks": 1, "unpriced_tasks": 1, "credits": "48"})
        self.assertEqual(period["unpriced"]["by_reason"], {"model_unknown": 1})
        self.assertEqual(period["unpriced"]["by_model"], {"unknown": 1})

    def test_summary_without_asset_info_and_string_payload(self):
        plain = entry("i1", "image", NOW * 1000, "test-image-tier", "2K", asset_info=False)
        encoded = entry("i2", "image", NOW * 1000, "test-image-tier", "4K")
        encoded["summary"] = json.dumps(encoded["summary"])
        encoded["result"] = json.dumps(encoded["result"])
        period = self.value([plain, encoded])["periods"]["all"]
        self.assertEqual(period["totals"]["credits"], "128")
        self.assertEqual(period["totals"]["priced_tasks"], 2)

    def test_period_boundaries(self):
        def at(seconds, cid):
            return entry(cid, "video", seconds * 1000, "test-video-second", "480p", seconds=1)

        entries = [at(TODAY_START, "b1"), at(TODAY_START - 1, "b2"), at(NOW - 7 * DAY, "b3"),
                   at(NOW - 7 * DAY - 1, "b4"), at(NOW - 30 * DAY, "b5"), at(NOW - 30 * DAY - 1, "b6"),
                   at(NOW + 1, "future"), at(NOW, "b7")]
        periods = self.value(entries)["periods"]
        self.assertEqual(periods["today"]["totals"],
                         {"tasks": 2, "priced_tasks": 2, "unpriced_tasks": 0, "credits": "64"})
        self.assertEqual(periods["7d"]["totals"]["tasks"], 4)
        self.assertEqual(periods["7d"]["totals"]["credits"], "128")
        self.assertEqual(periods["30d"]["totals"]["tasks"], 6)
        self.assertEqual(periods["30d"]["totals"]["credits"], "192")
        self.assertEqual(periods["all"]["totals"]["tasks"], 7)
        self.assertEqual(periods["all"]["totals"]["credits"], "224")
        self.assertEqual(periods["7d"]["start"]["epoch_seconds"], NOW - 7 * DAY)
        self.assertEqual(periods["30d"]["start"]["epoch_seconds"], NOW - 30 * DAY)

    def test_dedup_across_project_ledgers(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = entry("shared", "video", NOW * 1000, "test-video-second", "480p", seconds=2)
            write_ledger(tmp, [first], project="a")
            write_ledger(tmp, [dict(first), entry("other", "image", NOW * 1000, "test-image-tier", "2K")],
                         project="b")
            with patch("agent_meter.design_credits.get_json", return_value=pricing_table()):
                out = collect_design_media_credits(GATEWAY, tmp, NOW, 5)
        stats = out["value"]["ledger"]
        self.assertEqual((stats["files"], stats["entries_seen"], stats["duplicate_entries"]), (2, 3, 1))
        self.assertEqual(out["value"]["periods"]["all"]["totals"],
                         {"tasks": 2, "priced_tasks": 2, "unpriced_tasks": 0, "credits": "112"})

    def test_single_file_ledger_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_ledger(tmp, normal_entries())
            with patch("agent_meter.design_credits.get_json", return_value=pricing_table()):
                out = collect_design_media_credits(GATEWAY, path, NOW, 5)
        self.assertEqual(out["status"], "available")
        self.assertEqual(out["value"]["ledger"]["files"], 1)
        self.assertEqual(out["value"]["periods"]["all"]["totals"]["credits"], "1143.888")

    def test_out_of_scope_and_failed_tasks_are_not_priced(self):
        entries = [entry("audio", "audio", NOW * 1000, "test-video-second", "480p", seconds=3),
                   entry("failed", "video", NOW * 1000, "test-video-second", "480p", seconds=3, ok=False),
                   entry("good", "video", NOW * 1000, "test-video-second", "480p", seconds=3)]
        value = self.value(entries)
        stats = value["ledger"]
        self.assertEqual((stats["entries_seen"], stats["out_of_scope_entries"], stats["failed_entries"]), (3, 1, 1))
        self.assertEqual(stats["rejected_entries"], 0)
        self.assertEqual(value["periods"]["all"]["totals"],
                         {"tasks": 1, "priced_tasks": 1, "unpriced_tasks": 0, "credits": "96"})

    def test_corrupt_rows_are_rejected_and_counted(self):
        good = entry("good", "image", NOW * 1000, "test-image-tier", "2K")
        entries = [
            good,
            "not-an-object",
            dict(good, cloudTaskId=""),
            dict(good, cloudTaskId="x" * 200),
            dict(good, mediaType=None),
            dict(good, recordedAt="1789778303279"),
            dict(good, recordedAt=True),
            dict(good, recordedAt=-1),
            dict(good, recordedAt=10 ** 15),
            dict(good, summary="{not json"),
            dict(good, result=17),
            dict(entry("no-meta", "image", NOW * 1000), summary=None, result=None),
        ]
        value = self.value(entries)
        stats = value["ledger"]
        self.assertEqual(stats["entries_seen"], 12)
        self.assertEqual(stats["rejected_entries"], 10)
        self.assertEqual(stats["rejection_reasons"],
                         {"invalid_recorded_at": 4, "invalid_result": 1, "invalid_summary": 1,
                          "missing_media_type": 1, "missing_task_id": 2, "not_an_object": 1})
        self.assertEqual(value["periods"]["all"]["totals"],
                         {"tasks": 2, "priced_tasks": 1, "unpriced_tasks": 1, "credits": "48"})

    def test_all_rows_rejected_is_schema_drift(self):
        out, _ = self.collect([{"cloudTaskId": "a"}, "junk"])
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["reason"], "design_media_ledger_entries_invalid")
        self.assertIsNone(out["value"])

    def test_empty_ledger_is_a_real_zero(self):
        out, _ = self.collect([])
        self.assertEqual(out["status"], "available")
        self.assertEqual(out["value"]["periods"]["all"]["totals"],
                         {"tasks": 0, "priced_tasks": 0, "unpriced_tasks": 0, "credits": "0"})
        self.assertEqual(out["value"]["periods"]["all"]["groups"], [])

    def test_missing_ledger_is_not_connected(self):
        for path in ("absent.json", "ROOT"):
            with tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) if path == "ROOT" else Path(tmp) / path
                with patch("agent_meter.design_credits.get_json", return_value=pricing_table()):
                    out = collect_design_media_credits(GATEWAY, target, NOW, 5)
            self.assertEqual(out["status"], "not_connected", path)
            self.assertEqual(out["reason"], "design_media_ledger_not_found", path)
            self.assertIsNone(out["value"])

    def test_unreadable_ledger_is_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "completed-results.json"
            path.write_text("{\"schemaVersion\": 1, \"entries\": [", encoding="utf-8")
            with patch("agent_meter.design_credits.get_json", return_value=pricing_table()):
                out = collect_design_media_credits(GATEWAY, path, NOW, 5)
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["reason"], "design_media_ledger_read_failed")

    def test_unsupported_ledger_schema_is_error(self):
        for payload in ({"schemaVersion": 2, "entries": []}, {"schemaVersion": True, "entries": []},
                        {"schemaVersion": 1, "entries": {}}, []):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "completed-results.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                with patch("agent_meter.design_credits.get_json", return_value=pricing_table()):
                    out = collect_design_media_credits(GATEWAY, path, NOW, 5)
            self.assertEqual(out["status"], "error")
            self.assertEqual(out["reason"], "design_media_unsupported_ledger_schema")

    def test_pricing_unavailable_is_not_connected(self):
        for payload in ({}, {"enabled": False, "image": [], "video": []},
                        {"enabled": True, "video": pricing_table()["video"]},
                        {"enabled": True, "image": [], "video": pricing_table()["video"]},
                        {"enabled": True, "image": [{"defaultCost": 20}], "video": [{"modelID": "v"}]}):
            out, _ = self.collect(normal_entries(), pricing=payload)
            self.assertEqual(out["status"], "not_connected")
            self.assertEqual(out["reason"], "design_media_pricing_unavailable")
            self.assertIsNone(out["value"])

    def test_gateway_failures_map_to_fixed_codes(self):
        for code, expected in (("connection_failed", "design_media_gateway_unreachable"),
                               ("http_404", "design_media_pricing_unavailable"),
                               ("not_authenticated", "design_media_pricing_unavailable"),
                               ("invalid_json", "design_media_pricing_unavailable"),
                               ("response_too_large", "design_media_pricing_unavailable")):
            out, _ = self.collect(normal_entries(), error=SourceError(code))
            self.assertEqual(out["status"], "not_connected", code)
            self.assertEqual(out["reason"], expected, code)

    def test_endpoint_allowlist(self):
        for gateway in ("https://127.0.0.1:8001", "http://design.example.com", "http://127.0.0.1:8001/api",
                        "http://127.0.0.1:8001/?x=1", "http://user:pass@127.0.0.1:8001",
                        "http://127.0.0.1:8001/#frag", "ftp://127.0.0.1"):
            out, query = self.collect(normal_entries(), gateway=gateway)
            self.assertEqual(out["status"], "not_connected", gateway)
            self.assertEqual(out["reason"], "design_media_invalid_endpoint", gateway)
            query.assert_not_called()
        for gateway in ("http://localhost:8001", "http://[::1]:8001", "http://127.0.0.1:8001/"):
            out, query = self.collect(normal_entries(), gateway=gateway)
            self.assertEqual(out["status"], "available", gateway)
            self.assertTrue(query.call_args.kwargs["local"])

    def test_pricing_query_rejects_foreign_origins(self):
        with patch("agent_meter.design_credits.get_json") as query:
            with self.assertRaises(SourceError) as ctx:
                pricing_query("http://design.example.com", 5)
            self.assertEqual(ctx.exception.code, "design_media_invalid_endpoint")
            query.assert_not_called()
            pricing_query("http://localhost:8001", 5)
            self.assertEqual(query.call_args.args[0], "http://localhost:8001/api/v1/billing/pricing")

    def test_no_wallet_fields_leak_into_the_estimate(self):
        payload = pricing_table()
        payload["wallets"] = [{"total_credit": 999999, "source": 1}]
        value = self.value(normal_entries(), pricing=payload)
        self.assertNotIn("balance", json.dumps(value))
        self.assertNotIn("999999", json.dumps(value))
        self.assertNotIn("redacted", json.dumps(value))
        self.assertEqual(value["periods"]["all"]["totals"]["credits"], "1143.888")

    def test_normalize_pricing_keeps_only_media_models(self):
        table = normalize_pricing(pricing_table())
        self.assertEqual(sorted(table), ["image", "video"])
        self.assertEqual(table["video"]["test-video-second"]["model"], "test-video-second")
        self.assertEqual(table["video"]["test-video-block"]["tiers"][0]["unit"], "per_block")
        self.assertEqual(table["video"]["test-video-flat"]["tiers"][1]["durations"], {Decimal(10)})
        self.assertEqual(table["image"]["test-image-noprice"]["tiers"], [])
        self.assertEqual(table["image"]["test-image-flat"]["default"], Decimal(20))
        self.assertEqual(table["image"]["test-image-flat"]["tiers"], [])

    def test_price_task_never_invents_a_price(self):
        table = normalize_pricing(pricing_table())
        with tempfile.TemporaryDirectory() as tmp:
            tasks, _ = load_ledger(write_ledger(tmp, [
                entry("v1", "video", NOW * 1000, "test-video-second", "1080p", seconds=5)]))
        credits, tier, reason = price_task(tasks[0], table)
        self.assertIsNone(credits)
        self.assertIsNone(tier)
        self.assertEqual(reason, "resolution_not_priced")

    def test_load_ledger_missing_path_raises(self):
        for path in ("/nonexistent/design-media-ledger", None, ""):
            with self.assertRaises(SourceError) as ctx:
                load_ledger(path)
            self.assertEqual(ctx.exception.code, "design_media_ledger_not_found")


if __name__ == "__main__":
    unittest.main()