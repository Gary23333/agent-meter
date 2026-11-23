"""Hermetic tests for the harness process monitor.

Every test feeds synthetic `ps` / `lsof` text through an injected runner; nothing reads the real process
table. What is pinned here: only processes descending from a harness are reported, harness roots never carry a
command line, secrets are masked, nothing reads the environment, and orphans stay attributed.
"""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from agent_meter import processes as P
from agent_meter.collector import SnapshotService, default_config
from agent_meter.server import load_or_create_token, make_server

NOW = 1_800_000_000.0
HOME = "/Users/u"


def ps_row(pid, ppid, command, stat="S", pcpu=0.0, rss=2048, etime="10:00", cpu_time="0:01.00", pgid=None, uid=501):
    return f"{pid} {ppid} {pgid or pid} {uid} {stat} {pcpu} {rss} {etime} {cpu_time} {command}"


class FakeSystem:
    """A scripted process table: ps output, comm output and lsof output."""

    def __init__(self, rows, exes=None, ports="", cwds=""):
        self.rows, self.exes, self.ports, self.cwds = rows, exes or {}, ports, cwds
        self.calls = []

    def runner(self, argv, timeout=4.0):
        self.calls.append(list(argv))
        joined = " ".join(argv)
        if "pid=,ppid=" in joined:
            return "\n".join(self.rows)
        if "pid=,comm=" in joined:
            return "\n".join(f"{pid} {exe}" for pid, exe in self.exes.items())
        if "-iTCP" in joined:
            return self.ports
        if "cwd" in joined:
            return self.cwds
        return ""


def collect(system, memory=None, now=NOW, own_pid=999_999):
    with patch.object(P.sys, "platform", "darwin"), patch.object(P, "_find", side_effect=lambda *c: c[0]):
        return P.collect_processes({}, now=now, runner=system.runner, memory=memory or P.ProcessMemory(),
                                   own_pid=own_pid)


def reported_pids(payload):
    pids = set()
    for g in payload["harnesses"]:
        if g["pid"] is not None:
            pids.add(g["pid"])
        pids.update(p["pid"] for p in g["processes"])
    return pids


def standard_machine():
    """A terminal with a Claude Code session running a dev server, next to unrelated apps and a user-run node."""
    rows = [
        ps_row(1, 0, "/sbin/launchd"),
        ps_row(100, 1, "/System/Library/CoreServices/WindowServer -daemon"),
        ps_row(200, 1, "/Applications/Slack.app/Contents/MacOS/Slack"),
        ps_row(201, 200, "/Applications/Slack.app/Contents/Frameworks/Slack Helper --type=renderer"),
        ps_row(300, 1, "/Applications/iTerm.app/Contents/MacOS/iTerm2"),
        ps_row(301, 300, "-zsh"),
        ps_row(302, 301, "node /Users/u/other/node_modules/.bin/vite --port 4000"),
        ps_row(310, 300, "-zsh"),
        ps_row(311, 310, "claude -p refactor my secret project", etime="01:00:00", pcpu=3.0, rss=300_000),
        ps_row(312, 311, "/bin/zsh -c source ~/.zshrc && eval 'npm run dev'"),
        ps_row(313, 312, "npm run dev", pcpu=0.5, rss=60_000),
        ps_row(314, 313, "node /Users/u/proj/node_modules/.bin/vite --port 5173", pcpu=12.0, rss=180_000, etime="00:30"),
    ]
    exes = {1: "/sbin/launchd", 100: "/System/Library/CoreServices/WindowServer", 200: "/Applications/Slack.app/Contents/MacOS/Slack",
            201: "/Applications/Slack.app/Contents/Frameworks/Slack Helper", 300: "/Applications/iTerm.app/Contents/MacOS/iTerm2",
            301: "-zsh", 302: "/usr/local/bin/node", 310: "-zsh", 311: "/Users/u/.local/bin/claude", 312: "/bin/zsh",
            313: "/usr/local/bin/npm", 314: "/usr/local/bin/node"}
    return FakeSystem(rows, exes, ports="p314\nn*:5173\nn[::1]:5173\n", cwds="p311\nn/Users/u/proj\n")


