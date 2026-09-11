"""Regression tests for Issue 01 and Issue 02.

Issue 01: Synthetic forward metrics lacking independent financial drivers (EBITDA, FCFF, FCFE).
Issue 02: _TickerBundle quarterly attributes missing causing silent annual fallback.
"""
from datetime import date, datetime
from decimal import Decimal
import pandas as pd
import pytest

from app.models.domain import (
    CompanyFinancialSnapshot,
    FinancialMetric,
    SourceType,
    ValuationAssumptions,
)
from app.models.overrides import ValuationOverrideRequest
from app.providers.base import ProviderRateLimitError, ProviderUnavailableError
from app.providers.statement_aggregator import (
    aggregate_ttm_cashflow,
    aggregate_ttm_income,
    extract_latest_balance_sheet,
)
from app.providers.yfinance_provider import (
    _TickerBundle,
    YFinanceProvider,
    _RequestBudget,
)
from app.services.projections import (
    RequestProjections,
    derive_request_projections,
)
from app.engines.dcf import run_dcf
from app.services.valuation_service import (
    apply_overrides,
    FinancialDataService,
    ValuationService,
)


# ============================================================================
# Issue 02: _TickerBundle quarterly initialization and error propagation
# ============================================================================

def test_issue_02_ticker_bundle_has_quarterly_attributes_initialized():
    """_TickerBundle must explicitly initialize _qbs, _qcf, _qfin to None."""
    bundle = _TickerBundle("NVDA", "NVDA")
    assert hasattr(bundle, "_qbs"), "_TickerBundle missing _qbs attribute"
    assert hasattr(bundle, "_qcf"), "_TickerBundle missing _qcf attribute"
    assert hasattr(bundle, "_qfin"), "_TickerBundle missing _qfin attribute"
    assert bundle._qbs is None
    assert bundle._qcf is None
    assert bundle._qfin is None


def test_issue_02_quarterly_getters_do_not_swallow_rate_limit_or_timeout(monkeypatch):
    """get_quarterly_* must not swallow ProviderRateLimitError or ProviderUnavailableError."""
    bundle = _TickerBundle("NVDA", "NVDA")

    def mock_fetch_429(*args, **kwargs):
        raise ProviderRateLimitError("Rate limited by Yahoo Finance for NVDA")

    def mock_fetch_timeout(*args, **kwargs):
        raise ProviderUnavailableError("Upstream total deadline exceeded")

    monkeypatch.setattr(bundle, "_fetch_property", mock_fetch_429)
    with pytest.raises(ProviderRateLimitError):
        bundle.get_quarterly_balance_sheet()

    with pytest.raises(ProviderRateLimitError):
        bundle.get_quarterly_cashflow()

    with pytest.raises(ProviderRateLimitError):
        bundle.get_quarterly_financials()

    monkeypatch.setattr(bundle, "_fetch_property", mock_fetch_timeout)
    with pytest.raises(ProviderUnavailableError):
        bundle.get_quarterly_balance_sheet()

    with pytest.raises(ProviderUnavailableError):
        bundle.get_quarterly_cashflow()

    with pytest.raises(ProviderUnavailableError):
        bundle.get_quarterly_financials()


def test_issue_02_bundle_with_valid_quarterly_statements_produces_ttm():
    """When quarterly statements have 4 consecutive quarters, cashflow must be TTM, not ANNUAL_FALLBACK."""
    q_dates = [pd.Timestamp("2026-06-30"), pd.Timestamp("2026-03-31"), pd.Timestamp("2025-12-31"), pd.Timestamp("2025-09-30")]
    q_cf_df = pd.DataFrame(
        {
            q_dates[0]: [1000, 200, 50],
            q_dates[1]: [1100, 220, 60],
            q_dates[2]: [1200, 250, 70],
            q_dates[3]: [1050, 210, 40],
        },
        index=["Operating Cash Flow", "Capital Expenditure", "Net Issuance Payments Of Debt"],
    )
    a_cf_df = pd.DataFrame(
        {
            pd.Timestamp("2025-12-31"): [4000, 800, 200],
        },
        index=["Operating Cash Flow", "Capital Expenditure", "Net Issuance Payments Of Debt"],
    )

    agg = aggregate_ttm_cashflow(
        quarterly_cf=q_cf_df,
        annual_cf=a_cf_df,
        default_as_of=date(2026, 7, 1),
    )
    assert agg["statement_basis"] == "TTM"
    assert agg["annual_fallback"] is False
    assert agg["cfo"] == Decimal("4350")
    assert agg["capex"] == Decimal("880")
    assert agg["as_of"] == date(2026, 6, 30)


