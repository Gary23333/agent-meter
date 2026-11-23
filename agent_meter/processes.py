"""Processes started by local agent harnesses (read-only).

Scope is deliberately narrow. A process is reported only when it descends from a
harness (Claude Code, Codex, Kimi Code, ...) through the parent chain, or was seen
descending from one earlier and has since been reparented (an orphan the harness
left behind). Every other process on the machine stays out of the payload: the
process table is read to find the harness trees, then discarded.

What is read: the process table (`ps`: pid, parent, state, CPU, memory, uptime,
command line) and, for the reported pids only, listening TCP ports and the
harness working directory (`lsof`). What is never read: environment variables,
open files, remote peers, standard streams, memory. Command lines are redacted
(secrets, long opaque tokens, URL credentials) and truncated, and a harness root
is never given a command line at all because its arguments can carry a prompt.
Nothing here signals, kills or renices a process.
"""
import os
import re
import shutil
import subprocess
import sys
import threading
from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePath

from .model import timestamp

SCHEMA_VERSION = 1
MAX_PROCESSES = 400
MAX_PER_HARNESS = 120
MAX_DEPTH = 10
COMMAND_LIMIT = 120
ORPHAN_SLACK_SECONDS = 3
MEMORY_LIMIT = 4000
SUPPORTED_PLATFORMS = ("darwin", "linux")


@dataclass(frozen=True)
class Harness:
    """How one harness shows up in the process table.

    `exes` are executable basenames (case-sensitive: the Claude desktop app is
    "Claude", the CLI is "claude"). `scripts` match the script an interpreter
    runs; `hints` are install-path fragments that identify a wrapper.
    """
    app: str
    label: str
    exes: tuple = ()
    scripts: tuple = ()
    hints: tuple = ()


HARNESSES = (
    Harness("claude", "Claude Code", exes=("claude",), scripts=("claude", "claude-code"),
            hints=("/@anthropic-ai/claude-code/", "/.claude/local/")),
    Harness("codex", "Codex", exes=("codex",), scripts=("codex", "codex.js"), hints=("/@openai/codex/",)),
    Harness("kimi", "Kimi Code", exes=("kimi", "kimi-code", "kimi-cli"), scripts=("kimi", "kimi-code", "kimi-cli")),
    Harness("gemini", "Gemini CLI", exes=("gemini",), scripts=("gemini",), hints=("/@google/gemini-cli/",)),
    Harness("opencode", "OpenCode", exes=("opencode", ".opencode"), scripts=("opencode",), hints=("/opencode-ai/",)),
    Harness("deepseek_harness", "DeepSeek Harness", exes=("dsh",), scripts=("dsh",)),
    Harness("antigravity", "Antigravity", exes=("agy",), scripts=("agy",)),
    Harness("mimo_code", "MiMo Code", exes=("mimocode", "mimo-code"), scripts=("mimocode",)),
    Harness("qoder", "Qoder CLI", exes=("qodercli",), scripts=("qodercli",)),
)

INTERPRETER = re.compile(r"^(node|nodejs|bun|deno|tsx|ts-node|ruby|python\d*(\.\d+)*|uv|uvx)$")
SHELLS = {"sh", "bash", "zsh", "fish", "dash", "ksh", "tcsh", "csh"}
VCS = {"git", "gh", "hg", "svn"}
BUILD = {"make", "cmake", "ninja", "cargo", "rustc", "swift", "swift-build", "swift-frontend", "swift-driver", "swiftc",
         "xcodebuild", "gradle", "gradlew", "mvn", "tsc", "esbuild", "rollup", "clang", "clang++", "gcc", "g++", "go",
         "javac", "ld", "pip", "pip3", "cc", "c++"}
TEST = {"pytest", "py.test", "jest", "vitest", "mocha", "playwright", "xctest", "xcrun"}
SERVER_HINTS = ("vite", "next", "nuxt", "astro", "remix", "webpack-dev-server", "uvicorn", "gunicorn", "flask", "django",
                "http.server", "live-server", "nodemon", "puma", "rails", "runserver", "serve")
PACKAGE_RUNNERS = {"npm", "npx", "pnpm", "yarn", "bunx", "corepack"}

