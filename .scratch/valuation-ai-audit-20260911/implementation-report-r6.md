# 01/02 R6 Implementation Report

## Objective / Scope / Ownership

本轮接续 Codex Luna max Worker，按 `rework-01-02-r6.md` 修复期间解析造成的 DCF 误隔离，并验证 R5 四标真实 live payload 的 provider → normalizer → projection → engine → response 回放。范围严格限于 01/02 的期间资格、生产 DCF 输入隔离、直接关联回归/证据与报告；不扩展 03—08，不另派 Worker，不 commit/push，主控负责最终验收。

## Baseline and safety

- 工作目录：`D:\workshop\stock-valuation`；分支 `master`；HEAD `11b0495 (MVP版本)`。
- 接手前已执行 `git status --short --branch`、`git log -5 --oneline --decorate`、`git diff --stat` 与 R5 scratch 文件清单。工作树已有 R4/R5 相关 tracked 修改、历史回归测试和 `.scratch/valuation-ai-audit-20260911/`、`.scratch/workflow-optimization-20260911/`、`ai_comment/` 等 untracked 成果；本轮保留全部既有修改，未覆盖式整理。
- 未执行 `git clean`、`git reset --hard`、commit、push 或其他破坏性操作；未修改 frontend 或其他工作流文档（仅按 R6 要求给 R5 报告追加勘误）。
- 实际执行回退为 Codex / `gpt-5.6-luna` / `max`，原因是 Antigravity 额度中断；运行时未暴露 `resets_at`，因此不能验证重置时间。本轮无外部副作用、无密钥或凭据写入。

## Reproduction and diagnosis

R6 契约给出的最小症状是 `_is_explicit_fy_metric(FinancialMetric(period="0y"), 1, date(2026, 12, 31))` 返回 `False`。新增回归在修复前真实 exit 1：`7 failed, 10 passed, 2 warnings`，其中所有 anchored relative positive cases 和 driver-to-DCF path 失败；之后针对 META 暴露的非正 projected FCFF 历史退路新增回归，修复前真实 exit 1：`1 failed`。

根因有两层：

1. `_is_explicit_fy_metric` 先执行 `period.startswith("FY")`，使 `0y`、`+1y`、`forward_1y`、`forward_2y` 的后续 relative-slot 映射不可达；R5 四标 payload 明确包含这些标签及 `forecast_fiscal_year_end` 锚点。
2. 生产 `run_all_engines` 只检查 projection FCFF 是否非空；FY1 合格但 FY2 缺失，或 FY1/FY2 桥接结果为负时，DCF engine 仍可见历史 `fcff_ttm`，进而执行其 standalone 历史/增长兼容退路。

## Implementation

- `backend/app/services/projections.py`：先拒绝 NTM/TTM，再识别受限 relative-slot 标签；相对标签必须有 `forecast_fy_end`，slot 必须匹配，并按锚点年度校验。带嵌入年度的 `FY20xx...` 仍需 FY 前缀与年度一致，不放宽为任意字符串；`FY1E/FY2E` 也只有在锚点存在时作为相对标签通过。R5 既有 NTM/TTM、错 slot、错财年隔离保持不变。
- `backend/app/services/valuation_service.py`：生产 DCF 仅在 FY1 与 FY2 projection 均存在、有限且严格为正时提交两个 forward FCFF；否则同时清空两个 forward FCFF 和 `fcff_ttm`。这样缺任一期或 projected FCFF 不适用时，standalone `run_dcf` 的历史增长兼容行为仍可供直接 engine callers 使用，但不能从生产 orchestration/API 进入。
- `backend/tests/test_audit_issues_01_02_regression_r6.py`：新增 18 项红绿回归，覆盖 anchored relative labels、无锚点/NTM/TTM/错 slot/错财年、真实 driver bridge 对账、FY1/FY2 缺失和非正 FCFF 历史退路。
- `.scratch/valuation-ai-audit-20260911/verification/r6/replay_r5_payloads.py`：新增离线回放器。输入仅为 R5 `live-validation-r5.json` 中四标七类 provider payload，不读取旧 response 作为 oracle；每 ticker 运行 `complete`、移除 FY1、移除 FY2 三案，均经过七个 provider 方法、`FinancialDataService` normalizer、projection、`run_all_engines` 和 response assembly，并对可用 DCF 的 bridge value/period/as_of/fiscal range 与 engine input 做断言。
- `.scratch/valuation-ai-audit-20260911/implementation-report-r5.md`：追加 R6 erratum，纠正“R5 四标不可用仅因 upstream FCFF null/uncertified”的不完整解释，保留 R5 历史结果和证据。

## Verification evidence

路径相对于仓库根目录；除注明外 cwd 为 `D:\workshop\stock-valuation`；结果以命令真实退出码为准。

