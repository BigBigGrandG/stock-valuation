"""Regression coverage for S1 forward-borrowing horizon alignment."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pandas as pd

from app.models.domain import CompanyFinancialSnapshot, FinancialMetric, SourceType, ValuationAssumptions
from app.providers.yfinance_provider import (
    YFinanceProvider,
    _extract_forward_net_borrowing,
    _forward_borrowing_period,
)
from app.services.projections import calculate_ntm_weights, derive_request_projections


AS_OF = date(2026, 9, 12)
NEXT_FY_END = date(2026, 12, 31)


def _metric(
    value: object,
    *,
    period: str = "TTM",
    source_type: SourceType = SourceType.DERIVED,
    unit: str = "USD",
) -> FinancialMetric:
    return FinancialMetric(
        value=Decimal(str(value)),
        unit=unit,
        period=period,
        source="s1-regression",
        source_type=source_type,
        as_of=AS_OF,
        confidence=0.9,
        is_estimated=source_type != SourceType.ACTUAL,
    )


def _snapshot(**updates: object) -> CompanyFinancialSnapshot:
    fields: dict[str, object] = {
        "ticker": "S1",
        "company_name": "S1 Test Co",
        "currency": "USD",
        "current_price": _metric("100", period="2026-09-12", source_type=SourceType.ACTUAL),
        "price_timestamp": datetime(2026, 9, 12, 12, 0),
        "diluted_shares": _metric("1000", unit="shares", source_type=SourceType.ACTUAL),
        "cash": _metric("100", source_type=SourceType.ACTUAL),
        "total_debt": _metric("200", source_type=SourceType.ACTUAL),
        "revenue_ttm": _metric("1000"),
        "ebitda_ttm": _metric("200"),
        "eps_ttm": _metric("5", unit="USD/share"),
        "tax_rate": _metric("0.20", unit="ratio"),
        "capex_ttm": _metric("50"),
        "nwc_change_ttm": _metric("10"),
        "da_ttm": _metric("30"),
        "interest_ttm": _metric("20"),
        "net_borrowing_ttm": _metric("500"),
        "revenue_estimate_1y": _metric("1200", period="FY2026E", source_type=SourceType.ANALYST_ESTIMATE),
        "revenue_estimate_2y": _metric("1400", period="FY2027E", source_type=SourceType.ANALYST_ESTIMATE),
        "forward_eps_1y": _metric("6", period="FY2026E", source_type=SourceType.ANALYST_ESTIMATE),
        "forward_eps_2y": _metric("7", period="FY2027E", source_type=SourceType.ANALYST_ESTIMATE),
        "forecast_fiscal_year_end": NEXT_FY_END,
        "country": "US",
        "security_type": "COMMON_STOCK",
        "sector": "Technology",
        "industry": "Software",
        "is_profitable": True,
    }
    fields.update(updates)
    return CompanyFinancialSnapshot(**fields)


def _borrow(value: object, period: str) -> FinancialMetric:
    return _metric(value, period=period, source_type=SourceType.ANALYST_ESTIMATE)


def test_ntm_does_not_relabel_fy1_borrowing_as_rolling_ntm():
    snapshot = _snapshot(forward_net_borrowing_1y=_borrow("100", "FY2026E"))

    projection = derive_request_projections(snapshot, ValuationAssumptions(forecast_horizon="ntm"))

    assert projection.forward_net_borrowing is None
    assert projection.forward_net_borrowing_status != "provider_forward"
    assert projection.financial_bridge is not None
    assert Decimal(projection.financial_bridge["forward_net_borrowing"]) == Decimal("0")
    assert any("NTM" in warning and "FY1" in warning for warning in projection.warnings)


def test_ntm_blends_aligned_fy1_and_fy2_borrowing_with_fiscal_weights():
    snapshot = _snapshot(
        forward_net_borrowing_1y=_borrow("100", "FY2026E"),
        forward_net_borrowing_2y=_borrow("200", "FY2027E"),
    )
    w0, w1, _, _ = calculate_ntm_weights(AS_OF, NEXT_FY_END)
    expected = (w0 * Decimal("100") + w1 * Decimal("200")).quantize(Decimal("1"))

    projection = derive_request_projections(snapshot, ValuationAssumptions(forecast_horizon="ntm"))

    assert projection.forward_net_borrowing is not None
    assert projection.forward_net_borrowing.value == expected
    assert projection.forward_net_borrowing.period.startswith("NTM")
    assert projection.forward_net_borrowing_status == "provider_forward"
    assert projection.financial_bridge is not None
    assert Decimal(projection.financial_bridge["forward_net_borrowing"]) == expected


def test_ntm_fy_pair_without_fiscal_anchor_is_explicitly_unavailable():
    snapshot = _snapshot(
        forecast_fiscal_year_end=None,
        forward_net_borrowing_1y=_borrow("100", "FY2026E"),
        forward_net_borrowing_2y=_borrow("200", "FY2027E"),
    )

    projection = derive_request_projections(snapshot, ValuationAssumptions(forecast_horizon="ntm"))

    assert projection.forward_net_borrowing is None
    assert projection.forward_net_borrowing_status == "rejected_period_mismatch"
    assert any("anchored fiscal year end" in warning for warning in projection.warnings)


def test_ntm_accepts_only_an_explicit_current_fy_stub_plus_fy2_conversion():
    snapshot = _snapshot(
        forward_net_borrowing_1y=_borrow("10", "FY2026E_STUB"),
        forward_net_borrowing_2y=_borrow("200", "FY2027E"),
    )

    projection = derive_request_projections(snapshot, ValuationAssumptions(forecast_horizon="ntm"))

    assert projection.forward_net_borrowing is not None
    assert projection.forward_net_borrowing.value == Decimal("210")
    assert projection.forward_net_borrowing.period == "NTM (stub+FY2)"
    assert "stub" in (projection.forward_net_borrowing.notes or "").lower()


def test_current_fy_does_not_treat_a_stub_as_a_full_fiscal_year():
    snapshot = _snapshot(
        forward_net_borrowing_1y=_borrow("10", "FY2026E_STUB"),
        forward_net_borrowing_2y=_borrow("200", "FY2027E"),
    )

    projection = derive_request_projections(
        snapshot, ValuationAssumptions(forecast_horizon="current_fy")
    )

    assert projection.forward_net_borrowing is None
    assert projection.forward_net_borrowing_status == "rejected_period_mismatch"
    assert any("current_fy" in warning and "stub" in warning.lower() for warning in projection.warnings)


def test_next_fy_uses_fy2_only_and_rejects_period_mismatch():
    snapshot = _snapshot(
        forward_net_borrowing_1y=_borrow("100", "FY2026E"),
        forward_net_borrowing_2y=_borrow("200", "FY2027E"),
    )
    projection = derive_request_projections(snapshot, ValuationAssumptions(forecast_horizon="next_fy"))
    assert projection.forward_net_borrowing is not None
    assert projection.forward_net_borrowing.value == Decimal("200")
    assert projection.forward_net_borrowing.period == "FY2027E"

    mismatched = _snapshot(
        forward_net_borrowing_1y=_borrow("100", "FY2026E"),
        forward_net_borrowing_2y=_borrow("999", "FY2026E"),
    )
    rejected = derive_request_projections(mismatched, ValuationAssumptions(forecast_horizon="next_fy"))
    assert rejected.forward_net_borrowing is None
    assert rejected.financial_bridge is not None
    assert Decimal(rejected.financial_bridge["forward_net_borrowing"]) == Decimal("0")
    assert any("next_fy" in warning or "FY2026E" in warning for warning in rejected.warnings)


def test_explicit_net_borrowing_override_survives_provider_period_mismatch():
    snapshot = _snapshot(
        forward_net_borrowing_1y=_borrow("100", "FY2025E"),
        forward_net_borrowing_2y=_borrow("999", "FY2025E"),
    )
    assumptions = ValuationAssumptions(forecast_horizon="ntm", driver_net_borrowing=Decimal("55"))

    projection = derive_request_projections(snapshot, assumptions)

    assert projection.forward_net_borrowing is None
    assert projection.forward_net_borrowing_status == "user_override"
    assert projection.financial_bridge is not None
    assert Decimal(projection.financial_bridge["forward_net_borrowing"]) == Decimal("55")
    assert projection.financial_bridge["forward_net_borrowing_period"] == "forward_user_override"


def test_yfinance_forward_borrowing_period_metadata_uses_verified_fiscal_years():
    provider = YFinanceProvider()
    fiscal_end_ts = datetime(2026, 12, 31, tzinfo=timezone.utc).timestamp()
    last_fiscal_end_ts = datetime(2025, 12, 31, tzinfo=timezone.utc).timestamp()
    annual_date = pd.Timestamp("2025-12-31")

    with patch("yfinance.Ticker") as ticker_factory:
        ticker = MagicMock()
        ticker_factory.return_value = ticker
        ticker.info = {
            "quoteType": "EQUITY",
            "currency": "USD",
            "financialCurrency": "USD",
            "lastFiscalYearEnd": last_fiscal_end_ts,
            "nextFiscalYearEnd": fiscal_end_ts,
            "forwardNetBorrowing1Y": 100,
            "forwardNetBorrowing2Y": 200,
        }
        ticker.cashflow = pd.DataFrame(
            {annual_date: [300, -50]},
            index=["Operating Cash Flow", "Capital Expenditure"],
        )
        ticker.financials = pd.DataFrame(
            {annual_date: [20, 0.2]},
            index=["Interest Expense", "Tax Rate For Calcs"],
        )
        ticker.quarterly_cashflow = pd.DataFrame()
        ticker.quarterly_financials = pd.DataFrame()

        cash_flow = provider.get_cash_flow("S1")

    assert cash_flow["forward_net_borrowing_1y"] == Decimal("100")
    assert cash_flow["forward_net_borrowing_2y"] == Decimal("200")
    assert cash_flow["forward_net_borrowing_1y_period"] == "FY2026E"
    assert cash_flow["forward_net_borrowing_2y_period"] == "FY2027E"
    assert "period=FY2026E" in cash_flow["forward_net_borrowing_1y_notes"]


def test_yfinance_explicit_ntm_borrowing_alias_keeps_rolling_period():
    info = {"forwardNetBorrowingNTM": 321}

    value, field_key = _extract_forward_net_borrowing(info, 1)

    assert value == Decimal("321")
    assert _forward_borrowing_period(info, 1, field_key) == "NTM"


def test_yfinance_annual_borrowing_without_fiscal_anchor_stays_unverified():
    info = {"forwardNetBorrowing1Y": 321}

    value, field_key = _extract_forward_net_borrowing(info, 1)

    assert value == Decimal("321")
    assert _forward_borrowing_period(info, 1, field_key) == "forward_1y_unverified"
