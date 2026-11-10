"""Create synthetic UI data for README screenshots; never reads user accounts.

Everything here is invented: the accounts, the balances, the token history and
the collection binder. The shapes follow the real contracts (the same
``agent_meter`` modules the backend uses) so the preview renders exactly what
the app would draw for a real snapshot.
"""
import json
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from agent_meter import collection as coll
from agent_meter.applications import application_usage
from agent_meter.collector import coverage_matrix, coverage_summary
from agent_meter.model import SCHEMA_VERSION, metric, source, timestamp
from agent_meter.prices import estimate_daily_cost, estimate_source_cost, load_prices

now = int(time.time())
today = datetime.fromtimestamp(now, ZoneInfo("Asia/Shanghai")).date()
CN = ZoneInfo("Asia/Shanghai")

# --- 本机消耗：30 天的重度用量 ---------------------------------------------
DAYS = 30


def day_total(index):
    """Older days are busier than they look; the last ten rise steadily so the
    personal-record medals have something to chew on."""
    if index < 20:
        return 150_000_000 + (index % 7) * 35_000_000
    return 500_000_000 + (index - 20) * 78_000_000


# app, scope, model (a real entry of the local price table), share of the day's tokens
APPS = [
    ("codex", "account", "gpt-5.3-codex", 0.21),
    ("claude", "account", "claude-sonnet-5-5", 0.17),
    ("antigravity", "account", "gemini-3.1-pro", 0.14),
    ("opencode", "local_session_history", "gpt-5.3-codex", 0.12),
    ("gemini", "local_session_history", "gemini-3-flash", 0.10),
    ("zcode", "local_session_history", "glm-5.3", 0.09),
    ("deepseek_harness", "local_session_history", "deepseek-v4-pro", 0.07),
    ("kimi_desktop", "local_session_history", "kimi-k2.7-code", 0.06),
    ("mimo_code", "local_session_history", "mimo-v2.6-pro", 0.04),
]
# The price table is the real one in CNY, so the demo's estimated spend is a
# real calculation over the built-in prices rather than an invented number.
table = load_prices(str(root / ".runtime" / "readme-demo"), "CNY")


def split_tokens(total, requests):
    """A day's tokens split the way the local ledgers report them."""
    fresh = int(total * 0.21)
    output = int(total * 0.06)
    cache_read = int(total * 0.62)
    cache_write = int(total * 0.11)
    return fresh, output, cache_read, cache_write, requests


def day_bounds(index):
    """[start, end) of the day, index 0 is the oldest."""
    day = today - timedelta(days=DAYS - 1 - index)
    start = int(datetime(day.year, day.month, day.day, tzinfo=CN).timestamp())
    return day, start, start + 86400


def build_ledger_source(app, scope, model, share):
    daily = []
    daily_models = []
    for index in range(DAYS):
        day, start, _ = day_bounds(index)
        total = int(day_total(index) * share)
        requests = max(4, int(total / 900_000))
        fresh, output, cache_read, cache_write, requests = split_tokens(total, requests)
        daily.append({"date": day.isoformat(), "tokens": total})
        daily_models.append({"date": day.isoformat(), "model": model, "requests": requests,
                             "fresh_input": fresh, "output": output, "reasoning": 0,
                             "cache_read": cache_read, "cache_write": cache_write,
                             "total_tokens": total, "app": app})
    row = source(app, scope, now)
    periods = {}
    for name, span in (("today", 1), ("7d", 7), ("30d", 30), ("all", DAYS)):
        picked = daily_models[-span:] if name != "all" else daily_models
        totals = {"requests": 0, "fresh_input": 0, "output": 0, "reasoning": 0,
                  "cache_read": 0, "cache_write": 0}
        for entry in picked:
            for key in totals:
                totals[key] += entry[key]
        totals["total_tokens"] = sum(totals[k] for k in
                                    ("fresh_input", "output", "reasoning", "cache_read", "cache_write"))
        denominator = totals["fresh_input"] + totals["cache_read"] + totals["cache_write"]
        totals["cache_hit_rate"] = totals["cache_read"] / denominator if denominator else None
        # A peak/off-peak split, so DeepSeek's peak multiplier shows up in the estimate.
        peak = {k: int(totals[k] * 0.38) for k in totals}
        peak["total_tokens"] = sum(peak[k] for k in
                                   ("fresh_input", "output", "reasoning", "cache_read", "cache_write"))
        offpeak = {k: totals[k] - peak[k] for k in totals}
        offpeak["total_tokens"] = totals["total_tokens"] - peak["total_tokens"]
        totals["peak"] = dict(peak)
        totals["offpeak"] = dict(offpeak)
        start_day, start_ts, _ = day_bounds(DAYS - span)
        periods[name] = {"start": timestamp(start_ts), "end": timestamp(now),
                         "totals": totals,
                         "groups": [{"app": app, "model": model,
                                     **{k: totals[k] for k in ("requests", "fresh_input", "output",
                                                               "reasoning", "cache_read", "cache_write")},
                                     "total_tokens": totals["total_tokens"],
                                     "peak": peak, "offpeak": offpeak}],
                         "timezone": str(CN)}
    row["metrics"]["tokens"] = metric({
        "periods": periods,
        "peak_split": "request_timestamp",
        "daily_buckets": daily,
        "daily_models": daily_models,
        "coverage": app + "_local_ledger",
        "dedup_rule": "one_assistant_message_per_response",
    })
    # Same estimation the backend does: day-level amounts feed the spending medals.
    estimated = estimate_source_cost(row["metrics"]["tokens"], table)
    if estimated is not None:
        estimated["value"]["daily"] = estimate_daily_cost(row["metrics"]["tokens"], table)
        row["metrics"]["cost"] = estimated
    return row


