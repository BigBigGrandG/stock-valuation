# Issues 03/04 R3 implementation report

Date: 2026-09-12 (Asia/Shanghai)  
Worker ownership: end-to-end Issues 03/04 R3 mapping policy, live/API evidence, replay oracle, regression, and report.  
Runtime: `codex / gpt-5.6-luna / max`; no Antigravity probe or model fallback was used.

## Baseline and scope

- Baseline: `master` at `d0a7d62` (`origin/master` matched at task start).
- The worktree was already dirty with the R1/R2 Issues 03/04 implementation and artifacts. Existing R1/R2 source, code, tests, reports, and evidence were preserved; the earlier R3 live capture was copied to `verification/03-04-r3/live_results_r3-pre-conservative.json` before the final conservative-policy rerun.
- No `git clean`, `git reset`, commit, push, deployment, or nested worker was used. Issues 01/02 gates and accepted DCF work remain intact; Issues 05–08 were not implemented.
- Issue files now say `Status: pending coordinator acceptance` and `Execution: in_progress`; neither was marked resolved.

## R3 diagnosis and red-first evidence

The smallest real seam was the production `lookup_industry_benchmark` resolver. Before changing it, the new regression oracle asserted that a Yahoo `Internet Content & Information` label must not be treated as economically equivalent to a Damodaran `Software (Internet)` row:

```text
cwd: D:\workshop\stock-valuation
command: .\\.venv\\Scripts\\python.exe -m pytest backend/tests/test_audit_issues_03_04_rework_r3.py -q
exit: 1
result: 1 failed in 0.13s
artifact: verification/03-04-r3/mapping-red-regression.log
```

After removing that alias, a second red oracle covered the similarly unsupported `Beverages - Non-Alcoholic -> Beverage (Soft)` alias:

```text
command: .\\.venv\\Scripts\\python.exe -m pytest backend/tests/test_audit_issues_03_04_rework_r3.py -q
exit: 1
result: 1 failed, 1 passed in 0.12s
artifact: verification/03-04-r3/mapping-ambiguity-red.log
```

The final policy retains only the direct singular/plural `Semiconductors ->
Semiconductor` normalization. Internet, beverage, software application,
pharmaceutical, aerospace, machinery, auto, and other descriptive
cross-taxonomy aliases now degrade until a source-backed economic mapping is
available; broad/unknown labels never select an arbitrary row.

## Implementation changes

### Issue 03

- `backend/app/services/multiples.py` removes unsupported cross-taxonomy aliases while retaining the exact public snapshot rows and the direct Semiconductor label normalization. P/E industry selection remains available for actual Semiconductor profiles; GOOG/META Internet Content & Information and KO Beverages - Non-Alcoholic independently use system fallback with warnings.
- Existing R2 point-in-time company-history validation and independent P/E/EV arbitration are preserved: forecast vintage <= observation, future FY target, explicit forward evidence, HTTPS provenance, matching currency/unit/basis, deduplication, dense-history sampling, post-filter 3–5-year coverage, MAD/zero-MAD behavior, and explicit EV observed-all-firms rejection.
- `.scratch/.../issues/03-company-specific-multiples.md` records pending coordinator acceptance and the conservative decision; `issues/04...` is updated only for its lifecycle status/comment.

### Verification path and oracle

- `run_live_audit_r3.py` uses the production `app.main` FastAPI route with a recording `YFinanceProvider`. It captures the request, all seven provider outputs entering normalization, and the complete newly evaluated API response; the recording wrapper does not alter provider values or financial eligibility.
- `verify_r3_oracle.py` separately checks API output and reconstructs `QuoteData`, profile, balance, cash flow, income, estimates, and multiples models from saved raw JSON. It then runs the real Normalizer -> FinancialDataService -> ValuationService path offline, compares independent layers/DCF availability/base value with the API result, and numerically checks `Decimal` g3/g4/g5, FCFF Years 3–5 recurrence, and Year 6 terminal growth.
- `--corrupt-demo` writes a separate `live_results_r3.corrupt-control.json`, changes only a copied API g3 to `999`, and returns nonzero. The original `live_results_r3.json` remains unchanged; final integrity check observed `NVDA final g3=0.180...` versus corrupted-copy `g3=999`.

### Issue 04 preservation

No DCF production formula rewrite was introduced in R3. R1's exact Years 3–5 linear fade, terminal equality, sensitivity trajectory rebuild, explicit FY1/FY2 FCFF gate, and FCFE/FCFF applicability semantics remain covered by the prior tests and the R3 raw-output numerical oracle.

## Six-ticker live/API evidence

The final run used `DATA_PROVIDER=live`, a 15-second provider timeout, and no
demo data. All six requests returned HTTP 200 through the production route;
each has seven raw provider method outputs and a complete API body in
`verification/03-04-r3/live_results_r3.json`.

| Ticker | Actual live profile | P/E layer | EV layer | DCF / applicability |
| --- | --- | --- | --- | --- |
| NVDA | Technology / Semiconductors | industry | system (observed EV basis rejected) | available, 3 scenarios |
| AMD | Technology / Semiconductors | industry | system (observed EV basis rejected) | available, 3 scenarios |
| GOOG | Communication Services / Internet Content & Information | system (mapping conservatively rejected) | system | available, 3 scenarios |
| META | Communication Services / Internet Content & Information | system (mapping conservatively rejected) | system | unavailable: no FCFF; no FCFE substitution |
| KO | Consumer Defensive / Beverages - Non-Alcoholic | system (mapping conservatively rejected) | system | available, 3 scenarios |
| JPM | Financial Services / Banks - Diversified | system | system | EV/FCF/DCF unavailable by bank gate; P/E remains available |

