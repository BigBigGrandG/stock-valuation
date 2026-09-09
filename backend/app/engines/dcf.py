"""Five-year FCFF DCF engine.

The engine never substitutes FCFE for FCFF. Forward FCFF1/FCFF2 are used as
the first two explicit forecast years; if they are missing, a historical TTM
value is grown into a newly-labelled forecast year. Years 3–5 are deterministic
and capped, with each derived projection carrying its own provenance metric.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from app.config import (
    DEFAULT_DCF_FCF_GROWTH_FALLBACK,
    DCF_TERMINAL_GROWTH_MAX,
    FCF_GROWTH_CAP_BASE,
    FCF_GROWTH_CAP_BEAR,
    FCF_GROWTH_CAP_BULL,
    FCF_GROWTH_FLOOR,
)
from app.models.domain import (
    CompanyFinancialSnapshot,
    DataQuality,
    DCFScenario,
    FinancialMetric,
    ModelValuation,
    PriceEstimate,
    ScenarioValues,
    SourceType,
    ValuationAssumptions,
    metric_dict,
    net_debt_metric,
)

PREC = Decimal("0.01")
FOUR = Decimal("0.0001")
ZERO = Decimal("0")
N_YEARS = 5
FORMULA = "EV = Σ FCFF_t/(1+WACC)^t + TV/(1+WACC)^5; Equity = EV − Net Debt; Price = Equity/Shares"


def _upside(price: Decimal, current: Decimal) -> Decimal:
    return ((price - current) / current).quantize(FOUR, ROUND_HALF_UP) if current else ZERO


def _premium(current: Decimal, fair_value: Decimal) -> Decimal:
    return ((current - fair_value) / fair_value).quantize(FOUR, ROUND_HALF_UP) if fair_value else ZERO


def _cap_growth(value: Decimal, cap: Decimal) -> Decimal:
    return min(max(value, FCF_GROWTH_FLOOR), cap)


def _ordered_growth(raw: Decimal) -> ScenarioValues:
    values = [
        _cap_growth(raw * Decimal("0.85"), FCF_GROWTH_CAP_BEAR),
        _cap_growth(raw, FCF_GROWTH_CAP_BASE),
        _cap_growth(raw * Decimal("1.15"), FCF_GROWTH_CAP_BULL),
    ]
    values.sort()
    return ScenarioValues(low=values[0], base=values[1], high=values[2])


def _growth_source(
    snapshot: CompanyFinancialSnapshot,
    override: Optional[ScenarioValues],
) -> tuple[ScenarioValues, str, str, Optional[FinancialMetric]]:
    """Resolve growth using FCFF-forward, analyst operational, historical, fallback order."""

    if override is not None:
        capped = ScenarioValues(
            low=_cap_growth(override.low, FCF_GROWTH_CAP_BEAR),
            base=_cap_growth(override.base, FCF_GROWTH_CAP_BASE),
            high=_cap_growth(override.high, FCF_GROWTH_CAP_BULL),
        )
        metric = FinancialMetric(
            value=capped.base,
            unit="ratio",
            period="valuation assumption",
            source="User override: dcf.fcf_growth",
            source_type=SourceType.USER_OVERRIDE,
            as_of=snapshot.current_price.as_of,
            confidence=1.0,
            is_estimated=False,
            notes="Capped deterministic FCFF growth for years 3-5.",
        )
        return capped, "user_override dcf.fcf_growth (capped)", "user_override", metric

    # Prefer explicit analyst forward FCFF1 -> FCFF2. Fixture values retain
    # fixture provenance; the *derived rate* is never labelled consensus.
    if (
        snapshot.forward_fcff_1y is not None
        and snapshot.forward_fcff_2y is not None
        and snapshot.forward_fcff_1y.value > ZERO
        and snapshot.forward_fcff_2y.value > ZERO
    ):
        first = snapshot.forward_fcff_1y
        second = snapshot.forward_fcff_2y
        raw = (second.value - first.value) / first.value
        metric = FinancialMetric(
            value=raw,
            unit="ratio",
            period=f"{first.period}->{second.period}",
            source=f"Derived from forward FCFF {first.period} and {second.period}",
            source_type=SourceType.DERIVED,
            as_of=max(first.as_of, second.as_of),
            confidence=min(first.confidence, second.confidence),
            is_estimated=True,
            notes="Derived FCFF growth; not a separate analyst consensus value.",
        )
        return _ordered_growth(raw), "derived from forward FCFF1→FCFF2 (capped)", "derived", metric

    # Historical TTM -> first forecast is still FCFF, not FCFE. This rate is
    # also the least-surprising deterministic continuation when FCFF2 is absent.
    if snapshot.fcff_ttm is not None and snapshot.forward_fcff_1y is not None:
        ttm = snapshot.fcff_ttm
        first = snapshot.forward_fcff_1y
        if ttm.value > ZERO and first.value > ZERO:
            raw = (first.value - ttm.value) / ttm.value
            metric = FinancialMetric(
                value=raw,
                unit="ratio",
                period=f"{ttm.period}->{first.period}",
                source="Derived from FCFF TTM to forward FCFF1",
                source_type=SourceType.DERIVED,
                as_of=max(ttm.as_of, first.as_of),
                confidence=min(ttm.confidence, first.confidence),
                is_estimated=True,
                notes="Historical-to-forward FCFF growth; not FCFE.",
            )
            return _ordered_growth(raw), "derived from FCFF TTM→FCFF1 (capped)", "derived", metric

    # Prefer an explicitly forward/analyst operational estimate next.  An
    # actual/historical operational metric is not an analyst proxy.
    operational = (
        (snapshot.revenue_growth, "revenue growth"),
        (snapshot.ebitda_growth, "EBITDA growth"),
        (snapshot.eps_growth, "EPS growth"),
    )
    forward_operational = [
        (candidate, label)
        for candidate, label in operational
        if candidate is not None
        and candidate.value.is_finite()
        and (
            candidate.source_type == SourceType.ANALYST_ESTIMATE
            or (
                candidate.source_type not in {SourceType.ACTUAL, SourceType.FIXTURE}
                and candidate.is_estimated
                and any(token in f"{candidate.period} {candidate.source}".lower() for token in ("forward", "estimate"))
            )
        )
    ]
    for candidate, label in forward_operational:
        metric = candidate.model_copy(update={
            "source": f"Derived FCFF growth from {label}: {candidate.source}",
            "source_type": SourceType.DERIVED,
            "notes": f"Forward operational {label} proxy; FCFE growth is not used.",
        })
        return _ordered_growth(candidate.value), f"derived from forward {label} (capped)", "derived", metric

    # Historical FCFF growth has explicit firm-cash-flow lineage and outranks
    # a historical revenue/EBITDA/EPS metric that could be unrelated to FCFF.
    if snapshot.fcff_growth is not None and snapshot.fcff_growth.value.is_finite():
        candidate = snapshot.fcff_growth
        metric = candidate.model_copy(update={
            "source": f"Historical FCFF growth: {candidate.source}",
            "source_type": SourceType.DERIVED,
            "notes": "Historical FCFF growth; FCFE growth is not used.",
        })
        return _ordered_growth(candidate.value), "historical FCFF growth (capped)", "derived", metric

    # Last, use an explicitly historical operational proxy.  This branch is
    # intentionally after FCFF growth and never considers FCFE growth.
    for candidate, label in operational:
        if candidate is not None and candidate.value.is_finite():
            metric = candidate.model_copy(update={
                "source": f"Derived FCFF growth from historical {label}: {candidate.source}",
                "source_type": SourceType.DERIVED,
                "notes": f"Historical operational {label} proxy; FCFE growth is not used.",
            })
            return _ordered_growth(candidate.value), f"derived from historical {label} (capped)", "derived", metric

    fallback = DEFAULT_DCF_FCF_GROWTH_FALLBACK
    metric = FinancialMetric(
        value=fallback.base,
        unit="ratio",
        period="configured fallback",
        source="Configured fallback FCFF growth",
        source_type=SourceType.CONFIGURED_FALLBACK,
        as_of=snapshot.current_price.as_of,
        confidence=1.0,
        is_estimated=True,
        notes="Fallback only; no FCFF growth estimate was available.",
    )
    return fallback, "configured fallback FCFF growth (capped)", "configured_fallback", metric


def _derive_fcff_growth(snapshot: CompanyFinancialSnapshot, override: Optional[ScenarioValues]):
    """Compatibility wrapper retained for existing callers/tests."""

    values, label, source_type, _ = _growth_source(snapshot, override)
    return values, label, source_type


def _year_from_period(period: str, as_of: date) -> int:
    match = re.search(r"(?:FY)?(20\d{2})", period or "")
    if match:
        year = int(match.group(1))
        return year + 1 if "TTM" in period.upper() else year
    return as_of.year


def _forecast_period(period: str, as_of: date, offset: int = 0) -> str:
    year = _year_from_period(period, as_of) + offset
    return f"FY{year}E"


def _projection_metric(
    value: Decimal,
    *,
    period: str,
    source: str,
    source_type: SourceType,
    as_of: date,
    confidence: float,
    is_estimated: bool,
    notes: str,
) -> FinancialMetric:
    return FinancialMetric(
        value=value,
        unit="USD",
        period=period,
        source=source,
        source_type=source_type,
        as_of=as_of,
        confidence=confidence,
        is_estimated=is_estimated,
        notes=notes,
    )


def _compute_dcf_scenario(
    scenario_name: str,
    fcff_y1: Decimal,
    fcff_y2: Optional[Decimal],
    fcff_y1_label: str,
    fcff_y2_label: Optional[str],
    growth_rate: Decimal,
    wacc: Decimal,
    terminal_growth: Decimal,
    total_debt: Decimal,
    cash: Decimal,
    diluted_shares: Decimal,
    current_price: Decimal,
    base_year: int = 2025,
    *,
    fcff_y1_metric: Optional[FinancialMetric] = None,
    fcff_y2_metric: Optional[FinancialMetric] = None,
    growth_metric: Optional[FinancialMetric] = None,
    growth_cap: Optional[Decimal] = None,
    net_debt_value: Optional[Decimal] = None,
    projection_as_of: Optional[date] = None,
) -> DCFScenario:
    """Compute one path using explicit five-year PV math."""

    if not wacc.is_finite() or not terminal_growth.is_finite() or wacc <= terminal_growth:
        raise ValueError(
            f"DCF [{scenario_name}]: WACC ({wacc}) must be > terminal_growth ({terminal_growth})"
        )
    if terminal_growth > DCF_TERMINAL_GROWTH_MAX:
        raise ValueError(
            f"DCF [{scenario_name}]: terminal_growth ({terminal_growth}) exceeds configured max ({DCF_TERMINAL_GROWTH_MAX})"
        )
    if diluted_shares <= ZERO:
        raise ValueError("DCF requires positive diluted shares")
    if fcff_y1 <= ZERO:
        raise ValueError("DCF requires positive FCFF")

    as_of = projection_as_of or (fcff_y1_metric.as_of if fcff_y1_metric else date.today())
    first_period = fcff_y1_metric.period if fcff_y1_metric else f"FY{base_year}E"
    projections: list[Decimal] = []
    periods: list[str] = []
    metrics: list[dict] = []
    pvs: list[Decimal] = []

    previous: Optional[Decimal] = None
    raw_growth_metric = growth_metric
    effective_growth_metric = growth_metric
    if growth_metric is not None:
        raw_growth = growth_metric.value
        cap = growth_cap if growth_cap is not None else Decimal("Infinity")
        effective_growth_metric = growth_metric.model_copy(update={
            "value": growth_rate,
            "source": f"{growth_metric.source}; effective {scenario_name} FCFF growth",
            "notes": (
                f"Raw growth={raw_growth}; effective growth={growth_rate}; "
                f"floor={FCF_GROWTH_FLOOR}; cap={cap}; lineage={growth_metric.source}."
            ),
        })
    growth_note = (
        f" Raw growth={growth_metric.value}; effective growth={growth_rate}; "
        f"floor={FCF_GROWTH_FLOOR}; cap={growth_cap}; lineage={growth_metric.source}."
        if growth_metric is not None
        else ""
    )
    for year in range(1, N_YEARS + 1):
        if year == 1:
            value = fcff_y1.quantize(PREC, ROUND_HALF_UP)
            metric = fcff_y1_metric or _projection_metric(
                value,
                period=first_period,
                source=fcff_y1_label,
                source_type=SourceType.DERIVED,
                as_of=as_of,
                confidence=0.5,
                is_estimated=True,
                notes="FCFF Year 1 input supplied directly to DCF.",
            )
        elif year == 2 and fcff_y2 is not None:
            value = fcff_y2.quantize(PREC, ROUND_HALF_UP)
            metric = fcff_y2_metric or _projection_metric(
                value,
                period=fcff_y2_metric.period if fcff_y2_metric else f"FY{base_year + 1}E",
                source=fcff_y2_label or "Forward FCFF Year 2",
                source_type=SourceType.DERIVED,
                as_of=as_of,
                confidence=0.5,
                is_estimated=True,
                notes="FCFF Year 2 input supplied directly to DCF.",
            )
        else:
            value = (previous * (Decimal("1") + growth_rate)).quantize(PREC, ROUND_HALF_UP)  # type: ignore[operator]
            metric = _projection_metric(
                value,
                period=_forecast_period(first_period, as_of, year - 1),
                source=f"Derived from prior FCFF projection × (1 + {growth_rate})",
                source_type=SourceType.DERIVED,
                as_of=as_of,
                confidence=(growth_metric.confidence if growth_metric else 1.0),
                is_estimated=True,
                notes="Capped deterministic FCFF projection; no FCFE substitution." + growth_note,
            )
        if value <= ZERO:
            raise ValueError(f"DCF [{scenario_name}] produced non-positive FCFF in year {year}")
        pv = (value / ((Decimal("1") + wacc) ** year)).quantize(PREC, ROUND_HALF_UP)
        projections.append(value)
        periods.append(metric.period)
        metrics.append(metric_dict(metric) or {})
        pvs.append(pv)
        previous = value

    terminal_value = (
        projections[-1] * (Decimal("1") + terminal_growth) / (wacc - terminal_growth)
    ).quantize(PREC, ROUND_HALF_UP)
    pv_terminal_value = (terminal_value / ((Decimal("1") + wacc) ** N_YEARS)).quantize(PREC, ROUND_HALF_UP)
    enterprise_value = (sum(pvs) + pv_terminal_value).quantize(PREC, ROUND_HALF_UP)
    net_debt = net_debt_value if net_debt_value is not None else total_debt - cash
    equity_value = enterprise_value - net_debt
    if equity_value <= ZERO:
        raise ValueError(f"DCF [{scenario_name}] produced non-positive equity value ({equity_value})")
    price = (equity_value / diluted_shares).quantize(PREC, ROUND_HALF_UP)

    formulas = {
        "pv_year": "PV_t = FCFF_t / (1 + WACC)^t",
        "terminal_value": "TV = FCFF_5 × (1 + g) / (WACC - g)",
        "pv_terminal_value": "PVTV = TV / (1 + WACC)^5",
        "enterprise_value": "EV = Σ(PV_1..PV_5) + PVTV",
        "equity_value": "Equity = EV - debt + cash = EV - net_debt",
        "price_per_share": "Price = Equity / diluted shares",
    }
    steps = [
        f"[{scenario_name}] FCFF projections ({', '.join(periods)}) = {projections}",
        *[f"[{scenario_name}] PV year {year} = {projections[year - 1]} / (1 + {wacc})^{year} = {pvs[year - 1]}" for year in range(1, N_YEARS + 1)],
        f"[{scenario_name}] TV = {projections[-1]} × (1 + {terminal_growth}) / ({wacc} - {terminal_growth}) = {terminal_value}",
        f"[{scenario_name}] PVTV = {terminal_value} / (1 + {wacc})^5 = {pv_terminal_value}",
        f"[{scenario_name}] EV = {sum(pvs)} + {pv_terminal_value} = {enterprise_value}",
        f"[{scenario_name}] Equity = {enterprise_value} - {total_debt} + {cash} = {equity_value}",
        f"[{scenario_name}] Price/share = {equity_value} / {diluted_shares} = {price}",
    ]
    return DCFScenario(
        scenario=scenario_name,  # type: ignore[arg-type]
        wacc=wacc,
        terminal_growth=terminal_growth,
        growth_rate=growth_rate,
        growth_metric=metric_dict(effective_growth_metric),
        growth_metric_raw=metric_dict(raw_growth_metric),
        growth_cap=growth_cap,
        growth_floor=FCF_GROWTH_FLOOR,
        fcff_year1=projections[0],
        fcff_projections=projections,
        projection_periods=periods,
        projection_metrics=metrics,
        pv_years=list(range(1, N_YEARS + 1)),
        pv_projections=pvs,
        terminal_value=terminal_value,
        pv_terminal_value=pv_terminal_value,
        enterprise_value=enterprise_value,
        total_debt=total_debt,
        cash=cash,
        net_debt=net_debt,
        equity_value=equity_value,
        diluted_shares=diluted_shares,
        price_per_share=price,
        upside_pct=_upside(price, current_price),
        premium_discount_pct=_premium(current_price, price),
        formulas=formulas,
        calculation_steps=steps,
    )


def _calculate_wacc(snapshot: CompanyFinancialSnapshot) -> Optional[Decimal]:
    """Calculate CAPM/equity-debt weighted WACC when every input exists."""

    required = (
        snapshot.risk_free_rate,
        snapshot.beta,
        snapshot.equity_risk_premium,
        snapshot.pre_tax_cost_of_debt,
        snapshot.tax_rate,
    )
    if any(metric is None for metric in required):
        return None
    market_cap = snapshot.current_price.value * snapshot.diluted_shares.value
    debt = snapshot.total_debt.value
    denominator = market_cap + debt
    if denominator <= ZERO:
        return None
    rf, beta, erp, debt_cost, tax = (metric.value for metric in required)  # type: ignore[misc]
    cost_of_equity = rf + beta * erp
    return (cost_of_equity * market_cap + debt_cost * (Decimal("1") - tax) * debt) / denominator


def run_dcf(snapshot: CompanyFinancialSnapshot, assumptions: ValuationAssumptions) -> ModelValuation:
    warnings: list[str] = []
    current = snapshot.current_price.value
    shares = snapshot.diluted_shares.value
    if current <= ZERO:
        return ModelValuation(formula=FORMULA, formula_description="Five-year FCFF DCF", inputs={}, assumptions={}, calculation_steps=[], available=False, unavailable_reason="Current quote must be positive", data_quality=DataQuality.LOW)
    if shares <= ZERO:
        return ModelValuation(formula=FORMULA, formula_description="Five-year FCFF DCF", inputs={}, assumptions={}, calculation_steps=[], available=False, unavailable_reason="Diluted shares must be positive", data_quality=DataQuality.LOW)
    if snapshot.financial_currency and snapshot.financial_currency.upper() != snapshot.currency.upper():
        return ModelValuation(
            formula=FORMULA,
            formula_description="Five-year FCFF DCF",
            inputs={},
            assumptions={},
            calculation_steps=[],
            available=False,
            unavailable_reason=f"Currency mismatch: quote currency ({snapshot.currency}) differs from statement reporting currency ({snapshot.financial_currency}) without FX conversion",
            data_quality=DataQuality.LOW,
        )
    if snapshot.cash is None or snapshot.total_debt is None:
        return ModelValuation(
            formula=FORMULA,
            formula_description="Five-year FCFF DCF",
            inputs={},
            assumptions={},
            calculation_steps=[],
            available=False,
            unavailable_reason="Cash and total debt are required to compute net debt for DCF equity value",
            data_quality=DataQuality.LOW,
        )
    cash = snapshot.cash.value
    debt = snapshot.total_debt.value
    nd_metric = net_debt_metric(snapshot)
    if cash < ZERO or debt < ZERO:
        return ModelValuation(formula=FORMULA, formula_description="Five-year FCFF DCF", inputs={}, assumptions={}, calculation_steps=[], available=False, unavailable_reason="Cash and debt must be non-negative", data_quality=DataQuality.LOW)

    sec = f"{snapshot.sector or ''} {snapshot.industry or ''}".lower()
    if any(term in sec for term in ["financial services", "financials", "bank", "insurance"]):
        return ModelValuation(
            formula=FORMULA,
            formula_description="Five-year FCFF DCF",
            inputs={},
            assumptions={},
            calculation_steps=[],
            available=False,
            unavailable_reason="FCFF DCF is not applicable to banks and financial institutions (operating debt structure is inseparable from operating cash flow)",
            warnings=["Banks and financial institutions do not use standard FCFF DCF; use Forward P/E instead."],
            data_quality=DataQuality.LOW,
        )
    if any(term in sec for term in ["reit", "real estate investment trust"]):
        return ModelValuation(
            formula=FORMULA,
            formula_description="Five-year FCFF DCF",
            inputs={},
            assumptions={},
            calculation_steps=[],
            available=False,
            unavailable_reason="DCF is not applicable to REITs (requires FFO/AFFO-based dividend models)",
            warnings=["REITs require FFO/AFFO-based dividend models instead of FCFF DCF."],
            data_quality=DataQuality.LOW,
        )

    y1_metric = snapshot.forward_fcff_1y if snapshot.forward_fcff_1y and snapshot.forward_fcff_1y.value > ZERO else None
    y2_metric = snapshot.forward_fcff_2y if snapshot.forward_fcff_2y and snapshot.forward_fcff_2y.value > ZERO else None
    ttm_metric = snapshot.fcff_ttm if snapshot.fcff_ttm and snapshot.fcff_ttm.value > ZERO else None
    if y1_metric is None and ttm_metric is None:
        only_fcfe = snapshot.forward_fcf_1y is not None or snapshot.fcf_ttm is not None
        reason = "No FCFF data available. FCFE cannot be substituted for FCFF in DCF."
        if only_fcfe:
            warnings.append("Only FCFE data was provided; FCFE cannot substitute FCFF in the DCF.")
        return ModelValuation(formula=FORMULA, formula_description="Five-year FCFF DCF", inputs={}, assumptions={}, calculation_steps=[], available=False, unavailable_reason=reason, warnings=warnings, data_quality=DataQuality.LOW)

    growth_scenarios, growth_label, growth_source_type, growth_metric = _growth_source(snapshot, assumptions.dcf_fcf_growth)

    # WACC precedence: request override, then CAPM if complete, then config.
    wacc_sv = assumptions.dcf_wacc
    if assumptions.dcf_wacc_source == SourceType.USER_OVERRIDE:
        wacc_source = "user_override"
        wacc_source_type = SourceType.USER_OVERRIDE
        wacc_source_label = assumptions.dcf_wacc_source_label
    else:
        calculated = _calculate_wacc(snapshot)
        if calculated is not None and calculated.is_finite() and calculated > ZERO:
            wacc_sv = ScenarioValues(
                low=calculated * Decimal("1.1"),
                base=calculated,
                high=calculated * Decimal("0.9"),
            )
            wacc_source = "calculated"
            wacc_source_type = SourceType.DERIVED
            wacc_source_label = "Calculated CAPM/equity-debt weighted WACC"
        else:
            wacc_source = "fallback"
            wacc_source_type = SourceType.CONFIGURED_FALLBACK
            wacc_source_label = assumptions.dcf_wacc_source_label

    tg_sv = assumptions.dcf_terminal_growth
    params = [
        ("bear", wacc_sv.low, tg_sv.low, growth_scenarios.low),
        ("base", wacc_sv.base, tg_sv.base, growth_scenarios.base),
        ("bull", wacc_sv.high, tg_sv.high, growth_scenarios.high),
    ]
    for name, wacc, tg, _ in params:
        if not wacc.is_finite() or not tg.is_finite() or wacc <= tg:
            raise ValueError(f"DCF [{name}]: WACC ({wacc}) must be > terminal_growth ({tg})")
        if tg > DCF_TERMINAL_GROWTH_MAX:
            return ModelValuation(
                formula=FORMULA,
                formula_description="Five-year discounted FCFF model",
                inputs={},
                assumptions={"terminal_growth_max": str(DCF_TERMINAL_GROWTH_MAX)},
                calculation_steps=[],
                available=False,
                unavailable_reason=(
                    f"DCF [{name}]: terminal_growth ({tg}) exceeds configured max "
                    f"({DCF_TERMINAL_GROWTH_MAX})"
                ),
                warnings=warnings,
                data_quality=DataQuality.LOW,
            )

    if y1_metric is not None:
        y1_value = y1_metric.value
        y1_label = f"Forward FCFF {y1_metric.period} [{y1_metric.source}]"
        first_period = y1_metric.period
        base_year = _year_from_period(first_period, y1_metric.as_of)
    else:
        # TTM is historical. Derive a separate Y1 for each scenario below,
        # rather than relabelling the TTM metric as a forecast.
        y1_value = None
        y1_label = f"Derived from FCFF TTM [{ttm_metric.source}]"  # type: ignore[union-attr]
        first_period = _forecast_period(ttm_metric.period, ttm_metric.as_of)  # type: ignore[union-attr]
        base_year = _year_from_period(first_period, ttm_metric.as_of)  # type: ignore[union-attr]
        warnings.append(f"FCFF TTM used only as historical base; Year 1 is derived as {first_period}.")

    scenarios: list[DCFScenario] = []
    errors: list[str] = []
    growth_caps = {
        "bear": FCF_GROWTH_CAP_BEAR,
        "base": FCF_GROWTH_CAP_BASE,
        "bull": FCF_GROWTH_CAP_BULL,
    }
    for name, wacc, tg, growth in params:
        try:
            if y1_value is None:
                y1_metric_for_scenario = _projection_metric(
                    (ttm_metric.value * (Decimal("1") + growth)).quantize(PREC, ROUND_HALF_UP),  # type: ignore[union-attr]
                    period=first_period,
                    source=f"Derived from historical FCFF {ttm_metric.period} × (1 + {growth})",  # type: ignore[union-attr]
                    source_type=SourceType.DERIVED,
                    as_of=ttm_metric.as_of,  # type: ignore[union-attr]
                    confidence=ttm_metric.confidence,  # type: ignore[union-attr]
                    is_estimated=True,
                    notes="Forecast Y1 derived from FCFF TTM; TTM is not relabelled.",
                )
                y1 = y1_metric_for_scenario.value
            else:
                y1_metric_for_scenario = y1_metric
                y1 = y1_value
            scenario = _compute_dcf_scenario(
                scenario_name=name,
                fcff_y1=y1,
                fcff_y2=y2_metric.value if y2_metric is not None else None,
                fcff_y1_label=y1_label,
                fcff_y2_label=(f"Forward FCFF {y2_metric.period} [{y2_metric.source}]" if y2_metric else None),
                growth_rate=growth,
                wacc=wacc,
                terminal_growth=tg,
                total_debt=debt,
                cash=cash,
                diluted_shares=shares,
                current_price=current,
                base_year=base_year,
                fcff_y1_metric=y1_metric_for_scenario,
                fcff_y2_metric=y2_metric,
                growth_metric=growth_metric,
                growth_cap=growth_caps[name],
                net_debt_value=nd_metric.value,
                projection_as_of=(y1_metric_for_scenario.as_of if y1_metric_for_scenario else snapshot.current_price.as_of),
            )
            scenarios.append(scenario)
        except ValueError as exc:
            errors.append(str(exc))
            warnings.append(str(exc))

    # A composite may only consume a complete three-scenario DCF. A partial
    # DCF is therefore explicitly unavailable, even if one path succeeded.
    if len(scenarios) != 3:
        return ModelValuation(
            formula=FORMULA,
            formula_description="Five-year discounted FCFF model",
            inputs={},
            assumptions={"wacc_source": wacc_source},
            calculation_steps=[],
            dcf_scenarios=scenarios or None,
            available=False,
            unavailable_reason="Incomplete DCF scenarios: " + "; ".join(errors),
            warnings=list(dict.fromkeys(warnings)),
            data_quality=DataQuality.LOW,
        )

    # Ensure result ordering even when a caller supplies unusual scenario
    # assumptions (e.g. a base WACC above the configured bear WACC).
    sorted_scenarios = sorted(scenarios, key=lambda scenario: scenario.price_per_share)
    expected_names = ["bear", "base", "bull"]
    if [scenario.scenario for scenario in sorted_scenarios] != expected_names:
        warnings.append("DCF scenarios were ordered by resulting fair value to preserve bear <= base <= bull.")
        sorted_scenarios = [scenario.model_copy(update={"scenario": label}) for scenario, label in zip(sorted_scenarios, expected_names)]
    scenario_map = {scenario.scenario: scenario for scenario in sorted_scenarios}

    def estimate(scenario: DCFScenario) -> PriceEstimate:
        return PriceEstimate(
            price_per_share=scenario.price_per_share,
            upside_pct=scenario.upside_pct,
            premium_discount_pct=scenario.premium_discount_pct,
            intermediates={
                "enterprise_value": str(scenario.enterprise_value),
                "equity_value": str(scenario.equity_value),
                "net_debt": str(scenario.net_debt),
                "terminal_value": str(scenario.terminal_value),
                "pv_terminal_value": str(scenario.pv_terminal_value),
                "fcff_projections": [str(value) for value in scenario.fcff_projections],
                "pv_projections": [str(value) for value in scenario.pv_projections],
            },
        )

    input_metrics = {
        key: value
        for key, value in {
            "current_price": metric_dict(snapshot.current_price),
            "diluted_shares": metric_dict(snapshot.diluted_shares),
            "cash": metric_dict(snapshot.cash),
            "total_debt": metric_dict(snapshot.total_debt),
            "net_debt": metric_dict(nd_metric),
            "fcff_ttm": metric_dict(snapshot.fcff_ttm),
            "forward_fcff_1y": metric_dict(snapshot.forward_fcff_1y),
            "forward_fcff_2y": metric_dict(snapshot.forward_fcff_2y),
        }.items()
        if value is not None
    }
    assumption_metrics: dict[str, dict] = {}
    for label, value, source_type in (
        ("bear", wacc_sv.low, wacc_source_type),
        ("base", wacc_sv.base, wacc_source_type),
        ("bull", wacc_sv.high, wacc_source_type),
    ):
        assumption_metrics[f"wacc_{label}"] = metric_dict(FinancialMetric(
            value=value,
            unit="rate",
            period="valuation assumption",
            source=wacc_source_label,
            source_type=source_type,
            as_of=snapshot.current_price.as_of,
            confidence=1.0 if source_type == SourceType.USER_OVERRIDE else 0.8,
            is_estimated=source_type != SourceType.USER_OVERRIDE,
            notes=f"wacc_source={wacc_source}",
        )) or {}
    terminal_source_type = assumptions.dcf_terminal_growth_source
    terminal_source_label = assumptions.dcf_terminal_growth_source_label
    for label, value in (("bear", tg_sv.low), ("base", tg_sv.base), ("bull", tg_sv.high)):
        assumption_metrics[f"terminal_growth_{label}"] = metric_dict(FinancialMetric(
            value=value,
            unit="rate",
            period="valuation assumption",
            source=terminal_source_label,
            source_type=terminal_source_type,
            as_of=snapshot.current_price.as_of,
            confidence=1.0,
            is_estimated=terminal_source_type != SourceType.USER_OVERRIDE,
            notes=f"terminal growth cap={DCF_TERMINAL_GROWTH_MAX}",
        )) or {}
    for label, value in (("bear", growth_scenarios.low), ("base", growth_scenarios.base), ("bull", growth_scenarios.high)):
        if growth_metric is None:
            assumption_metrics[f"growth_{label}"] = {}
            continue
        cap = growth_caps[label]
        effective = growth_metric.model_copy(update={
            "value": value,
            "source": f"{growth_metric.source}; effective {label} FCFF growth",
            "notes": (
                f"Raw growth={growth_metric.value}; effective growth={value}; "
                f"floor={FCF_GROWTH_FLOOR}; cap={cap}; lineage={growth_metric.source}."
            ),
        })
        assumption_metrics[f"growth_{label}"] = metric_dict(effective) or {}

    steps = [
        "IMPORTANT: Uses FCFF (firm/unlevered FCF), NOT FCFE.",
        "Year 1 and Year 2 use explicit forward FCFF metrics when available; missing years are derived and labelled.",
        f"Growth lineage: {growth_label}; source_type={growth_source_type}",
        f"WACC lineage: {wacc_source}; {wacc_source_label}",
        f"Terminal growth (bear/base/bull) = {tg_sv.low}/{tg_sv.base}/{tg_sv.high}; max={DCF_TERMINAL_GROWTH_MAX}",
        f"Net debt = debt {debt} - cash {cash} = {nd_metric.value}",
        *[f"{scenario.scenario}: EV={scenario.enterprise_value}, PVTV={scenario.pv_terminal_value}, equity={scenario.equity_value}, price={scenario.price_per_share}" for scenario in sorted_scenarios],
    ]
    quality = DataQuality.LOW if snapshot.is_demo else DataQuality.MEDIUM
    return ModelValuation(
        formula=FORMULA,
        formula_description=(
            "Five-year FCFF DCF. PV_t = FCFF_t/(1+WACC)^t; TV = FCFF5×(1+g)/(WACC-g); "
            "PVTV = TV/(1+WACC)^5; EV = ΣPV + PVTV; equity = EV − debt + cash; price = equity/shares."
        ),
        inputs={
            "fcff_y1": str(scenario_map["bear"].fcff_projections[0]),
            "fcff_y1_label": y1_label,
            "fcff_y2": str(y2_metric.value) if y2_metric else None,
            "fcff_y2_label": f"Forward FCFF {y2_metric.period} [{y2_metric.source}]" if y2_metric else None,
            "fcf_type": "FCFF (firm/unlevered FCF — discounted at WACC, NOT FCFE)",
            "current_price": str(current),
            "diluted_shares": str(shares),
            "cash": str(cash),
            "total_debt": str(debt),
            "net_debt": str(nd_metric.value),
        },
        assumptions={
            "growth_source": growth_label,
            "growth_source_type": growth_source_type,
            "growth_bear": str(growth_scenarios.low),
            "growth_base": str(growth_scenarios.base),
            "growth_bull": str(growth_scenarios.high),
            "wacc_bear": str(wacc_sv.low),
            "wacc_base": str(wacc_sv.base),
            "wacc_bull": str(wacc_sv.high),
            "wacc_source": wacc_source,
            "wacc_source_type": wacc_source_type,
            "wacc_source_label": wacc_source_label,
            "terminal_growth_bear": str(tg_sv.low),
            "terminal_growth_base": str(tg_sv.base),
            "terminal_growth_bull": str(tg_sv.high),
            "terminal_growth_max": str(DCF_TERMINAL_GROWTH_MAX),
            "terminal_growth_source": terminal_source_type,
            "terminal_growth_source_label": terminal_source_label,
            "n_years": N_YEARS,
        },
        input_metrics=input_metrics,
        assumption_metrics=assumption_metrics,
        calculation_steps=steps,
        low=estimate(scenario_map["bear"]),
        base=estimate(scenario_map["base"]),
        high=estimate(scenario_map["bull"]),
        dcf_scenarios=sorted_scenarios,
        warnings=list(dict.fromkeys(warnings)),
        data_quality=quality,
    )
