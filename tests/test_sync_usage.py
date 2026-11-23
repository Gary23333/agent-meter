import tempfile
import unittest

from agent_meter import sync_usage

NOW = 1795082400  # 2026-11-19 18:00 Asia/Shanghai
LOCAL = "a" * 32
REMOTE = "b" * 32


def row(date, model="glm-5.3", tokens=10, app="codex", device=REMOTE):
    return {"date": date, "app": app, "model": model, "device": device,
            "requests": 2, "fresh_input": 1, "output": 2, "reasoning": 3,
            "cache_read": 4, "cache_write": 0, "total_tokens": tokens}


class UsageTests(unittest.TestCase):
    def store(self, rows):
        return {"schema": 1, "local_device": LOCAL,
                "devices": {REMOTE: {"rows": rows, "quota": [], "cards": {}}}}

    def test_periods_window_and_exclude_this_machine(self):
        rows = [row("2026-11-19"), row("2026-11-14"), row("2026-10-25"), row("2026-09-01")]
        rows.append(row("2026-11-19", device=LOCAL))
        store = self.store(rows)
        store["devices"][LOCAL] = {"rows": [row("2026-11-19", tokens=999, device=LOCAL)]}
        with tempfile.TemporaryDirectory() as home:
            usage = sync_usage.usage_periods(store, home, NOW)
        self.assertEqual(usage["device_count"], 1)
        self.assertEqual(usage["periods"]["today"]["totals"]["total_tokens"], 10)
        self.assertEqual(usage["periods"]["7d"]["totals"]["total_tokens"], 20)
        self.assertEqual(usage["periods"]["30d"]["totals"]["total_tokens"], 30)
        self.assertEqual(usage["periods"]["all"]["totals"]["total_tokens"], 40)
        self.assertEqual(usage["periods"]["today"]["device_count"], 1)

    def test_groups_and_cost_use_the_local_price_table(self):
        with tempfile.TemporaryDirectory() as home:
            usage = sync_usage.usage_periods(self.store([row("2026-11-19")]), home, NOW)
        today = usage["periods"]["today"]
        self.assertEqual([g["app"] + "|" + g["model"] for g in today["groups"]], ["codex|glm-5.3"])
        self.assertEqual(today["groups"][0]["source"], "sync")
        self.assertIsNotNone(today["cost"])
        self.assertEqual(today["cost"]["unit"], "USD")
        self.assertGreater(float(today["cost"]["amount"]), 0)

    def test_no_remote_rows_is_none(self):
        self.assertIsNone(sync_usage.usage_periods({"schema": 1, "local_device": LOCAL, "devices": {}}, "", NOW))


if __name__ == "__main__":
    unittest.main()
