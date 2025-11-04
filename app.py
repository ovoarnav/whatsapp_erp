#!/usr/bin/env python3
import sys, csv, tempfile, subprocess, uuid
from pathlib import Path
from flask import Flask, request, render_template_string, send_file, redirect, url_for, flash
from typing import Any, Dict, List, Mapping, cast

# --- CONFIG ---
# Adjust these if your script filenames differ:
PHASE1_SCRIPT = "whatsapp_zip_to_jsonl.py"
PHASE2_SCRIPT = "extract_jobs_with_ai.py"  # or "extract_jobs_with_ai_hybrid.py"
DEFAULT_TZ = "America/Toronto"
OLLAMA_MODEL = "phi3.5"  # or "llama3.1:8b-instruct"

ALLOWED_EXTS = {".zip"}

app = Flask(__name__)
app.secret_key = "dev"  # for flash messages

TEMPLATE = r"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>BuildSafe | WhatsApp → Jobs</title>
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 2rem; }
    .card { max-width: 900px; margin: 0 auto; background: #fff; border: 1px solid #e5e7eb; border-radius: 14px; padding: 1.5rem; box-shadow: 0 4px 16px rgba(0,0,0,0.05); }
    h1 { margin-top: 0; font-size: 1.4rem; }
    .row { margin: 0.5rem 0; }
    .muted { color: #6b7280; }
    input[type=file] { padding: 0.6rem; border: 1px solid #d1d5db; border-radius: 10px; width: 100%; }
    button { padding: 0.6rem 1rem; border: 0; background: #111827; color: white; border-radius: 10px; cursor: pointer; }
    button:hover { opacity: 0.9; }
    table { border-collapse: collapse; width: 100%; margin-top: 1rem; }
    th, td { text-align: left; border-bottom: 1px solid #e5e7eb; padding: 8px; font-size: 0.95rem; vertical-align: top; }
    .pill { display: inline-block; padding: 2px 8px; border-radius: 999px; background: #eef2ff; color: #3730a3; margin-right: 4px; margin-bottom: 4px; }
    .links a { margin-right: 12px; }
    .flash { color: #b91c1c; margin-bottom: 0.5rem; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
  </style>
</head>
<body>
  <div class="card">
    <h1>BuildSafe – WhatsApp ZIP → Structured Jobs (Local)</h1>
    {% with messages = get_flashed_messages() %}
      {% if messages %}
        {% for m in messages %}<div class="flash">{{ m }}</div>{% endfor %}
      {% endif %}
    {% endwith %}
    <form action="{{ url_for('process') }}" method="post" enctype="multipart/form-data">
      <div class="row"><strong>Upload WhatsApp export (.zip)</strong></div>
      <div class="row"><input type="file" name="zipfile" required></div>
      <div class="grid">
        <div>
          <label class="muted">Timezone (IANA)</label>
          <input type="text" name="tz" value="{{ tz }}" style="width:100%;padding:0.5rem;border:1px solid #d1d5db;border-radius:10px">
        </div>
        <div>
          <label class="muted">Ollama model</label>
          <input type="text" name="model" value="{{ model }}" style="width:100%;padding:0.5rem;border:1px solid #d1d5db;border-radius:10px">
        </div>
      </div>
      <div class="row"><button type="submit">Run Extraction</button></div>
      <p class="muted">Tip: make sure the Ollama app is open and <code>ollama pull {{ model }}</code> has been run at least once.</p>
    </form>

    {% if csv_rows %}
      <hr style="margin: 1.5rem 0; border: 0; border-top: 1px solid #e5e7eb;">
      <div class="links">
        <a href="{{ url_for('download', kind='jsonl', token=token) }}">Download jobs.jsonl</a>
        <a href="{{ url_for('download', kind='csv', token=token) }}">Download jobs.csv</a>
      </div>
      <h2>Extracted Jobs</h2>
      <table>
        <thead>
          <tr>
            <th>Customer</th>
            <th>Date (start)</th>
            <th>Location</th>
            <th>Job Type</th>
            <th>Materials</th>
            <th>Confidence</th>
            <th>Notes</th>
          </tr>
        </thead>
        <tbody>
          {% for r in csv_rows %}
            <tr>
              <td>{{ r.get('customer_name') or '' }}</td>
              <td>{{ r.get('job_date_start') or '' }}</td>
              <td>{{ r.get('location') or r.get('location_raw') or '' }}</td>
              <td>{{ r.get('job_type') or '' }}</td>
              <td>
                {% if r.get('materials_required') %}
                  {% for it in (r.get('materials_required') or '').split(',') %}
                    {% if it.strip() %}<span class="pill">{{ it.strip() }}</span>{% endif %}
                  {% endfor %}
                {% endif %}
              </td>
              <td>{{ r.get('confidence') or '' }}</td>
              <td style="max-width:260px">{{ r.get('notes') or '' }}</td>
            </tr>
          {% endfor %}
        </tbody>
      </table>
    {% endif %}
  </div>
</body>
</html>
"""


def _run(cmd: list[str], cwd: Path | None = None):
    # Run a subprocess and raise if it fails; capture output for debugging.
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed:\n{' '.join(cmd)}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    return proc.stdout


def _read_csv_rows(csv_path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)  # yields Mapping[str, str]-like rows
        for r in reader:
            r_map: Mapping[str, str] = cast(Mapping[str, str], r)
            row: Dict[str, Any] = {k: v for k, v in r_map.items()}  # materialize a plain dict
            # keep materials_required as a comma-joined string; template already splits on commas
            rows.append(row)
    return rows


@app.route("/", methods=["GET"])
def index():
    return render_template_string(TEMPLATE, tz=DEFAULT_TZ, model=OLLAMA_MODEL, csv_rows=None, token=None)


@app.route("/process", methods=["POST"])
def process():
    file = request.files.get("zipfile")
    tz = request.form.get("tz") or DEFAULT_TZ
    model = request.form.get("model") or OLLAMA_MODEL

    if not file or file.filename == "":
        flash("Please choose a .zip file.")
        return redirect(url_for("index"))

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTS:
        flash("Only .zip files are allowed.")
        return redirect(url_for("index"))

    token = uuid.uuid4().hex[:12]
    workdir = Path(tempfile.gettempdir()) / f"buildsafe_{token}"
    workdir.mkdir(parents=True, exist_ok=True)

    zip_path = workdir / "upload.zip"
    msgs_path = workdir / "messages.jsonl"
    jobs_jsonl = workdir / "jobs.jsonl"
    jobs_csv = workdir / "jobs.csv"

    file.save(str(zip_path))

    try:
        # Phase 1
        _run([sys.executable, PHASE1_SCRIPT,
              "--zip", str(zip_path),
              "--out", str(msgs_path),
              "--tz", tz],
             cwd=Path.cwd())

        # Phase 2 (AI)
        _run([sys.executable, PHASE2_SCRIPT,
              "--in", str(msgs_path),
              "--out", str(jobs_jsonl),
              "--csv", str(jobs_csv),
              "--model", model],
             cwd=Path.cwd())

        rows = _read_csv_rows(jobs_csv)
        return render_template_string(TEMPLATE, tz=tz, model=model, csv_rows=rows, token=token)

    except Exception as e:
        # Show clean error, keep temp folder for inspection
        flash(str(e))
        return redirect(url_for("index"))


@app.route("/download/<kind>/<token>", methods=["GET"])
def download(kind: str, token: str):
    base = Path(tempfile.gettempdir()) / f"buildsafe_{token}"
    if kind == "jsonl":
        path = base / "jobs.jsonl"
    elif kind == "csv":
        path = base / "jobs.csv"
    else:
        return "Not found", 404
    if not path.exists():
        return "Not found", 404
    return send_file(str(path), as_attachment=True, download_name=path.name)


if __name__ == "__main__":
    # Let you run: python app.py
    app.run(host="127.0.0.1", port=5000, debug=True)
