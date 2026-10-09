"""Independent record-based reconciliation and field coverage audit.

The reference computation deliberately does not use backend SQL expressions.
It reads only usage columns in one read transaction, never provider configs.
"""
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
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


def reference_zcode(conn,start,end):
    """Independent single-pass accumulation, separate from the collector."""
    counts=[0]*6
    for row in conn.execute("SELECT started_at/1000.0,input_tokens,output_tokens,reasoning_tokens,"
                            "cache_creation_input_tokens,cache_read_input_tokens FROM model_usage"):
        seconds=row[0]
        if (start is not None and seconds<start) or seconds>end:continue
        counts[0]+=1
        for i in range(1,6):counts[i]+=row[i]
    return {"requests":counts[0],"fresh_input":counts[1],"output":counts[2],"reasoning":counts[3],
            "cache_write":counts[4],"cache_read":counts[5],"total_tokens":sum(counts[1:])}


def reference_zcode_turns(conn):
    """turn_usage cross-check: near-exact subset of model_usage (upstream drift)."""
    try:
        turn=conn.execute("SELECT SUM(input_tokens+output_tokens+reasoning_tokens"
                          "+cache_creation_input_tokens+cache_read_input_tokens)"
                          " FROM turn_usage WHERE status='completed'").fetchone()[0]
        model=conn.execute("SELECT SUM(m.input_tokens+m.output_tokens+m.reasoning_tokens"
                           "+m.cache_creation_input_tokens+m.cache_read_input_tokens) FROM model_usage m"
                           " WHERE EXISTS(SELECT 1 FROM turn_usage t WHERE t.session_id=m.session_id"
                           " AND t.turn_id=m.turn_id AND t.status='completed')").fetchone()[0]
    except sqlite3.Error:
        return None,None
    return turn,model


def reference_workbuddy(root,now,zone):
    periods={p:{"requests":0,"fresh_input":0,"output":0,"cache_read":0,"cache_write":0}
             for p in ("all","today")}
    bounds={p:period_bounds(now,p,zone) for p in periods}
    for path in Path(root).glob("**/*.jsonl"):
        try:
            handle=open(path,encoding="utf-8")
        except OSError:
            continue
        with handle:
            for line in handle:
                if "rawUsage" not in line:continue
                try:o=json.loads(line)
                except ValueError:continue
                raw=(o.get("providerData") or {}).get("rawUsage") if isinstance(o,dict) else None
                ts=o.get("timestamp") if isinstance(o,dict) else None
                if not isinstance(raw,dict) or isinstance(ts,bool) or not isinstance(ts,(int,float)):continue
                prompt=raw.get("prompt_tokens") if isinstance(raw.get("prompt_tokens"),int) else 0
                hit,miss=raw.get("prompt_cache_hit_tokens"),raw.get("prompt_cache_miss_tokens")
                read,write=raw.get("cache_read_input_tokens"),raw.get("cache_creation_input_tokens")
                if isinstance(hit,int) and isinstance(miss,int):fresh,cache_read,cache_write=miss,hit,0
                elif read or write:
                    fresh,cache_read,cache_write=max(0,prompt-(read or 0)-(write or 0)),read or 0,write or 0
                else:fresh,cache_read,cache_write=prompt,0,0
                for p,(start,end) in bounds.items():
                    if (start is not None and ts/1000<start) or ts/1000>end:continue
                    row=periods[p]
                    row["requests"]+=1;row["fresh_input"]+=fresh
                    row["output"]+=raw.get("completion_tokens") if isinstance(raw.get("completion_tokens"),int) else 0
                    row["cache_read"]+=cache_read;row["cache_write"]+=cache_write
    for row in periods.values():
        row["total_tokens"]=row["fresh_input"]+row["output"]+row["cache_read"]+row["cache_write"]
    return periods


