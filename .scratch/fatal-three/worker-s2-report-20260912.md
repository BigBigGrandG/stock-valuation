# S2 worker report — Forward FCFF driver quality and lineage

Date: 2026-09-12 (Asia/Shanghai)  
Task/Dispatch: the current worker shell did not expose an authoritative Orca Task ID/Dispatch ID; no identifiers are invented.  
Provider/model: OpenAI Codex runtime / GPT-5 (exact deployment identifier not separately exposed); no provider fallback was used.  
Working directory: `D:\workshop\stock-valuation`

## Objective and ownership

S2 required Forward FCFF to reduce mechanical dependence on one TTM ratio for EBITDA margin, D&A, CapEx, ΔNWC and tax, while retaining a reproducible financial provenance chain. Ownership was the driver resolver, selection, period/quality checks, bridge lineage and related regression coverage in `backend/app/services/projections.py` and `backend/tests/test_s2_forward_fcff_driver_lineage.py`.

The existing S1 period-aware borrowing resolver in `projections.py` was preserved. `backend/app/engines/fcf_yield.py` and provider files were not edited by this worker; their dirty state is concurrent/pre-existing work and remains untouched.

## Baseline and repository safety

Before inspection/editing, the baseline commands were run:

```text
git status --short --branch
## master...origin/master
 M backend/app/engines/fcf_yield.py
 M backend/app/providers/yfinance_provider.py
 M backend/app/services/projections.py
 M backend/tests/test_forward_fcfe_borrowing_api.py
 M backend/tests/test_forward_fcfe_borrowing_isolation.py
 M backend/tests/test_p0_p1_deep_remediation.py
?? .scratch/fatal-three/current-severity-reassessment-20260912.md
?? .scratch/fatal-three/issues/
?? .scratch/fatal-three/worker-f1-report-20260912.md
?? .scratch/fatal-three/worker-s1-report-20260912.md
?? backend/tests/test_s1_ntm_borrowing_period_alignment.py

git log -5 --oneline --decorate
7aaec80 (HEAD -> master, origin/master) 修复三个致命问题
68e98d4 修复两个严重问题
d0a7d62 修复致命问题
11b0495 MVP版本
3652146 提交
```

Exit code: 0 for both commands. The pre-existing/concurrent changes and untracked artifacts were preserved. No `git clean`, reset, commit, push, provider call or external side effect was performed.

## Implementation

The driver hierarchy is now explicit and auditable:

1. Request override.
2. Reliable explicit forward NTM or aligned FY1/FY2 amount/ratio candidates.
3. Day-weighted NTM blend of two aligned annual candidates, retaining both annual periods and `as_of` metadata.
4. Multi-period historical ratio median, requiring at least two independently dated observations and, for amount histories, provenance-rich revenue denominators.
5. Provenance-rich industry comparable ratio.
6. Single-period TTM ratio/rate only as a final degraded fallback, with `is_estimated=True`, a `historical_ttm_ratio`/`historical_ttm_rate` lineage type and an explicit warning.
7. Missing data remains `unavailable`; the resolver does not zero-fill D&A, CapEx or ΔNWC.

Forward adapter candidates accept the existing normalized extensibility shapes (explicit forward attributes, forward driver mappings and grouped `multiple_candidates`) without changing the domain/provider contract. Bare or metadata-incomplete adapter numerics cannot pass the reliable-forward, historical multi-period or industry gates. Forward EBITDA amount and direct EBITDA-margin candidates are distinguished from ratios; explicit FY DCF construction uses per-year values where present and does not relabel a rolling NTM amount as a full fiscal year.

`financial_bridge` now carries top-level `warnings`/`driver_warnings`; each `drivers_source` entry retains `type`, `source`, `source_type`, `as_of`, `period`, `confidence`, `is_estimated`, `kind`, `lineage` and driver-specific warnings. Derived FCFF notes include selected-driver warnings, preserving the `source → normalizer → projection → engine/API` audit path.

## Acceptance matrix