ledgers = [build_ledger_source(*app) for app in APPS]
by_id = {row["id"]: row for row in ledgers}

# --- 账户来源 ---------------------------------------------------------------

def account(provider, scope, plan, label="演示"):
    row = source(provider, scope, now)
    row["account_label"] = label
    row["subscription"] = {"plan": plan + " · 演示数据"}
    return row


codex = by_id["codex"]
codex["account_label"] = "演示"
codex["subscription"] = {"plan": "Plus · 演示数据"}
codex["metrics"]["quota"] = metric([{"bucket": "primary", "window_minutes": 300,
    "used_percent": 62, "remaining_percent": 38, "resets_at": timestamp(now + 9000)}])
codex["metrics"]["reset_cards"] = metric({"available_count": 3, "cards": [
    {"expires_at": timestamp(now + 86400 * days), "expiration_state": "active"}
    for days in [3, 7, 14]]})
codex["metrics"]["image_generation"] = metric({"daily_buckets": [
    {"date": day_bounds(index)[0].isoformat(), "images": 18 + (index % 6) * 9}
    for index in range(DAYS)]})

claude = by_id["claude"]
claude["account_label"] = "演示"
claude["subscription"] = {"plan": "Max · 演示数据"}
claude["metrics"]["quota"] = metric([
    {"bucket": "limit5h", "window_minutes": 300, "used_percent": 93, "remaining_percent": 7,
     "resets_at": timestamp(now + 4200)},
    {"bucket": "limit7d", "window_minutes": 10080, "used_percent": 61, "remaining_percent": 39,
     "resets_at": timestamp(now + 4 * 86400)}])

antigravity = by_id["antigravity"]
antigravity["account_label"] = "演示"
antigravity["subscription"] = {"plan": "Ultra · 演示数据"}
antigravity["metrics"]["quota"] = metric([
    {"bucket": "gemini", "window_minutes": 300, "used_percent": 44, "remaining_percent": 56,
     "resets_at": timestamp(now + 11000)},
    {"bucket": "week", "window_minutes": 10080, "used_percent": 38, "remaining_percent": 62,
     "resets_at": timestamp(now + 5 * 86400)}])

kimi = account("kimi", "account", "Kimi Code")
kimi["metrics"]["quota"] = metric([
    {"bucket": "limit5h", "used_percent": 27, "remaining_percent": 73, "resets_at": timestamp(now + 5400)},
    {"bucket": "limit7d", "used_percent": 46, "remaining_percent": 54, "resets_at": timestamp(now + 4 * 86400)},
])

design = account("minimax_design", "creative_personal_account", "Media Plan")
design["metrics"]["credits"] = metric([{"balance": 24800, "unit": "credits", "buckets": [
    {"type": "vip", "balance": 22000, "expires_at": timestamp(now + 12 * 86400)},
    {"type": "gift", "balance": 2800, "expires_at": timestamp(now + 3 * 86400)},
]}])
design["metrics"]["credit_refresh_time"] = metric({"date": (today + timedelta(days=12)).isoformat()})
design["metrics"]["renewal_time"] = metric({"date": (today + timedelta(days=30)).isoformat()})