class ScopeTests(unittest.TestCase):
    def test_only_harness_descendants_are_reported(self):
        payload = collect(standard_machine())
        self.assertEqual(payload["status"], "available")
        self.assertEqual(reported_pids(payload), {311, 312, 313, 314})
        self.assertEqual(payload["scope"], "harness_spawned_only")
        # Nothing else on the machine leaks into the payload, not even by name.
        text = json.dumps(payload)
        for stranger in ("Slack", "WindowServer", "iTerm", "other/node_modules", "--port 4000"):
            self.assertNotIn(stranger, text)

    def test_group_header_and_rows(self):
        payload = collect(standard_machine())
        self.assertEqual(len(payload["harnesses"]), 1)
        group = payload["harnesses"][0]
        self.assertEqual((group["app"], group["label"], group["pid"], group["alive"]), ("claude", "Claude Code", 311, True))
        self.assertEqual(group["project_alias"], "proj")
        self.assertEqual(group["process_count"], 3)
        names = [(p["depth"], p["name"]) for p in group["processes"]]
        self.assertEqual(names, [(1, "zsh"), (2, "npm"), (3, "vite")])
        vite = group["processes"][-1]
        self.assertEqual(vite["ports"], [5173])
        self.assertEqual(vite["kind"], "server")
        self.assertEqual(vite["command"], "vite --port 5173")
        self.assertEqual(group["processes"][0]["kind"], "shell")
        self.assertEqual(group["processes"][0]["command"], "zsh -c …")
        self.assertEqual(payload["totals"]["process_count"], 3)
        self.assertEqual(payload["totals"]["harness_count"], 1)
        self.assertEqual(payload["totals"]["rss_bytes"], (300_000 + 2048 + 60_000 + 180_000) * 1024)

    def test_harness_root_never_carries_a_command_line(self):
        text = json.dumps(collect(standard_machine()))
        self.assertNotIn("secret project", text)
        self.assertNotIn("refactor", text)

    def test_case_sensitive_desktop_app_is_not_a_harness(self):
        rows = [ps_row(1, 0, "/sbin/launchd"),
                ps_row(500, 1, "/Applications/Claude.app/Contents/MacOS/Claude"),
                ps_row(501, 500, "/Applications/Claude.app/Contents/Frameworks/Claude Helper --type=gpu-process")]
        exes = {1: "/sbin/launchd", 500: "/Applications/Claude.app/Contents/MacOS/Claude",
                501: "/Applications/Claude.app/Contents/Frameworks/Claude Helper"}
        self.assertEqual(collect(FakeSystem(rows, exes))["harnesses"], [])

    def test_node_wrapper_and_native_child_form_one_group(self):
        rows = [ps_row(1, 0, "/sbin/launchd"),
                ps_row(600, 1, "node /Users/u/.npm/lib/node_modules/@openai/codex/bin/codex.js"),
                ps_row(601, 600, "/Users/u/.npm/lib/node_modules/@openai/codex/vendor/codex/codex --model x"),
                ps_row(602, 601, "/bin/bash -c ls"),
                ps_row(603, 602, "sleep 30")]
        exes = {1: "/sbin/launchd", 600: "/usr/local/bin/node", 601: "/Users/u/.npm/lib/node_modules/@openai/codex/vendor/codex/codex",
                602: "/bin/bash", 603: "/bin/sleep"}
        payload = collect(FakeSystem(rows, exes))
        self.assertEqual(len(payload["harnesses"]), 1)
        group = payload["harnesses"][0]
        self.assertEqual((group["app"], group["pid"]), ("codex", 600))
        core = [p for p in group["processes"] if p["core"]]
        self.assertEqual([p["pid"] for p in core], [601])
        self.assertEqual(core[0]["kind"], "harness")
        self.assertEqual(group["process_count"], 2)              # bash + sleep; the native core is not a spawned process

    def test_a_harness_started_by_another_harness_stays_in_the_outer_group(self):
        rows = [ps_row(1, 0, "/sbin/launchd"), ps_row(700, 1, "claude"),
                ps_row(701, 700, "codex mcp-server"), ps_row(702, 701, "/bin/zsh")]
        exes = {1: "/sbin/launchd", 700: "/usr/local/bin/claude", 701: "/usr/local/bin/codex", 702: "/bin/zsh"}
        payload = collect(FakeSystem(rows, exes))
        self.assertEqual([g["app"] for g in payload["harnesses"]], ["claude"])
        self.assertEqual({p["pid"] for p in payload["harnesses"][0]["processes"]}, {701, 702})

    def test_own_process_tree_is_excluded(self):
        payload = collect(standard_machine(), own_pid=313)       # the backend itself runs under the harness
        self.assertEqual(reported_pids(payload), {311, 312})

    def test_mcp_servers_started_by_a_harness_are_listed(self):
        rows = [ps_row(1, 0, "/sbin/launchd"), ps_row(800, 1, "claude"),
                ps_row(801, 800, "node /Users/u/.npm/_npx/abc/node_modules/.bin/playwright-mcp --headless")]
        exes = {1: "/sbin/launchd", 800: "/usr/local/bin/claude", 801: "/usr/local/bin/node"}
        row = collect(FakeSystem(rows, exes))["harnesses"][0]["processes"][0]
        self.assertEqual((row["kind"], row["name"]), ("mcp", "playwright-mcp"))


