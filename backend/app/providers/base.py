"""Vendor-neutral financial data provider boundary."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.domain import CompanyFinancialSnapshot


class ProviderError(Exception):
    """Base class for errors originating in a data provider."""


class TickerNotFoundError(ProviderError):
    """The provider has no record for a syntactically valid ticker."""


class InvalidTickerError(ProviderError):
    """Ticker syntax is invalid and should be returned as HTTP 422."""


class UnsupportedCompanyError(ProviderError):
    """The security is outside the MVP's supported operating-company scope."""

    def __init__(self, ticker: str, reason: str, detail: str = ""):
        self.ticker = ticker
        self.reason = reason
        self.detail = detail
        super().__init__(f"{ticker}: {reason} — {detail}".strip())


class ProviderUnavailableError(ProviderError):
    """Provider/network failure (HTTP 503)."""


class ProviderRateLimitError(ProviderUnavailableError):
    """Provider rate limit (HTTP 429)."""


class StaleDataError(ProviderError):
    """Provider returned data too stale to use."""


class FinancialDataValidationError(ValueError):
    """Provider data violated a financial-domain invariant (HTTP 422)."""


# Raw containers are typed at this boundary while allowing vendor-specific
# extra fields.  Providers may return either these models or dictionaries;
# Normalizer validates both forms before constructing the domain snapshot.
class _RawData(BaseModel):
    model_config = ConfigDict(extra="allow")

    @field_validator("as_of", mode="before", check_fields=False)
    @classmethod
    def _as_of_date(cls, value):
        if value is None or isinstance(value, date):
            return value
        return date.fromisoformat(str(value)[:10])


class QuoteData(_RawData):
    price: Decimal
    currency: str = "USD"
    exchange: Optional[str] = None
    market: Optional[str] = None
    timestamp: Optional[datetime] = None
    as_of: Optional[date] = None
    source: str = "provider"


class CompanyProfileData(_RawData):
    name: str
    diluted_shares: Optional[Decimal] = None
    currency: str = "USD"
    financial_currency: Optional[str] = None
    country: Optional[str] = None
    exchange: Optional[str] = None
    market: Optional[str] = None
    security_type: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    is_profitable: Optional[bool] = None
    as_of: Optional[date] = None
    source: str = "provider"


class BalanceSheetData(_RawData):
    cash: Optional[Decimal] = None
    total_debt: Optional[Decimal] = None
    net_debt: Optional[Decimal] = None
    period: str = "latest"
    as_of: Optional[date] = None
    source: str = "provider"


class CashFlowData(_RawData):
    period: str = "TTM"
    as_of: Optional[date] = None
    source: str = "provider"


class IncomeStatementData(_RawData):
    revenue_ttm: Optional[Decimal] = None
    ebitda_ttm: Optional[Decimal] = None
    eps_ttm: Optional[Decimal] = None
    period: str = "TTM"
    as_of: Optional[date] = None
    source: str = "provider"


class ForwardEstimatesData(_RawData):
    forward_revenue_1y: Optional[Decimal] = None
    forward_revenue_2y: Optional[Decimal] = None
    period_1y: str = "FY1E"
    period_2y: str = "FY2E"
    as_of: Optional[date] = None
    source: str = "provider"



class HistoricalMultiplesData(_RawData):
    period: str = "historical"
    as_of: Optional[date] = None
    source: str = "provider"


class FinancialDataProvider(ABC):
    """Seven-method provider interface plus a compatibility template method."""

    @abstractmethod
    def get_quote(self, ticker: str) -> QuoteData: ...

    @abstractmethod
    def get_company_profile(self, ticker: str) -> CompanyProfileData: ...

    @abstractmethod
    def get_balance_sheet(self, ticker: str) -> BalanceSheetData: ...

    @abstractmethod
    def get_cash_flow(self, ticker: str) -> CashFlowData: ...

    @abstractmethod
    def get_income_statement(self, ticker: str) -> IncomeStatementData: ...

    @abstractmethod
    def get_forward_estimates(self, ticker: str) -> ForwardEstimatesData: ...

    @abstractmethod
    def get_historical_multiples(self, ticker: str) -> HistoricalMultiplesData: ...

    def get_snapshot(self, ticker: str) -> CompanyFinancialSnapshot:
        """Convenience snapshot for callers; only the seven public methods are required."""

        # Keep the provider boundary vendor-neutral: a provider implementing
        # the documented seven methods need not add a private assembler.  The
        # service itself also calls these methods directly so it can cache
        # each category independently.
        from app.services.valuation_service import Normalizer

        raw = (
            self.get_quote(ticker),
            self.get_company_profile(ticker),
            self.get_balance_sheet(ticker),
            self.get_cash_flow(ticker),
            self.get_income_statement(ticker),
            self.get_forward_estimates(ticker),
            self.get_historical_multiples(ticker),
        )
        normalizer = Normalizer(strict_profile=True)
        snapshot = normalizer.normalize_provider_data(ticker, *raw)
        return normalizer.normalize(snapshot)

    def _assemble_snapshot(
        self,
        ticker: str,
        quote: QuoteData,
        profile: CompanyProfileData,
        balance: BalanceSheetData,
        cash_flow: CashFlowData,
        income: IncomeStatementData,
        estimates: ForwardEstimatesData,
        multiples: HistoricalMultiplesData,
    ) -> CompanyFinancialSnapshot:
        # Legacy compatibility hook for older provider callers.  New providers
        # should implement only the seven public methods above; neither this
        # hook nor a provider-specific assembler is used by FinancialDataService.
        from app.services.valuation_service import Normalizer

        return Normalizer(strict_profile=True).normalize_provider_data(
            ticker, quote, profile, balance, cash_flow, income, estimates, multiples
        )

    def supports_ticker(self, ticker: str) -> bool:
        try:
            self.get_quote(ticker)
            return True
        except ProviderError:
            return False
