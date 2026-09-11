"""Request-scoped financial projection and consensus horizon interpolation module.

Decouples raw upstream provider data from request-scoped assumptions.
Calculates:
1. Exact bounded day-weighted NTM blends (w0, w1 in [0, 1]) for EPS and Revenue across fiscal years.
2. Request-scoped growth clamping with user-configured growth_floor and growth_cap.
3. Derived forward EBITDA, FCF, and FCFF without mutating global snapshot or provider cache.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from app.models.domain import (
    CompanyFinancialSnapshot,
    FinancialMetric,
    SourceType,
    ValuationAssumptions,
)


@dataclass(frozen=True)
class RequestProjections:
    effective_horizon: str
    horizon_weight_fy1: Decimal
    horizon_weight_fy2: Decimal
    forward_eps: Optional[FinancialMetric]
    forward_revenue: Optional[FinancialMetric]
    forward_ebitda: Optional[FinancialMetric]
    forward_fcfe_1y: Optional[FinancialMetric]
    forward_fcff_1y: Optional[FinancialMetric]
    forward_fcff_2y: Optional[FinancialMetric]
    effective_growth_floor: Decimal
    effective_growth_cap: Decimal
    fallback_warning: Optional[str]
    financial_bridge: Optional[dict[str, Any]] = None
    dcf_fcff_1y: Optional[FinancialMetric] = None
    dcf_fcff_2y: Optional[FinancialMetric] = None


def _is_leap_year(y: int) -> bool:
    return calendar.isleap(y)


def _safe_add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return date(d.year + years, d.month, 28)


def _period_year(period: object) -> Optional[int]:
    """Return the explicit fiscal year embedded in a metric period, if any."""

    match = re.search(r"FY(20\d{2})", str(period or "").upper())
    return int(match.group(1)) if match else None


def _is_explicit_fy_metric(metric: Optional[FinancialMetric], slot: int, forecast_fy_end: Optional[date]) -> bool:
    """Require a verifiable annual period before using a metric in DCF Y1/Y2."""

    if metric is None:
        return False
    period = str(metric.period or "").upper().strip()
    if "NTM" in period or "TTM" in period:
        return False

    # Relative provider labels (0y/+1y, forward_1y/2y, FY1E/FY2E) carry no
    # calendar anchor by themselves.  They become verifiable only when the
    # provider also supplied the next fiscal-year end.  This branch must run
    # before the explicit ``FY`` prefix check because the live provider uses
    # 0y/+1y for annual consensus rows.
    relative_slot = {
        "0Y": 1,
        "FORWARD_1Y": 1,
        "FY1E": 1,
        "+1Y": 2,
        "1Y": 2,
        "FORWARD_2Y": 2,
        "FY2E": 2,
    }.get(period)
    if relative_slot is not None:
        if relative_slot != slot or forecast_fy_end is None:
            return False
        explicit_year = forecast_fy_end.year + slot - 1
    else:
        # Only full-fiscal-year labels with an embedded year are accepted as
        # self-anchored annual periods; do not broaden this to arbitrary text.
        if not period.startswith("FY"):
            return False
        explicit_year = _period_year(period)
        if explicit_year is None:
            return False
    if forecast_fy_end is not None:
        expected_year = forecast_fy_end.year + slot - 1
        if explicit_year != expected_year:
            return False
    return True


def _periods_compatible(left: Optional[FinancialMetric], right: Optional[FinancialMetric]) -> bool:
    """Only scale a historical driver when its reporting period matches revenue."""

    if left is None or right is None:
        return False
    left_period = str(left.period or "").upper().strip()
    right_period = str(right.period or "").upper().strip()
    if left_period == right_period:
        return True
    if left_period.startswith("TTM") and right_period.startswith("TTM"):
        return True
    left_year = _period_year(left_period)
    right_year = _period_year(right_period)
    return left_year is not None and left_year == right_year


def _fiscal_year_bounds(
    metric: Optional[FinancialMetric],
    slot: int,
    forecast_fy_end: Optional[date],
) -> tuple[Optional[date], Optional[date]]:
    """Resolve a full-FY date range from provider metadata without guessing."""

    if not _is_explicit_fy_metric(metric, slot, forecast_fy_end):
        return None, None
    if forecast_fy_end is not None:
        end = _safe_add_years(forecast_fy_end, slot - 1)
    else:
        year = _period_year(metric.period if metric is not None else None)
        if year is None:
            return None, None
        end = date(year, 12, 31)
    start = _safe_add_years(end, -1) + timedelta(days=1)
    return start, end


def calculate_ntm_weights(
    as_of: date,
    next_fy_end: Optional[date],
) -> tuple[Decimal, Decimal, int, int]:
    """
    Calculate bounded NTM day weights w0 (current FY) and w1 (next FY).
    w0 + w1 = 1.0; 0 <= w0 <= 1.0; 0 <= w1 <= 1.0.
    """
    if next_fy_end is None:
        return Decimal("1.0"), Decimal("0.0"), 365, 365

    if next_fy_end <= as_of:
        # If next fiscal year end is in the past, current FY has expired: 100% weight on next FY
        return Decimal("0.0"), Decimal("1.0"), 0, 365

    # Determine fiscal year length
    # If the target fiscal year ends in month m, day d, previous fiscal year end was ~1 year prior
    prev_fy_year = next_fy_end.year - 1
    try:
        prev_fy_end = date(prev_fy_year, next_fy_end.month, next_fy_end.day)
    except ValueError:
        prev_fy_end = date(prev_fy_year, next_fy_end.month, 28)

    fy_length = (next_fy_end - prev_fy_end).days
    if fy_length <= 0 or fy_length > 375:
        fy_length = 366 if _is_leap_year(next_fy_end.year) else 365

    remaining_days = (next_fy_end - as_of).days
    # Clamp remaining days to [0, fy_length] to guarantee bounded weights
    clamped_days = max(0, min(remaining_days, fy_length))

    w0 = (Decimal(str(clamped_days)) / Decimal(str(fy_length))).quantize(Decimal("0.0001"), ROUND_HALF_UP)
    w0 = max(Decimal("0.0"), min(Decimal("1.0"), w0))
    w1 = Decimal("1.0") - w0

    return w0, w1, clamped_days, fy_length


def derive_request_projections(
    snapshot: CompanyFinancialSnapshot,
    assumptions: ValuationAssumptions,
) -> RequestProjections:
    """
    Derive request-scoped forward metrics and projections with configured growth bounds
    and consensus horizon without modifying the input snapshot.
    """
    as_of = getattr(snapshot, "as_of", None) or (snapshot.current_price.as_of if getattr(snapshot, "current_price", None) else date.today())
    horizon = getattr(assumptions, "forecast_horizon", "ntm") or "ntm"
    growth_floor = getattr(assumptions, "growth_floor", Decimal("-0.20"))
    growth_cap = getattr(assumptions, "growth_cap", Decimal("0.40"))

    def clamp(g: Decimal) -> Decimal:
        return min(max(g, growth_floor), growth_cap)

    # Calculate NTM day weights
    next_fy_end = getattr(snapshot, "forecast_fiscal_year_end", None) or getattr(snapshot, "next_fiscal_year_end", None)
    w0, w1, remaining_days, fy_len = calculate_ntm_weights(as_of, next_fy_end)

    effective_horizon = horizon
    fallback_warning: Optional[str] = None

    # Forward EPS resolution
    fy1_eps = getattr(snapshot, "forward_eps_1y", None) or getattr(snapshot, "forward_eps", None)
    fy2_eps = getattr(snapshot, "forward_eps_2y", None) or getattr(snapshot, "forward_eps_next_fy", None)

    blended_eps: Optional[FinancialMetric] = None
    if horizon == "current_fy":
        blended_eps = fy1_eps
    elif horizon == "next_fy":
        if fy2_eps is not None and fy2_eps.value.is_finite():
            blended_eps = fy2_eps
        else:
            blended_eps = fy1_eps
            effective_horizon = "current_fy"
            fallback_warning = "Next FY (+2y) EPS estimate unavailable; fell back to current FY"
    elif horizon == "ntm":
        if fy1_eps is not None and fy2_eps is not None and fy1_eps.value.is_finite() and fy2_eps.value.is_finite():
            # Interpolate NTM EPS
            blended_val = (w0 * fy1_eps.value + w1 * fy2_eps.value).quantize(Decimal("0.01"), ROUND_HALF_UP)
            blended_eps = FinancialMetric(
                value=blended_val,
                unit="USD",
                period=f"NTM (w0={w0:.2f}, w1={w1:.2f})",
                source=f"NTM day-weighted blend: {w0:.1%} FY1 ({fy1_eps.value}) + {w1:.1%} FY2 ({fy2_eps.value})",
                source_type=SourceType.DERIVED,
                as_of=as_of,
                confidence=min(fy1_eps.confidence, fy2_eps.confidence),
                is_estimated=True,
                notes=f"Calculated from {remaining_days}/{fy_len} remaining days in fiscal year",
            )
        elif fy1_eps is not None:
            blended_eps = fy1_eps
            effective_horizon = "current_fy"
            fallback_warning = "NTM interpolation unavailable (missing +2y estimate); fell back to current FY"

    # Forward Revenue resolution.  A trailing TTM amount is a base input, not
    # an explicit FY1 estimate; keeping it out of ``fy1_rev`` prevents the
    # DCF path from relabelling NTM/TTM revenue as FY1E.
    fy1_rev = getattr(snapshot, "revenue_estimate_1y", None)
    fy2_rev = getattr(snapshot, "revenue_estimate_2y", None)
    raw_forward_revenue = getattr(snapshot, "forward_revenue", None)
    if fy1_rev is None and _is_explicit_fy_metric(raw_forward_revenue, 1, next_fy_end):
        fy1_rev = raw_forward_revenue
    blended_rev: Optional[FinancialMetric] = None
    if horizon == "current_fy":
        blended_rev = fy1_rev
    elif horizon == "next_fy":
        blended_rev = fy2_rev
    elif horizon == "ntm":
        if fy1_rev is not None and fy2_rev is not None and fy1_rev.value.is_finite() and fy2_rev.value.is_finite():
            blended_r_val = (w0 * fy1_rev.value + w1 * fy2_rev.value).quantize(Decimal("1"), ROUND_HALF_UP)
            blended_rev = FinancialMetric(
                value=blended_r_val,
                unit="USD",
                period=f"NTM (w0={w0:.2f}, w1={w1:.2f})",
                source=f"NTM day-weighted revenue: {w0:.1%} FY1 + {w1:.1%} FY2",
                source_type=SourceType.DERIVED,
                as_of=as_of,
                confidence=min(fy1_rev.confidence, fy2_rev.confidence),
                is_estimated=True,
                notes=f"Calculated from {remaining_days}/{fy_len} remaining days in fiscal year",
            )
        elif fy1_rev is not None:
            blended_rev = fy1_rev
        elif raw_forward_revenue is not None and str(raw_forward_revenue.period or "").upper().startswith("NTM"):
            blended_rev = raw_forward_revenue

    # With no independently forecast revenue, NTM can still be estimated from
    # an explicitly sourced historical revenue growth rate.  This is an NTM
    # bridge only; it is never exposed as FY1E/FY2E for DCF.
    if blended_rev is None and horizon == "ntm":
        base_revenue = getattr(snapshot, "revenue_ttm", None)
        raw_revenue_growth = getattr(snapshot, "revenue_growth", None)
        if (
            base_revenue is not None
            and base_revenue.value > Decimal("0")
            and raw_revenue_growth is not None
            and raw_revenue_growth.value.is_finite()
        ):
            effective_revenue_growth = clamp(raw_revenue_growth.value)
            derived_revenue = (
                base_revenue.value * (Decimal("1") + effective_revenue_growth)
            ).quantize(Decimal("1"), ROUND_HALF_UP)
            blended_rev = FinancialMetric(
                value=derived_revenue,
                unit=base_revenue.unit,
                period="NTM",
                source=f"Derived NTM revenue: {base_revenue.value} × (1 + {effective_revenue_growth})",
                source_type=SourceType.DERIVED,
                as_of=as_of,
                confidence=min(base_revenue.confidence, raw_revenue_growth.confidence),
                is_estimated=True,
                notes=(
                    f"Historical revenue growth continuation; raw={raw_revenue_growth.value}, "
                    f"effective={effective_revenue_growth}; not an explicit FY1 estimate."
                ),
            )

    # ------------------------------------------------------------------
    # Forward Financial Drivers & Auditable Bridge (Issue 01 remediation)
    # Bridge:
    # 1. EBITDA = Forecast Revenue * EBITDA Margin
    # 2. EBIT = EBITDA - D&A
    # 3. NOPAT = EBIT * (1 - TaxRate)
    # 4. FCFF = NOPAT + D&A - CapEx - ΔNWC
    # 5. FCFE = FCFF - Interest * (1 - TaxRate) + NetBorrowing
    # ------------------------------------------------------------------

    # Resolve Forecast Revenue
    fwd_rev_val: Optional[Decimal] = None
    if blended_rev is not None and blended_rev.value > Decimal("0"):
        fwd_rev_val = blended_rev.value
    elif fy1_rev is not None and fy1_rev.value > Decimal("0"):
        fwd_rev_val = fy1_rev.value
    elif raw_forward_revenue is not None and raw_forward_revenue.value > Decimal("0") and horizon == "ntm":
        fwd_rev_val = raw_forward_revenue.value

    # Resolve EBITDA Margin
    base_ebitda = getattr(snapshot, "ebitda_ttm", None) or getattr(snapshot, "ebitda", None)
    raw_forward_ebitda = getattr(snapshot, "forward_ebitda_1y", None) or getattr(snapshot, "forward_ebitda", None)

    is_ebitda_consensus = (
        raw_forward_ebitda is not None
        and getattr(raw_forward_ebitda, "source_type", None) == SourceType.ANALYST_ESTIMATE
    )

    has_forward_revenue_est = (
        getattr(snapshot, "revenue_estimate_1y", None) is not None
        or getattr(snapshot, "revenue_estimate_2y", None) is not None
        or getattr(snapshot, "forward_revenue", None) is not None
    )

    has_driver_overrides_ebitda = getattr(assumptions, "driver_ebitda_margin", None) is not None

    ebitda_margin: Optional[Decimal] = None
    ebitda_margin_source = "derived_historical"
    ebitda_margin_as_of = getattr(snapshot, "income_statement_as_of", None) or as_of
    ebitda_margin_period = getattr(getattr(snapshot, "revenue_ttm", None), "period", "TTM")

    if has_driver_overrides_ebitda:
        ebitda_margin = assumptions.driver_ebitda_margin
        ebitda_margin_source = "user_override"
        ebitda_margin_period = "user_override"
        ebitda_margin_as_of = as_of
    elif is_ebitda_consensus and fwd_rev_val is not None and fwd_rev_val > Decimal("0"):
        # Direct analyst consensus EBITDA: margin is implied from consensus EBITDA / forward revenue
        ebitda_margin = (raw_forward_ebitda.value / fwd_rev_val).quantize(Decimal("0.0001"), ROUND_HALF_UP)
        ebitda_margin_source = "analyst_estimate"
        ebitda_margin_as_of = raw_forward_ebitda.as_of
        ebitda_margin_period = raw_forward_ebitda.period
    elif base_ebitda is not None and getattr(snapshot, "revenue_ttm", None) is not None and snapshot.revenue_ttm.value > Decimal("0"):
        ebitda_margin = (base_ebitda.value / snapshot.revenue_ttm.value).quantize(Decimal("0.0001"), ROUND_HALF_UP)
        ebitda_margin_source = "derived_historical"
    elif raw_forward_ebitda is not None and fwd_rev_val is not None and fwd_rev_val > Decimal("0"):
        ebitda_margin = (raw_forward_ebitda.value / fwd_rev_val).quantize(Decimal("0.0001"), ROUND_HALF_UP)
        ebitda_margin_source = "derived_historical"

    target_metric_period = (
        blended_rev.period
        if blended_rev is not None and str(blended_rev.period or "").upper().startswith(("FY", "NTM"))
        else ("FY1E" if horizon == "current_fy" else ("FY2E" if horizon == "next_fy" else "NTM"))
    )

    # Derive forward EBITDA (EBITDA = Revenue * EBITDA Margin; no base*(1+g) extrapolation)
    derived_ebitda: Optional[FinancialMetric] = None
    if is_ebitda_consensus and not has_driver_overrides_ebitda:
        derived_ebitda = raw_forward_ebitda
    elif fwd_rev_val is not None and ebitda_margin is not None:
        calc_ebitda_val = (fwd_rev_val * ebitda_margin).quantize(Decimal("1"), ROUND_HALF_UP)
        derived_ebitda = FinancialMetric(
            value=calc_ebitda_val,
            unit=getattr(snapshot, "currency", "USD") or "USD",
            period=target_metric_period,
            source=f"Financial driver bridge: Revenue ({fwd_rev_val}) × EBITDA Margin ({ebitda_margin:.2%})",
            source_type=SourceType.USER_OVERRIDE if has_driver_overrides_ebitda else SourceType.DERIVED,
            as_of=as_of,
            confidence=0.85,
            is_estimated=True,
            notes=f"EBITDA margin source: {ebitda_margin_source}",
        )

    # Resolve D&A
    da_val: Optional[Decimal] = None
    da_source: Optional[str] = None
    da_as_of: Any = getattr(snapshot, "income_statement_as_of", None) or getattr(snapshot, "cash_flow_as_of", None) or as_of
    da_period_str: str = getattr(getattr(snapshot, "da_ttm", None), "period", "TTM")
    if getattr(assumptions, "driver_da", None) is not None:
        da_val = assumptions.driver_da
        da_source = "user_override"
        da_period_str = "user_override"
        da_as_of = as_of
    elif getattr(assumptions, "driver_da_ratio", None) is not None and fwd_rev_val is not None:
        da_ratio = assumptions.driver_da_ratio
        da_val = (fwd_rev_val * da_ratio).quantize(Decimal("1"), ROUND_HALF_UP)
        da_source = "user_override"
        da_period_str = "user_override"
        da_as_of = as_of
    elif getattr(snapshot, "da_ttm", None) is not None:
        if (
            getattr(snapshot, "revenue_ttm", None) is not None
            and snapshot.revenue_ttm.value > Decimal("0")
            and fwd_rev_val is not None
            and _periods_compatible(snapshot.da_ttm, snapshot.revenue_ttm)
        ):
            da_ratio = snapshot.da_ttm.value / snapshot.revenue_ttm.value
            da_val = (fwd_rev_val * da_ratio).quantize(Decimal("1"), ROUND_HALF_UP)
            da_source = "derived_historical"
        else:
            # Annual fallback D&A must not be divided by a TTM revenue base.
            # Keep the amount and its FY metadata visible instead of creating
            # a cross-period margin that looks like a TTM fact.
            da_val = snapshot.da_ttm.value
            da_source = "derived_historical_period_mismatch"
        da_as_of = snapshot.da_ttm.as_of
        da_period_str = snapshot.da_ttm.period

    # EBIT = EBITDA - D&A (requires both EBITDA and D&A; never fabricate D&A)
    ebit_val = (derived_ebitda.value - da_val) if (derived_ebitda is not None and da_val is not None) else None

    # Resolve Tax Rate
    tax_rate_val = Decimal("0.21")
    tax_source = "statutory_default"
    tax_as_of: Any = getattr(snapshot, "income_statement_as_of", None) or as_of
    tax_period_str: str = "statutory"
    if getattr(assumptions, "driver_tax_rate", None) is not None:
        tax_rate_val = assumptions.driver_tax_rate
        tax_source = "user_override"
        tax_period_str = "user_override"
        tax_as_of = as_of
    elif getattr(snapshot, "tax_rate", None) is not None:
        tr = snapshot.tax_rate.value
        if Decimal("0") <= tr <= Decimal("0.50"):
            tax_rate_val = tr
            tax_source = "derived_historical"
            tax_as_of = snapshot.tax_rate.as_of
            tax_period_str = snapshot.tax_rate.period

    # NOPAT = EBIT * (1 - TaxRate)
    nopat_val = (ebit_val * (Decimal("1") - tax_rate_val)).quantize(Decimal("1"), ROUND_HALF_UP) if ebit_val is not None else None

    # Resolve CapEx
    capex_val: Optional[Decimal] = None
    capex_source: Optional[str] = None
    capex_as_of: Any = getattr(snapshot, "cash_flow_as_of", None) or as_of
    capex_period_str: str = getattr(getattr(snapshot, "capex_ttm", None), "period", "TTM")
    if getattr(assumptions, "driver_capex", None) is not None:
        capex_val = assumptions.driver_capex
        capex_source = "user_override"
        capex_as_of = as_of
        capex_period_str = "user_override"
    elif getattr(assumptions, "driver_capex_ratio", None) is not None and fwd_rev_val is not None:
        capex_ratio = assumptions.driver_capex_ratio
        capex_val = (fwd_rev_val * capex_ratio).quantize(Decimal("1"), ROUND_HALF_UP)
        capex_source = "user_override"
        capex_as_of = as_of
        capex_period_str = "user_override"
    elif getattr(snapshot, "capex_ttm", None) is not None:
        if (
            getattr(snapshot, "revenue_ttm", None) is not None
            and snapshot.revenue_ttm.value > Decimal("0")
            and fwd_rev_val is not None
            and _periods_compatible(snapshot.capex_ttm, snapshot.revenue_ttm)
        ):
            capex_ratio = snapshot.capex_ttm.value / snapshot.revenue_ttm.value
            capex_val = (fwd_rev_val * capex_ratio).quantize(Decimal("1"), ROUND_HALF_UP)
        else:
            capex_val = snapshot.capex_ttm.value
            capex_source = "derived_historical_period_mismatch"
        if capex_source is None:
            capex_source = "derived_historical"
        capex_as_of = snapshot.capex_ttm.as_of
        capex_period_str = snapshot.capex_ttm.period

    # Resolve ΔNWC (balance sheet investment in working capital; cash outflow when positive)
    nwc_change_val: Optional[Decimal] = None
    nwc_source: Optional[str] = None
    nwc_as_of: Any = getattr(snapshot, "cash_flow_as_of", None) or as_of
    nwc_period_str: str = getattr(getattr(snapshot, "nwc_change_ttm", None), "period", "TTM")
    if getattr(assumptions, "driver_nwc_change", None) is not None:
        nwc_change_val = assumptions.driver_nwc_change
        nwc_source = "user_override"
        nwc_as_of = as_of
        nwc_period_str = "user_override"
    elif getattr(assumptions, "driver_nwc_ratio", None) is not None and fwd_rev_val is not None:
        nwc_ratio = assumptions.driver_nwc_ratio
        nwc_change_val = (fwd_rev_val * nwc_ratio).quantize(Decimal("1"), ROUND_HALF_UP)
        nwc_source = "user_override"
        nwc_as_of = as_of
        nwc_period_str = "user_override"
    elif getattr(snapshot, "nwc_change_ttm", None) is not None:
        if (
            getattr(snapshot, "revenue_ttm", None) is not None
            and snapshot.revenue_ttm.value > Decimal("0")
            and fwd_rev_val is not None
            and _periods_compatible(snapshot.nwc_change_ttm, snapshot.revenue_ttm)
        ):
            nwc_ratio = snapshot.nwc_change_ttm.value / snapshot.revenue_ttm.value
            nwc_change_val = (fwd_rev_val * nwc_ratio).quantize(Decimal("1"), ROUND_HALF_UP)
        else:
            nwc_change_val = snapshot.nwc_change_ttm.value
            nwc_source = "derived_historical_period_mismatch"
        if nwc_source is None:
            nwc_source = "derived_historical"
        nwc_as_of = snapshot.nwc_change_ttm.as_of
        nwc_period_str = snapshot.nwc_change_ttm.period

    # FCFF = NOPAT + D&A - CapEx - ΔNWC
    raw_forward_fcff = getattr(snapshot, "forward_fcff_1y", None)
    is_fcff_consensus = (
        raw_forward_fcff is not None
        and getattr(raw_forward_fcff, "source_type", None) == SourceType.ANALYST_ESTIMATE
    )

    has_driver_overrides_fcff = any(
        getattr(assumptions, k, None) is not None
        for k in ("driver_ebitda_margin", "driver_capex", "driver_capex_ratio", "driver_nwc_change", "driver_nwc_ratio", "driver_da", "driver_da_ratio", "driver_tax_rate")
    )

    bridge_fcff: Optional[Decimal] = None
    if nopat_val is not None and da_val is not None and capex_val is not None and nwc_change_val is not None:
        bridge_fcff = (nopat_val + da_val - capex_val - nwc_change_val).quantize(Decimal("1"), ROUND_HALF_UP)

    derived_fcff_1y: Optional[FinancialMetric] = None
    derived_fcff_2y: Optional[FinancialMetric] = None

    if is_fcff_consensus and not has_driver_overrides_fcff:
        derived_fcff_1y = raw_forward_fcff
        if getattr(snapshot, "forward_fcff_2y", None) is not None and snapshot.forward_fcff_2y.source_type == SourceType.ANALYST_ESTIMATE:
            derived_fcff_2y = snapshot.forward_fcff_2y
    elif bridge_fcff is not None and (has_driver_overrides_fcff or has_forward_revenue_est or fwd_rev_val is not None):
        derived_fcff_1y = FinancialMetric(
            value=bridge_fcff,
            unit=getattr(snapshot, "currency", "USD") or "USD",
            period=target_metric_period,
            source=f"Financial driver bridge: NOPAT ({nopat_val}) + D&A ({da_val}) - CapEx ({capex_val}) - ΔNWC ({nwc_change_val})",
            source_type=SourceType.USER_OVERRIDE if has_driver_overrides_fcff else SourceType.DERIVED,
            as_of=as_of,
            confidence=0.8,
            is_estimated=True,
            notes="FCFF = EBIT*(1-T) + D&A - CapEx - ΔNWC; excludes net borrowing.",
        )

    # ------------------------------------------------------------------
    # Construct DCF explicit forecast Year 1 and Year 2 as consistent,
    # non-overlapping full fiscal years (FY1E and FY2E).
    # ------------------------------------------------------------------
    dcf_fcff_1y: Optional[FinancialMetric] = None
    dcf_fcff_2y: Optional[FinancialMetric] = None

    fy1_revenue_is_explicit = _is_explicit_fy_metric(fy1_rev, 1, next_fy_end)
    fy2_revenue_is_explicit = _is_explicit_fy_metric(fy2_rev, 2, next_fy_end)

    # A direct FCFF estimate is eligible for DCF only when it identifies a
    # concrete FY1 period. Relative 0y/forward_1y labels become concrete only
    # with a fiscal-year-end anchor; NTM/TTM remain ineligible. Driver
    # overrides take precedence over direct consensus for both years.
    if (
        is_fcff_consensus
        and not has_driver_overrides_fcff
        and _is_explicit_fy_metric(raw_forward_fcff, 1, next_fy_end)
    ):
        dcf_fcff_1y = raw_forward_fcff
    elif (
        fy1_revenue_is_explicit
        and ebitda_margin is not None
        and da_val is not None
        and capex_val is not None
        and nwc_change_val is not None
    ):
        fy1_revenue_val = fy1_rev.value
        if fy1_revenue_val > Decimal("0"):
            scale_1 = (fy1_revenue_val / fwd_rev_val) if (fwd_rev_val and fwd_rev_val > Decimal("0")) else Decimal("1")
            ebitda_fy1 = (fy1_revenue_val * ebitda_margin).quantize(Decimal("1"), ROUND_HALF_UP)
            da_fy1 = (da_val * scale_1).quantize(Decimal("1"), ROUND_HALF_UP)
            ebit_fy1 = ebitda_fy1 - da_fy1
            nopat_fy1 = (ebit_fy1 * (Decimal("1") - tax_rate_val)).quantize(Decimal("1"), ROUND_HALF_UP)
            capex_fy1 = (capex_val * scale_1).quantize(Decimal("1"), ROUND_HALF_UP)
            nwc_fy1 = (nwc_change_val * scale_1).quantize(Decimal("1"), ROUND_HALF_UP)
            fcff_fy1 = (nopat_fy1 + da_fy1 - capex_fy1 - nwc_fy1).quantize(Decimal("1"), ROUND_HALF_UP)
            dcf_fcff_1y = FinancialMetric(
                value=fcff_fy1,
                unit=getattr(snapshot, "currency", "USD") or "USD",
                period="FY1E",
                source=f"DCF FY1E driver bridge: NOPAT ({nopat_fy1}) + D&A ({da_fy1}) - CapEx ({capex_fy1}) - ΔNWC ({nwc_fy1})",
                source_type=SourceType.USER_OVERRIDE if has_driver_overrides_fcff else SourceType.DERIVED,
                as_of=as_of,
                confidence=0.8,
                is_estimated=True,
                notes="DCF Year 1 explicit full fiscal year forecast (not NTM rolling stub).",
            )
    if (
        getattr(snapshot, "forward_fcff_2y", None) is not None
        and snapshot.forward_fcff_2y.source_type == SourceType.ANALYST_ESTIMATE
        and not has_driver_overrides_fcff
        and _is_explicit_fy_metric(snapshot.forward_fcff_2y, 2, next_fy_end)
    ):
        dcf_fcff_2y = snapshot.forward_fcff_2y
        derived_fcff_2y = snapshot.forward_fcff_2y
    elif (
        fy2_revenue_is_explicit
        and fy2_rev.value > Decimal("0")
        and ebitda_margin is not None
        and fwd_rev_val
        and fwd_rev_val > Decimal("0")
        and da_val is not None
        and capex_val is not None
        and nwc_change_val is not None
    ):
        fy2_rev_val = fy2_rev.value
        scale_2 = fy2_rev_val / fwd_rev_val
        ebitda_2y = (fy2_rev_val * ebitda_margin).quantize(Decimal("1"), ROUND_HALF_UP)
        da_2y = (da_val * scale_2).quantize(Decimal("1"), ROUND_HALF_UP)
        ebit_2y = ebitda_2y - da_2y
        nopat_2y = (ebit_2y * (Decimal("1") - tax_rate_val)).quantize(Decimal("1"), ROUND_HALF_UP)
        capex_2y = (capex_val * scale_2).quantize(Decimal("1"), ROUND_HALF_UP)
        nwc_2y = (nwc_change_val * scale_2).quantize(Decimal("1"), ROUND_HALF_UP)
        fcff_2y_calc = (nopat_2y + da_2y - capex_2y - nwc_2y).quantize(Decimal("1"), ROUND_HALF_UP)
        dcf_fcff_2y = FinancialMetric(
            value=fcff_2y_calc,
            unit=getattr(snapshot, "currency", "USD") or "USD",
            period="FY2E",
            source=f"DCF FY2E driver projection: NOPAT ({nopat_2y}) + D&A ({da_2y}) - CapEx ({capex_2y}) - ΔNWC ({nwc_2y})",
            source_type=SourceType.USER_OVERRIDE if has_driver_overrides_fcff else SourceType.DERIVED,
            as_of=as_of,
            confidence=0.7,
            is_estimated=True,
            notes="DCF Year 2 explicit full fiscal year forecast.",
        )
        derived_fcff_2y = dcf_fcff_2y

    # Resolve Interest and After-Tax Interest
    interest_val: Optional[Decimal] = None
    interest_source: Optional[str] = None
    interest_as_of: Any = getattr(snapshot, "cash_flow_as_of", None) or getattr(snapshot, "income_statement_as_of", None) or as_of
    interest_period_str: str = "TTM"
    if getattr(snapshot, "interest_ttm", None) is not None:
        interest_val = snapshot.interest_ttm.value
        interest_source = "derived_historical"
        interest_as_of = snapshot.interest_ttm.as_of
        interest_period_str = snapshot.interest_ttm.period
    after_tax_interest = (interest_val * (Decimal("1") - tax_rate_val)).quantize(Decimal("1"), ROUND_HALF_UP) if interest_val is not None else None

    # Resolve Net Borrowing
    net_borrowing_val: Optional[Decimal] = None
    net_borrowing_source: Optional[str] = None
    net_borrowing_as_of: Any = getattr(snapshot, "cash_flow_as_of", None) or as_of
    net_borrowing_period_str: str = "TTM"
    if getattr(assumptions, "driver_net_borrowing", None) is not None:
        net_borrowing_val = assumptions.driver_net_borrowing
        net_borrowing_source = "user_override"
        net_borrowing_as_of = as_of
        net_borrowing_period_str = "user_override"
    elif getattr(snapshot, "net_borrowing_ttm", None) is not None:
        net_borrowing_val = snapshot.net_borrowing_ttm.value
        net_borrowing_source = "derived_historical"
        net_borrowing_as_of = snapshot.net_borrowing_ttm.as_of
        net_borrowing_period_str = snapshot.net_borrowing_ttm.period

    # FCFE = FCFF - After-Tax Interest + Net Borrowing
    raw_forward_fcfe = getattr(snapshot, "forward_fcf_1y", None) or getattr(snapshot, "forward_fcfe_1y", None)
    is_fcfe_consensus = (
        raw_forward_fcfe is not None
        and getattr(raw_forward_fcfe, "source_type", None) == SourceType.ANALYST_ESTIMATE
    )

    has_driver_overrides_fcfe = has_driver_overrides_fcff or getattr(assumptions, "driver_net_borrowing", None) is not None

    derived_fcfe_1y: Optional[FinancialMetric] = None
    if is_fcfe_consensus and not has_driver_overrides_fcfe:
        derived_fcfe_1y = raw_forward_fcfe
    elif derived_fcff_1y is not None and after_tax_interest is not None and net_borrowing_val is not None:
        fcfe_calc = (derived_fcff_1y.value - after_tax_interest + net_borrowing_val).quantize(Decimal("1"), ROUND_HALF_UP)
        derived_fcfe_1y = FinancialMetric(
            value=fcfe_calc,
            unit=getattr(snapshot, "currency", "USD") or "USD",
            period=target_metric_period,
            source=f"Financial driver bridge: FCFF ({derived_fcff_1y.value}) - Interest*(1-T) ({after_tax_interest}) + NetBorrowing ({net_borrowing_val})",
            source_type=SourceType.USER_OVERRIDE if has_driver_overrides_fcfe else SourceType.DERIVED,
            as_of=as_of,
            confidence=0.8,
            is_estimated=True,
            notes="FCFE derived from FCFF with debt cash flow adjustment.",
        )

    # FCFE's reconciliation is deliberately separate from FCFF's.  Net
    # borrowing is an equity cash-flow adjustment and must never enter FCFF.
    bridge_fcfe: Optional[Decimal] = None
    if bridge_fcff is not None and after_tax_interest is not None and net_borrowing_val is not None:
        bridge_fcfe = (bridge_fcff - after_tax_interest + net_borrowing_val).quantize(Decimal("1"), ROUND_HALF_UP)

    # Build comprehensive financial bridge report payload
    financial_bridge_dict: Optional[dict[str, Any]] = None
    if fwd_rev_val is not None and derived_ebitda is not None:
        val_as_of = as_of
        fy1_start, fy1_end = _fiscal_year_bounds(fy1_rev, 1, next_fy_end)
        fy2_start, fy2_end = _fiscal_year_bounds(fy2_rev, 2, next_fy_end)
        if horizon == "current_fy" and fy1_start is not None and fy1_end is not None:
            forecast_start, forecast_end = fy1_start, fy1_end
        elif horizon == "next_fy" and fy2_start is not None and fy2_end is not None:
            forecast_start, forecast_end = fy2_start, fy2_end
        elif horizon == "current_fy" and next_fy_end is not None:
            forecast_end = next_fy_end
            forecast_start = _safe_add_years(forecast_end, -1) + timedelta(days=1)
        elif horizon == "next_fy" and next_fy_end is not None:
            forecast_start = next_fy_end + timedelta(days=1)
            forecast_end = _safe_add_years(next_fy_end, 1)
        else:
            forecast_start = val_as_of
            forecast_end = _safe_add_years(val_as_of, 1)

        # Check each accounting identity independently.  ``None`` means the
        # evidence needed for that identity was not available; it is never
        # reported as a successful reconciliation.
        ebitda_identity: Optional[bool] = None
        if ebitda_margin is not None and fwd_rev_val is not None and derived_ebitda is not None:
            ebitda_identity = derived_ebitda.value == (fwd_rev_val * ebitda_margin).quantize(Decimal("1"), ROUND_HALF_UP)
        ebit_identity: Optional[bool] = None
        if derived_ebitda is not None and da_val is not None and ebit_val is not None:
            ebit_identity = ebit_val == derived_ebitda.value - da_val
        nopat_identity: Optional[bool] = None
        if ebit_val is not None and nopat_val is not None:
            nopat_identity = nopat_val == (ebit_val * (Decimal("1") - tax_rate_val)).quantize(Decimal("1"), ROUND_HALF_UP)
        fcff_identity: Optional[bool] = None
        if bridge_fcff is not None and derived_fcff_1y is not None:
            fcff_identity = derived_fcff_1y.value == bridge_fcff
        fcfe_identity: Optional[bool] = None
        if bridge_fcfe is not None and derived_fcfe_1y is not None:
            fcfe_identity = derived_fcfe_1y.value == bridge_fcfe

        identity_checks: dict[str, Optional[bool]] = {
            "ebitda": ebitda_identity,
            "ebit": ebit_identity,
            "nopat": nopat_identity,
            "fcff": fcff_identity,
            "fcfe": fcfe_identity,
        }
        known_checks = [value for value in identity_checks.values() if value is not None]
        if any(value is False for value in known_checks):
            identity_holds: Optional[bool] = False
        elif len(known_checks) == len(identity_checks) and all(known_checks):
            identity_holds = True
        else:
            # Partial evidence is not a successful reconciliation.  Keep the
            # unknown state explicit so API/export/UI consumers cannot mistake
            # a single passing identity for five passing identities.
            identity_holds = None

        reconciliation_difference: Optional[str] = None
        fcfe_reconciliation_difference: Optional[str] = None
        reconciliation_messages: list[str] = []
        if is_fcff_consensus:
            if bridge_fcff is not None and derived_fcff_1y is not None:
                reconciliation_difference = str(derived_fcff_1y.value - bridge_fcff)
                if fcff_identity is False:
                    reconciliation_messages.append(
                        f"Direct analyst consensus FCFF ({derived_fcff_1y.value}) differs from operational driver bridge ({bridge_fcff}) by {derived_fcff_1y.value - bridge_fcff} USD; valuation uses consensus."
                    )
            else:
                reconciliation_messages.append(
                    "FCFF consensus was supplied, but the driver bridge is incomplete; FCFF identity cannot be verified."
                )
        if is_fcfe_consensus:
            if bridge_fcfe is not None and derived_fcfe_1y is not None:
                fcfe_reconciliation_difference = str(derived_fcfe_1y.value - bridge_fcfe)
                if fcfe_identity is False:
                    reconciliation_messages.append(
                        f"Direct analyst consensus FCFE ({derived_fcfe_1y.value}) differs from FCFF - after-tax interest + net borrowing ({bridge_fcfe}) by {derived_fcfe_1y.value - bridge_fcfe} USD; valuation uses consensus."
                    )
            else:
                reconciliation_messages.append(
                    "FCFE consensus was supplied, but FCFF, interest, or net borrowing evidence is incomplete; FCFE identity cannot be verified."
                )
        if identity_holds is None and not reconciliation_messages:
            reconciliation_messages.append("Accounting identities cannot be fully verified because one or more driver inputs are unavailable.")
        reconciliation_note = " ".join(reconciliation_messages) or None

        dcf_forecasts: list[dict[str, Any]] = []
        for year, metric, start_date, end_date in (
            (1, dcf_fcff_1y, fy1_start, fy1_end),
            (2, dcf_fcff_2y, fy2_start, fy2_end),
        ):
            if metric is not None:
                dcf_forecasts.append({
                    "year": year,
                    "value": str(metric.value),
                    "period": metric.period,
                    "as_of": metric.as_of.isoformat(),
                    "source": metric.source,
                    "source_type": metric.source_type,
                    "start_date": start_date.isoformat() if start_date is not None else None,
                    "end_date": end_date.isoformat() if end_date is not None else None,
                })

        financial_bridge_dict = {
            "period": effective_horizon,
            "forecast_start_date": forecast_start.isoformat(),
            "forecast_end_date": forecast_end.isoformat(),
            "as_of": val_as_of.isoformat(),
            "currency": getattr(snapshot, "currency", "USD") or "USD",
            "revenue": str(fwd_rev_val),
            "ebitda_margin": str(ebitda_margin) if ebitda_margin is not None else None,
            "ebitda": str(derived_ebitda.value),
            "da": str(da_val) if da_val is not None else None,
            "ebit": str(ebit_val) if ebit_val is not None else None,
            "tax_rate": str(tax_rate_val),
            "nopat": str(nopat_val) if nopat_val is not None else None,
            "capex": str(capex_val) if capex_val is not None else None,
            "nwc_change": str(nwc_change_val) if nwc_change_val is not None else None,
            "fcff": str(derived_fcff_1y.value) if derived_fcff_1y is not None else None,
            "bridge_fcff": str(bridge_fcff) if bridge_fcff is not None else None,
            "bridge_fcfe": str(bridge_fcfe) if bridge_fcfe is not None else None,
            "identity_holds": identity_holds,
            "identity_checks": identity_checks,
            "ebitda_identity_holds": ebitda_identity,
            "ebit_identity_holds": ebit_identity,
            "nopat_identity_holds": nopat_identity,
            "fcff_identity_holds": fcff_identity,
            "fcfe_identity_holds": fcfe_identity,
            "reconciliation_difference": reconciliation_difference,
            "fcfe_reconciliation_difference": fcfe_reconciliation_difference,
            "reconciliation_note": reconciliation_note,
            "interest": str(interest_val) if interest_val is not None else None,
            "after_tax_interest": str(after_tax_interest) if after_tax_interest is not None else None,
            "net_borrowing": str(net_borrowing_val) if net_borrowing_val is not None else None,
            "fcfe": str(derived_fcfe_1y.value) if derived_fcfe_1y is not None else None,
            "dcf_forecasts": dcf_forecasts,
            "restrictions_note": (
                "Financial bridge isolates operating business cash flows from non-operating items. "
                "Operating EBITDA is defined as Operating Income + D&A to isolate core operations "
                "from non-operating investment gains/losses (e.g. securities sales). "
                "Excludes stock-based compensation (SBC), operating lease capitalizations, "
                "and non-operating investment gains/losses from operating free cash flows."
            ),
            "drivers_source": {
                "ebitda_margin": {
                    "type": ebitda_margin_source,
                    "as_of": str(ebitda_margin_as_of.isoformat() if hasattr(ebitda_margin_as_of, "isoformat") else ebitda_margin_as_of),
                    "period": str(ebitda_margin_period),
                    "description": f"EBITDA margin: {ebitda_margin:.2%}" if ebitda_margin is not None else "N/A",
                },
                "da": {
                    "type": da_source or "statutory_default",
                    "as_of": str(da_as_of.isoformat() if hasattr(da_as_of, "isoformat") else da_as_of),
                    "period": str(da_period_str),
                    "description": f"D&A: {da_val} USD" if da_val is not None else "N/A",
                },
                "tax_rate": {
                    "type": tax_source,
                    "as_of": str(tax_as_of.isoformat() if hasattr(tax_as_of, "isoformat") else tax_as_of),
                    "period": str(tax_period_str),
                    "description": f"Effective tax rate: {tax_rate_val:.2%}",
                },
                "capex": {
                    "type": capex_source or "derived_historical",
                    "as_of": str(capex_as_of.isoformat() if hasattr(capex_as_of, "isoformat") else capex_as_of),
                    "period": str(capex_period_str),
                    "description": f"CapEx: {capex_val} USD" if capex_val is not None else "N/A",
                },
                "nwc_change": {
                    "type": nwc_source or "derived_historical",
                    "as_of": str(nwc_as_of.isoformat() if hasattr(nwc_as_of, "isoformat") else nwc_as_of),
                    "period": str(nwc_period_str),
                    "description": f"ΔNWC investment: {nwc_change_val} USD (cash outflow when positive)" if nwc_change_val is not None else "N/A",
                },
                "net_borrowing": {
                    "type": net_borrowing_source or "derived_historical",
                    "as_of": str(net_borrowing_as_of.isoformat() if hasattr(net_borrowing_as_of, "isoformat") else net_borrowing_as_of),
                    "period": str(net_borrowing_period_str),
                    "description": f"Net debt issuance: {net_borrowing_val} USD" if net_borrowing_val is not None else "N/A",
                },
            },
        }

    return RequestProjections(
        effective_horizon=effective_horizon,
        horizon_weight_fy1=w0,
        horizon_weight_fy2=w1,
        forward_eps=blended_eps,
        forward_revenue=blended_rev,
        forward_ebitda=derived_ebitda,
        forward_fcfe_1y=derived_fcfe_1y,
        forward_fcff_1y=derived_fcff_1y,
        forward_fcff_2y=derived_fcff_2y,
        effective_growth_floor=growth_floor,
        effective_growth_cap=growth_cap,
        fallback_warning=fallback_warning,
        financial_bridge=financial_bridge_dict,
        dcf_fcff_1y=dcf_fcff_1y,
        dcf_fcff_2y=dcf_fcff_2y,
    )

