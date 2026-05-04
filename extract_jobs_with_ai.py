#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import argparse, csv, json, re, urllib.request
from collections import defaultdict, Counter
from typing import List, Dict, Any, Optional
from media_processing import media_type_for, extract_video_frames
from vision_analyzer import get_vision_analyzer, DEFAULT_VISION_MODEL
import os

VALID_STATUS = {"new_lead","needs_info","inspection_required","ready_to_quote","quote_sent","scheduled","in_progress","blocked","completed"}
VALID_URGENCY = {"low","medium","high"}
VALID_QR = {"not_ready","partially_ready","ready"}
ENABLE_VISION_ANALYSIS = os.getenv("ENABLE_VISION_ANALYSIS","1") != "0"
VISION_ANALYZER_MODE = os.getenv("VISION_ANALYZER_MODE","auto")
VISION_MODEL = os.getenv("DEFAULT_VISION_MODEL", DEFAULT_VISION_MODEL)
MAX_MEDIA_PER_JOB = int(os.getenv("MAX_MEDIA_PER_JOB", "2"))
MAX_CHAT_CONTEXT_CHARS = int(os.getenv("MAX_CHAT_CONTEXT_CHARS", "1400"))


def read_messages(path: Path) -> List[Dict[str, Any]]:
    out=[]
    with path.open("r",encoding="utf-8") as f:
        for line in f:
            line=line.strip()
            if line: out.append(json.loads(line))
    return out


def group_by_chat(msgs):
    g=defaultdict(list)
    for m in msgs: g[m["chat_id"]].append(m)
    for k in g: g[k].sort(key=lambda x:x["timestamp"])
    return g


def contains_any(text, words):
    t=text.lower()
    return any(w in t for w in words)


def classify_trade(text: str) -> str:
    t=text.lower()
    if contains_any(t,["toilet","faucet","sink","pipe","plumb","drain","leak"]): return "plumbing"
    if contains_any(t,["roof","shingle","flashing","attic"]): return "roofing"
    if contains_any(t,["tile","grout","shower","bathroom"]): return "tile"
    if contains_any(t,["outlet","breaker","panel","electric","spark","power"]): return "electrical"
    if contains_any(t,["hvac","furnace","ac","a/c","cooling","heat","thermostat"]): return "hvac"
    if contains_any(t,["paint","floor","renov","remodel"]): return "general"
    return "unknown"


def extract_location(text: str) -> Optional[str]:
    m=re.search(r"(?:address|addr)\s*:?\s*([^\n\.]+)",text,re.I)
    if m: return m.group(1).strip()
    m=re.search(r"\b\d{1,5}\s+[\w\s\.-]+(?:St|Street|Ave|Avenue|Rd|Road|Dr|Drive|Blvd|Lane|Ln|Ct|Court)\b[^\n,]*",text,re.I)
    return m.group(0).strip() if m else None


def detect_urgency(text: str) -> str:
    hi=["urgent","emergency","asap","today","tomorrow","before friday","before weekend","leaking","flood","no heat","no ac","no power","burst","active leak","water coming through","safety issue"]
    med=["this week","soon","next few days","quote quickly","trying to schedule","time sensitive"]
    low=["no rush","whenever","next month","flexible","just planning"]
    t=text.lower()
    if any(k in t for k in hi): return "high"
    if any(k in t for k in med): return "medium"
    if any(k in t for k in low): return "low"
    return "medium"


def find_snippet(text: str, keywords: List[str]) -> str:
    for line in text.splitlines():
        l=line.lower()
        if any(k in l for k in keywords):
            return line.strip()[:180]
    return text.splitlines()[0].strip()[:180] if text.splitlines() else ""


