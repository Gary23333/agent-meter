"""Official HTTP MCP metadata probe; never calls tools/call or generates media."""
import json
import urllib.request
from urllib.parse import urlparse
from .transport import MAX_BODY

DEFAULT_MCP_URL = 'http://127.0.0.1:18810/mcp'

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('MCP redirect refused')

def probe_design_mcp(node=None, entry=None, origin=None, timeout=10):
    # Keep the old signature for saved configurations. node and gateway origin are
    # no longer transport inputs; legacy filesystem entry paths use official URL.
    url = entry if isinstance(entry, str) and entry.startswith(('http:', 'https:')) else DEFAULT_MCP_URL
    try:
        parsed = urlparse(url)
        if (parsed.scheme != 'http' or parsed.hostname not in {'localhost','127.0.0.1','::1'}
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError('Only local HTTP MCP is supported')
        headers = {'Content-Type':'application/json','Accept':'application/json, text/event-stream'}
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        def call(ident, method, params):
            if method not in {'initialize','notifications/initialized','tools/list'}:
                raise ValueError('Metadata methods only')
            obj={'jsonrpc':'2.0','method':method,'params':params}
            if ident is not None:obj['id']=ident
            request=urllib.request.Request(url,json.dumps(obj).encode(),headers)
            with opener.open(request,timeout=timeout) as response:
                sid=response.headers.get('mcp-session-id')
                if sid:headers['Mcp-Session-Id']=sid
                raw=response.read(MAX_BODY+1)
                if len(raw)>MAX_BODY:raise ValueError('Oversized response')
                if ident is None:return {}
                if 'text/event-stream' in response.headers.get('Content-Type',''):
                    messages=[]
                    for event in raw.decode().replace('\r\n','\n').split('\n\n'):
                        data='\n'.join(line[5:].lstrip() for line in event.splitlines() if line.startswith('data:'))
                        if data:messages.append(json.loads(data))
                    msg=next(m for m in messages if m.get('id')==ident)
                else:msg=json.loads(raw)
                if msg.get('id')!=ident or 'error' in msg:raise ValueError('Invalid MCP response')
                return msg.get('result',{})
        initialized=call(1,'initialize',{'protocolVersion':'2025-03-26','capabilities':{},
            'clientInfo':{'name':'agent-meter-readonly','version':'0.3'}})
        headers['MCP-Protocol-Version']=initialized['protocolVersion']
        call(None,'notifications/initialized',{})
        items=[];params={}
        for index in range(50):
            result=call(index+2,'tools/list',params)
            page=result.get('tools')
            if not isinstance(page,list):raise ValueError('Invalid catalog')
            items.extend(page)
            if not result.get('nextCursor'):break
            params={'cursor':result['nextCursor']}
        else:raise ValueError('Too many tool pages')
        names={x.get('name') for x in items if isinstance(x,dict)}
        financial=bool(names & {'get_credit_balance','get_wallet','get_subscription','get_renewal'})
        return {'connected':True,'transport':'streamable_http','tool_count':len(items),
            'financial_tool_names_detected':financial,'financial_collection':'local_gateway_fallback','tools_called':[]}
    except Exception:
        return {'connected':False,'reason':'design_mcp_probe_failed'}
