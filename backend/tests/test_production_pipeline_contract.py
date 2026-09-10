"""Comprehensive production pipeline integration tests.

Verifies the entire production chain:
Mock Upstream Ticker Tables -> YFinanceProvider -> Typed Data -> Snapshot -> ValuationService -> FastAPI TestClient.

Tests:
1. Discrete 100/200/300/400 quarterly revenue produces true TTM = 1000 without false YTD de-accumulation.
2. Incomplete quarterly statements (missing quarter or missing EBITDA) do not under-sum; they trigger clean ANNUAL_FALLBACK.
3. Single point-in-time latest balance sheet extraction without cross-quarter summation.
4. Share conflict degradation: DCF, EV/EBITDA, FCF Yield are unavailable, Forward P/E remains available.
5. Forward revenue 0y/+1y consensus estimates enter snapshot and blend by exact NTM day-weights.
6. Growth cap override (0.80 vs 0.40) dynamically derives higher EBITDA/FCFE/FCFF/DCF without mutating default cache.
7. Expired fiscal year puts 0% weight on expired FY and 100% on next FY.
8. FastAPI response realistically serializes all provenance metadata fields.
"""
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.domain import (
    CompanyFinancialSnapshot,
    FinancialMetric,
    SourceType,
    ValuationAssumptions,
)
from app.models.overrides import DCFOverride, ValuationOverrideRequest
from app.providers.yfinance_provider import YFinanceProvider, _TickerBundle
from app.services.projections import calculate_ntm_weights, derive_request_projections
from app.services.valuation_service import FinancialDataService, MemoryTTLCache, ValuationService
from app.config import DEFAULT_ASSUMPTIONS


# Valuation date: 2026-09-10; Non-December fiscal year ending October 31 (like AVGO)
VAL_DATE = date(2026, 9, 10)
VAL_TIMESTAMP = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)
FY_END_DATE = date(2026, 10, 31)

Q_DATES = [
    datetime(2026, 7, 31),
    datetime(2026, 4, 30),
    datetime(2026, 1, 31),
    datetime(2025, 10, 31),
]
ANNUAL_DATES = [
    datetime(2025, 10, 31),
    datetime(2024, 10, 31),
]


