🧰 BuildSafe AI – WhatsApp Job Extractor

A local-first AI-powered tool that converts WhatsApp chat exports into structured job data for trades workers.

🚀 Overview

This project ingests a WhatsApp .zip export (from the official chat export feature), extracts messages, and uses a local LLM (via Ollama
) to automatically identify key details such as:

Customer name

Date & time of job

Job type

Location

Materials required

Confidence score

The extracted data is displayed in a web dashboard and can be exported to .csv or .jsonl formats.

🏗️ Architecture

Phase 1 – WhatsApp ZIP → JSONL

whatsapp_zip_to_jsonl.py parses the exported WhatsApp ZIP and outputs normalized messages:

{"chat_id": "chat_123", "timestamp": "2024-12-31T14:37:00", "sender": "John Doe", "text": "Toilet replacement"}


Phase 2 – JSONL → AI Extraction

extract_jobs_with_ai.py uses an Ollama model (e.g. phi3.5) to identify and structure job details.

Combines rule-based parsing + AI extraction for reliability and speed.

Phase 3 – Web UI

app.py provides a simple Flask interface for:

Uploading WhatsApp ZIPs

Automatically running Phases 1 & 2

Viewing and downloading structured outputs

🧩 Requirements

Python 3.10+

Pip packages:

pip install flask


Ollama (Local LLM runtime)

Download at ollama.ai/download

Run in background:

ollama serve


Pull the model (recommended lightweight one):

ollama pull phi3.5

🖥️ Local Development

Clone or open project

cd "C:\Users\User\PycharmProjects\whatsapp erp"


Run Flask UI

python app.py


Visit http://127.0.0.1:5000

Upload your WhatsApp .zip file
The app will:

Parse ZIP → messages JSONL

Extract job info using phi3.5

Show results in a table

Offer .csv and .jsonl download links

📂 File Structure
whatsapp-erp/
│
├── app.py                      # Flask web interface
├── whatsapp_zip_to_jsonl.py    # Phase 1: ZIP → JSONL extractor
├── extract_jobs_with_ai.py     # Phase 2: AI extractor (Ollama-based)
│
├── templates/                  # (optional future HTML files)
├── static/                     # (optional CSS/JS files)
│
└── README.md

⚙️ Configuration

Edit these lines at the top of app.py if needed:

PHASE1_SCRIPT = "whatsapp_zip_to_jsonl.py"
PHASE2_SCRIPT = "extract_jobs_with_ai.py"
DEFAULT_TZ = "America/Toronto"
OLLAMA_MODEL = "phi3.5"


Or use absolute paths if your scripts live elsewhere.

✅ Example Output (CSV)
Customer	Date	Location	Job Type	Materials	Confidence	Notes
John Doe	2024-12-31T09:00:00	12 King St, Toronto	Toilet replacement	wax ring, bolts	0.88	Confirmed Friday
🧠 Debugging Tips
Issue	Fix
File not found errors	Make sure both scripts are in the same directory as app.py.
UnicodeEncodeError	Replace fancy Unicode arrows (→) in prints with ASCII (->).
Ollama connection error	Start Ollama via ollama serve.
Model not found	Run ollama pull phi3.5.
Empty CSV	Test with more detailed WhatsApp data — short chats may not trigger the AI parser.
🔐 Next Steps (Production Upgrade Roadmap)

Planned Phase 4 Goals:

Add user authentication (JWT or OAuth)

Support multi-tenant data isolation (Postgres + RLS)

Move inference to serverless (AWS Lambda + ECS Ollama container)

Enforce secure S3 storage + encryption at rest

Validate against data protection standards (PII minimization, retention, encryption)

Implement per-message extraction + deduplication
