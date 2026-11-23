"""The sync sections added after the first release of payload schema 1:
accounts, quota history, rewards, images, credits, device name and the
settings that are no longer dead weight. Everything here is additive: an
older device ignores these keys, and this build reads a payload without them.
"""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from agent_meter import collection, sync_quota, sync_store, sync_usage
from agent_meter.collector import SnapshotService
from agent_meter.model import SourceError, source, timestamp
from agent_meter.prices import load_prices
from agent_meter.server import load_or_create_token, make_server
from agent_meter.sync_payload import build_payload, parse_payload

NOW = 1795082400  # 2026-11-19 18:00 Asia/Shanghai
DAY = 86400
LOCAL = "a" * 32
REMOTE = "b" * 32
OTHER = "c" * 32
BASE_KEYS = {"schema", "device", "generated_at", "usage", "quota", "cards", "settings"}


def day(offset=0):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    return (datetime.fromtimestamp(NOW, ZoneInfo("Asia/Shanghai")) + timedelta(days=offset)).date().isoformat()


def metric(value, status="available"):
    return {"status": status, "value": value, "reason": None}


QUOTA = [{"bucket": "primary", "window": "primary", "used_percent": 40.0, "remaining_percent": 60.0,
          "window_minutes": 300, "resets_at": timestamp(NOW + 3600)}]
CARDS = {"available_count": 3, "details_state": "returned", "next_known_expiry": timestamp(NOW + DAY),
         "cards": [{"status": "available", "expires_at": timestamp(NOW + DAY), "reset_type": "week"},
                   {"status": "redeemed", "expires_at": timestamp(NOW + 2 * DAY)}]}
WALLETS = [{"bucket": "credits", "balance": "123.45", "total": "500", "unit": "zcode_credits",
            "account_label": "工作账号", "note": "/Users/someone/private"},
           {"unlimited": True},
           {"balance": 50, "unit": "minimax_design_credits",
            "buckets": [{"type": "vip", "balance": "20", "expires_at": timestamp(NOW + 3 * DAY)},
                        {"type": "gift", "balance": 30}]}]


def account_source(sid="zcode", account="acct-zcode", observed=NOW, status="available", **metrics):
    src = source(sid, "account", observed, status)
    if account:
        src["account_key"] = account
    src["subscription"] = {"plan": "GLM Coding Pro", "ends_on": "2026-12-01", "auto_renew": True}
    for name, value in metrics.items():
        src["metrics"][name] = metric(value)
    return src


def full_source(**extra):
    return account_source(credits=WALLETS, reset_cards=CARDS, quota=QUOTA,
                          renewal_time={"date": "2026-12-01", "origin": "provider"},
                          renewal_amount={"amount": 20.0, "currency": "CNY", "confirmed_by_provider": False},
                          credit_refresh_time={"date": "2026-12-05", "origin": "provider"}, **extra)


EXPECTED_ACCOUNT = {
    "account": "acct-zcode", "provider": "zcode", "status": "available", "observed_at": float(NOW),
    "plan": "GLM Coding Pro", "ends_on": "2026-12-01", "auto_renew": True, "renewal_date": "2026-12-01",
    "renewal_amount": 20.0, "renewal_currency": "CNY", "credit_refresh_date": "2026-12-05",
    "credits": [{"bucket": "credits", "unit": "zcode_credits", "balance": 123.45, "total": 500.0},
                {"unlimited": True},
                {"unit": "minimax_design_credits", "balance": 50.0,
                 "buckets": [{"balance": 20.0, "type": "vip", "expires_at": float(NOW + 3 * DAY)},
                             {"balance": 30.0, "type": "gift"}]}],
    "reset_cards": {"count": 3, "expiries": [float(NOW + DAY)], "details": "returned"},
}

LEDGER = {"schema": 1, "accounts": {
    "trae_cn": {"provider": "trae_cn", "checked_at": NOW, "days": {
        "2026-09-01": {"status": {"signed_in": True}, "claims": []},            # outside the 35-day window
        day(-2): {"status": {"signed_in": True}, "claims": []},
        day(-1): {"status": {"signed_in": False}, "claims": [
            {"item": "daily_checkin", "title": "每日签到", "at": NOW - DAY, "result": "ok", "credits": 300}]},
        day(0): {"status": {"signed_in": False}, "claims": [
            {"item": "daily_checkin", "title": "每日签到", "at": NOW, "result": "error", "reason": "x"}]}}},
    "workbuddy": {"provider": "workbuddy", "days": {}},
    "workbuddy#2": {"provider": "workbuddy", "checked_at": NOW, "days": {day(-1): {"status": {}, "claims": [
        {"item": "task:skill_1", "title": "任务 skill_1", "at": NOW, "result": "ok", "credits": 100, "badge": "尝鲜达人"}]}}},
}}