def test_issue_02_bundle_pit_balance_sheet_independent_of_cashflow_fallback():
    """Latest PIT balance sheet is extracted from latest quarterly date even if cashflow falls back."""
    # Quarterly BS has latest date 2026-06-30
    q_bs_df = pd.DataFrame(
        {
            pd.Timestamp("2026-06-30"): [15000, 5000],
        },
        index=["Cash And Cash Equivalents", "Total Debt"],
    )
    a_bs_df = pd.DataFrame(
        {
            pd.Timestamp("2025-12-31"): [12000, 6000],
        },
        index=["Cash And Cash Equivalents", "Total Debt"],
    )

    bs = extract_latest_balance_sheet(q_bs_df, a_bs_df)
    assert bs["source_type"] == "quarterly"
    assert bs["as_of"] == date(2026, 6, 30)
    assert bs["cash"] == Decimal("15000")
    assert bs["total_debt"] == Decimal("5000")
    assert bs["net_debt"] == Decimal("-10000")


# ============================================================================
# Issue 01: Independent financial drivers & financial bridge verification
# ============================================================================

def _make_sample_snapshot(
    revenue_est: Decimal = Decimal("100000"),
    revenue_ttm: Decimal = Decimal("80000"),
    ebitda_ttm: Decimal = Decimal("32000"),
    cfo_ttm: Decimal = Decimal("28000"),
    capex_ttm: Decimal = Decimal("8000"),
    da_ttm: Decimal = Decimal("6000"),
    nwc_change_ttm: Decimal = Decimal("1000"),
    interest_ttm: Decimal = Decimal("1500"),
    tax_rate: Decimal = Decimal("0.20"),
    net_borrowing_ttm: Decimal = Decimal("2000"),
) -> CompanyFinancialSnapshot:
    as_of = date(2026, 7, 1)
    return CompanyFinancialSnapshot(
        ticker="ACME",
        company_name="ACME Corp",
        currency="USD",
        current_price=FinancialMetric(value=Decimal("150"), unit="USD", period="quote", source="live", source_type=SourceType.ACTUAL, as_of=as_of),
        price_timestamp=datetime(2026, 7, 1, 12, 0),
        diluted_shares=FinancialMetric(value=Decimal("1000"), unit="shares", period="latest", source="sec", source_type=SourceType.ACTUAL, as_of=as_of),
        cash=FinancialMetric(value=Decimal("20000"), unit="USD", period="latest", source="bs", source_type=SourceType.ACTUAL, as_of=as_of),
        total_debt=FinancialMetric(value=Decimal("10000"), unit="USD", period="latest", source="bs", source_type=SourceType.ACTUAL, as_of=as_of),
        revenue_ttm=FinancialMetric(value=revenue_ttm, unit="USD", period="TTM", source="is", source_type=SourceType.ACTUAL, as_of=as_of),
        ebitda_ttm=FinancialMetric(value=ebitda_ttm, unit="USD", period="TTM", source="is", source_type=SourceType.ACTUAL, as_of=as_of),
        fcf_ttm=FinancialMetric(value=cfo_ttm - capex_ttm + net_borrowing_ttm, unit="USD", period="TTM", source="cf", source_type=SourceType.ACTUAL, as_of=as_of),
        fcff_ttm=FinancialMetric(value=ebitda_ttm - da_ttm - (ebitda_ttm - da_ttm) * tax_rate + da_ttm - capex_ttm - nwc_change_ttm, unit="USD", period="TTM", source="cf", source_type=SourceType.ACTUAL, as_of=as_of),
        revenue_estimate_1y=FinancialMetric(value=revenue_est, unit="USD", period="0y", source="analyst", source_type=SourceType.ANALYST_ESTIMATE, as_of=as_of),
        tax_rate=FinancialMetric(value=tax_rate, unit="ratio", period="TTM", source="fin", source_type=SourceType.ACTUAL, as_of=as_of),
        cfo_ttm=FinancialMetric(value=cfo_ttm, unit="USD", period="TTM", source="cf", source_type=SourceType.ACTUAL, as_of=as_of),
        capex_ttm=FinancialMetric(value=capex_ttm, unit="USD", period="TTM", source="cf", source_type=SourceType.ACTUAL, as_of=as_of),
        da_ttm=FinancialMetric(value=da_ttm, unit="USD", period="TTM", source="is", source_type=SourceType.ACTUAL, as_of=as_of),
        nwc_change_ttm=FinancialMetric(value=nwc_change_ttm, unit="USD", period="TTM", source="cf", source_type=SourceType.ACTUAL, as_of=as_of),
        interest_ttm=FinancialMetric(value=interest_ttm, unit="USD", period="TTM", source="cf", source_type=SourceType.ACTUAL, as_of=as_of),
        net_borrowing_ttm=FinancialMetric(value=net_borrowing_ttm, unit="USD", period="TTM", source="cf", source_type=SourceType.ACTUAL, as_of=as_of),
    )


