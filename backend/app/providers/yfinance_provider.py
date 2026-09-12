"""
Live Yahoo Finance data provider implementing the seven FinancialDataProvider methods.
Fetches real market quotes, company profiles, financial statements, analyst estimates,
and historical valuation multiples via yfinance.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from contextvars import ContextVar
from datetime import date, datetime, timedelta, timezone
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
from app.services.multiples import industry_multiple_payload

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")

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


def _extract_forward_net_borrowing(info: dict[str, Any], slot: int) -> tuple[Optional[Decimal], Optional[str]]:
    """Read only explicitly named vendor forward-borrowing fields.

    Yahoo's standard ``info`` payload does not currently publish a forward
    debt-flow estimate.  This helper deliberately does not derive one from
    the TTM cash-flow statement; it merely preserves a value if an upstream
    adapter supplies an explicit, forecast-labelled field.
    """

    if slot not in (1, 2):
        return None, None
    suffix = f"{slot}Y"
    ntm_keys = (
        "forwardNetBorrowingNTM",
        "forward_net_borrowing_ntm",
        "forwardBorrowingNTM",
        "forward_borrowing_ntm",
        "netBorrowingForecastNTM",
    )
    annual_keys = (
        f"forwardNetBorrowing{suffix}",
        f"forward_net_borrowing_{slot}y",
        f"forwardBorrowing{suffix}",
        f"forward_borrowing_{slot}y",
        f"netBorrowingForecast{suffix}",
    )
    # The canonical snapshot has one 1Y slot for a direct NTM value.  NTM
    # aliases are therefore accepted only in that slot and retain their
    # explicit rolling-period identity below.
    keys = ntm_keys + annual_keys if slot == 1 else annual_keys
    for key in keys:
        if key in info:
            value = _to_decimal(info.get(key))
            if value is not None:
                return value, key
    return None, None


def _forward_borrowing_period(info: dict[str, Any], slot: int, field_key: Optional[str]) -> Optional[str]:
    """Attach an explicit rolling or fiscal period to a borrowing estimate.

    A slot name such as ``forwardNetBorrowing1Y`` is not evidence that the
    amount covers the rolling NTM window.  Prefer upstream period metadata;
    when it is absent, derive a calendar fiscal label from the verified
    ``nextFiscalYearEnd``.  If neither is available, retain an explicit
    unverified label so the projection layer fails closed instead of inventing
    ``FY1E``/``FY2E`` semantics.
    """

    if field_key is None:
        return None
    key_upper = field_key.upper()
    if "NTM" in key_upper:
        period_keys = (
            "forwardNetBorrowingNTMPeriod",
            "forward_net_borrowing_ntm_period",
            "forwardBorrowingNTMPeriod",
            "forward_borrowing_ntm_period",
            # Some adapters key the amount as NTM but reuse the canonical
            # 1Y metadata field.  Honor that explicit metadata before the
            # field-name fallback below.
            "forwardNetBorrowing1YPeriod",
            "forward_net_borrowing_1y_period",
            "forwardBorrowing1YPeriod",
            "forward_borrowing_1y_period",
        )
    else:
        suffix = f"{slot}Y"
        period_keys = (
            f"forwardNetBorrowing{suffix}Period",
            f"forward_net_borrowing_{slot}y_period",
            f"forwardBorrowing{suffix}Period",
            f"forward_borrowing_{slot}y_period",
        )
    for key in period_keys:
        raw_period = info.get(key)
        if raw_period is not None and str(raw_period).strip():
            return str(raw_period).strip()
    if "NTM" in key_upper:
        return "NTM"

    next_fy_ts = info.get("nextFiscalYearEnd")
    if isinstance(next_fy_ts, (int, float)) and next_fy_ts > 0:
        try:
            next_fy_date = datetime.fromtimestamp(next_fy_ts, tz=timezone.utc).date()
            return f"FY{next_fy_date.year + slot - 1}E"
        except (OverflowError, OSError, ValueError):
            pass
    return f"forward_{slot}y_unverified"


def _provider_date(value: Any) -> Optional[date]:
    """Coerce a Yahoo date/epoch value without inventing a calendar date."""

    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and value > 0:
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _provider_column_date(column: Any) -> Optional[date]:
    """Return a statement column's date while retaining non-date labels."""

    if hasattr(column, "date"):
        try:
            return column.date()
        except Exception:
            pass
    return _provider_date(column)


