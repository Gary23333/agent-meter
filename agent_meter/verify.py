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
from .model import METRICS, SourceError, timestamp
from .reset_forecast import SOURCES as FORECAST_SOURCES


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
    """Totals plus the per-model split; thinking is a sub-part of output."""
    periods={p:{"requests":0,"fresh_input":0,"output":0,"cache_read":0,"cache_write":0,"thinking_tokens":0}
             for p in ("all","today")}
    models={p:{} for p in periods}
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
                provider=(o.get("providerData") or {}) if isinstance(o,dict) else {}
                raw=provider.get("rawUsage")
                ts=o.get("timestamp") if isinstance(o,dict) else None
                if not isinstance(raw,dict) or isinstance(ts,bool) or not isinstance(ts,(int,float)):continue
                prompt=raw.get("prompt_tokens") if isinstance(raw.get("prompt_tokens"),int) else 0
                hit,miss=raw.get("prompt_cache_hit_tokens"),raw.get("prompt_cache_miss_tokens")
                read,write=raw.get("cache_read_input_tokens"),raw.get("cache_creation_input_tokens")
                if isinstance(hit,int) and isinstance(miss,int):fresh,cache_read,cache_write=miss,hit,0
                elif read or write:
                    fresh,cache_read,cache_write=max(0,prompt-(read or 0)-(write or 0)),read or 0,write or 0
                else:fresh,cache_read,cache_write=prompt,0,0
                output=raw.get("completion_tokens") if isinstance(raw.get("completion_tokens"),int) else 0
                thinking=raw.get("completion_thinking_tokens") if isinstance(raw.get("completion_thinking_tokens"),int) else 0
                model="unknown"
                for key in ("model","requestModelName"):
                    if isinstance(provider.get(key),str) and 0<len(provider[key])<120:model=provider[key];break
                for p,(start,end) in bounds.items():
                    if (start is not None and ts/1000<start) or ts/1000>end:continue
                    row=periods[p]
                    row["requests"]+=1;row["fresh_input"]+=fresh;row["output"]+=output
                    row["cache_read"]+=cache_read;row["cache_write"]+=cache_write;row["thinking_tokens"]+=thinking
                    target=models[p].setdefault(model,{"requests":0,"fresh_input":0,"output":0,
                                                       "cache_read":0,"cache_write":0,"thinking_tokens":0})
                    target["requests"]+=1;target["fresh_input"]+=fresh;target["output"]+=output
                    target["cache_read"]+=cache_read;target["cache_write"]+=cache_write;target["thinking_tokens"]+=thinking
    for row in periods.values():
        row["total_tokens"]=row["fresh_input"]+row["output"]+row["cache_read"]+row["cache_write"]
    return periods,models


def reference_kimi_period(records,start,end):
    """Independent single-loop recompute over kimi_tokens record tuples."""
    totals={"requests":0,"fresh_input":0,"output":0,"cache_read":0,"cache_write":0}
    models={}
    for t,model,fresh,out,read,write in records:
        if (start is not None and t<start) or t>end:continue
        totals["requests"]+=1
        target=models.setdefault(model,dict.fromkeys(("requests","fresh_input","output","cache_read","cache_write"),0))
        target["requests"]+=1
        for name,value in (("fresh_input",fresh),("output",out),("cache_read",read),("cache_write",write)):
            totals[name]+=value
            target[name]+=value
    return totals,models


