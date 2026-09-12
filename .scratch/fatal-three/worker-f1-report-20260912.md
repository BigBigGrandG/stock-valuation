# F1 Worker Report — Forward FCF Yield must not capitalize historical FCFE

## 1. Task and execution identity

- Task: F1 — prohibit `snapshot.fcf_ttm` from entering Forward FCF Yield valuation.
- Scope/Ownership: `backend/app/engines/fcf_yield.py` and its dedicated regression coverage in `backend/tests/test_forward_fcfe_borrowing_isolation.py`. Per coordinator follow-up, one stale full-suite policy-test fixture/assertion was also updated in `backend/tests/test_p0_p1_deep_remediation.py` so it supplies an explicit forward FCFE instead of relying on historical `fcf_ttm`. `projections.py`, provider files, and other Worker-owned product files were not edited by this Worker.
- Task ID / dispatch ID: Not provided in the Worker payload; no IDs were invented.
- Execution time: 2026-09-12, Asia/Shanghai. The session identifies as Codex / GPT-5; the host does not expose a more specific runtime deployment string, so the exact deployment is Not verified. No provider fallback was used.
- Repository safety: no commit, push, reset, clean, deployment, credential access, or destructive cleanup was performed. One non-mutating orchestration status message was sent to the bound run so the coordinator could find this report; no product/external data state was changed.

## 2. Baseline and workspace separation

The mandatory baseline was captured before edits:

```text
git status --short --branch
## master...origin/master
?? .scratch/fatal-three/current-severity-reassessment-20260912.md
?? .scratch/fatal-three/issues/

git log -5 --oneline --decorate
7aaec80 (HEAD -> master, origin/master) 修复三个致命问题
68e98d4 修复两个严重问题
d0a7d62 修复致命问题
11b0495 MVP版本
3652146 提交
```

At baseline there was no tracked working-tree diff. The two untracked `.scratch/fatal-three/` entries above were pre-existing user/audit material and were preserved.

During this Worker run another Worker added/modified S1 borrowing-period work in the shared workspace. Final workspace state therefore also contains the following non-owned changes, which are not attributed to F1:

- `backend/app/services/projections.py` — concurrent S1 Worker change; not edited here.
- `backend/app/providers/yfinance_provider.py` — concurrent S1 Worker change; not edited here.
- `backend/tests/test_forward_fcfe_borrowing_api.py` — concurrent S1 test change; not edited here.
- `backend/tests/test_s1_ntm_borrowing_period_alignment.py` — concurrent untracked S1 tests; not edited here.
- `.scratch/fatal-three/worker-s1-report-20260912.md` — concurrent S1 Worker report; not edited here.
- The pre-existing `.scratch/fatal-three/` untracked audit files.

Owned changes are limited to:

- `backend/app/engines/fcf_yield.py`
- `backend/tests/test_forward_fcfe_borrowing_isolation.py`
- `backend/tests/test_p0_p1_deep_remediation.py` — narrow coordinator-authorized test-contract update; it now supplies an explicit analyst forward FCFE before checking cashflow-group policy metadata.
- This report: `.scratch/fatal-three/worker-f1-report-20260912.md`

## 3. Diagnosis and implementation

The pre-fix engine selected `snapshot.forward_fcf_1y`/`forward_fcf_2y`, then, when those were absent or historical, assigned `snapshot.fcf_ttm` to the valuation variable and generated all three prices. The existing test explicitly expected that behavior, so the pre-fix dedicated suite was green while the defect remained.

The engine now:

1. Iterates the explicit forward FCFE slots and skips empty or historical periods (`TTM`, `LTM`, `HISTORICAL`, or `TRAILING`) instead of treating them as forecast inputs. If FY1 is historical but FY2 is genuinely forward, the valid FY2 candidate may still be used.
2. Returns `available=False` with reason `No forward FCFE (equity FCF) estimate available` when no eligible forward metric remains. `snapshot.fcf_ttm` is never assigned to `fcfe`, never appears in `PriceEstimate.intermediates`, and cannot create `low`, `base`, or `high` prices.
3. Preserves historical FCFE only as explicitly named display/audit metadata (`historical_fcfe_ttm`) and a warning that a true forward estimate or explicit forward bridge is required.
4. Keeps an explicitly forward `forward_fcf_*` metric, including a `SourceType.USER_OVERRIDE` bridge, eligible for the existing FCFE/yield calculation. The result quality and provenance continue to be derived from the accepted forward metric.

