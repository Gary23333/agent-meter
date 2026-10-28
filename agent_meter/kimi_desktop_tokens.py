"""Kimi desktop Agent-mode token history (read-only).

Kimi.app keeps its own Agent runtime under
~/Library/Application Support/kimi-desktop/daimon-share/daimon/runtime/
kimi-code/home/sessions; its wire.jsonl files use the same schema as the
CLI's ~/.kimi-code/sessions ledger, so parsing is shared. Verified on this
machine (2026-10-26): 153 session dirs / 7,896 usage.record lines with zero
overlap by session id or record tuple against the CLI ledger, so the two
sources can be added. Auto-titled (ctitle-*) and sub-agent sessions count.
Only token fields and model names are read, never message text.
"""
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .ccswitch import period_bounds
from .kimi_tokens import load_records, summarize
from .model import SourceError, metric, source


def collect_kimi_desktop_tokens(sessions_dir, now, zone=ZoneInfo("Asia/Shanghai")):
    root = Path(sessions_dir)
    if not root.is_dir():
        raise SourceError("kimi_desktop_sessions_not_found")
    try:
        records, excluded = load_records(root)
    except SourceError as e:
        if e.code != "kimi_sessions_not_found":
            raise
        raise SourceError("kimi_desktop_sessions_not_found") from None
    periods = {p: summarize(records, *period_bounds(now, p, zone), app="kimi_desktop")
               for p in ("today", "7d", "30d", "all")}
    for p in periods.values():
        p["timezone"] = str(zone)
    daily = defaultdict(int)
    for t, _, fresh, out, read, write in records:
        daily[datetime.fromtimestamp(t, zone).date().isoformat()] += fresh + out + read + write
    out = source("kimi_desktop", "local_session_history", now)
    out["metrics"]["tokens"] = metric({
        "periods": periods,
        "peak_split": "request_timestamp",
        "daily_buckets": [{"date": d, "tokens": n} for d, n in sorted(daily.items())],
        "coverage": "kimi_desktop_local_sessions",
        "dedup_rule": "usage.record_turn_only",
        "excluded_session_scope_records": excluded,
    })
    return out
