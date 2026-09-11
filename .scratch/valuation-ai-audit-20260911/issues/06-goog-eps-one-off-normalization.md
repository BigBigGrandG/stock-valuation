# Issue 06: 严重4 - GOOG NTM EPS 一次性收益影响待证实 (GOOG EPS Normalization)

Status: needs-info
Execution: deferred_by_user
Audit-Finding: unproven
Severity: high
Feature: valuation-ai-audit-20260911

## 1. 缺陷核验证据 (Audit Verification & Provenance)
- **原始报告行号证据**：
  - GOOG 报告第 105 行、117 行：`NTM day-weighted blend: 30.7% FY1 (20.60) + 69.3% FY2 (14.85) = $16.61`。
  - FY1 EPS ($20.60) 显著高于 FY2 EPS ($14.85)。
- **源码行号证据**：
  - `backend/app/providers/yfinance_provider.py` L895-931：直接采用 yfinance `earnings_estimate.loc["0y", "avg"]`。
  - `backend/app/services/projections.py` L120-135：直接进行年度日历插值。
- **一手事实核查与限制**：
  - Alphabet 2026-06-30 10-Q 原文中，Q2 确实存在其他收益净额约 $98B（权益证券未实现增值净额约 $99B）。
  - **核心未证实点**：外部卖方分析师对 FY2026 的 EPS 一致预期（$20.60）是否为已做非经常性调整的 Non-GAAP/Adjusted 口径，目前缺乏上游 vendor 明细披露证据。在获得明细凭据前，不能将“EPS 受到污染”作为已确凿事实。
- **事实裁定**：`unproven`。

## 2. 根因分析与影响边界 (Root Cause & Impact)
- **根因**：外部数据消费层未对分析师一致预期的底层会计口径（GAAP vs Non-GAAP）进行自动化甄别。
- **影响边界**：若分析师预测包含重大未实现资产重估收益，可能导致 P/E 模型前瞻基数产生偏差。

## 3. 拟议解决方案 (Proposed Remediation)
1. **上游预测口径核查调查**：向数据商验证 consensus EPS 的口径规范。
2. **异常倒挂告警机制**：对成熟企业 FY1 显著高于 FY2 的异常倒挂发出提示，允许用户输入经清洗的经营性 EPS。

## 4. 验收标准 (Acceptance Criteria)
- [ ] 补充外部 vendor EPS 口径标准证据；
- [ ] 在出现重大倒挂时提供提示与自定义覆盖机制。

## Comments
- 2026-09-11: 裁定为 unproven，状态置为 needs-info，保留待核验，不按 confirmed 漏洞处理。
