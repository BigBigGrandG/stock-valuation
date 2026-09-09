# Remaining acceptance defects and worker verification assignment

The first correction is partially accepted: missing balance fields are optional, individual models isolate missing inputs, and false historical multiples were removed. Acceptance remains OPEN. Do not claim all defects resolved without executing this file and the coordinator verification plan.

## Required corrections with reproducible tests

1. `get_cash_flow`: annual CFO plus missing annual capex currently computes capex from TTM `freeCashflow`. Mock annual CFO=100, missing capex, info operatingCashflow=200/freeCashflow=150. It must NOT produce annual FCFE=150. Do not mix annual/TTM components. Prefer no fallback inside a nonempty statement, or use a wholly consistent sourced dataset.
2. Cash-flow and income statements may have different latest column dates. Only compute after-tax interest using the SAME fiscal date as CFO/capex. Current zero debt does not prove historical interest was zero; remove this historical inference. Explicit missing data is preferable.
3. Balance-sheet missing latest debt plus current info debt also mixes periods; income missing latest EBITDA/EPS plus info TTM currently labels them annual. Leave missing values unavailable or propagate field-specific source and actual period consistently. Never substitute partial debt or other short-term investments for total debt or cash equivalents.
4. `forwardEps` fallback is currently falsely labelled 0y analyst consensus. Remove ambiguous fallback or correctly identify its source horizon. Merely renaming FY1E to 0y is insufficient fiscal mapping. Do NOT apply analyst 0y annual growth to arbitrary TTM or stale annual values and label a fiscal forecast. Simplest safe solution: omit unverified forward EBITDA/FCFE/FCFF projections and let engines use actual inputs plus explicitly configured assumptions. If retaining projections, prove base fiscal period and corresponding forecast period, recording source dates/formulas.
5. `_TickerBundle` still swallows statement failures and most info failures. Map timeouts/rate limit/unavailable consistently, do not silently turn source failures into 404 or a successful fabricated dataset. Bound semaphore acquisition and network waits, including quote history fallback. Add meaningful failure/timeout tests.
6. Profile uses sharesOutstanding as diluted shares without approximation provenance and may pull a historical balance share count with quote date. Label outstanding shares approximation/source/date; never pretend weighted-average diluted shares. For share classes/ADRs verify unit basis; if inconsistent disable affected aggregate-per-share models.

## Execution and evidence, not just code

You own backend and backend evidence. Read `coordinator-verification-plan.md` and EXECUTE its backend checks. Store actual pytest stdout, five live response JSON files and live oracle stdout, financial/loss/share-class/ADR/non-equity errors, plus raw-source-to-normalized NVDA and KO reconciliation. Report any missing checks explicitly. Update report with actual commands and exit codes. Do not claim no defects remain just because tests passed.

Use `.venv/Scripts/python.exe`, API port8002. No commits. Coordinate with frontend dispatch ctx_2b65515e5cd9 when backend ready. Retain existing valid edits, no bulk rewrites or unrelated refactors.
