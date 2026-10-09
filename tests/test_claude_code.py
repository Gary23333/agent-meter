import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from agent_meter.claude_code import collect_claude, collect_claude_web, normalize_claude, pick_organization, read_credentials
from agent_meter.model import SourceError

NOW = datetime(2026, 10, 9, 3, 0, tzinfo=timezone.utc).timestamp()
OAUTH = {"accessToken": "PRIVATE_ACCESS", "refreshToken": "PRIVATE_REFRESH",
         "expiresAt": (NOW + 3600) * 1000, "subscriptionType": "max", "scopes": ["user:inference"]}
USAGE = {"five_hour": {"utilization": 37.0, "resets_at": "2026-10-09T05:00:00.123+00:00"},
         "seven_day": {"utilization": 12, "resets_at": "2026-10-13T00:00:00Z"},
         "seven_day_opus": None,
         "seven_day_sonnet": {"utilization": None, "resets_at": None},
         "extra_usage": {"is_enabled": False, "monthly_limit": None, "used_credits": None}}


def keychain(code, payload=b""):
    return subprocess.CompletedProcess([], code, payload, b"")


class ClaudeCodeTests(unittest.TestCase):
    def test_windows_plan_and_redaction(self):
        out = normalize_claude(USAGE, OAUTH, NOW)
        quota = out["metrics"]["quota"]["value"]
        self.assertEqual([q["bucket"] for q in quota], ["five_hour", "seven_day"])
        self.assertEqual(quota[0]["remaining_percent"], 63.0)
        self.assertEqual(quota[0]["window_minutes"], 300)
        self.assertEqual(quota[1]["resets_at"]["display"], "2026-10-13T08:00:00+08:00")
        self.assertEqual(out["subscription"], {"plan": "max"})
        self.assertNotIn("PRIVATE", json.dumps(out))

    def test_zero_is_kept_and_bad_values_rejected(self):
        out = normalize_claude({"five_hour": {"utilization": 0, "resets_at": None}}, OAUTH, NOW)
        self.assertEqual(out["metrics"]["quota"]["value"][0]["remaining_percent"], 100)
        for bad in [{"five_hour": {"utilization": -1}}, {"five_hour": "x"}, {}, []]:
            with self.assertRaises(SourceError):
                normalize_claude(bad, OAUTH, NOW)

    def test_keychain_read_is_query_only(self):
        payload = json.dumps({"claudeAiOauth": OAUTH}).encode()
        with tempfile.TemporaryDirectory() as home, \
                patch("agent_meter.claude_code.subprocess.run", return_value=keychain(0, payload)) as run:
            self.assertEqual(read_credentials(home, 5)["accessToken"], "PRIVATE_ACCESS")
        args = run.call_args.args[0]
        self.assertEqual(args[1:], ["find-generic-password", "-s", "Claude Code-credentials", "-w"])
        self.assertFalse(run.call_args.kwargs.get("shell", False))

    def test_keychain_states(self):
        with tempfile.TemporaryDirectory() as home:
            for code, expected in [(44, "claude_subscription_login_missing"), (128, "claude_keychain_denied")]:
                with patch("agent_meter.claude_code.subprocess.run", return_value=keychain(code)):
                    with self.assertRaises(SourceError) as ctx:
                        read_credentials(home, 5)
                self.assertEqual(ctx.exception.code, expected)
            with patch("agent_meter.claude_code.subprocess.run", side_effect=subprocess.TimeoutExpired("x", 1)):
                with self.assertRaises(SourceError) as ctx:
                    read_credentials(home, 5)
            self.assertEqual(ctx.exception.code, "claude_keychain_timeout")

    def test_credentials_file_preferred(self):
        with tempfile.TemporaryDirectory() as home:
            (Path(home) / ".claude").mkdir()
            (Path(home) / ".claude/.credentials.json").write_text(json.dumps({"claudeAiOauth": OAUTH}))
            with patch("agent_meter.claude_code.subprocess.run") as run:
                self.assertEqual(read_credentials(home, 5)["subscriptionType"], "max")
            run.assert_not_called()

    def test_expired_token_is_not_refreshed_or_sent(self):
        expired = dict(OAUTH, expiresAt=(NOW - 1) * 1000)
        with patch("agent_meter.claude_code.read_credentials", return_value=expired), \
                patch("agent_meter.claude_code.get_json") as get:
            with self.assertRaises(SourceError) as ctx:
                collect_claude("/home", NOW)
        self.assertEqual(ctx.exception.code, "claude_token_expired")
        get.assert_not_called()

    def test_request_shape(self):
        with patch("agent_meter.claude_code.read_credentials", return_value=OAUTH), \
                patch("agent_meter.claude_code.get_json", return_value=USAGE) as get:
            collect_claude("/home", NOW)
        url, token = get.call_args.args[:2]
        self.assertEqual(url, "https://api.anthropic.com/api/oauth/usage")
        self.assertEqual(token, "PRIVATE_ACCESS")
        self.assertEqual(get.call_args.kwargs["headers"]["anthropic-beta"], "oauth-2025-04-20")


    def test_web_org_choice(self):
        orgs = [{"uuid": "11111111-api", "capabilities": ["api"]},
                {"uuid": "22222222-aaaa", "capabilities": ["chat", "claude_max"]}]
        self.assertEqual(pick_organization(orgs)["uuid"], "22222222-aaaa")
        for bad in [{}, [], [{"uuid": "../../evil"}], [{"uuid": "11111111-api", "capabilities": ["api"]}]]:
            with self.assertRaises(SourceError):
                pick_organization(bad)

    def test_web_route(self):
        orgs = [{"uuid": "22222222-aaaa", "capabilities": ["chat"]}]
        with patch("agent_meter.claude_code.get_json", side_effect=[orgs, USAGE]) as get:
            out = collect_claude_web({"cookie": "sessionKey=PRIVATE_SK; cf=1", "user_agent": "UA"}, NOW)
        self.assertEqual(get.call_args_list[1].args[0], "https://claude.ai/api/organizations/22222222-aaaa/usage")
        self.assertEqual(get.call_args.kwargs["headers"]["Cookie"], "sessionKey=PRIVATE_SK; cf=1")
        self.assertEqual(out["diagnostics"]["transport"], "claude_ai_web_session")
        self.assertEqual(out["metrics"]["quota"]["value"][0]["remaining_percent"], 63.0)
        self.assertNotIn("PRIVATE_SK", json.dumps(out))
        self.assertNotIn("22222222-aaaa", json.dumps(out))
        with self.assertRaises(SourceError) as ctx:
            collect_claude_web({"cookie": "other=1"}, NOW)
        self.assertEqual(ctx.exception.code, "web_session_missing")


if __name__ == "__main__":
    unittest.main()
