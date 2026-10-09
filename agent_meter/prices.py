"""Optional local price table for API-equivalent cost estimates (USD/CNY).

The CC Switch source already reports its own USD estimates; this module adds
estimates for the direct local token sources that have none. Prices are per
1M tokens: input (fresh), cache read, cache write, output. Defaults come
from the 2026-10-09 pricing survey (docs/pricing-survey-2026-10-09.md):
CN list prices where published, otherwise USD list prices; CNY fallbacks
for USD-only models are converted at 7.25 and flagged as converted. Every
value is user-editable via PUT /v1/prices; user entries override defaults
by pattern. Estimates are never bills: 订阅套餐内的调用不按 API 价计费.
"""
import json
from decimal import Decimal
from pathlib import Path

from .model import SourceError, decimal_string, metric

# pattern -> per-1M price (input, cache_read, cache_write, output)
DEFAULTS_USD = {
    "glm-5.3-flash": (0.15, 0.03, 0, 0.50),
    "glm-5.3": (1.10, 0, 0, 3.90),
    "k3": (3.00, 0.30, 0, 15.00),
    "deepseek-v4-pro": (0.66, 0.022, 0, 1.98),
    "deepseek-v4.1-flash": (0.15, 0.003, 0, 0.60),
    "deepseek-v4-flash": (0.15, 0.003, 0, 0.60),
    "deepseek-flash": (0.15, 0.003, 0, 0.60),
    "gemini-3.7-flash": (0.75, 0.075, 0, 3.75),
    "gemini-3.8-flash": (0.75, 0.075, 0, 3.75),
    "gemini-3-flash": (0.30, 0.075, 0, 2.50),
    "gemini-3.1-pro": (2.00, 0.50, 0, 12.00),
    "claude-opus-5-5": (4, 0.20, 0, 20),
    "claude-opus-5": (5, 0.50, 0, 25),
    "claude-sonnet-5": (2, 0.10, 0, 10),
    "claude-haiku-5": (0.10, 0.01, 0, 0.50),
    "claude-haiku-4-5": (1, 0.10, 0, 5),
    "mimo-v2.5-pro": (0.435, 0.0036, 0, 0.87),
    "minimax-m3": (0.30, 0, 0, 1.20),
}
# CN list prices where published; the rest are USD x 7.25 (flagged converted).
DEFAULTS_CNY_PUBLISHED = {
    "glm-5.3-flash": (0.8, 0.23, 0, 2.8),
    "glm-5.3": (8, 0, 0, 28),
    "mimo-v2.5-pro": (3, 0.025, 0, 6),
}
FX_FALLBACK = Decimal("7.25")
PRICE_KEYS = ("input", "cache_read", "cache_write", "output")
CURRENCIES = {"USD", "CNY"}


def default_prices(currency):
    if currency == "CNY":
        converted = {p: tuple(round(Decimal(v) * FX_FALLBACK, 4) for v in prices)
                     for p, prices in DEFAULTS_USD.items() if p not in DEFAULTS_CNY_PUBLISHED}
        table = dict(DEFAULTS_CNY_PUBLISHED)
        table.update({p: tuple(float(v) for v in prices) for p, prices in converted.items()})
        return table
    return {p: prices for p, prices in DEFAULTS_USD.items()}


def converted_patterns():
    """CNY entries that are pure FX conversions of USD list prices."""
    return set(DEFAULTS_USD) - set(DEFAULTS_CNY_PUBLISHED)


