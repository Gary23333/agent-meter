"""Optional executable bridge; no scraping and no provider auth scripts."""
import json
import subprocess

from .model import SourceError, metric, number, source, timestamp


def normalize_codexbar(payload, now):
    if not isinstance(payload,list):
        raise SourceError("unsupported_codexbar_json")
    results=[]
    for item in payload:
        if not isinstance(item,dict) or not isinstance(item.get("provider"),str):
            raise SourceError("unsupported_codexbar_json")
        provider=item["provider"]
        if provider not in {"claude","kimi","minimax","qoder","workbuddy","zai","trae","cursor","gemini","opencode","codex"}:
            continue
        if item.get("error"):
            continue
        usage=item.get("usage")
        if not isinstance(usage,dict):
            continue
        out=source("codexbar:"+provider,"account",now)
        quotas,resets=[],[]
        for key in ("primary","secondary","tertiary"):
            raw=usage.get(key)
            if not isinstance(raw,dict) or raw.get("usedPercent") is None:
                continue
            used=number(raw["usedPercent"])
            reset=timestamp(raw.get("resetsAt"))
            quotas.append({"bucket":key,"used_percent":used,"remaining_percent":max(0,100-used),"resets_at":reset})
            if reset:resets.append({"bucket":key,"resets_at":reset})
        out["metrics"]["quota"]=metric(quotas or None)
        out["metrics"]["reset_time"]=metric(resets or None)
        # CLI reports a summary only, never fabricate individual card rows.
        cards=item.get("resetCredits")
        if isinstance(cards,dict):
            from .model import integer
            out["metrics"]["reset_cards"]=metric({"available_count":integer(cards.get("available")),
                "cards":None,"details_state":"unknown","next_known_expiry":timestamp(cards.get("nextExpiresAt"))})
        results.append(out)
    return results


def collect_codexbar(binary,now,timeout=30):
    if not binary:raise SourceError("codexbar_not_installed")
    try:
        proc=subprocess.run([binary,"usage","--format","json"],capture_output=True,timeout=timeout)
        if proc.returncode:raise SourceError("codexbar_fetch_failed")
        if len(proc.stdout)>8*1024*1024:raise SourceError("response_too_large")
        return normalize_codexbar(json.loads(proc.stdout),now)
    except subprocess.TimeoutExpired:
        raise SourceError("codexbar_timeout") from None
    except (ValueError,OSError):
        raise SourceError("codexbar_response_failed") from None
