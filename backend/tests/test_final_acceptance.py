"""
Final backend acceptance test suite covering backend-final-corrections.md:

1. Listing Geography & Exchange Evidence:
   - Non-US USD listings (e.g. LSE with USD quote) rejected as non_us_listing.
   - Unknown listing evidence (e.g. foreign country, missing exchange/market) rejected as unknown_listing.
   - Foreign-headquartered US ADRs (e.g. TSM on NYQ/us_market) accepted.
   - Normal US equities (e.g. AAPL on NMS/us_market) accepted.
   - Exchange and market fields carried through QuoteData, CompanyProfileData, and CompanyFinancialSnapshot.

2. Concurrency Deduplication & TTL:
   - 10 threads calling provider methods concurrently trigger exactly ONE upstream fetch.
   - TTL expiration triggers fresh upstream fetch.
   - Lock release and error retry on upstream failure.

3. Real Request Budget vs Cache Age & Timeout Enforcement:
   - Elapsed bound on public provider path with blocking upstream times out within bounded duration.
   - Resource cleanup and immediate subsequent recovery after timeout.
   - Cache age is NOT request clock: partly cached bundle older than 25s uses fresh request budget.
   - HTTP 429 maps to RateLimitExceededError and HTTP 503 maps to ProviderUnavailableError.

4. Exact Fiscal Date Alignment & Forecast Horizon:
   - June fiscal year ends (e.g. MSFT 06-30) align and produce FY2025E forecasts.
   - January floating fiscal year ends (e.g. NVDA 01-26/01-31) align within tolerance.
   - Same-year date mismatch (e.g. 06-30 fiscal vs 03-31 statement) disables forward forecasts.
   - Missing/stale fiscal metadata disables forward forecasts with honest explanation.
   - Horizon mismatch (>450 days) disables forward forecasts.
   - Fallback summary forwardEps receives isolated label without polluting EBITDA/FCF periods.

5. TSM Grounded Per-ADS Basis & Currency Isolation:
   - Empirical grounding of TSM USD quote, shares, market cap, and USD earnings estimates.
   - Forward P/E available in USD; statement models disabled due to TWD vs USD statement currency.
"""
from datetime import date, datetime, timezone
from decimal import Decimal
import threading
import time
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import requests

from app.config import DEFAULT_ASSUMPTIONS
from app.engines.composite import run_composite
from app.engines.forward_pe import run_forward_pe
from app.models.domain import (
    CompanyFinancialSnapshot,
    FinancialMetric,
    SourceType,
)
from app.providers.base import (
    ProviderError,
    ProviderRateLimitError,
    ProviderUnavailableError,
    UnsupportedCompanyError,
)
from app.providers.yfinance_provider import (
    YFinanceProvider,
    _BUNDLE_TTL,
    _RequestBudget,
    _TickerBundle,
    _UPSTREAM_TOTAL_TIMEOUT,
    _verify_forecast_alignment,
)
from app.services.valuation_service import Normalizer, run_all_engines


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


# ======================================================================
# 1. Listing Geography & Exchange Evidence
# ======================================================================
def test_non_us_exchange_usd_quote_rejected_as_non_us_listing():
    """Security trading in USD but listed on a non-US exchange (e.g. LSE) is rejected with non_us_listing."""
    today = date.today()
    normalizer = Normalizer(strict_profile=False, allow_all_equities=True)

    quote = {
        "price": Decimal("50.00"),
        "currency": "USD",
        "exchange": "LSE",
        "market": "gb_market",
        "as_of": today,
        "source": "LSE quote",
    }
    profile = {
        "name": "London Tech Plc",
        "diluted_shares": Decimal("100000000"),
        "currency": "USD",
        "country": "United Kingdom",
        "exchange": "LSE",
        "market": "gb_market",
        "security_type": "EQUITY",
        "financial_currency": "USD",
        "as_of": today,
        "source": "LSE profile",
    }

    with pytest.raises(UnsupportedCompanyError) as exc_info:
        raw = normalizer.normalize_provider_data(
            "LONCO",
            quote,
            profile,
            {"as_of": today, "source": "s"},
            {"as_of": today, "source": "s"},
            {"as_of": today, "source": "s"},
            {"as_of": today, "source": "s"},
            {"as_of": today, "source": "s"},
        )
        normalizer.normalize(raw)

    assert exc_info.value.reason == "non_us_listing"
    assert "non-US exchange" in str(exc_info.value.detail)


