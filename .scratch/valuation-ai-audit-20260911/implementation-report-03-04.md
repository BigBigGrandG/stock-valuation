# Implementation Report — Issues 03/04

## Objective

Implement and verify Issue 03 company/industry-specific multiples and Issue 04
DCF growth fade on `master/d0a7d62`, preserving the closed Issue 01/02
invariants and leaving Issues 05–08 untouched.

## Baseline and ownership

* Baseline command: `git status --short --branch`; `git log -5 --oneline --decorate`;
  `git diff --stat`; `git diff -- .`.
* Baseline: `master...origin/master`, `HEAD d0a7d62 (修复致命问题)`. The only
  pre-existing untracked item was
  `.scratch/valuation-ai-audit-20260911/implementation-03-04.md`.
* Ownership: this worker completed the backend provider/normalizer/service/
  engine changes, frontend/API/export contract, tests and evidence. No worker
  was dispatched; no commit, push, reset or clean was performed.
* Runtime recorded by the implementation contract: `codex / gpt-5.6-luna / max`;
  no quota fallback was needed during this run.

## Completed changes

### Issue 03

* Added `backend/app/services/multiples.py`, a request-scoped independent
  arbiter: user override → validated company historical forward observations →
  versioned public industry snapshot → explicit system fallback.
* Company observations require contemporaneous FY forward period, HTTPS source,
  matching price/EPS or EV/EBITDA evidence, positive finite values, 3–5 retained
  samples, date coverage/age limits and robust outlier filtering. Current
  trailing Yahoo fields remain unavailable rather than being relabeled.
* Added NYU Stern/Damodaran January 2026 US industry rows with separate P/E and
  EV/EBITDA sources, sample/date/period/currency/estimated metadata, aliases by
  upstream industry labels, and no ticker whitelist. The selected metric's
  layer, value, as_of, sample size, basis, URLs, configured spread and
  degradation warning are carried through API, model assumptions and export.
* P/E and EV/EBITDA resolve independently; bank/REIT/ADR and other existing
  applicability gates remain unchanged.

### Issue 04

* Added exact Decimal `_fade_growth_rate` and changed DCF Years 3–5 to
  `g_t = g_start + ((t-2)/3) * (g_terminal-g_start)`, with g5 exactly terminal;
  FCFF6 is exposed as `FCFF5 * (1 + terminal_growth)`.
* Years 1–2 retain explicit FCFF qualification/production isolation. DCF
  terminal TV/PV and every sensitivity cell use the same backend trajectory;
  sensitivity changes rebuild Years 3–5 while preserving Years 1–2.
* Added growth/PV provenance to projection metrics, scenario fields and price
  intermediates. Frontend and Markdown render the backend rates/formula and do
  not perform business math.

## Verification

Detailed artifacts are in
`.scratch/valuation-ai-audit-20260911/verification/03-04/`.

| Area | Command / result |
| --- | --- |
| Red-first regression | `pytest ...test_audit_issues_03_04_regression.py -q`, exit 1, first run recorded in `red-regression.log` |
| Targeted backend | 19 passed, 2 warnings |
| Full backend | `pytest backend/tests/ -q`, exit 0, **356 passed**, 2 warnings |
| Frontend | typecheck, lint, build, exit 0 |
| Markdown formatter | all 7 groups passed, exit 0 |
| Browser export contract | 3 passed, exit 0 |
| Demo UI smoke | DCF growth column/formula/FCFF6, export and sensitivity center passed, exit 0; explicitly DEMO only |
| Full Playwright suite | 5 passed, 1 existing fixture workflow failed because its incomplete FCFF fixture is correctly isolated by Issue 01/02 while stale test expects DCF `$21.47`; not changed |
| Live provider | GOOG/META/AMD/NVDA HTTP 200, non-demo; source layers and DCF fade recorded in `live.log` |

## Source and limitations

The industry layer is a versioned January 2026 public snapshot, not a claim of
real-time industry data. EV/EBITDA is labelled as an observed all-firms
aggregate; its configured scenario spread is not a percentile. Live quote and
financial inputs remain subject to Yahoo availability, stale-date warnings and
the existing FCFF eligibility gate. META had no available production DCF in the
bounded live run for that reason; this is not silently substituted with FCFE.

## Risks and pending items

* The existing fullstack browser fixture/test mismatch is outside Issues 03/04;
  relaxing the production FCFF gate would violate the closed Issue 01/02
  contract. Coordinator may update that fixture/test in a separate scoped task.
* Industry snapshot values require explicit refresh when the cited public tables
  roll forward; until then their January 2026 date is displayed and age-checked.
* No Issues 05–08 work was performed.

## Resume Here

Review `source-evidence.md`, `live.log`, and the code diff; run the full backend
and frontend commands above. No commit/push was made. The worker completion
message should be treated as the handoff boundary.