def reference_opencode(conn,start,end,excluded,zone):
    row={"requests":0,"fresh_input":0,"output":0,"reasoning":0,"cache_read":0,"cache_write":0}
    for created,role,inp,out,reasoning,read,write in conn.execute(
            "SELECT time_created,json_extract(data,'$.role'),json_extract(data,'$.tokens.input'),"
            "json_extract(data,'$.tokens.output'),json_extract(data,'$.tokens.reasoning'),"
            "json_extract(data,'$.tokens.cache.read'),json_extract(data,'$.tokens.cache.write') FROM message"):
        if role!="assistant" or inp is None:continue
        if datetime.fromtimestamp(created/1000,zone).date().isoformat() in excluded:continue
        seconds=created/1000
        if (start is not None and seconds<start) or seconds>end:continue
        row["requests"]+=1;row["fresh_input"]+=inp;row["output"]+=out or 0
        row["reasoning"]+=reasoning or 0;row["cache_read"]+=read or 0;row["cache_write"]+=write or 0
    row["total_tokens"]=sum(row[k] for k in ("fresh_input","output","reasoning","cache_read","cache_write"))
    return row


def reference_opencode_excluded(ccswitch_db,zone):
    try:
        conn=sqlite3.connect(Path(ccswitch_db).expanduser().resolve().as_uri()+"?mode=ro",uri=True,timeout=3)
        try:
            conn.execute("PRAGMA query_only=ON")
            return {datetime.fromtimestamp(r[0],zone).date().isoformat() for r in conn.execute(
                "SELECT created_at FROM proxy_request_logs WHERE app_type='opencode'")}
        finally:conn.close()
    except (sqlite3.Error,OSError):
        return None


def reference_cli_period(records,start,end,zone):
    """Independent single-loop recomputation over cli_sessions record tuples."""
    out={"requests":0,"fresh_input":0,"output":0,"reasoning":0,"cache_read":0,"cache_write":0}
    for t,_model,fresh,output,reasoning,read,write in records:
        if start is not None and t<start:continue
        if t>end:continue
        out["requests"]+=1
        out["fresh_input"]+=fresh;out["output"]+=output;out["reasoning"]+=reasoning
        out["cache_read"]+=read;out["cache_write"]+=write
    return out


def reference_ccswitch_day_sums(ccswitch_db,zone,apps,subtract_cache_read):
    """Per local-day sums from CC Switch rows for an app (folded, any source).

    Also returns the days that contain proxy-routed rows: on those days the
    upstream applies its own session/proxy dedup when summarizing, which a
    raw-file reference cannot reproduce, so cross-checks skip them.
    """
    try:
        conn=sqlite3.connect(Path(ccswitch_db).expanduser().resolve().as_uri()+"?mode=ro",uri=True,timeout=3)
        try:
            conn.execute("PRAGMA query_only=ON")
            marks=",".join("?"*len(apps))
            rows=conn.execute("SELECT created_at,COALESCE(data_source,'proxy'),input_tokens,output_tokens,"
                              "cache_read_tokens,cache_creation_tokens"
                              " FROM proxy_request_logs WHERE app_type IN ("+marks+")",tuple(apps)).fetchall()
            last=conn.execute("SELECT MAX(last_synced_at) FROM session_log_sync").fetchone()[0]
        finally:conn.close()
    except (sqlite3.Error,OSError):
        return None,None,None
    days=defaultdict(lambda:{"requests":0,"fresh_input":0,"output":0,"cache_read":0,"cache_write":0})
    proxy_days=set()
    for created,source,inp,out,read,write in rows:
        day=datetime.fromtimestamp(created,zone).date().isoformat()
        if source=="proxy":
            proxy_days.add(day)
        fresh=inp-read if subtract_cache_read and inp>=read else inp
        days[day]["requests"]+=1
        days[day]["fresh_input"]+=fresh
        days[day]["output"]+=out
        days[day]["cache_read"]+=read
        days[day]["cache_write"]+=write
    return dict(days),last,proxy_days


