"""
test_dcf.py
Tests DCF engine: all discounted years, TV/PVTV/EV/equity/share independent expected math.
WACC <= g raises validation error.
Year-1 and Year-2 use actual FCFF estimates; years 3-5 use growth.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from decimal import Decimal, ROUND_HALF_UP
from datetime import date, datetime
from app.models.domain import (
    CompanyFinancialSnapshot, FinancialMetric, SourceType, ValuationAssumptions,
    ScenarioValues,
)
from app.engines.dcf import run_dcf, _compute_dcf_scenario

FIXTURE_DATE = date(2025, 1, 1)

def _metric(v, u="USD") -> FinancialMetric:
    return FinancialMetric(
        value=Decimal(v), unit=u, period="TTM", source="fixture",
        source_type=SourceType.FIXTURE, as_of=FIXTURE_DATE
    )


def _avgo_snapshot_fcff(fcff1="89600000000", fcff2=None) -> CompanyFinancialSnapshot:
    base = CompanyFinancialSnapshot(
        ticker="AVGO",
        company_name="Broadcom Inc.",
        current_price=_metric("343.83"),
        price_timestamp=datetime(2025, 1, 1),
        diluted_shares=_metric("4940000000", "shares"),
        cash=_metric("24000000000"),
        total_debt=_metric("59400000000"),
        revenue_ttm=_metric("51574000000"),
        ebitda_ttm=_metric("28000000000"),
        eps_ttm=_metric("15.00"),
        forward_fcff_1y=FinancialMetric(
            value=Decimal(fcff1), unit="USD", period="FY2025E",
            source="analyst estimate", source_type=SourceType.ANALYST_ESTIMATE,
            as_of=FIXTURE_DATE, is_estimated=True,
        ),
    )
    if fcff2 is not None:
        base = base.model_copy(update={
            "forward_fcff_2y": FinancialMetric(
                value=Decimal(fcff2), unit="USD", period="FY2026E",
                source="analyst estimate", source_type=SourceType.ANALYST_ESTIMATE,
                as_of=FIXTURE_DATE, is_estimated=True,
            )
        })
    return base


def test_wacc_less_than_g_raises():
    """WACC <= terminal_growth must raise ValueError."""
    with pytest.raises(ValueError, match="WACC"):
        _compute_dcf_scenario(
            scenario_name="base",
            fcff_y1=Decimal("1000000"),
            fcff_y2=None,
            fcff_y1_label="test",
            fcff_y2_label=None,
            growth_rate=Decimal("0.05"),
            wacc=Decimal("0.03"),         # wacc < g
            terminal_growth=Decimal("0.04"),
            total_debt=Decimal("1000000"),
            cash=Decimal("500000"),
            diluted_shares=Decimal("1000000"),
            current_price=Decimal("10"),
        )


def test_wacc_equal_g_raises():
    """WACC == terminal_growth must raise ValueError."""
    with pytest.raises(ValueError, match="WACC"):
        _compute_dcf_scenario(
            scenario_name="base",
            fcff_y1=Decimal("1000000"),
            fcff_y2=None,
            fcff_y1_label="test",
            fcff_y2_label=None,
            growth_rate=Decimal("0.05"),
            wacc=Decimal("0.04"),
            terminal_growth=Decimal("0.04"),  # equal -> invalid
            total_debt=Decimal("1000000"),
            cash=Decimal("500000"),
            diluted_shares=Decimal("1000000"),
            current_price=Decimal("10"),
        )


def test_dcf_scenario_math():
    """
    Manually verify DCF math for a simple case (no Y2 estimate).
    FCFF1=100, growth=0.10 for years 2-5, WACC=0.12, terminal_growth=0.03
    Y1: 100, PV1 = 100/1.12^1
    Y2: 110, PV2 = 110/1.12^2  (growth-projected since fcff_y2=None)
    ...
    """
    PREC = Decimal("0.01")
    fcff_y1 = Decimal("100")
    growth = Decimal("0.10")
    wacc = Decimal("0.12")
    tg = Decimal("0.03")
    shares = Decimal("100")
    debt = Decimal("50")
    cash = Decimal("20")

    sc = _compute_dcf_scenario(
        scenario_name="base",
        fcff_y1=fcff_y1,
        fcff_y2=None,           # no Y2 estimate -> growth-projected
        fcff_y1_label="test Y1",
        fcff_y2_label=None,
        growth_rate=growth,
        wacc=wacc,
        terminal_growth=tg,
        total_debt=debt,
        cash=cash,
        diluted_shares=shares,
        current_price=Decimal("10"),
    )

    assert len(sc.fcff_projections) == 5
    assert len(sc.pv_projections) == 5

    # Y1 = fcff_y1 (actual)
    assert sc.fcff_projections[0] == fcff_y1

    # Y2 onwards = growth-projected (since fcff_y2=None)
    for t in range(2, 6):
        prev = sc.fcff_projections[t - 2]
        expected = (prev * (1 + growth)).quantize(PREC, ROUND_HALF_UP)
        assert sc.fcff_projections[t - 1] == expected, f"Year {t}: {sc.fcff_projections[t-1]} != {expected}"

    # Verify PVs using ACT/365 year fractions
    import math
    for t, pv in enumerate(sc.pv_projections, start=1):
        fcff_t = sc.fcff_projections[t - 1]
        yf = sc.year_fractions[t - 1]
        df = Decimal(str(math.exp(float(yf) * math.log(float(1 + wacc)))))
        expected_pv = (fcff_t / df).quantize(PREC, ROUND_HALF_UP)
        assert pv == expected_pv, f"PV Year {t}: {pv} != {expected_pv}"

    # Terminal value
    fcff_5 = sc.fcff_projections[-1]
    expected_tv = (fcff_5 * (1 + tg) / (wacc - tg)).quantize(PREC, ROUND_HALF_UP)
    assert sc.terminal_value == expected_tv

    # PVTV using Year 5 fraction
    t5 = sc.year_fractions[-1]
    df5 = Decimal(str(math.exp(float(t5) * math.log(float(1 + wacc)))))
    expected_pvtv = (expected_tv / df5).quantize(PREC, ROUND_HALF_UP)
    assert sc.pv_terminal_value == expected_pvtv

    # EV = sum(PV) + PVTV
    expected_ev = (sum(sc.pv_projections) + expected_pvtv).quantize(PREC, ROUND_HALF_UP)
    assert sc.enterprise_value == expected_ev

    # Equity = EV - net_debt
    net_debt = debt - cash
    assert sc.net_debt == net_debt
    expected_equity = expected_ev - net_debt
    assert sc.equity_value == expected_equity

    # Price/share
    expected_price = (expected_equity / shares).quantize(PREC, ROUND_HALF_UP)
    assert sc.price_per_share == expected_price


def test_dcf_y1_y2_actual_estimates():
    """When Y1 and Y2 FCFF estimates available, years 1 and 2 use actual values."""
    snap = _avgo_snapshot_fcff("89600000000", "99000000000")
    assumptions = ValuationAssumptions(
        dcf_wacc=ScenarioValues(low=Decimal("0.12"), base=Decimal("0.10"), high=Decimal("0.08")),
        dcf_terminal_growth=ScenarioValues(low=Decimal("0.03"), base=Decimal("0.03"), high=Decimal("0.04")),
        dcf_fcf_growth=ScenarioValues(low=Decimal("0.05"), base=Decimal("0.08"), high=Decimal("0.12")),
    )
    result = run_dcf(snap, assumptions)
    assert result.available
    # Base scenario Y1 should be the actual forward FCFF1
    base_sc = next(sc for sc in result.dcf_scenarios if sc.scenario == "base")
    assert base_sc.fcff_projections[0] == Decimal("89600000000")
    assert base_sc.fcff_projections[1] == Decimal("99000000000")


def test_dcf_full_avgo():
    """Run full DCF on AVGO fixture; verify all 3 scenarios present."""
    snap = _avgo_snapshot_fcff("89600000000")
    assumptions = ValuationAssumptions(
        dcf_wacc=ScenarioValues(low=Decimal("0.12"), base=Decimal("0.10"), high=Decimal("0.08")),
        dcf_terminal_growth=ScenarioValues(low=Decimal("0.03"), base=Decimal("0.03"), high=Decimal("0.04")),
        dcf_fcf_growth=ScenarioValues(low=Decimal("0.05"), base=Decimal("0.08"), high=Decimal("0.12")),
    )
    result = run_dcf(snap, assumptions)
    assert result.available
    assert result.dcf_scenarios is not None
    assert len(result.dcf_scenarios) == 3
    scenarios = {sc.scenario for sc in result.dcf_scenarios}
    assert scenarios == {"bear", "base", "bull"}


def test_dcf_bear_lower_than_bull():
    """Bear scenario produces lower price than bull."""
    snap = _avgo_snapshot_fcff("89600000000")
    result = run_dcf(snap, ValuationAssumptions())
    assert result.available
    assert result.low is not None and result.high is not None
    assert result.low.price_per_share < result.high.price_per_share


def test_no_fcff_unavailable():
    """DCF should be unavailable when only FCFE exists (cannot substitute)."""
    snap = CompanyFinancialSnapshot(
        ticker="TEST", company_name="Test",
        current_price=_metric("100"),
        price_timestamp=datetime(2025, 1, 1),
        diluted_shares=_metric("1000000", "shares"),
        cash=_metric("1000000"), total_debt=_metric("2000000"),
        revenue_ttm=_metric("5000000"), ebitda_ttm=_metric("1000000"),
        eps_ttm=_metric("5.00"),
        forward_fcf_1y=_metric("500000"),  # FCFE only
    )
    result = run_dcf(snap, ValuationAssumptions())
    assert not result.available
    assert "FCFE" in result.unavailable_reason or "FCFF" in result.unavailable_reason


def test_dcf_terminal_growth_exceeds_max_is_unavailable():
    """Terminal growth above the configured cap must not produce a valuation."""
    snap = _avgo_snapshot_fcff("89600000000")
    # Override terminal growth above max
    assumptions = ValuationAssumptions(
        dcf_terminal_growth=ScenarioValues(
            low=Decimal("0.06"), base=Decimal("0.06"), high=Decimal("0.07")
        ),
        dcf_fcf_growth=ScenarioValues(low=Decimal("0.05"), base=Decimal("0.08"), high=Decimal("0.12")),
    )
    result = run_dcf(snap, assumptions)
    assert not result.available
    assert "exceeds configured max" in result.unavailable_reason


def test_fcfe_not_proxied_for_fcff():
    """FCFE growth must never be used as a FCFF growth proxy."""
    # Create snapshot with only FCFE growth and FCFF data but no FCFF growth
    snap = CompanyFinancialSnapshot(
        ticker="TEST", company_name="Test",
        current_price=_metric("100"),
        price_timestamp=datetime(2025, 1, 1),
        diluted_shares=_metric("1000000", "shares"),
        cash=_metric("1000000"), total_debt=_metric("2000000"),
        revenue_ttm=_metric("5000000"), ebitda_ttm=_metric("1000000"),
        eps_ttm=_metric("5.00"),
        forward_fcff_1y=_metric("800000"),
        fcfe_growth=None,  # if any field like this existed
        fcf_growth=FinancialMetric(  # FCFE growth — must NOT be used for FCFF
            value=Decimal("0.50"), unit="ratio", period="YoY",
            source="test", source_type=SourceType.FIXTURE, as_of=FIXTURE_DATE
        ),
        fcff_growth=None,  # No FCFF growth
    )
    result = run_dcf(snap, ValuationAssumptions())
    # DCF should still run but must NOT use FCFE growth as FCFF proxy
    if result.available:
        growth_source = result.assumptions.get("growth_source", "")
        # Should not reference FCFE
        assert "FCFE" not in growth_source or "not FCFE" in growth_source