def _provider_columns(frame: Any) -> list[Any]:
    if frame is None or not hasattr(frame, "columns"):
        return []
    columns = [column for column in list(frame.columns) if _provider_column_date(column) is not None]
    return sorted(columns, key=lambda column: _provider_column_date(column) or date.min)


def _provider_column_label(column: Any) -> str:
    return str(getattr(column, "name", None) or column)


def _provider_period_basis(columns: list[Any]) -> Optional[str]:
    """Classify statement columns without treating ambiguous short periods as quarters."""

    if columns is None or len(columns) == 0:
        return None
    has_cumulative = False
    has_short_ambiguous = False
    has_discrete = False
    for column in columns:
        label = _provider_column_label(column).upper()
        if any(token in label for token in ("YTD", "6M", "9M", "12M")):
            has_cumulative = True
        elif "3M" in label:
            has_short_ambiguous = True
        elif re.search(r"\bQ[1-4]\b", label) or _provider_column_date(column) is not None:
            has_discrete = True
        else:
            return None
    if has_cumulative:
        return "mixed" if has_discrete else "cumulative"
    if has_short_ambiguous:
        return "mixed" if has_discrete else None
    return "discrete" if has_discrete else None


def _provider_series_value(series: Any, labels: tuple[str, ...], *, absolute: bool = False) -> Optional[Decimal]:
    if series is None or not hasattr(series, "index"):
        return None
    for label in labels:
        if label not in series.index:
            continue
        value = _to_decimal(series.loc[label])
        if value is not None:
            return abs(value) if absolute else value
    return None


def _provider_tax_rate(series: Any) -> Optional[Decimal]:
    if series is None or not hasattr(series, "index"):
        return None
    direct = _provider_series_value(series, ("Tax Rate For Calcs", "Effective Tax Rate"))
    if direct is not None and Decimal("0") <= direct <= Decimal("1"):
        return direct
    tax = _provider_series_value(series, ("Tax Provision",))
    pretax = _provider_series_value(series, ("Pretax Income",))
    if tax is not None and pretax is not None and pretax > _ZERO:
        rate = tax / pretax
        if Decimal("0") <= rate <= Decimal("1"):
            return rate
    return None


def _fiscal_ytd_unavailable(
    reason: str,
    *,
    valuation_date: Optional[date] = None,
    fiscal_year_end: Optional[date] = None,
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "reason": reason,
        "as_of": valuation_date,
        "fiscal_year_end": fiscal_year_end,
        "start": start,
        "end": end,
    }


