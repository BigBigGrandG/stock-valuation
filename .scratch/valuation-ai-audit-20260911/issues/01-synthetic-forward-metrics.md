# Issue 01: 致命1 - 前瞻指标缺乏细分财务科目驱动缺陷 (Synthetic Forward Metrics)

Status: resolved
Execution: accepted_by_coordinator
Audit-Finding: confirmed
Original-AI-Severity: fatal
Severity: high
Feature: valuation-ai-audit-20260911

## 主控验收（2026-09-11）

已接受 R6 最终修复与前序有效证据；主控独立全量测试 346 passed，exit 0。独立驱动、期间/共识、生产隔离及导出验证详见 [最终验收记录](../final-acceptance-01-02.md)。以下历史缺陷证据保留，不代表当前版本仍有同一问题。

## 1. 缺陷核验证据 (Audit Verification & Provenance)
- **原始报告行号证据**：
  - AMD 报告第 148 行：`forward_ebitda $10.185B (clamped to 40.0%)`；第 200 行：`forward_fcfe $11.516B (* 1.40)`；第 249 行：`forward_fcff_1y $9.57B (* 1.40)`。
  - NVDA 报告第 148 行：`forward_ebitda $202.373B (* 1.40)`；第 200 行：`forward_fcfe $135.346B (* 1.40)`；第 249 行：`forward_fcff_1y $135.65B (* 1.40)`。
- **源码行号证据**：
  - `backend/app/providers/yfinance_provider.py` L727-736, L969-985：EBITDA/FCFE/FCFF 直接绑定 `re_est.growth` 或 `ee.growth` 并强行截断在 `[-20%, +40%]`。
  - `backend/app/services/projections.py` L165-263：`derive_request_projections()` 对历史财务科目机械乘以同一截断增长率。
  - `backend/app/engines/dcf.py` L111-131, L438-449：DCF Year 3~5 继续单倍率滚动。
- **事实与财务建模核验**：
  - **合规事实澄清**：系统并非未披露来源或恶意编造，代码与报告均明确标注了 `source_type = derived` 及其计算公式。
  - **核心财务缺陷**：在缺少明细分析师预测时，系统将营业额增速直接作为 EBITDA、FCFE 和 FCFF 的共同增速。在财务学中，常数利润率下 EBITDA 增速等于营收增速在数学上自洽；真正缺陷在于**缺少 CapEx、营运资本变动（ΔNWC）和净借款等各科目的独立财务假设驱动，导致现金流转化率脱离经营周期**。
- **事实裁定**：`confirmed`。

## 2. 根因分析与影响边界 (Root Cause & Impact)
- **根因**：系统缺少细分财务科目的前瞻预测驱动模型，对非营收科目采用了统一增速外推。
  - **影响边界**：前瞻输入缺乏业务针对性，可能显著偏离高成长或资本开支转型企业的现金流；本次未量化偏差方向与幅度。

## 3. 拟议解决方案 (Proposed Remediation)

## 3. 拟议解决方案 (Proposed Remediation)
1. **构建独立的细分财务驱动模型**：
   - 存在 Revenue 与 EPS 预期时，EBITDA 应通过 `Revenue_Est × Normalized_EBITDA_Margin` 建模；
   - 现金流推导应引入独立的 CapEx 资本开支强度指引、营运资本假设以及债务净变动。
2. **口径隔离与元数据明晰**：
   - 严格隔离 FCFE（含净借款）与 FCFF（无杠杆税后息前），确保推导过程与期间完全透明。

## 4. 验收标准 (Acceptance Criteria)
- [x] 导出报告与 API 响应中，明确披露前瞻指标各项细分财务驱动科目及计算依据。
- [x] 单元测试覆盖独立 CapEx 与利润率波动情景，验证现金流转化率能够真实反映资本开支周期。

## Comments
- 2026-09-11: 独立核验确认为 confirmed 缺陷。
- 2026-09-11: 端到端实现完成（工单01）。新增细分财务科目驱动（EBITDA Margin, CapEx, ΔNWC, D&A, Tax, Net Borrowing）、财务对账桥接（Financial Driver Bridge）披露、API与Markdown导出，并通过全量回归测试。等待主控验收。
