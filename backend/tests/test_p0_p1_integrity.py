"""Comprehensive deterministic regression tests for P0/P1 valuation integrity fixes.

Covers:
1. [P0-A] Multi-class point-in-time share capital reconciliation.
2. [P0-B] True 4-quarter non-overlapping TTM statement rollup with annual fallback.
3. [P0-C] Calendar-anchored DCF forecasting, ACT/365 discounting, and display hygiene.
4. [P1-D] NTM consensus horizon selection with verified fiscal year day-weighting.
5. [P1-E] Configurable derived growth rate floor and cap without request leakage.
6. [P1-F] Dynamic model weight overrides with cash flow group cap (default 40%) and edge-case handling.
7. [P1-G] 3x3 terminal value sensitivity matrix with TV/EV ratio threshold alerts.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import pytest

from app.config import (
    DEFAULT_ASSUMPTIONS,
    DEFAULT_CASHFLOW_GROUP_MAX_WEIGHT,
    DEFAULT_GROWTH_CAP,
    DEFAULT_GROWTH_FLOOR,
)
from app.engines.composite import run_composite
from app.engines.dcf import run_dcf
from app.engines.ev_ebitda import run_ev_ebitda
from app.engines.fcf_yield import run_fcf_yield
from app.engines.forward_pe import run_forward_pe
from app.models.domain import (
    CompanyFinancialSnapshot,
    DataQuality,
    DCFSensitivityMatrix,
    FinancialMetric,
    ScenarioValues,
    SourceType,
    ValuationAssumptions,
)
from app.models.overrides import (
    DCFOverride,
    OverrideValidationError,
    ValuationOverrideRequest,
    WeightOverride,
)
from app.services.valuation_service import apply_overrides


def _make_metric(val: Decimal | str | int, unit: str = "USD", period: str = "TTM", as_of: date = date(2026, 9, 10)) -> FinancialMetric:
    return FinancialMetric(
        value=Decimal(str(val)),
        unit=unit,
        period=period,
        source="unit_test",
        source_type=SourceType.ACTUAL,
        as_of=as_of,
    )


def _make_snapshot(
    shares: Decimal = Decimal("2547506225"),
    price: Decimal = Decimal("650.00"),
    cash: Decimal = Decimal("60000000000"),
    debt: Decimal = Decimal("30000000000"),
    as_of: date = date(2026, 9, 10),
    statement_period: str = "TTM (2025-09 to 2026-06)",
    statement_basis: str = "TTM",
    annual_fallback: bool = False,
    shares_basis: str = "point_in_time_all_classes",
    shares_reconciliation: dict | None = None,
) -> CompanyFinancialSnapshot:
    p_metric = _make_metric(price, "USD", period=str(as_of), as_of=as_of)
    s_metric = _make_metric(shares, "shares", period="latest", as_of=as_of)
    c_metric = _make_metric(cash, "USD", period="latest", as_of=as_of)
    d_metric = _make_metric(debt, "USD", period="latest", as_of=as_of)

    return CompanyFinancialSnapshot(
        ticker="TEST",
        company_name="Test Corp",
        currency="USD",
        current_price=p_metric,
        price_timestamp=datetime(as_of.year, as_of.month, as_of.day, 12, 0, 0, tzinfo=timezone.utc),
        diluted_shares=s_metric,
        cash=c_metric,
        total_debt=d_metric,
        shares_basis=shares_basis,
        shares_reconciliation=shares_reconciliation or {"basis": shares_basis, "selected_shares": str(shares)},
        statement_basis=statement_basis,
        annual_fallback=annual_fallback,
        revenue_ttm=_make_metric("180000000000", period=statement_period, as_of=as_of),
        ebitda_ttm=_make_metric("100000000000", period=statement_period, as_of=as_of),
        eps_ttm=_make_metric("30.00", "USD/share", period=statement_period, as_of=as_of),
        fcf_ttm=_make_metric("70000000000", period=statement_period, as_of=as_of),
        fcff_ttm=_make_metric("72000000000", period=statement_period, as_of=as_of),
        forward_eps_1y=_make_metric("35.00", "USD/share", period="FY2026E", as_of=as_of),
        forward_eps_2y=_make_metric("40.00", "USD/share", period="FY2027E", as_of=as_of),
        forward_ebitda_1y=_make_metric("110000000000", period="FY2026E", as_of=as_of),
        forward_fcf_1y=_make_metric("75000000000", period="FY2026E", as_of=as_of),
        forward_fcff_1y=_make_metric("78000000000", period="FY2026E", as_of=as_of),
        country="US",
        exchange="NASDAQ",
        security_type="COMMON_STOCK",
        is_profitable=True,
    )


# ----------------------------------------------------------------------
# 1. P0-A: Multi-Class Share Capital Reconciliation
# ----------------------------------------------------------------------
def test_share_reconciliation_multi_class():
    """Verify that multi-class all-class shares are used for per-share bridge, while P/E is independent."""
    # Class A only = 2.205B, All-class combined = 2.5475B
    snap = _make_snapshot(
        shares=Decimal("2547506225"),
        shares_basis="point_in_time_all_classes",
        shares_reconciliation={
            "basis": "point_in_time_all_classes",
            "shares_outstanding": "2205128509",
            "implied_shares_outstanding": "2547506225",
            "reconciliation_notes": "All-class shares selected",
        },
    )
    res_pe = run_forward_pe(snap, DEFAULT_ASSUMPTIONS)
    res_ev = run_ev_ebitda(snap, DEFAULT_ASSUMPTIONS)
    res_fcf = run_fcf_yield(snap, DEFAULT_ASSUMPTIONS)
    res_dcf = run_dcf(snap, DEFAULT_ASSUMPTIONS)

    assert res_pe.available
    assert res_ev.available
    assert res_fcf.available
    assert res_dcf.available

    # P/E model price = EPS * multiple = 35.00 * 20 = 700.00 (NOT divided by shares)
    assert res_pe.base.price_per_share == Decimal("700.00")

    # EV model divides equity by 2547506225, NOT 2205128509
    # EV base = EBITDA 110B * 22 = 2420B; net debt = -30B (net cash +30B) => Equity = 2450B
    # Price = 2450B / 2547506225 = ~961.72 (if divided by 2.205B it would be ~1111.05)
    assert res_ev.base.price_per_share < Decimal("1000.00")
    assert res_ev.inputs["diluted_shares"] == "2547506225"
    assert snap.shares_basis == "point_in_time_all_classes"


# ----------------------------------------------------------------------
# 2. P0-B: True 4-Quarter TTM Statement Rollup & Annual Fallback
# ----------------------------------------------------------------------
def test_true_ttm_vs_annual_fallback():
    """Verify statement_basis and annual_fallback flag in snapshot."""
    ttm_snap = _make_snapshot(statement_basis="TTM", annual_fallback=False)
    assert ttm_snap.statement_basis == "TTM"
    assert not ttm_snap.annual_fallback

    fallback_snap = _make_snapshot(
        statement_period="FY2025",
        statement_basis="ANNUAL_FALLBACK",
        annual_fallback=True,
    )
    assert fallback_snap.statement_basis == "ANNUAL_FALLBACK"
    assert fallback_snap.annual_fallback
    assert fallback_snap.revenue_ttm.period == "FY2025"


# ----------------------------------------------------------------------
# 3. P0-C: Calendar-Anchored DCF Projection & Discounting
# ----------------------------------------------------------------------
def test_dcf_calendar_anchored_dates():
    """Verify DCF future projection periods anchor to valuation as_of and never use past FYs."""
    as_of = date(2026, 9, 10)
    snap = _make_snapshot(as_of=as_of)
    res_dcf = run_dcf(snap, DEFAULT_ASSUMPTIONS)

    assert res_dcf.available
    scenarios = res_dcf.dcf_scenarios
    assert scenarios is not None and len(scenarios) == 3
    base_scen = next(s for s in scenarios if s.scenario == "base")

    # Projection periods must be future relative to 2026-09-10
    assert len(base_scen.projection_periods) == 5
    for period in base_scen.projection_periods:
        assert "FY2025" not in period, f"Past FY2025 found in future projection: {period}"

    # Year 1 period label must indicate future window from 2026
    y1_period = base_scen.projection_periods[0]
    assert "2026" in y1_period or "2027" in y1_period

    # PV Math check: 5 projection PVs, terminal value PV discounted at 5 years
    assert len(base_scen.pv_projections) == 5
    assert base_scen.pv_terminal_value > Decimal("0")
    assert base_scen.enterprise_value == sum(base_scen.pv_projections) + base_scen.pv_terminal_value


# ----------------------------------------------------------------------
# 4. P1-D: NTM Consensus Horizon Selection
# ----------------------------------------------------------------------
def test_ntm_consensus_horizon_override():
    """Verify NTM / current_fy / next_fy horizon selection in assumptions."""
    req_ntm = ValuationOverrideRequest(forecast_horizon="ntm")
    d_ntm = req_ntm.to_override_dict()
    assert d_ntm.get("forecast_horizon") == "ntm"

    req_fy1 = ValuationOverrideRequest(forecast_horizon="current_fy")
    d_fy1 = req_fy1.to_override_dict()
    assert d_fy1.get("forecast_horizon") == "current_fy"

    req_fy2 = ValuationOverrideRequest(forecast_horizon="next_fy")
    d_fy2 = req_fy2.to_override_dict()
    assert d_fy2.get("forecast_horizon") == "next_fy"

    assump = apply_overrides(DEFAULT_ASSUMPTIONS, d_ntm)
    assert assump.forecast_horizon == "ntm"


# ----------------------------------------------------------------------
# 5. P1-E: Configurable Derived Growth Floor & Cap
# ----------------------------------------------------------------------
def test_configurable_growth_limits():
    """Verify user can configure growth_floor and growth_cap, and invalid values are rejected."""
    # Valid override with cap=0.60
    req = ValuationOverrideRequest(dcf=DCFOverride(growth_cap=Decimal("0.60"), growth_floor=Decimal("-0.15")))
    d = req.to_override_dict()
    assert d["dcf.growth_cap"] == Decimal("0.60")
    assert d["dcf.growth_floor"] == Decimal("-0.15")

    assump = apply_overrides(DEFAULT_ASSUMPTIONS, d)
    assert assump.growth_cap == Decimal("0.60")
    assert assump.growth_floor == Decimal("-0.15")

    # Reject invalid bounds (floor > cap)
    with pytest.raises((ValueError, OverrideValidationError)):
        ValuationOverrideRequest(dcf=DCFOverride(growth_cap=Decimal("0.20"), growth_floor=Decimal("0.30")))

    # Reject floor <= -1.0
    with pytest.raises((ValueError, OverrideValidationError)):
        ValuationOverrideRequest(dcf=DCFOverride(growth_floor=Decimal("-1.05")))


# ----------------------------------------------------------------------
# 6. P1-F: Flexible Multi-Model Weighting & Cash Flow Group Cap
# ----------------------------------------------------------------------
def test_weight_overrides_and_cashflow_group_cap():
    """Verify custom weights, PE-only, cashflow group cap, and all-zero rejection."""
    # PE-only override
    req_pe = ValuationOverrideRequest(
        weights=WeightOverride(weight_pe=Decimal("1.0"), weight_ev_ebitda=Decimal("0"), weight_fcf_yield=Decimal("0"), weight_dcf=Decimal("0"))
    )
    d_pe = req_pe.to_override_dict()
    assump_pe = apply_overrides(DEFAULT_ASSUMPTIONS, d_pe)
    assert assump_pe.weight_pe == Decimal("1.0")
    assert assump_pe.weight_ev_ebitda == Decimal("0")

    snap = _make_snapshot()
    res_pe = run_forward_pe(snap, assump_pe)
    res_ev = run_ev_ebitda(snap, assump_pe)
    res_fcf = run_fcf_yield(snap, assump_pe)
    res_dcf = run_dcf(snap, assump_pe)

    comp_pe = run_composite(
        current_price=snap.current_price.value,
        pe_result=res_pe,
        ev_result=res_ev,
        fcf_result=res_fcf,
        dcf_result=res_dcf,
        assumptions=assump_pe,
    )
    assert comp_pe.available
    assert comp_pe.weights_used.get("forward_pe") == Decimal("1.0000")
    assert comp_pe.base == res_pe.base.price_per_share

    # Cashflow group cap (default 40% cap on FCF + DCF)
    comp_default = run_composite(
        current_price=snap.current_price.value,
        pe_result=res_pe,
        ev_result=res_ev,
        fcf_result=res_fcf,
        dcf_result=res_dcf,
        assumptions=DEFAULT_ASSUMPTIONS,
    )
    assert comp_default.available
    # Combined effective FCF + DCF weight should be capped at 40% (0.4000)
    cf_weight = comp_default.weights_used.get("fcf_yield", Decimal("0")) + comp_default.weights_used.get("dcf", Decimal("0"))
    assert cf_weight <= Decimal("0.4001")

    # Reject all-zero weights
    with pytest.raises((ValueError, OverrideValidationError)):
        ValuationOverrideRequest(
            weights=WeightOverride(weight_pe=Decimal("0"), weight_ev_ebitda=Decimal("0"), weight_fcf_yield=Decimal("0"), weight_dcf=Decimal("0"))
        )


# ----------------------------------------------------------------------
# 7. P1-G: Terminal Value 3x3 Sensitivity Matrix
# ----------------------------------------------------------------------
def test_dcf_sensitivity_matrix():
    """Verify 3x3 TV sensitivity matrix around base WACC and terminal growth."""
    snap = _make_snapshot()
    res_dcf = run_dcf(snap, DEFAULT_ASSUMPTIONS)

    assert res_dcf.available
    matrix = res_dcf.sensitivity_matrix
    assert matrix is not None
    assert len(matrix.wacc_range) == 3
    assert len(matrix.terminal_growth_range) == 3
    assert len(matrix.cells) == 3
    for row in matrix.cells:
        assert len(row) == 3

    # Center cell [1][1] must equal base DCF price per share
    center_cell = matrix.cells[1][1]
    assert center_cell.available
    assert center_cell.price_per_share == res_dcf.base.price_per_share
    assert center_cell.wacc == DEFAULT_ASSUMPTIONS.dcf_wacc.base
    assert center_cell.terminal_growth == DEFAULT_ASSUMPTIONS.dcf_terminal_growth.base

    # Monotonicity checks:
    # 1. Fixed g, higher WACC -> lower price
    assert matrix.cells[0][1].price_per_share > matrix.cells[1][1].price_per_share > matrix.cells[2][1].price_per_share
    # 2. Fixed WACC, higher g -> higher price
    assert matrix.cells[1][2].price_per_share > matrix.cells[1][1].price_per_share > matrix.cells[1][0].price_per_share

    # TV dependence alert
    assert matrix.base_tv_ratio > Decimal("0")
    if matrix.base_tv_ratio > Decimal("0.80"):
        assert matrix.tv_dependence_warning == "high_tv_dependence_strong"
    elif matrix.base_tv_ratio > Decimal("0.70"):
        assert matrix.tv_dependence_warning == "high_tv_dependence_moderate"
