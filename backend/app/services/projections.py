"""Request-scoped financial projection and consensus horizon interpolation module.

Decouples raw upstream provider data from request-scoped assumptions.
Calculates:
1. Exact bounded day-weighted NTM blends (w0, w1 in [0, 1]) for EPS and Revenue across fiscal years.
2. Request-scoped growth clamping with user-configured growth_floor and growth_cap.
3. Derived forward EBITDA, FCF, and FCFF without mutating global snapshot or provider cache.
"""
from __future__ import annotations

import calendar
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


def _is_leap_year(y: int) -> bool:
    return calendar.isleap(y)


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

    # Forward Revenue resolution
    fy1_rev = getattr(snapshot, "revenue_estimate_1y", None) or getattr(snapshot, "revenue_ttm", None)
    fy2_rev = getattr(snapshot, "revenue_estimate_2y", None)
    blended_rev: Optional[FinancialMetric] = None
    if horizon == "current_fy":
        blended_rev = fy1_rev
    elif horizon == "next_fy":
        blended_rev = fy2_rev or fy1_rev
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

    # Derived Forward EBITDA with request growth bounds
    base_ebitda = getattr(snapshot, "ebitda_ttm", None) or getattr(snapshot, "ebitda", None)
    raw_forward_ebitda = getattr(snapshot, "forward_ebitda_1y", None) or getattr(snapshot, "forward_ebitda", None)
    derived_ebitda: Optional[FinancialMetric] = raw_forward_ebitda
    if raw_forward_ebitda is not None and base_ebitda is not None and base_ebitda.value > Decimal("0"):
        raw_growth = None
        if snapshot.ebitda_growth is not None:
            raw_growth = snapshot.ebitda_growth.value
        elif snapshot.revenue_growth is not None:
            raw_growth = snapshot.revenue_growth.value
        elif raw_forward_ebitda.value > Decimal("0"):
            raw_growth = (raw_forward_ebitda.value - base_ebitda.value) / base_ebitda.value

        if raw_growth is not None:
            effective_g = clamp(raw_growth)
            fwd_ebitda_val = (base_ebitda.value * (Decimal("1") + effective_g)).quantize(Decimal("1"), ROUND_HALF_UP)
            derived_ebitda = FinancialMetric(
                value=fwd_ebitda_val,
                unit="USD",
                period="forward_1y",
                source=f"Derived from base EBITDA ({base_ebitda.value}) × (1 + {effective_g:.1%})",
                source_type=SourceType.DERIVED,
                as_of=as_of,
                confidence=raw_forward_ebitda.confidence,
                is_estimated=True,
                notes=f"Growth clamped to [{growth_floor:.1%}, {growth_cap:.1%}]",
            )

    # Derived Forward FCFE with request growth bounds
    base_fcfe = getattr(snapshot, "fcf_ttm", None)
    raw_forward_fcfe = getattr(snapshot, "forward_fcf_1y", None) or getattr(snapshot, "forward_fcfe_1y", None)
    derived_fcfe_1y: Optional[FinancialMetric] = raw_forward_fcfe
    if raw_forward_fcfe is not None and base_fcfe is not None and base_fcfe.value > Decimal("0"):
        raw_growth = None
        if snapshot.fcf_growth is not None:
            raw_growth = snapshot.fcf_growth.value
        elif snapshot.eps_growth is not None:
            raw_growth = snapshot.eps_growth.value
        elif snapshot.revenue_growth is not None:
            raw_growth = snapshot.revenue_growth.value
        elif raw_forward_fcfe.value > Decimal("0"):
            raw_growth = (raw_forward_fcfe.value - base_fcfe.value) / base_fcfe.value

        if raw_growth is not None:
            effective_g = clamp(raw_growth)
            fwd_fcfe_val = (base_fcfe.value * (Decimal("1") + effective_g)).quantize(Decimal("1"), ROUND_HALF_UP)
            derived_fcfe_1y = FinancialMetric(
                value=fwd_fcfe_val,
                unit="USD",
                period="forward_1y",
                source=f"Derived from base FCFE ({base_fcfe.value}) × (1 + {effective_g:.1%})",
                source_type=SourceType.DERIVED,
                as_of=as_of,
                confidence=raw_forward_fcfe.confidence,
                is_estimated=True,
                notes=f"Growth clamped to [{growth_floor:.1%}, {growth_cap:.1%}]",
            )

    # Derived Forward FCFF with request growth bounds
    base_fcff = snapshot.fcff_ttm
    derived_fcff_1y: Optional[FinancialMetric] = snapshot.forward_fcff_1y
    derived_fcff_2y: Optional[FinancialMetric] = snapshot.forward_fcff_2y

    if base_fcff is not None and base_fcff.value > Decimal("0"):
        raw_growth = None
        if snapshot.fcff_growth is not None:
            raw_growth = snapshot.fcff_growth.value
        elif snapshot.revenue_growth is not None:
            raw_growth = snapshot.revenue_growth.value
        elif derived_fcff_1y is not None and derived_fcff_1y.value > Decimal("0"):
            raw_growth = (derived_fcff_1y.value - base_fcff.value) / base_fcff.value

        if raw_growth is not None:
            effective_g = clamp(raw_growth)
            fwd_fcff_val = (base_fcff.value * (Decimal("1") + effective_g)).quantize(Decimal("1"), ROUND_HALF_UP)
            derived_fcff_1y = FinancialMetric(
                value=fwd_fcff_val,
                unit="USD",
                period="FY1E",
                source=f"Derived from base FCFF ({base_fcff.value}) × (1 + {effective_g:.1%})",
                source_type=SourceType.DERIVED,
                as_of=as_of,
                confidence=0.8,
                is_estimated=True,
                notes=f"Growth clamped to [{growth_floor:.1%}, {growth_cap:.1%}]",
            )
            fwd_fcff_2y_val = (fwd_fcff_val * (Decimal("1") + effective_g)).quantize(Decimal("1"), ROUND_HALF_UP)
            derived_fcff_2y = FinancialMetric(
                value=fwd_fcff_2y_val,
                unit="USD",
                period="FY2E",
                source=f"Derived from Year 1 FCFF × (1 + {effective_g:.1%})",
                source_type=SourceType.DERIVED,
                as_of=as_of,
                confidence=0.7,
                is_estimated=True,
                notes=f"Growth clamped to [{growth_floor:.1%}, {growth_cap:.1%}]",
            )

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
    )

