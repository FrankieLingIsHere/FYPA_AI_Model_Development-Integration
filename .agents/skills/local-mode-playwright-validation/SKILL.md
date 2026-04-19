---
name: local-mode-playwright-validation
description: Run and interpret local-mode reconnect and deployed reports-progress Playwright validations for this repository.
---

Use this skill when the user asks to simulate offline behavior, validate reconnect sync, verify report-generation progress UX parity, or run the full Playwright validation flow used in this project.

## Workflow

1. Confirm the repository root is active and that local backend UI is reachable at http://127.0.0.1:5000 for local-mode checks.
   - Before local-reconnect runs, clean stale `luna_app.py` listeners on port 5000 and launch a fresh backend from the project venv.
   - A stale non-venv python process can bind 5000 and cause false Playwright startup/page timeouts.
2. Run the skill runner script from the repository root:

   python .agents/skills/local-mode-playwright-validation/run_playwright_validation.py --scenario local-reconnect

3. For deployed Reports progress parity checks:

   python .agents/skills/local-mode-playwright-validation/run_playwright_validation.py --scenario deployed-parity

4. To run both scenarios in one execution:

   python .agents/skills/local-mode-playwright-validation/run_playwright_validation.py --scenario all

5. Runner overrides for target URL and preflight:

    - Pin deployed checks to a specific frontend target:

       python .agents/skills/local-mode-playwright-validation/run_playwright_validation.py --scenario deployed-parity --frontend-url http://127.0.0.1:5000

    - Pin local reconnect base URL:

       python .agents/skills/local-mode-playwright-validation/run_playwright_validation.py --scenario local-reconnect --local-ui-url http://127.0.0.1:5000

    - Enforce local backend readiness checks before local reconnect script:

       python .agents/skills/local-mode-playwright-validation/run_playwright_validation.py --scenario local-reconnect --check-local-backend

6. Deployment trigger reminder for this repository:

   - Treat a commit on the deployment-tracked repository branch as the redeploy trigger.
   - Keep deployment-impacting fixes grouped into a single clear commit when possible.
   - If validation JSON artifacts are generated during checks, do not include them in the deploy commit unless explicitly requested.

## Patch Gate: Action Tests Must Pass

When patching frontend/runtime behavior, do not finalize the patch until all repository action tests pass with exit code 0.

Run from repository root:

python Updated_Pipeline_Supabase/deployed_frontend_navigation_timezone_action_test.py
python Updated_Pipeline_Supabase/deployed_provisioning_action_test.py

When patching installer/startup batch flows (
`frontend/static/LUNA_LocalInstaller.bat`, `start.bat`, or `/api/bootstrap/installer` rendering),
`deployed_provisioning_action_test.py` is mandatory because it now also asserts:

- rendered installer assignment placeholders are replaced without mutating internal token maps,
- self-update label targets remain present,
- startup batch label contracts remain intact.

When patching installer re-download eligibility/recovery UX (for example `credentials_present` states
in `frontend/js/settings-modal.js` or `/api/bootstrap/installer/request`),
`deployed_provisioning_action_test.py` must still pass because it also guards:

- no-cache headers on installer request responses (prevents stale cached 403/redirect behavior),
- provision-secret based recovery when query `machine_id` collides with a pending record,
- pending records remaining unchanged while approved-machine installer issuance succeeds.

Enforcement rule:

- If any action test exits non-zero, keep patching and re-run until both are green.
- If output contains non-blocking INFO lines but exit code is 0, treat as pass and report the INFO lines explicitly.

## Required Reporting

After each run, report the exact evidence fields from the runner JSON:

- all_passed
- env_overrides
- preflight (when `--check-local-backend` is used)
- results[].script
- results[].status and exit_code
- local reconnect metrics:
  - sync_started_auto_after_reconnect
  - sync_seen_auto_after_reconnect
  - sync_seen_after_reconnect
  - manual_sync_attempt
  - sync_local_cache_summary
  - sync_after_reconnect_started_calls_len
  - sync_after_reconnect_calls_len
- deployed parity metrics:
  - local_pass and cloud_pass
  - local_sequence and cloud_sequence

