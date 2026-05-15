# Mira Assistant Logic

Date: 2026-05-15

## Terminology

- **Intent**: the user goal detected from a prompt, such as browsing reports, explaining a term, exporting CSV, opening a workflow page, or applying a settings profile.
- **Entity**: a value extracted from the prompt, such as `cloud`, `local`, `high`, `mask`, `today`, or a free-text location/device token.
- **Report review carousel**: Mira's in-chat report browser. It shows filtered report cards with previous/next actions, report source tag, severity, timestamp, summary, and missing PPE labels.
- **Filter**: a deterministic constraint applied to live report rows. Current report filters include source, severity, date range, PPE type, and remaining search tokens.
- **Likelihood**: how probable the listed harm is if the observed scene continues without correction. Likelihood belongs to a specific risk cell.
- **Severity**: the consequence level of the observed violation. Severity belongs to the report row and should be classified from actual PPE evidence.
- **Source tag**: report origin label. `Cloud` means generated through the cloud path, `Local` means generated locally and not yet synced, and `Local Synced` means a local-origin report was uploaded after reconnect.
- **Action**: an assistant response button that invokes a safe app behavior, such as opening Reports, exporting CSV, navigating to a handbook section, or moving the carousel.
- **Guardrail**: deterministic handling that keeps Mira from exposing credentials, private admin details, or unapproved system actions.

## Intent Order

Mira runs in the browser and uses deterministic logic rather than an external chatbot model. The main answer flow is ordered so report and admin commands stay predictable:

1. Normalize the prompt and detect export requests.
2. Apply safety, language, and negative guardrails.
3. Resolve report review intent for prompts such as `show cloud reports`, `check reports on front gate`, or `what are the main risks of each case`.
4. Resolve direct terminology explanations, including `likelihood`, `local synced`, `cloud mode`, `local mode`, caption providers, and local checkup.
5. Search handbook/docs entries for workflow and terminology questions.
6. Resolve compound actions, local/cloud workflow actions, analytics, settings, report destination, exports, tutorials, and page navigation.
7. Fall back to a concise help response with useful actions.

Report browsing intentionally runs before general documentation search so prompts about concrete report rows do not become vague handbook answers.

## Report Filtering

`buildReportFilters()` extracts:

- `source`: `cloud`, `local`, or `synced_local`.
- `severity`: `high`, `medium`, or `low`.
- `dateRange`: today, yesterday, week, or month.
- `ppeTypes`: hardhat, vest, mask, gloves, goggles, or shoes.
- `searchTokens`: remaining useful words, after removing filler terms like `report`, `risk`, `case`, `likelihood`, `on`, `at`, and command verbs.

`matchesReportFilters()` checks each live row against the selected constraints. Search tokens match report id, device id, timestamp, summary, and missing PPE labels, so prompts like `check reports on front gate` can match either a device id or report summary.

## Report Content Questions

Mira handles report-content inquiry through the report review carousel:

- `what are the main risks of each case` opens the filtered report set instead of requiring a source/severity filter.
- `what does likelihood mean` returns a terminology explanation and links to the report section.
- `check reports on XXX` applies `XXX` as search tokens.
- `explain this report` uses the selected carousel card and summarizes severity, missing PPE, status, source, and report summary.

The assistant reads report rows through `API.getViolations()`. It does not infer new safety findings by itself; it explains and filters the report data already produced by the pipeline.

## Test Coverage

The assistant inquiry contract is covered by `tests/assistant_report_inquiry_contract_test.py`. It stubs live report rows in a real browser and verifies likelihood explanation, main-risk browsing, location/device filtering, and no-match handling.
