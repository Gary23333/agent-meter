"""Shared per-day per-model rollups for calendar-period reports (E3).

daily_buckets only carries day totals; week/month comparisons with cost and
model attribution need the model split per day. Rows without a request time
(imported daily rollups) keep their date and model but cannot be peak-split;
the report prices them at the base rate and says so.
"""

KEYS = ("fresh_input", "output", "reasoning", "cache_read", "cache_write")


def add(table, day, model, values, *, app=None, requests=1):
    key = (day, app, model) if app is not None else (day, model)
    row = table.get(key)
    if row is None:
        row = {"requests": 0}
        row.update(dict.fromkeys(KEYS, 0))
        table[key] = row
    row["requests"] += requests
    for name in KEYS:
        row[name] += values.get(name, 0)
    unclassified = values.get("unclassified")
    if unclassified:
        row["unclassified"] = row.get("unclassified", 0) + unclassified


def rows(table, app=None):
    out = []
    for key, value in sorted(table.items()):
        day, model = key[0], key[-1]
        row_app = key[1] if len(key) == 3 else app
        row = {"date": day, "model": model, **value,
               "total_tokens": sum(value[k] for k in KEYS) + value.get("unclassified", 0)}
        if row_app is not None:
            row["app"] = row_app
        out.append(row)
    return out