def risk_flags(text: str):
    t=text.lower(); out=[]
    def add(tp,sev,ev,impact,mit,kw):
        snippet = find_snippet(text, kw)
        out.append({"type":tp,"severity":sev,"evidence":ev[:180],"evidence_snippet":snippet,"business_impact":impact,"recommended_mitigation":mit})
    if contains_any(t,["maybe","not sure","i think","roughly","unclear"]): add("scope_uncertainty","medium","Vague scope in messages","Quote may be inaccurate","Ask clarifying questions or inspect",["maybe","not sure","i think","roughly","unclear"])
    if contains_any(t,["leak","soft wall","water behind","damp","mold","flood","stain"]): add("water_damage","high","Water-damage indicators present","Hidden damage can increase labor/materials","Inspect before final quote",["leak","soft wall","water","damp","mold","stain"])
    if detect_urgency(text)=="high": add("timeline_pressure","high","Urgent timing request","Schedule disruption and rush cost risk","Confirm availability and rush pricing",["urgent","asap","today","tomorrow","before friday"])
    if contains_any(t,["cheap","discount","cash deal","low budget","can you do less","budget"]): add("budget_pressure","medium","Budget-sensitive language","Margin pressure","Offer options and define scope",["budget","cheap","discount","can you do less"])
    if contains_any(t,["condo","tenant","gate","parking","buzzer","limited hours","locked","no one home"]): add("access_issue","medium","Access constraints mentioned","Potential missed visits","Confirm access details in advance",["condo","tenant","gate","parking","buzzer","locked"])
    if contains_any(t,["not chosen","color","finish","brand","size unknown","which tile"]): add("material_uncertainty","medium","Materials not finalized","Delays/wrong purchases","Confirm selections or allowance",["not chosen","color","finish","brand","size unknown","which tile","materials"])
    if contains_any(t,["panel","gas","structural","sparks","no power","unsafe"]): add("safety_or_code_risk","high","Potential safety/code issue","May require licensed specialist","Require qualified inspection",["panel","gas","structural","sparks","no power","unsafe"])
    if contains_any(t,["also","while you're here","one more thing","another room","add this"]): add("scope_creep_risk","medium","Scope expansion language","Out-of-scope expansion risk","Document change order",["also","while you're here","one more thing","another room","add this"])
    if contains_any(t,["waiting","no reply","send photos","missing address"]): add("communication_gap","low","Information gaps detected","Lead can stall","Follow up with concise checklist",["waiting","no reply","send photos","missing address"])
    if contains_any(t,["behind wall","ceiling","unknown source","not sure what happened"]): add("unknown_site_condition","high","Hidden condition likely","Estimate uncertainty","Inspect and note assumptions",["behind wall","ceiling","unknown source","not sure what happened"])
    return out


def materials_for_trade(trade: str, text: str):
    if trade=="tile":
        return (["replacement tiles","grout","thinset","spacers","waterproofing membrane"],["tile size","tile type","grout color","square footage","waterproofing/backer board condition"],["affected square footage","tile dimensions","shower area dimensions"])
    if trade=="roofing":
        likely=["shingles or roofing material","underlayment","flashing","sealant"]
        if "active leak" in text.lower() or "leak" in text.lower(): likely.append("emergency tarp")
        return (likely,["roof material","roof age","shingle color","leak location"],["affected area","number of stories/access"])
    if trade=="plumbing":
        return (["wax ring","bolts","supply line","valve/fittings","teflon tape"],["fixture model","pipe type","shutoff condition"],["fixture dimensions if replacement"])
    if trade=="electrical":
        return (["outlet/switch/fixture/breaker"],["device type","panel/breaker type","fixture model"],["panel details","affected circuit details"])
    if trade=="hvac":
        return (["filter","thermostat","capacitor","unit-specific parts"],["unit model","unit age","error code"],["unit access location"])
    return (["paint/flooring/finish materials"],["finish selections","brand/grade","rooms affected"],["room dimensions","scope measurements"])


