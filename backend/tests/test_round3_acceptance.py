"""
Round 3 acceptance test suite verifying requirements from backend-final-round3.md:
1. Real bounded upstream resources: admission tied to actual future completion,
   in-flight deduplication, recovery after release, no unbounded queues.
2. Total incoming valuation budget across the service/API aggregation path.
3. _verify_forecast_alignment strictly without projection, missing-next, stale,
   non-calendar, and date mismatch handling.
4. ADR currency & share basis evidence enforcement, negative regressions for
   non-USD or unknown currency ADR EPS, and grounded USD/ADS TSM forward P/E.
"""
from datetime import date, datetime, timezone
from decimal import Decimal
import threading
import time
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.domain import FinancialMetric, SourceType
from app.providers.base import ProviderUnavailableError
from app.providers.yfinance_provider import (
    YFinanceProvider,
    _RequestBudget,
    _TickerBundle,
    _SEMAPHORE,
    _verify_forecast_alignment,
)
from app.services.valuation_service import FinancialDataService, Normalizer, ValuationService


# ======================================================================
# 1. Real bounded upstream resources & in-flight reuse
# ======================================================================
def test_bounded_upstream_resources_event_blocked_and_recovery():
    """
    Admission accounting attached to actual future completion:
    5 blocked requests saturate the semaphore; 6th request fails cleanly with timeout.
    Unblocking the event allows all running tasks to finish, releases semaphore slots,
    and subsequent request succeeds immediately.
    """
    provider = YFinanceProvider(timeout=0.15)
    unblock_event = threading.Event()
    started_barrier = threading.Barrier(6)  # 5 worker threads + test runner thread

    def slow_fetch():
        started_barrier.wait(timeout=2.0)
        unblock_event.wait(timeout=5.0)
        return {"quoteType": "EQUITY", "currency": "USD", "regularMarketPrice": 100.0}

    threads = []
    worker_errors = []

    def worker(ticker_id: str):
        try:
            bundle = provider._get_bundle(f"SLOW_{ticker_id}")
            bundle.ticker = MagicMock()
            type(bundle.ticker).info = property(lambda self: slow_fetch())
            # Use longer budget for the 5 holding workers so they don't timeout before unblock
            budget = _RequestBudget(timeout=5.0)
            bundle.get_info(budget=budget)
        except Exception as exc:
            worker_errors.append(exc)

    try:
        # Launch 5 workers to consume all 5 semaphore slots
        for i in range(5):
            t = threading.Thread(target=worker, args=(str(i),), daemon=True)
            threads.append(t)
            t.start()

        # Wait until all 5 workers are inside slow_fetch
        started_barrier.wait(timeout=2.0)
        time.sleep(0.05)

        # 6th request with a tight budget must fail cleanly without acquiring semaphore
        sixth_bundle = provider._get_bundle("SIXTH_TICKER")
        sixth_bundle.ticker = MagicMock()
        type(sixth_bundle.ticker).info = property(lambda self: {"quoteType": "EQUITY", "currency": "USD"})

        short_budget = _RequestBudget(timeout=0.10)
        with pytest.raises(ProviderUnavailableError) as exc_info:
            sixth_bundle.get_info(budget=short_budget)

        assert "semaphore" in str(exc_info.value).lower() or "deadline exceeded" in str(exc_info.value).lower()

    finally:
        # Release the event so the 5 workers complete and release their semaphore slots
        unblock_event.set()
        for t in threads:
            t.join(timeout=3.0)

    assert len(worker_errors) == 0

    # Wait briefly for callbacks to complete releasing semaphore slots
    time.sleep(0.05)

    # Recovery: 7th request on a new bundle must succeed immediately
    seventh_bundle = provider._get_bundle("RECOVERED_TICKER")
    seventh_bundle.ticker = MagicMock()
    type(seventh_bundle.ticker).info = property(
        lambda self: {"quoteType": "EQUITY", "currency": "USD", "regularMarketPrice": 150.0}
    )
    res = seventh_bundle.get_info()
    assert res["regularMarketPrice"] == 150.0


