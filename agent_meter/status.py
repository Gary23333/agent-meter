"""Collection status panel payload (E4): what worked, what failed, what is
unpriced or stale — so "why is today lower" has an answer. Pure projection
of one snapshot plus config; collects nothing new.
"""
from .model import timestamp


def collection_status(snapshot, config, now):
    sources = []
    unpriced = set()
    stale = []
    for src in snapshot.get("sources", []):
        cost = (src.get("metrics") or {}).get("cost") or {}
        value = cost.get("value") if isinstance(cost.get("value"), dict) else {}
        periods = value.get("periods") if isinstance(value, dict) else None
        if isinstance(periods, dict):
            for period in periods.values():
                if isinstance(period, dict):
                    for model in period.get("unmatched_models") or []:
                        if isinstance(model, str):
                            unpriced.add(model)
        if src.get("status") == "stale":
            stale.append(src["id"])
        sources.append({"id": src["id"], "scope": src["scope"], "status": src.get("status"),
                        "reason": (src.get("diagnostics") or {}).get("reason"),
                        "observed_at": src.get("observed_at"),
                        "last_error": (src.get("diagnostics") or {}).get("last_error")})
    preferences = config.get("preferences") or {}
    low_resource = bool(preferences.get("low_resource_mode"))
    return {
        "schema_version": 1,
        "generated_at": timestamp(now),
        "snapshot_at": snapshot.get("collected_at"),
        "served_from_cache": snapshot.get("served_from_cache", False),
        "low_resource_mode": low_resource,
        "skipped_ledgers": (preferences.get("skip_ledgers_low_resource") or []) if low_resource else [],
        "cache_ttl_seconds": config.get("cache_ttl_seconds", 120),
        "sources": sources,
        "stale_sources": stale,
        "unpriced_models": sorted(unpriced),
        "disabled_sources": sorted(set(config.get("disabled_sources") or []) |
                                 set(preferences.get("disabled_sources") or [])),
    }