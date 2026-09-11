# Issue 02: 致命2 - Live 路径季度属性未声明导致静默年报回退 (Quarterly Statement Bundle Bug)

Status: resolved
Execution: accepted_by_coordinator
Audit-Finding: confirmed
Severity: fatal
Feature: valuation-ai-audit-20260911

## 主控验收（2026-09-11）

季度初始化、异常传播、TTM/PIT 和真实数据链路已通过本次验收；主控独立全量测试 346 passed，exit 0。详见 [最终验收记录](../final-acceptance-01-02.md)。以下历史缺陷证据保留，不代表当前版本仍有同一问题。

## 1. 缺陷核验证据 (Audit Verification & Provenance)
- **原始报告行号证据**：
  - 四份报告基本信息表（第 13 行）：`财务报表统计口径：年报回退 (ANNUAL_FALLBACK)`；
  - 四份报告数据提醒（第 22 行）：`Financial inputs are stale (oldest age 253 days)`；
  - 输入明细表中资产负债表与现金流基准日停留在 2025/12/31（NVDA 为 2026/01/31）。
  - **官方最新财报所属季度截止日核实**：Alphabet/Meta 为 2026-06-30，AMD 为 2026-06-27，NVIDIA 为 **2026-07-26**。供应商月末标签不等于实际财务截止日。
- **源码行号证据**：
  - `backend/app/providers/yfinance_provider.py` L220-236：`_TickerBundle.__init__` 初始化属性仅声明了 `_bs, _cf, _fin, _ee, _re`，缺少 `_qbs, _qcf, _qfin`。
  - `backend/app/providers/yfinance_provider.py` L337-360：`get_quarterly_balance_sheet()` 等方法尝试读取 `self._fetch_property("_qbs", ...)`。
  - `backend/app/providers/yfinance_provider.py` L258：`_fetch_property` 执行 `getattr(self, prop_name)` 抛出 `AttributeError: '_TickerBundle' object has no attribute '_qcf'`。
  - `backend/app/providers/yfinance_provider.py` L340, L350, L360：外层 `except Exception: return None` 静默捕获了此 AttributeError，导致在默认 live 模式新建 bundle 路径下，季度接口恒定返回 `None`。
  - `backend/app/providers/statement_aggregator.py` L128-136, L193-197：因入参全为 None，聚合器被迫触发 `ANNUAL_FALLBACK`。
- **作用边界精确定位**：
  - 缺陷专门限定在默认 live 模式下新建 bundle 访问未声明属性的代码路径；在离线 demo 模式或完整 mock 环境下不触发；
  - 澄清：即使官方存在最新 10-Q，若公开数据源客观缺失连续 4 季度数据，系统仍应合法回退年报。
- **事实裁定**：`confirmed`。

## 2. 根因分析与影响边界 (Root Cause & Impact)
- **根因**：`_TickerBundle` 类定义中属性初始化遗漏，配合宽泛的异常吞没，阻断了 live 季度数据的提取。
- **影响边界**：导致在线 live 实时查询无法提取最新季度资产负债表与 TTM 滚动数据。

## 3. 拟议解决方案 (Proposed Remediation)
1. **完善属性声明**：在 `_TickerBundle.__init__` 中显式添加 `self._qbs = None`、`self._qcf = None`、`self._qfin = None`。
2. **规范异常捕获**：仅安全捕获上游网络与超时异常，严禁捕获并掩盖代码级程序错误。
3. **合法回退保护**：当上游数据源客观缺失 4 季度数据时，保留清晰可溯源的 `ANNUAL_FALLBACK` 路径。

## 4. 验收标准 (Acceptance Criteria)
- [x] 在提供完整 4 季度离散财报 fixture 的条件下，系统成功提取最新季度 PIT 现金与债务，产出 4 季度 TTM，`statement_basis` 返回 `TTM`，`annual_fallback` 为 `False`。
- [x] 当季度数据客观缺失时，系统合规回退年报并正确记录 fallback 原因。

## Comments
- 2026-09-11: 缺陷定位确凿且经离线诊断命令复现。
- 2026-09-11: 端到端实现完成（工单02）。修复 `_TickerBundle` 初始化缺失季度属性缺陷，消除异常吞没，确保 live 实时及受控 fixture 读取季度数据生成 TTM。4 项专用回归测试全部通过。等待主控验收。