class PriceTable:
    def __init__(self, currency, user_models, converted):
        self.currency = currency
        self.models = dict(default_prices(currency))
        self.models.update(user_models or {})
        # CNY entries that are pure FX conversions (unless the user edited them).
        self.converted = (converted_patterns() - set(user_models or {})) if currency == "CNY" else set()

    def match(self, model):
        """Longest matching pattern (exact first, then substring), or None."""
        name = model.lower()
        if name in self.models:
            return name
        best = None
        for pattern in self.models:
            if pattern in name and (best is None or len(pattern) > len(best)):
                best = pattern
        return best

    def cost_for(self, group, pattern):
        """Decimal cost of one {fresh_input, cache_read, cache_write, output} group."""
        prices = dict(zip(PRICE_KEYS, self.models[pattern]))
        values = {"input": group.get("fresh_input") or 0, "cache_read": group.get("cache_read") or 0,
                  "cache_write": group.get("cache_write") or 0, "output": group.get("output") or 0}
        total = Decimal(0)
        for key, tokens in values.items():
            total += Decimal(str(tokens)) * Decimal(str(prices[key])) / Decimal(1000000)
        return total


def load_prices(runtime_dir):
    path = Path(runtime_dir) / "prices.json"
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict) or data.get("currency") not in CURRENCIES \
                or not isinstance(data.get("models"), dict):
            raise ValueError()
        models = {}
        for pattern, prices in data["models"].items():
            if not isinstance(pattern, str) or not 0 < len(pattern) <= 120 or not isinstance(prices, dict):
                raise ValueError()
            clean = {}
            for key in PRICE_KEYS:
                value = prices.get(key, 0)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                    raise ValueError()
                clean[key] = value
            models[pattern] = tuple(clean[k] for k in PRICE_KEYS)
        return PriceTable(data["currency"], models, set(data.get("converted", [])))
    except (OSError, ValueError, json.JSONDecodeError):
        return PriceTable("USD", {}, set())


def save_prices(runtime_dir, currency, models):
    if currency not in CURRENCIES:
        raise SourceError("invalid_price_currency")
    clean = {}
    for pattern, prices in models.items():
        if not isinstance(pattern, str) or not 0 < len(pattern) <= 120 or not isinstance(prices, dict):
            raise SourceError("invalid_price_table")
        row = {}
        for key in PRICE_KEYS:
            value = prices.get(key, 0)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise SourceError("invalid_price_table")
            row[key] = value
        clean[pattern] = row
    from .collector import atomic_json
    payload = {"currency": currency, "models": clean,
               "converted": sorted(converted_patterns() & set(clean)) if currency == "CNY" else []}
    atomic_json(Path(runtime_dir) / "prices.json", payload)
    return {"currency": currency, "models": clean}


def estimate_source_cost(tokens_metric, table):
    """Fill a cost metric from a tokens metric's per-period groups.

    Sources without a per-model breakdown cannot be priced and stay
    not_provided. Returns the cost metric, or None when nothing matched.
    """
    value = tokens_metric.get("value") if isinstance(tokens_metric, dict) else None
    periods = value.get("periods") if isinstance(value, dict) else None
    if not isinstance(periods, dict):
        return None
    out_periods = {}
    unmatched_all = set()
    any_group = False
    for period, data in periods.items():
        groups = data.get("groups") if isinstance(data, dict) else None
        if not isinstance(groups, list) or not groups:
            # A period with no rows (e.g. archive-only history has no today)
            # simply costs nothing; it does not block the other periods.
            out_periods[period] = {"amount": "0", "unmatched_models": []}
            continue
        total = Decimal(0)
        unmatched = set()
        for group in groups:
            model = str(group.get("model", ""))
            pattern = table.match(model)
            if pattern is None or "fresh_input" not in group:
                # No price, or no per-component breakdown (e.g. Kimi totals):
                # both stay unpriced rather than costing zero.
                unmatched.add(model + ("" if "fresh_input" in group else " (no breakdown)"))
                continue
            any_group = True
            total += table.cost_for(group, pattern)
        unmatched_all |= unmatched
        out_periods[period] = {"amount": format(total, "f"), "unmatched_models": sorted(unmatched)}
    if not any_group:
        return None
    status = "partial" if unmatched_all else "available"
    return metric({"unit": table.currency, "kind": "estimate", "basis": "local_price_table",
                   "fx_note": "converted_at_7.25" if table.currency == "CNY" and table.converted else None,
                   "periods": out_periods}, status=status)
