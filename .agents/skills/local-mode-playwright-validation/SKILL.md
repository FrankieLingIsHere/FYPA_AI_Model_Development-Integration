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
- Skill runner script: .agents/skills/local-mode-playwright-validation/run_playwright_validation.py
- Avoid broad Playwright route interception for this reconnect flow; this project uses in-page fetch telemetry for more reliable evidence.

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
