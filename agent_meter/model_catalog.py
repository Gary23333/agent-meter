"""Read-only model catalogue sync for local API-equivalent estimates.

The public models.dev catalogue supplies model ids, display names and list
prices. Remote rows live apart from the user's editable price table, so a sync
can never overwrite a local edit. Unknown/free/preview models without a usable
price are deliberately omitted; users can bind those ids to an existing model
in the price window instead of treating them as free.
"""
import json
import time
import urllib.request
from pathlib import Path

CATALOG_URL = "https://models.dev/api.json"
SYNC_INTERVAL = 24 * 60 * 60
MAX_BYTES = 16 * 1024 * 1024
PROVIDERS = {"openai", "anthropic", "google", "moonshotai", "minimax", "deepseek", "zai", "xai", "alibaba"}
PRICE_KEYS = ("input", "cache_read", "cache_write", "output")


def _read(path, default):
    try:
        value = json.loads(Path(path).read_text())
        return value if isinstance(value, dict) else default
    except (OSError, ValueError, json.JSONDecodeError):
        return default


def load_catalog(runtime_dir):
    data = _read(Path(runtime_dir) / "model-catalog.json", {})
    models = data.get("models")
    return models if isinstance(models, dict) else {}


def catalog_status(runtime_dir):
    data = _read(Path(runtime_dir) / "model-catalog.json", {})
    return {
        "source": CATALOG_URL,
        "synced_at": data.get("synced_at"),
        "model_count": len(load_catalog(runtime_dir)),
        "last_error": data.get("last_error"),
    }


def _catalog_rows(payload):
    rows = {}
    for provider_id, provider in payload.items():
        if provider_id not in PROVIDERS or not isinstance(provider, dict):
            continue
        for model_id, model in (provider.get("models") or {}).items():
            if not isinstance(model_id, str) or not isinstance(model, dict):
                continue
            cost = model.get("cost")
            if not isinstance(cost, dict):
                continue
            prices = {}
            for key in PRICE_KEYS:
                value = cost.get(key, 0)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                    prices = {}
                    break
                prices[key] = value
            # A zero price can be a real free tier, but automatic pricing must
            # not turn an unpriced preview into a free model. Require a positive
            # input or output list price; explicit user entries remain allowed.
            if not prices or not (prices["input"] > 0 or prices["output"] > 0):
                continue
            rows[model_id] = {
                "name": model.get("name") if isinstance(model.get("name"), str) else model_id,
                "provider": provider_id,
                "prices": prices,
                "release_date": model.get("release_date") if isinstance(model.get("release_date"), str) else None,
            }
            if len(rows) >= 500:
                return rows
    return rows


def sync_catalog(runtime_dir, force=False, fetcher=None, now=None):
    """Refresh at most daily; retain the last good catalogue on network errors."""
    path = Path(runtime_dir) / "model-catalog.json"
    previous = _read(path, {})
    now = time.time() if now is None else now
    synced_at = previous.get("synced_at")
    if not force and isinstance(synced_at, (int, float)) and now - synced_at < SYNC_INTERVAL:
        return {**catalog_status(runtime_dir), "status": "fresh", "added": 0, "updated": 0}
    try:
        if fetcher is None:
            request = urllib.request.Request(CATALOG_URL, headers={
                "User-Agent": "AgentMeter/0.9 (+local price estimates)",
                "Accept": "application/json",
            })
            with urllib.request.urlopen(request, timeout=15) as response:
                raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError("catalog_too_large")
            payload = json.loads(raw)
        else:
            payload = fetcher()
        if not isinstance(payload, dict):
            raise ValueError("invalid_catalog")
        rows = _catalog_rows(payload)
        if not rows:
            raise ValueError("empty_catalog")
        old = load_catalog(runtime_dir)
        added = sum(1 for key in rows if key not in old)
        updated = sum(1 for key, row in rows.items() if key in old and old[key] != row)
        from .collector import atomic_json
        atomic_json(path, {"synced_at": now, "models": rows, "last_error": None})
        return {**catalog_status(runtime_dir), "status": "updated", "added": added, "updated": updated}
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        # Do not replace good data with an error page or a partial download.
        if previous:
            previous["last_error"] = str(exc)[:160]
            from .collector import atomic_json
            atomic_json(path, previous)
        return {**catalog_status(runtime_dir), "status": "stale" if previous else "error",
                "added": 0, "updated": 0}
