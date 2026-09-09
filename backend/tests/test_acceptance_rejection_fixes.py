"""
Offline regression tests covering all acceptance rejection defects:
1. Missing cash/debt/CFO/capex/interest/tax isolation:
   - Must not become zero/default without explicit assumptions.
   - Disable dependent models when missing, preserve other models.
2. Single statement column selection:
   - Never dropna per row and mix years across columns.
   - Annual statement vs TTM metadata accurate.
3. Derived EBITDA / FCFE / FCFF provenance:
   - Not labelled analyst estimates.
   - Source type 'derived', formulas raw and capped growth, fiscal periods 0y/+1y explicit.
   - Forward EPS retained as analyst estimate.
4. Historical multiples:
   - Current trailingPE and current enterpriseToEbitda are NOT historical forward or averages.
   - Historical left unavailable; engines use explicit configured assumption defaults.
5. Currency mismatch:
   - Quote currency vs financial reporting currency mismatch safely handled.
6. Financial applicability:
   - Banks / financial institutions: EV/EBITDA, DCF, FCF Yield unavailable; Forward P/E preserved.
"""
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.config import DEFAULT_ASSUMPTIONS
from app.engines.composite import run_composite
from app.engines.dcf import run_dcf
from app.engines.ev_ebitda import run_ev_ebitda
from app.engines.fcf_yield import run_fcf_yield
from app.engines.forward_pe import run_forward_pe
from app.models.domain import (
    CompanyFinancialSnapshot,
    DataQuality,
    FinancialMetric,
    SourceType,
    ValuationAssumptions,
)
from app.providers.base import (
    BalanceSheetData,
    CashFlowData,
    CompanyProfileData,
    FinancialDataProvider,
    FinancialDataValidationError,
    ForwardEstimatesData,
    HistoricalMultiplesData,
    IncomeStatementData,
    QuoteData,
)
from app.providers.yfinance_provider import YFinanceProvider
from app.services.valuation_service import FinancialDataService, MemoryTTLCache, Normalizer, run_all_engines


def _metric(val, unit="USD", period="FY2024", source="test", source_type=SourceType.ACTUAL):
    return FinancialMetric(
        value=Decimal(str(val)),
        unit=unit,
        period=period,
        source=source,
        source_type=source_type,
        as_of=date(2024, 12, 31),
        confidence=1.0,
        is_estimated=False,
    )


# ----------------------------------------------------------------------
# 1. Missing cash/debt: disable EV/EBITDA & DCF, preserve Forward P/E & FCF yield
# ----------------------------------------------------------------------
def test_missing_cash_or_debt_disables_ev_and_dcf_preserves_pe_and_fcf():
    """Missing cash or debt leaves EV/EBITDA and DCF unavailable, preserving PE and FCF yield."""
    snapshot = CompanyFinancialSnapshot(
        ticker="NOCASH",
        company_name="No Cash Corp",
        currency="USD",
        current_price=_metric("100.00"),
        price_timestamp=datetime(2025, 1, 1, 16, 0, 0),
        diluted_shares=_metric("10000000", "shares"),
        cash=None,  # Missing cash!
        total_debt=None,  # Missing debt!
        forward_eps_1y=_metric("10.00", "USD/share", period="0y", source_type=SourceType.ANALYST_ESTIMATE),
        forward_ebitda_1y=_metric("200000000", period="0y", source_type=SourceType.DERIVED),
        forward_fcf_1y=_metric("80000000", period="0y", source_type=SourceType.DERIVED),
        forward_fcff_1y=_metric("85000000", period="0y", source_type=SourceType.DERIVED),
        sector="Technology",
        industry="Software",
        is_profitable=True,
    )

    results = run_all_engines(snapshot, DEFAULT_ASSUMPTIONS)

    # Forward P/E does not need cash or debt:
    assert results["forward_pe"].available is True
    assert results["forward_pe"].base.price_per_share > Decimal("0")

    # FCF Yield does not need cash or debt:
    assert results["fcf_yield"].available is True
    assert results["fcf_yield"].base.price_per_share > Decimal("0")

    # EV/EBITDA requires net debt:
    assert results["ev_ebitda"].available is False
    assert "cash and total debt are required" in results["ev_ebitda"].unavailable_reason.lower()

    # DCF requires net debt:
    assert results["dcf"].available is False
    assert "cash and total debt are required" in results["dcf"].unavailable_reason.lower()

    # Composite runs using the available models (PE and FCF yield):
    comp = run_composite(
        snapshot.current_price.value,
        results["forward_pe"],
        results["ev_ebitda"],
        results["fcf_yield"],
        results["dcf"],
        DEFAULT_ASSUMPTIONS,
    )
    assert comp.available is True
    assert sorted(comp.available_models) == ["fcf_yield", "forward_pe"]


