#!/usr/bin/env python3
import json
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from flask import Flask, flash, redirect, render_template_string, request, send_file, url_for

PHASE1_SCRIPT = "whatsapp_zip_to_jsonl.py"
PHASE2_SCRIPT = "extract_jobs_with_ai.py"
DEFAULT_TZ = "America/Toronto"
OLLAMA_MODEL = "phi3.5"
ALLOWED_EXTS = {".zip"}

app = Flask(__name__)
app.secret_key = "dev"


def pretty_status(value: str) -> str:
    return (value or "").replace("_", " ").title()


def pretty_risk(value: str) -> str:
    return (value or "none").replace("_", " ")


TEMPLATE = """
<!doctype html><html><head><meta charset="utf-8"><title>BuildSafe AI</title>
<style>
body{font-family:system-ui;margin:0;background:#f8fafc;color:#111827}.wrap{max-width:1220px;margin:auto;padding:1rem}.card{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:1rem;margin-bottom:1rem}
.hero{background:#0f172a;color:#fff}.hero h1{margin:.1rem 0}.hero p{margin:.45rem 0}.sub{color:#cbd5e1}.flow{font-weight:700;color:#93c5fd}
.formline{display:flex;gap:.5rem;flex-wrap:wrap;align-items:center}input,button,a.btn{padding:.55rem .7rem;border:1px solid #d1d5db;border-radius:8px;text-decoration:none}button,.btn.primary{background:#111827;color:#fff;border-color:#111827}.btn{color:#111827;background:#fff}
.kpi{display:grid;grid-template-columns:repeat(7,1fr);gap:.5rem}.k{background:#111827;color:#fff;padding:.6rem;border-radius:10px}.k b{display:block;font-size:1.25rem}
table{width:100%;border-collapse:collapse}th,td{border-bottom:1px solid #e5e7eb;padding:8px;font-size:.9rem;vertical-align:top}th{background:#f8fafc;position:sticky;top:0}
.badge{padding:2px 8px;border-radius:999px;font-size:.8rem;font-weight:600;display:inline-block}.high{background:#fecaca}.medium{background:#fde68a}.low{background:#bbf7d0}
.inspection_required{background:#fecaca}.needs_info{background:#fde68a}.ready_to_quote{background:#bbf7d0}.blocked{background:#fdba74}.completed{background:#d1d5db}.new_lead{background:#e5e7eb}
.grid2{display:grid;grid-template-columns:1.1fr 1fr;gap:1rem}.muted{color:#6b7280}.next{font-weight:700}.flash{color:#b91c1c;margin:.4rem 0}
pre{white-space:pre-wrap;background:#f8fafc;padding:.6rem;border-radius:8px;margin:.35rem 0}
</style></head><body><div class="wrap">
<div class="card hero">
  <h1>BuildSafe AI — Privacy-First WhatsApp Operating Layer for Trades</h1>
  <p class="flow">WhatsApp conversations → structured job intelligence → quote/material/risk/action dashboard.</p>
  <p class="sub">Runs locally with Ollama for business reasoning + optional local SmolVLM2 for media analysis. No cloud LLM required.</p>
  {% with messages = get_flashed_messages() %}{% for m in messages %}<div class="flash">{{m}}</div>{% endfor %}{% endwith %}
  <form action="{{url_for('process')}}" method="post" enctype="multipart/form-data" class="formline">
    <input type="file" name="zipfile" required>
    <input name="tz" value="{{tz}}" title="Timezone">
    <input name="model" value="{{model}}" title="Ollama model">
    <button type="submit">Run Intake Analysis</button>
    <a class="btn primary" href="{{url_for('use_demo')}}">Run 60-Second Demo</a>
  </form>
  <p class="sub">Demo path: Click <b>Run 60-Second Demo</b> to load 5 trade leads with urgency, risk, and quote-readiness differences.</p>
</div>

{% if jobs %}
<div class="card"><div class="kpi">{% for k,v in kpis.items() %}<div class="k">{{k}}<b>{{v}}</b></div>{% endfor %}</div></div>
<div class="card">
  <h3 style="margin-top:0">Operating Queue</h3>
  <table><tr><th>Customer</th><th>Trade</th><th>Job Type</th><th>Location</th><th>Status</th><th>Urgency</th><th>Quote Readiness</th><th>Risk</th><th>Top Risk</th><th>Next Action</th></tr>
  {% for j in jobs %}<tr>
    <td>{{j.customer_name or 'Unknown'}}</td><td>{{j.trade_category}}</td><td>{{j.job_type}}</td><td>{{j.location or 'Missing'}}</td>
    <td><span class="badge {{j.job_status}}">{{pretty_status(j.job_status)}}</span></td>
    <td><span class="badge {{j.urgency}}">{{j.urgency.title()}}</span></td>
    <td><b>{{pretty_status(j.quote_readiness.status)}}</b><br><span class="muted">Score {{j.quote_readiness.score}}</span></td>
    <td>{{j.risk_flags|length}}</td>
    <td>{{pretty_risk(j.risk_flags[0].type if j.risk_flags else 'none')}}</td>
    <td class="next">{{j.recommended_actions[0].action if j.recommended_actions else 'Review lead'}}</td>
  </tr>{% endfor %}</table>
</div>

{% for j in jobs %}<div class="card grid2">
  <div>
    <h3 style="margin-top:0">{{j.customer_name or j.chat_id}} — {{pretty_status(j.job_status)}}</h3>
    <p>{{j.operator_summary}}</p>
    <p><b>Primary Next Action:</b> {{j.recommended_actions[0].action if j.recommended_actions else 'Review lead'}} <span class="muted">({{j.recommended_actions[0].owner if j.recommended_actions else 'contractor'}})</span></p>
    <b>Missing Quote Inputs</b><pre>{{j.quote_readiness.missing_quote_inputs}}</pre>
    <b>Customer Reply Draft</b><pre>{{j.customer_reply_draft}}</pre>
  </div>
  <div>
    <b>Risk Flags</b><pre>{{j.risk_flags}}</pre>
    <b>Materials Intelligence</b><pre>{{j.materials_intelligence}}</pre>
    <b>Recommended Actions</b><pre>{{j.recommended_actions}}</pre>
    <b>Source Evidence</b><pre>
Risk evidence: {{ j.risk_flags | map(attribute='evidence_snippet') | list if j.risk_flags else [] }}
Missing input evidence: {{ j.quote_readiness.missing_quote_input_evidence if j.quote_readiness else [] }}
Action evidence: {{ j.recommended_actions | map(attribute='evidence_snippet') | list if j.recommended_actions else [] }}
Source message IDs: {{ j.source_msg_ids }}
</pre>
    <b>Multimodal Evidence</b><pre>Evidence mode: {{ j.evidence_mode }}
Vision analyzer mode: {{ j.vision_analysis_mode }}
Media assets: {{ j.media_assets }}
Media summary: {{ j.media_summary }}
Visual observations: {{ j.visual_observations }}
Media follow-up questions: {{ j.media_followup_questions }}
</pre>
  </div>
</div>{% endfor %}

<div class="card"><a href="{{ url_for('download', kind='jsonl', token=token) }}">Download jobs.jsonl</a> | <a href="{{ url_for('download', kind='csv', token=token) }}">Download jobs.csv</a></div>
{% endif %}
</div></body></html>
"""