def usage(date, model="glm-5.3", tokens=10, app="codex", device=REMOTE):
    return {"date": date, "app": app, "model": model, "device": device,
            "requests": 2, "fresh_input": 1, "output": 2, "reasoning": 3,
            "cache_read": 4, "cache_write": 0, "total_tokens": tokens}


def quota_row(day_str, used, observed, account="acct-1", device=None, peak=None):
    row = {"account": account, "bucket": "primary", "window": "primary", "day": day_str,
           "observed_at": observed, "used_percent": used, "remaining_percent": 100 - used,
           "window_minutes": 300, "resets_at": None, "peak_used_percent": used if peak is None else peak}
    if device:
        row["device"] = device
    return row


def sync_store_entries(home):
    """The quota journal's own entries, observations included (test helper)."""
    days = json.loads((Path(home) / sync_quota.JOURNAL_NAME).read_text())["days"]
    return [entry for entries in days.values() for entry in entries.values()]


class AccountSectionTests(unittest.TestCase):
    def test_account_facts_travel_and_nothing_else(self):
        payload = build_payload({"sources": [full_source()]}, LOCAL, now=NOW)
        self.assertEqual(payload["accounts"], [EXPECTED_ACCOUNT])
        blob = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("工作账号", blob)
        self.assertNotIn("/Users", blob)
        self.assertNotIn("reset_type", blob)          # only what a card shows
        self.assertNotIn("confirmed_by_provider", blob)
        self.assertNotIn("origin", blob)

    def test_a_source_without_account_facts_is_left_out(self):
        ledger = source("opencode", "local_session_history", NOW)
        ledger["account_key"] = "abc123"
        payload = build_payload({"sources": [ledger]}, LOCAL, now=NOW)
        self.assertNotIn("accounts", payload)
        self.assertNotIn("abc123", json.dumps(payload))

    def test_two_slots_of_one_account_fold_field_by_field(self):
        older = account_source("qoder", observed=NOW - 60, reset_cards=CARDS)
        newer = account_source("qoder#2", observed=NOW, credits=WALLETS[:1])
        accounts = build_payload({"sources": [newer, older]}, LOCAL, now=NOW)["accounts"]
        self.assertEqual(len(accounts), 1)
        self.assertEqual((accounts[0]["observed_at"], accounts[0]["provider"]), (float(NOW), "qoder"))
        self.assertEqual(accounts[0]["reset_cards"]["count"], 3)      # seen by the older slot, kept
        self.assertEqual(accounts[0]["credits"], [{"bucket": "credits", "unit": "zcode_credits",
                                                   "balance": 123.45, "total": 500.0}])

    def test_the_slot_index_never_travels(self):
        payload = build_payload({"sources": [account_source("qoder#3", account=None, credits=WALLETS[:1])]},
                                LOCAL, now=NOW)
        self.assertEqual((payload["accounts"][0]["account"], payload["accounts"][0]["provider"]), ("qoder", "qoder"))

    def test_a_source_that_failed_this_time_is_not_carried(self):
        payload = build_payload({"sources": [full_source(status="error")]}, LOCAL, now=NOW)
        self.assertNotIn("accounts", payload)

    def test_an_overdrawn_balance_and_a_card_inventory_alone_both_travel(self):
        overdrawn = build_payload({"sources": [account_source(credits=[{"balance": "-2.5", "unit": "CNY"}])]},
                                  LOCAL, now=NOW)["accounts"][0]["credits"]
        self.assertEqual(overdrawn, [{"unit": "CNY", "balance": -2.5}])
        only_cards = account_source(credits=[{"balance": "x", "total": None}], reset_cards={"available_count": 0})
        row = build_payload({"sources": [only_cards]}, LOCAL, now=NOW)["accounts"][0]
        self.assertEqual((row["reset_cards"]["count"], row["reset_cards"]["expiries"]), (0, []))
        self.assertNotIn("credits", row)


