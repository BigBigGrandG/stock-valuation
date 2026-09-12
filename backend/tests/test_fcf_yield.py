"""
test_fcf_yield.py
Tests FCF yield engine. Verifies that a higher yield rate produces a LOWER price.
(.055 yield -> lower price than .045 yield)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from decimal import Decimal
from datetime import date, datetime
from app.models.domain import (
    CompanyFinancialSnapshot, FinancialMetric, SourceType, ValuationAssumptions,
    ScenarioValues,
)
from app.engines.fcf_yield import run_fcf_yield

FIXTURE_DATE = date(2025, 1, 1)

def _metric(v, u="USD") -> FinancialMetric:
    return FinancialMetric(
        value=Decimal(v), unit=u, period="TTM", source="fixture",
        source_type=SourceType.FIXTURE, as_of=FIXTURE_DATE
    )

def _avgo_snapshot_fcfe(forward_fcfe="89600000000") -> CompanyFinancialSnapshot:
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
        # FCFE for FCF yield model
        forward_fcf_1y=FinancialMetric(
            value=Decimal(forward_fcfe), unit="USD", period="FY2025E",
            source="analyst estimate", source_type=SourceType.ANALYST_ESTIMATE,
            as_of=FIXTURE_DATE, is_estimated=True,
        ),
        is_demo=True,
    )


def test_high_yield_lower_price():
    """
    Spec: 0.055 yield produces lower price than 0.045 yield.
    equity_at_055 = FCFE/0.055 < equity_at_045 = FCFE/0.045
    """
    snap = _avgo_snapshot_fcfe("89600000000")
    assumptions = ValuationAssumptions(
        fcf_yield=ScenarioValues(
            low=Decimal("0.055"),  # low scenario = conservative = highest yield
            base=Decimal("0.050"),
            high=Decimal("0.045"),  # high scenario = optimistic = lowest yield
        ),
        fcf_yield_source=SourceType.USER_OVERRIDE,
        fcf_yield_source_label="Test user override",
    )
    result = run_fcf_yield(snap, assumptions)
    assert result.available
    assert result.low is not None
    assert result.high is not None
    # low yield scenario (.045) gives HIGHER price
    # spec says "low valuation uses HIGH yield"
    assert result.low.price_per_share < result.high.price_per_share, (
        f"Low price ({result.low.price_per_share}) should be < high price ({result.high.price_per_share})"
    )


def test_fcf_yield_math():
    """
    Manual verification:
    FCFE = 89600000000, yield = 0.05, shares = 4940000000
    equity = 89600000000 / 0.05 = 1792000000000
    price = 1792000000000 / 4940000000 = 362.75...
    """
    snap = _avgo_snapshot_fcfe("89600000000")
    assumptions = ValuationAssumptions(
        fcf_yield=ScenarioValues(
            low=Decimal("0.055"), base=Decimal("0.050"), high=Decimal("0.045")
        ),
        fcf_yield_source=SourceType.USER_OVERRIDE,
        fcf_yield_source_label="Test user override",
    )
    result = run_fcf_yield(snap, assumptions)
    # base price = 89600000000 / 0.05 / 4940000000
    expected_equity = (Decimal("89600000000") / Decimal("0.050")).quantize(Decimal("0.01"))
    expected_price = (expected_equity / Decimal("4940000000")).quantize(Decimal("0.01"))
    assert result.base.price_per_share == expected_price


def test_high_yield_produces_lower_equity():
    """Verify equity value inversely proportional to yield."""
    snap = _avgo_snapshot_fcfe("100000000000")
    assumptions = ValuationAssumptions(
        fcf_yield=ScenarioValues(
            low=Decimal("0.055"), base=Decimal("0.050"), high=Decimal("0.045")
        ),
        fcf_yield_source=SourceType.USER_OVERRIDE,
        fcf_yield_source_label="Test user override",
    )
    result = run_fcf_yield(snap, assumptions)
    # low scenario uses highest yield -> lowest equity value
    low_equity = Decimal(result.low.intermediates["equity_value"])
    high_equity = Decimal(result.high.intermediates["equity_value"])
    assert low_equity < high_equity


def test_negative_fcfe_unavailable():
    """Negative FCFE should make model unavailable."""
    snap = _avgo_snapshot_fcfe("-1000000000")
    result = run_fcf_yield(snap, ValuationAssumptions())
    assert not result.available


def test_no_fcfe_unavailable():
    """No FCFE data should make model unavailable."""
    snap = CompanyFinancialSnapshot(
        ticker="TEST", company_name="Test",
        current_price=_metric("100"),
        price_timestamp=datetime(2025, 1, 1),
        diluted_shares=_metric("1000000", "shares"),
        cash=_metric("1000000"), total_debt=_metric("2000000"),
        revenue_ttm=_metric("5000000"), ebitda_ttm=_metric("1000000"),
        eps_ttm=_metric("5.00"),
    )
    result = run_fcf_yield(snap, ValuationAssumptions())
    assert not result.available


def test_fcf_type_documented():
    """FCF type should be clearly documented as FCFE in inputs."""
    snap = _avgo_snapshot_fcfe("89600000000")
    result = run_fcf_yield(
        snap,
        ValuationAssumptions(
            fcf_yield_source=SourceType.USER_OVERRIDE,
            fcf_yield_source_label="Test user override",
        ),
    )
    assert result.available
    assert "FCFE" in result.inputs.get("fcf_type", "")
