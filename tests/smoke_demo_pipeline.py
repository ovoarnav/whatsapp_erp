#!/usr/bin/env python3
import json, subprocess, sys
from pathlib import Path

subprocess.run([sys.executable, "demo_data/generate_demo_zip.py"], check=True)
subprocess.run([sys.executable, "whatsapp_zip_to_jsonl.py", "--zip", "demo_data/demo_whatsapp_export.zip", "--out", "/tmp/smoke_msgs.jsonl", "--tz", "America/Toronto", "--media-out", "/tmp/smoke_media.jsonl"], check=True)
subprocess.run([sys.executable, "extract_jobs_with_ai.py", "--in", "/tmp/smoke_msgs.jsonl", "--out", "/tmp/smoke_jobs.jsonl", "--csv", "/tmp/smoke_jobs.csv", "--model", "phi3.5", "--media", "/tmp/smoke_media.jsonl"], check=True)

jobs=[json.loads(x) for x in Path('/tmp/smoke_jobs.jsonl').read_text(encoding='utf-8').splitlines() if x.strip()]
assert len(jobs) >= 5
for j in jobs:
    assert j.get('job_status')
    assert j.get('urgency') in {'low','medium','high'}
    qr=j.get('quote_readiness') or {}
    assert qr.get('status') in {'not_ready','partially_ready','ready'}
    assert isinstance(qr.get('score'), (int,float))
    assert isinstance(j.get('recommended_actions'), list) and len(j['recommended_actions']) >= 1
    assert isinstance(j.get('operator_summary'), str) and len(j['operator_summary'].strip()) > 10
    assert j.get('privacy_mode') == 'local_ollama'
    assert j.get('evidence_mode') in {'text_only', 'text_image', 'text_video', 'multimodal'}
print('Smoke test passed:', len(jobs), 'jobs')
