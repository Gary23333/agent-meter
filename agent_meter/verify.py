"""Independent record-based reconciliation and field coverage audit.

The reference computation deliberately does not use backend SQL expressions.
It reads only usage columns in one read transaction, never provider configs.
"""
from collections import defaultdict
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from .ccswitch import readonly_database, summarize, validate_schema, period_bounds
from .model import METRICS, timestamp


def reference_ccswitch(conn,start,end,zone):
    columns="app_type,model,input_tokens,output_tokens,cache_read_tokens,cache_creation_tokens,input_token_semantics,total_cost_usd,status_code,created_at,data_source"
    rows=[dict(r) for r in conn.execute("SELECT "+columns+" FROM proxy_request_logs")]
    proxy_index=defaultdict(list)
    for r in rows:
        if (r["data_source"] or "proxy")=="proxy" and 200<=r["status_code"]<300:
            proxy_index[(r["app_type"],r["input_tokens"],r["output_tokens"],r["cache_read_tokens"])].append(r)
    totals=dict(requests=0,successful_requests=0,fresh_input=0,output=0,cache_read=0,cache_write=0)
    cost=Decimal(0)

    def add(r,count,successes):
        nonlocal cost
        value=r["input_tokens"]
        if r["app_type"] in ("codex","gemini","grokbuild") and r["input_token_semantics"]!=2:
            deduction=r["cache_read_tokens"]+(r["cache_creation_tokens"] if r["input_token_semantics"]==1 else 0)
            if deduction<=value:value-=deduction
        totals["requests"]+=count
        totals["successful_requests"]+=successes
        totals["fresh_input"]+=value
        totals["output"]+=r["output_tokens"]
        totals["cache_read"]+=r["cache_read_tokens"]
        totals["cache_write"]+=r["cache_creation_tokens"]
        cost+=Decimal(r["total_cost_usd"])

    for r in rows:
        if (start is not None and r["created_at"]<start) or (end is not None and r["created_at"]>end):continue
        duplicate=False
        kind=r["data_source"] or "proxy"
        if kind in {"session_log","codex_session","gemini_session","opencode_session"}:
            apps=[r["app_type"]]+(["claude-desktop"] if r["app_type"]=="claude" else [])
            for app in apps:
                for p in proxy_index[(app,r["input_tokens"],r["output_tokens"],r["cache_read_tokens"])]:
                    cache_match=p["cache_creation_tokens"]==r["cache_creation_tokens"] or (
                        r["cache_creation_tokens"]==0 and kind in {"codex_session","gemini_session","opencode_session"})
                    model_match=p["model"].lower()==r["model"].lower() or "unknown" in {p["model"].lower(),r["model"].lower()}
                    if cache_match and model_match and abs(p["created_at"]-r["created_at"])<=600:
                        duplicate=True;break
                if duplicate:break
        if not duplicate:add(r,1,int(200<=r["status_code"]<300))
    for raw in conn.execute("SELECT app_type,date,input_tokens,output_tokens,cache_read_tokens,cache_creation_tokens,input_token_semantics,total_cost_usd,request_count,success_count FROM usage_daily_rollups"):
        r=dict(raw)
        day=datetime.strptime(r["date"],"%Y-%m-%d").date()
        midnight=int(datetime.combine(day,time(),zone).timestamp())
        # Upstream treats the entire final minute as fully covered.
        final_minute=int(datetime.combine(day,time(23,59),zone).timestamp())
        if (start is None or start<=midnight) and (end is None or end>=final_minute):
            add(r,r["request_count"],r["success_count"])
    totals["total_tokens"]=sum(totals[k] for k in ("fresh_input","output","cache_read","cache_write"))
    totals["estimated_cost_usd"]=str(cost)
    return totals


