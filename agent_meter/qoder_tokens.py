"""Qoder CN local credits ledger from its CLI session logs (read-only).

~/.qoder-cn/projects/**/*.jsonl holds Claude-Code-compatible session logs.
Every assistant request's final record carries message.usage with a
per-request credits amount; the token fields exist in the schema but are
always zero on this machine (verified 2026-10-15: 8,896 usage records, not
one non-zero token value, and the IDE reports tokenCountsAvailable=false),
so this collector reports credits only and never invents token counts.
request_id is unique per record and is the dedup key. Only usage fields,
model names and timestamps are read, never message text.

The ledger is account-page statistics: it is merged into the qoder account
source's credits metric ({"rows": wallets, "usage": ledger}) and is never
written to a tokens metric, so the local-consumption tab cannot sum it.
"""
import json
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from .ccswitch import period_bounds
from .model import SourceError, metric, timestamp

MARKER = b'"usage"'
from .record_cache import records_cache as _cache


def _parse_ts(value):
    if not isinstance(value, str) or not value or len(value) > 40:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.timestamp()


def _parse_file(path):
    records, excluded = [], 0
    with open(path, "rb") as handle:
        for line in handle:
            if MARKER not in line:
                continue
            try:
                o = json.loads(line, parse_float=Decimal)
            except ValueError:
                continue
            if not isinstance(o, dict):
                continue
            message = o.get("message")
            usage = message.get("usage") if isinstance(message, dict) else None
            if not isinstance(usage, dict):
                continue
            credits = usage.get("credits")
            if isinstance(credits, bool) or not isinstance(credits, (int, Decimal)) or credits < 0:
                excluded += 1
                continue
            request_id = usage.get("request_id")
            if not isinstance(request_id, str) or not request_id or len(request_id) > 120:
                excluded += 1
                continue
            when = _parse_ts(o.get("timestamp"))
            if when is None:
                excluded += 1
                continue
            model = message.get("model")
            model = model if isinstance(model, str) and 0 < len(model) < 80 else "unknown"
            records.append((when, model, Decimal(credits), usage.get("billable") is True,
                            o.get("isSidechain") is True, request_id))
    return records, excluded


def load_records(root):
    """(records, excluded, usage_seen); records are deduplicated by request_id."""
    root = Path(root)
    if not root.is_dir():
        raise SourceError("qoder_sessions_not_found")
    paths = sorted(root.glob("**/*.jsonl"))
    if not paths:
        raise SourceError("qoder_sessions_not_found")
    records, excluded, seen_ids = [], 0, set()
    live = set()
    for path in paths:
        key = str(path)
        live.add(key)
        try:
            cached = _cache.read(path, _parse_file, ("qoder_tokens", str(root)))
        except OSError:
            continue
        for record in cached[0]:
            if record[5] in seen_ids:
                excluded += 1
                continue
            seen_ids.add(record[5])
            records.append(record)
        excluded += cached[1]
    _cache.prune(live, ("qoder_tokens", str(root)))
    usage_seen = len(records) + excluded
    if usage_seen and not records:
        # Every usage object lost its credits: the private format drifted.
        raise SourceError("unsupported_qoder_usage_schema")
    return records, excluded, usage_seen


def _totals(rows):
    out = {"requests": 0, "credits": Decimal(0), "billable_requests": 0, "billable_credits": Decimal(0)}
    for _when, _model, credits, billable, _side, _rid in rows:
        out["requests"] += 1
        out["credits"] += credits
        if billable:
            out["billable_requests"] += 1
            out["billable_credits"] += credits
    return {"requests": out["requests"], "credits": format(out["credits"], "f"),
            "billable_requests": out["billable_requests"],
            "billable_credits": format(out["billable_credits"], "f")}


def _summarize(records, start, end, zone):
    window = [r for r in records if (start is None or r[0] >= start) and r[0] <= end]
    models = defaultdict(list)
    for record in window:
        models[record[1]].append(record)
    return {"start": timestamp(start) if start is not None else None, "end": timestamp(end),
            "timezone": str(zone), "totals": _totals(window),
            "groups": [{"model": m, **_totals(rows)} for m, rows in sorted(models.items())]}


def collect_qoder_credits(root, now, zone=ZoneInfo("Asia/Shanghai")):
    """The credits ledger value; raises SourceError when nothing is readable."""
    records, excluded, usage_seen = load_records(root)
    periods = {p: _summarize(records, *period_bounds(now, p, zone), zone) for p in ("today", "7d", "30d", "all")}
    daily = defaultdict(lambda: [0, Decimal(0)])
    side = [0, Decimal(0)]
    for when, _model, credits, _billable, sidechain, _rid in records:
        day = datetime.fromtimestamp(when, zone).date().isoformat()
        daily[day][0] += 1
        daily[day][1] += credits
        if sidechain:
            side[0] += 1
            side[1] += credits
    return {
        "unit": "qoder_credits",
        "token_fields": "not_provided",
        "coverage": "qoder_cn_cli_local_sessions",
        "dedup_rule": "request_id_unique_per_record",
        "usage_records_seen": usage_seen,
        "excluded_usage_records": excluded,
        "sidechain": {"requests": side[0], "credits": format(side[1], "f")},
        "periods": periods,
        "daily_buckets": [{"date": d, "requests": n, "credits": format(c, "f")}
                          for d, (n, c) in sorted(daily.items())],
    }


def merge_credits_metric(existing, ledger):
    """Fold the ledger into an account source's credits metric.

    Web/SDK wallet rows stay under "rows"; the local ledger lives under
    "usage". A legacy list value (wallets only) keeps rendering unchanged.
    """
    value = existing.get("value") if isinstance(existing, dict) else None
    if isinstance(value, list):
        rows = value
    elif isinstance(value, dict) and isinstance(value.get("rows"), list):
        rows = value["rows"]
    else:
        rows = []
    return metric({"rows": rows, "usage": ledger})
