# Final bridge isolation report

## Objective

Fix the production live-path leak where an unavailable DCF response exposed a
partial `financial_bridge.dcf_forecasts` list. The final path now keeps FCFE
and forward-borrowing isolation intact, keeps complete fiscal DCF timelines,
and does not reintroduce Composite valuation; no commit or push was performed.

## Baseline and execution context

- Working directory: `D:\workshop\stock-valuation`
- Dispatch: `task_c0cd5484b9c9` / `ctx_f8d3daddb17d`
- Baseline before this continuation: `master...origin/master`, `HEAD 68e98d4`
  (`origin/master`); the worktree already contained shared Worker A/C and
  earlier Worker B edits plus their reports/artifacts.
- Existing dirty/untracked changes were preserved; no `git clean`, reset,
  checkout, commit, or push was run.
- Requested runtime: Codex Luna Max max. Provider/model telemetry and
  `resets_at` are not exposed by this worker terminal; no fallback event or
  external side effect was observed.

## Implementation

- `backend/app/services/projections.py`: only populate bridge
  `dcf_forecasts` when both production-eligible FY1 and FY2 FCFF metrics are
  finite and positive. Partial FCFF driver calculations remain available for
  FCFE reconciliation but cannot look like DCF forecast inputs.
- `backend/app/services/valuation_service.py`: after independent engines run,
  apply a production-path guard that copies the bridge and forces
  `dcf_forecasts=[]` whenever the DCF model is unavailable. Complete DCF
  responses retain Worker C fiscal start/end dates, stub/proration, discount
  time/factor, and PV metadata unchanged.
- `backend/tests/test_forward_fcfe_borrowing_api.py`: added a parameterized
  API regression for missing FY1 and missing FY2 revenue estimates. It asserts
  DCF unavailable, empty bridge forecasts, no FCFF keys in DCF engine inputs,
  FCFE bridge preservation, and explicit forward borrowing `321` separate from
  historical TTM borrowing `500`.

## Verification

All commands ran from `D:\workshop\stock-valuation`:

| Command | Exit | Result |
|---|---:|---|
| `\.venv\Scripts\python.exe -m pytest backend/tests/test_forward_fcfe_borrowing_api.py backend/tests/test_audit_issues_01_02_regression_r6.py -q` | 0 | `21 passed, 2 warnings` |
| `\.venv\Scripts\python.exe -m pytest backend/tests/ -q` | 0 | `386 passed, 2 warnings` |
| `git diff --check` | 0 | No whitespace errors; only existing LF/CRLF conversion warnings. |

The focused regression failed before the guard with one leaked forecast for
each incomplete FY case, then passed after the projections and service guards
were applied. The complete fiscal DCF and prior Worker B borrowing tests remain
covered by the full backend run.

## Risks / pending

The worktree remains concurrently dirty in shared Worker A/C surfaces; this
worker changed only the Worker B projection/service integration and its API
regression. Two pre-existing Starlette/httpx deprecation warnings remain; no
new test failure or warning was introduced.
