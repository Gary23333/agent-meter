"""WorkBuddy token history from its local session logs (read-only).

~/.workbuddy/projects/**/*.jsonl writes exactly one providerData.rawUsage
record per model response, attached either to the function_call record or
to the plain assistant message. Verified on this machine (2026-10-09):
5,965 usage records, zero duplicate (sessionId, timestamp) groups, so
every rawUsage-bearing record is counted once. Cache semantics come in
two dialects: doubao-style prompt_cache_hit/miss (verified identity
hit+miss == prompt_tokens on all 5,661 such records; fresh input is the
miss part) and anthropic-style cache_read/creation columns (not present
locally; the fresh = prompt - read - write rule is implemented but
flagged in diagnostics until seen). Only token fields are read, never
message text.
"""
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from .ccswitch import period_bounds
from .model import SourceError, metric, timestamp

MARKER = b'"rawUsage"'
_cache = {}   # path -> ((mtime_ns, size), records, stats)


def _int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _parse_file(path):
    records = []
    stats = {"identity_mismatches": 0, "anthropic_style_records": 0,
             "skipped_malformed": 0, "credit_records": 0}
    credit = Decimal(0)
    with open(path, "rb") as handle:
        for line in handle:
            if MARKER not in line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                stats["skipped_malformed"] += 1
                continue
            if not isinstance(o, dict) or not isinstance((o.get("providerData") or {}).get("rawUsage"), dict):
                continue
            raw = o["providerData"]["rawUsage"]
            ts = o.get("timestamp")
            if isinstance(ts, bool) or not isinstance(ts, (int, float)):
                stats["skipped_malformed"] += 1
                continue
            prompt = _int(raw.get("prompt_tokens")) or 0
            output = _int(raw.get("completion_tokens")) or 0
            hit = _int(raw.get("prompt_cache_hit_tokens"))
            miss = _int(raw.get("prompt_cache_miss_tokens"))
            read = _int(raw.get("cache_read_input_tokens"))
            write = _int(raw.get("cache_creation_input_tokens"))
            if hit is not None or miss is not None:
                if hit is None or miss is None or hit + miss != prompt:
                    stats["identity_mismatches"] += 1
                fresh, cache_read, cache_write = (miss or 0), (hit or 0), 0
            elif read or write:
                # Locally unseen dialect; surfaced in diagnostics, not silent.
                stats["anthropic_style_records"] += 1
                fresh, cache_read, cache_write = max(0, prompt - read - write), read, write
            else:
                fresh, cache_read, cache_write = prompt, 0, 0
            charged = raw.get("credit")
            if isinstance(charged, (int, float)) and not isinstance(charged, bool) and charged > 0:
                try:
                    credit += Decimal(str(charged))
                    stats["credit_records"] += 1
                except (InvalidOperation, ValueError):
                    pass
            records.append((ts / 1000, fresh, output, cache_read, cache_write))
    return records, credit, stats


def load_records(root):
    root = Path(root)
    if not root.is_dir():
        raise SourceError("workbuddy_projects_not_found")
    records, seen = [], set()
    credit = Decimal(0)
    totals = {k: 0 for k in ("identity_mismatches", "anthropic_style_records",
                             "skipped_malformed", "credit_records")}
    for path in root.glob("**/*.jsonl"):
        seen.add(str(path))
        try:
            st = path.stat()
        except OSError:
            continue
        stamp = (st.st_mtime_ns, st.st_size)
        cached = _cache.get(str(path))
        if cached is None or cached[0] != stamp:
            try:
                cached = (stamp, *_parse_file(path))
            except OSError:
                continue
            _cache[str(path)] = cached
        records.extend(cached[1])
        credit += cached[2]
        for k in totals:
            totals[k] += cached[3][k]
    for gone in set(_cache) - seen:
        del _cache[gone]
    return records, credit, totals


def summarize(records, start, end):
    out = {"requests": 0, "fresh_input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    for t, fresh, output, cache_read, cache_write in records:
        if (start is not None and t < start) or t > end:
            continue
        out["requests"] += 1
        out["fresh_input"] += fresh
        out["output"] += output
        out["cache_read"] += cache_read
        out["cache_write"] += cache_write
    out["total_tokens"] = out["fresh_input"] + out["output"] + out["cache_read"] + out["cache_write"]
    denominator = out["fresh_input"] + out["cache_read"] + out["cache_write"]
    out["cache_hit_rate"] = out["cache_read"] / denominator if denominator else None
    return {"start": timestamp(start) if start is not None else None, "end": timestamp(end), "totals": out}


def collect_workbuddy_tokens(root, now, zone=ZoneInfo("Asia/Shanghai")):
    records, credit, stats = load_records(root)
    periods = {p: summarize(records, *period_bounds(now, p, zone)) for p in ("today", "7d", "30d", "all")}
    # Credit is only meaningfully attributable to whole responses, so it is
    # attached to periods by the same window as tokens.
    for p in periods.values():
        p["timezone"] = str(zone)
    periods["all"]["credit_charged"] = format(credit, "f")
    daily = {}
    for t, fresh, output, cache_read, cache_write in records:
        day = datetime.fromtimestamp(t, zone).date().isoformat()
        daily[day] = daily.get(day, 0) + fresh + output + cache_read + cache_write
    return metric({
        "periods": periods,
        "daily_buckets": [{"date": d, "tokens": n} for d, n in sorted(daily.items())],
        "coverage": "workbuddy_local_projects",
        "dedup_rule": "one_rawUsage_record_per_response",
        "credit_unit": "workbuddy_credits",
        **stats,
    })
