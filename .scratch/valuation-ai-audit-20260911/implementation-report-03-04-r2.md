# Issues 03/04 R2 implementation report

Date: 2026-09-12 (Asia/Shanghai)  
Worker ownership: end-to-end Issues 03/04 R2 implementation, regression, browser verification, and evidence capture.  
Runtime: `codex / gpt-5.6-luna / max`; no provider fallback was used or claimed.

## Baseline and scope

- Repository baseline: `master` at `d0a7d62` (`origin/master` matched at start).
- The initial worktree was already dirty with the R1 Issues 03/04 implementation and evidence. Those changes, untracked artifacts, and R1 evidence under `verification/03-04/` were preserved; no `git clean`, `git reset`, commit, push, or deployment was performed.
- Ownership remained the single-worker contract in `implementation-03-04.md` and `rework-03-04-r2.md`. Issues 01/02 invariants were preserved; Issues 05–08 were not implemented or inspected for unrelated changes.
- R1 DCF work was retained: explicit FY1/FY2 FCFF eligibility, exact Years 3–5 linear fade, terminal-year equality, sensitivity rebuilding, model applicability gates, and existing frontend display paths.

## Red-first diagnosis

Following the diagnosing-bugs workflow, R2 regression tests were written and run against the real resolver path before production fixes:

```text
cwd: D:\workshop\stock-valuation
command: .\\.venv\\Scripts\\python.exe -m pytest backend/tests/test_audit_issues_03_04_rework_r2.py -q
exit: 1
result: 6 failed, 1 passed, 2 warnings
artifact: .scratch/valuation-ai-audit-20260911/verification/03-04-r2/red-regression.log
```

The failures reproduced the R2 holes: stale/undated forward history was accepted; one-year history, repeated dates, and dense history were not governed by the required post-filter 3–5-year policy; endpoint outlier filtering could invalidate coverage without rechecking it; observed all-firms EV/EBITDA was accepted as a forward operating-EBITDA target; and broad `Software` substring matching selected an arbitrary industry row. The failure log is retained as evidence rather than replacing the assertions with skips.

## Implementation

### Issue 03 — source-compatible independent multiples selection

- `backend/app/services/multiples.py` now validates company history point-in-time. Every retained row must have an observation date, HTTPS quote source, HTTPS forecast source, explicit `is_forward=true`, a forecast vintage on or before the observation, a future FY target period, matching USD currency, compatible per-share P/E or total-value enterprise-value/operating-EBITDA units and basis, and a ratio consistency check.
- History validation requires 3–5 unique observations over at least three years and no more than five years, with latest retained observation age bounded at 730 days. Duplicate dates are deterministically deduplicated; at most five evenly spaced rows including endpoints are retained; a 3×MAD filter is applied; zero MAD retains the selected rows; coverage, count, age, and provenance are rechecked after filtering. Missing or incompatible evidence degrades rather than inventing a time series.
- Industry selection is exact normalized label/alias matching only. Broad/ambiguous labels such as `Software` return no row; controlled exact mappings include `Internet Content & Information -> Software (Internet)` and `Semiconductors -> Semiconductor`. The mapping is documented as a conservative policy mapping between upstream taxonomies, not as an unverified taxonomy identity; unknown labels independently fall back.
- The January 2026 Damodaran snapshot is versioned and carries source date, retrieval date, sample count, metric currency/unit, forward basis/type, mapping key, and separate PE/EV HTTPS URLs. Forward PE may be selected when compatible; the observed all-firms EV/EBITDA table is explicitly rejected as a forward operating-EBITDA target, so EV independently falls to the explicit system fallback with a warning. Scenario low/high values are a documented configured ±10% spread, not claimed public percentiles.
- Provider metadata, normalizer output, service arbitration, override/reset selection layers, warnings, source labels, and export fields carry the evidence needed to trace `source -> normalizer -> assumptions -> engine -> API/export`. P/E and EV are resolved independently, and user overrides remain highest priority per metric.

### Issue 04 — DCF fade and full-stack verification

- The R1 backend fade contract remains intact for each scenario: `g_t = g_start + ((t - 2) / 3) * (g_terminal - g_start)` for Years 3–5, with exact `g5 == terminal_growth` and Year 6 derived from Year 5 and terminal growth. Sensitivities rebuild the same trajectory against each sensitivity terminal growth.
- The Markdown export now includes annual projection growth and an explicit Years 3–5 fade formula, with defensive fallback to the canonical formula when optional API fields are absent. Frontend types and scenario display expose the same trajectory without introducing a second business calculation.
- The browser fixture now uses an isolated fixture FastAPI app with explicit FY1/FY2 FCFF and bridge inputs only for test routes. Production `app.main` resolver functions and the production missing-FCFF gate are untouched. The stale expected value and non-viable test CapEx input were corrected; browser assertions cover parameter override, reset, ticker switch, source-layer changes, sensitivity, fade, and export.

## Verification and evidence

All commands below were run from the stated working directory; exit codes are the observed process exit codes.

