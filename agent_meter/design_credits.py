"""MiniMax Design media (image/video) credit estimates from local task ledgers.

Route 2 of docs/research/minimax-design-local-tokens-recon-2026-10-15.md:
the Design gateway publishes per-model credit prices
(`GET /api/v1/billing/pricing`) and each Hub project keeps a
`.hilo/completed-results.json` task ledger. Combining the two yields a
`basis=local_price_table` reference estimate. There is no local per-task
debit ledger, so this is never reconciled against the wallet balance and
never subtracted from it.

Ledger shape verified read-only on this machine (2026-11-12, 34 project
ledgers / 317 entries): {"schemaVersion": 1, "entries": [{cloudTaskId,
mediaType, assetPath, recordedAt(epoch ms), nodeId?, result?, summary?}]}.
`result` carries ok/path/duration/width/height; `summary` carries
`assetInfo` with model_id, params{resolution, duration, model_name} and the
measured output duration. Only 43 of 317 entries carry model metadata, so
most tasks stay unpriced: an unknown model/resolution/duration is reported
as an unpriced task, never as zero credits and never with a guessed price.

Only the published base generation price is used (per image, per output
second, per block, or a flat tier price). Reference-image/video surcharges,
free quotas and promotions are excluded because the ledger does not record
how they were applied.
"""
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from urllib.parse import urlsplit

from .model import DISPLAY_ZONE, SourceError, metric, period_bounds, timestamp
from .transport import get_json

PRICING = "/api/v1/billing/pricing"
ALLOWED = {PRICING}
LEDGER_GLOBS = (".hilo/completed-results.json", "*/.hilo/completed-results.json")
LEDGER_SCHEMA = 1
PERIODS = ("today", "7d", "30d", "all")
MEDIA_TYPES = ("image", "video")
SIX = Decimal("0.000001")
MAX_ID = 120
MAX_RESOLUTION = 40
MAX_SECONDS = Decimal(86400)
MAX_EPOCH_MS = 253402271999000
FAILED_CODES = {"design_media_ledger_read_failed", "design_media_unsupported_ledger_schema",
                "design_media_ledger_entries_invalid"}


def pricing_query(origin, timeout):
    # Same loopback allowlist guard as minimax_design.design_query, whose
    # ALLOWED set does not contain the pricing endpoint and must not change.
    parsed = urlsplit(origin)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
            or parsed.username or parsed.password or PRICING not in ALLOWED):
        raise SourceError("design_media_invalid_endpoint")
    try:
        return get_json(origin.rstrip("/") + PRICING, timeout=timeout, local=True)
    except SourceError as error:
        raise SourceError("design_media_gateway_unreachable" if error.code == "connection_failed"
                          else "design_media_pricing_unavailable") from None


def _decimal(value, maximum=None):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not number.is_finite() or number < 0 or (maximum is not None and number > maximum):
        return None
    return number


def _text(value, limit):
    return value if isinstance(value, str) and 0 < len(value) <= limit else None


def _object(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value, parse_float=Decimal)
        except ValueError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _resolutions(value):
    if not isinstance(value, list):
        return None
    labels = {v.strip().lower() for v in value if isinstance(v, str) and v.strip()}
    return labels or None


def _durations(value):
    if not isinstance(value, list):
        return None
    seconds = {_decimal(v, MAX_SECONDS) for v in value}
    seconds.discard(None)
    return seconds or None


def _tiers(rows, kind):
    out = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        price = _decimal(row.get("realCost"))
        if kind == "image":
            if price is None or price <= 0:
                continue
            out.append({"resolutions": _resolutions(row.get("resolutions")), "durations": None,
                        "unit": "per_image", "price": price, "block": None})
            continue
        rate = _decimal(row.get("costPerSecond"))
        block_price = _decimal(row.get("costPerBlock"))
        block = _decimal(row.get("blockSeconds"))
        if rate is not None and rate > 0:
            unit, price, block_seconds = "per_second", rate, None
        elif block_price is not None and block_price > 0 and block is not None and block > 0:
            unit, price, block_seconds = "per_block", block_price, block
        elif price is not None and price > 0:
            unit, price, block_seconds = "per_task", price, None
        else:
            continue
        out.append({"resolutions": _resolutions(row.get("resolutions")),
                    "durations": _durations(row.get("durations")),
                    "unit": unit, "price": price, "block": block_seconds})
    return out