def test_yfinance_provider_does_not_zero_default_missing_cash_or_debt():
    """Provider leaves cash and debt as None when not present in statement or info."""
    provider = YFinanceProvider()
    with patch("yfinance.Ticker") as mock_cls:
        mock_t = MagicMock()
        mock_t.info = {"quoteType": "EQUITY", "currency": "USD"}
        mock_t.balance_sheet = pd.DataFrame()  # empty balance sheet
        mock_cls.return_value = mock_t

        bs = provider.get_balance_sheet("EMPTYBS")
        assert bs["cash"] is None
        assert bs["total_debt"] is None
        assert bs["net_debt"] is None


# ----------------------------------------------------------------------
# 2. Missing CFO/capex/interest/tax: no zero-defaults
# ----------------------------------------------------------------------
def test_missing_cfo_or_capex_leaves_fcfe_and_fcff_none():
    """When CFO or Capex is missing, FCFE and FCFF are None, not defaulted to 0."""
    provider = YFinanceProvider()
    with patch("yfinance.Ticker") as mock_cls:
        mock_t = MagicMock()
        mock_t.info = {"quoteType": "EQUITY", "currency": "USD"}
        mock_t.cashflow = pd.DataFrame()  # empty cashflow
        mock_t.financials = pd.DataFrame()
        mock_t.earnings_estimate = None
        mock_t.revenue_estimate = None
        mock_cls.return_value = mock_t

        cf = provider.get_cash_flow("NOCF")
        assert cf["fcfe_ttm"] is None
        assert cf["fcff_ttm"] is None
        assert "unavailable" in cf["fcfe_definition"].lower()
        assert "unavailable" in cf["fcff_definition"].lower()


def test_company_with_debt_missing_interest_does_not_zero_default():
    """When company has debt and interest is missing, FCFF cannot be derived without assumption."""
    provider = YFinanceProvider()
    col = pd.Timestamp("2024-12-31")
    cf_df = pd.DataFrame({col: [100_000_000, -20_000_000]}, index=["Operating Cash Flow", "Capital Expenditure"])
    # Financials has no Interest Expense
    fin_df = pd.DataFrame({col: [0.21]}, index=["Tax Rate For Calcs"])

    with patch("yfinance.Ticker") as mock_cls:
        mock_t = MagicMock()
        mock_t.info = {"quoteType": "EQUITY", "currency": "USD", "totalDebt": 500_000_000}
        mock_t.cashflow = cf_df
        mock_t.financials = fin_df
        mock_t.earnings_estimate = None
        mock_t.revenue_estimate = None
        mock_cls.return_value = mock_t

        cf = provider.get_cash_flow("DEBTCO")
        # FCFE can be computed (CFO - capex):
        assert cf["fcfe_ttm"] == Decimal("80000000")
        # FCFF cannot be computed because interest is missing for a company with debt:
        assert cf["fcff_ttm"] is None
        assert "interest expense missing" in cf["fcff_definition"].lower()


