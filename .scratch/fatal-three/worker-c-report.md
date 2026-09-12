# Worker C — Fiscal-year DCF time-axis report

## Objective / scope / ownership

Implement the Worker C contract from `.scratch/fatal-three-implementation.md`: align DCF forecast periods to a verified fiscal-year end and valuation date; prorate an in-progress FY1 stub except at fiscal start; discount each cash flow and terminal value at its actual ACT/365 endpoint; expose period dates, t, discount factor, PV, and stub metadata through the API, UI, and Markdown export. Ownership was limited to `backend/app/engines/dcf.py`, DCF fields in `backend/app/models/domain.py`, `frontend/components/DCFScenarios.tsx`, `frontend/lib/types.ts`, `frontend/lib/exportMarkdown.ts`, and Worker C tests/evidence; no Worker A/B files were intentionally edited.

## Baseline and safety

- Start cwd: `D:\workshop\stock-valuation`.
- Start baseline: `git status --short --branch` reported `master...origin/master` with only the supplied untracked `.scratch/fatal-three-implementation.md`; `git log -5 --oneline --decorate` identified `68e98d4` at HEAD, equal to `origin/master`; start `git diff` was empty for tracked files.
- No `git clean`, `git reset --hard`, commit, push, or destructive cleanup was run.
- The shared workspace later became concurrently dirty in Worker A/B surfaces (`README.md`, providers/services, composite-related frontend/API files, and their tests). Those changes were preserved and are explicitly not attributed to Worker C.
- Runtime requested by the task: Codex Luna Max / max. `resets_at` was not exposed; no provider fallback was observed and no credentials were written.

## Implementation

- Added provider-anchored fiscal schedule construction. FY1 starts at the valuation date when the date falls inside FY1 and is prorated by remaining fiscal days; valuation at fiscal start keeps the full FY1 amount. FY2–FY5 are complete, non-overlapping fiscal years.
- Reused actual fiscal-period end dates for ACT/365 discount times; centralized Decimal exponential discount-factor calculation for base DCF and sensitivity cells. Terminal value and PVTV now use the actual FY5 endpoint.
- Added DCF scenario and sensitivity metadata for period starts/ends, discount times, discount factors, proration, stub status, fiscal days, PV projections, and terminal endpoint; included the same metadata in calculation steps/formulas and price-estimate intermediates.
- Updated DCFScenarios and Markdown export to render start/end dates, t, discount factor, FY1 proration/stub, PV, and terminal endpoint metadata.
- Added `backend/tests/test_fatal_three_worker_c.py` for the 2026-09-11 FY2026 stub/FY2027 `t≈1.3` contract, fiscal-start full-year behavior, center sensitivity timeline identity, and JSON serialization.

## Verification

| Command (cwd) | Exit | Result |
|---|---:|---|
| `.\\.venv\\Scripts\\python.exe -m compileall -q backend/app` (cwd `D:\workshop\stock-valuation`) | 0 | passed |
| `.\\.venv\\Scripts\\python.exe -m pytest backend/tests/test_fatal_three_worker_c.py -q` (cwd `D:\workshop\stock-valuation`) | 0 | 3 passed in 0.11s |
| `.\\.venv\\Scripts\\python.exe -m pytest backend/tests/test_dcf.py backend/tests/test_p0_p1_deep_remediation.py backend/tests/test_backend_acceptance_revisions.py backend/tests/test_audit_issues_03_04_regression.py -q` | 0 | 76 passed, 2 warnings |
| `.\\.venv\\Scripts\\python.exe -m pytest backend/tests/ -q` | 0 | 383 passed, 2 warnings |
| `npm run lint` (cwd `frontend`) | 0 | passed |
| `npm run typecheck` (cwd `frontend`) | 0 | passed |
| `npm run build` (cwd `frontend`) | 0 | production build passed |
| `npx playwright test tests/contract_export.spec.ts --reporter=line` (cwd `frontend`) | 0 | 3 passed |
| `npx playwright test tests/e2e_valuation_integrity.spec.ts --reporter=line` (cwd `frontend`) | 0 | 3 passed |
| `git diff --check -- <Worker C touched paths>` | 0 | no whitespace errors |

