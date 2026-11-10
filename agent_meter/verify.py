"""Independent record-based reconciliation and field coverage audit.

The reference computation deliberately does not use backend SQL expressions.
It reads only usage columns in one read transaction, never provider configs.
"""
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

from .model import DISPLAY_ZONE, METRICS, SourceError, period_bounds, timestamp
from .reset_forecast import SOURCES as FORECAST_SOURCES


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


def reference_opencode(conn,start,end,zone):
    row={"requests":0,"fresh_input":0,"output":0,"reasoning":0,"cache_read":0,"cache_write":0}
    for created,role,inp,out,reasoning,read,write,total in conn.execute(
            "SELECT time_created,json_extract(data,'$.role'),json_extract(data,'$.tokens.input'),"
            "json_extract(data,'$.tokens.output'),json_extract(data,'$.tokens.reasoning'),"
            "json_extract(data,'$.tokens.cache.read'),json_extract(data,'$.tokens.cache.write'),json_extract(data,'$.tokens.total') FROM message WHERE json_valid(data)"):
        if role!="assistant" or any(type(v) is not int or v<0 for v in (inp,out,reasoning,read,write)):continue
        if reasoning<=out and total==inp+out+read+write:out-=reasoning
        seconds=created/1000
        if (start is not None and seconds<start) or seconds>end:continue
        row["requests"]+=1;row["fresh_input"]+=inp;row["output"]+=out or 0
        row["reasoning"]+=reasoning or 0;row["cache_read"]+=read or 0;row["cache_write"]+=write or 0
    row["total_tokens"]=sum(row[k] for k in ("fresh_input","output","reasoning","cache_read","cache_write"))
    return row


def reference_design_tokens(conn,start,end,excluded,zone):
    """Independent recompute over the @hilo message table, session-level exclusion."""
    row={"requests":0,"fresh_input":0,"output":0,"reasoning":0,"cache_read":0,"cache_write":0}
    sql=("SELECT time_created,json_extract(data,'$.role'),json_extract(data,'$.tokens.input'),"
         "json_extract(data,'$.tokens.output'),json_extract(data,'$.tokens.reasoning'),"
         "json_extract(data,'$.tokens.cache.read'),json_extract(data,'$.tokens.cache.write'),json_extract(data,'$.tokens.total') FROM message")
    params=()
    if excluded:
        sql+=" WHERE session_id NOT IN ("+",".join("?"*len(excluded))+")"
        params=tuple(excluded)
    for created,role,inp,out,reasoning,read,write,total in conn.execute(sql,params):
        if role!="assistant" or any(type(v) is not int or v<0 for v in (inp,out,reasoning,read,write)):continue
        if reasoning<=out and total==inp+out+read+write:out-=reasoning
        seconds=created/1000
        if (start is not None and seconds<start) or seconds>end:continue
        row["requests"]+=1;row["fresh_input"]+=inp;row["output"]+=out or 0
        row["reasoning"]+=reasoning or 0;row["cache_read"]+=read or 0;row["cache_write"]+=write or 0
    row["total_tokens"]=sum(row[k] for k in ("fresh_input","output","reasoning","cache_read","cache_write"))
    return row


def reference_cli_period(records,start,end,zone):
    """Independent single-loop recomputation over cli_sessions record tuples."""
    out={"requests":0,"fresh_input":0,"output":0,"reasoning":0,"cache_read":0,"cache_write":0}
    for t,_model,fresh,output,reasoning,read,write,*unknown in records:
        if start is not None and t<start:continue
        if t>end:continue
        out["requests"]+=1
        if unknown:out["unclassified"]=out.get("unclassified",0)+unknown[0]
        out["fresh_input"]+=fresh;out["output"]+=output;out["reasoning"]+=reasoning
        out["cache_read"]+=read;out["cache_write"]+=write
    return out


