# S1 worker report — NTM borrowing period alignment

Date: 2026-09-12 (Asia/Shanghai)  
Task/Dispatch: the current worker shell did not expose an authoritative Orca Task ID/Dispatch ID; do not invent identifiers. The parent coordinator must attach this report to the active S1 lifecycle envelope.  
Provider/model: OpenAI Codex runtime / GPT-5 (exact deployment identifier not separately exposed); no provider fallback was used.  
Working directory: `D:\workshop\stock-valuation`

## Objective and ownership

S1 required the NTM FCFE bridge's net borrowing to cover the same rolling NTM period as the other forward drivers. This worker owned the borrowing selection/normalization in `backend/app/services/projections.py`, period metadata in `backend/app/providers/yfinance_provider.py`, and S1 regression coverage/reporting. `backend/app/engines/fcf_yield.py` was not edited by this worker; it is dirty because a concurrent F1 worker owns that change.

## Baseline

Before S1 edits, the repository was on `master` at `7aaec80` (`修复三个致命问题`), tracking `origin/master`, with no tracked diff. The pre-existing untracked artifacts were `.scratch/fatal-three/current-severity-reassessment-20260912.md` and `.scratch/fatal-three/issues/`; they were preserved. A concurrent worker subsequently changed the F1 surface (`fcf_yield.py`, portions of `test_forward_fcfe_borrowing_isolation.py`, and `test_p0_p1_deep_remediation.py`); those changes were preserved and are not claimed as S1-owned.

## Implementation

### Projection resolver

`projections.py` now normalizes both forward borrowing slots, then resolves by requested horizon:

- `ntm` accepts an explicitly labelled `NTM` metric directly.
- When no direct NTM metric exists, it requires both fiscal values to be period-aligned to the verified `forecast_fiscal_year_end`, and applies the existing `calculate_ntm_weights()` remaining-current-FY/next-FY day weights. The derived metric retains `source_type=derived`, both source periods, confidence minimum, `as_of`, unit and an auditable blend note.
- A provider-labelled current fiscal stub (for example `FY2026E_STUB`) plus aligned FY2 is converted by addition; a plain `FY1E` is never treated as that stub or relabelled as rolling NTM.
- `current_fy` and `next_fy` select only their matching fiscal slot. Missing or mismatched periods are rejected with an explicit unavailable warning; the other slot is never substituted.
- `driver_net_borrowing` is authoritative and bypasses provider-period rejection, preserving the existing `user_override` bridge metadata.

### Provider metadata

`yfinance_provider.py` now recognizes explicit NTM aliases, carries upstream period metadata, derives `FY{year}E` labels only from a verified `nextFiscalYearEnd`, and emits `forward_{slot}y_unverified` plus a warning when an annual field lacks a fiscal anchor. It no longer invents `FY1E`/`FY2E` as a default period for a value whose horizon is unproven. Forward borrowing remains separate from historical `net_borrowing_ttm`; no TTM value is used as a forward driver.

### Financial provenance chain

`source → normalizer → projection → engine → API/export` is preserved as follows: an explicit Yahoo/provider field enters `get_cash_flow()` with `period`, `as_of`, currency/unit, source/source type, estimated flag and confidence; the existing provider attachment/normalizer transports the metadata into the snapshot; `_normalize_forward_borrowing_metric()` validates the candidate and `_resolve_forward_borrowing_metric()` enforces horizon alignment or records an unavailable reason; the FCFF/FCFE bridge uses only the resolved forward value (or the explicit request override); the existing valuation service/API exposes the resulting `financial_bridge`. Historical `net_borrowing_ttm` remains display/audit-only. `fcf_yield.py` was not changed by S1.

## Acceptance matrix

