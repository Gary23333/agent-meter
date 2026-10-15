"""Global Codex reset forecasts from independent trackers.

A "Tibo reset" is a global limit reset with no fixed schedule. It is a different
event class from the account's own 5-hour / weekly windows, so it never writes
`reset_time` and never joins an account card.

Sites also keep internals that change without notice (willreset ran cadence-v1
in the morning and evidence-v2 the same afternoon, with raw_* going to zero), so
the pooled number is each site's own published answer and its internals stay
visible as metadata instead of becoming our input.
"""

import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .model import SourceError, metric, source, timestamp
from .transport import get_json, get_text

# All three sites answer Python's default User-Agent with 403.
USER_AGENT = "AgentMeter/0.5 (macOS menu bar usage app; read-only)"
JSON_HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}
HTML_HEADERS = {"User-Agent": USER_AGENT, "Accept": "text/html"}

CACHE_NAME = "reset-forecast.json"
REFRESH_MINUTES = 45
# A source that just failed gets retried soon instead of waiting out the throttle.
RETRY_MINUTES = 5
MAX_SOURCE_AGE_HOURS = 48
HISTORY_LIMIT = 40
SUMMARY_LIMIT = 240

DISCLAIMER = "第三方独立统计，与 OpenAI 无关；官方从未保证未来会重置，也不是你的账户周期时钟。"

SOURCES = {
    "willreset": {"name": "Will Codex Reset", "forecast": "https://willreset.com/api/forecast",
                  "history": "https://willreset.com/api/timeline"},
    "codex_reset": {"name": "Tibo Radar", "forecast": "https://codex-reset.com/api/forecast",
                    "history": "https://codex-reset.com/api/timeline"},
    "codexreset_org": {"name": "Codex Reset Monitor", "forecast": "https://codexreset.org/"},
}

# Weight inputs are the sources' own reported quality, not our judgement of them.
CONFIDENCE_WEIGHT = {"high": 1.0, "medium": 0.7, "low": 0.4}
UNKNOWN_CONFIDENCE_WEIGHT = 0.4
CALIBRATION_WEIGHT = {"calibrated": 1.25, "experimental": 0.8}
FRESH_NEAR_HOURS = 6
FRESH_MID_HOURS = 24


def _stamp(value):
    """ISO from these sites carries 9 fractional digits; 3.9 parses 6 at most."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or text.startswith("0001-01-01"):
        return None
    text = re.sub(r"(\.\d{6})\d+", r"\1", text)
    try:
        return timestamp(text)
    except SourceError:
        return None


def _percent(value):
    """0.184 and 18.4 mean the same here; each adapter knows its own units."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return round(value * 100, 2) if 0 <= value <= 1 else round(float(value), 2)


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return round(float(value), 4)


