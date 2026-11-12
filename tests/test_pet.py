import contextlib
import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from agent_meter import pet
from agent_meter.collector import SnapshotService
from agent_meter.model import metric, source, timestamp
from agent_meter.pet import PetMind
from agent_meter.server import make_server

NOW = 1_760_000_000  # 2025-10-09 16:53:20 Beijing
FIXTURES = Path(__file__).parent / "fixtures"


def row(bucket="primary", remaining=80, resets=NOW + 9000, minutes=300, **extra):
    out = {"bucket": bucket, "used_percent": 100 - remaining, "remaining_percent": remaining,
           "resets_at": timestamp(resets)}
    if minutes:
        out["window_minutes"] = minutes
    out.update(extra)
    return out


def account(sid, rows=None, status="available", label=None, **metrics):
    src = source(sid, "account", NOW, status=status)
    if label:
        src["account_label"] = label
    if rows is not None:
        src["metrics"]["quota"] = metric(rows, status=status if status != "available" else None)
    for name, value in metrics.items():
        src["metrics"][name] = metric(value)
    return src


def snapshot(sources, collected=NOW, usage=None):
    return {"schema_version": 5, "collected_at": timestamp(collected), "sources": sources,
            "application_usage": usage or {}}


def session(app="codex", status="running", last=NOW - 10, sid="s1", tokens=1000, **extra):
    out = {"app": app, "session_id": sid, "status": status, "last_event_at": timestamp(last),
           "project_alias": "demo", "granularity": "turn", "tokens": {"total_tokens": tokens},
           "recent_turns": []}
    out.update(extra)
    return out


def activity(rows, generated=NOW):
    return {"schema_version": 1, "generated_at": timestamp(generated), "activities": rows, "sources_meta": {}}


def mind(now=NOW, settled=True, hello=False):
    m = PetMind(clock=lambda: now)
    if settled:
        m.started_at = now - 3600
    m._hello_done = not hello          # the startup wave has its own test; keep the others deterministic
    return m


class FormatTests(unittest.TestCase):
    def test_countdown_matches_swift_wording(self):
        self.assertEqual(pet.fmt_countdown(9060), "2小时31分后")
        self.assertEqual(pet.fmt_countdown(86400 * 6 + 3600 * 8), "6天8小时后")
        self.assertEqual(pet.fmt_countdown(86400 * 2), "2天后")
        self.assertEqual(pet.fmt_countdown(30), "不到1分钟")
        self.assertEqual(pet.fmt_countdown(0), "已过时间")

    def test_bucket_labels_share_the_cards_vocabulary(self):
        self.assertEqual(pet.bucket_label({"bucket": "limit5h"}), "5 小时")
        self.assertEqual(pet.bucket_label({"bucket": "primary", "window_minutes": 10080}), "7 天")
        self.assertEqual(pet.bucket_label({"bucket": "mcp"}), "MCP 调用（月）")
        self.assertEqual(pet.bucket_label({"bucket": "x", "group": "Gemini", "window_minutes": 300}), "Gemini · 5 小时")
        self.assertEqual(pet.bucket_label({}), "额度")

    def test_tone_thresholds(self):
        self.assertEqual([pet.tone_of(v, 20) for v in (None, 0, 3, 5, 5.1, 20, 20.1)],
                         ["unknown", "empty", "critical", "critical", "low", "low", "ok"])
        self.assertEqual(pet.tone_of(8, 10), "low")      # threshold 10 keeps 5% as critical

    def test_clean_strips_controls_and_truncates(self):
        self.assertEqual(pet._clean("a\x00b\x1b[31mc\n"), "ab[31mc")
        self.assertEqual(len(pet._clean("x" * 500)), pet.MAX_TEXT)
        self.assertIsNone(pet._clean("\x01\x02"))
        self.assertIsNone(pet._clean(5))


class MeterTests(unittest.TestCase):
    def test_unknown_is_not_zero_and_mcp_counters_are_excluded(self):
        src = account("zcode", [row("limit5h", 40), {"bucket": "mcp", "remaining_percent": 3},
                                {"bucket": "weird", "used_percent": 10}])
        meters = pet.collect_meters(snapshot([src]))
        self.assertEqual([m["id"] for m in meters], ["zcode:limit5h"])

    def test_stale_accounts_are_flagged_and_labels_keep_accounts_apart(self):
        a = account("qoder", [row("primary", 70)], label="主号")
        b = account("qoder#2", [row("primary", 10)], status="stale", label="小号")
        meters = {m["source"]: m for m in pet.collect_meters(snapshot([a, b]))}
        self.assertFalse(meters["qoder"]["stale"])
        self.assertTrue(meters["qoder#2"]["stale"])
        self.assertEqual(meters["qoder#2"]["name"], "Qoder·小号")
        self.assertEqual(meters["qoder#2"]["base"], "qoder")


