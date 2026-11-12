"""Public USD/CNY market quotes and the local offline fallback."""

from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import threading

from .model import SourceError
from .transport import get_json

FX_FALLBACK = Decimal("7.25")
QUOTE_URL = "https://query1.finance.yahoo.com/v8/finance/chart/CNY%3DX?interval=1m&range=1d"
REFRESH_SECONDS = 300
MAX_LIVE_AGE = 900
CACHE_NAME = "usd-cny.json"
_lock = threading.Lock()
_attempted_at = {}


def _rate(value):
    if isinstance(value, bool):
        raise ValueError("invalid USD/CNY rate")
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("invalid USD/CNY rate") from None
    if not result.is_finite() or not 0 < result < 100:
        raise ValueError("invalid USD/CNY rate")
    return result


def rate_from(snapshot):
    """Old snapshots and offline fixtures use the same labeled fallback."""
    try:
        return _rate(snapshot["exchange_rate"]["usd_cny"])
    except (KeyError, TypeError, ValueError):
        return FX_FALLBACK


def fetch_quote(now):
    payload = get_json(QUOTE_URL, timeout=4, headers={"User-Agent": "Mozilla/5.0"})
    try:
        meta = payload["chart"]["result"][0]["meta"]
        if meta["symbol"] != "CNY=X" or meta["currency"] != "CNY":
            raise ValueError("unexpected currency pair")
        rate = _rate(meta["regularMarketPrice"])
        quoted_at = meta["regularMarketTime"]
        if type(quoted_at) is not int or not 0 < quoted_at <= now + 60:
            raise ValueError("invalid quote time")
    except (KeyError, IndexError, TypeError, ValueError):
        raise SourceError("invalid_exchange_rate_quote") from None
    return {"usd_cny": format(rate, "f"), "quoted_at": quoted_at,
            "fetched_at": now, "source": "yahoo_finance"}


def _read_cache(path):
    try:
        data = json.loads(path.read_text())
        _rate(data["usd_cny"])
        if data["source"] == "yahoo_finance" and type(data["quoted_at"]) is int \
                and type(data["fetched_at"]) in (float, int) \
                and 0 < data["quoted_at"] <= data["fetched_at"] + 60:
            return data
    except (OSError, KeyError, TypeError, ValueError):
        pass
    return None


def exchange_rate(runtime_dir, now, *, online=False):
    """Return one rate per snapshot. Only full online collection fetches quotes."""
    path = Path(runtime_dir).resolve() / CACHE_NAME
    quote = _read_cache(path)
    recent = quote and 0 <= now - quote["fetched_at"] < REFRESH_SECONDS
    if online and not recent:
        with _lock:
            last_attempt = _attempted_at.get(path)
            retry = last_attempt is None or not 0 <= now - last_attempt < REFRESH_SECONDS
            if retry:
                _attempted_at[path] = now
        if retry:
            try:
                fetched = fetch_quote(now)
            except SourceError:
                pass
            else:
                # A second process may have refreshed the same runtime during the request.
                latest = _read_cache(path) or quote
                if latest is None or fetched["quoted_at"] >= latest["quoted_at"]:
                    quote = fetched
                    from .collector import atomic_json
                    try:
                        atomic_json(path, quote)
                    except OSError:
                        pass
                else:
                    quote = latest
    if quote is None:
        return {"usd_cny": format(FX_FALLBACK, "f"), "source": "fallback",
                "status": "fallback", "quoted_at": None}
    live = (-60 <= now - quote["quoted_at"] < MAX_LIVE_AGE
            and 0 <= now - quote["fetched_at"] < REFRESH_SECONDS)
    return {**quote, "status": "live" if live else "cached"}
