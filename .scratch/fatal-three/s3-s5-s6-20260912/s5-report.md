# S5 worker report — FY1 stub actual FCFF bridge

## Objective

Close `FY1-stub-proration-no-ytd` end to end: obtain aligned actual FCFF YTD from provider statements, carry it through the existing normalization boundary with provenance, subtract it from the full-year FY1 forecast for an in-progress fiscal year, and retain the verified fiscal timeline and forecast growth anchors. Integrate the already-existing S6 terminal-governance helper at the final successful `run_dcf` return without editing S6-owned code.

## Current state and execution route

- Baseline: `master`, HEAD `7aaec80`, with existing dirty/untracked F1/S1/S2 work protected; baseline commands and artifacts are recorded in [`baseline-status.txt`](baseline-status.txt), [`baseline-untracked.txt`](baseline-untracked.txt), and [`baseline.patch`](baseline.patch).
- Actual route: user-selected Codex / `gpt-5.6-luna` / max effort per coordinator state; no provider fallback, no `resets_at`, and no commit/push/cleanup.
- Working directory for every command: `D:/workshop/stock-valuation`.
- Provider under implementation/test: `yfinance` statement extraction; tests use `DATA_PROVIDER=demo` and synthetic in-memory statements, with no live network claim.
- Ownership: changed only S5-owned `dcf.py`, `domain.py`, `yfinance_provider.py`, S5 tests, S5 issue, and this report/evidence. The pre-existing provider forward-borrowing edits were preserved. `terminal_governance.py` and S6 tests were read/integrated but not modified.
- Final workspace inspection also showed concurrent S3/S6 and shared-test edits; those files remain untouched and are not attributed to S5.

## Implementation

1. `backend/app/providers/yfinance_provider.py` adds `_extract_fiscal_ytd_fcff`. It derives the FY1 interval from `nextFiscalYearEnd` and `lastFiscalYearEnd`, selects quarterly cash-flow/financial columns through the valuation date, requires exact latest-date coverage and a contiguous fiscal-start sequence, rejects gaps/mixed labels/missing CFO-CapEx-interest-tax inputs/nonfinite values, de-accumulates explicit cumulative YTD columns, and computes `CFO + after-tax interest - abs(CapEx)`. It returns `status`, `reason`, `value`, `period`, `source`, `source_type`, `as_of`, `unit`, `confidence`, `is_estimated`, notes, and fiscal coverage dates; unavailable conditions remain unavailable rather than becoming zero.
2. Provider metadata is serialized as `S5_FISCAL_YTD_V1:` and appended to both FCFE/FCFF definitions. This uses the existing seven-method normalizer seam and survives even when only the canonical FCFE metric is available for notes; no `valuation_service.py` edit was made.
3. `backend/app/models/domain.py` adds optional additive snapshot fields (`fiscal_ytd_fcff` plus compatibility aliases, coverage dates/status/reason) and decodes the marker into a typed `FinancialMetric`. It preserves source, source type, period, as-of, currency/unit, confidence, estimate flag, and notes, and sets a required/unavailable state on malformed markers.
4. `backend/app/engines/dcf.py` validates YTD source type, FCFF-vs-FCFE identity, period/year, unit, finite value, estimate flag, as-of, fiscal anchor, and exact coverage end. A live in-progress FY1 without a trustworthy YTD contract now returns unavailable with no prices/scenarios and no day-ratio fallback. A valid contract computes `FCFF_1,stub = FCFF_1,full − FCFF_actual_YTD`; only demo snapshots without a contract use the explicitly labelled `day_ratio_compatibility` compatibility path. FY2+ growth uses the unprorated full-FY1 anchor, and scenario inputs/metrics/formulas expose the bridge and provenance.
5. Fiscal-year scheduling accepts a provider-supplied exact FY1 start (including 52/53-week-style years) while deriving later non-overlapping periods from the verified FY1 end. The final successful `run_dcf` result is passed exactly once to `apply_terminal_governance(result, snapshot, assumptions)` from the S6-owned module; there is no reverse helper-to-DCF dependency.

## Financial provenance chain

