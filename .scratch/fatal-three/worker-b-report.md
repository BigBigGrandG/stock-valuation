# Worker B — Forward FCFE borrowing isolation

Date: 2026-09-12 (Asia/Shanghai)  
Task: `task_19d39dae5fca`  
Dispatch: `ctx_549db03db5a9`  
Provider/model: Codex Luna Max max (per dispatch instruction; runtime capability not independently verified)

## Baseline and ownership

- CWD: `D:\workshop\stock-valuation`
- Baseline commands before edits:
  - `git status --short --branch` → `## master...origin/master`; only the untracked task contract `.scratch/fatal-three-implementation.md` was present.
  - `git log -5 --oneline --decorate` → `68e98d4 (HEAD -> master, origin/master) 修复两个严重问题`, followed by `d0a7d62`, `11b0495`, `3652146`, `86490f9`.
  - Initial tracked diff was empty; no commit, push, clean, reset, or destructive operation was run.
- Worker B changed only these owned product/test files:
  - `backend/app/providers/base.py`
  - `backend/app/providers/statement_aggregator.py`
  - `backend/app/providers/yfinance_provider.py`
  - `backend/app/services/projections.py`
  - `backend/app/engines/fcf_yield.py`
  - `backend/tests/test_forward_fcfe_borrowing_isolation.py` (new)
  - this report (new)
- During the run, other workers changed shared/out-of-scope files (including `domain.py`, `valuation_service.py`, `dcf.py`, frontend files, README/docs, and Worker A/C tests). Those changes were preserved and are not attributed to Worker B.

## Implemented

1. Added typed provider-boundary fields for explicit `forward_net_borrowing_1y/2y` with period, as-of, currency/unit, source, source type, confidence, estimate flag, notes, plus explicit historical borrowing metadata.
2. Added provider snapshot transport for explicit forward borrowing. It accepts provider/analyst/reliable-derived metadata, fails closed on invalid/fallback candidates, and never maps `net_borrowing_ttm` into a forward field.
3. Made statement aggregation emit historical net borrowing separately and explicit empty forward slots/warnings. Yahoo extraction reads only explicitly forecast-labelled upstream keys; standard Yahoo responses therefore return no forward borrowing instead of synthesizing it from TTM.
4. Changed the FCFE bridge to use, in order, a user override, an explicit forward provider metric, or normalized zero. The bridge exposes forward status/source/period/as-of and historical TTM value separately; missing forward borrowing adds an auditable warning.
5. Downgraded historical TTM FCFE fallback to `DataQuality.LOW`, marks it as a historical proxy, and prevents a TTM-labelled forward field from being treated as forward FCFE.

## Acceptance matrix

| Acceptance | Result | Evidence |
|---|---|---|
| Case A: TTM borrowing cannot enter forward FCFE; zero/unavailable is explicit | PASS | `test_case_a_ttm_borrowing_is_not_used_and_missing_forward_normalizes_zero` |
| Case B: user forward borrowing override is used | PASS | `test_case_b_user_forward_override_is_the_only_debt_flow_used` |
| Case C: explicit provider forward borrowing is used with metadata | PASS | `test_case_c_explicit_provider_forward_borrowing_is_used_with_metadata`; provider boundary replay test also passes |
| Historical TTM remains display/audit-only | PASS | Case A bridge asserts historical `500`, forward `0`, period `TTM` vs `forward_unavailable` |
| FCFE quality/unavailable semantics are honest; no high-quality TTM proxy | PASS | `test_historical_ttm_fallback_is_not_high_quality_forward_fcfe` asserts available fallback has `LOW` quality and proxy warning |
| META/GOOG replay without TTM borrowing | NOT RUN | No live/replay artifact was executed in this worker; no live values were fabricated |
| Full backend regression | PASS | `.\\.venv\\Scripts\\python.exe -m pytest backend/tests/ -q` from repo root → exit 0, `380 passed, 2 warnings` |

## Verification commands

All commands below were run from the stated CWD and exited 0 unless noted:

- `D:\workshop\stock-valuation\backend`: `..\\.venv\\Scripts\\python.exe -m pytest tests/test_forward_fcfe_borrowing_isolation.py -q` → `6 passed`.
- `D:\workshop\stock-valuation\backend`: `..\\.venv\\Scripts\\python.exe -m pytest tests/test_fcf_yield.py tests/test_live_and_mock_provider.py -q` → `14 passed, 2 warnings`.
- `D:\workshop\stock-valuation\backend`: projection/provider regression set (`test_p0_p1_deep_remediation.py`, `test_production_pipeline_contract.py`) → `27 passed, 2 warnings`; (`test_acceptance_rejection_fixes.py`, `test_round2_acceptance.py`) → `24 passed`; `test_service_independent_acceptance.py` → `82 passed, 2 warnings`.
- `D:\workshop\stock-valuation\backend`: `..\\.venv\\Scripts\\python.exe -m compileall -q app/providers/base.py app/providers/statement_aggregator.py app/providers/yfinance_provider.py app/services/projections.py app/engines/fcf_yield.py` → exit 0.
- `D:\workshop\stock-valuation`: `git diff --check -- backend/app/providers/base.py backend/app/providers/statement_aggregator.py backend/app/providers/yfinance_provider.py backend/app/services/projections.py backend/app/engines/fcf_yield.py` → exit 0.
- `D:\workshop\stock-valuation`: final `git status --short --branch` was captured before delivery; shared concurrent edits remain dirty and were not cleaned or reverted.

## Source-to-engine evidence

`provider raw CashFlowData/ForwardEstimatesData → FinancialDataProvider._attach_forward_borrowing (explicit metadata only) → projections._normalize_forward_borrowing_metric → forward FCFE bridge → fcf_yield quality/warnings`. The bridge preserves `historical_net_borrowing`, `historical_net_borrowing_period`, `forward_net_borrowing`, status/source/period/as-of/unit, and warning fields. Missing forward borrowing is represented as a normalized zero decision, not as a historical fact.

## Risks and unresolved items

- The live `ValuationService` route calls its own `Normalizer.normalize_provider_data` directly. That normalizer is in a Worker A shared dirty surface and currently drops the new raw forward-borrowing fields; direct provider snapshot transport and projection-level cases pass, but Coordinator must add the minimal normalizer/domain transport after Worker A's shared-surface work for Case C to be API-end-to-end. This was escalated through Orca (`msg_6cb9caa218ad`); Worker B did not edit Worker A/C files.
- META/GOOG real/replay verification was not run by this worker, so their current online payload behavior is `Not verified`. Yahoo standard payloads are fail-closed when no explicit forward borrowing key exists.
- No commit or push was performed. Stop point: Coordinator integration and final cross-worker acceptance.
