import json
import tempfile
import unittest
from pathlib import Path

from agent_meter import collection
from agent_meter.collection import CollectionService, build, empty_ledger, window_kind

NOW = 1794211200  # 2026-11-09 08:00 Asia/Shanghai
H = 3600
DAY = 86400


def quota_source(sid, rows, status="available", cards=None):
    src = {"id": sid, "scope": "account", "status": status,
           "metrics": {"quota": {"status": "available", "value": rows}}}
    if cards is not None:
        src["metrics"]["reset_cards"] = {"status": "available", "value": cards}
    return src


def row(used, reset, minutes=300, bucket="five_hour"):
    return {"bucket": bucket, "window_minutes": minutes, "used_percent": used, "resets_at": {"epoch_seconds": reset}}


def token_source(sid, days):
    return {"id": sid, "scope": "local_session_history", "status": "available",
            "metrics": {"tokens": {"status": "available", "value": {"daily_buckets": [
                {"date": d, "tokens": t} for d, t in days.items()]}}}}


class WindowTests(unittest.TestCase):
    def test_window_kinds(self):
        self.assertEqual(window_kind({"window_minutes": 300}), "five_hour")
        self.assertEqual(window_kind({"window": {"duration": 1, "unit": "week"}}), "seven_day")
        self.assertEqual(window_kind({"window": {"duration": 5, "unit": "hour"}}), "five_hour")
        self.assertEqual(window_kind({"bucket": "5h"}), "five_hour")
        self.assertEqual(window_kind({"bucket": "week"}), "seven_day")
        self.assertIsNone(window_kind({"bucket": "credits"}))
        self.assertIsNone(window_kind({"window_minutes": 43200}))

    def test_settles_highest_tier_once_per_window(self):
        led = empty_ledger()
        reset = NOW + 2 * H
        for t, used in ((NOW, 40), (NOW + H, 93), (NOW + H + 60, 91)):
            collection.track_windows(led, [quota_source("claude", [row(used, reset + 5)])], t)
        self.assertEqual(led["drops"], [])
        collection.track_windows(led, [quota_source("claude", [row(3, reset + 5 * H)])], reset + 60)
        self.assertEqual([d["card"] for d in led["drops"]], ["q5_90"])
        self.assertEqual(led["drops"][0]["detail"], "峰值 93%")
        self.assertEqual(led["windows"]["claude|five_hour|five_hour"]["peak"], 3)

    def test_full_low_and_stale(self):
        led = empty_ledger()
        collection.track_windows(led, [quota_source("codex", [row(100, NOW + H, 10080, "codex")])], NOW)
        collection.track_windows(led, [quota_source("codex", [row(20, NOW + H, 10080, "codex")], status="stale")], NOW + 2 * H)
        self.assertEqual(led["drops"], [])  # stale data never settles a window
        collection.track_windows(led, [quota_source("codex", [row(0, NOW + 8 * DAY, 10080, "codex")])], NOW + 2 * H)
        self.assertEqual(led["drops"][0]["card"], "q7_full")
        collection.track_windows(led, [quota_source("codex", [row(30, NOW + 15 * DAY, 10080, "codex")])], NOW + 9 * DAY)
        self.assertEqual(len(led["drops"]), 1)  # under 50%: no card

    def test_vanished_window_settles_after_a_day(self):
        led = empty_ledger()
        collection.track_windows(led, [quota_source("kimi", [row(85, NOW + H)])], NOW)
        collection.track_windows(led, [], NOW + 2 * DAY)
        self.assertEqual([d["card"] for d in led["drops"]], ["q5_80"])

    def test_reset_cards_used_or_wasted(self):
        led = empty_ledger()
        cards = lambda *exp: {"available_count": len(exp), "cards": [{"status": "available", "expires_at": {"epoch_seconds": e}} for e in exp]}
        collection.track_reset_cards(led, [quota_source("codex", [], cards=cards(NOW + DAY, NOW + 3 * DAY))], NOW)
        collection.track_reset_cards(led, [quota_source("codex", [], cards=cards(NOW + DAY))], NOW + H)
        self.assertEqual(led["drops"][-1]["card"], "rc_saved")
        collection.track_reset_cards(led, [quota_source("codex", [], cards=cards())], NOW + 2 * DAY)
        self.assertEqual(led["drops"][-1]["card"], "rc_wasted")
        # Count-only inventory falls back to the next known expiry.
        collection.track_reset_cards(led, [quota_source("zc", [], cards={"available_count": 2, "next_known_expiry": NOW + DAY})], NOW)
        collection.track_reset_cards(led, [quota_source("zc", [], cards={"available_count": 1})], NOW + H)
        self.assertEqual(led["drops"][-1]["card"], "rc_saved")