class ReminderParityTests(unittest.TestCase):
    """Keys derived by hand from Notifier.swift rules; the Swift suite checks the same list."""

    EXPECTED = sorted([
        "low|codex|primary|1760009000|20",
        "low|codex|secondary|1760259200|5",
        "low|claude|limit5h|1760001000|0",
        "low|zcode|mcp|1761728000|5",
        "card|codex|1760018000|1",
        "card|codex|1760172800|3",
        "credit|minimax_design|1760108000|3",
        "renew|minimax_design|2025-10-11|3",
        "member|dreamina|2025-10-12|7",
        "tiboWindow|1760007200|open",
        "tiboLanded|p-9",
    ])

    def fixture(self):
        return json.loads((FIXTURES / "pet_reminder_parity.json").read_text())

    def test_reminder_keys_match_the_notifier(self):
        data = self.fixture()
        keys = sorted(r["id"] for r in pet.compute_reminders(data["snapshot"], data["threshold"], data["now"]))
        self.assertEqual(keys, self.EXPECTED)

    def test_titles_and_bodies_use_the_notification_wording(self):
        data = self.fixture()
        by_id = {r["id"]: r for r in pet.compute_reminders(data["snapshot"], data["threshold"], data["now"])}
        low = by_id["low|codex|primary|1760009000|20"]
        self.assertEqual(low["title"], "Codex 额度不足")
        self.assertEqual(low["body"], "5 小时 窗口剩余 18%，2小时30分后（10月9日 19:23）重置。")
        self.assertEqual(by_id["low|claude|limit5h|1760001000|0"]["title"], "Claude Code 额度已用完")
        self.assertEqual(by_id["card|codex|1760172800|3"]["body"],
                         "2 张重置卡将于 10月11日 16:53 到期（还剩 2天），当前共 4 张，记得使用。")
        self.assertEqual(by_id["credit|minimax_design|1760108000|3"]["body"],
                         "2,800 媒体积分 将于 10月10日 22:53 失效（还剩 1天6小时）。")
        self.assertEqual(by_id["renew|minimax_design|2025-10-11|3"]["body"],
                         "订阅将于 10月11日 自动续费（2 天后），金额 ¥68。")
        self.assertEqual(by_id["member|dreamina|2025-10-12|7"]["body"],
                         "会员将于 10月12日 到期（3 天后），未开启自动续费。")

    def test_user_threshold_changes_levels_but_five_percent_stays(self):
        data = self.fixture()
        keys = {r["id"] for r in pet.compute_reminders(data["snapshot"], 10, data["now"])}
        self.assertNotIn("low|codex|primary|1760009000|20", keys)     # 18% is above a 10% threshold
        self.assertIn("low|codex|secondary|1760259200|5", keys)
        keys30 = {r["id"] for r in pet.compute_reminders(data["snapshot"], 30, data["now"])}
        self.assertIn("low|codex|primary|1760009000|30", keys30)

    def test_past_and_far_expiries_are_silent(self):
        src = account("codex", reset_cards={"available_count": 2, "cards": [
            {"expires_at": timestamp(NOW - 5)}, {"expires_at": timestamp(NOW + 4 * 86400)}]})
        self.assertEqual(pet.compute_reminders(snapshot([src]), 20, NOW), [])

    def test_null_reset_card_details_keep_the_pet_frame_and_expiry_reminder(self):
        expires = NOW + 3600
        src = account("codex", reset_cards={"available_count": 1, "cards": None,
                                           "next_known_expiry": timestamp(expires)})
        frame = mind().frame(snapshot([src]), activity([]), NOW)
        self.assertIn(f"card|codex|{expires}|1", [row["id"] for row in frame["reminders"]])

    def test_sources_without_account_data_never_alert(self):
        silent = source("qoder", "account", NOW, status="not_connected", reason="web_session_missing")
        history = source("imported_history", "local_imported_history", NOW)
        history["metrics"]["quota"] = metric([row("primary", 1)])
        self.assertEqual(pet.compute_reminders(snapshot([silent, history]), 20, NOW), [])


