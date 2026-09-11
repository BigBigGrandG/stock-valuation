# Issue 05: 严重3 - DCF 终值占比警示未进入综合加权控制（候选策略） (TV Sensitivity Gate)

Status: needs-triage
Execution: deferred_by_user
Audit-Finding: partial
Severity: medium
Feature: valuation-ai-audit-20260911

## 1. 缺陷核验证据 (Audit Verification & Provenance)
- **原始报告行号证据**：
  - 四份报告第 23 行、280 行：GOOG (78.6%)、META (79.2%)、AMD (80.2%)、NVDA (80.2%) 均触发了 TV/EV > 70% 或 > 80% 的高敏感度警示。
  - 第一节综合计算推导过程中，四家公司的 DCF 权重依然均享受顶格的 21.82% 有效权重。
- **源码行号证据**：
  - `backend/app/engines/dcf.py` L622-632：仅将警告存入 `warnings` 文本列表。
  - `backend/app/engines/composite.py` L48-58, L129-150：综合引擎未读取 `warnings` 或 `tv_ratio` 对权重进行动态调整。
- **财务严谨性核查**：
  - 终值占比高反映企业价值依赖长期现金流，不能断言模型失去了 DCF 意义；警示未联动权重属实，但阶梯降权属于候选风控策略，非代码算术错误。
- **事实裁定**：`partial`。

## 2. 根因分析与影响边界 (Root Cause & Impact)
- **根因**：展示层监控提示未与综合估值引擎建立控制联动。
- **影响边界**：在终值极度敏感时，未能在综合层提示或缓冲终值假设波动对目标价的冲击。

## 3. 拟议解决方案 (Candidate Proposals for Review)
1. **评估终值敏感度与权重联动策略（待校准候选）**：
   - 候选方案 A：当 $TV / EV > 70\%$ 或 $> 80\%$ 时，评估对 DCF 权重实施阶梯式缩减或降为敏感性参考；
   - 候选方案 B：保持权重不变，但在综合评估中显著强化终值敏感性区间提示。

## 4. 验收标准 (Acceptance Criteria)
- [ ] 策略评审确定是否采纳降权方案；若采纳，提供清晰可溯源的推导记录与用户配置开关。

## Comments
- 2026-09-11: 裁定为 partial，初始状态设为 needs-triage 待策略定夺。
