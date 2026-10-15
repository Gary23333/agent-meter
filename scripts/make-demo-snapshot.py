"""Create synthetic UI data for README screenshots; never reads user accounts."""
import json
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from agent_meter.ccswitch import collect_ccswitch
from agent_meter.collector import coverage_matrix, coverage_summary
from agent_meter.model import SCHEMA_VERSION, metric, source, timestamp
from tests.support import database, insert

now = int(time.time())
today = datetime.fromtimestamp(now, ZoneInfo("Asia/Shanghai")).date()
output = root / ".runtime/readme-demo/snapshot.json"
output.parent.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(dir=output.parent) as temp:
    db_path = Path(temp) / "synthetic-history.db"
    db = database(db_path)
    for day in range(7):
        for i, (app, model, base, cost) in enumerate([
            ("codex", "gpt-5.4", 32000, "0.12"),
            ("claude", "claude-sonnet-4.6", 24000, "0.09"),
            ("gemini", "gemini-2.5-pro", 16000, "0.06"),
        ]):
            for turn in range(8):
                insert(db, f"demo-{day}-{i}-{turn}", app_type=app, model=model,
                       input_tokens=base, output_tokens=base // 4,
                       cache_read_tokens=base * 2, cache_creation_tokens=base // 8,
                       total_cost_usd=cost, created_at=now - day * 86400 - turn * 60)
    db.close()
    history = collect_ccswitch(db_path, now)

def account(provider, scope, plan):
    row = source(provider, scope, now)
    row["account_label"] = "演示"
    row["subscription"] = {"plan": plan + " · 演示数据"}
    return row

codex = account("codex", "account", "Plus")
codex["metrics"]["quota"] = metric([{"bucket": "primary", "window_minutes": 300,
    "used_percent": 18, "remaining_percent": 82, "resets_at": timestamp(now + 9000)}])
codex["metrics"]["reset_cards"] = metric({"available_count": 3, "cards": [
    {"expires_at": timestamp(now + 86400 * days), "expiration_state": "active"}
    for days in [3, 7, 14]]})
codex["metrics"]["tokens"] = metric({"lifetime_tokens": 12480000, "daily_buckets": [
    {"date": (today - timedelta(days=6-i)).isoformat(), "tokens": value}
    for i, value in enumerate([240000, 380000, 310000, 510000, 430000, 620000, 570000])]})

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

sources = [codex, kimi, design, history, forecast]
apps = [{"name": name, "provider": provider, "installed": True, "path": None,
         "version": None, "bundle_id": None} for name, provider in [
    ("Codex", "codex"), ("Kimi Code", "kimi"), ("MiniMax Design", "minimax_design"),
    ("Claude Code", "claude"), ("Gemini CLI", "gemini"), ("CC Switch", "ccswitch")]]
coverage = coverage_matrix(apps, sources)
output.write_text(json.dumps({"schema_version": SCHEMA_VERSION, "collected_at": timestamp(now),
    "served_from_cache": False, "sources": sources, "coverage": coverage,
    "coverage_summary": coverage_summary(coverage)}, ensure_ascii=False, indent=2) + "\n")
print(output)