def _integer(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _pair(value):
    """Already-percent pairs (willreset ranges) as [low, high]."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    low, high = _number(value[0]), _number(value[1])
    return [low, high] if low is not None and high is not None and low <= high else None


def _fraction_pair(value):
    if not isinstance(value, dict):
        return None
    low, high = _percent(value.get("lower")), _percent(value.get("upper"))
    return [low, high] if low is not None and high is not None and low <= high else None


def _text(value, limit=SUMMARY_LIMIT):
    if not isinstance(value, str):
        return None
    text = re.sub(r"\s+", " ", value).strip()
    if not text:
        return None
    return (text[:limit] + "…") if len(text) > limit else text


def _url(value):
    return value[:200] if isinstance(value, str) and value.startswith("https://") else None


def _machine_window(value):
    """Only an unambiguous instant or an ISO pair becomes a countdown target."""
    if isinstance(value, str):
        at = _stamp(value)
        return {"close_at": at} if at else None
    if not isinstance(value, dict):
        return None
    out = {}
    for key in ("start", "from", "open", "window_start"):
        if _stamp(value.get(key)):
            out["open_at"] = _stamp(value[key])
            break
    for key in ("end", "until", "to", "close", "window_end", "expected_at", "at"):
        if _stamp(value.get(key)):
            out["close_at"] = _stamp(value[key])
            break
    return out or None


def normalize_willreset(payload, now):
    row = {"source": "willreset", "name": SOURCES["willreset"]["name"],
           "updated_at": _stamp(payload.get("computed_at")),
           "model_version": _text(payload.get("model_version"), 60),
           "raw_24h": _percent(payload.get("raw_24")), "raw_48h": _percent(payload.get("raw_48")),
           "band_24h": _pair(payload.get("range_24")), "band_48h": _pair(payload.get("range_48")),
           "headline_24h": _percent(payload.get("prob_24")), "headline_48h": _percent(payload.get("prob_48")),
           "answered": _text(payload.get("answer"), 40)}
    promise = payload.get("promise")
    if isinstance(promise, dict) and promise.get("active"):
        floor = _percent(promise.get("percent"))
        row["promise"] = {"label": _text(promise.get("label"), 120), "quote": _text(promise.get("quote"), 200),
                         "url": _url(promise.get("url")), "at": _stamp(promise.get("at")),
                         "floor_percent": floor,
                         # The site's own rule: a named clock scores 93, a bare
                         # promise 83. The clock itself stays inside prose.
                         "has_clock": floor == 93,
                         "basis": "third_party_promise_overlay"}
    row["self_reported"] = {"confidence": _text(payload.get("confidence"), 20),
                            "note": _text(payload.get("confidence_note")), "backtest": None, "calibration": None}
    row["cadence"] = {"interval_sample": _integer(payload.get("sample")),
                      "sample_basis": "all_verified_intervals",
                      "median_gap_days": _number(payload.get("median_gap_days")),
                      "mean_gap_days": _number(payload.get("mean_gap_days")),
                      "longest_gap_days": _number(payload.get("longest_gap_days")),
                      "age_days": _number(payload.get("age_days"))}
    row["last_reset"] = {"at": _stamp(payload.get("last_reset_at")), "post_id": _text(payload.get("last_reset_id"), 40),
                        "url": _url(payload.get("last_reset_url")), "text": _text(payload.get("last_reset_text"), 120)}
    hour = payload.get("peak_hour_utc")
    row["typical_window"] = {"label": _text(payload.get("peak_label"), 40), "timezone": "UTC",
                             "start_hour": hour if isinstance(hour, int) and not isinstance(hour, bool) else None,
                             "end_hour": None}
    return row


def normalize_codex_reset(payload, now):
    probabilities = payload.get("probabilities")
    if not isinstance(probabilities, dict):
        raise SourceError("unsupported_forecast_contract")
    model = payload.get("model")
    row = {"source": "codex_reset", "name": SOURCES["codex_reset"]["name"],
           "updated_at": _stamp(payload.get("updated_at")),
           "model_version": _text(model.get("version"), 60) if isinstance(model, dict) else None,
           "raw_24h": _percent(probabilities.get("raw_24h")), "raw_48h": _percent(probabilities.get("raw_48h")),
           # These ranges arrive as fractions, unlike willreset's.
           "band_24h": _fraction_pair(probabilities.get("range_24h")),
           "band_48h": _fraction_pair(probabilities.get("range_48h")),
           "headline_24h": _percent(probabilities.get("rounded_24h")),
           "headline_48h": _percent(probabilities.get("rounded_48h")),
           "signal_state": None, "latest_hint": None}
    tease = _machine_window(payload.get("teased_window")) or _machine_window(payload.get("official_signal"))
    if tease:
        row["promise"] = dict(tease, basis="third_party_announced_window",
                              quote=None, url=None, label=None, floor_percent=None, has_clock=True)
    backtest = payload.get("backtest")
    calibration = None
    if isinstance(backtest, dict):
        calibration = {"24h": {"brier": _number(backtest.get("brier")),
                               "sample": _integer(backtest.get("sample_size")),
                               "state": _text(backtest.get("status"), 20)},
                       "baseline_brier": _number(backtest.get("baseline_brier"))}
    row["self_reported"] = {"confidence": _text(payload.get("confidence"), 20),
                            "note": _text(payload.get("confidence_note")),
                            "backtest": calibration, "calibration": None}
    cadence = payload.get("cadence")
    wait = payload.get("wait_comparison")
    row["cadence"] = {"interval_sample": _integer(wait.get("sample")) if isinstance(wait, dict) else None,
                      "sample_basis": "recent_completed_intervals",
                      "recent_median_gap_days": _number(cadence.get("recent_median_days")) if isinstance(cadence, dict) else None,
                      "recent_interval_sample": _integer(cadence.get("recent_sample")) if isinstance(cadence, dict) else None,
                      "weighted_mean_gap_days": _number(cadence.get("weighted_mean_days")) if isinstance(cadence, dict) else None,
                      "median_gap_days": _number(wait.get("median_days")) if isinstance(wait, dict) else None,
                      "mean_gap_days": _number(wait.get("mean_days")) if isinstance(wait, dict) else None,
                      "longest_gap_days": _number(wait.get("longest_days")) if isinstance(wait, dict) else None,
                      "age_days": _number(payload.get("age_days"))}
    row["last_reset"] = {"at": _stamp(payload.get("last_reset_at")), "post_id": None, "url": None, "text": None}
    alert = payload.get("latest_alert")
    if isinstance(alert, dict):
        row["last_reset"] = {"at": _stamp(alert.get("observed_at") or alert.get("source_at")),
                             "post_id": _text(alert.get("id"), 40), "url": _url(alert.get("url")),
                             "text": _text(alert.get("summary"), 120),
                             "state": _text(alert.get("state"), 30),
                             "confirmed_by": _text(alert.get("confirmation_source"), 40)}
    window = payload.get("time_window")
    if isinstance(window, dict):
        row["typical_window"] = {"label": _text(window.get("label"), 40), "timezone": _text(window.get("timezone"), 20),
                                 "start_hour": _integer(window.get("start_hour")),
                                 "end_hour": _integer(window.get("end_hour"))}
    context = payload.get("context")
    if isinstance(context, dict):
        row["signal_state"] = _text(context.get("state"), 30)
        primary = context.get("primary_post")
        if isinstance(primary, dict):
            row["latest_hint"] = {"quote": _text(primary.get("quote"), 120), "url": _url(primary.get("url")),
                                  "at": _stamp(primary.get("at")), "signal": _text(primary.get("signal"), 20)}
    return row


ORG_REQUIRED = ("baseScore24h", "score24h", "score48h", "algorithmVersion",
                "forecastConfidence", "nextReassessmentAt", "horizonCalibration")


def _org_head(page):
    """score24h also repeats 400+ times in the history series, so reads stay
    inside the live forecast object head."""
    anchor = page.find("forecast:$R[")
    if anchor < 0:
        raise SourceError("forecast_object_not_found")
    head = page[anchor:anchor + 6000]
    cut = head.find("semanticSignals")
    if cut < 0:
        raise SourceError("forecast_object_not_found")
    head = head[:cut]
    if any(key not in head for key in ORG_REQUIRED):
        raise SourceError("unsupported_forecast_contract")
    return head


def _org_calibration(head):
    out = {}
    for horizon in ("24h", "48h"):
        pattern = r'"' + horizon + r'":[^{]{0,20}\{brierScore:([\d.]+),calibrationSampleSize:(\d+),calibrationState:"([^"]+)"'
        match = re.search(pattern, head)
        if match:
            out[horizon] = {"brier": float(match.group(1)), "sample": int(match.group(2)), "state": match.group(3)}
    if "24h" not in out:
        raise SourceError("unsupported_forecast_contract")
    return out


def normalize_codexreset_org(page, now):
    head = _org_head(page)

    def literal(key):
        match = re.search(re.escape(key) + r":(\d+)", head)
        return int(match.group(1)) if match else None

    def string(key):
        match = re.search(re.escape(key) + r':"([^"]{1,120})"', head)
        return match.group(1) if match else None

    score24, score48 = literal("score24h"), literal("score48h")
    if score24 is None or score48 is None:
        raise SourceError("unsupported_forecast_contract")
    calibration = _org_calibration(head)
    row = {"source": "codexreset_org", "name": SOURCES["codexreset_org"]["name"],
           # nextReassessmentAt is when the site recomputes, not when it last did;
           # this source reports no observation time we can trust for freshness.
           "updated_at": None, "reassessed_at": _stamp(string("nextReassessmentAt")),
           "model_version": _text(string("algorithmVersion"), 60),
           "raw_24h": round(float(score24), 2), "raw_48h": round(float(score48), 2),
           "headline_24h": round(float(score24), 2), "headline_48h": round(float(score48), 2),
           "base_24h": literal("baseScore24h"), "base_48h": literal("baseScore48h"),
           "band_24h": None, "band_48h": None, "promise": None, "signal_state": None,
           "latest_hint": None, "typical_window": None, "last_reset": None}
    row["self_reported"] = {"confidence": _text(string("forecastConfidence"), 20), "note": None,
                            "backtest": None, "calibration": calibration}
    row["cadence"] = {"interval_sample": calibration["24h"]["sample"],
                      "sample_basis": "calibration_backtest_sample",
                      "median_gap_days": None, "mean_gap_days": None, "longest_gap_days": None, "age_days": None}
    return row


NORMALIZERS = {"willreset": normalize_willreset, "codex_reset": normalize_codex_reset,
               "codexreset_org": normalize_codexreset_org}


def _freshness(age_hours):
    if age_hours is None:
        # No trusted observation time is not a penalty; the payload says so.
        return 1.0, "updated_at_unreported"
    if age_hours <= FRESH_NEAR_HOURS:
        return 1.0, None
    if age_hours <= FRESH_MID_HOURS:
        return 0.7, "updated_at_24h_plus"
    if age_hours <= MAX_SOURCE_AGE_HOURS:
        return 0.5, "updated_at_48h_plus"
    return None, "forecast_source_stale"


def pooled_value(row, horizon):
    """The source's own published answer; internals only when nothing is published."""
    published, model = row.get("headline_" + horizon), row.get("raw_" + horizon)
    if published is not None:
        return published, "published_answer"
    if model is not None:
        return model, "cadence_model_fallback"
    return None, "no_answer"


def score_source(row, now):
    """Weight = self-reported confidence x calibration x sample x freshness."""
    if row.get("status") not in ("available", "stale"):
        return None, {"excluded": row.get("reason") or "source_unavailable"}
    age = None
    if row.get("updated_at"):
        age = max(0.0, round((now - row["updated_at"]["epoch_seconds"]) / 3600, 2))
    fresh, freshness_note = _freshness(age)
    reported = row.get("self_reported") or {}
    confidence = reported.get("confidence")
    confidence_weight = CONFIDENCE_WEIGHT.get(confidence, UNKNOWN_CONFIDENCE_WEIGHT)
    notes = [] if confidence in CONFIDENCE_WEIGHT else ["confidence_unrecognized:" + str(confidence)]
    calibration = (reported.get("calibration") or reported.get("backtest") or {}).get("24h") or {}
    state = calibration.get("state")
    cadence = row.get("cadence") or {}
    sample = cadence.get("interval_sample")
    if sample is None:
        sample_weight, sample_note = 1.0, "interval_sample_unreported"
    elif sample >= 30:
        sample_weight, sample_note = 1.0, None
    elif sample >= 8:
        sample_weight, sample_note = 0.85, None
    else:
        sample_weight, sample_note = 0.6, None
    if freshness_note:
        notes.append(freshness_note)
    if sample_note:
        notes.append(sample_note)
    if fresh is None:
        return None, {"excluded": freshness_note}
    components = {"age_hours": age, "confidence": confidence, "confidence_weight": confidence_weight,
                  "calibration_state": state, "calibration_weight": CALIBRATION_WEIGHT.get(state, 1.0),
                  "calibration_sample": calibration.get("sample"), "calibration_brier": calibration.get("brier"),
                  "interval_sample": sample, "sample_basis": cadence.get("sample_basis"),
                  "sample_weight": sample_weight, "freshness_weight": fresh, "notes": notes,
                  "weight": round(confidence_weight * CALIBRATION_WEIGHT.get(state, 1.0) * sample_weight * fresh, 4)}
    return components["weight"], components


def combine(rows, now):
    usable = []
    for row in rows:
        weight, components = score_source(row, now)
        row["weight_components"] = components
        row["weight"] = weight
        if weight and pooled_value(row, "24h")[0] is not None:
            usable.append(row)
    pooled = {"status": "no_usable_source", "horizons": {}, "sources_used": [], "n_sources": 0}
    if usable:
        pooled = {"status": "available", "pooled_field": "each site's own published answer",
                  "internals_kept_as": "raw_24h and raw_48h per source",
                  "weights_are": "self_reported_quality_only",
                  "sources_used": [row["source"] for row in usable], "n_sources": len(usable), "horizons": {}}
        for horizon in ("24h", "48h"):
            entries = []
            for row in usable:
                value, basis = pooled_value(row, horizon)
                if value is None:
                    continue
                entries.append((round(value, 2), row["weight"], row["source"], basis))
            if not entries:
                continue
            entries.sort()
            total = sum(weight for _, weight, _, _ in entries) or 1.0
            running, median = 0.0, entries[-1][0]
            for value, weight, _, _ in entries:
                running += weight / total
                if running >= 0.5:
                    median = value
                    break
            low, high = entries[0][0], entries[-1][0]
            spread = round(high - low, 2)
            pooled["horizons"][horizon] = {"min": low, "max": high, "spread": spread, "n": len(entries),
                                           "weighted_median": round(median, 2),
                                           "values": [{"source": source, "percent": value, "basis": basis}
                                                      for value, _, source, basis in entries],
                                           "agreement": "close" if spread <= 15 else "split"}
    return pooled


def promises(rows):
    """A promise without a machine-readable clock becomes a banner, never a target."""
    out = []
    for row in rows:
        promise = row.get("promise")
        if not isinstance(promise, dict):
            continue
        out.append({"source": row["source"], "name": row["name"], "label": promise.get("label"),
                    "quote": promise.get("quote"), "url": promise.get("url"), "at": promise.get("at"),
                    "has_clock": bool(promise.get("has_clock")) or promise.get("close_at") is not None,
                    "floor_percent": promise.get("floor_percent"),
                    "open_at": promise.get("open_at"), "close_at": promise.get("close_at"),
                    "basis": promise.get("basis", "third_party_promise_overlay")})
    return out


def _next_hour_window(start_hour, end_hour, now):
    """Announcement hours repeat daily; the target is the next occurrence."""
    if not isinstance(start_hour, int) or isinstance(start_hour, bool) or \
            not isinstance(end_hour, int) or isinstance(end_hour, bool) or end_hour <= start_hour:
        return None
    current = datetime.fromtimestamp(now, timezone.utc)
    open_at = current.replace(minute=0, second=0, microsecond=0) + timedelta(hours=start_hour - current.hour)
    if open_at <= current:
        open_at += timedelta(days=1)
    return {"open_at": timestamp(open_at.timestamp()),
            "close_at": timestamp((open_at + timedelta(hours=end_hour - start_hour)).timestamp())}


def _fill_seconds(target, now):
    """Label-only and unclocked promises keep seconds null, like day-precision renewals."""
    for edge in ("open", "close"):
        stamp = target.get(edge + "_at")
        target["seconds_remaining_" + edge] = None if not stamp else round(stamp["epoch_seconds"] - now, 1)
    close = target.get("close_at")
    if target.get("precision") != "window" or not close:
        target["state"] = "no_clock" if target["kind"] == "promised_reset" else "label_only"
    elif close["epoch_seconds"] < now:
        target["state"] = "elapsed_awaiting_landing"
    elif target.get("open_at") and target["open_at"]["epoch_seconds"] <= now:
        target["state"] = "inside_window"
    else:
        target["state"] = "upcoming"
    return target


def countdown_targets(rows, now):
    targets = []
    for item in promises(rows):
        if not (item.get("has_clock") and item.get("close_at")):
            continue
        targets.append({"kind": "promised_reset", "precision": "window",
                        "label": item["label"] or "Tibo announced a reset with a time",
                        "open_at": item["open_at"], "close_at": item["close_at"],
                        "sources": [item["source"]], "quote": item["quote"], "url": item["url"],
                        "basis": item["basis"]})
    windows = {}
    for row in rows:
        window = row.get("typical_window") or {}
        pair = _next_hour_window(window.get("start_hour"), window.get("end_hour"), now)
        if not pair:
            if window.get("label"):
                targets.append({"kind": "typical_window", "precision": "label_only",
                                "label": window["label"], "open_at": None, "close_at": None,
                                "timezone": window.get("timezone"), "sources": [row["source"]],
                                "quote": None, "url": None, "basis": "announcement_hour_cluster"})
            continue
        key = (pair["open_at"]["epoch_seconds"], pair["close_at"]["epoch_seconds"])
        entry = windows.setdefault(key, dict(pair, kind="typical_window", precision="window",
                                            label="公告常见时段 " + (window.get("label") or ""),
                                            timezone=window.get("timezone"), sources=[], quote=None, url=None,
                                            basis="announcement_hour_cluster"))
        entry["sources"].append(row["source"])
    targets.extend(windows.values())
    for target in targets:
        _fill_seconds(target, now)
    targets.sort(key=lambda t: (t["kind"] != "promised_reset",
                                (t.get("close_at") or {}).get("epoch_seconds") or float("inf")))
    return targets


def normalize_history(key, payload):
    events = payload.get("events") if isinstance(payload, dict) else payload
    if not isinstance(events, list):
        raise SourceError("unsupported_history_contract")
    out = []
    for event in events:
        if not isinstance(event, dict):
            continue
        announced = _stamp(event.get("announced_at"))
        # Tweet ids are the only key the three sites genuinely share.
        if event.get("id") is None or announced is None:
            continue
        out.append({"post_id": _text(str(event.get("id")), 40),
                    "kind": _text(event.get("kind") or event.get("group") or event.get("type"), 30),
                    "announced_at": announced,
                    "effective_at": _stamp(event.get("effective_at")),
                    "official_window": _machine_window(event.get("official_window")),
                    "scope": _text(event.get("scope"), 20),
                    "confidence": _text(event.get("confidence"), 20),
                    "confirmed": event.get("confirmed") if isinstance(event.get("confirmed"), bool) else None,
                    "banked_grant": event.get("banked_grant") if isinstance(event.get("banked_grant"), bool) else None,
                    "summary": _text(event.get("summary")),
                    "url": _url(event.get("source_url") or event.get("url")),
                    "sources": [key]})
    if not out:
        raise SourceError("unsupported_history_contract")
    return out


def merge_history(per_source):
    merged = {}
    for events in per_source.values():
        for event in events:
            entry = merged.get(event["post_id"])
            if entry is None:
                merged[event["post_id"]] = dict(event)
                continue
            entry["sources"] = sorted(set(entry["sources"] + event["sources"]))
            # Announcement time and observed-landing time are different facts; keep both.
            for name in ("effective_at", "official_window", "summary", "confidence", "scope",
                         "confirmed", "banked_grant"):
                if entry.get(name) in (None, {}):
                    entry[name] = event.get(name)
            if event["announced_at"]["epoch_seconds"] < entry["announced_at"]["epoch_seconds"]:
                entry["announced_at"] = event["announced_at"]
    out = sorted(merged.values(), key=lambda e: e["announced_at"]["epoch_seconds"], reverse=True)
    return out[:HISTORY_LIMIT]


def _error_row(key, code):
    return {"source": key, "name": SOURCES[key]["name"], "status": "error", "reason": code,
            "provenance": SOURCES[key]["forecast"], "updated_at": None,
            "raw_24h": None, "raw_48h": None, "self_reported": None, "cadence": None}


def default_fetchers(with_history):
    """History feeds are heavy; pull them only when the throttle says refresh."""
    def json_forecast(key, probe, normalizer):
        def run(now):
            payload = get_json(SOURCES[key]["forecast"], headers=JSON_HEADERS, timeout=25)
            if not isinstance(payload, dict) or probe not in payload:
                raise SourceError("unsupported_forecast_contract")
            return normalizer(payload, now)
        return run

    def json_history(key):
        def run():
            return normalize_history(key, get_json(SOURCES[key]["history"], headers=JSON_HEADERS, timeout=25))
        return run

    def html_forecast(now):
        page = get_text(SOURCES["codexreset_org"]["forecast"], headers=HTML_HEADERS,
                        timeout=25, max_bytes=4 * 1024 * 1024)
        return normalize_codexreset_org(page, now)

    return {
        "willreset": {"forecast": json_forecast("willreset", "raw_24", normalize_willreset),
                      "history": json_history("willreset") if with_history else None},
        "codex_reset": {"forecast": json_forecast("codex_reset", "probabilities", normalize_codex_reset),
                        "history": json_history("codex_reset") if with_history else None},
        "codexreset_org": {"forecast": html_forecast, "history": None},
    }


def read_cache(path):
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("rows"), list) or \
            not isinstance(data.get("saved_at"), (int, float)):
        return None
    return data