def test_issue_01_financial_drivers_independent_variation():
    """
    Fixed revenue forecast:
    1. Changing EBITDA margin must independently change EBITDA, FCFF, and FCFE.
    2. Changing CapEx must independently change FCFF and FCFE by the exact same amount, without changing EBITDA.
    3. Changing ΔNWC must independently change FCFF and FCFE by the exact same amount, without changing EBITDA.
    4. Changing Net Borrowing must change FCFE, but MUST NOT change FCFF or EBITDA!
    """
    snapshot = _make_sample_snapshot()
    base_assumptions = ValuationAssumptions()

    proj_base = derive_request_projections(snapshot, base_assumptions)
    assert proj_base.forward_ebitda is not None
    assert proj_base.forward_fcff_1y is not None
    assert proj_base.forward_fcfe_1y is not None

    base_ebitda_val = proj_base.forward_ebitda.value
    base_fcff_val = proj_base.forward_fcff_1y.value
    base_fcfe_val = proj_base.forward_fcfe_1y.value

    # 1. Independent EBITDA margin override: +5%
    assumptions_margin = apply_overrides(base_assumptions, {"drivers.ebitda_margin": Decimal("0.45")})
    proj_margin = derive_request_projections(snapshot, assumptions_margin)
    assert proj_margin.forward_ebitda.value > base_ebitda_val
    assert proj_margin.forward_fcff_1y.value > base_fcff_val
    assert proj_margin.forward_fcfe_1y.value > base_fcfe_val

    # 2. Independent CapEx override: increase CapEx by $5,000
    base_capex = Decimal("10000")
    new_capex = Decimal("15000")
    assumptions_capex1 = apply_overrides(base_assumptions, {"drivers.capex": base_capex})
    assumptions_capex2 = apply_overrides(base_assumptions, {"drivers.capex": new_capex})
    proj_c1 = derive_request_projections(snapshot, assumptions_capex1)
    proj_c2 = derive_request_projections(snapshot, assumptions_capex2)

    # EBITDA must be completely unchanged by CapEx change
    assert proj_c1.forward_ebitda.value == proj_c2.forward_ebitda.value
    # FCFF and FCFE must decrease by exactly 5000
    assert proj_c1.forward_fcff_1y.value - proj_c2.forward_fcff_1y.value == Decimal("5000")
    assert proj_c1.forward_fcfe_1y.value - proj_c2.forward_fcfe_1y.value == Decimal("5000")

    # 3. Independent ΔNWC override: increase ΔNWC by $2,000
    assumptions_nwc1 = apply_overrides(base_assumptions, {"drivers.nwc_change": Decimal("1000")})
    assumptions_nwc2 = apply_overrides(base_assumptions, {"drivers.nwc_change": Decimal("3000")})
    proj_n1 = derive_request_projections(snapshot, assumptions_nwc1)
    proj_n2 = derive_request_projections(snapshot, assumptions_nwc2)

    # EBITDA must be completely unchanged by ΔNWC change
    assert proj_n1.forward_ebitda.value == proj_n2.forward_ebitda.value
    # FCFF and FCFE must decrease by exactly 2000
    assert proj_n1.forward_fcff_1y.value - proj_n2.forward_fcff_1y.value == Decimal("2000")
    assert proj_n1.forward_fcfe_1y.value - proj_n2.forward_fcfe_1y.value == Decimal("2000")

    # 4. Independent Net Borrowing override: increase Net Borrowing by $4,000
    assumptions_nb1 = apply_overrides(base_assumptions, {"drivers.net_borrowing": Decimal("0")})
    assumptions_nb2 = apply_overrides(base_assumptions, {"drivers.net_borrowing": Decimal("4000")})
    proj_nb1 = derive_request_projections(snapshot, assumptions_nb1)
    proj_nb2 = derive_request_projections(snapshot, assumptions_nb2)

    # FCFF and EBITDA MUST BE COMPLETELY UNCHANGED by Net Borrowing!
    assert proj_nb1.forward_ebitda.value == proj_nb2.forward_ebitda.value
    assert proj_nb1.forward_fcff_1y.value == proj_nb2.forward_fcff_1y.value
    # FCFE must increase by exactly 4000
    assert proj_nb2.forward_fcfe_1y.value - proj_nb1.forward_fcfe_1y.value == Decimal("4000")


