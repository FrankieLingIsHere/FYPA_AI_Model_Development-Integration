---
name: local-mode-playwright-validation
description: Run and interpret local-mode reconnect and deployed reports-progress Playwright validations for this repository.
---

Use this skill when the user asks to simulate offline behavior, validate reconnect sync, verify report-generation progress UX parity, or run the full Playwright validation flow used in this project.

## Workflow

1. Confirm the repository root is active and that local backend UI is reachable at http://127.0.0.1:5000 for local-mode checks.
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
