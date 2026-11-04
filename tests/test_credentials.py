import json
import tempfile
import unittest
from pathlib import Path

from agent_meter.minimax import credential_from_local_store


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.runtime = Path(self.tmp.name)

    def write(self, payload):
        path = self.runtime / "secrets" / "minimax_code.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload if isinstance(payload, str) else json.dumps(payload))
        return path

    def test_missing_store(self):
        self.assertEqual(credential_from_local_store(self.runtime), (None, None))

    def test_migrated_key_and_region(self):
        self.write({"api_key": "test-key", "region": "global"})
        self.assertEqual(credential_from_local_store(self.runtime), ("test-key", "global"))

    def test_unknown_region_falls_back_to_cn(self):
        self.write({"api_key": "test-key", "region": "mars"})
        self.assertEqual(credential_from_local_store(self.runtime), ("test-key", "cn"))

    def test_malformed_or_empty_store(self):
        self.write("not json")
        self.assertEqual(credential_from_local_store(self.runtime), (None, None))
        self.write({"api_key": ""})
        self.assertEqual(credential_from_local_store(self.runtime), (None, None))
