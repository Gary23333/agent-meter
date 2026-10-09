"""Antigravity CLI (agy) local token usage from its conversation databases.

~/.gemini/antigravity-cli/conversations/<uuid>.db stores one conversation
per sqlite file. LLM-call steps (steps.step_type=15) carry a protobuf
metadata blob: field 1 is a google.protobuf.Timestamp (field 1 = epoch
seconds) and field 9 is the usage message. Field semantics were decoded
from this machine's data (2026-10-09, agy 1.3.2) and verified internally:
usage.2 = input tokens per call, usage.3 = output tokens including
thinking, usage.9 = the thinking part (3 − 9 = 10 = plain output holds on
every checked step). The per-generation model name sits in the aligned
gen_metadata row (blob field 1, then field 19).

Two fields are constant across every step (usage.1 = 1319, usage.6 = 24)
and could not be identified; per the project's no-guessing rule they are
excluded from the metrics and noted in diagnostics, and cache read/write
is reported as unverified rather than zero-claimed. Databases are opened
with mode=ro&immutable=1 because agy keeps its schema in an uncheckpointed
WAL: rows still only in the WAL of a live conversation are not visible, so
an active conversation's newest steps appear after the next checkpoint.
On this machine the history starts 2026-06-17, exactly when the retired
Gemini CLI wrote its last chat, so the gemini and antigravity sources are
complementary, never overlapping. Only usage fields are read, never
conversation text.
"""
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .ccswitch import app_imported_days
from .cli_sessions import _file_records, _metric_value, _model, _nonneg, _prune
from .model import SourceError, metric, source

LLM_STEP_TYPE = 15


def _varint(buf, i):
    v = s = 0
    while True:
        b = buf[i]
        i += 1
        v |= (b & 0x7F) << s
        if not b & 0x80:
            return v, i
        s += 7


def _fields(buf):
    """Top-level protobuf fields: [(number, wire_type, value)]."""
    i = 0
    out = []
    while i < len(buf):
        try:
            key, i = _varint(buf, i)
            fn, wt = key >> 3, key & 7
            if wt == 0:
                v, i = _varint(buf, i)
                out.append((fn, wt, v))
            elif wt == 2:
                ln, i = _varint(buf, i)
                out.append((fn, wt, buf[i:i + ln]))
                i += ln
            else:
                break
        except IndexError:
            break
    return out


def _usage_and_time(metadata):
    """(epoch_seconds, input, output_total, thinking) from one step blob."""
    t = usage = None
    for fn, wt, v in _fields(metadata):
        if fn == 1 and wt == 2:
            stamp = {f: val for f, w, val in _fields(v) if w == 0}.get(1)
            if isinstance(stamp, int) and stamp > 1_000_000_000:
                t = stamp
        elif fn == 9 and wt == 2:
            d = {f: val for f, w, val in _fields(v) if w == 0}
            if isinstance(d.get(2), int):
                usage = d
    if usage is None or t is None:
        return None
    return (t, _nonneg(usage.get(2)), _nonneg(usage.get(3)), _nonneg(usage.get(9)))


def _generation_model(blob):
    if not isinstance(blob, bytes):
        return "unknown"
    top = {f: v for f, w, v in _fields(blob) if w == 2}
    inner = {f: v for f, w, v in _fields(top.get(1, b"")) if w == 2}
    name = inner.get(19)
    if isinstance(name, bytes) and name:
        try:
            return _model(name.decode("utf-8"))
        except UnicodeDecodeError:
            return "unknown"
    return "unknown"


def _parse_conversation(path):
    """[(epoch, model, input, output_total, thinking)] for one db file."""
    conn = sqlite3.connect("file:" + str(path) + "?mode=ro&immutable=1", uri=True, timeout=3)
    try:
        conn.execute("PRAGMA query_only=ON")
        steps = conn.execute("SELECT metadata FROM steps WHERE step_type=? ORDER BY idx",
                             (LLM_STEP_TYPE,)).fetchall()
        gens = [row[0] for row in conn.execute("SELECT data FROM gen_metadata ORDER BY idx")]
    finally:
        conn.close()
    records = []
    for seq, (metadata,) in enumerate(steps):
        if not isinstance(metadata, bytes):
            continue
        parsed = _usage_and_time(metadata)
        if parsed is None:
            continue
        t, total_input, output, thinking = parsed
        model = _generation_model(gens[seq]) if seq < len(gens) else "unknown"
        records.append((t, model, total_input, output, thinking))
    return records


def load_antigravity(root):
    root = Path(root)
    if not root.is_dir():
        raise SourceError("agy_conversations_not_found")
    records = []
    seen = set()
    skipped = 0
    for path in sorted(root.glob("*.db")):
        seen.add(str(path))
        try:
            file_records = _file_records(path, _parse_conversation)
        except (sqlite3.Error, OSError):
            skipped += 1
            continue
        if not file_records:
            skipped += 1
            continue
        records.extend((t, model, inp, out, think, 0, 0) for t, model, inp, out, think in file_records)
    _prune(seen)
    return records, skipped


def collect_antigravity_sessions(root, ccswitch_db, now, zone=ZoneInfo("Asia/Shanghai")):
    excluded, overlap_state = app_imported_days(ccswitch_db, zone, "antigravity")
    records, skipped = load_antigravity(root)
    out = source("antigravity", "local_session_history", now)
    value = _metric_value(records, now, zone, excluded, "antigravity",
                          "antigravity_cli_conversations", "one_usage_per_llm_step", overlap_state)
    # The two constant usage fields could not be identified; cache semantics
    # stay unverified instead of being claimed as zero.
    for period in value["periods"].values():
        period["totals"]["cache_hit_rate"] = None
    value["cache_semantics"] = "unverified_constants_excluded"
    value["skipped_conversation_dbs"] = skipped
    out["metrics"]["tokens"] = metric(value)
    return out