def reference_qoder_credits(root,now,zone):
    """Independent recomputation of the Qoder CN local credits ledger."""
    periods={p:{"requests":0,"credits":Decimal(0),"billable_requests":0,"billable_credits":Decimal(0)}
             for p in ("all","today")}
    bounds={p:period_bounds(now,p,zone) for p in periods}
    root=Path(root)
    if not root.is_dir():
        return None
    seen=set()
    for path in sorted(root.glob("**/*.jsonl")):
        try:
            handle=open(path,"rb")
        except OSError:
            continue
        with handle:
            for line in handle:
                if b'"usage"' not in line:
                    continue
                try:
                    o=json.loads(line,parse_float=Decimal)
                except ValueError:
                    continue
                if not isinstance(o,dict):
                    continue
                message=o.get("message")
                usage=message.get("usage") if isinstance(message,dict) else None
                if not isinstance(usage,dict):
                    continue
                credits=usage.get("credits")
                if isinstance(credits,bool) or not isinstance(credits,(int,Decimal)) or credits<0:
                    continue
                request_id=usage.get("request_id")
                if not isinstance(request_id,str) or not request_id or request_id in seen:
                    continue
                seen.add(request_id)
                ts=o.get("timestamp")
                if not isinstance(ts,str):
                    continue
                try:
                    when=datetime.fromisoformat(ts[:-1]+"+00:00" if ts.endswith("Z") else ts).timestamp()
                except ValueError:
                    continue
                for p,(start,end) in bounds.items():
                    if (start is not None and when<start) or when>end:
                        continue
                    row=periods[p]
                    row["requests"]+=1
                    row["credits"]+=Decimal(credits)
                    if usage.get("billable") is True:
                        row["billable_requests"]+=1
                        row["billable_credits"]+=Decimal(credits)
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