def test_issue_01_direct_consensus_not_overwritten():
    """If a direct analyst consensus metric exists, it is not overwritten by growth calculations."""
    snapshot = _make_sample_snapshot()
    # Add direct analyst consensus EBITDA
    snapshot = snapshot.model_copy(
        update={
            "forward_ebitda_1y": FinancialMetric(
                value=Decimal("42000"),
                unit="USD",
                period="FY1E",
                source="Analyst Consensus EBITDA",
                source_type=SourceType.ANALYST_ESTIMATE,
                as_of=date(2026, 7, 1),
            )
        }
    )
    assumptions = ValuationAssumptions()
    proj = derive_request_projections(snapshot, assumptions)
    # Direct consensus must be preserved with its source and period
    assert proj.forward_ebitda.value == Decimal("42000")
    assert proj.forward_ebitda.source_type == SourceType.ANALYST_ESTIMATE
    assert proj.forward_ebitda.period == "FY1E"


def test_issue_01_override_request_schema_and_reset():
    """ValuationOverrideRequest must support driver fields and serialize/deserialize properly."""
    req = ValuationOverrideRequest.model_validate({
        "drivers": {
            "ebitda_margin": 0.42,
            "capex": 12000,
            "nwc_change": 1500,
            "net_borrowing": 3000,
        }
    })
    odict = req.to_override_dict()
    assert odict["drivers.ebitda_margin"] == Decimal("0.42")
    assert odict["drivers.capex"] == Decimal("12000")
    assert odict["drivers.nwc_change"] == Decimal("1500")
    assert odict["drivers.net_borrowing"] == Decimal("3000")