class DerivedTests(unittest.TestCase):
    def test_checkin_streak_cards(self):
        days = {}
        for i in range(8):
            date = collection.day_of(NOW - (7 - i) * DAY)
            days[date] = {"status": {"signed_in": True}, "claims": []}
        days[collection.day_of(NOW)]["claims"] = [{"item": "task:x", "title": "任务", "result": "ok", "at": NOW, "badge": "尝鲜达人"},
                                                 {"item": "task:y", "result": "error", "at": NOW}]
        drops = collection.checkin_drops({"accounts": {"trae_cn": {"days": days, "checked_at": NOW}}})
        cards = [d["card"] for d in drops]
        self.assertEqual(cards.count("ck_daily"), 8)
        self.assertEqual(cards.count("ck_7"), 1)
        self.assertEqual(cards.count("ck_task"), 1)
        self.assertEqual(cards.count("ck_badge"), 1)

    def test_medals_from_history(self):
        days = {"2026-11-01": 2 * collection.YI, "2026-11-02": 6 * collection.YI, "2026-11-03": collection.YI // 2,
                "2026-11-05": 11 * collection.YI}
        sources = [token_source("codex", days), token_source("claude", {"2026-11-02": 1}),
                   token_source("gemini", {"2026-11-02": 5}), token_source("imported_history", {"2026-11-02": 9})]
        medals, stats = collection.medals(sources, None, NOW)
        got = {m["id"]: m for m in medals}
        self.assertTrue(got["day_1"]["earned"])
        self.assertEqual(got["day_1"]["count"], 3)
        self.assertEqual(got["day_5"]["earned_on"], "2026-11-02")
        self.assertEqual(got["day_10"]["earned_on"], "2026-11-05")
        self.assertFalse(got["day_50"]["earned"])
        self.assertEqual(got["life_10"]["earned_on"], "2026-11-05")
        self.assertEqual(got["apps_3"]["earned_on"], "2026-11-02")  # imported history is not an app
        self.assertEqual(got["pr_1"]["count"], 2)  # 11-02 and 11-05 beat earlier days
        self.assertEqual((stats["longest_streak"], stats["current_streak"]), (3, 0))
        self.assertEqual(stats["best_day"]["date"], "2026-11-05")
        self.assertAlmostEqual(got["day_50"]["progress"], 11 / 50)

    def test_free_credits(self):
        qoder = {"id": "qoder", "scope": "account", "status": "available", "metrics": {"credits": {"status": "available", "value": {
            "rows": [], "usage": {"periods": {"all": {"totals": {"credits": "1500.5", "billable_credits": "300.5"}}}}}}}}
        rewards = {"accounts": [{"claimed_credits_total": 100}]}
        self.assertEqual(collection.free_credits([qoder], rewards), 1300)
        got = {m["id"]: m for m in collection.medals([qoder], rewards, NOW)[0]}
        self.assertTrue(got["free_1k"]["earned"])


