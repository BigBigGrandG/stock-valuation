# 01/02 R5 Implementation Report

## Objective / Scope / Ownership

本轮接续 Codex Luna max Worker，处理 `rework-01-02-r5.md` 指定的两个缺口：生产 DCF projection 失败后的历史 FCFF 退路，以及可复算的 AMD/META/GOOG/NVDA live 证据。沿用 R4 已接受实现，不扩展 03—08，不另派 Worker；本 worker 负责 backend、回归测试、live 采集脚本、`verification/r5/` 和本报告，主控负责最终验收。

## Baseline and safety

- 工作目录：`D:\workshop\stock-valuation`
- 接手前已执行：`git status --short --branch`、`git log -5 --oneline --decorate`、`git diff --stat/name-only`、未跟踪文件清单。
- Git：`master`，HEAD `11b0495 (MVP版本)`；接手时已有 25 个 tracked 文件修改以及 `.scratch/valuation-ai-audit-20260911/`、`.scratch/workflow-optimization-20260911/`、`ai_comment/` 和历史测试等 untracked 成果。本轮未执行 `git clean`、`git reset --hard`、commit、push 或覆盖式整理。
- 执行回退：实际 provider/model 为 Codex / `gpt-5.6-luna` / `max`，承接原因是原 Antigravity 额度中断；`resets_at` 未由运行时暴露，不能验证。本轮未产生外部副作用。
- 无 root `CONTEXT.md`，无 `docs/adr/`；R5 契约已完整读取，其他工作流文档未修改。

## Reproduction and diagnosis

R5 提供的最小复现实际输出：`dcf_projection None`、`model_available True`，DCF steps 含 `configured fallback FCFF growth`。随后新增的真实调用链 regression 在修复前以 exit 1 收敛为 `9 failed, 1 passed, 2 warnings`，见 `verification/r5/red-regression.log`；失败覆盖 ACTUAL/DERIVED/FIXTURE、带/不带 revenue forecast、FY2-only 以及 API TestClient。

根因是 `run_all_engines` 在 projection 的 FY1 FCFF 为 `None` 时，仍可能把 `fcff_ttm`（包括 actual/fixture）放入 request snapshot；`run_dcf` 的 standalone 历史 TTM fallback 随后把它乘以配置增长率，绕过生产 projection 的 fail-closed 语义。

## Implementation

- `backend/app/services/valuation_service.py`：当 `proj.dcf_fcff_1y` 缺失时，无条件清除 request snapshot 的 `forward_fcff_1y`、`forward_fcff_2y` 和 `fcff_ttm`，不再按 source type 或 revenue presence 放行历史 fallback。`run_dcf` 本身未改，显式 standalone engine 测试仍可保留其历史兼容语义；普通生产 orchestration/API 不会再走这条退路。
- `backend/tests/test_audit_issues_01_02_regression_r5.py`：新增 10 项回归，真实覆盖三类 source type、revenue forecast 有无、FY2-only、`run_all_engines` 和 HTTP API。
- `backend/tests/test_production_pipeline_contract.py`：将旧 fixture 在缺少可验证 FY1/FY2 FCFF 时依赖历史退路的两个断言，改为验证 DCF honest unavailable、growth-cap 仍不污染 cache/assumptions；未在产品代码中恢复 fallback，也撤回了本轮尝试性 fixture 行改动。
- `.scratch/valuation-ai-audit-20260911/verification/r5/run_live_validation.py`：新增有界 live 采集器。每 ticker 使用 `YFinanceProvider(timeout=25s)` 和单一 `_RequestBudget(25s)`，记录 quote/profile/balance_sheet/cash_flow/income_statement/forward_estimates/historical_multiples 七类 raw payload、完整 `ValuationResponse`、`provider_class=YFinanceProvider`、`provider_kind=live`、`is_demo=false`；不读取或复用 R2/R3 结果。若 DCF available，断言 bridge forecast 与 DCF `input_metrics` 的 value/period/as_of 和 fiscal start/end 一致；若 DCF unavailable，断言没有 forward FCFF engine input 或 bridge forecast 泄漏。网络/provider 错误逐 ticker 落盘并返回非零退出码。

## Verification evidence

路径相对于仓库根目录；除注明外 cwd 为 `D:\workshop\stock-valuation`。以下结果以命令真实退出码为准。