| Acceptance check | Command / working directory | Result | Evidence |
| --- | --- | --- | --- |
| R2 safety regression plus R1 regression | `.\\.venv\\Scripts\\python.exe -m pytest backend/tests/test_audit_issues_03_04_rework_r2.py backend/tests/test_audit_issues_03_04_regression.py -q` / repo root | PASS — 21 passed, 2 warnings, exit 0 | `verification/03-04-r2/backend-targeted.log` |
| Complete offline backend suite | `.\\.venv\\Scripts\\python.exe -m pytest backend/tests -q` / repo root | PASS — 367 passed, 2 warnings, exit 0 | `verification/03-04-r2/backend-full.log` |
| Python compile check | `.\\.venv\\Scripts\\python.exe -m compileall -q backend/app backend/tests .scratch/valuation-ai-audit-20260911/verification/03-04-r2` / repo root | PASS, exit 0 | `verification/03-04-r2/compileall.log` |
| Frontend types | `npm run typecheck` / `frontend` | PASS, exit 0 | `verification/03-04-r2/frontend-static.log` |
| Frontend lint | `npm run lint` / `frontend` | PASS, exit 0 | `verification/03-04-r2/frontend-static.log` |
| Production frontend build | `$env:NEXT_DIST_DIR='.next-test'; $env:NEXT_PUBLIC_BACKEND_URL='http://127.0.0.1:18082'; npm run build` / `frontend` | PASS, exit 0 | `verification/03-04-r2/browser.log` |
| Targeted browser flow | `npx playwright test tests/e2e_valuation_integrity.spec.ts --reporter=line` / `frontend` | PASS — 3 passed, exit 0 | `verification/03-04-r2/browser.log` |
| Full frontend/browser suite | `npx playwright test --reporter=line` / `frontend` | PASS — 6 passed, exit 0 | `verification/03-04-r2/browser.log` |
| Four-ticker live production replay capture | `.\\.venv\\Scripts\\python.exe .scratch/valuation-ai-audit-20260911/verification/03-04-r2/run_live_audit_r2.py` / repo root | PASS — NVDA, GOOG, AMD, META completed; exit 0 | raw `verification/03-04-r2/live_results.json`, command output `live.log` |
| Industry boundaries and replay | `.\\.venv\\Scripts\\python.exe .scratch/valuation-ai-audit-20260911/verification/03-04-r2/verify_boundaries_and_replay.py` / repo root | PASS — broad label degraded; two exact mappings and available DCF trajectories replayed; exit 0 | `verification/03-04-r2/boundary_replay.json`, command output `live.log` |

The live run used the production `YFinanceProvider(timeout=15)` and did not use demo data. All four tickers completed with PE selected from the exact industry snapshot and EV independently selected from the system fallback because the public EV source is observed all-firms. NVDA, GOOG, and AMD had eligible DCF trajectories and passed replayed fade checks; META remained explicitly DCF-unavailable because complete forward FCFF was not present, with no FCFE substitution or fabricated value. The raw provider/service responses, per-metric layers, warnings, DCF eligibility, and replay calculations are retained in `live_results.json`.

Primary source and policy evidence is in `verification/03-04-r2/source-evidence.md`, including the NYU Stern/Aswath Damodaran January 2026 PE and EV pages, table columns, dates, sample counts, metric bases, and Yahoo Finance exact profile labels used for the controlled mapping boundary. `boundary_replay.json` records `Technology / Software -> None`, `Technology / Internet Content & Information -> Software (Internet)`, and `Technology / Semiconductors -> Semiconductor`; the broad case is intentionally conservative.

## Acceptance status

- **PASS** — strict point-in-time company-history validation, post-filter 3–5-year coverage, deduplication/dense sampling, zero-MAD behavior, endpoint-outlier recheck, currency/unit/basis checks, and independent PE/EV fallback tests.
- **PASS** — exact industry mapping and unknown/broad-label degradation with auditable source metadata.
- **PASS** — observed all-firms EV/EBITDA rejection and explicit system fallback warning; compatible PE industry differentiation remains available.
- **PASS** — user override, reset, ticker switch, source-layer reporting, DCF sensitivity/fade, and Markdown export through the real browser path.
- **PASS** — DCF Years 3–5 exact linear convergence, terminal equality, sensitivity consistency, and existing eligibility/applicability gates, covered by retained R1 tests plus R2 browser/replay evidence.
- **PASS** — full offline backend, frontend typecheck/lint/build, targeted browser flow, full browser suite, compile check, and four-ticker live raw evidence.
- **NOT RUN / out of scope** — Issues 05–08, deployment, commit, push, and manual acceptance outside automated browser checks.
- **FAIL** — none observed in the final verification set.

## Risks and remaining policy limits

1. The industry snapshot is January 2026 and must be refreshed through the same source/version/age checks as it ages; it is not represented as real-time dynamic data.
2. Yahoo's `Internet Content & Information` taxonomy and Damodaran's `Software (Internet)` taxonomy are separate upstream taxonomies. The exact alias is a documented controlled policy mapping supported by source labels, not a claim of identical classification; future unlisted or ambiguous labels conservatively degrade to fallback.
3. The live provider does not expose archived company forward-multiple series with historical vintages, so live company-history selection degrades rather than attaching current estimates to old prices. Synthetic `example.test` URLs exist only inside validator tests and are never used for production valuation.
4. META DCF unavailability is an honest data-eligibility result and remains visible; completing FCFF data ingestion is outside this R2 acceptance and must not be solved by weakening the production gate.

No unresolved implementation failure remains; coordinator product acceptance is still the next lifecycle decision.
