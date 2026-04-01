# Master Change Tracker - 2026-03-29

This file is the single consolidated tracker for all current local changes in this workspace.

## 1) Scope Summary

- Goal: consolidate backend/frontend upgrades, provider routing, reliability visibility, and deployment split support.
- Current state: large multi-area change set with app startup still failing locally (exit code 1).
- Tracking mode: grouped by impact area with file-level mapping.

## 2) Current Runtime Status

- Local startup attempts (`start.bat` and direct `venv\\Scripts\\python.exe luna_app.py`) are currently exiting with code 1.
- This tracker records change coverage, but startup root-cause still requires dedicated debugging.

## 3) Backend API and Runtime Changes

### 3.1 Core app and endpoints

Files:
- `luna_app.py`

Highlights:
- Added split frontend/backend serving behavior (`SERVE_FRONTEND`, API-only `/` response mode).
- Added custom CORS handling with allowlist (`ALLOWED_ORIGINS`) for split deployment.
- Added realtime SSE endpoint (`/api/realtime/stream`).
- Added provider routing settings endpoint (`/api/settings/provider-routing`).
- Added disk-space status endpoint (`/api/settings/disk-space-status`).
- Added reliability stats endpoint (`/api/reliability/stats`).
- Added generate-now priority endpoint (`/api/report/<report_id>/generate-now`).
- Expanded report status fallback and stale-status correction logic.
- Added traceability widget injection path for served reports.
- Updated failure handling to avoid silent placeholder success states.

### 3.2 Captioning and provider routing (vision)

Files:
- `caption_image.py`

Highlights:
- Reworked from local-only Ollama flow to routed provider chain (model API -> Gemini -> Ollama, configurable).
- Added runtime provider update/get functions.
- Added quota-aware Gemini backoff and provider failure diagnostics.
- Added lightweight response cache for repeated vision requests.
- Added user-facing failure message semantics for unavailable local mode.
- Updated prompt quality/grounding rules for better factual captions.

### 3.3 Report generation pipeline and strictness

Files:
- `pipeline/backend/core/report_generator.py`
- `pipeline/backend/core/supabase_report_generator.py`
- `pipeline/backend/core/supabase_db.py`
- `pipeline/backend/integration/gemini_client.py`
- `pipeline/config.py`

Highlights:
- Added model API routing for NLP and embeddings.
- Added provider order controls and runtime configuration alignment.
- Added strict report generation mode behavior and richer NLP error propagation.
- Added safer Supabase progress updates and transaction rollback guard.
- Improved Gemini key cleanup, error tracking, JSON recovery, and quota fail-fast behavior.
- Cleared stale `error_message` on healthy status transitions in detection events.
- Parameterized config values through environment variables for Ollama/Gemini/Model API.

### 3.4 Deployment startup behavior

Files:
- `docker-entrypoint.sh`
- `start.bat`

Highlights:
- Hosted/Railway guard to disable local Ollama embeddings when unsuitable.
- Start script updated to use explicit venv python/pip and more deterministic dependency checks.

## 4) Frontend Changes

### 4.1 Realtime sync and routing lifecycle

Files:
- `frontend/js/realtime.js` (new)
- `frontend/js/app.js`
- `frontend/js/router.js`
- `frontend/css/style.css`

Highlights:
- Added centralized SSE realtime manager with reconnect handling.
- Added live/reconnecting/offline badge behavior.
- Added component unmount lifecycle support in router.
- App startup now triggers realtime sync manager when available.

### 4.2 API client expansion

Files:
- `frontend/js/api.js`
- `frontend/js/config.js`
- `frontend/js/runtime-config.js` (new)

Highlights:
- Added API methods for provider routing, reliability stats, disk status, realtime URL, and generate-now trigger.
- Added runtime-config-based API base URL support for split deployments.

### 4.3 Page-level behavior updates

Files:
- `frontend/js/pages/home.js`
- `frontend/js/pages/analytics.js`
- `frontend/js/pages/live.js`
- `frontend/js/pages/reports.js`

Highlights:
- Home/Analytics now support realtime refresh plus polling fallback.
- Live page significantly expanded:
  - settings modal window
  - provider routing controls
  - reliability metrics panel
  - recommended settings flow
  - additional notifications for key user actions
- Reports page enhanced:
  - realtime updates + fallback polling
  - normalized status handling
  - process/reprocess actions
  - stronger notifications and modal flow

### 4.4 Frontend deployment docs/config

Files:
- `frontend/vercel.json`
- `frontend/README.md`

Highlights:
- Updated static rewrite behavior and deployment instructions for split backend URL configuration.

## 5) Root Documentation and Env Examples

Files:
- `.env.example`
- `README.md`

Highlights:
- Added environment examples for provider routing and split deployment setup.
- Added Model API/Gemini/Ollama fallback routing examples and hosted deployment notes.

## 6) Utility/Debug/Test File Cleanup (Deleted)

Deleted files:
- `debug_caption_v3.py`
- `debug_imports.py`
- `debug_ollama.py`
- `debug_ollama_short.py`
- `debug_syntax.py`
- `demo_versioning.py`
- `smoke_test.py`
- `test_image_models.py`
- `test_ppe_assignment_logic.py`

Also removed temporary/intermediate artifacts in working folder:
- `_tmp_queue_check.py`
- `_tmp_short_bench.py`
- `reprocess_log.txt`

## 7) Minor Remaining Utility Adjustment

File:
- `view_reports.py`

Change:
- Added `render_template_string` import (small utility-side adjustment).

## 8) Risk and Validation Notes

- High-risk areas:
  - `luna_app.py` (broad API/runtime behavior changes)
  - `frontend/js/pages/live.js` (large UI/logic delta)
  - `pipeline/backend/core/report_generator.py` (core NLP/reporting behavior)
- Current blocker:
  - Local app startup exits with code 1, not yet root-caused in this tracker.

## 9) Suggested Next Validation Order

1. Fix startup failure first (capture full traceback and identify first exception site).
2. Verify provider routing endpoints (`GET/POST /api/settings/provider-routing`).
3. Verify realtime stream (`/api/realtime/stream`) and frontend reconnect behavior.
4. Verify report lifecycle statuses (`pending/generating/completed/failed`) and generate-now flow.
5. Verify split deployment mode (`SERVE_FRONTEND=false` + CORS allowlist).

## 10) Change Ownership Note

This file is intended as the single tracking source for the current in-progress branch state on 2026-03-29.
