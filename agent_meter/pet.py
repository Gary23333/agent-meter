"""Desktop-pet brain: one PetFrame from snapshot, session activity and hook events.

Read-only and in-memory. The brain never starts a collection, never writes a
file and never talks to the network; it only interprets data the service
already holds. Contract (schema 1) is documented in docs/pet-system-plan-2026-11-09.md.

Honesty rules inherited from the rest of the project:
- unknown is not zero: no readable quota -> ``confused``, never ``exhausted``;
- a recency-only session that stops writing is not a success (no reaction);
- accounts are never summed; every meter is listed on its own;
- reminders reuse Notifier.swift keys, levels and thresholds so the pet and
  the system notification agree about what happened.
"""
import math
import re
import threading
import time
from collections import deque
from datetime import date, datetime, timedelta

from .applications import app_id
from .exchange_rates import FX_FALLBACK, rate_from
from .model import DISPLAY_ZONE

SCHEMA_VERSION = 1

# Base states, highest priority first (see the plan document, section 5).
STATES = ("offline", "exhausted", "alarm", "waiting", "busy", "working", "painting", "tired",
          "alert", "focus", "excited", "confused", "sleeping", "idle")
MOODS = ("neutral", "happy", "excited", "worried", "sad", "sleepy", "surprised", "confused", "determined")
REACTIONS = ("celebrate", "eating", "startle", "wave", "painting")
REACTION_RANK = {"startle": 4, "celebrate": 3, "painting": 2, "eating": 1, "wave": 0}
TONES = ("ok", "low", "critical", "empty", "unknown")

EVENT_KINDS = ("agent_started", "agent_done", "agent_waiting", "agent_failed", "nudge",
               "focus_start", "focus_stop", "prices_synced")
MAX_EVENTS = 50
MAX_TEXT = 80
SOURCE_RE = re.compile(r"^[a-z0-9][a-z0-9_#.\-]{0,31}$")
DEFAULT_EVENT_TTL = {"agent_waiting": 600, "agent_started": 1800, "agent_done": 30, "agent_failed": 60,
                     "nudge": 20, "prices_synced": 20, "focus_start": 60, "focus_stop": 20}
MAX_EVENT_TTL = 3600

RELEVANT_WINDOW = 6 * 3600
# The app refreshes about every 5 minutes; a snapshot this old means nobody is refreshing, so quota is unknown.
SNAPSHOT_STALE_SECONDS = 20 * 60
REACTION_SECONDS = {"celebrate": 8, "eating": 5, "startle": 6, "wave": 5, "painting": 8}
CELEBRATE_COOLDOWN = 120
EAT_TOKENS = 20_000
EAT_COOLDOWN = 20
PRICE_REACTION_COOLDOWN = 60

DEFAULT_PREFERENCES = {"low_quota_threshold": 20.0, "energy_source": "auto", "quiet_hours": None,
                       "break_after_minutes": 120, "sleep_after_minutes": 30, "alerts": True}
QUIET_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)-([01]\d|2[0-3]):([0-5]\d)$")

# Activity row app -> quota source whose percentage windows describe it.
ACTIVITY_QUOTA_SOURCE = {"codex": "codex", "codex_images": "codex", "claude": "claude", "kimi": "kimi",
                         "kimi_desktop": "kimi", "zcode": "zcode"}

BRAND_NAMES = {
    "codex": "Codex", "claude": "Claude Code", "kimi": "Kimi Code", "kimi_desktop": "Kimi 桌面端",
    "qoder": "Qoder CN", "workbuddy": "WorkBuddy", "trae_cn": "TRAE CN", "minimax_code": "MiniMax Code",
    "minimax_design": "MiniMax Design", "dreamina": "即梦", "deepseek_api": "DeepSeek API", "zcode": "ZCode",
    "volcengine": "火山方舟 Coding Plan", "mimo": "MiMo API", "stepfun": "阶跃星辰",
    "reset_forecast": "重置预测", "imported_history": "历史导入", "opencode": "OpenCode",
    "gemini": "Gemini CLI", "antigravity": "Antigravity", "deepseek_harness": "DeepSeek Harness"}
SHORT_NAMES = {
    "codex": "Codex", "claude": "Claude", "kimi": "Kimi", "kimi_desktop": "Kimi 桌面", "qoder": "Qoder",
    "workbuddy": "WorkBuddy", "trae_cn": "TRAE", "minimax_code": "MiniMax", "minimax_design": "Design",
    "dreamina": "即梦", "deepseek_api": "DeepSeek", "zcode": "ZCode", "volcengine": "火山", "mimo": "MiMo",
    "stepfun": "阶跃", "opencode": "OpenCode", "gemini": "Gemini", "antigravity": "Antigravity",
    "deepseek_harness": "DS Harness", "reset_forecast": "预测"}
APP_LABELS = {"claude": "Claude Code", "codex": "Codex", "codex_images": "Codex 生图", "kimi": "Kimi Code",
              "kimi_desktop": "Kimi 桌面端", "gemini": "Gemini", "opencode": "OpenCode", "mcode": "MiniMax Code",
              "zcode": "ZCode", "workbuddy": "WorkBuddy", "antigravity": "Antigravity", "agy": "Antigravity",
              "dsh": "DeepSeek Harness", "deepseek_harness": "DeepSeek Harness"}
WINDOW_NAMES = {"limit5h": "5 小时", "limit7d": "7 天", "monthTotal": "本月总量", "monthCode": "本月编程",
                "stepPlanCredits": "STEP 积分", "5h": "5 小时", "week": "每周", "userQuota": "套餐额度",
                "addOnQuota": "加购额度", "orgResourcePackage": "组织资源包", "totalQuota": "总额度",
                "sharedQuota": "共享额度", "credits": "积分", "primary": "主窗口", "secondary": "次窗口",
                "tertiary": "第三窗口", "summary": "汇总"}
NAMED_BUCKETS = {"seven_day_opus": "7 天 Opus", "seven_day_sonnet": "7 天 Sonnet", "monthly": "每月",
                 "mcp": "MCP 调用（月）", "seven_day_oauth_apps": "7 天 OAuth 应用"}
UNIT_NAMES = {"second": "秒", "minute": "分钟", "hour": "小时", "day": "天", "week": "周", "month": "个月"}
UNIT_MINUTES = {"minute": 1.0, "hour": 60.0, "day": 1440.0, "week": 10080.0}
CREDIT_UNITS = {"provider_credits": "积分", "dreamina_credits": "积分", "credits": "积分", "credit": "积分",
                "minimax_design_media_credits": "媒体积分", "workbuddy_credits": "积分", "trae_credits": "积分",
                "qoder_credits": "积分", "stepfun_credits": "积分", "zcode_credits": "额度", "tokens": "Token",
                "calls": "次", "CNY": "元", "USD": "美元"}
