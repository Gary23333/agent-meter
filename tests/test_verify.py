import unittest
from agent_meter.codex import normalize_limits
from agent_meter.verify import verify_snapshot
from tests.test_sources import LIMITS,NOW


class VerificationTests(unittest.TestCase):
    def audit(self,expected_used=25,identity=None):
        src=normalize_limits(LIMITS,NOW)
        snapshot={'collected_at':src['observed_at'],'sources':[src],'coverage':[]}
        ref={'account_key':identity or src['account_key'],'quota_buckets':[{'bucket':'codex',
             'primary':{'usedPercent':expected_used,'windowDurationMins':300,'resetsAt':1791483600},
             'credits':{'balance':'0','hasCredits':False,'unlimited':False}}],
             'cards':{'available_count':3,'expires_at':[1792000000]}}
        return verify_snapshot(snapshot,{},ref)

    def test_reference_checks_all_native_dimensions(self):
        report=self.audit()
        self.assertEqual(report['failed_checks'],0)
        self.assertEqual(report['inconclusive_checks'],0)
        self.assertTrue(any(c['name']=='codex.native.cards.expiry_seconds' for c in report['checks']))

    def test_different_account_fails_identity(self):
        report=self.audit(identity='wrong-account')
        self.assertEqual(report['failed_checks'],1)

    def test_large_usage_mismatch_fails(self):
        self.assertEqual(self.audit(expected_used=75)['failed_checks'],1)

    def test_small_live_drift_inconclusive_not_passed(self):
        report=self.audit(expected_used=26)
        self.assertEqual(report['failed_checks'],0)
        self.assertEqual(report['inconclusive_checks'],1)
