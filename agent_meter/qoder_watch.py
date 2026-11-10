"""Qoder usage-field drift watch (read-only, aggregates only).

Qoder CN's local ledger records credits but, on every version checked so far
(0.4.11 and 0.5.6), zero token values. This watcher samples recent session
logs after each app upgrade and reports drift: a new app version, token
fields turning non-zero (a collector upgrade becomes possible), or usage
records disappearing. It never reads message text and never guesses tokens
from request counts or text length.
"""
import json
import plistlib
import time
from pathlib import Path

from .collector import atomic_json

TOKEN_MARKERS = ("input_tokens", "output_tokens", "cache_read_input_tokens",
                 "cache_creation_input_tokens", "total_tokens")


def app_version(app_path):
    try:
        info = plistlib.loads((Path(app_path) / "Contents/Info.plist").read_bytes())
        version = info.get("CFBundleShortVersionString")
        return version if isinstance(version, str) else None
    except (OSError, ValueError):
        return None


def sample_qoder_usage(projects_dir, days=3, now=None):
    now = time.time() if now is None else now
    cutoff = now - days * 86400
    root = Path(projects_dir).expanduser()
    stats = {"sampled_at": now, "window_days": days, "files": 0, "assistant": 0,
             "with_usage": 0, "usage_nonzero_tokens": 0, "with_credits": 0,
             "token_keys_seen": []}
    keys = set()
    if not root.is_dir():
        stats["projects_dir_missing"] = True
        return stats
    for path in root.glob("**/*.jsonl"):
        try:
            if path.stat().st_mtime < cutoff:
                continue
            handle = open(path, errors="replace")
        except OSError:
            continue
        stats["files"] += 1
        with handle:
            for line in handle:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(rec, dict):
                    continue
                msg = rec.get("message") if isinstance(rec.get("message"), dict) else {}
                if rec.get("type") != "assistant" and msg.get("role") != "assistant":
                    continue
                stats["assistant"] += 1
                usage = msg.get("usage") if isinstance(msg.get("usage"), dict) else \
                    rec.get("usage") if isinstance(rec.get("usage"), dict) else None
                if usage is None:
                    continue
                stats["with_usage"] += 1
                if usage.get("credits") is not None:
                    stats["with_credits"] += 1
                nonzero = False
                for key, value in usage.items():
                    if "token" in key.lower():
                        keys.add(key)
                        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
                            nonzero = True
                if nonzero:
                    stats["usage_nonzero_tokens"] += 1
    stats["token_keys_seen"] = sorted(keys)
    return stats


def watch(projects_dir, app_path, state_path, days=3, now=None):
    current = sample_qoder_usage(projects_dir, days, now)
    current["app_version"] = app_version(app_path)
    previous = None
    state = Path(state_path)
    if state.is_file():
        try:
            previous = json.loads(state.read_text())
        except (OSError, ValueError):
            previous = None
    drift = []
    if current.get("projects_dir_missing"):
        drift.append("projects_dir_missing")
    if isinstance(previous, dict):
        if previous.get("app_version") != current["app_version"]:
            drift.append("app_version_changed")
        if current["usage_nonzero_tokens"] > 0 and not previous.get("usage_nonzero_tokens"):
            drift.append("tokens_appeared")
        if current["assistant"] > 0 and current["with_usage"] == 0 and previous.get("with_usage"):
            drift.append("usage_field_missing")
    atomic_json(state, current)
    return {"current": current, "previous": previous, "drift": drift,
            "note": "aggregates only; zero tokens are never treated as zero consumption"}


def main(argv=None):
    import argparse
    import sys
    home = Path.home()
    parser = argparse.ArgumentParser(description="Read-only Qoder usage-field drift watch")
    parser.add_argument("--projects-dir", default=str(home / ".qoder-cn/projects"))
    parser.add_argument("--app", default="/Applications/Qoder CN.app")
    parser.add_argument("--state", default=str(Path.cwd() / ".runtime/qoder-usage-watch.json"))
    parser.add_argument("--days", type=int, default=3)
    args = parser.parse_args(argv)
    report = watch(args.projects_dir, args.app, args.state, args.days)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if report["drift"] else 0