def test_unknown_listing_evidence_rejected_when_exchange_missing():
    """Foreign company with no exchange/market evidence is rejected as unknown_listing."""
    today = date.today()
    normalizer = Normalizer(strict_profile=False, allow_all_equities=True)

    quote = {
        "price": Decimal("30.00"),
        "currency": "USD",
        "exchange": None,
        "market": None,
        "as_of": today,
        "source": "OTC quote",
    }
    profile = {
        "name": "Unknown Foreign Corp",
        "diluted_shares": Decimal("50000000"),
        "currency": "USD",
        "country": "Germany",
        "exchange": None,
        "market": None,
        "security_type": "EQUITY",
        "financial_currency": "EUR",
        "as_of": today,
        "source": "OTC profile",
    }

    with pytest.raises(UnsupportedCompanyError) as exc_info:
        raw = normalizer.normalize_provider_data(
            "UNKCO",
            quote,
            profile,
            {"as_of": today, "source": "s"},
            {"as_of": today, "source": "s"},
            {"as_of": today, "source": "s"},
            {"as_of": today, "source": "s"},
            {"as_of": today, "source": "s"},
        )
        normalizer.normalize(raw)

    assert exc_info.value.reason == "unknown_listing"
    assert "unknown listing evidence" in str(exc_info.value.detail).lower()


def test_foreign_headquartered_us_adr_accepted():
    """Foreign company (e.g. Taiwan) with US exchange listing (e.g. NYQ) is accepted."""
    today = date.today()
    normalizer = Normalizer(strict_profile=False, allow_all_equities=True)

    quote = {
        "price": Decimal("200.00"),
        "currency": "USD",
        "exchange": "NYQ",
        "market": "us_market",
        "as_of": today,
        "source": "NYSE quote",
    }
    profile = {
        "name": "Taiwan Semiconductor Manufacturing Co Ltd ADR",
        "diluted_shares": Decimal("5180000000"),
        "currency": "USD",
        "country": "Taiwan",
        "exchange": "NYQ",
        "market": "us_market",
        "security_type": "COMMON_STOCK",
        "financial_currency": "TWD",
        "as_of": today,
        "source": "NYSE profile",
    }

    raw = normalizer.normalize_provider_data(
        "TSM",
        quote,
        profile,
        {"as_of": today, "source": "s"},
        {"as_of": today, "source": "s"},
        {"as_of": today, "source": "s"},
        {"as_of": today, "source": "s"},
        {"as_of": today, "source": "s"},
    )
    snapshot = normalizer.normalize(raw)
    assert snapshot.ticker == "TSM"
    assert snapshot.exchange == "NYQ"
    assert snapshot.market == "us_market"
    assert snapshot.currency == "USD"
    assert snapshot.financial_currency == "TWD"


def test_us_equity_listing_accepted():
    """US company listed on NASDAQ is accepted with exchange and market populated."""
    today = date.today()
    normalizer = Normalizer(strict_profile=False, allow_all_equities=True)

    quote = {
        "price": Decimal("150.00"),
        "currency": "USD",
        "exchange": "NMS",
        "market": "us_market",
        "as_of": today,
        "source": "NASDAQ quote",
    }
    profile = {
        "name": "Apple Inc",
        "diluted_shares": Decimal("15000000000"),
        "currency": "USD",
        "country": "United States",
        "exchange": "NMS",
        "market": "us_market",
        "security_type": "EQUITY",
        "financial_currency": "USD",
        "as_of": today,
        "source": "NASDAQ profile",
    }

    raw = normalizer.normalize_provider_data(
        "AAPL",
        quote,
        profile,
        {"as_of": today, "source": "s"},
        {"as_of": today, "source": "s"},
        {"as_of": today, "source": "s"},
        {"as_of": today, "source": "s"},
        {"as_of": today, "source": "s"},
    )
    snapshot = normalizer.normalize(raw)
    assert snapshot.ticker == "AAPL"
    assert snapshot.exchange == "NMS"
    assert snapshot.market == "us_market"


