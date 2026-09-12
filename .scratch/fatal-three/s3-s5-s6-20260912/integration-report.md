# S3 integration follow-up report

Date: 2026-09-12 Asia/Shanghai  
Completed: 2026-09-12 19:43 +08:00  
Task: `task_000847c82050`  
Dispatch: `ctx_0c028e7e8833`  
Worker terminal: `term_25e1b3e2-a605-49dc-bf9b-c1ece705c1ed`

## Objective and execution context

This follow-up completed S3 acceptance against the shared S3/S5/S6 contract
and reconciled the 33 failures captured in
`coordinator-full-pytest.log`. The worker used the user-selected Codex Luna
Max route (`codex` / `gpt-5.6-luna` / `max`); this was not a quota fallback,
`resets_at` is not applicable, and no external side effect occurred. All
commands below ran from `D:/workshop/stock-valuation`; no commit, push,
cleanup, reset, or nested worker was used.

## Baseline and protected work

- Branch: `master...origin/master`; HEAD `7aaec80` (`修复三个致命问题`).
- Initial baseline checks (`git status --short --branch`, `git log -5
  --oneline --decorate`, diff/stat and untracked inventory) exited 0.
- The worktree already contained protected F1/S1/S2 changes and concurrent
  S5/S6 changes, including dirty `dcf.py`, `domain.py`, provider,
  `projections.py`, shared tests, `terminal_governance.py`, S5/S6 tests, and
  prior reports/artifacts. Those changes were preserved; this dispatch did
  not edit `dcf.py`, `domain.py`, provider, `projections.py`,
  `terminal_governance.py`, `test_s5_fiscal_ytd_dcf.py`, or
  `test_s6_terminal_governance.py`.
- Existing S3 edits to the three engines and `parameter_governance.py` were
  retained. The pre-existing F1 FCFE/borrowing changes in `fcf_yield.py` and
  pre-existing changes in `test_forward_fcfe_borrowing_isolation.py` were
  preserved; this follow-up only added the policy-aligned assumptions needed
  by the affected regression.

## S3 implementation

`backend/app/engines/parameter_governance.py` now applies the same
fail-closed source-conflict rules as S6 terminal governance:

1. There is no `model_fields_set` or metadata-shape inference. A direct
   `ScenarioValues` object without a deliberate source remains configured
   fallback and is rejected; an explicit `SourceType.USER_OVERRIDE`, or the
   `apply_overrides` API path, is the only user-scenario authorization.
2. A source label containing `fallback` is rejected before considering a
   non-user source type. Thus `DERIVED`/`industry` metadata cannot rescue an
   explicit configured-fallback label.
3. `SourceType.FIXTURE` is accepted only when `snapshot.is_demo` is explicitly
   true. The demo flag is passed by all three S3 engines; fixture assumptions
   on a non-demo snapshot are unavailable.
4. Unknown source tokens are unavailable. Known actual, analyst-estimate,
   derived, user-override, and explicitly permitted demo-fixture provenance
   is retained without relabelling company evidence.

Rejected S3 models clear low/base/high price values, retain the selected
parameter source/type/label/layer, warning, unavailable reason, and
provenance-rich input/assumption metrics. Numerical formulas, scenario order,
fiscal dates, applicability isolation, and API/export shape are unchanged.

## Classification of the original 33 failures

The source failure list is the direct log evidence in
`coordinator-full-pytest.log` (33 failed, 410 passed, exit 1). Every entry
below is now covered by the passing full-suite run; no test was deleted,
skipped, xfailed, or weakened.