Replay command (cwd `D:\workshop\stock-valuation`, exit 0; stdout was intentionally discarded after the script completed):

```powershell
@'
import importlib.util
from pathlib import Path

script_path = Path('.scratch/valuation-ai-audit-20260911/verification/r6/replay_r5_payloads.py').resolve()
spec = importlib.util.spec_from_file_location('worker_c_replay', script_path)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)
module.OUTPUT_PATH = Path('.scratch/fatal-three/worker-c-replay.json').resolve()
raise SystemExit(module.main())
'@ | .\\.venv\\Scripts\\python.exe - | Out-Null
Write-Output ("REPLAY_EXIT=" + $LASTEXITCODE)
```

Replay artifact: `.scratch/fatal-three/worker-c-replay.json` (`schema=valuation-ai-audit-r6-replay-v1`, `overall_status=ok`, 12 results, 0 errors). It used the historical live payload fixture in offline replay mode (`input_provider_kind=live`, `replay_provider_kind=offline_replay_of_historical_live_payload`, `is_demo=false`) for AMD, META, GOOG, and NVDA across `complete`, `missing_fy1`, and `missing_fy2`; all 12 cases matched their expected statuses, with 3 DCF-available and 9 correctly isolated as unavailable.

The dedicated test and replay are supplemented by a manual serialized snapshot check for valuation date `2026-09-11`, which observed starts `2026-09-11`, `2027-01-01`, …, ends `2026-12-31`, `2027-12-31`, …, `t=[0.30410959, 1.30410959, …]`, FY1 proration `0.30410959`, and terminal endpoint `2030-12-31`; the check also verified the first projection row exposes `period_start`, `period_end`, `t`, `discount_factor`, `proration_factor`, `is_stub`, and nested PV metadata.

## Acceptance / risks / pending

### Acceptance

- The `2026-09-11` / FY2026 / FY2027 contract passes: FY1 is a `2026-09-11`–`2026-12-31` stub with `t<1` and `111/365` proration; FY2 ends `2027-12-31` with `t≈1.3041`; terminal value uses the FY2030 endpoint.
- Fiscal-start behavior passes: valuation on `2026-01-01` keeps FY1 unprorated (`proration_factor=1`, `is_stub=false`).
- Base and sensitivity DCF paths carry the same actual period dates, ACT/365 times, discount factors, PV values, and terminal metadata; API model serialization and the DCF UI/Markdown export expose those fields.
- Existing growth fade, sensitivity, and prior P0/P1/Audit gates remain green; the full backend suite is 383 passed and frontend lint/typecheck/build plus the two contract/browser suites are green.

### Risks / pending

The no-fiscal-anchor direct helper retains its legacy anniversary compatibility schedule so it does not invent a fiscal calendar; production snapshots with provider `forecast_fiscal_year_end` use the new fiscal-year path. No target price or FX rate is invented. Two existing deprecation warnings remain in the test suite; no new warning was introduced by this work. The shared workspace still contains concurrent Worker A/B edits, so the coordinator must review the combined diff and run final integrated acceptance after those branches/surfaces settle; no other Worker C action is pending.

## Changed paths owned by Worker C

- `backend/app/engines/dcf.py`
- `backend/app/models/domain.py` (additive DCF timeline fields; concurrent changes in the same file were preserved)
- `frontend/components/DCFScenarios.tsx`
- `frontend/lib/types.ts` (additive DCF timeline fields; concurrent changes in the same file were preserved)
- `frontend/lib/exportMarkdown.ts` (additive DCF timeline fields; concurrent changes in the same file were preserved)
- `backend/tests/test_fatal_three_worker_c.py`
- `.scratch/fatal-three/worker-c-report.md`
- `.scratch/fatal-three/worker-c-replay.json`

No Worker C change was made to `backend/app/services/projections.py`, composite valuation files, provider implementations, FCFE/FCF-yield code, or Worker A/B test files.