def verify_snapshot(snapshot,config,native_reference=None):
    checks=[]
    def check(name,ok,detail=None):
        checks.append({"name":name,"status":"pass" if ok else "fail","detail":detail})
    for src in snapshot["sources"]:
        for name in METRICS:
            m=src["metrics"][name]
            check(src["id"]+"."+name+".null_contract",not (m["status"]=="available" and m["value"] is None))
        if src["id"]=="codex" and src["metrics"]["quota"]["value"]:
            for i,q in enumerate(src["metrics"]["quota"]["value"]):
                check("codex.quota."+str(i)+".remaining",q["remaining_percent"]==max(0,100-q["used_percent"]))
            cards=src["metrics"]["reset_cards"]["value"]
            if cards:
                check("codex.cards.count_authoritative",isinstance(cards["available_count"],int))
                check("codex.cards.truncated_contract",cards["cards"] is None or len(cards["cards"])>=cards["available_count"] or cards["details_state"]=="truncated")
    if native_reference is not None:
        codex=next((s for s in snapshot['sources'] if s['id']=='codex' and s['status'] in {'available','partial'}),None)
        identity_matches=codex is not None and codex.get('account_key') is not None and codex.get('account_key')==native_reference.get('account_key')
        check('codex.native.same_account',identity_matches)
        if identity_matches:
            rows=codex['metrics']['quota']['value'] or []
            for bucket in native_reference.get('quota_buckets',[]):
                for window in ('primary','secondary'):
                    expected=bucket.get(window)
                    if expected is None:continue
                    actual=next((x for x in rows if x['bucket']==bucket['bucket'] and x['window']==window),{})
                    prefix='codex.native.'+bucket['bucket']+'.'+window
                    check(prefix+'.window_minutes',actual.get('window_minutes')==expected.get('windowDurationMins'))
                    check(prefix+'.reset_seconds',(actual.get('resets_at') or {}).get('epoch_seconds')==expected.get('resetsAt'))
                    # Consumption can move while these two clients query.
                    if actual.get('used_percent')==expected.get('usedPercent'):
                        check(prefix+'.used_percent',True)
                    elif isinstance(actual.get('used_percent'),(int,float)) and abs(actual['used_percent']-expected.get('usedPercent',0))<=1:
                        checks.append({'name':prefix+'.used_percent','status':'inconclusive_live_drift',
                                       'detail':{'backend':actual.get('used_percent'),'reference':expected.get('usedPercent')}})
                    else:
                        check(prefix+'.used_percent',False,{'backend':actual.get('used_percent'),'reference':expected.get('usedPercent')})
                expected_credit=bucket.get('credits')
                if expected_credit is not None:
                    actual=next((x for x in codex['metrics']['credits']['value'] or [] if x['bucket']==bucket['bucket']),{})
                    for field,origin in [('balance','balance'),('unlimited','unlimited'),('has_credits','hasCredits')]:
                        a,b=actual.get(field),expected_credit.get(origin)
                        equal=Decimal(a)==Decimal(b) if field=='balance' and a is not None and b is not None else a==b
                        check('codex.native.credits.'+field,equal)
            expected_cards=native_reference.get('cards')
            if expected_cards is not None:
                actual=codex['metrics']['reset_cards']['value'] or {}
                check('codex.native.cards.count',actual.get('available_count')==expected_cards['available_count'])
                if actual.get('cards') is not None:
                    expires=[(c['expires_at'] or {}).get('epoch_seconds') for c in actual['cards']]
                    sort_key=lambda x:-1 if x is None else x
                    check('codex.native.cards.expiry_seconds',sorted(expires,key=sort_key)==sorted(expected_cards['expires_at'],key=sort_key))
    cc=next((s for s in snapshot["sources"] if s["id"]=="ccswitch" and s["status"]=="available"),None)
    if cc:
        zone=ZoneInfo(config["ccswitch_timezone"])
        now=snapshot["collected_at"]["epoch_seconds"]
        with readonly_database(config["ccswitch_db"]) as conn:
            validate_schema(conn)
            for period in ("today","7d","30d","all"):
                bounds=period_bounds(now,period,zone)
                actual=summarize(conn,*bounds,zone=zone)["totals"]
                expected=reference_ccswitch(conn,*bounds,zone)
                for field,value in expected.items():
                    equal=Decimal(actual[field])==Decimal(value) if field=="estimated_cost_usd" else actual[field]==value
                    check("ccswitch."+period+"."+field,equal,{"backend":actual[field],"reference":value})
    measured=[]
    missing=[]
    for row in snapshot["coverage"]:
        for field,value in row["fields"].items():
            entry={"application":row["application"]["name"],"field":field,"status":value["status"],"source":value["source"]}
            (measured if value["status"] in {"available","partial"} else missing).append(entry)
    failed=sum(c["status"]=="fail" for c in checks)
    passed=sum(c["status"]=="pass" for c in checks)
    return {"verified_at":timestamp(__import__('time').time()),"snapshot_at":snapshot["collected_at"],
            "passed_checks":passed,"failed_checks":failed,"inconclusive_checks":len(checks)-passed-failed,"checks":checks,
            "collected_fields":measured,"uncollected_fields":missing,
            "all_requested_fields_collected":bool(snapshot.get('coverage')) and not missing,
            "scope":"CC Switch compares independent Python aggregation with backend SQL in one read transaction. Optional native reference cross-checks Codex account identity, quota, reset times, credits and cards. Remaining checks validate normalized contracts; uncollected fields are gaps, not passing integrations."}
