import unittest

from agent_meter.account_check import account_connection_report

NOW = 1762600000.0


def src(sid, status, reason=None, quota=None):
    return {"id": sid, "status": status, "diagnostics": {"reason": reason},
            "metrics": {"quota": {"status": quota or "not_provided"}}}


class AccountCheckTests(unittest.TestCase):
    def test_connected_and_missing(self):
        sources = [
            src("qoder", "available", None, "available"),
            src("workbuddy", "not_connected", "not_authenticated"),
            src("mimo", "not_connected", "mimo_not_authenticated"),
            src("stepfun", "not_connected", "stepfun_credential_not_connected"),
            src("volcengine", "not_connected", "volcengine_credential_not_connected"),
            src("qoder#2", "not_connected", "not_authenticated"),   # secondary accounts ignored
        ]
        report = account_connection_report(sources)
        self.assertEqual(report["connected"], ["qoder"])
        self.assertEqual(report["missing"], ["workbuddy", "mimo", "stepfun", "volcengine"])
        qoder = next(r for r in report["targets"] if r["source"] == "qoder")
        self.assertTrue(qoder["has_quota"])

    def test_disabled_is_not_connected(self):
        report = account_connection_report([src("qoder", "not_connected", "disabled_by_user")])
        self.assertIn("qoder", report["missing"])

    def test_absent_source_reported(self):
        report = account_connection_report([])
        self.assertEqual(len(report["targets"]), 5)
        self.assertEqual(set(report["missing"]), {"qoder", "workbuddy", "mimo", "stepfun", "volcengine"})


if __name__ == "__main__":
    unittest.main()