def _build_mock_bundle(
    ticker: str = "OCTO",
    shares_conflict: bool = False,
    missing_quarter: bool = False,
    missing_ebitda_quarter: bool = False,
) -> MagicMock:
    bundle = MagicMock(spec=_TickerBundle)
    bundle.raw_ticker = ticker
    bundle.query_symbol = ticker

    # Info dict
    # Oct 31 FY timestamps
    last_fy_ts = int(datetime(2025, 10, 31, tzinfo=timezone.utc).timestamp())
    next_fy_ts = int(datetime(2026, 10, 31, tzinfo=timezone.utc).timestamp())

    reported_shares = 1_000_000_000
    market_cap = 200_000_000_000 if shares_conflict else 100_000_000_000
    price = 100.0

    info: dict[str, Any] = {
        "shortName": "October Fiscal Co",
        "longName": "October Fiscal Corporation",
        "currency": "USD",
        "financialCurrency": "USD",
        "quoteType": "EQUITY",
        "regularMarketPrice": price,
        "currentPrice": price,
        "regularMarketTime": int(VAL_TIMESTAMP.timestamp()),
        "sharesOutstanding": reported_shares,
        "marketCap": market_cap,
        "lastFiscalYearEnd": last_fy_ts,
        "nextFiscalYearEnd": next_fy_ts,
        "trailingEps": 5.0,
        "forwardEps": 6.5,
        "beta": 1.1,
        "sector": "Technology",
        "industry": "Semiconductors",
    }
    bundle.get_info.return_value = info

    # Quarterly financials
    # 4 discrete quarters revenues: 400 (Q3), 300 (Q2), 200 (Q1), 100 (Q4) -> sum = 1000
    q_cols = Q_DATES[:3] if missing_quarter else Q_DATES
    q_revs = [Decimal("400000000"), Decimal("300000000"), Decimal("200000000")] if missing_quarter else [
        Decimal("400000000"), Decimal("300000000"), Decimal("200000000"), Decimal("100000000")
    ]
    q_ebitdas = [
        Decimal("160000000"),
        Decimal("120000000"),
        None if missing_ebitda_quarter else Decimal("80000000"),
        Decimal("40000000"),
    ]
    if missing_quarter:
        q_ebitdas = q_ebitdas[:3]

    fin_dict = {
        col: [rev, ebitda] for col, rev, ebitda in zip(q_cols, q_revs, q_ebitdas)
    }
    q_fin_df = pd.DataFrame(fin_dict, index=["Total Revenue", "EBITDA"])
    bundle.get_quarterly_financials.return_value = q_fin_df

    # Annual financials
    a_fin_df = pd.DataFrame(
        {
            ANNUAL_DATES[0]: [Decimal("900000000"), Decimal("350000000"), Decimal("50000000"), Decimal("30000000"), Decimal("150000000")],
            ANNUAL_DATES[1]: [Decimal("750000000"), Decimal("280000000"), Decimal("45000000"), Decimal("25000000"), Decimal("120000000")],
        },
        index=["Total Revenue", "EBITDA", "Interest Expense", "Tax Provision", "Pretax Income"],
    )
    bundle.get_financials.return_value = a_fin_df

    # Quarterly cashflow
    q_cf_df = pd.DataFrame(
        {
            c: [Decimal("120000000"), Decimal("30000000")] for c in q_cols
        },
        index=["Operating Cash Flow", "Capital Expenditure"],
    )
    bundle.get_quarterly_cashflow.return_value = q_cf_df

    # Annual cashflow
    a_cf_df = pd.DataFrame(
        {
            ANNUAL_DATES[0]: [Decimal("400000000"), Decimal("100000000")],
        },
        index=["Operating Cash Flow", "Capital Expenditure"],
    )
    bundle.get_cashflow.return_value = a_cf_df

    # Balance sheet: quarterly has latest 2026-07-31
    q_bs_df = pd.DataFrame(
        {
            Q_DATES[0]: [Decimal("5000000000"), Decimal("1000000000"), Decimal("1000000000")],
            Q_DATES[1]: [Decimal("4500000000"), Decimal("1050000000"), Decimal("1000000000")],
        },
        index=["Cash And Cash Equivalents", "Total Debt", "Ordinary Shares Number"],
    )
    bundle.get_quarterly_balance_sheet.return_value = q_bs_df

    a_bs_df = pd.DataFrame(
        {
            ANNUAL_DATES[0]: [Decimal("4000000000"), Decimal("1200000000"), Decimal("1000000000")],
        },
        index=["Cash And Cash Equivalents", "Total Debt", "Ordinary Shares Number"],
    )
    bundle.get_balance_sheet.return_value = a_bs_df

    # Earnings estimate
    ee_df = pd.DataFrame(
        {
            "avg": [Decimal("6.50"), Decimal("7.80")],
            "currency": ["USD", "USD"],
        },
        index=["0y", "+1y"],
    )
    bundle.get_earnings_estimate.return_value = ee_df

    # Revenue estimate
    re_df = pd.DataFrame(
        {
            "avg": [Decimal("1500000000"), Decimal("1800000000")],
            "growth": [Decimal("0.70"), Decimal("0.20")],
        },
        index=["0y", "+1y"],
    )
    bundle.get_revenue_estimate.return_value = re_df

    return bundle


def test_discrete_100_200_300_400_produces_1000_ttm():
    """Requirement A: Discrete 100/200/300/400 quarterly revenue must produce true TTM = 1000."""
    provider = YFinanceProvider()
    mock_bundle = _build_mock_bundle()

    with patch.object(provider, "_get_bundle", return_value=mock_bundle):
        inc = provider.get_income_statement("OCTO")
        assert inc["statement_basis"] == "TTM"
        assert inc["annual_fallback"] is False
        assert inc["revenue_ttm"] == Decimal("1000000000"), f"Expected 1000M, got {inc['revenue_ttm']}"
        assert inc["ebitda_ttm"] == Decimal("400000000")


