# Report Building Logic

Date: 2026-05-15

## Pipeline Overview

1. Capture or upload creates a report id, saves `original.jpg`, and writes preliminary metadata.
2. YOLO detections identify people, PPE, missing PPE, machinery, vehicles, cones, and other supported scene objects.
3. Caption generation creates a narrative visual description. Cloud mode uses the cloud vision path; local mode uses the approved local provider path.
4. Caption quality enforcement preserves good model captions and appends YOLO PPE context when needed.
5. Report generation sends grounded caption, YOLO detections, missing PPE, source markers, and severity into the report model.
6. Strict JSON parsing and sanitization produce report sections: summary, scene evidence, per-person PPE, hazards, risks, likelihood, and recommended actions.
7. HTML is rendered locally, then cloud artifacts are uploaded when that path is active and available.
8. Recovery and sync paths reuse the same metadata fields so report cards stay consistent across cloud, local, local-synced, and reprocess flows.

## Captions

Captions should remain descriptive narrative sentences. They should describe visible people, posture, clothing, objects, and background without becoming a terse list of detector labels.

When YOLO evidence is missing from a good caption, the quality floor appends a short grounded PPE clause such as the detected person count and confirmed PPE deficiencies. This preserves readability while keeping the report prompt grounded.

## Risk Cells

Risk cells come from the model JSON when structured output is available. Each risk cell can include:

- `risk_category`
- `risk`
- `likelihood`
- `evidence`
- `regulation_citation`
- `legal_regulatory_consequences`
- `mitigation_steps`

Fallback analysis only runs when model output is missing or invalid. Fallback risks are generated from YOLO labels and evidenced scene context, not from unsupported assumptions.

Non-PPE activity categories such as restricted-area entry, unsafe posture, machinery exposure, and regulatory report generation are included in Potential Risks and Recommended Actions only when observed in the live frame, caption, or detector payload. They are not forced into every caption or every report.

## Severity Classification

Report severity is now classified from observed violation evidence instead of defaulting every report to `HIGH`.

- `NO-Hardhat` and `NO-Safety Vest` classify as `HIGH` because the configured PPE rules mark them as high consequence.
- `NO-Mask`, `NO-Gloves`, `NO-Safety Shoes`, and `NO-Goggles` classify as `MEDIUM`.
- Three or more distinct medium-only missing PPE categories escalate to `HIGH`.
- Generic violation count without a specific PPE label becomes `MEDIUM`, not `HIGH`.
- No violation evidence becomes `LOW`.

Queue priority may still be `URGENT` or `CRITICAL` for recovery, upload, or manual reprocess flows. That priority is separate from report severity and should not overwrite the user-facing severity badge.

## Likelihood

Likelihood is risk-cell specific. It describes how probable the listed harm is if the observed scene continues without correction.

Severity is report-level. It describes consequence level from the actual violation evidence.

Example: missing mask can be `MEDIUM` severity at report level, while a specific dust-inhalation risk cell may have `MEDIUM` likelihood. Missing hardhat near falling-object exposure can produce `HIGH` report severity and `HIGH` likelihood for head injury.

## Recovery And Sync

Recovery paths reconstruct report data from local metadata, Supabase detection events, violation rows, and filesystem artifacts. They should carry:

- `violation_types`
- `missing_ppe`
- `ppe_tags`
- `violation_count`
- `source_scope`
- `sync_source`
- `severity`

Local-cache sync and browser-draft handoff enqueue high-priority work when needed, but the queued payload includes the classified report severity so the final report row does not become incorrectly high.

## Test Coverage

Severity behavior is covered by `tests/severity_classification_contract_test.py`.

Report grounding and risk prompt behavior remain covered by existing report prompt and caption contract tests.
