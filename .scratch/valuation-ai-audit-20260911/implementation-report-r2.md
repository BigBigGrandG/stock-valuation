# 工单 01 与 02 主控二轮验收修复报告 (Round 2 Implementation Report)

- **任务编号 (Task ID)**: `task_e8cd508a8585`
- **上下文编号 (Context ID)**: `ctx_3904399d304c`
- **分支基线 (Baseline)**: `master/11b0495`
- **执行角色 (Worker Terminal)**: `term_5abf4fd1-a6db-4d7f-a593-73affbcefd0c`
- **调度主控 (Coordinator Terminal)**: `term_6023c84b-1b9c-4190-9243-bc262cb85488`
- **完成日期**: 2026-09-11

---

## 一、主控二轮退回项（1–7）逐条闭环整改证据

### 1. 彻底去除历史现金流统一增长退路与 Provider 旧合成预测
- **整改措施**：
  - 在 `backend/app/providers/yfinance_provider.py` 的 `get_cash_flow` 中，彻底移除基于 `base_fcff * (1 + g)` 与 `base_fcfe * (1 + g)` 的旧合成预测，将未经审核的粗暴外推归零（`forward_fcfe_1y = None`, `forward_fcff_1y = None`），直接透出真实的 `cfo`, `capex`, `net_borrowing`, `nwc_change`, `da`。
  - 在 `backend/app/services/projections.py` 中，彻底删除 `base_fcff * (1 + effective_g)` 与 `base_fcfe * (1 + effective_g)` 历史现金流统一乘增长外推的生产回退路径。
  - 前瞻现金流仅允许通过两种合规路径产生：① 真实的分析师一致预期 (ANALYST_ESTIMATE)；② 经过显式会计勾稽的细分财务驱动桥接 (Financial Driver Bridge)。
  - 对历史上固化了错误外推算法的断言，按契约解释更新，确保无历史现金流统一外推生产退路。

### 2. D&A 真实提取与 15% 假数据彻底废除；关键驱动缺失时严格 Fail-Closed
- **整改措施**：
  - 在 `statement_aggregator.py` 中增加对真实的 `Depreciation And Amortization` 与 `Reconciled Depreciation` 的提取，打通至 `yfinance_provider.py`、`avgo_fixture.py` 与 `valuation_service.py` (`Normalizer`)。
  - 彻底删除 `projections.py` 中任何形式的 `derived_ebitda * Decimal("0.15")` 伪造假数据。若 D&A 既无覆盖亦无历史财报数据，`da_val` 严格保持 `None`。
  - 严格执行模型隔离：当关键财务驱动（如 CapEx 或 D&A）缺失且无直接一致预期时，前瞻 FCFF 保持 `None`，使依赖企业自由现金流的 DCF 模型进入 `available=False` 的 fail-closed 保护状态，绝不凭空造数。
  - 营运资本现金流符号与净借款严格对账：营运资本变动增加（`ΔNWC > 0`）作为现金流流出扣减 FCFF；净借款（`Net Borrowing`）严格隔离在企业自由现金流之外，仅进入股权自由现金流 FCFE 对账。

### 3. 财务桥接严格满足 5 大会计恒等式与口径一致性
- **整改措施**：
  - 财务桥接输出（`financial_bridge`）严格对账，满足以下 5 大财务会计恒等式：
    1. $\text{EBITDA} = \text{Revenue} \times \text{EBITDA Margin}$
    2. $\text{EBIT} = \text{EBITDA} - \text{D\&A}$
    3. $\text{NOPAT} = \text{EBIT} \times (1 - \text{Tax Rate})$
    4. $\text{FCFF} = \text{NOPAT} + \text{D\&A} - \text{CapEx} - \Delta\text{NWC}$
    5. $\text{FCFE} = \text{FCFF} - \text{Interest} \times (1 - \text{Tax Rate}) + \text{Net Borrowing}$
  - 当存在直接分析师一致预期时，保留其 `ANALYST_ESTIMATE` 来源与期间，禁止请求层与假对账篡改。

### 4. 期间起止、基准日、币种与限制说明完整披露
- **整改措施**：
  - `financial_bridge` 包含完整元数据字典：
    - `period`: 预测周期目标 (`"ntm"` 或 `"FY1E"`)
    - `forecast_start_date` 与 `forecast_end_date`: 完整的预测起止日期区间（如 `2026-09-10` 至 `2027-09-10`）
    - `as_of`: 财务数据基准日
    - `currency`: 计价币种（如 `"USD"`）
    - `restrictions_note`: 显式说明非现金项与资本结构口径限制：*"Financial bridge isolates non-cash (D&A) and working capital items. Excludes stock-based compensation (SBC), operating lease capitalizations, and non-operating investment gains/losses from operating free cash flows."*
    - `drivers_source`: 逐项披露每个细分驱动的取值来源（`user_override` / `derived_historical` / `analyst_estimate` / `statutory_default`）。