The two additional cases KO and JPM are actual live provider/API evaluations,
not synthetic fixtures. KO verifies a different operating-company industry
degrades rather than taking a guessed row; JPM verifies that bank
applicability gates remain active while P/E remains available.

## Verification commands and observed results

Every command below retained stdout/stderr, working directory, and exit code
in a new R3 artifact. The path prefix is relative to
`.scratch/valuation-ai-audit-20260911/`.

| Acceptance item | Command / cwd | Observed result | Artifact |
| --- | --- | --- | --- |
| Conservative mapping plus R1/R2 regressions | `.\\.venv\\Scripts\\python.exe -m pytest backend/tests/test_audit_issues_03_04_rework_r3.py backend/tests/test_audit_issues_03_04_rework_r2.py backend/tests/test_audit_issues_03_04_regression.py -q` / repo root | PASS — 23 passed, 2 warnings, exit 0 | `verification/03-04-r3/backend-targeted-command.log` |
| Complete offline backend suite | `.\\.venv\\Scripts\\python.exe -m pytest backend/tests -q` / repo root | PASS — 369 passed, 2 warnings, exit 0 | `verification/03-04-r3/backend-full-command.log` |
| Live provider -> normalizer -> service -> FastAPI response | `.\\.venv\\Scripts\\python.exe .scratch/.../verification/03-04-r3/run_live_audit_r3.py` / repo root | PASS — six HTTP 200 responses, exit 0 | `verification/03-04-r3/live-api-command-final.log`, raw `live_results_r3.json` |
| Boundary and raw-input replay oracle | `.\\.venv\\Scripts\\python.exe .scratch/.../verification/03-04-r3/verify_r3_oracle.py` / repo root | PASS — 4 mapping checks, 6 API checks, 6 raw replays, exit 0 | `verification/03-04-r3/oracle-command-final.log`, `oracle_r3.json` |
| Oracle failure control | same script with `--corrupt-demo` / repo root | EXPECTED FAIL — exit 1, two numeric failures after g3 corruption | `oracle-corrupt-command-final.log`, `oracle_r3_corrupt_control.json` |
| Python syntax/compile | `.\\.venv\\Scripts\\python.exe -m compileall -q backend/app backend/tests .scratch/.../verification/03-04-r3` / repo root | PASS, exit 0 | `verification/03-04-r3/compileall-command.log` |
| Frontend TypeScript | `npm run typecheck` / `frontend` | PASS, exit 0 | `verification/03-04-r3/frontend-typecheck-command.log` |
| Frontend lint | `npm run lint` / `frontend` | PASS, exit 0 | `verification/03-04-r3/frontend-lint-command.log` |
| Frontend production build | `NEXT_DIST_DIR=.next-test NEXT_PUBLIC_BACKEND_URL=http://127.0.0.1:18082 npm run build` / `frontend` | PASS — Next 15.4.3 build, exit 0 | `verification/03-04-r3/frontend-build-command.log` |
| Full real-browser suite | `npx playwright test --reporter=line` / `frontend` | PASS — 6 passed, exit 0 | `verification/03-04-r3/frontend-playwright-command.log` |
| Diff whitespace safety | `git diff --check` / repo root | PASS (only expected LF/CRLF warnings from Git) | terminal output at final check |

## Acceptance matrix

- **PASS** — conservative industry mapping: unsupported Internet and beverage aliases degrade; only direct Semiconductor normalization remains; broad/unknown labels are not substring matched.
- **PASS** — independent P/E and EV arbitration, observed all-firms EV rejection, source/period/currency/unit/basis metadata, and existing R2 company-history safety tests.
- **PASS** — four core tickers plus two actual extra different-industry live/API cases with raw inputs and responses; no demo data.
- **PASS** — API-output and raw-input engine replay oracle; Decimal g3/g4/g5 and FCFF recurrence checks; controlled corruption returns exit 1 without modifying original evidence.
- **PASS** — DCF R1 fade/sensitivity/applicability behavior preserved and covered by full backend plus R3 numerical replay/browser suite.
- **PASS** — full backend 369/369, targeted 23/23, frontend typecheck/lint/build, Playwright 6/6, compileall, and diff check.
- **NOT RUN / out of scope** — Issues 05–08, deployment, commit, push, manual product acceptance, and refreshing the January 2026 public industry snapshot.
- **FAIL** — none in the final acceptance set; the only nonzero final command is the intentional corrupted-oracle control (expected failure).

## Risks and remaining limits

1. Yahoo Finance profile labels and Damodaran rows are separate taxonomies. R3 deliberately does not infer economic equivalence from naming; broader industry specificity will remain system fallback until an authoritative constituent/methodology mapping is obtained.
2. The public industry snapshot is January 2026 and must be refreshed with source date, retrieval date, age, sample, and basis checks as it ages. EV all-firms data remains observed and is not relabeled as forward operating EBITDA.
3. The live provider has no archived company forward-multiple series with historical vintages; live company-history candidates therefore degrade honestly rather than attaching current estimates to old prices.
4. META's DCF is unavailable because complete forward FCFF is absent; JPM's EV/FCF/DCF are unavailable because of bank applicability. Neither result is hidden or replaced with an incompatible model.

Coordinator product acceptance remains the next lifecycle decision; Issues 03/04 were intentionally left pending rather than resolved.