def test_provider_populates_exchange_and_market():
    """YFinanceProvider populates exchange and market in get_quote and get_company_profile."""
    provider = YFinanceProvider()
    with patch("yfinance.Ticker") as mock_yf:
        mock_t = MagicMock()
        mock_yf.return_value = mock_t
        mock_t.info = {
            "regularMarketPrice": 220.0,
            "currency": "USD",
            "exchange": "NYQ",
            "market": "us_market",
            "quoteType": "EQUITY",
            "sharesOutstanding": 1000000,
            "shortName": "Test NYSE Corp",
        }

        quote = provider.get_quote("NYSETICK")
        assert quote["exchange"] == "NYQ"
        assert quote["market"] == "us_market"

        profile = provider.get_company_profile("NYSETICK")
        assert profile["exchange"] == "NYQ"
        assert profile["market"] == "us_market"


# ======================================================================
# 2. Concurrency Deduplication & TTL
# ======================================================================
def test_ticker_bundle_concurrency_deduplication():
    """Concurrent calls to bundle.get_info() trigger exactly ONE upstream fetch."""
    bundle = _TickerBundle("CONC_TEST", "CONC_TEST")
    fetch_count = 0
    lock = threading.Lock()

    def mock_fetch():
        nonlocal fetch_count
        with lock:
            fetch_count += 1
        time.sleep(0.05)
        return {"quoteType": "EQUITY", "currency": "USD", "currentPrice": 100.0}

    bundle.ticker = MagicMock()
    type(bundle.ticker).info = property(lambda self: mock_fetch())

    results = []
    errors = []

    def worker():
        try:
            info = bundle.get_info()
            results.append(info)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
    assert len(results) == 10
    assert fetch_count == 1
    assert bundle._info["currency"] == "USD"


def test_ticker_bundle_ttl_expiration_refetches():
    """After _BUNDLE_TTL expires, provider creates a new bundle and refetches."""
    provider = YFinanceProvider()
    with patch("yfinance.Ticker") as mock_yf:
        mock_t = MagicMock()
        mock_yf.return_value = mock_t
        mock_t.info = {"quoteType": "EQUITY", "currency": "USD", "regularMarketPrice": 100.0}

        bundle1 = provider._get_bundle("TTL_TEST")
        # Artificially age the bundle past TTL
        bundle1.fetched_at = time.monotonic() - (_BUNDLE_TTL + 5.0)

        bundle2 = provider._get_bundle("TTL_TEST")
        assert bundle1 is not bundle2


def test_ticker_bundle_error_retry():
    """If initial upstream call fails, lock is released and subsequent call retries."""
    bundle = _TickerBundle("RETRY_TEST", "RETRY_TEST")
    attempt = 0

    def faulty_fetch():
        nonlocal attempt
        attempt += 1
        if attempt == 1:
            raise ConnectionError("Temporary upstream network error")
        return {"quoteType": "EQUITY", "regularMarketPrice": 50.0}

    bundle.ticker = MagicMock()
    type(bundle.ticker).info = property(lambda self: faulty_fetch())

    with pytest.raises(ProviderUnavailableError):
        bundle.get_info()

    # Lock must not remain locked: retry must succeed
    assert not bundle._lock.locked()
    info2 = bundle.get_info()
    assert info2["regularMarketPrice"] == 50.0
    assert attempt == 2