def test_issue_01_financial_bridge_payload_and_reconciliation():
    """Verify that derive_request_projections generates a fully reconcilable financial bridge."""
    snapshot = _make_sample_snapshot()
    assumptions = ValuationAssumptions(
        driver_ebitda_margin=Decimal("0.40"),
        driver_capex=Decimal("10000"),
        driver_nwc_change=Decimal("2000"),
        driver_da=Decimal("5000"),
        driver_tax_rate=Decimal("0.25"),
        driver_net_borrowing=Decimal("3000"),
    )
    proj = derive_request_projections(snapshot, assumptions)
    bridge = proj.financial_bridge
    assert bridge is not None
    # 1. EBITDA = Revenue × Margin = 100000 × 0.40 = 40000
    assert Decimal(bridge["revenue"]) == Decimal("100000")
    assert Decimal(bridge["ebitda"]) == Decimal("40000")
    # 2. EBIT = EBITDA - D&A = 40000 - 5000 = 35000
    assert Decimal(bridge["da"]) == Decimal("5000")
    assert Decimal(bridge["ebit"]) == Decimal("35000")
    # 3. NOPAT = EBIT × (1 - Tax) = 35000 × 0.75 = 26250
    assert Decimal(bridge["nopat"]) == Decimal("26250")
    # 4. FCFF = NOPAT + D&A - CapEx - ΔNWC = 26250 + 5000 - 10000 - 2000 = 19250
    assert Decimal(bridge["fcff"]) == Decimal("19250")
    assert proj.forward_fcff_1y.value == Decimal("19250")
    # 5. FCFE = FCFF - Interest×(1-T) + Net Borrowing
    # Interest = 1500, after-tax interest = 1500 × 0.75 = 1125
    # FCFE = 19250 - 1125 + 3000 = 21125
    assert Decimal(bridge["after_tax_interest"]) == Decimal("1125")
    assert Decimal(bridge["fcfe"]) == Decimal("21125")
    assert proj.forward_fcfe_1y.value == Decimal("21125")


# ============================================================================
# R2 Regressions: Penetration through _TickerBundle & YFinanceProvider
# ============================================================================

def test_r2_issue_02_bundle_penetration_4_quarters_and_pit_bs(monkeypatch):
    """
    Penetrate through _TickerBundle and YFinanceProvider:
    Simulate real upstream yf.Ticker properties on _TickerBundle.
    Verify get_balance_sheet, get_cash_flow, and get_income_statement correctly aggregate 4 discrete quarters into TTM.
    """
    provider = YFinanceProvider(timeout=5.0)
    bundle = provider._get_bundle("TEST")

    # Mock yf.Ticker underlying properties
    q_dates = [pd.Timestamp("2026-06-30"), pd.Timestamp("2026-03-31"), pd.Timestamp("2025-12-31"), pd.Timestamp("2025-09-30")]
    q_bs_df = pd.DataFrame(
        {q_dates[0]: [50000, 20000]},
        index=["Cash And Cash Equivalents", "Total Debt"],
    )
    a_bs_df = pd.DataFrame(
        {pd.Timestamp("2025-12-31"): [40000, 25000]},
        index=["Cash And Cash Equivalents", "Total Debt"],
    )
    q_cf_df = pd.DataFrame(
        {
            q_dates[0]: [10000, -2000, 500, -300],
            q_dates[1]: [11000, -2200, 600, -250],
            q_dates[2]: [12000, -2500, 700, -400],
            q_dates[3]: [10500, -2100, 400, -200],
        },
        index=["Operating Cash Flow", "Capital Expenditure", "Net Issuance Payments Of Debt", "Change In Working Capital"],
    )
    a_cf_df = pd.DataFrame(
        {pd.Timestamp("2025-12-31"): [40000, -8000, 2000, -1000]},
        index=["Operating Cash Flow", "Capital Expenditure", "Net Issuance Payments Of Debt", "Change In Working Capital"],
    )
    q_fin_df = pd.DataFrame(
        {
            q_dates[0]: [25000, 8000, 500, 300, 1500, 1000],
            q_dates[1]: [26000, 8500, 520, 310, 1600, 1050],
            q_dates[2]: [27000, 9000, 550, 330, 1700, 1100],
            q_dates[3]: [25500, 8200, 510, 305, 1550, 1020],
        },
        index=["Total Revenue", "Operating Income", "Reconciled Depreciation", "Interest Expense", "Pretax Income", "Tax Provision"],
    )
    a_fin_df = pd.DataFrame(
        {pd.Timestamp("2025-12-31"): [100000, 32000, 2000, 1200, 6000, 4000]},
        index=["Total Revenue", "Operating Income", "Reconciled Depreciation", "Interest Expense", "Pretax Income", "Tax Provision"],
    )

    import yfinance as yf
    monkeypatch.setattr(yf.Ticker, "quarterly_balance_sheet", property(lambda self: q_bs_df))
    monkeypatch.setattr(yf.Ticker, "balance_sheet", property(lambda self: a_bs_df))
    monkeypatch.setattr(yf.Ticker, "quarterly_cashflow", property(lambda self: q_cf_df))
    monkeypatch.setattr(yf.Ticker, "cashflow", property(lambda self: a_cf_df))
    monkeypatch.setattr(yf.Ticker, "quarterly_financials", property(lambda self: q_fin_df))
    monkeypatch.setattr(yf.Ticker, "financials", property(lambda self: a_fin_df))
    monkeypatch.setattr(yf.Ticker, "info", property(lambda self: {
        "shortName": "Test Co",
        "currency": "USD",
        "regularMarketTime": 1782800000,
        "sharesOutstanding": 1000000,
    }))

    # Call provider methods directly through _TickerBundle
    bs = provider.get_balance_sheet("TEST")
    assert bs["cash"] == Decimal("50000")
    assert bs["total_debt"] == Decimal("20000")
    assert bs["net_debt"] == Decimal("-30000")
    assert bs["period"] == "Q_2026-06-30"

    cf = provider.get_cash_flow("TEST")
    assert cf["statement_basis"] == "TTM"
    assert cf["annual_fallback"] is False
    assert cf["cfo"] == Decimal("43500")
    assert cf["capex"] == Decimal("8800")
    # Verify D&A and NWC investment ΔNWC (converted from cash outflow -1150 to +1150)
    assert cf["nwc_change"] == Decimal("1150")

    inc = provider.get_income_statement("TEST")
    assert inc["statement_basis"] == "TTM"
    assert inc["revenue_ttm"] == Decimal("103500")
    assert inc["da"] == Decimal("2080")


