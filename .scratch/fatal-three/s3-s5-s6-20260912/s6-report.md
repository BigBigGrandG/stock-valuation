# S6 worker report — terminal-value fallback dependence

## Objective

Implement the S6 terminal-value risk governance helper and owned tests under the shared S3/S5/S6 contract. The helper is pure, has no import dependency on `dcf.py`, and is ready for S5 to call on the final successful DCF result.

## Current state

- Baseline branch/HEAD: `master`, `7aaec80`.
- Existing workspace changes were dirty/untracked before S6 and concurrent S3/S5 work appeared during execution; they remain untouched by this worker.
- Actual execution route: user-selected Codex / `gpt-5.6-luna` / max effort per coordinator state; no provider fallback and no `resets_at`.
- Worker owns only `backend/app/engines/terminal_governance.py`, `backend/tests/test_s6_terminal_governance.py`, this report/evidence, and the S6 issue evidence section.

## Implementation

`apply_terminal_governance(model, snapshot, assumptions)`:

1. Resolves effective WACC and terminal-growth lineage from final `assumption_metrics`, with compatibility fallback to flat model assumptions and `ValuationAssumptions`.
2. Evaluates finite positive PVTV and enterprise value plus WACC > terminal growth for every DCF scenario; it does not short-circuit after a bad scenario.
3. Uses inclusive `PVTV/EV >= Decimal("0.75")` as an explicit conservative policy-attention threshold, documented as non-universal.
4. Blocks configured fallback or unknown effective parameters, and blocks invalid terminal-value inputs. Blocked results clear public prices, DCF scenarios, and sensitivity output while retaining inputs, assumption metrics, calculation steps, warnings, and structured governance diagnostics under `assumptions["terminal_governance"]`.
5. Keeps supported/user-explicit high-concentration scenarios available with a structured `limited` status and one-level `DataQuality` downgrade.

## Changed files

S6 changes:

- `backend/app/engines/terminal_governance.py` — new pure post-calculation governance helper and policy constants.
- `backend/tests/test_s6_terminal_governance.py` — nine tests covering actual DCF paths, fallback/unknown lineage, explicit overrides, threshold boundary, invalid denominators, all-scenario evaluation, immutability/public-price clearing, and JSON serialization.
- `.scratch/fatal-three/s3-s5-s6-20260912/s6-evidence.md` — durable command and acceptance evidence.
- `.scratch/fatal-three/issues/S6-terminal-value-fallback-dependence.md` — appended S6 implementation/evidence status.
- `.scratch/fatal-three/s3-s5-s6-20260912/s6-report.md` — this report.

Pre-existing/concurrent files such as `backend/app/engines/dcf.py`, `backend/app/engines/parameter_governance.py`, `backend/app/engines/fcf_yield.py`, `backend/app/engines/forward_pe.py`, `backend/app/engines/ev_ebitda.py`, `backend/app/models/domain.py`, provider/projection files, and other workers' tests were not modified by S6.

## Verification

All commands ran from `D:/workshop/stock-valuation` with the repository `.venv` and `DATA_PROVIDER=demo` for tests:

- `pytest backend/tests/test_s6_terminal_governance.py -v`: PASS, 9 passed, exit 0.
- `pytest backend/tests/test_dcf.py -v`: PASS, 9 passed, exit 0.
- `python -m compileall -q backend/app/engines/terminal_governance.py backend/tests/test_s6_terminal_governance.py`: PASS, exit 0.
- `git diff --check`: PASS, exit 0.

Full post-integration DCF/API validation was `NOT RUN / PENDING S5` at the time of the original helper attempt; see the continuation section below for current integrated verification.

## Risks and pending items

- S5 must import `apply_terminal_governance` and call it exactly once on the final successful `run_dcf` result; do not add a helper-to-DCF import or stub.
- Existing demo/live tests that directly expect a fallback-backed DCF price may need expectation updates after S5 integration; assertions must verify unavailable reasons and preserved lineage rather than weakening coverage.
- No live-provider validation was run by this worker; the policy is source/provenance-driven and was validated with deterministic demo-isolated tests.

## Resume here

Coordinator should review the helper and S6 evidence, confirm S5 integration, then run the final targeted DCF/API regression. S6 has sent a status message notifying the coordinator that the helper is ready for S5.

## Continuation acceptance (task_dc94fd6c9d4e)

Date: 2026-09-12 Asia/Shanghai 19:02 (worker local clock). This continuation is a new dispatch after the original helper attempt; the original `worker_done` is not used as evidence for this acceptance.

### Concrete gap closed

- `_provenance_descriptor` now checks a source label containing `fallback` before accepting `derived`, `actual`, or `fixture`; only an explicit `user_override` source type is exempt from that label conflict.
- `SourceType.FIXTURE` is supported only when `snapshot.is_demo` is true. Live snapshots with fixture WACC/terminal-growth lineage resolve to unknown and fail closed; isolated demo fixture scenarios remain deterministic and testable.
- Every effective assumption metric is checked against its scenario WACC/terminal-growth value. Missing, mismatched, or non-finite claimed metric values cannot justify provenance; supported mismatches are explicitly classified as invalid and withheld.
- Existing 0.75 inclusive threshold, all-scenario PVTV/EV evaluation, invalid denominator guard, structured governance metadata, and public price/scenario/sensitivity clearing remain intact.

### New tests

`backend/tests/test_s6_terminal_governance.py` now has 15 tests, including derived-plus-fallback-label conflict, missing/unknown lineage, user-override exception, fixture demo/live isolation, mismatched/non-finite effective metrics, direct integrated `run_dcf`, and API serialization with a single governance application.

### Evidence commands and outcomes

All commands ran from `D:/workshop/stock-valuation` using `.venv/Scripts/python.exe` and `DATA_PROVIDER=demo` for tests:

- `pytest backend/tests/test_s6_terminal_governance.py -v`: PASS, 15 passed, exit 0. Raw stdout: `s6-continuation-owned.stdout.txt`; exit artifact: `s6-continuation-owned.exit-code.txt`.
- `pytest backend/tests/test_dcf.py -v`: exit 1 with 3 legacy assertions expecting fallback-backed `run_dcf` to remain available (`test_dcf_y1_y2_actual_estimates`, `test_dcf_full_avgo`, `test_dcf_bear_lower_than_bull`). The failures are expected consequences of S5's integrated governance policy and shared `test_dcf.py` is outside S6 ownership; raw stdout: `s6-continuation-dcf.stdout.txt`; exit artifact: `s6-continuation-dcf.exit-code.txt`.
- `python -m compileall -q backend/app/engines/terminal_governance.py backend/tests/test_s6_terminal_governance.py`: PASS, exit 0.
- `git diff --check`: PASS, exit 0 (pre-existing/concurrent CRLF warnings only).

### Integration/API status

S5 has wired `return apply_terminal_governance(result, snapshot, assumptions)` at the final successful `run_dcf` return and imports the helper without a reverse dependency. S6 direct tests call `run_dcf` without applying the helper again; the API test calls `/api/v1/valuation/AVGO?provider=demo`, verifies blocked prices/scenarios/sensitivity plus retained governance metadata, and confirms exactly one governance calculation step.

### Continuation risks

- Shared DCF tests and any other tests that assert a normal fallback-backed DCF price require coordinator-owned expectation review; S6 did not modify shared tests.
- No F1/S1/S2 files, S3 files, `domain.py`, provider, or other S5 production files were changed by this continuation.