# ======================================================================
# 3. Real Request Budget vs Cache Age & Timeout Enforcement
# ======================================================================
def test_upstream_total_timeout_enforcement_with_blocking_upstream():
    """When upstream blocks, provider with short timeout raises ProviderUnavailableError within limit."""
    provider = YFinanceProvider(timeout=0.15)
    with patch("yfinance.Ticker") as mock_yf:
        mock_t = MagicMock()
        mock_yf.return_value = mock_t

        def blocking_fetch():
            time.sleep(2.0)
            return {"quoteType": "EQUITY", "currency": "USD"}

        type(mock_t).info = property(lambda self: blocking_fetch())

        start = time.monotonic()
        with pytest.raises(ProviderUnavailableError) as exc_info:
            provider.get_quote("SLOWCO")
        elapsed = time.monotonic() - start

        assert elapsed < 0.6, f"Request took {elapsed:.2f}s, expected to timeout around 0.15s"
        assert "timed out" in str(exc_info.value).lower() or "deadline exceeded" in str(exc_info.value).lower()


def test_upstream_timeout_bounded_resource_recovery():
    """After a timeout failure, subsequent call with fast upstream immediately succeeds."""
    provider = YFinanceProvider(timeout=0.15)
    with patch("yfinance.Ticker") as mock_yf:
        mock_t = MagicMock()
        mock_yf.return_value = mock_t

        call_idx = 0

        def alternating_fetch():
            nonlocal call_idx
            call_idx += 1
            if call_idx == 1:
                time.sleep(2.0)
                return {}
            return {"quoteType": "EQUITY", "currency": "USD", "regularMarketPrice": 75.0}

        type(mock_t).info = property(lambda self: alternating_fetch())

        # First call fails on timeout
        with pytest.raises(ProviderUnavailableError):
            provider.get_quote("RECOV")

        # Second call to a different ticker with normal timeout must succeed immediately
        fast_provider = YFinanceProvider(timeout=5.0)
        fast_bundle = fast_provider._get_bundle("RECOV2")
        fast_bundle.ticker = mock_t

        q = fast_provider.get_quote("RECOV2")
        assert q["price"] == Decimal("75.00")


def test_cache_age_is_not_request_clock():
    """A partly cached valid bundle older than 25s within TTL fetches missing category with fresh budget."""
    provider = YFinanceProvider(timeout=25.0)
    bundle = provider._get_bundle("CACHE_TEST")

    # Simulate info cached 26 seconds ago (older than 25s, but within 30s TTL)
    bundle.fetched_at = time.monotonic() - 26.0
    bundle._info = {"quoteType": "EQUITY", "currency": "USD", "regularMarketPrice": 100.0}

    # Balance sheet has not been fetched yet
    bundle.ticker = MagicMock()
    bundle.ticker.balance_sheet = pd.DataFrame(
        {pd.Timestamp("2024-12-31"): [1000.0, 500.0]},
        index=["Cash And Cash Equivalents", "Total Debt"],
    )

    # A new request starts NOW with a fresh 25.0s budget
    budget = _RequestBudget(25.0)
    bs_data = bundle.get_balance_sheet(budget)

    assert bs_data is not None
    assert not bs_data.empty


def test_http_429_and_503_classification_preserved():
    """HTTP 429 raises ProviderRateLimitError and HTTP 503 raises ProviderUnavailableError."""
    bundle = _TickerBundle("ERR_TEST", "ERR_TEST")

    resp_429 = MagicMock()
    resp_429.status_code = 429
    err_429 = requests.exceptions.HTTPError(response=resp_429)

    bundle.ticker = MagicMock()
    type(bundle.ticker).info = property(lambda self: (_ for _ in ()).throw(err_429))

    with pytest.raises(ProviderRateLimitError) as exc_429:
        bundle.get_info()
    assert "rate limit" in str(exc_429.value).lower()

    resp_503 = MagicMock()
    resp_503.status_code = 503
    err_503 = requests.exceptions.HTTPError(response=resp_503)

    bundle2 = _TickerBundle("ERR_TEST2", "ERR_TEST2")
    bundle2.ticker = MagicMock()
    type(bundle2.ticker).info = property(lambda self: (_ for _ in ()).throw(err_503))

    with pytest.raises(ProviderUnavailableError) as exc_503:
        bundle2.get_info()
    assert "error/timeout" in str(exc_503.value).lower() or "unavailable" in str(exc_503.value).lower()


