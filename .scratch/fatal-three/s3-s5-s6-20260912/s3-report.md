# S3 worker report — fallback parameter governance

Date: 2026-09-12 Asia/Shanghai  
Task: `task_a630e578a15a`  
Dispatch: `ctx_2b385f231385`  
Worker terminal: `term_25e1b3e2-a605-49dc-bf9b-c1ece705c1ed`

## Objective and ownership

Closed the S3 fallback-parameter-governance issue at the direct engine and API
boundaries. Ownership was limited to `backend/app/engines/forward_pe.py`,
`backend/app/engines/ev_ebitda.py`, `backend/app/engines/fcf_yield.py`, the
additive `backend/app/engines/parameter_governance.py`,
`backend/tests/test_s3_*.py`, the S3 issue, and this report/evidence directory.
No `dcf.py`, `domain.py`, `projections.py`, provider, config, frontend, shared
test, or S5/S6 file was edited.

Actual execution route was the user-selected Codex Luna Max worker
(`codex` / `gpt-5.6-luna` / `max`), recorded in
`coordinator-state.md`; this was not quota fallback, `resets_at` is not
applicable, and no provider fallback occurred.

## Baseline and protected work

- Branch: `master`, tracking `origin/master`; HEAD: `7aaec80` (`修复三个致命问题`).
- Initial baseline command was run from `D:/workshop/stock-valuation`:
  `git status --short --branch; git log -5 --oneline --decorate; git diff --stat; git diff -- .; rg --files ...`; exit 0.
- Initial workspace already contained unrelated F1/S1/S2 work, including
  tracked modifications in provider/projections/shared tests and an existing
  49-addition/22-deletion modification to the owned
  `backend/app/engines/fcf_yield.py`. That F1 change was copied before editing
  to `s3-preexisting-owned/fcf_yield.py.before` and preserved.
- Before snapshots of all three owned engines are in
  `s3-preexisting-owned/{forward_pe,ev_ebitda,fcf_yield}.py.before`.
- During this task, S5/S6 concurrently modified `dcf.py`, `domain.py`, and
  created `terminal_governance.py`/S6 tests; those changes are not S3 work and
  remain untouched.
- No commit, push, cleanup, reset, or nested worker was used.

## Implementation

`parameter_governance.py` provides a source-type gate shared by all three
engines. `configured_fallback` is rejected after forward inputs are selected,
even when a caller lies about `selection_layer`; the returned unavailable model
has no low/base/high price values. It retains flat assumption aliases,
`source/source_label`, selected layer, a `configured_fallback_rejected`
governance marker, rejection warning, and provenance-rich input and assumption
metrics.

Validated source-backed historical/company or industry selections continue to
run independently. Explicit `USER_OVERRIDE` parameters continue to run as
user scenarios and are never relabelled as company evidence. For compatibility
with direct engine callers that pass a `ScenarioValues` field without source
metadata, the helper recognizes only that exact explicit-field shape (not the
application `DEFAULT_ASSUMPTIONS` object or an explicitly declared fallback)
and normalizes it to `user_override`.

The pre-existing F1 FCFE historical-slot isolation remains in `fcf_yield.py`;
S3 only adds yield-parameter governance and fallback provenance.

## Financial provenance chain

For a rejected default request, the existing normalized snapshot remains the
source (`forward_eps`, `forward_ebitda`, or forward FCFE with its `period`,
`as_of`, `unit`, `source`, `source_type`, `confidence`, and `is_estimated`). The
new governance boundary evaluates the selected assumption source before the
engine calculation; `configured_fallback` is retained in the assumption
metric, but no projection or price is produced. `ValuationService` passes that
unavailable `ModelValuation` through `assemble_response`, so API JSON preserves
the evidence and `unavailable_reason` without manufacturing a target price.

The executable lineage is `provider/raw snapshot → Normalizer →
resolve_multiple_assumptions (P/E and EV/EBITDA) / forward metric selection
(FCFE yield) → governed engine → assemble_response → API JSON`; S3 adds only the
governed engine boundary and does not replace upstream financial facts.

For source-backed history/industry, the existing `multiples` resolver remains
the source/normalizer and supplies derived scenario values plus selection
metadata to the engine. For request overrides, `apply_overrides` is the source
of `USER_OVERRIDE` scenario parameters and the engines preserve that label and
source type. No FX conversion, missing-to-zero conversion, or new financial
source was introduced.

## Acceptance matrix