| Surface | Command | Exit | Result / artifact |
|---|---|---:|---|
| R6 regression before period fix | `$env:PYTHONPATH='backend'; & .\\.venv\\Scripts\\python.exe -m pytest backend/tests/test_audit_issues_01_02_regression_r6.py -q` | 1 | `7 failed, 10 passed, 2 warnings`; `verification/r6-red-regression.log` |
| Non-positive FCFF regression before guard | same pytest command targeting `test_nonpositive_projected_fcff_does_not_reopen_historical_fallback` | 1 | `1 failed`; `verification/r6-red-nonpositive.log` |
| R6 regression after fix | same full R6 pytest command | 0 | `18 passed in 0.68s`; `verification/r6-green-regression.log` |
| R3 + R4 + R5 + R6 targeted | `& .\\.venv\\Scripts\\python.exe -m pytest backend/tests/test_audit_issues_01_02_regression_r3.py backend/tests/test_audit_issues_01_02_regression_r4.py backend/tests/test_audit_issues_01_02_regression_r5.py backend/tests/test_audit_issues_01_02_regression_r6.py -q` | 0 | `45 passed, 2 warnings in 1.06s`; `verification/r6/targeted-r3-r6.log` |
| Production pipeline | `$env:PYTHONPATH='backend'; & .\\.venv\\Scripts\\python.exe -m pytest backend/tests/test_production_pipeline_contract.py -q` | 0 | `9 passed, 2 warnings in 1.05s`; `verification/r6/production-pipeline-after.log` |
| Full backend | `& .\\.venv\\Scripts\\python.exe -m pytest backend/tests/ -q` | 0 | `346 passed, 2 warnings in 4.82s`; `verification/r6/full-after.log` |
| Python syntax | `& .\\.venv\\Scripts\\python.exe -m py_compile backend/app/services/projections.py backend/app/services/valuation_service.py backend/tests/test_audit_issues_01_02_regression_r6.py .scratch\\valuation-ai-audit-20260911\\verification\\r6\\replay_r5_payloads.py` | 0 | `verification/r6/py_compile-final.log` |
| R5 payload replay | `& .\\.venv\\Scripts\\python.exe .scratch\\valuation-ai-audit-20260911\\verification\\r6\\replay_r5_payloads.py` | 0 | `12/12 cases` (`4 tickers × complete/missing FY1/missing FY2`); `verification/r6/replay-r5-payloads.log`, `verification/r6/replay-r5-payloads-r6.json` |
| Replay artifact validation | JSON assertion for schema, 4 tickers, 12 cases, raw categories, provider calls, expected DCF state and consistency | 0 | `R6 replay artifact validation passed: 12 cases / 4 tickers`; `verification/r6/artifact-check.log` |
| Diff/debug audit | `git diff --check` on touched tracked code + `rg '\\[DEBUG-[^]]+\\]'` | 0 | `verification/r6/diff-check.log`; `debug-tags=none` |
| Frontend checks | NOT RUN | — | No frontend source changed in R6; prior R4 frontend evidence remains separate. |

## Four-ticker replay results

The replay artifact declares `input_artifact=verification/r5/live-validation-r5.json`, `input_provider_kind=live`, `replay_provider_kind=offline_replay_of_historical_live_payload`, `is_demo=false`; it makes no network request and does not treat the old R5 response as expected output.

- AMD: complete DCF available; bridge/engine FCFF inputs match for FY1 `5571477004` and FY2 `9620496361`, including period, as_of and fiscal dates. Missing FY1 or FY2: DCF unavailable and no FCFF engine inputs.
- GOOG: complete DCF available; bridge/engine FCFF inputs match for FY1 `9709723045` and FY2 `11949589442`, including period, as_of and fiscal dates. Missing FY1 or FY2: DCF unavailable and no FCFF engine inputs.
- NVDA: complete DCF available; bridge/engine FCFF inputs match for FY1 `164887077695` and FY2 `271777729658`, including period, as_of and fiscal dates. Missing FY1 or FY2: DCF unavailable and no FCFF engine inputs.
- META: complete relative-period parsing and driver bridge succeed, but both independently derived FCFF values are negative (`-7476174442`, `-8997780875`); production DCF is unavailable with no FCFF engine inputs rather than falling back to historical TTM. Missing FY1 or FY2 is likewise unavailable with no FCFF engine inputs.

The missing-year cases retain any partial projection evidence in the financial bridge for auditability (one forecast can remain visible), while the production DCF request snapshot receives neither forward FCFF nor historical FCFF. This is intentional separation of auditable projection evidence from valuation eligibility.

## Financial fidelity, risks, and pending

- No missing value is converted to zero, and no target price or FX rate is invented. Relative labels are promoted only with provider-supplied fiscal-year anchors; NTM/TTM, no-anchor relative labels, wrong slots and wrong fiscal years remain isolated.
- DCF still uses explicit FY1/FY2 bridge metrics and configured/genuine growth only for Years 3–5 after those inputs pass production eligibility. Direct `run_dcf` historical fallback remains for its explicit standalone compatibility seam and is not changed by this task.
- META is an honest unavailable model because its independent operating-driver FCFF is non-positive; this is not classified as a provider-null failure. Live R5 values are point-in-time and can change after upstream revisions or a fresh bounded run.
- Two expected dependency warnings remain from the existing environment (`StarletteDeprecationWarning` and `DeprecationWarning`); no new warning or debug instrumentation was introduced.
- No implementation item remains for this R6 scope. Coordinator should review the current diff against pre-existing uncommitted work and decide any human-authorized commit/push; this worker performed neither.

## Resume Here

R6 code, red-green regression, R3–R6 targeted suite, production pipeline, full backend suite, R5 four-ticker payload replay, artifact validation, and R5 report erratum are complete. Authoritative artifacts are `verification/r6/full-after.log`, `verification/r6/targeted-r3-r6.log`, `verification/r6/replay-r5-payloads.log`, `verification/r6/replay-r5-payloads-r6.json`, `verification/r6/artifact-check.log`, and this report; coordinator acceptance is the only remaining step.