class ArbitrationTests(unittest.TestCase):
    def frame(self, sources=None, rows=None, events=(), now=NOW, **prefs):
        m = mind(now)
        if prefs:
            m.set_preferences(prefs)
        for event in events:
            m.add_event(event, now=now)
        snap = snapshot(sources) if sources is not None else None
        return m.frame(snap, activity(rows or []) if rows is not None else None, now)

    def test_idle_with_healthy_quota(self):
        f = self.frame([account("codex", [row("primary", 90)])], rows=[session(status="suspected_ended", last=NOW - 600)])
        self.assertEqual((f["state"], f["mood"]), ("idle", "happy"))
        self.assertEqual(f["energy"]["tone"], "ok")
        self.assertTrue(f["energy"]["known"])

    def test_running_sessions_work_and_three_make_it_busy(self):
        base = [account("codex", [row("primary", 90)])]
        one = self.frame(base, rows=[session()])
        self.assertEqual((one["state"], one["activity"]["running"]), ("working", 1))
        three = self.frame(base, rows=[session(sid=str(i)) for i in range(3)])
        self.assertEqual(three["state"], "busy")
        self.assertGreater(three["intensity"], one["intensity"])

    def test_empty_quota_of_a_used_source_exhausts_the_pet(self):
        f = self.frame([account("codex", [row("primary", 0)])], rows=[session()])
        self.assertEqual((f["state"], f["mood"], f["energy"]["tone"]), ("exhausted", "sad", "empty"))

    def test_critical_quota_is_an_alarm_even_while_working(self):
        f = self.frame([account("codex", [row("primary", 3)])], rows=[session()])
        self.assertEqual(f["state"], "alarm")

    def test_low_quota_while_working_stays_working_but_worried(self):
        f = self.frame([account("codex", [row("primary", 15)])], rows=[session()])
        self.assertEqual((f["state"], f["mood"]), ("working", "worried"))

    def test_low_quota_while_idle_is_tired(self):
        f = self.frame([account("codex", [row("primary", 15)])], rows=[session(status="completed", last=NOW - 900)])
        self.assertEqual((f["state"], f["energy"]["scope"]), ("tired", "auto"))

    def test_an_unused_empty_account_does_not_make_the_pet_faint(self):
        sources = [account("qoder", [row("primary", 0)]), account("codex", [row("primary", 80)])]
        f = self.frame(sources, rows=[session(app="codex", status="suspected_ended", last=NOW - 400)])
        self.assertEqual(f["energy"]["source"], "codex")           # relevance follows recent use
        self.assertEqual(f["state"], "idle")
        nobody = self.frame([account("qoder", [row("primary", 0)])], rows=[])
        self.assertEqual(nobody["energy"]["scope"], "all")
        self.assertFalse(nobody["energy"]["known"] and nobody["state"] in ("exhausted", "alarm", "tired"))
        self.assertNotIn(nobody["state"], ("exhausted", "alarm", "tired"))

    def test_pinned_source_drives_the_state_even_without_activity(self):
        f = self.frame([account("qoder", [row("primary", 0)]), account("codex", [row("primary", 80)])],
                       rows=[], energy_source="qoder")
        self.assertEqual((f["state"], f["energy"]["scope"]), ("exhausted", "pinned"))

    def test_stale_data_is_confusion_not_exhaustion(self):
        f = self.frame([account("codex", [row("primary", 0)], status="stale")], rows=[])
        self.assertEqual(f["state"], "confused")
        self.assertFalse(f["energy"]["known"])
        self.assertTrue(f["energy"]["stale"])
        self.assertIn("codex", f["honesty"]["stale_sources"])

    def test_an_old_snapshot_is_unknown_not_still_true(self):
        sources = [account("codex", [row("primary", 0)])]
        fresh = mind().frame(snapshot(sources, NOW), activity([]), NOW + 60)
        self.assertEqual((fresh["energy"]["tone"], fresh["energy"]["drives_state"]), ("empty", False))   # shown honestly, moves nothing
        self.assertNotIn(fresh["state"], ("exhausted", "alarm", "tired"))
        old = mind().frame(snapshot(sources, NOW), activity([]), NOW + pet.SNAPSHOT_STALE_SECONDS + 60)
        self.assertEqual(old["state"], "confused")
        self.assertTrue(old["energy"]["stale"])
        self.assertFalse(old["energy"]["known"])
        self.assertGreater(old["honesty"]["snapshot_age"], pet.SNAPSHOT_STALE_SECONDS)
        running = mind().frame(snapshot([account("codex", [row("primary", 0)])], NOW),
                               activity([session(last=NOW + 1300)], NOW + 1300), NOW + 1300)
        self.assertNotIn(running["state"], ("exhausted", "alarm"))            # an old 0% must not faint the pet

    def test_accounts_without_percent_windows_are_simply_idle(self):
        credits = account("deepseek_api", credits=[{"balance": "12.5", "unit": "CNY"}])
        f = self.frame([credits], rows=[])
        self.assertNotIn(f["state"], ("confused", "exhausted", "alarm"))
        self.assertFalse(f["energy"]["known"])

    def test_hook_waiting_wins_over_working_and_clears_on_done(self):
        sources = [account("claude", [row("primary", 80)])]
        waiting = {"kind": "agent_waiting", "source": "claude"}
        f = self.frame(sources, rows=[session(app="claude")], events=[waiting])
        self.assertEqual(f["state"], "waiting")
        m = mind()
        m.add_event(waiting, now=NOW)
        m.add_event({"kind": "agent_started", "source": "claude"}, now=NOW + 1)
        after = m.frame(snapshot(sources), activity([]), NOW + 2)
        self.assertEqual(after["state"], "working")               # started clears the wait, hook counts as running

    def test_waiting_event_expires_by_ttl(self):
        m = mind()
        m.add_event({"kind": "agent_waiting", "source": "claude", "ttl": 30}, now=NOW)
        self.assertEqual(m.frame(None, activity([]), NOW + 10)["state"], "waiting")
        self.assertNotEqual(m.frame(None, activity([]), NOW + 31)["state"], "waiting")

    def test_image_generation_is_painting(self):
        rows = [session(app="codex_images", granularity="image_call", generating_calls=1)]
        f = self.frame([account("codex", [row("primary", 80)])], rows=rows)
        self.assertEqual(f["state"], "painting")
        self.assertEqual(f["activity"]["generating_images"], 1)

    def test_card_expiring_within_a_day_raises_an_alert_state(self):
        cards = {"available_count": 1, "cards": [{"expires_at": timestamp(NOW + 5 * 3600)}]}
        f = self.frame([account("codex", [row("primary", 90)], reset_cards=cards)],
                       rows=[session(status="completed", last=NOW - 900)])
        self.assertEqual(f["state"], "alert")
        self.assertTrue(any(r["kind"] == "reset_card" for r in f["reminders"]))

    def test_focus_timer_sets_focus_and_celebrates_when_done(self):
        m = mind()
        m.add_event({"kind": "focus_start", "minutes": 25}, now=NOW)
        sources = [account("codex", [row("primary", 90)])]
        during = m.frame(snapshot(sources), activity([]), NOW + 60)
        self.assertEqual((during["state"], during["focus"]["active"]), ("focus", True))
        after = m.frame(snapshot(sources), activity([]), NOW + 25 * 60 + 1)
        self.assertFalse(after["focus"]["active"])
        self.assertEqual(after["reaction"]["id"], "celebrate")
        m.add_event({"kind": "focus_start", "minutes": 5}, now=NOW + 2000)
        m.add_event({"kind": "focus_stop"}, now=NOW + 2001)
        self.assertFalse(m.frame(None, activity([]), NOW + 2002)["focus"]["active"])

    def test_forecast_excitement_and_unknown_forecast(self):
        forecast = source("reset_forecast", "external_forecast", NOW)
        forecast["metrics"]["reset_forecast"] = metric({"ensemble": {"horizons": {"48h": {"weighted_median": 62.0}}}})
        f = self.frame([account("codex", [row("primary", 90)]), forecast], rows=[session(status="completed", last=NOW - 900)])
        self.assertEqual((f["state"], f["forecast"]["mood"]), ("excited", "excited"))
        calm = source("reset_forecast", "external_forecast", NOW)
        calm["metrics"]["reset_forecast"] = metric({"ensemble": {"horizons": {"48h": {"weighted_median": 12.0}}}})
        g = self.frame([account("codex", [row("primary", 90)]), calm], rows=[session(status="completed", last=NOW - 900)])
        self.assertEqual(g["forecast"]["mood"], "sleepy")
        self.assertNotEqual(g["state"], "excited")

    def test_sleeping_needs_long_idleness_and_a_settled_process(self):
        sources = [account("codex", [row("primary", 90)])]
        old = [session(status="completed", last=NOW - 3600)]
        self.assertEqual(self.frame(sources, rows=old)["state"], "sleeping")
        fresh = PetMind(clock=lambda: NOW)                       # just started
        self.assertNotEqual(fresh.frame(snapshot(sources), activity(old), NOW)["state"], "sleeping")
        recent = [session(status="completed", last=NOW - 120)]
        self.assertNotEqual(self.frame(sources, rows=recent)["state"], "sleeping")

    def test_quiet_hours_put_an_idle_pet_to_sleep_and_mute_soft_reminders(self):
        sources = [account("codex", [row("primary", 15)])]
        # NOW is 16:53 in Beijing; quiet hours are evaluated on the machine clock, so cover every hour.
        f = self.frame(sources, rows=[], quiet_hours="00:00-23:59")
        self.assertEqual(f["state"], "sleeping")
        self.assertFalse([r for r in f["reminders"] if r["tone"] != "danger"])

    def test_offline_flag_wins(self):
        m = mind()
        self.assertEqual(m.frame(None, None, NOW, offline=True)["state"], "offline")

    def test_missing_everything_is_calm(self):
        f = mind().frame(None, None, NOW)
        self.assertEqual(f["state"], "idle")
        self.assertFalse(f["honesty"]["quota_known"])
        self.assertFalse(f["honesty"]["activity_known"])
        self.assertEqual(f["reminders"], [])

    def test_frame_is_json_safe_and_deterministic(self):
        sources = [account("codex", [row("primary", 15), row("secondary", 40, minutes=10080)])]
        a = mind().frame(snapshot(sources), activity([session()]), NOW)
        b = mind().frame(snapshot(sources), activity([session()]), NOW)
        a.pop("state_since"), b.pop("state_since")
        self.assertEqual(json.dumps(a, allow_nan=False, sort_keys=True), json.dumps(b, allow_nan=False, sort_keys=True))
        self.assertEqual(a["schema_version"], 1)
        self.assertIn(a["state"], pet.STATES)
        self.assertIn(a["mood"], pet.MOODS)

    def test_meters_are_listed_tightest_first_never_summed(self):
        sources = [account("codex", [row("primary", 60)]), account("kimi", [row("limit5h", 20)])]
        f = self.frame(sources, rows=[])
        self.assertEqual([m["source"] for m in f["meters"]], ["kimi", "codex"])
        self.assertEqual(len(f["meters"]), 2)

    def test_alerts_preference_silences_reminders(self):
        data = json.loads((FIXTURES / "pet_reminder_parity.json").read_text())
        m = mind(data["now"])
        self.assertTrue(m.frame(data["snapshot"], activity([], data["now"]), data["now"])["reminders"])
        m.set_preferences({"alerts": False})
        self.assertEqual(m.frame(data["snapshot"], activity([], data["now"]), data["now"])["reminders"], [])


