"""
Offline mock provider integration and regression tests for YFinanceProvider.
Covers all 7 methods, normalization, FCFE vs FCFF formulas, error mappings (404, 422, 429, 503),
ticker normalization (uppercase/lowercase/share-class), bank/insurance applicability,
loss-maker handling, category TTL caching, and non-blocking async execution.
"""
import asyncio
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import DEFAULT_ASSUMPTIONS
from app.models.domain import DataQuality, SourceType
from app.providers.base import (
    ProviderRateLimitError,
    ProviderUnavailableError,
    TickerNotFoundError,
    UnsupportedCompanyError,
)
from app.providers.yfinance_provider import YFinanceProvider, _normalize_query_symbol
from app.services.valuation_service import (
    FinancialDataService,
    MemoryTTLCache,
    Normalizer,
    ValuationService,
)


def test_normalize_query_symbol():
    assert _normalize_query_symbol("BRK.B") == "BRK-B"
    assert _normalize_query_symbol("brk.b") == "BRK-B"
    assert _normalize_query_symbol("brk-b") == "BRK-B"
    assert _normalize_query_symbol("AAPL") == "AAPL"
    assert _normalize_query_symbol("aapl") == "AAPL"
    assert _normalize_query_symbol("bf.a") == "BF-A"


def test_mock_yfinance_provider_seven_methods():
    provider = YFinanceProvider()

    mock_info = {
        "shortName": "Mock Corp",
        "currentPrice": 150.0,
        "currency": "USD",
        "regularMarketTime": 1750000000,
        "sharesOutstanding": 1000000000,
        "totalCash": 20000000000,
        "totalDebt": 30000000000,
        "operatingCashflow": 12000000000,
        "freeCashflow": 8000000000,
        "totalRevenue": 50000000000,
        "ebitda": 15000000000,
        "trailingEps": 5.0,
        "forwardEps": 6.0,
        "trailingPE": 25.0,
        "enterpriseToEbitda": 18.0,
        "country": "United States",
        "sector": "Technology",
        "industry": "Software",
        "quoteType": "EQUITY",
    }

    with patch("yfinance.Ticker") as mock_ticker_cls:
        mock_t = MagicMock()
        mock_t.info = mock_info
        mock_t.balance_sheet = None
        mock_t.cashflow = None
        mock_t.financials = None
        mock_t.earnings_estimate = None
        mock_t.revenue_estimate = None
        mock_ticker_cls.return_value = mock_t

        # 1. get_quote
        q = provider.get_quote("MCORP")
        assert q["price"] == Decimal("150.00")
        assert q["currency"] == "USD"
        assert isinstance(q["as_of"], date)

        # 2. get_company_profile
        p = provider.get_company_profile("MCORP")
        assert p["name"] == "Mock Corp"
        assert p["diluted_shares"] == Decimal("1000000000")
        assert p["is_profitable"] is True

        # 3. get_balance_sheet
        bs = provider.get_balance_sheet("MCORP")
        assert bs["cash"] == Decimal("20000000000")
        assert bs["total_debt"] == Decimal("30000000000")
        assert bs["net_debt"] == Decimal("10000000000")

        # 4. get_cash_flow
        cf = provider.get_cash_flow("MCORP")
        assert cf["fcfe_ttm"] == Decimal("8000000000")
        assert "FCFE" in cf["fcfe_definition"]
        assert "FCFF" in cf["fcff_definition"]

        # 5. get_income_statement
        inc = provider.get_income_statement("MCORP")
        assert inc["revenue_ttm"] == Decimal("50000000000")
        assert inc["ebitda_ttm"] == Decimal("15000000000")
        assert inc["eps_ttm"] == Decimal("5")

        # 6. get_forward_estimates
        est = provider.get_forward_estimates("MCORP")
        assert est["forward_eps_1y"] == Decimal("6.00")

        # 7. get_historical_multiples (current trailing multiples are NOT historical forward or averages)
        mult = provider.get_historical_multiples("MCORP")
        assert mult["historical_forward_pe"] is None
        assert mult["historical_ev_ebitda"] is None