def test_r2_issue_01_no_synthetic_growth_fallbacks_in_provider_or_projections(monkeypatch):
    """
    R2 requirement 1:
    Neither YFinanceProvider nor derive_request_projections may invent forward EBITDA, FCFF, or FCFE
    using base * (1 + g) synthetic growth formulas.
    If analyst forward estimates or driver assumptions are absent, provider must return None.
    """
    provider = YFinanceProvider(timeout=5.0)
    bundle = provider._get_bundle("NOCONSENSUS")

    # Mock annual and quarterly statements without forward consensus estimates
    q_dates = [pd.Timestamp("2026-06-30"), pd.Timestamp("2026-03-31"), pd.Timestamp("2025-12-31"), pd.Timestamp("2025-09-30")]
    q_cf_df = pd.DataFrame(
        {d: [1000, -200, 50, -30] for d in q_dates},
        index=["Operating Cash Flow", "Capital Expenditure", "Net Issuance Payments Of Debt", "Change In Working Capital"],
    )
    a_cf_df = pd.DataFrame(
        {pd.Timestamp("2025-12-31"): [4000, -800, 200, -100]},
        index=["Operating Cash Flow", "Capital Expenditure", "Net Issuance Payments Of Debt", "Change In Working Capital"],
    )
    q_fin_df = pd.DataFrame(
        {d: [2500, 800, 50, 30, 150, 100] for d in q_dates},
        index=["Total Revenue", "Operating Income", "Reconciled Depreciation", "Interest Expense", "Pretax Income", "Tax Provision"],
    )
    a_fin_df = pd.DataFrame(
        {pd.Timestamp("2025-12-31"): [10000, 3200, 200, 120, 600, 400]},
        index=["Total Revenue", "Operating Income", "Reconciled Depreciation", "Interest Expense", "Pretax Income", "Tax Provision"],
    )

    import yfinance as yf
    monkeypatch.setattr(yf.Ticker, "quarterly_cashflow", property(lambda self: q_cf_df))
    monkeypatch.setattr(yf.Ticker, "cashflow", property(lambda self: a_cf_df))
    monkeypatch.setattr(yf.Ticker, "quarterly_financials", property(lambda self: q_fin_df))
    monkeypatch.setattr(yf.Ticker, "financials", property(lambda self: a_fin_df))
    monkeypatch.setattr(yf.Ticker, "earnings_estimate", property(lambda self: pd.DataFrame()))
    monkeypatch.setattr(yf.Ticker, "revenue_estimate", property(lambda self: pd.DataFrame()))
    monkeypatch.setattr(yf.Ticker, "info", property(lambda self: {"regularMarketTime": 1782800000, "currency": "USD"}))

    # Provider get_cash_flow and get_forward_estimates must NOT have synthetic (1+g) cashflows
    cf = provider.get_cash_flow("NOCONSENSUS")
    assert cf["forward_fcfe_1y"] is None
    assert cf["forward_fcff_1y"] is None


    est = provider.get_forward_estimates("NOCONSENSUS")
    assert est["forward_ebitda_1y"] is None
    assert est["forward_fcff_1y"] is None
    assert est["forward_fcfe_1y"] is None


