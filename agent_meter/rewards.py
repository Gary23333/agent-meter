"""Daily free-credit rewards on website logins: status always, claiming opt-in.

This is the only module that writes to a provider account. Everything else in
the backend stays read-only. Claiming runs only for providers the user switched
on (preferences ``auto_claim``) or for one account the user asked to claim now.
It never buys, redeems streak tiers, spends streak-recovery cards, accepts new
tasks or draws lotteries.

Endpoints come from each provider's public web bundle (2026-11-09 research,
docs/research/checkin-automation-and-collection-2026-11-09.md):

- TRAE CN: ``/trae/api/v2/ug/checkin_credits/status`` and ``/claim`` with the
  website Cloud-IDE-JWT already used for the account card.
- WorkBuddy: growth-center ``/activity/growth/streak``, ``/v2/activity/growth/tasks``
  and ``/activity/growth/tasks/{task_code}/claim`` with the website cookie.
- Qoder CN: ``/sash/api/v1/me/campaigns`` and ``.../{campaign_id}/claim`` with
  the desktop client's own token (not a website login), see
  ``agent_meter/qoder_campaign.py``.

The ledger ``<runtime>/rewards.json`` (0600) keeps one record per account and
day (Asia/Shanghai, the providers' own day boundary): the last observed status
and every claim attempt. It holds no credentials, cookies or response bodies.
"""
import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .model import SourceError, number, timestamp
from .transport import get_json, post_json
from .qoder_campaign import qoder_campaigns_claim, qoder_campaigns_status
from .web_sources import SAFARI_UA, WORKBUDDY_ORIGIN, as_account_lists, require

PROVIDERS = ("trae_cn", "workbuddy", "qoder")
# Providers whose credentials come from a desktop app instead of a website
# login. The collector passes the app path; the provider reads what it needs
# from that pseudo-session, so it behaves like a single account.
DESKTOP_PROVIDERS = {"qoder": "desktop_app"}
LEDGER_NAME = "rewards.json"
LEDGER_SCHEMA = 1
CN = timezone(timedelta(hours=8))
STATUS_EVERY = 30 * 60      # seconds between status reads per account
RETRY_AFTER = 60 * 60       # seconds before retrying a failed claim
MAX_ATTEMPTS = 3            # claim attempts per item per day
KEEP_DAYS = 400
HISTORY_DAYS = 35
DEFAULT_CLAIM_TIME = "00:05"
CLAIM_TIME = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9])$")

TRAE_UG = "https://api.trae.cn/trae/api/v2/ug"
TASK_CODE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
# TRAE answers these when today's credits were already taken.
TRAE_ALREADY = {9004}


def day_of(now):
    return datetime.fromtimestamp(now, CN).strftime("%Y-%m-%d")


def claim_moments(now, claim_time):
    """Today's claim moment and the next one (epoch seconds, Asia/Shanghai)."""
    match = CLAIM_TIME.match(claim_time or "") or CLAIM_TIME.match(DEFAULT_CLAIM_TIME)
    local = datetime.fromtimestamp(now, CN)
    today = local.replace(hour=int(match.group(1)), minute=int(match.group(2)), second=0, microsecond=0)
    nxt = today if today.timestamp() > now else today + timedelta(days=1)
    return today.timestamp(), nxt.timestamp()


def _short(text, limit=60):
    return text[:limit] if isinstance(text, str) else None


def _envelope(payload, error):
    if not isinstance(payload, dict) or payload.get("code") != 0:
        raise SourceError(error)
    return payload


# --- TRAE CN ---------------------------------------------------------------

def _trae_headers(session):
    token = require(session, "token")
    if token.lower().startswith("cloud-ide-jwt "):
        token = token[len("cloud-ide-jwt "):].strip()
    headers = {"Authorization": "Cloud-IDE-JWT " + token, "X-User-Region": "CN",
               "User-Agent": session.get("user_agent") or SAFARI_UA,
               "Origin": "https://www.trae.cn", "Referer": "https://www.trae.cn/"}
    if session.get("device_id"):
        headers["X-Device-Id"] = session["device_id"]
    return headers