| Criterion | Evidence | Status |
|---|---|---|
| Configured fallback blocked at direct P/E, EV/EBITDA, and FCFE-yield seams | `test_direct_multiple_engines_reject_configured_fallback`, `test_direct_fcf_yield_rejects_configured_fallback_and_keeps_forward_lineage`, and application-default test in `test_s3_parameter_governance.py` | PASS |
| No normal target/scenario price for rejected fallback | All rejected tests assert `available is False` and `low/base/high is None` | PASS |
| Rejected fallback provenance and unavailable reason retained | Flat assumptions, `assumption_metrics`, `input_metrics`, warning and reason assertions; API test checks serialized JSON | PASS |
| Reliable historical/industry selections remain usable | `test_reliable_selected_multiples_remain_available_independently` and industry-source test | PASS |
| Explicit user overrides remain usable and correctly labelled | `test_explicit_user_overrides_remain_usable_for_each_independent_model`, direct scenario test, and POST path exercised through API setup | PASS |
| Models remain independent | Historical P/E stays available while EV fallback is rejected; API asserts P/E/EV available while FCF fallback is unavailable | PASS |
| Targeted demo/mocked API regression | `.scratch/fatal-three/s3-s5-s6-20260912/s3-targeted-pytest-post-parallel.log`: 13 passed, 2 warnings, exit 0 | PASS |
| Python syntax check | `s3-compile-final.log`: `py_compile` exit 0 | PASS |
| Full backend integration | `s3-full-pytest-final.log`: 391 passed, 34 failed, exit 1. Failures are legacy fallback-price expectations and concurrent S5/S6 DCF expectations; no S3 targeted test failed. | NOT PASS / coordinator integration pending |
| Live provider/API network verification | Not run; scope used isolated demo fixtures and mocked snapshots as contracted | NOT RUN |
| Frontend verification | Out of S3 ownership | NOT RUN |

## Commands and artifacts

All commands ran with cwd `D:/workshop/stock-valuation` unless noted.

| Command | Exit | Artifact |
|---|---:|---|
| `git status --short --branch; git log -5 --oneline --decorate; git diff --stat; git diff -- .; rg --files ...` | 0 | terminal baseline output |
| Snapshot copies with `New-Item`/`Copy-Item` for the three owned engines | 0 | `s3-preexisting-owned/` |
| `$env:PYTHONPATH='backend'; .venv/Scripts/python.exe -m py_compile backend/app/engines/parameter_governance.py backend/app/engines/forward_pe.py backend/app/engines/ev_ebitda.py backend/app/engines/fcf_yield.py` | 0 | `s3-compile-final.log` |
| `$env:DATA_PROVIDER='demo'; .venv/Scripts/python.exe -m pytest -q backend/tests/test_s3_parameter_governance.py backend/tests/test_audit_issues_03_04_rework_r4.py` | 0 | `s3-targeted-pytest-final.log` and post-parallel rerun |
| `$env:DATA_PROVIDER='demo'; .venv/Scripts/python.exe -m pytest -q` | 1 | `s3-full-pytest-final.log` |
| `git diff --check -- backend/app/engines/forward_pe.py backend/app/engines/ev_ebitda.py backend/app/engines/fcf_yield.py` | 0 | terminal output |
| `ruff check ...` | NOT RUN | `ruff` is not installed in the environment |

## Changed files

Worker-authored S3 files:

- `backend/app/engines/parameter_governance.py` (new shared policy helper)
- `backend/app/engines/forward_pe.py`
- `backend/app/engines/ev_ebitda.py`
- `backend/app/engines/fcf_yield.py` (pre-existing F1 diff retained; S3 gate added)
- `backend/tests/test_s3_parameter_governance.py`
- `.scratch/fatal-three/issues/S3-fallback-parameter-governance.md`
- `.scratch/fatal-three/s3-s5-s6-20260912/s3-preexisting-owned/*`
- `.scratch/fatal-three/s3-s5-s6-20260912/s3-*-pytest*.log`
- `.scratch/fatal-three/s3-s5-s6-20260912/s3-compile-final.log`

Concurrent/pre-existing files deliberately not counted as S3 changes include
`dcf.py`, `domain.py`, `terminal_governance.py`, `test_s6_terminal_governance.py`,
provider/projections files, F1/S1/S2 tests, and the prior live-validation
artifacts.

## Risks and pending coordinator actions

1. Existing shared tests still assert that configured P/E, EV/EBITDA, FCFE-yield,
   or DCF fallback values produce prices. They need policy-aware expected
   unavailable results or explicit user/source-backed parameters; S3 did not
   edit those shared tests per contract.
2. The full-suite DCF failures overlap concurrent S5/S6 work and require the
   coordinator's combined integration pass after those workers settle.
3. The direct explicit-scenario compatibility rule intentionally relies on
   Pydantic `model_fields_set` plus the exact legacy label; callers that
   explicitly set any source/label/layer metadata to fallback are fail-closed.
   Coordinator may choose to tighten this further when updating legacy tests.
4. No live network run was claimed. Demo fixtures are deterministic test-only
   evidence and do not broaden production support.

Stopping point: S3 implementation, targeted evidence, issue update, and this
report are complete; final cross-worker acceptance remains with the
coordinator.
