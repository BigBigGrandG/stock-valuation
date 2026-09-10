/**
 * Types for the valuation API.
 *
 * The backend serializes Decimal values as JSON strings. A few compatibility
 * unions intentionally accept numbers too: this keeps the UI useful while a
 * provider is swapped or a locally running backend is upgraded.
 */

export type DecimalLike = string | number;

export interface FinancialMetric {
  value: DecimalLike;
  unit: string;
  period: string;
  source: string;
  source_type: string;
  as_of: string;
  confidence?: number;
  is_estimated: boolean;
  notes?: string;
}

export type MetricMap = Record<string, FinancialMetric>;

export interface PriceEstimate {
  price_per_share: DecimalLike;
  upside_pct: DecimalLike;
  premium_discount_pct: DecimalLike;
  intermediates?: Record<string, unknown>;
}

export interface ProjectionMetric {
  year?: number | string;
  label?: string;
  period?: string;
  fcff?: FinancialMetric | DecimalLike;
  pv?: FinancialMetric | DecimalLike;
  fcff_metric?: FinancialMetric;
  pv_metric?: FinancialMetric;
  [key: string]: unknown;
}

export interface DCFSensitivityCell {
  wacc: DecimalLike;
  terminal_growth: DecimalLike;
  price_per_share?: DecimalLike;
  enterprise_value?: DecimalLike;
  equity_value?: DecimalLike;
  tv_ratio?: DecimalLike;
  available: boolean;
  unavailable_reason?: string;
}

export interface DCFSensitivityMatrix {
  wacc_range: DecimalLike[];
  terminal_growth_range: DecimalLike[];
  cells: DCFSensitivityCell[][];
  base_tv_ratio: DecimalLike;
  tv_dependence_warning?: string;
}

export interface DCFScenario {
  scenario: "bear" | "base" | "bull" | string;
  wacc: DecimalLike;
  terminal_growth: DecimalLike;
  growth_rate?: DecimalLike;
  growth_metric?: FinancialMetric | Record<string, unknown>;
  growth_cap?: DecimalLike;
  growth_floor?: DecimalLike;
  fcff_year1: DecimalLike;
  fcff_projections: DecimalLike[];
  projection_periods?: string[];
  pv_projections: DecimalLike[];
  pv_years?: number[];
  year_fractions?: DecimalLike[];
  period_start_dates?: string[];
  period_end_dates?: string[];
  growth_compound_horizon?: string;
  projection_years?: Array<number | string>;
  projection_metrics?: ProjectionMetric[] | Record<string, ProjectionMetric>;
  terminal_value: DecimalLike;
  pv_terminal_value: DecimalLike;
  enterprise_value: DecimalLike;
  total_debt: DecimalLike;
  cash: DecimalLike;
  net_debt: DecimalLike;
  equity_value: DecimalLike;
  diluted_shares: DecimalLike;
  price_per_share: DecimalLike;
  upside_pct: DecimalLike;
  premium_discount_pct: DecimalLike;
  formula?: string;
  formula_description?: string;
  formulas?: Record<string, string>;
  calculation_steps?: string[];
  input_metrics?: MetricMap;
  assumption_metrics?: MetricMap;
  warnings: string[];
}

export interface ModelValuation {
  formula: string;
  formula_description: string;
  inputs: Record<string, unknown>;
  assumptions: Record<string, unknown>;
  input_metrics?: MetricMap;
  assumption_metrics?: MetricMap;
  calculation_steps: string[];
  low?: PriceEstimate;
  base?: PriceEstimate;
  high?: PriceEstimate;
  dcf_scenarios?: DCFScenario[];
  sensitivity_matrix?: DCFSensitivityMatrix;
  available: boolean;
  unavailable_reason?: string;
  warnings: string[];
  data_quality: "HIGH" | "MEDIUM" | "LOW" | string;
  fair_value_low?: DecimalLike;
  fair_value_base?: DecimalLike;
  fair_value_high?: DecimalLike;
}

