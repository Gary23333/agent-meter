"""Card collection and medals built from data the backend already reads.

Nothing here talks to a provider. Inputs are the fresh snapshot (quota
windows, reset cards, local token ledgers, Qoder credits) and the rewards
ledger (daily check-ins, task claims).

Two kinds of trophies:

- **Cards** drop on events. Quota cards drop when a 5-hour or 7-day window
  resets: one card per finished window, the highest tier its peak usage
  reached. Reset-card cards drop when a reset card leaves the inventory
  (used before expiry, or expired unused). Check-in cards come from the
  rewards ledger. Cards repeat; the binder counts copies.
- **Medals** are milestones recomputed from history every time (single-day
  tokens, lifetime tokens, active streaks, apps in one day, personal records,
  free credits). Old history therefore unlocks medals on first launch.

Window peaks and reset-card inventories have no history of their own, so
``<runtime>/collection.json`` (0600) keeps open windows, the last inventory
and the drops they produced. It holds no credentials or conversation text.
"""
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .model import timestamp

LEDGER_NAME = "collection.json"
LEDGER_SCHEMA = 1
CN = timezone(timedelta(hours=8))
MAX_DROPS = 3000
RECENT = 12
# A provider's reset time drifts by seconds between reads; a larger jump is a new window.
RESET_JITTER = 600
FULL = 99.5

RARITIES = ("common", "rare", "epic", "legendary", "faded")

# id, name, series, rarity, SF Symbol, description
CARDS = [
    ("q5_50", "热身完毕", "five_hour", "common", "flame", "5 小时窗口结算时用到 50% 以上"),
    ("q5_80", "八分饱", "five_hour", "rare", "flame.fill", "5 小时窗口结算时用到 80% 以上"),
    ("q5_90", "九成功力", "five_hour", "epic", "bolt.fill", "5 小时窗口结算时用到 90% 以上"),
    ("q5_full", "满载而归", "five_hour", "legendary", "crown.fill", "5 小时窗口在重置前用满"),
    ("q7_50", "周中漫步", "seven_day", "common", "figure.walk", "7 天窗口结算时用到 50% 以上"),
    ("q7_80", "周常达人", "seven_day", "rare", "figure.run", "7 天窗口结算时用到 80% 以上"),
    ("q7_90", "极限一周", "seven_day", "epic", "bolt.shield.fill", "7 天窗口结算时用到 90% 以上"),
    ("q7_full", "七日满贯", "seven_day", "legendary", "trophy.fill", "7 天窗口在重置前用满"),
    ("rc_saved", "物尽其用", "reset_card", "epic", "ticket.fill", "重置卡在过期前用掉"),
    ("rc_wasted", "白白过期", "reset_card", "faded", "hourglass.bottomhalf.filled", "重置卡没用就过期了"),
    ("ck_daily", "每日签到", "checkin", "common", "calendar.badge.checkmark", "领到当天的签到积分"),
    ("ck_7", "七日之约", "checkin", "rare", "7.circle.fill", "连续签到满 7 天（每 7 天一张）"),
    ("ck_30", "月度全勤", "checkin", "epic", "30.circle.fill", "连续签到满 30 天"),
    ("ck_100", "百日筑基", "checkin", "legendary", "laurel.leading", "连续签到满 100 天"),
    ("ck_task", "任务完成", "checkin", "common", "checklist", "领到一份任务奖励"),
    ("ck_badge", "徽章猎人", "checkin", "rare", "rosette", "任务奖励附带一枚官方徽章"),
    ("sp_welcome", "启程", "special", "rare", "sparkles", "打开卡册的第一天，收集从这里开始"),
]
SERIES = {"five_hour": "5 小时窗口", "seven_day": "7 天窗口", "reset_card": "重置卡", "checkin": "签到与任务", "special": "纪念"}
CARD_IDS = {c[0] for c in CARDS}
QUOTA_TIERS = {"five_hour": [(FULL, "q5_full"), (90, "q5_90"), (80, "q5_80"), (50, "q5_50")],
               "seven_day": [(FULL, "q7_full"), (90, "q7_90"), (80, "q7_80"), (50, "q7_50")]}