`Yahoo quarterly cash-flow/financial statements` → `_extract_fiscal_ytd_fcff` (period/fiscal dates, CFO, CapEx, same-period interest/tax) → provider marker in `fcfe_definition`/`fcff_definition` → existing normalizer canonical metric notes → `CompanyFinancialSnapshot` marker validator → DCF YTD contract validation and full-year-minus-YTD projection → `ModelValuation.inputs`, `input_metrics`, `DCFScenario.projection_metrics`/`fiscal_ytd_actual`, and JSON serialization.

For an available actual, the carried metadata is `period=FY{fiscal_end.year} YTD`, `as_of=valuation date`, statement currency/unit from provider financial currency, `source=Yahoo Finance quarterly cash-flow statements`, `source_type=actual`, `is_estimated=False`, `confidence=1.0`, explicit notes/formula, and `start..end` plus FY-end anchor. Mismatched units, dates, periods, FCFE labels, missing inputs, and nonfinite values do not receive a fabricated exchange rate, zero, or relabelled actual.

## Acceptance matrix

| Contract acceptance | Result | Evidence |
| --- | --- | --- |
| Concentrated CapEx/seasonality uses full FY minus actual YTD | PASS | `test_full_year_minus_ytd_actual_replaces_uniform_day_ratio_and_preserves_anchor`; provider synthetic result `394`; DCF FY1 `600` rather than `1000*92/365`. |
| Missing, incomplete, stale, mismatched, FCFE, and nonfinite YTD fail closed | PASS | S5 tests for absent live contract, latest-quarter gap, stale end, EUR unit, FCFE notes, and nonfinite CFO. |
| Fiscal/leap/non-calendar boundaries and full-year anchors | PASS | Leap FY end `2028-02-29`, fiscal days `366`, provider 52/53-week-style start, FY1 remaining interval, explicit FY2 anchor `1200`. |
| Provenance reaches model/API JSON | PASS | Domain marker test, normalizer smoke (`available`, `394`, `2026-09-30`), and `ModelValuation.model_dump(mode="json")` assertions. |
| S6 final successful-result integration | PASS | Static import in `dcf.py` and one final-return call; S6-owned helper unchanged. |
| Full product/live/frontend regression | NOT RUN | Outside S5 targeted scope; no live data or frontend claim. |

## Verification commands and outcomes

All commands ran from `D:/workshop/stock-valuation` with `.venv/Scripts/python.exe`:

- Baseline `git status --short --branch`, `git log -5 --oneline --decorate`, diff/stat/untracked inspection: exit `0`.
- `DATA_PROVIDER=demo pytest backend/tests/test_s5_fiscal_ytd_dcf.py -q -p no:cacheprovider`: **13 passed**, exit `0` (final run `0.70s`).
- `python -m py_compile backend/app/engines/dcf.py backend/app/models/domain.py backend/app/providers/yfinance_provider.py`: exit `0`.
- `git diff --check` on S5 files: exit `0` (Git emitted only existing LF→CRLF warnings).
- Static integration count: `dcf_helper_imports=1`, `dcf_helper_calls=1`, `reverse_import_matches=0`.
- Normalizer seam smoke with synthetic raw provider maps: exit `0`; marker status/value/end were `available` / `394` / `2026-09-30`.
- Overlapping `test_fatal_three_worker_c.py` + `test_dcf.py`: exit `1`, `6 failed, 6 passed`, due old fallback/absent-YTD and S6 governance expectations outside S5.
- Overlapping acceptance/audit regression set: exit `1`, `2 failed, 36 passed`, both S3 fallback expectations outside S5.
- Current S6-owned suite: exit `1`, `10 passed, 4 failed`; S6 helper-owned assertion/fallback expectations, not S5 files. Coordinator was notified; this is not represented as S5 acceptance failure.

Detailed command evidence is in [`s5-evidence.md`](s5-evidence.md).

## Risks and pending items

- S6 helper/test state currently has four observed failures in its ownership surface; coordinator/S6 must settle those and review the overlapping legacy expectations before final repository acceptance.
- Existing shared DCF tests still expect fallback-backed availability or day-ratio behavior and were intentionally not edited under the S5 contract; coordinator must decide expectation updates in the final integration pass.
- Live-provider/API/frontend verification is `NOT RUN`; only deterministic synthetic/demo-isolated evidence is claimed. The production path fails closed when Yahoo data cannot prove exact YTD coverage.

## Resume here

Coordinator should inspect this report/evidence, review S6's current helper/test failures, and run the final cross-worker regression. S5 implementation is complete within ownership; no commit or push was performed.
