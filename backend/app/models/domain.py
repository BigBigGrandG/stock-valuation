"""
Domain objects for the stock-valuation service.

The API intentionally keeps provenance next to every number. A ``Decimal``
is used for calculations and is rendered as a JSON string by ``app.main`` so
that a client never has to guess whether a rounded float was used.

Two cash-flow concepts are deliberately separate throughout this module:

* FCFE is an equity cash flow and is used by the FCF-yield model.
* FCFF is an unlevered firm cash flow and is discounted at WACC by the DCF.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class SourceType(str, Enum):
    ACTUAL = "actual"
    ANALYST_ESTIMATE = "analyst_estimate"
    DERIVED = "derived"
    CONFIGURED_FALLBACK = "configured_fallback"
    USER_OVERRIDE = "user_override"
    FIXTURE = "fixture"


class DataQuality(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ValuationClassification(str, Enum):
    SIGNIFICANTLY_UNDERVALUED = "significantly_undervalued"
    UNDERVALUED = "undervalued"
    SLIGHTLY_UNDERVALUED = "slightly_undervalued"
    FAIRLY_VALUED = "fairly_valued"
    OVERVALUED = "overvalued"
    SIGNIFICANTLY_OVERVALUED = "significantly_overvalued"


class FCFType(str, Enum):
    """The two cash-flow definitions accepted by the valuation models."""

    FCFE = "FCFE"
    FCFF = "FCFF"


class UnsupportedReason(str, Enum):
    BANK_OR_INSURANCE = "bank_or_insurance"
    REIT = "reit"
    SPAC = "spac"
    ETF = "etf"
    LONG_TERM_LOSS = "long_term_loss"
    NON_US = "non_us"
    NOT_FOUND = "not_found"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    CURRENCY_MISMATCH = "currency_mismatch"


class FinancialMetric(BaseModel):
    """A value plus the provenance required to interpret it safely."""

    value: Decimal
    unit: str
    period: str
    source: str
    source_type: SourceType
    as_of: date
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    is_estimated: bool = False
    notes: Optional[str] = None

    model_config = {"frozen": True}

    @field_validator("value", mode="before")
    @classmethod
    def _finite_value(cls, value: object) -> Decimal:
        try:
            result = value if isinstance(value, Decimal) else Decimal(str(value))
        except Exception as exc:
            raise ValueError(f"metric value must be a Decimal-compatible number: {value!r}") from exc
        if not result.is_finite():
            raise ValueError(f"FinancialMetric value must be finite, got: {result}")
        return result


class CompanyFinancialSnapshot(BaseModel):
    """Normalized company data consumed by every valuation engine.

    Quote, shares, cash and debt are required because every supported model
    needs them. Other financial metrics may be missing and are represented by
    ``None``; a missing metric is never silently filled with a made-up value.
    ``net_debt`` is the stable public key. ``net_debt_metric`` remains as a
    compatibility alias for the original MVP schema.
    """

    ticker: str
    company_name: str
    currency: str = "USD"
    financial_currency: Optional[str] = None
    current_price: FinancialMetric
    price_timestamp: datetime
    diluted_shares: FinancialMetric
    cash: Optional[FinancialMetric] = None
    total_debt: Optional[FinancialMetric] = None
    net_debt: Optional[FinancialMetric] = Field(
        default=None,
        description="Provenance-rich total_debt - cash metric.",
    )
    net_debt_metric: Optional[FinancialMetric] = Field(
        default=None,
        description="Deprecated alias for net_debt.",
    )
    shares_basis: Optional[str] = "point_in_time_all_classes"
    shares_reconciliation: Optional[dict[str, Any] | str] = None
    statement_basis: Optional[str] = "TTM"
    annual_fallback: bool = False
    forecast_fiscal_year_end: Optional[date] = None
    ntm_weights: Optional[dict[str, Decimal]] = None

    # FY1 DCF stub bridge.  These fields are additive and optional so legacy
    # fixture/direct snapshots remain wire-compatible.  A live provider may
    # carry the same payload through a structured marker in ``cfo_ttm.notes``
    # because the seven-method normalizer intentionally preserves only the
    # canonical metrics above.
    fiscal_ytd_fcff: Optional[FinancialMetric] = Field(
        None,
        description="Actual FCFF from the current fiscal-year start through the valuation date",
    )
    fiscal_ytd_fcff_actual: Optional[FinancialMetric] = Field(
        None,
        description="Compatibility alias for fiscal_ytd_fcff",
    )
    ytd_fcff_actual: Optional[FinancialMetric] = Field(
        None,
        description="Compatibility alias for fiscal_ytd_fcff",
    )
    fiscal_ytd_start: Optional[date] = None
    fiscal_ytd_end: Optional[date] = None
    fiscal_ytd_prior_fiscal_year_end: Optional[date] = None
    fiscal_ytd_fiscal_year_end: Optional[date] = None
    fiscal_ytd_status: Optional[str] = None
    fiscal_ytd_required: Optional[bool] = None
    fiscal_ytd_unavailable_reason: Optional[str] = None

    revenue_ttm: Optional[FinancialMetric] = None
    ebitda_ttm: Optional[FinancialMetric] = None
    eps_ttm: Optional[FinancialMetric] = None

    # FCFE (equity FCF) — FCF-yield model only.
    fcf_ttm: Optional[FinancialMetric] = Field(None, description="FCFE TTM; FCF yield only")
    forward_fcf_1y: Optional[FinancialMetric] = Field(None, description="Forward FCFE Y1; FCF yield only")
    forward_fcf_2y: Optional[FinancialMetric] = Field(None, description="Forward FCFE Y2; FCF yield only")

    # FCFF (firm/unlevered FCF) — DCF at WACC only.
    fcff_ttm: Optional[FinancialMetric] = Field(None, description="FCFF TTM; DCF only")
    forward_fcff_1y: Optional[FinancialMetric] = Field(None, description="Forward FCFF Y1; DCF only")
    forward_fcff_2y: Optional[FinancialMetric] = Field(None, description="Forward FCFF Y2; DCF only")

    # Financial driver base items for auditable bridge derivation.
    cfo_ttm: Optional[FinancialMetric] = None
    capex_ttm: Optional[FinancialMetric] = None
    net_borrowing_ttm: Optional[FinancialMetric] = None
    # Explicit provider forward net borrowing; never inferred from the
    # historical ``net_borrowing_ttm`` driver above.
    forward_net_borrowing_1y: Optional[FinancialMetric] = None
    forward_net_borrowing_2y: Optional[FinancialMetric] = None
    da_ttm: Optional[FinancialMetric] = None
    nwc_change_ttm: Optional[FinancialMetric] = None
    interest_ttm: Optional[FinancialMetric] = None

    forward_eps_1y: Optional[FinancialMetric] = None
    forward_eps_2y: Optional[FinancialMetric] = None
    forward_ebitda_1y: Optional[FinancialMetric] = None
    forward_ebitda_2y: Optional[FinancialMetric] = None
    revenue_estimate_1y: Optional[FinancialMetric] = None
    revenue_estimate_2y: Optional[FinancialMetric] = None
    forward_revenue: Optional[FinancialMetric] = None


    historical_forward_pe: Optional[FinancialMetric] = None
    historical_ev_ebitda: Optional[FinancialMetric] = None
    # Raw company-history and public-industry candidates retained for the
    # service-level multiple arbiter.  They are never used as values until
    # provenance, date, sample and accounting-basis checks pass.
    multiple_candidates: dict[str, Any] = Field(default_factory=dict)

    # fcf_growth is FCFE growth; fcff_growth is FCFF growth.
    revenue_growth: Optional[FinancialMetric] = None
    ebitda_growth: Optional[FinancialMetric] = None
    eps_growth: Optional[FinancialMetric] = None
    fcf_growth: Optional[FinancialMetric] = None
    fcff_growth: Optional[FinancialMetric] = None

    # Optional CAPM/WACC inputs. Providers may omit these and use the
    # documented configured fallback instead.
    risk_free_rate: Optional[FinancialMetric] = None
    beta: Optional[FinancialMetric] = None
    equity_risk_premium: Optional[FinancialMetric] = None
    pre_tax_cost_of_debt: Optional[FinancialMetric] = None
    tax_rate: Optional[FinancialMetric] = None

    # Profile fields used by the support guard.
    country: Optional[str] = None
    exchange: Optional[str] = None
    market: Optional[str] = None
    security_type: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    is_profitable: Optional[bool] = None

    data_quality: DataQuality = DataQuality.HIGH
    is_demo: bool = False
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _synchronize_net_debt(self) -> "CompanyFinancialSnapshot":
        metric = self.net_debt or self.net_debt_metric
        if self.total_debt is not None and self.cash is not None:
            expected = self.total_debt.value - self.cash.value
            if metric is not None and metric.value != expected:
                raise ValueError(
                    "net_debt must equal total_debt - cash "
                    f"({expected}), got {metric.value}"
                )
            if metric is not None:
                self.net_debt = metric
                self.net_debt_metric = metric
        else:
            self.net_debt = None
            self.net_debt_metric = None

        # ``FinancialDataService`` owns the public seven-method normalization
        # boundary and cannot pass vendor-specific additive fields directly.
        # Providers therefore append a JSON object to the canonical CFO metric
        # notes.  Decode it here so the DCF engine receives typed provenance,
        # never a bare number or a missing-to-zero substitute.
        explicit_metrics = [
            metric
            for metric in (
                self.fiscal_ytd_fcff,
                self.fiscal_ytd_fcff_actual,
                self.ytd_fcff_actual,
            )
            if metric is not None
        ]
        ytd_metric = explicit_metrics[0] if explicit_metrics else None
        marker_payload: Optional[dict[str, Any]] = None
        if ytd_metric is None:
            marker_prefix = "S5_FISCAL_YTD_V1:"
            note_candidates = [
                self.cfo_ttm.notes if self.cfo_ttm is not None else None,
                self.fcff_ttm.notes if self.fcff_ttm is not None else None,
                self.fcf_ttm.notes if self.fcf_ttm is not None else None,
            ]
            for note in note_candidates:
                if not note or marker_prefix not in note:
                    continue
                encoded = note.split(marker_prefix, 1)[1].lstrip()
                try:
                    decoded, _ = json.JSONDecoder().raw_decode(encoded)
                except (TypeError, ValueError, json.JSONDecodeError):
                    marker_payload = {
                        "status": "unavailable",
                        "reason": "Malformed provider fiscal YTD provenance marker",
                    }
                else:
                    if isinstance(decoded, dict):
                        marker_payload = decoded
                    else:
                        marker_payload = {
                            "status": "unavailable",
                            "reason": "Provider fiscal YTD provenance marker is not an object",
                        }
                break

        if marker_payload is not None:
            status = str(marker_payload.get("status") or "unavailable").strip().lower()
            self.fiscal_ytd_status = status
            self.fiscal_ytd_required = True
            for field_name, payload_name in (
                ("fiscal_ytd_start", "start"),
                ("fiscal_ytd_end", "end"),
                ("fiscal_ytd_prior_fiscal_year_end", "prior_fiscal_year_end"),
                ("fiscal_ytd_fiscal_year_end", "fiscal_year_end"),
            ):
                raw_date = marker_payload.get(payload_name)
                if raw_date is None or getattr(self, field_name) is not None:
                    continue
                try:
                    setattr(self, field_name, date.fromisoformat(str(raw_date)[:10]))
                except (TypeError, ValueError):
                    self.fiscal_ytd_status = "unavailable"
                    status = "unavailable"
                    self.fiscal_ytd_unavailable_reason = (
                        f"Invalid provider fiscal YTD {payload_name} date: {raw_date!r}"
                    )
            if status == "available":
                missing_coverage = [
                    payload_name
                    for field_name, payload_name in (
                        ("fiscal_ytd_start", "start"),
                        ("fiscal_ytd_end", "end"),
                        ("fiscal_ytd_fiscal_year_end", "fiscal_year_end"),
                    )
                    if getattr(self, field_name, None) is None
                ]
                if missing_coverage:
                    status = "unavailable"
                    self.fiscal_ytd_status = status
                    self.fiscal_ytd_unavailable_reason = (
                        "Provider fiscal YTD marker is missing explicit coverage fields: "
                        + ", ".join(missing_coverage)
                    )
            if status == "available" and ytd_metric is None:
                try:
                    required_provenance = (
                        "value",
                        "unit",
                        "period",
                        "source",
                        "source_type",
                        "as_of",
                        "confidence",
                        "is_estimated",
                    )
                    missing_provenance = [
                        key
                        for key in required_provenance
                        if key not in marker_payload
                        or marker_payload[key] is None
                        or (isinstance(marker_payload[key], str) and not marker_payload[key].strip())
                    ]
                    if missing_provenance:
                        raise ValueError(
                            "missing explicit provenance fields: " + ", ".join(missing_provenance)
                        )
                    if not isinstance(marker_payload["is_estimated"], bool):
                        raise ValueError("is_estimated must be an explicit boolean")
                    raw_source_type = str(marker_payload["source_type"]).strip().lower()
                    source_type = {
                        "actual": SourceType.ACTUAL,
                        "provider_actual": SourceType.ACTUAL,
                        "derived": SourceType.DERIVED,
                        "fixture": SourceType.FIXTURE,
                    }.get(raw_source_type)
                    if source_type is None:
                        raise ValueError(f"unsupported source_type={raw_source_type}")
                    ytd_metric = FinancialMetric(
                        value=marker_payload.get("value"),
                        unit=str(marker_payload["unit"]),
                        period=str(marker_payload["period"]),
                        source=str(marker_payload["source"]),
                        source_type=source_type,
                        as_of=marker_payload["as_of"],
                        confidence=marker_payload["confidence"],
                        is_estimated=marker_payload["is_estimated"],
                        notes=marker_payload.get("notes"),
                    )
                except Exception as exc:
                    ytd_metric = None
                    self.fiscal_ytd_status = "unavailable"
                    self.fiscal_ytd_unavailable_reason = f"Invalid provider fiscal YTD FCFF metric: {exc}"
            if self.fiscal_ytd_status != "available" or ytd_metric is None:
                self.fiscal_ytd_unavailable_reason = (
                    self.fiscal_ytd_unavailable_reason
                    or str(marker_payload.get("reason") or "Provider fiscal YTD FCFF is unavailable")
                )

        if ytd_metric is not None:
            self.fiscal_ytd_fcff = ytd_metric
            self.fiscal_ytd_fcff_actual = ytd_metric
            self.ytd_fcff_actual = ytd_metric
            if self.fiscal_ytd_status is None:
                self.fiscal_ytd_status = "available"
        return self

    def get_net_debt(self) -> Optional[Decimal]:
        """Return the metric value, falling back to the balance-sheet identity."""

        if self.net_debt is not None:
            return self.net_debt.value
        if self.total_debt is not None and self.cash is not None:
            return self.total_debt.value - self.cash.value
        return None


class ScenarioValues(BaseModel):
    low: Decimal
    base: Decimal
    high: Decimal

    model_config = {"frozen": True}

    @field_validator("low", "base", "high", mode="before")
    @classmethod
    def _finite(cls, value: object) -> Decimal:
        try:
            result = value if isinstance(value, Decimal) else Decimal(str(value))
        except Exception as exc:
            raise ValueError("scenario values must be numeric") from exc
        if not result.is_finite():
            raise ValueError("scenario values must be finite")
        return result


def _default_scenarios(name: str) -> ScenarioValues:
    """Load defaults lazily so config.py remains the operative source."""

    from app import config

    return getattr(config, name)


def _default_decimal(name: str) -> Decimal:
    from app import config

    return getattr(config, name)


class ValuationAssumptions(BaseModel):
    """Internal valuation assumptions; defaults are supplied by ``app.config``.

    The legacy composite-weight fields remain here solely so callers importing
    the retired ``app.engines.composite`` helper do not break.  They are not
    part of the public valuation response; see ``ValuationAssumptionsResponse``.
    """

    pe_target: ScenarioValues = Field(default_factory=lambda: _default_scenarios("DEFAULT_PE_TARGET"))
    pe_source: SourceType = SourceType.CONFIGURED_FALLBACK
    pe_source_label: str = "Configured fallback"
    pe_selection_layer: str = "system"
    pe_selection_as_of: Optional[date] = None
    pe_selection_sample_size: Optional[int] = None
    pe_selection_basis: Optional[str] = None

    ev_ebitda_multiple: ScenarioValues = Field(
        default_factory=lambda: _default_scenarios("DEFAULT_EV_EBITDA_MULTIPLE")
    )
    ev_ebitda_source: SourceType = SourceType.CONFIGURED_FALLBACK
    ev_ebitda_source_label: str = "Configured fallback"
    ev_ebitda_selection_layer: str = "system"
    ev_ebitda_selection_as_of: Optional[date] = None
    ev_ebitda_selection_sample_size: Optional[int] = None
    ev_ebitda_selection_basis: Optional[str] = None

    # low valuation uses the highest yield; high valuation uses the lowest.
    fcf_yield: ScenarioValues = Field(default_factory=lambda: _default_scenarios("DEFAULT_FCF_YIELD"))
    fcf_yield_source: SourceType = SourceType.CONFIGURED_FALLBACK
    fcf_yield_source_label: str = "Configured fallback"

    # low valuation uses the highest WACC; high valuation uses the lowest.
    dcf_wacc: ScenarioValues = Field(default_factory=lambda: _default_scenarios("DEFAULT_DCF_WACC"))
    dcf_terminal_growth: ScenarioValues = Field(
        default_factory=lambda: _default_scenarios("DEFAULT_DCF_TERMINAL_GROWTH")
    )
    dcf_fcf_growth: Optional[ScenarioValues] = None
    dcf_wacc_source: SourceType = SourceType.CONFIGURED_FALLBACK
    dcf_wacc_source_label: str = "Configured fallback"
    dcf_terminal_growth_source: SourceType = SourceType.CONFIGURED_FALLBACK
    dcf_terminal_growth_source_label: str = "Configured fallback"

    weight_pe: Decimal = Field(default_factory=lambda: _default_decimal("DEFAULT_WEIGHT_PE"))
    weight_ev_ebitda: Decimal = Field(default_factory=lambda: _default_decimal("DEFAULT_WEIGHT_EV_EBITDA"))
    weight_fcf_yield: Decimal = Field(default_factory=lambda: _default_decimal("DEFAULT_WEIGHT_FCF_YIELD"))
    weight_dcf: Decimal = Field(default_factory=lambda: _default_decimal("DEFAULT_WEIGHT_DCF"))
    cashflow_group_max_weight: Decimal = Field(
        default_factory=lambda: _default_decimal("DEFAULT_CASHFLOW_GROUP_MAX_WEIGHT")
    )
    growth_floor: Decimal = Field(default_factory=lambda: _default_decimal("DEFAULT_GROWTH_FLOOR"))
    growth_cap: Decimal = Field(default_factory=lambda: _default_decimal("DEFAULT_GROWTH_CAP"))
    forecast_horizon: str = Field(default="ntm")

    # Financial driver overrides for forward cash flow bridge
    driver_ebitda_margin: Optional[Decimal] = None
    driver_capex: Optional[Decimal] = None
    driver_capex_ratio: Optional[Decimal] = None
    driver_nwc_change: Optional[Decimal] = None
    driver_nwc_ratio: Optional[Decimal] = None
    driver_net_borrowing: Optional[Decimal] = None
    driver_da: Optional[Decimal] = None
    driver_da_ratio: Optional[Decimal] = None
    driver_tax_rate: Optional[Decimal] = None


class ValuationAssumptionsResponse(BaseModel):
    """Public assumptions contract for the four independent models.

    Composite weighting was removed from the product contract.  Keep the
    internal ``ValuationAssumptions`` model available to calculation helpers,
    while exposing only assumptions that affect an individual model here.
    """

    pe_target: ScenarioValues = Field(default_factory=lambda: _default_scenarios("DEFAULT_PE_TARGET"))
    pe_source: SourceType = SourceType.CONFIGURED_FALLBACK
    pe_source_label: str = "Configured fallback"
    pe_selection_layer: str = "system"
    pe_selection_as_of: Optional[date] = None
    pe_selection_sample_size: Optional[int] = None
    pe_selection_basis: Optional[str] = None

    ev_ebitda_multiple: ScenarioValues = Field(
        default_factory=lambda: _default_scenarios("DEFAULT_EV_EBITDA_MULTIPLE")
    )
    ev_ebitda_source: SourceType = SourceType.CONFIGURED_FALLBACK
    ev_ebitda_source_label: str = "Configured fallback"
    ev_ebitda_selection_layer: str = "system"
    ev_ebitda_selection_as_of: Optional[date] = None
    ev_ebitda_selection_sample_size: Optional[int] = None
    ev_ebitda_selection_basis: Optional[str] = None

    fcf_yield: ScenarioValues = Field(default_factory=lambda: _default_scenarios("DEFAULT_FCF_YIELD"))
    fcf_yield_source: SourceType = SourceType.CONFIGURED_FALLBACK
    fcf_yield_source_label: str = "Configured fallback"

    dcf_wacc: ScenarioValues = Field(default_factory=lambda: _default_scenarios("DEFAULT_DCF_WACC"))
    dcf_terminal_growth: ScenarioValues = Field(
        default_factory=lambda: _default_scenarios("DEFAULT_DCF_TERMINAL_GROWTH")
    )
    dcf_fcf_growth: Optional[ScenarioValues] = None
    dcf_wacc_source: SourceType = SourceType.CONFIGURED_FALLBACK
    dcf_wacc_source_label: str = "Configured fallback"
    dcf_terminal_growth_source: SourceType = SourceType.CONFIGURED_FALLBACK
    dcf_terminal_growth_source_label: str = "Configured fallback"

    growth_floor: Decimal = Field(default_factory=lambda: _default_decimal("DEFAULT_GROWTH_FLOOR"))
    growth_cap: Decimal = Field(default_factory=lambda: _default_decimal("DEFAULT_GROWTH_CAP"))
    forecast_horizon: str = Field(default="ntm")

    driver_ebitda_margin: Optional[Decimal] = None
    driver_capex: Optional[Decimal] = None
    driver_capex_ratio: Optional[Decimal] = None
    driver_nwc_change: Optional[Decimal] = None
    driver_nwc_ratio: Optional[Decimal] = None
    driver_net_borrowing: Optional[Decimal] = None
    driver_da: Optional[Decimal] = None
    driver_da_ratio: Optional[Decimal] = None
    driver_tax_rate: Optional[Decimal] = None

    model_config = {"frozen": True, "extra": "ignore"}


class PriceEstimate(BaseModel):
    price_per_share: Decimal
    upside_pct: Decimal
    premium_discount_pct: Decimal
    intermediates: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True}


class DCFScenario(BaseModel):
    """One complete DCF path, including projection provenance and PV math."""

    scenario: Literal["bear", "base", "bull"]
    wacc: Decimal
    terminal_growth: Decimal
    growth_rate: Decimal = Decimal("0")
    growth_start: Optional[Decimal] = None
    growth_fade_formula: Optional[str] = None
    projection_growth_rates: list[Optional[Decimal]] = Field(default_factory=list)
    growth_metric: Optional[dict[str, Any]] = None
    growth_metric_raw: Optional[dict[str, Any]] = None
    growth_cap: Optional[Decimal] = None
    growth_floor: Optional[Decimal] = None
    fcff_year1: Decimal
    fcff_projections: list[Decimal]
    # Year 6 is the first terminal-period cash flow used by the perpetuity
    # formula: FCFF_6 = FCFF_5 × (1 + terminal_growth).
    fcff_year6: Optional[Decimal] = None
    projection_periods: list[str] = Field(default_factory=list)
    projection_metrics: list[dict[str, Any]] = Field(default_factory=list)
    pv_years: list[int] = Field(default_factory=list)
    year_fractions: list[Decimal] = Field(default_factory=list)
    period_start_dates: list[str] = Field(default_factory=list)
    period_end_dates: list[str] = Field(default_factory=list)
    # Fiscal-year timeline audit fields. ``year_fractions`` remains the
    # backwards-compatible name for discount time (t).
    projection_proration_factors: list[Decimal] = Field(default_factory=list)
    period_is_stub: list[bool] = Field(default_factory=list)
    fiscal_year_days: list[int] = Field(default_factory=list)
    projection_stub_basis: list[str] = Field(default_factory=list)
    fiscal_ytd_actual: Optional[dict[str, Any]] = None
    discount_times: list[Decimal] = Field(default_factory=list)
    projection_discount_times: list[Decimal] = Field(default_factory=list)
    discount_factors: list[Decimal] = Field(default_factory=list)
    projection_discount_factors: list[Decimal] = Field(default_factory=list)
    terminal_period_end_date: Optional[str] = None
    terminal_discount_time: Optional[Decimal] = None
    terminal_discount_factor: Optional[Decimal] = None
    growth_compound_horizon: Optional[str] = None
    pv_projections: list[Decimal]
    terminal_value: Decimal
    pv_terminal_value: Decimal
    enterprise_value: Decimal
    total_debt: Decimal
    cash: Decimal
    net_debt: Decimal
    equity_value: Decimal
    diluted_shares: Decimal
    price_per_share: Decimal
    upside_pct: Decimal
    premium_discount_pct: Decimal
    formulas: dict[str, str] = Field(default_factory=dict)
    calculation_steps: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    model_config = {"frozen": True}


class DCFSensitivityCell(BaseModel):
    wacc: Decimal
    terminal_growth: Decimal
    price_per_share: Optional[Decimal] = None
    enterprise_value: Optional[Decimal] = None
    equity_value: Optional[Decimal] = None
    tv_ratio: Optional[Decimal] = None
    # Expose the exact trajectory used by this cell so sensitivity output can
    # be independently reconciled with the base DCF fade policy.
    fcff_projections: list[Decimal] = Field(default_factory=list)
    fcff_year6: Optional[Decimal] = None
    projection_growth_rates: list[Optional[Decimal]] = Field(default_factory=list)
    year_fractions: list[Decimal] = Field(default_factory=list)
    discount_times: list[Decimal] = Field(default_factory=list)
    discount_factors: list[Decimal] = Field(default_factory=list)
    period_start_dates: list[str] = Field(default_factory=list)
    period_end_dates: list[str] = Field(default_factory=list)
    pv_projections: list[Decimal] = Field(default_factory=list)
    available: bool = True
    unavailable_reason: Optional[str] = None

    model_config = {"frozen": True}


class DCFSensitivityMatrix(BaseModel):
    wacc_range: list[Decimal]
    terminal_growth_range: list[Decimal]
    cells: list[list[DCFSensitivityCell]]
    base_tv_ratio: Decimal
    tv_dependence_warning: Optional[str] = None

    model_config = {"frozen": True}


class ModelValuation(BaseModel):
    """Stable per-model response contract.

    ``inputs`` and ``assumptions`` keep the original flat aliases. New
    consumers should use ``input_metrics`` and ``assumption_metrics`` where
    every value is a provenance-rich FinancialMetric dictionary.
    """

    formula: str
    formula_description: str
    inputs: dict[str, Any]
    assumptions: dict[str, Any]
    input_metrics: dict[str, dict[str, Any]] = Field(default_factory=dict)
    assumption_metrics: dict[str, dict[str, Any]] = Field(default_factory=dict)
    calculation_steps: list[str]
    low: Optional[PriceEstimate] = None
    base: Optional[PriceEstimate] = None
    high: Optional[PriceEstimate] = None
    dcf_scenarios: Optional[list[DCFScenario]] = None
    sensitivity_matrix: Optional[DCFSensitivityMatrix] = None
    available: bool = True
    unavailable_reason: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    data_quality: DataQuality = DataQuality.HIGH

    model_config = {"frozen": True}


class CompositeValuation(BaseModel):
    """Legacy composite result kept for import compatibility only.

    The public ``ValuationResponse`` no longer includes this model and the
    service does not calculate it.
    """

    current_price: Optional[Decimal] = None
    low: Optional[Decimal] = None
    base: Optional[Decimal] = None
    high: Optional[Decimal] = None
    # Explicit stable aliases (properties were not serialized by Pydantic).
    fair_value_low: Optional[Decimal] = None
    fair_value_base: Optional[Decimal] = None
    fair_value_high: Optional[Decimal] = None
    weights_used: dict[str, Decimal] = Field(default_factory=dict)
    selected_weights: dict[str, Decimal] = Field(default_factory=dict)
    effective_weights: dict[str, Decimal] = Field(default_factory=dict)
    cashflow_group_weight: Optional[Decimal] = None
    cashflow_group_max_weight: Optional[Decimal] = None
    cashflow_sensitivity: Optional[dict[str, Any]] = None
    cashflow_group_policy_message: Optional[str] = None
    available_models: list[str] = Field(default_factory=list)
    classification: Optional[ValuationClassification] = None
    margin_of_safety: Optional[Decimal] = None
    upside_downside: Optional[Decimal] = None
    premium_discount_pct: Optional[Decimal] = None
    formula: str = "Weighted average of complete model scenario fair values"
    calculation_steps: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    data_quality: DataQuality = DataQuality.HIGH
    available: bool = True
    unavailable_reason: Optional[str] = None

    model_config = {"frozen": True}


class ValuationResponse(BaseModel):
    ticker: str
    company_name: str
    current_price: Decimal
    currency: str
    as_of: datetime
    price_timestamp: datetime
    valuations: dict[str, ModelValuation]
    is_demo: bool = False
    data_quality: DataQuality
    warnings: list[str] = Field(default_factory=list)
    assumptions_used: ValuationAssumptionsResponse
    provider: Optional[str] = None
    provider_label: Optional[str] = None
    shares_basis: Optional[str] = None
    shares_reconciliation: Optional[dict[str, Any] | str] = None
    statement_basis: Optional[str] = None
    annual_fallback: bool = False
    forecast_fiscal_year_end: Optional[date] = None
    ntm_weights: Optional[dict[str, Decimal]] = None
    forecast_horizon_effective: Optional[str] = None
    growth_cap_effective: Optional[Decimal] = None
    growth_floor_effective: Optional[Decimal] = None
    financial_bridge: Optional[dict[str, Any]] = None

    model_config = {"frozen": True}



# Kept for import compatibility. The operative thresholds live in config.py;
# classify_valuation imports them lazily to avoid the config/domain cycle.
CLASSIFICATION_BOUNDARIES_CONFIG = {
    "significantly_undervalued": Decimal("0.80"),
    "undervalued": Decimal("0.90"),
    "slightly_undervalued_max": Decimal("1.00"),
    "fairly_valued": Decimal("1.10"),
    "overvalued": Decimal("1.25"),
}


def classify_valuation(current_price: Decimal, fair_value: Decimal) -> ValuationClassification:
    """Classify price/fair-value using the centralized config boundaries."""

    if not current_price.is_finite() or not fair_value.is_finite():
        raise ValueError("current_price and fair_value must be finite")
    if current_price <= 0:
        raise ValueError("current_price must be positive")
    if fair_value <= 0:
        raise ValueError("fair_value must be positive")

    # Local import prevents app.config -> app.models.domain circular import.
    from app.config import (
        CLASSIFICATION_FAIRLY_VALUED_MAX,
        CLASSIFICATION_OVERVALUED_MAX,
        CLASSIFICATION_SIGNIFICANTLY_UNDERVALUED_MAX,
        CLASSIFICATION_SLIGHTLY_UNDERVALUED_STRICT_MAX,
        CLASSIFICATION_UNDERVALUED_MAX,
    )

    ratio = current_price / fair_value
    if ratio <= CLASSIFICATION_SIGNIFICANTLY_UNDERVALUED_MAX:
        return ValuationClassification.SIGNIFICANTLY_UNDERVALUED
    if ratio <= CLASSIFICATION_UNDERVALUED_MAX:
        return ValuationClassification.UNDERVALUED
    if ratio < CLASSIFICATION_SLIGHTLY_UNDERVALUED_STRICT_MAX:
        return ValuationClassification.SLIGHTLY_UNDERVALUED
    if ratio <= CLASSIFICATION_FAIRLY_VALUED_MAX:
        return ValuationClassification.FAIRLY_VALUED
    if ratio <= CLASSIFICATION_OVERVALUED_MAX:
        return ValuationClassification.OVERVALUED
    return ValuationClassification.SIGNIFICANTLY_OVERVALUED


CLASSIFICATION_LABELS_ZH = {
    ValuationClassification.SIGNIFICANTLY_UNDERVALUED: "严重低估",
    ValuationClassification.UNDERVALUED: "低估",
    ValuationClassification.SLIGHTLY_UNDERVALUED: "略微低估",
    ValuationClassification.FAIRLY_VALUED: "合理估值",
    ValuationClassification.OVERVALUED: "高估",
    ValuationClassification.SIGNIFICANTLY_OVERVALUED: "严重高估",
}


def metric_dict(metric: Optional[FinancialMetric]) -> Optional[dict[str, Any]]:
    """Return a JSON-ready provenance dictionary for a metric."""

    if metric is None:
        return None
    return metric.model_dump(mode="json")


def net_debt_metric(snapshot: CompanyFinancialSnapshot) -> Optional[FinancialMetric]:
    """Build the stable derived net-debt metric for unnormalized snapshots."""

    if snapshot.cash is None or snapshot.total_debt is None:
        return None
    expected = snapshot.total_debt.value - snapshot.cash.value
    if snapshot.net_debt is not None:
        if snapshot.net_debt.value != expected:
            raise ValueError(
                "net_debt must equal total_debt - cash "
                f"({expected}), got {snapshot.net_debt.value}"
            )
        return snapshot.net_debt
    return FinancialMetric(
        value=expected,
        unit=snapshot.total_debt.unit,
        period=snapshot.total_debt.period,
        source="Derived from total_debt - cash",
        source_type=SourceType.DERIVED,
        as_of=max(snapshot.total_debt.as_of, snapshot.cash.as_of),
        confidence=min(snapshot.total_debt.confidence, snapshot.cash.confidence),
        is_estimated=snapshot.total_debt.is_estimated or snapshot.cash.is_estimated,
        notes="Derived net debt; normalize_snapshot publishes it on the snapshot.",
    )