class ReactionTests(unittest.TestCase):
    def two_snapshots(self, before, after):
        m = mind()
        m.frame(snapshot(before, NOW), activity([session()], NOW), NOW)
        return m, m.frame(snapshot(after, NOW + 300), activity([session()], NOW + 300), NOW + 300)

    def test_first_observation_only_records_a_baseline(self):
        f = mind().frame(snapshot([account("codex", [row("primary", 100)])]), activity([session()]), NOW)
        self.assertNotEqual((f["reaction"] or {}).get("reason"), "quota_refill")   # at most the startup wave

    def test_refill_of_a_used_source_celebrates_once(self):
        before = [account("codex", [row("primary", 6, resets=NOW + 200)])]
        after = [account("codex", [row("primary", 100, resets=NOW + 5 * 3600 + 200)])]
        m, f = self.two_snapshots(before, after)
        self.assertEqual(f["reaction"]["id"], "celebrate")
        self.assertEqual(f["reaction"]["reason"], "quota_refill")
        again = m.frame(snapshot(after, NOW + 300), activity([session()], NOW + 301), NOW + 301)
        self.assertEqual(again["reaction"]["key"], f["reaction"]["key"])      # idempotent, same key
        later = m.frame(snapshot(after, NOW + 600), activity([session()], NOW + 600), NOW + 600)
        self.assertIsNone(later["reaction"])

    def test_refill_of_an_unused_source_is_not_news(self):
        m = mind()
        m.frame(snapshot([account("qoder", [row("primary", 5)])], NOW), activity([]), NOW)
        f = m.frame(snapshot([account("qoder", [row("primary", 100, resets=NOW + 99999)])], NOW + 300), activity([], NOW + 300), NOW + 300)
        self.assertIsNone(f["reaction"])

    def test_small_changes_do_not_celebrate(self):
        before = [account("codex", [row("primary", 60)])]
        after = [account("codex", [row("primary", 70)])]
        self.assertIsNone(self.two_snapshots(before, after)[1]["reaction"])

    def test_completed_session_celebrates_but_suspected_end_does_not(self):
        m = mind()
        m.frame(None, activity([session(sid="a"), session(sid="b")], NOW), NOW)
        f = m.frame(None, activity([session(sid="a", status="suspected_ended"),
                                    session(sid="b", status="completed")], NOW + 5), NOW + 5)
        self.assertEqual(f["reaction"]["id"], "celebrate")
        self.assertIn("b", f["reaction"]["key"])
        m2 = mind()
        m2.frame(None, activity([session(sid="a")], NOW), NOW)
        quiet = m2.frame(None, activity([session(sid="a", status="suspected_ended")], NOW + 5), NOW + 5)
        self.assertIsNone(quiet["reaction"])                                  # stopped writing != success

    def test_failed_session_startles(self):
        m = mind()
        m.frame(None, activity([session()], NOW), NOW)
        f = m.frame(None, activity([session(status="failed")], NOW + 5), NOW + 5)
        self.assertEqual(f["reaction"]["id"], "startle")

    def test_turn_level_outcome_is_reported_as_a_turn(self):
        m = mind()
        t1 = session(recent_turns=[{"turn": "1", "status": "completed"}])
        t2 = session(recent_turns=[{"turn": "1", "status": "completed"}, {"turn": "2", "status": "completed"}])
        m.frame(None, activity([t1], NOW), NOW)
        f = m.frame(None, activity([t2], NOW + 5), NOW + 5)
        self.assertEqual((f["reaction"]["id"], f["reaction"]["reason"]), ("celebrate", "turn_completed"))

    def test_token_burst_makes_the_pet_eat(self):
        m = mind()
        m.frame(None, activity([session(tokens=100_000)], NOW), NOW)
        f = m.frame(None, activity([session(tokens=150_000)], NOW + 5), NOW + 5)
        self.assertEqual(f["reaction"]["id"], "eating")
        calm = mind()
        calm.frame(None, activity([session(tokens=100_000)], NOW), NOW)
        self.assertIsNone(calm.frame(None, activity([session(tokens=101_000)], NOW + 5), NOW + 5)["reaction"])

    def test_creative_credit_spend_is_painting(self):
        def design(balance):
            src = source("minimax_design", "creative_personal_account", NOW)
            src["metrics"]["credits"] = metric([{"balance": balance, "unit": "minimax_design_media_credits"}])
            return src
        m = mind()
        m.frame(snapshot([design("1000")], NOW), activity([]), NOW)
        f = m.frame(snapshot([design("880")], NOW + 300), activity([], NOW + 300), NOW + 300)
        self.assertEqual((f["reaction"]["id"], f["reaction"]["reason"]), ("painting", "credits_spent"))
        top_up = m.frame(snapshot([design("5000")], NOW + 600), activity([], NOW + 600), NOW + 600)
        self.assertIsNone(top_up["reaction"])

    def test_announced_landing_celebrates_once_per_post(self):
        data = json.loads((FIXTURES / "pet_reminder_parity.json").read_text())
        src = [s for s in data["snapshot"]["sources"] if s["id"] == "reset_forecast"][0]
        value = src["metrics"]["reset_forecast"]["value"]
        value["history_events"][0]["announced_at"] = timestamp(NOW - 3600)
        m = mind()
        f = m.frame(snapshot([src]), activity([]), NOW)
        self.assertTrue(f["reaction"] is not None and f["reaction"]["key"] == "tiboLanded|p-9")

    def test_startup_waves_once_and_only_briefly(self):
        m = mind(hello=True)
        first = m.frame(None, activity([]), NOW)
        self.assertEqual((first["reaction"]["id"], first["reaction"]["reason"]), ("wave", "startup"))
        self.assertEqual(first["mood"], "happy")
        self.assertIsNone(m.frame(None, activity([]), NOW + 30)["reaction"])
        self.assertIsNone(m.frame(None, activity([]), NOW + 31)["reaction"])      # never again

    def test_reactions_tint_the_mood_but_never_hide_distress(self):
        m = mind()
        m.add_event({"kind": "agent_failed", "source": "codex"}, now=NOW)
        self.assertEqual(m.frame(None, activity([]), NOW + 1)["mood"], "surprised")
        distress = mind()
        distress.add_event({"kind": "agent_done", "source": "codex"}, now=NOW)
        f = distress.frame(snapshot([account("codex", [row("primary", 0)])]), activity([session()]), NOW + 1)
        self.assertEqual((f["state"], f["mood"]), ("exhausted", "sad"))

    def test_reactions_expire(self):
        m = mind()
        m.add_event({"kind": "agent_done", "source": "codex"}, now=NOW)
        self.assertEqual(m.frame(None, activity([]), NOW + 1)["reaction"]["id"], "celebrate")
        self.assertIsNone(m.frame(None, activity([]), NOW + 60)["reaction"])


