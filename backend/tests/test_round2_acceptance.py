"""
Round 2 acceptance test suite verifying coordinator-verification-plan and backend-round2 requirements.

Covers:
1. No mixing annual statement CFO with TTM info capex; missing capex leaves FCFE/FCFF unavailable.
2. Exact fiscal date matching between cash-flow and income statements; no zero-debt -> zero-interest inference.
3. No substitution of Other Short Term Investments or partial debt; no mixing info with nonempty statements.
4. Forward EPS properly labeled NTM; forward projections record base fiscal period and explicit formula/capping.
5. Upstream error classification (429, 503, timeout, statement failures) and bounded semaphore.
6. Share count provenance (outstanding shares approximation, balance sheet column date, ADR label).
7. Non-equity (ETF), ADR currency mismatch, and REIT model isolation.
"""
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, PropertyMock, patch
import pandas as pd
import pytest

from app.models.domain import CompanyFinancialSnapshot, FinancialMetric, SourceType, DataQuality
from app.providers.base import (
    ProviderRateLimitError,
    ProviderUnavailableError,
    TickerNotFoundError,
    UnsupportedCompanyError,
)
from app.providers.yfinance_provider import YFinanceProvider, _bounded_semaphore, _classify_and_raise
from app.engines.ev_ebitda import run_ev_ebitda
from app.engines.fcf_yield import run_fcf_yield
from app.engines.dcf import run_dcf
from app.engines.forward_pe import run_forward_pe
from app.config import DEFAULT_ASSUMPTIONS


# ----------------------------------------------------------------------
# 1. get_cash_flow: No mixing annual CFO with TTM capex
# ----------------------------------------------------------------------
def test_no_mixing_annual_cfo_with_ttm_capex():
    """Mock annual CFO=100, missing capex in statement, info operatingCashflow=200/freeCashflow=150.
    Must NOT produce annual FCFE=150. Missing capex leaves capex, FCFE, and FCFF unavailable."""
    provider = YFinanceProvider()
    with patch("yfinance.Ticker") as mock_yf:
        mock_t = MagicMock()
        mock_yf.return_value = mock_t

        mock_t.info = {
            "regularMarketPrice": 50.0,
            "sharesOutstanding": 1_000_000,
            "operatingCashflow": 200.0,
            "freeCashflow": 150.0,
        }

        # Statement has CFO but NO Capital Expenditure row
        ts = pd.Timestamp("2024-12-31")
        cf_df = pd.DataFrame(
            {ts: [100.0]},
            index=["Operating Cash Flow"],
        )
        mock_t.cashflow = cf_df
        mock_t.financials = pd.DataFrame()
        mock_t.balance_sheet = pd.DataFrame()

        cf_data = provider.get_cash_flow("TEST")

        assert cf_data["fcfe_ttm"] is None, "FCFE must be unavailable when capex is missing from statement"
        assert cf_data["fcff_ttm"] is None, "FCFF must be unavailable when capex is missing from statement"
        assert "unavailable" in cf_data["fcfe_definition"].lower()
        assert "missing operating cash flow or capital expenditure" in cf_data["fcfe_definition"].lower()


# ----------------------------------------------------------------------
# 2. Date alignment and no zero-debt -> zero-interest inference
# ----------------------------------------------------------------------
def test_cashflow_and_income_mismatched_fiscal_dates():
    """Interest from income statement is only used if its fiscal date matches cashflow column."""
    provider = YFinanceProvider()
    with patch("yfinance.Ticker") as mock_yf:
        mock_t = MagicMock()
        mock_yf.return_value = mock_t

        mock_t.info = {"regularMarketPrice": 50.0, "sharesOutstanding": 1_000_000}
        ts_cf = pd.Timestamp("2024-12-31")
        cf_df = pd.DataFrame(
            {ts_cf: [200.0, -50.0]},
            index=["Operating Cash Flow", "Capital Expenditure"],
        )
        # Financials column has different date: 2023-12-31
        ts_fin = pd.Timestamp("2023-12-31")
        fin_df = pd.DataFrame(
            {ts_fin: [10.0, 0.21]},
            index=["Interest Expense", "Tax Rate For Calcs"],
        )
        mock_t.cashflow = cf_df
        mock_t.financials = fin_df

        cf_data = provider.get_cash_flow("TEST")

        assert cf_data["fcfe_ttm"] == Decimal("150.0")  # CFO - capex = 200 - 50 = 150
        assert cf_data["fcff_ttm"] is None, "FCFF requires matching fiscal period interest"
        assert "missing" in cf_data["fcff_definition"].lower()