The stale composite-policy test was adjusted only at its fixture/contract seam: it now provides a `FY1E` analyst-estimate FCFE and asserts that the FCF Yield result is available from that explicit forward input before checking the existing policy metadata. It no longer passes merely because the engine capitalizes the historical TTM value.

The old `historical_proxy` output path and its “temporary proxy” warning were removed so an unavailable model cannot advertise a historical number as forward FCFE.

## 4. Acceptance matrix

| Acceptance criterion | Evidence | Status |
| --- | --- | --- |
| Missing forward FCFE must be unavailable even when positive `fcf_ttm` exists | `test_missing_forward_fcfe_with_historical_ttm_is_unavailable`: no `low/base/high`, reason contains `No forward FCFE` | PASS |
| A TTM value in a forward slot must not fall through to `fcf_ttm`, including historical financing contamination | `test_historical_forward_fcfe_field_cannot_reenter_via_ttm_fallback`: unavailable with no price scenarios and historical warning | PASS |
| Historical TTM remains display-only with provenance | Same missing-forward test asserts `inputs["historical_fcfe_ttm"]`, `input_metrics["historical_fcfe_ttm"]["period"] == "TTM"`, and no `forward_fcfe` input | PASS |
| Explicit forward FCFE bridge/override remains usable and ignores TTM history | `test_explicit_forward_fcfe_override_is_eligible_and_ignores_ttm_history`: `USER_OVERRIDE`, `FY2026E`, value `1234`, base price `24.68` | PASS |
| No changes to `projections.py` or other non-owned product files | Final `git status`/diff name check; only owned engine/test plus concurrent files listed separately | PASS |
| No debug instrumentation remains | `rg` for removed `historical_proxy`/temporary-proxy markers returned no matches in owned engine/test | PASS |
| Legacy cashflow-policy test no longer relies on historical TTM fallback | `test_p0_p1_deep_remediation.py::TestP1FModelWeightsAndPolicy::test_cashflow_group_policy_message_visibility` supplies explicit `FY1E` analyst FCFE and passes | PASS |

## 5. Financial provenance chain

The relevant chain was inspected but only the engine/test surface was changed:

```text
provider raw FCFE/forward fields
  -> Normalizer (`valuation_service.py`): `fcfe_ttm` -> `snapshot.fcf_ttm`, forward aliases -> `forward_fcf_1y/2y`
  -> request projection (`projections.py`): an explicit FCFE analyst metric or documented driver bridge may produce `forward_fcfe_1y`
  -> engine (`fcf_yield.py`): only non-historical `forward_fcf_1y/2y` drives FCFE/yield prices
  -> API/export: unavailable model carries reason/display-only historical metadata; no price is produced
```

The engine does not alter the historical metric, invent borrowing, infer an FX rate, or substitute FCFF. Accepted forward metrics retain `period`, `as_of`, `unit`, `source`, `source_type`, `confidence`, and `is_estimated` in `input_metrics`; historical TTM is labeled separately and is not a valuation input.

## 6. Verification commands and results

All commands below ran from `D:\workshop\stock-valuation` using the repository `.venv`.