| Surface | Command / cwd | Exit | Result / artifact |
|---|---|---:|---|
| Minimal R5 repro | R5 提供的 `runpy` probe / root | 0 | 输出 `dcf_projection None model_available True`，并显示 `configured fallback FCFF growth`; `.scratch/valuation-ai-audit-20260911/verification/r5/red.log` |
| R5 regression before fix | `$env:PYTHONPATH='backend'; & .\\.venv\\Scripts\\python.exe -m pytest backend/tests/test_audit_issues_01_02_regression_r5.py -q` / root | 1 | `9 failed, 1 passed, 2 warnings`; `.scratch/valuation-ai-audit-20260911/verification/r5/red-regression.log` |
| R5 regression after fix | same command / root | 0 | `10 passed, 2 warnings in 0.98s`; `.scratch/valuation-ai-audit-20260911/verification/r5/green-regression.log` |
| R3 + R4 + R5 targeted | `& .\\.venv\\Scripts\\python.exe -m pytest backend/tests/test_audit_issues_01_02_regression_r3.py backend/tests/test_audit_issues_01_02_regression_r4.py backend/tests/test_audit_issues_01_02_regression_r5.py -q` / root | 0 | `27 passed, 2 warnings in 1.22s`; `.scratch/valuation-ai-audit-20260911/verification/r5/targeted-r3-r5.log` |
| Production pipeline compatibility | `$env:PYTHONPATH='backend'; & .\\.venv\\Scripts\\python.exe -m pytest backend/tests/test_production_pipeline_contract.py -q` / root | 0 | `9 passed, 2 warnings in 1.33s`; `.scratch/valuation-ai-audit-20260911/verification/r5/production-pipeline-after.log` |
| Full backend | `& .\\.venv\\Scripts\\python.exe -m pytest backend/tests/ -q` / root | 0 | `328 passed, 2 warnings in 5.21s`; `.scratch/valuation-ai-audit-20260911/verification/r5/full-after.log` |
| Python syntax | `& .\\.venv\\Scripts\\python.exe -m py_compile backend/app/services/valuation_service.py backend/tests/test_audit_issues_01_02_regression_r5.py .scratch\\valuation-ai-audit-20260911\\verification\\r5\\run_live_validation.py` / root | 0 | passed; `.scratch/valuation-ai-audit-20260911/verification/r5/py_compile.log` |
| Live evidence collection | `$env:LIVE_VALIDATION_TIMEOUT='25'; & .\\.venv\\Scripts\\python.exe .scratch\\valuation-ai-audit-20260911\\verification\\r5\\run_live_validation.py` / root | 0 | AMD/META/GOOG/NVDA all `status=ok`; `.scratch/valuation-ai-audit-20260911/verification/r5/live-validation-r5-final.log` and full JSON `.scratch/valuation-ai-audit-20260911/verification/r5/live-validation-r5.json` |
| Live artifact validation | JSON schema/raw-count/response/consistency assertion script / root | 0 | Each ticker has raw=7, full response present, consistency=ok; `.scratch/valuation-ai-audit-20260911/verification/r5/artifact-check.log` |
| Frontend checks | NOT RUN | — | No frontend source changed in R5; R4 frontend typecheck/lint/build/contract/E2E evidence remains accepted and is not relabeled as a new R5 run. |

### New live evidence summary

The live artifact is explicitly `provider_kind=live`, `provider_class=YFinanceProvider`, `is_demo=false`, and contains all seven raw categories plus the full response for each ticker. The run observed real point-in-time quote values AMD `503.60`, META `644.38`, GOOG `330.39`, NVDA `218.36`; all four responses had `financial_bridge=true`, `DataQuality.MEDIUM`, and DCF `available=false` with no FCFF input leakage. This is not a claim that every model must produce a number: current Yahoo forward FCFF fields were null/uncertified for these responses, so production isolation correctly left DCF unavailable while preserving bridge/raw evidence; all per-ticker consistency checks passed.

### R6 erratum

The R5 explanation above is incomplete: the four live payloads also carried explicit `forecast_fiscal_year_end` anchors and revenue estimate periods `0y`/`+1y`, but `_is_explicit_fy_metric` rejected those labels before reaching its relative-period mapping. Therefore R5 DCF unavailability cannot be attributed solely to upstream forward FCFF null/uncertified data. R6 replays the saved raw payloads through the production provider/normalizer/projection/engine path; AMD, GOOG and NVDA now reach positive FY1/FY2 driver-bridge DCF inputs with value/period/as_of/date-range reconciliation, while META's independently derived FCFF is negative and remains honestly unavailable rather than falling back to historical FCFF.

## Financial fidelity, risks, and pending

- Missing FCFF drivers are isolated, never replaced by zero or historical FCFF×configured-growth. FCFE cannot substitute for FCFF. The direct engine fallback remains only at its explicit standalone seam and cannot be reached from `run_all_engines` after a failed FY1 projection.
- Raw source records retain provider payloads and their source/period/as_of fields; complete response records retain API model inputs, bridge, reasons and applicability state. Live values are point-in-time and can change after cache expiry or upstream revisions.
- The first R5 live script invocation was corrected before the authoritative run; the final script exit 0 and artifact are the evidence of record. No secrets, auth headers or credentials were written.
- No implementation item remains for this R5 scope. Coordinator should review the diff against the pre-existing uncommitted worktree and decide any human-authorized commit/push; this worker performed neither.

## Resume Here

R5 implementation, regression, full backend verification, and four-ticker live evidence are complete. The authoritative handoff is this report plus `verification/r5/full-after.log`, `targeted-r3-r5.log`, `live-validation-r5-final.log`, `live-validation-r5.json`, and `artifact-check.log`; coordinator acceptance remains the only next step.
