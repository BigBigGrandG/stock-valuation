"""Five-year FCFF DCF engine.

The engine never substitutes FCFE for FCFF. Forward FCFF1/FCFF2 are used as
the first two explicit forecast years; with a provider fiscal-year anchor,
FY1 uses aligned full-year FCFF minus actual fiscal-YTD FCFF when available,
and FY2+ are complete fiscal years. Legacy fixture/direct callers without a
YTD contract retain the compatibility day-ratio schedule.
When the explicit inputs are missing, a historical TTM value is grown into a
newly-labelled forecast year for standalone/direct callers. Years 3–5 use a
deterministic linear fade from the effective scenario growth start to that
scenario's terminal growth, with each derived projection carrying its own
provenance metric; FCFF6 is exposed for the terminal-value bridge.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
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
from app.engines.terminal_governance import apply_terminal_governance

PREC = Decimal("0.01")
FOUR = Decimal("0.0001")
EIGHT = Decimal("0.00000001")
ZERO = Decimal("0")
N_YEARS = 5
FORMULA = (
    "EV = Σ FCFF_t/(1+WACC)^t + TV/(1+WACC)^t_5; "
    "t = (fiscal period end − valuation date)/365; "
    "Equity = EV − Net Debt; Price = Equity/Shares"
)


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


def _safe_add_years(value: date, years: int) -> date:
    """Add calendar years without losing a leap-day valuation date."""

    try:
        return value.replace(year=value.year + years)
    except ValueError:
        # February 29 has no anniversary in a non-leap year.  February 28 is
        # the same convention used by the projection service and provider.
        return value.replace(year=value.year + years, day=28)


def _fiscal_year_bounds(
    fiscal_year_end: date,
    slot: int,
    fiscal_year_start: Optional[date] = None,
) -> tuple[date, date]:
    """Return the inclusive fiscal-year dates for a forecast slot.

    ``forecast_fiscal_year_end`` is the provider-verified end of FY1. When a
    provider also supplies an exact FY1 start (for example, a 52/53-week
    fiscal year), that start is used for slot 1; otherwise a prior matching
    end-date anniversary is used. This handles non-December year ends and
    leap years without assuming every fiscal year has 365 days.
    """

    end = _safe_add_years(fiscal_year_end, slot - 1)
    if slot == 1 and fiscal_year_start is not None:
        return fiscal_year_start, end
    # Derive both endpoints from the original anchor.  Computing the prior
    # end from ``end`` would turn a leap-day anchor (2028-02-29) into
    # 2028-02-28 for the following period and overlap one day.
    previous_end = _safe_add_years(fiscal_year_end, slot - 2)
    return previous_end + timedelta(days=1), end


def _build_projection_schedule(
    as_of: date,
    *,
    first_period: str,
    base_year: int,
    fiscal_year_end: Optional[date] = None,
    fiscal_year_start: Optional[date] = None,
) -> tuple[list[str], list[str], list[Decimal], list[Decimal], list[bool], list[int]]:
    """Build the DCF cash-flow timeline and its audit metadata.

    When a fiscal-year anchor is supplied, the first forecast is the portion
    of FY1 remaining after the valuation date.  If aligned actual fiscal-YTD
    FCFF is supplied, its cash flow is the full-year forecast less that actual;
    otherwise the legacy compatibility path prorates by remaining fiscal-year
    days.  Later forecasts are complete, non-overlapping fiscal years. Discount
    times are measured
    from the valuation date to each fiscal period end using ACT/365.

    The no-anchor branch intentionally retains the historical direct-helper
    anniversary schedule.  Production callers have a provider fiscal anchor;
    retaining this compatibility seam prevents a bare unit-level helper call
    from silently inventing a fiscal calendar.

    Returns ``(starts, ends, discount_times, proration_factors, is_stub,
    fiscal_year_days)``.  Date strings are used here because they are the
    stable wire representation in the DCF response.
    """

    starts: list[str] = []
    ends: list[str] = []
    discount_times: list[Decimal] = []
    proration_factors: list[Decimal] = []
    is_stub: list[bool] = []
    fiscal_year_days: list[int] = []

    for slot in range(1, N_YEARS + 1):
        if fiscal_year_end is None:
            full_start = _safe_add_years(as_of, slot - 1)
            end = _safe_add_years(as_of, slot)
            start = full_start
            factor = Decimal("1")
            stub = False
            fy_days = (end - full_start).days + 1
        else:
            full_start, end = _fiscal_year_bounds(
                fiscal_year_end,
                slot,
                fiscal_year_start=fiscal_year_start,
            )
            if end <= as_of:
                raise ValueError(
                    f"DCF fiscal period {slot} ends on {end}, not after valuation date {as_of}"
                )
            # The valuation date is the effective start of an in-progress FY1
            # stub.  For a valuation before the FY begins, no proration is
            # necessary and the period starts at the actual fiscal start.
            start = max(as_of, full_start) if slot == 1 else full_start
            # ``full_start`` and ``end`` are inclusive fiscal dates.  The
            # denominator therefore includes both endpoints (and naturally
            # becomes 366 for a leap fiscal year).
            fy_days = (end - full_start).days + 1
            if slot == 1 and as_of > full_start:
                remaining_days = (end - as_of).days
                factor = (
                    Decimal(str(max(0, remaining_days))) / Decimal(str(fy_days))
                    if fy_days > 0
                    else ZERO
                )
                factor = min(max(factor, ZERO), Decimal("1"))
                stub = factor < Decimal("1")
            else:
                factor = Decimal("1")
                stub = False

        days_to_end = (end - as_of).days
        if days_to_end <= 0:
            raise ValueError(
                f"DCF fiscal period {slot} has no positive discount horizon from {as_of}"
            )
        starts.append(start.isoformat())
        ends.append(end.isoformat())
        discount_times.append(
            (Decimal(str(days_to_end)) / Decimal("365")).quantize(EIGHT, ROUND_HALF_UP)
        )
        proration_factors.append(factor.quantize(EIGHT, ROUND_HALF_UP))
        is_stub.append(stub)
        fiscal_year_days.append(fy_days)

    return starts, ends, discount_times, proration_factors, is_stub, fiscal_year_days


def _discount_factor(discount_time: Decimal, wacc: Decimal) -> Decimal:
    """Return ACT/365 discount factor using deterministic Decimal math."""

    return ((discount_time * (Decimal("1") + wacc).ln()).exp())


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


def _fiscal_ytd_metric(snapshot: CompanyFinancialSnapshot) -> Optional[FinancialMetric]:
    """Return the canonical FY1 actual, accepting additive compatibility aliases."""

    for field_name in ("fiscal_ytd_fcff", "fiscal_ytd_fcff_actual", "ytd_fcff_actual"):
        metric = getattr(snapshot, field_name, None)
        if metric is not None:
            return metric
    return None


def _fiscal_ytd_contract_required(
    snapshot: CompanyFinancialSnapshot,
    metric: Optional[FinancialMetric],
) -> bool:
    """Detect provider/direct callers that explicitly claim a YTD contract."""

    return bool(
        metric is not None
        or getattr(snapshot, "fiscal_ytd_required", None)
        or getattr(snapshot, "fiscal_ytd_status", None) is not None
        or getattr(snapshot, "fiscal_ytd_unavailable_reason", None)
        or any(
            getattr(snapshot, field_name, None) is not None
            for field_name in (
                "fiscal_ytd_start",
                "fiscal_ytd_end",
                "fiscal_ytd_prior_fiscal_year_end",
                "fiscal_ytd_fiscal_year_end",
            )
        )
    )


def _validate_fiscal_ytd_contract(
    snapshot: CompanyFinancialSnapshot,
    metric: Optional[FinancialMetric],
    *,
    valuation_date: date,
    fiscal_year_end: date,
    full_year_metric: FinancialMetric,
) -> tuple[Optional[FinancialMetric], Optional[str]]:
    """Validate actual FY1 coverage before subtracting it from the full year."""

    status = getattr(snapshot, "fiscal_ytd_status", None)
    if status is not None and str(status).strip().lower() != "available":
        return None, str(
            getattr(snapshot, "fiscal_ytd_unavailable_reason", None)
            or f"provider fiscal YTD status is {status!r}, not available"
        )
    if metric is None:
        reason = getattr(snapshot, "fiscal_ytd_unavailable_reason", None) or (
            "aligned actual FCFF YTD through the valuation date is missing"
        )
        return None, str(reason)
    if not metric.value.is_finite():
        return None, "actual FCFF YTD is non-finite"
    if metric.source_type not in ({SourceType.ACTUAL, SourceType.FIXTURE} if snapshot.is_demo else {SourceType.ACTUAL}):
        return None, f"actual FCFF YTD source_type={metric.source_type} is not actual"
    if metric.source_type != SourceType.FIXTURE and metric.is_estimated:
        return None, "actual FCFF YTD is marked estimated"
    period = str(metric.period or "").strip().upper()
    source_notes = f"{metric.source} {metric.notes or ''}".upper()
    if "FCFE" in f"{period} {source_notes}":
        return None, "actual candidate is FCFE, not FCFF"
    if any(token in f"{period} {source_notes}" for token in ("NTM", "TTM")):
        return None, f"actual FCFF YTD period/source is not FCFF YTD ({metric.period})"
    if "YTD" not in period:
        return None, f"actual FCFF metric period is not YTD ({metric.period})"
    if f"{fiscal_year_end.year}" not in period:
        return None, (
            f"actual FCFF YTD period {metric.period} does not match fiscal year ending {fiscal_year_end}"
        )
    expected_unit = str(full_year_metric.unit or snapshot.currency).strip().upper()
    actual_unit = str(metric.unit or "").strip().upper()
    if not actual_unit or actual_unit != expected_unit:
        return None, f"actual FCFF YTD unit {metric.unit!r} does not match full-year FCFF unit {full_year_metric.unit!r}"
    if metric.as_of > valuation_date:
        return None, f"actual FCFF YTD as_of {metric.as_of} is after valuation date {valuation_date}"

    prior_fiscal_end = getattr(snapshot, "fiscal_ytd_prior_fiscal_year_end", None)
    if prior_fiscal_end is not None and prior_fiscal_end >= fiscal_year_end:
        return None, (
            f"actual FCFF YTD prior fiscal anchor {prior_fiscal_end} is not before DCF FY1 end {fiscal_year_end}"
        )
    supplied_start = getattr(snapshot, "fiscal_ytd_start", None)
    supplied_end = getattr(snapshot, "fiscal_ytd_end", None)
    supplied_fiscal_end = getattr(snapshot, "fiscal_ytd_fiscal_year_end", None)
    missing_coverage = [
        field_name
        for field_name, value in (
            ("fiscal_ytd_start", supplied_start),
            ("fiscal_ytd_end", supplied_end),
            ("fiscal_ytd_fiscal_year_end", supplied_fiscal_end),
        )
        if value is None
    ]
    if missing_coverage:
        return None, (
            "explicit actual FCFF YTD coverage is required; missing "
            + ", ".join(missing_coverage)
            + "; metric.as_of and forecast fiscal-year dates cannot substitute coverage"
        )
    expected_start = (
        prior_fiscal_end + timedelta(days=1)
        if prior_fiscal_end is not None
        else _fiscal_year_bounds(fiscal_year_end, 1)[0]
    )
    actual_start = supplied_start
    actual_end = supplied_end
    actual_fiscal_end = supplied_fiscal_end
    if actual_fiscal_end != fiscal_year_end:
        return None, (
            f"actual FCFF YTD fiscal anchor {actual_fiscal_end} does not match DCF FY1 end {fiscal_year_end}"
        )
    if actual_start != expected_start:
        return None, f"actual FCFF YTD starts {actual_start}, expected fiscal start {expected_start}"
    if actual_end != valuation_date:
        return None, (
            f"actual FCFF YTD ends {actual_end}, but valuation date is {valuation_date}; "
            "the uncovered interval cannot be filled by day-ratio proration"
        )
    return metric, None


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
    pvs: list[Decimal] = []
    for proj, frac in zip(projections, year_fractions):
        disc_factor = _discount_factor(frac, wacc)
        pv = (proj / disc_factor).quantize(PREC, ROUND_HALF_UP)
        pvs.append(pv)

    terminal_val = (
        projections[-1] * (Decimal("1") + terminal_growth) / (wacc - terminal_growth)
    ).quantize(PREC, ROUND_HALF_UP)

    tv_frac = year_fractions[-1]
    tv_disc_factor = _discount_factor(tv_frac, wacc)
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
    fiscal_year_end: Optional[date] = None,
    forecast_fiscal_year_end: Optional[date] = None,
    fiscal_year_start: Optional[date] = None,
    fiscal_ytd_fcff: Optional[FinancialMetric] = None,
) -> DCFScenario:
    """Compute one path using explicit five-year PV math.

    ``fiscal_year_end`` (or its descriptive alias
    ``forecast_fiscal_year_end``) is the provider-verified FY1 end.  With an
    anchor, FY1 uses full-year minus actual fiscal-YTD FCFF when that contract
    is supplied; otherwise it uses the legacy compatibility proration when the
    valuation date falls inside that year. No-anchor direct calls retain the
    legacy anniversary schedule.
    """

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

    # Guarantee first_period never labels a past year as future
    first_period = fcff_y1_metric.period if fcff_y1_metric else f"FY{base_year}E"
    match_y = re.search(r"(?:FY)?(20\d{2})", first_period or "")
    if match_y and int(match_y.group(1)) < as_of.year:
        first_period = f"FY{as_of.year}E"

    effective_fiscal_year_end = fiscal_year_end or forecast_fiscal_year_end
    (
        start_dates,
        end_dates,
        year_fractions,
        proration_factors,
        period_is_stub,
        fiscal_year_days,
    ) = _build_projection_schedule(
        as_of,
        first_period=first_period,
        base_year=base_year,
        fiscal_year_end=effective_fiscal_year_end,
        fiscal_year_start=fiscal_year_start,
    )

    projections: list[Decimal] = []
    projection_growth_rates: list[Optional[Decimal]] = []
    periods: list[str] = []
    metrics: list[dict] = []
    projection_stub_basis: list[str] = [
        "full_year_forecast_minus_actual_ytd" if period_is_stub[0] and fiscal_ytd_fcff is not None else (
            "day_ratio_compatibility" if period_is_stub[0] else "full_year_forecast"
        ),
        *["full_year_forecast" for _ in range(N_YEARS - 1)],
    ]

    previous: Optional[Decimal] = None
    # Keep the unprorated FY1 value available for deriving a full FY2 when a
    # provider did not supply the second explicit year.  Starting FY2 from a
    # short FY1 stub would compound only a fraction of an annual cash flow.
    full_fcff_y1 = fcff_y1.quantize(PREC, ROUND_HALF_UP)
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
            full_value = full_fcff_y1
            if period_is_stub[0] and fiscal_ytd_fcff is not None:
                value = (full_value - fiscal_ytd_fcff.value).quantize(PREC, ROUND_HALF_UP)
                # The schedule's day fraction remains the discount-time basis,
                # not a cash-flow scaling factor.  Expose 1.0 so consumers do
                # not mistake the actual bridge for uniform day proration.
                proration_factors[0] = Decimal("1.00000000")
            else:
                value = (full_value * proration_factors[0]).quantize(PREC, ROUND_HALF_UP)
            metric = fcff_y1_metric or _projection_metric(
                full_value,
                period=first_period,
                source=fcff_y1_label,
                source_type=SourceType.DERIVED,
                as_of=as_of,
                confidence=0.5,
                is_estimated=True,
                notes=f"FCFF Year 1 ({s_str} to {e_str}) supplied directly to DCF.",
            )
            if period_is_stub[0] and fiscal_ytd_fcff is not None:
                original_notes = metric.notes or ""
                metric = metric.model_copy(update={
                    "value": value,
                    "source": f"{metric.source}; full FY forecast minus actual FCFF YTD",
                    "source_type": SourceType.DERIVED,
                    "is_estimated": True,
                    "confidence": min(metric.confidence, fiscal_ytd_fcff.confidence),
                    "notes": (
                        f"FY1 full-year FCFF={full_value}; actual FCFF YTD={fiscal_ytd_fcff.value}; "
                        f"remaining FY1 stub={value}; no day-ratio fallback. "
                        f"Coverage {getattr(fiscal_ytd_fcff, 'as_of', as_of)} through {e_str}. "
                        f"{original_notes}"
                    ).strip(),
                })
            elif period_is_stub[0]:
                original_notes = metric.notes or ""
                metric = metric.model_copy(update={
                    "value": value,
                    "source": f"{metric.source}; prorated FY1 stub",
                    "notes": (
                        f"FY1 full-year FCFF={full_value}; prorated to {value} using "
                        f"{max(0, int((Decimal(str(fiscal_year_days[0])) * proration_factors[0]).to_integral_value(rounding=ROUND_HALF_UP)))} "
                        f"of {fiscal_year_days[0]} fiscal days remaining ({proration_factors[0]}). "
                        f"Period {s_str} to {e_str}. {original_notes}"
                    ).strip(),
                })
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
            growth_base = (
                full_fcff_y1
                if year == 2 and period_is_stub[0]
                else previous
            )
            value = (growth_base * (Decimal("1") + projection_growth)).quantize(PREC, ROUND_HALF_UP)  # type: ignore[operator]
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
            # observed one-year rate separately from the scenario g_start.  A
            # prorated FY1 is not a valid denominator for an annual rate.
            projection_growth = (value / full_fcff_y1 - Decimal("1")) if full_fcff_y1 else growth_rate
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
        metric_row["period_start"] = s_str
        metric_row["period_end"] = e_str
        # ``start_date``/``end_date`` are retained as explicit aliases for
        # consumers that use the provider's bridge vocabulary.
        metric_row["start_date"] = s_str
        metric_row["end_date"] = e_str
        metric_row["discount_time"] = str(year_fractions[year - 1])
        metric_row["t"] = str(year_fractions[year - 1])
        metric_row["proration_factor"] = str(proration_factors[year - 1])
        metric_row["stub_cashflow_basis"] = projection_stub_basis[year - 1]
        if year == 1 and fiscal_ytd_fcff is not None:
            metric_row["fiscal_ytd_actual"] = metric_dict(fiscal_ytd_fcff)
        metric_row["is_stub"] = period_is_stub[year - 1]
        metric_row["fiscal_year_days"] = fiscal_year_days[year - 1]
        metrics.append(metric_row)
        previous = value

    net_debt = net_debt_value if net_debt_value is not None else total_debt - cash
    fcff_year6 = projections[-1] * (Decimal("1") + terminal_growth)
    pvs, terminal_value, pv_terminal_value, enterprise_value, equity_value, price, _ = _calculate_dcf(
        projections, year_fractions, wacc, terminal_growth, net_debt, diluted_shares
    )
    discount_factors = [
        _discount_factor(discount_time, wacc).quantize(EIGHT, ROUND_HALF_UP)
        for discount_time in year_fractions
    ]

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
            notes=(
                f"PV = FCFF / discount factor; t={year_fractions[index]:.8f}; "
                f"discount factor={discount_factors[index]:.8f}; "
                "ACT/365 day fraction from valuation date to fiscal period end."
            ),
        )) or {}
        metric_row["discount_factor"] = str(discount_factors[index])
        metric_row["pv_value"] = str(pvs[index])

    formulas = {
        "growth_fade": "g_t = g_start + ((t - 2) / 3) × (g_terminal - g_start), t=3..5; g_5=g_terminal",
        "stub_cashflow": (
            "FCFF_1,stub = FCFF_1,full − FCFF_actual_YTD"
            if fiscal_ytd_fcff is not None and period_is_stub[0]
            else "FCFF_1,stub = FCFF_1,full × remaining fiscal-year days / fiscal-year days"
        ),
        "stub_proration": (
            "Not applied: FY1 stub is full-year FCFF minus aligned actual FCFF YTD"
            if fiscal_ytd_fcff is not None and period_is_stub[0]
            else "FCFF_1,stub = FCFF_1,full × remaining fiscal-year days / fiscal-year days"
        ),
        "discount_time": "t = (fiscal period end − valuation date) / 365 (ACT/365)",
        "discount_factor": "DF_t = (1 + WACC)^t = exp(t × ln(1 + WACC))",
        "pv_year": "PV_t = FCFF_t / DF_t; DF_t=(1+WACC)^t (ACT/365 day-fraction)",
        "terminal_value": "TV = FCFF_5 × (1 + g) / (WACC - g)",
        "terminal_year_cash_flow": "FCFF_6 = FCFF_5 × (1 + terminal_growth)",
        "pv_terminal_value": "PVTV = TV / DF_t5; t5=(terminal period end − valuation date)/365",
        "enterprise_value": "EV = Σ(PV_1..PV_5) + PVTV",
        "equity_value": "Equity = EV - debt + cash = EV - net_debt",
        "price_per_share": "Price = Equity / diluted shares",
    }
    steps = [
        f"[{scenario_name}] FCFF projections ({', '.join(periods)}) = {projections}",
        *[
            f"[{scenario_name}] Fiscal period {year}: {start_dates[year - 1]} to {end_dates[year - 1]}"
            f"; proration={proration_factors[year - 1]}"
            f"; stub_cashflow_basis={projection_stub_basis[year - 1]}"
            f"; stub={period_is_stub[year - 1]}"
            for year in range(1, N_YEARS + 1)
        ],
        f"[{scenario_name}] Linear growth fade: g_start={growth_rate}; g3={projection_growth_rates[2]}; g4={projection_growth_rates[3]}; g5={projection_growth_rates[4]} = terminal_growth={terminal_growth}",
        *[
            f"[{scenario_name}] PV year {year} (t={year_fractions[year - 1]:.8f}; "
            f"factor={discount_factors[year - 1]:.8f}) = {projections[year - 1]} / "
            f"{discount_factors[year - 1]} = {pvs[year - 1]}"
            for year in range(1, N_YEARS + 1)
        ],
        f"[{scenario_name}] TV = {projections[-1]} × (1 + {terminal_growth}) / ({wacc} - {terminal_growth}) = {terminal_value}",
        f"[{scenario_name}] PVTV at {end_dates[-1]} (t={year_fractions[-1]:.8f}; factor={discount_factors[-1]:.8f}) = {terminal_value} / {discount_factors[-1]} = {pv_terminal_value}",
        f"[{scenario_name}] EV = {sum(pvs)} + {pv_terminal_value} = {enterprise_value}",
        f"[{scenario_name}] Equity = {enterprise_value} - {total_debt} + {cash} = {equity_value}",
        f"[{scenario_name}] Price/share = {equity_value} / {diluted_shares} = {price}",
    ]
    compound_horizon = growth_compound_horizon or (
        f"Fiscal-year DCF timeline from valuation date {as_of}; "
        f"FY1 end={end_dates[0]} (t1={year_fractions[0]:.8f}), "
        f"terminal FY5 end={end_dates[-1]} (t5={year_fractions[-1]:.8f}); ACT/365"
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
        projection_proration_factors=proration_factors,
        period_is_stub=period_is_stub,
        discount_times=year_fractions,
        projection_discount_times=year_fractions,
        discount_factors=discount_factors,
        projection_discount_factors=discount_factors,
        fiscal_year_days=fiscal_year_days,
        terminal_period_end_date=end_dates[-1],
        terminal_discount_time=year_fractions[-1],
        terminal_discount_factor=discount_factors[-1],
        growth_compound_horizon=compound_horizon,
        projection_stub_basis=projection_stub_basis,
        fiscal_ytd_actual=metric_dict(fiscal_ytd_fcff),
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
    period_start_dates = base_scenario.period_start_dates
    period_end_dates = base_scenario.period_end_dates
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
                discount_factors = [
                    _discount_factor(discount_time, wacc).quantize(EIGHT, ROUND_HALF_UP)
                    for discount_time in year_fractions
                ]
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
                        year_fractions=year_fractions,
                        discount_times=year_fractions,
                        discount_factors=discount_factors,
                        period_start_dates=period_start_dates,
                        period_end_dates=period_end_dates,
                        pv_projections=pvs,
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
    y1_end_date = _safe_add_years(val_date, 1)

    # ``forecast_fiscal_year_end`` is the provider's verified end of the
    # current forward fiscal year.  It is the sole anchor for production DCF
    # timing.  A concrete FY2026E-style metric can safely use the calendar
    # year only when no upstream anchor exists; relative labels remain on the
    # legacy direct-call path because they have no date evidence of their own.
    provider_fiscal_end = getattr(snapshot, "forecast_fiscal_year_end", None)
    timeline_fiscal_end: Optional[date] = None
    y1_value: Optional[Decimal] = None
    y1_label: str = ""
    first_period: str = ""
    base_year: int = val_date.year

    if y1_metric is not None:
        y1_period = str(y1_metric.period or "")
        upper_y1_period = y1_period.upper().strip()
        explicit_y1_match = re.search(r"(?:FY)?(20\d{2})", y1_period)
        explicit_y1_year = int(explicit_y1_match.group(1)) if explicit_y1_match else None

        if provider_fiscal_end is not None and any(token in upper_y1_period for token in ("NTM", "TTM")):
            return ModelValuation(
                formula=FORMULA,
                formula_description="Five-year discounted FCFF model",
                inputs={},
                assumptions={},
                calculation_steps=[],
                available=False,
                unavailable_reason=(
                    f"Forward FCFF period {y1_period} is a rolling/non-annual metric; "
                    "a provider-anchored fiscal-year DCF requires a full FY1 estimate "
                    "before constructing the remaining-period stub."
                ),
                warnings=warnings,
                data_quality=DataQuality.LOW,
            )

        if provider_fiscal_end is not None:
            if explicit_y1_year is not None and explicit_y1_year != provider_fiscal_end.year:
                return ModelValuation(
                    formula=FORMULA,
                    formula_description="Five-year discounted FCFF model",
                    inputs={},
                    assumptions={},
                    calculation_steps=[],
                    available=False,
                    unavailable_reason=(
                        f"Forward FCFF period {y1_period} does not match provider fiscal anchor "
                        f"FY{provider_fiscal_end.year} ending {provider_fiscal_end}."
                    ),
                    warnings=warnings,
                    data_quality=DataQuality.LOW,
                )
            timeline_fiscal_end = provider_fiscal_end
        elif explicit_y1_year is not None and "NTM" not in upper_y1_period and "TTM" not in upper_y1_period:
            # Concrete fiscal years are self-anchored to calendar year end;
            # this fallback is only for direct callers without provider
            # metadata, never for relative 0y/+1y labels.
            timeline_fiscal_end = date(explicit_y1_year, 12, 31)

        y1_value = y1_metric.value
        y1_label = f"Forward FCFF {y1_metric.period} [{y1_metric.source}]"
        first_period = y1_metric.period
        base_year = _year_from_period(first_period, y1_metric.as_of)
    else:
        y1_value = None
        y1_label = f"Derived from FCFF TTM [{ttm_metric.source}]"  # type: ignore[union-attr]
        first_period = _forecast_period(ttm_metric.period, val_date)  # type: ignore[union-attr]
        base_year = _year_from_period(first_period, val_date)  # type: ignore[union-attr]
        warnings.append(f"FCFF TTM used only as historical base; Year 1 is derived as {first_period}.")

    # Validate a supplied FY2 label against the same fiscal anchor.  A
    # mismatched second year would otherwise make the growth rate and the
    # non-overlapping fiscal timeline disagree silently.
    if y2_metric is not None and timeline_fiscal_end is not None:
        y2_period = str(y2_metric.period or "")
        y2_match = re.search(r"(?:FY)?(20\d{2})", y2_period)
        if y2_match and int(y2_match.group(1)) != timeline_fiscal_end.year + 1:
            return ModelValuation(
                formula=FORMULA,
                formula_description="Five-year discounted FCFF model",
                inputs={},
                assumptions={},
                calculation_steps=[],
                available=False,
                unavailable_reason=(
                    f"Forward FCFF period {y2_period} does not match provider fiscal anchor "
                    f"FY{timeline_fiscal_end.year + 1} for DCF Year 2."
                ),
                warnings=warnings,
                data_quality=DataQuality.LOW,
            )

    fiscal_ytd_metric = _fiscal_ytd_metric(snapshot)
    fiscal_ytd_used: Optional[FinancialMetric] = None
    if timeline_fiscal_end is not None:
        fy1_end = _fiscal_year_bounds(timeline_fiscal_end, 1)[1]
        fy1_start = getattr(snapshot, "fiscal_ytd_start", None) or _fiscal_year_bounds(timeline_fiscal_end, 1)[0]
        if val_date > fy1_start:
            remaining_days = (fy1_end - val_date).days
            fiscal_days = (fy1_end - fy1_start).days + 1
            ytd_required = _fiscal_ytd_contract_required(snapshot, fiscal_ytd_metric)
            if ytd_required:
                fiscal_ytd_used, ytd_reason = _validate_fiscal_ytd_contract(
                    snapshot,
                    fiscal_ytd_metric,
                    valuation_date=val_date,
                    fiscal_year_end=fy1_end,
                    full_year_metric=y1_metric or ttm_metric,  # type: ignore[arg-type]
                )
                if fiscal_ytd_used is None:
                    return ModelValuation(
                        formula=FORMULA,
                        formula_description="Five-year discounted FCFF model",
                        inputs={
                            "forward_fcff_1y": metric_dict(y1_metric),
                            "fiscal_ytd_fcff": metric_dict(fiscal_ytd_metric),
                        },
                        assumptions={
                            "timeline_basis": "fiscal_year_end",
                            "fiscal_ytd_status": getattr(snapshot, "fiscal_ytd_status", None),
                        },
                        calculation_steps=[],
                        available=False,
                        unavailable_reason=(
                            "DCF FY1 stub requires aligned actual FCFF YTD through the valuation date: "
                            f"{ytd_reason}"
                        ),
                        warnings=warnings,
                        data_quality=DataQuality.LOW,
                    )
                warnings.append(
                    f"DCF FY1 uses full-year FCFF {y1_metric.value if y1_metric else None} minus actual FCFF YTD "
                    f"{fiscal_ytd_used.value} for coverage {getattr(snapshot, 'fiscal_ytd_start', fy1_start)}..{val_date}; "
                    "uniform day-ratio proration is not applied."
                )
            else:
                if not snapshot.is_demo:
                    return ModelValuation(
                        formula=FORMULA,
                        formula_description="Five-year discounted FCFF model",
                        inputs={
                            "forward_fcff_1y": metric_dict(y1_metric),
                            "fiscal_ytd_fcff": metric_dict(fiscal_ytd_metric),
                        },
                        assumptions={
                            "timeline_basis": "fiscal_year_end",
                            "fiscal_ytd_status": getattr(snapshot, "fiscal_ytd_status", None),
                        },
                        calculation_steps=[],
                        available=False,
                        unavailable_reason=(
                            "Live DCF FY1 stub requires aligned actual FCFF YTD through the valuation date; "
                            "provider fiscal-YTD coverage is absent, so no day-ratio fallback is permitted"
                        ),
                        warnings=warnings,
                        data_quality=DataQuality.LOW,
                    )
                warnings.append(
                    f"DCF FY1 uses a compatibility day-ratio stub from {val_date} to {fy1_end}; "
                    f"full-year FCFF is prorated by {remaining_days}/{fiscal_days}. "
                    "No provider fiscal-YTD contract was supplied."
                )
        elif fiscal_ytd_metric is not None or _fiscal_ytd_contract_required(snapshot, fiscal_ytd_metric):
            # At fiscal start no stub exists, but an explicit malformed YTD
            # payload must not be silently accepted as actual company data.
            if fiscal_ytd_metric is not None:
                _, ytd_reason = _validate_fiscal_ytd_contract(
                    snapshot,
                    fiscal_ytd_metric,
                    valuation_date=val_date,
                    fiscal_year_end=fy1_end,
                    full_year_metric=y1_metric or ttm_metric,  # type: ignore[arg-type]
                )
                if ytd_reason:
                    warnings.append(f"FY1 begins at fiscal start; YTD payload ignored after validation failure: {ytd_reason}")
    elif fiscal_ytd_metric is not None or _fiscal_ytd_contract_required(snapshot, fiscal_ytd_metric):
        return ModelValuation(
            formula=FORMULA,
            formula_description="Five-year discounted FCFF model",
            inputs={
                "forward_fcff_1y": metric_dict(y1_metric),
                "fiscal_ytd_fcff": metric_dict(fiscal_ytd_metric),
            },
            assumptions={},
            calculation_steps=[],
            available=False,
            unavailable_reason=(
                "Fiscal-YTD FCFF contract was supplied but no verified FY1 fiscal-year anchor is available"
            ),
            warnings=warnings,
            data_quality=DataQuality.LOW,
        )

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
                fiscal_year_end=timeline_fiscal_end,
                fiscal_year_start=fy1_start if fiscal_ytd_used is not None else None,
                fiscal_ytd_fcff=fiscal_ytd_used,
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
                "period_start_dates": list(scenario.period_start_dates),
                "period_end_dates": list(scenario.period_end_dates),
                "discount_times": [str(value) for value in scenario.discount_times],
                "discount_factors": [str(value) for value in scenario.discount_factors],
                "proration_factors": [str(value) for value in scenario.projection_proration_factors],
                "stub_cashflow_basis": list(scenario.projection_stub_basis),
                "fiscal_ytd_actual": scenario.fiscal_ytd_actual,
                "terminal_period_end_date": scenario.terminal_period_end_date,
                "terminal_discount_time": str(scenario.terminal_discount_time) if scenario.terminal_discount_time is not None else None,
                "terminal_discount_factor": str(scenario.terminal_discount_factor) if scenario.terminal_discount_factor is not None else None,
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
            "fiscal_ytd_fcff": metric_dict(fiscal_ytd_used),
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
        (
            f"DCF timeline basis: fiscal FY1 end {timeline_fiscal_end} from valuation date {val_date}; "
            + (
                "FY1 is full-year FCFF minus aligned actual FCFF YTD when valuation is inside the fiscal year."
                if fiscal_ytd_used is not None
                else "FY1 is a remaining-period compatibility stub when no fiscal-YTD contract is supplied."
            )
            if timeline_fiscal_end is not None
            else "DCF timeline basis: anniversary compatibility schedule (no provider fiscal-year anchor)."
        ),
        "Year 1 and Year 2 use explicit forward FCFF metrics when available; missing years are derived and labelled.",
        f"Growth lineage: {growth_label}; source_type={growth_source_type}",
        f"WACC lineage: {wacc_source}; {wacc_source_label}",
        f"Terminal growth (bear/base/bull) = {tg_sv.low}/{tg_sv.base}/{tg_sv.high}; max={DCF_TERMINAL_GROWTH_MAX}",
        f"Net debt = debt {debt} - cash {cash} = {nd_metric.value}",
        *[f"{scenario.scenario}: EV={scenario.enterprise_value}, PVTV={scenario.pv_terminal_value}, equity={scenario.equity_value}, price={scenario.price_per_share}" for scenario in sorted_scenarios],
    ]
    quality = DataQuality.LOW if snapshot.is_demo else DataQuality.MEDIUM
    result = ModelValuation(
        formula=FORMULA,
        formula_description=(
            "Five-year FCFF DCF. PV_t = FCFF_t/DF_t; DF_t=(1+WACC)^t with "
            "t=(fiscal period end−valuation date)/365; TV = FCFF5×(1+g)/(WACC-g); "
            "PVTV = TV/DF_t5 at the actual terminal fiscal period end; EV = ΣPV + PVTV; "
            "equity = EV − debt + cash; price = equity/shares."
        ),
        inputs={
            "fcff_y1": str(scenario_map["bear"].fcff_projections[0]),
            "fcff_y1_full_year": str(y1_metric.value) if y1_metric is not None else None,
            "fcff_y1_label": y1_label,
            "fcff_y2": str(y2_metric.value) if y2_metric else None,
            "fcff_y2_label": f"Forward FCFF {y2_metric.period} [{y2_metric.source}]" if y2_metric else None,
            "fiscal_ytd_fcff": metric_dict(fiscal_ytd_used),
            "stub_cashflow_basis": (
                "full_year_minus_actual_ytd" if fiscal_ytd_used is not None else "day_ratio_compatibility"
            ),
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
            "timeline_basis": "fiscal_year_end" if timeline_fiscal_end is not None else "anniversary_compatibility",
            "valuation_date": val_date.isoformat(),
            "forecast_fiscal_year_end": timeline_fiscal_end.isoformat() if timeline_fiscal_end is not None else None,
            "terminal_period_end_date": base_scenario.terminal_period_end_date,
            "terminal_discount_time": str(base_scenario.terminal_discount_time),
            "terminal_discount_factor": str(base_scenario.terminal_discount_factor),
            "fiscal_ytd_status": getattr(snapshot, "fiscal_ytd_status", None),
            "fiscal_ytd_start": (
                getattr(snapshot, "fiscal_ytd_start", None).isoformat()
                if getattr(snapshot, "fiscal_ytd_start", None) is not None else None
            ),
            "fiscal_ytd_prior_fiscal_year_end": (
                getattr(snapshot, "fiscal_ytd_prior_fiscal_year_end", None).isoformat()
                if getattr(snapshot, "fiscal_ytd_prior_fiscal_year_end", None) is not None else None
            ),
            "fiscal_ytd_end": (
                getattr(snapshot, "fiscal_ytd_end", None).isoformat()
                if getattr(snapshot, "fiscal_ytd_end", None) is not None else None
            ),
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
    return apply_terminal_governance(result, snapshot, assumptions)