def test_incomplete_quarterly_fails_to_annual_fallback_not_partial_sum():
    """Requirement A: Missing quarter or missing EBITDA cannot under-sum as TTM; triggers annual fallback."""
    provider = YFinanceProvider()

    # 1. Missing quarter (only 3 quarters available)
    bundle_3q = _build_mock_bundle(missing_quarter=True)
    with patch.object(provider, "_get_bundle", return_value=bundle_3q):
        inc_3q = provider.get_income_statement("OCTO")
        assert inc_3q["statement_basis"] == "ANNUAL_FALLBACK"
        assert inc_3q["annual_fallback"] is True
        # Annual statement revenue is 900M, not 900M partial sum of 3 quarters (400+300+200)
        assert inc_3q["revenue_ttm"] == Decimal("900000000")

    # 2. Missing EBITDA in 1 of 4 quarters
    bundle_missing_ebitda = _build_mock_bundle(missing_ebitda_quarter=True)
    with patch.object(provider, "_get_bundle", return_value=bundle_missing_ebitda):
        inc_me = provider.get_income_statement("OCTO")
        assert inc_me["statement_basis"] == "ANNUAL_FALLBACK"
        assert inc_me["annual_fallback"] is True
        assert inc_me["revenue_ttm"] == Decimal("1000000000")
        assert inc_me["ebitda_ttm"] == Decimal("350000000")  # Annual EBITDA fallback


def test_latest_balance_sheet_point_in_time():
    """Requirement A: Balance sheet extracts latest single point-in-time statement without summing."""
    provider = YFinanceProvider()
    mock_bundle = _build_mock_bundle()

    with patch.object(provider, "_get_bundle", return_value=mock_bundle):
        bs = provider.get_balance_sheet("OCTO")
        assert bs["cash"] == Decimal("5000000000")
        assert bs["total_debt"] == Decimal("1000000000")
        assert bs["net_debt"] == Decimal("-4000000000")
        assert bs["period"] == "Q_2026-07-31"


def test_shares_conflict_degradation_full_pipeline():
    """Requirement A: Severe shares conflict degrades 3 models to unavailable while keeping Forward P/E operational."""
    provider = YFinanceProvider()
    mock_bundle = _build_mock_bundle(shares_conflict=True)

    with patch.object(provider, "_get_bundle", return_value=mock_bundle):
        data_svc = FinancialDataService(provider, MemoryTTLCache(), DEFAULT_ASSUMPTIONS)
        val_svc = ValuationService(data_svc, default_assumptions=DEFAULT_ASSUMPTIONS)

        res = val_svc.compute("OCTO")
        assert res.shares_basis == "CONFLICT_DEGRADED"
        assert not res.valuations["dcf"].available
        assert not res.valuations["ev_ebitda"].available
        assert not res.valuations["fcf_yield"].available
        assert res.valuations["forward_pe"].available


def test_forecast_revenue_consensus_and_day_weights():
    """Requirement A: Forecast revenue 0y/+1y enters snapshot and blends by exact NTM day-weights."""
    provider = YFinanceProvider()
    mock_bundle = _build_mock_bundle()

    with patch.object(provider, "_get_bundle", return_value=mock_bundle):
        data_svc = FinancialDataService(provider, MemoryTTLCache(), DEFAULT_ASSUMPTIONS)
        snap = data_svc.get_snapshot("OCTO")

        assert snap.revenue_estimate_1y is not None
        assert snap.revenue_estimate_1y.value == Decimal("1500000000")
        assert snap.revenue_estimate_2y is not None
        assert snap.revenue_estimate_2y.value == Decimal("1800000000")

        # Valuation date 2026-09-10 to FY end 2026-10-31 is 51 days
        w0, w1, rem_days, total_days = calculate_ntm_weights(VAL_DATE, FY_END_DATE)
        assert rem_days == 51
        assert (w0 + w1) == Decimal("1.0")

        proj = derive_request_projections(snap, ValuationAssumptions(forecast_horizon="ntm"))
        expected_blended_rev = (w0 * Decimal("1500000000") + w1 * Decimal("1800000000")).quantize(Decimal("1"), ROUND_HALF_UP)
        assert proj.forward_revenue is not None
        assert proj.forward_revenue.value == expected_blended_rev