def test_current_zero_debt_does_not_infer_historical_zero_interest():
    """Current zero debt does not prove historical interest was zero; missing interest leaves FCFF unavailable."""
    provider = YFinanceProvider()
    col = pd.Timestamp("2024-12-31")
    cf_df = pd.DataFrame({col: [100_000_000, -20_000_000]}, index=["Operating Cash Flow", "Capital Expenditure"])
    fin_df = pd.DataFrame()

    with patch("yfinance.Ticker") as mock_cls:
        mock_t = MagicMock()
        mock_t.info = {"quoteType": "EQUITY", "currency": "USD", "totalDebt": 0}
        mock_t.cashflow = cf_df
        mock_t.financials = fin_df
        mock_t.earnings_estimate = None
        mock_t.revenue_estimate = None
        mock_cls.return_value = mock_t

        cf = provider.get_cash_flow("NODEBT")
        assert cf["fcff_ttm"] is None
        assert "interest expense missing" in cf["fcff_definition"].lower()


# ----------------------------------------------------------------------
# 3. Single statement column selection: never dropna per row and mix years
# ----------------------------------------------------------------------
def test_statement_column_selection_does_not_mix_years():
    """A row missing in the latest column must NOT pick a prior year's value via dropna."""
    provider = YFinanceProvider()
    col_2024 = pd.Timestamp("2024-12-31")
    col_2023 = pd.Timestamp("2023-12-31")

    # In 2024: Cash exists, Total Debt is NaN!
    # In 2023: Cash exists, Total Debt exists!
    bs_df = pd.DataFrame(
        {
            col_2024: [50_000_000, float("nan")],
            col_2023: [40_000_000, 30_000_000],
        },
        index=["Cash Cash Equivalents And Short Term Investments", "Total Debt"],
    )

    with patch("yfinance.Ticker") as mock_cls:
        mock_t = MagicMock()
        mock_t.info = {"quoteType": "EQUITY", "currency": "USD"}
        mock_t.balance_sheet = bs_df
        mock_cls.return_value = mock_t

        bs = provider.get_balance_sheet("MIXTEST")
        # Cash from 2024:
        assert bs["cash"] == Decimal("50000000")
        # Debt in 2024 was NaN, so it must NOT pick 2023 debt (30M) via dropna:
        assert bs["total_debt"] is None
        assert bs["period"] == "FY2024"


def test_statement_period_metadata_accurate():
    """Annual statement receives FY<year> period while info fallback receives TTM."""
    provider = YFinanceProvider()
    col_2024 = pd.Timestamp("2024-12-31")
    cf_df = pd.DataFrame(
        {col_2024: [100_000_000, -20_000_000]},
        index=["Operating Cash Flow", "Capital Expenditure"],
    )

    with patch("yfinance.Ticker") as mock_cls:
        mock_t = MagicMock()
        mock_t.info = {"quoteType": "EQUITY", "currency": "USD", "totalDebt": 0}
        mock_t.cashflow = cf_df
        mock_t.financials = pd.DataFrame()
        mock_t.earnings_estimate = None
        mock_t.revenue_estimate = None
        mock_cls.return_value = mock_t

        cf = provider.get_cash_flow("ANNUAL")
        assert cf["period"] == "FY2024"
        assert "Annual fiscal year" in cf["notes"]

    # When statement is empty, info fallback is used -> period is TTM:
    with patch("yfinance.Ticker") as mock_cls:
        mock_t = MagicMock()
        mock_t.info = {
            "quoteType": "EQUITY",
            "currency": "USD",
            "totalDebt": 0,
            "operatingCashflow": 90_000_000,
            "freeCashflow": 70_000_000,
        }
        mock_t.cashflow = pd.DataFrame()
        mock_t.financials = pd.DataFrame()
        mock_t.earnings_estimate = None
        mock_t.revenue_estimate = None
        mock_cls.return_value = mock_t

        cf = provider.get_cash_flow("TTMFALLBACK")
        assert cf["period"] == "TTM"
        assert "TTM quote summary" in cf["notes"]


