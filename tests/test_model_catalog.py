import tempfile
import unittest

from agent_meter.model_catalog import load_catalog, sync_catalog
from agent_meter.prices import load_prices


class ModelCatalogTests(unittest.TestCase):
    def payload(self):
        return {
            "openai": {"models": {
                "gpt-6.1-sol": {"name": "GPT-6.1 Sol", "release_date": "2026-09-29",
                                "cost": {"input": 2, "cache_read": 0.1, "cache_write": 2.5, "output": 10}},
                "gpt-experience": {"name": "GPT Experience", "cost": {"input": 0, "output": 0}},
            }},
            "ignored": {"models": {"unknown": {"cost": {"input": 99, "output": 99}}}},
        }

    def test_sync_preserves_user_prices_and_skips_unpriced(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = sync_catalog(tmp, force=True, fetcher=self.payload, now=1000)
            self.assertEqual(result["status"], "updated")
            self.assertEqual(result["added"], 1)
            self.assertNotIn("gpt-experience", load_catalog(tmp))
            table = load_prices(tmp)
            self.assertEqual(table.match("openai/gpt-6.1-sol"), "gpt-6.1-sol")
            self.assertIsNone(table.match("gpt-experience"))

    def test_daily_throttle_and_stale_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            sync_catalog(tmp, force=True, fetcher=self.payload, now=1000)
            result = sync_catalog(tmp, fetcher=lambda: (_ for _ in ()).throw(AssertionError()), now=2000)
            self.assertEqual(result["status"], "fresh")
            result = sync_catalog(tmp, force=True, fetcher=lambda: (_ for _ in ()).throw(OSError("offline")), now=90000)
            self.assertEqual(result["status"], "stale")
            self.assertIn("gpt-6.1-sol", load_catalog(tmp))


if __name__ == "__main__":
    unittest.main()