def reference_design_tokens(conn,start,end,excluded,zone):
    """Independent recompute over the @hilo message table, session-level exclusion."""
    row={"requests":0,"fresh_input":0,"output":0,"reasoning":0,"cache_read":0,"cache_write":0}
    sql=("SELECT time_created,json_extract(data,'$.role'),json_extract(data,'$.tokens.input'),"
         "json_extract(data,'$.tokens.output'),json_extract(data,'$.tokens.reasoning'),"
         "json_extract(data,'$.tokens.cache.read'),json_extract(data,'$.tokens.cache.write') FROM message")
    params=()
    if excluded:
        sql+=" WHERE session_id NOT IN ("+",".join("?"*len(excluded))+")"
        params=tuple(excluded)
    for created,role,inp,out,reasoning,read,write in conn.execute(sql,params):
        if role!="assistant" or inp is None:continue
        seconds=created/1000
        if (start is not None and seconds<start) or seconds>end:continue
        row["requests"]+=1;row["fresh_input"]+=inp;row["output"]+=out or 0
        row["reasoning"]+=reasoning or 0;row["cache_read"]+=read or 0;row["cache_write"]+=write or 0
    row["total_tokens"]=sum(row[k] for k in ("fresh_input","output","reasoning","cache_read","cache_write"))
    return row


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
        tokens=src["metrics"].get("tokens") or {}
        token_value=tokens.get("value") if isinstance(tokens.get("value"),dict) else None
        if token_value and token_value.get("peak_split")=="request_timestamp":
            # A split ledger must keep peak+off-peak exactly equal to the parent,
            # and every model group must carry the split (a partial split would
            # silently price part of a day at the wrong rate).
            for period,data in (token_value.get("periods") or {}).items():
                if not isinstance(data,dict):continue
                groups=data.get("groups") or []
                present=[all(isinstance(g.get(k),dict) for k in ("peak","offpeak")) for g in groups]
                check(src["id"]+".tokens."+period+".peak_split.groups_complete",all(present),
                      {"groups":len(groups),"split":sum(present)})
                for label,bucket in [("totals",data.get("totals") or {})]+ \
                        [("model."+str(g.get("model")),g) for g in groups if all(isinstance(g.get(k),dict) for k in ("peak","offpeak"))]:
                    for field,value in bucket.items():
                        if field in {"peak","offpeak","cache_hit_rate","app","model","timezone","start","end"}:
                            continue
                        if isinstance(value,bool) or not isinstance(value,(int,float)):continue
                        composed=sum(bucket[k].get(field,0) or 0 for k in ("peak","offpeak"))
                        check(src["id"]+".tokens."+period+".peak_split."+label+"."+field,composed==value,
                              {"peak":bucket["peak"].get(field), "offpeak":bucket["offpeak"].get(field),
                               "reference":value})
        if src["id"]=="codex" and src["metrics"]["quota"]["value"]:
            for i,q in enumerate(src["metrics"]["quota"]["value"]):
                check("codex.quota."+str(i)+".remaining",q["remaining_percent"]==max(0,100-q["used_percent"]))
            cards=src["metrics"]["reset_cards"]["value"]
            if cards:
                check("codex.cards.count_authoritative",isinstance(cards["available_count"],int))
                check("codex.cards.truncated_contract",cards["cards"] is None or len(cards["cards"])>=cards["available_count"] or cards["details_state"]=="truncated")
        if src["id"]=="reset_forecast":
            forecast=src["metrics"]["reset_forecast"]["value"]
            if forecast:
                ensemble=forecast["ensemble"]
                pooled=[row for row in forecast["sources"] if row.get("weight")]
                check("reset_forecast.pool_membership",sorted(ensemble.get("sources_used") or [])==sorted(row["source"] for row in pooled))
                for horizon in ("24h","48h"):
                    band=ensemble["horizons"].get(horizon)
                    if not band:continue
                    prefix="reset_forecast."+horizon
                    # A source's published answer is the pooled number; its internals are metadata.
                    entries=[]
                    for row in pooled:
                        published,model=row.get("headline_"+horizon),row.get("raw_"+horizon)
                        if published is not None:
                            entries.append((round(published,2),row["weight"],row["source"],"published_answer"))
                        elif model is not None:
                            entries.append((round(model,2),row["weight"],row["source"],"cadence_model_fallback"))
                    entries.sort()
                    total=sum(weight for _,weight,_,_ in entries) or 1.0
                    running,median=0.0,entries[-1][0]
                    for value,weight,_,_ in entries:
                        running+=weight/total
                        if running>=0.5:
                            median=value
                            break
                    check(prefix+".band",band["min"]==entries[0][0] and band["max"]==entries[-1][0])
                    check(prefix+".median_recomputed",band["weighted_median"]==round(median,2),
                          {"backend":band["weighted_median"],"reference":round(median,2)})
                    check(prefix+".spread",band["spread"]==round(entries[-1][0]-entries[0][0],2))
                    check(prefix+".agreement_rule",band["agreement"]==("close" if band["spread"]<=15 else "split"))
                    check(prefix+".values_are_published_answers_only",
                          sorted((item["source"],item["percent"],item["basis"]) for item in band["values"])==
                          sorted((source,value,basis) for value,_,source,basis in entries))
                events=forecast["history_events"]
                ids=[event["post_id"] for event in events]
                check("reset_forecast.history_dedup",len(ids)==len(set(ids)))
                check("reset_forecast.history_sources_known",all(set(event["sources"])<=set(FORECAST_SOURCES) for event in events))
                check("reset_forecast.no_tweet_bodies",not any("body" in event for event in events))
                check("reset_forecast.history_order",[event["announced_at"]["epoch_seconds"] for event in events]==
                      sorted((event["announced_at"]["epoch_seconds"] for event in events),reverse=True))
            countdown=src["metrics"]["known_reset_countdown"]["value"]
            if countdown:
                for index,target in enumerate(countdown["targets"]):
                    prefix="reset_forecast.countdown."+str(index)
                    seconds=(target["seconds_remaining_open"],target["seconds_remaining_close"])
                    if target["precision"]!="window":
                        check(prefix+".no_invented_seconds",all(item is None for item in seconds),{"seconds":seconds})
                        check(prefix+".state",target["state"]==("no_clock" if target["kind"]=="promised_reset" else "label_only"))
                        continue
                    close,open_seconds=target.get("close_at"),target.get("open_at")
                    expected=("elapsed_awaiting_landing" if seconds[1]<0 else
                              "inside_window" if seconds[0] is not None and seconds[0]<=0 else "upcoming")
                    check(prefix+".state",target["state"]==expected,{"backend":target["state"],"reference":expected})
                    if close and open_seconds and seconds[0] is not None:
                        check(prefix+".band_shape",close["epoch_seconds"]>open_seconds["epoch_seconds"])
                        check(prefix+".band_matches_seconds",
                              abs((close["epoch_seconds"]-open_seconds["epoch_seconds"])-(seconds[1]-seconds[0]))<0.2)
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
        expected,model_reference=reference_workbuddy(config["workbuddy_projects_dir"],now,zone)
        for period,reference in expected.items():
            value=wb["metrics"]["tokens"]["value"]["periods"][period]
            for field,ref in reference.items():
                check("workbuddy."+period+"."+field,value["totals"][field]==ref,
                      {"backend":value["totals"][field],"reference":ref})
            # The per-model split must reproduce the same numbers per model.
            backend={g["model"]:g for g in value["groups"]}
            check("workbuddy."+period+".models",set(backend)==set(model_reference[period]),
                  {"backend":sorted(backend),"reference":sorted(model_reference[period])})
            for model,ref in model_reference[period].items():
                group=backend.get(model) or {}
                for field,ref_value in ref.items():
                    check("workbuddy."+period+".model."+model+"."+field,group.get(field)==ref_value,
                          {"backend":group.get(field),"reference":ref_value})
    qd=None
    for s in snapshot["sources"]:
        if s["id"]!="qoder":
            continue
        value=s["metrics"]["credits"]["value"]
        if isinstance(value,dict) and isinstance(value.get("usage"),dict):
            qd=s
    if qd:
        expected=reference_qoder_credits(config["qoder_projects_dir"],now,zone)
        if expected is None:
            check("qoder.credits.ledger_root_present",False,{"root":config["qoder_projects_dir"]})
        else:
            for period,reference in expected.items():
                actual=qd["metrics"]["credits"]["value"]["usage"]["periods"][period]["totals"]
                for field,value in reference.items():
                    if isinstance(value,int):
                        check("qoder.credits."+period+"."+field,actual[field]==value,
                              {"backend":actual[field],"reference":value})
                    else:
                        check("qoder.credits."+period+"."+field,Decimal(str(actual[field]))==value,
                              {"backend":actual[field],"reference":format(value,"f")})
    km=next((s for s in snapshot["sources"] if s["id"]=="kimi" and s["metrics"]["tokens"]["status"] in {"available","partial"}),None)
    if km:
        from .kimi_tokens import load_records
        try:
            kimi_records,_=load_records(Path(config["home"])/".kimi-code/sessions")
        except Exception:
            kimi_records=None
            checks.append({"name":"kimi_local.reload","status":"fail","detail":"reference reload failed"})
        if kimi_records is not None:
            for period in ("today","7d","30d","all"):
                value=km["metrics"]["tokens"]["value"]["periods"][period]
                totals,models=reference_kimi_period(kimi_records,*period_bounds(now,period,zone))
                for field,ref in totals.items():
                    check("kimi."+period+"."+field,value["totals"][field]==ref,
                          {"backend":value["totals"][field],"reference":ref})
                backend={g["model"]:g for g in value["groups"]}
                check("kimi."+period+".models",set(backend)==set(models),
                      {"backend":sorted(backend),"reference":sorted(models)})
                for model,ref in models.items():
                    group=backend.get(model) or {}
                    for field,ref_value in ref.items():
                        check("kimi."+period+".model."+model+"."+field,group.get(field)==ref_value,
                              {"backend":group.get(field),"reference":ref_value})
    kd=next((s for s in snapshot["sources"] if s["id"]=="kimi_desktop" and s["metrics"]["tokens"]["status"] in {"available","partial"}),None)
    if kd and "kimi_desktop_sessions_dir" in config:
        from .kimi_tokens import load_records as load_kimi_records
        try:
            desktop_records,_=load_kimi_records(config["kimi_desktop_sessions_dir"])
        except Exception:
            desktop_records=None
            checks.append({"name":"kimi_desktop_local.reload","status":"fail","detail":"reference reload failed"})
        if desktop_records is not None:
            for period in ("today","7d","30d","all"):
                value=kd["metrics"]["tokens"]["value"]["periods"][period]
                totals,models=reference_kimi_period(desktop_records,*period_bounds(now,period,zone))
                for field,ref in totals.items():
                    check("kimi_desktop."+period+"."+field,value["totals"][field]==ref,
                          {"backend":value["totals"][field],"reference":ref})
                backend={g["model"]:g for g in value["groups"]}
                check("kimi_desktop."+period+".models",set(backend)==set(models),
                      {"backend":sorted(backend),"reference":sorted(models)})
                for model,ref in models.items():
                    group=backend.get(model) or {}
                    for field,ref_value in ref.items():
                        check("kimi_desktop."+period+".model."+model+"."+field,group.get(field)==ref_value,
                              {"backend":group.get(field),"reference":ref_value})
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
    # MiniMax Design agent tokens (attached to its account source): the
    # copied-session exclusion and the totals are recomputed independently.
    md=next((s for s in snapshot["sources"] if s["id"]=="minimax_design" and s["metrics"]["tokens"]["status"] in {"available","partial"}),None)
    if md and "design_opencode_db" in config:
        from .design_tokens import readonly_database as design_database, copied_session_ids
        try:
            excluded,_state=copied_session_ids(config["opencode_db"])
        except SourceError:
            excluded=None
        overlap=md["metrics"]["tokens"]["value"]["opencode_overlap"]
        if excluded is None:
            check("minimax_design_local.opencode_excluded_sessions.known",overlap["state"]!="checked",
                  {"backend":overlap["state"]})
        else:
            check("minimax_design_local.opencode_excluded_sessions",
                  overlap["state"]=="checked" and overlap["excluded_sessions"]==len(excluded),
                  {"backend":overlap["excluded_sessions"],"reference":len(excluded)})
            with design_database(config["design_opencode_db"]) as conn:
                for period in ("today","7d","30d","all"):
                    actual=md["metrics"]["tokens"]["value"]["periods"][period]["totals"]
                    reference=reference_design_tokens(conn,*period_bounds(now,period,zone),excluded,zone)
                    for field,value in reference.items():
                        check("minimax_design_local."+period+"."+field,actual[field]==value,
                              {"backend":actual[field],"reference":value})
    # Local price-table estimates: recompute every cost metric from its own
    # token groups with an independent match + arithmetic loop ("input" is the
    # group's fresh_input, the other three keep their names).
    from .prices import load_prices as load_price_table, normalize_model
    price_table=load_price_table(config.get("runtime_dir") or ".")
    for src in snapshot["sources"]:
        cost=src["metrics"]["cost"]
        value=cost["value"] if isinstance(cost["value"],dict) else None
        if cost["status"] not in {"available","partial"} or (value or {}).get("basis")!="local_price_table":
            continue
        tokens=src["metrics"]["tokens"]["value"]
        for period in ("today","7d","30d","all"):
            groups=(tokens["periods"].get(period) or {}).get("groups") or []
            peak_total=Decimal(0)
            offpeak_total=Decimal(0)
            peak_models={}
            offpeak_models={}
            unmatched=set()
            for g in groups:
                pattern=None
                model=str(g.get("model",""))
                key=normalize_model(model)
                if key:
                    if key in price_table.index:
                        pattern=price_table.index[key]
                    else:
                        best=None
                        for candidate in price_table.index:
                            if candidate in key and (best is None or len(candidate)>len(best)):
                                best=candidate
                        pattern=price_table.index.get(best) if best is not None else None
                split=isinstance(g.get("peak"),dict) and isinstance(g.get("offpeak"),dict)
                breakdown="fresh_input" in g or (split and any(
                    "fresh_input" in part for part in (g["peak"],g["offpeak"])))
                if pattern is None or not breakdown:
                    unmatched.add(str(g.get("model",""))+("" if breakdown else " (no breakdown)"))
                    continue
                prices=dict(zip(("input","cache_read","cache_write","output"),price_table.models[pattern]))
                def amount_for(row,multiplier):
                    cost=Decimal(0)
                    for price,field in (("input","fresh_input"),("cache_read","cache_read"),
                                        ("cache_write","cache_write"),("output","output")):
                        cost+=Decimal(str(row.get(field,0) or 0))*Decimal(str(prices[price]))*multiplier/Decimal(1000000)
                    return cost
                if split:
                    peak_part=amount_for(g["peak"],
                                         Decimal(str(price_table.peak_multipliers.get(pattern,1.0))).normalize())
                    offpeak_part=amount_for(g["offpeak"],Decimal(1))
                    peak_total+=peak_part
                    offpeak_total+=offpeak_part
                    if peak_part:
                        peak_models[model]=peak_models.get(model,Decimal(0))+peak_part
                    if offpeak_part:
                        offpeak_models[model]=offpeak_models.get(model,Decimal(0))+offpeak_part
                else:
                    offpeak_part=amount_for(g,Decimal(1))
                    offpeak_total+=offpeak_part
                    if offpeak_part:
                        offpeak_models[model]=offpeak_models.get(model,Decimal(0))+offpeak_part
            total=peak_total+offpeak_total
            backend=value["periods"].get(period) or {}
            check("prices."+src["id"]+"."+period+".amount",Decimal(backend.get("amount") or 0)==total,
                  {"backend":backend.get("amount"),"reference":format(total,"f")})
            check("prices."+src["id"]+"."+period+".peak_amount",
                  Decimal(backend.get("peak_amount") or 0)==peak_total,
                  {"backend":backend.get("peak_amount"),"reference":format(peak_total,"f")})
            check("prices."+src["id"]+"."+period+".offpeak_amount",
                  Decimal(backend.get("offpeak_amount") or 0)==offpeak_total,
                  {"backend":backend.get("offpeak_amount"),"reference":format(offpeak_total,"f")})
            backend_peak_models={name:Decimal(value or 0)
                                 for name,value in (backend.get("peak_models") or {}).items()}
            check("prices."+src["id"]+"."+period+".peak_models",backend_peak_models==peak_models,
                  {"backend":backend.get("peak_models") or {},
                   "reference":{name:format(value,"f") for name,value in peak_models.items()}})
            backend_offpeak_models={name:Decimal(value or 0)
                                    for name,value in (backend.get("offpeak_models") or {}).items()}
            check("prices."+src["id"]+"."+period+".offpeak_models",backend_offpeak_models==offpeak_models,
                  {"backend":backend.get("offpeak_models") or {},
                   "reference":{name:format(value,"f") for name,value in offpeak_models.items()}})
            check("prices."+src["id"]+"."+period+".unmatched",set(backend.get("unmatched_models") or [])==unmatched,
                  {"backend":backend.get("unmatched_models"),"reference":sorted(unmatched)})
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
    # DeepSeek Harness (dsh): independent recompute over the zstd session files.
    dsh=next((s for s in snapshot["sources"] if s["id"]=="deepseek_harness"),None)
    if dsh is not None and dsh["metrics"]["tokens"]["status"] in {"available","partial"}:
        from .dsh_tokens import load_dsh_sessions
        try:
            records,*_=load_dsh_sessions(config.get("dsh_sessions_dir"),config.get("zstd_binary"))
            check_cli_tokens(checks,snapshot,config,"dsh_local","deepseek_harness",records,("dsh",),False)
        except Exception:
            checks.append({"name":"dsh_local.reload","status":"fail","detail":"reference reload failed"})
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
