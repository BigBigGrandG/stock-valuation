# S6 verification evidence

Date: 2026-09-12 Asia/Shanghai 18:50 (worker local clock)

## Execution identity

- Run: `run_9c475ef16943`
- Task: `task_c165c8562821`
- Dispatch: `ctx_9119fa8b6489`
- Actual requested/effective route from coordinator state: Codex / `gpt-5.6-luna` / max effort; user-selected route, no provider fallback; `resets_at` not applicable.
- Working directory: `D:/workshop/stock-valuation`
- No commit, push, reset, clean, or unrelated production-file edits performed by this worker.

## Baseline

- Branch: `master...origin/master`
- HEAD: `7aaec80 修复三个致命问题`
- The workspace already contained dirty and untracked F1/S1/S2 work plus concurrent S3/S5 edits. Those files were preserved and are not attributed to S6.
- Owned files were absent at start: `backend/app/engines/terminal_governance.py`, `backend/tests/test_s6_terminal_governance.py`, and the S6 report/evidence files.

## Commands and results

| Command | Exit | Result |
| --- | ---: | --- |
| `git status --short --branch` | 0 | Baseline captured; pre-existing/concurrent changes preserved |
| `git log -5 --oneline --decorate` | 0 | HEAD `7aaec80` confirmed |
| `git diff --stat; git diff -- backend/app/engines/terminal_governance.py; git ls-files --others --exclude-standard` | 0 | Existing diff/untracked inventory captured |
| `$env:DATA_PROVIDER='demo'; .\\.venv\\Scripts\\python.exe -m pytest backend/tests/test_s6_terminal_governance.py -v` | 0 | 9 passed |
| `$env:DATA_PROVIDER='demo'; .\\.venv\\Scripts\\python.exe -m pytest backend/tests/test_dcf.py -v` | 0 | 9 passed |
| `$env:DATA_PROVIDER='demo'; .\\.venv\\Scripts\\python.exe -m compileall -q backend/app/engines/terminal_governance.py backend/tests/test_s6_terminal_governance.py` | 0 | Compiled successfully |
| `git diff --check` | 0 | No whitespace errors reported |

## Acceptance matrix

| Requirement | Evidence | Status |
| --- | --- | --- |
| Configured fallback WACC/g cannot publish a normal DCF | S6 test covers all three scenarios; public `low/base/high`, `dcf_scenarios`, and `sensitivity_matrix` are cleared while governance diagnostics remain | PASS |
| Unknown WACC/g lineage fails closed | S6 test uses missing effective provenance and verifies six parameter issues | PASS |
| Every scenario PVTV/EV is evaluated | Tests verify three diagnostics are retained even when one scenario has a zero denominator | PASS |
| Non-positive/invalid EV denominator cannot bypass governance | Parameterized zero and negative EV tests fail closed | PASS |
| Inclusive 0.75 policy threshold is explicit | Exact 0.75 tests produce `limited`; 0.7499 tests produce `approved` | PASS |
| Supported/user-explicit high concentration remains visible but limited | Target/scenario/sensitivity values remain available, structured limitation is recorded, and `DataQuality` downgrades one level | PASS |
| Explanatory metadata survives API serialization | `ModelValuation.model_dump(mode="json")` assertion covers governance record | PASS |
| Real DCF path with configured fallback is blocked | Test invokes `run_dcf` then helper and verifies fallback blocking | PASS |
| Real DCF path with explicit WACC/g overrides remains publishable | Test invokes `run_dcf` then helper and verifies public values remain | PASS |
| Final DCF integration after S5 wiring | Original helper attempt recorded this as pending; continuation now verifies direct `run_dcf` and API serialization after S5 wiring | PASS (continuation; see below) |

## Financial provenance chain

This change is a post-calculation policy gate only: it consumes the final DCF `ModelValuation.assumption_metrics` produced by the existing snapshot/provider/normalizer/projection/engine chain. It records each scenario's effective WACC and terminal-growth source type, source, origin, value, PVTV, EV, and exact `PVTV/EV` ratio; no source values, FX, forecasts, or prices are invented and no missing value is converted to zero.

## Continuation evidence — task_dc94fd6c9d4e / dispatch ctx_543a4112cbb5

### Hardened checks

- Source labels containing `fallback` are now rejected before accepting non-override source types; explicit `user_override` remains the only label-conflict exception.
- Fixture provenance is accepted only for `snapshot.is_demo=True`; live fixture provenance is unknown and fails closed.
- Claimed assumption metric values are checked against each scenario's effective WACC/terminal-growth value; supported mismatches and non-finite/missing claims fail closed with structured `invalid_parameters` evidence.

### Raw stdout and exit-code artifacts

- Owned suite stdout: [`s6-continuation-owned.stdout.txt`](s6-continuation-owned.stdout.txt), exit [`s6-continuation-owned.exit-code.txt`](s6-continuation-owned.exit-code.txt) = `0`; 15 passed.
- Shared DCF regression stdout: [`s6-continuation-dcf.stdout.txt`](s6-continuation-dcf.stdout.txt), exit [`s6-continuation-dcf.exit-code.txt`](s6-continuation-dcf.exit-code.txt) = `1`; three legacy availability assertions fail because integrated fallback governance intentionally withholds DCF prices. This shared file remains untouched under S6 ownership.

### Direct integration/API verification

The owned suite directly invokes integrated `run_dcf` and verifies no second helper call, then calls the demo API endpoint and verifies JSON serialization, blocked public price/scenario/sensitivity fields, retained governance evidence, and exactly one governance calculation step. This covers the available S5 integration without claiming any change outside S6 ownership.