def build_job(chat_id: str, messages: List[Dict[str,Any]]) -> Dict[str,Any]:
    text="\n".join((m.get("text") or "") for m in messages)
    senders=[m.get("sender") for m in messages if m.get("sender") and m.get("sender")!="You"]
    customer=Counter(senders).most_common(1)[0][0] if senders else None
    trade=classify_trade(text)
    loc=extract_location(text)
    risks=risk_flags(text)
    urgency=detect_urgency(text)
    inspection_needed=any(r["type"] in ["water_damage","safety_or_code_risk","unknown_site_condition"] for r in risks)
    missing=[]
    if not loc: missing.append("exact service address")
    if trade=="unknown": missing.append("clear job type")
    missing_evidence = []
    if "photo" not in text.lower():
        missing.append("photos")
        missing_evidence.append({"input":"photos","evidence_snippet":find_snippet(text,["photo","pics","image"]) or "No photo mention found."})
    likely,confirm,measure=materials_for_trade(trade,text)
    for c in confirm[:2]:
        missing.append(c)
        missing_evidence.append({"input":c,"evidence_snippet":find_snippet(text,[c.split()[0].lower(),"not sure","unknown", "maybe"])})
    missing=list(dict.fromkeys(missing))
    if inspection_needed:
        status,qscore,qstatus,qreason="inspection_required",0.2,"not_ready","Potential hidden/safety risk requires inspection before pricing."
    elif len(missing)>=4:
        status,qscore,qstatus,qreason="needs_info",0.5,"partially_ready","Basic scope exists but key quote inputs are missing."
    else:
        status,qscore,qstatus,qreason="ready_to_quote",0.85,"ready","Scope and inputs appear sufficient for a quote."
    purchase_risk="high" if trade in ["tile","roofing","electrical","hvac"] else "medium"
    actions=[{"action":"Ask customer for missing info checklist","owner":"contractor","priority":"high" if status!="ready_to_quote" else "medium","reason":"Improve quote accuracy and reduce callbacks.","evidence_snippet":(missing_evidence[0]["evidence_snippet"] if missing_evidence else find_snippet(text,["quote","not sure","details"]))},
             {"action":"Schedule inspection" if status=="inspection_required" else "Prepare quote draft","owner":"contractor","priority":"high","reason":"Move lead to the next stage quickly.","evidence_snippet":find_snippet(text,["leak","sparking","urgent","unknown","soft wall"])}]
    top_risk=risks[0]["type"] if risks else "communication_gap"
    reply=f"Thanks for reaching out. To quote this properly, please share {', '.join(missing[:3])}." + (" Because of potential hidden conditions, we may need an inspection before final pricing." if status=="inspection_required" else "")
    summary=f"{urgency.title()}-urgency {trade} lead. Status: {status}. Quote readiness: {qstatus} ({qscore}). Top risk: {top_risk}. Next step: {actions[0]['action'].lower()}."
    return {
      "job_id":f"job_{chat_id}","chat_id":chat_id,"customer_name":customer,"phone":None,"location":loc,"trade_category":trade,
      "job_type":trade.replace("_"," ").title()+" job","scope_summary":(text[:220] or "No scope found"),"job_status":status,
      "urgency":urgency,"requested_timeline":None,
      "quote_readiness":{"status":qstatus,"score":round(qscore,2),"reason":qreason,"missing_quote_inputs":missing[:8],"missing_quote_input_evidence":missing_evidence[:8]},
      "materials_intelligence":{"likely_materials":likely,"materials_to_confirm":confirm,"measurements_needed":measure,"purchase_risk":purchase_risk,"material_notes":"Generated as planning guidance; confirm before purchase."},
      "risk_flags":risks or [{"type":"communication_gap","severity":"low","evidence":"No explicit risks stated","business_impact":"Lead may stall","recommended_mitigation":"Send follow-up checklist"}],
      "recommended_actions":actions,"customer_reply_draft":reply,"operator_summary":summary,"confidence":0.8,"privacy_mode":"local_ollama","source_msg_ids":[m["message_id"] for m in messages[-12:]]
    }


def _is_vague(text: Any) -> bool:
    if not isinstance(text, str):
        return True
    s = text.strip().lower()
    return len(s) < 12 or s in {"n/a", "unknown", "none", "tbd", "na"}


def normalize_job(job: Dict[str,Any], fallback: Dict[str,Any]) -> Dict[str,Any]:
    merged = dict(fallback)
    merged.update(job or {})
    merged["job_status"] = merged.get("job_status") if merged.get("job_status") in VALID_STATUS else fallback["job_status"]
    merged["urgency"] = merged.get("urgency") if merged.get("urgency") in VALID_URGENCY else fallback["urgency"]

    qr = merged.get("quote_readiness") if isinstance(merged.get("quote_readiness"), dict) else {}
    fqr = fallback["quote_readiness"]
    qstatus = qr.get("status") if qr.get("status") in VALID_QR else fqr["status"]
    try: qscore = float(qr.get("score", fqr["score"]))
    except Exception: qscore = fqr["score"]
    qscore = max(0.0, min(1.0, qscore))
    qreason = qr.get("reason") if not _is_vague(qr.get("reason")) else fqr["reason"]
    missing = qr.get("missing_quote_inputs") if isinstance(qr.get("missing_quote_inputs"), list) and qr.get("missing_quote_inputs") else fqr["missing_quote_inputs"]
    merged["quote_readiness"] = {"status": qstatus, "score": round(qscore,2), "reason": qreason, "missing_quote_inputs": missing, "missing_quote_input_evidence": qr.get("missing_quote_input_evidence") if isinstance(qr.get("missing_quote_input_evidence"), list) else fqr.get("missing_quote_input_evidence", [])}

    if not isinstance(merged.get("recommended_actions"), list) or len(merged["recommended_actions"]) == 0:
        merged["recommended_actions"] = fallback["recommended_actions"]
    for i,a in enumerate(merged.get("recommended_actions", [])):
        if not isinstance(a, dict):
            merged["recommended_actions"][i] = fallback["recommended_actions"][0]
            continue
        if _is_vague(a.get("evidence_snippet")):
            a["evidence_snippet"] = (fallback.get("recommended_actions", [{}])[min(i, len(fallback.get("recommended_actions", []))-1)].get("evidence_snippet") if fallback.get("recommended_actions") else "")
    if _is_vague(merged.get("operator_summary")):
        merged["operator_summary"] = fallback["operator_summary"]
    if _is_vague(merged.get("customer_reply_draft")):
        merged["customer_reply_draft"] = fallback["customer_reply_draft"]
    if not isinstance(merged.get("risk_flags"), list) or len(merged["risk_flags"]) == 0:
        merged["risk_flags"] = fallback["risk_flags"]
    merged["privacy_mode"] = "local_ollama"
    return merged