def test_same_ticker_inflight_reuse_no_duplicate_submissions():
    """
    Concurrent requests for the same property on the same ticker bundle attach
    to the already running future rather than submitting duplicate upstream jobs.
    """
    bundle = _TickerBundle("DEDUP_CO", "DEDUP_CO", timeout=5.0)
    fetch_count = 0
    lock = threading.Lock()

    def counting_fetch():
        nonlocal fetch_count
        with lock:
            fetch_count += 1
        time.sleep(0.1)
        return {"quoteType": "EQUITY", "currency": "USD", "shortName": "Dedup Co"}

    bundle.ticker = MagicMock()
    type(bundle.ticker).info = property(lambda self: counting_fetch())

    results = []
    errors = []

    def caller():
        try:
            info = bundle.get_info()
            results.append(info)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=caller, daemon=True) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2.0)

    assert len(errors) == 0
    assert len(results) == 5
    assert fetch_count == 1, f"Expected 1 upstream fetch submission, got {fetch_count}"
    assert results[0]["shortName"] == "Dedup Co"


# ======================================================================
# 2. Total incoming valuation budget across service & API path
# ======================================================================
def test_total_incoming_valuation_budget_across_service_path():
    """
    FinancialDataService.get_snapshot enforces ONE shared incoming deadline
    across all serial category calls. If cumulative delays exceed the total
    budget, the request aborts with ProviderUnavailableError.
    """
    mock_provider = MagicMock(spec=YFinanceProvider)
    today = date.today()

    def delayed_quote(ticker, budget=None):
        time.sleep(0.08)
        if budget:
            budget.check(ticker, "delayed_quote")
        return {"price": Decimal("100.00"), "currency": "USD", "as_of": today, "source": "q"}

    def delayed_profile(ticker, budget=None):
        time.sleep(0.08)
        if budget:
            budget.check(ticker, "delayed_profile")
        return {
            "name": "Test Co",
            "diluted_shares": Decimal("1000000"),
            "country": "United States",
            "security_type": "EQUITY",
            "is_profitable": True,
            "as_of": today,
            "source": "p",
        }

    def delayed_balance(ticker, budget=None):
        time.sleep(0.08)
        if budget:
            budget.check(ticker, "delayed_balance")
        return {"cash": Decimal("100"), "total_debt": Decimal("50"), "as_of": today, "source": "b"}

    mock_provider.get_quote.side_effect = delayed_quote
    mock_provider.get_company_profile.side_effect = delayed_profile
    mock_provider.get_balance_sheet.side_effect = delayed_balance
    mock_provider.get_cash_flow.return_value = {"as_of": today, "source": "cf"}
    mock_provider.get_income_statement.return_value = {"as_of": today, "source": "inc"}
    mock_provider.get_forward_estimates.return_value = {"as_of": today, "source": "est"}
    mock_provider.get_historical_multiples.return_value = {"as_of": today, "source": "m"}

    # Total timeout set to 0.15s: quote (0.08s) + profile (0.08s) = 0.16s > 0.15s
    service = FinancialDataService(provider=mock_provider, timeout=0.15)

    with pytest.raises(ProviderUnavailableError) as exc_info:
        service.get_snapshot("BUDG")

    assert "total deadline exceeded" in str(exc_info.value).lower()


def test_api_valuation_endpoint_total_budget_timeout():
    """
    /api/v1/valuation/{ticker} returns HTTP 503 when total upstream budget is exceeded.
    """
    client = TestClient(app)
    with patch("app.main._resolve_valuation_service") as mock_get_svc:
        mock_svc = MagicMock(spec=ValuationService)
        mock_svc.compute.side_effect = ProviderUnavailableError("Upstream total deadline exceeded (25.0s)")
        mock_get_svc.return_value = mock_svc

        response = client.get("/api/v1/valuation/TIMEOUTCO")
        assert response.status_code == 503
        assert "Provider unavailable" in response.json()["detail"]
        assert "deadline exceeded" in response.json()["detail"].lower()