_SECRET_WORD = r"(?:token|secret|passw(?:or)?d|passwd|pwd|api[-_]?key|apikey|auth(?:orization)?|bearer|credential|cookie|session|private[-_]?key|access[-_]?key)"
SECRET_FLAG = re.compile(r"^--?[A-Za-z0-9_-]*" + _SECRET_WORD + r"[A-Za-z0-9_-]*$", re.I)
SECRET_ASSIGN = re.compile(r"^([A-Za-z_][A-Za-z0-9_.-]*" + _SECRET_WORD + r"[A-Za-z0-9_.-]*)=(.+)$", re.I)
OPAQUE_TOKEN = re.compile(
    r"(?:\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}|\bgh[pousr]_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}"
    r"|\bxox[abprs]-[A-Za-z0-9-]{10,}|\bAKIA[0-9A-Z]{16}\b|\bAIza[0-9A-Za-z_-]{30,}"
    r"|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]*|[A-Za-z0-9+/_=-]{40,})")
BEARER = re.compile(r"(?i)\b(bearer|basic)\s+\S+")
URL_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s:@]+(?::[^/\s@]*)?@")


# --- ps parsing ---------------------------------------------------------------

@dataclass
class Proc:
    pid: int
    ppid: int
    pgid: int
    uid: int
    stat: str
    pcpu: float
    rss_kb: int
    elapsed: float
    cpu_time: float
    exe: str = ""
    command: str = ""


def parse_elapsed(text):
    """`[[dd-]hh:]mm:ss` (ps etime) or `[dd-]hh:mm:ss[.cc]` / `m:ss.cc` (ps time) as seconds."""
    try:
        days = 0
        if "-" in text:
            d, text = text.split("-", 1)
            days = int(d)
        parts = text.split(":")
        seconds = 0.0
        for part in parts:
            seconds = seconds * 60 + float(part)
        return days * 86400 + seconds
    except (ValueError, AttributeError):
        return 0.0


def parse_table(text):
    """The numeric `ps` table: pid ppid pgid uid stat pcpu rss etime time command."""
    procs = {}
    for line in text.splitlines():
        parts = line.split(None, 9)
        if len(parts) < 9 or not parts[0].isdigit():
            continue
        try:
            pid, ppid, pgid, uid = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
            procs[pid] = Proc(pid, ppid, pgid, uid, parts[4], float(parts[5]), int(parts[6]),
                              parse_elapsed(parts[7]), parse_elapsed(parts[8]),
                              command=parts[9].strip() if len(parts) > 9 else "")
        except ValueError:
            continue
    return procs


def parse_exes(text, procs):
    """`ps -o pid=,comm=`: the executable (a full path on macOS, a short name on Linux)."""
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and parts[0].isdigit() and int(parts[0]) in procs:
            procs[int(parts[0])].exe = parts[1].strip()


def _unescape_lsof(name):
    """lsof prints bytes ≥ 0x80 as `\\xNN`; a UTF-8 path (a Chinese project folder) comes back as those escapes."""
    if "\\x" not in name:
        return name
    raw = re.sub(rb"\\x([0-9a-fA-F]{2})", lambda m: bytes([int(m.group(1), 16)]), name.encode("utf-8", "replace"))
    return raw.decode("utf-8", "replace")


def parse_lsof(text):
    """`lsof -F pn` → {pid: [names]} (listening addresses or the working directory)."""
    out, pid = defaultdict(list), None
    for line in text.splitlines():
        if line.startswith("p") and line[1:].isdigit():
            pid = int(line[1:])
        elif line.startswith("n") and pid is not None:
            out[pid].append(_unescape_lsof(line[1:]))
    return out


def listening_ports(text):
    ports = defaultdict(set)
    for pid, names in parse_lsof(text).items():
        for name in names:
            match = re.search(r":(\d{1,5})$", name)
            if match and 0 < int(match.group(1)) < 65536:
                ports[pid].add(int(match.group(1)))
    return {pid: sorted(p) for pid, p in ports.items()}


# --- harness detection ----------------------------------------------------------

def _basename(path):
    return PurePath(path).name if path else ""


def match_harness(proc, harnesses=HARNESSES):
    """The harness this process IS (not one it merely started), judged by executable and script."""
    exe = _basename(proc.exe) or _basename(proc.command.split(" ", 1)[0])
    for h in harnesses:
        if exe in h.exes:
            return h
    if INTERPRETER.match(exe):
        tokens = proc.command.split()
        script = next((t for t in tokens[1:] if not t.startswith("-")), "")
        base = _basename(script)
        for h in harnesses:
            if base in h.scripts or any(hint in proc.command for hint in h.hints):
                return h
    return None


# --- presentation: redaction, naming, kinds ----------------------------------------

