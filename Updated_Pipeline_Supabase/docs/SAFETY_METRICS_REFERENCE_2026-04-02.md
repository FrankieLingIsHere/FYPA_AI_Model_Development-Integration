# Safety Metrics Reference - 2026-04-02

## Purpose
This document defines the safety metrics currently used by the dashboard, including formula, interpretation, benchmark bands, and limitations.

It is intended to be cited in daily worklogs and implementation summaries.

## Metric 1: PPE Compliance Score (Leading Indicator, Dashboard)

### Where it is used
- Home page safety score widget
- Analytics page safety score widget

### Data inputs
- `severity.high`
- `severity.medium`
- `severity.low`
- `today`
- `total`

### Formula
1. Weighted burden:

   `weighted_burden = high * 1.0 + medium * 0.6 + low * 0.3`

2. Severity penalty:

   `severity_penalty = (weighted_burden / max(total, 1)) * 45`

3. Frequency penalty (short-term pressure):

   `frequency_penalty = min(30, today * 2.5)`

4. Compliance score:

   `score = clamp(100 - severity_penalty - frequency_penalty, 0, 100)`

Where `clamp(x, 0, 100)` restricts score range to [0, 100].

### Benchmark bands used
- `95-100`: Best-practice
- `85-94`: Acceptable
- `70-84`: Watchlist
- `<70`: Critical

### Why this model was chosen
- Uses severity weighting instead of count-only scoring.
- Keeps daily signal sensitivity through `today` penalty so operational drift is visible quickly.
- Produces stable 0-100 output suitable for trend display and on-site communication.

### Important limitations
- This score is a leading indicator proxy, not a statutory injury metric.
- It is not a substitute for TRIR/LTIFR because exposure hours and recordable injury outcomes are not yet part of this dataset.
- It should be interpreted with incident context and supervisor validation.

## Metric 2: Violation Type Breakdown

### Normalization policy
Violation labels from old and new records are canonicalized to:
- `NO-Hardhat`
- `NO-Safety Vest`
- `NO-Gloves`
- `NO-Mask`
- `NO-Goggles`
- `NO-Safety Shoes`

### Synonym handling examples
- `No-Hardhat`, `NO HARDHAT`, `Missing Helmet` -> `NO-Hardhat`
- `NO-VEST`, `Missing Safety Vest`, `HI-VIS missing` -> `NO-Safety Vest`
- `Missing Respirator` -> `NO-Mask`
- `Missing Safety Boots` -> `NO-Safety Shoes`

This prevents split counts caused by mixed historical naming conventions.

## Governance and review
- Review weighting and bands monthly against site safety outcomes.
- If exposure-hours and incident-outcome fields become available, add official lagging metrics (TRIR/LTIFR) in parallel.
- Keep this reference updated whenever formulas or thresholds change.

## Implementation pointers
- Frontend aggregation and scoring helper:
  - `Updated_Pipeline_Supabase/frontend/js/api.js`
- Home score usage:
  - `Updated_Pipeline_Supabase/frontend/js/pages/home.js`
- Analytics score usage:
  - `Updated_Pipeline_Supabase/frontend/js/pages/analytics.js`