| Criterion | Result | Evidence |
|---|---|---|
| TTM ratios are not silently advertised as forward quality | PASS | `test_s2_single_ttm_ratios_are_explicitly_degraded_and_traceable` |
| Reliable FY1/FY2 forward candidates outrank TTM and use NTM weights | PASS | `test_s2_reliable_forward_driver_candidates_outrank_ttm_and_ntm_blend` |
| Multi-period historical ratios outrank single TTM ratio and retain periods | PASS | `test_s2_multi_period_history_beats_ttm_ratio_and_keeps_periods` |
| Industry comparable is usable with complete provenance | PASS | CapEx and EBITDA-margin industry tests |
| Metadata-poor candidate is not promoted to synthetic evidence | PASS | `test_s2_metadata_poor_history_does_not_become_synthetic_multi_period_evidence` |
| Missing D&A/CapEx/ΔNWC stays unavailable with no fabricated value | PASS | `test_s2_missing_driver_stays_unavailable_without_zero_fill` |
| S1 borrowing period alignment and existing R3–R6 behavior remain green | PASS | Focused regression command below |
| Forbidden files untouched by this worker | PASS | no worker edits to `fcf_yield.py` or provider files |

## Verification

All commands ran in `D:\workshop\stock-valuation` using the repository `.venv`.

1. S2 tests: `PYTHONPATH=backend .\.venv\Scripts\python.exe -m pytest -q backend/tests/test_s2_forward_fcff_driver_lineage.py` — exit 0, `7 passed`.
2. S2 + S1 + R3–R6 focused regressions: `PYTHONPATH=backend .\.venv\Scripts\python.exe -m pytest -q backend/tests/test_s2_forward_fcff_driver_lineage.py backend/tests/test_s1_ntm_borrowing_period_alignment.py backend/tests/test_audit_issues_01_02_regression_r3.py backend/tests/test_audit_issues_01_02_regression_r4.py backend/tests/test_audit_issues_01_02_regression_r5.py backend/tests/test_audit_issues_01_02_regression_r6.py` — exit 0, `62 passed, 2 warnings`.
3. Full backend suite: `PYTHONPATH=backend .\.venv\Scripts\python.exe -m pytest -q` — exit 0, `405 passed, 2 warnings`.
4. Syntax: `.\.venv\Scripts\python.exe -m compileall -q backend/app/services/projections.py backend/tests/test_s2_forward_fcff_driver_lineage.py` — exit 0.
5. Diff hygiene: `git diff --check` — exit 0; Git emitted only LF/CRLF normalization warnings for dirty shared files.
6. Final status: `git status --short --branch` — exit 0; expected shared dirty files plus the new S2 test/report remain; no commit/push.

The two pytest warnings are dependency deprecations from Starlette/httpx and AnyIO's `BlockingPortal` alias; they do not fail the suite. No live/network provider retrieval was run, so live adapter availability for new optional driver candidates remains unverified.

## Repository changes and shared-worktree boundary

S2-owned changes:

- `backend/app/services/projections.py` — forward/multi-period/industry/TTM driver hierarchy, quality gates, ratio/amount handling, bridge lineage/warnings and FY projection safeguards. This file also contains the pre-existing S1 edits from the shared worktree; they were retained.
- `backend/tests/test_s2_forward_fcff_driver_lineage.py` — seven S2 regression tests.
- `.scratch/fatal-three/worker-s2-report-20260912.md` — this report.

The status also includes concurrent/pre-existing `fcf_yield.py`, `yfinance_provider.py`, S1/F1 tests and reports, and severity artifacts. They were not reverted or claimed.

## Risks and unresolved items

- Optional forward D&A/CapEx/ΔNWC/tax and comparable candidates are consumed when an adapter supplies complete metadata; no provider change was made in this scoped worker, so live availability is not verified.
- A single aligned annual forward driver used for an NTM request is explicitly marked with a degraded-proxy warning. A rolling NTM amount is not reused as a full FY amount for DCF; missing per-year values remain unavailable except the existing period-mismatch annual amount compatibility path.
- The statutory tax fallback remains available but is explicitly marked `configured_fallback` and warned when company-specific evidence is absent.
- No commit or push was performed. Parent coordinator must review the shared diff and attach the active lifecycle identifiers/outcome using the coordinator's `worker_done` protocol.

## Resume Here

Review `backend/app/services/projections.py` and the seven-test S2 file, then merge/settle the shared worktree without reverting S1/F1 changes. Current verification is green: focused `62 passed`, full backend `405 passed`.
