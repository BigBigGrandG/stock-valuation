# S5 rework report — strict FY1 actual-FCFF bridge

## Objective and execution context

- Baseline: `master` at `7aaec80 (修复三个致命问题)`, with pre-existing tracked and untracked S1/S2/S3/S5/S6/integration edits preserved. Baseline evidence remains in [`baseline-status.txt`](baseline-status.txt), [`baseline-untracked.txt`](baseline-untracked.txt), and [`baseline.patch`](baseline.patch).
- Ownership: this rework changed only the S5-owned production files `backend/app/engines/dcf.py`, `backend/app/models/domain.py`, and `backend/app/providers/yfinance_provider.py`, plus `backend/tests/test_s5_fiscal_ytd_dcf.py`, this report, and the S5 issue. Shared tests and S6 production code were not edited.
- Route: user-selected Codex / `gpt-5.6-luna` / max effort, as recorded in [`coordinator-state.md`](coordinator-state.md); no quota fallback, `resets_at`, commit, push, cleanup, or live-network claim.
- Working directory: `D:/workshop/stock-valuation`. Test commands used `.venv/Scripts/python.exe` and `DATA_PROVIDER=demo`.

## Rework changes

1. `_validate_fiscal_ytd_contract` now requires explicit `fiscal_ytd_start`, `fiscal_ytd_end`, and `fiscal_ytd_fiscal_year_end`. `metric.as_of`, the forecast anchor, and an inferred fiscal start are validation references only; they never fill missing actual coverage. An invalid/missing contract returns unavailable before FY1 subtraction, while the existing demo-only no-contract compatibility day-ratio path remains explicitly labelled.
2. The domain marker decoder now requires explicit YTD value, unit, period, source, source type, `as_of`, confidence, and estimate flag, and requires explicit coverage dates for an `available` marker. Malformed metadata or dates becomes `fiscal_ytd_status=unavailable` with a reason rather than using snapshot currency or quote `as_of` defaults.
3. `_extract_fiscal_ytd_fcff` now requires a valid three-letter `financialCurrency`; quote currency and USD are never used as statement-currency fallbacks. It classifies cash-flow and aligned financial columns independently, rejects unknown/mixed/mismatched bases, and rejects a first period shorter than 60 days or longer than 125 days from fiscal start. For cumulative statements it de-accumulates CFO, CapEx, interest, Tax Provision, and Pretax Income, then derives each period’s tax rate before applying after-tax interest; discrete statements retain per-period tax rates.
4. S5 tests now cover missing coverage with a current `as_of`, missing financial currency despite USD quote currency, missing marker provenance, cash-flow cumulative versus financial discrete mismatch, varying cumulative tax, short first period, complete JSON provenance, and existing aligned discrete, leap-year, and 52/53-week fixtures. The existing full-year-minus-YTD bridge and S6 final helper integration were preserved.

## Financial provenance

`Yahoo quarterly cash-flow and financial statements` → `_extract_fiscal_ytd_fcff` (same-period CFO, CapEx, interest, tax, basis, fiscal dates) → `S5_FISCAL_YTD_V1` marker in provider FCFE/FCFF definitions → existing normalizer metric notes → `CompanyFinancialSnapshot` typed marker validation → DCF explicit coverage/unit/source checks → `FCFF_1,stub = FCFF_1,full − FCFF_actual_YTD` → `ModelValuation.inputs`, `input_metrics`, `DCFScenario.projection_metrics`, `fiscal_ytd_actual`, and JSON.

An available synthetic actual carries `period=FY2026 YTD`, `as_of=2026-09-30`, `unit/currency=USD` only when explicit `financialCurrency=USD` is supplied, source `Yahoo Finance quarterly cash-flow statements`, `source_type=actual`, `is_estimated=false`, confidence `1.0`, notes/formula, and explicit `start..end` and FY-end anchors. Missing or invalid fields stay unavailable; no zero, quote-currency inference, FX invention, retrieval-date-as-period-end, or silent relabelling is used.

## Acceptance matrix

