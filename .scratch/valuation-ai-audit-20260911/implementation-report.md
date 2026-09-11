# 工单 01 与 02 实施验收报告 (Implementation Report)

**任务编号**: task_886e7bc60e29  
**调度上下文**: ctx_d032a74b937d  
**基线分支**: master / 11b0495  
**执行角色**: Worker (`term_5abf4fd1-a6db-4d7f-a593-73affbcefd0c`)  
**实施目标**: 端到端解决工单 02（季度缓存未声明导致年报回退）与工单 01（前瞻指标缺乏细分财务科目驱动与对账桥接），保持全套既有测试零破坏，恢复数据链路、预测生成、API 与 Markdown 披露及参数覆盖能力。

---

## 1. 变更文件清单 (Changed Files)

### 后端核心实现 (Backend)
1. **`backend/app/providers/yfinance_provider.py`**:
   - `_TickerBundle.__init__` 中显式初始化季度缓存属性：`self._qbs = None`, `self._qcf = None`, `self._qfin = None`。
   - `_fetch_property` 与各 `get_quarterly_*` 方法修正宽泛异常捕获，禁止吞没内部 `AttributeError` / 程序缺陷，仅合规映射 `ProviderRateLimitError` (429) 与 `ProviderUnavailableError` (503 / timeout)。
2. **`backend/app/models/domain.py`**:
   - 扩充 `CompanyFinancialSnapshot`，加入底层真实财务科目 TTM：`cfo_ttm`, `capex_ttm`, `net_borrowing_ttm`, `da_ttm`, `nwc_change_ttm`, `interest_ttm`。
   - 扩充 `ValuationAssumptions`，加入 9 个独立细分驱动参数（`driver_ebitda_margin`, `driver_capex`, `driver_capex_ratio`, `driver_nwc_change`, `driver_nwc_ratio`, `driver_da`, `driver_da_ratio`, `driver_tax_rate`, `driver_net_borrowing`）。
   - 扩充 `ValuationResponse`，新增 `financial_bridge: Optional[dict[str, Any]]`，输出可对账的财务桥接字典。
3. **`backend/app/models/overrides.py`**:
   - 新增 `FinancialDriversOverride` 校验模型，集成到 `ValuationOverrideRequest.drivers` 及 `to_override_dict()`（支持键前缀 `drivers.`）。
4. **`backend/app/services/projections.py`**:
   - 重构 `derive_request_projections()`，接入前瞻细分财务驱动桥接模型：
     - **EBITDA** = Forecast Revenue × EBITDA Margin
     - **EBIT** = EBITDA − D&A
     - **NOPAT** = EBIT × (1 − TaxRate)
     - **FCFF** = NOPAT + D&A − CapEx − ΔNWC
     - **FCFE** = FCFF − Interest × (1 − TaxRate) + Net Borrowing
   - 严格维护模型边界：直接分析师 consensus 不被 growth 覆写；无独立前瞻预测与用户驱动覆盖时模型诚实隔离 (fail-closed)；净借款严禁污染 FCFF。
5. **`backend/app/services/valuation_service.py`**:
   - 在数据提取层映射季度/报表新增科目至快照；
   - 在 `assemble_response()` 中挂载 `financial_bridge` 结构化对象至 API 响应。

### 前端与报告导出 (Frontend)
6. **`frontend/lib/types.ts`**:
   - 在 `ValuationResponse` 中添加 `financial_bridge?: FinancialBridge | null`。
   - 新增 `FinancialBridge` 与 `FinancialDriversOverride` 接口定义，更新 `OverrideRequest.drivers`。
7. **`frontend/lib/exportMarkdown.ts`**:
   - 新增专章 `## 三、前瞻财务驱动与对账桥接 (Financial Driver Bridge)`，表格化清晰列示营收基准、利润率、D&A、NOPAT、CapEx、ΔNWC、FCFF、税后利息、净借款及 FCFE 各科目金额、数据假设来源与对账逻辑。

### 测试套件 (Tests)
8. **`backend/tests/test_audit_issues_01_02_regression.py`**:
   - 针对工单 01 与 02 编写 8 个核心回归断言，覆盖真实 bundle 属性初始化、异常非吞没、PIT 资产负债表与连续四季 TTM 聚合、细分驱动独立敏感性变化、共识不覆盖、覆盖参数校验与重置、桥接全科目数值精确对账。

---

## 2. 缺陷修复前后对比与验证证据 (Before vs After Evidence)