def normalize_pricing(payload):
    """Per-model price tiers keyed by lowercased modelID; unusable rows are dropped."""
    if not isinstance(payload, dict) or payload.get("enabled") is not True:
        raise SourceError("design_media_pricing_unavailable")
    table = {}
    for media_type, field in (("image", "imageCosts"), ("video", "videoCosts")):
        rows = payload.get(media_type)
        if not isinstance(rows, list):
            raise SourceError("design_media_pricing_unavailable")
        models = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            model = _text(row.get("modelID"), MAX_ID)
            if model is None:
                continue
            models[model.lower()] = {"model": model, "default": _decimal(row.get("defaultCost")),
                                     "tiers": _tiers(row.get(field), media_type)}
        if not models:
            raise SourceError("design_media_pricing_unavailable")
        table[media_type] = models
    return table


def _entry(entry):
    """(task, rejection) for one ledger entry; task is None when it cannot be counted."""
    if not isinstance(entry, dict):
        return None, "not_an_object"
    task_id = _text(entry.get("cloudTaskId"), MAX_ID)
    if task_id is None:
        return None, "missing_task_id"
    media_type = _text(entry.get("mediaType"), MAX_RESOLUTION)
    if media_type is None:
        return None, "missing_media_type"
    when = entry.get("recordedAt")
    if isinstance(when, bool) or not isinstance(when, int) or not 0 < when <= MAX_EPOCH_MS:
        return None, "invalid_recorded_at"
    for field in ("result", "summary"):
        if entry.get(field) is not None and _object(entry[field]) is None:
            return None, "invalid_" + field
    result = _object(entry.get("result")) or {}
    if result.get("ok") is False:
        return None, "failed_task"
    media_type = media_type.lower()
    if media_type not in MEDIA_TYPES:
        return None, "out_of_scope"
    summary = _object(entry.get("summary")) or {}
    meta = summary.get("assetInfo") if isinstance(summary.get("assetInfo"), dict) else summary
    params = meta.get("params") if isinstance(meta.get("params"), dict) else {}
    model = _text(meta.get("model_id"), MAX_ID) or _text(params.get("model_name"), MAX_ID)
    resolution = _text(params.get("resolution"), MAX_RESOLUTION) or _text(meta.get("resolution"), MAX_RESOLUTION)
    requested = _decimal(params.get("duration"), MAX_SECONDS)
    measured = _decimal(meta.get("duration"), MAX_SECONDS)
    if measured is None:
        measured = _decimal(result.get("duration"), MAX_SECONDS)
    return {"id": task_id, "when": when, "media_type": media_type, "model": model,
            "resolution": resolution.strip().lower() if resolution else None,
            "seconds": measured if measured is not None else requested,
            "tier_seconds": requested if requested is not None else measured}, None