class EventTests(unittest.TestCase):
    def test_validation(self):
        m = mind()
        for bad in ({}, {"kind": "nope"}, {"kind": "agent_done", "extra": 1}, {"kind": "agent_done", "source": "Bad Name"},
                    {"kind": "agent_done", "ttl": 0}, {"kind": "agent_done", "ttl": 99999}, {"kind": "agent_done", "ttl": True},
                    {"kind": "focus_start"}, {"kind": "focus_start", "minutes": 0}, {"kind": "agent_done", "minutes": 5},
                    {"kind": "agent_done", "text": 5}, {"kind": "nudge", "tone": "loud"}, "x", None, 5):
            with self.assertRaises(ValueError, msg=repr(bad)):
                m.add_event(bad, now=NOW)

    def test_text_is_sanitised_and_ring_is_bounded(self):
        m = mind()
        event = m.add_event({"kind": "nudge", "text": "hi\x00 there !" + "x" * 300, "project": "p" * 90}, now=NOW)
        self.assertNotIn("\x00", event["text"])
        self.assertEqual(len(event["text"]), pet.MAX_TEXT)
        self.assertEqual(len(event["project"]), 40)
        for _ in range(80):
            m.add_event({"kind": "nudge", "text": "n"}, now=NOW)
        self.assertLessEqual(len(m.frame(None, activity([]), NOW)["events"]), 10)
        self.assertLessEqual(len(m.events), pet.MAX_EVENTS)

    def test_nudge_becomes_a_reminder_until_it_expires(self):
        m = mind()
        m.add_event({"kind": "nudge", "text": "该提交了", "tone": "warn", "ttl": 20}, now=NOW)
        self.assertIn("该提交了", [r["text"] for r in m.frame(None, activity([]), NOW + 1)["reminders"]])
        self.assertEqual(m.frame(None, activity([]), NOW + 25)["reminders"], [])

    def test_done_event_names_the_app_and_project(self):
        m = mind()
        m.add_event({"kind": "agent_done", "source": "claude", "project": "NEW-agent 统计"}, now=NOW)
        reminder = m.frame(None, activity([]), NOW + 1)["reminders"][0]
        self.assertEqual(reminder["text"], "Claude Code 完成了「NEW-agent 统计」")
        self.assertEqual(reminder["tone"], "good")

    def test_failed_event_is_a_danger_reminder_and_a_startle(self):
        m = mind()
        m.add_event({"kind": "agent_failed", "source": "codex"}, now=NOW)
        f = m.frame(None, activity([]), NOW + 1)
        self.assertEqual(f["reaction"]["id"], "startle")
        self.assertEqual(f["reminders"][0]["tone"], "danger")

    def test_price_sync_waves_with_a_cooldown(self):
        m = mind()
        m.add_event({"kind": "prices_synced"}, now=NOW)
        m.add_event({"kind": "prices_synced"}, now=NOW + 5)
        self.assertEqual(len([r for r in m.reactions if r["reason"] == "prices_synced"]), 1)

    def test_break_reminder_after_a_long_busy_stretch(self):
        m = mind()
        m.set_preferences({"break_after_minutes": 30})
        m.frame(None, activity([session()], NOW), NOW)
        later = NOW + 31 * 60
        f = m.frame(None, activity([session(last=later - 5)], later), later)
        self.assertTrue([r for r in f["reminders"] if r["kind"] == "break"])
        off = mind()
        off.set_preferences({"break_after_minutes": 0})
        off.frame(None, activity([session()], NOW), NOW)
        self.assertFalse([r for r in off.frame(None, activity([session(last=later - 5)], later), later)["reminders"]
                          if r["kind"] == "break"])


