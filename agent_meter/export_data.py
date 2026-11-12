"""Local history export (C1): a pure projection of the cached snapshot.

Raw measured quantities only: no cost/amount fields, because the local price
table is an estimate basis, not a bill. Every usage row keeps its ledger
signature; independent ledgers are never merged or deduplicated here.
"""
import copy
import csv
import io

from .applications import app_id
from .model import DISPLAY_ZONE, timestamp

EXPORT_SCHEMA = 1
CSV_COLUMNS = ("date", "ledger", "app", "model", "requests", "fresh_input", "output",
               "reasoning", "cache_read", "cache_write", "unclassified", "total_tokens")
_TOKEN_FIELDS = ("fresh_input", "output", "reasoning", "cache_read", "cache_write", "unclassified")
_DATA_STATUSES = {"available", "partial", "stale"}


def _rows(value):
    if isinstance(value, dict) and isinstance(value.get("rows"), list):
        value = value["rows"]
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _sources(snapshot):
    return [src for src in ((snapshot or {}).get("sources") or []) if isinstance(src, dict)]


def _metric(src, name):
    entry = (src.get("metrics") or {}).get(name)
    return entry if isinstance(entry, dict) else {}


def _app_for(src, row):
    app = row.get("app")
    if app is not None:
        return app
    ledger = src.get("id")
    if not ledger or ledger == "imported_history":
        # imported_history spans apps; a missing app there is unknown, not the source id.
        return None
    return app_id(str(ledger).split("#", 1)[0])


def _usage_row(src, row, total):
    out = {"date": row.get("date"), "ledger": src.get("id"), "app": _app_for(src, row),
           "model": row.get("model"), "requests": row.get("requests")}
    for name in _TOKEN_FIELDS:
        out[name] = row.get(name)
    out["total_tokens"] = total
    return out


def _usage_daily(snapshot):
    out = []
    for src in _sources(snapshot):
        entry = _metric(src, "tokens")
        if entry.get("status") not in _DATA_STATUSES:
            continue
        value = entry.get("value")
        if not isinstance(value, dict):
            continue
        models = value.get("daily_models")
        if isinstance(models, list) and models:
            out.extend(_usage_row(src, row, row.get("total_tokens"))
                       for row in models if isinstance(row, dict))
            continue
        # daily_buckets are the same ledger's day totals: exporting them alongside
        # daily_models would double-count, so they are only a fallback.
        for row in _rows(value.get("daily_buckets")):
            out.append(_usage_row(src, row, row.get("tokens")))
    out.sort(key=lambda r: tuple(str(r[k] or "") for k in ("date", "ledger", "app", "model")))
    return out


def _quota_observations(snapshot):
    out = []
    for src in _sources(snapshot):
        entry = _metric(src, "quota")
        if entry.get("status") not in _DATA_STATUSES:
            continue
        for row in _rows(entry.get("value")):
            obs = copy.deepcopy(row)
            obs["account"] = src.get("id")
            obs["account_key"] = src.get("account_key")
            obs["observed_at"] = src.get("observed_at")
            obs["status"] = entry.get("status")
            out.append(obs)
    out.sort(key=lambda obs: str(obs.get("account") or ""))
    return out


def _cards(snapshot):
    collection = (snapshot or {}).get("collection")
    if not isinstance(collection, dict):
        return None
    stats = collection.get("stats")
    stats = stats if isinstance(stats, dict) else {}
    cards = collection.get("cards")
    cards = cards if isinstance(cards, dict) else {}
    rarity = stats.get("by_rarity")
    return {"total_cards": stats.get("total_cards"),
            "distinct_cards": stats.get("distinct_cards"),
            "catalog_size": stats.get("catalog_size"),
            "by_rarity": dict(rarity) if isinstance(rarity, dict) else None,
            "cards": {cid: (entry.get("count") if isinstance(entry, dict) else None)
                      for cid, entry in sorted(cards.items())}}


def export_payload(snapshot, now):
    """Project the cached snapshot into the export envelope; never collects."""
    return {"schema": EXPORT_SCHEMA,
            "generated_at": timestamp(now),
            "timezone": str(DISPLAY_ZONE),
            "usage_daily": _usage_daily(snapshot),
            "quota_observations": _quota_observations(snapshot),
            "cards": _cards(snapshot)}


def export_csv(snapshot):
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)
    for row in _usage_daily(snapshot):
        writer.writerow(["" if row[name] is None else row[name] for name in CSV_COLUMNS])
    return buf.getvalue()