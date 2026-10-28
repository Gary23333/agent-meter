"""MiniMax Design agent token usage from its embedded opencode database.

MiniMax Design.app embeds an opencode runtime (process
`Resources/opencode/opencode serve`) that records the design agent's LLM
sessions in ~/Library/Application Support/@hilo/desktop/ai-runtime/
data-home/opencode/opencode.db. The message table matches the standalone
OpenCode schema (time_created + data JSON); assistant rows carry
tokens {total, input, output, reasoning, cache:{write, read}}. Verified
on this machine (2026-10-15): 11,115 assistant rows, none with zero or
missing tokens, history back to 2026-05-10 and still live (see
docs/research/minimax-design-local-tokens-recon-2026-10-15.md).

Dedup: Design's data-home also contains sessions copied verbatim from
the standalone ~/.local/share/opencode/opencode.db (that machine's own
CLI history — 384 sessions, none under the Hub projects directory).
The opencode source already counts those tokens, so sessions whose id
exists there are excluded here; on this machine the remaining sessions
are the design agent's own. The reference db is read only for session
ids; when it exists but cannot be read the source fails instead of
risking a double count. CC Switch never reads the @hilo database, so no
third ledger overlaps.

Scope: tokens cover the agent chat side only. Media generation (image/
video) bills media credits, produces no tokens, and has no local
per-task ledger. Only token/model fields are read; message text stays
in the database.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import peak
from .ccswitch import period_bounds
from .model import SourceError, metric, timestamp

COLUMNS = {"time_created", "data", "session_id"}


@contextmanager
def readonly_database(path):
    path = Path(path).expanduser()
    if not path.is_file():
        raise SourceError("design_opencode_db_not_found")
    conn = None
    try:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=3)
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        yield conn
    except sqlite3.Error:
        raise SourceError("design_opencode_db_read_failed") from None
    finally:
        if conn is not None:
            conn.rollback()
            conn.close()


def validate_schema(conn):
    columns = {r[1] for r in conn.execute("PRAGMA table_info(message)")}
    if not COLUMNS <= columns:
        raise SourceError("unsupported_design_opencode_schema")


def copied_session_ids(path):
    """Session ids the standalone OpenCode db owns (its own CLI history).

    Returns (ids, state). A missing reference db means no overlap is
    possible ("opencode_absent"); a reference that exists but cannot be
    read raises rather than collecting unexcluded duplicates.
    """
    path = Path(path).expanduser()
    if not path.is_file():
        return set(), "opencode_absent"
    try:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=3)
        try:
            conn.execute("PRAGMA query_only=ON")
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "session" not in tables:
                raise sqlite3.DatabaseError("session table missing")
            return {r[0] for r in conn.execute("SELECT id FROM session")}, "checked"
        finally:
            conn.close()
    except (sqlite3.Error, OSError):
        raise SourceError("design_opencode_reference_unreadable") from None


def _tokens(data):
    """(model, agent, fresh, output, reasoning, cache_read, cache_write) or None."""
    try:
        o = json.loads(data)
    except (ValueError, TypeError):
        return None
    if not isinstance(o, dict) or o.get("role") != "assistant":
        return None
    tokens = o.get("tokens")
    if not isinstance(tokens, dict):
        return None
    def nonneg(v):
        return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None
    cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}
    values = (nonneg(tokens.get("input")), nonneg(tokens.get("output")), nonneg(tokens.get("reasoning")),
              nonneg(cache.get("read")), nonneg(cache.get("write")))
    if any(v is None for v in values):
        return None
    model = o.get("modelID")
    model = model if isinstance(model, str) and 0 < len(model) < 120 else "unknown"
    agent = o.get("agent")
    agent = agent if isinstance(agent, str) and 0 < len(agent) < 60 else "unknown"
    return (model, agent, *values)


def _zero():
    return {"requests": 0, "fresh_input": 0, "output": 0, "reasoning": 0, "cache_read": 0, "cache_write": 0}


def _add(totals, fresh, output, reasoning, cache_read, cache_write):
    totals["requests"] += 1
    totals["fresh_input"] += fresh
    totals["output"] += output
    totals["reasoning"] += reasoning
    totals["cache_read"] += cache_read
    totals["cache_write"] += cache_write


def _close(bucket_values):
    """Attach total_tokens to a peak/off-peak accumulator."""
    bucket_values["total_tokens"] = peak.total(bucket_values)
    return bucket_values


def _summarize(rows, start, end):
    totals = _zero()
    split = {"peak": peak.bucket(), "offpeak": peak.bucket()}
    models = {}
    model_splits = {}
    agents = {}
    for day, t, model, agent, fresh, output, reasoning, cache_read, cache_write in rows:
        if (start is not None and t < start * 1000) or t > end * 1000:
            continue
        _add(totals, fresh, output, reasoning, cache_read, cache_write)
        target = models.setdefault(model, _zero())
        _add(target, fresh, output, reasoning, cache_read, cache_write)
        target = agents.setdefault(agent, _zero())
        _add(target, fresh, output, reasoning, cache_read, cache_write)
        values = {"fresh_input": fresh, "output": output, "reasoning": reasoning,
                  "cache_read": cache_read, "cache_write": cache_write}
        side = "offpeak" if peak.is_offpeak(t / 1000) else "peak"
        peak.add(split[side], values)
        peak.add(model_splits.setdefault(model, {"peak": peak.bucket(), "offpeak": peak.bucket()})[side], values)
    totals["total_tokens"] = sum(totals[k] for k in ("fresh_input", "output", "reasoning", "cache_read", "cache_write"))
    totals["peak"] = _close(split["peak"])
    totals["offpeak"] = _close(split["offpeak"])
    denominator = totals["fresh_input"] + totals["cache_read"] + totals["cache_write"]
    totals["cache_hit_rate"] = totals["cache_read"] / denominator if denominator else None
    keys = ("requests", "fresh_input", "output", "reasoning", "cache_read", "cache_write")
    return {"start": timestamp(start) if start is not None else None, "end": timestamp(end),
            "totals": totals,
            "groups": [{"app": "minimax_design", "model": m, **{k: v[k] for k in keys},
                        "total_tokens": sum(v[k] for k in keys[1:]),
                        "peak": _close(model_splits[m]["peak"]),
                        "offpeak": _close(model_splits[m]["offpeak"])}
                       for m, v in sorted(models.items(), key=lambda x: -x[1]["fresh_input"])],
            "agent_groups": [{"agent": a, **{k: v[k] for k in keys},
                              "total_tokens": sum(v[k] for k in keys[1:])}
                             for a, v in sorted(agents.items(), key=lambda x: -x[1]["fresh_input"])]}


def collect_design_tokens(db_path, reference_db, now, zone=ZoneInfo("Asia/Shanghai")):
    excluded_sessions, overlap_state = copied_session_ids(reference_db)
    with readonly_database(db_path) as conn:
        validate_schema(conn)
        rows = []
        malformed = 0
        for time_created, session_id, data in conn.execute(
                "SELECT time_created, session_id, data FROM message"):
            parsed = _tokens(data)
            if parsed is None:
                if '"tokens"' in (data or ""):
                    malformed += 1
                continue
            if session_id in excluded_sessions:
                continue
            day = datetime.fromtimestamp(time_created / 1000, zone).date().isoformat()
            rows.append((day, time_created, *parsed))
    periods = {p: _summarize(rows, *period_bounds(now, p, zone)) for p in ("today", "7d", "30d", "all")}
    for p in periods.values():
        p["timezone"] = str(zone)
    daily = {}
    for day, _t, _model, _agent, fresh, output, reasoning, cache_read, cache_write in rows:
        daily[day] = daily.get(day, 0) + fresh + output + reasoning + cache_read + cache_write
    return metric({
        "periods": periods,
        "peak_split": "request_timestamp",
        "daily_buckets": [{"date": d, "tokens": n} for d, n in sorted(daily.items())],
        "coverage": "minimax_design_embedded_opencode_message_db",
        "dedup_rule": "exclude_sessions_also_in_standalone_opencode_db",
        "opencode_overlap": {"state": overlap_state, "excluded_sessions": len(excluded_sessions)},
        "malformed_token_rows": malformed,
    })