class OrphanTests(unittest.TestCase):
    def machine(self, claude_alive):
        rows = [ps_row(1, 0, "/sbin/launchd"), ps_row(900, 1, "/usr/sbin/cron")]
        exes = {1: "/sbin/launchd", 900: "/usr/sbin/cron", 914: "/usr/local/bin/node"}
        if claude_alive:
            rows += [ps_row(911, 1, "claude"), ps_row(912, 911, "/bin/zsh -c x"),
                     ps_row(914, 912, "node /proj/server.js", etime="05:00")]
            exes.update({911: "/usr/local/bin/claude", 912: "/bin/zsh"})
        else:
            rows += [ps_row(914, 1, "node /proj/server.js", etime="05:08")]      # same process, parent chain gone
        return FakeSystem(rows, exes)

    def test_process_left_behind_stays_attributed(self):
        memory = P.ProcessMemory()
        first = collect(self.machine(True), memory, now=NOW)
        self.assertTrue(first["harnesses"][0]["alive"])
        second = collect(self.machine(False), memory, now=NOW + 8)
        group = second["harnesses"][0]
        self.assertEqual((group["app"], group["alive"], group["pid"]), ("claude", False, None))
        row = group["processes"][0]
        self.assertEqual((row["pid"], row["orphaned"], row["name"]), (914, True, "server.js"))
        self.assertNotIn(900, reported_pids(second))            # an unrelated daemon under init is not an orphan of anyone

    def test_reused_pid_is_not_attributed(self):
        memory = P.ProcessMemory()
        collect(self.machine(True), memory, now=NOW)
        reused = FakeSystem([ps_row(1, 0, "/sbin/launchd"), ps_row(914, 1, "node /other/thing.js", etime="00:02")],
                            {1: "/sbin/launchd", 914: "/usr/local/bin/node"})
        self.assertEqual(collect(reused, memory, now=NOW + 8)["harnesses"], [])


class CpuTests(unittest.TestCase):
    def machine(self, cpu_time):
        rows = [ps_row(1, 0, "/sbin/launchd"), ps_row(10, 1, "claude", cpu_time="1:00.00"),
                ps_row(11, 10, "node /p/a.js", pcpu=0.2, cpu_time=cpu_time)]
        return FakeSystem(rows, {1: "/sbin/launchd", 10: "/usr/local/bin/claude", 11: "/usr/local/bin/node"})

    def test_instant_cpu_comes_from_cumulative_time(self):
        memory = P.ProcessMemory()
        first = collect(self.machine("0:10.00"), memory, now=NOW)["harnesses"][0]["processes"][0]
        self.assertEqual((first["cpu_percent"], first["cpu_basis"]), (0.2, "average"))
        second = collect(self.machine("0:11.00"), memory, now=NOW + 2)["harnesses"][0]["processes"][0]
        self.assertEqual((second["cpu_percent"], second["cpu_basis"]), (50.0, "instant"))