### 5. 真实 `_TickerBundle` 穿透式高保真回归测试
- **整改措施**：
  - 在 `backend/tests/test_audit_issues_01_02_regression.py` 中编写受控真实数据流测试：
    - `test_issue_02_ticker_bundle_has_quarterly_attributes_initialized`: 验证 `_qbs`, `_qcf`, `_qfin` 显式初始化为 `None`。
    - `test_issue_02_quarterly_getters_do_not_swallow_rate_limit_or_timeout`: 验证 429 (`ProviderRateLimitError`) 与超时 (`ProviderUnavailableError`) 不被吞掉。
    - `test_r2_issue_02_bundle_penetration_4_quarters_and_pit_bs`: 穿透真实 `_TickerBundle`，注入受控 4 季度连续数据，调用完整的 `YFinanceProvider` 方法，断言 `statement_basis == "TTM"`, `annual_fallback is False`, 真实 D&A/NWC/CapEx/CFO 提取无误，资产负债表为 Point-in-Time 最新时点。

### 6. 覆盖重置生命周期、Markdown 导出与前端交互
- **整改措施**：
  - 在 `backend/tests/test_audit_issues_01_02_regression.py` 与 `backend/tests/test_e2e_valuation_integrity_export.py` 中，完整测试：
    - POST 用户细分驱动覆盖（`ebitda_margin`, `capex`, `nwc_change`, `net_borrowing`, `da`, `tax_rate`），断言桥接数值与 5 大恒等式精确变动；
    - GET `/reset` 彻底清除所有覆盖，恢复默认历史驱动基准；
    - 股票切换不残留历史覆盖。
  - 前端导出扩展：
    - `frontend/lib/exportMarkdown.ts`: 增加“第三节：前瞻财务驱动与对账桥接 (Financial Driver Bridge)”，完整输出分项金额、驱动来源、对账公式依据、预测区间起止、币种与限制说明。
  - 前端界面交互与披露：
    - `frontend/app/valuation/[ticker]/page.tsx`: 新增 `FinancialBridgeCard` 组件，直观展示财务桥接对账表；在高级配置表单中新增 6 项细分财务驱动参数的编辑输入与说明。

### 7. 可复现的 Live 真实环境四标的 (NVDA, GOOG, AMD, META) 审计
- **整改措施**：
  - 编写并固化了独立的有界 Live 测试脚本：`.scratch/valuation-ai-audit-20260911/verification/r2/run_live_audit.py`。
  - 使用 `DATA_PROVIDER=live` 且无 demo 伪造对 4 标的进行并发受控抓取，原始响应已完整固化于 `.scratch/valuation-ai-audit-20260911/verification/r2/live_results.json`。
  - 4 标的真实运行结果见下文。

---

## 二、命令、环境与测试执行证据

### 1. 测试套件执行记录
- **红灯失败测试（Red Log）**:
  - 文件位置：`.scratch/valuation-ai-audit-20260911/verification/r2/red.log`
  - 失败原因：捕获到真实的 D&A 缺失、无细分驱动时 DCF 需 fail-closed、API reset 校验等。
- **全绿通过测试（Green Log）**:
  - 执行命令：`.venv\Scripts\pytest backend\tests\ -v > .scratch\valuation-ai-audit-20260911\verification\r2\green.log`
  - 退出码：`0`
  - 结果：**301 passed, 2 warnings in 4.75s (100% 通过)**。
- **针对性回归测试集**:
  - 执行命令：`.venv\Scripts\pytest backend\tests\test_audit_issues_01_02_regression.py -v`
  - 退出码：`0`
  - 结果：**14 passed in 0.86s**。

### 2. 前端静态类型与代码质量检查
- **类型检查 (Typecheck)**:
  - 工作目录：`D:\workshop\stock-valuation\frontend`
  - 执行命令：`npm run typecheck`
  - 退出码：`0` (`tsc --noEmit` 通过，无类型错误)
- **代码规范检查 (ESLint)**:
  - 执行命令：`npx eslint lib/exportMarkdown.ts lib/types.ts app/valuation/[ticker]/page.tsx`
  - 退出码：`0` (0 errors, 0 warnings)