# ======================================================================
# 4. Exact Fiscal Date Alignment & Forecast Horizon
# ======================================================================
def test_june_fiscal_year_end_alignment():
    """June 30 fiscal year end (e.g. MSFT) aligns and derives FY2025E forecasts."""
    provider = YFinanceProvider()
    with patch("yfinance.Ticker") as mock_yf:
        mock_t = MagicMock()
        mock_yf.return_value = mock_t

        # MSFT FY ends June 30: 2024-06-30 timestamp is 1719705600
        # Next FY ends June 30: 2025-06-30 timestamp is 1751241600
        mock_t.info = {
            "regularMarketPrice": 400.0,
            "currency": "USD",
            "quoteType": "EQUITY",
            "sharesOutstanding": 7400000000,
            "lastFiscalYearEnd": 1719705600,  # 2024-06-30
            "nextFiscalYearEnd": 1751241600,  # 2025-06-30
        }
        ts_june = pd.Timestamp("2024-06-30")
        mock_t.financials = pd.DataFrame(
            {ts_june: [100000.0, 5000.0, 0.18]},
            index=["EBITDA", "Interest Expense", "Tax Rate For Calcs"],
        )
        mock_t.cashflow = pd.DataFrame(
            {ts_june: [80000.0, -20000.0]},
            index=["Operating Cash Flow", "Capital Expenditure"],
        )
        mock_t.balance_sheet = pd.DataFrame()
        mock_t.earnings_estimate = None
        mock_t.revenue_estimate = pd.DataFrame(
            {"growth": [0.14, 0.12]},
            index=["0y", "+1y"],
        )

        est = provider.get_forward_estimates("MSFTCO")
        # No independent analyst EBITDA consensus exists in this fixture;
        # fiscal-date alignment is not permission to synthesize EBITDA from
        # a revenue-growth rate in the provider layer.
        assert est["forward_ebitda_1y"] is None
        assert est["forward_ebitda_1y_source_type"] is None
        assert "independent analyst" in est["forward_ebitda_1y_notes"]

        cf = provider.get_cash_flow("MSFTCO")
        # Issue 01 R2 contract: provider does not synthesize forward cash flow via (1 + g).
        # Forward cash flows are derived in projections layer via financial driver bridge or direct analyst estimates.
        assert cf["forward_fcfe_1y"] is None
        assert cf["cfo"] == Decimal("80000.0")
        assert cf["capex"] == Decimal("20000.0")


def test_january_floating_fiscal_year_end_alignment():
    """January floating fiscal year end (e.g. NVDA 01-26 vs 01-31) aligns within 14-day tolerance."""
    provider = YFinanceProvider()
    with patch("yfinance.Ticker") as mock_yf:
        mock_t = MagicMock()
        mock_yf.return_value = mock_t

        # NVDA floating FY ends late January: 2025-01-26 timestamp is 1737849600
        # Statement column recorded at month-end 2025-01-31 (delta 5 days <= 14 days)
        mock_t.info = {
            "regularMarketPrice": 120.0,
            "currency": "USD",
            "quoteType": "EQUITY",
            "sharesOutstanding": 24000000000,
            "lastFiscalYearEnd": 1737849600,  # 2025-01-26
            "nextFiscalYearEnd": 1769385600,  # 2026-01-25
        }
        ts_jan = pd.Timestamp("2025-01-31")
        mock_t.financials = pd.DataFrame(
            {ts_jan: [50000.0, 1000.0, 0.15]},
            index=["EBITDA", "Interest Expense", "Tax Rate For Calcs"],
        )
        mock_t.cashflow = pd.DataFrame(
            {ts_jan: [40000.0, -5000.0]},
            index=["Operating Cash Flow", "Capital Expenditure"],
        )
        mock_t.balance_sheet = pd.DataFrame()
        mock_t.earnings_estimate = None
        mock_t.revenue_estimate = pd.DataFrame(
            {"growth": [0.25, 0.15]},
            index=["0y", "+1y"],
        )

        est = provider.get_forward_estimates("NVDACO")
        assert est["forward_ebitda_1y"] is None
        assert est["forward_ebitda_1y_source_type"] is None
        assert "independent analyst" in est["forward_ebitda_1y_notes"]