export interface CompositeValuation {
  low?: DecimalLike;
  base?: DecimalLike;
  high?: DecimalLike;
  fair_value_low?: DecimalLike;
  fair_value_base?: DecimalLike;
  fair_value_high?: DecimalLike;
  current_price?: DecimalLike;
  weights_used: Record<string, DecimalLike>;
  selected_weights?: Record<string, DecimalLike>;
  effective_weights?: Record<string, DecimalLike>;
  cashflow_group_weight?: DecimalLike;
  cashflow_group_max_weight?: DecimalLike;
  cashflow_sensitivity?: Record<string, unknown>;
  cashflow_group_policy_message?: string;
  available_models: string[];
  normalized_weights?: Record<string, DecimalLike>;
  formula?: string;
  calculation_steps?: string[];
  classification?: string;
  classification_label_zh?: string;
  margin_of_safety?: DecimalLike;
  mos_pct?: DecimalLike;
  upside_downside?: DecimalLike;
  upside_pct?: DecimalLike;
  premium_discount_pct?: DecimalLike;
  available: boolean;
  unavailable_reason?: string;
}

export interface ScenarioValues {
  low: DecimalLike;
  base: DecimalLike;
  high: DecimalLike;
}

export interface ValuationAssumptions {
  pe_target: ScenarioValues;
  pe_source: string;
  pe_source_label: string;
  ev_ebitda_multiple: ScenarioValues;
  ev_ebitda_source: string;
  ev_ebitda_source_label: string;
  fcf_yield: ScenarioValues;
  fcf_yield_source: string;
  fcf_yield_source_label: string;
  dcf_wacc: ScenarioValues;
  dcf_terminal_growth: ScenarioValues;
  dcf_fcf_growth?: ScenarioValues;
  dcf_wacc_source: string;
  dcf_wacc_source_label: string;
  weight_pe: DecimalLike;
  weight_ev_ebitda: DecimalLike;
  weight_fcf_yield: DecimalLike;
  weight_dcf: DecimalLike;
  cashflow_group_max_weight?: DecimalLike;
  growth_floor?: DecimalLike;
  growth_cap?: DecimalLike;
  forecast_horizon?: string;
}

export interface ValuationResponse {
  ticker: string;
  company_name: string;
  current_price: DecimalLike;
  currency: string;
  as_of: string;
  price_timestamp?: string;
  valuations: {
    forward_pe: ModelValuation;
    ev_ebitda: ModelValuation;
    fcf_yield: ModelValuation;
    dcf: ModelValuation;
  };
  composite: CompositeValuation;
  is_demo: boolean;
  data_quality: "HIGH" | "MEDIUM" | "LOW" | string;
  warnings: string[];
  assumptions_used: ValuationAssumptions;
  provider?: string;
  provider_label?: string;
  shares_basis?: string;
  shares_reconciliation?: Record<string, unknown> | string;
  statement_basis?: string;
  annual_fallback?: boolean;
  forecast_fiscal_year_end?: string;
  ntm_weights?: Record<string, DecimalLike>;
  forecast_horizon_effective?: string;
  growth_cap_effective?: DecimalLike;
  growth_floor_effective?: DecimalLike;
}

/** Nested POST contract. Empty fields are omitted by the page before POST. */
export interface OverrideRequest {
  forward_pe?: { base?: number };
  ev_ebitda?: { base?: number };
  fcf_yield?: { base?: number };
  dcf?: {
    wacc?: number;
    terminal_growth?: number;
    fcf_growth?: number;
    growth_floor?: number;
    growth_cap?: number;
  };
  weights?: {
    weight_pe?: number;
    weight_ev_ebitda?: number;
    weight_fcf_yield?: number;
    weight_dcf?: number;
  };
  forecast_horizon?: "current_fy" | "next_fy" | "ntm";
}

export interface OverrideForm {
  pe_base: string;
  ev_base: string;
  fcf_yield_base: string;
  dcf_wacc: string;
  dcf_terminal_growth: string;
  dcf_fcf_growth: string;
  dcf_growth_floor?: string;
  dcf_growth_cap?: string;
  forecast_horizon?: "current_fy" | "next_fy" | "ntm";
  weight_pe?: string;
  weight_ev_ebitda?: string;
  weight_fcf_yield?: string;
  weight_dcf?: string;
}

export const CLASSIFICATION_LABELS_ZH: Record<string, string> = {
  significantly_undervalued: "严重低估",
  undervalued: "低估",
  slightly_undervalued: "略微低估",
  fairly_valued: "合理估值",
  overvalued: "高估",
  significantly_overvalued: "严重高估",
};

export const DATA_QUALITY_LABELS_ZH: Record<string, string> = {
  HIGH: "高质量",
  MEDIUM: "中等质量",
  LOW: "低质量",
};

export const MODEL_LABELS_ZH: Record<string, string> = {
  forward_pe: "市盈率估值",
  ev_ebitda: "EV / EBITDA 估值",
  fcf_yield: "FCF 收益率估值",
  dcf: "现金流折现（DCF）",
};
