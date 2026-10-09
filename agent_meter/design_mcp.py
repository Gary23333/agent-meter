"""MCP metadata only. This client has no tools/call or generation method."""
import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path

from .transport import MAX_BODY


def probe_design_mcp(node,entry,origin,timeout=10):
    if not node or not entry or not Path(entry).is_file():
        return {'connected':False,'reason':'design_mcp_not_installed'}
    process=None
    inbox=queue.Queue(maxsize=64)
    try:
        process=subprocess.Popen([node,entry],env=dict(os.environ,GATEWAY_URL=origin),
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,start_new_session=True)
        def read():
            while True:
                line=process.stdout.readline(MAX_BODY+1)
                if not line:
                    try:inbox.put(None,timeout=.1)
                    except queue.Full:pass
                    return
                if len(line)>MAX_BODY:continue
                try:inbox.put(json.loads(line),timeout=.1)
                except (ValueError,queue.Full):continue
        thread=threading.Thread(target=read,daemon=True);thread.start()
        deadline=time.monotonic()+timeout
        def send(obj):
            process.stdin.write((json.dumps(obj)+'\n').encode());process.stdin.flush()
        def call(i,method,params):
            if method not in {'initialize','tools/list'}:raise ValueError()
            send({'jsonrpc':'2.0','id':i,'method':method,'params':params})
            while time.monotonic()<deadline:
                obj=inbox.get(timeout=max(.01,deadline-time.monotonic()))
                if obj is None:raise ValueError()
                if isinstance(obj,dict) and obj.get('id')==i:
                    if 'error' in obj:raise ValueError()
                    return obj.get('result',{})
            raise ValueError()
        call(1,'initialize',{'protocolVersion':'2024-11-05','capabilities':{},
             'clientInfo':{'name':'agent-meter-readonly','version':'0.2'}})
        send({'jsonrpc':'2.0','method':'notifications/initialized'})
        result=call(2,'tools/list',{})
        items=result.get('tools')
        if not isinstance(items,list):raise ValueError()
        names={x.get('name') for x in items if isinstance(x,dict) and isinstance(x.get('name'),str)}
        # Discovery does not imply a future tool's schema or billing contract is safe.
        financial=bool(names & {'get_credit_balance','get_wallet','get_subscription','get_renewal'})
        return {'connected':True,'tool_count':len(items),'financial_tool_names_detected':financial,
                'financial_collection':'local_gateway_fallback','tools_called':[]}
    except Exception:
        return {'connected':False,'reason':'design_mcp_probe_failed'}
    finally:
        if process:
            if process.stdin:process.stdin.close()
            try:process.wait(timeout=.5)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:process.wait(timeout=1)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=1)
            if process.stdout:process.stdout.close()