PATHLIKE = re.compile(r"(\.(?:app|js|mjs|cjs|py|ts|json|sh|rb|asar|unpacked)\b|/Contents/|/node_modules/|/Library/|/Applications/|/usr/|/opt/|/var/|/tmp/)")


def _shorten_path(token, home):
    """Long paths keep their last two segments. Only path-looking tokens are touched: a secret with a
    slash in it must fall through to redaction, not be shown in part."""
    if "/" not in token or not (token.startswith(("/", "~", "./", "../")) or PATHLIKE.search(token)):
        return token
    if home and token.startswith(home + "/"):
        token = "~" + token[len(home):]
    if len(token) > 40:
        parts = [p for p in token.split("/") if p]
        token = "…/" + "/".join(parts[-2:])
    return token


def redact(tokens):
    """Masks secrets in argument tokens; keeps the shape so the command stays recognisable."""
    out, mask_next = [], False
    for token in tokens:
        if mask_next:
            out.append("***")
            mask_next = False
            continue
        if SECRET_FLAG.match(token) and "=" not in token:
            out.append(token)
            mask_next = True
            continue
        if "=" in token and SECRET_FLAG.match(token.split("=", 1)[0]):
            out.append(token.split("=", 1)[0] + "=***")
            continue
        assign = SECRET_ASSIGN.match(token)
        if assign:
            out.append(assign.group(1) + "=***")
            continue
        out.append(OPAQUE_TOKEN.sub("***", token))
    text = " ".join(out)
    text = BEARER.sub(lambda m: m.group(1) + " ***", text)
    return URL_USERINFO.sub(lambda m: m.group(1) + "***@", text)


CODE_FLAGS = {"-c", "-e", "-p", "--eval", "--print", "-lc", "-ic", "-lic", "-ec"}


def describe(proc, home=None):
    """(name, command) for display. Shell and interpreter code bodies are collapsed, secrets masked."""
    exe = _basename(proc.exe) or _basename(proc.command.split(" ", 1)[0])
    # argv[0] may be a path with spaces on macOS: strip the executable path itself when the command starts with it.
    if proc.exe and proc.command.startswith(proc.exe):
        rest = proc.command[len(proc.exe):]
    else:
        parts = proc.command.split(None, 1)
        rest = parts[1] if len(parts) > 1 else ""
    args = rest.split()
    if exe in SHELLS:
        return exe, exe + (" -c …" if any(a in CODE_FLAGS for a in args) else "")
    name, tail = exe or "?", args
    if INTERPRETER.match(exe):
        if args and args[0] in CODE_FLAGS:
            return exe, exe + " " + args[0] + " …"
        i = next((i for i, a in enumerate(args) if not a.startswith("-")), None)
        name, tail = (_basename(args[i]) or exe, args[i + 1:]) if i is not None else (exe, [])
    home = home if home is not None else os.path.expanduser("~")
    shown = redact([_shorten_path(a, home) for a in tail])
    command = (name + " " + shown).strip()
    if len(command) > COMMAND_LIMIT:
        command = command[:COMMAND_LIMIT - 1] + "…"
    return name, command


def classify(name, command, ports):
    lower = command.lower()
    if name in SHELLS:
        return "shell"
    if "mcp" in lower:
        return "mcp"
    if name in TEST or "pytest" in lower or "unittest" in lower or (name in PACKAGE_RUNNERS and re.search(r"\btest\b", lower)):
        return "test"
    if name in VCS:
        return "vcs"
    if name in BUILD or lower.endswith(" build") or " run build" in lower:
        return "build"
    if ports or any(re.search(r"(^|[\s/_.-])" + re.escape(h) + r"($|[\s/_.-])", lower) for h in SERVER_HINTS):
        return "server"
    if INTERPRETER.match(name) or name in PACKAGE_RUNNERS:
        return "runtime"
    return "other"


def state_of(stat):
    return {"R": "running", "S": "sleeping", "I": "idle", "U": "waiting", "D": "waiting",
            "T": "stopped", "t": "stopped", "Z": "zombie"}.get(stat[:1], "unknown")


# --- memory across polls ------------------------------------------------------------

