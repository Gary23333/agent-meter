"""Antigravity CLI (agy) local token usage from its conversation databases.

~/.gemini/antigravity-cli/conversations/<uuid>.db stores one conversation
per sqlite file; the desktop app writes the same schema under
~/.gemini/antigravity/conversations. LLM-call steps (steps.step_type=15)
carry a protobuf metadata blob: field 1 is a google.protobuf.Timestamp
(field 1 = epoch seconds) and field 9 is the usage message. Field semantics
were decoded from this machine's data (agy 1.3.2 / desktop 2.28.2,
2026-10-31) and cross-checked against the app's own transcript token fields:
usage.2 = fresh input tokens per call, usage.3 = output tokens including
thinking, usage.5 = cache-read tokens, usage.9 = the thinking part
(3 − 9 = 10 = plain output). usage.10 matched output − thinking on every
checked step, and usage.5 matched the transcript's cache_read_tokens on
155/155 steps whose transcript carried token fields. The per-generation
model name sits in the aligned gen_metadata row (blob field 1, then field 19).

usage.1 and usage.6 vary by conversation but stay constant across its steps
and could not be identified; per the project's no-guessing rule they are
excluded from the metrics. No checked step carried a cache-write value (the
transcript field is null/zero), so cache_write is recorded as 0 and the
diagnostics declare the decoded semantics. Databases are opened with
mode=ro&immutable=1 because agy keeps its schema in an uncheckpointed WAL:
rows still only in the WAL of a live conversation are not visible, so an
active conversation's newest steps appear after the next checkpoint. On this
machine the history starts 2026-06-17, exactly when the retired Gemini CLI
wrote its last chat, so the gemini and antigravity sources are complementary,
never overlapping. Only usage fields are read, never conversation text.
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
    """(epoch_seconds, input, output_total, thinking, cache_read) from one step blob."""
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
    return (t, _nonneg(usage.get(2)), _nonneg(usage.get(3)), _nonneg(usage.get(9)),
            _nonneg(usage.get(5)))


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
                             (LLM_STEP_TYPE,))
        gens = iter(conn.execute("SELECT data FROM gen_metadata ORDER BY idx"))
        records = []
        for (metadata,) in steps:
            # Consume the corresponding generation even for malformed steps.
            generation = next(gens, (None,))[0]
            if not isinstance(metadata, bytes):
                continue
            parsed = _usage_and_time(metadata)
            if parsed is None:
                continue
            t, total_input, output, thinking, cache_read = parsed
            model = _generation_model(generation) if isinstance(generation, bytes) else "unknown"
            records.append((t, model, total_input, output, thinking, cache_read))
        return records
    finally:
        conn.close()


def load_antigravity_roots(roots):
    """Records from CLI and desktop conversation directories, deduplicated.

    Each sqlite file is one conversation named by its UUID (the file stem).
    The desktop app and the CLI can hold the same UUID in different roots, so
    one file per UUID is chosen: newest mtime first, then the larger file.
    Missing roots and unparseable databases only count as skipped; the whole
    source fails only when no configured root exists.
    """
    roots = [Path(root).expanduser() for root in roots]
    present = [root for root in roots if root.is_dir()]
    if not present:
        raise SourceError("agy_conversations_not_found")
    chosen = {}
    duplicates = 0
    for root in present:
        for path in sorted(root.glob("*.db")):
            try:
                stat = path.stat()
            except OSError:
                continue
            candidate = (stat.st_mtime_ns, stat.st_size, path)
            previous = chosen.get(path.stem)
            if previous is None:
                chosen[path.stem] = candidate
            else:
                duplicates += 1
                if candidate[:2] > previous[:2]:
                    chosen[path.stem] = candidate
    records = []
    seen = set()
    skipped = len(roots) - len(present)
    for _mtime, _size, path in sorted(chosen.values(), key=lambda item: str(item[2])):
        seen.add(str(path))
        try:
            file_records = _file_records(path, _parse_conversation)
        except (sqlite3.Error, OSError):
            skipped += 1
            continue
        if not file_records:
            skipped += 1
            continue
        records.extend((t, model, inp, out, think, cache_read, 0)
                       for t, model, inp, out, think, cache_read in file_records)
    _prune(seen, "_parse_conversation")
    diagnostics = {"roots_declared": len(roots), "roots_present": len(present),
                   "duplicate_conversation_ids": duplicates}
    return records, skipped, diagnostics


def load_antigravity(root):
    records, skipped, _diagnostics = load_antigravity_roots([root])
    return records, skipped


def collect_antigravity_sessions(root, ccswitch_db, now, zone=ZoneInfo("Asia/Shanghai"),
                                desktop_root=None):
    roots = [root] if desktop_root is None else [root, desktop_root]
    records, skipped, diagnostics = load_antigravity_roots(roots)
    # CC Switch's agy importer reads brain transcripts: on this machine it
    # covered 3 of 19 history days and missed steps in old conversations.
    # The conversation DBs are the complete ledger, so this source stays
    # primary and does not skip CC Switch days (CC Switch excludes agy rows).
    observed_agy, state_agy = app_imported_days(ccswitch_db, zone, "agy")
    observed_old, state_old = app_imported_days(ccswitch_db, zone, "antigravity")
    if state_agy == "checked" or state_old == "checked":
        overlap_state = "checked"
    elif state_agy == "ccswitch_absent" and state_old == "ccswitch_absent":
        overlap_state = "ccswitch_absent"
    else:
        overlap_state = "ccswitch_read_failed"
    out = source("antigravity", "account", now)
    value = _metric_value(records, now, zone, set(), "antigravity",
                          "antigravity_conversations", "one_usage_per_llm_step", overlap_state)
    # usage.5 is cache-read and matched the app's transcript field on every
    # checked step; cache-write is absent in all checked steps.
    value["cache_semantics"] = "f5_cache_read_verified_cache_write_absent"
    value["skipped_conversation_dbs"] = skipped
    value["ccswitch_overlap"]["direct_primary"] = True
    value["ccswitch_overlap"]["observed_imported_days"] = sorted(observed_agy | observed_old)
    out["diagnostics"].update(diagnostics)
    out["diagnostics"]["ccswitch_policy"] = "direct_primary"
    out["metrics"]["tokens"] = metric(value)
    return out