class SpendingAndImageTests(unittest.TestCase):
    def test_cost_medals_in_cny(self):
        src = {"id": "codex", "scope": "account", "status": "available", "metrics": {"cost": {"status": "available", "value": {
            "basis": "local_price_table", "unit": "USD", "daily": [
                {"date": "2026-10-01", "amount": "20"}, {"date": "2026-10-02", "amount": "100"},
                {"date": "2026-11-01", "amount": "1500"}]}}}}
        other = {"id": "claude", "scope": "account", "status": "available", "metrics": {"cost": {"status": "available", "value": {
            "basis": "platform_web_usage", "unit": "CNY", "daily": [{"date": "2026-10-01", "amount": "99999"}]}}}}
        medals, stats = collection.medals([src, other], None, NOW)
        got = {m["id"]: m for m in medals}
        self.assertAlmostEqual(stats["lifetime_cost_cny"], 1620 * 7.25)
        self.assertEqual(got["cost_day_100"]["earned_on"], "2026-10-01")  # $20 = ¥145
        self.assertEqual(got["cost_day_500"]["count"], 2)
        self.assertEqual(got["cost_day_5k"]["earned_on"], "2026-11-01")
        self.assertEqual(got["cost_month_10k"]["earned_on"], "2026-11-01")
        self.assertEqual(got["cost_life_10k"]["earned_on"], "2026-11-01")
        self.assertEqual(stats["best_cost_month"]["month"], "2026-11")

    def test_daily_cost_from_daily_models(self):
        from decimal import Decimal
        from agent_meter.prices import estimate_daily_cost

        class Table:
            def match(self, model):
                return "m" if model == "known" else None

            def cost_for(self, group, pattern):
                return Decimal(group["fresh_input"] + group["output"]) / 1000

        tokens = {"value": {"daily_models": [
            {"date": "2026-11-01", "model": "known", "fresh_input": 1000, "output": 500},
            {"date": "2026-11-01", "model": "known", "fresh_input": 500, "output": 0},
            {"date": "2026-11-02", "model": "unknown", "fresh_input": 9000, "output": 0},
            {"date": "2026-11-03", "model": "known", "total_tokens": 10}]}}
        self.assertEqual(estimate_daily_cost(tokens, Table()), [{"date": "2026-11-01", "amount": "2.0000"}])

    def test_image_medals(self):
        src = {"id": "codex", "scope": "account", "status": "available", "metrics": {"image_generation": {"status": "available", "value": {
            "daily_buckets": [{"date": "2026-11-0%d" % d, "images": 40 + d * 10} for d in range(1, 8)]}}}}
        medals, stats = collection.medals([src], None, NOW)
        got = {m["id"]: m for m in medals}
        self.assertEqual(got["img_day_50"]["earned_on"], "2026-11-01")
        self.assertEqual(got["img_day_100"]["count"], 2)
        self.assertEqual(got["img_life_100"]["earned_on"], "2026-11-02")
        self.assertEqual(got["img_streak_7"]["earned_on"], "2026-11-07")
        self.assertEqual(stats["lifetime_images"], 7 * 40 + 280)

    def test_creative_credits_count_only_drops(self):
        led = empty_ledger()
        wallet = lambda b: {"id": "dreamina", "scope": "creative_account", "status": "available", "metrics": {
            "credits": {"status": "available", "value": {"balance": str(b), "unit": "dreamina_credits"}}}}
        for t, b in ((NOW, 5000), (NOW + H, 4200), (NOW + 2 * H, 9000), (NOW + DAY, 8700)):
            collection.track_creative(led, [wallet(b)], t)
        self.assertEqual(led["creative"]["dreamina"]["spent"], 1100)
        got = {m["id"]: m for m in collection.medals([], None, NOW + DAY, led["creative"])[0]}
        self.assertEqual(got["creative_1k"]["earned_on"], collection.day_of(NOW + DAY))


class ServiceTests(unittest.TestCase):
    def test_binder_counts_and_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            svc = CollectionService(tmp)
            snap = {"sources": [quota_source("claude", [row(95, NOW + H)])]}
            out = svc.update(snap, None, NOW)
            self.assertEqual(out["cards"]["sp_welcome"]["count"], 1)
            out = svc.update({"sources": [quota_source("claude", [row(1, NOW + 6 * H)])]}, None, NOW + 2 * H)
            self.assertEqual(out["cards"]["q5_90"]["count"], 1)
            self.assertEqual(out["recent"][0]["card"], "q5_90")
            self.assertEqual(out["stats"]["distinct_cards"], 2)
            self.assertEqual(out["stats"]["by_rarity"]["epic"], 1)
            self.assertEqual(out["open_windows"][0]["next_card"], "q5_50")
            path = Path(tmp) / "collection.json"
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            again = CollectionService(tmp).update({"sources": []}, None, NOW + 3 * H)
            self.assertEqual(again["cards"]["sp_welcome"]["count"], 1)  # welcome only once
            self.assertEqual(len(again["catalog"]), len(collection.CARDS))

    def test_corrupt_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "collection.json").write_text("[]")
            self.assertEqual(collection.load_ledger(Path(tmp) / "collection.json"), empty_ledger())

    def test_snapshot_carries_collection(self):
        from agent_meter.collector import SnapshotService
        with tempfile.TemporaryDirectory() as tmp:
            sample = {"schema_version": 5, "collected_at": None, "sources": [token_source("codex", {"2026-11-09": 2 * collection.YI})],
                      "coverage": [], "application_usage": {}, "coverage_summary": {}}
            svc = SnapshotService({"runtime_dir": tmp}, lambda config, now: json.loads(json.dumps(sample)), clock=lambda: NOW)
            data = svc.get()
            self.assertTrue({m["id"]: m for m in data["collection"]["medals"]}["day_1"]["earned"])
            self.assertIn("sp_welcome", data["collection"]["cards"])


if __name__ == "__main__":
    unittest.main()