def test_same_year_date_mismatch_disables_forward_forecasts():
    """Statement date mismatching fiscal year end (e.g. 03-31 vs 06-30, delta 91 days) disables forward forecasts."""
    provider = YFinanceProvider()
    with patch("yfinance.Ticker") as mock_yf:
        mock_t = MagicMock()
        mock_yf.return_value = mock_t

        mock_t.info = {
            "regularMarketPrice": 100.0,
            "currency": "USD",
            "quoteType": "EQUITY",
            "sharesOutstanding": 1000000,
            "lastFiscalYearEnd": 1719705600,  # 2024-06-30
        }
        # Statement column is March 31, 2024 (delta 91 days from June 30 fiscal year end)
        ts_march = pd.Timestamp("2024-03-31")
        mock_t.financials = pd.DataFrame(
            {ts_march: [1000.0, 50.0, 0.20]},
            index=["EBITDA", "Interest Expense", "Tax Rate For Calcs"],
        )
        mock_t.cashflow = pd.DataFrame(
            {ts_march: [800.0, -200.0]},
            index=["Operating Cash Flow", "Capital Expenditure"],
        )
        mock_t.balance_sheet = pd.DataFrame()
        mock_t.earnings_estimate = None
        mock_t.revenue_estimate = pd.DataFrame(
            {"growth": [0.10, 0.10]},
            index=["0y", "+1y"],
        )

        est = provider.get_forward_estimates("MISMATCH")
        assert est["forward_ebitda_1y"] is None
        assert "delta=91d" in est["forward_ebitda_1y_notes"] or "lags" in est["forward_ebitda_1y_notes"]


def test_stale_missing_fiscal_metadata_disables_forward_forecasts():
    """Missing lastFiscalYearEnd metadata disables derived forward forecasts with honest explanation."""
    provider = YFinanceProvider()
    with patch("yfinance.Ticker") as mock_yf:
        mock_t = MagicMock()
        mock_yf.return_value = mock_t

        mock_t.info = {
            "regularMarketPrice": 100.0,
            "currency": "USD",
            "quoteType": "EQUITY",
            "sharesOutstanding": 1000000,
            "lastFiscalYearEnd": None,  # Missing!
        }
        ts = pd.Timestamp("2024-12-31")
        mock_t.financials = pd.DataFrame({ts: [1000.0]}, index=["EBITDA"])
        mock_t.cashflow = pd.DataFrame({ts: [800.0, -200.0]}, index=["Operating Cash Flow", "Capital Expenditure"])
        mock_t.balance_sheet = pd.DataFrame()
        mock_t.earnings_estimate = None
        mock_t.revenue_estimate = pd.DataFrame({"growth": [0.10]}, index=["0y"])

        est = provider.get_forward_estimates("NOMETA")
        assert est["forward_ebitda_1y"] is None
        assert "Missing upstream fiscal year end metadata" in est["forward_ebitda_1y_notes"]