ACCOUNT_METRICS = ("quota", "reset_cards", "credits", "renewal_time", "credit_refresh_time")


# --------------------------------------------------------------------------- helpers

def _num(value):
    """JSON numbers or Decimal strings -> float, else None (bool is not a number)."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
        return number if math.isfinite(number) else None
    return None


def _epoch(stamp):
    """Backend timestamps are {epoch_seconds, utc, display}; plain numbers are accepted."""
    if isinstance(stamp, dict):
        return _num(stamp.get("epoch_seconds"))
    return _num(stamp)


def _rows(value):
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _round_half_up(value):
    return int(math.floor(value + 0.5)) if value >= 0 else -int(math.floor(-value + 0.5))


def _clean(value, limit=MAX_TEXT):
    """Strip control characters and cap the length; hooks must not smuggle content in."""
    if not isinstance(value, str):
        return None
    text = "".join(ch for ch in value if ch >= " " and ch != "\x7f" and ch not in "  ").strip()
    return text[:limit] or None


def base_id(source_id):
    return source_id.split("#", 1)[0]


def brand_name(source_id):
    if source_id.startswith("codexbar:"):
        return brand_name(source_id[len("codexbar:"):]) + " · CodexBar"
    return BRAND_NAMES.get(base_id(source_id), source_id)


def short_name(source_id):
    return SHORT_NAMES.get(base_id(source_id)) or brand_name(source_id)


def display_name(src):
    label = src.get("account_label")
    return brand_name(src.get("id", "unknown")) + (" · " + label if label else "")


def app_label(app):
    return APP_LABELS.get(app, app)


# Formatting mirrors Fmt.swift so pet text matches the notification wording.

def fmt_trim(value):
    return str(int(value)) if value == round(value) else "%.1f" % value


def fmt_percent(value):
    return "%d%%" % value if value == round(value) else "%.1f%%" % value


def fmt_window(minutes):
    n = int(minutes)
    if n % 1440 == 0:
        return "%d 天" % (n // 1440)
    if n % 60 == 0:
        return "%d 小时" % (n // 60)
    return "%d 分钟" % n


def fmt_countdown(seconds):
    s = int(seconds)
    if s <= 0:
        return "已过时间"
    days, hours, minutes = s // 86400, (s % 86400) // 3600, (s % 3600) // 60
    if days > 0:
        return "%d天%d小时后" % (days, hours) if hours > 0 else "%d天后" % days
    if hours > 0:
        return "%d小时%d分后" % (hours, minutes) if minutes > 0 else "%d小时后" % hours
    return "%d分钟后" % minutes if minutes > 0 else "不到1分钟"


def fmt_countdown_bare(seconds):
    return fmt_countdown(seconds).replace("后", "")


def fmt_moment(epoch, now):
    when = datetime.fromtimestamp(epoch, DISPLAY_ZONE)
    if when.year == datetime.fromtimestamp(now, DISPLAY_ZONE).year:
        return "%d月%d日 %02d:%02d" % (when.month, when.day, when.hour, when.minute)
    return "%d年%d月%d日 %02d:%02d" % (when.year, when.month, when.day, when.hour, when.minute)


def fmt_day(day, now):
    if day.year == datetime.fromtimestamp(now, DISPLAY_ZONE).year:
        return "%d月%d日" % (day.month, day.day)
    return "%d年%d月%d日" % (day.year, day.month, day.day)


def parse_day(text):
    if not isinstance(text, str):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def days_until(day, now):
    return (day - datetime.fromtimestamp(now, DISPLAY_ZONE).date()).days


def fmt_day_countdown(day, now):
    d = days_until(day, now)
    if d > 0:
        return "%d 天后" % d
    if d == 0:
        return "今天"
    return "已过 %d 天" % -d


def fmt_grouped(value, fraction=0):
    text = "{:,.{n}f}".format(value, n=fraction)
    if fraction and "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def fmt_amount(value, unit, fx_rate=FX_FALLBACK):
    if unit in ("USD", "CNY"):
        return "¥" + fmt_grouped(value * float(fx_rate) if unit == "USD" else value, 2)
    return fmt_grouped(value, 2)


def window_minutes(row):
    minutes = _num(row.get("window_minutes"))
    if minutes is not None:
        return minutes
    window = row.get("window") if isinstance(row.get("window"), dict) else {}
    duration, unit = _num(window.get("duration")), window.get("unit")
    if duration is not None and unit in UNIT_MINUTES:
        return duration * UNIT_MINUTES[unit]
    return {"limit5h": 300.0, "5h": 300.0, "limit7d": 10080.0, "week": 10080.0}.get(row.get("bucket"))


def _window_label(row):
    minutes = _num(row.get("window_minutes"))
    if minutes is not None:
        return fmt_window(minutes)
    window = row.get("window") if isinstance(row.get("window"), dict) else {}
    duration, unit = _num(window.get("duration")), window.get("unit")
    if duration is not None and isinstance(unit, str):
        return "%s %s" % (fmt_trim(duration), UNIT_NAMES.get(unit, unit))
    bucket = row.get("bucket") if isinstance(row.get("bucket"), str) else ""
    return WINDOW_NAMES.get(bucket, bucket or "额度")


def bucket_label(row):
    """Catalog.bucketLabel: the same words the card, ticker and notification use."""
    group = row.get("group")
    if isinstance(group, str) and group:
        return "%s · %s" % (group, _window_label(row))
    bucket = row.get("bucket")
    if isinstance(bucket, str) and bucket in NAMED_BUCKETS:
        return NAMED_BUCKETS[bucket]
    minutes = _num(row.get("window_minutes"))
    if minutes is not None:
        return fmt_window(minutes)
    window = row.get("window") if isinstance(row.get("window"), dict) else {}
    guessed = window_minutes(row)
    if guessed is not None and window.get("unit") is not None and guessed % 60 == 0:
        return fmt_window(guessed)
    return _window_label(row)


def tone_of(remaining, threshold):
    if remaining is None:
        return "unknown"
    if remaining <= 0:
        return "empty"
    if remaining <= min(5.0, threshold):
        return "critical"
    if remaining <= threshold:
        return "low"
    return "ok"


# --------------------------------------------------------------------------- snapshot views

def _metric(src, name):
    """Source.metric: only metrics that actually carry a value."""
    entry = (src.get("metrics") or {}).get(name)
    if isinstance(entry, dict) and entry.get("value") is not None:
        return entry
    return None


def is_account_source(src):
    """Snapshot.accountSources: neither local history nor the forecast feature, with account data."""
    scope = src.get("scope") or ""
    if scope in ("local_imported_history", "local_session_history") or scope == "external_forecast":
        return False
    if any(_metric(src, name) is not None for name in ACCOUNT_METRICS):
        return True
    return base_id(src.get("id", "")) == "antigravity" and _metric(src, "tokens") is not None


def credit_rows(entry):
    """Metric.creditRows: a list value is the rows; an object may carry them under "rows"."""
    value = entry.get("value")
    if isinstance(value, dict) and isinstance(value.get("rows"), list):
        return _rows(value["rows"])
    return _rows(value)


def account_sources(snapshot):
    return [s for s in (snapshot or {}).get("sources", []) if isinstance(s, dict) and is_account_source(s)]


def collect_meters(snapshot):
    """Every percentage window of every account (mcp call counters stay on the card)."""
    meters = []
    for src in account_sources(snapshot):
        entry = _metric(src, "quota")
        if entry is None:
            continue
        stale = src.get("status") == "stale" or entry.get("status") == "stale"
        for index, row in enumerate(_rows(entry.get("value"))):
            remaining = _num(row.get("remaining_percent"))
            if remaining is None or row.get("bucket") == "mcp":
                continue
            resets = _epoch(row.get("resets_at"))
            meters.append({"id": "%s:%s" % (src["id"], row.get("bucket") or index), "source": src["id"],
                           "base": base_id(src["id"]), "name": short_name(src["id"]) +
                           ("·" + src["account_label"] if src.get("account_label") else ""),
                           "window": bucket_label(row), "remaining": remaining, "resets_at": resets,
                           "window_minutes": window_minutes(row), "stale": bool(stale)})
    return meters


def recent_landing(forecast, now, within=86400):
    """The newest history event when it is a confident global reset announced within `within` seconds."""
    events = forecast.get("history_events") if isinstance(forecast.get("history_events"), list) else []
    latest = events[0] if events and isinstance(events[0], dict) else None
    if latest and latest.get("kind") == "reset" and latest.get("confidence") in ("high", "medium"):
        at = _epoch(latest.get("announced_at"))
        if at is not None and at <= now and now - at < within:
            return latest
    return None


def forecast_mood(forecast, targets, now):
    """TiboMood.from(forecast:targets:now:), same thresholds as the notifier."""
    for target in targets:
        if target.get("kind") == "promised_reset" and target.get("state") == "inside_window":
            return "resetting"
    if recent_landing(forecast, now) is not None:
        return "celebrate"
    ensemble = forecast.get("ensemble") if isinstance(forecast.get("ensemble"), dict) else {}
    horizons = ensemble.get("horizons") if isinstance(ensemble.get("horizons"), dict) else {}
    if not horizons:
        return "offline"
    median = _num((horizons.get("48h") or {}).get("weighted_median"))
    if median is None:
        median = _num((horizons.get("24h") or {}).get("weighted_median"))
    median = median or 0.0
    promises = forecast.get("promises")
    if (isinstance(promises, list) and promises) or median >= 50:
        return "excited"
    return "waiting" if median >= 20 else "sleepy"


def forecast_view(snapshot, now):
    """(mood, median_48h, targets, forecast value) for the reset_forecast source, or None."""
    for src in (snapshot or {}).get("sources", []):
        if isinstance(src, dict) and src.get("id") == "reset_forecast":
            entry = _metric(src, "reset_forecast")
            forecast = entry["value"] if entry and isinstance(entry["value"], dict) else {}
            countdown = _metric(src, "known_reset_countdown")
            targets = _rows((countdown["value"] or {}).get("targets")) if countdown and isinstance(countdown["value"], dict) else []
            targets = [_fresh_target(t, now) for t in targets]
            if not forecast and not targets:
                return None
            horizons = ((forecast.get("ensemble") or {}).get("horizons") or {}) if isinstance(forecast.get("ensemble"), dict) else {}
            median = _num((horizons.get("48h") or {}).get("weighted_median")) if isinstance(horizons.get("48h"), dict) else None
            return forecast_mood(forecast, targets, now), median, targets, forecast
    return None


def _fresh_target(target, now):
    """The stored state is as old as the snapshot; recompute it from the window clock.

    Mirrors reset_forecast._fill_seconds so the pet agrees with what a fresh read would say.
    """
    out = dict(target)
    open_at, close_at = _epoch(target.get("open_at")), _epoch(target.get("close_at"))
    if target.get("precision") != "window" or close_at is None:
        return out
    if close_at < now:
        out["state"] = "elapsed_awaiting_landing"
    elif open_at is not None and open_at <= now:
        out["state"] = "inside_window"
    else:
        out["state"] = "upcoming"
    return out


def expiry_level(expires, now):
    """Notifier.expiryLevel: "1" within 24 hours, "3" within 3 days, None otherwise or past."""
    left = expires - now
    if left <= 0:
        return None
    if left <= 86400:
        return "1"
    if left <= 3 * 86400:
        return "3"
    return None


def compute_reminders(snapshot, threshold, now):
    """Notifier.alerts(snapshot:threshold:now:) with the same keys; each is title/body plus pet metadata."""
    out = []
    threshold = float(threshold)

    def add(key, kind, level, title, body, tone, priority, source, tab="accounts"):
        out.append({"id": key, "kind": kind, "level": level, "title": title, "body": body, "tone": tone,
                    "priority": priority, "source": source, "action": {"kind": "open_panel", "tab": tab}})

    for src in account_sources(snapshot):
        name, sid = display_name(src), src["id"]
        quota = _metric(src, "quota")
        for row in _rows(quota["value"]) if quota else []:
            remaining = _num(row.get("remaining_percent"))
            if remaining is None:
                continue
            resets = _epoch(row.get("resets_at"))
            if remaining <= 0:
                level = "0"
            elif remaining <= min(5.0, threshold):
                level = "5"
            elif remaining <= threshold:
                level = str(int(threshold))
            else:
                continue
            bucket = row.get("bucket") if isinstance(row.get("bucket"), str) else "quota"
            reset_text = ""
            if resets is not None:
                reset_text = "，%s（%s）重置" % (fmt_countdown(resets - now), fmt_moment(resets, now))
            add("low|%s|%s|%d|%s" % (sid, bucket, int(resets or 0), level), "low_quota", level,
                "%s 额度已用完" % name if remaining <= 0 else "%s 额度不足" % name,
                "%s 窗口剩余 %s%s。" % (bucket_label(row), fmt_percent(float(_round_half_up(remaining))), reset_text),
                "danger" if level in ("0", "5") else "warn", {"0": 90, "5": 80}.get(level, 60), sid)

        cards = _metric(src, "reset_cards")
        if cards and isinstance(cards["value"], dict):
            value = cards["value"]
            total = int(_num(value.get("available_count")) or 0)
            expiries = [e for e in (_epoch((c or {}).get("expires_at")) for c in value.get("cards", []) if isinstance(c, dict)) if e is not None]
            if not expiries:
                fallback = _epoch(value.get("next_known_expiry"))
                expiries = [fallback] if fallback is not None else []
            grouped = {}
            for exp in expiries:
                grouped[exp] = grouped.get(exp, 0) + 1
            for exp, count in sorted(grouped.items()):
                level = expiry_level(exp, now)
                if level is None:
                    continue
                add("card|%s|%d|%s" % (sid, int(exp), level), "reset_card", level,
                    "%s 重置卡即将到期" % name,
                    "%d 张重置卡将于 %s 到期（还剩 %s），当前共 %d 张，记得使用。" % (
                        count, fmt_moment(exp, now), fmt_countdown_bare(exp - now), total),
                    "danger" if level == "1" else "warn", 70 if level == "1" else 40, sid)

        credits = _metric(src, "credits")
        for row in credit_rows(credits) if credits else []:
            for bucket in _rows(row.get("buckets")):
                amount, exp = _num(bucket.get("balance")), _epoch(bucket.get("expires_at"))
                if amount is None or amount <= 0 or exp is None:
                    continue
                level = expiry_level(exp, now)
                if level is None:
                    continue
                unit = CREDIT_UNITS.get(row.get("unit"), row.get("unit") or "")
                add("credit|%s|%d|%s" % (sid, int(exp), level), "credit", level, "%s 积分即将失效" % name,
                    "%s %s 将于 %s 失效（还剩 %s）。" % (fmt_grouped(amount), unit, fmt_moment(exp, now),
                                                     fmt_countdown_bare(exp - now)),
                    "danger" if level == "1" else "warn", 70 if level == "1" else 40, sid)

        renewal = _metric(src, "renewal_time")
        subscription = src.get("subscription") if isinstance(src.get("subscription"), dict) else {}
        renew_day = parse_day((renewal["value"] or {}).get("date")) if renewal and isinstance(renewal["value"], dict) else None
        if renew_day is not None:
            days = days_until(renew_day, now)
            if 0 <= days <= 3:
                body = "订阅将于 %s 自动续费（%s）" % (fmt_day(renew_day, now), fmt_day_countdown(renew_day, now))
                amount_entry = _metric(src, "renewal_amount")
                if amount_entry and isinstance(amount_entry["value"], dict):
                    amount = _num(amount_entry["value"].get("amount"))
                    if amount is not None:
                        body += "，金额 %s" % fmt_amount(amount, amount_entry["value"].get("currency"), rate_from(snapshot))
                add("renew|%s|%s|%s" % (sid, renewal["value"].get("date") or "", "0" if days == 0 else "3"),
                    "renewal", "0" if days == 0 else "3", "%s 即将续费" % name, body + "。",
                    "warn", 65 if days == 0 else 45, sid)
        elif subscription.get("auto_renew") is False:
            end = parse_day(subscription.get("ends_on"))
            if end is not None:
                days = days_until(end, now)
                if 0 <= days <= 7:
                    level = "1" if days <= 1 else "7"
                    add("member|%s|%s|%s" % (sid, subscription.get("ends_on") or "", level), "membership", level,
                        "%s 会员即将到期" % name,
                        "会员将于 %s 到期（%s），未开启自动续费。" % (fmt_day(end, now), fmt_day_countdown(end, now)),
                        "warn", 65 if days <= 1 else 35, sid)

    view = forecast_view(snapshot, now)
    if view is not None:
        _, _, targets, forecast = view
        for target in targets:
            close = _epoch(target.get("close_at"))
            if target.get("kind") != "promised_reset" or close is None:
                continue
            if target.get("state") not in ("inside_window", "elapsed_awaiting_landing"):
                continue
            inside = target.get("state") == "inside_window"
            label = target.get("label") if isinstance(target.get("label"), str) else "Tibo 公告的重置"
            add("tiboWindow|%d|%s" % (int(close), "open" if inside else "past"), "forecast_window",
                "open" if inside else "past",
                "已公告的全员重置进入时段" if inside else "公告时段已过，额度尚未刷新",
                label + ("：%s 前落地，去 Codex 确认额度。" % fmt_moment(close, now) if inside
                         else "：%s 已过，本机还没看到刷新。" % fmt_moment(close, now)),
                "good" if inside else "info", 75 if inside else 50, "codex", "forecast")
        latest = recent_landing(forecast, now, within=3 * 86400)
        if latest:
            at = _epoch(latest.get("announced_at"))
            sources = latest.get("sources") if isinstance(latest.get("sources"), list) else []
            detail = "，%d 家印证" % len(sources) if len(sources) > 1 else "，仅 1 家记录"
            add("tiboLanded|%s" % (latest.get("post_id") or ""), "forecast_landed", "landed",
                "全员重置已记录落地",
                (latest.get("summary") if isinstance(latest.get("summary"), str) else "追踪站记录到一次全局重置")
                + "（%s%s）" % (fmt_moment(at, now), detail), "good", 55, "codex", "forecast")
    return out


def short_text(reminder):
    """The one-line bubble wording derived from a Notifier-style title/body pair."""
    return reminder["title"] + "：" + reminder["body"].rstrip("。") if reminder.get("body") else reminder["title"]


def daily_report(snapshot, now):
    """Yesterday's local usage, projected from what the snapshot already carries.

    Tokens come from each ledger's daily_models rows, the estimated cost from the
    cost metric's daily amounts (base prices, CNY at the fixed estimate). Returns
    None when yesterday has no recorded usage; an unknown cost stays None, never 0.
    """
    yesterday = (datetime.fromtimestamp(now, DISPLAY_ZONE) - timedelta(days=1)).date().isoformat()
    by_app = {}
    cost = 0.0
    cost_known = False
    fx_rate = float(rate_from(snapshot))
    for src in (snapshot or {}).get("sources", []):
        if not isinstance(src, dict):
            continue
        sid = src.get("id", "")
        # Same convention as application_usage: account splits and CodexBar mirrors are not ledgers.
        if "#" in sid or sid.startswith("codexbar:"):
            continue
        metrics = src.get("metrics") or {}
        tokens = metrics.get("tokens") or {}
        if tokens.get("status") in ("available", "partial", "stale"):
            value = tokens.get("value") if isinstance(tokens.get("value"), dict) else {}
            for row in _rows(value.get("daily_models")):
                if row.get("date") != yesterday:
                    continue
                count = row.get("total_tokens")
                if isinstance(count, int) and not isinstance(count, bool) and count > 0:
                    app = app_id(row.get("app") or sid)
                    by_app[app] = by_app.get(app, 0) + count
        entry = metrics.get("cost") or {}
        value = entry.get("value")
        if isinstance(value, dict) and value.get("unit") in ("CNY", "USD"):
            for day in _rows(value.get("daily")):
                amount = _num(day.get("amount"))
                if day.get("date") == yesterday and amount is not None:
                    cost += amount * (fx_rate if value["unit"] == "USD" else 1.0)
                    cost_known = True
    total = sum(by_app.values())
    if not total:
        return None
    top = max(by_app.items(), key=lambda item: item[1])
    return {"date": yesterday, "tokens": total, "cost_cny": round(cost, 2) if cost_known else None,
            "top_app": top[0], "top_tokens": top[1]}


# --------------------------------------------------------------------------- brain

class PetMind:
    """Interprets data; remembers only what transitions need (baselines, events, focus timer)."""

    def __init__(self, clock=time.time):
        self.clock = clock
        self.lock = threading.RLock()
        self.started_at = clock()
        self.preferences = dict(DEFAULT_PREFERENCES)
        self.events = deque(maxlen=MAX_EVENTS)
        self._event_seq = 0
        self.reactions = []
        self.focus = None
        # Baselines for transition detection. The first observation only records.
        self._snapshot_epoch = None
        self._activity_epoch = None
        self._quota_last = {}
        self._credit_last = {}
        self._session_last = {}
        self._turn_last = {}
        self._tokens_last = None
        self._landed_seen = set()
        self._reaction_keys = set()
        self._last_celebrate = 0.0
        self._last_eat = 0.0
        self._last_price = 0.0
        self._busy_since = None
        self._busy_gap_since = None
        self._activity = None
        self._activity_at = 0.0
        self._hello_done = False
        self._last_state = None
        self._last_state_at = clock()

    # ---- preferences

    def set_preferences(self, values):
        """Whitelisted keys only; raises ValueError so the HTTP layer can answer 400."""
        if not isinstance(values, dict) or not values or set(values) - set(DEFAULT_PREFERENCES):
            raise ValueError("invalid_preferences")
        clean = {}
        for key, value in values.items():
            if key == "low_quota_threshold":
                if value not in (10, 20, 30, 10.0, 20.0, 30.0) or isinstance(value, bool):
                    raise ValueError("invalid_preferences")
                clean[key] = float(value)
            elif key == "energy_source":
                if value != "auto" and not (isinstance(value, str) and SOURCE_RE.match(value)):
                    raise ValueError("invalid_preferences")
                clean[key] = value
            elif key == "quiet_hours":
                if value is not None and not (isinstance(value, str) and QUIET_RE.match(value)):
                    raise ValueError("invalid_preferences")
                clean[key] = value
            elif key == "break_after_minutes":
                if isinstance(value, bool) or not isinstance(value, int) or not (value == 0 or 30 <= value <= 480):
                    raise ValueError("invalid_preferences")
                clean[key] = value
            elif key == "sleep_after_minutes":
                if isinstance(value, bool) or not isinstance(value, int) or not 5 <= value <= 240:
                    raise ValueError("invalid_preferences")
                clean[key] = value
            elif key == "alerts":
                if not isinstance(value, bool):
                    raise ValueError("invalid_preferences")
                clean[key] = value
        with self.lock:
            self.preferences.update(clean)
            return dict(self.preferences)

    # ---- events

    def add_event(self, body, now=None):
        """Validate and store a hook event; returns the stored event (raises ValueError)."""
        if not isinstance(body, dict):
            raise ValueError("invalid_event")
        allowed = {"kind", "source", "text", "project", "ttl", "minutes", "tone"}
        kind = body.get("kind")
        if set(body) - allowed or kind not in EVENT_KINDS:
            raise ValueError("invalid_event")
        source = body.get("source")
        if source is not None and not (isinstance(source, str) and SOURCE_RE.match(source)):
            raise ValueError("invalid_event")
        ttl = body.get("ttl", DEFAULT_EVENT_TTL[kind])
        if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or not 1 <= ttl <= MAX_EVENT_TTL:
            raise ValueError("invalid_event")
        tone = body.get("tone", "info")
        if tone not in ("info", "good", "warn", "danger"):
            raise ValueError("invalid_event")
        minutes = body.get("minutes")
        if kind == "focus_start":
            if isinstance(minutes, bool) or not isinstance(minutes, (int, float)) or not 1 <= minutes <= 180:
                raise ValueError("invalid_event")
        elif minutes is not None:
            raise ValueError("invalid_event")
        for field in ("text", "project"):
            if field in body and not isinstance(body[field], str):
                raise ValueError("invalid_event")
        now = self.clock() if now is None else float(now)
        with self.lock:
            self._event_seq += 1
            event = {"id": "evt-%d" % self._event_seq, "kind": kind, "source": source,
                     "text": _clean(body.get("text")), "project": _clean(body.get("project"), 40),
                     "tone": tone, "at": now, "ttl": float(ttl)}
            self.events.append(event)
            label = app_label(source) if source else "Agent"
            if kind == "agent_done":
                self._react("celebrate", "done|%s" % event["id"], now, "agent_done")
            elif kind == "agent_failed":
                self._react("startle", "failed|%s" % event["id"], now, "agent_failed")
            elif kind == "prices_synced":
                if now - self._last_price >= PRICE_REACTION_COOLDOWN:
                    self._last_price = now
                    self._react("wave", "prices|%s" % event["id"], now, "prices_synced")
            elif kind == "focus_start":
                self.start_focus(minutes, now)
            elif kind == "focus_stop":
                self.stop_focus()
            event["label"] = label
            return dict(event)

    def start_focus(self, minutes, now=None):
        now = self.clock() if now is None else float(now)
        with self.lock:
            self.focus = {"started": now, "ends_at": now + float(minutes) * 60, "minutes": float(minutes)}

    def stop_focus(self):
        with self.lock:
            self.focus = None

    # ---- reactions

    def _react(self, rid, key, now, reason):
        if key in self._reaction_keys:
            return
        self._reaction_keys.add(key)
        if len(self._reaction_keys) > 400:
            self._reaction_keys = set(list(self._reaction_keys)[-200:])
        self.reactions.append({"id": rid, "key": key, "until": now + REACTION_SECONDS[rid],
                               "at": now, "reason": reason})

    def _active_reaction(self, now):
        self.reactions = [r for r in self.reactions if r["until"] > now]
        if not self.reactions:
            return None
        best = max(self.reactions, key=lambda r: (REACTION_RANK[r["id"]], r["at"]))
        return {"id": best["id"], "key": best["key"], "until": best["until"], "reason": best["reason"]}

    # ---- activity polling (own gate so the 2 s pet poll never scans every 2 s)

    def poll_activity(self, fetch, now):
        with self.lock:
            running = any(r.get("status") == "running" for r in (self._activity or {}).get("activities", []))
            gap = 5 if running else 30
            if self._activity is not None and now - self._activity_at < gap:
                return self._activity
        try:
            payload = fetch()
        except Exception:
            payload = None
        with self.lock:
            if payload is not None:
                self._activity, self._activity_at = payload, now
            return self._activity

    # ---- observation (transition detection, once per new data identity)

    def _observe_snapshot(self, snapshot, meters, relevant, now):
        epoch = _epoch((snapshot or {}).get("collected_at"))
        if snapshot is None or epoch is None or epoch == self._snapshot_epoch:
            return
        first = self._snapshot_epoch is None
        self._snapshot_epoch = epoch
        seen = {}
        for m in meters:
            seen[(m["source"], m["id"])] = (m["remaining"], m["resets_at"])
        if not first:
            for m in meters:
                # Only sources the user is actually using: a refill of an idle account is not news.
                if m["stale"] or relevant is None or m["base"] not in relevant:
                    continue
                previous = self._quota_last.get((m["source"], m["id"]))
                if previous is None:
                    continue
                before, before_reset = previous
                refilled = m["remaining"] >= before + 25 or (
                    m["resets_at"] and before_reset and m["resets_at"] > before_reset + 60
                    and m["remaining"] > before)
                if refilled and m["remaining"] >= 50 and now - self._last_celebrate >= CELEBRATE_COOLDOWN:
                    key = "refill|%s|%d" % (m["id"], int(m["resets_at"] or 0))
                    if key not in self._reaction_keys:
                        self._last_celebrate = now
                        self._react("celebrate", key, now, "quota_refill")
        self._quota_last = seen
        # Creative credits: a fall in one source's balance is observable, a "generation" is not.
        balances = {}
        for src in account_sources(snapshot):
            if not (src.get("scope") or "").startswith("creative"):
                continue
            entry = _metric(src, "credits")
            for row in credit_rows(entry) if entry else []:
                amount = _num(row.get("balance"))
                if amount is not None:
                    balances[(src["id"], row.get("unit") or "")] = balances.get((src["id"], row.get("unit") or ""), 0.0) + amount
        if not first:
            for key, amount in balances.items():
                before = self._credit_last.get(key)
                if before is not None and amount < before:
                    self._react("painting", "paint|%s|%d" % (key[0], int(epoch)), now, "credits_spent")
        self._credit_last = balances
        # Announced landing: celebrate once per post, even if the app starts just after.
        view = forecast_view(snapshot, now)
        landing = recent_landing(view[3], now) if view is not None else None
        post = landing.get("post_id") if landing else None
        if post and post not in self._landed_seen:
            self._landed_seen.add(post)
            self._react("celebrate", "tiboLanded|%s" % post, now, "forecast_landed")

    def _observe_activity(self, activity, now):
        epoch = _epoch((activity or {}).get("generated_at"))
        if activity is None or epoch is None or epoch == self._activity_epoch:
            return
        first = self._activity_epoch is None
        self._activity_epoch = epoch
        statuses, turns, tokens = {}, {}, {}
        for row in activity.get("activities", []):
            if not isinstance(row, dict):
                continue
            ident = (row.get("app"), row.get("session_id"))
            statuses[ident] = row.get("status")
            recent = [t for t in row.get("recent_turns", []) if isinstance(t, dict)]
            terminal = [t for t in recent if t.get("status") in ("completed", "failed")]
            if terminal:
                turns[ident] = (terminal[-1].get("turn"), terminal[-1].get("status"))
            total = ((row.get("tokens") or {}).get("total_tokens")) if isinstance(row.get("tokens"), dict) else None
            if row.get("status") == "running" and isinstance(total, int):
                tokens[ident] = total
        if not first:
            for ident, status in statuses.items():
                before = self._session_last.get(ident)
                label = app_label(ident[0])
                if before == "running" and status == "completed":
                    self._react("celebrate", "done|%s|%s|%d" % (ident[0], ident[1], int(epoch)), now, "session_completed")
                elif before == "running" and status == "failed":
                    self._react("startle", "failed|%s|%s|%d" % (ident[0], ident[1], int(epoch)), now, "session_failed")
                elif ident in turns and self._turn_last.get(ident) not in (None, turns[ident]):
                    outcome = turns[ident][1]
                    self._react("celebrate" if outcome == "completed" else "startle",
                                "turn|%s|%s|%s" % (ident[0], ident[1], turns[ident][0]), now,
                                "turn_" + outcome)
            if self._tokens_last is not None:
                burst = sum(max(0, total - self._tokens_last[i]) for i, total in tokens.items() if i in self._tokens_last)
                if burst >= EAT_TOKENS and now - self._last_eat >= EAT_COOLDOWN:
                    self._last_eat = now
                    self._react("eating", "eat|%d" % int(now // EAT_COOLDOWN), now, "token_burst")
        self._session_last, self._turn_last, self._tokens_last = statuses, turns, tokens

    # ---- the frame

    def frame(self, snapshot, activity, now=None, offline=False):
        now = self.clock() if now is None else float(now)
        with self.lock:
            prefs = dict(self.preferences)
            threshold = prefs["low_quota_threshold"]
            self.events = deque((e for e in self.events if e["at"] + e["ttl"] > now), maxlen=MAX_EVENTS)
            meters = collect_meters(snapshot)
            collected = _epoch((snapshot or {}).get("collected_at"))
            if collected is not None and now - collected > SNAPSHOT_STALE_SECONDS:
                for m in meters:
                    m["stale"] = True
            rows = [r for r in (activity or {}).get("activities", []) if isinstance(r, dict)]
            running_rows = [r for r in rows if r.get("status") == "running"]

            # Hook-driven sessions: a started event counts until a done/failed from the same source.
            hook_running, waiting_events = {}, {}
            for event in self.events:
                key = event["source"] or "agent"
                if event["kind"] == "agent_started":
                    hook_running[key] = event
                    waiting_events.pop(key, None)
                elif event["kind"] == "agent_waiting":
                    waiting_events[key] = event
                elif event["kind"] in ("agent_done", "agent_failed"):
                    hook_running.pop(key, None)
                    waiting_events.pop(key, None)
            # The ledger already counts an app it sees running; a hook only adds apps it does not.
            feed_apps = {r.get("app") for r in running_rows}
            hook_only = [k for k in hook_running if k not in feed_apps]
            running = len(running_rows) + len(hook_only)

            # Relevance scope for severity (pinned > running/recent sources > everything).
            pinned = prefs["energy_source"] if prefs["energy_source"] != "auto" else None
            relevant = None
            if pinned:
                relevant = {base_id(pinned)}
                scope = "pinned"
            else:
                relevant = set()
                for row in rows:
                    target = ACTIVITY_QUOTA_SOURCE.get(row.get("app"))
                    last = _epoch(row.get("last_event_at"))
                    if target and (row.get("status") == "running" or (last is not None and now - last <= RELEVANT_WINDOW)):
                        relevant.add(target)
                for key in hook_running:
                    target = ACTIVITY_QUOTA_SOURCE.get(key)
                    if target:
                        relevant.add(target)
                scope = "auto" if relevant else "all"
                relevant = relevant or None
            self._observe_snapshot(snapshot, meters, relevant, now)
            self._observe_activity(activity, now)
            if not self._hello_done:
                self._hello_done = True
                self._react("wave", "hello|%d" % int(self.started_at), now, "startup")

            in_scope = [m for m in meters if not m["stale"] and (relevant is None or m["base"] in relevant)]
            capped = False
            if not in_scope and relevant is not None:
                in_scope = [m for m in meters if not m["stale"]]
                capped = True
            tight = min(in_scope, key=lambda m: (m["remaining"], m["resets_at"] or 1e18)) if in_scope else None
            tone = tone_of(tight["remaining"], threshold) if tight else "unknown"
            # Ambient pose follows what the user is using; with nothing in use (or nothing readable
            # there) the tightest window is shown honestly in the HUD but does not move the pet.
            drives_state = tight is not None and not (scope == "all" or capped)
            state_tone = tone if drives_state else "ok"
            energy = {"known": tight is not None, "remaining": tight["remaining"] if tight else None,
                      "tone": tone, "drives_state": drives_state, "scope": "all" if capped else scope,
                      "source": tight["source"] if tight else None,
                      "label": ("%s · %s" % (tight["name"], tight["window"])) if tight else None,
                      "resets_at": tight["resets_at"] if tight else None,
                      "stale": bool(meters) and all(m["stale"] for m in meters)}
            shown = sorted(meters, key=lambda m: (m["stale"], m["remaining"]))[:6]
            hud = [{"id": m["id"], "source": m["source"], "name": m["name"], "window": m["window"],
                    "remaining": m["remaining"], "tone": tone_of(m["remaining"], threshold),
                    "resets_at": m["resets_at"], "stale": m["stale"]} for m in shown]

            reminders = compute_reminders(snapshot, threshold, now) if (snapshot and prefs["alerts"]) else []
            for event in self.events:
                if event["kind"] == "nudge" and event["text"]:
                    reminders.append({"id": "nudge|" + event["id"], "kind": "nudge", "level": "0", "title": event["text"],
                                      "body": "", "tone": event["tone"], "priority": 50,
                                      "source": event["source"], "action": {"kind": "open_panel", "tab": "accounts"}})
            for event in self.events:
                if event["kind"] in ("agent_done", "agent_failed") and now - event["at"] <= 15:
                    label = app_label(event["source"]) if event["source"] else "Agent"
                    done = event["kind"] == "agent_done"
                    text = event["text"] or (("%s 完成了" % label) + (("「%s」" % event["project"]) if event["project"] else ""))
                    reminders.append({"id": "event|" + event["id"], "kind": event["kind"], "level": "0",
                                      "title": text if done else "%s 出错了" % label, "body": "" if done else (event["text"] or ""),
                                      "tone": "good" if done else "danger", "priority": 55,
                                      "source": event["source"], "action": {"kind": "open_panel", "tab": "apps"}})
            busy_minutes = self._track_busy(running, now)
            interval = prefs["break_after_minutes"]
            if interval and busy_minutes >= interval:
                step = int(busy_minutes // interval)
                reminders.append({"id": "break|%d|%d" % (int(self._busy_since or 0), step), "kind": "break",
                                  "level": str(step), "title": "起来活动一下",
                                  "body": "已经连续用 Agent %s了，站起来喝口水吧。" % (
                                      "%d 小时" % (busy_minutes // 60) if busy_minutes >= 120 else "%d 分钟" % busy_minutes),
                                  "tone": "info", "priority": 20, "source": None,
                                  "action": {"kind": "open_panel", "tab": "apps"}})
            # Once per local day: the id is the date, and the host persists which bubbles it already said.
            report = daily_report(snapshot, now) if (snapshot and prefs["alerts"]) else None
            if report is not None:
                body = "共 %s Token" % fmt_grouped(report["tokens"])
                if report["cost_cny"] is not None:
                    body += "，估算 ¥%s" % fmt_grouped(report["cost_cny"], 2)
                body += "，%s 最高产。" % app_label(report["top_app"])
                reminders.append({"id": "daily|" + report["date"], "kind": "daily_report", "level": "0",
                                  "title": "昨日用量报告", "body": body, "tone": "info", "priority": 10,
                                  "source": None, "action": {"kind": "open_panel", "tab": "usage"}})
            quiet = self._in_quiet_hours(prefs["quiet_hours"], now)
            if quiet:
                reminders = [r for r in reminders if r["tone"] == "danger"]
            reminders.sort(key=lambda r: (-r["priority"], r["id"]))
            for r in reminders:
                r["text"] = short_text(r)
            reminders = reminders[:8]

            focus_state = None
            if self.focus is not None:
                if now >= self.focus["ends_at"]:
                    self._react("celebrate", "focus-done|%d" % int(self.focus["started"]), now, "focus_done")
                    self.focus = None
                else:
                    focus_state = {"active": True, "ends_at": self.focus["ends_at"], "minutes": self.focus["minutes"]}
            focus = focus_state or {"active": False, "ends_at": None, "minutes": None}

            forecast = forecast_view(snapshot, now)
            forecast_out = {"known": forecast is not None, "mood": forecast[0] if forecast else None,
                            "median_48h": forecast[1] if forecast else None}

            painting = sum(int(r.get("generating_calls") or 0) for r in rows if r.get("app") == "codex_images"
                           and r.get("status") == "running")
            apps = {}
            for row in running_rows:
                entry = apps.setdefault(row.get("app"), {"app": row.get("app"), "label": app_label(row.get("app")),
                                                         "count": 0, "project": row.get("project_alias")})
                entry["count"] += 1
            for key in hook_only:
                event = hook_running[key]
                apps[key] = {"app": key, "label": app_label(key), "count": 1, "project": event.get("project")}
            finished = []
            for row in rows:
                if row.get("status") in ("completed", "failed"):
                    last = _epoch(row.get("last_event_at"))
                    if last is not None and 0 <= now - last <= 600:
                        finished.append({"app": row.get("app"), "label": app_label(row.get("app")),
                                         "status": row["status"], "project": row.get("project_alias"),
                                         "ago": int(now - last)})
            finished.sort(key=lambda f: f["ago"])
            newest = max([_epoch(r.get("last_event_at")) or 0 for r in rows] + [e["at"] for e in self.events] + [0])
            idle_for = now - newest if newest else None
            activity_known = activity is not None

            today = None
            usage = (snapshot or {}).get("application_usage")
            if isinstance(usage, dict):
                values = [(v.get("today") or {}).get("total_tokens") for v in usage.values() if isinstance(v, dict)]
                values = [v for v in values if isinstance(v, int) and not isinstance(v, bool)]
                today = sum(values) if values else None

            alert_soon = [r for r in reminders if r["kind"] in ("reset_card", "credit", "renewal", "membership")
                          and r["level"] in ("1", "0")]
            waiting = max(waiting_events.values(), key=lambda e: e["at"]) if waiting_events else None
            reasons = []
            state = self._arbitrate(offline, energy, state_tone, running, painting, waiting, bool(alert_soon),
                                    focus["active"], forecast_out["mood"], quiet, idle_for, prefs,
                                    activity_known, now, reasons)
            reaction = self._active_reaction(now)
            mood = self._mood(state, state_tone, energy, reaction)
            snapshot_age = now - _epoch(snapshot["collected_at"]) if snapshot and _epoch(snapshot.get("collected_at")) else None
            reasons.insert(0, "state=" + state)
            if energy["known"]:
                reasons.append("energy=%s(%s)" % (tone, fmt_trim(energy["remaining"])))
            return {
                "schema_version": SCHEMA_VERSION, "generated_at": now, "state": state,
                "state_since": self._state_since(state, now), "intensity": self._intensity(state, energy, running, threshold),
                "mood": mood, "reaction": reaction, "energy": energy, "meters": hud,
                "activity": {"known": activity_known, "running": running, "apps": list(apps.values()),
                             "recent_finished": finished[:3], "generating_images": painting},
                "forecast": forecast_out,
                "today": {"known": today is not None, "tokens": today},
                "focus": focus, "reminders": reminders,
                "events": [{"id": e["id"], "kind": e["kind"], "source": e["source"], "text": e["text"],
                            "at": e["at"], "ttl": e["ttl"]} for e in list(self.events)[-10:]],
                "honesty": {"quota_known": energy["known"], "activity_known": activity_known,
                            "snapshot_age": round(snapshot_age, 1) if snapshot_age is not None else None,
                            "stale_sources": sorted({m["source"] for m in meters if m["stale"]})},
                "reasons": reasons,
            }

    # ---- pieces of the frame

    def _arbitrate(self, offline, energy, tone, running, painting, waiting, alert_due, focusing,
                   forecast_mood_value, quiet, idle_for, prefs, activity_known, now, reasons):
        """First matching rule wins; the order is the table in the plan document, section 5."""
        if offline:
            reasons.append("backend=offline")
            return "offline"
        if tone == "empty":
            return "exhausted"
        if tone == "critical":
            return "alarm"
        if waiting is not None:
            reasons.append("waiting=" + (waiting["source"] or "agent"))
            return "waiting"
        if painting:
            reasons.append("images.generating=%d" % painting)
            return "painting"
        if running >= 3:
            reasons.append("activity.running=%d" % running)
            return "busy"
        if running >= 1:
            reasons.append("activity.running=%d" % running)
            return "working"
        if quiet:
            reasons.append("quiet_hours")
            return "sleeping"
        if tone == "low":
            return "tired"
        if alert_due:
            reasons.append("reminder.within_24h")
            return "alert"
        if focusing:
            return "focus"
        if forecast_mood_value in ("resetting", "excited"):
            reasons.append("forecast=" + forecast_mood_value)
            return "excited"
        if energy["stale"]:
            # Every window we could read is old: say "not sure", never "empty".
            reasons.append("quota=stale")
            return "confused"
        sleep_after = prefs["sleep_after_minutes"] * 60
        settled = now - self.started_at >= 120
        if settled and activity_known and (idle_for is None or idle_for >= sleep_after):
            reasons.append("idle>=%dm" % prefs["sleep_after_minutes"])
            return "sleeping"
        return "idle"

    REACTION_MOOD = {"celebrate": "excited", "startle": "surprised", "wave": "happy", "eating": "happy",
                     "painting": "happy"}

    @classmethod
    def _mood(cls, state, tone, energy, reaction):
        if reaction is not None and state not in ("offline", "exhausted", "alarm"):
            return cls.REACTION_MOOD[reaction["id"]]
        if state in ("offline", "confused"):
            return "confused"
        if state == "exhausted":
            return "sad"
        if state in ("alarm", "tired"):
            return "worried"
        if state in ("busy", "working"):
            return "worried" if tone == "low" else "determined"
        if state == "alert":
            return "surprised"
        if state == "focus":
            return "determined"
        if state == "excited":
            return "excited"
        if state == "sleeping":
            return "sleepy"
        if state in ("waiting", "painting"):
            return "happy"
        return "happy" if (energy["known"] and (energy["remaining"] or 0) >= 60) else "neutral"

    def _intensity(self, state, energy, running, threshold):
        remaining = energy["remaining"]
        if state == "busy":
            return round(min(1.0, 0.6 + 0.1 * running), 2)
        if state == "working":
            return round(min(1.0, 0.35 + 0.25 * running), 2)
        if state == "tired" and remaining is not None:
            return round(min(1.0, max(0.2, 1 - remaining / max(threshold, 1.0))), 2)
        if state == "alarm" and remaining is not None:
            return round(min(1.0, max(0.5, 1 - remaining / 5.0)), 2)
        if state in ("exhausted", "waiting", "alert", "offline"):
            return 1.0
        if state == "sleeping":
            return 0.2
        return 0.5

    def _state_since(self, state, now):
        if self._last_state != state:
            self._last_state = state
            self._last_state_at = now
        return self._last_state_at

    def _track_busy(self, running, now):
        """Minutes of uninterrupted activity; a 10 minute gap starts a new stretch."""
        if running:
            self._busy_gap_since = None
            if self._busy_since is None:
                self._busy_since = now
            return int((now - self._busy_since) // 60)
        if self._busy_since is not None:
            if self._busy_gap_since is None:
                self._busy_gap_since = now
            if now - self._busy_gap_since >= 600:
                self._busy_since = self._busy_gap_since = None
                return 0
            return int((now - self._busy_since) // 60)
        return 0

    @staticmethod
    def _in_quiet_hours(spec, now):
        if not spec:
            return False
        match = QUIET_RE.match(spec)
        start, end = int(match.group(1)) * 60 + int(match.group(2)), int(match.group(3)) * 60 + int(match.group(4))
        local = datetime.fromtimestamp(now)
        minute = local.hour * 60 + local.minute
        if start == end:
            return False
        return start <= minute < end if start < end else (minute >= start or minute < end)
