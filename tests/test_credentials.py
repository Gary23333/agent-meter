import json
import tempfile
import unittest
from pathlib import Path

from agent_meter.minimax import credential_from_ccswitch
from agent_meter.model import SourceError
from tests.support import database


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'cc.db';self.c=database(self.path)
        self.c.execute('CREATE TABLE providers(settings_config TEXT,is_current INTEGER)');self.c.commit()
    def tearDown(self):self.c.close();self.tmp.cleanup()

    def add(self,url,key,current=1):
        self.c.execute('INSERT INTO providers VALUES(?,?)',(json.dumps({'env':{'ANTHROPIC_BASE_URL':url,'ANTHROPIC_AUTH_TOKEN':key}}),current));self.c.commit()

    def test_exact_host_and_current_provider_only(self):
        self.add('https://api.minimax.cn.attacker.invalid','bad-key')
        self.add('https://api.minimax.cn','inactive-key',0)
        self.assertEqual(credential_from_ccswitch(self.path),(None,None))
        self.add('https://api.minimax.cn/anthropic','test-key')
        self.assertEqual(credential_from_ccswitch(self.path),('test-key','cn'))

    def test_multiple_accounts_require_explicit_selection(self):
        self.add('https://api.minimax.cn','key-one');self.add('https://api.minimax.io','key-two')
        with self.assertRaisesRegex(SourceError,'multiple_minimax_accounts_require_selection'):
            credential_from_ccswitch(self.path)

    def test_usage_scripts_never_executed(self):
        target=Path(self.tmp.name)/'should-not-exist'
        text=json.dumps({'usage_script':{'script':"writeFile('"+str(target)+"','unsafe')"}})
        self.c.execute('INSERT INTO providers VALUES(?,1)',(text,));self.c.commit()
        self.assertEqual(credential_from_ccswitch(self.path),(None,None))
        self.assertFalse(target.exists())
