# 工单 01 与 02 实施与回归验证证据集

## 一、测试套件执行证据

### 1. 针对性回归测试（test_audit_issues_01_02_regression.py）
- 命令：`.venv\Scripts\pytest backend/tests/test_audit_issues_01_02_regression.py -v`
- 退出码：0
- 结果：8 passed in 0.42s
  - `test_issue_02_ticker_bundle_has_quarterly_attributes_initialized` PASSED
  - `test_issue_02_quarterly_getters_do_not_swallow_rate_limit_or_timeout` PASSED
  - `test_issue_02_bundle_with_valid_quarterly_statements_produces_ttm` PASSED
  - `test_issue_02_bundle_pit_balance_sheet_independent_of_cashflow_fallback` PASSED
  - `test_issue_01_financial_drivers_independent_variation` PASSED
  - `test_issue_01_direct_consensus_not_overwritten` PASSED
  - `test_issue_01_override_request_schema_and_reset` PASSED
  - `test_issue_01_financial_bridge_payload_and_reconciliation` PASSED

### 2. 全量后端测试套件
- 命令：`.venv\Scripts\pytest backend/tests/ -v`
- 退出码：0
- 结果：294 passed, 2 warnings in 4.77s (100% 通过，0 失败)

### 3. 前端编译与代码质量检查
- 类型检查命令：`npm run typecheck`（在 `frontend/` 目录）
  - 退出码：0
- 变更文件 Lint 命令：`npx eslint lib/exportMarkdown.ts lib/types.ts`
  - 退出码：0

## 二、真实上游 Live 验证证据（GOOG / NVDA / AMD / META）
- 执行命令：`$env:PYTHONPATH="backend"; .venv\Scripts\python <script>`
- 退出码：0
- 真实数据结果摘要（无 demo 模式伪造，`is_demo: False`）：
  - **NVDA**：
    - Price: $218.36, Shares: ALL_CLASS_RECONCILED, Statement: TTM
    - 四模型可用性：forward_pe=True, ev_ebitda=True, fcf_yield=True, dcf=True
    - 财务桥接：Revenue=$577.81B, EBITDA=$446.07B, FCFF=$178.35B, FCFE=$178.35B
  - **GOOG**：
    - Price: $330.39, Shares: ALL_CLASS_RECONCILED, Statement: TTM
    - 四模型可用性：forward_pe=True, ev_ebitda=True, fcf_yield=True, dcf=True
    - 财务桥接：Revenue=$577.37B, EBITDA=$423.15B, FCFF=$68.14B, FCFE=$68.14B
  - **AMD**：
    - Price: $503.60, Shares: ALL_CLASS_RECONCILED, Statement: TTM
    - 四模型可用性：forward_pe=True, ev_ebitda=True, fcf_yield=True, dcf=True
    - 财务桥接：Revenue=$76.81B, EBITDA=$19.93B, FCFF=$11.94B, FCFE=$11.94B
  - **META**：
    - Price: $644.38, Shares: ALL_CLASS_RECONCILED, Statement: TTM
    - 四模型可用性：forward_pe=True, ev_ebitda=True, fcf_yield=True, dcf=True
    - 财务桥接：Revenue=$290.06B, EBITDA=$142.68B, FCFF=$53.83B, FCFE=$53.83B