def test_cached_and_partial_cache_requests_succeed_within_budget():
    """
    Cached and partial-cache requests return immediately without depleting
    the total incoming valuation deadline.
    """
    mock_provider = MagicMock(spec=YFinanceProvider)
    today = date.today()

    mock_provider.get_quote.return_value = {"price": Decimal("100.00"), "currency": "USD", "as_of": today, "source": "q"}
    mock_provider.get_company_profile.return_value = {
        "name": "Test Co",
        "diluted_shares": Decimal("1000000"),
        "country": "United States",
        "security_type": "EQUITY",
        "is_profitable": True,
        "as_of": today,
        "source": "p",
    }
    mock_provider.get_balance_sheet.return_value = {"cash": Decimal("100"), "total_debt": Decimal("50"), "as_of": today, "source": "b"}
    mock_provider.get_cash_flow.return_value = {"as_of": today, "source": "cf"}
    mock_provider.get_income_statement.return_value = {"as_of": today, "source": "inc"}
    mock_provider.get_forward_estimates.return_value = {"as_of": today, "source": "est"}
    mock_provider.get_historical_multiples.return_value = {"as_of": today, "source": "m"}

    service = FinancialDataService(provider=mock_provider, timeout=5.0)

    # First fetch populates cache
    snapshot1 = service.get_snapshot("FASTCO")
    assert snapshot1.ticker == "FASTCO"

    # Second fetch served entirely from cache within a very tight 0.05s budget
    service_short = FinancialDataService(provider=mock_provider, timeout=0.05)
    service_short._cache = service._cache  # Share cache
    snapshot2 = service_short.get_snapshot("FASTCO")
    assert snapshot2.ticker == "FASTCO"


# ======================================================================
# 3. Forecast alignment: strictly no projection & negative cases
# ======================================================================
def test_verify_forecast_alignment_missing_next_fiscal_year():
    """
    When nextFiscalYearEnd is absent, alignment is rejected without fabricating
    a projected next fiscal year date.
    """
    info = {
        "lastFiscalYearEnd": 1735603200,  # 2024-12-31
        # nextFiscalYearEnd missing!
    }
    valid, target_date, label, reason = _verify_forecast_alignment(
        date(2024, 12, 31), "FY2024", info
    )
    assert valid is False
    assert target_date is None
    assert label is None
    assert "nextFiscalYearEnd" in reason
    assert "unproven" in reason


def test_verify_forecast_alignment_stale_and_non_calendar_and_mismatch():
    """
    Validates negative alignment conditions:
    - Date mismatch: nextFiscalYearEnd <= lastFiscalYearEnd
    - Stale horizon: nextFiscalYearEnd < 180 days from statement date
    - Too distant: nextFiscalYearEnd > 450 days from statement date
    - Non-annual statement period: e.g. Q3 or TTM
    """
    # 1. Non-annual statement
    valid, _, _, reason = _verify_forecast_alignment(
        date(2024, 9, 30), "Q3", {"lastFiscalYearEnd": 1735603200, "nextFiscalYearEnd": 1767139200}
    )
    assert valid is False
    assert "not an annual fiscal year statement" in reason

    # 2. Date mismatch (next <= last)
    info_mismatch = {
        "lastFiscalYearEnd": 1735603200,  # 2024-12-31
        "nextFiscalYearEnd": 1735603200,  # 2024-12-31 (same date!)
    }
    valid, _, _, reason = _verify_forecast_alignment(date(2024, 12, 31), "FY2024", info_mismatch)
    assert valid is False
    assert "date mismatch" in reason

    # 3. Stale horizon (< 180 days)
    info_stale = {
        "lastFiscalYearEnd": 1735603200,  # 2024-12-31
        "nextFiscalYearEnd": 1740787200,  # 2025-03-01 (60 days ahead)
    }
    valid, _, _, reason = _verify_forecast_alignment(date(2024, 12, 31), "FY2024", info_stale)
    assert valid is False
    assert "stale or not adjacent" in reason

    # 4. Too distant horizon (> 450 days)
    info_distant = {
        "lastFiscalYearEnd": 1735603200,  # 2024-12-31
        "nextFiscalYearEnd": 1798675200,  # 2026-12-31 (730 days ahead)
    }
    valid, _, _, reason = _verify_forecast_alignment(date(2024, 12, 31), "FY2024", info_distant)
    assert valid is False
    assert "not adjacent" in reason