def maybe_refine_with_ollama(job: Dict[str,Any], model: str, chat_text: str) -> Dict[str,Any]:
    compact = {
        "job_id": job.get("job_id"),
        "chat_id": job.get("chat_id"),
        "trade_category": job.get("trade_category"),
        "job_status": job.get("job_status"),
        "urgency": job.get("urgency"),
        "scope_summary": job.get("scope_summary"),
        "quote_readiness": job.get("quote_readiness"),
        "risk_flags": job.get("risk_flags", [])[:4],
        "recommended_actions": job.get("recommended_actions", [])[:3],
        "media_summary": job.get("media_summary"),
        "visual_observations": job.get("visual_observations", [])[:4],
    }
    prompt=f"Return only valid JSON for same schema keys. Keep concise fields and practical actions. Input JSON: {json.dumps(compact)}\\nChat:\\n{chat_text[:MAX_CHAT_CONTEXT_CHARS]}"
    try:
        req=urllib.request.Request("http://localhost:11434/api/chat",data=json.dumps({"model":model,"stream":False,"messages":[{"role":"user","content":prompt}],"options":{"temperature":0,"num_predict":220,"top_k":20,"top_p":0.9,"repeat_penalty":1.05}}).encode("utf-8"),headers={"Content-Type":"application/json"})
        with urllib.request.urlopen(req, timeout=90) as resp:
            obj=json.loads(resp.read().decode("utf-8"))
        parsed=json.loads(obj.get("message",{}).get("content","{}"))
        out = normalize_job(parsed, job)
        out["confidence"] = max(float(out.get("confidence") or 0.0), 0.86)
        return out
    except Exception:
        job["notes"] = "Ollama unavailable/malformed output; deterministic fallback used."
        return normalize_job(job, job)



def read_media(path: Optional[Path]) -> List[Dict[str,Any]]:
    if not path or not path.exists():
        return []
    rows=[]
    with path.open("r",encoding="utf-8") as f:
        for line in f:
            line=line.strip()
            if line: rows.append(json.loads(line))
    return rows


def build_context_text(job: Dict[str,Any], msgs: List[Dict[str,Any]]) -> str:
    conv=" ".join((m.get("text") or "") for m in msgs[-8:])[:600]
    risks=", ".join(r.get("type","") for r in job.get("risk_flags",[])[:4])
    return f"Current job context: customer={job.get('customer_name')}; job_type={job.get('job_type')}; trade={job.get('trade_category')}; scope={job.get('scope_summary')}; operator_summary={job.get('operator_summary')}; risks={risks}; quote_reason={(job.get('quote_readiness') or {}).get('reason')}; conversation={conv}. Analyze media and return observations only."