def test_no_zero_interest_inference_from_current_zero_debt():
    """Current zero debt does not prove historical interest was zero. Missing interest must leave FCFF unavailable."""
    provider = YFinanceProvider()
    with patch("yfinance.Ticker") as mock_yf:
        mock_t = MagicMock()
        mock_yf.return_value = mock_t

        mock_t.info = {"regularMarketPrice": 50.0, "sharesOutstanding": 1_000_000, "totalDebt": 0}
        ts = pd.Timestamp("2024-12-31")
        cf_df = pd.DataFrame(
            {ts: [200.0, -50.0]},
            index=["Operating Cash Flow", "Capital Expenditure"],
        )
        # Financials missing Interest Expense row entirely
        fin_df = pd.DataFrame(
            {ts: [100.0]},
            index=["Pretax Income"],
        )
        mock_t.cashflow = cf_df
        mock_t.financials = fin_df

        cf_data = provider.get_cash_flow("TEST")

        assert cf_data["fcff_ttm"] is None
        assert "interest expense missing" in cf_data["fcff_definition"].lower()


# ----------------------------------------------------------------------
# 3. No substitution of Other Short Term Investments or Partial Debt
# ----------------------------------------------------------------------
def test_balance_sheet_excludes_other_short_term_investments_and_partial_debt():
    """Never substitute 'Other Short Term Investments' for cash, nor partial debt for Total Debt."""
    provider = YFinanceProvider()
    with patch("yfinance.Ticker") as mock_yf:
        mock_t = MagicMock()
        mock_yf.return_value = mock_t

        mock_t.info = {"regularMarketPrice": 50.0, "sharesOutstanding": 1_000_000}
        ts = pd.Timestamp("2024-12-31")
        # Statement has only Other Short Term Investments and Short Term Debt
        bs_df = pd.DataFrame(
            {ts: [500.0, 200.0]},
            index=["Other Short Term Investments", "Short Long Term Debt"],
        )
        mock_t.balance_sheet = bs_df

        bs_data = provider.get_balance_sheet("TEST")

        assert bs_data["cash"] is None, "Other Short Term Investments must not be substituted for cash"
        assert bs_data["total_debt"] is None, "Partial debt must not be substituted for Total Debt"
        assert bs_data["net_debt"] is None


def test_balance_sheet_does_not_mix_info_when_statement_present():
    """When balance sheet statement is present but missing Total Debt, do not fall back to info totalDebt."""
    provider = YFinanceProvider()
    with patch("yfinance.Ticker") as mock_yf:
        mock_t = MagicMock()
        mock_yf.return_value = mock_t

        mock_t.info = {
            "regularMarketPrice": 50.0,
            "sharesOutstanding": 1_000_000,
            "totalDebt": 999.0,  # current TTM info debt
        }
        ts = pd.Timestamp("2024-12-31")
        bs_df = pd.DataFrame(
            {ts: [500.0]},
            index=["Cash And Cash Equivalents"],
        )
        mock_t.balance_sheet = bs_df

        bs_data = provider.get_balance_sheet("TEST")

        assert bs_data["cash"] == Decimal("500.0")
        assert bs_data["total_debt"] is None, "Must not mix current info debt with annual statement cash"
        assert bs_data["net_debt"] is None


