"""Optional local price table for API-equivalent cost estimates (USD/CNY).

The CC Switch source already reports its own USD estimates; this module adds
estimates for the direct local token sources that have none. Prices are per
1M tokens: input (fresh), cache read, cache write, output. Defaults come
from the pricing surveys (docs/pricing-survey-2026-10-09.md and its
2026-10-15 update), taking the official list price in whichever currency
published one; the other currency falls back to an FX conversion at 7.25,
flagged as converted (USD-only models convert into CNY, domestic CNY-only
models convert into USD). Every value is user-editable via PUT /v1/prices;
user entries override defaults by pattern. Estimates are never bills:
订阅套餐内的调用不按 API 价计费.

Matching (2026-10-15) normalizes both sides first — see normalize_model —
so the same model is priced no matter which prefix or separator spelling a
reader stores. Only published prices are shipped: a model with no known
list price stays unmatched (unknown ≠ zero) and is named in the estimate's
unmatched_models so the user can add it in the price table.
"""
import json
import re
from decimal import Decimal
from pathlib import Path

from .model import SourceError, metric
from .model_catalog import load_catalog
from .peak import WINDOW

# Built-in fallback: per-1M price (input, cache_read, cache_write, output).
# The live catalogue refreshes these without replacing user overrides.
DEFAULTS_USD = {
    "glm-5.3-flash": (0.15, 0.03, 0, 0.50),
    "glm-5.3": (1.40, 0.26, 0, 4.40),
    "k3": (3.00, 0.30, 3.00, 15.00),
    "kimi-k3.1-pro": (2.00, 0.20, 2.00, 10.00),
    "kimi-k3.1-pro-highspeed": (4.00, 0.20, 4.00, 20.00),
    "kimi-k2.7-code": (0.95, 0.19, 0, 4.00),
    "kimi-k2.7-code-highspeed": (1.90, 0.38, 0, 8.00),
    "kimi-k2.6": (0.95, 0.16, 0, 4.00),
    "gpt-6.1-sol": (2.00, 0.10, 2.50, 10.00),
    "gpt-6-sol": (2.00, 0.20, 2.50, 10.00),
    "gpt-6-luna": (0.10, 0.01, 0.125, 0.50),
    "gpt-6-astra": (10.00, 1.00, 12.50, 50.00),
    "deepseek-v4-pro": (0.66, 0.022, 0, 1.98),
    "deepseek-v4.1-flash": (0.15, 0.003, 0, 0.60),
    "deepseek-v4-flash": (0.15, 0.003, 0, 0.60),
    "deepseek-flash": (0.15, 0.003, 0, 0.60),
    "gemini-3.7-flash": (0.75, 0.075, 0, 3.75),
    "gemini-3.8-flash": (0.75, 0.075, 0, 3.75),
    "gemini-3.6-flash": (0.75, 0.075, 0, 3.75),
    "gemini-3-flash": (0.50, 0.05, 0, 3.00),
    "gemini-3.1-pro": (2.00, 0.20, 0, 12.00),
    "gemini-4-argon": (2.00, 0.10, 0, 10.00),
    "claude-opus-5-5": (4, 0.20, 5.00, 20),
    "claude-sonnet-5-5": (2, 0.10, 2.50, 10),
    "claude-haiku-5-5": (0.10, 0.01, 0.125, 0.50),
    "claude-opus-5": (5, 0.50, 6.25, 25),
    "claude-opus-4-8": (5, 0.50, 6.25, 25),
    "claude-fable-5": (10, 1.00, 12.50, 50),
    "claude-fable-5-1": (10, 0.25, 12.50, 50),
    "claude-mythos-5": (10, 1.00, 12.50, 50),
    "claude-mythos-5-1": (10, 0.25, 12.50, 50),
    "gpt-5.3-codex": (1.75, 0.175, 0, 14.00),
    "glm-5.3-flashx": (0.37, 0.075, 0, 1.25),
    "minimax-m2.7": (0.30, 0.06, 0.375, 1.20),
    "mimo-v2.6-pro": (0.435, 0.0036, 0, 0.87),
    "mimo-v2.6-pro-ultraspeed": (4.35, 0.036, 0, 8.70),
    "mimo-v2.6-flash": (0.14, 0.0028, 0, 0.28),
    "step-3.7-flash": (0.20, 0.04, 0, 1.15),
    "claude-sonnet-5": (2, 0.20, 2.50, 10),
    "claude-haiku-5": (0.10, 0.01, 0.125, 0.50),
    "claude-haiku-4-5": (1, 0.10, 1.25, 5),
    "mimo-v2.5-pro": (0.435, 0.0036, 0, 0.87),
    "minimax-m3": (0.30, 0.06, 0, 1.20),
    "minimax-m3.1-flash": (0.15, 0.015, 0, 0.60),
}
# CN list prices where published; the rest are USD x 7.25 (flagged converted).
# The 2026-10-15 additions are official CNY list prices with no official USD
# rate (Hunyuan Hy4/Hy3, Step 5 Preview, MiMo v2.6-flash); USD tables get them
# back at 1/7.25, flagged as converted.
DEFAULTS_CNY_PUBLISHED = {
    "glm-5.3-flash": (0.8, 0.23, 0, 2.8),
    "glm-5.3": (8, 2, 0, 28),
    "glm-5.3-flashx": (2, 0.57, 0, 7),
    "mimo-v2.5-pro": (3, 0.025, 0, 6),
    "hy4-preview": (6, 0.3, 0, 18),
    "hy3": (1, 0.25, 0, 4),
    "step-5-preview": (7, 0.7, 0, 20),
    "step-3.7-flash": (1.35, 0.27, 0, 8.1),
    "mimo-v2.6-pro": (3, 0.025, 0, 6),
    "mimo-v2.6-pro-ultraspeed": (30, 0.25, 0, 60),
    "mimo-v2.6-flash": (1, 0.02, 0, 2),
    "minimax-m3": (2.10, 0.42, 0, 8.40),
    "minimax-m2.7-highspeed": (4.2, 0.42, 2.625, 16.8),
    "minimax-m3.1-flash": (1, 0.1, 0, 4),
}
FX_FALLBACK = Decimal("7.25")
PRICE_KEYS = ("input", "cache_read", "cache_write", "output")
CURRENCIES = {"USD", "CNY"}
# DeepSeek's peak rate is 2x its list price during Beijing weekday
# 09:00-12:00 and 14:00-18:00 (weekends are off-peak all day). The table's
# prices are the off-peak base; peak-multiplier models use the same ratio on
# every component.
PEAK_PATTERNS = ("deepseek-v4-pro", "deepseek-v4.1-flash", "deepseek-v4-flash", "deepseek-flash")
PEAK_MULTIPLIER = 2.0
MAX_PEAK_MULTIPLIER = 10.0


