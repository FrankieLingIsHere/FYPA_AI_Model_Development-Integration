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

Timezone-specific enforcement (Reports + sidebar timezone changes):

- `deployed_frontend_navigation_timezone_action_test.py` now also enforces timezone timestamp alignment contract checks:
   - synthetic `report_id` and timestamp pair stays aligned at database timezone,
   - switching sidebar timezone changes rendered timestamp output,
   - timezone change events and page refresh hooks still fire across reports/home/analytics.
- Any patch touching report timestamp rendering, timezone parsing, or sidebar timezone selector must keep this contract green.

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

## Feature Patch Git Sync Rule

When a feature patch changes repository files, do not stop at code + tests only.

Required post-patch git flow (non-interactive):

1. Stage intended files and create a commit with a clear message.
2. Pull from origin with fast-forward only:
   - `git pull --ff-only`
   - or explicit branch form: `git pull --ff-only origin <branch>`
3. Report final branch state from `git status -sb` (ahead/behind/clean).

Interpretation:

- If pull says `Already up to date`, still report current ahead/behind state.
- If branch is ahead after pull, call out that push is still required for remote/deploy pickup.
- Do not use merge commits or interactive git flows for this step.

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

## Runtime Triage Addendum: Queue Busy While Idle

Use this when users report "queue busy" during reprocess even though no report appears to be generating.

1. Confirm actual queue state first:
   - `GET /api/queue/status`
   - check `queue_size`, `worker_running`, `available`, `by_device`, and `queue_preview`

2. Confirm generate-now rejection type:
   - `POST /api/report/<report_id>/generate-now`
   - inspect response fields `rejected_reason`, `queue_size`, `queue_capacity`, and `worker_running`

3. Interpretation rules:
   - `rejected_reason=queue_full` with `queue_size >= queue_capacity` means true queue saturation.
   - `rejected_reason=rate_limited` with `queue_size=0` means device rate limiting, not queue saturation.
   - `worker_running=false` should be surfaced as worker-health error, not generic queue-busy cooldown.
   - if `by_device.local_cache_sync` dominates and logs are full of `local_cache_sync_queued`, local-to-cloud reconciliation is likely driving queue pressure.

5. Local-to-cloud migration interaction check:
   - inspect `GET /api/logs?limit=...` for repeated `local_cache_sync_queued` with reconnect reasons.
   - avoid running multiple backend instances; confirm only one `luna_app.py` process owns port 5000.
   - for auto reconnect sync, defer/limit sync enqueue when queue already has backlog.

4. Patch guidance for manual reprocess/recovery actions:
   - Avoid reusing deterministic per-report fallback `device_id` values for retries.
   - Use per-attempt unique fallback device ids for manual enqueue retries to avoid sticky rate-limit loops.
   - Keep required action tests green after patching.

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

### Six-Step Recovery Procedure (Use This Exact Order)

Use this when users report queue/reprocess drift and process ownership confusion on Windows.

1. Snapshot active ownership and queue state first:
   - list all `python` processes containing `luna_app.py`
   - check port 5000 listener PID + executable path
   - query `GET /api/queue/status` and keep `queue_size`, `by_device`, and `queue_preview`

2. Stop all existing `luna_app.py` python processes before restart:
   - only target processes where command line contains `luna_app.py`
   - do not kill unrelated python tasks

3. Start backend from project venv in `Updated_Pipeline_Supabase`:
   - `"<repo>/.venv/Scripts/python.exe" luna_app.py`
   - prefer one dedicated foreground terminal for diagnostics to avoid silent detached failures

4. Validate readiness immediately after start:
   - `GET /api/system/startup-status` must return HTTP 200
   - `startup-status.runtime.python_executable` should match expected interpreter path for this session
   - `GET /api/queue/status` must return HTTP 200 and `worker_running=true`

5. Confirm migration pressure source before reprocess actions:
   - if `by_device.local_cache_sync` dominates and logs show repeated `local_cache_sync_queued`, treat as migration/reconnect queue pressure
   - use `queue_preview` to identify actual queued `report_id` entries

