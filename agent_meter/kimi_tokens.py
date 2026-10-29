"""Kimi Code token history from its local session logs (read-only).

~/.kimi-code/sessions/**/agents/<agent>/wire.jsonl holds every agent's own
log. Each model turn writes exactly one {"type": "usage.record",
"usageScope": "turn"} line; the same numbers repeat in that step's
"step.end" event, in per-message metadata and in the parent's
"subagent.completed" summary, so only usage.record/turn is counted.
Verified on this machine (2026-10-09): 15,493 turn records, no duplicates
across files, sub-agent summaries equal the sub-agent's own records, and
usage.record ⊇ step.end (2 interrupted steps had no step.end).
"session"-scope records have an unconfirmed meaning; they are excluded and
counted. Only token fields and model names are read, never message text.
"""
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import peak
from .ccswitch import period_bounds
from .model import SourceError, metric, timestamp

FIELDS = ("inputOther", "output", "inputCacheRead", "inputCacheCreation")
MARKER = b'"usage.record"'
from .record_cache import records_cache as _cache


def _parse_file(path):
    records, excluded = [], 0
    with open(path, "rb") as handle:
        for line in handle:
            if MARKER not in line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if not isinstance(o, dict) or o.get("type") != "usage.record" or not isinstance(o.get("usage"), dict):
                continue
            if o.get("usageScope") != "turn":
                excluded += 1
                continue
            u = o["usage"]
            values = [u.get(k, 0) for k in FIELDS]
            t = o.get("time")
            if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in values) \
                    or isinstance(t, bool) or not isinstance(t, int):
                continue
            model = o.get("model") if isinstance(o.get("model"), str) and len(o["model"]) < 80 else "unknown"
            records.append((t / 1000, model, *values))
    return records, excluded


def load_records(root):
    root = Path(root)
    if not root.is_dir():
        raise SourceError("kimi_sessions_not_found")
    records, excluded, seen = [], 0, set()
    for path in root.glob("**/agents/*/wire.jsonl"):
        key = str(path)
        seen.add(key)
        try:
            parsed, skipped = _cache.read(path, _parse_file, ("kimi", str(root)))
        except OSError:
            continue
        records.extend(parsed)
        excluded += skipped
    _cache.prune(seen, ("kimi", str(root)))
    return records, excluded


def _close(bucket_values):
    """Attach total_tokens; this source has no reasoning key, so drop the pad."""
    del bucket_values["reasoning"]
    bucket_values["total_tokens"] = peak.total(bucket_values)
    return bucket_values


def summarize(records, start, end, app="kimi"):
    totals = dict.fromkeys(("requests", "fresh_input", "output", "cache_read", "cache_write"), 0)
    split = {"peak": peak.bucket(), "offpeak": peak.bucket()}
    models = {}
    model_splits = {}
    for t, model, fresh, out, read, write in records:
        if (start is not None and t < start) or t > end:
            continue
        totals["requests"] += 1
        totals["fresh_input"] += fresh
        totals["output"] += out
        totals["cache_read"] += read
        totals["cache_write"] += write
        target = models.setdefault(model, dict.fromkeys(("requests", "fresh_input", "output",
                                                         "cache_read", "cache_write"), 0))
        target["requests"] += 1
        target["fresh_input"] += fresh
        target["output"] += out
        target["cache_read"] += read
        target["cache_write"] += write
        values = {"fresh_input": fresh, "output": out, "cache_read": read, "cache_write": write}
        side = "offpeak" if peak.is_offpeak(t) else "peak"
        peak.add(split[side], values)
        peak.add(model_splits.setdefault(model, {"peak": peak.bucket(), "offpeak": peak.bucket()})[side], values)
    total = totals["fresh_input"] + totals["output"] + totals["cache_read"] + totals["cache_write"]
    cache_base = totals["fresh_input"] + totals["cache_read"] + totals["cache_write"]
    totals["total_tokens"] = total
    totals["cache_hit_rate"] = totals["cache_read"] / cache_base if cache_base else None
    totals["peak"] = _close(split["peak"])
    totals["offpeak"] = _close(split["offpeak"])
    return {"start": timestamp(start) if start is not None else None, "end": timestamp(end),
            "totals": totals,
            # The per-model split carries the same input/output/cache breakdown
            # as the totals, so the price table can cost each model.
            "groups": [{"app": app, "model": m, **v,
                        "total_tokens": sum(v[k] for k in ("fresh_input", "output",
                                                           "cache_read", "cache_write")),
                        "peak": _close(model_splits[m]["peak"]),
                        "offpeak": _close(model_splits[m]["offpeak"])}
                       for m, v in sorted(models.items(), key=lambda x: -x[1]["fresh_input"])]}


def collect_kimi_tokens(home, now, zone=ZoneInfo("Asia/Shanghai")):
    records, excluded = load_records(Path(home) / ".kimi-code/sessions")
    periods = {p: summarize(records, *period_bounds(now, p, zone)) for p in ("today", "7d", "30d", "all")}
    for p in periods.values():
        p["timezone"] = str(zone)
    daily = defaultdict(int)
    for t, _, fresh, out, read, write in records:
        daily[datetime.fromtimestamp(t, zone).date().isoformat()] += fresh + out + read + write
    return metric({
        "periods": periods,
        "peak_split": "request_timestamp",
        "daily_buckets": [{"date": d, "tokens": n} for d, n in sorted(daily.items())],
        "coverage": "kimi_code_local_sessions",
        "dedup_rule": "usage.record_turn_only",
        "excluded_session_scope_records": excluded,
    })