class DailyReportTests(unittest.TestCase):
    """A2: one bubble per local day about yesterday, from the snapshot's own daily rollups."""

    YESTERDAY = "2025-10-08"          # NOW is 2025-10-09 16:53 Beijing
    TODAY = "2025-10-09"

    def ledger(self, sid, rows, cost=None, status="available", scope="local_session_history"):
        src = source(sid, scope, NOW, status=status)
        src["metrics"]["tokens"] = metric({"periods": {}, "daily_models": rows},
                                          status=status if status != "available" else None)
        if cost is not None:
            src["metrics"]["cost"] = metric(cost)
        return src

    def day_row(self, day, tokens, app=None, model="m"):
        row = {"date": day, "model": model, "total_tokens": tokens, "requests": 1,
               "fresh_input": tokens, "output": 0, "reasoning": 0, "cache_read": 0, "cache_write": 0}
        if app is not None:
            row["app"] = app
        return row

    def test_totals_cost_and_top_app(self):
        sources = [
            self.ledger("claude", [self.day_row(self.YESTERDAY, 300_000), self.day_row(self.TODAY, 900_000)],
                        cost={"unit": "USD", "daily": [{"date": self.YESTERDAY, "amount": "2.0000"}]}),
            self.ledger("codex", [self.day_row(self.YESTERDAY, 100_000)],
                        cost={"unit": "CNY", "daily": [{"date": self.YESTERDAY, "amount": "3.0000"}]}),
        ]
        report = pet.daily_report(snapshot(sources), NOW)
        self.assertEqual(report["date"], self.YESTERDAY)
        self.assertEqual(report["tokens"], 400_000)                    # today's 900k stays out
        self.assertEqual(report["cost_cny"], 17.5)                     # 2 USD * 7.25 + 3 CNY
        self.assertEqual((report["top_app"], report["top_tokens"]), ("claude", 300_000))

    def test_bubble_wording_and_stable_daily_id(self):
        sources = [self.ledger("claude", [self.day_row(self.YESTERDAY, 1_234_567), self.day_row(self.TODAY, 42)],
                               cost={"unit": "CNY", "daily": [{"date": self.YESTERDAY, "amount": "12.3400"}]})]
        m = mind()
        frame = m.frame(snapshot(sources), activity([]), NOW)
        reports = [r for r in frame["reminders"] if r["kind"] == "daily_report"]
        self.assertEqual(len(reports), 1)
        r = reports[0]
        self.assertEqual(r["id"], "daily|" + self.YESTERDAY)
        self.assertEqual(r["text"], "昨日用量报告：共 1,234,567 Token，估算 ¥12.34，Claude Code 最高产")
        self.assertEqual(r["action"], {"kind": "open_panel", "tab": "usage"})
        self.assertEqual(r["tone"], "info")
        again = m.frame(snapshot(sources), activity([]), NOW + 60)
        self.assertEqual([x["id"] for x in again["reminders"] if x["kind"] == "daily_report"], [r["id"]])
        tomorrow = m.frame(snapshot(sources), activity([]), NOW + 86400)
        self.assertEqual([x["id"] for x in tomorrow["reminders"] if x["kind"] == "daily_report"],
                         ["daily|2025-10-09"])

    def test_no_yesterday_data_is_silent(self):
        self.assertIsNone(pet.daily_report(snapshot([self.ledger("claude", [self.day_row(self.TODAY, 5)])]), NOW))
        self.assertIsNone(pet.daily_report(snapshot([self.ledger("claude", [])]), NOW))
        self.assertIsNone(pet.daily_report(None, NOW))
        self.assertIsNone(pet.daily_report(snapshot([]), NOW))
        m = mind()
        frame = m.frame(snapshot([self.ledger("claude", [self.day_row(self.TODAY, 5)])]), activity([]), NOW)
        self.assertFalse([r for r in frame["reminders"] if r["kind"] == "daily_report"])

    def test_unknown_cost_is_omitted_not_zero(self):
        sources = [self.ledger("claude", [self.day_row(self.YESTERDAY, 10)])]
        report = pet.daily_report(snapshot(sources), NOW)
        self.assertIsNone(report["cost_cny"])
        frame = mind().frame(snapshot(sources), activity([]), NOW)
        r = [x for x in frame["reminders"] if x["kind"] == "daily_report"][0]
        self.assertNotIn("¥", r["text"])
        self.assertIn("共 10 Token", r["text"])

    def test_account_splits_and_codexbar_mirrors_are_not_ledgers(self):
        sources = [self.ledger("claude#2", [self.day_row(self.YESTERDAY, 10)]),
                   self.ledger("codexbar:claude", [self.day_row(self.YESTERDAY, 10)])]
        self.assertIsNone(pet.daily_report(snapshot(sources), NOW))

    def test_imported_history_keeps_the_app_of_each_row(self):
        rows = [self.day_row(self.YESTERDAY, 40, app="codex"), self.day_row(self.YESTERDAY, 60, app="claude"),
                self.day_row(self.YESTERDAY, 5, app="mcode")]
        sources = [self.ledger("imported_history", rows, scope="local_imported_history")]
        report = pet.daily_report(snapshot(sources), NOW)
        self.assertEqual(report["tokens"], 105)
        self.assertEqual(report["top_app"], "claude")
        frame = mind().frame(snapshot(sources), activity([]), NOW)
        r = [x for x in frame["reminders"] if x["kind"] == "daily_report"][0]
        self.assertIn("Claude Code 最高产", r["text"])

    def test_stale_ledgers_still_report_history_but_unreadable_ones_do_not(self):
        stale = self.ledger("claude", [self.day_row(self.YESTERDAY, 10)], status="stale")
        self.assertEqual(pet.daily_report(snapshot([stale]), NOW)["tokens"], 10)
        broken = self.ledger("claude", [self.day_row(self.YESTERDAY, 10)], status="error")
        self.assertIsNone(pet.daily_report(snapshot([broken]), NOW))

    def test_alerts_preference_and_quiet_hours_apply(self):
        sources = [self.ledger("claude", [self.day_row(self.YESTERDAY, 10)])]
        m = mind()
        m.set_preferences({"alerts": False})
        self.assertFalse([r for r in m.frame(snapshot(sources), activity([]), NOW)["reminders"]
                          if r["kind"] == "daily_report"])
        quiet = mind()
        quiet.set_preferences({"quiet_hours": "00:00-23:59"})
        self.assertFalse([r for r in quiet.frame(snapshot(sources), activity([]), NOW)["reminders"]
                          if r["kind"] == "daily_report"])

    def test_malformed_rows_are_ignored(self):
        rows = [{"date": self.YESTERDAY, "total_tokens": True}, {"date": self.YESTERDAY, "total_tokens": "9"},
                {"date": self.YESTERDAY}, "junk", self.day_row(self.YESTERDAY, 7)]
        report = pet.daily_report(snapshot([self.ledger("claude", rows)]), NOW)
        self.assertEqual(report["tokens"], 7)


