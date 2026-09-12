"""EV/EBITDA engine with all enterprise-to-equity intermediates."""
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
FORMULA = "EV = Forward EBITDA × Multiple; Price = (EV - Net Debt) / Shares"


def _upside(price: Decimal, current: Decimal) -> Decimal:
    return ((price - current) / current).quantize(FOUR_PLACES, ROUND_HALF_UP)


def _premium(current: Decimal, fair_value: Decimal) -> Decimal:
    return ((current - fair_value) / fair_value).quantize(FOUR_PLACES, ROUND_HALF_UP)


def _assumption_metric(
    value: Decimal,
    label: str,
    source: str,
    source_type: SourceType,
    as_of: date,
    multiple_source: str,
    *,
    period: str = "valuation assumption",
    confidence: float | None = None,
    is_estimated: bool | None = None,
) -> dict:
    return metric_dict(FinancialMetric(
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
        is_estimated=(
            is_estimated
            if is_estimated is not None
            else source_type != SourceType.USER_OVERRIDE
        ),
        notes=f"{label}; multiple_source={multiple_source}",
    )) or {}


def _unavailable(reason: str, inputs: dict | None = None, warnings: list[str] | None = None) -> ModelValuation:
    return ModelValuation(
        formula=FORMULA,
        formula_description="Enterprise value based on forward EBITDA",
        inputs=inputs or {},
        assumptions={},
        calculation_steps=[],
        available=False,
        unavailable_reason=reason,
        warnings=warnings or [],
        data_quality=DataQuality.LOW,
    )