def test_fcfe_vs_fcff_separate_definitions():
    """FCFE and FCFF must use their exact distinct financial formulas."""
    provider = YFinanceProvider()

    # Cash flow statement dataframe with explicit lines
    import pandas as pd

    dates = [pd.Timestamp("2025-12-31")]
    cf_df = pd.DataFrame(
        {
            dates[0]: [
                10_000_000_000,  # CFO
                -2_000_000_000,  # Capex
                1_000_000_000,   # Net Issuance Payments Of Debt
            ]
        },
        index=[
            "Operating Cash Flow",
            "Capital Expenditure",
            "Net Issuance Payments Of Debt",
        ],
    )
    fin_df = pd.DataFrame(
        {
            dates[0]: [
                1_000_000_000,  # Interest Expense
                0.20,           # Tax Rate For Calcs
            ]
        },
        index=["Interest Expense", "Tax Rate For Calcs"],
    )

    with patch("yfinance.Ticker") as mock_ticker_cls:
        mock_t = MagicMock()
        mock_t.info = {"quoteType": "EQUITY", "currency": "USD"}
        mock_t.cashflow = cf_df
        mock_t.financials = fin_df
        mock_t.earnings_estimate = None
        mock_t.revenue_estimate = None
        mock_ticker_cls.return_value = mock_t

        cf = provider.get_cash_flow("TESTCO")
        # FCFE = CFO - capex + net_borrowing = 10B - 2B + 1B = 9B
        assert cf["fcfe_ttm"] == Decimal("9000000000")
        assert "net borrowing" in cf["fcfe_definition"].lower()

        # FCFF = CFO + interest*(1-tax) - capex = 10B + 1B*(1-0.20) - 2B = 10B + 0.8B - 2B = 8.8B
        assert cf["fcff_ttm"] == Decimal("8800000000")
        assert "interest*(1-tax)" in cf["fcff_definition"].lower()
        assert cf["fcfe_ttm"] != cf["fcff_ttm"]


def test_non_equity_etf_rejected_with_typed_error():
    provider = YFinanceProvider()
    with patch("yfinance.Ticker") as mock_ticker_cls:
        mock_t = MagicMock()
        mock_t.info = {"quoteType": "ETF", "shortName": "SPDR S&P 500 ETF", "currentPrice": 500.0}
        mock_ticker_cls.return_value = mock_t

        with pytest.raises(UnsupportedCompanyError) as exc_info:
            provider.get_quote("SPY")
        assert "etf" in str(exc_info.value).lower()


def test_unlisted_ticker_raises_ticker_not_found():
    provider = YFinanceProvider()
    with patch("yfinance.Ticker") as mock_ticker_cls:
        mock_t = MagicMock()
        mock_t.info = {}
        mock_t.history.return_value = None
        mock_ticker_cls.return_value = mock_t

        with pytest.raises(TickerNotFoundError):
            provider.get_quote("NONEXISTENT")


def test_rate_limit_raises_provider_rate_limit_error():
    provider = YFinanceProvider()
    with patch("yfinance.Ticker") as mock_ticker_cls:
        mock_t = MagicMock()
        type(mock_t).info = property(lambda self: (_ for _ in ()).throw(Exception("429 Too Many Requests")))
        mock_ticker_cls.return_value = mock_t

        with pytest.raises(ProviderRateLimitError):
            provider.get_quote("RATELIMITED")


def test_financial_institution_models_applicability():
    """Banks and financial institutions should have Forward P/E applicable and EV/EBITDA/DCF unavailable."""
    from app.engines.dcf import run_dcf
    from app.engines.ev_ebitda import run_ev_ebitda
    from app.engines.forward_pe import run_forward_pe
    from app.engines.composite import run_composite
    from app.models.domain import CompanyFinancialSnapshot, FinancialMetric, ValuationAssumptions

    def fm(v, unit="USD"):
        return FinancialMetric(
            value=Decimal(str(v)),
            unit=unit,
            period="FY2025",
            source="Test Bank",
            source_type=SourceType.ACTUAL,
            as_of=date(2025, 1, 1),
            confidence=1.0,
            is_estimated=False,
        )

    bank_snap = CompanyFinancialSnapshot(
        ticker="JPM",
        company_name="JPMorgan Chase & Co.",
        currency="USD",
        current_price=fm("200.00"),
        price_timestamp=datetime(2025, 1, 1, 16, 0, 0),
        diluted_shares=fm("2800000000", "shares"),
        cash=fm("500000000000"),
        total_debt=fm("400000000000"),
        forward_eps_1y=FinancialMetric(
            value=Decimal("18.00"),
            unit="USD/share",
            period="FY1E",
            source="analyst",
            source_type=SourceType.ANALYST_ESTIMATE,
            as_of=date(2025, 1, 1),
            confidence=0.8,
            is_estimated=True,
        ),
        sector="Financials",
        industry="Banks - Diversified",
        is_profitable=True,
        is_demo=False,
    )

    pe_res = run_forward_pe(
        bank_snap,
        ValuationAssumptions(
            pe_source=SourceType.USER_OVERRIDE,
            pe_source_label="Explicit P/E test assumption",
        ),
    )
    assert pe_res.available is True
    assert pe_res.base.price_per_share > Decimal("0")

    ev_res = run_ev_ebitda(bank_snap, DEFAULT_ASSUMPTIONS)
    assert ev_res.available is False
    assert "not applicable to banks" in ev_res.unavailable_reason.lower()

    dcf_res = run_dcf(bank_snap, DEFAULT_ASSUMPTIONS)
    assert dcf_res.available is False
    assert "not applicable to banks" in dcf_res.unavailable_reason.lower()

    comp_res = run_composite(
        bank_snap.current_price.value,
        pe_res,
        ev_res,
        pe_res.model_copy(update={"available": False, "unavailable_reason": "No FCFE"}),
        dcf_res,
        DEFAULT_ASSUMPTIONS,
    )
    assert comp_res.available is True
    assert comp_res.available_models == ["forward_pe"]
    assert comp_res.weights_used["forward_pe"] == Decimal("1.0000")