qoder = account("qoder", "account", "Free")
qoder["metrics"]["credits"] = metric({"rows": [], "usage": {"periods": {"all": {"totals": {
    "credits": "46000", "billable_credits": "12500"}}}}})

# --- 重置预测（虚构）--------------------------------------------------------
forecast = source("reset_forecast", "external_forecast", now)
def band(values):
    nums = sorted(v for _, v in values)
    return {"min": nums[0], "max": nums[-1], "spread": nums[-1] - nums[0], "n": len(nums),
            "weighted_median": nums[len(nums) // 2], "agreement": "close" if nums[-1] - nums[0] <= 10 else "split",
            "values": [{"source": s, "percent": v, "basis": "published_answer"} for s, v in values]}
def site(key, name, h24, h48, confidence, weight, median_gap):
    return {"source": key, "name": name, "status": "available", "updated_at": timestamp(now - 600),
            "raw_24h": h24, "raw_48h": h48, "headline_24h": h24, "headline_48h": h48, "weight": weight,
            "model_version": "demo", "self_reported": {"confidence": confidence, "note": "演示数据，非真实预测。"},
            "cadence": {"median_gap_days": median_gap, "longest_gap_days": 14}}
def event(post, kind, hours_ago, summary, n):
    return {"post_id": post, "kind": kind, "announced_at": timestamp(now - hours_ago * 3600), "scope": "global",
            "confidence": "high", "summary": summary, "sources": ["willreset", "codex_reset"][:n]}
forecast["metrics"]["reset_forecast"] = metric({
    "basis": "third_party_forecast", "cache_state": "fresh", "refresh_minutes": 45,
    "disclaimer": "第三方独立统计，与 OpenAI 无关；官方从未保证未来会重置，也不是你的账户周期时钟。",
    "ensemble": {"status": "available", "n_sources": 3, "horizons": {
        "24h": band([("willreset", 22), ("codex_reset", 28), ("codexreset_org", 31)]),
        "48h": band([("willreset", 46), ("codex_reset", 52), ("codexreset_org", 58)])}},
    "sources": [site("willreset", "Will Codex Reset", 22, 46, "medium", 0.40, 3.0),
                site("codex_reset", "Tibo Radar", 28, 52, "low", 0.27, 4.3),
                site("codexreset_org", "Codex Reset Monitor", 31, 58, "medium", 0.88, 3.5)],
    "promises": [{"source": "willreset", "label": "Explicit future reset, no clock", "quote": "演示：下一次重置在路上",
                  "at": timestamp(now - 5 * 3600), "floor_percent": 60, "has_clock": False}],
    "history_events": [event("demo-4", "reset_preview", 5, "演示：预告还会再重置一次", 2),
                       event("demo-3", "reset", 3 * 24, "演示：全员额度已重置", 2),
                       event("demo-2", "banked", 6 * 24, "演示：重置卡发放到账", 1),
                       event("demo-1", "reset", 9 * 24, "演示：全员额度已重置", 2)]})
window_open = now + 9 * 3600
forecast["metrics"]["known_reset_countdown"] = metric({"basis": "third_party_forecast", "targets": [
    {"kind": "typical_window", "precision": "window", "label": "公告常见时段 3 AM - 6 AM", "state": "upcoming",
     "open_at": timestamp(window_open), "close_at": timestamp(window_open + 3 * 3600), "sources": ["codex_reset"]}]})

sources = [kimi, design, qoder, forecast] + ledgers

# --- 收集册（卡册与奖章）--------------------------------------------------
ledger = coll.empty_ledger()
coll.record_drop(ledger, "sp_welcome", now - 29 * 86400, None, None)
# 过去 30 天里反复越过的额度档位
for index in range(30):
    at = now - (30 - index) * 86400 + 3600
    for card, detail in (("q5_50", "用到 50%"), ("q5_80", "用到 80%")):
        if (index + len(card)) % 5:
            coll.record_drop(ledger, card, at, "codex", detail)
    if index % 4 == 0:
        coll.record_drop(ledger, "q5_90", at + 1800, "claude", "用到 90%")
    if index % 9 == 0:
        coll.record_drop(ledger, "q5_full", at + 2400, "claude", "用满")
    if index % 6 == 0:
        coll.record_drop(ledger, "q7_50", at + 600, "claude", "用到 50%")
    if index % 11 == 0:
        coll.record_drop(ledger, "q7_80", at + 900, "claude", "用到 80%")
    if index % 17 == 0:
        coll.record_drop(ledger, "q7_90", at + 1200, "kimi", "用到 90%")
    if index % 3 == 0:
        coll.record_drop(ledger, "rc_saved", at + 300, "codex", "到期 2026-11-%02d" % (10 + index % 20))
    if index % 13 == 0:
        coll.record_drop(ledger, "rc_wasted", at + 400, "codex", "到期 2026-10-%02d" % (10 + index % 20))
# 进行中的窗口：已越过档位的实时发卡
ledger["windows"] = {
    "codex|primary|five_hour": {"source": "codex", "bucket": "primary", "kind": "five_hour",
                                 "resets_at": now + 9000, "peak": 62, "first_at": now - 5400,
                                 "last_at": now, "granted": ["q5_50"]},
    "claude|limit5h|five_hour": {"source": "claude", "bucket": "limit5h", "kind": "five_hour",
                                      "resets_at": now + 4200, "peak": 93, "first_at": now - 7200,
                                      "last_at": now, "granted": ["q5_50", "q5_80", "q5_90"]},
    "claude|limit7d|seven_day": {"source": "claude", "bucket": "limit7d", "kind": "seven_day",
                                      "resets_at": now + 4 * 86400, "peak": 61, "first_at": now - 86400,
                                      "last_at": now, "granted": ["q7_50"]},
    "kimi|limit5h|five_hour": {"source": "kimi", "bucket": "limit5h", "kind": "five_hour",
                               "resets_at": now + 5400, "peak": 27, "first_at": now - 3600,
                               "last_at": now, "granted": []},
}
ledger["creative"] = {"dreamina": {"balance": 18000, "spent": 12400, "since": now - 30 * 86400,
                                   "days": {day_bounds(index)[0].isoformat(): 380 + index * 21
                                            for index in range(30)}}}

# 每日签到：TRAE 连续 12 天 + WorkBuddy 任务奖励
checkin_days = {}
for index in range(12):
    day = (today - timedelta(days=11 - index)).isoformat()
    checkin_days[day] = {"status": {"signed_in": True}, "claims": [
        {"item": "daily_checkin", "result": "ok", "at": timestamp(int(datetime.fromisoformat(day)
                                          .replace(hour=9, tzinfo=CN).timestamp()))}]}
rewards_ledger = {"accounts": {
    "trae_cn": {"days": checkin_days, "checked_at": now},
    "workbuddy": {"days": {(today - timedelta(days=index)).isoformat(): {
        "status": {"signed_in": False},
        "claims": [{"item": "task:daily", "title": "完成一次协作任务", "result": "ok",
                    "at": timestamp(now - index * 86400), "badge": "协作达人" if index % 4 == 0 else None}]
    } for index in range(6)}, "checked_at": now},
}}
rewards_summary = {"accounts": [{"claimed_credits_total": 18500}]}

collection_payload = coll.build(ledger, sources, rewards_ledger, rewards_summary, now)

# --- 落盘 -------------------------------------------------------------------
apps = [{"name": name, "provider": provider, "installed": True, "path": None,
         "version": None, "bundle_id": None} for name, provider in [
    ("Codex", "codex"), ("Claude Code", "claude"), ("Kimi Code", "kimi"),
    ("Antigravity", "antigravity"), ("OpenCode", "opencode"), ("Gemini CLI", "gemini"),
    ("ZCode", "zcode"), ("DeepSeek Harness", "deepseek_harness")]]
coverage = coverage_matrix(apps, sources)
output = root / ".runtime/readme-demo/snapshot.json"
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps({"schema_version": SCHEMA_VERSION, "collected_at": timestamp(now),
    "served_from_cache": False, "sources": sources, "application_usage": application_usage(sources),
    "coverage": coverage, "coverage_summary": coverage_summary(coverage),
    "collection": collection_payload}, ensure_ascii=False, indent=2) + "\n")
print(output)
