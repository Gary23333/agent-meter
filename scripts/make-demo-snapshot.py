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

sources = [codex, kimi, design, history]
apps = [{"name": name, "provider": provider, "installed": True, "path": None,
         "version": None, "bundle_id": None} for name, provider in [
    ("Codex", "codex"), ("Kimi Code", "kimi"), ("MiniMax Design", "minimax_design"),
    ("Claude Code", "claude"), ("Gemini CLI", "gemini"), ("CC Switch", "ccswitch")]]
coverage = coverage_matrix(apps, sources)
output.write_text(json.dumps({"schema_version": SCHEMA_VERSION, "collected_at": timestamp(now),
    "served_from_cache": False, "sources": sources, "coverage": coverage,
    "coverage_summary": coverage_summary(coverage)}, ensure_ascii=False, indent=2) + "\n")
print(output)