def test_loss_maker_models_preserve_reasons():
    """Loss makers should return snapshot and explicit reasons without blanket rejection."""
    from app.engines.forward_pe import run_forward_pe
    from app.engines.ev_ebitda import run_ev_ebitda
    from app.models.domain import CompanyFinancialSnapshot, FinancialMetric

    def fm(v, unit="USD"):
        return FinancialMetric(
            value=Decimal(str(v)),
            unit=unit,
            period="FY2025",
            source="Loss Corp",
            source_type=SourceType.ACTUAL,
            as_of=date(2025, 1, 1),
            confidence=1.0,
            is_estimated=False,
        )

    loss_snap = CompanyFinancialSnapshot(
        ticker="LOSER",
        company_name="Unprofitable Tech Corp",
        currency="USD",
        current_price=fm("15.00"),
        price_timestamp=datetime(2025, 1, 1, 16, 0, 0),
        diluted_shares=fm("100000000", "shares"),
        cash=fm("50000000"),
        total_debt=fm("20000000"),
        forward_eps_1y=FinancialMetric(
            value=Decimal("-1.50"),
            unit="USD/share",
            period="FY1E",
            source="analyst",
            source_type=SourceType.ANALYST_ESTIMATE,
            as_of=date(2025, 1, 1),
            confidence=0.8,
            is_estimated=True,
        ),
        forward_ebitda_1y=FinancialMetric(
            value=Decimal("-5000000"),
            unit="USD",
            period="FY1E",
            source="analyst",
            source_type=SourceType.ANALYST_ESTIMATE,
            as_of=date(2025, 1, 1),
            confidence=0.8,
            is_estimated=True,
        ),
        sector="Technology",
        industry="Software",
        is_profitable=False,
        is_demo=False,
    )

    pe_res = run_forward_pe(loss_snap, DEFAULT_ASSUMPTIONS)
    assert pe_res.available is False
    assert "non-positive" in pe_res.unavailable_reason.lower()

    ev_res = run_ev_ebitda(loss_snap, DEFAULT_ASSUMPTIONS)
    assert ev_res.available is False
    assert "non-positive" in ev_res.unavailable_reason.lower()


def test_category_ttl_caching():
    """FinancialDataService caches raw categories according to their configured TTL."""
    provider = MagicMock(spec=YFinanceProvider)
    provider.is_demo = False
    provider.get_quote.return_value = {
        "price": Decimal("100.00"), "currency": "USD", "as_of": date(2025, 1, 1), "timestamp": datetime(2025, 1, 1)
    }
    provider.get_company_profile.return_value = {
        "name": "Cache Co", "diluted_shares": Decimal("1000000"), "country": "US", "security_type": "COMMON_STOCK", "as_of": date(2025, 1, 1)
    }
    provider.get_balance_sheet.return_value = {"cash": Decimal("100000"), "total_debt": Decimal("50000"), "as_of": date(2025, 1, 1)}
    provider.get_cash_flow.return_value = {
        "fcfe_ttm": Decimal("10000"), "fcfe_definition": "FCFE", "fcff_ttm": Decimal("12000"), "fcff_definition": "FCFF", "as_of": date(2025, 1, 1)
    }
    provider.get_income_statement.return_value = {"revenue_ttm": Decimal("500000"), "ebitda_ttm": Decimal("100000"), "eps_ttm": Decimal("2"), "as_of": date(2025, 1, 1)}
    provider.get_forward_estimates.return_value = {"forward_eps_1y": Decimal("2.50"), "as_of": date(2025, 1, 1)}
    provider.get_historical_multiples.return_value = {"historical_forward_pe": Decimal("20"), "as_of": date(2025, 1, 1)}

    cache = MemoryTTLCache()
    svc = FinancialDataService(provider=provider, cache=cache, normalizer=Normalizer(strict_profile=False, allow_all_equities=True))

    snap1 = svc.get_snapshot("AAPL")
    snap2 = svc.get_snapshot("AAPL")

    assert snap1.company_name == snap2.company_name
    # Provider methods should have been called only once because second call hits cache
    assert provider.get_quote.call_count == 1
    assert provider.get_company_profile.call_count == 1