class PreferenceTests(unittest.TestCase):
    def test_valid_values_are_applied(self):
        m = mind()
        saved = m.set_preferences({"low_quota_threshold": 30, "energy_source": "codex", "quiet_hours": "23:00-08:00",
                                   "break_after_minutes": 60, "sleep_after_minutes": 10, "alerts": False})
        self.assertEqual(saved["low_quota_threshold"], 30.0)
        self.assertEqual(saved["energy_source"], "codex")
        self.assertFalse(saved["alerts"])
        self.assertIsNone(m.set_preferences({"quiet_hours": None})["quiet_hours"])

    def test_invalid_values_are_rejected_atomically(self):
        m = mind()
        for bad in ({}, {"unknown": 1}, {"low_quota_threshold": 25}, {"low_quota_threshold": True},
                    {"energy_source": "Bad Id"}, {"quiet_hours": "25:00-08:00"}, {"quiet_hours": "late"},
                    {"break_after_minutes": 10}, {"sleep_after_minutes": 1}, {"alerts": "yes"}, "x", None):
            with self.assertRaises(ValueError, msg=repr(bad)):
                m.set_preferences(bad)
        with self.assertRaises(ValueError):
            m.set_preferences({"alerts": False, "low_quota_threshold": 25})
        self.assertTrue(m.preferences["alerts"])                  # nothing from a rejected batch leaks in

    def test_quiet_hours_wrap_midnight(self):
        evening = 22 * 3600 + 30 * 60
        base = int(__import__("datetime").datetime(2025, 10, 9).timestamp())
        self.assertTrue(PetMind._in_quiet_hours("22:00-07:00", base + evening))
        self.assertTrue(PetMind._in_quiet_hours("22:00-07:00", base + 3 * 3600))
        self.assertFalse(PetMind._in_quiet_hours("22:00-07:00", base + 12 * 3600))
        self.assertFalse(PetMind._in_quiet_hours("09:00-09:00", base + 9 * 3600))
        self.assertFalse(PetMind._in_quiet_hours(None, base))


