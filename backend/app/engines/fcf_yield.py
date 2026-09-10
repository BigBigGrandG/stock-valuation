"""FCF-yield engine using FCFE (equity cash flow) only."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from app.models.domain import (
    CompanyFinancialSnapshot,
    DataQuality,
    FinancialMetric,
    ModelValuation,
    PriceEstimate,
    SourceType,
    ValuationAssumptions,
    metric_dict,
    net_debt_metric,
)

TWO_PLACES = Decimal("0.01")
FOUR_PLACES = Decimal("0.0001")
ZERO = Decimal("0")
FORMULA = "Equity Value = Forward FCFE / Yield Rate; Price = Equity / Shares"


def _upside(price: Decimal, current: Decimal) -> Decimal:
    return ((price - current) / current).quantize(FOUR_PLACES, ROUND_HALF_UP)


def _premium(current: Decimal, fair_value: Decimal) -> Decimal:
    return ((current - fair_value) / fair_value).quantize(FOUR_PLACES, ROUND_HALF_UP)


def _assumption_metric(value: Decimal, label: str, source: str, source_type: SourceType, as_of: date) -> dict:
    return metric_dict(FinancialMetric(
        value=value,
        unit="yield",
        period="valuation assumption",
        source=source,
        source_type=source_type,
        as_of=as_of,
        confidence=1.0 if source_type == SourceType.USER_OVERRIDE else 0.8,
        is_estimated=source_type != SourceType.USER_OVERRIDE,
        notes=f"{label}; low scenario is the high-yield conservative case",
    )) or {}


def _unavailable(reason: str, inputs: dict | None = None, warnings: list[str] | None = None) -> ModelValuation:
    return ModelValuation(
        formula=FORMULA,
        formula_description="FCF-yield-based equity valuation using FCFE (not FCFF)",
        inputs=inputs or {},
        assumptions={},
        calculation_steps=[],
        available=False,
        unavailable_reason=reason,
        warnings=warnings or [],
        data_quality=DataQuality.LOW,
    )


def run_fcf_yield(snapshot: CompanyFinancialSnapshot, assumptions: ValuationAssumptions) -> ModelValuation:
    warnings: list[str] = []
    current_price = snapshot.current_price.value
    shares = snapshot.diluted_shares.value
    if current_price <= ZERO:
        return _unavailable(f"Current quote must be positive, got {current_price}")
    if shares <= ZERO:
        return _unavailable(f"Diluted shares must be positive, got {shares}")
    if getattr(snapshot, "shares_basis", None) == "CONFLICT_DEGRADED":
        return _unavailable(
            "Share capital reconciliation conflict: severe divergence across share classes/sources; model fails closed to prevent erroneous price targets.",
            warnings=["Diluted share count is in CONFLICT_DEGRADED state; per-share valuation model is unavailable."],
        )
    if snapshot.financial_currency and snapshot.financial_currency.upper() != snapshot.currency.upper():
        return _unavailable(
            f"Currency mismatch: quote currency ({snapshot.currency}) differs from statement reporting currency ({snapshot.financial_currency}) without FX conversion"
        )

    sec = f"{snapshot.sector or ''} {snapshot.industry or ''}".lower()
    if any(term in sec for term in ["financial services", "financials", "bank", "insurance"]):
        return _unavailable(
            "FCF yield is not applicable to banks and financial institutions (operating cash flow includes customer deposits and loan activities)"
        )
    if any(term in sec for term in ["reit", "real estate investment trust"]):
        return _unavailable(
            "FCF yield is not applicable to REITs (requires FFO/AFFO instead of standard cash flow)"
        )

    fcfe_metric = snapshot.forward_fcf_1y or snapshot.forward_fcf_2y
    if fcfe_metric is None and snapshot.fcf_ttm is not None:
        fcfe_metric = snapshot.fcf_ttm
        warnings.append("Using TTM FCFE as a forward proxy because no forward FCFE estimate is available")
    if fcfe_metric is None:
        return _unavailable("No forward FCFE (equity FCF) estimate available", warnings=warnings)
    fcfe = fcfe_metric.value
    if fcfe <= ZERO:
        return _unavailable(
            f"Forward FCFE is non-positive ({fcfe}); model requires positive FCFE",
            inputs={"forward_fcfe": str(fcfe)},
            warnings=warnings,
        )

    yields = assumptions.fcf_yield
    if not (yields.low >= yields.base >= yields.high > ZERO):
        return _unavailable("Effective FCF yields must satisfy low >= base >= high > 0", warnings=warnings)
    source_type = assumptions.fcf_yield_source
    source_label = assumptions.fcf_yield_source_label
    nd_metric = net_debt_metric(snapshot)

    input_metrics = {
        key: value
        for key, value in {
            "current_price": metric_dict(snapshot.current_price),
            "diluted_shares": metric_dict(snapshot.diluted_shares),
            "cash": metric_dict(snapshot.cash),
            "total_debt": metric_dict(snapshot.total_debt),
            "net_debt": metric_dict(nd_metric),
            "forward_fcfe": metric_dict(fcfe_metric),
        }.items()
        if value is not None
    }
    assumption_metrics = {
        f"yield_{label}": _assumption_metric(
            value, label, source_label, source_type, fcfe_metric.as_of
        )
        for label, value in (("low", yields.low), ("base", yields.base), ("high", yields.high))
    }

    def calculate(rate: Decimal, label: str) -> tuple[PriceEstimate, list[str]]:
        equity = (fcfe / rate).quantize(TWO_PLACES, ROUND_HALF_UP)
        price = (equity / shares).quantize(TWO_PLACES, ROUND_HALF_UP)
        return PriceEstimate(
            price_per_share=price,
            upside_pct=_upside(price, current_price),
            premium_discount_pct=_premium(current_price, price),
            intermediates={
                "equity_value": str(equity),
                "yield_rate": str(rate),
                "forward_fcfe": str(fcfe),
            },
        ), [
            f"[{label}] Equity value = {fcfe} / {rate} = {equity}",
            f"[{label}] Price/share = {equity} / {shares} = {price}",
        ]

    low, low_steps = calculate(yields.low, "low (high yield = conservative)")
    base, base_steps = calculate(yields.base, "base")
    high, high_steps = calculate(yields.high, "high (low yield = optimistic)")
    steps = [
        "IMPORTANT: Uses FCFE (equity FCF), NOT FCFF (firm FCF used by DCF)",
        f"Forward FCFE = {fcfe} [{fcfe_metric.period}; {fcfe_metric.source}; as_of={fcfe_metric.as_of}; estimated={fcfe_metric.is_estimated}]",
        f"Yield rates (low/base/high) = {yields.low}/{yields.base}/{yields.high} [{source_label}]",
        "Low valuation uses the highest yield; high valuation uses the lowest yield.",
        *low_steps,
        *base_steps,
        *high_steps,
    ]
    quality = DataQuality.LOW if snapshot.is_demo else (
        DataQuality.MEDIUM if fcfe_metric.is_estimated else DataQuality.HIGH
    )
    return ModelValuation(
        formula=FORMULA,
        formula_description=(
            "FCFE (equity free cash flow) divided by the target yield rate, then divided by shares. "
            "FCFF is never substituted or discounted in this model."
        ),
        inputs={
            "forward_fcfe": str(fcfe),
            "forward_fcfe_period": fcfe_metric.period,
            "forward_fcfe_source": fcfe_metric.source,
            "forward_fcfe_source_type": fcfe_metric.source_type,
            "forward_fcfe_as_of": str(fcfe_metric.as_of),
            "forward_fcfe_is_estimated": fcfe_metric.is_estimated,
            "fcf_type": "FCFE (equity FCF, NOT FCFF)",
            "current_price": str(current_price),
            "diluted_shares": str(shares),
        },
        assumptions={
            "yield_low": str(yields.low),
            "yield_base": str(yields.base),
            "yield_high": str(yields.high),
            "source": source_type,
            "source_label": source_label,
            "yield_source": "user_override" if source_type == SourceType.USER_OVERRIDE else "fallback",
        },
        input_metrics=input_metrics,
        assumption_metrics=assumption_metrics,
        calculation_steps=steps,
        low=low,
        base=base,
        high=high,
        warnings=warnings,
        data_quality=quality,
    )

