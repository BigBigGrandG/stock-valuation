"""
Live Yahoo Finance data provider implementing the seven FinancialDataProvider methods.
Fetches real market quotes, company profiles, financial statements, analyst estimates,
and historical valuation multiples via yfinance.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from contextvars import ContextVar
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Optional

import yfinance as yf

from app.models.domain import DataQuality, SourceType
from app.providers.base import (
    BalanceSheetData,
    CashFlowData,
    CompanyProfileData,
    FinancialDataProvider,
    FinancialDataValidationError,
    ForwardEstimatesData,
    HistoricalMultiplesData,
    IncomeStatementData,
    InvalidTickerError,
    ProviderError,
    ProviderRateLimitError,
    ProviderUnavailableError,
    QuoteData,
    TickerNotFoundError,
    UnsupportedCompanyError,
)
from app.providers.share_reconciliation import reconcile_share_capital
from app.providers.statement_aggregator import (
    aggregate_ttm_cashflow,
    aggregate_ttm_income,
    extract_latest_balance_sheet,
)

logger = logging.getLogger(__name__)

import concurrent.futures
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from contextlib import contextmanager

# Module-level executor for bounded upstream fetches
_EXECUTOR = ThreadPoolExecutor(max_workers=32, thread_name_prefix="yf_fetch")

# Bounded upstream concurrency
_MAX_CONCURRENCY = int(os.getenv("UPSTREAM_MAX_CONCURRENT_REQUESTS", "5"))
_SEMAPHORE = threading.BoundedSemaphore(_MAX_CONCURRENCY)
_SEMAPHORE_TIMEOUT = float(os.getenv("UPSTREAM_SEMAPHORE_TIMEOUT", "10.0"))


@contextmanager
def _bounded_semaphore(timeout: float = _SEMAPHORE_TIMEOUT):
    acquired = _SEMAPHORE.acquire(timeout=timeout)
    if not acquired:
        raise ProviderUnavailableError(f"Concurrency semaphore acquisition timed out ({timeout}s)")
    try:
        yield
    finally:
        _SEMAPHORE.release()


def _classify_and_raise(exc: Exception, raw_ticker: str, context: str = "") -> None:
    """Map yfinance/network errors to domain exceptions without swallowing or fabricating."""
    if isinstance(exc, (ProviderError, FinancialDataValidationError)):
        raise exc

    err_str = str(exc).lower()
    exc_type = type(exc).__name__.lower()
    status_code = (
        getattr(exc, "status_code", None)
        or getattr(getattr(exc, "response", None), "status_code", None)
        or getattr(exc, "code", None)
    )

    if (
        status_code == 429
        or "429" in err_str
        or "too many requests" in err_str
        or "rate limit" in err_str
    ):
        raise ProviderRateLimitError(f"Rate limited by Yahoo Finance for {raw_ticker}: {exc}") from exc

    if (
        status_code == 404
        or "404" in err_str
        or "not found" in err_str
        or "delisted" in err_str
        or "no data found" in err_str
    ):
        raise TickerNotFoundError(f"Ticker '{raw_ticker}' not found on Yahoo Finance: {exc}") from exc

    if (
        status_code in (500, 502, 503, 504)
        or "503" in err_str
        or "502" in err_str
        or "500" in err_str
        or "504" in err_str
        or "unavailable" in err_str
        or "connection" in err_str
        or "timeout" in err_str
        or "timed out" in err_str
        or "timeout" in exc_type
        or isinstance(exc, (TimeoutError, ConnectionError, OSError))
    ):
        raise ProviderUnavailableError(f"Yahoo Finance service error/timeout for {raw_ticker} ({context}): {exc}") from exc

# Short internal cache (seconds) so 7 consecutive calls within the same request
# share the same underlying yfinance Ticker bundle.
_BUNDLE_TTL = 30.0


def _to_decimal(val: Any) -> Optional[Decimal]:
    if val is None:
        return None
    try:
        # Check float nan/inf
        if isinstance(val, float):
            import math
            if math.isnan(val) or math.isinf(val):
                return None
        d = Decimal(str(val))
        if not d.is_finite():
            return None
        return d
    except (InvalidOperation, ValueError, TypeError):
        return None


def _normalize_query_symbol(ticker: str) -> str:
    """Normalize ticker for Yahoo Finance query (e.g. BRK.B -> BRK-B, BF.B -> BF-B)."""
    t = ticker.strip().upper()
    return t.replace(".", "-")


_UPSTREAM_TOTAL_TIMEOUT = float(os.getenv("UPSTREAM_TOTAL_TIMEOUT", "25.0"))
current_request_budget: ContextVar[Optional[_RequestBudget]] = ContextVar("current_request_budget", default=None)


class _RequestBudget:
    """Per-request deadline budget. Cache age is NOT the request clock."""

    def __init__(self, timeout: float = _UPSTREAM_TOTAL_TIMEOUT):
        self.start = time.monotonic()
        self.timeout = timeout
        self.deadline = self.start + timeout

    @property
    def remaining(self) -> float:
        return max(0.001, self.deadline - time.monotonic())

    def check(self, ticker: str, context: str) -> None:
        elapsed = time.monotonic() - self.start
        if elapsed >= self.timeout:
            raise ProviderUnavailableError(
                f"Upstream total deadline exceeded ({self.timeout:.1f}s) for {ticker} ({context})"
            )


def _verify_forecast_alignment(
    statement_as_of: Optional[date],
    statement_period: str,
    info: dict[str, Any],
) -> tuple[bool, Optional[date], Optional[str], Optional[str]]:
    """
    Verifies that an annual statement column date aligns with the latest completed
    fiscal year and that the consensus 0y forecast horizon is adjacent.

    Returns:
        (is_valid, target_date, target_label_0y, failure_reason)
    """
    if statement_as_of is None or not str(statement_period).startswith("FY"):
        return False, None, None, f"Base statement is not an annual fiscal year statement (period={statement_period})"

    last_fy_ts = info.get("lastFiscalYearEnd")
    if not isinstance(last_fy_ts, (int, float)) or last_fy_ts <= 0:
        return False, None, None, "Missing upstream fiscal year end metadata (lastFiscalYearEnd); alignment unproven"

    last_fy_date = datetime.fromtimestamp(last_fy_ts, tz=timezone.utc).date()

    # Statement date vs last_fy_date (allow 14 days tolerance for floating/weekend fiscal year-ends)
    days_lag = (last_fy_date - statement_as_of).days
    if days_lag > 14:
        return False, None, None, f"Statement date ({statement_as_of}) lags completed fiscal year end ({last_fy_date}, delta={days_lag}d); 0y growth cannot be applied to lagging statement"
    if days_lag < -14:
        return False, None, None, f"Statement date ({statement_as_of}) is ahead of reported lastFiscalYearEnd ({last_fy_date}, delta={days_lag}d); alignment unproven"

    # Next fiscal year end verification - strictly required from upstream metadata without unproven projection
    next_fy_ts = info.get("nextFiscalYearEnd")
    if not isinstance(next_fy_ts, (int, float)) or next_fy_ts <= 0:
        return False, None, None, "Missing upstream next fiscal year end metadata (nextFiscalYearEnd); forecast horizon unproven"

    next_fy_date = datetime.fromtimestamp(next_fy_ts, tz=timezone.utc).date()
    if next_fy_date <= last_fy_date:
        return False, None, None, f"nextFiscalYearEnd ({next_fy_date}) is not after lastFiscalYearEnd ({last_fy_date}); date mismatch"

    days_to_next = (next_fy_date - statement_as_of).days
    if days_to_next < 180:
        return False, None, None, f"Forecast 0y horizon ({next_fy_date}) is stale or not adjacent to base statement ({statement_as_of}, delta={days_to_next}d); cannot apply 0y growth"
    if days_to_next > 450:
        return False, None, None, f"Forecast 0y horizon ({next_fy_date}) is not adjacent (too distant) to base statement ({statement_as_of}, delta={days_to_next}d); cannot apply 0y growth"

    # 0y estimate horizon independently maps to nextFiscalYearEnd:
    # In Yahoo Finance analyst consensus, '0y' represents the in-progress fiscal year
    # ending at nextFiscalYearEnd, confirmed by info.epsCurrentYear and info.nextFiscalYearEnd.
    target_date = next_fy_date
    target_label = f"FY{next_fy_date.year}E"
    return True, target_date, target_label, None


class _TickerBundle:
    """Container caching fetched yfinance properties for a single ticker with thread-safe deduplication and deadline."""

    def __init__(self, raw_ticker: str, query_symbol: str, timeout: float = _UPSTREAM_TOTAL_TIMEOUT):
        self.raw_ticker = raw_ticker
        self.query_symbol = query_symbol
        self.timeout = timeout
        self.fetched_at = time.monotonic()
        self.ticker = yf.Ticker(query_symbol)
        self._lock = threading.Lock()
        self._inflight: dict[str, concurrent.futures.Future] = {}
        self._info: Optional[dict[str, Any]] = None
        self._bs: Any = None
        self._cf: Any = None
        self._fin: Any = None
        self._ee: Any = None
        self._re: Any = None

    def has_inflight(self) -> bool:
        with self._lock:
            return bool(self._inflight)

    def _check_deadline(self, budget: Optional[_RequestBudget] = None) -> None:
        if budget is not None:
            budget.check(self.raw_ticker, "deadline check")
        else:
            elapsed = time.monotonic() - self.fetched_at
            if elapsed > self.timeout:
                raise ProviderUnavailableError(
                    f"Upstream total deadline exceeded ({self.timeout:.1f}s) for {self.raw_ticker} (elapsed {elapsed:.1f}s)"
                )

    def _fetch_property(
        self,
        prop_name: str,
        fetcher: Any,
        budget: Optional[_RequestBudget],
        context: str,
    ) -> Any:
        cached = getattr(self, prop_name)
        if cached is not None:
            return cached

        req_budget = budget or current_request_budget.get() or _RequestBudget(self.timeout)
        req_budget.check(self.raw_ticker, f"before acquiring bundle lock for {context}")

        rem = req_budget.remaining
        acquired = self._lock.acquire(timeout=rem)
        if not acquired:
            raise ProviderUnavailableError(
                f"Upstream total deadline exceeded ({req_budget.timeout:.1f}s) for {self.raw_ticker} waiting for bundle lock ({context})"
            )
        future = None
        new_submission = False
        try:
            cached = getattr(self, prop_name)
            if cached is not None:
                return cached

            # Reuse in-flight future for this property if already running
            future = self._inflight.get(prop_name)
            if future is None:
                req_budget.check(self.raw_ticker, f"before acquiring semaphore for {context}")
                rem = req_budget.remaining
                acquired_sem = _SEMAPHORE.acquire(timeout=rem)
                if not acquired_sem:
                    raise ProviderUnavailableError(
                        f"Upstream total deadline exceeded ({req_budget.timeout:.1f}s) for {self.raw_ticker} waiting for concurrency semaphore ({context})"
                    )
                try:
                    req_budget.check(self.raw_ticker, f"before upstream submit for {context}")
                    future = _EXECUTOR.submit(fetcher)
                    self._inflight[prop_name] = future
                    new_submission = True
                except Exception:
                    _SEMAPHORE.release()
                    raise
        finally:
            self._lock.release()

        if new_submission and future is not None:
            # Keep admission accounting attached to actual future completion
            def _on_future_done(fut: concurrent.futures.Future) -> None:
                try:
                    if fut.exception() is None:
                        setattr(self, prop_name, fut.result())
                except Exception:
                    pass
                finally:
                    with self._lock:
                        if self._inflight.get(prop_name) is fut:
                            self._inflight.pop(prop_name, None)
                    _SEMAPHORE.release()

            future.add_done_callback(_on_future_done)

        # Wait outside bundle lock for completion within remaining budget
        rem = req_budget.remaining
        try:
            result = future.result(timeout=rem)
            return result
        except FutureTimeoutError as exc:
            raise ProviderUnavailableError(
                f"Upstream request timed out ({req_budget.timeout:.1f}s) for {self.raw_ticker} during {context}"
            ) from exc
        except Exception as exc:
            _classify_and_raise(exc, self.raw_ticker, context)
            raise ProviderUnavailableError(
                f"Failed to fetch {context} for {self.raw_ticker}: {exc}"
            ) from exc

    def get_info(self, budget: Optional[_RequestBudget] = None) -> dict[str, Any]:
        info = self._fetch_property("_info", lambda: self.ticker.info, budget, "info")
        return info if isinstance(info, dict) else {}

    def get_balance_sheet(self, budget: Optional[_RequestBudget] = None) -> Any:
        return self._fetch_property("_bs", lambda: self.ticker.balance_sheet, budget, "balance sheet")

    def get_quarterly_balance_sheet(self, budget: Optional[_RequestBudget] = None) -> Any:
        try:
            return self._fetch_property("_qbs", lambda: self.ticker.quarterly_balance_sheet, budget, "quarterly balance sheet")
        except Exception:
            return None

    def get_cashflow(self, budget: Optional[_RequestBudget] = None) -> Any:
        return self._fetch_property("_cf", lambda: self.ticker.cashflow, budget, "cashflow")

    def get_quarterly_cashflow(self, budget: Optional[_RequestBudget] = None) -> Any:
        try:
            return self._fetch_property("_qcf", lambda: self.ticker.quarterly_cashflow, budget, "quarterly cashflow")
        except Exception:
            return None

    def get_financials(self, budget: Optional[_RequestBudget] = None) -> Any:
        return self._fetch_property("_fin", lambda: self.ticker.financials, budget, "financials")

    def get_quarterly_financials(self, budget: Optional[_RequestBudget] = None) -> Any:
        try:
            return self._fetch_property("_qfin", lambda: self.ticker.quarterly_financials, budget, "quarterly financials")
        except Exception:
            return None

    def get_earnings_estimate(self, budget: Optional[_RequestBudget] = None) -> Any:
        try:
            return self._fetch_property("_ee", lambda: self.ticker.earnings_estimate, budget, "earnings estimate")
        except Exception as exc:
            logger.debug(f"Earnings estimate not available for {self.raw_ticker}: {exc}")
            return None

    def get_revenue_estimate(self, budget: Optional[_RequestBudget] = None) -> Any:
        try:
            return self._fetch_property("_re", lambda: self.ticker.revenue_estimate, budget, "revenue estimate")
        except Exception as exc:
            logger.debug(f"Revenue estimate not available for {self.raw_ticker}: {exc}")
            return None


class YFinanceProvider(FinancialDataProvider):
    """
    Live Yahoo Finance provider implementing all 7 FinancialDataProvider methods.
    Supports arbitrary listed US equities with real quotes, statements, forward
    estimates, and historical multiples.
    """

    def __init__(self, timeout: Optional[float] = None):
        self._cache: dict[str, _TickerBundle] = {}
        self._lock = threading.Lock()
        self.is_demo = False
        self.timeout = timeout if timeout is not None else _UPSTREAM_TOTAL_TIMEOUT

    def _get_active_budget(self, explicit_budget: Optional[_RequestBudget] = None) -> _RequestBudget:
        if explicit_budget is not None:
            return explicit_budget
        ctx = current_request_budget.get()
        if ctx is not None:
            return ctx
        return _RequestBudget(self.timeout)

    def _get_bundle(self, ticker: str) -> _TickerBundle:
        norm = ticker.strip().upper()
        query = _normalize_query_symbol(norm)
        now = time.monotonic()
        with self._lock:
            bundle = self._cache.get(norm)
            if bundle is None or ((now - bundle.fetched_at) > _BUNDLE_TTL and not bundle.has_inflight()):
                bundle = _TickerBundle(norm, query, timeout=self.timeout)
                self._cache[norm] = bundle
            return bundle

    def _verify_equity(self, ticker: str, info: dict[str, Any]) -> None:
        """Reject non-equity securities like ETFs, mutual funds, indices, crypto."""
        quote_type = str(info.get("quoteType") or "").upper()
        if quote_type in {"ETF", "MUTUALFUND", "INDEX", "CRYPTOCURRENCY", "CURRENCY", "FUTURE", "OPTION"}:
            raise UnsupportedCompanyError(
                ticker,
                reason=quote_type.lower(),
                detail=f"Non-equity security type: {quote_type}",
            )

    # ------------------------------------------------------------------
    # 1. get_quote
    # ------------------------------------------------------------------
    def get_quote(self, ticker: str, budget: Optional[_RequestBudget] = None) -> QuoteData:
        req_budget = self._get_active_budget(budget)
        req_budget.check(ticker, "get_quote")
        bundle = self._get_bundle(ticker)
        info = bundle.get_info(req_budget)

        # Check for 404 / nonexistent ticker
        price_val = (
            info.get("currentPrice")
            or info.get("regularMarketPrice")
            or info.get("previousClose")
        )
        if price_val is None:
            # Fallback: check 1d history with bounded semaphore and timeout
            try:
                with _bounded_semaphore(timeout=req_budget.remaining):
                    hist = bundle.ticker.history(period="1d", timeout=min(10, int(req_budget.remaining) + 1))
                if hist is not None and not hist.empty and "Close" in hist.columns:
                    price_val = float(hist["Close"].iloc[-1])
            except Exception as exc:
                _classify_and_raise(exc, ticker, "quote history fallback")

        if price_val is None or float(price_val) <= 0:
            raise TickerNotFoundError(f"Ticker '{ticker}' not found or has no market price on Yahoo Finance")

        self._verify_equity(ticker, info)

        price = Decimal(str(price_val)).quantize(Decimal("0.01"), ROUND_HALF_UP)
        currency = str(info.get("currency") or "USD").upper()

        reg_time = info.get("regularMarketTime")
        if isinstance(reg_time, (int, float)) and reg_time > 0:
            ts = datetime.fromtimestamp(reg_time, tz=timezone.utc).replace(tzinfo=None)
            as_of_date = ts.date()
        else:
            ts = datetime.now(timezone.utc).replace(tzinfo=None)
            as_of_date = ts.date()

        return {
            "price": price,
            "currency": currency,
            "exchange": str(info.get("exchange") or "") or None,
            "market": str(info.get("market") or "") or None,
            "timestamp": ts,
            "as_of": as_of_date,
            "source": f"Yahoo Finance live quote ({bundle.query_symbol})",
        }

    # ------------------------------------------------------------------
    # 2. get_company_profile
    # ------------------------------------------------------------------
    def get_company_profile(self, ticker: str, budget: Optional[_RequestBudget] = None) -> CompanyProfileData:
        req_budget = self._get_active_budget(budget)
        req_budget.check(ticker, "get_company_profile")
        bundle = self._get_bundle(ticker)
        info = bundle.get_info(req_budget)
        self._verify_equity(ticker, info)

        name = (
            info.get("shortName")
            or info.get("longName")
            or ticker.strip().upper()
        )

        # As of date from quote
        reg_time = info.get("regularMarketTime")
        if isinstance(reg_time, (int, float)) and reg_time > 0:
            as_of_date = datetime.fromtimestamp(reg_time, tz=timezone.utc).date()
        else:
            as_of_date = date.today()

        q_bs = bundle.get_quarterly_balance_sheet(req_budget)
        a_bs = bundle.get_balance_sheet(req_budget)
        try:
            share_res = reconcile_share_capital(
                info=info,
                quarterly_bs=q_bs,
                annual_bs=a_bs,
                default_as_of=as_of_date,
                ticker=bundle.query_symbol,
            )
            shares = share_res.shares
            shares_source = share_res.source
            shares_as_of = share_res.as_of
            shares_period = share_res.period
            shares_notes = share_res.notes
            shares_estimated = share_res.is_estimated
            shares_basis = share_res.basis
            shares_reconciliation = share_res.reconciliation
        except Exception as exc:
            raise FinancialDataValidationError(f"Could not determine diluted shares for ticker '{ticker}': {exc}") from exc
        country = info.get("country", "US")
        sector = info.get("sector")
        industry = info.get("industry")
        security_type = str(info.get("quoteType") or "COMMON_STOCK")
        financial_currency = str(info.get("financialCurrency") or info.get("currency") or "USD").upper()

        # ADR check
        is_adr = (
            security_type.upper() == "ADR"
            or "ADR" in name.upper()
            or "ADR" in str(info.get("shortName") or "").upper()
            or "ADS" in str(info.get("shortName") or "").upper()
        )
        profile_notes = "American Depositary Receipt (ADR); per-share metrics reflect depositary share basis" if is_adr else None

        # Profitability check
        trailing_eps = info.get("trailingEps")
        forward_eps = info.get("forwardEps")
        is_profitable: Optional[bool] = None
        if trailing_eps is not None:
            is_profitable = float(trailing_eps) > 0
        elif forward_eps is not None:
            is_profitable = float(forward_eps) > 0

        return {
            "name": name,
            "ticker": ticker.strip().upper(),
            "diluted_shares": shares,
            "diluted_shares_source": shares_source,
            "diluted_shares_as_of": shares_as_of,
            "diluted_shares_period": shares_period,
            "diluted_shares_notes": shares_notes,
            "diluted_shares_is_estimated": shares_estimated,
            "diluted_shares_source_type": "derived",
            "shares_basis": shares_basis,
            "shares_reconciliation": shares_reconciliation,
            "currency": str(info.get("currency") or "USD").upper(),
            "financial_currency": financial_currency,
            "country": country,
            "exchange": str(info.get("exchange") or "") or None,
            "market": str(info.get("market") or "") or None,
            "security_type": security_type,
            "sector": sector,
            "industry": industry,
            "is_profitable": is_profitable,
            "as_of": as_of_date,
            "notes": profile_notes,
            "source": f"Yahoo Finance profile ({bundle.query_symbol})",
        }

    # ------------------------------------------------------------------
    # 3. get_balance_sheet
    # ------------------------------------------------------------------
    def get_balance_sheet(self, ticker: str, budget: Optional[_RequestBudget] = None) -> BalanceSheetData:
        req_budget = self._get_active_budget(budget)
        req_budget.check(ticker, "get_balance_sheet")
        bundle = self._get_bundle(ticker)
        info = bundle.get_info(req_budget)
        q_bs = bundle.get_quarterly_balance_sheet(req_budget)
        a_bs = bundle.get_balance_sheet(req_budget)
        agg_bs = extract_latest_balance_sheet(q_bs, a_bs, date.today())

        cash_val = agg_bs["cash"]
        debt_val = agg_bs["total_debt"]
        net_debt = agg_bs["net_debt"]
        period_str = agg_bs["period"]
        bs_as_of = agg_bs["as_of"]

        # Fallback to quote info only if statement data is completely missing
        if cash_val is None and debt_val is None:
            cash_info = info.get("totalCash")
            if cash_info is not None:
                c_dec = _to_decimal(cash_info)
                if c_dec is not None and c_dec >= 0:
                    cash_val = c_dec
            debt_info = info.get("totalDebt")
            if debt_info is not None:
                d_dec = _to_decimal(debt_info)
                if d_dec is not None and d_dec >= 0:
                    debt_val = d_dec
            net_debt = (debt_val - cash_val) if (debt_val is not None and cash_val is not None) else None
            period_str = "latest"

        return {
            "cash": cash_val,
            "total_debt": debt_val,
            "net_debt": net_debt,
            "period": period_str,
            "as_of": bs_as_of,
            "source": f"Yahoo Finance balance sheet ({bundle.query_symbol})",
        }

    # ------------------------------------------------------------------
    # 4. get_cash_flow
    # ------------------------------------------------------------------
    def get_cash_flow(self, ticker: str, budget: Optional[_RequestBudget] = None) -> CashFlowData:
        req_budget = self._get_active_budget(budget)
        req_budget.check(ticker, "get_cash_flow")
        bundle = self._get_bundle(ticker)
        info = bundle.get_info(req_budget)
        cf = bundle.get_cashflow(req_budget)
        fin = bundle.get_financials(req_budget)

        cf_as_of = date.today()
        period_str = "TTM"
        statement_basis = "TTM"
        annual_fallback = False
        is_annual_statement = False

        cfo: Optional[Decimal] = None
        capex: Optional[Decimal] = None
        net_borrowing: Optional[Decimal] = None
        has_net_borrowing = False

        agg = aggregate_ttm_cashflow(
            quarterly_cf=bundle.get_quarterly_cashflow(req_budget),
            annual_cf=bundle.get_cashflow(req_budget),
            quarterly_fin=bundle.get_quarterly_financials(req_budget),
            annual_fin=bundle.get_financials(req_budget),
            default_as_of=date.today(),
        )
        cfo = agg["cfo"]
        capex = agg["capex"]
        net_borrowing = agg["net_borrowing"]
        has_net_borrowing = agg["has_net_borrowing"]
        interest = agg["interest"]
        tax_rate = agg["tax_rate"]
        statement_basis = agg["statement_basis"]
        annual_fallback = agg["annual_fallback"]
        cf_as_of = agg["as_of"]
        period_str = agg["period"]
        is_annual_statement = annual_fallback

        # Fallback to info ONLY when statements are completely missing
        if cfo is None and capex is None:
            cfo_info = info.get("operatingCashflow")
            fcf_info = info.get("freeCashflow")
            if cfo_info is not None:
                cfo = _to_decimal(cfo_info)
            if fcf_info is not None and cfo is not None:
                fcf_dec = _to_decimal(fcf_info)
                if fcf_dec is not None:
                    capex = max(Decimal("0"), cfo - fcf_dec)
            period_str = "TTM"
            statement_basis = "TTM"
            is_annual_statement = False
            annual_fallback = False

        # --------------------------------------------------------------
        # CRUCIAL: FCFE vs FCFF formulas
        # FCFE = CFO - capex + net_borrowing (if available; approximation if not)
        # FCFF = CFO + interest*(1 - tax_rate) - capex
        # Missing cash/debt/CFO/capex/interest/tax must NOT become zero without explicit assumptions!
        # --------------------------------------------------------------
        fcfe: Optional[Decimal] = None
        fcfe_def: str
        if cfo is None or capex is None:
            fcfe = None
            fcfe_def = "FCFE unavailable: missing operating cash flow or capital expenditure in statement"
        elif has_net_borrowing and net_borrowing is not None:
            fcfe = cfo - capex + net_borrowing
            fcfe_def = "FCFE = CFO - capex + net borrowing"
        else:
            fcfe = cfo - capex
            fcfe_def = "FCFE = CFO - capex (approximation: net borrowing component not reported)"

        fcff: Optional[Decimal] = None
        fcff_def: str
        if cfo is None or capex is None:
            fcff = None
            fcff_def = "FCFF unavailable: missing operating cash flow or capital expenditure in statement"
        elif interest is None:
            fcff = None
            fcff_def = "FCFF unavailable: interest expense missing from financials for firm cash flow calculation (same fiscal date)"
        elif interest == Decimal("0"):
            fcff = cfo - capex
            fcff_def = "FCFF = CFO - capex (unlevered firm cash flow, zero interest expense)"
        elif tax_rate is None:
            fcff = None
            fcff_def = "FCFF unavailable: tax rate missing from financials for after-tax interest calculation"
        else:
            after_tax_interest = (interest * (Decimal("1") - tax_rate)).quantize(Decimal("0.01"), ROUND_HALF_UP)
            fcff = cfo + after_tax_interest - capex
            fcff_def = f"FCFF = CFO + interest*(1-tax) - capex (unlevered firm cash flow at tax_rate={tax_rate})"

        # Forward estimates from analyst growth if positive and base statement is annual
        ee = bundle.get_earnings_estimate(req_budget)
        re_est = bundle.get_revenue_estimate(req_budget)

        forward_fcfe_1y: Optional[Decimal] = None
        forward_fcfe_2y: Optional[Decimal] = None
        forward_fcff_1y: Optional[Decimal] = None
        forward_fcff_2y: Optional[Decimal] = None
        forward_fcfe_1y_notes: Optional[str] = None
        forward_fcfe_2y_notes: Optional[str] = None
        forward_fcff_1y_notes: Optional[str] = None
        forward_fcff_2y_notes: Optional[str] = None

        g_eps1: Optional[Decimal] = None
        g_eps2: Optional[Decimal] = None
        g_rev1: Optional[Decimal] = None
        g_rev2: Optional[Decimal] = None

        if ee is not None and hasattr(ee, "index") and not ee.empty:
            if "0y" in ee.index and "growth" in ee.columns:
                g_eps1 = _to_decimal(ee.loc["0y", "growth"])
            if "+1y" in ee.index and "growth" in ee.columns:
                g_eps2 = _to_decimal(ee.loc["+1y", "growth"])

        if re_est is not None and hasattr(re_est, "index") and not re_est.empty:
            if "0y" in re_est.index and "growth" in re_est.columns:
                g_rev1 = _to_decimal(re_est.loc["0y", "growth"])
            if "+1y" in re_est.index and "growth" in re_est.columns:
                g_rev2 = _to_decimal(re_est.loc["+1y", "growth"])

        # Growth rates capped reasonably (-20% to +40%) for justified projections
        g_fe1 = g_eps1 if g_eps1 is not None else g_rev1
        g_fe2 = g_eps2 if g_eps2 is not None else g_rev2
        g_ff1 = g_rev1 if g_rev1 is not None else g_eps1
        g_ff2 = g_rev2 if g_rev2 is not None else g_eps2

        g_fe1_clamped = min(max(g_fe1, Decimal("-0.20")), Decimal("0.40")) if g_fe1 is not None else None
        g_fe2_clamped = min(max(g_fe2, Decimal("-0.20")), Decimal("0.40")) if g_fe2 is not None else None
        g_ff1_clamped = min(max(g_ff1, Decimal("-0.20")), Decimal("0.40")) if g_ff1 is not None else None
        g_ff2_clamped = min(max(g_ff2, Decimal("-0.20")), Decimal("0.40")) if g_ff2 is not None else None

        # Verify exact fiscal end and forecast horizon alignment
        aligned_cf, target_cf_date, target_cf_label, align_cf_fail = _verify_forecast_alignment(
            cf_as_of if is_annual_statement else None,
            period_str,
            info,
        )

        fcfe_period_1y = "0y"
        fcfe_period_2y = "+1y"
        fcff_period_1y = "0y"
        fcff_period_2y = "+1y"

        # Only apply growth if base is an annual statement with proven, non-lagging fiscal date
        if aligned_cf and fcfe is not None and fcfe > 0 and g_fe1_clamped is not None:
            forward_fcfe_1y = (fcfe * (Decimal("1") + g_fe1_clamped)).quantize(Decimal("0.01"), ROUND_HALF_UP)
            forward_fcfe_1y_notes = f"Derived forward FCFE for {target_cf_label} (0y) from base {period_str} annual FCFE ({fcfe}) as of {cf_as_of}; raw_growth={g_fe1}, capped_growth={g_fe1_clamped}, formula={period_str}_FCFE × (1 + g)"
            if g_fe2_clamped is not None:
                forward_fcfe_2y = (forward_fcfe_1y * (Decimal("1") + g_fe2_clamped)).quantize(Decimal("0.01"), ROUND_HALF_UP)
                forward_fcfe_2y_notes = f"Derived forward FCFE for (+1y) from forward {target_cf_label} FCFE ({forward_fcfe_1y}); raw_growth={g_fe2}, capped_growth={g_fe2_clamped}, formula=FCFE_1y × (1 + g)"
        elif not aligned_cf:
            forward_fcfe_1y_notes = f"Forward FCFE unavailable: {align_cf_fail}"
            forward_fcfe_2y_notes = f"Forward FCFE unavailable: {align_cf_fail}"

        if aligned_cf and fcff is not None and fcff > 0 and g_ff1_clamped is not None:
            forward_fcff_1y = (fcff * (Decimal("1") + g_ff1_clamped)).quantize(Decimal("0.01"), ROUND_HALF_UP)
            forward_fcff_1y_notes = f"Derived forward FCFF for {target_cf_label} (0y) from base {period_str} annual FCFF ({fcff}) as of {cf_as_of}; raw_growth={g_ff1}, capped_growth={g_ff1_clamped}, formula={period_str}_FCFF × (1 + g)"
            if g_ff2_clamped is not None:
                forward_fcff_2y = (forward_fcff_1y * (Decimal("1") + g_ff2_clamped)).quantize(Decimal("0.01"), ROUND_HALF_UP)
                forward_fcff_2y_notes = f"Derived forward FCFF for (+1y) from forward {target_cf_label} FCFF ({forward_fcff_1y}); raw_growth={g_ff2}, capped_growth={g_ff2_clamped}, formula=FCFF_1y × (1 + g)"
        elif not aligned_cf:
            forward_fcff_1y_notes = f"Forward FCFF unavailable: {align_cf_fail}"
            forward_fcff_2y_notes = f"Forward FCFF unavailable: {align_cf_fail}"

        period_note = "Annual fiscal year statement" if is_annual_statement else "TTM quote summary"
        return {
            "fcfe_ttm": fcfe,
            "fcfe_ttm_source_type": "derived" if fcfe is not None else None,
            "fcfe_definition": fcfe_def,
            "forward_fcfe_1y": forward_fcfe_1y,
            "forward_fcfe_1y_source_type": "derived" if forward_fcfe_1y is not None else None,
            "forward_fcfe_1y_period": fcfe_period_1y,
            "forward_fcfe_1y_notes": forward_fcfe_1y_notes,
            "forward_fcfe_2y": forward_fcfe_2y,
            "forward_fcfe_2y_source_type": "derived" if forward_fcfe_2y is not None else None,
            "forward_fcfe_2y_period": fcfe_period_2y,
            "forward_fcfe_2y_notes": forward_fcfe_2y_notes,
            "fcff_ttm": fcff,
            "fcff_ttm_source_type": "derived" if fcff is not None else None,
            "fcff_definition": fcff_def,
            "forward_fcff_1y": forward_fcff_1y,
            "forward_fcff_1y_source_type": "derived" if forward_fcff_1y is not None else None,
            "forward_fcff_1y_period": fcff_period_1y,
            "forward_fcff_1y_notes": forward_fcff_1y_notes,
            "forward_fcff_2y": forward_fcff_2y,
            "forward_fcff_2y_source_type": "derived" if forward_fcff_2y is not None else None,
            "forward_fcff_2y_period": fcff_period_2y,
            "forward_fcff_2y_notes": forward_fcff_2y_notes,
            "period": period_str,
            "statement_basis": statement_basis,
            "annual_fallback": annual_fallback,
            "as_of": cf_as_of,
            "notes": period_note,
            "source": f"Yahoo Finance cash flow statement ({bundle.query_symbol})",
        }

    # ------------------------------------------------------------------
    # 5. get_income_statement
    # ------------------------------------------------------------------
    def get_income_statement(self, ticker: str, budget: Optional[_RequestBudget] = None) -> IncomeStatementData:
        req_budget = self._get_active_budget(budget)
        req_budget.check(ticker, "get_income_statement")
        bundle = self._get_bundle(ticker)
        info = bundle.get_info(req_budget)
        fin = bundle.get_financials(req_budget)

        rev: Optional[Decimal] = None
        ebitda: Optional[Decimal] = None
        eps: Optional[Decimal] = None
        inc_as_of = date.today()
        period_str = "TTM"
        statement_basis = "TTM"
        annual_fallback = False
        is_annual = False

        agg = aggregate_ttm_income(
            quarterly_fin=bundle.get_quarterly_financials(req_budget),
            annual_fin=bundle.get_financials(req_budget),
            default_as_of=date.today(),
        )
        rev = agg["revenue"]
        ebitda = agg["ebitda"]
        statement_basis = agg["statement_basis"]
        annual_fallback = agg["annual_fallback"]
        inc_as_of = agg["as_of"]
        period_str = agg["period"]

        # Trailing EPS from quote info
        eps = _to_decimal(info.get("trailingEps"))

        # Fallback to info ONLY when statements are completely missing
        if rev is None and ebitda is None:
            rev_info = info.get("totalRevenue")
            if rev_info is not None:
                rev = _to_decimal(rev_info)
            ebitda_info = info.get("ebitda")
            if ebitda_info is not None:
                ebitda = _to_decimal(ebitda_info)
            period_str = "TTM"

        return {
            "revenue_ttm": rev,
            "ebitda_ttm": ebitda,
            "eps_ttm": eps,
            "period": period_str,
            "statement_basis": statement_basis,
            "annual_fallback": annual_fallback,
            "as_of": inc_as_of,
            "source": f"Yahoo Finance income statement ({bundle.query_symbol})",
        }

    # ------------------------------------------------------------------
    # 6. get_forward_estimates
    # ------------------------------------------------------------------
    def get_forward_estimates(self, ticker: str, budget: Optional[_RequestBudget] = None) -> ForwardEstimatesData:
        req_budget = self._get_active_budget(budget)
        req_budget.check(ticker, "get_forward_estimates")
        bundle = self._get_bundle(ticker)
        info = bundle.get_info(req_budget)
        ee = bundle.get_earnings_estimate(req_budget)
        re_est = bundle.get_revenue_estimate(req_budget)

        as_of_date = date.today()
        reg_time = info.get("regularMarketTime")
        if isinstance(reg_time, (int, float)) and reg_time > 0:
            as_of_date = datetime.fromtimestamp(reg_time, tz=timezone.utc).date()

        quote_curr = str(info.get("currency") or "USD").upper()
        fin_curr = str(info.get("financialCurrency") or quote_curr).upper()
        sec_type = str(info.get("quoteType") or "").upper()
        name_str = f"{info.get('shortName', '')} {info.get('longName', '')}".upper()
        is_adr = (
            sec_type == "ADR"
            or "ADR" in name_str
            or "ADS" in name_str
            or fin_curr != quote_curr
        )
        eps_basis = "ADS" if is_adr else "share"

        f_eps1: Optional[Decimal] = None
        f_eps2: Optional[Decimal] = None
        eps_period_1y = "0y"
        eps_period_2y = "+1y"
        eps1_source = f"Yahoo Finance earnings_estimate (0y) for {bundle.query_symbol}"
        eps1_notes = f"Analyst consensus mean EPS for current fiscal year (0y); basis: {eps_basis}"
        est_1y_currency: Optional[str] = None
        est_2y_currency: Optional[str] = None

        if ee is not None and hasattr(ee, "index") and not ee.empty:
            if "0y" in ee.index and "avg" in ee.columns:
                raw_curr_0y = str(ee.loc["0y", "currency"]).strip().upper() if "currency" in ee.columns and ee.loc["0y", "currency"] is not None and str(ee.loc["0y", "currency"]).strip() != "" and str(ee.loc["0y", "currency"]).lower() != "nan" else None
                val = _to_decimal(ee.loc["0y", "avg"])
                if is_adr:
                    if raw_curr_0y is None:
                        f_eps1 = None
                        eps1_notes = f"Forward EPS disabled for ADR {bundle.query_symbol}: earnings_estimate currency is missing/unknown; cannot verify USD/ADS basis"
                    elif raw_curr_0y != quote_curr:
                        f_eps1 = None
                        eps1_notes = f"Forward EPS disabled for ADR {bundle.query_symbol}: earnings_estimate currency ({raw_curr_0y}) does not match quote currency ({quote_curr})"
                    else:
                        if val is not None:
                            f_eps1 = val.quantize(Decimal("0.01"), ROUND_HALF_UP)
                            est_1y_currency = raw_curr_0y
                            eps1_notes = f"Analyst consensus mean EPS for current fiscal year (0y); verified {raw_curr_0y}/{eps_basis} basis matching quote currency"
                else:
                    if raw_curr_0y is not None and raw_curr_0y != quote_curr:
                        f_eps1 = None
                        eps1_notes = f"Forward EPS disabled for {bundle.query_symbol}: estimate currency ({raw_curr_0y}) does not match quote currency ({quote_curr})"
                    else:
                        if val is not None:
                            f_eps1 = val.quantize(Decimal("0.01"), ROUND_HALF_UP)
                            est_1y_currency = raw_curr_0y or quote_curr

            if "+1y" in ee.index and "avg" in ee.columns:
                raw_curr_1y = str(ee.loc["+1y", "currency"]).strip().upper() if "currency" in ee.columns and ee.loc["+1y", "currency"] is not None and str(ee.loc["+1y", "currency"]).strip() != "" and str(ee.loc["+1y", "currency"]).lower() != "nan" else None
                val = _to_decimal(ee.loc["+1y", "avg"])
                if is_adr:
                    if raw_curr_1y == quote_curr and val is not None:
                        f_eps2 = val.quantize(Decimal("0.01"), ROUND_HALF_UP)
                        est_2y_currency = raw_curr_1y
                else:
                    if (raw_curr_1y is None or raw_curr_1y == quote_curr) and val is not None:
                        f_eps2 = val.quantize(Decimal("0.01"), ROUND_HALF_UP)
                        est_2y_currency = raw_curr_1y or quote_curr

        if f_eps1 is None and not is_adr:
            raw_f_eps = info.get("forwardEps")
            if raw_f_eps is not None:
                d = _to_decimal(raw_f_eps)
                if d is not None:
                    f_eps1 = d.quantize(Decimal("0.01"), ROUND_HALF_UP)
                    eps_period_1y = "forward_1y"
                    est_1y_currency = quote_curr
                    eps1_source = f"Yahoo Finance info.forwardEps for {bundle.query_symbol}"
                    eps1_notes = "Yahoo Finance forward EPS from quote summary (source field: info.forwardEps)"

        # Forward EBITDA from revenue growth projection if base statement is an annual statement
        inc_data = self.get_income_statement(ticker, budget=req_budget)
        ebitda_val = inc_data.get("ebitda_ttm")
        inc_period = str(inc_data.get("period") or "")
        inc_as_of = inc_data.get("as_of") or as_of_date
        f_ebitda1: Optional[Decimal] = None
        f_ebitda2: Optional[Decimal] = None
        ebitda1_notes: Optional[str] = None
        ebitda2_notes: Optional[str] = None
        ebitda_period_1y = "0y"
        ebitda_period_2y = "+1y"

        g_rev1: Optional[Decimal] = None
        g_rev2: Optional[Decimal] = None
        f_rev1: Optional[Decimal] = None
        f_rev2: Optional[Decimal] = None
        if re_est is not None and hasattr(re_est, "index") and not re_est.empty:
            if "0y" in re_est.index and "avg" in re_est.columns:
                f_rev1 = _to_decimal(re_est.loc["0y", "avg"])
            if "+1y" in re_est.index and "avg" in re_est.columns:
                f_rev2 = _to_decimal(re_est.loc["+1y", "avg"])
            if "0y" in re_est.index and "growth" in re_est.columns:
                g_rev1 = _to_decimal(re_est.loc["0y", "growth"])
            if "+1y" in re_est.index and "growth" in re_est.columns:
                g_rev2 = _to_decimal(re_est.loc["+1y", "growth"])

        g_rev1_clamped = min(max(g_rev1, Decimal("-0.20")), Decimal("0.40")) if g_rev1 is not None else None
        g_rev2_clamped = min(max(g_rev2, Decimal("-0.20")), Decimal("0.40")) if g_rev2 is not None else None

        aligned_inc, target_inc_date, target_inc_label, align_inc_fail = _verify_forecast_alignment(
            inc_as_of if inc_period.startswith("FY") else None,
            inc_period,
            info,
        )

        # Only apply 0y growth if base EBITDA is from a verified, non-lagging annual statement column (not arbitrary TTM or stale base)
        if aligned_inc and ebitda_val is not None and ebitda_val > 0 and g_rev1_clamped is not None:
            ebitda_period_1y = "0y"
            f_ebitda1 = (ebitda_val * (Decimal("1") + g_rev1_clamped)).quantize(Decimal("0.01"), ROUND_HALF_UP)
            ebitda1_notes = f"Derived forward EBITDA for {target_inc_label} (0y) from base {inc_period} annual EBITDA ({ebitda_val}) as of {inc_as_of}; raw_growth={g_rev1}, capped_growth={g_rev1_clamped}, formula={inc_period}_EBITDA × (1 + g)"
            if g_rev2_clamped is not None:
                f_ebitda2 = (f_ebitda1 * (Decimal("1") + g_rev2_clamped)).quantize(Decimal("0.01"), ROUND_HALF_UP)
                ebitda2_notes = f"Derived forward EBITDA for (+1y) from forward {target_inc_label} EBITDA ({f_ebitda1}); raw_growth={g_rev2}, capped_growth={g_rev2_clamped}, formula=EBITDA_1y × (1 + g)"
        elif not aligned_inc:
            ebitda1_notes = f"Forward EBITDA unavailable: {align_inc_fail}"
            ebitda2_notes = f"Forward EBITDA unavailable: {align_inc_fail}"

        # Forward cash flows from cash flow category
        cf_data = self.get_cash_flow(ticker, budget=req_budget)
        f_fcfe1 = cf_data.get("forward_fcfe_1y")
        f_fcfe2 = cf_data.get("forward_fcfe_2y")
        f_fcff1 = cf_data.get("forward_fcff_1y")
        f_fcff2 = cf_data.get("forward_fcff_2y")

        next_fy_ts = info.get("nextFiscalYearEnd")
        forecast_fy_end = None
        ntm_weights = None
        if isinstance(next_fy_ts, (int, float)) and next_fy_ts > 0:
            try:
                forecast_fy_end = datetime.fromtimestamp(next_fy_ts, tz=timezone.utc).date()
                days_to_fy = (forecast_fy_end - as_of_date).days
                if 0 < days_to_fy <= 366:
                    w1 = Decimal(str(round(days_to_fy / 365.0, 4)))
                    w2 = (Decimal("1.0000") - w1).quantize(Decimal("0.0001"), ROUND_HALF_UP)
                    ntm_weights = {"current_fy": w1, "next_fy": w2}
            except Exception:
                pass

        return {
            "forward_revenue_1y": f_rev1,
            "forward_revenue_1y_source_type": "analyst_estimate" if f_rev1 is not None else None,
            "forward_revenue_1y_period": eps_period_1y,
            "forward_revenue_1y_notes": "Analyst consensus mean revenue for period 0y" if f_rev1 else None,
            "forward_revenue_2y": f_rev2,
            "forward_revenue_2y_source_type": "analyst_estimate" if f_rev2 is not None else None,
            "forward_revenue_2y_period": eps_period_2y,
            "forward_revenue_2y_notes": "Analyst consensus mean revenue for period +1y" if f_rev2 else None,

            "forward_eps_1y": f_eps1,
            "forward_eps_1y_source_type": "analyst_estimate" if f_eps1 is not None else None,
            "forward_eps_1y_period": eps_period_1y,
            "forward_eps_1y_notes": eps1_notes,
            "forward_eps_1y_source": eps1_source,
            "forward_eps_1y_currency": est_1y_currency,
            "forward_eps_2y": f_eps2,
            "forward_eps_2y_source_type": "analyst_estimate" if f_eps2 is not None else None,
            "forward_eps_2y_period": eps_period_2y,
            "forward_eps_2y_notes": "Analyst consensus mean EPS for period +1y",
            "forward_eps_2y_currency": est_2y_currency,
            "forward_eps_basis": eps_basis,
            "forecast_fiscal_year_end": forecast_fy_end,
            "ntm_weights": ntm_weights,


            "forward_ebitda_1y": f_ebitda1,
            "forward_ebitda_1y_source_type": "derived" if f_ebitda1 is not None else None,
            "forward_ebitda_1y_period": ebitda_period_1y,
            "forward_ebitda_1y_notes": ebitda1_notes,
            "forward_ebitda_2y": f_ebitda2,
            "forward_ebitda_2y_source_type": "derived" if f_ebitda2 is not None else None,
            "forward_ebitda_2y_period": ebitda_period_2y,
            "forward_ebitda_2y_notes": ebitda2_notes,

            "forward_fcfe_1y": f_fcfe1,
            "forward_fcfe_1y_source_type": "derived" if f_fcfe1 is not None else None,
            "forward_fcfe_1y_period": cf_data.get("forward_fcfe_1y_period") or "0y",
            "forward_fcfe_1y_notes": cf_data.get("forward_fcfe_1y_notes"),
            "forward_fcfe_2y": f_fcfe2,
            "forward_fcfe_2y_source_type": "derived" if f_fcfe2 is not None else None,
            "forward_fcfe_2y_period": cf_data.get("forward_fcfe_2y_period") or "+1y",
            "forward_fcfe_2y_notes": cf_data.get("forward_fcfe_2y_notes"),

            "forward_fcff_1y": f_fcff1,
            "forward_fcff_1y_source_type": "derived" if f_fcff1 is not None else None,
            "forward_fcff_1y_period": cf_data.get("forward_fcff_1y_period") or "0y",
            "forward_fcff_1y_notes": cf_data.get("forward_fcff_1y_notes"),
            "forward_fcff_2y": f_fcff2,
            "forward_fcff_2y_source_type": "derived" if f_fcff2 is not None else None,
            "forward_fcff_2y_period": cf_data.get("forward_fcff_2y_period") or "+1y",
            "forward_fcff_2y_notes": cf_data.get("forward_fcff_2y_notes"),

            "period_1y": eps_period_1y,
            "period_2y": eps_period_2y,
            "revenue_growth": g_rev1,
            "as_of": as_of_date,
            "source": f"Yahoo Finance forward estimates ({bundle.query_symbol})",
        }

    # ------------------------------------------------------------------
    # 7. get_historical_multiples
    # ------------------------------------------------------------------
    def get_historical_multiples(self, ticker: str, budget: Optional[_RequestBudget] = None) -> HistoricalMultiplesData:
        req_budget = self._get_active_budget(budget)
        req_budget.check(ticker, "get_historical_multiples")
        bundle = self._get_bundle(ticker)
        info = bundle.get_info(req_budget)

        as_of_date = date.today()
        reg_time = info.get("regularMarketTime")
        if isinstance(reg_time, (int, float)) and reg_time > 0:
            as_of_date = datetime.fromtimestamp(reg_time, tz=timezone.utc).date()

        # Current trailingPE and enterpriseToEbitda are NOT historical forward or historical averages:
        # Leave historical multiples unavailable unless actual historical timeseries data exists;
        # valuation models use explicit configured assumption defaults instead.
        return {
            "historical_forward_pe": None,
            "historical_ev_ebitda": None,
            "period": "historical",
            "as_of": as_of_date,
            "source": f"Yahoo Finance multiples ({bundle.query_symbol})",
        }

    def supports_ticker(self, ticker: str) -> bool:
        try:
            self.get_quote(ticker)
            return True
        except (TickerNotFoundError, UnsupportedCompanyError, InvalidTickerError):
            return False
        except ProviderError:
            return False