def analyze_media_for_job(job: Dict[str,Any], media_rows: List[Dict[str,Any]], msgs: List[Dict[str,Any]]) -> Dict[str,Any]:
    job_media=media_rows[:MAX_MEDIA_PER_JOB]
    if not job_media or not ENABLE_VISION_ANALYSIS:
        job['media_assets']=job_media
        job['visual_observations']=[]
        job['media_summary']=None
        job['media_followup_questions']=[]
        job['evidence_mode']='text_only'
        job['vision_analysis_mode']='skipped'
        return job
    analyzer=get_vision_analyzer(VISION_ANALYZER_MODE,VISION_MODEL)
    all_obs=[]; summaries=[]; questions=[]; modes=[]; model_used=[]
    has_img=False; has_vid=False
    ctx=build_context_text(job,msgs)
    for m in job_media:
        mtype=m.get('media_type') or media_type_for(m.get('filename',''))
        if mtype=='image':
            has_img=True
            res=analyzer.analyze_image(m.get('local_path',''),ctx)
        elif mtype=='video':
            has_vid=True
            frames=[]
            if VISION_ANALYZER_MODE != "mock":
                frames=extract_video_frames(m.get('local_path',''), str(Path(m.get('local_path','')).parent / 'frames'))
            m['extracted_frames']=frames
            res=analyzer.analyze_video(m.get('local_path',''), [f['frame_path'] for f in frames], ctx)
        else:
            m['analysis_status']='skipped'; continue
        m['analysis_status']='analyzed' if res.get('analysis_mode') in ('mock','smolvlm') else 'failed'
        if res.get("model_used"):
            model_used.append(res["model_used"])
        for o in res.get('visual_observations',[]):
            o['media_id']=m.get('media_id')
            all_obs.append(o)
        if res.get('media_summary'): summaries.append(res['media_summary'])
        questions.extend(res.get('recommended_followup_questions',[]))
        modes.append(res.get('analysis_mode','skipped'))
    mode='text_only'
    if has_img and has_vid: mode='multimodal'
    elif has_vid: mode='text_video'
    elif has_img: mode='text_image'
    job['media_assets']=job_media
    job['visual_observations']=all_obs
    job['media_summary']=' '.join(summaries)[:600] if summaries else None
    job['media_followup_questions']=list(dict.fromkeys(questions))[:6]
    job['evidence_mode']=mode
    uniq_modes=list(dict.fromkeys(modes))
    job['vision_analysis_mode']=uniq_modes[0] if len(uniq_modes)==1 else ('mixed' if uniq_modes else 'skipped')
    job['vision_model_used']=model_used[0] if model_used else None
    return job


def write_outputs(jobs, out_jsonl: Path, out_csv: Path):
    with out_jsonl.open("w",encoding="utf-8") as f:
        for j in jobs: f.write(json.dumps(j,ensure_ascii=False)+"\n")
    headers=["job_id","customer_name","trade_category","location","job_type","urgency","job_status","quote_readiness_status","quote_readiness_score","risk_count","top_risk","material_purchase_risk","next_action","customer_reply_draft","operator_summary","confidence"]
    with out_csv.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=headers)
        w.writeheader()
        for j in jobs:
            w.writerow({"job_id":j["job_id"],"customer_name":j.get("customer_name"),"trade_category":j.get("trade_category"),"location":j.get("location"),"job_type":j.get("job_type"),"urgency":j.get("urgency"),"job_status":j.get("job_status"),"quote_readiness_status":j["quote_readiness"].get("status"),"quote_readiness_score":j["quote_readiness"].get("score"),"risk_count":len(j.get("risk_flags",[])),"top_risk":(j.get("risk_flags") or [{"type":"none"}])[0]["type"],"material_purchase_risk":j["materials_intelligence"].get("purchase_risk"),"next_action":(j.get("recommended_actions") or [{"action":""}])[0]["action"],"customer_reply_draft":j.get("customer_reply_draft"),"operator_summary":j.get("operator_summary"),"confidence":j.get("confidence")})


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--in",dest="inp",required=True)
    ap.add_argument("--out",dest="out_jsonl",required=True)
    ap.add_argument("--csv",dest="out_csv",required=True)
    ap.add_argument("--model",default="phi3.5")
    ap.add_argument("--media",dest="media_jsonl",default=None)
    args=ap.parse_args()
    jobs=[]
    groups=group_by_chat(read_messages(Path(args.inp)))
    media_rows=read_media(Path(args.media_jsonl)) if args.media_jsonl else []
    media_by_chat=defaultdict(list)
    for m in media_rows:
        media_by_chat[m.get("chat_id")].append(m)
    for cid,msgs in groups.items():
        chat_text="\n".join((m.get("text") or "") for m in msgs)
        base=build_job(cid,msgs)
        mm_job=analyze_media_for_job(base, media_by_chat.get(cid, []), msgs)
        final_job=maybe_refine_with_ollama(mm_job,args.model,chat_text)
        jobs.append(normalize_job(final_job, mm_job))
    write_outputs(jobs,Path(args.out_jsonl),Path(args.out_csv))
    print(f"Wrote {len(jobs)} jobs -> {args.out_jsonl} and {args.out_csv}")

if __name__=="__main__":
    main()
