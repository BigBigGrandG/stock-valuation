# 01/02 R4 Implementation Report

## Objective

接续 Antigravity 额度中断后的 01/02 第四轮修复，以当前未提交工作区为唯一代码起点，闭环处理 `rework-01-02-r4.md` 列出的六项缺口，并完成后端、前端、浏览器全栈及指定 live ticker 验证。

## Baseline and execution context

- 工作目录：`D:\workshop\stock-valuation`
- 基线命令：`git status --short --branch`、`git log -5 --oneline --decorate`、相关 `git diff` 已在本轮任何编辑/测试前执行。
- Git 基线：`master`，HEAD `11b0495 (MVP版本)`；工作区在接手时已有多处 tracked 修改、`.scratch/valuation-ai-audit-20260911/`、`.scratch/workflow-optimization-20260911/`、`ai_comment/` 及历史测试文件等 untracked 成果。本轮未执行 `git clean`、`git reset --hard`、commit 或 push，也未覆盖这些既有成果。
- 调度回退：实际执行者为 Codex / `gpt-5.6-luna` / `max`；原因是 Antigravity 额度中断。`resets_at` 未由运行时暴露，无法验证；本轮没有因该回退产生外部副作用。
- Ownership：本 worker 负责 01/02 后端 projection/provider/service、对应回归测试、前端 bridge/export/交互验收和本报告；其他工作流文档修改仅保留，不在本轮整理。

## Remaining gaps confirmed and resolved

1. **R3 false-green**：历史 `verification/r4/red.log` 的真实结果为 `10 failed, 303 passed`，不是报告中的 green。当前完整后端运行已真实退出码 0，并对旧 EBITDA/growth 断言按新财务契约改为验证“无独立共识时不合成”。
2. **Stale projection isolation**：`run_all_engines` 不再把 projection 缺失解释为保留旧 forward EV/FCF/DCF 值；DCF 不再从通用 `forward_fcff_1y/2y` 静默回填。独立的 actual/fixture 历史 FCFF 仅在有合法上下文时保留。
3. **DCF consensus/driver precedence**：新增显式 FY1/FY2 period 与 fiscal-year 边界校验；NTM/TTM 不会伪装为 FY1。CapEx、D&A、NWC 等 driver override 优先于直接 FCFF consensus，并同时覆盖两年 DCF 预测；年度证据保留 start/end、period、as_of、source/source_type。
4. **D&A provenance**：`CashFlowData`、Yahoo provider、AVGO fixture、normalizer 到 bridge 全链路传递 `da_period`、`da_as_of`、fallback 标记；年度 D&A 与 TTM 基准期不兼容时保留原金额并公开 period，不做跨期比例缩放。
5. **FCFF/FCFE reconciliation**：bridge 增加独立 FCFE 计算和五项恒等式（EBITDA、EBIT、NOPAT、FCFF、FCFE）状态；缺证据为 `null`，任一不一致为 `false`，不再默认 `identity_holds=true`。FCFF/FCFE 差额与各自身份状态传到 API、前端卡片和 Markdown 导出。
6. **Full acceptance surface**：前端补齐 driver edit、reset、ticker switch、bridge identity/reconciliation、export evidence 的真实浏览器断言；Playwright 使用独立 fixture backend `127.0.0.1:18082`，并修正 Next public backend URL 的 build-time 注入。

## Implementation touchpoints

- Backend: `backend/app/services/projections.py`、`backend/app/services/valuation_service.py`、`backend/app/providers/base.py`、`backend/app/providers/yfinance_provider.py`、`backend/app/providers/avgo_fixture.py`。
- Backend regression/contract coverage: `backend/tests/test_audit_issues_01_02_regression_r4.py`，以及当前 acceptance、R3、service-independent、E2E 测试中的 period/consensus/metadata 契约更新。
- Frontend: `frontend/app/valuation/[ticker]/page.tsx`、`frontend/lib/types.ts`、`frontend/lib/exportMarkdown.ts`、`frontend/playwright.config.ts`、`frontend/eslint.config.mjs`；export source metadata now renders readable source/period/as-of text instead of `[object Object]`.
- Frontend tests: `frontend/tests/contract_export.spec.ts` and `frontend/tests/e2e_valuation_integrity.spec.ts`.

## Verification evidence

所有命令均记录真实退出码；路径均相对于仓库根目录，除特别注明外 cwd 为仓库根目录。