## Interpretation Rules

- If sync_started_auto_after_reconnect is true and manual_sync_attempt.attempted is false, auto-sync behavior is functioning and no manual fallback path was needed.
- If sync_seen_auto_after_reconnect is false but sync_after_reconnect_started_calls_len is greater than 0, treat this as in-flight/long-running sync and verify completion call count/duration before concluding failure.
- Do not mask reconnect failures with automatic manual fallback unless explicitly requested by the user.

## Repository-Specific Notes

- Local reconnect test script: Updated_Pipeline_Supabase/local_mode_ui_checkup_reconnect_perf_test.py
- Deployed parity script: Updated_Pipeline_Supabase/deployed_frontend_reports_progress_parity_test.py
- Deployed local-label contract script: Updated_Pipeline_Supabase/deployed_frontend_local_reports_label_contract_test.py
- Skill runner script: .agents/skills/local-mode-playwright-validation/run_playwright_validation.py
- Avoid broad Playwright route interception for this reconnect flow; this project uses in-page fetch telemetry for more reliable evidence.

## Runtime Triage Addendum: Deployed Local Report Label Contract

Use this when validating Reports-page label clarity for local-mode rows in deployed frontend.

Contract target:

- local-source badge shows `Local`
- status badges map clearly for local rows:
   - `queued -> Queued`
   - `generating -> Generating...`
   - `failed -> Failed`
   - `completed -> Ready`

Script:

- `Updated_Pipeline_Supabase/deployed_frontend_local_reports_label_contract_test.py`

Runner integration:

- Included in `deployed-parity` and `all` scenarios via
   `.agents/skills/local-mode-playwright-validation/run_playwright_validation.py`

Required reporting fields for this contract:

- `results[].metrics.label_contract_pass`
- `results[].metrics.checks[]` with:
   - `reportId`
   - `expectedStatus`
   - `sourceBadgeText`
   - `statusBadgeText`
   - `sourceOk`
   - `statusOk`

Interpretation detail:

- `pending` and `queued` are treated as the same queue stage and must render user-facing badge text `Queued`.
- `processing` and `generating` are treated as the same generation stage and must render `Generating...`.

## Runtime Triage Addendum: URL Targeting and Deployment Lag

Use this when source patches are correct but deployed frontend still shows stale labels.

1. Verify patched behavior against local served frontend first:

   python .agents/skills/local-mode-playwright-validation/run_playwright_validation.py --scenario deployed-parity --frontend-url http://127.0.0.1:5000 --check-local-backend --local-ui-url http://127.0.0.1:5000

2. Then run against deployed target without overrides:

   python .agents/skills/local-mode-playwright-validation/run_playwright_validation.py --scenario deployed-parity

3. If local passes but deployed fails, treat as deployment lag/runtime drift instead of a patch regression.

## Runtime Triage Addendum: Queue Worker Health

Use this quick triage whenever local backend logs mention queue-worker health (for example
`Queue worker is not healthy; attempting restart`) or when users report pending reports not processing.

1. Confirm queue status endpoint from local backend:

   http://127.0.0.1:5000/api/queue/status

   Expected healthy signal:
   - `available: true`
   - `worker_running: true`

2. Interpret startup log semantics correctly:
   - First-run bootstrap can legitimately start the worker when none exists yet.
   - Repeated restart warnings after startup indicate real instability and require deeper inspection.

3. If worker remains unhealthy after startup settles (for example > 15s):
   - Re-check startup state endpoint and queue status.
   - Verify no fatal exceptions are emitted from `queue_worker_loop` in local backend logs.
   - Re-run required action tests before finalizing any runtime patch.

## Runtime Triage Addendum: Optional Gemini Startup Noise

When strict local profile is active, Gemini is optional and local providers should remain primary.
Treat these as non-fatal unless cloud profile is explicitly required:

- missing Gemini key at startup,
- Gemini SDK import unavailable,
- fallback-to-local provider notices.

Preferred behavior for local profile patches:

1. Do not initialize Gemini client during strict local bootstrap.
2. Use info/warning logs for optional-cloud conditions.
3. Keep error logs only when Gemini is explicitly required for that runtime profile.