# ----------------------------------------------------------------------
# 4. Derived EBITDA / FCFE / FCFF carry source_type derived, not analyst_estimate
# ----------------------------------------------------------------------
def test_derived_forward_metrics_provenance_and_periods():
    """Forward EBITDA, FCFE, FCFF must carry source_type derived, formula notes, and 0y/+1y periods."""
    provider = YFinanceProvider()

    ee_df = pd.DataFrame(
        {"avg": [5.0, 6.0], "growth": [0.10, 0.15]},
        index=["0y", "+1y"],
    )
    re_df = pd.DataFrame(
        {"growth": [0.12, 0.14]},
        index=["0y", "+1y"],
    )

    with patch("yfinance.Ticker") as mock_cls:
        mock_t = MagicMock()
        mock_t.info = {
            "quoteType": "EQUITY",
            "currency": "USD",
            "ebitda": 100_000_000,
            "operatingCashflow": 80_000_000,
            "freeCashflow": 60_000_000,
            "totalDebt": 0,
            "lastFiscalYearEnd": 1735603200,  # 2024-12-31
            "nextFiscalYearEnd": 1767139200,  # 2025-12-31
        }
        col = pd.Timestamp("2024-12-31")
        mock_t.financials = pd.DataFrame(
            {col: [100_000_000, 10_000_000, 0.21]},
            index=["EBITDA", "Interest Expense", "Tax Rate For Calcs"],
        )
        mock_t.cashflow = pd.DataFrame(
            {col: [80_000_000, -20_000_000]},
            index=["Operating Cash Flow", "Capital Expenditure"],
        )
        mock_t.earnings_estimate = ee_df
        mock_t.revenue_estimate = re_df
        mock_cls.return_value = mock_t

        est = provider.get_forward_estimates("PROVTEST")

        # Forward EPS is an analyst estimate:
        assert est["forward_eps_1y_source_type"] == "analyst_estimate"
        assert est["forward_eps_1y_period"] == "0y"
        assert est["forward_eps_2y_source_type"] == "analyst_estimate"
        assert est["forward_eps_2y_period"] == "+1y"

        # Forward EBITDA is derived:
        assert est["forward_ebitda_1y_source_type"] == "derived"
        assert est["forward_ebitda_1y_period"] == "0y"
        assert "raw_growth" in est["forward_ebitda_1y_notes"]
        assert "capped_growth" in est["forward_ebitda_1y_notes"]
        assert "formula=" in est["forward_ebitda_1y_notes"]

        # Forward FCFE is derived:
        assert est["forward_fcfe_1y_source_type"] == "derived"
        assert est["forward_fcfe_1y_period"] == "0y"

        # Forward FCFF is derived:
        assert est["forward_fcff_1y_source_type"] == "derived"
        assert est["forward_fcff_1y_period"] == "0y"


def test_normalizer_propagates_derived_provenance_to_snapshot():
    """Normalizer preserves source_type derived on snapshot metrics."""
    today = date.today()

    quote = {"price": Decimal("150.00"), "currency": "USD", "as_of": today, "source": "test"}
    profile = {
        "name": "Test Co",
        "diluted_shares": Decimal("1000000"),
        "currency": "USD",
        "country": "US",
        "security_type": "COMMON_STOCK",
        "is_profitable": True,
        "as_of": today,
        "source": "test",
    }
    balance = {"cash": Decimal("1000000"), "total_debt": Decimal("500000"), "as_of": today, "source": "test"}
    cash_flow = {
        "fcfe_ttm": Decimal("100000"),
        "fcfe_ttm_source_type": "derived",
        "fcff_ttm": Decimal("120000"),
        "fcff_ttm_source_type": "derived",
        "as_of": today,
        "source": "test",
    }
    income = {"revenue_ttm": Decimal("1000000"), "ebitda_ttm": Decimal("200000"), "eps_ttm": Decimal("5"), "as_of": today, "source": "test"}
    estimates = {
        "forward_eps_1y": Decimal("6.00"),
        "forward_eps_1y_source_type": "analyst_estimate",
        "forward_eps_1y_period": "0y",
        "forward_ebitda_1y": Decimal("220000"),
        "forward_ebitda_1y_source_type": "derived",
        "forward_ebitda_1y_period": "0y",
        "forward_ebitda_1y_notes": "Derived forward EBITDA; raw_growth=0.10, capped_growth=0.10, formula=EBITDA*(1+g)",
        "forward_fcfe_1y": Decimal("110000"),
        "forward_fcfe_1y_source_type": "derived",
        "forward_fcfe_1y_period": "0y",
        "forward_fcff_1y": Decimal("130000"),
        "forward_fcff_1y_source_type": "derived",
        "forward_fcff_1y_period": "0y",
        "as_of": today,
        "source": "test",
    }
    multiples = {"historical_forward_pe": None, "historical_ev_ebitda": None, "as_of": today, "source": "test"}

    normalizer = Normalizer(strict_profile=False, allow_all_equities=True)
    snapshot = normalizer.normalize_provider_data(
        "TEST", quote, profile, balance, cash_flow, income, estimates, multiples
    )
    normalized = normalizer.normalize(snapshot)

    assert normalized.forward_eps_1y.source_type == SourceType.ANALYST_ESTIMATE
    assert normalized.forward_ebitda_1y.source_type == SourceType.DERIVED
    assert "formula=EBITDA*(1+g)" in normalized.forward_ebitda_1y.notes
    assert normalized.forward_fcf_1y.source_type == SourceType.DERIVED
    assert normalized.forward_fcff_1y.source_type == SourceType.DERIVED


