"""
test_ev_ebitda.py
Tests EV/EBITDA engine with AVGO fixture values.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from decimal import Decimal
from datetime import date, datetime
from app.models.domain import (
    CompanyFinancialSnapshot, FinancialMetric, SourceType, ValuationAssumptions,
    ScenarioValues,
)
from app.engines.ev_ebitda import run_ev_ebitda

FIXTURE_DATE = date(2025, 1, 1)

def _metric(v, u="USD") -> FinancialMetric:
    return FinancialMetric(
        value=Decimal(v), unit=u, period="TTM", source="fixture",
        source_type=SourceType.FIXTURE, as_of=FIXTURE_DATE
    )

def _avgo_snapshot(multiple_base="22") -> CompanyFinancialSnapshot:
    """AVGO test fixture with EBITDA=118300000000"""
    return CompanyFinancialSnapshot(
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
        forward_ebitda_1y=FinancialMetric(
            value=Decimal("118300000000"), unit="USD", period="FY2025E",
            source="analyst consensus", source_type=SourceType.ANALYST_ESTIMATE,
            as_of=FIXTURE_DATE, is_estimated=True,
        ),
    )


def test_ev_net_debt_equity_per_share():
    """
    Test with AVGO fixture:
    net_debt = 59400000000 - 24000000000 = 35400000000
    EV (base, 22x) = 118300000000 * 22 = 2602600000000
    equity = 2602600000000 - 35400000000 = 2567200000000
    price = 2567200000000 / 4940000000 = 519.88 (approximately)
    """
    snap = _avgo_snapshot()
    assumptions = ValuationAssumptions(
        ev_ebitda_multiple=ScenarioValues(
            low=Decimal("18"), base=Decimal("22"), high=Decimal("26")
        )
    )
    result = run_ev_ebitda(snap, assumptions)

    assert result.available
    assert result.base is not None
    assert result.low is not None
    assert result.high is not None

    # Verify net debt calculation exposed in intermediates
    assert result.base.intermediates["net_debt"] == str(Decimal("35400000000"))

    # Verify EV calculation
    expected_ev = (Decimal("118300000000") * Decimal("22")).quantize(Decimal("0.01"))
    assert result.base.intermediates["ev"] == str(expected_ev)

    # Verify equity = EV - net_debt
    expected_equity = expected_ev - Decimal("35400000000")
    assert result.base.intermediates["equity_value"] == str(expected_equity)

    # Verify price/share
    expected_price = (expected_equity / Decimal("4940000000")).quantize(Decimal("0.01"))
    assert result.base.price_per_share == expected_price


def test_low_less_than_high():
    """Low price scenario must be less than high price scenario."""
    snap = _avgo_snapshot()
    result = run_ev_ebitda(snap, ValuationAssumptions())
    assert result.low.price_per_share < result.base.price_per_share < result.high.price_per_share


def test_negative_ebitda_unavailable():
    """Negative EBITDA should make model unavailable."""
    snap = _avgo_snapshot()
    snap = snap.model_copy(update={
        "forward_ebitda_1y": _metric("-1000000000")
    })
    result = run_ev_ebitda(snap, ValuationAssumptions())
    assert not result.available
    assert "non-positive" in result.unavailable_reason.lower()


def test_no_forward_ebitda_unavailable():
    """No forward EBITDA should make model unavailable."""
    snap = CompanyFinancialSnapshot(
        ticker="TEST", company_name="Test",
        current_price=_metric("100"),
        price_timestamp=datetime(2025, 1, 1),
        diluted_shares=_metric("1000000", "shares"),
        cash=_metric("1000000"), total_debt=_metric("2000000"),
        revenue_ttm=_metric("5000000"), ebitda_ttm=_metric("1000000"),
        eps_ttm=_metric("5.00"),
    )
    result = run_ev_ebitda(snap, ValuationAssumptions())
    assert not result.available


def test_historical_multiple_used():
    """Historical EV/EBITDA multiple should be used when available."""
    snap = _avgo_snapshot()
    snap = snap.model_copy(update={
        "historical_ev_ebitda": _metric("20")
    })
    result = run_ev_ebitda(snap, ValuationAssumptions())
    # base should use hist=20; low=18, high=22
    # The selected historical metric carries fixture provenance; it must not
    # be relabelled as a live actual merely because it is a historical input.
    assert result.assumptions["source"] == SourceType.FIXTURE
    assert Decimal(result.assumptions["multiple_base"]) == Decimal("20")
