# CASM - Construction-Site AI Safety Monitor

CASM is a full-stack AI safety compliance platform for construction sites. It monitors camera feeds, detects PPE violations with a YOLO-based vision pipeline, generates AI-assisted incident reports, and gives safety officers a browser dashboard for live monitoring, report review, analytics, notifications, and device administration.

This repository is the Final Year Project A codebase for AI Model Development and Integration.

## Live Access

- Main prototype: https://fypa-ai-model-development-integrati.vercel.app
- Admin/device portal: https://fypa-ai-model-development-integrati.vercel.app/admin/devices
- Main application code: `Updated_Pipeline_Supabase/`

The deployed prototype is the fastest way to review the system. Use a local installation when you need to connect your own webcam or RealSense camera, run offline/local mode, or develop the code.

## What CASM Does

- Live PPE monitoring from webcam, RealSense relay, or configured camera sources.
- YOLO detection for hard hat/helmet, safety vest, safety boots, respirator mask, person count, and related PPE classes.
- Violation logging with severity, timestamps, source metadata, and image evidence.
- AI report generation through cloud Gemini mode or local Ollama/Gemma mode.
- Supabase-backed cloud storage for reports, private images, signed URLs, realtime state, and device provisioning.
- Local/offline mode with filesystem persistence and later cloud sync.
- Mira AI Safety Copilot for natural-language help, system questions, report summaries, and guided actions.
- Admin portal for device approval, rejection, revocation, one-time installer issuing, and audit log review.

## Technology Stack

| Layer | Implementation |
| --- | --- |
| Frontend UI | Static HTML/CSS/vanilla JavaScript SPA in `Updated_Pipeline_Supabase/frontend/` |
| Backend API | Python Flask application in `Updated_Pipeline_Supabase/casm_app.py` |
| Detection | Ultralytics YOLO/PyTorch using weights under `Updated_Pipeline_Supabase/Results/` |
| Cloud data | Supabase Postgres, Storage, and signed URLs |
| Cloud deployment | Vercel frontend and Railway backend |
| Local AI mode | Ollama with `gemma3:4b` by default |
| Cloud AI mode | Gemini models configured through environment variables |
| Validation | Python, JavaScript, Playwright/Selenium-style contract tests under `Updated_Pipeline_Supabase/tests/` |

## Repository Layout

```text
FYPA_AI_Model_Development-Integration/
|-- README.md                         # This outer project guide
|-- MARKDOWN/                         # Historical setup, migration, and audit notes
|-- Updated_Pipeline_Supabase/         # Main CASM application
|   |-- casm_app.py                    # Unified Flask server and API entry point
|   |-- frontend/                      # Static SPA served locally or deployed to Vercel
|   |-- pipeline/backend/core/         # Detection, queue, storage, report, and Supabase core modules
|   |-- pipeline/backend/integration/  # Gemini, caption, and local LLM integration helpers
|   |-- scripts/                       # Operational scripts for queue/reprocess/relay tasks
|   |-- setup/                         # Provisioning, migration, and model setup helpers
|   |-- tests/                         # Contract, deployed, local, and browser validation tests
|   |-- requirements.txt               # Python dependencies
|   |-- start.bat / start.sh           # Local startup helpers
|   `-- README.md                      # Detailed Supabase/backend deployment notes
```

## Using The Deployed Prototype

1. Open https://fypa-ai-model-development-integrati.vercel.app.
2. Use the sidebar to navigate Home, Live Monitor, Reports, Analytics, About, Settings, and Handbook.
3. Use Mira from the dashboard/chat panel for report questions, system guidance, and export help.
4. Open the admin portal directly at `/admin/devices` only if you have Basic Auth credentials from the deployment owner.

The deployed prototype uses a shared cloud backend. To test with your own camera hardware, run CASM locally.

## Local Installation

### Prerequisites

- Python 3.10 or later.
- Git.
- A webcam or RealSense camera for live detection.
- Supabase project credentials for cloud mode.
- Ollama for local/offline AI report generation.
- Docker is optional.

### Start From Source

```powershell
git clone https://github.com/FrankieLingIsHere/FYPA_AI_Model_Development-Integration.git
cd FYPA_AI_Model_Development-Integration\Updated_Pipeline_Supabase

py -3 -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt

copy .env.example .env
python casm_app.py
```

Open http://localhost:5000 after the Flask server starts.

You can also use:

```powershell
.\start.bat
```

On Linux/macOS:

```bash
cd Updated_Pipeline_Supabase
./start.sh
```

## Environment Modes

### Cloud Mode

Cloud mode stores detection events, reports, and images in Supabase. Configure these in `Updated_Pipeline_Supabase/.env`:

```env
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
SUPABASE_DB_URL=postgresql://postgres:password@db.your-project-id.supabase.co:5432/postgres
SUPABASE_IMAGES_BUCKET=violation-images
SUPABASE_REPORTS_BUCKET=reports
GEMINI_API_KEY=your-google-ai-key
CASM_ROUTING_PROFILE=cloud
```

Use the SQL files in `Updated_Pipeline_Supabase/pipeline/supabase_schema.sql` and `Updated_Pipeline_Supabase/docs/SUPABASE_PROVISIONING_STATE_SCHEMA.sql` to create or verify the Supabase schema.

### Local/Offline Mode

Local mode keeps data on the workstation and uses Ollama for local AI generation.

```powershell
ollama pull gemma3:4b
ollama serve
```

Then open CASM, go to Settings, switch to Local Mode, and run the Local Mode Checkup. If provisioning is pending, request provisioning and wait for admin approval from the Admin Portal.

## Navigation Guide

| Area | Purpose |
| --- | --- |
| Home | Operational dashboard, recent violations, stats, and Mira assistant |
| Live Monitor | Camera source selection, live preview, detection start/stop, voice alerts |
| Reports | Incident list, filters, severity/status badges, report open/export/reprocess actions |
| Analytics | Trend charts, compliance breakdown, zones, and common violation types |
| Settings | Cloud/local mode toggle, system health, timezone, notifications, local diagnostics |
| Handbook | Built-in user guide and walkthrough panel |
| Admin Portal | Separate protected URL for device provisioning and audit logs |

## Report Workflow

1. YOLO detects a violation in a frame.
2. The event enters the violation/report queue.
3. Image evidence and detection metadata are stored locally or in Supabase.
4. Gemini or local Ollama/Gemma generates the incident analysis.
5. CASM formats the report and updates status from queued/generating to ready or failed.
6. The UI notifies the user and exposes report review/export actions.
7. Local mode reports sync to cloud when connectivity returns.

## Admin Workflow

The admin portal is available at:

```text
https://fypa-ai-model-development-integrati.vercel.app/admin/devices
```

Admins can:

- Review pending device metadata.
- Approve trusted devices.
- Reject unknown requests.
- Revoke provisioned devices.
- Issue one-time installer downloads.
- Review the append-only audit log.

Device provisioning should never be treated as automatic trust. Approve only devices you recognise.

## Common Commands

```powershell
# Run the main local server
cd Updated_Pipeline_Supabase
python casm_app.py

# Reprocess reports
python scripts\reprocess_reports.py

# Manage the queue
python scripts\manage_queue.py

# Start RealSense edge relay for deployed backend
scripts\START_EDGE_REALSENSE_RELAY.bat https://your-backend.up.railway.app

# Start local RealSense relay
scripts\START_LOCAL_REALSENSE_RELAY.bat
```

## Troubleshooting

| Problem | Likely cause | Fix |
| --- | --- | --- |
| No cameras appear | Camera unavailable or device not approved | Check hardware, stop other camera apps, approve device in admin portal |
| Report generation is slow | Local LLM processing | Ensure `ollama serve` is running, use test mode to isolate pipeline speed |
| Gemma/Ollama health is red | Ollama not running or model missing | Run `ollama serve` and `ollama pull gemma3:4b` |
| Supabase errors | Missing or wrong `.env` credentials | Verify URL, service role key, DB URL, bucket names, and schema |
| Images do not load | Signed URL expired or storage key mismatch | Refresh report, verify bucket policies and stored keys |
| Admin portal returns 403 | Wrong Basic Auth or blocked access | Contact the deployment/admin owner |
| CSV looks garbled in Excel | Encoding handling | Import through Excel Data > From Text/CSV and choose UTF-8 |

## Security Notes

- Never commit `.env`, Supabase service-role keys, API keys, or admin passwords.
- Use the Supabase service-role key only on the backend.
- Keep Supabase buckets private and serve evidence through signed URLs.
- Review device provisioning requests before approval.
- Revoke devices immediately when access should end.
- Review audit logs regularly for unexpected provisioning activity.

## Documentation

- `Updated_Pipeline_Supabase/README.md` - detailed Supabase/backend deployment notes.
- `Updated_Pipeline_Supabase/frontend/README.md` - frontend SPA notes.
- `MARKDOWN/INSTALL.md` and `MARKDOWN/QUICKSTART.md` - earlier setup references.
- `Updated_Pipeline_Supabase/docs/` - schema and presentation/defense documentation.

## Project Status

CASM is a prototype-stage FYP system. It is suitable for demonstration, evaluation, and controlled testing. For real site deployment, validate camera coverage, PPE class accuracy, device provisioning security, data retention policy, and report review workflow with the responsible safety officer or administrator.