| Original failure | Classification and reconciliation |
|---|---|
| `test_acceptance_rejection_fixes.py::test_missing_cash_or_debt_disables_ev_and_dcf_preserves_pe_and_fcf` | Policy fixture adjustment: P/E now receives an explicit user source; missing cash/debt and raw derived FCFE isolation assertions remain unchanged. |
| `test_acceptance_rejection_fixes.py::test_bank_applicability_disables_ev_dcf_fcf_preserves_pe` | Policy fixture adjustment: P/E receives an explicit user source; bank applicability remains the reason for EV/DCF/FCF rejection. |
| `test_audit_issues_01_02_regression_r5.py::test_r5_api_isolates_missing_capex_in_production_response[actual]` | API fixture adjustment: explicit P/E user source keeps the independent model usable while DCF still exposes missing CapEx/FCFF. |
| `...test_r5_api_isolates_missing_capex_in_production_response[derived]` | Same policy fixture adjustment for derived FCFF input; no DCF fallback price is restored. |
| `...test_r5_api_isolates_missing_capex_in_production_response[fixture]` | Same policy fixture adjustment; the non-demo fixture remains isolated and does not bypass governance. |
| `test_audit_issues_01_02_regression_r6.py::test_anchored_relative_revenue_drivers_reach_dcf_and_reconcile_inputs` | Real integration fixture correction: supplied aligned actual `FY2026 YTD` FCFF with fiscal start/end, FY end, actual source, and valuation-date `as_of`; DCF also carries explicit user WACC/growth provenance. |
| `test_audit_issues_03_04_regression.py::test_issue03_production_api_selects_company_and_industry_independently` | Policy expectation adjustment: valid company-history P/E remains available; malformed EV/EBITDA selection now asserts unavailable/no prices for configured fallback instead of indexing a nonexistent price. |
| `...test_issue04_dcf_growth_fade_reaches_each_scenario_terminal_rate` | Direct DCF fixture now deliberately marks WACC and terminal growth as user assumptions; growth-fade numerical assertions are unchanged. |
| `...test_issue04_sensitivity_recomputes_growth_path_for_changed_terminal_rate` | Same explicit DCF provenance correction; sensitivity trajectory assertions are unchanged. |
| `test_backend_acceptance_revisions.py::test_ttm_fcff_is_derived_into_a_new_forecast_period` | Direct DCF fixture now uses explicit user WACC/growth provenance; derived-period assertions remain. |
| `...test_dcf_projection_periods_are_contiguous_and_fixture_is_not_consensus` | Same explicit DCF provenance correction; fiscal-period and fixture-source assertions remain. |
| `...test_dcf_growth_exposes_raw_and_effective_capped_metrics` | Same explicit DCF provenance correction; raw/effective growth cap assertions remain. |
| `...test_dcf_prefers_historical_fcff_over_actual_operating_growth` | Live-style fixture now supplies aligned actual FY1 YTD metadata (`FY2025 YTD`, start/end, FY anchor, actual source); historical-growth preference assertion remains. |
| `...test_model_exception_isolation_preserves_other_valuations` | Partial-result fixture explicitly authorizes FCF-yield and DCF parameters; P/E exception isolation and independent EV/FCF/DCF assertions remain. |
| `test_dcf.py::test_dcf_y1_y2_actual_estimates` | Direct DCF WACC/growth are explicit user assumptions; Y1/Y2 numerical estimate assertions remain. |
| `test_dcf.py::test_dcf_full_avgo` | Same explicit DCF provenance correction; all three scenarios remain required. |
| `test_dcf.py::test_dcf_bear_lower_than_bull` | Same explicit DCF provenance correction; monotonicity assertion remains. |
| `test_e2e_valuation_integrity_export.py::test_e2e_avgo_baseline_valuation_provenance_and_export_fields` | API fixture now sends deliberate DCF WACC/terminal-growth overrides; all provenance, sensitivity, export, and no-composite assertions remain. |
| `test_ev_ebitda.py::test_low_less_than_high` | Direct EV/EBITDA fixture now deliberately marks its parameter as a user override; price ordering remains. |
| `test_fatal_three_worker_c.py::test_fiscal_year_dcf_uses_stub_and_true_endpoint_times` | Legacy direct fixture is explicitly demo (`is_demo=True`) and uses explicit DCF parameters, preserving its documented compatibility day-ratio schedule assertions. |
| `...test_fiscal_start_keeps_full_fy1_without_proration` | Same explicit demo/direct DCF fixture treatment; fiscal-start assertions remain. |
| `...test_api_model_dump_contains_fiscal_timeline_fields` | Same explicit demo/direct DCF fixture treatment; serialized timeline assertions remain. |
| `test_fcf_yield.py::test_fcf_type_documented` | Direct FCF-yield fixture now deliberately marks yield parameters as user assumptions; FCFE labeling assertion remains. |
| `test_final_acceptance.py::test_tsm_grounded_per_ads_basis_and_currency_isolation` | TSM P/E fixture now explicitly authorizes the user scenario; USD-per-ADS and TWD statement currency isolation assertions remain. |
| `test_forward_fcfe_borrowing_isolation.py::test_explicit_forward_fcfe_override_is_eligible_and_ignores_ttm_history` | Explicit forward FCFE input is paired with an explicit user yield parameter; forward-vs-TTM borrowing assertions remain. |
| `test_forward_pe.py::test_formula_and_description` | Direct P/E fixture now deliberately marks the P/E parameter as user supplied; formula/steps/input assertions remain. |
| `test_live_and_mock_provider.py::test_financial_institution_models_applicability` | Bank P/E test now supplies explicit user P/E provenance; EV/DCF/FCF bank applicability remains unchanged. |
| `test_p0_p1_deep_remediation.py::TestP0CDCFDiscounting::test_pure_calculator_center_equivalence` | Direct DCF fixture is explicitly demo and uses user WACC/growth provenance; center-cell math assertion remains. |
| `...TestP1FModelWeightsAndPolicy::test_cashflow_group_policy_message_visibility` | Explicit analyst FCFE input is paired with an explicit user yield parameter; cashflow policy metadata assertions remain. |
| `test_p0_p1_integrity.py::test_share_reconciliation_multi_class` | All direct model parameters are explicitly authorized; multi-class share reconciliation and price-bridge assertions remain. |
| `test_p0_p1_integrity.py::test_dcf_calendar_anchored_dates` | Direct DCF fixture is explicitly demo with user WACC/growth; calendar and PV identity assertions remain. |
| `test_p0_p1_integrity.py::test_dcf_sensitivity_matrix` | Same explicit demo/direct DCF treatment; sensitivity monotonicity and TV-dependence assertions remain. |
| `test_service_independent_acceptance.py::TestModelExceptionIsolation::test_valuation_service_propagates_partial_results` | Partial service fixture explicitly authorizes independent EV/EBITDA and FCF-yield parameters, so missing forward EPS still fails only P/E while at least one other model remains available. |

