"""Forward P/E engine: ``price = forward EPS * target multiple``."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from app.models.domain import (
    CompanyFinancialSnapshot,
    DataQuality,
    FinancialMetric,
    ModelValuation,
    PriceEstimate,
    ScenarioValues,
    SourceType,
    ValuationAssumptions,
    metric_dict,
    net_debt_metric,
)

TWO_PLACES = Decimal("0.01")
FOUR_PLACES = Decimal("0.0001")
ZERO = Decimal("0")
FORMULA = "Price = Forward EPS × Target P/E"


def _ratio(value: Decimal, current: Decimal) -> Decimal:
    return ((value - current) / current).quantize(FOUR_PLACES, ROUND_HALF_UP)


def _premium(current: Decimal, fair_value: Decimal) -> Decimal:
    return ((current - fair_value) / fair_value).quantize(FOUR_PLACES, ROUND_HALF_UP)


def _assumption_metric(
    value: Decimal,
    *,
    name: str,
    source: str,
    source_type: SourceType,
    as_of: date,
    is_estimated: bool,
    notes: str,
    period: str = "valuation assumption",
    confidence: float | None = None,
) -> dict:
    return metric_dict(
        FinancialMetric(
            value=value,
            unit="multiple",
            period=period,
            source=source,
            source_type=source_type,
            as_of=as_of,
            confidence=(
                confidence
                if confidence is not None
                else (1.0 if source_type == SourceType.USER_OVERRIDE else 0.8)
            ),
            is_estimated=is_estimated,
            notes=f"{name}: {notes}",
        )
    ) or {}


def _unavailable(reason: str, *, inputs: dict | None = None, warnings: list[str] | None = None) -> ModelValuation:
    return ModelValuation(
        formula=FORMULA,
        formula_description="Forward earnings-based price target",
        inputs=inputs or {},
        assumptions={},
        calculation_steps=[],
        available=False,
        unavailable_reason=reason,
        warnings=warnings or [],
        data_quality=DataQuality.LOW,
    )


def run_forward_pe(snapshot: CompanyFinancialSnapshot, assumptions: ValuationAssumptions) -> ModelValuation:
    warnings: list[str] = []
    current_price = snapshot.current_price.value

    if current_price <= ZERO:
        return _unavailable(f"Current quote must be positive, got {current_price}")
    if snapshot.diluted_shares.value <= ZERO:
        return _unavailable(f"Diluted shares must be positive, got {snapshot.diluted_shares.value}")
    horizon = getattr(assumptions, "forecast_horizon", "ntm")
    eps_metric: FinancialMetric | None = None
    forward_eps_override = getattr(snapshot, "forward_eps", None)
    if forward_eps_override is not None:
        eps_metric = forward_eps_override
    elif snapshot.forward_eps_1y is not None and "NTM" in (snapshot.forward_eps_1y.period or ""):
        eps_metric = snapshot.forward_eps_1y
    elif horizon == "current_fy":
        eps_metric = snapshot.forward_eps_1y or snapshot.forward_eps_2y
    elif horizon == "next_fy":
        eps_metric = snapshot.forward_eps_2y or snapshot.forward_eps_1y
    else:  # "ntm"
        if (
            snapshot.forward_eps_1y is not None
            and snapshot.forward_eps_2y is not None
        ):
            w1 = Decimal("1")
            w2 = Decimal("0")
            if snapshot.ntm_weights is not None:
                w1 = snapshot.ntm_weights.get("current_fy", Decimal("1"))
                w2 = snapshot.ntm_weights.get("next_fy", Decimal("0"))
            elif snapshot.forecast_fiscal_year_end is not None:
                from app.services.projections import calculate_ntm_weights
                as_of = snapshot.current_price.as_of if snapshot.current_price else date.today()
                w1, w2, _, _ = calculate_ntm_weights(as_of, snapshot.forecast_fiscal_year_end)
            blended_eps = (
                snapshot.forward_eps_1y.value * w1 + snapshot.forward_eps_2y.value * w2
            ).quantize(TWO_PLACES, ROUND_HALF_UP)
            eps_metric = FinancialMetric(
                value=blended_eps,
                unit=snapshot.forward_eps_1y.unit,
                period="NTM",
                source=f"NTM day-weighted: {w1 * 100:.1f}% {snapshot.forward_eps_1y.period} + {w2 * 100:.1f}% {snapshot.forward_eps_2y.period}",
                source_type=SourceType.DERIVED,
                as_of=max(snapshot.forward_eps_1y.as_of, snapshot.forward_eps_2y.as_of),
                confidence=min(snapshot.forward_eps_1y.confidence, snapshot.forward_eps_2y.confidence),
                is_estimated=True,
                notes="Day-weighted NTM consensus forecast",
            )
        else:
            eps_metric = snapshot.forward_eps_1y or snapshot.forward_eps_2y

    if eps_metric is None:
        return _unavailable("No forward EPS estimate available")

    # Check for currency mismatch between quote and forward EPS
    eps_unit = (eps_metric.unit or "").upper()
    quote_curr = (snapshot.currency or "USD").upper()
    if snapshot.financial_currency and snapshot.financial_currency.upper() != quote_curr:
        if eps_unit and not eps_unit.startswith(quote_curr) and eps_unit not in {quote_curr, f"{quote_curr}/SHARE"}:
            return _unavailable(
                f"Currency mismatch: quote currency ({snapshot.currency}) differs from forward EPS currency ({eps_metric.unit}) without FX conversion"
            )
    forward_eps = eps_metric.value
    if forward_eps <= ZERO:
        return _unavailable(
            f"Forward EPS is non-positive ({forward_eps}); model requires profitable company",
            inputs={"forward_eps": str(forward_eps)},
        )

    scenarios = assumptions.pe_target
    source_type = assumptions.pe_source
    source_label = assumptions.pe_source_label
    selection_layer = getattr(assumptions, "pe_selection_layer", "system")
    selection_as_of = getattr(assumptions, "pe_selection_as_of", None)
    multiple_source = "fallback"
    historical_metric: FinancialMetric | None = None

    # Historical medians are preferred unless the request explicitly supplied
    # an override. This ordering is intentional and tested by the API.
    if assumptions.pe_source == SourceType.USER_OVERRIDE:
        multiple_source = "user_override"
    elif selection_layer in {"company_historical", "industry"}:
        # The service-level arbiter has already validated and selected this
        # source independently for P/E.  Do not re-derive it from a current
        # quote or from an unrelated historical field.
        multiple_source = selection_layer
    elif snapshot.historical_forward_pe is not None and snapshot.historical_forward_pe.value > ZERO:
        historical_metric = snapshot.historical_forward_pe
        hist = historical_metric.value
        scenarios = ScenarioValues(
            low=(hist * Decimal("0.9")).quantize(Decimal("0.0001"), ROUND_HALF_UP),
            base=hist.quantize(Decimal("0.0001"), ROUND_HALF_UP),
            high=(hist * Decimal("1.1")).quantize(Decimal("0.0001"), ROUND_HALF_UP),
        )
        source_type = historical_metric.source_type
        source_label = f"Historical median P/E ({historical_metric.source})"
        multiple_source = "historical"
    elif snapshot.historical_forward_pe is not None:
        warnings.append("Historical P/E is non-positive; using configured fallback")

    if multiple_source == "fallback" and source_type == SourceType.CONFIGURED_FALLBACK:
        warnings.append(
            f"P/E used configured fallback because parameter specificity was insufficient [{source_label}]"
        )

    if not (scenarios.low <= scenarios.base <= scenarios.high):
        return _unavailable("Effective P/E assumptions must satisfy low <= base <= high")

    as_of = selection_as_of or eps_metric.as_of
    assumption_source_type = (
        historical_metric.source_type
        if historical_metric is not None
        else (SourceType.USER_OVERRIDE if multiple_source == "user_override" else source_type)
    )

    def assumption_metric(label: str, value: Decimal) -> dict:
        if historical_metric is not None:
            observed = label == "base"
            return _assumption_metric(
                value,
                name=f"P/E {label}",
                source=(
                    historical_metric.source
                    if observed
                    else f"Derived {label} range from historical median ({historical_metric.source})"
                ),
                source_type=(historical_metric.source_type if observed else SourceType.DERIVED),
                as_of=historical_metric.as_of,
                is_estimated=(historical_metric.is_estimated if observed else True),
                period=historical_metric.period,
                confidence=historical_metric.confidence,
                notes=(
                    "multiple_source=historical; observed historical median"
                    if observed
                    else "multiple_source=historical; derived ±10% scenario range"
                ),
            )
        return _assumption_metric(
            value,
            name=f"P/E {label}",
            source=source_label,
            source_type=assumption_source_type,
            as_of=as_of,
            is_estimated=multiple_source != "user_override",
            notes=f"multiple_source={multiple_source}",
        )

    assumption_metrics = {
        f"pe_multiple_{label}": assumption_metric(label, value)
        for label, value in (("low", scenarios.low), ("base", scenarios.base), ("high", scenarios.high))
    }

    structural = {
        "current_price": metric_dict(snapshot.current_price),
        "diluted_shares": metric_dict(snapshot.diluted_shares),
        "cash": metric_dict(snapshot.cash),
        "total_debt": metric_dict(snapshot.total_debt),
        "net_debt": metric_dict(net_debt_metric(snapshot)),
        "forward_eps": metric_dict(eps_metric),
    }
    input_metrics = {k: v for k, v in structural.items() if v is not None}

    prices = {
        "low": (forward_eps * scenarios.low).quantize(TWO_PLACES, ROUND_HALF_UP),
        "base": (forward_eps * scenarios.base).quantize(TWO_PLACES, ROUND_HALF_UP),
        "high": (forward_eps * scenarios.high).quantize(TWO_PLACES, ROUND_HALF_UP),
    }

    def estimate(price: Decimal, multiple: Decimal) -> PriceEstimate:
        return PriceEstimate(
            price_per_share=price,
            upside_pct=_ratio(price, current_price),
            premium_discount_pct=_premium(current_price, price),
            intermediates={
                "forward_eps": str(forward_eps),
                "target_multiple": str(multiple),
            },
        )

    steps = [
        f"Forward EPS = {forward_eps} [{eps_metric.period}; {eps_metric.source}; as_of={eps_metric.as_of}; estimated={eps_metric.is_estimated}]",
        f"P/E multiples (low/base/high) = {scenarios.low}/{scenarios.base}/{scenarios.high} [{multiple_source}; {source_label}]",
        f"Price (low) = {forward_eps} × {scenarios.low} = {prices['low']}",
        f"Price (base) = {forward_eps} × {scenarios.base} = {prices['base']}",
        f"Price (high) = {forward_eps} × {scenarios.high} = {prices['high']}",
    ]
    quality = DataQuality.LOW if snapshot.is_demo else (
        DataQuality.MEDIUM if eps_metric.is_estimated else DataQuality.HIGH
    )

    return ModelValuation(
        formula=FORMULA,
        formula_description=(
            "Price target derived from forward EPS multiplied by a target P/E. "
            "Historical median is used when available; otherwise the configured fallback applies."
        ),
        inputs={
            "forward_eps": str(forward_eps),
            "forward_eps_period": eps_metric.period,
            "forward_eps_source": eps_metric.source,
            "forward_eps_source_type": eps_metric.source_type,
            "forward_eps_as_of": str(eps_metric.as_of),
            "forward_eps_is_estimated": eps_metric.is_estimated,
            "current_price": str(current_price),
        },
        assumptions={
            "pe_multiple_low": str(scenarios.low),
            "pe_multiple_base": str(scenarios.base),
            "pe_multiple_high": str(scenarios.high),
            "pe_source": assumption_source_type,
            "pe_source_label": source_label,
            "multiple_source": multiple_source,
            "selection_layer": selection_layer,
            "forecast_horizon": horizon,
        },
        input_metrics=input_metrics,
        assumption_metrics=assumption_metrics,
        calculation_steps=steps,
        low=estimate(prices["low"], scenarios.low),
        base=estimate(prices["base"], scenarios.base),
        high=estimate(prices["high"], scenarios.high),
        warnings=warnings,
        data_quality=quality,
    )
