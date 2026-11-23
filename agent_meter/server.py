import hmac
import json
import os
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .model import SCHEMA_VERSION, SourceError
from .web_sources import validate_sessions
from .dreamina_web import validate_observations

MAX_SESSION_BODY = 64 * 1024
MAX_PET_BODY = 4 * 1024
# A decrypted sync payload from another device travels over loopback only.
MAX_SYNC_BODY = 8 * 1024 * 1024
# Sources the app may switch off at runtime.
TOGGLEABLE = {"claude", "codex", "kimi", "qoder", "minimax_code", "deepseek_api", "dreamina", "minimax_design", "workbuddy", "trae_cn", "reset_forecast"}
# Accounts whose daily rewards the claim endpoints accept (agent_meter/rewards.py).
CLAIMABLE = {"trae_cn", "workbuddy", "qoder", "minimax_code"}


def load_or_create_token(path):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    try:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    except FileExistsError:
        if path.is_symlink():raise ValueError("token file cannot be a symlink")
        token=path.read_text().strip()
        if len(token)<32:raise ValueError("invalid local token")
        os.chmod(path,0o600)
        return token
    token=secrets.token_urlsafe(32)
    with os.fdopen(fd,"w") as handle:handle.write(token+"\n")
    return token


def make_server(service,token,port=8769):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass

        def send_json(self,status,payload):
            body=json.dumps(payload,ensure_ascii=False,allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type","application/json; charset=utf-8")
            self.send_header("Content-Length",str(len(body)))
            self.send_header("Cache-Control","no-store")
            self.send_header("X-Content-Type-Options","nosniff")
            self.end_headers()
            self.wfile.write(body)

        def authorized(self):
            # Reject browser-origin traffic and DNS rebinding regardless of auth.
            port=self.server.server_address[1]
            if self.headers.get("Host") not in {f"127.0.0.1:{port}",f"localhost:{port}"}:
                self.send_json(403,{"error":"host_rejected"});return False
            if self.headers.get("Origin"):
                self.send_json(403,{"error":"origin_rejected"});return False
            provided=self.headers.get("Authorization","")
            if not hmac.compare_digest(provided.encode(),("Bearer "+token).encode()):
                self.send_json(401,{"error":"authentication_required"});return False
            return True

        def do_GET(self):
            if not self.authorized():return
            route=urlsplit(self.path)
            if route.query or len(self.path)>200:
                self.send_json(400,{"error":"unsupported_query"});return
            if route.path=="/v1/health":
                self.send_json(200,{"status":"ok","schema_version":SCHEMA_VERSION});return
            if route.path in {"/v1/prices","/v1/prices/USD","/v1/prices/CNY"}:
                from .prices import load_prices
                from .peak import WINDOW
                from .model_catalog import catalog_status
                currency = route.path.rsplit("/",1)[-1] if route.path != "/v1/prices" else None
                table=load_prices(service.config["runtime_dir"], currency)
                self.send_json(200,{"currency":table.currency,
                                    "models":{p:{**dict(zip(("input","cache_read","cache_write","output"),v)),
                                                 "peak_multiplier":table.peak_multipliers.get(p,1.0)}
                                              for p,v in table.models.items()},
                                    "peak_window":WINDOW,
                                    "peak_multipliers":table.peak_overrides,
                                    "user_patterns":sorted(table.user_models),
                                    "aliases":table.aliases,"catalog":table.catalog,
                                    "sync":catalog_status(service.config["runtime_dir"]),
                                    "converted_patterns":sorted(table.converted)})
                return
            if route.path=="/v1/budget":
                # Config + current snapshot only; never triggers a collection.
                from .budget import budget_state
                try:self.send_json(200,budget_state(service))
                except Exception:self.send_json(500,{"error":"budget_failed"})
                return
            if route.path=="/v1/pet":
                # Interprets cached data only; never triggers a collection.
                try:self.send_json(200,service.pet_frame())
                except Exception:self.send_json(500,{"error":"pet_failed"})
                return
            if route.path=="/v1/activity":
                # Lightweight recent-activity scan; independent of the full snapshot.
                try:self.send_json(200,service.activity())
                except Exception:self.send_json(500,{"error":"activity_failed"})
                return
            if route.path in {"/v1/projects","/v1/status","/v1/periods/week","/v1/periods/month"}:
                # Projections of the cached snapshot; no new account collection.
                try:
                    import time as _time
                    data=service.get()
                    now=_time.time()
                    if route.path=="/v1/projects":
                        from .projects import project_usage
                        self.send_json(200,project_usage(service.config,data))
                    elif route.path=="/v1/status":
                        from .status import collection_status
                        self.send_json(200,collection_status(data,service.config,now))
                    else:
                        from .report_periods import compute_period_report
                        from .prices import load_prices
                        from .exchange_rates import rate_from
                        table=load_prices(service.config["runtime_dir"],"CNY",fx_rate=rate_from(data))
                        self.send_json(200,compute_period_report(data,table,now,route.path.rsplit("/",1)[-1]))
                except Exception:
                    self.send_json(500,{"error":"projection_failed"})
                return
            if route.path=="/v1/forecast/landings":
                # Landing scorecard over the local observation store; no collection.
                from .reset_landings import landing_scorecard
                try:self.send_json(200,landing_scorecard(str(Path(service.config["runtime_dir"])/"reset-forecast-landings.json")))
                except Exception:self.send_json(500,{"error":"landings_failed"})
                return
            if route.path in {"/v1/export/json","/v1/export/csv"}:
                # Local export projects the cached snapshot; never collects.
                import time as _time
                from .export_data import export_payload, export_csv
                data=service.peek() or {}
                if route.path=="/v1/export/json":
                    self.send_json(200,export_payload(data,_time.time()))
                else:
                    body=export_csv(data).encode()
                    self.send_response(200)
                    self.send_header("Content-Type","text/csv; charset=utf-8")
                    self.send_header("Content-Length",str(len(body)))
                    self.send_header("Cache-Control","no-store")
                    self.send_header("X-Content-Type-Options","nosniff")
                    self.end_headers()
                    self.wfile.write(body)
                return
            if route.path=="/v1/sync/history":
                # Local rows plus whatever other devices pushed. Synced rows
                # never enter the snapshot, so this is its own projection. The
                # shape only ever grows: a client reads the keys it knows.
                try:
                    from .sync_store import (account_history, card_history, day_history, device_summaries, history,
                                             load_store, quota_history, quota_series, remote_quota_history,
                                             reward_history)
                    from .sync_payload import card_tally, quota_rows, usage_rows
                    from .sync_quota import series as local_quota_series
                    from .sync_usage import usage_periods
                    runtime=service.config["runtime_dir"]
                    data=service.get()
                    store=load_store(runtime)
                    local=store.get("local_device") or ""
                    # The service's clock, never the wall clock: the same
                    # "now" as the snapshot the rows are projected from.
                    now=service.clock()
                    self.send_json(200,{"schema":1,"local_device":local,
                                        "rows":history(store,usage_rows(data,local)),
                                        "quota":quota_history(store,quota_rows(data,now)),
                                        "remote_quota":remote_quota_history(store),
                                        # Every known day of every account window, this
                                        # device's own journal included.
                                        "quota_series":quota_series(store,local_quota_series(runtime)),
                                        "accounts":account_history(store),
                                        "rewards":reward_history(store),
                                        "images":day_history(store,"images"),
                                        "credits":day_history(store,"credits"),
                                        "cards":card_history(store,card_tally(data)),
                                        "devices":device_summaries(store),
                                        "usage":usage_periods(store,runtime,now)})
                except Exception:
                    self.send_json(500,{"error":"sync_history_failed"})
                return
            if route.path not in {"/v1/snapshot","/v1/coverage","/v1/sources"}:
                self.send_json(404,{"error":"not_found"});return
            try:
                data=service.get()
                if route.path=="/v1/snapshot":self.send_json(200,data)
                elif route.path=="/v1/coverage":self.send_json(200,{"summary":data["coverage_summary"],"coverage":data["coverage"]})
                else:self.send_json(200,{"sources":data["sources"]})
            except Exception:
                self.send_json(500,{"error":"collection_failed"})

        def read_json(self,limit):
            """Parsed JSON body, or None after the error response has been sent."""
            if self.headers.get("Transfer-Encoding") or not (self.headers.get("Content-Type","").split(";")[0].strip()=="application/json"):
                self.send_json(400,{"error":"json_body_required"});self.close_connection=True;return None
            try:length=int(self.headers.get("Content-Length",""))
            except ValueError:length=-1
            if not 0<length<=limit:
                self.send_json(400,{"error":"invalid_body_length"});self.close_connection=True;return None
            try:return json.loads(self.rfile.read(length))
            except (ValueError,UnicodeDecodeError):
                self.send_json(400,{"error":"invalid_json"});return None

        def do_POST(self):
            if not self.authorized():return
            if self.path=="/v1/forecast/announcement":
                # Manual announcement time: a fact only, never a probability or a clock.
                body=self.read_json(MAX_SESSION_BODY)
                if body is None:return
                from .reset_landings import add_manual_announcement
                try:
                    event=add_manual_announcement(str(Path(service.config["runtime_dir"])/"reset-forecast-manual.json"),
                                                  body.get("announced_at"),body.get("note"))
                except SourceError as e:
                    self.send_json(400 if e.code=="manual_announcement_invalid" else 500,
                                   {"error":e.code});return
                self.send_json(200,event);return
            if self.path=="/v1/pet/events":
                # Hook events (agent finished / waiting ...): in-memory only, kinds are whitelisted.
                body=self.read_json(MAX_PET_BODY)
                if body is None:return
                try:event=service.pet_event(body)
                except ValueError:
                    self.send_json(400,{"error":"invalid_event"});return
                self.send_json(200,{"id":event["id"],"kind":event["kind"]});return
            if self.path=="/v1/sync/payload":
                # The redacted projection this device is willing to upload.
                body=self.read_json(MAX_SESSION_BODY)
                if body is None:return
                if not isinstance(body,dict):
                    self.send_json(400,{"error":"invalid_sync_payload"});return
                try:
                    from .sync_payload import build_payload, quota_rows
                    from .sync_quota import record as record_quota
                    from .sync_store import set_local_device
                    runtime=service.config["runtime_dir"]
                    device=body.get("device")
                    # Checked before anything is written: an invalid device must
                    # not open the quota journal or name this installation.
                    if not isinstance(device,str) or not device or len(device)>64:
                        raise SourceError("invalid_device")
                    set_local_device(runtime,device)
                    now=service.clock()
                    data=service.get()
                    # Today's observations join this device's quota history. The
                    # first payload also opens the journal that every later
                    # collection fills, so the history grows between syncs too.
                    history=record_quota(runtime,quota_rows(data,now),now,create=True)
                    self.send_json(200,build_payload(data,device,body.get("settings"),now,
                                                     settings_times=body.get("settings_times"),
                                                     device_name=body.get("name"),app_version=body.get("app_version"),
                                                     quota_history=history,
                                                     rewards_ledger=service.rewards.ledger if service.rewards else None))
                except SourceError:
                    self.send_json(400,{"error":"invalid_sync_payload"});return
                except Exception:
                    self.send_json(500,{"error":"sync_payload_failed"});return
                return
            if self.path=="/v1/sync/reset":
                # The user left the space: forget every remote device, and the
                # quota history that only existed to be synced.
                body=self.read_json(MAX_SESSION_BODY)
                if body is None:return
                if not isinstance(body,dict):
                    self.send_json(400,{"error":"invalid_sync_payload"});return
                try:
                    from .sync_quota import clear as clear_quota
                    from .sync_store import reset
                    runtime=service.config["runtime_dir"]
                    reset(runtime)
                    clear_quota(runtime)
                except OSError:
                    self.send_json(500,{"error":"sync_reset_failed"});return
                self.send_json(200,{"reset":True});return
            if self.path=="/v1/sync/forget":
                # One remote device was removed from the space: drop what it sent.
                body=self.read_json(MAX_SESSION_BODY)
                if body is None:return
                if not isinstance(body,dict):
                    self.send_json(400,{"error":"invalid_device"});return
                try:
                    from .sync_store import forget_device, load_store
                    runtime=service.config["runtime_dir"]
                    device=body.get("device")
                    # Only another device's rows can be forgotten here; this
                    # device's own data is the live snapshot, not a stored copy.
                    if not isinstance(device,str) or not device:
                        raise ValueError("invalid_device")
                    forget_device(runtime,device,load_store(runtime).get("local_device"))
                except ValueError:
                    self.send_json(400,{"error":"invalid_device"});return
                except OSError:
                    self.send_json(500,{"error":"sync_forget_failed"});return
                self.send_json(200,{"device":device,"forgotten":True});return
            if self.path=="/v1/doubao/import-app-cookies":
                # 从本机豆包客户端的 Cookie 库取登录态；只回给本机 App，不落盘。
                if self.headers.get("Content-Length","0")!="0" or self.headers.get("Transfer-Encoding"):
                    self.send_json(400,{"error":"body_not_allowed"});self.close_connection=True;return
                from .doubao import import_doubao_app_cookies
                try:cookie=import_doubao_app_cookies(service.config)
                except SourceError as e:
                    self.send_json(400,{"error":e.code});return
                except Exception:
                    self.send_json(500,{"error":"doubao_cookie_import_failed"});return
                self.send_json(200,{"cookie":cookie});return
            claim_slot=None
            claim_all=False
            if self.path=="/v1/rewards/claim":
                # The panel's "claim everything now" button: no slot, no body.
                claim_all=True
            elif self.path.startswith("/v1/rewards/claim/"):
                # "#" travels percent-encoded ("trae_cn%232").
                claim_slot=unquote(self.path[len("/v1/rewards/claim/"):])
                provider,_,number=claim_slot.partition("#")
                if provider not in CLAIMABLE or (number and not (number.isdigit() and 2<=int(number)<=5)):
                    self.send_json(404,{"error":"not_found"});return
            elif self.path not in {"/v1/refresh","/v1/prices/sync"}:self.send_json(404,{"error":"not_found"});return
            if self.headers.get("Content-Length","0")!="0" or self.headers.get("Transfer-Encoding"):
                self.send_json(400,{"error":"body_not_allowed"});self.close_connection=True;return
            if claim_all or claim_slot is not None:
                try:self.send_json(200,service.claim_now(claim_slot))
                except Exception:self.send_json(500,{"error":"claim_failed"})
                return
            if self.path=="/v1/prices/sync":
                from .model_catalog import sync_catalog
                result=sync_catalog(service.config["runtime_dir"],force=True)
                service.reload_prices()
                self.send_json(200 if result["status"]!="error" else 502,result)
                return
            try:self.send_json(200,service.get(force=True))
            except Exception:self.send_json(500,{"error":"collection_failed"})

        def do_PUT(self):
            # Website logins from the menu bar app: kept in memory, never echoed.
            if not self.authorized():return
            if self.path not in {"/v1/web-sessions","/v1/observations","/v1/preferences","/v1/prices","/v1/budget","/v1/pet/preferences","/v1/sync/import"}:self.send_json(404,{"error":"not_found"});return
            if self.headers.get("Transfer-Encoding") or not (self.headers.get("Content-Type","").split(";")[0].strip()=="application/json"):
                self.send_json(400,{"error":"json_body_required"});self.close_connection=True;return
            try:length=int(self.headers.get("Content-Length",""))
            except ValueError:length=-1
            limit=MAX_SYNC_BODY if self.path=="/v1/sync/import" else MAX_SESSION_BODY
            if not 0<length<=limit:
                self.send_json(400,{"error":"invalid_body_length"});self.close_connection=True;return
            try:body=json.loads(self.rfile.read(length))
            except (ValueError,UnicodeDecodeError):
                self.send_json(400,{"error":"invalid_json"});return
            if self.path=="/v1/sync/import":
                # A payload this device decrypted from the service.
                try:
                    import time as _time
                    from .sync_payload import parse_payload
                    from .sync_store import replace_device, set_local_device
                    if not isinstance(body,dict):raise SourceError("invalid_sync_payload")
                    local_device=body.get("local_device")
                    if not isinstance(local_device,str) or not local_device:
                        raise SourceError("invalid_device")
                    # Validate before anything is written: a rejected payload
                    # must not repoint the local device or touch the store.
                    record=parse_payload(body.get("payload"))
                    record["updated_at"]=_time.time()
                    set_local_device(service.config["runtime_dir"],local_device)
                    replace_device(service.config["runtime_dir"],record,local_device)
                except (SourceError,ValueError):
                    self.send_json(400,{"error":"invalid_sync_payload"});return
                except OSError:
                    self.send_json(500,{"error":"sync_import_failed"});return
                self.send_json(200,{"device":record["device"],"rows":len(record["rows"]),
                                    "stored":record["device"]!=local_device})
                return
            if self.path=="/v1/budget":
                from .budget import save_budget
                try:saved=save_budget(service.config["runtime_dir"],body)
                except ValueError:
                    self.send_json(400,{"error":"invalid_budget"});return
                self.send_json(200,saved);return
            if self.path=="/v1/pet/preferences":
                try:saved=service.set_pet_preferences(body)
                except ValueError:
                    self.send_json(400,{"error":"invalid_preferences"});return
                self.send_json(200,saved);return
            if self.path=="/v1/preferences":
                # Device-local switches only. Claiming has no preference: it
                # runs when the user asks for it and at no other time.
                ok=isinstance(body,dict) and "disabled_sources" in body and set(body)<={"disabled_sources","low_resource_mode","skip_ledgers_low_resource"}
                off=body.get("disabled_sources") if ok else None
                low=body.get("low_resource_mode",False) if ok else None
                skip=body.get("skip_ledgers_low_resource",[]) if ok else None
                if not isinstance(off,list) or any(x not in TOGGLEABLE for x in off) \
                        or not isinstance(low,bool) \
                        or not isinstance(skip,list) or any(not isinstance(x,str) for x in skip):
                    self.send_json(400,{"error":"invalid_preferences"});return
                prefs={"disabled_sources":sorted(set(off)),"low_resource_mode":low,
                       "skip_ledgers_low_resource":sorted(set(skip))}
                service.set_preferences(prefs)
                self.send_json(200,prefs);return
            if self.path=="/v1/prices":
                try:
                    from .prices import PRICE_KEYS
                    if not isinstance(body,dict) or set(body)-{"currency","models","aliases","peak_multipliers"} \
                            or body.get("currency") not in {"USD","CNY"} or not isinstance(body.get("models"),dict) \
                            or not isinstance(body.get("aliases",{}),dict) \
                            or not isinstance(body.get("peak_multipliers",{}),dict):
                        raise ValueError()
                    for pattern,row in body["models"].items():
                        if not isinstance(pattern,str) or not 0<len(pattern)<=120 or not isinstance(row,dict) \
                                or set(row)-set(PRICE_KEYS) or len(body["models"])>500:
                            raise ValueError()
                    aliases=body.get("aliases",{})
                    peak_multipliers=body.get("peak_multipliers")
                    saved=service.set_prices(body["currency"],body["models"],aliases,peak_multipliers)
                    self.send_json(200,saved);return
                except (ValueError, SourceError):
                    self.send_json(400,{"error":"invalid_prices"});return
            if self.path=="/v1/observations":
                try:observations=validate_observations(body)
                except ValueError:
                    self.send_json(400,{"error":"invalid_observations"});return
                service.set_observations(observations)
                self.send_json(200,{"dreamina":len(observations["dreamina"])});return
            try:sessions=validate_sessions(body)
            except ValueError:
                self.send_json(400,{"error":"invalid_sessions"});return
            service.set_web_sessions(sessions)
            self.send_json(200,{"providers":sorted(sessions)})

    server=ThreadingHTTPServer(("127.0.0.1",port),Handler)
    server.daemon_threads=True
    return server