def load_ledger(path):
    """(tasks, stats) from one ledger file or a directory of project ledgers."""
    if not path:
        raise SourceError("design_media_ledger_not_found")
    root = Path(path).expanduser()
    if root.is_file():
        paths = [root]
    elif root.is_dir():
        paths = sorted({p for pattern in LEDGER_GLOBS for p in root.glob(pattern) if p.is_file()})
    else:
        raise SourceError("design_media_ledger_not_found")
    if not paths:
        raise SourceError("design_media_ledger_not_found")
    tasks, seen = [], set()
    stats = {"files": len(paths), "entries_seen": 0, "duplicate_entries": 0, "rejected_entries": 0,
             "failed_entries": 0, "out_of_scope_entries": 0, "rejection_reasons": {}}
    for ledger in paths:
        try:
            payload = json.loads(ledger.read_text(encoding="utf-8"), parse_float=Decimal)
        except (OSError, ValueError, UnicodeDecodeError):
            raise SourceError("design_media_ledger_read_failed") from None
        if (not isinstance(payload, dict) or isinstance(payload.get("schemaVersion"), bool)
                or payload.get("schemaVersion") != LEDGER_SCHEMA or not isinstance(payload.get("entries"), list)):
            raise SourceError("design_media_unsupported_ledger_schema")
        for entry in payload["entries"]:
            stats["entries_seen"] += 1
            task, rejection = _entry(entry)
            if rejection == "out_of_scope":
                stats["out_of_scope_entries"] += 1
                continue
            if rejection == "failed_task":
                stats["failed_entries"] += 1
                continue
            if task is None:
                stats["rejected_entries"] += 1
                stats["rejection_reasons"][rejection] = stats["rejection_reasons"].get(rejection, 0) + 1
                continue
            if task["id"] in seen:
                stats["duplicate_entries"] += 1
                continue
            seen.add(task["id"])
            tasks.append(task)
    if stats["entries_seen"] and not tasks and not stats["failed_entries"] and not stats["out_of_scope_entries"]:
        raise SourceError("design_media_ledger_entries_invalid")
    stats["rejection_reasons"] = dict(sorted(stats["rejection_reasons"].items()))
    return tasks, stats


def _select(tiers, resolution, tier_seconds):
    matched = [t for t in tiers if not t["resolutions"] or (resolution and resolution in t["resolutions"])]
    if not matched:
        return None, "resolution_unknown" if resolution is None else "resolution_not_priced"
    matched = [t for t in matched if not t["durations"]
               or (tier_seconds is not None and tier_seconds in t["durations"])]
    if not matched:
        return None, "duration_unknown" if tier_seconds is None else "duration_not_priced"
    prices = {(t["unit"], t["price"], t["block"]) for t in matched}
    if len(prices) != 1:
        return None, "price_tier_ambiguous"
    return matched[0], None


def price_task(task, table):
    """(credits, tier, reason): credits is None whenever the price is not evidenced."""
    model = task["model"]
    if model is None:
        return None, None, "model_unknown"
    entry = table[task["media_type"]].get(model.lower())
    if entry is None:
        return None, None, "model_not_in_price_table"
    default = {"resolutions": None, "durations": None, "unit": "per_image"
               if task["media_type"] == "image" else "per_task", "price": entry["default"], "block": None}
    if not entry["tiers"]:
        if entry["default"] is None:
            return None, None, "model_price_unavailable"
        tier, rule = default, "model_default"
    else:
        tier, reason = _select(entry["tiers"], task["resolution"], task["tier_seconds"])
        if tier is None:
            if reason == "resolution_unknown" and entry["default"] is not None:
                tier, rule = default, "model_default"
            else:
                return None, None, reason
        else:
            rule = "price_table_tier"
    seconds = task["seconds"]
    if tier["unit"] in {"per_second", "per_block"}:
        if seconds is None or seconds <= 0:
            return None, None, "duration_unknown"
        amount = tier["price"] * seconds
        if tier["unit"] == "per_block":
            blocks, remainder = divmod(seconds, tier["block"])
            amount = tier["price"] * (blocks + (1 if remainder else 0))
    else:
        amount = tier["price"]
    try:
        credits = amount.quantize(SIX, rounding=ROUND_HALF_UP)
    except (InvalidOperation, OverflowError, ValueError):
        return None, None, "credits_out_of_range"
    return credits, {**tier, "rule": rule, "model": entry["model"]}, None


def _money(value):
    return format(value.normalize(), "f")