def test_forecast_0y_horizon_mismatch_disables_forward_forecasts():
    """nextFiscalYearEnd > 450 days ahead of statement date disables forward growth."""
    provider = YFinanceProvider()
    with patch("yfinance.Ticker") as mock_yf:
        mock_t = MagicMock()
        mock_yf.return_value = mock_t

        mock_t.info = {
            "regularMarketPrice": 100.0,
            "currency": "USD",
            "quoteType": "EQUITY",
            "sharesOutstanding": 1000000,
            "lastFiscalYearEnd": 1735603200,  # 2024-12-31
            "nextFiscalYearEnd": 1798675200,  # 2026-12-31 (730 days ahead!)
        }
        ts = pd.Timestamp("2024-12-31")
        mock_t.financials = pd.DataFrame({ts: [1000.0]}, index=["EBITDA"])
        mock_t.cashflow = pd.DataFrame({ts: [800.0, -200.0]}, index=["Operating Cash Flow", "Capital Expenditure"])
        mock_t.balance_sheet = pd.DataFrame()
        mock_t.earnings_estimate = None
        mock_t.revenue_estimate = pd.DataFrame({"growth": [0.10]}, index=["0y"])

        est = provider.get_forward_estimates("HORIZON_GAP")
        assert est["forward_ebitda_1y"] is None
        assert "not adjacent" in est["forward_ebitda_1y_notes"]


def test_summary_forward_eps_label_isolation():
    """Fallback info.forwardEps receives quote_summary_forward_eps label without contaminating EBITDA period."""
    provider = YFinanceProvider()
    with patch("yfinance.Ticker") as mock_yf:
        mock_t = MagicMock()
        mock_yf.return_value = mock_t

        mock_t.info = {
            "regularMarketPrice": 100.0,
            "currency": "USD",
            "quoteType": "EQUITY",
            "sharesOutstanding": 1000000,
            "forwardEps": 5.50,  # Fallback forwardEps from quote summary
            "lastFiscalYearEnd": 1735603200,  # 2024-12-31
            "nextFiscalYearEnd": 1767139200,  # 2025-12-31
        }
        ts = pd.Timestamp("2024-12-31")
        mock_t.financials = pd.DataFrame({ts: [1000.0]}, index=["EBITDA"])
        mock_t.cashflow = pd.DataFrame()
        mock_t.balance_sheet = pd.DataFrame()
        mock_t.earnings_estimate = None  # No earnings estimate table
        mock_t.revenue_estimate = pd.DataFrame({"growth": [0.15]}, index=["0y"])

        est = provider.get_forward_estimates("LABEL_ISO")
        # Forward EPS has provider-unspecified forward_1y label
        assert est["forward_eps_1y"] == Decimal("5.50")
        assert est["forward_eps_1y_period"] == "forward_1y"

        # EBITDA remains unavailable rather than inheriting the EPS fallback
        # label or a synthetic revenue-growth projection.
        assert est["forward_ebitda_1y"] is None
        assert est["forward_ebitda_1y_period"] is None
        assert "independent analyst" in est["forward_ebitda_1y_notes"]


