"""DeepSeek peak/off-peak billing window (Asia/Shanghai display time).

DeepSeek's current price list has one off-peak rate and a peak rate that is
twice it. Peak hours are UTC 01:00-04:00 and 06:00-10:00, Monday through
Friday, excluding Chinese public holidays: in Beijing time that is weekdays
09:00-12:00 and 14:00-18:00. Weekends are off-peak all day; public holidays
are not subtracted here (no holiday calendar is bundled), so a weekday
holiday is conservatively billed at the peak rate.

Only ledgers that keep a per-request timestamp can be split; anything
recorded as a daily total (or without a timestamp) stays priced at the
off-peak base price.
"""
from datetime import datetime

from .model import DISPLAY_ZONE

WINDOW = {
    "timezone": "Asia/Shanghai",
    "weekdays": [1, 2, 3, 4, 5],
    "intervals": [["09:00", "12:00"], ["14:00", "18:00"]],
    "weekend_offpeak": True,
    "note": "工作日 09:00-12:00、14:00-18:00 为峰时；其余时间与周末全天为谷时",
}
PEAK_INTERVALS = ((9 * 3600, 12 * 3600), (14 * 3600, 18 * 3600))
TOKEN_FIELDS = ("fresh_input", "output", "reasoning", "cache_read", "cache_write")


def is_offpeak(epoch, zone=DISPLAY_ZONE, holidays=None):
    """True when a request at this epoch is billed at the off-peak rate.

    holidays is an optional set of ISO dates ("2026-10-01") to treat as
    off-peak; without it only weekends are known to be off-peak.
    """
    moment = datetime.fromtimestamp(epoch, zone)
    if moment.weekday() >= 5:
        return True
    if holidays and moment.date().isoformat() in holidays:
        return True
    seconds = moment.hour * 3600 + moment.minute * 60 + moment.second
    return not any(start <= seconds < end for start, end in PEAK_INTERVALS)


def bucket():
    """An empty peak or off-peak accumulator (requests + token fields)."""
    return {"requests": 0, **dict.fromkeys(TOKEN_FIELDS, 0)}


def add(bucket_values, values):
    """Accumulate one record's {field: tokens} dict into a bucket."""
    bucket_values["requests"] += 1
    for field in TOKEN_FIELDS:
        bucket_values[field] += values.get(field, 0) or 0


def total(bucket_values):
    """Sum a bucket's token fields (the same total_tokens rule as groups)."""
    return sum(bucket_values.get(field, 0) or 0 for field in TOKEN_FIELDS)