class HttpTests(unittest.TestCase):
    TOKEN = "t" * 40

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.collections = 0

        def collect(config, now):
            self.collections += 1
            return snapshot([account("codex", [row("primary", 15)])], int(now))

        self.service = SnapshotService({"runtime_dir": self.tmp.name, "cache_ttl_seconds": 120}, collect, lambda: NOW)
        self.service.activity = lambda now=None: activity([session()])     # no scan of real ledgers
        self.server = make_server(self.service, self.TOKEN, 0)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def call(self, method, path, body=None, headers=None, token=True, raw=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        head = {"Authorization": "Bearer " + self.TOKEN} if token else {}
        if data is not None and method in ("POST", "PUT"):
            head["Content-Type"] = "application/json"
        head.update(headers or {})
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), data=data, method=method, headers=head)
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read() or b"null")

    def test_requires_the_local_token(self):
        self.assertEqual(self.call("GET", "/v1/pet", token=False)[0], 401)
        self.assertEqual(self.call("GET", "/v1/pet", headers={"Origin": "http://evil.example"})[0], 403)

    def test_frame_comes_from_cache_and_never_collects(self):
        status, frame = self.call("GET", "/v1/pet")
        self.assertEqual(status, 200)
        self.assertEqual(frame["schema_version"], 1)
        self.assertEqual(frame["state"], "working")            # one running session
        self.assertFalse(frame["honesty"]["quota_known"])      # nothing collected yet: unknown, not zero
        self.assertEqual(self.collections, 0)
        self.assertFalse((Path(self.tmp.name) / "snapshot.json").exists())
        self.service.get()                                      # a real collection happens elsewhere
        status, frame = self.call("GET", "/v1/pet")
        self.assertTrue(frame["honesty"]["quota_known"])
        self.assertEqual(frame["energy"]["tone"], "low")
        self.assertEqual(self.collections, 1)

    def test_query_strings_are_still_rejected(self):
        self.assertEqual(self.call("GET", "/v1/pet?x=1")[0], 400)

    def test_events_round_trip_and_validation(self):
        status, body = self.call("POST", "/v1/pet/events", {"kind": "agent_waiting", "source": "claude"})
        self.assertEqual((status, body["kind"]), (200, "agent_waiting"))
        self.assertEqual(self.call("GET", "/v1/pet")[1]["state"], "waiting")
        self.assertEqual(self.call("POST", "/v1/pet/events", {"kind": "bogus"})[0], 400)
        self.assertEqual(self.call("POST", "/v1/pet/events", raw=b"{not json")[1]["error"], "invalid_json")
        self.assertEqual(self.call("POST", "/v1/pet/events", raw=json.dumps({"kind": "nudge", "text": "x" * 6000}).encode())[0], 400)
        self.assertEqual(self.call("POST", "/v1/pet/events", headers={"Content-Type": "text/plain"}, raw=b"{}")[0], 400)

    def test_preferences_round_trip(self):
        status, saved = self.call("PUT", "/v1/pet/preferences", {"low_quota_threshold": 10})
        self.assertEqual((status, saved["low_quota_threshold"]), (200, 10.0))
        self.assertEqual(self.call("PUT", "/v1/pet/preferences", {"low_quota_threshold": 7})[0], 400)
        self.assertEqual(self.call("PUT", "/v1/pet/preferences", {"surprise": 1})[0], 400)

    def test_existing_post_routes_still_refuse_bodies(self):
        status, body = self.call("POST", "/v1/refresh", {"x": 1})
        self.assertEqual((status, body["error"]), (400, "body_not_allowed"))


class CliTests(unittest.TestCase):
    def run_cli(self, *argv):
        from agent_meter.pet_cli import main
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(list(argv))
        return code, out.getvalue()

    def test_state_from_a_snapshot_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            snap = Path(tmp) / "s.json"
            snap.write_text(json.dumps(snapshot([account("codex", [row("primary", 2)])])))
            act = Path(tmp) / "a.json"
            act.write_text(json.dumps(activity([session()])))
            code, text = self.run_cli("state", "--snapshot", str(snap), "--activity", str(act), "--now", str(NOW), "--brief")
        self.assertEqual(code, 0)
        self.assertIn("alarm（告急）", text)
        self.assertIn("额度 2%", text)

    def test_claude_hooks_are_valid_json_with_safe_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            (runtime / "api.token").write_text("a" * 40 + "\n")
            code, text = self.run_cli("--runtime", tmp, "hooks", "claude")
        self.assertEqual(code, 0)
        data = json.loads("\n".join(line for line in text.splitlines() if not line.startswith("//")))
        self.assertEqual(set(data["hooks"]), {"UserPromptSubmit", "Stop", "Notification"})
        for groups in data["hooks"].values():
            command = groups[0]["hooks"][0]["command"]
            self.assertIn("api.token", command)
            self.assertIn("-m 2", command)                        # never hang the tool
            self.assertTrue(command.rstrip().endswith("|| true"))  # never fail the tool
            self.assertIn("/v1/pet/events", command)
        self.assertNotIn("a" * 40, text)                          # the token itself is never printed

    def test_codex_notify_snippet(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "api.token").write_text("b" * 40 + "\n")
            _, text = self.run_cli("--runtime", tmp, "hooks", "codex")
        self.assertIn("notify = [\"sh\", \"-c\",", text)
        self.assertIn("agent_done", text)

    def test_states_listing_covers_the_catalog(self):
        _, text = self.run_cli("states")
        for state in pet.STATES:
            self.assertIn(state, text)


if __name__ == "__main__":
    unittest.main()
