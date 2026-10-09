"""即梦 account data observed by the menu bar app on 即梦's own web page.

The app loads the logged-in page in a hidden web view; the page makes its
own requests (subscription/user_info, benefits/user_credit) and the app keeps
an allowlisted subset of fields. Nothing here signs, replays or forges any
request. Observations arrive via PUT /v1/observations, live only in memory
and are merged into the CLI 即梦 source when the account fingerprint matches.
"""
import copy
import re
from datetime import datetime

from .billing import countdown, renewal_date
from .model import failed_source, DISPLAY_ZONE, SourceError, decimal_string, metric, source, timestamp

MAX_OBSERVATIONS = 5
MAX_AGE_SECONDS = 6 * 3600
ACCOUNT_KEY = re.compile(r"^[0-9a-f]{24}$")
CREDIT_KINDS = {"vip", "gift", "purchase"}


def _int(value, allow_zero=True):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or (value == 0 and not allow_zero):
        raise ValueError("invalid integer")
    return value


def _epoch(value):
    """Epoch seconds, or None for 0/absent (the page uses 0 for 'none')."""
    if value in (None, 0):
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 1_000_000_000 <= value <= 4_000_000_000:
        raise ValueError("invalid epoch")
    return value


def _text(value, limit=40):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > limit or "\n" in value:
        raise ValueError("invalid text")
    return value


def validate_observations(payload):
    """{"dreamina": [observation, ...]} → clean dict, or ValueError."""
    if not isinstance(payload, dict) or set(payload) - {"dreamina"}:
        raise ValueError("unknown observation source")
    items = payload.get("dreamina") or []
    if not isinstance(items, list) or len(items) > MAX_OBSERVATIONS:
        raise ValueError("invalid observation list")
    clean = []
    for item in items:
        if not isinstance(item, dict) or set(item) - {"account_key", "label", "observed_at", "credit", "subscription", "failed"}:
            raise ValueError("unknown observation field")
        if item.get("failed") is not None and item["failed"] is not True:
            raise ValueError("invalid flag")
        key = item.get("account_key")
        if key is not None and (not isinstance(key, str) or not ACCOUNT_KEY.match(key)):
            raise ValueError("invalid account key")
        out = {"account_key": key, "label": _text(item.get("label")), "observed_at": _epoch(item.get("observed_at"))}
        if out["observed_at"] is None:
            raise ValueError("observed_at required")
        if item.get("failed"):
            # The page gave no data for this login (expired session or timeout).
            if item.get("credit") is not None or item.get("subscription") is not None:
                raise ValueError("failed observation with data")
            out["failed"] = True
            clean.append(out)
            continue
        credit = item.get("credit")
        if credit is not None:
            if not isinstance(credit, dict) or set(credit) - {"gift", "purchase", "vip", "details"}:
                raise ValueError("invalid credit")
            details = []
            for d in credit.get("details") or []:
                if not isinstance(d, dict) or set(d) - {"kind", "balance", "expires_at", "level"} or d.get("kind") not in CREDIT_KINDS:
                    raise ValueError("invalid credit detail")
                details.append({"kind": d["kind"], "balance": _int(d.get("balance")),
                                "expires_at": _epoch(d.get("expires_at")), "level": _text(d.get("level"))})
            out["credit"] = {k: _int(credit.get(k)) for k in ("gift", "purchase", "vip")}
            out["credit"]["details"] = details[:20]
        sub = item.get("subscription")
        if sub is not None:
            allowed = {"level", "end_time", "next_renewal_time", "is_cancel_subscribe", "cycle_unit", "subscribe_cycle"}
            if not isinstance(sub, dict) or set(sub) - allowed:
                raise ValueError("invalid subscription")
            cancel = sub.get("is_cancel_subscribe")
            if cancel is not None and not isinstance(cancel, bool):
                raise ValueError("invalid flag")
            cycle = sub.get("subscribe_cycle")
            out["subscription"] = {"level": _text(sub.get("level")), "end_time": _epoch(sub.get("end_time")),
                                   "next_renewal_time": _epoch(sub.get("next_renewal_time")),
                                   "is_cancel_subscribe": cancel, "cycle_unit": _text(sub.get("cycle_unit"), 20),
                                   "subscribe_cycle": None if cycle is None else _int(cycle)}
        clean.append(out)
    return {"dreamina": clean}


def _day(epoch):
    return datetime.fromtimestamp(epoch, DISPLAY_ZONE).date().isoformat()