def _extract_fiscal_ytd_fcff(
    info: dict[str, Any],
    quarterly_cf: Any,
    quarterly_fin: Any,
) -> dict[str, Any]:
    """Extract aligned actual FCFF through the valuation date.

    This intentionally fails closed.  A latest quarter ending before the
    valuation date leaves an uncovered interval, so it is not treated as YTD
    actual and cannot be used to justify a day-ratio stub.
    """

    valuation_date = _provider_date(info.get("regularMarketTime"))
    if valuation_date is None:
        return _fiscal_ytd_unavailable(
            "Missing upstream regularMarketTime; valuation-date YTD alignment is unproven"
        )
    raw_financial_currency = info.get("financialCurrency")
    if not isinstance(raw_financial_currency, str) or not raw_financial_currency.strip():
        return _fiscal_ytd_unavailable(
            "Missing explicit financialCurrency; quote currency cannot establish statement currency",
            valuation_date=valuation_date,
        )
    financial_currency = raw_financial_currency.strip().upper()
    if re.fullmatch(r"[A-Z]{3}", financial_currency) is None:
        return _fiscal_ytd_unavailable(
            f"Invalid explicit financialCurrency {raw_financial_currency!r}; statement currency is untrusted",
            valuation_date=valuation_date,
        )
    fiscal_year_end = _provider_date(info.get("nextFiscalYearEnd"))
    last_fiscal_end = _provider_date(info.get("lastFiscalYearEnd"))
    if fiscal_year_end is None:
        return _fiscal_ytd_unavailable(
            "Missing upstream nextFiscalYearEnd; fiscal-year YTD alignment is unproven",
            valuation_date=valuation_date,
        )
    if last_fiscal_end is None:
        return _fiscal_ytd_unavailable(
            "Missing upstream lastFiscalYearEnd; fiscal-year YTD start is unproven",
            valuation_date=valuation_date,
            fiscal_year_end=fiscal_year_end,
        )
    if last_fiscal_end >= fiscal_year_end:
        return _fiscal_ytd_unavailable(
            f"Cannot derive a valid fiscal-year start before {fiscal_year_end}",
            valuation_date=valuation_date,
            fiscal_year_end=fiscal_year_end,
        )
    previous_fiscal_end = last_fiscal_end
    fiscal_start = previous_fiscal_end + timedelta(days=1)
    if valuation_date < fiscal_start or valuation_date > fiscal_year_end:
        return _fiscal_ytd_unavailable(
            f"Valuation date {valuation_date} is outside forecast fiscal year "
            f"{fiscal_start}..{fiscal_year_end}",
            valuation_date=valuation_date,
            fiscal_year_end=fiscal_year_end,
            start=fiscal_start,
            end=valuation_date,
        )

    columns = _provider_columns(quarterly_cf)
    selected = [
        column
        for column in columns
        if fiscal_start <= (_provider_column_date(column) or date.min) <= valuation_date
    ]
    if not selected:
        return _fiscal_ytd_unavailable(
            "No quarterly cash-flow actual covers the current fiscal-year interval",
            valuation_date=valuation_date,
            fiscal_year_end=fiscal_year_end,
            start=fiscal_start,
            end=valuation_date,
        )
    latest_date = _provider_column_date(selected[-1])
    if latest_date != valuation_date:
        relation = "before" if latest_date is not None and latest_date < valuation_date else "after"
        return _fiscal_ytd_unavailable(
            f"Latest quarterly actual ends {latest_date}, {relation} valuation date {valuation_date}; "
            "missing fiscal interval cannot be treated as actual YTD",
            valuation_date=valuation_date,
            fiscal_year_end=fiscal_year_end,
            start=fiscal_start,
            end=latest_date or valuation_date,
        )
    first_date = _provider_column_date(selected[0])
    first_period_days = (first_date - fiscal_start).days + 1 if first_date is not None else 0
    if first_date is None or not 60 <= first_period_days <= 125:
        return _fiscal_ytd_unavailable(
            f"Incomplete YTD coverage: first quarterly actual {first_date} has {first_period_days} days "
            f"from fiscal start {fiscal_start}; defensible quarterly coverage requires 60..125 days",
            valuation_date=valuation_date,
            fiscal_year_end=fiscal_year_end,
            start=fiscal_start,
            end=valuation_date,
        )
    for previous_column, current_column in zip(selected, selected[1:]):
        previous_date = _provider_column_date(previous_column)
        current_date = _provider_column_date(current_column)
        if previous_date is None or current_date is None or not 60 <= (current_date - previous_date).days <= 125:
            return _fiscal_ytd_unavailable(
                f"Incomplete or mismatched quarterly YTD sequence ending {valuation_date}",
                valuation_date=valuation_date,
                fiscal_year_end=fiscal_year_end,
                start=fiscal_start,
                end=valuation_date,
            )

    cashflow_basis = _provider_period_basis(selected)
    if cashflow_basis in (None, "mixed"):
        return _fiscal_ytd_unavailable(
            "Cash-flow quarterly period basis is unknown or mixed; YTD basis is ambiguous",
            valuation_date=valuation_date,
            fiscal_year_end=fiscal_year_end,
            start=fiscal_start,
            end=valuation_date,
        )

    financial_columns = _provider_columns(quarterly_fin)
    aligned_financial_columns: list[Any] = []
    for column in selected:
        column_date = _provider_column_date(column)
        matches = [
            financial_column
            for financial_column in financial_columns
            if _provider_column_date(financial_column) == column_date
        ]
        if len(matches) != 1:
            return _fiscal_ytd_unavailable(
                f"Missing or ambiguous same-period financial statement at {column}; "
                "interest and tax basis cannot be aligned",
                valuation_date=valuation_date,
                fiscal_year_end=fiscal_year_end,
                start=fiscal_start,
                end=valuation_date,
            )
        aligned_financial_columns.append(matches[0])
    financial_basis = _provider_period_basis(aligned_financial_columns)
    if financial_basis != cashflow_basis:
        return _fiscal_ytd_unavailable(
            f"Cash-flow and financial-statement period basis does not match "
            f"({cashflow_basis} vs {financial_basis or 'unknown'}); actual FCFF is unavailable",
            valuation_date=valuation_date,
            fiscal_year_end=fiscal_year_end,
            start=fiscal_start,
            end=valuation_date,
        )

    cfo_values: list[Decimal] = []
    capex_values: list[Decimal] = []
    interest_values: list[Decimal] = []
    tax_rates: list[Optional[Decimal]] = []
    tax_provision_values: list[Optional[Decimal]] = []
    pretax_values: list[Optional[Decimal]] = []
    for column, financial_column in zip(selected, aligned_financial_columns):
        series = quarterly_cf[column]
        cfo = _provider_series_value(series, ("Operating Cash Flow", "Cash Flow From Continuing Operating Activities"))
        capex = _provider_series_value(series, ("Capital Expenditure", "Purchase Of PPE"))
        if cfo is None or capex is None:
            return _fiscal_ytd_unavailable(
                f"Incomplete YTD cash-flow inputs at {column}: CFO and CapEx are both required",
                valuation_date=valuation_date,
                fiscal_year_end=fiscal_year_end,
                start=fiscal_start,
                end=valuation_date,
            )
        cfo_values.append(cfo)
        capex_values.append(capex)

        fin_series = quarterly_fin[financial_column]
        interest = _provider_series_value(
            fin_series,
            ("Interest Expense", "Interest Expense Non Operating"),
            absolute=True,
        )
        if cashflow_basis == "cumulative":
            tax_rates.append(None)
            tax_provision_values.append(_provider_series_value(fin_series, ("Tax Provision",)))
            pretax_values.append(_provider_series_value(fin_series, ("Pretax Income",)))
        else:
            tax_rates.append(_provider_tax_rate(fin_series))
        if interest is None:
            return _fiscal_ytd_unavailable(
                f"Missing same-period interest expense for actual FCFF at {column}",
                valuation_date=valuation_date,
                fiscal_year_end=fiscal_year_end,
                start=fiscal_start,
                end=valuation_date,
            )
        interest_values.append(interest)

    def _deaccumulate(values: list[Decimal]) -> list[Decimal]:
        return [values[0], *[current - previous for previous, current in zip(values, values[1:])]]

    if cashflow_basis == "cumulative":
        cfo_values = _deaccumulate(cfo_values)
        capex_values = _deaccumulate(capex_values)
        interest_values = _deaccumulate(interest_values)

        if any(value != _ZERO for value in interest_values):
            if any(value is None for value in tax_provision_values + pretax_values):
                return _fiscal_ytd_unavailable(
                    "Cumulative financial statements require Tax Provision and Pretax Income "
                    "to de-accumulate same-period tax rates",
                    valuation_date=valuation_date,
                    fiscal_year_end=fiscal_year_end,
                    start=fiscal_start,
                    end=valuation_date,
                )
            tax_period_values = _deaccumulate([value for value in tax_provision_values if value is not None])
            pretax_period_values = _deaccumulate([value for value in pretax_values if value is not None])
            for index, (tax, pretax) in enumerate(zip(tax_period_values, pretax_period_values)):
                if pretax <= _ZERO:
                    return _fiscal_ytd_unavailable(
                        "Cumulative financial statements have non-positive same-period Pretax Income; "
                        "tax rate basis is unavailable",
                        valuation_date=valuation_date,
                        fiscal_year_end=fiscal_year_end,
                        start=fiscal_start,
                        end=valuation_date,
                    )
                rate = tax / pretax
                if not rate.is_finite() or not _ZERO <= rate <= Decimal("1"):
                    return _fiscal_ytd_unavailable(
                        "De-accumulated same-period tax rate is outside 0..1; "
                        "actual FCFF is unavailable",
                        valuation_date=valuation_date,
                        fiscal_year_end=fiscal_year_end,
                        start=fiscal_start,
                        end=valuation_date,
                    )
                tax_rates[index] = rate

    if any(not value.is_finite() for value in cfo_values + capex_values + interest_values):
        return _fiscal_ytd_unavailable(
            "Non-finite quarterly input prevents actual FCFF construction",
            valuation_date=valuation_date,
            fiscal_year_end=fiscal_year_end,
            start=fiscal_start,
            end=valuation_date,
        )
    if any(value != _ZERO for value in interest_values) and any(rate is None for rate in tax_rates):
        return _fiscal_ytd_unavailable(
            "Missing same-period tax rate prevents after-tax interest calculation for actual FCFF",
            valuation_date=valuation_date,
            fiscal_year_end=fiscal_year_end,
            start=fiscal_start,
            end=valuation_date,
        )

    after_tax_interest = sum(
        interest * (Decimal("1") - (rate if rate is not None else _ZERO))
        for interest, rate in zip(interest_values, tax_rates)
    )
    cfo_total = sum(cfo_values)
    capex_total = sum(abs(value) for value in capex_values)
    fcff = cfo_total + after_tax_interest - capex_total
    if not fcff.is_finite():
        return _fiscal_ytd_unavailable(
            "Non-finite actual FCFF result",
            valuation_date=valuation_date,
            fiscal_year_end=fiscal_year_end,
            start=fiscal_start,
            end=valuation_date,
        )
    mode = "cumulative-YTD de-accumulated" if cashflow_basis == "cumulative" else "discrete-quarter summed"
    return {
        "status": "available",
        "value": fcff,
        "unit": financial_currency,
        "period": f"FY{fiscal_year_end.year} YTD",
        "source": "Yahoo Finance quarterly cash-flow statements",
        "source_type": "actual",
        "as_of": valuation_date,
        "confidence": 1.0,
        "is_estimated": False,
        "notes": (
            f"Actual FCFF = CFO ({cfo_total}) + after-tax interest ({after_tax_interest}) "
            f"- CapEx ({capex_total}); {mode}; coverage={fiscal_start}..{valuation_date}."
        ),
        "fiscal_year_end": fiscal_year_end,
        "prior_fiscal_year_end": previous_fiscal_end,
        "start": fiscal_start,
        "end": valuation_date,
    }