## Provenance and financial-fidelity evidence

The governed S3 path remains:

`provider/raw snapshot → Normalizer → multiple resolver or explicit forward
metric selection → governed P/E, EV/EBITDA, or FCFE-yield engine →
assemble_response → API/export JSON`.

For rejected assumptions, the selected forward metric still carries its
`period`, `as_of`, currency/unit, source/source_type, estimate flag,
confidence, and notes; the assumption metrics retain the rejected source
lineage and an explicit governance marker. No missing value is converted to a
financial zero, no FX or target price is invented, and the three S3 models
remain independent. The R6 and historical-FCFF integration fixtures carry
explicit fiscal-YTD period/start/end/FY anchor and valuation-date `as_of`
metadata, so their successful DCF paths do not rely on day-ratio fallback.

## Verification

| Command (cwd `D:/workshop/stock-valuation`) | Exit | Result / artifact |
|---|---:|---|
| `git status --short --branch; git log -5 --oneline --decorate; git diff --stat; git diff --name-only` | 0 | Baseline and protected dirty-worktree inventory. |
| `$env:DATA_PROVIDER='demo'; .venv/Scripts/python.exe -m pytest -q backend/tests/test_s3_parameter_governance.py` | 0 | 17 passed, 2 warnings; source-conflict, fixture-gate, unknown-provenance, explicit-user regressions. |
| `$env:DATA_PROVIDER='demo'; .venv/Scripts/python.exe -m pytest -q` | 0 | 450 passed, 2 warnings in 4.69s; raw stdout: [`integration-full-pytest.log`](integration-full-pytest.log), exit: [`integration-full-pytest.exit.txt`](integration-full-pytest.exit.txt). |
| Targeted S3/integration regression command covering all modified backend tests | 0 | 281 passed, 2 warnings in 2.00s; raw stdout: [`integration-targeted-pytest.log`](integration-targeted-pytest.log), exit: [`integration-targeted-pytest.exit.txt`](integration-targeted-pytest.exit.txt). |
| `PYTHONPATH=backend .venv/Scripts/python.exe -m py_compile` helper + three S3 engines | 0 | Current syntax check; [`integration-compile.log`](integration-compile.log), [`integration-compile.exit.txt`](integration-compile.exit.txt). |
| `git diff --check` plus owned/excluded path review | 0 | [`integration-owned-diff-review.txt`](integration-owned-diff-review.txt), [`integration-owned-diff-review.exit.txt`](integration-owned-diff-review.exit.txt). LF/CRLF warnings are Git working-copy normalization notices only. |

