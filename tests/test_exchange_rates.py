from decimal import Decimal
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from agent_meter.exchange_rates import FX_FALLBACK, exchange_rate, fetch_quote, rate_from
from agent_meter.model import SourceError
from agent_meter.prices import load_prices


class ExchangeRateTests(unittest.TestCase):
    def test_live_quote_drives_both_price_tables_and_survives_network_failure(self):
        quote = {"chart": {"result": [{"meta": {
            "symbol": "CNY=X", "currency": "CNY", "regularMarketPrice": 6.7,
            "regularMarketTime": 997}}]}}
        with TemporaryDirectory() as runtime, patch("agent_meter.exchange_rates.get_json") as get:
            get.return_value = quote
            snapshot = {"exchange_rate": exchange_rate(runtime, 1000, online=True)}
            self.assertEqual(snapshot["exchange_rate"]["status"], "live")
            self.assertEqual(exchange_rate(runtime, 1050, online=True), snapshot["exchange_rate"])
            get.assert_called_once()
            cny = load_prices(runtime, "CNY", fx_rate=rate_from(snapshot))
            usd = load_prices(runtime, "USD", fx_rate=rate_from(snapshot))
            self.assertEqual(cny.models["gpt-5.4"][0], 16.75)
            self.assertEqual(cny.models["glm-5.3"][0], 8.0)
            self.assertEqual(usd.fx_rate, Decimal("6.7"))
            self.assertEqual(usd.models["hy4"][0], 0.8955)
            get.side_effect = SourceError("connection_failed")
            stale = exchange_rate(runtime, 1400, online=True)
            self.assertEqual(stale["status"], "cached")
            self.assertEqual(stale["usd_cny"], "6.7")
            exchange_rate(runtime, 1401, online=True)
            self.assertEqual(get.call_count, 2)

    def test_invalid_pair_falls_back_without_overwriting_a_quote(self):
        with TemporaryDirectory() as runtime, patch("agent_meter.exchange_rates.get_json") as get:
            get.return_value = {"chart": {"result": [{"meta": {
                "symbol": "CNH=X", "currency": "CNH", "regularMarketPrice": 6.7,
                "regularMarketTime": 997}}]}}
            with self.assertRaises(SourceError):
                fetch_quote(1000)
            offline = exchange_rate(runtime, 1000)
            get.assert_called_once()
            self.assertEqual(offline["status"], "fallback")
            self.assertEqual(rate_from({"exchange_rate": offline}), FX_FALLBACK)
            self.assertEqual(exchange_rate(runtime, 1000, online=True), offline)