# ----------------------------------------------------------------------
# 5. Historical multiples: trailing PE and enterpriseToEbitda are NOT historical
# ----------------------------------------------------------------------
def test_historical_multiples_leave_unavailable_and_engines_use_fallbacks():
    """Observed trailing multiples are NOT historical forward multiples; engines use configured fallbacks."""
    provider = YFinanceProvider()
    with patch("yfinance.Ticker") as mock_cls:
        mock_t = MagicMock()
        mock_t.info = {
            "quoteType": "EQUITY",
            "trailingPE": 45.0,  # High current trailing PE
            "enterpriseToEbitda": 30.0,  # High current EV/EBITDA
        }
        mock_cls.return_value = mock_t

        mult = provider.get_historical_multiples("TRAILTEST")
        assert mult["historical_forward_pe"] is None
        assert mult["historical_ev_ebitda"] is None

    # Verify that forward_pe and ev_ebitda engines use configured fallback, not the 45x/30x!
    snap = CompanyFinancialSnapshot(
        ticker="TRAILTEST",
        company_name="Trailing PE Test",
        currency="USD",
        current_price=_metric("100.00"),
        price_timestamp=datetime(2025, 1, 1, 16, 0, 0),
        diluted_shares=_metric("1000000", "shares"),
        cash=_metric("10000000"),
        total_debt=_metric("5000000"),
        forward_eps_1y=_metric("5.00", "USD/share", period="0y", source_type=SourceType.ANALYST_ESTIMATE),
        forward_ebitda_1y=_metric("20000000", period="0y", source_type=SourceType.DERIVED),
        historical_forward_pe=None,  # Not available from provider!
        historical_ev_ebitda=None,  # Not available from provider!
        sector="Technology",
        industry="Software",
        is_profitable=True,
    )

    pe_res = run_forward_pe(snap, DEFAULT_ASSUMPTIONS)
    assert pe_res.assumptions["multiple_source"] == "fallback"
    assert pe_res.assumptions["pe_source"] == SourceType.CONFIGURED_FALLBACK
    # Fallback base PE is from config, NOT 45.0x:
    assert Decimal(pe_res.assumptions["pe_multiple_base"]) == DEFAULT_ASSUMPTIONS.pe_target.base

    ev_res = run_ev_ebitda(snap, DEFAULT_ASSUMPTIONS)
    assert ev_res.assumptions["multiple_source"] == "fallback"
    assert ev_res.assumptions["source"] == SourceType.CONFIGURED_FALLBACK
    # Fallback base EV/EBITDA is from config, NOT 30.0x:
    assert Decimal(ev_res.assumptions["multiple_base"]) == DEFAULT_ASSUMPTIONS.ev_ebitda_multiple.base