The full run includes the untouched S5/S6 test files and concurrent production
changes; all 450 tests pass under isolated demo provider mode. Live-network,
frontend, and deployment verification were not run and are not claimed.

Coordinator follow-up received after the passing run: the S5 worker is
reworking YTD date/currency acquisition and cumulative cash-flow normalization.
The S3-owned shared YTD fixtures now provide explicit fiscal anchors and
`financial_currency`; the 450-test result above is a valid current-worktree
snapshot but remains provisional for cross-worker acceptance until the S5
worker's new changes land and coordinator reruns the suite.

## Changed files in this dispatch

Worker-owned production:

- `backend/app/engines/parameter_governance.py` (shared S3 source gate;
  existing S3 file further hardened).
- `backend/app/engines/forward_pe.py`, `ev_ebitda.py`, `fcf_yield.py` (pass
  demo context into the gate; existing S3/F1 formulas and lineage retained).

Worker-owned tests/acceptance fixtures:

- `backend/tests/test_s3_parameter_governance.py`
- `backend/tests/test_acceptance_rejection_fixes.py`
- `backend/tests/test_audit_issues_01_02_regression_r5.py`
- `backend/tests/test_audit_issues_01_02_regression_r6.py`
- `backend/tests/test_audit_issues_03_04_regression.py`
- `backend/tests/test_backend_acceptance_revisions.py`
- `backend/tests/test_dcf.py`
- `backend/tests/test_e2e_valuation_integrity_export.py`
- `backend/tests/test_ev_ebitda.py`
- `backend/tests/test_fatal_three_worker_c.py`
- `backend/tests/test_fcf_yield.py`
- `backend/tests/test_final_acceptance.py`
- `backend/tests/test_forward_fcfe_borrowing_isolation.py`
- `backend/tests/test_forward_pe.py`
- `backend/tests/test_live_and_mock_provider.py`
- `backend/tests/test_p0_p1_deep_remediation.py`
- `backend/tests/test_p0_p1_integrity.py`
- `backend/tests/test_service_independent_acceptance.py`

Evidence/issue artifacts:

- `.scratch/fatal-three/issues/S3-fallback-parameter-governance.md`
- `.scratch/fatal-three/s3-s5-s6-20260912/integration-targeted-pytest.log`
  and `.exit.txt`
- `.scratch/fatal-three/s3-s5-s6-20260912/integration-full-pytest.log` and
  `.exit.txt`
- `.scratch/fatal-three/s3-s5-s6-20260912/integration-compile.log` and
  `.exit.txt`
- `.scratch/fatal-three/s3-s5-s6-20260912/integration-owned-diff-review.txt`
  and `.exit.txt`
- this `integration-report.md`

## Acceptance and handoff

- S3 fallback governance: PASS in direct engines, API serialization, and full
  suite.
- Fixture/demo gate and unknown-provenance rejection: PASS in 17 S3 tests.
- All 33 originally logged failures: PASS in the current pre-S5-rework
  snapshot after policy-aligned fixture or expectation reconciliation; the
  coordinator's post-S5-rework rerun remains pending.
- Financial formulas, lineage, dates, currency isolation, applicability, and
  model independence: PASS in targeted/full assertions.
- Live provider/frontend/deployment: NOT RUN (out of this worker's isolated
  acceptance evidence).
- Final cross-worker acceptance and any commit/push decision remain with the
  coordinator; S5 rework is an explicit pending cross-worker item. No true
  blocker remains within S3 ownership.