def normalize_model(name):
    """Match key for a model id: vendor prefix dropped, dot/dash unified.

    The same model is spelled differently per reader — ZCode stores
    "account:bigmodel-coding-plan/GLM-5.3-Flash", Kimi "kimi-code/k3",
    OpenCode "custom_provider:deepseek/deepseek-v4-flash", WorkBuddy
    "glm-5-3-flash" — while vendors publish one id. The part after the last
    "/" is the vendor's own model id, and "-" and "." are used
    interchangeably inside it (glm-5.3-flash vs glm-5-3-flash), so both are
    unified here. The snapshot keeps the raw name; only matching normalizes.
    """
    if not isinstance(name, str):
        return ""
    tail = name.rsplit("/", 1)[-1].strip().lower()
    return tail.replace(".", "-")


def default_peak_multipliers():
    """Built-in peak multipliers: DeepSeek 2x, every other model 1x."""
    return {pattern: PEAK_MULTIPLIER for pattern in PEAK_PATTERNS}


def default_prices(currency):
    if currency == "CNY":
        converted = {p: tuple(round(Decimal(v) * FX_FALLBACK, 4) for v in prices)
                     for p, prices in DEFAULTS_USD.items() if p not in DEFAULTS_CNY_PUBLISHED}
        table = dict(DEFAULTS_CNY_PUBLISHED)
        table.update({p: tuple(float(v) for v in prices) for p, prices in converted.items()})
        return table
    # USD mirrors the CNY rule: a domestic model with only a CNY list price
    # converts back at 1/FX and is flagged, instead of staying unpriced.
    converted = {p: tuple(float(round(Decimal(v) / FX_FALLBACK, 4)) for v in prices)
                 for p, prices in DEFAULTS_CNY_PUBLISHED.items() if p not in DEFAULTS_USD}
    return {**{p: prices for p, prices in DEFAULTS_USD.items()}, **converted}


