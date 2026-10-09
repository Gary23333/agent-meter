import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from agent_meter.transport import CodexRPC, get_json
from agent_meter.model import SourceError


class RPCTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory()
    def tearDown(self):self.tmp.cleanup()

    def child(self,code):
        p=Path(self.tmp.name)/'fake-codex'
        p.write_text('#!/usr/bin/python3\n'+code)
        p.chmod(0o700)
        return str(p)

    def test_notifications_and_server_request_id_collision(self):
        child=self.child('''import sys,json
for line in sys.stdin:
    x=json.loads(line)
    if x.get('method')=='initialized' or 'error' in x:continue
    i=x['id']
    print(json.dumps({'method':'notification','params':{}}),flush=True)
    print(json.dumps({'method':'command/exec','id':i,'params':{}}),flush=True)
    reply=json.loads(sys.stdin.readline())
    if reply.get('error',{}).get('code')!=-32601:sys.exit(2)
    print(json.dumps({'id':i,'result':{'accepted_read':x['method']}}),flush=True)
''')
        with CodexRPC(child,timeout=2) as rpc:
            result=rpc.call('account/usage/read',{})
        self.assertEqual(result['accepted_read'],'account/usage/read')

    def test_dead_child_does_not_hang(self):
        child=self.child('import sys\nsys.exit(1)\n')
        with self.assertRaisesRegex(SourceError,'rpc_disconnected'):
            with CodexRPC(child,timeout=2):pass

    def test_timeout_terminates_helper(self):
        child=self.child('import time\ntime.sleep(10)\n')
        rpc=CodexRPC(child,timeout=.1)
        with self.assertRaisesRegex(SourceError,'rpc_timeout'):
            with rpc:pass
        self.assertIsNotNone(rpc.process.poll())

    def test_rpc_error_body_is_not_published(self):
        child=self.child('''import json,sys
for line in sys.stdin:
 x=json.loads(line)
 if 'id' in x:print(json.dumps({'id':x['id'],'error':{'code':-32000,'message':'secret-value'}}),flush=True)
''')
        with self.assertRaises(SourceError) as ctx:
            with CodexRPC(child,timeout=2):pass
        self.assertNotIn('secret-value',str(ctx.exception))


class HTTPTransportTests(unittest.TestCase):
    def test_non_loopback_local_endpoint_rejected(self):
        with self.assertRaisesRegex(SourceError,'non_loopback_endpoint'):
            get_json('http://example.com/api',local=True)

    def test_remote_cleartext_and_embedded_credential_rejected(self):
        for url in ('http://example.com/api','https://user:secret@example.com/api'):
            with self.assertRaises(SourceError):get_json(url)

    def test_redirect_does_not_forward_bearer(self):
        reached=[]
        class Target(BaseHTTPRequestHandler):
            def do_GET(self):
                reached.append(True);self.send_response(200);self.end_headers();self.wfile.write(b'{}')
            def log_message(self,*args):pass
        target=ThreadingHTTPServer(('127.0.0.1',0),Target)
        class Redirect(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302);self.send_header('Location','http://127.0.0.1:'+str(target.server_address[1])+'/');self.end_headers()
            def log_message(self,*args):pass
        redirect=ThreadingHTTPServer(('127.0.0.1',0),Redirect)
        threads=[]
        for server in (target,redirect):
            t=threading.Thread(target=server.serve_forever,daemon=True);t.start();threads.append(t)
        try:
            with self.assertRaisesRegex(SourceError,'redirect_rejected'):
                get_json('http://127.0.0.1:'+str(redirect.server_address[1])+'/',token='sensitive-credential',local=True)
            self.assertEqual(reached,[])
        finally:
            for server in (target,redirect):server.shutdown();server.server_close()
            for t in threads:t.join()