def normalize_trae_status(payload):
    data = _envelope(payload, "trae_checkin_api_error")
    if not isinstance(data.get("checked_in"), bool):
        raise SourceError("unsupported_trae_checkin_contract")
    credits = number(data.get("credits"), optional=True) or 0
    extra = number(data.get("extra_credits"), optional=True) or 0
    enabled = data.get("enable") is not False
    signed = data["checked_in"]
    claimable = []
    if enabled and not signed:
        claimable.append({"item": "daily_checkin", "title": "每日签到", "credits": credits + extra})
    return {"kind": "daily_checkin", "enabled": enabled, "signed_in": signed,
            "daily_credits": credits, "extra_credits": extra, "claimable": claimable}


def trae_status(session, timeout):
    return normalize_trae_status(post_json(TRAE_UG + "/checkin_credits/status", {"req_source": 1},
                                           timeout=timeout, headers=_trae_headers(session)))


def normalize_trae_claim(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("code"), int):
        raise SourceError("trae_checkin_api_error")
    code = payload["code"]
    if code == 0:
        return {"result": "ok", "credits": number(payload.get("credits"), optional=True)}
    if code in TRAE_ALREADY:
        return {"result": "already", "code": code}
    return {"result": "rejected", "code": code}


def trae_claim(session, item, timeout):
    if item != "daily_checkin":
        raise SourceError("unknown_reward_item")
    return normalize_trae_claim(post_json(TRAE_UG + "/checkin_credits/claim", {"req_source": 1},
                                          timeout=timeout, headers=_trae_headers(session)))


# --- WorkBuddy -------------------------------------------------------------

def _workbuddy_headers(session):
    return {"Cookie": require(session, "cookie"), "User-Agent": session.get("user_agent") or SAFARI_UA,
            "Origin": WORKBUDDY_ORIGIN, "Referer": WORKBUDDY_ORIGIN + "/growth-center"}


def normalize_workbuddy_status(streak_payload, tasks_payload):
    streak_data = _envelope(streak_payload, "workbuddy_growth_api_error").get("data")
    tasks_data = _envelope(tasks_payload, "workbuddy_growth_api_error").get("data")
    if not isinstance(streak_data, dict) or not isinstance(tasks_data, dict) \
            or not isinstance(tasks_data.get("tasks"), list):
        raise SourceError("unsupported_workbuddy_growth_contract")
    streak = streak_data.get("streak") or {}
    cards = streak_data.get("makeup_cards") or {}
    redemption = streak_data.get("redemption_status") or {}
    tiers = []
    for tier in redemption.get("tiers") or []:
        if not isinstance(tier, dict) or not isinstance(tier.get("tier"), str):
            continue
        tiers.append({"tier": _short(tier["tier"], 8), "days": number(tier.get("days"), optional=True),
                      "credits": number(tier.get("credit"), optional=True),
                      "status": _short(redemption.get("tier_%s_status" % tier["tier"]), 20)})
    claimable, open_tasks = [], 0
    for task in tasks_data["tasks"]:
        if not isinstance(task, dict):
            continue
        state, code = task.get("accept_status"), task.get("task_code")
        if state in {"accepted", "in_progress"}:
            open_tasks += 1
        if state == "completed" and isinstance(code, str) and TASK_CODE.match(code):
            claimable.append({"item": "task:" + code, "title": _short(task.get("title")) or code,
                              "credits": number(task.get("reward_credit"), optional=True) or 0})
    return {"kind": "growth_tasks", "enabled": True, "signed_in": None,
            "streak_days": number(streak.get("days"), optional=True),
            "next_tier": _short(streak.get("next_tier"), 8),
            "next_tier_remaining": number(streak.get("next_tier_remaining"), optional=True),
            "makeup_cards": number(cards.get("balance"), optional=True),
            "makeup_cards_max": number(cards.get("max"), optional=True),
            "tiers": tiers, "open_tasks": open_tasks, "claimable": claimable}


def workbuddy_status(session, timeout):
    headers = _workbuddy_headers(session)
    streak = get_json(WORKBUDDY_ORIGIN + "/activity/growth/streak", timeout=timeout, headers=headers)
    tasks = get_json(WORKBUDDY_ORIGIN + "/v2/activity/growth/tasks", timeout=timeout, headers=headers)
    return normalize_workbuddy_status(streak, tasks)


def normalize_workbuddy_claim(payload):
    data = _envelope(payload, "workbuddy_growth_api_error").get("data")
    if not isinstance(data, dict):
        raise SourceError("unsupported_workbuddy_growth_contract")
    if data.get("already_claimed") is True:
        return {"result": "already"}
    badge = data.get("badge") if isinstance(data.get("badge"), dict) else {}
    out = {"result": "ok", "credits": number(data.get("credit"), optional=True)}
    if isinstance(badge.get("name"), str):
        out["badge"] = _short(badge["name"], 40)
    return out


