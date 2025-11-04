#!/usr/bin/env python3
# Hybrid Phase 2: rules prefill + local LLM (Ollama) refine, with strict JSON re-ask.
from __future__ import annotations
from pathlib import Path
import argparse, csv, json, re, urllib.request, urllib.error
from datetime import datetime, timedelta, time
from collections import defaultdict, Counter
from typing import List, Dict, Any, Optional, Tuple


# ---------- IO ----------
def read_messages(path: Path) -> List[Dict[str, Any]]:
    out = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def group_by_chat(msgs: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    g = defaultdict(list)
    for m in msgs: g[m["chat_id"]].append(m)
    for k in g: g[k].sort(key=lambda x: x["timestamp"])
    return g


def write_outputs(jobs: List[Dict[str, Any]], out_jsonl: Path, out_csv: Path) -> None:
    with out_jsonl.open("w", encoding="utf-8") as f:
        for j in jobs: f.write(json.dumps(j, ensure_ascii=False) + "\n")
    headers = ["job_id", "chat_id", "customer_name", "job_date_start", "job_date_end", "location", "job_type",
               "materials_required", "confidence", "notes"]
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        w.writeheader()
        for j in jobs:
            row = j.copy()
            row["materials_required"] = ", ".join(j.get("materials_required") or [])
            w.writerow(row)


# ---------- Tiny rules (prefill) ----------
WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
MONTHS = {"january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8,
          "september": 9, "october": 10, "november": 11, "december": 12}
POSTAL_RE = re.compile(r"\b([A-Za-z]\d[A-Za-z])\s?(\d[A-Za-z]\d)\b")
ADDRESS_RE = re.compile(
    r"\b(\d{1,5}\s+[A-Za-z0-9.\-']+(?:\s+[A-Za-z0-9.\-']+)*\s+(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard|Dr|Drive|Court|Ct|Ln|Lane|Way|Pkwy|Parkway|Highway|Hwy)\b(?:[^0-9A-Za-z]|$))",
    re.I)
CITY_HINTS = ["Toronto", "Mississauga", "Brampton", "Scarborough", "Etobicoke", "North York", "Vaughan", "Markham",
              "Oakville", "Hamilton", "Kitchener", "Waterloo", "Guelph"]
TIME_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", re.I)
DATE_PATTERNS = ["%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y", "%m/%d/%y", "%d/%m/%y"]
JOB_TYPE_MAP = {"toilet": "Toilet replacement/repair", "sink": "Sink install/repair", "faucet": "Faucet install/repair",
                "shower": "Shower install/repair", "leak": "Leak diagnosis/repair", "drain": "Drain clear/repair",
                "water heater": "Water heater service", "boiler": "Boiler service", "roof": "Roof leak/repair",
                "shingle": "Shingle repair", "furnace": "Furnace service", "ac ": "AC service", "a/c": "AC service",
                "outlet": "Electrical outlet", "switch": "Light switch", "panel": "Electrical panel"}
MATERIAL_HINTS = ["wax ring", "bolts", "pex", "copper", "cpvc", "p-trap", "shutoff", "hose", "valve", "teflon tape",
                  "thinset", "2x4", "nails", "screws", "gasket", "anode", "thermocouple", "primer", "cement",
                  "adhesive"]


def most_likely_customer_name(messages):
    cnt = Counter()
    for m in messages:
        s = m.get("sender")
        if s and s.lower() != "you" and not m.get("is_system", False): cnt[s] += 1
    return cnt.most_common(1)[0][0] if cnt else None


def find_address(text: str) -> Optional[str]:
    m = re.search(r"address\s*:\s*(.+)", text, re.I)
    if m: return re.split(r"[\n\r]", m.group(1).strip())[0]
    m2 = ADDRESS_RE.search(text)
    if m2:
        cand = m2.group(0).strip(" ,.;")
        for city in CITY_HINTS:
            if re.search(r"\b" + re.escape(city) + r"\b", text,
                         re.I) and city.lower() not in cand.lower(): cand += f", {city}"; break
        p = POSTAL_RE.search(text)
        if p and p.group(0).upper() not in cand.upper(): cand += " " + p.group(0).upper()
        return cand
    p = POSTAL_RE.search(text)
    return p.group(0).upper() if p else None


def parse_absolute_date(s: str) -> Optional[datetime]:
    for fmt in DATE_PATTERNS:
        try:
            return datetime.strptime(s, fmt)
        except:
            pass
    m = re.search(r"\b([A-Za-z]+)\s+(\d{1,2})(?:,\s*(\d{4}))?\b", s)
    if m:
        mon = MONTHS.get(m.group(1).lower())
        if mon:
            day = int(m.group(2))
            year = int(m.group(3)) if m.group(3) else 1900
            return datetime(year, mon, day)
    return None


def resolve_relative_date(s: str, ref_dt: datetime) -> Optional[datetime]:
    sl = s.lower()
    if "day after tomorrow" in sl: return ref_dt + timedelta(days=2)
    if "tomorrow" in sl: return ref_dt + timedelta(days=1)
    if "today" in sl: return ref_dt
    for name, idx in WEEKDAYS.items():
        if name in sl:
            days_ahead = (idx - ref_dt.weekday()) % 7
            if "next " in sl and days_ahead == 0: days_ahead = 7
            return ref_dt + timedelta(days=days_ahead)
    return None


def extract_time(s: str) -> Optional[Tuple[int, int]]:
    m = TIME_RE.search(s)
    if not m: return None
    h = int(m.group(1))
    mi = int(m.group(2) or 0)
    ap = (m.group(3) or "").lower()
    if ap == "pm" and h != 12: h += 12
    if ap == "am" and h == 12: h = 0
    return (h, mi) if (0 <= h <= 23 and 0 <= mi <= 59) else None


def extract_job_type(text: str) -> Optional[str]:
    t = text.lower()
    best = None
    for k, v in JOB_TYPE_MAP.items():
        if k in t: best = v
    return best


def extract_materials(text: str) -> List[str]:
    out = []
    m = re.search(r"materials?\s*:\s*(.+)", text, re.I)
    if m:
        for it in re.split(r",|;|\band\b", m.group(1), flags=re.I):
            it = it.strip(" .;,-").lower()
            if it and it not in out: out.append(it)
    t = text.lower()
    for h in MATERIAL_HINTS:
        if h in t and h not in out: out.append(h)
    return out


def rule_prefill(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    customer = most_likely_customer_name(messages)
    location = None
    job_type = None
    materials = []
    notes = []
    job_dt = None
    job_time = None
    last_ts = None
    for m in messages:
        text = m.get("text") or ""
        if not text.strip(): continue
        last_ts = datetime.fromisoformat(m["timestamp"])
        loc = find_address(text)
        if loc: location = loc
        jt = extract_job_type(text)
        if jt: job_type = jt
        for it in extract_materials(text):
            if it not in materials: materials.append(it)
        absd = parse_absolute_date(text)
        if absd:
            if absd.year == 1900: absd = absd.replace(year=last_ts.year)
            job_dt = absd
        reld = resolve_relative_date(text, last_ts)
        if isinstance(reld, datetime):
            job_dt = reld
        elif reld:  # date object
            job_dt = datetime.combine(reld, time(9, 0))
        tm = extract_time(text)
        if tm: job_time = tm
        if any(k in text.lower() for k in ["note", "gate", "parking", "buzzer", "unit", "floor"]):
            notes.append(text.strip())
    if job_dt is None and last_ts is not None:
        job_dt = (last_ts + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    if job_time and job_dt: job_dt = job_dt.replace(hour=job_time[0], minute=job_time[1])
    base = {
        "job_id": messages[0]["chat_id"],
        "chat_id": messages[0]["chat_id"],
        "customer_name": customer,
        "job_date_start": job_dt.isoformat() if job_dt else None,
        "job_date_end": None,
        "location": location,
        "job_type": job_type or "OTHER",
        "materials_required": materials,
        "confidence": 0.6 if any([customer, location, job_type, materials]) else 0.3,
        "notes": "; ".join(notes)[:400] if notes else None,
        "source_msg_ids": [m["message_id"] for m in messages[-10:]],
    }
    return base


# ---------- Ollama ----------
def ollama_chat(model: str, system: str, user: str, temperature: float = 0.0) -> str:
    url = "http://localhost:11434/api/chat"
    payload = {"model": model, "options": {"temperature": temperature},
               "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
               "stream": False}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        obj = json.loads(resp.read().decode("utf-8"))
        return obj.get("message", {}).get("content", "")


ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?)?$")


def coerce_job(job: Dict[str, Any], chat_id: str) -> Dict[str, Any]:
    out = {"job_id": job.get("job_id") or chat_id, "chat_id": job.get("chat_id") or chat_id,
           "customer_name": job.get("customer_name"), "job_date_start": job.get("job_date_start"),
           "job_date_end": job.get("job_date_end"), "location": job.get("location"),
           "job_type": job.get("job_type") or "OTHER", "materials_required": job.get("materials_required") or [],
           "confidence": float(job.get("confidence") or 0.0), "notes": job.get("notes"),
           "source_msg_ids": job.get("source_msg_ids") or []}
    for k in ("job_date_start", "job_date_end"):
        v = out.get(k)
        if isinstance(v, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            out[k] = v + "T09:00:00"
        elif v and (not isinstance(v, str) or not ISO_DATE_RE.match(v)):
            out[k] = None
    if not isinstance(out["materials_required"], list): out["materials_required"] = []
    out["confidence"] = round(max(0.0, min(0.99, out["confidence"])), 2)
    return out


SCHEMA = """Return ONLY a single JSON object exactly like:
{
  "job_id":"string",
  "chat_id":"string",
  "customer_name":"string|null",
  "job_date_start":"YYYY-MM-DDThh:mm[:ss]|null",
  "job_date_end":"YYYY-MM-DDThh:mm[:ss]|null",
  "location":"string|null",
  "job_type":"string",
  "materials_required":["string",...],
  "confidence":0.0,
  "notes":"string|null",
  "source_msg_ids":["string",...]
}
No markdown. No extra keys. JSON only.
"""

SYSTEM = "You are a precise information extractor for trades jobs. Respect the schema exactly. Temperature is zero."

USER_TMPL = """CHAT_ID: {chat_id}

DRAFT (prefilled by rules):
{draft_json}

Your task:
- Read the DRAFT and the MESSAGES.
- Correct/complete the fields using the conversation.
- Resolve relative dates (e.g., "Friday") relative to each message's timestamp.
- Use canonical job types like:
  Toilet replacement/repair, Sink install/repair, Faucet install/repair, Leak diagnosis/repair,
  Drain clear/repair, Water heater service, Boiler service, Roof leak/repair, Shingle repair,
  Furnace service, AC service, Electrical outlet, Light switch, Electrical panel, or "OTHER".

Return JSON in the EXACT schema below.

SCHEMA:
{schema}

MESSAGES (last ~60):
{chat}
"""


def compact_messages(messages: List[Dict[str, Any]]) -> str:
    last = messages[-60:] if len(messages) > 60 else messages
    lines = []
    budget = 12000
    for m in last:
        line = f'[{m.get("timestamp", "")}] {(m.get("sender") or "System")}: {(m.get("text") or "").replace("\\n", " ").strip()}'
        if len("\n".join(lines)) + len(line) > budget: break
        lines.append(line)
    return "\n".join(lines)


def ask_llm_with_retries(model: str, sys_prompt: str, user_prompt: str, max_tries: int = 3) -> Optional[Dict[str, Any]]:
    content = ""
    for attempt in range(1, max_tries + 1):
        content = ollama_chat(model=model, system=sys_prompt, user=user_prompt, temperature=0.0).strip()
        # strip accidental fences
        if content.startswith("```"):
            content = re.sub(r"^```[a-zA-Z0-9]*\s*", "", content)
            content = re.sub(r"\s*```$", "", content)
        try:
            return json.loads(content)
        except Exception:
            if attempt == max_tries: return None
    return None


# ---------- Main ----------
def main():
    ap = argparse.ArgumentParser(description="Hybrid AI extractor (rules + Ollama) for WhatsApp jobs.")
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", dest="out_jsonl", required=True)
    ap.add_argument("--csv", dest="out_csv")
    ap.add_argument("--model", default="llama3.1:8b-instruct")
    args = ap.parse_args()

    inp = Path(args.inp)
    out_jsonl = Path(args.out_jsonl)
    out_csv = Path(args.out_csv) if args.out_csv else out_jsonl.with_suffix(".csv")
    groups = group_by_chat(read_messages(inp))

    jobs = []
    for chat_id, msgs in groups.items():
        draft = rule_prefill(msgs)
        chat_text = compact_messages(msgs)
        user = USER_TMPL.format(chat_id=chat_id, draft_json=json.dumps(draft, ensure_ascii=False, indent=2),
                                schema=SCHEMA, chat=chat_text)
        parsed = ask_llm_with_retries(args.model, SYSTEM, user, max_tries=3)
        job = coerce_job(parsed if parsed else draft, chat_id)
        # ensure linkage
        if not job.get("source_msg_ids"): job["source_msg_ids"] = [m["message_id"] for m in msgs[-10:]]
        # nudge confidence up if AI succeeded
        if parsed: job["confidence"] = max(job["confidence"], 0.8)
        jobs.append(job)

    write_outputs(jobs, out_jsonl, out_csv)
    print(f"Wrote {len(jobs)} jobs -> {out_jsonl} and {out_csv}")


if __name__ == "__main__":
    main()