def apply_observation(src, obs, now):
    """Adds web-only detail to a 即梦 source (CLI-based or a bare one)."""
    out = copy.deepcopy(src)
    age = now - obs["observed_at"]
    stale = age > MAX_AGE_SECONDS
    status = "stale" if stale else "available"
    credit = obs.get("credit")
    if credit:
        total = credit["gift"] + credit["purchase"] + credit["vip"]
        buckets = [{"type": d["kind"], "balance": decimal_string(d["balance"]),
                    "expires_at": timestamp(d["expires_at"]) if d["expires_at"] else None}
                   for d in credit["details"] if d["balance"] > 0]
        if credit["purchase"] > 0 and not any(b["type"] == "purchase" for b in buckets):
            buckets.append({"type": "purchase", "balance": decimal_string(credit["purchase"]), "expires_at": None})
        previous = (out["metrics"]["credits"].get("value") or {}) if out["metrics"]["credits"]["status"] == "available" else {}
        out["metrics"]["credits"] = metric({
            "balance": previous.get("balance") or decimal_string(total), "unit": "dreamina_credits",
            "web_total": decimal_string(total),
            "split": {k: decimal_string(credit[k]) for k in ("vip", "gift", "purchase")},
            "buckets": buckets}, status=status if not previous else out["metrics"]["credits"]["status"])
    sub = obs.get("subscription")
    if sub:
        auto = True if sub["next_renewal_time"] else (False if sub["is_cancel_subscribe"] else None)
        out["subscription"] = {"plan": sub["level"] or (out.get("subscription") or {}).get("plan"),
                               "ends_on": _day(sub["end_time"]) if sub["end_time"] else None,
                               "auto_renew": auto, "cycle_unit": sub["cycle_unit"], "subscribe_cycle": sub["subscribe_cycle"]}
        if sub["next_renewal_time"]:
            target = renewal_date(_day(sub["next_renewal_time"]))
            out["metrics"]["renewal_time"] = metric(target, status=status)
            out["metrics"]["renewal_countdown"] = metric(countdown(target, now), status=status)
        else:
            reason = "dreamina_subscription_cancelled" if sub["is_cancel_subscribe"] else "dreamina_no_scheduled_renewal"
            for name in ("renewal_time", "renewal_countdown"):
                out["metrics"][name] = metric(reason=reason)
    out["diagnostics"]["web_observed_at"] = timestamp(obs["observed_at"])
    out["diagnostics"]["web_transport"] = "dreamina_page_observation"
    return out


def merge_dreamina(sources, observations, now):
    """Observations arrive one per 即梦 login, in login order, and keep that
    order as ids ("dreamina", "dreamina#2"…) — the app maps cards back to
    logins by it. The first login enriches the CLI source when it is the same
    account; a login whose page gave no data keeps its place as not connected."""
    items = (observations or {}).get("dreamina") or []
    if not items:
        return sources
    sources = list(sources)
    index = next((i for i, s in enumerate(sources) if s["id"] == "dreamina"), None)
    cli = sources[index] if index is not None else None
    # A working CLI source for another account keeps "dreamina"; web logins then start at #2.
    shift = int(cli is not None and cli["status"] not in {"error", "not_connected"}
                and cli.get("account_key") is not None and cli.get("account_key") != items[0].get("account_key"))
    for n, obs in enumerate(items):
        position = n + shift
        sid = "dreamina" if position == 0 else "dreamina#" + str(position + 1)
        label = obs.get("label") or (None if position == 0 else "账号 " + str(position + 1))
        if obs.get("failed"):
            out = failed_source(sid, "creative_account", now, "dreamina_web_no_data", "not_connected")
        elif position == 0 and index is not None and sources[index]["status"] not in {"error", "not_connected"} \
                and sources[index].get("account_key") in (None, obs["account_key"]):
            out = apply_observation(sources[index], obs, now)
        else:
            out = source(sid, "creative_account", now)
            out["account_key"] = obs["account_key"]
            out = apply_observation(out, obs, now)
        if label:
            out["account_label"] = label
        if position == 0 and index is not None:
            # A working CLI source for a different account stays; the web login is then account 1 only if it read data.
            if obs.get("failed") and sources[index]["status"] not in {"error", "not_connected"}:
                continue
            sources[index] = out
        else:
            sources.append(out)
    return sources
    sources = list(sources)
    index = next((i for i, s in enumerate(sources) if s["id"] == "dreamina"), None)
    extra = 2
    for position, obs in enumerate(items):
        if obs.get("failed"):
            # Keep the account's place: ids follow login order ("dreamina", "dreamina#2"…),
            # which is how the app maps a card back to its login.
            sid = "dreamina" if position == 0 else "dreamina#" + str(extra)
            failed = failed_source(sid, "creative_account", now, "dreamina_web_no_data", "not_connected")
            failed["account_label"] = obs.get("label") or ("账号 " + str(position + 1) if position else None)
            if failed["account_label"] is None:
                del failed["account_label"]
            if position == 0 and index is not None:
                if sources[index]["status"] in {"error", "not_connected"}:
                    sources[index] = failed
            elif position == 0:
                sources.append(failed)
            else:
                sources.append(failed)
                extra += 1
            continue
        cli = sources[index] if index is not None else None
        if cli is not None and (cli.get("account_key") is None or cli.get("account_key") == obs["account_key"]) \
                and cli["diagnostics"].get("web_observed_at") is None:
            if cli["status"] in {"error", "not_connected"}:
                base = source("dreamina", "creative_account", now)
                base["account_key"] = obs["account_key"]
                cli = base
            sources[index] = apply_observation(cli, obs, now)
            if obs.get("label"):
                sources[index]["account_label"] = obs["label"]
            continue
        bare = source("dreamina#" + str(extra), "creative_account", now)
        bare["account_key"] = obs["account_key"]
        # Extra accounts always carry a name so the cards can be told apart.
        bare["account_label"] = obs.get("label") or "账号 " + str(extra)
        sources.append(apply_observation(bare, obs, now))
        extra += 1
    return sources