def workbuddy_claim(session, item, timeout):
    code = item[len("task:"):] if item.startswith("task:") else ""
    if not TASK_CODE.match(code):
        raise SourceError("unknown_reward_item")
    return normalize_workbuddy_claim(post_json(WORKBUDDY_ORIGIN + "/activity/growth/tasks/%s/claim" % code, {},
                                               timeout=timeout, headers=_workbuddy_headers(session)))


ADAPTERS = {"trae_cn": (trae_status, trae_claim), "workbuddy": (workbuddy_status, workbuddy_claim),
            "qoder": (qoder_campaigns_status, qoder_campaigns_claim)}


# --- ledger ----------------------------------------------------------------

def load_ledger(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"schema": LEDGER_SCHEMA, "accounts": {}}
    if not isinstance(data, dict) or data.get("schema") != LEDGER_SCHEMA or not isinstance(data.get("accounts"), dict):
        return {"schema": LEDGER_SCHEMA, "accounts": {}}
    return data


def save_ledger(path, ledger, now):
    cutoff = day_of(now - KEEP_DAYS * 86400)
    for account in ledger["accounts"].values():
        account["days"] = {d: v for d, v in account.get("days", {}).items() if d >= cutoff}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        temp = Path(handle.name)
        json.dump(ledger, handle, ensure_ascii=False, indent=1, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temp, 0o600)
    os.replace(temp, path)


def _signed(record):
    status = record.get("status") or {}
    # "already" is not proof: TRAE's 9004 may also mean a rejected request.
    return status.get("signed_in") is True or any(c.get("result") == "ok" and c.get("item") == "daily_checkin"
                                                  for c in record.get("claims", []))


def claim_streak(days, today):
    """Consecutive signed-in days ending today, or yesterday while today is still open."""
    cursor = datetime.strptime(today, "%Y-%m-%d")
    if not _signed(days.get(today, {})):
        cursor -= timedelta(days=1)
    count = 0
    while _signed(days.get(cursor.strftime("%Y-%m-%d"), {})):
        count += 1
        cursor -= timedelta(days=1)
    return count


def _claimed_credits(record):
    return sum(c.get("credits") or 0 for c in record.get("claims", []) if c.get("result") == "ok")


def summarize(slot, provider, account, now, auto, label=None, state="available", reason=None):
    today = day_of(now)
    days = account.get("days", {})
    record = days.get(today, {})
    status = record.get("status")
    out = {"id": slot, "provider": provider, "auto_claim": auto, "status": state, "reason": reason,
           "checked_at": timestamp(account["checked_at"]) if account.get("checked_at") else None,
           "today": status, "claims_today": record.get("claims", []),
           "claimed_credits_today": _claimed_credits(record),
           "claimed_credits_total": sum(_claimed_credits(r) for r in days.values()),
           "streak_days": claim_streak(days, today) if provider == "trae_cn" else None}
    if label:
        out["account_label"] = label
    history = []
    for offset in range(HISTORY_DAYS - 1, -1, -1):
        d = day_of(now - offset * 86400)
        if d in days:
            history.append({"date": d, "signed_in": _signed(days[d]) if provider == "trae_cn" else None,
                            "claimed_credits": _claimed_credits(days[d])})
    out["history"] = history
    return out


