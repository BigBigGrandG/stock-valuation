# Issue 04: 严重2 - DCF 预测期末至永续期缺乏平滑衰减 (DCF Growth Fade)

Status: ready-for-agent
Execution: deferred_by_user
Audit-Finding: confirmed
Severity: high
Feature: valuation-ai-audit-20260911

## 1. 缺陷核验证据 (Audit Verification & Provenance)
- **原始报告行号证据**：
  - GOOG 报告第 360-362 行：Year 3~5 FCFF 增速固定为 23.64%，终值增长率突变为 3.00%。
  - META 报告第 360-362 行：Year 3~5 FCFF 增速固定为 26.49%，终值突变为 3.00%。
  - NVDA 报告第 360-362 行：Year 3~5 FCFF 增速固定为 30.00%（上限截断），终值突变为 3.00%。
- **源码行号证据**：
  - `backend/app/engines/dcf.py` L438-449：在 5 年预测期循环中，Year 3~5 均使用静态单一的 `growth_rate` 递推：`value = previous * (1 + growth_rate)`。
- **事实裁定**：`confirmed`。

## 2. 根因分析与影响边界 (Root Cause & Impact)
- **根因**：DCF 引擎采用单一固定增速递推，未考虑企业规模扩张伴随增速放缓的财务规律。
- **影响边界**：导致高速成长公司末期现金流基数被人为推高，在进入永续期时遭遇数学断崖，放大了终值对末期增长率的敏感度。

## 3. 拟议解决方案 (Proposed Remediation)
1. **实施线性增长衰减模型 (Growth Fade)**：
   - Year 1~2: 采用显式前瞻预测增速 $g_1, g_2$；
   - Year 3~5: 增速逐年平滑递减至永续增长率 $g_{terminal}$：
     $$g_t = g_2 - \frac{t - 2}{5 - 2} \times (g_2 - g_{terminal})$$
2. **公开呈现 Fade 轨迹**：在 DCF 预测明细表中逐年展示生效增速及衰减过程。

## 4. 验收标准 (Acceptance Criteria)
- [ ] 高成长标的 Year 3~5 FCFF 增速呈现平滑递减趋势，消除与 3% 永续增长率之间的断崖跳跃。
- [ ] 单元测试验证平滑衰减算法在各种初速度下的收敛性。

## Comments
- 2026-09-11: 财务建模缺陷确凿。已建单。
