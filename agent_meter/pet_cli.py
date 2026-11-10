"""`agent_meter pet ...`: inspect the pet brain, send it events, print hook snippets.

Nothing here edits a user's tool configuration: `hooks` only prints text to paste.
"""
import argparse
import json
import shlex
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .pet import EVENT_KINDS, STATES, PetMind

STATE_LABELS = {
    "offline": "失联", "exhausted": "电量耗尽", "alarm": "告急", "waiting": "等你确认", "busy": "忙翻了",
    "working": "干活中", "painting": "创作中", "tired": "没力气", "alert": "有提醒", "focus": "专注",
    "excited": "期待", "confused": "拿不准", "sleeping": "睡觉", "idle": "待机"}


def runtime_dirs(explicit=None):
    if explicit:
        yield Path(explicit)
    yield Path.cwd() / ".runtime"
    yield Path.home() / "Library/Application Support/AgentMeter/.runtime"


def find_token(explicit=None):
    for directory in runtime_dirs(explicit):
        token_file = directory / "api.token"
        if token_file.is_file() and not token_file.is_symlink():
            token = token_file.read_text().strip()
            if len(token) >= 32:
                return token_file, token
    return None, None


def request(args, method, path, payload=None):
    token_file, token = find_token(args.runtime)
    if token is None:
        raise SystemExit("api.token not found; start the backend first (python3 -m agent_meter serve) or pass --runtime")
    body = json.dumps(payload).encode() if payload is not None else None
    req = Request("http://127.0.0.1:%d%s" % (args.port, path), data=body, method=method,
                  headers={"Authorization": "Bearer " + token,
                           **({"Content-Type": "application/json"} if body is not None else {})})
    try:
        with urlopen(req, timeout=5) as response:
            return json.load(response)
    except HTTPError as error:
        raise SystemExit("backend answered %d: %s" % (error.code, error.read().decode("utf-8", "replace")[:200]))
    except URLError as error:
        raise SystemExit("backend not reachable on port %d (%s)" % (args.port, error.reason))


def load_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError) as error:
        raise SystemExit("cannot read %s: %s" % (path, error))


def brief(frame):
    energy = frame["energy"]
    left = "%s%%" % (energy["remaining"] if energy["remaining"] is None else round(energy["remaining"])) if energy["known"] else "未知"
    parts = ["%s（%s）" % (frame["state"], STATE_LABELS.get(frame["state"], "")), "心情 " + frame["mood"],
             "额度 %s" % left, "进行中 %d" % frame["activity"]["running"]]
    if frame["reaction"]:
        parts.append("反应 " + frame["reaction"]["id"])
    if frame["reminders"]:
        parts.append("提醒 %d" % len(frame["reminders"]))
    return " · ".join(parts)


def cmd_state(args):
    if args.snapshot or args.activity:
        mind = PetMind(clock=lambda: args.now if args.now is not None else time.time())
        snapshot = load_json(args.snapshot) if args.snapshot else None
        activity = load_json(args.activity) if args.activity else None
        if args.threshold:
            mind.set_preferences({"low_quota_threshold": args.threshold})
        now = args.now if args.now is not None else time.time()
        # Two passes: the first only records baselines, like a freshly started backend.
        frame = mind.frame(snapshot, activity, now)
    else:
        frame = request(args, "GET", "/v1/pet")
    print(brief(frame) if args.brief else json.dumps(frame, ensure_ascii=False, indent=2))
    return 0


def cmd_emit(args):
    payload = {"kind": args.kind}
    for key in ("source", "text", "project", "ttl", "tone"):
        value = getattr(args, key)
        if value is not None:
            payload[key] = value
    if args.minutes is not None:
        payload["minutes"] = args.minutes
    print(json.dumps(request(args, "POST", "/v1/pet/events", payload), ensure_ascii=False))
    return 0


def cmd_focus(args):
    if args.minutes == "stop":
        payload = {"kind": "focus_stop"}
    else:
        try:
            payload = {"kind": "focus_start", "minutes": float(args.minutes)}
        except ValueError:
            raise SystemExit("minutes must be a number or 'stop'")
    print(json.dumps(request(args, "POST", "/v1/pet/events", payload), ensure_ascii=False))
    return 0