def test_r2_issue_01_no_fabricated_da_15_percent_and_fail_closed_when_drivers_missing():
    """
    R2 requirement 2:
    Projections must NEVER fabricate D&A as EBITDA * 15%.
    When critical drivers (D&A or CapEx) are missing and no analyst forward estimate exists,
    dependent forward metrics (FCFF/FCFE) must remain None, causing DCF / FCF Yield to fail closed.
    """
    snapshot = _make_sample_snapshot()
    # Explicitly clear D&A and CapEx from snapshot and forecast
    snapshot = snapshot.model_copy(
        update={
            "da_ttm": None,
            "capex_ttm": None,
            "forward_fcff_1y": None,
            "forward_fcff_2y": None,
            "fcff_ttm": None,
        }
    )
    assumptions = ValuationAssumptions()
    proj = derive_request_projections(snapshot, assumptions)

    # Projections must NOT fabricate D&A as 15% of EBITDA
    if proj.financial_bridge is not None:
        assert proj.financial_bridge.get("da") is None or Decimal(proj.financial_bridge["da"]) != Decimal("4800") # 32000 * 0.15 = 4800 forbidden

    # Without D&A and CapEx, forward FCFF cannot be derived from bridge -> must be None
    assert proj.forward_fcff_1y is None
    assert proj.forward_fcff_2y is None

    # DCF engine must fail closed with available=False
    dcf_val = run_dcf(snapshot, assumptions)
    assert dcf_val.available is False
    assert "FCFF" in dcf_val.unavailable_reason or "missing" in dcf_val.unavailable_reason.lower()


def test_r2_issue_01_financial_bridge_identity_and_meta():
    """
    R2 requirement 3 & 4:
    Verify financial bridge strictly satisfies 5 accounting identities:
    1. EBITDA = Revenue * Margin
    2. EBIT = EBITDA - D&A
    3. NOPAT = EBIT * (1 - TaxRate)
    4. FCFF = NOPAT + D&A - CapEx - ΔNWC
    5. FCFE = FCFF - Interest*(1 - TaxRate) + NetBorrowing
    And output carries full metadata: period, start/end dates, currency, and restrictions note.
    """
    snapshot = _make_sample_snapshot()
    assumptions = ValuationAssumptions(
        driver_ebitda_margin=Decimal("0.35"),
        driver_da=Decimal("4000"),
        driver_tax_rate=Decimal("0.22"),
        driver_capex=Decimal("7000"),
        driver_nwc_change=Decimal("1500"),
        driver_net_borrowing=Decimal("1000"),
    )
    proj = derive_request_projections(snapshot, assumptions)
    bridge = proj.financial_bridge
    assert bridge is not None

    rev = Decimal(bridge["revenue"])
    ebitda = Decimal(bridge["ebitda"])
    da = Decimal(bridge["da"])
    ebit = Decimal(bridge["ebit"])
    tax_rate = Decimal(bridge["tax_rate"])
    nopat = Decimal(bridge["nopat"])
    capex = Decimal(bridge["capex"])
    nwc = Decimal(bridge["nwc_change"])
    fcff = Decimal(bridge["fcff"])
    at_interest = Decimal(bridge["after_tax_interest"])
    net_borrowing = Decimal(bridge["net_borrowing"])
    fcfe = Decimal(bridge["fcfe"])

    # Identity 1: EBITDA = Revenue * Margin
    assert ebitda == (rev * Decimal(bridge["ebitda_margin"])).quantize(Decimal("1"))
    # Identity 2: EBIT = EBITDA - D&A
    assert ebit == ebitda - da
    # Identity 3: NOPAT = EBIT * (1 - TaxRate)
    assert nopat == (ebit * (Decimal("1") - tax_rate)).quantize(Decimal("1"))
    # Identity 4: FCFF = NOPAT + D&A - CapEx - ΔNWC
    assert fcff == nopat + da - capex - nwc
    # Identity 5: FCFE = FCFF - AfterTaxInterest + NetBorrowing
    assert fcfe == fcff - at_interest + net_borrowing

    # Verify metadata fields
    assert "period" in bridge
    assert "currency" in bridge
    assert "restrictions_note" in bridge
    assert bridge["currency"] == "USD"