YI = 100_000_000
# id, name, category, target, unit, SF Symbol, tier
MEDALS = [
    ("day_1", "亿级玩家", "day_peak", 1 * YI, "tokens", "sun.min.fill", "bronze"),
    ("day_5", "五亿狂飙", "day_peak", 5 * YI, "tokens", "sun.max.fill", "silver"),
    ("day_10", "十亿日", "day_peak", 10 * YI, "tokens", "sparkles", "gold"),
    ("day_50", "五十亿传说", "day_peak", 50 * YI, "tokens", "flame.circle.fill", "platinum"),
    ("life_10", "十亿里程", "lifetime", 10 * YI, "tokens", "road.lanes", "bronze"),
    ("life_100", "百亿里程", "lifetime", 100 * YI, "tokens", "airplane", "silver"),
    ("life_1000", "千亿里程", "lifetime", 1000 * YI, "tokens", "globe.asia.australia.fill", "gold"),
    ("life_10000", "万亿星辰", "lifetime", 10000 * YI, "tokens", "moon.stars.fill", "platinum"),
    ("streak_7", "一周不停", "streak", 7, "days", "calendar", "bronze"),
    ("streak_30", "月度常驻", "streak", 30, "days", "calendar.circle.fill", "silver"),
    ("streak_100", "百日连击", "streak", 100, "days", "flame.fill", "gold"),
    ("streak_365", "全年无休", "streak", 365, "days", "infinity.circle.fill", "platinum"),
    ("apps_3", "三栖开发", "apps", 3, "apps", "square.stack.3d.up.fill", "bronze"),
    ("apps_5", "五路并进", "apps", 5, "apps", "square.grid.3x3.fill", "silver"),
    ("apps_8", "全家桶", "apps", 8, "apps", "shippingbox.fill", "gold"),
    ("pr_1", "刷新纪录", "record", 1, "times", "chart.line.uptrend.xyaxis", "bronze"),
    ("pr_10", "纪录收割机", "record", 10, "times", "medal.fill", "gold"),
    ("free_1k", "白嫖入门", "free", 1_000, "credits", "gift.fill", "bronze"),
    ("free_10k", "白嫖大师", "free", 10_000, "credits", "giftcard.fill", "silver"),
    ("free_100k", "羊毛宗师", "free", 100_000, "credits", "crown.fill", "gold"),
    # API-equivalent spending (local price table, in CNY).
    ("cost_day_100", "小试牛刀", "cost_day", 100, "cny", "yensign.circle.fill", "bronze"),
    ("cost_day_500", "挥金如土", "cost_day", 500, "cny", "banknote.fill", "silver"),
    ("cost_day_1k", "千金一日", "cost_day", 1_000, "cny", "creditcard.fill", "gold"),
    ("cost_day_5k", "一掷千金", "cost_day", 5_000, "cny", "diamond.fill", "platinum"),
    ("cost_month_3k", "月光族", "cost_month", 3_000, "cny", "moon.fill", "bronze"),
    ("cost_month_10k", "万元月", "cost_month", 10_000, "cny", "moon.stars.fill", "silver"),
    ("cost_month_30k", "三万大关", "cost_month", 30_000, "cny", "sparkles.rectangle.stack.fill", "gold"),
    ("cost_month_100k", "十万火急", "cost_month", 100_000, "cny", "flame.circle.fill", "platinum"),
    ("cost_life_10k", "万元户", "cost_life", 10_000, "cny", "house.fill", "bronze"),
    ("cost_life_50k", "Token 小康", "cost_life", 50_000, "cny", "building.2.fill", "silver"),
    ("cost_life_100k", "十万雄兵", "cost_life", 100_000, "cny", "building.columns.fill", "gold"),
    ("cost_life_1m", "百万富翁", "cost_life", 1_000_000, "cny", "crown.fill", "platinum"),
    # Image generation (Codex built-in image_gen files) and creative credits.
    ("img_day_10", "灵感速写", "img_day", 10, "images", "pencil.and.scribble", "bronze"),
    ("img_day_50", "画室开张", "img_day", 50, "images", "paintbrush.fill", "silver"),
    ("img_day_100", "百图斩", "img_day", 100, "images", "paintpalette.fill", "gold"),
    ("img_day_300", "印钞机", "img_day", 300, "images", "printer.fill", "platinum"),
    ("img_life_100", "百图集", "img_life", 100, "images", "photo.fill", "bronze"),
    ("img_life_1k", "千图展", "img_life", 1_000, "images", "photo.on.rectangle.angled", "silver"),
    ("img_life_5k", "美术馆", "img_life", 5_000, "images", "building.columns.fill", "gold"),
    ("img_life_20k", "万象画廊", "img_life", 20_000, "images", "photo.stack.fill", "platinum"),
    ("img_streak_3", "三日作画", "img_streak", 3, "days", "camera.fill", "bronze"),
    ("img_streak_7", "一周画展", "img_streak", 7, "days", "camera.aperture", "silver"),
    ("img_streak_30", "月月出片", "img_streak", 30, "days", "film.stack.fill", "gold"),
    ("creative_1k", "初露锋芒", "creative", 1_000, "credits", "wand.and.stars", "bronze"),
    ("creative_10k", "创作达人", "creative", 10_000, "credits", "theatermasks.fill", "silver"),
    ("creative_100k", "造梦大师", "creative", 100_000, "credits", "sparkles.tv.fill", "gold"),
]
CATEGORIES = {"day_peak": "单日巅峰", "lifetime": "累计里程", "streak": "连续出勤", "apps": "多端并用",
              "record": "个人纪录", "free": "免费额度", "cost_day": "单日估算花费", "cost_month": "月度估算花费",
              "cost_life": "累计估算价值", "img_day": "单日出图", "img_life": "累计出图", "img_streak": "连续出图",
              "creative": "创作积分"}