### 3. 真实上游 Live 审计证据（NVDA / GOOG / AMD / META）
- **执行命令**: `.venv\Scripts\python .scratch\valuation-ai-audit-20260911\verification\r2\run_live_audit.py`
- **退出码**: `0`
- **数据源与参数**: `DATA_PROVIDER=live`, `timeout=15.0s`, `is_demo: false`
- **四标的对账结果摘要**:
  1. **NVDA (NVIDIA Corporation)**:
     - 耗时：6.43s | 参考股价：$218.36 USD | 财报基准：TTM (四季流量累加，年报回退: False) | 股数基准：ALL_CLASS_RECONCILED
     - 四模型可用性：forward_pe=True ($263.80), ev_ebitda=True ($407.40), fcf_yield=True ($105.19), dcf=True ($410.13)
     - 财务桥接 (NTM 2026-09-10 ~ 2027-09-10):
       - Revenue = $577,805,410,595
       - EBITDA Margin = 77.20% $\rightarrow$ EBITDA = $446,065,776,979
       - D&A = $7,031,638,712 $\rightarrow$ EBIT = $439,034,138,267
       - Tax Rate = 16.05% $\rightarrow$ NOPAT = $368,586,189,649
       - CapEx = $14,025,134,550, ΔNWC = -$77,706,568,839
       - FCFF = $368,586,189,649 + $7,031,638,712 - $14,025,134,550 - (-$77,706,568,839) = **$439,299,262,650**
  2. **GOOG (Alphabet Inc.)**:
     - 耗时：3.99s | 参考股价：$330.39 USD | 财报基准：TTM | 股数基准：ALL_CLASS_RECONCILED
     - 四模型可用性：forward_pe=True ($332.60), ev_ebitda=True ($772.77), fcf_yield=True ($415.96), dcf=True ($251.13)
     - 财务桥接 (NTM 2026-09-10 ~ 2027-09-10):
       - Revenue = $578,100,773,084
       - EBITDA Margin = 73.29% $\rightarrow$ EBITDA = $423,690,056,593
       - D&A = $32,721,706,720 $\rightarrow$ EBIT = $390,968,349,873
       - Tax Rate = 18.40% $\rightarrow$ NOPAT = $319,032,127,887
       - CapEx = $171,669,351,080, ΔNWC = -$5,979,811,840
       - FCFF = $319,032,127,887 + $32,721,706,720 - $171,669,351,080 - (-$5,979,811,840) = **$186,064,295,367**
       - After-tax Interest = $1,837,643,257, Net Borrowing = $70,129,000,000
       - FCFE = $186,064,295,367 - $1,837,643,257 + $70,129,000,000 = **$254,355,652,110**
  3. **AMD (Advanced Micro Devices, Inc.)**:
     - 耗时：3.65s | 参考股价：$503.60 USD | 财报基准：TTM | 股数基准：ALL_CLASS_RECONCILED
     - 桥接成功生成，财务恒等式严格闭合。
  4. **META (Meta Platforms, Inc.)**:
     - 耗时：3.64s | 参考股价：$644.38 USD | 财报基准：TTM | 股数基准：ALL_CLASS_RECONCILED
     - 桥接成功生成，财务恒等式严格闭合。

---

## 三、代码变更清单与统计 (Git Diff Stat)

```
 backend/app/models/domain.py                       |  20 +
 backend/app/models/overrides.py                    |  55 +++
 backend/app/providers/avgo_fixture.py              |  15 +
 backend/app/providers/statement_aggregator.py      | 127 ++++++-
 backend/app/providers/yfinance_provider.py         | 130 +++----
 backend/app/services/projections.py                | 418 ++++++++++++++++-----
 backend/app/services/valuation_service.py          |  48 ++-
 backend/tests/test_acceptance_rejection_fixes.py   |  12 +-
 backend/tests/test_audit_issues_01_02_regression.py| 633 +++++++++++++++++++++
 backend/tests/test_e2e_valuation_integrity_export.py| 70 ++++
 backend/tests/test_final_acceptance.py             |   7 +-
 backend/tests/test_p0_p1_deep_remediation.py       |   4 +-
 frontend/app/valuation/[ticker]/page.tsx           | 218 +++++++++++
 frontend/lib/exportMarkdown.ts                     |  75 +++-
 frontend/lib/types.ts                              |  50 +++
 15 files changed, 1878 insertions(+), 195 deletions(-)
```

---

## 四、剩余说明与边界约束

1. **工单状态流转**：工单 01 与 02 的状态严格维持 `ready-for-human`，待主控二轮正式验收通过后方可关闭。
2. **无关工单隔离**：严格保护未修改工单 03—08；未改动折现率 WACC 计算体系、Terminal Growth Fade 衰减逻辑或综合阈值规则。
3. **版本库安全性**：全过程严格遵守版本库安全约束，未执行任何 `git clean`、`reset --hard`、`commit` 或 `push`。