class DayAndRewardSectionTests(unittest.TestCase):
    def test_image_counts_and_their_cost_travel_per_day(self):
        images = {"currency": "USD", "daily_buckets": [
            {"date": day(0), "images": 4, "estimated_cost": "0.4800"},
            {"date": day(-1), "images": 0, "estimated_cost": "0"},
            {"date": "bad", "images": 2}, {"date": day(-3), "images": 1}]}
        src = source("codex", "account", NOW)
        src["metrics"]["image_generation"] = metric(images, status="partial")
        payload = build_payload({"sources": [src]}, LOCAL, now=NOW)
        self.assertEqual(payload["images"], [{"date": day(-3), "app": "codex", "images": 1},
                                             {"date": day(0), "app": "codex", "images": 4,
                                              "estimated_cost": 0.48, "currency": "USD"}])

    def test_local_credit_spend_travels_but_wallet_rows_do_not_double(self):
        src = source("qoder", "account", NOW)
        src["metrics"]["credits"] = metric({"rows": WALLETS[:1], "usage": {"daily_buckets": [
            {"date": day(0), "requests": 5, "credits": "120.5"}, {"date": day(-1), "requests": 0, "credits": "0"}]}})
        payload = build_payload({"sources": [src]}, LOCAL, now=NOW)
        self.assertEqual(payload["credits"], [{"date": day(0), "app": "qoder", "unit": "qoder_credits",
                                               "credits": 120.5, "requests": 5}])
        # An app without a credit ledger carries no spend rows, whatever its metric holds.
        other = source("kimi", "account", NOW)
        other["metrics"]["credits"] = src["metrics"]["credits"]
        self.assertNotIn("credits", build_payload({"sources": [other]}, LOCAL, now=NOW))

    def test_reward_days_name_a_provider_never_an_account_slot(self):
        rows = build_payload({}, LOCAL, now=NOW, rewards_ledger=LEDGER)["rewards"]
        self.assertEqual([(r["provider"], r["day"], r["signed_in"], r["claimed_credits"], r["single"]) for r in rows], [
            ("trae_cn", day(-2), True, 0, True),
            ("trae_cn", day(-1), True, 300.0, True),
            ("workbuddy", day(-1), False, 100.0, False)])
        self.assertEqual(rows[1]["claims"], [{"item": "daily_checkin", "title": "每日签到"}])
        self.assertEqual(rows[2]["claims"], [{"item": "task:skill_1", "title": "任务 skill_1", "badge": "尝鲜达人"}])
        self.assertEqual(rows[0]["observed_at"], float(NOW))
        self.assertNotIn("workbuddy#2", json.dumps(rows, ensure_ascii=False))


class HeaderAndShapeTests(unittest.TestCase):
    def test_the_device_introduces_itself(self):
        payload = build_payload({}, LOCAL, now=NOW, device_name="  Gary 的\nMacBook\tPro  ", app_version="0.13.0")
        self.assertEqual((payload["device_name"], payload["app_version"]), ("Gary 的 MacBook Pro", "0.13.0"))
        long_name = build_payload({}, LOCAL, now=NOW, device_name="名" * 80, app_version=7)
        self.assertEqual((len(long_name["device_name"]), "app_version" in long_name), (60, False))

    def test_sections_are_left_out_while_empty(self):
        payload = build_payload({"sources": []}, LOCAL, now=NOW, quota_history=[], rewards_ledger={"accounts": {}})
        self.assertEqual(set(payload), BASE_KEYS)


class ParseNewSectionTests(unittest.TestCase):
    def test_a_payload_from_an_older_build_reads_with_empty_sections(self):
        old = {"schema": 1, "device": REMOTE, "generated_at": NOW, "usage": [], "quota": [], "cards": {}}
        record = parse_payload(old)
        for key in ("quota_history", "accounts", "rewards", "images", "credits"):
            self.assertEqual(record[key], [])
        self.assertEqual((record["settings"], record["generated_at"]), ({}, float(NOW)))
        self.assertNotIn("name", record)

    def test_every_section_survives_the_round_trip(self):
        history = [dict(quota_row(day(0), 55.0, NOW, peak=70.0), observations=3)]
        media = source("codex", "account", NOW)
        media["metrics"]["image_generation"] = metric({"currency": "CNY", "daily_buckets": [
            {"date": day(-1), "images": 2, "estimated_cost": "3.5"}]})
        qoder = source("qoder", "account", NOW)
        qoder["metrics"]["credits"] = metric({"rows": [], "usage": {"daily_buckets": [
            {"date": day(-1), "requests": 1, "credits": "12"}]}})
        payload = build_payload({"sources": [full_source(), media, qoder]}, LOCAL,
                                {"theme": "aurora", "budget": {"daily_cny": 30}, "menu_bar_mode": "flip"},
                                NOW, device_name="Studio", app_version="0.13.0",
                                quota_history=history, rewards_ledger=LEDGER)
        self.assertEqual(set(payload["images"][0]) & {"currency", "estimated_cost"}, {"currency", "estimated_cost"})
        record = parse_payload(json.loads(json.dumps(payload, ensure_ascii=False)))
        for key in ("quota_history", "accounts", "rewards", "images", "credits", "settings", "cards"):
            self.assertEqual(record[key], payload[key], key)
        self.assertEqual((record["name"], record["app_version"], record["generated_at"]),
                         ("Studio", "0.13.0", float(NOW)))

    def test_a_bad_entry_in_a_new_section_refuses_the_whole_payload(self):
        good = build_payload({"sources": [full_source()]}, LOCAL, now=NOW, rewards_ledger=LEDGER,
                             quota_history=[quota_row(day(0), 55.0, NOW)])

        def broken(change):
            payload = json.loads(json.dumps(good))
            change(payload)
            return payload

        cases = [broken(lambda p: p["accounts"][0].update(reset_cards={"count": "3"})),
                 # A balance row that is not in its normal form (a string
                 # amount, or a field the payload never carries).
                 broken(lambda p: p["accounts"][0]["credits"][0].update(balance="123.45")),
                 broken(lambda p: p["accounts"][0]["credits"][0].update(note="left in")),
                 broken(lambda p: p["accounts"][0].update(renewal_date="2026-13-01")),
                 broken(lambda p: p["accounts"][0].update(ends_on="2026-02-30")),
                 broken(lambda p: p["accounts"].append("not an account")),
                 broken(lambda p: p["rewards"][0].pop("single")),
                 broken(lambda p: p["rewards"][0].update(claims=[{"item": ""}])),
                 broken(lambda p: p["quota_history"][0].update(day="yesterday")),
                 broken(lambda p: p.update(images=[{"date": day(0), "app": "codex"}])),
                 broken(lambda p: p.update(credits=[{"date": day(0), "app": "codex", "unit": "qoder_credits",
                                                     "credits": 0}])),
                 broken(lambda p: p.update(accounts=[{}] * 61))]
        for payload in cases:
            with self.assertRaises(SourceError):
                parse_payload(payload)

    def test_a_history_row_without_a_peak_falls_back_to_its_last_value(self):
        record = parse_payload({"schema": 1, "device": REMOTE, "usage": [],
                                "quota_history": [quota_row(day(-1), 42.0, NOW - DAY)]})
        row = record["quota_history"][0]
        self.assertEqual((row["peak_used_percent"], row["observations"]), (42.0, 0))

    def test_settings_carry_their_change_stamps(self):
        settings = {"theme": "aurora", "low_quota_threshold": 20}
        payload = build_payload({}, LOCAL, settings, NOW,
                                settings_times={"theme": 1795000000.5, "low_quota_threshold": -1, "budget": 9})
        self.assertEqual(payload["settings_times"], {"theme": 1795000000.5})
        self.assertEqual(parse_payload(payload)["settings_times"], {"theme": 1795000000.5})
        # An older build sends settings without stamps: nothing to order them by.
        old = {"schema": 1, "device": REMOTE, "usage": [], "settings": settings}
        self.assertEqual(parse_payload(old)["settings_times"], {})
        self.assertEqual(parse_payload(old)["settings"], settings)
        self.assertNotIn("settings_times", build_payload({}, LOCAL, settings, NOW))


class QuotaJournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def path(self):
        return Path(self.home) / sync_quota.JOURNAL_NAME

    def test_nothing_is_kept_before_the_device_pairs(self):
        self.assertEqual(sync_quota.record(self.home, [quota_row(day(), 10.0, NOW)], NOW), [])
        self.assertFalse(self.path().exists())

    def test_the_first_payload_opens_the_journal(self):
        series = sync_quota.record(self.home, [quota_row(day(), 10.0, NOW)], NOW, create=True)
        self.assertEqual([(r["used_percent"], r["peak_used_percent"]) for r in series], [(10.0, 10.0)])
        self.assertEqual(self.path().stat().st_mode & 0o777, 0o600)
        self.assertNotIn("observations", series[0])

    def test_the_last_value_replaces_and_the_peak_only_rises(self):
        sync_quota.record(self.home, [quota_row(day(), 10.0, NOW)], NOW, create=True)
        sync_quota.record(self.home, [quota_row(day(), 80.0, NOW + 60)], NOW + 60)
        # A later observation that is lower is still the latest value.
        series = sync_quota.record(self.home, [quota_row(day(), 30.0, NOW + 120)], NOW + 120)
        self.assertEqual([(r["used_percent"], r["peak_used_percent"], r["observed_at"]) for r in series],
                         [(30.0, 80.0, float(NOW + 120))])
        # An observation that is older than the stored one moves nothing.
        series = sync_quota.record(self.home, [quota_row(day(), 5.0, NOW + 30)], NOW + 30)
        self.assertEqual((series[0]["used_percent"], series[0]["peak_used_percent"]), (30.0, 80.0))
        self.assertEqual([entry["observations"] for entry in sync_store_entries(self.home)], [3])

    def test_days_are_kept_for_35_days_and_then_dropped(self):
        kept = {day(-35): {"old": dict(quota_row(day(-35), 1.0, NOW - 35 * DAY), observations=1)},
                day(-34): {"old": dict(quota_row(day(-34), 5.0, NOW - 34 * DAY), observations=1)},
                day(-2): {"old": dict(quota_row(day(-2), 6.0, NOW - 2 * DAY), observations=1)}}
        self.path().write_text(json.dumps({"schema": sync_quota.JOURNAL_SCHEMA, "days": kept}))
        series = sync_quota.record(self.home, [quota_row(day(), 7.0, NOW)], NOW)
        self.assertEqual([(r["day"], r["used_percent"]) for r in series],
                         [(day(-34), 5.0), (day(-2), 6.0), (day(), 7.0)])
        self.assertEqual(sorted(json.loads(self.path().read_text())["days"]), [day(-34), day(-2), day()])

    def test_a_damaged_journal_reads_as_empty_and_clear_removes_it(self):
        self.path().write_text("{not json")
        self.assertEqual(sync_quota.series(self.home), [])
        sync_quota.record(self.home, [quota_row(day(), 1.0, NOW)], NOW, create=True)
        sync_quota.clear(self.home)
        self.assertFalse(self.path().exists())