class ProcessMemory:
    """What the previous polls saw: which pids belonged to which harness (so an orphan stays
    attributed after its parent exits) and cumulative CPU time (for instantaneous CPU%)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.owners = {}     # pid -> (app, start_epoch)
        self.cpu = {}        # pid -> (start_epoch, cpu_seconds, wall_seconds)

    def owner(self, pid, start):
        with self.lock:
            hit = self.owners.get(pid)
        return hit[0] if hit and abs(hit[1] - start) <= ORPHAN_SLACK_SECONDS else None

    def remember(self, owned, live):
        """`owned`: pid -> (app, start). Drops everything that is no longer running."""
        with self.lock:
            self.owners = {pid: v for pid, v in {**self.owners, **owned}.items() if pid in live}
            if len(self.owners) > MEMORY_LIMIT:
                self.owners = dict(list(self.owners.items())[-MEMORY_LIMIT:])

    def cpu_percent(self, proc, start, wall):
        with self.lock:
            prev = self.cpu.get(proc.pid)
            self.cpu[proc.pid] = (start, proc.cpu_time, wall)
            if len(self.cpu) > MEMORY_LIMIT:
                self.cpu = dict(list(self.cpu.items())[-MEMORY_LIMIT:])
        if prev and abs(prev[0] - start) <= ORPHAN_SLACK_SECONDS and wall - prev[2] >= 0.5 and proc.cpu_time >= prev[1]:
            return round(max(0.0, (proc.cpu_time - prev[1]) / (wall - prev[2]) * 100), 1), "instant"
        return round(proc.pcpu, 1), "average"


# --- collection ----------------------------------------------------------------------

def _find(*candidates):
    for c in candidates:
        found = shutil.which(c) or (c if os.path.isabs(c) and os.access(c, os.X_OK) else None)
        if found:
            return found
    return None


def default_runner(argv, timeout=4.0):
    """Runs a fixed, absolute command with a clean environment; returns stdout ('' on any failure)."""
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, errors="replace",
                              env={"LC_ALL": "C", "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"})
        return done.stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _empty(now, status, reason=None):
    return {"schema_version": SCHEMA_VERSION, "generated_at": timestamp(now), "scope": "harness_spawned_only",
            "platform": sys.platform, "status": status, "reason": reason, "harnesses": [],
            "totals": {"harness_count": 0, "process_count": 0, "cpu_percent": 0.0, "rss_bytes": 0},
            "notes": ["only_harness_descendants", "no_environment_read", "read_only_no_signals"]}


def _descendants(children, root, limit=5000):
    seen, stack = {root}, [root]
    while stack and len(seen) < limit:
        for child in children.get(stack.pop(), ()):
            if child not in seen:
                seen.add(child)
                stack.append(child)
    return seen


def _ancestors(procs, pid, limit=64):
    out = []
    while limit and pid in procs and procs[pid].ppid not in (0, pid):
        pid = procs[pid].ppid
        out.append(pid)
        limit -= 1
    return out


def collect_processes(config=None, now=None, runner=None, memory=None, harnesses=HARNESSES, own_pid=None):
    """The payload for GET /v1/processes. Never raises: failures become `status: unavailable`."""
    import time as _time
    now = _time.time() if now is None else float(now)
    if sys.platform not in SUPPORTED_PLATFORMS:
        return _empty(now, "unsupported_platform", "process_monitor_needs_macos_or_linux")
    runner = runner or default_runner
    memory = memory if memory is not None else ProcessMemory()
    ps = _find("/bin/ps", "/usr/bin/ps", "ps")
    if not ps:
        return _empty(now, "unavailable", "ps_not_found")
    table = runner([ps, "-axww", "-o", "pid=,ppid=,pgid=,uid=,stat=,pcpu=,rss=,etime=,time=,command="])
    procs = parse_table(table)
    if not procs:
        return _empty(now, "unavailable", "ps_failed")
    parse_exes(runner([ps, "-axww", "-o", "pid=,comm="]), procs)

    me = os.getpid() if own_pid is None else own_pid
    children = defaultdict(list)
    for p in procs.values():
        children[p.ppid].append(p.pid)
    mine = _descendants(children, me) if me in procs else {me}

    roots = {pid: match_harness(p, harnesses) for pid, p in procs.items() if pid not in mine}
    roots = {pid: h for pid, h in roots.items() if h}
    outer = [pid for pid in roots if not any(a in roots for a in _ancestors(procs, pid))]

    start_of = {pid: now - p.elapsed for pid, p in procs.items()}
    attributed = set()

    def walk(root_pid):
        """Depth-first, oldest child first: (pid, depth) rows of one subtree."""
        order, seen, stack = [], set(), [(root_pid, 0)]
        while stack:
            pid, depth = stack.pop()
            if pid in seen or pid in mine or pid in attributed or depth > MAX_DEPTH:
                continue
            seen.add(pid)
            order.append((pid, depth))
            kids = sorted(children.get(pid, ()), key=lambda c: -start_of.get(c, 0))
            stack.extend((c, depth + 1) for c in kids)
        attributed.update(seen)
        return order

    groups = [{"harness": roots[pid], "root": pid, "alive": True, "order": walk(pid)} for pid in sorted(outer)]

    # Orphans: seen under a harness before, parent gone since (reparented to init), still running.
    orphan_roots = defaultdict(list)
    for pid, p in procs.items():
        if pid in attributed or pid in mine:
            continue
        app = memory.owner(pid, start_of[pid])
        if app and (p.ppid <= 1 or p.ppid not in procs):
            orphan_roots[app].append(pid)
    by_app = {h.app: h for h in harnesses}
    for app, pids in sorted(orphan_roots.items()):
        if app not in by_app:
            continue
        order = [row for pid in sorted(pids) for row in walk(pid)]
        if order:
            groups.append({"harness": by_app[app], "root": None, "alive": False, "order": order})

    # Ports and working directories for the reported pids only.
    reported = sorted({pid for g in groups for pid, _ in g["order"]})[:MAX_PROCESSES]
    lsof = _find("/usr/sbin/lsof", "/usr/bin/lsof", "lsof")
    ports, cwds = {}, {}
    if lsof and reported:
        listing = ",".join(str(p) for p in reported)
        ports = listening_ports(runner([lsof, "-nP", "-a", "-iTCP", "-sTCP:LISTEN", "-p", listing, "-F", "pn"], 3.0))
        live_roots = ",".join(str(g["root"]) for g in groups if g["root"] is not None)
        if live_roots:
            cwds = {pid: names[0] for pid, names in
                    parse_lsof(runner([lsof, "-nP", "-a", "-d", "cwd", "-p", live_roots, "-F", "pn"], 3.0)).items() if names}

    home = os.path.expanduser("~")
    out, total_procs, total_cpu, total_rss, budget = [], 0, 0.0, 0, MAX_PROCESSES
    owned = {}
    for g in groups:
        h, items, g_cpu, g_rss, count = g["harness"], [], 0.0, 0, 0
        for pid, depth in g["order"]:
            p = procs[pid]
            owned[pid] = (h.app, start_of[pid])
            cpu, basis = memory.cpu_percent(p, start_of[pid], now)
            g_cpu += cpu
            g_rss += p.rss_kb * 1024
            if pid == g["root"]:
                continue                      # a live harness root is the group header, not a row
            core = match_harness(p, harnesses) is not None
            name, command = describe(p, home)
            kind = "harness" if core else classify(name, command, ports.get(pid))
            count += 0 if core else 1
            if len(items) < MAX_PER_HARNESS and budget > 0:
                budget -= 1
                items.append({"pid": pid, "ppid": p.ppid, "depth": depth, "name": name, "command": command if not core else name,
                              "kind": kind, "state": state_of(p.stat), "cpu_percent": cpu, "cpu_basis": basis,
                              "rss_bytes": p.rss_kb * 1024, "uptime_seconds": int(p.elapsed),
                              "started_at": timestamp(start_of[pid]), "ports": ports.get(pid, []),
                              "orphaned": not g["alive"], "core": core, "owner_uid": p.uid})
        rows = len(g["order"]) - (1 if g["root"] is not None else 0)
        cwd = cwds.get(g["root"]) if g["root"] is not None else None
        oldest = min((procs[pid].elapsed for pid, _ in g["order"]), default=None) if g["root"] is None else None
        total_procs += count
        total_cpu += g_cpu
        total_rss += g_rss
        out.append({"app": h.app, "label": h.label, "pid": g["root"], "alive": g["alive"],
                    "uptime_seconds": int(procs[g["root"]].elapsed) if g["root"] is not None else (int(oldest) if oldest is not None else None),
                    "started_at": timestamp(start_of[g["root"]]) if g["root"] is not None else None,
                    "project_path": cwd, "project_alias": _basename(cwd) or None,
                    "process_count": count, "cpu_percent": round(g_cpu, 1), "rss_bytes": g_rss,
                    "truncated": rows > len(items), "processes": items})
    memory.remember(owned, set(procs))
    out.sort(key=lambda g: (not g["alive"], -g["cpu_percent"], g["pid"]))
    payload = _empty(now, "available")
    payload["harnesses"] = out
    payload["totals"] = {"harness_count": len(out), "process_count": total_procs,
                         "cpu_percent": round(total_cpu, 1), "rss_bytes": total_rss}
    return payload
