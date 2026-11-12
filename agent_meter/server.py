import hmac
import json
import os
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .model import SCHEMA_VERSION
from .web_sources import validate_sessions
from .dreamina_web import validate_observations

MAX_SESSION_BODY = 64 * 1024
MAX_PET_BODY = 4 * 1024
# Sources the app may switch off at runtime.
# Providers whose daily rewards the app may claim (agent_meter/rewards.py).
CLAIMABLE = {"trae_cn", "workbuddy", "qoder", "minimax_code"}
TOGGLEABLE = {"claude", "codex", "kimi", "qoder", "minimax_code", "deepseek_api", "dreamina", "minimax_design", "workbuddy", "trae_cn", "reset_forecast"}


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
                from .model import SourceError
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
            if self.path not in {"/v1/web-sessions","/v1/observations","/v1/preferences","/v1/prices","/v1/budget","/v1/pet/preferences"}:self.send_json(404,{"error":"not_found"});return
            if self.headers.get("Transfer-Encoding") or not (self.headers.get("Content-Type","").split(";")[0].strip()=="application/json"):
                self.send_json(400,{"error":"json_body_required"});self.close_connection=True;return
            try:length=int(self.headers.get("Content-Length",""))
            except ValueError:length=-1
            if not 0<length<=MAX_SESSION_BODY:
                self.send_json(400,{"error":"invalid_body_length"});self.close_connection=True;return
            try:body=json.loads(self.rfile.read(length))
            except (ValueError,UnicodeDecodeError):
                self.send_json(400,{"error":"invalid_json"});return
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
                from .rewards import CLAIM_TIME, DEFAULT_CLAIM_TIME
                ok=isinstance(body,dict) and "disabled_sources" in body and set(body)<={"disabled_sources","low_resource_mode","skip_ledgers_low_resource","auto_claim","claim_time"}
                off=body.get("disabled_sources") if ok else None
                low=body.get("low_resource_mode",False) if ok else None
                skip=body.get("skip_ledgers_low_resource",[]) if ok else None
                auto=body.get("auto_claim",[]) if ok else None
                claim_time=body.get("claim_time",DEFAULT_CLAIM_TIME) if ok else None
                if not isinstance(off,list) or any(x not in TOGGLEABLE for x in off) \
                        or not isinstance(low,bool) \
                        or not isinstance(skip,list) or any(not isinstance(x,str) for x in skip) \
                        or not isinstance(auto,list) or any(x not in CLAIMABLE for x in auto) \
                        or not isinstance(claim_time,str) or not CLAIM_TIME.match(claim_time):
                    self.send_json(400,{"error":"invalid_preferences"});return
                prefs={"disabled_sources":sorted(set(off)),"low_resource_mode":low,
                       "skip_ledgers_low_resource":sorted(set(skip)),
                       "auto_claim":sorted(set(auto)),"claim_time":claim_time}
                service.set_preferences(prefs)
                self.send_json(200,prefs);return
            if self.path=="/v1/prices":
                try:
                    from .prices import PRICE_KEYS
                    from .model import SourceError
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