class JournalHookTests(unittest.TestCase):
    """The collection hook fills the journal only once the device has paired."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def service(self):
        snapshot = {"schema_version": 6, "collected_at": timestamp(NOW), "sources": [account_source(quota=QUOTA)],
                    "coverage": [], "coverage_summary": {}}
        return SnapshotService({"runtime_dir": self.tmp.name}, lambda config, now: snapshot, lambda: NOW)

    def test_an_unpaired_device_writes_no_journal(self):
        self.service().get()
        self.assertFalse((Path(self.tmp.name) / sync_quota.JOURNAL_NAME).exists())

    def test_a_paired_device_keeps_its_history_between_syncs(self):
        service = self.service()
        sync_quota.record(self.tmp.name, [], NOW, create=True)
        service.get()
        first = sync_quota.series(self.tmp.name)
        self.assertEqual(len(first), 1)
        self.assertEqual((first[0]["used_percent"], first[0]["peak_used_percent"]), (40.0, 40.0))
        # A second collection of the same window counts as another observation.
        service.get(force=True)
        entries = sync_store_entries(self.tmp.name)
        self.assertEqual([entry["observations"] for entry in entries], [2])


class StoreProjectionTests(unittest.TestCase):
    def test_every_section_and_the_name_are_kept_per_device(self):
        with tempfile.TemporaryDirectory() as home:
            record = parse_payload({"schema": 1, "device": REMOTE, "device_name": "Studio", "app_version": "0.13.0",
                                    "usage": [usage(day(-1))], "accounts": [EXPECTED_ACCOUNT],
                                    "rewards": build_payload({}, LOCAL, now=NOW, rewards_ledger=LEDGER)["rewards"],
                                    "quota_history": [quota_row(day(-1), 5.0, NOW)],
                                    "images": [{"date": day(0), "app": "codex", "images": 2}],
                                    "credits": [{"date": day(0), "app": "qoder", "unit": "qoder_credits",
                                                 "credits": 3.0}]})
            record["updated_at"] = NOW
            sync_store.replace_device(home, record)
            store = sync_store.load_store(home)
            bucket = store["devices"][REMOTE]
            self.assertEqual((bucket["name"], bucket["app_version"]), ("Studio", "0.13.0"))
            self.assertEqual([len(bucket[name]) for name in sync_store.SECTIONS], [1, 0, 1, 1, 3, 1, 1])
            summary = sync_store.device_summaries(store)[0]
            self.assertEqual((summary["device"], summary["name"], summary["rows"], summary["days"]), (REMOTE, "Studio", 1, 1))
            self.assertEqual((summary["accounts"], summary["rewards"], summary["images"], summary["quota"]), (1, 3, 2, 0))

    def test_a_bucket_from_an_older_build_reads_with_empty_sections(self):
        with tempfile.TemporaryDirectory() as home:
            path = sync_store.store_path(home)
            path.write_text(json.dumps({"schema": 1, "local_device": LOCAL,
                                        "devices": {REMOTE: {"rows": [usage(day(-1))], "quota": [], "cards": {}}}}))
            store = sync_store.load_store(home)
            self.assertEqual([len(sync_store.section(store["devices"][REMOTE], name)) for name in sync_store.SECTIONS],
                             [1, 0, 0, 0, 0, 0, 0])
            self.assertEqual((sync_store.account_history(store), sync_store.reward_history(store)), ([], []))
            summary = sync_store.device_summaries(store)[0]
            self.assertEqual((summary["device"], summary["name"], summary["rows"]), (REMOTE, "", 1))

    def test_forgetting_one_device_leaves_the_others_and_never_this_one(self):
        with tempfile.TemporaryDirectory() as home:
            for device in (REMOTE, OTHER):
                sync_store.replace_device(home, {"device": device, "rows": [usage(day(-1), device=device)]})
            sync_store.set_local_device(home, LOCAL)
            sync_store.forget_device(home, REMOTE, LOCAL)
            self.assertEqual(list(sync_store.load_store(home)["devices"]), [OTHER])
            with self.assertRaises(ValueError):
                sync_store.forget_device(home, LOCAL, LOCAL)
            self.assertEqual(list(sync_store.load_store(home)["devices"]), [OTHER])

    def test_the_quota_series_keeps_every_day_and_the_highest_peak(self):
        rows = [quota_row(day(-1), 40.0, NOW - DAY, device=REMOTE, peak=50.0),
                quota_row(day(0), 60.0, NOW - 600, device=REMOTE, peak=65.0)]
        store = {"local_device": LOCAL, "devices": {
            REMOTE: {"quota_history": rows},
            OTHER: {"quota_history": [quota_row(day(0), 55.0, NOW - 300, device=OTHER, peak=90.0)]}}}
        series = sync_store.quota_series(store, [quota_row(day(0), 61.0, NOW - 100)])
        self.assertEqual([(r["day"], r["used_percent"], r["peak_used_percent"], r.get("device")) for r in series],
                         [(day(-1), 40.0, 50.0, REMOTE), (day(0), 61.0, 90.0, None)])

    def test_account_reward_and_day_histories_are_tagged_with_their_device(self):
        rows = {"accounts": [dict(EXPECTED_ACCOUNT)], "rewards": [{"provider": "trae_cn", "day": day(-1)}],
                "images": [{"date": day(0), "images": 2}], "credits": [{"date": day(0), "credits": 3.0}]}
        older = dict(EXPECTED_ACCOUNT, observed_at=NOW - 500, plan="旧套餐")
        store = {"local_device": LOCAL, "devices": {REMOTE: rows, OTHER: {"accounts": [older]},
                                                    LOCAL: {"accounts": [dict(EXPECTED_ACCOUNT, plan="本机")]}}}
        accounts = sync_store.account_history(store)
        self.assertEqual([(a["plan"], a["device"]) for a in accounts], [("GLM Coding Pro", REMOTE)])
        self.assertEqual(sync_store.reward_history(store), [{"provider": "trae_cn", "day": day(-1), "device": REMOTE}])
        self.assertEqual(sync_store.day_history(store, "images"), [{"date": day(0), "images": 2, "device": REMOTE}])
        self.assertEqual(sync_store.day_history(store, "credits"), [{"date": day(0), "credits": 3.0, "device": REMOTE}])

    def test_this_device_bucket_is_never_a_remote_one(self):
        store = {"local_device": LOCAL, "devices": {LOCAL: {"accounts": [EXPECTED_ACCOUNT],
                                                              "quota_history": [quota_row(day(0), 1.0, NOW)]}}}
        self.assertEqual(sync_store.account_history(store), [])
        self.assertEqual(sync_store.quota_series(store), [])


class UsageProjectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def store(self, **buckets):
        return {"schema": 1, "local_device": LOCAL, "devices": buckets}

    def test_each_devices_share_of_the_period(self):
        store = self.store(**{REMOTE: {"rows": [usage(day(0), tokens=10), usage(day(-10), tokens=30)]},
                             OTHER: {"rows": [usage(day(0), tokens=20, device=OTHER)]}})
        with tempfile.TemporaryDirectory() as home:
            usage_all = sync_usage.usage_periods(store, home, NOW)
        today = usage_all["periods"]["today"]
        self.assertEqual([(d["device"][-1], d["total_tokens"], d["requests"]) for d in today["by_device"]],
                         [("b", 10, 2), ("c", 20, 2)])
        self.assertTrue(all(d["amount"] and d["amount"] > 0 for d in today["by_device"]))
        # Each device's amount adds up to the period's.
        period = today["cost"]["amount"]
        self.assertAlmostEqual(sum(d["amount"] for d in today["by_device"]), period, places=9)
        self.assertEqual(len(usage_all["periods"]["7d"]["by_device"]), 2)
        self.assertEqual(usage_all["periods"]["7d"]["by_device"][0]["total_tokens"], 10.0)

    def test_images_and_credit_spend_are_summed_per_period(self):
        table = load_prices(self.tmp.name)
        fx = float(table.fx_rate)
        store = self.store(**{REMOTE: {
            "images": [{"date": day(0), "app": "codex", "images": 4, "estimated_cost": 0.48, "currency": "USD"},
                       {"date": day(-3), "app": "codex", "images": 1, "estimated_cost": fx, "currency": "CNY"}],
            "credits": [{"date": day(0), "app": "qoder", "unit": "qoder_credits", "credits": 120.5, "requests": 5},
                        {"date": day(-3), "app": "qoder", "unit": "qoder_credits", "credits": 10, "requests": 1}]}})
        usage_all = sync_usage.usage_periods(store, self.tmp.name, NOW)
        today, week = usage_all["periods"]["today"], usage_all["periods"]["7d"]
        self.assertEqual((today["images"]["count"], week["images"]["count"]), (4, 5))
        self.assertEqual(today["images"]["cost"]["unit"], table.currency)
        # A row priced on the other device in the other currency is brought
        # onto this table's scale (fx CNY to the dollar either way).
        self.assertAlmostEqual(week["images"]["cost"]["amount"], 0.48 + (fx if table.currency == "CNY" else 1.0),
                               places=9)
        self.assertEqual(today["credits"], {"qoder_credits": {"credits": 120.5, "requests": 5}})
        self.assertEqual(week["credits"], {"qoder_credits": {"credits": 130.5, "requests": 6}})

    def test_media_without_usage_rows_still_makes_a_projection(self):
        store = self.store(**{REMOTE: {"images": [{"date": day(0), "app": "codex", "images": 4}]}})
        usage_all = sync_usage.usage_periods(store, self.tmp.name, NOW)
        self.assertEqual(usage_all["periods"]["today"]["totals"]["total_tokens"], 0)
        self.assertEqual(usage_all["periods"]["today"]["images"]["count"], 4)
        self.assertIsNone(sync_usage.usage_periods(self.store(**{REMOTE: {"rows": []}}), "", NOW))


class CollectionMergeTests(unittest.TestCase):
    NOW_ = NOW

    def cards(self, ledger, remote=None):
        built = collection.build(collection.empty_ledger(), [], ledger, None, self.NOW_, remote_rewards=remote)
        return {card: entry["count"] for card, entry in built["cards"].items()}

    def test_a_streak_continues_across_two_devices(self):
        local = {"accounts": {"trae_cn": {"checked_at": NOW, "days": {
            day(-3): {"status": {"signed_in": True}, "claims": []},
            day(-2): {"status": {"signed_in": True}, "claims": []}}}}}
        remote = [{"provider": "trae_cn", "day": day(-1), "signed_in": True, "single": True, "observed_at": NOW}]
        self.assertEqual(self.cards(local, remote).get("ck_daily"), 3)   # two local days + the other device's
        self.assertEqual(self.cards(local).get("ck_daily"), 2)

    def test_a_claim_both_devices_saw_is_one_card(self):
        claim = {"item": "task:skill_1", "title": "任务", "at": NOW, "result": "ok", "credits": 100, "badge": "徽章"}
        local = {"accounts": {"workbuddy": {"days": {day(-1): {"status": {}, "claims": [claim]}}}}}
        remote = [{"provider": "workbuddy", "day": day(-1), "signed_in": False, "single": True,
                   "claims": [{"item": "task:skill_1", "title": "任务", "badge": "徽章"}]},
                  {"provider": "workbuddy", "day": day(-2), "signed_in": False, "single": True,
                   "claims": [{"item": "task:skill_2", "title": "另一任务"}]}]
        cards = self.cards(local, remote)
        self.assertEqual((cards["ck_task"], cards["ck_badge"]), (2, 1))

    def test_several_accounts_here_are_never_mixed_with_remote_days(self):
        local = {"accounts": {"trae_cn": {"days": {day(-3): {"status": {"signed_in": True}, "claims": []}}},
                             "trae_cn#2": {"days": {day(-2): {"status": {"signed_in": True}, "claims": []}}}}}
        remote = [{"provider": "trae_cn", "day": day(-1), "signed_in": True, "single": True}]
        self.assertEqual(self.cards(local, remote).get("ck_daily"), 2)

    def test_a_provider_only_another_device_uses_keeps_its_own_streak(self):
        remote = [{"provider": "trae_cn", "day": day(-1), "signed_in": True, "single": True},
                  {"provider": "trae_cn", "day": day(0), "signed_in": True, "single": True}]
        merged = collection.merged_reward_days({}, remote)
        self.assertEqual(list(merged), ["remote:trae_cn"])
        drops = collection.checkin_drops({}, remote)
        self.assertEqual([d["card"] for d in drops], ["ck_daily", "ck_daily"])
        self.assertEqual({d["source"] for d in drops}, {"trae_cn"})

    def test_rows_that_cannot_be_matched_are_ignored(self):
        remote = [{"provider": "workbuddy", "day": day(-1), "signed_in": True, "single": False},
                  {"provider": "qoder", "day": day(-1), "signed_in": True}]
        self.assertEqual(self.cards({}, remote), {})
        self.assertEqual(collection.merged_reward_days({}, remote), {})


def sample(now=NOW):
    return {"schema_version": 6, "collected_at": timestamp(now), "sources": [account_source(quota=QUOTA)],
            "coverage": [], "coverage_summary": {}}


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.token = load_or_create_token(Path(self.tmp.name) / "api.token")
        self.service = SnapshotService({"runtime_dir": self.tmp.name}, lambda config, now: sample(now), lambda: NOW)
        self.server = make_server(self.service, self.token, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:" + str(self.server.server_address[1])

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.tmp.cleanup()

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Authorization": "Bearer " + self.token}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.url + path, data=data, headers=headers, method=method)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            body = exc.read()
            exc.close()
            return exc.code, json.loads(body)

    def journal(self):
        return Path(self.tmp.name) / sync_quota.JOURNAL_NAME

    def test_the_payload_names_the_device_and_opens_its_quota_history(self):
        status, payload = self.call("POST", "/v1/sync/payload",
                                    {"device": LOCAL, "name": "Studio", "app_version": "0.13.0"})
        self.assertEqual(status, 200)
        self.assertEqual((payload["device_name"], payload["app_version"]), ("Studio", "0.13.0"))
        self.assertEqual(len(payload["accounts"]), 1)
        # The first payload already carries today's observation as history.
        self.assertEqual([(r["day"], r["peak_used_percent"]) for r in payload["quota_history"]], [(day(0), 40.0)])
        self.assertTrue(self.journal().exists())
        status, history = self.call("GET", "/v1/sync/history")
        self.assertEqual(status, 200)
        self.assertEqual(history["quota_series"][0]["used_percent"], 40.0)
        self.assertEqual((history["accounts"], history["rewards"], history["local_device"]), ([], [], LOCAL))

    def test_an_invalid_device_leaves_no_trace(self):
        for body in ({"device": ""}, {"device": "x" * 65}, {"device": 5}):
            status, _ = self.call("POST", "/v1/sync/payload", body)
            self.assertEqual(status, 400)
        self.assertFalse(self.journal().exists())
        status, history = self.call("GET", "/v1/sync/history")
        self.assertEqual(history["local_device"], "")

    def import_remote(self, device=REMOTE, **extra):
        payload = {"schema": 1, "device": device, "usage": [usage(day(-1), device=device)],
                   "device_name": " Laptop ", "accounts": [EXPECTED_ACCOUNT],
                   "rewards": [{"provider": "trae_cn", "day": day(-1), "signed_in": True, "single": True}],
                   "images": [{"date": day(-1), "app": "codex", "images": 2}]}
        payload.update(extra)
        status, body = self.call("PUT", "/v1/sync/import", {"local_device": LOCAL, "payload": payload})
        self.assertEqual((status, body["stored"]), (200, True))

    def test_the_history_lists_devices_accounts_rewards_and_media(self):
        self.call("POST", "/v1/sync/payload", {"device": LOCAL})
        self.import_remote()
        status, history = self.call("GET", "/v1/sync/history")
        self.assertEqual(status, 200)
        device = history["devices"][0]
        self.assertEqual((device["device"], device["name"], device["accounts"], device["rewards"], device["images"]),
                         (REMOTE, "Laptop", 1, 1, 2))
        self.assertEqual(history["accounts"][0]["device"], REMOTE)
        self.assertEqual(history["rewards"][0]["day"], day(-1))
        self.assertEqual(history["images"], [{"date": day(-1), "app": "codex", "images": 2, "device": REMOTE}])
        self.assertEqual(history["usage"]["periods"]["today"]["by_device"], [])

    def test_forgetting_a_device_drops_what_it_sent(self):
        self.import_remote()
        self.import_remote(OTHER)
        self.assertEqual(len(self.call("GET", "/v1/sync/history")[1]["devices"]), 2)
        status, body = self.call("POST", "/v1/sync/forget", {"device": REMOTE})
        self.assertEqual((status, body), (200, {"device": REMOTE, "forgotten": True}))
        history = self.call("GET", "/v1/sync/history")[1]
        self.assertEqual([d["device"] for d in history["devices"]], [OTHER])
        self.assertEqual(len(history["rows"]), 1)
        # Only another device's rows can be forgotten.
        for bad in ({"device": LOCAL}, {"device": ""}, {"device": 5}, {}):
            self.assertEqual(self.call("POST", "/v1/sync/forget", bad)[0], 400)

    def test_resetting_the_space_also_ends_the_quota_history(self):
        self.call("POST", "/v1/sync/payload", {"device": LOCAL})
        self.import_remote()
        self.assertEqual(self.call("POST", "/v1/sync/reset", {})[0], 200)
        history = self.call("GET", "/v1/sync/history")[1]
        self.assertEqual((history["devices"], history["local_device"]), ([], LOCAL))
        self.assertFalse(self.journal().exists())
        self.assertEqual(history["quota_series"], [])

    def test_check_in_cards_count_the_days_other_devices_reported(self):
        self.call("POST", "/v1/sync/payload", {"device": LOCAL})
        self.import_remote()
        status, snapshot = self.call("POST", "/v1/refresh")
        self.assertEqual(status, 200)
        self.assertEqual(snapshot["collection"]["cards"]["ck_daily"]["count"], 1)
        self.assertEqual(snapshot["collection"]["cards"]["ck_daily"]["sources"], ["trae_cn"])

    def test_the_new_routes_need_the_local_token(self):
        for path in ("/v1/sync/forget",):
            request = urllib.request.Request(self.url + path, data=b"{}", method="POST",
                                             headers={"Content-Type": "application/json"})
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=5)
            self.assertEqual(ctx.exception.code, 401)
            ctx.exception.close()


if __name__ == "__main__":
    unittest.main()