def reference_imported_history(store,start,end,zone):
    """Independent recompute over the project-owned imported-history store."""
    out={"requests":0,"fresh_input":0,"output":0,"reasoning":0,"cache_read":0,"cache_write":0}
    for _app,_model,t,fresh,output,read,write in store.get("detail") or []:
        if (start is not None and t<start) or t>end:continue
        out["requests"]+=1
        out["fresh_input"]+=fresh;out["output"]+=output;out["cache_read"]+=read;out["cache_write"]+=write
    for _app,_model,date,requests,fresh,output,read,write in store.get("daily") or []:
        when=int(datetime.combine(datetime.fromisoformat(date).date(),time(),zone).timestamp())
        if (start is not None and when<start) or when>end:continue
        out["requests"]+=requests
        out["fresh_input"]+=fresh;out["output"]+=output;out["cache_read"]+=read;out["cache_write"]+=write
    out["total_tokens"]=sum(out[k] for k in ("fresh_input","output","reasoning","cache_read","cache_write"))
    return out


def reference_codex_reported(config, end):
    """Cross-check raw reported totals, independent of component parsing/model attribution."""
    from .cli_sessions import _codex_log, _codex_logs, _rollout_priority
    from .zstd_io import is_compressed, route
    copies = defaultdict(list)
    for key in ("codex_sessions_dir", "codex_archives_dir"):
        for path in _codex_logs(Path(config[key])):
            copies[path.stem if is_compressed(path) else path.name].append(path)
    observed = 0
    for paths in copies.values():
        previous = None
        path = max(paths, key=_rollout_priority)
        binary = config.get("zstd_binary")
        with _codex_log(path, route(binary) if is_compressed(path) else None, binary) as lines:
            for line in lines:
                if b'"token_count"' not in line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                payload = event.get("payload") if isinstance(event, dict) else None
                if not isinstance(payload, dict) or payload.get("type") != "token_count":
                    continue
                info = payload.get("info") or {}
                counters = info.get("total_token_usage")
                if not isinstance(counters, dict):
                    continue
                current = counters.get("total_tokens")
                if not isinstance(current, int):
                    return None  # this schema has no independent reported total
                if previous == current:
                    continue
                first = (info.get("last_token_usage") or {}).get("total_tokens", current)
                delta = first if previous is None else current if current < previous else current - previous
                previous = current
                if timestamp(event["timestamp"])["epoch_seconds"] <= end:
                    observed += delta
    return observed


def check_cli_tokens(checks,snapshot,config,prefix,source_id,records):
    """Exact period recompute for one direct local reader."""
    zone=DISPLAY_ZONE
    now=snapshot["collected_at"]["epoch_seconds"]
    src=next((s for s in snapshot["sources"] if s["id"]==source_id),None)
    if src is None or src["metrics"]["tokens"]["status"] not in {"available","partial"}:
        return
    value=src["metrics"]["tokens"]["value"]
    for period in ("today","7d","30d","all"):
        actual=value["periods"][period]["totals"]
        reference=reference_cli_period(records,*period_bounds(now,period,zone),zone)
        for field,v in reference.items():
            checks.append({"name":prefix+"."+period+"."+field,
                           "status":"pass" if actual[field]==v else "fail",
                           "detail":None if actual[field]==v else {"backend":actual[field],"reference":v}})


def check_antigravity_tokens(checks,snapshot,config,records):
    """Antigravity sqlite is a lower bound while the desktop app is writing.

    The WAL-aware read transaction and the later verification transaction may
    see different commits made by the running app. Equal
    totals pass, a small positive gap is inconclusive, anything else fails.
    """
    zone=DISPLAY_ZONE
    now=snapshot["collected_at"]["epoch_seconds"]
    src=next((s for s in snapshot["sources"] if s["id"]=="antigravity"),None)
    if src is None or src["metrics"]["tokens"]["status"] not in {"available","partial"}:
        return
    value=src["metrics"]["tokens"]["value"]
    for period in ("today","7d","30d","all"):
        actual=value["periods"][period]["totals"]
        reference=reference_cli_period(records,*period_bounds(now,period,zone),zone)
        for field,v in reference.items():
            b=actual[field]
            if b==v:
                status,detail="pass",None
            elif v>b and v-b<=max(v*0.15,5 if field=="requests" else 1):
                status="inconclusive_live_drift"
                detail={"backend":b,"reference":v,"note":"sqlite WAL may hide recent steps until checkpoint"}
            else:
                status,detail="fail",{"backend":b,"reference":v}
            checks.append({"name":"antigravity_local."+period+"."+field,"status":status,"detail":detail})


