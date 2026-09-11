# Issue 03: 严重1 - 全量使用单一硬编码 Fallback 倍数 (Company-Specific Multiples)

Status: ready-for-agent
Execution: deferred_by_user
Audit-Finding: confirmed
Severity: high
Feature: valuation-ai-audit-20260911

## 1. 缺陷核验证据 (Audit Verification & Provenance)
- **原始报告行号证据**：
  - 四份报告第二节第 67~70 行：P/E (18/20/22)、EV/EBITDA (18/22/26)、FCF Yield (5.5%/5.0%/4.5%)、WACC (12%/10%/8%) 全量标注 `Configured fallback`。
  - META 报告第 135 行：22x EV/EBITDA 得出 $1,153.86 离群估值。
- **源码行号证据与事实澄清**：
  - `backend/app/providers/yfinance_provider.py` L1074-1094 (`get_historical_multiples`)：
    源码在第 1088 行直接返回 `None`（`"historical_forward_pe": None, "historical_ev_ebitda": None`），注释说明 trailing 倍数不等于历史前瞻倍数，在缺乏时序数据库时直接返回 `None`。因此系统当前根本没有动态提取历史中位数的实现，直接全量跌入系统全局 fallback。
  - `backend/app/config.py` L14-23, L63-88：全局硬编码唯一定义。
  - `backend/app/services/valuation_service.py` L1056-1070：直接使用静态全局默认值。
- **事实裁定**：`confirmed`。

## 2. 根因分析与影响边界 (Root Cause & Impact)
- **根因**：系统缺乏基于行业或公司历史的前瞻倍数数据库与映射架构。
- **影响边界**：不同行业属性与资本周期的企业套用相同倍数，降低了模型在个股维度的适用性。

## 3. 拟议解决方案 (Proposed Remediation)
1. **支持任意美股，不设静态白名单**：建立基于 GICS 行业或上游行业标签的分层倍数配置。
2. **构建三级倍数仲裁架构**：
   - Level 1: 公司有效历史 3~5 年中位数（过滤离群值）；
   - Level 2: 公司所属行业动态基准；
   - Level 3: 保守系统兜底 Fallback。

## 4. 验收标准 (Acceptance Criteria)
- [ ] 系统能够为不同行业标的匹配具有行业针对性的参考倍数。
- [ ] 当降级至 Level 3 全局兜底时，明确输出参数特异性不足的风险提示。

## Comments
- 2026-09-11: 事实完全确认。已建单备忘。