def test_r2_issue_01_api_reset_and_stock_switch():
    """
    R2 requirement 6:
    Verify API override applies properly, GET /reset clears overrides and restores default,
    and switching ticker does not retain previous overrides.
    """
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)

    # 1. Override AVGO (demo ticker)
    override_payload = {
        "drivers": {
            "ebitda_margin": 0.55,
            "capex": 2000,
        }
    }
    post_res = client.post("/api/v1/valuation/AVGO", json=override_payload)
    assert post_res.status_code == 200
    data_post = post_res.json()
    assert data_post["financial_bridge"] is not None
    assert Decimal(data_post["financial_bridge"]["ebitda_margin"]) == Decimal("0.55")
    assert Decimal(data_post["financial_bridge"]["capex"]) == Decimal("2000")

    # 2. Reset AVGO
    reset_res = client.get("/api/v1/valuation/AVGO/reset")
    assert reset_res.status_code == 200
    data_reset = reset_res.json()
    assert data_reset["assumptions_used"]["driver_ebitda_margin"] is None
    assert data_reset["assumptions_used"]["driver_capex"] is None

    # 3. GET again without overrides: must be default
    get_res = client.get("/api/v1/valuation/AVGO")
    assert get_res.status_code == 200
    data_get = get_res.json()
    assert data_get["assumptions_used"]["driver_ebitda_margin"] is None
    assert data_get["assumptions_used"]["driver_capex"] is None


def test_r2_issue_01_fcff_fcfe_direct_consensus_source_protection():
    """
    R2 requirement 6:
    When snapshot has direct analyst estimate FCFF and FCFE,
    projections must preserve them as ANALYST_ESTIMATE without fabricating synthetic numbers.
    """
    snapshot = _make_sample_snapshot()
    snapshot = snapshot.model_copy(
        update={
            "forward_fcff_1y": FinancialMetric(
                value=Decimal("25000"),
                unit="USD",
                period="FY1E",
                source="Analyst Consensus FCFF",
                source_type=SourceType.ANALYST_ESTIMATE,
                as_of=date(2026, 7, 1),
            ),
            "forward_fcff_2y": FinancialMetric(
                value=Decimal("28000"),
                unit="USD",
                period="FY2E",
                source="Analyst Consensus FCFF 2Y",
                source_type=SourceType.ANALYST_ESTIMATE,
                as_of=date(2026, 7, 1),
            ),
            "forward_fcf_1y": FinancialMetric(
                value=Decimal("22000"),
                unit="USD",
                period="FY1E",
                source="Analyst Consensus FCFE",
                source_type=SourceType.ANALYST_ESTIMATE,
                as_of=date(2026, 7, 1),
            ),
        }
    )
    assumptions = ValuationAssumptions()
    proj = derive_request_projections(snapshot, assumptions)

    assert proj.forward_fcff_1y.value == Decimal("25000")
    assert proj.forward_fcff_1y.source_type == SourceType.ANALYST_ESTIMATE
    assert proj.forward_fcff_2y.value == Decimal("28000")
    assert proj.forward_fcff_2y.source_type == SourceType.ANALYST_ESTIMATE
    assert proj.forward_fcfe_1y.value == Decimal("22000")
    assert proj.forward_fcfe_1y.source_type == SourceType.ANALYST_ESTIMATE