# Creative wallets whose balance drops count as credits spent (即梦, MiniMax Design).
CREATIVE_UNITS = {"dreamina_credits", "minimax_design_media_credits"}
# Matches prices.FX_FALLBACK; the menu bar shows every amount in CNY.
USD_TO_CNY = 7.25


def day_of(epoch):
    return datetime.fromtimestamp(epoch, CN).strftime("%Y-%m-%d")


def _epoch(value):
    if isinstance(value, dict):
        value = value.get("epoch_seconds")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _number(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        return None


def _day_epoch(date):
    return datetime.strptime(date, "%Y-%m-%d").replace(hour=23, minute=59, tzinfo=CN).timestamp()


# --- window classification ------------------------------------------------

UNIT_MINUTES = {"minute": 1, "hour": 60, "day": 1440, "week": 10080}
BUCKET_MINUTES = {"five_hour": 300, "5h": 300, "seven_day": 10080, "week": 10080, "weekly": 10080}


def window_kind(row):
    minutes = row.get("window_minutes")
    window = row.get("window")
    if not isinstance(minutes, (int, float)) and isinstance(window, dict):
        unit = UNIT_MINUTES.get(str(window.get("unit", "")).lower().rstrip("s"))
        if unit and isinstance(window.get("duration"), (int, float)):
            minutes = unit * window["duration"]
    if not isinstance(minutes, (int, float)):
        minutes = BUCKET_MINUTES.get(str(row.get("bucket", "")).lower())
    if not isinstance(minutes, (int, float)):
        return None
    if 240 <= minutes <= 360:
        return "five_hour"
    if 9000 <= minutes <= 11000:
        return "seven_day"
    return None


def quota_card(kind, peak):
    for threshold, card in QUOTA_TIERS[kind]:
        if peak >= threshold:
            return card
    return None


def next_tier(kind, peak):
    for threshold, card in reversed(QUOTA_TIERS[kind]):
        if peak < threshold:
            return card, threshold
    return None, None


# --- ledger ---------------------------------------------------------------

def empty_ledger():
    return {"schema": LEDGER_SCHEMA, "windows": {}, "inventory": {}, "drops": [], "creative": {}}


def load_ledger(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty_ledger()
    if not isinstance(data, dict) or data.get("schema") != LEDGER_SCHEMA:
        return empty_ledger()
    for key, kind in (("windows", dict), ("inventory", dict), ("drops", list), ("creative", dict)):
        if not isinstance(data.get(key), kind):
            data[key] = kind()
    return data


def save_ledger(path, ledger):
    ledger["drops"] = ledger["drops"][-MAX_DROPS:]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        temp = Path(handle.name)
        json.dump(ledger, handle, ensure_ascii=False, indent=1, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temp, 0o600)
    os.replace(temp, path)


def _live(src):
    return src.get("status") in {"available", "partial"} and not src.get("scope", "").startswith("local_")


def track_windows(ledger, sources, now):
    """Updates open-window peaks; settles windows whose reset passed. Returns True on change."""
    changed = False
    seen = set()
    for src in sources:
        if not _live(src):
            continue
        quota = (src.get("metrics", {}).get("quota") or {})
        if quota.get("status") not in {"available", "partial"} or not isinstance(quota.get("value"), list):
            continue
        for row in quota["value"]:
            if not isinstance(row, dict):
                continue
            kind, reset = window_kind(row), _epoch(row.get("resets_at"))
            used = _number(row.get("used_percent"))
            if kind is None or reset is None or used is None:
                continue
            key = "%s|%s|%s" % (src["id"], row.get("bucket"), kind)
            if key in seen:
                continue
            seen.add(key)
            state = ledger["windows"].get(key)
            if state and abs(state["resets_at"] - reset) > RESET_JITTER:
                _settle(ledger, key, state)
                state = None
                changed = True
            if state is None:
                ledger["windows"][key] = {"source": src["id"], "bucket": row.get("bucket"), "kind": kind,
                                          "resets_at": reset, "peak": used, "first_at": now, "last_at": now}
                changed = True
            else:
                if used > state["peak"]:
                    state["peak"] = used
                    changed = True
                state["last_at"] = now
                state["resets_at"] = reset
    # A window whose source vanished but whose reset passed long ago is settled too.
    for key, state in list(ledger["windows"].items()):
        if key not in seen and now - state["resets_at"] > 86400:
            _settle(ledger, key, state)
            changed = True
    return changed


def _settle(ledger, key, state):
    ledger["windows"].pop(key, None)
    card = quota_card(state["kind"], state["peak"])
    if card:
        ledger["drops"].append({"card": card, "at": min(state["resets_at"], state["last_at"] + RESET_JITTER),
                                "source": state["source"], "detail": "峰值 %d%%" % round(state["peak"])})


def track_reset_cards(ledger, sources, now):
    changed = False
    for src in sources:
        if not _live(src):
            continue
        metric = src.get("metrics", {}).get("reset_cards") or {}
        value = metric.get("value")
        if metric.get("status") not in {"available", "partial"} or not isinstance(value, dict):
            continue
        cards = [c for c in value.get("cards") or [] if isinstance(c, dict)
                 and c.get("status", "available") == "available"]
        expiries = sorted(int(e) for e in (_epoch(c.get("expires_at")) for c in cards) if e is not None)
        count = value.get("available_count")
        count = int(count) if isinstance(count, (int, float)) and not isinstance(count, bool) else len(cards)
        next_known = _epoch(value.get("next_known_expiry")) or (expiries[0] if expiries else None)
        current = {"count": count, "expiries": expiries, "next": next_known}
        previous = ledger["inventory"].get(src["id"])
        if previous != current:
            changed = True
        ledger["inventory"][src["id"]] = current
        if not previous or count >= previous["count"]:
            continue
        gone = []
        if previous["expiries"]:
            remaining = list(expiries)
            for e in previous["expiries"]:
                if e in remaining:
                    remaining.remove(e)
                else:
                    gone.append(e)
        gone = (gone + [previous.get("next")] * (previous["count"] - count))[:previous["count"] - count]
        for expiry in gone:
            wasted = expiry is not None and now >= expiry - 60
            ledger["drops"].append({"card": "rc_wasted" if wasted else "rc_saved", "at": now, "source": src["id"],
                                    "detail": "到期 " + day_of(expiry) if expiry else None})
    return changed


def track_creative(ledger, sources, now):
    """Adds balance drops of creative wallets to a running "spent" total.

    Increases (top-ups, monthly refills) only move the baseline. History before
    the first observation is unknown and never counted.
    """
    changed = False
    for src in sources:
        if not _live(src):
            continue
        value = (src.get("metrics", {}).get("credits") or {}).get("value")
        if not isinstance(value, dict) or value.get("unit") not in CREATIVE_UNITS:
            continue
        balance = _number(value.get("balance"))
        if balance is None:
            continue
        state = ledger["creative"].setdefault(src["id"], {"balance": balance, "spent": 0.0, "since": now, "days": {}})
        if balance < state["balance"]:
            spent = state["balance"] - balance
            state["spent"] += spent
            day = day_of(now)
            state["days"][day] = state["days"].get(day, 0) + spent
            changed = True
        if balance != state["balance"]:
            state["balance"] = balance
            changed = True
    return changed


def daily_images(sources):
    days = {}
    for src in sources:
        metric = src.get("metrics", {}).get("image_generation") or {}
        value = metric.get("value")
        if metric.get("status") not in {"available", "partial", "stale"} or not isinstance(value, dict):
            continue
        for row in value.get("daily_buckets") or []:
            images = _number(row.get("images")) if isinstance(row, dict) else None
            if images and isinstance(row.get("date"), str):
                days[row["date"]] = days.get(row["date"], 0) + images
    return days


# --- derived drops --------------------------------------------------------

def checkin_drops(rewards_ledger):
    drops = []
    for slot, account in ((rewards_ledger or {}).get("accounts") or {}).items():
        days = account.get("days") or {}
        streak, previous = 0, None
        for date in sorted(days):
            record = days[date]
            status = record.get("status") or {}
            claims = record.get("claims") or []
            for claim in claims:
                if claim.get("result") != "ok":
                    continue
                at = _epoch(claim.get("at")) or _day_epoch(date)
                if str(claim.get("item", "")).startswith("task:"):
                    drops.append({"card": "ck_task", "at": at, "source": slot, "detail": claim.get("title")})
                    if claim.get("badge"):
                        drops.append({"card": "ck_badge", "at": at, "source": slot, "detail": claim.get("badge")})
            signed = status.get("signed_in") is True or any(c.get("result") == "ok" and c.get("item") == "daily_checkin"
                                                            for c in claims)
            if not signed:
                continue
            day = datetime.strptime(date, "%Y-%m-%d")
            streak = streak + 1 if previous and (day - previous).days == 1 else 1
            previous = day
            at = _day_epoch(date) if date != max(days) else min(_day_epoch(date), account.get("checked_at") or _day_epoch(date))
            drops.append({"card": "ck_daily", "at": at, "source": slot, "detail": "连续第 %d 天" % streak})
            for size, card in ((7, "ck_7"), (30, "ck_30"), (100, "ck_100")):
                if streak % size == 0:
                    drops.append({"card": card, "at": at, "source": slot, "detail": "连续 %d 天" % streak})
    return drops


# --- medals ---------------------------------------------------------------

def daily_tokens(sources):
    totals, apps = {}, {}
    for src in sources:
        metric = src.get("metrics", {}).get("tokens") or {}
        value = metric.get("value")
        if metric.get("status") not in {"available", "partial", "stale"} or not isinstance(value, dict):
            continue
        for bucket in value.get("daily_buckets") or []:
            if not isinstance(bucket, dict) or not isinstance(bucket.get("date"), str):
                continue
            tokens = _number(bucket.get("tokens")) or 0
            if tokens <= 0:
                continue
            totals[bucket["date"]] = totals.get(bucket["date"], 0) + tokens
            if src["id"] != "imported_history":
                apps.setdefault(bucket["date"], set()).add(src["id"].split("#", 1)[0])
    return totals, {d: len(v) for d, v in apps.items()}


def daily_cost(sources):
    """CNY per day from each source's estimated cost (off-peak daily pricing)."""
    days = {}
    for src in sources:
        metric = src.get("metrics", {}).get("cost") or {}
        value = metric.get("value")
        if metric.get("status") not in {"available", "partial", "stale"} or not isinstance(value, dict) \
                or value.get("basis") != "local_price_table":
            continue
        rate = USD_TO_CNY if value.get("unit") == "USD" else 1.0
        for row in value.get("daily") or []:
            amount = _number(row.get("amount")) if isinstance(row, dict) else None
            if amount and isinstance(row.get("date"), str):
                days[row["date"]] = days.get(row["date"], 0) + amount * rate
    return days


def streaks(dates, today):
    longest = current = run = 0
    previous = None
    for date in sorted(dates):
        day = datetime.strptime(date, "%Y-%m-%d")
        run = run + 1 if previous and (day - previous).days == 1 else 1
        longest = max(longest, run)
        previous = day
    if previous is not None:
        gap = (datetime.strptime(today, "%Y-%m-%d") - previous).days
        current = run if gap <= 1 else 0
    return current, longest


def free_credits(sources, rewards_summary):
    total = 0.0
    for src in sources:
        credits = (src.get("metrics", {}).get("credits") or {}).get("value")
        usage = credits.get("usage") if isinstance(credits, dict) else None
        totals = ((usage or {}).get("periods") or {}).get("all", {}).get("totals") if isinstance(usage, dict) else None
        if isinstance(totals, dict):
            all_credits, billable = _number(totals.get("credits")), _number(totals.get("billable_credits"))
            if all_credits is not None and billable is not None:
                total += max(0.0, all_credits - billable)
    for account in (rewards_summary or {}).get("accounts") or []:
        total += _number(account.get("claimed_credits_total")) or 0
    return total


def medals(sources, rewards_summary, now, creative=None):
    today = day_of(now)
    totals, apps = daily_tokens(sources)
    dates = sorted(totals)
    best_date = max(dates, key=lambda d: totals[d]) if dates else None
    lifetime = sum(totals.values())
    current, longest = streaks(dates, today)
    # Personal records: days that beat every earlier day (the first active day does not count).
    records, best = [], 0
    for date in dates:
        if totals[date] > best:
            if best > 0:
                records.append(date)
            best = totals[date]
    free = free_credits(sources, rewards_summary)
    costs = daily_cost(sources)
    cost_dates = sorted(costs)
    images = daily_images(sources)
    image_dates = sorted(images)
    creative_days = {}
    for state in (creative or {}).values():
        for d, v in (state.get("days") or {}).items():
            creative_days[d] = creative_days.get(d, 0) + v
    months = {}
    for date in cost_dates:
        months[date[:7]] = months.get(date[:7], 0) + costs[date]
    out = []
    for medal_id, name, category, target, unit, symbol, tier in MEDALS:
        earned_at, count = None, 0
        if category == "day_peak":
            hits = [d for d in dates if totals[d] >= target]
            count, value = len(hits), totals[best_date] if best_date else 0
            earned_at = hits[0] if hits else None
        elif category == "lifetime":
            value, running = lifetime, 0
            for date in dates:
                running += totals[date]
                if running >= target:
                    earned_at = date
                    break
        elif category == "streak":
            value = current
            if longest >= target:
                earned_at, count = _streak_reached(dates, target), 1
        elif category == "apps":
            hits = [d for d in sorted(apps) if apps[d] >= target]
            value, count = max(apps.values(), default=0), len(hits)
            earned_at = hits[0] if hits else None
        elif category == "record":
            value, count = len(records), len(records)
            earned_at = records[target - 1] if len(records) >= target else None
        elif category == "cost_day":
            hits = [d for d in cost_dates if costs[d] >= target]
            value, count = max(costs.values(), default=0), len(hits)
            earned_at = hits[0] if hits else None
        elif category == "cost_month":
            hits = [m for m in sorted(months) if months[m] >= target]
            value, count = max(months.values(), default=0), len(hits)
            # The month is reached on the day its running total crosses the target.
            if hits:
                running = 0
                for date in cost_dates:
                    if date[:7] == hits[0]:
                        running += costs[date]
                        if running >= target:
                            earned_at = date
                            break
        elif category == "img_day":
            hits = [d for d in image_dates if images[d] >= target]
            value, count = max(images.values(), default=0), len(hits)
            earned_at = hits[0] if hits else None
        elif category == "img_life":
            value, running = sum(images.values()), 0
            for date in image_dates:
                running += images[date]
                if running >= target:
                    earned_at = date
                    break
        elif category == "img_streak":
            value = streaks(image_dates, today)[0]
            reached = _streak_reached(image_dates, target)
            earned_at, count = reached, 1 if reached else 0
        elif category == "creative":
            value, running = sum(creative_days.values()), 0
            for date in sorted(creative_days):
                running += creative_days[date]
                if running >= target:
                    earned_at = date
                    break
        elif category == "cost_life":
            value, running = sum(costs.values()), 0
            for date in cost_dates:
                running += costs[date]
                if running >= target:
                    earned_at = date
                    break
        else:
            value = free
            earned_at = today if free >= target else None
        out.append({"id": medal_id, "name": name, "category": category, "category_name": CATEGORIES[category],
                    "target": target, "unit": unit, "symbol": symbol, "tier": tier, "value": value,
                    "progress": min(1.0, value / target) if target else 0.0, "earned": earned_at is not None,
                    "earned_on": earned_at, "count": count if category in {"day_peak", "apps", "record", "cost_day", "cost_month", "img_day"} else (1 if earned_at else 0)})
    stats = {"lifetime_tokens": lifetime, "active_days": len(dates), "current_streak": current,
             "longest_streak": longest, "record_breaks": len(records), "free_credits": free,
             "best_day": {"date": best_date, "tokens": totals[best_date]} if best_date else None,
             "today_tokens": totals.get(today, 0), "max_apps_in_day": max(apps.values(), default=0),
             "lifetime_cost_cny": sum(costs.values()),
             "best_cost_day": {"date": max(costs, key=costs.get), "cny": max(costs.values())} if costs else None,
             "best_cost_month": {"month": max(months, key=months.get), "cny": max(months.values())} if months else None,
             "lifetime_images": sum(images.values()),
             "best_image_day": {"date": max(images, key=images.get), "images": max(images.values())} if images else None,
             "creative_credits_spent": sum(creative_days.values())}
    return out, stats


def _streak_reached(dates, target):
    run, previous = 0, None
    for date in dates:
        day = datetime.strptime(date, "%Y-%m-%d")
        run = run + 1 if previous and (day - previous).days == 1 else 1
        previous = day
        if run >= target:
            return date
    return None


# --- assembly -------------------------------------------------------------

class CollectionService:
    def __init__(self, runtime_dir):
        self.path = Path(runtime_dir) / LEDGER_NAME
        self.ledger = load_ledger(self.path)
        self.fresh = not self.ledger["drops"] and not self.ledger["windows"] and not self.ledger["inventory"]

    def update(self, snapshot, rewards_ledger, now):
        sources = snapshot.get("sources") or []
        changed = False
        if self.fresh:
            self.ledger["drops"].append({"card": "sp_welcome", "at": now, "source": None, "detail": None})
            self.fresh, changed = False, True
        changed |= track_windows(self.ledger, sources, now)
        changed |= track_reset_cards(self.ledger, sources, now)
        changed |= track_creative(self.ledger, sources, now)
        if changed:
            try:
                save_ledger(self.path, self.ledger)
            except OSError:
                pass
        return build(self.ledger, sources, rewards_ledger, snapshot.get("rewards"), now)


def build(ledger, sources, rewards_ledger, rewards_summary, now):
    drops = [d for d in ledger["drops"] + checkin_drops(rewards_ledger) if d.get("card") in CARD_IDS]
    drops.sort(key=lambda d: d["at"])
    owned = {}
    for drop in drops:
        entry = owned.setdefault(drop["card"], {"count": 0, "first_at": drop["at"], "sources": []})
        entry["count"] += 1
        entry["last_at"] = drop["at"]
        base = str(drop.get("source") or "").split("#", 1)[0]
        if base and base not in entry["sources"]:
            entry["sources"].append(base)
    cards = {cid: {"count": e["count"], "first_at": timestamp(e["first_at"]), "last_at": timestamp(e["last_at"]),
                   "sources": e["sources"]} for cid, e in owned.items()}
    open_windows = []
    for state in ledger["windows"].values():
        card, threshold = next_tier(state["kind"], state["peak"])
        open_windows.append({"source": state["source"], "kind": state["kind"], "peak": state["peak"],
                             "resets_at": timestamp(state["resets_at"]), "current_card": quota_card(state["kind"], state["peak"]),
                             "next_card": card, "next_threshold": threshold})
    open_windows.sort(key=lambda w: w["resets_at"]["epoch_seconds"])
    medal_list, stats = medals(sources, rewards_summary, now, ledger.get("creative"))
    stats.update({"distinct_cards": len([c for c in cards if c != "rc_wasted"]),
                  "catalog_size": len([c for c in CARDS if c[3] != "faded"]),
                  "total_cards": sum(c["count"] for c in cards.values()),
                  "medals_earned": sum(m["earned"] for m in medal_list), "medals_total": len(medal_list)})
    by_rarity = {r: 0 for r in RARITIES}
    for cid, card in cards.items():
        by_rarity[next(c[3] for c in CARDS if c[0] == cid)] += card["count"]
    stats["by_rarity"] = by_rarity
    return {"schema_version": 1,
            "catalog": [{"id": c[0], "name": c[1], "series": c[2], "series_name": SERIES[c[2]], "rarity": c[3],
                         "symbol": c[4], "description": c[5]} for c in CARDS],
            "cards": cards,
            "recent": [{"card": d["card"], "at": timestamp(d["at"]), "source": d.get("source"), "detail": d.get("detail")}
                       for d in reversed(drops[-RECENT:])],
            "open_windows": open_windows, "medals": medal_list, "stats": stats}