class RewardsService:
    """Throttled status reads plus opt-in claims; one instance per backend."""

    def __init__(self, runtime_dir, adapters=None):
        self.path = Path(runtime_dir) / LEDGER_NAME
        self.adapters = adapters or ADAPTERS
        self.ledger = load_ledger(self.path)
        self.errors = {}

    def _due(self, account, now, force):
        if force:
            return True
        checked = account.get("checked_at")
        return not checked or now - checked >= STATUS_EVERY or day_of(checked) != day_of(now)

    def _claim_items(self, record, status, now):
        attempts = {}
        for c in record.get("claims", []):
            attempts.setdefault(c["item"], []).append(c)
        for item in status.get("claimable", []):
            tried = attempts.get(item["item"], [])
            if any(c["result"] in {"ok", "already"} or c.get("final") for c in tried) or len(tried) >= MAX_ATTEMPTS:
                continue
            if tried and now - tried[-1]["at"] < RETRY_AFTER:
                continue
            yield item

    def _run(self, slot, provider, session, now, timeout, auto, force):
        status_fn, claim_fn = self.adapters[provider]
        account = self.ledger["accounts"].setdefault(slot, {"provider": provider, "days": {}})
        account["provider"] = provider
        if not self._due(account, now, force):
            return False
        record = account["days"].setdefault(day_of(now), {"claims": []})
        try:
            status = status_fn(session, timeout)
            claimed = False
            if auto:
                for item in list(self._claim_items(record, status, now)):
                    try:
                        result = claim_fn(session, item["item"], timeout)
                    except SourceError as e:
                        result = {"result": "error", "reason": e.code}
                    entry = {"item": item["item"], "title": item.get("title"), "at": now}
                    entry.update(result)
                    if entry.get("result") == "ok" and entry.get("credits") is None:
                        entry["credits"] = item.get("credits")
                    record["claims"].append(entry)
                    claimed = True
                if claimed:
                    status = status_fn(session, timeout)
                    # "Already claimed" is only believable if the item is gone
                    # now. TRAE answers 9004 to web-only claims it refuses, and
                    # the status then still offers the check-in: stop for today.
                    still = {c["item"] for c in status.get("claimable", [])}
                    for entry in record["claims"]:
                        if entry.get("at") == now and entry.get("result") == "already" and entry["item"] in still:
                            entry["result"] = "rejected"
                            entry["final"] = True
                            entry["reason"] = "claim_refused_from_web"
            record["status"] = status
            account["checked_at"] = now
            self.errors.pop(slot, None)
        except SourceError as e:
            account["checked_at"] = now
            self.errors[slot] = e.code
        except Exception:
            account["checked_at"] = now
            self.errors[slot] = "unexpected_reward_error"
        return True

    def tick(self, web_sessions, now, auto_claim=(), disabled=(), timeout=15, only=None, local_only=False,
             claim_time=DEFAULT_CLAIM_TIME, desktop=None):
        """Reads due statuses, claims what is switched on and returns the summary.

        Automatic claims wait for the daily ``claim_time`` (HH:MM, Asia/Shanghai);
        the first read after that moment happens right away instead of waiting
        for the status interval. ``only`` names one slot to read and claim right
        away (the user's "claim now" button), regardless of time, throttling
        and the auto switch.

        ``desktop`` maps a desktop-backed provider to its app path; such a
        provider has no website session but still counts as one account.
        """
        accounts = as_account_lists(web_sessions)
        for provider, key in DESKTOP_PROVIDERS.items():
            app = (desktop or {}).get(provider)
            if app and not accounts.get(provider):
                accounts[provider] = [{key: app}]
        today_at, next_at = claim_moments(now, claim_time)
        claim_open = now >= today_at
        changed = False
        summaries = []
        for provider in PROVIDERS:
            if provider not in self.adapters:
                continue
            for index, session in enumerate(accounts.get(provider, [])):
                slot = provider if index == 0 else "%s#%d" % (provider, index + 1)
                auto = provider in auto_claim
                label = session.get("label")
                if local_only or provider in disabled:
                    summaries.append(summarize(slot, provider, self.ledger["accounts"].get(slot, {}), now, auto, label,
                                               "not_connected", "local_only_mode" if local_only else "disabled_by_user"))
                    continue
                if only is None or only == slot:
                    checked = self.ledger["accounts"].get(slot, {}).get("checked_at") or 0
                    # Read again as soon as today's claim moment passes.
                    first_after_open = auto and claim_open and checked < today_at
                    changed |= self._run(slot, provider, session, now, timeout,
                                         (auto and claim_open) or only == slot,
                                         force=only == slot or first_after_open)
                account = self.ledger["accounts"].get(slot, {})
                error = self.errors.get(slot)
                state = "available" if error is None else ("not_connected" if error in {"not_authenticated", "web_session_missing"}
                                                           else "error")
                summary = summarize(slot, provider, account, now, auto, label, state, error)
                summary["claim_time"] = claim_time if CLAIM_TIME.match(claim_time or "") else DEFAULT_CLAIM_TIME
                summary["next_claim_at"] = timestamp(next_at) if auto else None
                summaries.append(summary)
        if changed:
            try:
                save_ledger(self.path, self.ledger, now)
            except OSError:
                pass
        return {"schema_version": 1, "timezone": "Asia/Shanghai", "accounts": summaries}