def curl_command(token_file, port, payload, project=False):
    """A hook command that never fails the host tool: short timeout, errors swallowed."""
    data = json.dumps(payload, separators=(",", ":"))
    if project:
        # $P is stripped to a safe alphabet before it is placed inside the JSON string.
        data = data[:-1] + ',"project":"\'"$P"\'"}'
    command = ("curl -sS -m 2 -X POST -H \"Authorization: Bearer $(cat %s)\" -H 'Content-Type: application/json' "
               "-d '%s' http://127.0.0.1:%d/v1/pet/events >/dev/null 2>&1 || true") % (
                   shlex.quote(str(token_file)), data, port)
    if project:
        command = "P=$(basename \"${CLAUDE_PROJECT_DIR:-.}\" | tr -cd '[:alnum:]._ -'); " + command
    return command


def cmd_hooks(args):
    token_file, _ = find_token(args.runtime)
    if token_file is None:
        token_file = Path.home() / "Library/Application Support/AgentMeter/.runtime/api.token"
        print("# note: no running backend found; using the installed-app token path", file=sys.stderr)
    if args.target == "claude":
        hooks = {"hooks": {
            "UserPromptSubmit": [{"hooks": [{"type": "command", "command": curl_command(
                token_file, args.port, {"kind": "agent_started", "source": "claude"}, project=True)}]}],
            "Stop": [{"hooks": [{"type": "command", "command": curl_command(
                token_file, args.port, {"kind": "agent_done", "source": "claude"}, project=True)}]}],
            "Notification": [{"hooks": [{"type": "command", "command": curl_command(
                token_file, args.port, {"kind": "agent_waiting", "source": "claude"})}]}]}}
        print("// Merge into ~/.claude/settings.json (or .claude/settings.local.json). Not applied automatically.")
        print(json.dumps(hooks, ensure_ascii=False, indent=2))
    elif args.target == "codex":
        command = curl_command(token_file, args.port, {"kind": "agent_done", "source": "codex"})
        print("# Add to ~/.codex/config.toml. Codex runs it when a turn completes. Not applied automatically.")
        print("notify = [\"sh\", \"-c\", %s]" % json.dumps(command))
    else:
        for kind in ("agent_started", "agent_done", "agent_waiting", "agent_failed"):
            print(curl_command(token_file, args.port, {"kind": kind, "source": "mytool"}))
    return 0


def cmd_states(args):
    for state in STATES:
        print("%-10s %s" % (state, STATE_LABELS.get(state, "")))
    return 0


def main(argv):
    parser = argparse.ArgumentParser(prog="agent_meter pet", description="Desktop pet brain tools")
    parser.add_argument("--port", type=int, default=8769)
    parser.add_argument("--runtime", type=Path, help="directory holding api.token (default ./.runtime or the app's)")
    sub = parser.add_subparsers(dest="command", required=True)

    state = sub.add_parser("state", help="print the current PetFrame (live, or from a snapshot file)")
    state.add_argument("--snapshot", type=Path, help="evaluate a saved snapshot instead of asking the backend")
    state.add_argument("--activity", type=Path, help="saved /v1/activity payload to include")
    state.add_argument("--now", type=float, help="evaluate at this epoch (default: now)")
    state.add_argument("--threshold", type=float, choices=[10.0, 20.0, 30.0], help="low-quota threshold")
    state.add_argument("--brief", action="store_true", help="one line instead of JSON")
    state.set_defaults(run=cmd_state)

    emit = sub.add_parser("emit", help="send a hook event to the running backend")
    emit.add_argument("kind", choices=EVENT_KINDS)
    emit.add_argument("--source", help="tool name, e.g. claude, codex")
    emit.add_argument("--text", help="short message (80 chars, no prompts)")
    emit.add_argument("--project", help="project alias")
    emit.add_argument("--ttl", type=int, help="seconds the event stays relevant")
    emit.add_argument("--tone", choices=["info", "good", "warn", "danger"])
    emit.add_argument("--minutes", type=float, help="focus length for focus_start")
    emit.set_defaults(run=cmd_emit)

    focus = sub.add_parser("focus", help="start a focus timer (minutes) or stop it")
    focus.add_argument("minutes", help="e.g. 25, or 'stop'")
    focus.set_defaults(run=cmd_focus)

    hooks = sub.add_parser("hooks", help="print hook / notify configuration to paste (never applied for you)")
    hooks.add_argument("target", choices=["claude", "codex", "generic"], nargs="?", default="claude")
    hooks.set_defaults(run=cmd_hooks)

    sub.add_parser("states", help="list the canonical pet states").set_defaults(run=cmd_states)

    args = parser.parse_args(argv)
    return args.run(args)