def check_cli_tokens(checks,snapshot,config,prefix,source_id,records,cc_apps,subtract_cache_read):
    """Exact period recompute plus CC Switch cross-check on its imported days."""
    from .ccswitch import period_bounds as bounds
    zone=ZoneInfo(config.get("ccswitch_timezone","Asia/Shanghai"))
    now=snapshot["collected_at"]["epoch_seconds"]
    src=next((s for s in snapshot["sources"] if s["id"]==source_id),None)
    if src is None or src["metrics"]["tokens"]["status"] not in {"available","partial"}:
        return
    value=src["metrics"]["tokens"]["value"]
    excluded=set(value["ccswitch_overlap"]["excluded_days"])
    # Exact recompute applies the same day exclusions as the collector; the
    # cross-check below needs the unfiltered records on the imported days.
    all_records=records
    records=[r for r in records if datetime.fromtimestamp(r[0],zone).date().isoformat() not in excluded]
    for period in ("today","7d","30d","all"):
        actual=value["periods"][period]["totals"]
        reference=reference_cli_period(records,*bounds(now,period,zone),zone)
        for field,v in reference.items():
            checks.append({"name":prefix+"."+period+"."+field,
                           "status":"pass" if actual[field]==v else "fail",
                           "detail":None if actual[field]==v else {"backend":actual[field],"reference":v}})
    # Machine-level alignment: on days CC Switch imported, the direct reader
    # (without exclusions) must reproduce its sums modulo sync lag.
    imported=value["ccswitch_overlap"]["excluded_days"]
    if value["ccswitch_overlap"]["state"]=="checked" and imported:
        day_sums,last_sync,proxy_days=reference_ccswitch_day_sums(config["ccswitch_db"],zone,cc_apps,subtract_cache_read)
        if day_sums and isinstance(last_sync,(int,float)) and now-last_sync<=48*3600:
            today=datetime.fromtimestamp(now,zone).date().isoformat()
            mine=defaultdict(lambda:{"requests":0,"fresh_input":0,"output":0,"cache_read":0,"cache_write":0})
            for t,_m,fresh,output,_r,read,write in all_records:
                day=datetime.fromtimestamp(t,zone).date().isoformat()
                if day not in imported:continue
                mine[day]["requests"]+=1;mine[day]["fresh_input"]+=fresh
                mine[day]["output"]+=output;mine[day]["cache_read"]+=read;mine[day]["cache_write"]+=write
            fields={"requests":0,"fresh_input":0,"output":0,"cache_read":0,"cache_write":0}
            days_seen=0
            for day in imported:
                if day>=today or day in proxy_days or day not in day_sums or day not in mine:continue
                days_seen+=1
                for field in fields:
                    fields[field]+=mine[day][field]-day_sums[day][field]
            if days_seen:
                # Tolerance: sync lag (CC Switch misses the tail of recent
                # files) and local log rotation. Requests 1% + 5, tokens 5%.
                ok=True;detail={}
                for f in fields:
                    base=sum(day_sums[d][f] for d in imported
                             if d in day_sums and d<today and d not in proxy_days)
                    detail[f]={"drift":fields[f],"ccswitch":base}
                    if abs(fields[f])>max(0.05*base,5 if f=="requests" else 0):ok=False
                checks.append({"name":prefix+".ccswitch_cross","status":"pass" if ok else "fail",
                               "detail":{"days":days_seen,**detail}})


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
    zone=ZoneInfo(config.get("ccswitch_timezone","Asia/Shanghai"))
    now=snapshot["collected_at"]["epoch_seconds"]
    zc=next((s for s in snapshot["sources"] if s["id"]=="zcode" and s["metrics"]["tokens"]["status"] in {"available","partial"}),None)
    if zc:
        from .zcode_local import readonly_database as zcode_database
        with zcode_database(config["zcode_usage_db"]) as conn:
            for period in ("today","7d","30d","all"):
                actual=zc["metrics"]["tokens"]["value"]["periods"][period]["totals"]
                expected=reference_zcode(conn,*period_bounds(now,period,zone))
                for field,value in expected.items():
                    check("zcode."+period+"."+field,actual[field]==value,{"backend":actual[field],"reference":value})
            turn,model=reference_zcode_turns(conn)
            if turn is not None and model is not None:
                drift=abs(turn-model)
                check("zcode.turn_usage.reconciliation",drift<=max(model*0.001,1),
                      {"turn_usage":turn,"model_usage_in_completed_turns":model,"drift":drift})
    wb=next((s for s in snapshot["sources"] if s["id"]=="workbuddy" and s["metrics"]["tokens"]["status"] in {"available","partial"}),None)
    if wb:
        expected=reference_workbuddy(config["workbuddy_projects_dir"],now,zone)
        for period,reference in expected.items():
            actual=wb["metrics"]["tokens"]["value"]["periods"][period]["totals"]
            for field,value in reference.items():
                check("workbuddy."+period+"."+field,actual[field]==value,{"backend":actual[field],"reference":value})
    oc=next((s for s in snapshot["sources"] if s["id"]=="opencode" and s["metrics"]["tokens"]["status"] in {"available","partial"}),None)
    if oc:
        from .opencode_tokens import readonly_database as opencode_database
        excluded=reference_opencode_excluded(config["ccswitch_db"],zone)
        if excluded is None:
            check("opencode.ccswitch_excluded_days.known",oc["metrics"]["tokens"]["value"]["ccswitch_overlap"]["state"]!="checked",
                  {"backend":oc["metrics"]["tokens"]["value"]["ccswitch_overlap"]["state"]})
        else:
            check("opencode.ccswitch_excluded_days",
                  oc["metrics"]["tokens"]["value"]["ccswitch_overlap"]["excluded_days"]==sorted(excluded),
                  {"backend":oc["metrics"]["tokens"]["value"]["ccswitch_overlap"]["excluded_days"],"reference":sorted(excluded)})
        with opencode_database(config["opencode_db"]) as conn:
            for period in ("today","all"):
                actual=oc["metrics"]["tokens"]["value"]["periods"][period]["totals"]
                reference=reference_opencode(conn,*period_bounds(now,period,zone),
                                             set(oc["metrics"]["tokens"]["value"]["ccswitch_overlap"]["excluded_days"]),zone)
                for field,value in reference.items():
                    check("opencode."+period+"."+field,actual[field]==value,{"backend":actual[field],"reference":value})
    # Direct CLI session readers: exact recompute plus CC Switch cross-check.
    from . import cli_sessions as CS
    for prefix,source_id,loader,kwargs,cc_apps,subtract in (
        ("codex_local","codex",CS.load_codex,
         (config.get("codex_sessions_dir"),config.get("codex_archives_dir")),("codex",),True),
        ("claude_local","claude",CS.load_claude,(config.get("claude_projects_dir"),),("claude","claude-desktop"),False),
        ("gemini_local","gemini",CS.load_gemini,(config.get("gemini_dir"),),("gemini",),True),
        ("mcode_local","minimax_code",CS.load_mcode,(config.get("mcode_db"),),("mcode",),False),
    ):
        src=next((s for s in snapshot["sources"] if s["id"]==source_id),None)
        if src is None or src["metrics"]["tokens"]["status"] not in {"available","partial"}:
            continue
        try:
            records=loader(*kwargs)
        except Exception:
            checks.append({"name":prefix+".reload","status":"fail","detail":"reference reload failed"})
            continue
        check_cli_tokens(checks,snapshot,config,prefix,source_id,records,cc_apps,subtract)
    # Antigravity CLI: independent recompute with its own protobuf walker.
    agy=next((s for s in snapshot["sources"] if s["id"]=="antigravity"),None)
    if agy is not None and agy["metrics"]["tokens"]["status"] in {"available","partial"}:
        from .agy_tokens import load_antigravity
        try:
            records,_skipped=load_antigravity(config["agy_conversations_dir"])
            check_cli_tokens(checks,snapshot,config,"antigravity_local","antigravity",
                             records,("antigravity",),False)
        except Exception:
            checks.append({"name":"antigravity_local.reload","status":"fail","detail":"reference reload failed"})
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
