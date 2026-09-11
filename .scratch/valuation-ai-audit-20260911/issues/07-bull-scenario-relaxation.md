# Issue 07: 严重5 - Bull 情景三向同时放松与宏观资本结构校准 (Bull Scenario Macro Realism)

Status: needs-triage
Execution: deferred_by_user
Audit-Finding: partial
Severity: medium
Feature: valuation-ai-audit-20260911

## 1. 缺陷核验证据 (Audit Verification & Provenance)
- **原始报告行号证据**：
  - NVDA 报告第 234~236 行、第 256~264 行：Base EV $4.75T ($199.05) -> Bull EV $9.23T ($384.50)。
  - META 报告第 234~236 行：Base $686.70 -> Bull $1,315.74。
- **源码行号证据**：
  - `backend/app/config.py` L21-26：`DEFAULT_DCF_WACC = ScenarioValues(low=0.12, base=0.10, high=0.08)`；`DEFAULT_DCF_TERMINAL_GROWTH = ScenarioValues(low=0.03, base=0.03, high=0.04)`。
  - `backend/app/engines/dcf.py` L66-74：Bull 情景同时选取最高增长率、最低贴现率和最高永续增长率。
- **宏观与财务理论校准**：
  - 美国财政部 2026-09-09 10 年期美债收益率为 4.83%。在情景分析中，Bull Case 同时采取高成长、低贴现率与高永续假设属于经典情景分析范式，不属于程序 Bug。
  - 严谨的 WACC 必须基于 CAPM 权益成本与市场资本结构税后债务成本框架，不能脱离 Beta 与资本结构凭空断言固定数值下限。
- **事实裁定**：`partial`。

## 2. 根因分析与影响边界 (Root Cause & Impact)
- **根因**：情景参数为全局静态设定，缺乏与无风险利率及资本结构的内生关联。
- **影响边界**：利差 $WACC - g$ 收窄至 4% 会在极端情景下放大终值，降低情景分析的现实指导意义。

## 3. 拟议解决方案 (Candidate Proposals for Review)
1. **建立严谨的 CAPM 资本结构贴现率框架**：
   - 权益成本：$K_e = R_f + \beta \times \text{ERP}$；
   - 贴现率加权：$WACC = \frac{E}{V} K_e + \frac{D}{V} K_d (1 - T)$。
2. **数学约束与利差警示**：严格保证 $WACC > g_{terminal}$，并对过窄利差进行敏感度提示。

## 4. 验收标准 (Acceptance Criteria)
- [ ] 贴现率计算体现标的 Beta 与市场资本结构特征；
- [ ] 极小利差下输出敏感度与假设激进性提示。

## Comments
- 2026-09-11: 裁定为 partial，初始状态设为 needs-triage。