# ----------------------------------------------------------------------
# 6. Currency mismatch protection
# ----------------------------------------------------------------------
def test_currency_mismatch_disables_models():
    """When quote currency is USD but financial reporting currency is EUR, models are disabled."""
    snap = CompanyFinancialSnapshot(
        ticker="ADRCO",
        company_name="Foreign ADR Corp",
        currency="USD",
        financial_currency="EUR",  # Mismatch!
        current_price=_metric("100.00", unit="USD"),
        price_timestamp=datetime(2025, 1, 1, 16, 0, 0),
        diluted_shares=_metric("1000000", "shares"),
        cash=_metric("10000000", unit="EUR"),
        total_debt=_metric("5000000", unit="EUR"),
        forward_eps_1y=_metric("5.00", "EUR/share", period="0y", source_type=SourceType.ANALYST_ESTIMATE),
        forward_ebitda_1y=_metric("20000000", unit="EUR", period="0y", source_type=SourceType.DERIVED),
        forward_fcf_1y=_metric("10000000", unit="EUR", period="0y", source_type=SourceType.DERIVED),
        forward_fcff_1y=_metric("12000000", unit="EUR", period="0y", source_type=SourceType.DERIVED),
        sector="Technology",
        industry="Software",
        is_profitable=True,
    )

    results = run_all_engines(snap, DEFAULT_ASSUMPTIONS)
    assert results["forward_pe"].available is False
    assert "currency mismatch" in results["forward_pe"].unavailable_reason.lower()
    assert results["ev_ebitda"].available is False
    assert "currency mismatch" in results["ev_ebitda"].unavailable_reason.lower()
    assert results["fcf_yield"].available is False
    assert "currency mismatch" in results["fcf_yield"].unavailable_reason.lower()
    assert results["dcf"].available is False
    assert "currency mismatch" in results["dcf"].unavailable_reason.lower()

    comp = run_composite(
        snap.current_price.value,
        results["forward_pe"],
        results["ev_ebitda"],
        results["fcf_yield"],
        results["dcf"],
        DEFAULT_ASSUMPTIONS,
    )
    assert comp.available is False
    assert "no complete positive" in comp.unavailable_reason.lower()


# ----------------------------------------------------------------------
# 7. Financial applicability: banks and insurance
# ----------------------------------------------------------------------
def test_bank_applicability_disables_ev_dcf_fcf_preserves_pe():
    """Banks have EV/EBITDA, DCF, and FCF Yield unavailable, but Forward P/E available."""
    bank_snap = CompanyFinancialSnapshot(
        ticker="WFC",
        company_name="Wells Fargo & Co",
        currency="USD",
        current_price=_metric("60.00"),
        price_timestamp=datetime(2025, 1, 1, 16, 0, 0),
        diluted_shares=_metric("3500000000", "shares"),
        cash=_metric("150000000000"),
        total_debt=_metric("200000000000"),
        forward_eps_1y=_metric("5.50", "USD/share", period="0y", source_type=SourceType.ANALYST_ESTIMATE),
        sector="Financial Services",
        industry="Banks - Diversified",
        is_profitable=True,
    )

    results = run_all_engines(bank_snap, DEFAULT_ASSUMPTIONS)

    assert results["forward_pe"].available is True
    assert results["forward_pe"].base.price_per_share > Decimal("0")

    assert results["ev_ebitda"].available is False
    assert "not applicable to banks" in results["ev_ebitda"].unavailable_reason.lower()

    assert results["dcf"].available is False
    assert "not applicable to banks" in results["dcf"].unavailable_reason.lower()

    assert results["fcf_yield"].available is False
    assert "not applicable to banks" in results["fcf_yield"].unavailable_reason.lower()

    comp = run_composite(
        bank_snap.current_price.value,
        results["forward_pe"],
        results["ev_ebitda"],
        results["fcf_yield"],
        results["dcf"],
        DEFAULT_ASSUMPTIONS,
    )
    assert comp.available is True
    assert comp.available_models == ["forward_pe"]
    assert comp.weights_used["forward_pe"] == Decimal("1.0000")
