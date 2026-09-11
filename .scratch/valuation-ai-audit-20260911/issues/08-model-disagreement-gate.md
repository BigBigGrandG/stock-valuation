# Issue 08: 附属综合决策门禁 - 模型分歧提示与熔断门禁（候选策略） (Model Disagreement Gate)

Status: needs-triage
Execution: deferred_by_user
Audit-Finding: confirmed
Severity: high
Feature: valuation-ai-audit-20260911

## 1. 缺陷核验证据 (Audit Verification & Provenance)
- **原始报告行号证据**：
  - 四份报告各模型单项公允价值与最大/最小比值：
    - GOOG: Max $407.42 / Min $208.42 = **1.95x** (+95.48% 离散)
    - META: Max $1,153.86 / Min $663.40 = **1.74x** (+73.93% 离散)
    - AMD: Max $264.60 / Min $141.09 = **1.88x** (+87.54% 离散)
    - NVDA: Max $263.80 / Min $112.10 = **2.35x** (+135.33% 离散)
  - 系统在模型分歧显著时，依然机械平均合成综合公允价值，NVDA 恰好合成 $201.48 并得出合理估值结论。
- **源码行号证据**：
  - `backend/app/engines/composite.py` L54-58, L151-175：模型满足 `_complete_positive` 后直接线性加权合成 `fair_value_base`，未对模型间离散度做约束。
- **事实裁定**：`confirmed`。系统缺少模型分歧提示与熔断门禁机制。

## 2. 根因分析与影响边界 (Root Cause & Impact)
- **根因**：综合引擎定位为纯算术加权计算器，未设置上层置信度与分歧熔断逻辑。
- **影响边界**：在模型假设冲突剧烈时，单一机械综合值容易掩盖底层假设风险。

## 3. 拟议解决方案 (Candidate Proposals for Review)
1. **建立模型分歧度监控指标**：
   - 计算参与综合模型的离散比值 $\text{Ratio} = \frac{\max(P_i)}{\min(P_i)}$；
2. **评估分歧门禁策略（待校准候选提案）**：
   - 评估在比值超过一定阈值（如候选阈值 1.50x）时，禁止输出单一确定性投资结论，改为输出区间展示并提示模型冲突原因。

## 4. 验收标准 (Acceptance Criteria)
- [ ] 策略评审明确模型分歧度指标的阈值与交互规范；
- [ ] 极端离散时系统输出清晰的模型假设冲突警示。

## Comments
- 2026-09-11: 附属综合质量工单。主控指示作为候选策略规范纳入，状态设为 needs-triage，Execution 标记为 deferred_by_user。