def converted_patterns(currency):
    """Entries that are pure FX conversions of the other currency's list."""
    if currency == "CNY":
        return set(DEFAULTS_USD) - set(DEFAULTS_CNY_PUBLISHED)
    return set(DEFAULTS_CNY_PUBLISHED) - set(DEFAULTS_USD)


def _clean_peak_multipliers(value):
    """Validate {pattern: multiplier}; 0 < multiplier <= 10, bools rejected."""
    if not isinstance(value, dict):
        raise ValueError("invalid_peak_multiplier")
    clean = {}
    for pattern, multiplier in value.items():
        if not isinstance(pattern, str) or not 0 < len(pattern.strip()) <= 120:
            raise ValueError("invalid_peak_multiplier")
        if isinstance(multiplier, bool) or not isinstance(multiplier, (int, float)) \
                or not 0 < multiplier <= MAX_PEAK_MULTIPLIER:
            raise ValueError("invalid_peak_multiplier")
        clean[pattern.strip()] = float(multiplier)
    return clean


class PriceTable:
    def __init__(self, currency, user_models, converted, aliases=None, runtime_dir=None,
                 peak_multipliers=None):
        self.currency = currency
        self.catalog = load_catalog(runtime_dir) if runtime_dir else {}
        # A live catalogue row is a USD price; converting it into CNY would
        # overwrite a domestic model's officially published CNY list. Keep the
        # official CNY default in charge and let only USD-only models convert.
        published_cny = {normalize_model(p) for p in DEFAULTS_CNY_PUBLISHED} if currency == "CNY" else set()
        synced = {}
        for model_id, item in self.catalog.items():
            if normalize_model(model_id) in published_cny:
                continue
            values = tuple((item.get("prices") or {}).get(key, 0) for key in PRICE_KEYS)
            if currency == "CNY":
                values = tuple(float(round(Decimal(v) * FX_FALLBACK, 4)) for v in values)
            synced[model_id] = values
        self.synced_patterns = set(synced)
        self.models = {**default_prices(currency), **synced, **(user_models or {})}
        self.aliases = dict(aliases or {})
        self.index = {}
        for pattern in self.models:
            key = normalize_model(pattern)
            if key:
                self.index[key] = pattern
        self.converted = ((converted_patterns(currency) | (self.synced_patterns if currency == "CNY" else set()))
                          - set(user_models or {}))
        # Saved user overrides keep their spelling; matching normalizes both
        # sides the same way model matching does.
        self.peak_overrides = _clean_peak_multipliers(peak_multipliers or {})
        self.peak_multipliers = {pattern: self.peak_multiplier_for(pattern) for pattern in self.models}

    def peak_multiplier_for(self, pattern):
        """Effective peak multiplier: user override, then the built-in defaults."""
        key = normalize_model(pattern)
        for saved, value in self.peak_overrides.items():
            if normalize_model(saved) == key:
                return value
        for default_pattern in PEAK_PATTERNS:
            if normalize_model(default_pattern) == key:
                return PEAK_MULTIPLIER
        return 1.0

    def match(self, model):
        """Exact user binding first, then longest catalogue/local pattern."""
        key = normalize_model(model)
        if not key:
            return None
        bound = self.aliases.get(key)
        if bound and normalize_model(bound) != key:
            target_key = normalize_model(bound)
            if target_key in self.index:
                return self.index[target_key]
            for candidate in self.index:
                if candidate in target_key:
                    return self.index[candidate]
        if key in self.index:
            return self.index[key]
        best = None
        for candidate in self.index:
            if candidate in key and (best is None or len(candidate) > len(best)):
                best = candidate
        return self.index[best] if best is not None else None

    def binding_for(self, model):
        target = self.aliases.get(normalize_model(model))
        return target if target and self.match(model) else None

    def cost_for(self, group, pattern, peak=False):
        """Decimal cost of one {fresh_input, cache_read, cache_write, output} group.

        peak=True bills the group at the pattern's peak multiplier; the table
        prices themselves are the off-peak base (peak=False).
        """
        prices = dict(zip(PRICE_KEYS, self.models[pattern]))
        multiplier = Decimal(str(self.peak_multipliers.get(pattern, 1.0))).normalize() \
            if peak else Decimal(1)
        values = {"input": group.get("fresh_input") or 0, "cache_read": group.get("cache_read") or 0,
                  "cache_write": group.get("cache_write") or 0, "output": group.get("output") or 0}
        total = Decimal(0)
        for key, tokens in values.items():
            total += Decimal(str(tokens)) * Decimal(str(prices[key])) * multiplier / Decimal(1000000)
        return total