| Criterion | Result | Evidence |
|---|---|---|
| Direct NTM borrowing is accepted only with an explicit NTM period | PASS | `test_ntm_does_not_relabel_fy1_borrowing_as_rolling_ntm`; direct NTM/provider alias tests |
| FY1/FY2 values are converted only with verified fiscal anchoring | PASS | `test_ntm_blends_aligned_fy1_and_fy2_borrowing_with_fiscal_weights` |
| True current-FY stub + FY2 conversion is supported; plain FY1E is not a rolling NTM | PASS | `test_ntm_accepts_only_an_explicit_current_fy_stub_plus_fy2_conversion`; single FY1 test |
| A stub is not accepted as a complete current FY | PASS | `test_current_fy_does_not_treat_a_stub_as_a_full_fiscal_year` |
| `next_fy` uses FY2 and rejects a mismatched period | PASS | `test_next_fy_uses_fy2_only_and_rejects_period_mismatch` |
| Explicit net-borrowing override wins over provider mismatch | PASS | `test_explicit_net_borrowing_override_survives_provider_period_mismatch` |
| Provider metadata is NTM/verified FY/unverified, never an invented rolling FY1E | PASS | provider integration, NTM alias, and unverified-anchor tests |
| No S1 change to `fcf_yield.py`; no commit/push | PASS | worker file ownership and final status review |

## Verification

All commands below ran in `D:\workshop\stock-valuation` using the repository `.venv`.
Command timestamps were not emitted per invocation by the shell; all listed output was captured on 2026-09-12 (Asia/Shanghai). No live/network provider call or external side effect was performed.

1. Baseline: `git status --short --branch` and `git log -5 --oneline --decorate` — PASS; HEAD and pre-existing untracked artifacts recorded above.
2. Red regression before the fix: `.\.venv\Scripts\python.exe -m pytest -q backend/tests/test_s1_ntm_borrowing_period_alignment.py` — expected FAIL, observed `3 failed, 1 passed`; the failures showed NTM taking FY1, NTM using an unweighted FY1 value, and `next_fy` accepting a mismatched FY1-period candidate.
3. Focused regression after the fix: `.\.venv\Scripts\python.exe -m pytest -q backend/tests/test_s1_ntm_borrowing_period_alignment.py backend/tests/test_forward_fcfe_borrowing_isolation.py backend/tests/test_forward_fcfe_borrowing_api.py` — PASS, `21 passed, 2 warnings`.
4. Syntax: `.\.venv\Scripts\python.exe -m compileall -q backend/app/services/projections.py backend/app/providers/yfinance_provider.py` — PASS.
5. Full backend suite: `.\.venv\Scripts\python.exe -m pytest -q` — PASS, `398 passed, 2 warnings`.
6. Diff hygiene: `git diff --check` — PASS (only Git's LF/CRLF normalization warnings for dirty shared files).

The two warnings are dependency deprecations from Starlette/httpx and AnyIO's `BlockingPortal` alias; they do not fail the tests.

## Changed files and shared-worktree boundary

S1 changes are in:

- `backend/app/services/projections.py` — period-aware borrowing resolver, NTM fiscal conversion, mismatch/unavailable handling and override bypass.
- `backend/app/providers/yfinance_provider.py` — explicit NTM aliases and verified/unverified period metadata.
- `backend/tests/test_s1_ntm_borrowing_period_alignment.py` — ten S1 regressions (new, untracked at report time).
- `backend/tests/test_forward_fcfe_borrowing_api.py` — existing explicit-provider fixture/assertion now labels the default NTM case as `NTM`.
- `backend/tests/test_forward_fcfe_borrowing_isolation.py` — existing provider-forward fixture/assertion now labels the NTM case as `NTM`; the same file also contains concurrent F1 worker changes and must be reviewed by the coordinator as a shared file.
- `.scratch/fatal-three/worker-s1-report-20260912.md` — this report.

The current shared-worktree status also contains concurrent `backend/app/engines/fcf_yield.py`, `backend/tests/test_p0_p1_deep_remediation.py`, the pre-existing `.scratch` artifacts, and the concurrent F1 report. None were reverted or cleaned.

## Risks and unresolved items

- The standard Yahoo Finance payload normally does not expose forward net borrowing; live retrieval of a new upstream field was not attempted. The provider path is fail-closed when period metadata is absent.
- The annual FY1/FY2-to-NTM branch assumes `forward_net_borrowing_1y` and `_2y` are full-fiscal estimates when their periods are explicitly/anchored as FY values; a provider must label a remaining stub explicitly for stub-plus-FY2 arithmetic.
- No commit or push was performed. The parent coordinator must review the shared diff, attach the active Task/Dispatch IDs to the `worker_done` envelope, and settle the worker according to Orca lifecycle rules.