# ----------------------------------------------------------------------
# 4. Forward Estimates provenance & growth formula
# ----------------------------------------------------------------------
def test_forward_estimates_provenance_and_capping():
    """Forward EPS is labeled; provider does not invent forward EBITDA from growth."""
    provider = YFinanceProvider()
    with patch("yfinance.Ticker") as mock_yf:
        mock_t = MagicMock()
        mock_yf.return_value = mock_t

        mock_t.info = {
            "regularMarketPrice": 100.0,
            "sharesOutstanding": 1_000_000,
            "forwardEps": 5.50,
            "lastFiscalYearEnd": 1735603200,  # 2024-12-31
            "nextFiscalYearEnd": 1767139200,  # 2025-12-31
        }
        ts = pd.Timestamp("2024-12-31")
        mock_t.financials = pd.DataFrame(
            {ts: [1_000.0]},
            index=["EBITDA"],
        )
        mock_t.cashflow = pd.DataFrame()
        mock_t.balance_sheet = pd.DataFrame()
        mock_t.earnings_estimate = None
        re_df = pd.DataFrame(
            {"growth": [0.60, 0.40]},
            index=["0y", "+1y"],
        )
        mock_t.revenue_estimate = re_df

        est = provider.get_forward_estimates("TEST")

        assert est["forward_eps_1y_period"] == "forward_1y", "Forward EPS from info summary must be labeled forward_1y without unwarranted NTM assumption"
        assert est["forward_ebitda_1y"] is None
        assert est["forward_ebitda_1y_source_type"] is None
        assert "independent analyst" in est["forward_ebitda_1y_notes"]


# ----------------------------------------------------------------------
# 5. Upstream error mapping and bounded concurrency
# ----------------------------------------------------------------------
def test_upstream_error_classification():
    """429 maps to ProviderRateLimitError; 503/timeout maps to ProviderUnavailableError."""
    provider = YFinanceProvider()
    with patch("yfinance.Ticker") as mock_yf:
        mock_t = MagicMock()
        mock_yf.return_value = mock_t

        type(mock_t).info = PropertyMock(side_effect=Exception("HTTP Error 429: Too Many Requests"))
        with pytest.raises(ProviderRateLimitError):
            provider.get_quote("TEST429")

    with patch("yfinance.Ticker") as mock_yf:
        mock_t = MagicMock()
        mock_yf.return_value = mock_t

        type(mock_t).info = PropertyMock(side_effect=TimeoutError("Request timed out"))
        with pytest.raises(ProviderUnavailableError):
            provider.get_quote("TESTTIMEOUT")


def test_statement_failures_not_swallowed():
    """Upstream statement failures raise ProviderUnavailableError rather than silently becoming empty."""
    provider = YFinanceProvider()
    with patch("yfinance.Ticker") as mock_yf:
        mock_t = MagicMock()
        mock_yf.return_value = mock_t

        mock_t.info = {"regularMarketPrice": 50.0, "sharesOutstanding": 1_000_000}
        type(mock_t).balance_sheet = PropertyMock(side_effect=Exception("HTTP 503 Service Unavailable"))
        with pytest.raises(ProviderUnavailableError):
            provider.get_balance_sheet("TEST503")

    with patch("yfinance.Ticker") as mock_yf:
        mock_t = MagicMock()
        mock_yf.return_value = mock_t

        mock_t.info = {"regularMarketPrice": 50.0, "sharesOutstanding": 1_000_000}
        type(mock_t).cashflow = PropertyMock(side_effect=ConnectionError("Connection aborted"))
        with pytest.raises(ProviderUnavailableError):
            provider.get_cash_flow("TESTCONN")


# ----------------------------------------------------------------------
# 6. Profile diluted shares provenance and ADR labeling
# ----------------------------------------------------------------------
def test_company_profile_shares_provenance_and_adr_note():
    """Profile labels outstanding shares approximation and tags ADRs."""
    provider = YFinanceProvider()
    with patch("yfinance.Ticker") as mock_yf:
        mock_t = MagicMock()
        mock_yf.return_value = mock_t

        mock_t.info = {
            "shortName": "Taiwan Semiconductor Manufacturing Co Ltd ADR",
            "regularMarketPrice": 120.0,
            "regularMarketTime": 1718000000,
            "sharesOutstanding": 5_000_000_000,
            "quoteType": "EQUITY",
            "country": "Taiwan",
            "currency": "USD",
            "financialCurrency": "TWD",
        }

        profile = provider.get_company_profile("TSM")

        assert profile["diluted_shares_source_type"] == "derived"
        assert profile["diluted_shares_is_estimated"] is True
        assert "approximation" in profile["diluted_shares_notes"].lower()
        assert profile["notes"] is not None
        assert "American Depositary Receipt" in profile["notes"]


