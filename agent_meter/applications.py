"""Join local ledgers by client application, independently of billing accounts."""
from .model import COVERAGE_METRICS

APP_IDS = {"mcode": "minimax_code", "dsh": "deepseek_harness", "agy": "antigravity",
           "kimi_chat": "kimi_desktop", "codex_images": "codex"}


def app_id(name):
    return APP_IDS.get(name, name)


def application_usage(sources):
    """An absent period has no measurement. A measured empty ledger gets a zero."""
    apps = {}
    for src in sources:
        key = src["id"]
        if "#" in key or key.startswith("codexbar:"):
            continue
        value = src["metrics"]["tokens"].get("value") or {}
        imported = key == "imported_history"
        for period, window in value.get("periods", {}).items():
            if period not in ("today", "7d", "30d", "all") or not isinstance(window, dict):
                continue
            measurements = {}
            if imported:
                for group in window.get("groups", []):
                    row = measurements.setdefault(app_id(group["app"]), [0, 0])
                    row[0] += group["total_tokens"]
                    row[1] += group.get("requests", 0)
            elif "total_tokens" in window.get("totals", {}):
                totals = window["totals"]
                measurements[app_id(key)] = (totals["total_tokens"], totals.get("requests", 0))
            for app, (tokens, requests) in measurements.items():
                row = apps.setdefault(app, {}).setdefault(period, {"total_tokens": 0, "requests": 0})
                row["history" if imported else "direct"] = {
                    "source": key, "tokens": tokens, "requests": requests,
                    "status": src["metrics"]["tokens"]["status"]}
                row["total_tokens"] += tokens
                row["requests"] += requests
    return apps


def coverage_matrix(apps, sources, usage=None):
    usage = application_usage(sources) if usage is None else usage
    by_id = {s["id"]: s for s in sources}
    apps = [dict(app, application_id=app_id(app["provider"])) for app in apps]
    for key in sorted(usage.keys() - {app["application_id"] for app in apps}):
        kind = "local_ledger" if "direct" in usage[key].get("all", {}) else "imported_history"
        apps.append({"name": key, "application_id": key, "provider": key, "installed": False,
                     "path": None, "version": None, "bundle_id": None, "discovery_kind": kind})
    matrix = []
    for app in apps:
        key = app["application_id"]
        fields = {}
        for name in COVERAGE_METRICS:
            candidates = [by_id[k] for k in (key, "codexbar:" + key) if k in by_id]
            if name == "tokens" and any("history" in w for w in usage.get(key, {}).values()):
                candidates.append(by_id["imported_history"])
            chosen = next((s for s in candidates if s["metrics"][name]["value"] is not None),
                          candidates[0] if candidates else None)
            if chosen:
                m = chosen["metrics"][name]
                fields[name] = {"status": m["status"], "source": chosen["id"],
                                "reason": m["reason"], "scope": chosen["scope"]}
            else:
                fields[name] = {"status": "not_supported", "source": None, "reason": "adapter_not_implemented"}
        matrix.append({"application": app, "fields": fields})
    return matrix