def run_pipeline(zip_path: Path, tz: str, model: str, token: str):
    workdir = Path(tempfile.gettempdir()) / f"buildsafe_{token}"
    workdir.mkdir(parents=True, exist_ok=True)
    msgs_path = workdir / "messages.jsonl"
    media_jsonl = workdir / "media_assets.jsonl"
    jobs_jsonl = workdir / "jobs.jsonl"
    jobs_csv = workdir / "jobs.csv"

    for cmd in (
        [sys.executable, PHASE1_SCRIPT, "--zip", str(zip_path), "--out", str(msgs_path), "--tz", tz, "--media-out", str(media_jsonl)],
        [sys.executable, PHASE2_SCRIPT, "--in", str(msgs_path), "--out", str(jobs_jsonl), "--csv", str(jobs_csv), "--model", model, "--media", str(media_jsonl)],
    ):
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr or proc.stdout)

    jobs = []
    with jobs_jsonl.open("r", encoding="utf-8") as f:
        for line in f:
            jobs.append(json.loads(line))
    return jobs


def render(jobs, tz, model, token):
    kpis = {
        "Total Jobs": len(jobs),
        "High Urgency": sum(j["urgency"] == "high" for j in jobs),
        "Needs Info": sum(j["job_status"] == "needs_info" for j in jobs),
        "Inspection Required": sum(j["job_status"] == "inspection_required" for j in jobs),
        "Ready to Quote": sum(j["job_status"] == "ready_to_quote" for j in jobs),
        "Blocked Jobs": sum(j["job_status"] == "blocked" for j in jobs),
        "Material Risk": sum(j["materials_intelligence"]["purchase_risk"] == "high" for j in jobs),
    }
    return render_template_string(TEMPLATE, tz=tz, model=model, jobs=jobs, kpis=kpis, token=token, pretty_status=pretty_status, pretty_risk=pretty_risk)


@app.get("/")
def index():
    return render_template_string(TEMPLATE, tz=DEFAULT_TZ, model=OLLAMA_MODEL, jobs=None, kpis={}, token=None, pretty_status=pretty_status, pretty_risk=pretty_risk)


@app.post("/process")
def process():
    file = request.files.get("zipfile")
    tz = request.form.get("tz") or DEFAULT_TZ
    model = request.form.get("model") or OLLAMA_MODEL
    if not file or Path(file.filename).suffix.lower() not in ALLOWED_EXTS:
        flash("Upload a valid .zip file from official WhatsApp export.")
        return redirect(url_for("index"))

    token = uuid.uuid4().hex[:12]
    zip_path = Path(tempfile.gettempdir()) / f"upload_{token}.zip"
    file.save(str(zip_path))

    try:
        jobs = run_pipeline(zip_path, tz, model, token)
        return render(jobs, tz, model, token)
    except Exception as exc:
        flash(f"Pipeline failed. If Ollama is not running, start it with `ollama serve`. Details: {exc}")
        return redirect(url_for("index"))


@app.get("/use_demo")
def use_demo():
    token = uuid.uuid4().hex[:12]
    demo_zip = Path("demo_data/demo_whatsapp_export.zip")
    try:
        if not demo_zip.exists():
            subprocess.run([sys.executable, "demo_data/generate_demo_zip.py"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        jobs = run_pipeline(demo_zip, DEFAULT_TZ, OLLAMA_MODEL, token)
        return render(jobs, DEFAULT_TZ, OLLAMA_MODEL, token)
    except Exception as exc:
        flash(str(exc))
        return redirect(url_for("index"))


@app.get("/download/<kind>/<token>")
def download(kind, token):
    base = Path(tempfile.gettempdir()) / f"buildsafe_{token}"
    path = base / ("jobs.jsonl" if kind == "jsonl" else "jobs.csv")
    if not path.exists():
        return "Not found", 404
    return send_file(path, as_attachment=True, download_name=path.name)


if __name__ == "__main__":
    app.run(debug=True)