def _clean_aliases(value):
    if not isinstance(value, dict):
        return {}
    clean = {}
    for model, target in value.items():
        if not isinstance(model, str) or not isinstance(target, str):
            raise ValueError("invalid_model_binding")
        model, target = model.strip(), target.strip()
        key = normalize_model(model)
        if not key or not target or len(model) > 120 or len(target) > 120 or normalize_model(target) == key:
            raise ValueError("invalid_model_binding")
        clean[key] = target
    return clean


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
        return PriceTable(data["currency"], models, set(data.get("converted", [])),
                          _clean_aliases(data.get("aliases", {})), runtime_dir,
                          peak_multipliers=_clean_peak_multipliers(data.get("peak_multipliers", {})))
    except (OSError, ValueError, json.JSONDecodeError):
        return PriceTable("USD", {}, set(), runtime_dir=runtime_dir)


def save_prices(runtime_dir, currency, models, aliases=None, peak_multipliers=None):
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
    path = Path(runtime_dir) / "prices.json"
    if aliases is None:
        aliases = _clean_aliases(_read_existing(path, "aliases", {}))
    else:
        aliases = _clean_aliases(aliases)
    # None keeps whatever overrides the file already holds (legacy callers).
    if peak_multipliers is None:
        try:
            peak_multipliers = _clean_peak_multipliers(_read_existing(path, "peak_multipliers", {}))
        except ValueError:
            peak_multipliers = {}
    else:
        try:
            peak_multipliers = _clean_peak_multipliers(peak_multipliers)
        except ValueError:
            raise SourceError("invalid_peak_multiplier") from None
    from .collector import atomic_json
    payload = {"currency": currency, "models": clean, "aliases": aliases,
               "peak_multipliers": peak_multipliers,
               "converted": sorted(converted_patterns(currency) & set(clean))}
    atomic_json(path, payload)
    return {"currency": currency, "models": clean, "aliases": aliases,
            "peak_multipliers": peak_multipliers}


def _read_existing(path, key, default):
    try:
        data = json.loads(Path(path).read_text())
        return data.get(key, default) if isinstance(data, dict) else default
    except (OSError, ValueError, json.JSONDecodeError):
        return default