6. After any patch, enforce git sync completion:
   - `git add <intended files>`
   - `git commit -m "<clear message>"`
   - `git pull --ff-only`
   - `git status -sb` and report final branch clean/ahead/behind state

PowerShell caution:

- never use `$PID` as a loop variable because it is read-only in PowerShell
- use names like `$procId` when iterating owning process ids

## Runtime UI Guardrail: Text Visibility and Contrast

Use this whenever patching sidebar/nav/select/dropdown UI states.

Non-negotiable rules:

1. Text must remain readable in all interactive states (default, hover, active, focused, expanded, collapsed).
2. Do not rely on "different color" only; maintain strong contrast against background.
3. Target minimum contrast:
   - normal text: WCAG AA 4.5:1 or higher
   - large text (>= 18px regular or >= 14px bold): 3:1 or higher
4. Native select/dropdown options must explicitly set readable foreground + background colors (avoid white-on-white states).
5. If sidebar/nav collapses, open dropdowns/selectors must close/blur so floating lists do not remain visible off-state.
6. For native selects inside hover-collapsed sidebars, do not rely on `:hover` alone to keep controls visible while interacting.
   Use an explicit "selector-open" state (focus/pointer activated) so the sidebar does not collapse before the user can pick an option.

Verification checklist:

- open timezone selector and inspect option list text/background contrast
- keep timezone selector open and move pointer toward option area; selector must remain usable until selection/escape/outside click
- collapse/minimize sidebar and confirm dropdown list disappears immediately
- expand sidebar again and confirm selector remains usable

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

## Runtime Triage Addendum: Report Timestamp and Timezone Drift

Use this when `report_id` clock fragments (for example `YYYYMMDD_HHMMSS`) do not match rendered report timestamp on the Reports page.

1. Confirm backend timestamp semantics:
   - report-id-derived timestamps must be timezone-aware,
   - naive timestamp strings from local cache must be interpreted in backend database timezone context.

2. Confirm frontend normalization path:
   - sidebar selector supports IANA timezone IDs,
   - frontend timestamp parser treats naive timestamps as database timezone time,
   - timezone change re-renders Reports/Home/Analytics timestamp surfaces.

3. Validate with action test:

   python Updated_Pipeline_Supabase/deployed_frontend_navigation_timezone_action_test.py

4. If action test fails only on deployed target but passes locally with same commit, treat as deployment lag/runtime drift and re-check after redeploy.

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

## Runtime Triage Addendum: Local Live Camera Feed Delayed/Blank on Mode Switch

Use this when users report that switching to local mode causes Live page webcam feed to appear very late, intermittently, or never.

Common log signatures:

- `VIDEOIO(DSHOW): backend is generally available but can't be used to capture by index`
- `VIDEOIO(MSMF): backend is generally available but can't be used to capture by index`
- `/api/live/devices` and `/api/live/status` calls are slow before stream starts.

### Primary causes

1. Repeated forced webcam probing on status/device endpoints:
   - can repeatedly open/close camera backends,
   - increases startup latency and may temporarily lock camera access.

2. Transient first-frame read failures after successful open:
   - backend reports webcam started,
   - stream generator exits early on first failed frame read.

### Required patch behaviors

1. Keep webcam device probing cached for routine status checks.
2. Allow explicit forced reprobe only when user clicks refresh controls.
3. Add bounded webcam read retries + one reopen self-heal before declaring stream failure.
4. Keep browser-camera fallback path available when backend webcam is unavailable.

### Validation sequence

1. Local sanity check:
   - `GET /api/live/devices` should return quickly without repeated backend warnings on every poll.
   - `GET /api/live/devices?refresh=1` should still force a fresh device probe.

2. Start/stop contract:

   python Updated_Pipeline_Supabase/deployed_live_start_contract_test.py

3. Required action tests (must remain green after runtime/frontend changes):

   python Updated_Pipeline_Supabase/deployed_frontend_navigation_timezone_action_test.py
   python Updated_Pipeline_Supabase/deployed_provisioning_action_test.py

Interpretation guidance:

- If local start/stream is stable after patch but deployed still shows stale behavior, treat as deployment lag/runtime drift and re-check after redeploy.
