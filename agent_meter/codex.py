from .model import SourceError, account_key, decimal_string, integer, metric, number, source, timestamp


def normalize_limits(payload, now):
    out = source("codex", "account", now)
    out["account_key"] = account_key("codex", payload.get("accountId"))
    buckets = payload.get("rateLimitsByLimitId")
    if buckets is None or buckets == {}:
        legacy = payload.get("rateLimits")
        if not isinstance(legacy, dict):
            raise SourceError("missing_rate_limits")
        buckets = {legacy.get("limitId") or "codex": legacy}
    if not isinstance(buckets, dict):
        raise SourceError("invalid_rate_limits")
    quotas, resets, credits = [], [], []
    for bucket_id, raw in buckets.items():
        if not isinstance(raw, dict):
            raise SourceError("invalid_rate_limits")
        for window in ("primary", "secondary"):
            value = raw.get(window)
            if value is None:
                continue
            used = number(value.get("usedPercent"))
            reset = timestamp(value.get("resetsAt"))
            row = {"bucket": bucket_id, "window": window, "used_percent": used,
                   "remaining_percent": max(0, 100 - used),
                   "window_minutes": integer(value.get("windowDurationMins"), optional=True),
                   "resets_at": reset}
            quotas.append(row)
            if reset is not None:
                resets.append({"bucket": bucket_id, "window": window, "resets_at": reset})
        value = raw.get("credits")
        if isinstance(value, dict):
            credits.append({"bucket": bucket_id, "balance": decimal_string(value.get("balance"), optional=True, allow_negative=True),
                            "unit": "provider_credits", "unlimited": value.get("unlimited"),
                            "has_credits": value.get("hasCredits")})
    out["metrics"]["quota"] = metric(quotas or None)
    out["metrics"]["reset_time"] = metric(resets or None)
    out["metrics"]["credits"] = metric(credits or None)
    summary = payload.get("rateLimitResetCredits")
    if summary is not None:
        count = integer(summary.get("availableCount"))
        details = summary.get("credits")
        cards = None
        if details is not None:
            if not isinstance(details, list):
                raise SourceError("invalid_reset_cards")
            cards = []
            for card in details:
                status = card.get("status")
                if status not in {"available", "redeeming", "redeemed", "unknown"}:
                    raise SourceError("invalid_reset_card_status")
                expiry = timestamp(card.get("expiresAt"))
                cards.append({"status": status, "reset_type": card.get("resetType"),
                              "granted_at": timestamp(card.get("grantedAt")), "expires_at": expiry,
                              "expiration_state": "no_expiry_reported" if expiry is None else
                              ("expired" if expiry["epoch_seconds"] <= now else "active")})
        eligible = [c["expires_at"] for c in cards or [] if c["status"] == "available"
                    and c["expires_at"] is not None and c["expires_at"]["epoch_seconds"] > now]
        value = {"available_count": count, "cards": cards,
                 "details_state": "unknown" if cards is None else ("truncated" if len(cards) < count else "returned"),
                 "next_known_expiry": min(eligible, key=lambda x: x["epoch_seconds"]) if eligible else None}
        out["metrics"]["reset_cards"] = metric(value)
    # Backend permission is separate from quota percentages.
    out["ordinary_usage_allowed"] = payload.get("ordinaryUsageAllowed")
    return out


def normalize_usage(payload):
    summary = payload.get("summary")
    days = payload.get("dailyUsageBuckets")
    value = {"lifetime_tokens": integer(summary.get("lifetimeTokens"), optional=True) if isinstance(summary, dict) else None,
             "daily_buckets": None, "coverage": "provider_account_activity_not_local_logs"}
    if days is not None:
        if not isinstance(days, list):
            raise SourceError("invalid_usage_buckets")
        value["daily_buckets"] = []
        from datetime import date
        for day in days:
            try:
                date.fromisoformat(day["startDate"])
            except (ValueError, KeyError, TypeError):
                raise SourceError("invalid_usage_date") from None
            value["daily_buckets"].append({"date": day["startDate"], "tokens": integer(day.get("tokens"))})
    return metric(value if value["lifetime_tokens"] is not None or days is not None else None)


def collect_codex(binary, now, timeout=20, cwd=None, rpc_factory=None):
    if rpc_factory is None:
        from .transport import CodexRPC
        rpc_factory = CodexRPC
    with rpc_factory(binary, timeout=timeout, cwd=cwd) as rpc:
        # false avoids fallback exposure or any credit redemption.
        limits = rpc.call("account/rateLimits/read", {"excludeResetCreditDetails": False, "supportsLunaReserve": False})
        out = normalize_limits(limits, now)
        try:
            out["metrics"]["tokens"] = normalize_usage(rpc.call("account/usage/read", {}))
        except SourceError as e:
            out["metrics"]["tokens"] = metric(status="error", reason=e.code)
            out["status"] = "partial"
        return out
