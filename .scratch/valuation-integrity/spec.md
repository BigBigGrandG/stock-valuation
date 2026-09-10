# Specification: P0/P1 Valuation Integrity & Diagnostic Remediation

**Feature Slug**: `valuation-integrity`  
**Status**: `Approved / In Implementation`  
**Date**: `2026-09-10`  
**Baseline Audits**: `.scratch/valuation-audit/system-audit.md`, `.scratch/valuation-audit/financial-audit.md`  

---

## 1. Objectives & Scope

This specification defines the architectural and financial contracts to resolve the seven P0/P1 issues identified in the system and financial audits of AMD, META, and GOOG:

1. **[P0-A] Share Capital Reconciliation (全类全时点股本对账)**:
   - Equity-to-per-share bridge must use latest, all-class combined point-in-time common shares.
   - Cross-check `sharesOutstanding`, `impliedSharesOutstanding`, and balance sheet Ordinary Shares with explicit basis and reconciliation provenance.
   - Forward P/E (per-share flow) remains decoupled from aggregate share count.
   - Unmodeled future SBC/repurchase dilution noted clearly without double deduction.

2. **[P0-B] True TTM Statement Aggregation (真TTM聚合与回退隔离)**:
   - Flow statements (income & cash flow) aggregate the latest 4 consecutive, non-overlapping quarters.
   - Balance sheet takes the latest point-in-time quarter (never summed across 4 quarters).
   - If 4 complete quarters are unavailable, fall back explicitly to annual statement (`period: FY...`) with `annual_fallback: true` and active stale warnings; never masquerade annual figures as TTM.

3. **[P0-C] Calendar-Anchored DCF Projection & Discounting (日历锚定DCF与实际折现)**:
   - Cash flow periods and discounting strictly anchor to the valuation `as_of` date ($D_0$).
   - Year 1 covers the 12-month forward window $(D_0, D_0 + 1\text{y}]$, with subsequent anniversary horizons.
   - Disclose actual year fraction (ACT/365 convention) and growth compound horizon from historical base.
   - Strictly prohibit labeling past fiscal years as future projections (e.g. no FY2025E in 2026-09).
   - Terminal Value is discounted at Year 5 horizon without adding phantom years.

4. **[P1-D] NTM Consensus Horizon Selection (滚动NTM与财年选择)**:
   - Allow user/API selection: `ntm` (default), `current_fy` (0y), or `next_fy` (+1y).
   - Calculate NTM dynamically using linear calendar day weights $(w_0, w_1)$ derived from verified fiscal year end dates (`nextFiscalYearEnd`).
   - If either estimate is missing or contradictory, gracefully fall back to the verified single FY with clear lineage.

5. **[P1-E] Configurable Derived Growth Floor & Cap (可配置增长率上下限)**:
   - Expose `growth_floor` (default `-0.20`, allowed `> -1.0`) and `growth_cap` (default `0.40`, allowed `<= 2.0`).
   - Allow request-level overrides without cross-request state or cache leaks.

6. **[P1-F] Flexible Multi-Model Weighting & Cash Flow Group Cap (模型权重与现金流上限)**:
   - Support arbitrary non-negative weights for available models (`weight_pe`, `weight_ev_ebitda`, `weight_fcf_yield`, `weight_dcf`).
   - Effective weights renormalize to 1.0 across active models.
   - Introduce `cashflow_group_max_weight` (default `0.40`, adjustable) to prevent correlated FCF/DCF distortion during Capex-heavy cycles.
   - If only cashflow models are available, return clear policy status with cashflow sensitivity.
   - Reject all-zero weights with typed validation error.

7. **[P1-G] Terminal Value 3x3 Sensitivity Grid (终值3x3敏感性矩阵)**:
   - Generate a 3x3 grid around base WACC ($\pm 1\%$) and terminal growth $g$ ($\pm 0.5\%$).
   - Central cell $(W_0, g_0)$ exactly matches base DCF price per share.
   - Validate $W > g$; mark invalid cells `unavailable` without crashing.
   - Calculate $TV / EV$ ratio; tag $>70\%$ as moderate sensitivity and $>80\%$ as strong dependency.

---

## 2. Technical Contracts & Schemas

### 2.1 Backend Overrides Contract (`ValuationOverrideRequest`)
```python
class WeightOverride(BaseModel):
    weight_pe: Optional[Decimal] = None
    weight_ev_ebitda: Optional[Decimal] = None
    weight_fcf_yield: Optional[Decimal] = None
    weight_dcf: Optional[Decimal] = None
    cashflow_group_max_weight: Optional[Decimal] = None

class DCFOverride(BaseModel):
    wacc: Optional[Decimal] = None
    terminal_growth: Optional[Decimal] = None
    fcf_growth: Optional[Decimal] = None
    growth_floor: Optional[Decimal] = None
    growth_cap: Optional[Decimal] = None

class ValuationOverrideRequest(BaseModel):
    forward_pe: Optional[PEOverride] = None
    ev_ebitda: Optional[EVEBITDAOverride] = None
    fcf_yield: Optional[FCFYieldOverride] = None
    dcf: Optional[DCFOverride] = None
    weights: Optional[WeightOverride] = None
    forecast_horizon: Optional[Literal["ntm", "current_fy", "next_fy"]] = None
```

### 2.2 Sensitivity Matrix Contract (`DCFSensitivityMatrix`)
```python
class DCFSensitivityCell(BaseModel):
    wacc: Decimal
    terminal_growth: Decimal
    price_per_share: Optional[Decimal] = None
    enterprise_value: Optional[Decimal] = None
    equity_value: Optional[Decimal] = None
    tv_ratio: Optional[Decimal] = None
    available: bool = True
    unavailable_reason: Optional[str] = None

class DCFSensitivityMatrix(BaseModel):
    wacc_range: list[Decimal]
    terminal_growth_range: list[Decimal]
    cells: list[list[DCFSensitivityCell]]
    base_tv_ratio: Decimal
    tv_dependence_warning: Optional[str] = None
```

---

## 3. Frontend & Export Integrity
- Frontend provides collapsible **Advanced Settings (高级估值参数)**.
- Real-time display of True TTM vs Annual Fallback badge.
- Share reconciliation basis popup/text.
- 3x3 interactive DCF sensitivity table with color-coded TV ratio alerts.
- Markdown export includes all active override assumptions, effective weights, share basis, and sensitivity grid.
