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

### Evidence traceability (peer-reviewed)
- Leading-indicator framing: recent synthesis and conceptual work supports proactive indicators for monitoring safety performance before injury outcomes are observed (Boughaba et al., 2023; Radanliev et al., 2024).
- Construction-domain relevance: recent construction-focused systematic reviews confirm broad practical use of leading indicators and highlight implementation constraints that require context-aware calibration (Sanni-Anibire et al., 2024; Sanni-Anibire et al., 2023).
- Short-term signal inclusion (`today` term): current construction research emphasizes dynamic, project-level safety performance interpretation and supports tracking near-term movement rather than only cumulative totals (Yin et al., 2025; Sanni-Anibire et al., 2024).
- Combined indicator interpretation: recent construction studies and reviews support combining multiple indicator classes to improve explanatory value for project safety interpretation (Kalatpour et al., 2023; Yin et al., 2025).
- Weight constants (`1.0`, `0.6`, `0.3`) and penalty scales (`45`, `30`, `2.5`) are project calibration parameters for interpretability and operational sensitivity. They are not copied directly from a single published equation.

### Important limitations
- This score is a leading indicator proxy, not a statutory injury metric.
- It is not a substitute for TRIR/LTIFR because exposure hours and recordable injury outcomes are not yet part of this dataset.
- It should be interpreted with incident context and supervisor validation.
- Benchmark bands (`95-100`, `85-94`, `70-84`, `<70`) are governance thresholds for this project and must be periodically recalibrated against observed site outcomes.

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

## Peer-reviewed references
1. Sanni-Anibire, M. O., Nwankwo, C., Oke, A., & Ebekozien, A. (2024). A comprehensive systematic review of safety leading indicators in construction. *Safety Science, 179*, 106433. https://doi.org/10.1016/j.ssci.2024.106433
2. Sanni-Anibire, M. O., Nwankwo, C., Oke, A., & Ebekozien, A. (2023). Benefits and challenges relating to the implementation of health and safety leading indicators in the construction industry: A systematic review. *Safety Science, 166*, 106131. https://doi.org/10.1016/j.ssci.2023.106131
3. Boughaba, A., Hassel, S., & Rouhana, S. (2023). Constructs of leading indicators: A synthesis of safety literature. *Journal of Safety Research, 86*, 157-171. https://doi.org/10.1016/j.jsr.2023.04.015
4. Radanliev, P., De Roure, D., Santos, O., Ani, U., Cannady, S., Montalvo, R. M., & Santos, M. A. (2024). Unravelling the Gordian knot of leading indicators in occupational safety and health management. *Safety Science, 180*, 106603. https://doi.org/10.1016/j.ssci.2024.106603
5. Kalatpour, O., Ahmadi, O., Parnian, S., & Won, J. (2023). Association between leading indicators of safety performance in construction projects. *Journal of Occupational and Environmental Hygiene, 20*(6), 311-321. https://doi.org/10.1080/15578771.2023.2195209
6. Yin, C., Wang, M., & Deng, M. (2025). What is safety performance? A systematic review of conceptualizations in the construction safety research. *Safety Science, 187*, 107025. https://doi.org/10.1016/j.ssci.2025.107025

## Implementation pointers
- Frontend aggregation and scoring helper:
  - `Updated_Pipeline_Supabase/frontend/js/api.js`
- Home score usage:
  - `Updated_Pipeline_Supabase/frontend/js/pages/home.js`
- Analytics score usage:
  - `Updated_Pipeline_Supabase/frontend/js/pages/analytics.js`