class RedactionTests(unittest.TestCase):
    def describe(self, command, exe="/usr/local/bin/tool"):
        return P.describe(P.Proc(1, 0, 1, 501, "S", 0, 0, 0, 0, exe=exe, command=command), home=HOME)

    def test_secret_flags_and_assignments_are_masked(self):
        cases = {
            "tool --api-key sk-abcdefghijklmnopqrstuvwx run": "tool --api-key *** run",
            "tool --token=abc123 run": "tool --token=*** run",
            "tool OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwx run": "tool OPENAI_API_KEY=*** run",
            "tool https://user:hunter2@example.com/x": "tool https://***@example.com/x",
            "tool -H Authorization: Bearer abcdef123456 --url x": "tool -H Authorization: Bearer *** --url x",
            "tool ghp_abcdefghijklmnopqrstuvwxyz0123456789": "tool ***",
            "tool " + "a1b2c3d4" * 6: "tool ***",
            "tool --password hunter2": "tool --password ***",
        }
        for command, expected in cases.items():
            with self.subTest(command=command):
                self.assertEqual(self.describe(command)[1], expected)

    def test_code_bodies_are_collapsed(self):
        self.assertEqual(self.describe("/bin/zsh -c echo SECRET=1", "/bin/zsh"), ("zsh", "zsh -c …"))
        self.assertEqual(self.describe("python3 -c import os;print(os.environ)", "/usr/bin/python3"), ("python3", "python3 -c …"))
        self.assertEqual(self.describe("/bin/bash", "/bin/bash"), ("bash", "bash"))

    def test_interpreter_script_is_the_name(self):
        self.assertEqual(self.describe("node /proj/node_modules/.bin/vite --port 5173", "/usr/local/bin/node"),
                         ("vite", "vite --port 5173"))
        self.assertEqual(self.describe("python3 -m http.server 8000", "/usr/bin/python3"), ("http.server", "http.server 8000"))

    def test_app_bundle_paths_with_spaces_are_not_mistaken_for_secrets(self):
        command = ("/Applications/My Tool.app/Contents/MacOS/My Tool "
                   "/Applications/My Tool.app/Contents/Resources/app.asar.unpacked/node_modules/opencode/bin/opencode.js serve")
        name, shown = self.describe(command, "/Applications/My Tool.app/Contents/MacOS/My Tool")
        self.assertEqual(name, "My Tool")
        self.assertNotIn("***", shown)
        self.assertTrue(shown.endswith("serve"))

    def test_a_secret_with_slashes_is_masked_not_shortened(self):
        secret = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEYab"
        shown = self.describe("tool " + secret)[1]
        self.assertNotIn("EXAMPLEKEY", shown)
        self.assertNotIn("K7MDENG", shown)

    def test_long_commands_and_paths_are_shortened(self):
        command = "tool " + "/Users/u/a/very/long/path/to/some/deeply/nested/project/file.txt " * 6
        name, shown = self.describe(command)
        self.assertLessEqual(len(shown), P.COMMAND_LIMIT)
        self.assertNotIn("/Users/u/a/very", shown)
        self.assertEqual(self.describe("tool /Users/u/notes.txt")[1], "tool ~/notes.txt")


class ClassifyTests(unittest.TestCase):
    def test_kinds(self):
        cases = [("zsh", "zsh", None, "shell"), ("git", "git status", None, "vcs"), ("swift-build", "swift-build", None, "build"),
                 ("pytest", "pytest tests", None, "test"), ("npm", "npm test", None, "test"), ("node", "node app.js", [3000], "server"),
                 ("node", "node script.js", None, "runtime"), ("playwright-mcp", "playwright-mcp", None, "mcp"),
                 ("sleep", "sleep 30", None, "other"), ("python3", "python3 -m unittest", None, "test")]
        for name, command, ports, kind in cases:
            with self.subTest(name=name, command=command):
                self.assertEqual(P.classify(name, command, ports), kind)


class ParserTests(unittest.TestCase):
    def test_elapsed_and_cpu_time(self):
        self.assertEqual(P.parse_elapsed("01:02:03"), 3723)
        self.assertEqual(P.parse_elapsed("2-00:00:10"), 2 * 86400 + 10)
        self.assertEqual(P.parse_elapsed("0:11.50"), 11.5)
        self.assertEqual(P.parse_elapsed("garbage"), 0.0)

    def test_table_skips_malformed_rows_and_keeps_spaced_commands(self):
        procs = P.parse_table("  PID\n" + ps_row(5, 1, "/Applications/My App.app/Contents/MacOS/My App --flag") + "\nnot a row")
        self.assertEqual(list(procs), [5])
        self.assertEqual(procs[5].command, "/Applications/My App.app/Contents/MacOS/My App --flag")

    def test_lsof_escapes_decode_to_utf8(self):
        self.assertEqual(P.parse_lsof("p9\nn/Users/u/\\xe9\\xa1\\xb9\\xe7\\x9b\\xae/app\n")[9], ["/Users/u/项目/app"])

    def test_lsof_ports(self):
        self.assertEqual(P.listening_ports("p5\nn*:3000\nn127.0.0.1:8769\np6\nn[::1]:3000\nn*:notaport\n"),
                         {5: [3000, 8769], 6: [3000]})

    def test_harness_matching(self):
        def proc(exe, command):
            return P.Proc(1, 0, 1, 501, "S", 0, 0, 0, 0, exe=exe, command=command)
        self.assertEqual(P.match_harness(proc("/x/claude", "claude")).app, "claude")
        self.assertEqual(P.match_harness(proc("/usr/bin/node", "node /x/@anthropic-ai/claude-code/cli.js")).app, "claude")
        self.assertEqual(P.match_harness(proc("/usr/bin/python3", "python3 /x/bin/kimi chat")).app, "kimi")
        self.assertIsNone(P.match_harness(proc("/usr/bin/node", "node /x/vite.js")))
        self.assertIsNone(P.match_harness(proc("/Applications/Claude.app/Contents/MacOS/Claude", "Claude")))
        self.assertIsNone(P.match_harness(proc("/usr/bin/claudette", "claudette")))