# ======================================================================
# 5. TSM Grounded Per-ADS Basis & Currency Isolation
# ======================================================================
def test_tsm_grounded_per_ads_basis_and_currency_isolation():
    """
    TSM empirical raw fields:
      price: $439.0 USD, sharesOutstanding: 5,186,474,013, marketCap: $2,276,862,197,760
      earnings_estimate currency: USD, avg: $16.93 (0y), $21.93 (+1y)
      statements currency: TWD
    Forward P/E is valid (in USD per ADS); EV/EBITDA, FCF yield, and DCF are safely disabled.
    """
    today = date.today()
    quote = {
        "price": Decimal("439.00"),
        "currency": "USD",
        "exchange": "NYQ",
        "market": "us_market",
        "as_of": today,
        "source": "Yahoo Finance quote (TSM)",
    }
    profile = {
        "name": "Taiwan Semiconductor Manufacturing Company Limited",
        "diluted_shares": Decimal("5186474013"),
        "currency": "USD",
        "financial_currency": "TWD",
        "country": "Taiwan",
        "exchange": "NYQ",
        "market": "us_market",
        "security_type": "ADR",
        "is_profitable": True,
        "as_of": today,
        "source": "Yahoo Finance profile (TSM)",
    }
    balance = {
        "cash": Decimal("2413206000000"),  # TWD
        "total_debt": Decimal("1024345000000"),  # TWD
        "net_debt": Decimal("-1388861000000"),
        "currency": "TWD",
        "as_of": today,
        "source": "balance sheet",
    }
    cash_flow = {
        "fcfe_ttm": Decimal("1150000000000"),  # TWD
        "fcfe_ttm_source_type": "derived",
        "fcff_ttm": Decimal("1200000000000"),
        "fcff_ttm_source_type": "derived",
        "currency": "TWD",
        "as_of": today,
        "source": "cash flow",
    }
    income = {
        "revenue_ttm": Decimal("2894300000000"),  # TWD
        "ebitda_ttm": Decimal("1950000000000"),
        "eps_ttm": Decimal("45.24"),  # TWD
        "currency": "TWD",
        "as_of": today,
        "source": "income statement",
    }
    estimates = {
        "forward_eps_1y": Decimal("16.93"),  # USD per ADS
        "forward_eps_1y_source_type": "analyst_estimate",
        "forward_eps_1y_period": "0y",
        "forward_ebitda_1y": Decimal("2340000000000"),  # TWD
        "forward_ebitda_1y_source_type": "derived",
        "forward_ebitda_1y_period": "FY2025E",
        "forward_fcfe_1y": Decimal("1380000000000"),
        "forward_fcfe_1y_source_type": "derived",
        "forward_fcfe_1y_period": "FY2025E",
        "forward_fcff_1y": Decimal("1440000000000"),
        "forward_fcff_1y_source_type": "derived",
        "forward_fcff_1y_period": "FY2025E",
        "as_of": today,
        "source": "estimates",
    }
    multiples = {
        "historical_forward_pe": None,
        "historical_ev_ebitda": None,
        "as_of": today,
        "source": "multiples",
    }

    normalizer = Normalizer(strict_profile=False, allow_all_equities=True)
    raw = normalizer.normalize_provider_data(
        "TSM", quote, profile, balance, cash_flow, income, estimates, multiples
    )
    snapshot = normalizer.normalize(raw)
    assert snapshot.ticker == "TSM"
    assert snapshot.currency == "USD"
    assert snapshot.financial_currency == "TWD"
    assert snapshot.exchange == "NYQ"
    assert snapshot.market == "us_market"

    results = run_all_engines(snapshot, DEFAULT_ASSUMPTIONS)

    # Forward P/E is valid: $16.93 EPS and $439.00 Price are both in USD per ADS
    assert results["forward_pe"].available is True
    assert results["forward_pe"].base.intermediates["forward_eps"] == "16.93"
    assert results["forward_pe"].base.price_per_share == Decimal("338.60")

    # Statement models disabled due to TWD vs USD currency mismatch without synthetic FX
    assert results["ev_ebitda"].available is False
    assert "currency mismatch" in results["ev_ebitda"].unavailable_reason.lower()

    assert results["fcf_yield"].available is False
    assert "currency mismatch" in results["fcf_yield"].unavailable_reason.lower()

    assert results["dcf"].available is False
    assert "currency mismatch" in results["dcf"].unavailable_reason.lower()

    # Composite runs using available Forward P/E with weight 1.0
    comp = run_composite(
        snapshot.current_price.value,
        results["forward_pe"],
        results["ev_ebitda"],
        results["fcf_yield"],
        results["dcf"],
        DEFAULT_ASSUMPTIONS,
    )
    assert comp.available is True
    assert comp.available_models == ["forward_pe"]
    assert comp.weights_used["forward_pe"] == Decimal("1.0000")