def estimate_source_cost(tokens_metric, table):
    """Fill a cost metric from a tokens metric's per-period groups.

    Each period carries the period total, a per-model amount map (so the UI
    can show what each model cost) and the names of models that matched no
    pattern. A group with both a "peak" and an "offpeak" token object is
    billed at the peak multiplier for the peak part and at the base price for
    the off-peak part; a group that was never split stays at the off-peak
    base price and its model is named in unsplit_models. The per-model peak
    and off-peak amount maps (same keys as models) let the UI show only one
    vendor's models (DeepSeek is the only peak-multiplier vendor). Sources
    without a per-model breakdown cannot be priced and stay not_provided.
    Returns the cost metric, or None when nothing matched.
    """
    value = tokens_metric.get("value") if isinstance(tokens_metric, dict) else None
    periods = value.get("periods") if isinstance(value, dict) else None
    if not isinstance(periods, dict):
        return None
    out_periods = {}
    unmatched_all = set()
    bound_all = {}
    any_group = False
    for period, data in periods.items():
        groups = data.get("groups") if isinstance(data, dict) else None
        if not isinstance(groups, list) or not groups:
            out_periods[period] = {"amount": "0", "models": {}, "unmatched_models": [],
                                   "bound_models": {}, "peak_amount": "0",
                                   "offpeak_amount": "0", "unsplit_models": [],
                                   "peak_models": {}, "offpeak_models": {}}
            continue
        total = Decimal(0)
        peak_total = Decimal(0)
        offpeak_total = Decimal(0)
        models = {}
        peak_models = {}
        offpeak_models = {}
        unmatched = set()
        unsplit = set()
        bound = {}
        for group in groups:
            model = str(group.get("model", ""))
            pattern = table.match(model)
            split = isinstance(group.get("peak"), dict) and isinstance(group.get("offpeak"), dict)
            breakdown = "fresh_input" in group or (split and any(
                "fresh_input" in part for part in (group["peak"], group["offpeak"])))
            if pattern is None or not breakdown:
                unmatched.add(model + ("" if breakdown else " (no breakdown)"))
                continue
            any_group = True
            if split:
                peak_part = table.cost_for(group["peak"], pattern, peak=True)
                offpeak_part = table.cost_for(group["offpeak"], pattern)
            else:
                peak_part = Decimal(0)
                offpeak_part = table.cost_for(group, pattern)
                unsplit.add(model)
            amount = peak_part + offpeak_part
            peak_total += peak_part
            offpeak_total += offpeak_part
            total += amount
            models[model] = models.get(model, Decimal(0)) + amount
            if peak_part:
                peak_models[model] = (peak_models.get(model, Decimal(0)) + peak_part).normalize()
            if offpeak_part:
                offpeak_models[model] = (offpeak_models.get(model, Decimal(0)) + offpeak_part).normalize()
            target = table.binding_for(model)
            if target:
                bound[model] = target
        unmatched_all |= unmatched
        bound_all.update(bound)
        out_periods[period] = {"amount": format(total, "f"),
                               "peak_amount": format(peak_total, "f"),
                               "offpeak_amount": format(offpeak_total, "f"),
                               "models": {name: format(amount, "f") for name, amount in models.items()},
                               "peak_models": {name: format(amount, "f") for name, amount in peak_models.items()},
                               "offpeak_models": {name: format(amount, "f") for name, amount in offpeak_models.items()},
                               "unmatched_models": sorted(unmatched),
                               "unsplit_models": sorted(unsplit), "bound_models": bound}
    if not any_group:
        return None
    status = "partial" if unmatched_all else "available"
    peaks = {pattern: multiplier for pattern, multiplier in table.peak_multipliers.items()
             if multiplier != 1}
    return metric({"unit": table.currency, "kind": "estimate", "basis": "local_price_table",
                   "fx_note": "converted_at_7.25" if table.currency == "CNY" and table.converted else None,
                   "bound_models": bound_all, "peak_window": WINDOW,
                   "peak_multipliers": peaks, "periods": out_periods}, status=status)
