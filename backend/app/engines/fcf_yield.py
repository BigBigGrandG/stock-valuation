"""FCF-yield engine using FCFE (equity cash flow) only."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

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
from app.engines.parameter_governance import govern_parameter

TWO_PLACES = Decimal("0.01")
FOUR_PLACES = Decimal("0.0001")
ZERO = Decimal("0")
FORMULA = "Equity Value = Forward FCFE / Yield Rate; Price = Equity / Shares"
FALLBACK_WARNING = (
    "Configured system FCFE-yield fallback is rejected because no compatible "
    "company/industry-specific benchmark is available; parameter specificity is insufficient."
)


def _upside(price: Decimal, current: Decimal) -> Decimal:
    return ((price - current) / current).quantize(FOUR_PLACES, ROUND_HALF_UP)


def _premium(current: Decimal, fair_value: Decimal) -> Decimal:
    return ((current - fair_value) / fair_value).quantize(FOUR_PLACES, ROUND_HALF_UP)


def _assumption_metric(
    value: Decimal,
    label: str,
    source: str,
    source_type: SourceType | str | None,
    as_of: date,
) -> dict:
    raw_source_type = getattr(source_type, "value", source_type)
    try:
        metric_source_type = SourceType(raw_source_type)
    except (TypeError, ValueError):
        # Unknown provenance must be returned as a diagnostic, not allowed to
        # escape as a FinancialMetric validation exception after governance has
        # already decided that the valuation is unavailable.
        return {
            "value": str(value),
            "unit": "yield",
            "period": "valuation assumption",
            "source": source,
            "source_type": raw_source_type,
            "as_of": as_of.isoformat(),
            "confidence": 0.0,
            "is_estimated": True,
            "notes": f"{label}; low scenario is the high-yield conservative case",
        }
    return metric_dict(FinancialMetric(
        value=value,
        unit="yield",
        period="valuation assumption",
        source=source,
        source_type=metric_source_type,
        as_of=as_of,
        confidence=1.0 if metric_source_type == SourceType.USER_OVERRIDE else 0.8,
        is_estimated=metric_source_type != SourceType.USER_OVERRIDE,
        notes=f"{label}; low scenario is the high-yield conservative case",
    )) or {}


def _unavailable(
    reason: str,
    inputs: dict | None = None,
    warnings: list[str] | None = None,
    input_metrics: dict[str, dict[str, Any]] | None = None,
    assumptions: dict | None = None,
    assumption_metrics: dict[str, dict[str, Any]] | None = None,
) -> ModelValuation:
    return ModelValuation(
        formula=FORMULA,
        formula_description="FCF-yield-based equity valuation using FCFE (not FCFF)",
        inputs=inputs or {},
        assumptions=assumptions or {},
        input_metrics=input_metrics or {},
        assumption_metrics=assumption_metrics or {},
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

    # Only a metric in an explicitly forward slot may drive FCF-yield.  A
    # historical value can be present in either slot when an upstream adapter
    # carries legacy aliases; skip it rather than allowing it to fall through
    # to another historical field or to generate a price.
    fcfe_metric = None
    for candidate in (snapshot.forward_fcf_1y, snapshot.forward_fcf_2y):
        if candidate is None:
            continue
        period = str(candidate.period or "").upper().strip()
        if not period or any(
            marker in period for marker in ("TTM", "LTM", "HISTORICAL", "TRAILING")
        ):
            warnings.append(
                f"Forward FCFE field is historical ({candidate.period}); it is excluded from forward valuation and retained for display only."
            )
            continue
        fcfe_metric = candidate
        break
    if fcfe_metric is None:
        historical_inputs: dict[str, dict[str, Any]] = {}
        historical_fcf = snapshot.fcf_ttm
        if historical_fcf is not None:
            warnings.append(
                f"Historical FCFE ({historical_fcf.period}) is retained for display only; "
                "a true forward FCFE estimate or explicit forward bridge is required for valuation."
            )
            historical_metric = metric_dict(historical_fcf)
            if historical_metric is not None:
                historical_inputs["historical_fcfe_ttm"] = historical_metric
        return _unavailable(
            "No forward FCFE (equity FCF) estimate available",
            inputs={
                "historical_fcfe_ttm": str(historical_fcf.value)
                if historical_fcf is not None else None,
                "historical_fcfe_ttm_period": historical_fcf.period
                if historical_fcf is not None else None,
            } if historical_fcf is not None else None,
            warnings=warnings,
            input_metrics=historical_inputs,
        )
    metric_notes = str(fcfe_metric.notes or "")
    if any(
        marker in metric_notes.lower()
        for marker in (
            "normalized forward borrowing",
            "historical net_borrowing_ttm",
            "historical ttm net borrowing",
            "no explicit forward net borrowing",
        )
    ):
        warnings.append(
            "Forward FCFE bridge uses no historical TTM net borrowing; missing forward borrowing was normalized to zero."
        )
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
    governance = govern_parameter(
        assumptions,
        model_label="FCF yield",
        value_field="fcf_yield",
        source_field="fcf_yield_source",
        label_field="fcf_yield_source_label",
        layer_field="fcf_yield_source",
        source_type=source_type,
        source_label=source_label,
        selection_layer="system",
        multiple_source="fallback",
        snapshot_is_demo=bool(snapshot.is_demo),
    )
    if not governance.available:
        fallback_assumptions = {
            "yield_low": str(yields.low),
            "yield_base": str(yields.base),
            "yield_high": str(yields.high),
            "source": source_type,
            "source_label": source_label,
            "yield_source": "fallback",
            "governance": "configured_fallback_rejected",
        }
        fallback_assumption_metrics = {
            f"yield_{label}": _assumption_metric(
                value,
                label,
                source_label,
                source_type,
                fcfe_metric.as_of,
            )
            for label, value in (
                ("low", yields.low),
                ("base", yields.base),
                ("high", yields.high),
            )
        }
        forward_inputs = {
            "forward_fcfe": str(fcfe),
            "forward_fcfe_period": fcfe_metric.period,
            "forward_fcfe_source": fcfe_metric.source,
            "forward_fcfe_source_type": fcfe_metric.source_type,
            "forward_fcfe_as_of": str(fcfe_metric.as_of),
            "forward_fcfe_is_estimated": fcfe_metric.is_estimated,
            "fcf_type": "FCFE (equity FCF, NOT FCFF)",
            "current_price": str(current_price),
            "diluted_shares": str(shares),
        }
        return _unavailable(
            governance.reason or "FCF yield parameter governance rejected the selected parameter",
            inputs=forward_inputs,
            assumptions=fallback_assumptions,
            warnings=[*warnings, governance.warning or FALLBACK_WARNING],
            input_metrics={
                "current_price": metric_dict(snapshot.current_price) or {},
                "diluted_shares": metric_dict(snapshot.diluted_shares) or {},
                "forward_fcfe": metric_dict(fcfe_metric) or {},
            },
            assumption_metrics=fallback_assumption_metrics,
        )

    source_type = governance.source_type
    source_label = governance.source_label
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
            "forward_fcfe_quality_note": "Forward FCFE estimate or explicit forward bridge input.",
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
            "yield_source": (
                "user_override"
                if source_type == SourceType.USER_OVERRIDE
                else "provided"
            ),
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