class SafetyTests(unittest.TestCase):
    def test_only_ps_and_lsof_run_and_never_the_environment(self):
        system = standard_machine()
        collect(system)
        self.assertTrue(system.calls)
        for argv in system.calls:
            self.assertIn(Path(argv[0]).name, {"ps", "lsof"})
            flags = " ".join(argv[1:])
            self.assertNotRegex(flags, r"(^|\s)-?[a-zA-Z]*E[a-zA-Z]*(\s|$)(?!.*pid=)")    # no `ps -E`/`eww`-style env switches
            self.assertNotIn("env", flags.replace("pid=,ppid=", ""))
            self.assertNotIn("-k", argv)                                                # nothing that could signal
        # ps asks only for the fixed columns.
        ps_calls = [" ".join(c) for c in system.calls if Path(c[0]).name == "ps"]
        self.assertTrue(all("command=" in c or "comm=" in c for c in ps_calls))

    def test_unsupported_platform_and_ps_failure_never_raise(self):
        with patch.object(P.sys, "platform", "win32"):
            payload = P.collect_processes({}, now=NOW)
        self.assertEqual((payload["status"], payload["harnesses"]), ("unsupported_platform", []))
        broken = FakeSystem([])
        self.assertEqual(collect(broken)["status"], "unavailable")

    def test_payload_is_capped(self):
        rows = [ps_row(1, 0, "/sbin/launchd"), ps_row(2, 1, "claude")]
        exes = {1: "/sbin/launchd", 2: "/usr/local/bin/claude"}
        for pid in range(10, 10 + 600):
            rows.append(ps_row(pid, 2, "sleep 1"))
            exes[pid] = "/bin/sleep"
        group = collect(FakeSystem(rows, exes))["harnesses"][0]
        self.assertEqual(len(group["processes"]), P.MAX_PER_HARNESS)
        self.assertTrue(group["truncated"])
        self.assertEqual(group["process_count"], 600)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.token = load_or_create_token(Path(self.tmp.name) / "api.token")
        cfg = default_config()
        cfg["runtime_dir"] = self.tmp.name
        self.clock = [NOW]
        self.service = SnapshotService(cfg, lambda config, now: {}, lambda: self.clock[0])
        self.server = make_server(self.service, self.token, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:" + str(self.server.server_address[1])

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def request(self, path, auth=True):
        headers = {"Authorization": "Bearer " + self.token} if auth else {}
        return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
            urllib.request.Request(self.url + path, headers=headers), timeout=5)

    def test_endpoint_contract(self):
        with patch("agent_meter.processes.collect_processes", return_value=P._empty(NOW, "available")) as spy:
            with self.request("/v1/processes") as response:
                self.assertEqual(response.status, 200)
                payload = json.load(response)
            self.assertEqual(payload["schema_version"], 1)
            self.assertEqual(payload["scope"], "harness_spawned_only")
            self.assertEqual(spy.call_count, 1)

    def test_rejects_query_and_missing_auth(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.request("/v1/processes", auth=False)
        self.assertEqual(ctx.exception.code, 401)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.request("/v1/processes?pid=1")
        self.assertEqual(ctx.exception.code, 400)

    def test_polling_is_cached_for_a_moment(self):
        with patch("agent_meter.processes.collect_processes", return_value=P._empty(NOW, "available")) as spy:
            self.service.processes()
            self.service.processes()
            self.assertEqual(spy.call_count, 1)
            self.clock[0] += 5
            self.service.processes()
            self.assertEqual(spy.call_count, 2)

    def test_processes_never_trigger_a_collection(self):
        calls = []
        service = SnapshotService(default_config(), lambda config, now: calls.append(1) or {}, lambda: NOW)
        with patch("agent_meter.processes.collect_processes", return_value=P._empty(NOW, "available")):
            service.processes()
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