| Command | Exit/result | Notes |
| --- | --- | --- |
| `git status --short --branch` and `git log -5 --oneline --decorate` | 0 | Baseline recorded above before edits. |
| `.\.venv\Scripts\python.exe -m pytest backend/tests/test_fcf_yield.py backend/tests/test_forward_fcfe_borrowing_isolation.py -q` (pre-fix) | 0; `12 passed` | Historical fallback expectation was still green, demonstrating the masked defect. |
| `.\.venv\Scripts\python.exe -m pytest backend/tests/test_forward_fcfe_borrowing_isolation.py::test_missing_forward_fcfe_with_historical_ttm_is_unavailable backend/tests/test_forward_fcfe_borrowing_isolation.py::test_historical_forward_fcfe_field_cannot_reenter_via_ttm_fallback backend/tests/test_forward_fcfe_borrowing_isolation.py::test_explicit_forward_fcfe_override_is_eligible_and_ignores_ttm_history -q` (after test assertions, before engine fix) | 1; `2 failed, 1 passed` | Both failures showed the old positive `fcf_ttm` fallback still generated an available valuation. |
| `.\.venv\Scripts\python.exe -m pytest backend/tests/test_forward_fcfe_borrowing_isolation.py::test_missing_forward_fcfe_with_historical_ttm_is_unavailable backend/tests/test_forward_fcfe_borrowing_isolation.py::test_historical_forward_fcfe_field_cannot_reenter_via_ttm_fallback backend/tests/test_forward_fcfe_borrowing_isolation.py::test_explicit_forward_fcfe_override_is_eligible_and_ignores_ttm_history -q` | 0; `3 passed` | Current F1 regression coverage. |
| `.\.venv\Scripts\python.exe -m pytest backend/tests/test_fcf_yield.py -q` | 0; `6 passed` | Existing engine math/type coverage. |
| `.\.venv\Scripts\python.exe -m compileall -q backend\app\engines\fcf_yield.py backend\tests\test_forward_fcfe_borrowing_isolation.py` | 0 | Syntax/bytecode compilation passed. |
| `git diff --check` | 0 | Only Git’s normal LF/CRLF conversion warnings for dirty files; no whitespace errors. |
| `.\.venv\Scripts\python.exe -m pytest backend/tests/ -q` | 0; `397 passed, 2 warnings` | Full backend suite is green after the stale policy-test fixture/contract update; the two warnings are dependency deprecations. |
| `.\.venv\Scripts\python.exe -m pytest backend/tests/test_p0_p1_deep_remediation.py::TestP1FModelWeightsAndPolicy::test_cashflow_group_policy_message_visibility -q` | 0; `1 passed` | The legacy policy test now supplies an explicit `FY1E` analyst FCFE and asserts that FCF Yield used that forward input. |

The earlier full-suite failure caused by the stale policy-test fixture is resolved. No live-provider, frontend, API browser, deployment, commit, or push verification was run for this engine/test change (`NOT RUN`).

## 7. Diff review

Scoped `git diff --numstat` at review time:

```text
49  22  backend/app/engines/fcf_yield.py
52   7  backend/tests/test_forward_fcfe_borrowing_isolation.py
 9   2  backend/tests/test_p0_p1_deep_remediation.py
```

The borrowing-isolation test’s current physical diff includes three concurrent S1 period-label replacements (`FY2026E` → `NTM`), so its logical F1 test portion is 49 additions / 4 deletions; those three S1 hunks were not edited by this Worker. The global diff also showed concurrent `projections.py`, provider, API-test, and untracked S1-test changes; those were excluded from the scoped F1 review. The F1 diff removes the only assignment path from `snapshot.fcf_ttm` into the price-driving `fcfe` variable, adds a display-only unavailable path, and updates the dedicated test from the old proxy expectation to the required fail-closed contract. The narrow stale policy-test update supplies a real forward metric and verifies the policy behavior without reintroducing a historical fallback. No unrelated product file was edited by this Worker.

## 8. Risks and unresolved items

- The repository-wide suite is green in the latest run (`397 passed, 2 warnings`); concurrent S1 files remain in the shared workspace and are listed separately in the baseline section.
- API/frontend rendering of the new unavailable `historical_fcfe_ttm` display metadata was not exercised in this scoped run (`NOT RUN`); the engine contract is covered directly.
- The engine uses non-historical forward-slot provenance as the eligibility seam. Fiscal-year alignment and construction of an explicit bridge remain projection/provider responsibilities and were intentionally not changed here.
- Exact runtime deployment identity beyond the session-provided Codex/GPT-5 label is Not verified; no fallback state or external side effect occurred.

## 9. Handoff

Implementation, the stale policy-test contract update, and scoped F1 verification are complete. The coordinator should review the three owned code/test diffs and preserve the concurrent S1 files listed above. This session had no active F1 Dispatch/task identity (the bound Orca handle is a coordinator handle), so a protocol `worker_done` envelope could not be emitted without inventing IDs; the durable report and status message are the handoff artifacts. No commit or push is pending from this Worker.
