# FYPA_AI_Model_Development-Integration

## Deployed CI Workflows

Two GitHub Actions workflows continuously validate the deployed system:

| Workflow | File | Trigger |
|----------|------|---------|
| Backend Deployed Checks | `.github/workflows/deployed-e2e-tests.yml` | push / schedule (every 6 h) / manual |
| Frontend Deployed Checks | `.github/workflows/frontend-deployed-checks.yml` | push / schedule (every 6 h, offset) / manual |

---

## Strict Mode

All test scripts support a **strict mode** flag (enabled by default in CI).  
When strict mode is **on**, any failing critical check causes the script to exit non-zero, failing the workflow job.  
When strict mode is **off**, the same failure is surfaced as a `WARN:` log line but the job still passes — useful for investigative/diagnostic runs.

### Backend scripts

| Env var | Default | Controls |
|---------|---------|---------|
| `CASM_STRICT` | `1` | `deployed_generate_now_smoke.py` – fail if violations API is unreachable or generation never progresses beyond queued/pending |
| `CASM_CONDITIONS_STRICT` | `1` | `deployed_system_conditions_test.py` – fail on startup/queue/stats/routing contract violations |
| `CASM_LOCAL_FAILOVER_SYNC_STRICT` | `1` | `deployed_local_failover_sync_contract_test.py` – fail on failover sync contract violations |
| `CASM_FRONTEND_ASSETS_STRICT` | `1` | `deployed_frontend_asset_check.py` – fail if required asset markers are missing |

### Frontend scripts

| Env var | Default | Controls |
|---------|---------|---------|
| `CASM_FRONTEND_STRICT` | `1` | `deployed_frontend_robustness_test.py`, `deployed_frontend_navigation_timezone_action_test.py`, `deployed_frontend_visual_layout_integrity_selenium_test.py`, `deployed_frontend_mobile_usability_test.py` – fail on any layout/navigation/timezone/mobile assertion failure |

Set any flag to `0` to run in informational (non-blocking) mode:

```bash
CASM_STRICT=0 python Updated_Pipeline_Supabase/tests/deployed_generate_now_smoke.py
CASM_FRONTEND_STRICT=0 python Updated_Pipeline_Supabase/tests/deployed_frontend_robustness_test.py
```

---

## Running Tests Locally

### Prerequisites

```bash
pip install requests playwright selenium
python -m playwright install --with-deps chromium
```

### Backend tests (require a running Railway deployment)

```bash
export CASM_BASE_URL="https://fypaaimodeldevelopment-integration-production.up.railway.app"

# Routing and health
python Updated_Pipeline_Supabase/tests/schema_regen_contract_test.py
python Updated_Pipeline_Supabase/tests/deployed_routing_check.py

# System conditions matrix (strict, with extended polling)
CASM_CONDITIONS_STRICT=1 \
CASM_CONDITIONS_POLL_SECONDS=90 \
CASM_CONDITIONS_POLL_INTERVAL=5 \
python Updated_Pipeline_Supabase/tests/deployed_system_conditions_test.py

# Inference flood (thresholds: p95 ≤ 12 000 ms, success ratio ≥ 0.75)
CASM_FLOOD_TOTAL_REQUESTS=8 \
CASM_FLOOD_WORKERS=3 \
CASM_FLOOD_P95_MS=12000 \
CASM_FLOOD_MIN_SUCCESS_RATIO=0.75 \
CASM_FLOOD_MAX_UNIQUE_REPORTS=1 \
CASM_FLOOD_TEST_IMAGE=Updated_Pipeline_Supabase/static/images/handbook-live.png \
python Updated_Pipeline_Supabase/tests/deployed_inference_flood_test.py

# Live-start / live-frame contracts
python Updated_Pipeline_Supabase/tests/deployed_live_start_contract_test.py
CASM_LIVE_FRAME_TEST_IMAGE=Updated_Pipeline_Supabase/static/images/handbook-live.png \
python Updated_Pipeline_Supabase/tests/deployed_live_frame_contract_test.py

# Generate-now smoke (strict – fails if progression never occurs)
CASM_STRICT=1 python Updated_Pipeline_Supabase/tests/deployed_generate_now_smoke.py

# Report quality and latency contracts
python Updated_Pipeline_Supabase/tests/deployed_report_quality_test.py
python Updated_Pipeline_Supabase/tests/deployed_report_open_latency_test.py
```

### Frontend tests (require a running Vercel deployment)

```bash
export CASM_VERCEL_URL="https://fypa-ai-model-development-integrati.vercel.app"

# Asset checks (strict)
CASM_FRONTEND_ASSETS_STRICT=1 \
python Updated_Pipeline_Supabase/tests/deployed_frontend_asset_check.py

# Robustness (strict, 3 stress-click cycles)
CASM_FRONTEND_STRICT=1 \
CASM_FRONTEND_MAX_NAV_LATENCY_MS=30000 \
CASM_FRONTEND_STRESS_CLICKS=3 \
python Updated_Pipeline_Supabase/tests/deployed_frontend_robustness_test.py

# Navigation + timezone action (strict)
CASM_FRONTEND_STRICT=1 \
CASM_FRONTEND_MAX_NAV_LATENCY_MS=30000 \
python Updated_Pipeline_Supabase/tests/deployed_frontend_navigation_timezone_action_test.py

# Visual layout integrity / Selenium (strict)
CASM_FRONTEND_STRICT=1 \
CASM_FRONTEND_VISUAL_MAX_WAIT_SECONDS=120 \
python Updated_Pipeline_Supabase/tests/deployed_frontend_visual_layout_integrity_selenium_test.py

# Mobile usability (strict)
CASM_FRONTEND_STRICT=1 \
python Updated_Pipeline_Supabase/tests/deployed_frontend_mobile_usability_test.py
```

---

## Test Artifacts

Each CI job uploads a JSON summary as a GitHub Actions artifact.  
Artifacts are named:

| Artifact name | Job | Contents |
|---|---|---|
| `generate-now-smoke-summary` | Deployed Generate-Now Smoke | `generate-now-smoke-summary.json` |
| `system-conditions-summary` | Deployed System Conditions Matrix | `system-conditions-summary.json` (endpoint samples + thresholds) |
| `frontend-interaction-summaries` | Frontend Interaction Robustness | `frontend-robustness-summary.json`, `frontend-nav-timezone-summary.json`, `frontend-visual-layout-summary.json` |
| `frontend-mobile-usability-summary` | Frontend Mobile Usability | `frontend-mobile-usability-summary.json` |

Each JSON summary follows this schema:

```json
{
  "test_name": "...",
  "target_url": "...",
  "checks": [
    { "name": "check_name", "pass": true, "message": "..." }
  ],
  "pass": true,
  "metrics": { "key": "value" },
  "strict_mode": true
}
```