def collect_reset_forecast(now=None, fetchers=None, cache_path=None, refresh_minutes=REFRESH_MINUTES):
    now = time.time() if now is None else now
    out = source("reset_forecast", "external_forecast", now)
    cache = read_cache(cache_path) if cache_path else None
    if cache and now - cache["saved_at"] < (cache.get("throttle_minutes") or refresh_minutes) * 60:
        rows, per_source, cache_state = cache["rows"], cache.get("history") or {}, "served_from_cache"
    else:
        rows, per_source = _collect_live(fetchers or default_fetchers(cache is None), now)
        cache_state = "fresh"
        if any(row["status"] == "available" for row in rows):
            if cache_path:
                from .collector import atomic_json
                failed = any(row["status"] == "error" for row in rows)
                atomic_json(Path(cache_path), {"saved_at": now, "rows": rows, "history": per_source,
                                               "throttle_minutes": RETRY_MINUTES if failed else refresh_minutes})
        elif cache:
            rows, per_source, cache_state = cache["rows"], cache.get("history") or {}, "stale"
        else:
            raise SourceError("reset_forecast_sources_unavailable")
    usable = [row for row in rows if row.get("status") in ("available", "stale")]
    pooled = combine(usable, now)
    value = {"basis": "third_party_forecast", "disclaimer": DISCLAIMER, "cache_state": cache_state,
             "refresh_minutes": refresh_minutes, "ensemble": pooled, "sources": rows,
             "promises": promises(usable), "history_events": merge_history(per_source) if per_source else [],
             "history_sources": sorted(per_source)}
    out["metrics"]["reset_forecast"] = metric(
        value if usable else None,
        status="stale" if cache_state == "stale" else ("available" if pooled["status"] == "available" else "error"),
        reason=None if usable else "reset_forecast_sources_unavailable")
    targets = countdown_targets(usable, now) if usable else []
    out["metrics"]["known_reset_countdown"] = metric(
        {"basis": "third_party_forecast", "targets": targets} if targets else None,
        status="available" if targets else "not_provided",
        reason=None if targets else "no_machine_readable_reset_time")
    out["diagnostics"] = {"reason": None, "cache_state": cache_state,
                          "sources_available": sum(row.get("status") == "available" for row in rows),
                          "sources_total": len(rows)}
    out["status"] = "partial" if any(row.get("status") == "error" for row in rows) or cache_state == "stale" else "available"
    return out


def _collect_live(fetchers, now):
    rows, history = [], {}
    for key, adapter in fetchers.items():
        try:
            row = adapter["forecast"](now)
            row.update({"status": "available", "reason": None, "provenance": SOURCES[key]["forecast"]})
            rows.append(row)
        except SourceError as error:
            rows.append(_error_row(key, error.code))
        except Exception:
            rows.append(_error_row(key, "unexpected_forecast_shape"))
        load = adapter.get("history")
        if load:
            try:
                history[key] = load()
            except Exception:
                history[key] = []
    return rows, history


def refresh_forecast_countdowns(snapshot, now):
    """Recount the window countdowns on every read, like renewals."""
    for src in snapshot.get("sources", []):
        item = (src.get("metrics") or {}).get("known_reset_countdown") or {}
        value = item.get("value")
        for target in (value or {}).get("targets", []):
            _fill_seconds(target, now)
    return snapshot