def run_ev_ebitda(snapshot: CompanyFinancialSnapshot, assumptions: ValuationAssumptions) -> ModelValuation:
    warnings: list[str] = []
    current_price = snapshot.current_price.value
    diluted_shares = snapshot.diluted_shares.value
    if current_price <= ZERO:
        return _unavailable(f"Current quote must be positive, got {current_price}")
    if diluted_shares <= ZERO:
        return _unavailable(f"Diluted shares must be positive, got {diluted_shares}")
    if getattr(snapshot, "shares_basis", None) == "CONFLICT_DEGRADED":
        return _unavailable(
            "Share capital reconciliation conflict: severe divergence across share classes/sources; model fails closed to prevent erroneous price targets.",
            warnings=["Diluted share count is in CONFLICT_DEGRADED state; per-share valuation model is unavailable."],
        )
    if snapshot.financial_currency and snapshot.financial_currency.upper() != snapshot.currency.upper():
        return _unavailable(
            f"Currency mismatch: quote currency ({snapshot.currency}) differs from statement reporting currency ({snapshot.financial_currency}) without FX conversion"
        )
    if snapshot.cash is None or snapshot.total_debt is None:
        return _unavailable("Cash and total debt are required to compute net debt for EV/EBITDA")
    cash = snapshot.cash.value
    debt = snapshot.total_debt.value
    if cash < ZERO or debt < ZERO:
        return _unavailable("Cash and total debt must be non-negative")

    sec = f"{snapshot.sector or ''} {snapshot.industry or ''}".lower()
    if any(term in sec for term in ["financial services", "financials", "bank", "insurance"]):
        return _unavailable(
            "EV/EBITDA is not applicable to banks and financial institutions due to operating debt and deposit structures"
        )
    if any(term in sec for term in ["reit", "real estate investment trust"]):
        return _unavailable(
            "EV/EBITDA is not applicable to REITs (requires FFO/AFFO multiples instead of standard EV/EBITDA)"
        )

    ebitda_metric = snapshot.forward_ebitda_1y or snapshot.forward_ebitda_2y
    if ebitda_metric is None:
        return _unavailable("No forward EBITDA estimate available")
    ebitda = ebitda_metric.value
    if ebitda <= ZERO:
        return _unavailable(
            f"Forward EBITDA is non-positive ({ebitda}); model requires positive EBITDA",
            inputs={"forward_ebitda": str(ebitda)},
        )

    scenarios = assumptions.ev_ebitda_multiple
    source_type = assumptions.ev_ebitda_source
    source_label = assumptions.ev_ebitda_source_label
    selection_layer = getattr(assumptions, "ev_ebitda_selection_layer", "system")
    selection_as_of = getattr(assumptions, "ev_ebitda_selection_as_of", None)
    multiple_source = "fallback"
    historical_metric: FinancialMetric | None = None
    if assumptions.ev_ebitda_source == SourceType.USER_OVERRIDE:
        multiple_source = "user_override"
    elif selection_layer in {"company_historical", "industry"}:
        # The service-level arbiter validates EV/forward EBITDA evidence
        # independently from P/E and passes the selected scenarios here.
        multiple_source = selection_layer
    elif snapshot.historical_ev_ebitda is not None and snapshot.historical_ev_ebitda.value > ZERO:
        historical_metric = snapshot.historical_ev_ebitda
        hist = historical_metric.value
        scenarios = ScenarioValues(
            low=(hist * Decimal("0.9")).quantize(Decimal("0.0001"), ROUND_HALF_UP),
            base=hist.quantize(Decimal("0.0001"), ROUND_HALF_UP),
            high=(hist * Decimal("1.1")).quantize(Decimal("0.0001"), ROUND_HALF_UP),
        )
        source_type = historical_metric.source_type
        source_label = f"Historical median EV/EBITDA ({historical_metric.source})"
        multiple_source = "historical"
    elif snapshot.historical_ev_ebitda is not None:
        warnings.append("Historical EV/EBITDA is non-positive; using configured fallback")

    if multiple_source == "fallback" and source_type == SourceType.CONFIGURED_FALLBACK:
        warnings.append(
            f"EV/EBITDA used configured fallback because parameter specificity was insufficient [{source_label}]"
        )

    if not (scenarios.low <= scenarios.base <= scenarios.high):
        return _unavailable("Effective EV/EBITDA assumptions must satisfy low <= base <= high")

    nd_metric = net_debt_metric(snapshot)
    net_debt = nd_metric.value
    market_cap = (current_price * diluted_shares).quantize(TWO_PLACES, ROUND_HALF_UP)
    input_metrics = {
        key: value
        for key, value in {
            "current_price": metric_dict(snapshot.current_price),
            "diluted_shares": metric_dict(snapshot.diluted_shares),
            "cash": metric_dict(snapshot.cash),
            "total_debt": metric_dict(snapshot.total_debt),
            "net_debt": metric_dict(nd_metric),
            "forward_ebitda": metric_dict(ebitda_metric),
            "market_cap": metric_dict(FinancialMetric(
                value=market_cap,
                unit="USD",
                period="valuation date",
                source="Derived from current quote × diluted shares",
                source_type=SourceType.DERIVED,
                as_of=snapshot.current_price.as_of,
                confidence=min(snapshot.current_price.confidence, snapshot.diluted_shares.confidence),
                is_estimated=snapshot.current_price.is_estimated or snapshot.diluted_shares.is_estimated,
                notes="Market capitalization used as an exposed EV/EBITDA intermediate.",
            )),
        }.items()
        if value is not None
    }
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
                label,
                (
                    historical_metric.source
                    if observed
                    else f"Derived {label} range from historical median ({historical_metric.source})"
                ),
                historical_metric.source_type if observed else SourceType.DERIVED,
                historical_metric.as_of,
                multiple_source,
                period=historical_metric.period,
                confidence=historical_metric.confidence,
                is_estimated=(historical_metric.is_estimated if observed else True),
            )
        return _assumption_metric(
            value,
            label,
            source_label,
            assumption_source_type,
            selection_as_of or ebitda_metric.as_of,
            multiple_source,
        )

    assumption_metrics = {
        f"multiple_{label}": assumption_metric(label, value)
        for label, value in (("low", scenarios.low), ("base", scenarios.base), ("high", scenarios.high))
    }

    def calculate(multiple: Decimal, label: str) -> tuple[PriceEstimate, list[str], Decimal, Decimal]:
        ev = (ebitda * multiple).quantize(TWO_PLACES, ROUND_HALF_UP)
        equity = ev - net_debt
        if equity <= ZERO:
            raise ValueError(f"EV/EBITDA {label} scenario has non-positive equity value ({equity})")
        price = (equity / diluted_shares).quantize(TWO_PLACES, ROUND_HALF_UP)
        estimate = PriceEstimate(
            price_per_share=price,
            upside_pct=_upside(price, current_price),
            premium_discount_pct=_premium(current_price, price),
            intermediates={
                "ev": str(ev),
                "equity_value": str(equity),
                "net_debt": str(net_debt),
                "market_cap": str(market_cap),
                "multiple": str(multiple),
            },
        )
        return estimate, [
            f"[{label}] EV = {ebitda} × {multiple} = {ev}",
            f"[{label}] Equity = {ev} - {net_debt} = {equity}",
            f"[{label}] Price/share = {equity} / {diluted_shares} = {price}",
        ], ev, equity

    try:
        low, low_steps, _, _ = calculate(scenarios.low, "low")
        base, base_steps, _, _ = calculate(scenarios.base, "base")
        high, high_steps, _, _ = calculate(scenarios.high, "high")
    except ValueError as exc:
        return _unavailable(str(exc), warnings=warnings)

    steps = [
        f"Forward EBITDA = {ebitda} [{ebitda_metric.period}; {ebitda_metric.source}; as_of={ebitda_metric.as_of}; estimated={ebitda_metric.is_estimated}]",
        f"Market cap = {current_price} × {diluted_shares} = {market_cap}",
        f"Net debt = total debt {debt} - cash {cash} = {net_debt}",
        f"Multiples (low/base/high) = {scenarios.low}/{scenarios.base}/{scenarios.high} [{multiple_source}; {source_label}]",
        *low_steps,
        *base_steps,
        *high_steps,
    ]
    quality = DataQuality.LOW if snapshot.is_demo else (
        DataQuality.MEDIUM if ebitda_metric.is_estimated else DataQuality.HIGH
    )
    return ModelValuation(
        formula=FORMULA,
        formula_description=(
            "EV = forward EBITDA × multiple; equity value = EV − net debt; "
            "price per share = equity value / diluted shares."
        ),
        inputs={
            "forward_ebitda": str(ebitda),
            "forward_ebitda_period": ebitda_metric.period,
            "forward_ebitda_source": ebitda_metric.source,
            "forward_ebitda_source_type": ebitda_metric.source_type,
            "forward_ebitda_as_of": str(ebitda_metric.as_of),
            "current_price": str(current_price),
            "diluted_shares": str(diluted_shares),
            "cash": str(cash),
            "total_debt": str(debt),
            "net_debt": str(net_debt),
            "market_cap": str(market_cap),
        },
        assumptions={
            "multiple_low": str(scenarios.low),
            "multiple_base": str(scenarios.base),
            "multiple_high": str(scenarios.high),
            "source": assumption_source_type,
            "source_label": source_label,
            "multiple_source": multiple_source,
            "selection_layer": selection_layer,
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
