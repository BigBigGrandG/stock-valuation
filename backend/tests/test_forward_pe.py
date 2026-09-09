"""
test_forward_pe.py
Spec requirement: exact 19.21*18/20/22 -> 345.78/384.20/422.62
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from decimal import Decimal
from datetime import date, datetime
from app.models.domain import (
    CompanyFinancialSnapshot, FinancialMetric, SourceType, ValuationAssumptions,
    ScenarioValues, DataQuality
)
from app.engines.forward_pe import run_forward_pe


def _make_snapshot(forward_eps: str = "19.21") -> CompanyFinancialSnapshot:
    d = date(2025, 1, 1)
    metric = lambda v, u="USD": FinancialMetric(
        value=Decimal(v), unit=u, period="TTM", source="fixture",
        source_type=SourceType.FIXTURE, as_of=d
    )
    return CompanyFinancialSnapshot(
        ticker="AVGO",
        company_name="Broadcom Inc.",
        current_price=metric("343.83"),
        price_timestamp=datetime(2025, 1, 1),
        diluted_shares=metric("4940000000", "shares"),
        cash=metric("24000000000"),
        total_debt=metric("59400000000"),
        revenue_ttm=metric("51574000000"),
        ebitda_ttm=metric("28000000000"),
        eps_ttm=metric("15.00"),
        forward_eps_1y=FinancialMetric(
            value=Decimal(forward_eps), unit="USD/share", period="FY2025E",
            source="analyst consensus", source_type=SourceType.ANALYST_ESTIMATE,
            as_of=d, is_estimated=True,
        ),
    )


def test_exact_spec_values():
    """Spec: 19.21*18/20/22 -> 345.78/384.20/422.62"""
    snap = _make_snapshot("19.21")
    assumptions = ValuationAssumptions(
        pe_target=ScenarioValues(
            low=Decimal("18"), base=Decimal("20"), high=Decimal("22")
        )
    )
    result = run_forward_pe(snap, assumptions)

    assert result.available, f"Expected available, got: {result.unavailable_reason}"
    assert result.low is not None
    assert result.base is not None
    assert result.high is not None

    # Spec exact values
    assert result.low.price_per_share == Decimal("345.78"), f"Low: {result.low.price_per_share}"
    assert result.base.price_per_share == Decimal("384.20"), f"Base: {result.base.price_per_share}"
    assert result.high.price_per_share == Decimal("422.62"), f"High: {result.high.price_per_share}"


def test_upside_calculation():
    """Verify upside and premium/discount calculations."""
    snap = _make_snapshot("19.21")
    assumptions = ValuationAssumptions(
        pe_target=ScenarioValues(low=Decimal("18"), base=Decimal("20"), high=Decimal("22"))
    )
    result = run_forward_pe(snap, assumptions)
    current = Decimal("343.83")
    base_price = result.base.price_per_share  # 384.20
    expected_upside = ((base_price - current) / current).quantize(Decimal("0.0001"))
    assert result.base.upside_pct == expected_upside


def test_historical_pe_used_when_available():
    """Historical median P/E should override configured fallback."""
    snap = _make_snapshot("19.21")
    # Inject historical P/E
    snap = snap.model_copy(update={
        "historical_forward_pe": FinancialMetric(
            value=Decimal("24"), unit="ratio", period="5Y median",
            source="historical", source_type=SourceType.ACTUAL, as_of=date(2025, 1, 1)
        )
    })
    result = run_forward_pe(snap, ValuationAssumptions())
    # low = 24*0.9 = 21.6; base = 24; high = 24*1.1 = 26.4
    assert result.assumptions["pe_source"] == SourceType.ACTUAL
    assert result.base.price_per_share == (Decimal("19.21") * Decimal("24")).quantize(Decimal("0.01"))


def test_missing_forward_eps_unavailable():
    """Model should be unavailable when forward EPS is missing."""
    d = date(2025, 1, 1)
    metric = lambda v, u="USD": FinancialMetric(
        value=Decimal(v), unit=u, period="TTM", source="fixture",
        source_type=SourceType.FIXTURE, as_of=d
    )
    snap = CompanyFinancialSnapshot(
        ticker="TEST", company_name="Test Co",
        current_price=metric("100"),
        price_timestamp=datetime(2025, 1, 1),
        diluted_shares=metric("1000000", "shares"),
        cash=metric("1000000"), total_debt=metric("2000000"),
        revenue_ttm=metric("5000000"), ebitda_ttm=metric("1000000"),
        eps_ttm=metric("5.00"),
        # No forward_eps_1y or forward_eps_2y
    )
    result = run_forward_pe(snap, ValuationAssumptions())
    assert not result.available
    assert result.unavailable_reason is not None


def test_negative_eps_unavailable():
    """Model should be unavailable when forward EPS is non-positive."""
    snap = _make_snapshot("-1.00")
    result = run_forward_pe(snap, ValuationAssumptions())
    assert not result.available
    assert "non-positive" in result.unavailable_reason.lower()


def test_formula_and_description():
    """Verify formula metadata is populated."""
    snap = _make_snapshot("19.21")
    result = run_forward_pe(snap, ValuationAssumptions())
    assert "Forward EPS" in result.formula
    assert len(result.calculation_steps) >= 3
    assert "forward_eps" in result.inputs