| Surface | Command / cwd | Exit | Result / artifact |
|---|---|---:|---|
| R4 regression | `& .\.venv\Scripts\python.exe -m pytest backend/tests/test_audit_issues_01_02_regression_r4.py -q` / root | 0 | `5 passed in 0.82s`; `.scratch/valuation-ai-audit-20260911/verification/r4/r4-regression-green.log` |
| R3 + R4 targeted | `& .\.venv\Scripts\python.exe -m pytest backend/tests/test_audit_issues_01_02_regression_r3.py backend/tests/test_audit_issues_01_02_regression_r4.py -q` / root | 0 | `17 passed in 0.67s`; `.scratch/valuation-ai-audit-20260911/verification/r4/targeted-r3-r4-final.log` |
| Full backend | `& .\.venv\Scripts\python.exe -m pytest backend/tests/ -q` / root | 0 | `318 passed, 2 warnings in 4.69s`; `.scratch/valuation-ai-audit-20260911/verification/r4/full-after.log` |
| Frontend typecheck | `npm run typecheck` / `frontend` | 0 | passed; `.scratch/valuation-ai-audit-20260911/verification/r4/frontend-typecheck-r4-final.log` |
| Frontend lint | `npm run lint` / `frontend` | 0 | passed after ignoring generated `.next-test`; `.scratch/valuation-ai-audit-20260911/verification/r4/frontend-lint-r4-final.log` |
| Frontend production build | `NEXT_DIST_DIR=.next-test NEXT_PUBLIC_BACKEND_URL=http://127.0.0.1:18082 npm run build` / `frontend` | 0 | Next 15.4.3 build passed; `.scratch/valuation-ai-audit-20260911/verification/r4/frontend-build-testdist-r4-final.log` |
| Contract export | `npx playwright test tests/contract_export.spec.ts --project=chromium` / `frontend` | 0 | `3 passed (4.8s)`; `.scratch/valuation-ai-audit-20260911/verification/r4/frontend-contract-r4-final.log` |
| Real-browser fullstack | `npx playwright test tests/e2e_valuation_integrity.spec.ts --project=chromium` / `frontend` | 0 | `3 passed (7.9s)`; `.scratch/valuation-ai-audit-20260911/verification/r4/frontend-playwright-r4-final.log` |
| Live Yahoo validation | `FinancialDataService.compute_valuation` with `_RequestBudget(25s)` for AMD/META/GOOG/NVDA / root | 0 | all four returned successfully, all four models available and bridge present; `.scratch/valuation-ai-audit-20260911/verification/r4/live-validation-r4-final.log` |
| Changed-surface whitespace check | `git diff --check -- <R4 backend/frontend touchpoints>` / root | 0 | clean for R4 touchpoints (Git only emitted LF→CRLF warnings). Whole-worktree check still reports a pre-existing extra EOF blank line in `backend/tests/test_e2e_valuation_integrity_export.py`; not changed here. |

Live probe observations are point-in-time only: AMD 503.60, META 644.38, GOOG 330.39, NVDA 218.36; each reported `DataQuality.MEDIUM`, `financial_bridge=true`, and all four valuation models available. These values are evidence of the run, not hard-coded targets or a substitute for source freshness policy.

## Financial fidelity and known risks

- No missing financial input is converted to zero. FCFF and FCFE remain distinct; DCF consumes only FCFF-compatible values or an explicit verified driver bridge. Metrics retain period, as-of, currency/unit, source/source_type and estimated/fallback semantics through provider → normalizer → projection → engine → API/export.
- The fixture bridge intentionally exposes partial evidence where inputs are unavailable; `identity_holds=null` means evidence is insufficient, while an observed mismatch is `false`. This is an honest applicability state, not a failure to manufacture a value.
- Yahoo live values and analyst-estimate availability are volatile and may differ after cache expiry; the bounded live log is a reproducible record of this run only. The initial live harness typo (`FinancialDataService.compute`, exit 1) is preserved separately in `live-validation-r4.log`; the corrected public `compute_valuation` run is the authoritative live result in `live-validation-r4-final.log`.
- No commit/push/deploy was performed. Coordinator should review the diff against the pre-existing uncommitted worktree and decide later whether to commit.

## Resume Here

R4 implementation and required verification are complete. Coordinator may inspect this report and the listed logs, review the working-tree diff while preserving unrelated workflow documents, and perform any human-authorized commit or handoff; no further worker action is pending.