| Requirement | Result | Evidence |
| --- | --- | --- |
| Missing coverage fields do not become actual YTD | PASS | `test_live_ytd_missing_coverage_does_not_use_metric_as_of_or_inferred_end`; strict validator returns unavailable. |
| Missing `financialCurrency` with USD quote fails closed | PASS | `test_provider_requires_financial_currency_even_when_quote_currency_is_usd`. |
| Cumulative cashflow versus discrete financial basis is rejected | PASS | `test_provider_rejects_cumulative_cashflow_with_discrete_financial_statements`. |
| Cumulative interest and varying tax are aligned/de-accumulated | PASS | `test_provider_deaccumulates_cumulative_ytd_without_double_counting_quarters`; expected FCFF `394.00` from per-period tax rates `.10/.20/.30`. |
| Ambiguous short first period is rejected | PASS | `test_provider_rejects_short_first_period_as_ambiguous_quarterly_basis`. |
| Valid discrete and 52/53-week/leap fixtures remain valid | PASS | Concentrated CapEx provider fixture, leap FY-end `2028-02-29`, and week fiscal-end `2026-12-27` tests. |
| Full-year-minus-YTD preserves anchor and avoids day ratio | PASS | FY1 `600.00` from full-year `1000` minus YTD `400`; FY2 `1200`; proration factor `1.00000000`. |
| Complete model/API JSON provenance | PASS | S5 JSON assertions require unit, period, source, source type, `as_of`, confidence, and estimate flag. |
| S6 final integration | PASS | Static evidence: one helper import, one call in final successful `run_dcf`, zero reverse imports; S6 suite passes. |
| Live provider/frontend verification | NOT RUN | Only deterministic synthetic/demo-isolated provider statements were used; production live/network and frontend claims are intentionally absent. |

## Verification commands and artifacts

All commands ran from `D:/workshop/stock-valuation`.

| Command | Exit | Raw evidence |
| --- | ---: | --- |
| `$env:DATA_PROVIDER='demo'; .venv/Scripts/python.exe -m pytest backend/tests/test_s5_fiscal_ytd_dcf.py -q -p no:cacheprovider` | 0 | [`s5-rework-owned-pytest.stdout.txt`](s5-rework-owned-pytest.stdout.txt), [`s5-rework-owned-pytest.exit-code.txt`](s5-rework-owned-pytest.exit-code.txt); 18 passed. |
| `$env:DATA_PROVIDER='demo'; .venv/Scripts/python.exe -m pytest backend/tests/test_s6_terminal_governance.py -q -p no:cacheprovider` | 0 | [`s5-rework-s6-pytest.stdout.txt`](s5-rework-s6-pytest.stdout.txt), [`s5-rework-s6-pytest.exit-code.txt`](s5-rework-s6-pytest.exit-code.txt); 15 passed, 2 dependency warnings. |
| `$env:DATA_PROVIDER='demo'; .venv/Scripts/python.exe -m pytest backend/tests -q -p no:cacheprovider` | 0 | [`s5-rework-full-backend.stdout.txt`](s5-rework-full-backend.stdout.txt), [`s5-rework-full-backend.exit-code.txt`](s5-rework-full-backend.exit-code.txt); 455 passed, 2 dependency warnings. |
| `.venv/Scripts/python.exe -m compileall -q backend/app/engines/dcf.py backend/app/models/domain.py backend/app/providers/yfinance_provider.py` | 0 | [`s5-rework-compile.stdout.txt`](s5-rework-compile.stdout.txt), [`s5-rework-compile.exit-code.txt`](s5-rework-compile.exit-code.txt). |
| `git diff --check -- backend/app/engines/dcf.py backend/app/models/domain.py backend/app/providers/yfinance_provider.py` | 0 | [`s5-rework-diff-check.stdout.txt`](s5-rework-diff-check.stdout.txt), [`s5-rework-diff-check.exit-code.txt`](s5-rework-diff-check.exit-code.txt); only existing LF→CRLF warnings. |
| Static S6 integration import/call/reverse-import count | 0 | [`s5-rework-s6-integration.stdout.txt`](s5-rework-s6-integration.stdout.txt), [`s5-rework-s6-integration.exit-code.txt`](s5-rework-s6-integration.exit-code.txt): `1/1/0`. |

The red-capable pre-fix probe added six targeted regressions and observed `6 failed, 12 passed` (exit 1), isolating the four acceptance hypotheses before implementation. The post-fix owned suite is green; full backend is green with no shared fixture update required. If the integration worker reruns shared fixtures, any YTD fixture must provide explicit start/end/FY-end coverage and explicit statement currency, and any mixed cashflow/financial period basis must remain unavailable.

## Risks and pending decisions

- No live Yahoo response was asserted; real providers lacking `regularMarketTime`, exact quarter-end coverage, explicit `financialCurrency`, or matching statement basis now fail closed by design.
- Final repository acceptance remains coordinator-owned; no commit or push was performed.

## Resume here

Coordinator should review this report and the linked raw artifacts, then finalize repository acceptance. S5 rework is complete within ownership.
