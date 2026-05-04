# BuildSafe AI — Privacy-First Operating Layer for Trades

BuildSafe AI converts messy WhatsApp conversations **and media evidence** into structured job intelligence for trades teams.

## Core product loop (kept and extended)
1. WhatsApp ZIP import
2. `whatsapp_zip_to_jsonl.py` parses normalized messages **and discovers media assets**
3. `extract_jobs_with_ai.py` runs the existing Ollama-first text/business extraction
4. Optional SmolVLM2 media analysis runs second (images/videos only)
5. Final Ollama fusion pass enriches the job with visual evidence
6. `app.py` shows multi-job operating dashboard and exports CSV/JSONL

## Privacy-first local architecture
- **Ollama** remains the main local reasoning engine for business decisions.
- **SmolVLM2** is used only for visual observations from image/video.
- No cloud LLM is required.
- Customer messages/media can remain local.

## Multimodal design principle
SmolVLM2 does **not** make final business decisions.
It outputs observational visual evidence only:
- visual observations
- media summary
- follow-up visual questions

Then Ollama fuses:
- prior text job context
- conversation snippet
- visual observations
into final job intelligence.

## Vision model and fallback
Default model:
- `HuggingFaceTB/SmolVLM2-500M-Video-Instruct`

Analyzers:
- `SmolVLMVisionAnalyzer` (real model, optional)
- `MockVisionAnalyzer` (reliable fallback for demos)

Config flags (env vars):
- `ENABLE_VISION_ANALYSIS=1|0`
- `VISION_ANALYZER_MODE=auto|smolvlm|mock`
- `DEFAULT_VISION_MODEL=HuggingFaceTB/SmolVLM2-500M-Video-Instruct`

Behavior:
- `auto`: try SmolVLM path; if unavailable, fallback to mock
- `smolvlm`: try real model; fail gracefully
- `mock`: deterministic demo-safe visual observations

## Media ingestion and support
Detected media types in ZIP:
- Images: `.jpg .jpeg .png .webp`
- Videos: `.mp4 .mov .m4v`
- Audio placeholder: `.ogg .opus .m4a .mp3 .wav`
- Documents: `.pdf`

Normalized media objects are emitted with:
- media metadata
- local extracted path
- frame extraction fields for video
- analysis status

## New enriched fields in final job object
- `media_assets`
- `visual_observations`
- `media_summary`
- `media_followup_questions`
- `evidence_mode` (`text_only | text_image | text_video | multimodal`)
- `vision_analysis_mode` (`mock | smolvlm | skipped | failed`)

## Dashboard multimodal evidence
Each job card now includes:
- evidence mode
- media file list
- media summary
- visual observations
- media follow-up questions
- source evidence snippets and source message IDs

## Run locally
```bash
pip install -r requirements.txt
ollama serve
ollama pull phi3.5
python app.py
```
Open: `http://127.0.0.1:5000`

## 60-second multimodal demo
1. Start app and click **Run 60-Second Demo**.
2. Upload a WhatsApp ZIP containing text + media files (images/video) to see multimodal evidence mode.
3. Show: text reasoning (Ollama), visual observations (SmolVLM/mock), and final fused job actions.

## Smoke test
```bash
python tests/smoke_demo_pipeline.py
```

## Roadmap
- Live WhatsApp/Twilio ingestion
- Quote generation workflow
- Scheduling readiness workflows
- Material planning depth
- Job costing loop
- FSM/ERP/CRM integrations
