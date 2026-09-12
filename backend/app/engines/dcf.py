"""Five-year FCFF DCF engine.

The engine never substitutes FCFE for FCFF. Forward FCFF1/FCFF2 are used as
the first two explicit forecast years; if they are missing, a historical TTM
value is grown into a newly-labelled forecast year for standalone/direct
callers. Years 3–5 use a deterministic linear fade from the effective
scenario growth start to that scenario's terminal growth, with each derived
projection carrying its own provenance metric; FCFF6 is exposed for the
terminal-value bridge.
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
    DEFAULT_GROWTH_CAP,
    DEFAULT_GROWTH_FLOOR,
)
from app.services.projections import calculate_ntm_weights
from app.models.domain import (
    CompanyFinancialSnapshot,
    DataQuality,
    DCFScenario,
    DCFSensitivityCell,
    DCFSensitivityMatrix,
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


def _cap_growth(value: Decimal, cap: Decimal, floor: Decimal = FCF_GROWTH_FLOOR) -> Decimal:
    return min(max(value, floor), cap)


def _ordered_growth(
    raw: Decimal,
    base_cap: Decimal = FCF_GROWTH_CAP_BASE,
    floor: Decimal = FCF_GROWTH_FLOOR,
) -> ScenarioValues:
    bear_cap = min(base_cap * Decimal("0.85"), base_cap)
    bull_cap = min(base_cap * Decimal("1.15"), Decimal("2.0"))
    values = [
        _cap_growth(raw * Decimal("0.85"), bear_cap, floor),
        _cap_growth(raw, base_cap, floor),
        _cap_growth(raw * Decimal("1.15"), bull_cap, floor),
    ]
    values.sort()
    return ScenarioValues(low=values[0], base=values[1], high=values[2])


def _growth_source(
    snapshot: CompanyFinancialSnapshot,
    override: Optional[ScenarioValues],
    growth_cap: Optional[Decimal] = None,
    growth_floor: Optional[Decimal] = None,
) -> tuple[ScenarioValues, str, str, Optional[FinancialMetric]]:
    """Resolve growth using FCFF-forward, analyst operational, historical, fallback order."""
    base_cap = growth_cap if growth_cap is not None and growth_cap != DEFAULT_GROWTH_CAP else FCF_GROWTH_CAP_BASE
    effective_floor = growth_floor if growth_floor is not None and growth_floor != DEFAULT_GROWTH_FLOOR else FCF_GROWTH_FLOOR
    bear_cap = min(base_cap * Decimal("0.85"), base_cap)
    bull_cap = min(base_cap * Decimal("1.15"), Decimal("2.0"))

    if override is not None:
        capped = ScenarioValues(
            low=_cap_growth(override.low, bear_cap, effective_floor),
            base=_cap_growth(override.base, base_cap, effective_floor),
            high=_cap_growth(override.high, bull_cap, effective_floor),
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
        return _ordered_growth(raw, base_cap, effective_floor), "derived from forward FCFF1→FCFF2 (capped)", "derived", metric

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
            return _ordered_growth(raw, base_cap, effective_floor), "derived from FCFF TTM→FCFF1 (capped)", "derived", metric

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
        return _ordered_growth(candidate.value, base_cap, effective_floor), f"derived from forward {label} (capped)", "derived", metric

    # Historical FCFF growth has explicit firm-cash-flow lineage and outranks
    # a historical revenue/EBITDA/EPS metric that could be unrelated to FCFF.
    if snapshot.fcff_growth is not None and snapshot.fcff_growth.value.is_finite():
        candidate = snapshot.fcff_growth
        metric = candidate.model_copy(update={
            "source": f"Historical FCFF growth: {candidate.source}",
            "source_type": SourceType.DERIVED,
            "notes": "Historical FCFF growth; FCFE growth is not used.",
        })
        return _ordered_growth(candidate.value, base_cap, effective_floor), "historical FCFF growth (capped)", "derived", metric

    # Last, use an explicitly historical operational proxy.  This branch is
    # intentionally after FCFF growth and never considers FCFE growth.
    for candidate, label in operational:
        if candidate is not None and candidate.value.is_finite():
            metric = candidate.model_copy(update={
                "source": f"Derived FCFF growth from historical {label}: {candidate.source}",
                "source_type": SourceType.DERIVED,
                "notes": f"Historical operational {label} proxy; FCFE growth is not used.",
            })
            return _ordered_growth(candidate.value, base_cap, effective_floor), f"derived from historical {label} (capped)", "derived", metric

    fallback = ScenarioValues(
        low=_cap_growth(DEFAULT_DCF_FCF_GROWTH_FALLBACK.low, bear_cap, effective_floor),
        base=_cap_growth(DEFAULT_DCF_FCF_GROWTH_FALLBACK.base, base_cap, effective_floor),
        high=_cap_growth(DEFAULT_DCF_FCF_GROWTH_FALLBACK.high, bull_cap, effective_floor),
    )

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
        if "TTM" in period.upper():
            return max(year + 1, as_of.year)
        if year < as_of.year:
            return as_of.year
        return year
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


def _calculate_dcf(
    projections: list[Decimal],
    year_fractions: list[Decimal],
    wacc: Decimal,
    terminal_growth: Decimal,
    net_debt: Decimal,
    diluted_shares: Decimal,
) -> tuple[list[Decimal], Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]:
    """
    Pure mathematical DCF calculation function using exact ACT/365 year fractions.
    Returns:
        (pvs, terminal_value, pv_terminal_value, enterprise_value, equity_value, price_per_share, tv_ratio)
    """
    if not wacc.is_finite() or not terminal_growth.is_finite() or wacc <= terminal_growth:
        raise ValueError(f"WACC ({wacc}) must be > terminal_growth ({terminal_growth})")
    one_plus_wacc = Decimal("1") + wacc
    ln_wacc = one_plus_wacc.ln()

    pvs: list[Decimal] = []
    for proj, frac in zip(projections, year_fractions):
        disc_factor = (frac * ln_wacc).exp()
        pv = (proj / disc_factor).quantize(PREC, ROUND_HALF_UP)
        pvs.append(pv)

    terminal_val = (
        projections[-1] * (Decimal("1") + terminal_growth) / (wacc - terminal_growth)
    ).quantize(PREC, ROUND_HALF_UP)

    tv_frac = year_fractions[-1]
    tv_disc_factor = (tv_frac * ln_wacc).exp()
    pv_tv = (terminal_val / tv_disc_factor).quantize(PREC, ROUND_HALF_UP)

    ev = (sum(pvs) + pv_tv).quantize(PREC, ROUND_HALF_UP)
    equity = ev - net_debt
    if equity <= ZERO:
        raise ValueError(f"Non-positive equity value ({equity})")

    price = (equity / diluted_shares).quantize(PREC, ROUND_HALF_UP)
    tv_ratio = (pv_tv / ev).quantize(FOUR, ROUND_HALF_UP) if ev > ZERO else ZERO
    return pvs, terminal_val, pv_tv, ev, equity, price, tv_ratio


def _fade_growth_rate(growth_start: Decimal, terminal_growth: Decimal, year: int) -> Decimal:
    """Return the contractual linear fade rate for forecast Years 3–5.

    Year 3 is one third of the way from the bounded/scenario growth start to
    terminal growth, Year 4 is two thirds, and Year 5 equals terminal growth
    exactly. Keeping this helper free of clamping is deliberate: the inputs
    have already passed the configured bounds, and the resulting path must
    support decreasing, increasing, equal, and negative rates without
    overshoot.
    """

    if year not in (3, 4, 5):
        raise ValueError(f"Linear DCF growth fade is defined only for years 3-5, got {year}")
    if year == 5:
        return terminal_growth
    return growth_start + (Decimal(str(year - 2)) / Decimal("3")) * (terminal_growth - growth_start)


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
    growth_floor: Optional[Decimal] = None,
    net_debt_value: Optional[Decimal] = None,
    projection_as_of: Optional[date] = None,
    growth_compound_horizon: Optional[str] = None,
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
    effective_floor = growth_floor if growth_floor is not None else FCF_GROWTH_FLOOR

    def _safe_date(y: int, m: int, d: int) -> date:
        try:
            return date(y, m, d)
        except ValueError:
            return date(y, m, 28)

    # Guarantee first_period never labels a past year as future
    first_period = fcff_y1_metric.period if fcff_y1_metric else f"FY{base_year}E"
    match_y = re.search(r"(?:FY)?(20\d{2})", first_period or "")
    if match_y and int(match_y.group(1)) < as_of.year:
        first_period = f"FY{as_of.year}E"

    start_dates: list[str] = []
    end_dates: list[str] = []
    year_fractions: list[Decimal] = []

    for yr in range(1, N_YEARS + 1):
        s_date = _safe_date(as_of.year + yr - 1, as_of.month, as_of.day)
        e_date = _safe_date(as_of.year + yr, as_of.month, as_of.day)
        start_dates.append(s_date.isoformat())
        end_dates.append(e_date.isoformat())
        days_elapsed = (e_date - as_of).days
        yf = (Decimal(str(days_elapsed)) / Decimal("365")).quantize(Decimal("0.00000001"), ROUND_HALF_UP)
        year_fractions.append(yf)


    projections: list[Decimal] = []
    projection_growth_rates: list[Optional[Decimal]] = []
    periods: list[str] = []
    metrics: list[dict] = []

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
                f"floor={effective_floor}; cap={cap}; lineage={growth_metric.source}."
            ),
        })
    growth_note = (
        f" Raw growth={growth_metric.value}; effective growth={growth_rate}; "
        f"floor={effective_floor}; cap={growth_cap}; lineage={growth_metric.source}."
        if growth_metric is not None
        else ""
    )
    for year in range(1, N_YEARS + 1):
        s_str = start_dates[year - 1]
        e_str = end_dates[year - 1]
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
                notes=f"FCFF Year 1 ({s_str} to {e_str}) supplied directly to DCF.",
            )
        elif year == 2 and fcff_y2 is not None:
            value = fcff_y2.quantize(PREC, ROUND_HALF_UP)
            y2_label_period = fcff_y2_metric.period if fcff_y2_metric else _forecast_period(first_period, as_of, 1)
            match_y2 = re.search(r"(?:FY)?(20\d{2})", y2_label_period or "")
            if match_y2 and int(match_y2.group(1)) < as_of.year:
                y2_label_period = _forecast_period(first_period, as_of, 1)
            metric = fcff_y2_metric or _projection_metric(
                value,
                period=y2_label_period,
                source=fcff_y2_label or "Forward FCFF Year 2",
                source_type=SourceType.DERIVED,
                as_of=as_of,
                confidence=0.5,
                is_estimated=True,
                notes=f"FCFF Year 2 ({s_str} to {e_str}) supplied directly to DCF.",
            )
        else:
            projection_growth = (
                growth_rate
                if year == 2
                else _fade_growth_rate(growth_rate, terminal_growth, year)
            )
            value = (previous * (Decimal("1") + projection_growth)).quantize(PREC, ROUND_HALF_UP)  # type: ignore[operator]
            proj_period = _forecast_period(first_period, as_of, year - 1)
            metric = _projection_metric(
                value,
                period=proj_period,
                source=f"Derived from prior FCFF projection × (1 + {projection_growth})",
                source_type=SourceType.DERIVED,
                as_of=as_of,
                confidence=(growth_metric.confidence if growth_metric else 1.0),
                is_estimated=True,
                notes=(
                    f"Deterministic FCFF projection for {s_str} ~ {e_str}; "
                    f"growth={projection_growth}; linear fade from g_start={growth_rate} "
                    f"to terminal g={terminal_growth} for Years 3-5; no FCFE substitution."
                    + growth_note
                ),
            )
        if year == 1:
            projection_growth = None
        elif year == 2 and fcff_y2 is not None:
            # An explicit Y2 estimate remains authoritative; expose its
            # observed one-year rate separately from the scenario g_start.
            projection_growth = (value / projections[0] - Decimal("1")) if projections else growth_rate
        elif year == 2:
            projection_growth = growth_rate
        if value <= ZERO:
            raise ValueError(f"DCF [{scenario_name}] produced non-positive FCFF in year {year}")
        projections.append(value)
        projection_growth_rates.append(projection_growth)
        periods.append(metric.period)
        metric_row = metric_dict(metric) or {}
        metric_row["growth_rate"] = str(projection_growth) if projection_growth is not None else None
        metric_row["growth_type"] = (
            "linear_terminal_fade"
            if year >= 3
            else ("explicit_forward" if year == 2 and fcff_y2 is not None else "growth_start")
        )
        metrics.append(metric_row)
        previous = value

    net_debt = net_debt_value if net_debt_value is not None else total_debt - cash
    fcff_year6 = projections[-1] * (Decimal("1") + terminal_growth)
    pvs, terminal_value, pv_terminal_value, enterprise_value, equity_value, price, _ = _calculate_dcf(
        projections, year_fractions, wacc, terminal_growth, net_debt, diluted_shares
    )

    # Keep PV provenance next to each projection so the API, frontend and
    # Markdown exporter can render the same values without reimplementing the
    # discounting math client-side.
    for index, metric_row in enumerate(metrics):
        metric_row["pv"] = metric_dict(_projection_metric(
            pvs[index],
            period=f"PV {periods[index]}",
            source=f"Discounted {periods[index]} FCFF at WACC={wacc}",
            source_type=SourceType.DERIVED,
            as_of=as_of,
            confidence=1.0,
            is_estimated=True,
            notes=f"PV = FCFF / (1 + WACC)^{year_fractions[index]:.8f} using ACT/365 day fraction.",
        )) or {}

    formulas = {
        "growth_fade": "g_t = g_start + ((t - 2) / 3) × (g_terminal - g_start), t=3..5; g_5=g_terminal",
        "pv_year": "PV_t = FCFF_t / (1 + WACC)^t (ACT/365 day-fraction)",
        "terminal_value": "TV = FCFF_5 × (1 + g) / (WACC - g)",
        "terminal_year_cash_flow": "FCFF_6 = FCFF_5 × (1 + terminal_growth)",
        "pv_terminal_value": "PVTV = TV / (1 + WACC)^t_5 (ACT/365 Year 5 fraction)",
        "enterprise_value": "EV = Σ(PV_1..PV_5) + PVTV",
        "equity_value": "Equity = EV - debt + cash = EV - net_debt",
        "price_per_share": "Price = Equity / diluted shares",
    }
    steps = [
        f"[{scenario_name}] FCFF projections ({', '.join(periods)}) = {projections}",
        f"[{scenario_name}] Linear growth fade: g_start={growth_rate}; g3={projection_growth_rates[2]}; g4={projection_growth_rates[3]}; g5={projection_growth_rates[4]} = terminal_growth={terminal_growth}",
        *[f"[{scenario_name}] PV year {year} (t={year_fractions[year - 1]:.4f}) = {projections[year - 1]} / (1 + {wacc})^{year_fractions[year - 1]:.4f} = {pvs[year - 1]}" for year in range(1, N_YEARS + 1)],
        f"[{scenario_name}] TV = {projections[-1]} × (1 + {terminal_growth}) / ({wacc} - {terminal_growth}) = {terminal_value}",
        f"[{scenario_name}] PVTV = {terminal_value} / (1 + {wacc})^{year_fractions[-1]:.4f} = {pv_terminal_value}",
        f"[{scenario_name}] EV = {sum(pvs)} + {pv_terminal_value} = {enterprise_value}",
        f"[{scenario_name}] Equity = {enterprise_value} - {total_debt} + {cash} = {equity_value}",
        f"[{scenario_name}] Price/share = {equity_value} / {diluted_shares} = {price}",
    ]
    compound_horizon = growth_compound_horizon or (
        f"From valuation as_of {as_of} to Year 1 end {end_dates[0]} (ACT/365 convention; annual end-of-year discounting: t1={year_fractions[0]:.4f}, t5={year_fractions[-1]:.4f})"
    )

    return DCFScenario(
        scenario=scenario_name,  # type: ignore[arg-type]
        wacc=wacc,
        terminal_growth=terminal_growth,
        growth_rate=growth_rate,
        growth_start=growth_rate,
        growth_fade_formula="g_t = g_start + ((t - 2) / 3) × (g_terminal - g_start), t=3..5; g_5=g_terminal",
        projection_growth_rates=projection_growth_rates,
        growth_metric=metric_dict(effective_growth_metric),
        growth_metric_raw=metric_dict(raw_growth_metric),
        growth_cap=growth_cap,
        growth_floor=effective_floor,
        fcff_year1=projections[0],
        fcff_projections=projections,
        fcff_year6=fcff_year6,
        projection_periods=periods,
        projection_metrics=metrics,
        pv_years=list(range(1, N_YEARS + 1)),
        year_fractions=year_fractions,
        period_start_dates=start_dates,
        period_end_dates=end_dates,
        growth_compound_horizon=compound_horizon,
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


def _calculate_wacc(snapshot: CompanyFinancialSnapshot) -> Decimal | None:
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


def _generate_sensitivity_matrix(
    base_scenario: DCFScenario,
) -> DCFSensitivityMatrix:
    base_wacc = base_scenario.wacc
    base_tg = base_scenario.terminal_growth
    wacc_step = Decimal("0.01")
    tg_step = Decimal("0.005")

    wacc_range = [
        base_wacc - wacc_step,
        base_wacc,
        base_wacc + wacc_step,
    ]
    tg_range = [
        base_tg - tg_step,
        base_tg,
        base_tg + tg_step,
    ]

    base_projections = base_scenario.fcff_projections
    growth_start = base_scenario.growth_start if base_scenario.growth_start is not None else base_scenario.growth_rate
    base_growth_rates = list(base_scenario.projection_growth_rates or [])
    year_fractions = base_scenario.year_fractions
    net_debt = base_scenario.net_debt
    diluted_shares = base_scenario.diluted_shares

    cells: list[list[DCFSensitivityCell]] = []
    for row_idx, wacc in enumerate(wacc_range):
        row: list[DCFSensitivityCell] = []
        for col_idx, tg in enumerate(tg_range):
            if wacc <= tg:
                row.append(
                    DCFSensitivityCell(
                        wacc=wacc,
                        terminal_growth=tg,
                        available=False,
                        unavailable_reason=f"WACC ({wacc}) must be greater than terminal growth ({tg})",
                    )
                )
                continue

            if tg > DCF_TERMINAL_GROWTH_MAX:
                row.append(
                    DCFSensitivityCell(
                        wacc=wacc,
                        terminal_growth=tg,
                        available=False,
                        unavailable_reason=(
                            f"terminal_growth ({tg}) exceeds configured max "
                            f"({DCF_TERMINAL_GROWTH_MAX})"
                        ),
                    )
                )
                continue

            # A sensitivity cell changes terminal growth, so its Years 3–5
            # trajectory must be rebuilt with the same g_start and the cell's
            # own terminal rate. Years 1–2 stay explicit and unchanged.
            projections = list(base_projections[:2])
            growth_rates: list[Optional[Decimal]] = list(base_growth_rates[:2])
            while len(growth_rates) < 2:
                growth_rates.append(None if len(growth_rates) == 0 else growth_start)
            for year in range(3, N_YEARS + 1):
                rate = _fade_growth_rate(growth_start, tg, year)
                value = (projections[-1] * (Decimal("1") + rate)).quantize(PREC, ROUND_HALF_UP)
                if value <= ZERO:
                    row.append(
                        DCFSensitivityCell(
                            wacc=wacc,
                            terminal_growth=tg,
                            available=False,
                            unavailable_reason=f"Sensitivity cell produced non-positive FCFF in year {year}",
                        )
                    )
                    projections = []
                    break
                projections.append(value)
                growth_rates.append(rate)
            if not projections:
                continue

            try:
                pvs, terminal_val, pv_tv, ev, equity, price, tv_ratio = _calculate_dcf(
                    projections, year_fractions, wacc, tg, net_debt, diluted_shares
                )
                row.append(
                    DCFSensitivityCell(
                        wacc=wacc,
                        terminal_growth=tg,
                        price_per_share=price,
                        enterprise_value=ev,
                        equity_value=equity,
                        tv_ratio=tv_ratio,
                        fcff_projections=projections,
                        fcff_year6=projections[-1] * (Decimal("1") + tg),
                        projection_growth_rates=growth_rates,
                        available=True,
                    )
                )
            except Exception as exc:
                row.append(
                    DCFSensitivityCell(
                        wacc=wacc,
                        terminal_growth=tg,
                        available=False,
                        unavailable_reason=str(exc),
                    )
                )
        cells.append(row)

    base_tv_ratio = (
        base_scenario.pv_terminal_value / base_scenario.enterprise_value
    ).quantize(FOUR, ROUND_HALF_UP) if base_scenario.enterprise_value > ZERO else ZERO

    tv_warning: Optional[str] = None
    if base_tv_ratio > Decimal("0.80"):
        tv_warning = "high_tv_dependence_strong"
    elif base_tv_ratio > Decimal("0.70"):
        tv_warning = "high_tv_dependence_moderate"

    return DCFSensitivityMatrix(
        wacc_range=wacc_range,
        terminal_growth_range=tg_range,
        cells=cells,
        base_tv_ratio=base_tv_ratio,
        tv_dependence_warning=tv_warning,
    )


def run_dcf(snapshot: CompanyFinancialSnapshot, assumptions: ValuationAssumptions) -> ModelValuation:
    warnings: list[str] = []
    current = snapshot.current_price.value
    shares = snapshot.diluted_shares.value
    if current <= ZERO:
        return ModelValuation(formula=FORMULA, formula_description="Five-year FCFF DCF", inputs={}, assumptions={}, calculation_steps=[], available=False, unavailable_reason="Current quote must be positive", data_quality=DataQuality.LOW)
    if shares <= ZERO:
        return ModelValuation(formula=FORMULA, formula_description="Five-year FCFF DCF", inputs={}, assumptions={}, calculation_steps=[], available=False, unavailable_reason="Diluted shares must be positive", data_quality=DataQuality.LOW)
    if getattr(snapshot, "shares_basis", None) == "CONFLICT_DEGRADED":
        return ModelValuation(
            formula=FORMULA,
            formula_description="Five-year FCFF DCF",
            inputs={},
            assumptions={},
            calculation_steps=[],
            available=False,
            unavailable_reason="Share capital reconciliation conflict: severe divergence across share classes/sources; model fails closed to prevent erroneous price targets.",
            warnings=["Diluted share count is in CONFLICT_DEGRADED state; per-share valuation model is unavailable."],
            data_quality=DataQuality.LOW,
        )
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

    raw_cap = getattr(assumptions, "growth_cap", None)
    req_growth_cap = raw_cap if raw_cap is not None and raw_cap != DEFAULT_GROWTH_CAP else FCF_GROWTH_CAP_BASE
    raw_floor = getattr(assumptions, "growth_floor", None)
    req_growth_floor = raw_floor if raw_floor is not None and raw_floor != DEFAULT_GROWTH_FLOOR else FCF_GROWTH_FLOOR
    growth_scenarios, growth_label, growth_source_type, growth_metric = _growth_source(
        snapshot, assumptions.dcf_fcf_growth, growth_cap=req_growth_cap, growth_floor=req_growth_floor
    )


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

    val_date = snapshot.current_price.as_of

    def _safe_date(y: int, m: int, d: int) -> date:
        try:
            return date(y, m, d)
        except ValueError:
            return date(y, m, 28)

    y1_end_date = _safe_date(val_date.year + 1, val_date.month, val_date.day)

    match_fwd = re.search(r"(?:FY)?(20\d{2})", y1_metric.period if y1_metric else "")
    is_mismatched_forward_fy = False
    fy_end = None
    if y1_metric is not None and match_fwd and "NTM" not in (y1_metric.period or "").upper():
        fy_year = int(match_fwd.group(1))
        fy_end = getattr(snapshot, "forecast_fiscal_year_end", None) or _safe_date(fy_year, 12, 31)
        days_to_fy_end = (fy_end - val_date).days
        # If less than 330 days remain in this fiscal year (e.g. 112 days when val_date is in September),
        # it is a discrete fiscal year that does not cover the full upcoming 12-month anniversary window.
        if days_to_fy_end < 330:
            is_mismatched_forward_fy = True

    y1_value: Optional[Decimal] = None
    y1_label: str = ""
    first_period: str = ""
    base_year: int = val_date.year

    if y1_metric is not None and not is_mismatched_forward_fy:
        y1_value = y1_metric.value
        y1_label = f"Forward FCFF {y1_metric.period} [{y1_metric.source}]"
        first_period = y1_metric.period
        base_year = _year_from_period(first_period, y1_metric.as_of)
    elif y1_metric is not None and is_mismatched_forward_fy:
        if y2_metric is not None and fy_end is not None:
            w0, w1, _, _ = calculate_ntm_weights(val_date, fy_end)
            y1_blended = (w0 * y1_metric.value + w1 * y2_metric.value).quantize(PREC, ROUND_HALF_UP)
            y1_value = y1_blended
            y1_label = f"NTM blended forward FCFF ({w0:.1%} {y1_metric.period} + {w1:.1%} {y2_metric.period})"
            first_period = f"NTM (w0={w0:.2f}, w1={w1:.2f})"
            base_year = val_date.year
            warnings.append(f"Discrete fiscal year {y1_metric.period} blended with {y2_metric.period} into NTM anniversary cash flow.")
        elif ttm_metric is not None:
            y1_value = None
            y1_label = f"Historical proxy (derived from FCFF TTM [{ttm_metric.source}])"
            first_period = f"Anniversary Year 1 ({val_date} to {y1_end_date})"
            base_year = val_date.year
            warnings.append(
                f"Forward FCFF {y1_metric.period} is a discrete fiscal year without +2y estimate for NTM blending; "
                f"fell back to historical FCFF proxy compounded over {(y1_end_date - ttm_metric.as_of).days} days to anniversary Year 1."
            )
        else:
            return ModelValuation(
                formula=FORMULA,
                formula_description="Five-year discounted FCFF model",
                inputs={},
                assumptions={},
                calculation_steps=[],
                available=False,
                unavailable_reason=(
                    f"Forward FCFF estimate {y1_metric.period} represents a discrete fiscal year ending {fy_end}, "
                    f"which does not match the DCF anniversary horizon ending {y1_end_date}. "
                    f"Without a +2y estimate for NTM blending or a historical FCFF proxy, anniversary cash flow cannot be constructed without blind relabeling."
                ),
                warnings=warnings,
                data_quality=DataQuality.LOW,
            )
    else:
        y1_value = None
        y1_label = f"Derived from FCFF TTM [{ttm_metric.source}]"  # type: ignore[union-attr]
        first_period = _forecast_period(ttm_metric.period, val_date)  # type: ignore[union-attr]
        base_year = _year_from_period(first_period, val_date)  # type: ignore[union-attr]
        warnings.append(f"FCFF TTM used only as historical base; Year 1 is derived as {first_period}.")

    scenarios: list[DCFScenario] = []
    errors: list[str] = []
    growth_caps = {
        "bear": min(req_growth_cap * Decimal("0.85"), req_growth_cap),
        "base": req_growth_cap,
        "bull": min(req_growth_cap * Decimal("1.15"), Decimal("2.0")),
    }
    for name, wacc, tg, growth in params:
        try:
            horizon_desc = None
            if y1_value is None:
                base_date = ttm_metric.as_of  # type: ignore[union-attr]
                elapsed_days = (y1_end_date - base_date).days
                if elapsed_days <= 0:
                    elapsed_days = 365
                dt = Decimal(str(elapsed_days)) / Decimal("365")
                one_plus_g = Decimal("1") + growth
                if one_plus_g > ZERO:
                    compound_factor = (dt * one_plus_g.ln()).exp()
                else:
                    compound_factor = one_plus_g
                y1 = (ttm_metric.value * compound_factor).quantize(PREC, ROUND_HALF_UP)  # type: ignore[union-attr]
                horizon_desc = (
                    f"From historical base {base_date} to Year 1 end {y1_end_date} "
                    f"({elapsed_days} days = {dt:.2f} years; ACT/365 compound factor = {compound_factor:.4f})"
                )
                y1_metric_for_scenario = _projection_metric(
                    y1,
                    period=first_period,
                    source=f"Derived from historical FCFF {ttm_metric.period} × (1 + {growth})^{dt:.2f}",  # type: ignore[union-attr]
                    source_type=SourceType.DERIVED,
                    as_of=val_date,
                    confidence=ttm_metric.confidence,  # type: ignore[union-attr]
                    is_estimated=True,
                    notes=f"Forecast Y1 derived with ACT/365 compounding over {elapsed_days} days.",
                )
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
                growth_floor=req_growth_floor,
                net_debt_value=nd_metric.value,
                projection_as_of=val_date,
                growth_compound_horizon=horizon_desc,
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
                "projection_growth_rates": [
                    str(value) if value is not None else None
                    for value in scenario.projection_growth_rates
                ],
                "growth_start": str(scenario.growth_start) if scenario.growth_start is not None else None,
                "growth_fade_formula": scenario.growth_fade_formula,
                "fcff_year6": str(scenario.fcff_year6) if scenario.fcff_year6 is not None else None,
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

    base_scenario = scenario_map["base"]
    sensitivity_mat = _generate_sensitivity_matrix(base_scenario)
    if sensitivity_mat.tv_dependence_warning == "high_tv_dependence_strong":
        warnings.append(
            f"DCF Terminal Value accounts for {(sensitivity_mat.base_tv_ratio * Decimal('100')).quantize(Decimal('0.1'))}% of Enterprise Value (>80%). High sensitivity to terminal assumptions."
        )
    elif sensitivity_mat.tv_dependence_warning == "high_tv_dependence_moderate":
        warnings.append(
            f"DCF Terminal Value accounts for {(sensitivity_mat.base_tv_ratio * Decimal('100')).quantize(Decimal('0.1'))}% of Enterprise Value (>70%). Moderate sensitivity to terminal assumptions."
        )

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
            "growth_start_bear": str(scenario_map["bear"].growth_start),
            "growth_start_base": str(scenario_map["base"].growth_start),
            "growth_start_bull": str(scenario_map["bull"].growth_start),
            "growth_fade_formula": scenario_map["base"].growth_fade_formula,
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
        sensitivity_matrix=sensitivity_mat,
        warnings=list(dict.fromkeys(warnings)),
        data_quality=quality,
    )