### 工单 02：季度属性未声明与静默吞没缺陷
- **修复前**：
  - `_TickerBundle` 实例缺失 `_qcf`、`_qbs`、`_qfin` 字段声明。
  - 调用 `get_quarterly_cashflow()` 触发 `AttributeError`，被外层 `except Exception: return None` 静默吞没，所有 live 查询即使上游有完整季度数据也恒定回退为 `ANNUAL_FALLBACK`，报表新鲜度显示滞后达 253 天。
- **修复后**：
  - 属性安全初始化；非网络异常正常暴露；受控连续四季 fixture 稳定产出 `statement_basis == "TTM"`，`annual_fallback == False`；上游 429 限流与超时正确抛出 `ProviderRateLimitError` / `ProviderUnavailableError`。

### 工单 01：前瞻指标缺少细分财务科目驱动缺陷
- **修复前**：
  - 无前瞻分析师预测时，系统直接将营收历史或前瞻增长率强行赋给 EBITDA、FCFE 与 FCFF，机械使用 `base_fcff * (1 + g)`。FCFF 与 FCFE 未作债务现金流调整，CapEx、营运资本周期完全失真。
- **修复后**：
  - 建立标准五步财务勾稽桥接：固定预测营收下，独立改变 CapEx / ΔNWC 可精确减少 FCFF 与 FCFE，不改变 EBITDA；独立改变 Net Borrowing 仅改变 FCFE，**FCFF 绝不受 Net Borrowing 影响**；直接分析师一致预期被严格保护不覆写；API 与导出的 Markdown 披露完整桥接明细。

---

## 3. 核心财务对账数值示例 (Numerical Example)

以针对性测试中的 ACME 标的（营收预测 $100,000，税率 25%）基准场景为例：
- **预测营业收入 (Revenue)**: $100,000
- **EBITDA 利润率**: 40.00%
- **前瞻 EBITDA**: $100,000 × 40% = **$40,000**
- **折旧与摊销 (D&A)**: $5,000
- **息税前利润 (EBIT)**: $40,000 − $5,000 = **$35,000**
- **税后净营业利润 (NOPAT)**: $35,000 × (1 − 25%) = **$26,250**
- **资本开支 (CapEx)**: $10,000
- **营运资本变动 (ΔNWC)**: $2,000
- **企业自由现金流 (FCFF)**: $26,250 + $5,000 − $10,000 − $2,000 = **$19,250**
- **利息支出**: $1,500，税后利息 = $1,500 × (1 − 25%) = $1,125
- **净借款增加额 (Net Borrowing)**: +$3,000
- **股权自由现金流 (FCFE)**: $19,250 − $1,125 + $3,000 = **$21,125**

各分项加减勾稽 100% 严密自洽，并在 API 响应与 Markdown 导出中完整对账。

---

## 4. 测试与验证执行记录 (Verification Summary)

| 验证项 | 执行命令 | 退出码 | 结果与结论 |
| :--- | :--- | :---: | :--- |
| 工单01/02专项目标测试 | `.venv\Scripts\pytest backend/tests/test_audit_issues_01_02_regression.py -v` | **0** | 8 passed (全部通过) |
| 后端全量测试回归 | `.venv\Scripts\pytest backend/tests/ -v` | **0** | **294 passed** (0 failed，全套零破坏) |
| 前端类型检查 | `npm run typecheck` (in `frontend/`) | **0** | tsc --noEmit 通过，无任何类型错误 |
| 前端修改文件 Lint | `npx eslint lib/exportMarkdown.ts lib/types.ts` | **0** | 0 errors, 0 warnings (代码风格合规) |
| 真实 Live 数据验证 | Python 脚本真实在线查询 NVDA, GOOG, AMD, META | **0** | 4 支股票全部成功拉取 live 季度数据，`statement_basis: TTM`，全部 4 估值模型正常输出，财务桥接完整。 |

---

## 5. 限制与剩余问题说明 (Limitations & Remaining Scope)

1. **工单 03 至 08 保持延后 (Deferred)**：
   - 本次严格遵守契约边界，未修改 03—08 工单代码或测试，未引入 growth fade、公司倍数、WACC 调整或综合阈值变更。
2. **工单状态标识**：
   - 按照契约约束（“主控验收前工单不标 resolved”），`issues/01` 与 `issues/02` 当前状态更新为 `ready-for-human`，待主控验收评估后做最终闭环。
