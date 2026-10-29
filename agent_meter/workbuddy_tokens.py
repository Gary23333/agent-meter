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

Model attribution (added 2026-10-15) comes from providerData.model, the
vendor's own id (e.g. deepseek-v4.1-flash, hy4-preview, glm-5.3-flash);
providerData.requestModelName is the display spelling and is only the
fallback. completion_tokens already contains the thinking tokens
(verified on 6,398 records: completion_tokens >= completion_thinking_tokens
== completion_tokens_details.reasoning_tokens), so thinking is reported
as a sub-part and never added to the totals; prompt_cache_write_tokens is
read as the doubao-dialect cache write (zero on every local record).
"""
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from . import peak
from .ccswitch import period_bounds
from .model import SourceError, metric, timestamp

MARKER = b'"rawUsage"'
TOKEN_FIELDS = ("fresh_input", "output", "cache_read", "cache_write")
from .record_cache import records_cache as _cache


def _int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _model(provider_data):
    for key in ("model", "requestModelName"):
        value = provider_data.get(key)
        if isinstance(value, str) and 0 < len(value) < 120:
            return value
    return "unknown"


def _parse_file(path):
    records = []
    stats = {"identity_mismatches": 0, "anthropic_style_records": 0,
             "skipped_malformed": 0, "credit_records": 0, "unknown_model_records": 0}
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
            provider = o["providerData"]
            raw = provider["rawUsage"]
            ts = o.get("timestamp")
            if isinstance(ts, bool) or not isinstance(ts, (int, float)):
                stats["skipped_malformed"] += 1
                continue
            model = _model(provider)
            if model == "unknown":
                stats["unknown_model_records"] += 1
            prompt = _int(raw.get("prompt_tokens")) or 0
            output = _int(raw.get("completion_tokens")) or 0
            hit = _int(raw.get("prompt_cache_hit_tokens"))
            miss = _int(raw.get("prompt_cache_miss_tokens"))
            read = _int(raw.get("cache_read_input_tokens"))
            write = _int(raw.get("cache_creation_input_tokens"))
            if hit is not None or miss is not None:
                if hit is None or miss is None or hit + miss != prompt:
                    stats["identity_mismatches"] += 1
                fresh, cache_read = (miss or 0), (hit or 0)
                cache_write = _int(raw.get("prompt_cache_write_tokens")) or 0
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
            # Thinking is already inside completion_tokens; carried separately.
            records.append((ts / 1000, model, fresh, output, cache_read, cache_write,
                            _int(raw.get("completion_thinking_tokens")) or 0))
    return records, credit, stats


def load_records(root):
    root = Path(root)
    if not root.is_dir():
        raise SourceError("workbuddy_projects_not_found")
    records, seen = [], set()
    credit = Decimal(0)
    totals = {k: 0 for k in ("identity_mismatches", "anthropic_style_records",
                             "skipped_malformed", "credit_records", "unknown_model_records")}
    for path in root.glob("**/*.jsonl"):
        seen.add(str(path))
        try:
            cached = _cache.read(path, _parse_file, ("workbuddy_tokens", str(root)))
        except OSError:
            continue
        records.extend(cached[0])
        credit += cached[1]
        for k in totals:
            totals[k] += cached[2][k]
    _cache.prune(seen, ("workbuddy_tokens", str(root)))
    return records, credit, totals


def _split_bucket():
    """peak/off-peak accumulator over this source's own fields."""
    values = peak.bucket()
    del values["reasoning"]   # this source reports no reasoning column
    values["thinking_tokens"] = 0
    return values


def _close(bucket_values):
    """Attach total_tokens (same rule as the totals) to a split bucket."""
    bucket_values["total_tokens"] = peak.total(bucket_values)
    return bucket_values


def summarize(records, start, end):
    out = {"requests": 0, "fresh_input": 0, "output": 0, "cache_read": 0, "cache_write": 0,
           "thinking_tokens": 0}
    split = {"peak": _split_bucket(), "offpeak": _split_bucket()}
    models = {}
    model_splits = {}
    for t, model, fresh, output, cache_read, cache_write, thinking in records:
        if (start is not None and t < start) or t > end:
            continue
        out["requests"] += 1
        target = models.setdefault(model, dict.fromkeys(("requests", *TOKEN_FIELDS, "thinking_tokens"), 0))
        target["requests"] += 1
        values = {"fresh_input": fresh, "output": output, "cache_read": cache_read,
                  "cache_write": cache_write, "thinking_tokens": thinking}
        side = "offpeak" if peak.is_offpeak(t) else "peak"
        split[side]["requests"] += 1
        target_side = model_splits.setdefault(model, {"peak": _split_bucket(), "offpeak": _split_bucket()})[side]
        target_side["requests"] += 1
        for name, value in values.items():
            out[name] += value
            target[name] += value
            split[side][name] += value
            target_side[name] += value
    out["total_tokens"] = sum(out[k] for k in TOKEN_FIELDS)
    out["peak"] = _close(split["peak"])
    out["offpeak"] = _close(split["offpeak"])
    denominator = out["fresh_input"] + out["cache_read"] + out["cache_write"]
    out["cache_hit_rate"] = out["cache_read"] / denominator if denominator else None
    return {"start": timestamp(start) if start is not None else None, "end": timestamp(end),
            "totals": out,
            "groups": [{"app": "workbuddy", "model": m, **v,
                        "total_tokens": sum(v[k] for k in TOKEN_FIELDS),
                        "peak": _close(model_splits[m]["peak"]),
                        "offpeak": _close(model_splits[m]["offpeak"])}
                       for m, v in sorted(models.items(), key=lambda x: -x[1]["fresh_input"])]}


def collect_workbuddy_tokens(root, now, zone=ZoneInfo("Asia/Shanghai")):
    records, credit, stats = load_records(root)
    periods = {p: summarize(records, *period_bounds(now, p, zone)) for p in ("today", "7d", "30d", "all")}
    # Credit is only meaningfully attributable to whole responses, so it is
    # attached to periods by the same window as tokens.
    for p in periods.values():
        p["timezone"] = str(zone)
    periods["all"]["credit_charged"] = format(credit, "f")
    daily = {}
    for t, model, fresh, output, cache_read, cache_write, thinking in records:
        day = datetime.fromtimestamp(t, zone).date().isoformat()
        daily[day] = daily.get(day, 0) + fresh + output + cache_read + cache_write
    return metric({
        "periods": periods,
        "peak_split": "request_timestamp",
        "daily_buckets": [{"date": d, "tokens": n} for d, n in sorted(daily.items())],
        "coverage": "workbuddy_local_projects",
        "dedup_rule": "one_rawUsage_record_per_response",
        "credit_unit": "workbuddy_credits",
        # thinking_tokens is a sub-part of output, never an extra total.
        "thinking_in_output": True,
        **stats,
    })
