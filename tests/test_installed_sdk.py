import json
import struct
import tempfile
import unittest
from pathlib import Path

from agent_meter.installed_sdk import materialize_qoder_sdk
from agent_meter.model import SourceError


class SDKTests(unittest.TestCase):
    def test_only_installed_code_materialized_and_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);archive=root/'app.asar'
            body=b'export const test=1;'
            node={'files':{'node_modules':{'files':{'@qoder-ai':{'files':{'qoder-cn-agent-sdk':{'files':{
                'dist':{'files':{'index.js':{'size':len(body),'offset':'0'}}}}}}}}}}}
            header=json.dumps(node).encode();size=len(header)+8
            archive.write_bytes(b'\0'*4+struct.pack('<I',size)+b'\0'*8+header+body)
            a=materialize_qoder_sdk(archive,root/'runtime')
            self.assertEqual(a.read_bytes(),body)
            self.assertEqual(materialize_qoder_sdk(archive,root/'runtime'),a)

    def test_invalid_header_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);archive=root/'app.asar'
            archive.write_bytes(b'\0'*4+struct.pack('<I',2)+b'\0'*8)
            with self.assertRaises(SourceError):materialize_qoder_sdk(archive,root/'runtime')