def _fiscal_ytd_marker(payload: dict[str, Any]) -> str:
    serializable = {
        key: (value.isoformat() if isinstance(value, date) else str(value) if isinstance(value, Decimal) else value)
        for key, value in payload.items()
    }
    return "S5_FISCAL_YTD_V1:" + json.dumps(serializable, sort_keys=True, separators=(",", ":"))


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
        self._qbs: Any = None
        self._qcf: Any = None
        self._qfin: Any = None
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
        except (ProviderError, AttributeError, TypeError, NameError):
            raise
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
        except (ProviderRateLimitError, ProviderUnavailableError):
            raise
        except (AttributeError, TypeError, NameError):
            raise
        except Exception as exc:
            logger.debug(f"Quarterly balance sheet unavailable for {self.raw_ticker}: {exc}")
            return None

    def get_cashflow(self, budget: Optional[_RequestBudget] = None) -> Any:
        return self._fetch_property("_cf", lambda: self.ticker.cashflow, budget, "cashflow")

    def get_quarterly_cashflow(self, budget: Optional[_RequestBudget] = None) -> Any:
        try:
            return self._fetch_property("_qcf", lambda: self.ticker.quarterly_cashflow, budget, "quarterly cashflow")
        except (ProviderRateLimitError, ProviderUnavailableError):
            raise
        except (AttributeError, TypeError, NameError):
            raise
        except Exception as exc:
            logger.debug(f"Quarterly cashflow unavailable for {self.raw_ticker}: {exc}")
            return None

    def get_financials(self, budget: Optional[_RequestBudget] = None) -> Any:
        return self._fetch_property("_fin", lambda: self.ticker.financials, budget, "financials")

    def get_quarterly_financials(self, budget: Optional[_RequestBudget] = None) -> Any:
        try:
            return self._fetch_property("_qfin", lambda: self.ticker.quarterly_financials, budget, "quarterly financials")
        except (ProviderRateLimitError, ProviderUnavailableError):
            raise
        except (AttributeError, TypeError, NameError):
            raise
        except Exception as exc:
            logger.debug(f"Quarterly financials unavailable for {self.raw_ticker}: {exc}")
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

        quarterly_cf = bundle.get_quarterly_cashflow(req_budget)
        annual_cf = bundle.get_cashflow(req_budget)
        quarterly_fin = bundle.get_quarterly_financials(req_budget)
        annual_fin = bundle.get_financials(req_budget)
        agg = aggregate_ttm_cashflow(
            quarterly_cf=quarterly_cf,
            annual_cf=annual_cf,
            quarterly_fin=quarterly_fin,
            annual_fin=annual_fin,
            default_as_of=date.today(),
        )
        cfo = agg["cfo"]
        capex = agg["capex"]
        net_borrowing = agg["net_borrowing"]
        has_net_borrowing = agg["has_net_borrowing"]
        interest = agg["interest"]
        tax_rate = agg["tax_rate"]
        nwc_change = agg.get("nwc_change")
        da = agg.get("da")
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

        # Upstream provider does not invent forward FCFF or FCFE from single growth rates.
        # Forward projections belong to the service layer (projections.py) driven by independent financial drivers.
        forward_fcfe_1y: Optional[Decimal] = None
        forward_fcfe_2y: Optional[Decimal] = None
        forward_fcff_1y: Optional[Decimal] = None
        forward_fcff_2y: Optional[Decimal] = None
        # Forward borrowing is a separate input.  Standard Yahoo payloads do
        # not expose it; only an explicitly named vendor field is accepted.
        forward_net_borrowing_1y, forward_net_borrowing_1y_key = _extract_forward_net_borrowing(info, 1)
        forward_net_borrowing_2y, forward_net_borrowing_2y_key = _extract_forward_net_borrowing(info, 2)
        forward_fcfe_1y_notes: Optional[str] = None
        forward_fcfe_2y_notes: Optional[str] = None
        forward_fcff_1y_notes: Optional[str] = None
        forward_fcff_2y_notes: Optional[str] = None
        forward_net_borrowing_1y_period = _forward_borrowing_period(
            info, 1, forward_net_borrowing_1y_key
        )
        forward_net_borrowing_2y_period = _forward_borrowing_period(
            info, 2, forward_net_borrowing_2y_key
        )
        forward_borrowing_warnings: list[str] = []
        for slot, period in (
            (1, forward_net_borrowing_1y_period),
            (2, forward_net_borrowing_2y_period),
        ):
            if period is not None and period.endswith("_unverified"):
                forward_borrowing_warnings.append(
                    f"Explicit forward net borrowing {slot}Y has no verified fiscal/NTM period metadata; "
                    "projection layer will keep it unavailable for horizon alignment."
                )
        if forward_net_borrowing_1y is None and forward_net_borrowing_2y is None:
            forward_borrowing_warnings.append(
                "Yahoo Finance did not provide explicit forward net borrowing; "
                f"historical {period_str} net borrowing is retained for display only and is not used as a forward FCFE driver."
            )
        forward_net_borrowing_warning = " ".join(forward_borrowing_warnings) or None

        fiscal_ytd = _extract_fiscal_ytd_fcff(info, quarterly_cf, quarterly_fin)
        fiscal_ytd_marker = _fiscal_ytd_marker(fiscal_ytd)
        # Keep the marker in canonical metric notes so the existing normalizer
        # can carry it through without changing the service ownership boundary.
        fcfe_def = f"{fcfe_def}; {fiscal_ytd_marker}"
        fcff_def = f"{fcff_def}; {fiscal_ytd_marker}"
        fiscal_ytd_value = fiscal_ytd.get("value") if fiscal_ytd.get("status") == "available" else None
        fiscal_ytd_source_type = fiscal_ytd.get("source_type") if fiscal_ytd_value is not None else None
        fiscal_ytd_notes = fiscal_ytd.get("notes") if fiscal_ytd_value is not None else None
        fiscal_ytd_reason = fiscal_ytd.get("reason") if fiscal_ytd_value is None else None
        period_note = "Annual fiscal year statement" if is_annual_statement else "TTM quote summary"
        return {
            "cfo": cfo,
            "capex": capex,
            "net_borrowing": net_borrowing,
            "has_net_borrowing": has_net_borrowing,
            "historical_net_borrowing": net_borrowing,
            "historical_net_borrowing_period": period_str,
            "historical_net_borrowing_as_of": cf_as_of,
            "interest": interest,
            "tax_rate": tax_rate,
            "nwc_change": nwc_change,
            "da": da,
            "da_period": agg.get("da_period"),
            "da_as_of": agg.get("da_as_of"),
            "da_is_fallback": agg.get("da_is_fallback"),
            "fcfe_ttm": fcfe,
            "fcfe_ttm_source_type": "derived" if fcfe is not None else None,
            "fcfe_definition": fcfe_def,
            "forward_fcfe_1y": forward_fcfe_1y,
            "forward_fcfe_1y_source_type": None,
            "forward_fcfe_1y_period": "0y",
            "forward_fcfe_1y_notes": forward_fcfe_1y_notes,
            "forward_fcfe_2y": forward_fcfe_2y,
            "forward_fcfe_2y_source_type": None,
            "forward_fcfe_2y_period": "+1y",
            "forward_fcfe_2y_notes": forward_fcfe_2y_notes,
            "forward_net_borrowing_1y": forward_net_borrowing_1y,
            "forward_net_borrowing_1y_period": forward_net_borrowing_1y_period,
            "forward_net_borrowing_1y_source": (
                f"Yahoo Finance explicit field {forward_net_borrowing_1y_key}" if forward_net_borrowing_1y_key else None
            ),
            "forward_net_borrowing_1y_source_type": "provider_forward" if forward_net_borrowing_1y is not None else None,
            "forward_net_borrowing_1y_as_of": cf_as_of if forward_net_borrowing_1y is not None else None,
            "forward_net_borrowing_1y_unit": str(info.get("financialCurrency") or info.get("currency") or "USD").upper() if forward_net_borrowing_1y is not None else None,
            "forward_net_borrowing_1y_currency": str(info.get("financialCurrency") or info.get("currency") or "USD").upper() if forward_net_borrowing_1y is not None else None,
            "forward_net_borrowing_1y_confidence": 0.7 if forward_net_borrowing_1y is not None else None,
            "forward_net_borrowing_1y_is_estimated": True if forward_net_borrowing_1y is not None else None,
            "forward_net_borrowing_1y_notes": (
                (
                    "Explicit provider forward net-borrowing field; "
                    f"period={forward_net_borrowing_1y_period}; not derived from TTM."
                ) if forward_net_borrowing_1y is not None else None
            ),
            "forward_net_borrowing_2y": forward_net_borrowing_2y,
            "forward_net_borrowing_2y_period": forward_net_borrowing_2y_period,
            "forward_net_borrowing_2y_source": (
                f"Yahoo Finance explicit field {forward_net_borrowing_2y_key}" if forward_net_borrowing_2y_key else None
            ),
            "forward_net_borrowing_2y_source_type": "provider_forward" if forward_net_borrowing_2y is not None else None,
            "forward_net_borrowing_2y_as_of": cf_as_of if forward_net_borrowing_2y is not None else None,
            "forward_net_borrowing_2y_unit": str(info.get("financialCurrency") or info.get("currency") or "USD").upper() if forward_net_borrowing_2y is not None else None,
            "forward_net_borrowing_2y_currency": str(info.get("financialCurrency") or info.get("currency") or "USD").upper() if forward_net_borrowing_2y is not None else None,
            "forward_net_borrowing_2y_confidence": 0.7 if forward_net_borrowing_2y is not None else None,
            "forward_net_borrowing_2y_is_estimated": True if forward_net_borrowing_2y is not None else None,
            "forward_net_borrowing_2y_notes": (
                (
                    "Explicit provider forward net-borrowing field; "
                    f"period={forward_net_borrowing_2y_period}; not derived from TTM."
                ) if forward_net_borrowing_2y is not None else None
            ),
            "forward_net_borrowing_warning": forward_net_borrowing_warning,
            "fcff_ttm": fcff,
            "fcff_ttm_source_type": "derived" if fcff is not None else None,
            "fcff_definition": fcff_def,
            "fiscal_ytd_status": fiscal_ytd.get("status"),
            "fiscal_ytd_unavailable_reason": fiscal_ytd_reason,
            "fiscal_ytd_fcff": fiscal_ytd_value,
            "fiscal_ytd_fcff_source_type": fiscal_ytd_source_type,
            "fiscal_ytd_fcff_period": fiscal_ytd.get("period"),
            "fiscal_ytd_fcff_source": fiscal_ytd.get("source"),
            "fiscal_ytd_fcff_as_of": fiscal_ytd.get("as_of"),
            "fiscal_ytd_fcff_unit": fiscal_ytd.get("unit"),
            "fiscal_ytd_fcff_currency": fiscal_ytd.get("unit"),
            "fiscal_ytd_fcff_confidence": fiscal_ytd.get("confidence"),
            "fiscal_ytd_fcff_is_estimated": fiscal_ytd.get("is_estimated"),
            "fiscal_ytd_fcff_notes": fiscal_ytd_notes,
            "fiscal_ytd_start": fiscal_ytd.get("start"),
            "fiscal_ytd_end": fiscal_ytd.get("end"),
            "fiscal_ytd_prior_fiscal_year_end": fiscal_ytd.get("prior_fiscal_year_end"),
            "fiscal_ytd_fiscal_year_end": fiscal_ytd.get("fiscal_year_end"),
            "cfo_notes": fiscal_ytd_marker,
            "forward_fcff_1y": forward_fcff_1y,
            "forward_fcff_1y_source_type": None,
            "forward_fcff_1y_period": "0y",
            "forward_fcff_1y_notes": forward_fcff_1y_notes,
            "forward_fcff_2y": forward_fcff_2y,
            "forward_fcff_2y_source_type": None,
            "forward_fcff_2y_period": "+1y",
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
            "da": agg.get("da"),
            "da_period": agg.get("da_period"),
            "da_as_of": agg.get("da_as_of"),
            "da_is_fallback": agg.get("da_is_fallback"),
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

        inc_data = self.get_income_statement(ticker, budget=req_budget)
        ebitda_val = inc_data.get("ebitda_ttm")
        inc_period = str(inc_data.get("period") or "")
        inc_as_of = inc_data.get("as_of") or as_of_date

        aligned_inc, target_inc_date, target_inc_label, align_inc_fail = _verify_forecast_alignment(
            inc_as_of if inc_period.startswith("FY") else None,
            inc_period,
            info,
        )

        # Eliminate synthetic EBITDA growth formulas (Issue 01 remediation).
        # Provider must never synthesize forward EBITDA via base * (1 + g).
        # Genuine forward EBITDA comes from analyst consensus or service-layer financial bridge.
        f_ebitda1 = None
        f_ebitda2 = None
        ebitda_period_1y = None
        ebitda_period_2y = None
        if align_inc_fail:
            ebitda1_notes = f"Forward EBITDA unavailable: {align_inc_fail}; no synthetic growth extrapolation applied."
            ebitda2_notes = f"Forward EBITDA unavailable: {align_inc_fail}; no synthetic growth extrapolation applied."
        else:
            ebitda1_notes = (
                "Forward EBITDA unavailable: Yahoo Finance did not provide an independent analyst EBITDA consensus; "
                "service-layer driver bridge may derive EBITDA only from verified revenue and margin inputs."
            )
            ebitda2_notes = ebitda1_notes

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

            "forward_net_borrowing_1y": cf_data.get("forward_net_borrowing_1y"),
            "forward_net_borrowing_1y_period": cf_data.get("forward_net_borrowing_1y_period"),
            "forward_net_borrowing_1y_source": cf_data.get("forward_net_borrowing_1y_source"),
            "forward_net_borrowing_1y_source_type": cf_data.get("forward_net_borrowing_1y_source_type"),
            "forward_net_borrowing_1y_as_of": cf_data.get("forward_net_borrowing_1y_as_of"),
            "forward_net_borrowing_1y_unit": cf_data.get("forward_net_borrowing_1y_unit"),
            "forward_net_borrowing_1y_currency": cf_data.get("forward_net_borrowing_1y_currency"),
            "forward_net_borrowing_1y_confidence": cf_data.get("forward_net_borrowing_1y_confidence"),
            "forward_net_borrowing_1y_is_estimated": cf_data.get("forward_net_borrowing_1y_is_estimated"),
            "forward_net_borrowing_1y_notes": cf_data.get("forward_net_borrowing_1y_notes"),
            "forward_net_borrowing_2y": cf_data.get("forward_net_borrowing_2y"),
            "forward_net_borrowing_2y_period": cf_data.get("forward_net_borrowing_2y_period"),
            "forward_net_borrowing_2y_source": cf_data.get("forward_net_borrowing_2y_source"),
            "forward_net_borrowing_2y_source_type": cf_data.get("forward_net_borrowing_2y_source_type"),
            "forward_net_borrowing_2y_as_of": cf_data.get("forward_net_borrowing_2y_as_of"),
            "forward_net_borrowing_2y_unit": cf_data.get("forward_net_borrowing_2y_unit"),
            "forward_net_borrowing_2y_currency": cf_data.get("forward_net_borrowing_2y_currency"),
            "forward_net_borrowing_2y_confidence": cf_data.get("forward_net_borrowing_2y_confidence"),
            "forward_net_borrowing_2y_is_estimated": cf_data.get("forward_net_borrowing_2y_is_estimated"),
            "forward_net_borrowing_2y_notes": cf_data.get("forward_net_borrowing_2y_notes"),
            "forward_net_borrowing_warning": cf_data.get("forward_net_borrowing_warning"),

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

        # Current trailingPE and enterpriseToEbitda are NOT historical forward or historical averages.
        # Never relabel those current fields as historical.  Company history
        # remains unavailable from this API, while a bounded, versioned public
        # industry snapshot can be attached by the upstream sector/industry
        # labels and independently validated by the service arbiter.
        payload = {
            "historical_forward_pe": None,
            "historical_ev_ebitda": None,
            "period": "historical",
            "as_of": as_of_date,
            "source": f"Yahoo Finance multiples ({bundle.query_symbol})",
        }
        payload.update(
            industry_multiple_payload(
                info.get("sector"),
                info.get("industry"),
                as_of=as_of_date,
            )
        )
        return payload

    def supports_ticker(self, ticker: str) -> bool:
        try:
            self.get_quote(ticker)
            return True
        except (TickerNotFoundError, UnsupportedCompanyError, InvalidTickerError):
            return False
        except ProviderError:
            return False