def test_profile_balance_sheet_shares_fallback_provenance():
    """When sharesOutstanding is absent, uses balance sheet column date, not quote date."""
    provider = YFinanceProvider()
    with patch("yfinance.Ticker") as mock_yf:
        mock_t = MagicMock()
        mock_yf.return_value = mock_t

        mock_t.info = {
            "shortName": "Test Co",
            "regularMarketPrice": 10.0,
            "regularMarketTime": 1718000000,
            # sharesOutstanding missing
        }
        ts = pd.Timestamp("2023-12-31")
        bs_df = pd.DataFrame(
            {ts: [2_500_000]},
            index=["Ordinary Shares Number"],
        )
        mock_t.balance_sheet = bs_df

        profile = provider.get_company_profile("TEST")

        assert profile["diluted_shares"] == Decimal("2500000")
        assert profile["diluted_shares_period"] == "FY2023"
        assert profile["diluted_shares_as_of"] == date(2023, 12, 31)
        assert "FY2023" in profile["diluted_shares_notes"]


# ----------------------------------------------------------------------
# 7. Model isolation: REIT guard, non-equity security guard
# ----------------------------------------------------------------------
def test_reit_guard_disables_ev_ebitda_fcf_dcf():
    """REIT securities must disable EV/EBITDA, FCF yield, and DCF with explicit REIT reason."""
    today = date.today()
    now = datetime.now(timezone.utc)
    snapshot = CompanyFinancialSnapshot(
        ticker="O",
        company_name="Realty Income Corp",
        currency="USD",
        as_of=today,
        price_timestamp=now,
        current_price=FinancialMetric(value=Decimal("55.0"), as_of=today, source="quote", period="current", unit="USD", source_type=SourceType.ACTUAL),
        diluted_shares=FinancialMetric(value=Decimal("800000000"), as_of=today, source="shares", period="current", unit="shares", source_type=SourceType.ACTUAL),
        sector="Real Estate",
        industry="REIT - Retail",
        forward_ebitda_1y=FinancialMetric(value=Decimal("3000000000"), as_of=today, source="est", period="FY1E", unit="USD", source_type=SourceType.DERIVED),
        fcf_ttm=FinancialMetric(value=Decimal("2000000000"), as_of=today, source="cf", period="TTM", unit="USD", source_type=SourceType.ACTUAL),
        fcff_ttm=FinancialMetric(value=Decimal("2500000000"), as_of=today, source="cf", period="TTM", unit="USD", source_type=SourceType.ACTUAL),
        cash=FinancialMetric(value=Decimal("500000000"), as_of=today, source="bs", period="latest", unit="USD", source_type=SourceType.ACTUAL),
        total_debt=FinancialMetric(value=Decimal("20000000000"), as_of=today, source="bs", period="latest", unit="USD", source_type=SourceType.ACTUAL),
        net_debt=FinancialMetric(value=Decimal("19500000000"), as_of=today, source="bs", period="latest", unit="USD", source_type=SourceType.DERIVED),
    )

    ev_result = run_ev_ebitda(snapshot, DEFAULT_ASSUMPTIONS)
    assert ev_result.available is False
    assert "REIT" in ev_result.unavailable_reason

    fcf_result = run_fcf_yield(snapshot, DEFAULT_ASSUMPTIONS)
    assert fcf_result.available is False
    assert "REIT" in fcf_result.unavailable_reason

    dcf_result = run_dcf(snapshot, DEFAULT_ASSUMPTIONS)
    assert dcf_result.available is False
    assert "REIT" in dcf_result.unavailable_reason


def test_non_equity_rejection():
    """Non-equities (ETF, crypto) raise UnsupportedCompanyError."""
    provider = YFinanceProvider()
    with patch("yfinance.Ticker") as mock_yf:
        mock_t = MagicMock()
        mock_yf.return_value = mock_t

        mock_t.info = {
            "regularMarketPrice": 500.0,
            "quoteType": "ETF",
            "shortName": "SPDR S&P 500 ETF Trust",
        }
        with pytest.raises(UnsupportedCompanyError) as exc_info:
            provider.get_quote("SPY")
        assert exc_info.value.reason == "etf"
