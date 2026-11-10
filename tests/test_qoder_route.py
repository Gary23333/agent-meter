import unittest
from unittest import mock

from agent_meter.collector import collect_qoder_route
from agent_meter.model import SourceError

NOW = 1762600000.0
CONFIG = {"qoder_app": "/Applications/Qoder CN.app", "node_binary": "/usr/bin/node"}


class QoderRouteTests(unittest.TestCase):
    def test_web_success_skips_sdk(self):
        web_out = {"id": "qoder", "status": "available"}
        with mock.patch("agent_meter.collector.collect_qoder_web", return_value=web_out) as web, \
                mock.patch("agent_meter.collector.collect_qoder") as sdk:
            self.assertIs(collect_qoder_route(CONFIG, {"token": "t"}, "/tmp/r", NOW, 20), web_out)
            web.assert_called_once()
            sdk.assert_not_called()

    def test_expired_web_falls_back_to_sdk(self):
        sdk_out = {"id": "qoder", "status": "available"}
        with mock.patch("agent_meter.collector.collect_qoder_web",
                        side_effect=SourceError("not_authenticated")), \
                mock.patch("agent_meter.collector.collect_qoder", return_value=sdk_out) as sdk:
            self.assertIs(collect_qoder_route(CONFIG, {"token": "expired"}, "/tmp/r", NOW, 20), sdk_out)
            sdk.assert_called_once()

    def test_no_web_goes_straight_to_sdk(self):
        sdk_out = {"id": "qoder", "status": "available"}
        with mock.patch("agent_meter.collector.collect_qoder_web") as web, \
                mock.patch("agent_meter.collector.collect_qoder", return_value=sdk_out):
            self.assertIs(collect_qoder_route(CONFIG, None, "/tmp/r", NOW, 20), sdk_out)
            web.assert_not_called()

    def test_both_fail_surfaces_web_error(self):
        with mock.patch("agent_meter.collector.collect_qoder_web",
                        side_effect=SourceError("not_authenticated")), \
                mock.patch("agent_meter.collector.collect_qoder",
                           side_effect=SourceError("qoder_not_authenticated")):
            with self.assertRaises(SourceError) as raised:
                collect_qoder_route(CONFIG, {"token": "expired"}, "/tmp/r", NOW, 20)
            self.assertEqual(raised.exception.code, "not_authenticated")

    def test_no_web_sdk_failure_propagates(self):
        with mock.patch("agent_meter.collector.collect_qoder",
                        side_effect=SourceError("qoder_sdk_not_installed")):
            with self.assertRaises(SourceError) as raised:
                collect_qoder_route(CONFIG, None, "/tmp/r", NOW, 20)
            self.assertEqual(raised.exception.code, "qoder_sdk_not_installed")


if __name__ == "__main__":
    unittest.main()