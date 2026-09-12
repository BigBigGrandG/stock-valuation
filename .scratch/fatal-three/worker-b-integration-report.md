# Worker B integration report

## Objective

Continue the Worker B fatal-three implementation by carrying explicit provider
`forward_net_borrowing_1y/2y` through the production normalizer and
`ValuationService` path, while keeping `net_borrowing_ttm` historical-only.
Add an API-level Case C regression and verify the backend suite. No commit or
push was performed.

## Execution context

- Working directory: `D:\workshop\stock-valuation`
- Dispatch: `task_c0e92df6cacf` / `ctx_66d1f12a6489`
- Requested execution model: Codex Luna Max max. The worker terminal does not
  expose provider/model telemetry, so the actual runtime identity is not
  independently verifiable here; no fallback event, quota reset, or external
  side effect was observed.
- Baseline before edits: `master...origin/master`, `HEAD 68e98d4`.
- The working tree already contained shared Worker A/C and earlier Worker B
  changes; those files were preserved and no destructive Git command was used.

## Ownership and changes

- `backend/app/models/domain.py`: added the two optional domain transport fields
  `forward_net_borrowing_1y` and `forward_net_borrowing_2y`; they are separate
  from `net_borrowing_ttm` and have no historical fallback.
- `backend/app/services/valuation_service.py`: the normalizer now retains its
  snapshot in a local variable and invokes the existing provider-boundary
  `_attach_forward_borrowing(snapshot, cf, est)` helper before returning. This
  preserves explicit value, period, source, source type, date, unit,
  confidence, estimate marker, and notes; invalid/fallback metadata is ignored
  by the fail-closed helper, and TTM borrowing is never promoted.
- `backend/tests/test_forward_fcfe_borrowing_api.py`: added a raw seven-method
  provider fixture and FastAPI TestClient Case C regression. The test asserts
  the API bridge carries forward `321` as `FY2026E`, reports normalized
  `analyst_estimate` provenance, and independently retains historical TTM `500`.
- Report: this file, `.scratch/fatal-three/worker-b-integration-report.md`.

## Verification

All commands ran from `D:\workshop\stock-valuation`:

| Command | Exit | Result |
|---|---:|---|
| `git diff --check` | 0 | Passed; only existing LF/CRLF warnings were emitted. |
| `\.venv\Scripts\python.exe -m pytest backend/tests/test_forward_fcfe_borrowing_isolation.py backend/tests/test_forward_fcfe_borrowing_api.py -q` | 0 | `7 passed, 2 warnings` |
| `\.venv\Scripts\python.exe -m pytest backend/tests/ -q` | 0 | `384 passed, 2 warnings` |

## Risks and remaining work

The domain and service files still include pre-existing shared Worker A/C
changes in the dirty worktree; this report does not claim ownership of those
unrelated edits. The API regression uses a deterministic provider fixture and
does not exercise live Yahoo data, whose standard payload remains absent of an
explicit forward borrowing field and therefore correctly normalizes forward
borrowing to zero.
