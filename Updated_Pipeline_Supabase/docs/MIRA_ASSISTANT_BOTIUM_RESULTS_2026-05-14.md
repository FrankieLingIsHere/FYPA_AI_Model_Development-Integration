# Mira Assistant Botium Regression Results - 2026-05-14

## Purpose

Mira is intentionally rule-based with no LLM backend for the main assistant path, so the highest-risk failure mode is brittle prompt routing. This Botium suite pressure-tests deterministic rules with phrasing variance, typos, code-switching, off-topic prompts, privacy/security prompts, combined commands, and report/analytics filter extraction.

## Framework Decision

Botium Core/CLI was used as the local regression framework because Mira has deterministic outputs and exact route/action expectations. testRigor was kept as a future no-code option, but it was not used in this run because it is an external SaaS workflow and the local Botium SimpleRest adapter gives repeatable project-controlled results without extra credentials.

## Harness

- Test root: `Updated_Pipeline_Supabase/tests/mira-botium`
- Botium config: `botium.json`
- SimpleRest wrapper: `mira-simplerest-server.js`
- Runner: `run_mira_botium.ps1`
- Rerun command:

```powershell
powershell -ExecutionPolicy Bypass -File Updated_Pipeline_Supabase/tests/mira-botium/run_mira_botium.ps1
```

The wrapper loads `frontend/js/assistant.js` in a Node VM with stubbed browser APIs, fixture violation rows, and mocked analytics helpers. Botium sends each utterance through `POST /message` and checks the flattened assistant reply with wildcard case-insensitive assertions.

The same harness also exports `askMira()` for a broad Markdown coverage check. `mira_prompt_ideas_coverage.js` extracts every quoted prompt from `assistant_prompt_ideas.md`, runs it through Mira, and fails if a CASM-related prompt falls into an unknown/partial fallback. Pure off-topic or intentionally low-signal prompts are counted as covered when Mira gives the graceful fallback.

## Coverage

| Area | Variant Count | Assertion |
|---|---:|---|
| Live monitoring / supervision wording | 5 | Routes to Live Monitor |
| Image analysis wording | 4 | Routes to Analyze Image |
| Analytics filter prompts | 4 | Produces a live analytics snapshot |
| Combined camera + analytics requests | 3 | Splits into multiple safe actions |
| Permission-safe/privacy prompts | 4 | Gives permission-aware redaction guidance |
| Secret/admin bypass prompts | 4 | Refuses credential or authorization leaks |
| Capability/scope prompts | 4 | Explains local deterministic rules |
| Local-mode explanations | 3 | Explains approved host pipeline behavior |
| Report CSV export filters | 3 | Exports matching missing-hardhat rows |
| Off-topic/random prompts | 4 | Falls back without forcing analytics filters |

## Result

Final Botium run:

```text
38 passing (718ms)
```

Assistant prompt-ideas coverage:

```text
906 prompts checked
906 passed
0 failed
```

Coverage category counts from the final run:

| Category | Count |
|---|---:|
| Live monitor / camera routing | 327 |
| Analytics and data summaries | 278 |
| Navigation | 130 |
| Combined multi-action requests | 97 |
| Handbook / guidance | 31 |
| Export | 13 |
| Privacy guidance | 10 |
| Onboarding | 9 |
| Capability/scope | 6 |
| Settings | 2 |
| Other covered | 2 |
| Graceful fallback for allowed low-signal/off-topic prompt | 1 |

## Issues Found And Fixed

- `What can you help me with?` was treated as a weak tutorial/start request. Mira now recognizes this as a capability/scope question and explains its deterministic assistant boundaries.
- `Can you find yesterday helmet violations and export them to CSV?` returned no rows because conversational filler tokens such as `can`, `you`, `find`, `them`, and `to` leaked into report search filters. Report export now strips these non-filter tokens before matching rows.
- The full prompt-ideas sweep then exposed five additional everyday analytics phrasings, such as `Any violations today?` and `last week data`, that were landing in clarification. The analytics matcher now treats these natural phrasings as direct analytics/filter requests.
- Earlier harness setup issues were corrected by using one Botium conversation per `.convo.txt` file and relying on conversation utterance expansion instead of standalone empty-response utterance tests.

## Remaining Limits

- This suite validates assistant routing and text/action intent behavior, not the full browser UI.
- Botium checks deterministic outcomes; it does not prove broad semantic understanding like an LLM evaluator would.
- New product capabilities should add new utterance files and focused assertions so phrasing coverage grows with the rule set.