def check_codex_images(checks,snapshot,config,source):
    """Codex 内置生图的独立重算：重扫 PNG、重算每周期张数/成本，再重查历史库调用数。"""
    entry=source["metrics"].get("image_generation") or {}
    value=entry.get("value") if isinstance(entry.get("value"),dict) else None
    if entry.get("status") not in {"available","partial"} or not value:
        return
    images_dir=config.get("codex_images_dir")
    if not images_dir:
        return
    from .codex_images import estimate_cost_usd,history_call_counts,resolve_history_db,scan_image_files
    from .prices import FX_FALLBACK
    def check(name,ok,detail=None):
        checks.append({"name":name,"status":"pass" if ok else "fail","detail":detail})
    zone=ZoneInfo(value.get("timezone") or "Asia/Shanghai")
    now=snapshot["collected_at"]["epoch_seconds"]
    quality=value.get("quality_assumption","high")
    try:
        records=scan_image_files(images_dir,use_cache=False)
    except Exception:
        check("codex.image_generation.files",False,"reference scan failed")
        return
    for period in ("today","7d","30d","all"):
        start,end=period_bounds(now,period,zone)
        images=0
        usd=Decimal(0)
        for epoch,width,height in records:
            if (start is not None and epoch<start) or epoch>end:
                continue
            images+=1
            if width is not None and height is not None:
                usd+=estimate_cost_usd(width,height,quality)
        if value.get("currency")=="CNY":
            usd=usd*FX_FALLBACK
        expected=usd.quantize(Decimal("0.000001"),ROUND_HALF_UP)
        backend=value["periods"].get(period) or {}
        check("codex.image_generation."+period+".images",backend.get("images")==images,
              {"backend":backend.get("images"),"reference":images})
        actual=backend.get("estimated_cost")
        try:
            actual=Decimal(str(actual)) if actual is not None else None
        except (ValueError,InvalidOperation):
            actual=None
        check("codex.image_generation."+period+".estimated_cost",actual==expected,
              {"backend":backend.get("estimated_cost"),"reference":format(expected,"f")})
    if not value.get("call_counts_available"):
        return
    counts=history_call_counts(resolve_history_db(config.get("codex_history_db")),now,zone)
    if counts is None:
        check("codex.image_generation.history.reload",False,"reference history reload failed")
        return
    for period in ("today","7d","30d","all"):
        backend=value["periods"].get(period) or {}
        for field in ("calls","failed_calls","generating_calls"):
            check("codex.image_generation."+period+"."+field,backend.get(field)==counts[period][field],
                  {"backend":backend.get(field),"reference":counts[period][field]})


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
        if token_value and token_value.get("daily_buckets") is not None and "all" in token_value.get("periods", {}):
            for period,window in token_value["periods"].items():
                if "groups" in window:
                    for field in ("total_tokens","requests"):
                        check(src["id"]+"."+period+".model_groups."+field,
                              sum(g.get(field,0) for g in window["groups"])==window["totals"].get(field))
            all_tokens=token_value["periods"]["all"]["totals"].get("total_tokens")
            check(src["id"]+".daily.all",sum(day["tokens"] for day in token_value["daily_buckets"])==all_tokens)
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
    zone=DISPLAY_ZONE
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
    kl=next((s for s in snapshot["sources"] if s["id"]=="kimi_legacy" and s["metrics"]["tokens"]["status"] in {"available","partial"}),None)
    if kl and "kimi_legacy_sessions_dir" in config:
        from .kimi_legacy_tokens import load_records as load_legacy_records
        try:
            legacy_records,_=load_legacy_records(config["kimi_legacy_sessions_dir"])
        except Exception:
            legacy_records=None
            checks.append({"name":"kimi_legacy_local.reload","status":"fail","detail":"reference reload failed"})
        if legacy_records is not None:
            for period in ("today","7d","30d","all"):
                value=kl["metrics"]["tokens"]["value"]["periods"][period]
                totals,models=reference_kimi_period(legacy_records,*period_bounds(now,period,zone))
                for field,ref in totals.items():
                    check("kimi_legacy."+period+"."+field,value["totals"][field]==ref,
                          {"backend":value["totals"][field],"reference":ref})
                backend={g["model"]:g for g in value["groups"]}
                check("kimi_legacy."+period+".models",set(backend)==set(models),
                      {"backend":sorted(backend),"reference":sorted(models)})
                for model,ref in models.items():
                    group=backend.get(model) or {}
                    for field,ref_value in ref.items():
                        check("kimi_legacy."+period+".model."+model+"."+field,group.get(field)==ref_value,
                              {"backend":group.get(field),"reference":ref_value})
    # Calendar-report invariant: per-day model rows must sum to the same
    # numbers as the day buckets (both come from one pass over the records).
    for src in snapshot["sources"]:
        tokens=src.get("metrics",{}).get("tokens") or {}
        value=tokens.get("value") if isinstance(tokens.get("value"),dict) else None
        if tokens.get("status") not in {"available","partial"} or not value:
            continue
        buckets=value.get("daily_buckets"); dm=value.get("daily_models")
        if not isinstance(buckets,list) or not isinstance(dm,list):
            continue
        ref={}
        for row in dm:
            ref[row["date"]]=ref.get(row["date"],0)+row.get("total_tokens",0)
        backend={b["date"]:b["tokens"] for b in buckets}
        check(src["id"]+".daily_models.match_buckets",ref==backend,
              None if ref==backend else {"daily_models":ref,"daily_buckets":backend})
    oc=next((s for s in snapshot["sources"] if s["id"]=="opencode" and s["metrics"]["tokens"]["status"] in {"available","partial"}),None)
    if oc:
        from .opencode_tokens import readonly_database as opencode_database
        with opencode_database(config["opencode_db"]) as conn:
            for period in ("today","all"):
                actual=oc["metrics"]["tokens"]["value"]["periods"][period]["totals"]
                reference=reference_opencode(conn,*period_bounds(now,period,zone),zone)
                for field,value in reference.items():
                    check("opencode."+period+"."+field,actual[field]==value,{"backend":actual[field],"reference":value})
    # MiMo Code / DevECo: independent opencode-isomorphic ledgers, recomputed
    # with the same SQL reference but never merged with the opencode source.
    for sid,config_key,missing_code,read_code in (
            ("mimo_code","mimocode_db","mimocode_db_not_found","mimocode_db_read_failed"),
            ("deveco","deveco_db","deveco_db_not_found","deveco_db_read_failed")):
        mc=next((s for s in snapshot["sources"] if s["id"]==sid and s["metrics"]["tokens"]["status"] in {"available","partial"}),None)
        if mc and config_key in config:
            from .opencode_tokens import readonly_database as family_database
            try:
                with family_database(config[config_key],missing_code=missing_code,read_code=read_code) as conn:
                    for period in ("today","7d","30d","all"):
                        actual=mc["metrics"]["tokens"]["value"]["periods"][period]["totals"]
                        reference=reference_opencode(conn,*period_bounds(now,period,zone),zone)
                        for field,value in reference.items():
                            check(sid+"."+period+"."+field,actual[field]==value,{"backend":actual[field],"reference":value})
            except SourceError as e:
                check(sid+".reference_readable",False,{"reason":e.code})
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
                  overlap["state"]==_state and overlap["excluded_sessions"]==len(excluded),
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
                def lookup(target):
                    if target in price_table.index:
                        return price_table.index[target]
                    best=None
                    for candidate in price_table.index:
                        if candidate in target and (best is None or len(candidate)>len(best)):
                            best=candidate
                    return price_table.index[best] if best is not None else None
                if key:
                    # Same user binding rule as PriceTable.match: an alias wins
                    # over the raw spelling, then exact/longest substring.
                    bound=price_table.aliases.get(key)
                    target=normalize_model(bound) if bound else None
                    pattern=lookup(target) if target and target!=key else lookup(key)
                split=isinstance(g.get("peak"),dict) and isinstance(g.get("offpeak"),dict)
                breakdown="fresh_input" in g or (split and any(
                    "fresh_input" in part for part in (g["peak"],g["offpeak"])))
                if g.get("unclassified"):
                    unmatched.add(model+" (no breakdown)")
                    if g["unclassified"]==g["total_tokens"]:continue
                if pattern is None or not breakdown:
                    unmatched.add(str(g.get("model",""))+("" if breakdown else " (no breakdown)"))
                    continue
                prices=dict(zip(("input","cache_read","cache_write","output"),price_table.models[pattern]))
                def amount_for(row,multiplier):
                    cost=Decimal(0)
                    for price,field in (("input","fresh_input"),("cache_read","cache_read"),
                                        ("cache_write","cache_write"),("output","output")):
                        units=(row.get(field,0) or 0) + ((row.get("reasoning") or 0) if field=="output" else 0)
                        cost+=Decimal(str(units))*Decimal(str(prices[price]))*multiplier/Decimal(1000000)
                    return cost
                if split:
                    peak_part=amount_for(g["peak"],
                                         Decimal(str(price_table.peak_multipliers.get(pattern,1.0))).normalize())
                    offpeak_part=amount_for(g["offpeak"],Decimal(1))+amount_for(g.get("unsplit",{}),Decimal(1))
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
    # Direct CLI session readers: exact recompute per local ledger.
    from . import cli_sessions as CS
    for prefix,source_id,loader,kwargs in (
        ("codex_local","codex",CS.load_codex,
         (config.get("codex_sessions_dir"),config.get("codex_archives_dir"))),
        ("claude_local","claude",CS.load_claude,(config.get("claude_projects_dir"),config.get("claude_desktop_sessions_dir"))),
        ("gemini_local","gemini",CS.load_gemini,(config.get("gemini_dir"),)),
        ("mcode_local","minimax_code",CS.load_mcode,(config.get("mcode_db"),)),
    ):
        src=next((s for s in snapshot["sources"] if s["id"]==source_id),None)
        if src is None or src["metrics"]["tokens"]["status"] not in {"available","partial"}:
            continue
        try:
            records=loader(*kwargs,zstd_binary=config.get("zstd_binary")) if source_id=="codex" else loader(*kwargs)
        except Exception:
            checks.append({"name":prefix+".reload","status":"fail","detail":"reference reload failed"})
            continue
        check_cli_tokens(checks,snapshot,config,prefix,source_id,records)
    codex=next((s["metrics"]["tokens"] for s in snapshot["sources"] if s["id"]=="codex"),{})
    if codex.get("status")=="available" and (codex.get("value") or {}).get("coverage")=="codex_cli_local_rollouts":
        try:
            declared=reference_codex_reported(config,now)
        except (OSError,ValueError,SourceError,EOFError):
            declared=None
        if declared is None:
            checks.append({"name":"codex_local.raw_reported_total","status":"inconclusive",
                           "detail":"raw reported total unavailable"})
        else:
            actual=codex["value"]["periods"]["all"]["totals"]["total_tokens"]
            check("codex_local.raw_reported_total",actual==declared,{"backend":actual,"raw_reported":declared})
    # Antigravity: independent recompute over the CLI and desktop ledgers.
    agy=next((s for s in snapshot["sources"] if s["id"]=="antigravity"),None)
    if agy is not None and agy["metrics"]["tokens"]["status"] in {"available","partial"}:
        from .agy_tokens import load_antigravity_roots
        try:
            records,_skipped,_diagnostics=load_antigravity_roots([
                config["agy_conversations_dir"],config.get("agy_desktop_conversations_dir")])
            check_antigravity_tokens(checks,snapshot,config,records)
        except Exception:
            checks.append({"name":"antigravity_local.reload","status":"fail","detail":"reference reload failed"})
    # Its 5-hour/weekly buckets are a live local RPC read; compare structure
    # and remaining percentages with a fresh call (small drift is possible if
    # the user is generating while verify runs).
    if agy is not None and agy["metrics"]["quota"]["status"] in {"available","partial"}:
        from .agy_quota import collect_antigravity_quota
        try:
            fresh=collect_antigravity_quota(snapshot["collected_at"]["epoch_seconds"])
        except Exception:
            checks.append({"name":"antigravity_quota.reload","status":"fail","detail":"reference reload failed"})
        else:
            backend={row["bucket"]:row for row in agy["metrics"]["quota"]["value"]}
            reference={row["bucket"]:row for row in fresh}
            checks.append({"name":"antigravity_quota.buckets","status":"pass" if set(backend)==set(reference) else "fail",
                           "detail":{"backend":sorted(backend),"reference":sorted(reference)}})
            for bucket in sorted(set(backend)&set(reference)):
                b,r=backend[bucket],reference[bucket]
                drift=abs((b.get("remaining_percent") or 0)-(r.get("remaining_percent") or 0))
                fixed=(b.get("window_minutes")==r.get("window_minutes") and
                       (b.get("resets_at") or {}).get("epoch_seconds")==(r.get("resets_at") or {}).get("epoch_seconds"))
                checks.append({"name":"antigravity_quota."+bucket+".remaining",
                               "status":"pass" if fixed and drift<=1.0 else "fail",
                               "detail":{"backend":b.get("remaining_percent"),"reference":r.get("remaining_percent"),
                                         "window_minutes":b.get("window_minutes"),"drift":drift}})
    # DeepSeek Harness (dsh): independent recompute over the zstd session files.
    dsh=next((s for s in snapshot["sources"] if s["id"]=="deepseek_harness"),None)
    if dsh is not None and dsh["metrics"]["tokens"]["status"] in {"available","partial"}:
        from .dsh_tokens import load_dsh_sessions
        try:
            records,*_=load_dsh_sessions(config.get("dsh_sessions_dir"),config.get("zstd_binary"))
            check_cli_tokens(checks,snapshot,config,"dsh_local","deepseek_harness",records)
        except Exception:
            checks.append({"name":"dsh_local.reload","status":"fail","detail":"reference reload failed"})
    # Project-owned imported history: independent recompute from the store.
    ih=next((s for s in snapshot["sources"] if s["id"]=="imported_history"),None)
    if ih is not None and ih["metrics"]["tokens"]["status"] in {"available","partial"}:
        try:
            store_path=config.get("history_store") or str(Path(config["runtime_dir"])/"imported-history.json")
            store=json.loads(Path(store_path).read_text())
            for period in ("today","7d","30d","all"):
                actual=ih["metrics"]["tokens"]["value"]["periods"][period]["totals"]
                reference=reference_imported_history(store,*period_bounds(now,period,zone),zone)
                for field,value in reference.items():
                    check("imported_history."+period+"."+field,actual[field]==value,
                          {"backend":actual[field],"reference":value})
            history=ih["metrics"]["tokens"]["value"]["history"]
            check("imported_history.records",
                  history["detail_records"]==len(store.get("detail") or []) and
                  history["daily_records"]==len(store.get("daily") or []),
                  {"backend":{"detail":history["detail_records"],"daily":history["daily_records"]}})
        except Exception:
            checks.append({"name":"imported_history.reload","status":"fail","detail":"reference reload failed"})
    # Codex 内置生图：按文件重扫 + 历史库调用数重查（Codex-only 指标）。
    codex_src=next((s for s in snapshot["sources"] if s["id"]=="codex"),None)
    if codex_src is not None:
        check_codex_images(checks,snapshot,config,codex_src)
    if "application_usage" in snapshot:
        usage=snapshot["application_usage"]
        for period in ("today","7d","30d","all"):
            rows=[windows[period] for windows in usage.values() if period in windows]
            for key,field in (("total_tokens","tokens"), ("requests","requests")):
                attributed=sum(row[key] for row in rows)
                ledgers=sum(((((src["metrics"]["tokens"].get("value") or {}).get("periods") or {})
                             .get(period, {}).get("totals") or {}).get(key,0)) for src in snapshot["sources"]
                            if not src["id"].startswith("codexbar:") and "#" not in src["id"])
                check("application_usage."+period+"."+key,attributed==ledgers,
                      {"applications":attributed,"ledgers":ledgers})
                for app,windows in usage.items():
                    if period not in windows:continue
                    row=windows[period]
                    check("application_usage."+app+"."+period+"."+key,
                          row[key]==sum((row.get(k) or {}).get(field,0) for k in ("direct","history")))
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
            "scope":"Each local ledger is recomputed independently from its own files or database. Optional native reference cross-checks Codex account identity, quota, reset times, credits and cards. Remaining checks validate normalized contracts; uncollected fields are gaps, not passing integrations."}