def test_growth_bounds_scaling_and_cache_purity():
    """Requirement A: growth_cap=0.80 vs 0.40 scales derived metrics; post-check default doesn't leak."""
    provider = YFinanceProvider()
    mock_bundle = _build_mock_bundle()

    with patch.object(provider, "_get_bundle", return_value=mock_bundle):
        data_svc = FinancialDataService(provider, MemoryTTLCache(), DEFAULT_ASSUMPTIONS)
        val_svc = ValuationService(data_svc, default_assumptions=DEFAULT_ASSUMPTIONS)

        # 1. Base run
        res_default = val_svc.compute("OCTO")
        dcf_def = res_default.valuations["dcf"].base.price_per_share

        # 2. Override 0.80
        req_80 = ValuationOverrideRequest(dcf=DCFOverride(growth_cap=Decimal("0.80")))
        res_80 = val_svc.compute("OCTO", overrides=req_80.to_override_dict())
        dcf_80 = res_80.valuations["dcf"].base.price_per_share

        # 3. Override 0.40
        req_40 = ValuationOverrideRequest(dcf=DCFOverride(growth_cap=Decimal("0.40")))
        res_40 = val_svc.compute("OCTO", overrides=req_40.to_override_dict())
        dcf_40 = res_40.valuations["dcf"].base.price_per_share

        # 4. Post-check default
        res_after = val_svc.compute("OCTO")
        dcf_after = res_after.valuations["dcf"].base.price_per_share

        assert dcf_80 > dcf_40, f"DCF price at 0.80 ({dcf_80}) must exceed 0.40 ({dcf_40})"
        assert dcf_def == dcf_after, "Default cache must not be contaminated by override"


def test_expired_fiscal_year_weights():
    """Requirement A: Expired fiscal year puts 0% weight on expired FY and 100% on next FY."""
    as_of = date(2026, 9, 10)
    past_fy = date(2025, 10, 31)  # expired FY
    w0, w1, rem, tot = calculate_ntm_weights(as_of, past_fy)
    assert w0 == Decimal("0.0"), "Expired FY must get 0% weight"
    assert w1 == Decimal("1.0"), "Next FY must get 100% weight"


def test_fastapi_testclient_serialization_contract():
    """Requirement A & B: FastAPI HTTP response realistically serializes provenance fields."""
    from app.main import app as fastapi_app, _live_provider
    mock_bundle = _build_mock_bundle()

    with patch.object(_live_provider, "_get_bundle", return_value=mock_bundle):
        client = TestClient(fastapi_app)
        resp = client.get("/api/v1/valuation/OCTO?provider=live")
        assert resp.status_code == 200
        data = resp.json()

        assert data["statement_basis"] == "TTM"
        assert data["shares_basis"] == "SINGLE_CLASS_VERIFIED"
        assert data["annual_fallback"] is False
        assert "dcf" in data["valuations"]
        assert data["valuations"]["dcf"]["available"] is True
        assert "sensitivity_matrix" in data["valuations"]["dcf"]
        assert data["valuations"]["dcf"]["sensitivity_matrix"] is not None

        # Test POST override serialization
        post_resp = client.post(
            "/api/v1/valuation/OCTO?provider=live",
            json={"dcf": {"growth_cap": 0.65}},
        )
        assert post_resp.status_code == 200
        post_data = post_resp.json()
        assert post_data["growth_cap_effective"] == "0.65"


def test_cors_policy_rejects_unauthorized_and_allows_test_app():
    """Verify CORS policy: default production app strictly rejects non-3000 origins, test fixture app allows 13002."""
    from app.main import app as prod_app
    from tests.fixtures.e2e_server import app as test_app

    # 1. Default production app behavior
    prod_client = TestClient(prod_app)
    r_prod_allowed = prod_client.get("/health", headers={"Origin": "http://127.0.0.1:3000"})
    assert r_prod_allowed.headers.get("access-control-allow-origin") == "http://127.0.0.1:3000"

    r_prod_rejected = prod_client.get("/health", headers={"Origin": "http://127.0.0.1:13002"})
    assert r_prod_rejected.headers.get("access-control-allow-origin") is None

    # 2. Test fixture app explicitly allows test port 13002
    test_client = TestClient(test_app)
    r_test_allowed = test_client.get("/e2e/health", headers={"Origin": "http://127.0.0.1:13002"})
    assert r_test_allowed.headers.get("access-control-allow-origin") == "http://127.0.0.1:13002"