def _summarize(rows, start, end, zone):
    totals = {"tasks": 0, "priced_tasks": 0, "unpriced_tasks": 0, "credits": Decimal(0)}
    media = {kind: {"media_type": kind, "tasks": 0, "priced_tasks": 0, "unpriced_tasks": 0,
                    "credits": Decimal(0)} for kind in MEDIA_TYPES}
    groups, reasons, models = {}, {}, {}
    for task, credits, tier, reason in rows:
        if (start is not None and task["when"] < start * 1000) or task["when"] > end * 1000:
            continue
        kind = task["media_type"]
        for target in (totals, media[kind]):
            target["tasks"] += 1
            if credits is None:
                target["unpriced_tasks"] += 1
            else:
                target["priced_tasks"] += 1
                target["credits"] += credits
        if credits is None:
            reasons[reason] = reasons.get(reason, 0) + 1
            name = task["model"] or "unknown"
            models[name] = models.get(name, 0) + 1
            continue
        key = (kind, tier["model"], task["resolution"], tier["rule"], tier["unit"], tier["price"], tier["block"])
        group = groups.setdefault(key, {"tasks": 0, "credits": Decimal(0), "seconds": Decimal(0)})
        group["tasks"] += 1
        group["credits"] += credits
        if task["seconds"] is not None:
            group["seconds"] += task["seconds"]
    return {
        "start": timestamp(start) if start is not None else None,
        "end": timestamp(end),
        "timezone": str(zone),
        "totals": {**totals, "credits": _money(totals["credits"])},
        "media_types": [{**media[kind], "credits": _money(media[kind]["credits"])} for kind in MEDIA_TYPES],
        "groups": [{"media_type": kind, "model": model, "resolution": resolution, "price_rule": rule,
                    "price_unit": unit, "unit_price": _money(price),
                    "block_seconds": _money(block) if block is not None else None,
                    "tasks": row["tasks"], "credits": _money(row["credits"]),
                    "seconds": _money(row["seconds"]) if kind == "video" else None}
                   for (kind, model, resolution, rule, unit, price, block), row
                   in sorted(groups.items(), key=lambda item: (item[0][0], item[0][1], item[0][2] or "",
                                                               item[0][3], item[0][5]))],
        "unpriced": {"tasks": totals["unpriced_tasks"], "by_reason": dict(sorted(reasons.items())),
                     "by_model": dict(sorted(models.items()))},
    }


def collect_design_media_credits(gateway_url, ledger_path, now, timeout, node_binary=None):
    """The minimax_design `media_credits` metric; reference estimate only.

    node_binary exists for signature parity with the other Design collectors
    and is unused: pricing is a plain loopback GET, no MCP probe is needed.
    """
    zone = DISPLAY_ZONE
    try:
        table = normalize_pricing(pricing_query(gateway_url, timeout))
        tasks, stats = load_ledger(ledger_path)
    except SourceError as error:
        return metric(status="error" if error.code in FAILED_CODES else "not_connected", reason=error.code)
    rows = [(task, *price_task(task, table)) for task in tasks]
    periods = {name: _summarize(rows, *period_bounds(now, name, zone), zone) for name in PERIODS}
    unpriced = periods["all"]["totals"]["unpriced_tasks"]
    value = {
        "basis": "local_price_table",
        "unit": "minimax_credits",
        "reference_only": True,
        "wallet_reconciliation": "never",
        "price_scope": "base_generation_only_excludes_reference_surcharges_free_quota_and_promotions",
        "coverage": "minimax_design_completed_results_ledgers",
        "dedup_rule": "cloud_task_id_unique_across_project_ledgers",
        "timezone": str(zone),
        "pricing": {"endpoint": PRICING, "state": "available",
                    "image_models": len(table["image"]), "video_models": len(table["video"])},
        "ledger": stats,
        "periods": periods,
    }
    if unpriced:
        return metric(value, status="partial", reason="design_media_tasks_unpriced")
    return metric(value)