## Runtime Triage Addendum: Launcher Self-Update Reliability

When validating existing-install launch behavior, ensure launcher bootstrap does not regress to stale logic:

1. Do not blindly overwrite `C:\LUNA_System\Start_LUNA_Local_Mode.bat` from an external/stale downloaded BAT.
2. Preserve existing local launcher when running from non-local paths (for example Downloads).
3. Even when user skips source update check, attempt launcher refresh from installed template so label/flow fixes still propagate.
4. Preferred managed launcher name is `C:\LUNA_System\LUNA_LocalInstaller.bat`; keep `C:\LUNA_System\Start_LUNA_Local_Mode.bat` only as compatibility alias.
5. If launched from an external path (for example Downloads) and managed launcher already exists, hand off execution to the managed launcher to avoid stale-flow drift.

## Runtime Triage Addendum: Local Backend Process Hygiene

When local reconnect tests fail early with page navigation timeouts, validate backend ownership before patching code:

1. Check port 5000 listener process and command line.
2. Stop any stale `python ... luna_app.py` process not started from the active project venv/session.
3. Start a clean backend from `Updated_Pipeline_Supabase` using the venv python executable.
4. Verify both endpoints respond before Playwright execution:
   - http://127.0.0.1:5000/
   - http://127.0.0.1:5000/api/system/startup-status

## Runtime Triage Addendum: Bounded Local Checkup Prepare Timeout

If local checkup appears stuck while waiting for model pull/prepare, use bounded timeout tuning instead of treating as hard runtime failure.

Frontend checkup flow now supports runtime overrides:

- `window.LUNA_LOCAL_CHECKUP_WAIT_SECONDS` (clamped 3..30, default 8)
- `window.LUNA_LOCAL_CHECKUP_PULL_TIMEOUT_SECONDS` (clamped 60..900, default 120)

Use these when diagnosing slow environments or test constraints where long pull windows can exceed UI/test wait budgets.

## Runtime Triage Addendum: Offline Report Generation (No Cloud Fallback)

Use this when local backend logs show repeated Supabase/cloud connectivity errors during report flow, for example:

- `Failed to connect to database: could not translate host name ...`
- `Failed to insert pending event ...`
- `Failed collecting recovery candidates ...`

### Goal

Keep report generation functional in local/offline mode by using local filesystem + queue processing only,
without depending on cloud heartbeat/Supabase writes while connectivity is down.

### Required checks

1. Verify local backend is reachable:
   - `http://127.0.0.1:5000/`
   - `http://127.0.0.1:5000/api/system/startup-status`

2. Verify recovery endpoints still respond in offline mode:
   - `GET /api/reports/recovery/options` returns `success=true`
   - `POST /api/reports/sync-local-cache` with `{"dry_run": true}` returns counters and `success=true`
   - `POST /api/reports/recovery/execute` accepts local mode payload when queue worker is healthy

3. Validate queue health after startup settles:
   - `GET /api/queue/status`
   - expect `available=true` and `worker_running=true`

4. Validate local artifact progression for one report id:
   - local folder contains `original.jpg`
   - then `annotated.jpg`
   - then `report.html`

### No-cloud-fallback interpretation

- In strict offline validation, do not treat cloud/Supabase dependency as required for local report completion.
- If connectivity is down, local generation should continue via local runtime paths; cloud sync can resume after reconnect.

### Optional strict NLP no-fallback gate

When you must also enforce no NLP fallback behavior (model-provider strictness), run deployed system conditions with:

- `LUNA_REQUIRE_NO_NLP_FALLBACK=1`

and ensure runtime provider status reports empty `last_fallback_reason`.

### Runtime tuning knobs for repeated offline churn

- `SUPABASE_OFFLINE_BACKOFF_SECONDS` (default 90)
- `SUPABASE_OFFLINE_BACKOFF_MAX_SECONDS` (default 900)
- `SUPABASE_DB_RECONNECT_BACKOFF_SECONDS` (default 12)

Use these only for diagnostics/tuning; keep defaults unless environment constraints require adjustment.