# ======================================================================
# 4. ADR currency & share basis evidence enforcement
# ======================================================================
def test_adr_currency_validation_rejects_non_usd_or_missing_currency():
    """
    For ADRs, earnings_estimate currency is validated per-row:
    - If currency is non-USD (e.g. TWD or EUR): forward EPS is disabled.
    - If currency is missing/unknown (None or NaN): forward EPS is disabled.
    - If currency is USD: forward EPS is enabled with verified USD/ADS basis.
    """
    provider = YFinanceProvider()

    # 1. Non-USD currency in earnings_estimate
    with patch("yfinance.Ticker") as mock_yf:
        mock_t = MagicMock()
        mock_yf.return_value = mock_t
        mock_t.info = {
            "shortName": "Taiwan Semiconductor ADR",
            "quoteType": "EQUITY",
            "currency": "USD",
            "financialCurrency": "TWD",
            "lastFiscalYearEnd": 1735603200,
            "nextFiscalYearEnd": 1767139200,
        }
        mock_t.financials = pd.DataFrame()
        mock_t.cashflow = pd.DataFrame()
        mock_t.balance_sheet = pd.DataFrame()
        mock_t.revenue_estimate = pd.DataFrame()

        # ee has TWD currency
        mock_t.earnings_estimate = pd.DataFrame(
            {"avg": [16.93], "currency": ["TWD"]},
            index=["0y"],
        )

        est = provider.get_forward_estimates("TSM_NON_USD")
        assert est["forward_eps_1y"] is None
        assert "does not match quote currency" in est["forward_eps_1y_notes"]

    # 2. Missing/NaN currency in earnings_estimate
    with patch("yfinance.Ticker") as mock_yf:
        mock_t = MagicMock()
        mock_yf.return_value = mock_t
        mock_t.info = {
            "shortName": "Taiwan Semiconductor ADR",
            "quoteType": "EQUITY",
            "currency": "USD",
            "financialCurrency": "TWD",
            "lastFiscalYearEnd": 1735603200,
            "nextFiscalYearEnd": 1767139200,
        }
        mock_t.financials = pd.DataFrame()
        mock_t.cashflow = pd.DataFrame()
        mock_t.balance_sheet = pd.DataFrame()
        mock_t.revenue_estimate = pd.DataFrame()

        # ee missing currency column entirely
        mock_t.earnings_estimate = pd.DataFrame(
            {"avg": [16.93]},
            index=["0y"],
        )

        est = provider.get_forward_estimates("TSM_NO_CURR")
        assert est["forward_eps_1y"] is None
        assert "missing/unknown" in est["forward_eps_1y_notes"]

    # 3. Grounded USD currency in earnings_estimate
    with patch("yfinance.Ticker") as mock_yf:
        mock_t = MagicMock()
        mock_yf.return_value = mock_t
        mock_t.info = {
            "shortName": "Taiwan Semiconductor ADR",
            "quoteType": "EQUITY",
            "currency": "USD",
            "financialCurrency": "TWD",
            "lastFiscalYearEnd": 1735603200,
            "nextFiscalYearEnd": 1767139200,
        }
        mock_t.financials = pd.DataFrame()
        mock_t.cashflow = pd.DataFrame()
        mock_t.balance_sheet = pd.DataFrame()
        mock_t.revenue_estimate = pd.DataFrame()

        mock_t.earnings_estimate = pd.DataFrame(
            {"avg": [16.93], "currency": ["USD"]},
            index=["0y"],
        )

        est = provider.get_forward_estimates("TSM_USD")
        assert est["forward_eps_1y"] == Decimal("16.93")
        assert est["forward_eps_1y_currency"] == "USD"
        assert est["forward_eps_basis"] == "ADS"
        assert "USD/ADS" in est["forward_eps_1y_notes"]
