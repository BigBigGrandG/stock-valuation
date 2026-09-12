"""Vendor-neutral financial data provider boundary."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.domain import CompanyFinancialSnapshot, FinancialMetric, SourceType


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
    """Cash-flow facts with an explicit historical/forward boundary.

    ``net_borrowing`` is the aggregated statement value and is therefore
    historical (TTM or the documented annual fallback).  A forward borrowing
    value must arrive through one of the dedicated fields below; consumers
    must never promote ``net_borrowing`` into a forecast implicitly.
    """

    # Historical statement fields.  Keep the existing names for provider
    # compatibility while documenting that they are not forward drivers.
    cfo: Optional[Decimal] = None
    capex: Optional[Decimal] = None
    net_borrowing: Optional[Decimal] = None
    has_net_borrowing: Optional[bool] = None
    historical_net_borrowing: Optional[Decimal] = None
    historical_net_borrowing_period: Optional[str] = None
    historical_net_borrowing_as_of: Optional[date] = None
    interest: Optional[Decimal] = None
    tax_rate: Optional[Decimal] = None
    nwc_change: Optional[Decimal] = None

    # Explicit provider/model forward borrowing.  These fields intentionally
    # do not default from the historical ``net_borrowing`` field.
    forward_net_borrowing_1y: Optional[Decimal] = None
    forward_net_borrowing_1y_period: Optional[str] = None
    forward_net_borrowing_1y_source: Optional[str] = None
    forward_net_borrowing_1y_source_type: Optional[str] = None
    forward_net_borrowing_1y_as_of: Optional[date] = None
    forward_net_borrowing_1y_unit: Optional[str] = None
    forward_net_borrowing_1y_currency: Optional[str] = None
    forward_net_borrowing_1y_confidence: Optional[float] = None
    forward_net_borrowing_1y_is_estimated: Optional[bool] = None
    forward_net_borrowing_1y_notes: Optional[str] = None
    forward_net_borrowing_2y: Optional[Decimal] = None
    forward_net_borrowing_2y_period: Optional[str] = None
    forward_net_borrowing_2y_source: Optional[str] = None
    forward_net_borrowing_2y_source_type: Optional[str] = None
    forward_net_borrowing_2y_as_of: Optional[date] = None
    forward_net_borrowing_2y_unit: Optional[str] = None
    forward_net_borrowing_2y_currency: Optional[str] = None
    forward_net_borrowing_2y_confidence: Optional[float] = None
    forward_net_borrowing_2y_is_estimated: Optional[bool] = None
    forward_net_borrowing_2y_notes: Optional[str] = None
    forward_net_borrowing_warning: Optional[str] = None

    da: Optional[Decimal] = None
    da_period: Optional[str] = None
    da_as_of: Optional[date] = None
    da_is_fallback: Optional[bool] = None
    period: str = "TTM"
    as_of: Optional[date] = None
    source: str = "provider"


class IncomeStatementData(_RawData):
    revenue_ttm: Optional[Decimal] = None
    ebitda_ttm: Optional[Decimal] = None
    eps_ttm: Optional[Decimal] = None
    da: Optional[Decimal] = None
    da_period: Optional[str] = None
    da_as_of: Optional[date] = None
    da_is_fallback: Optional[bool] = None
    period: str = "TTM"
    as_of: Optional[date] = None
    source: str = "provider"


class ForwardEstimatesData(_RawData):
    forward_revenue_1y: Optional[Decimal] = None
    forward_revenue_2y: Optional[Decimal] = None
    # Optional explicit forward net-borrowing estimates.  These are kept at
    # the provider boundary so a normalizer can preserve their provenance;
    # they are never inferred from a TTM cash-flow statement.
    forward_net_borrowing_1y: Optional[Decimal] = None
    forward_net_borrowing_1y_period: Optional[str] = None
    forward_net_borrowing_1y_source: Optional[str] = None
    forward_net_borrowing_1y_source_type: Optional[str] = None
    forward_net_borrowing_1y_as_of: Optional[date] = None
    forward_net_borrowing_1y_unit: Optional[str] = None
    forward_net_borrowing_1y_currency: Optional[str] = None
    forward_net_borrowing_1y_confidence: Optional[float] = None
    forward_net_borrowing_1y_is_estimated: Optional[bool] = None
    forward_net_borrowing_1y_notes: Optional[str] = None
    forward_net_borrowing_2y: Optional[Decimal] = None
    forward_net_borrowing_2y_period: Optional[str] = None
    forward_net_borrowing_2y_source: Optional[str] = None
    forward_net_borrowing_2y_source_type: Optional[str] = None
    forward_net_borrowing_2y_as_of: Optional[date] = None
    forward_net_borrowing_2y_unit: Optional[str] = None
    forward_net_borrowing_2y_currency: Optional[str] = None
    forward_net_borrowing_2y_confidence: Optional[float] = None
    forward_net_borrowing_2y_is_estimated: Optional[bool] = None
    forward_net_borrowing_2y_notes: Optional[str] = None
    forward_net_borrowing_warning: Optional[str] = None
    period_1y: str = "FY1E"
    period_2y: str = "FY2E"
    as_of: Optional[date] = None
    source: str = "provider"



class HistoricalMultiplesData(_RawData):
    period: str = "historical"
    as_of: Optional[date] = None
    source: str = "provider"
    # Optional archived company observations.  Each row must include a
    # contemporaneous as_of/forecast_period/source and the matching price or
    # enterprise-value evidence; the selector validates the full contract.
    company_forward_pe_observations: Optional[list[dict[str, Any]]] = None
    company_ev_ebitda_observations: Optional[list[dict[str, Any]]] = None
    # Optional versioned public industry snapshot.  These fields are kept at
    # the provider boundary so source metadata survives normalisation.
    industry_name: Optional[str] = None
    industry_forward_pe: Optional[Decimal] = None
    industry_ev_ebitda: Optional[Decimal] = None
    industry_sample_size: Optional[int] = None
    industry_as_of: Optional[date] = None
    industry_period: Optional[str] = None
    industry_currency: Optional[str] = None
    industry_forward_pe_currency: Optional[str] = None
    industry_ev_ebitda_currency: Optional[str] = None
    industry_forward_pe_unit: Optional[str] = None
    industry_ev_ebitda_unit: Optional[str] = None
    industry_forward_pe_basis: Optional[str] = None
    industry_forward_pe_forecast_type: Optional[str] = None
    industry_ev_ebitda_basis: Optional[str] = None
    industry_ev_ebitda_forecast_type: Optional[str] = None
    industry_ev_ebitda_denominator_scope: Optional[str] = None
    industry_mapping_key: Optional[str] = None
    industry_mapping_source: Optional[str] = None
    industry_forward_pe_source: Optional[str] = None
    industry_forward_pe_source_url: Optional[str] = None
    industry_ev_ebitda_source: Optional[str] = None
    industry_ev_ebitda_source_url: Optional[str] = None
    industry_is_estimated: Optional[bool] = None
    industry_notes: Optional[str] = None
    industry_unavailable_reason: Optional[str] = None


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
        snapshot = self._attach_forward_borrowing(snapshot, raw[3], raw[5])
        return normalizer.normalize(snapshot)

    @staticmethod
    def _attach_forward_borrowing(
        snapshot: CompanyFinancialSnapshot,
        cash_flow: Any,
        estimates: Any,
    ) -> CompanyFinancialSnapshot:
        """Carry explicit provider forward borrowing into the request snapshot.

        The public snapshot predates the forward-borrowing contract and keeps
        compatibility with providers that do not publish this optional field.
        ``model_copy(update=...)`` preserves the metric for the projection
        layer without relabelling ``net_borrowing_ttm`` or manufacturing a
        default from it.
        """

        def mapping(raw: Any) -> dict[str, Any]:
            if isinstance(raw, BaseModel):
                return raw.model_dump()
            if isinstance(raw, dict):
                return dict(raw)
            return {}

        sources = [mapping(estimates), mapping(cash_flow)]
        updates: dict[str, Any] = {}
        for slot in (1, 2):
            prefix = f"forward_net_borrowing_{slot}y"
            payload: dict[str, Any] | None = None
            for source in sources:
                source_prefix = next(
                    (
                        candidate
                        for candidate in (
                            prefix,
                            f"forward_borrowing_{slot}y",
                            f"net_borrowing_forward_{slot}y",
                        )
                        if source.get(candidate) is not None
                    ),
                    None,
                )
                value = source.get(source_prefix) if source_prefix else None
                if value is not None:
                    metadata_prefix = source_prefix or prefix
                    payload = {
                        "value": value,
                        "period": source.get(f"{metadata_prefix}_period") or f"FY{slot}E",
                        "source": source.get(f"{metadata_prefix}_source") or source.get("source") or "provider forward net borrowing",
                        "source_type": source.get(f"{metadata_prefix}_source_type") or "analyst_estimate",
                        "as_of": source.get(f"{metadata_prefix}_as_of") or source.get("as_of") or snapshot.current_price.as_of,
                        "unit": source.get(f"{metadata_prefix}_unit") or source.get(f"{metadata_prefix}_currency") or snapshot.currency,
                        "confidence": source.get(f"{metadata_prefix}_confidence") or 0.7,
                        "is_estimated": source.get(f"{metadata_prefix}_is_estimated"),
                        "notes": source.get(f"{metadata_prefix}_notes"),
                    }
                    break
            if payload is None:
                continue

            raw_type = str(payload["source_type"]).strip().lower()
            normalized_type = {
                "provider_forward": SourceType.ANALYST_ESTIMATE,
                "provider": SourceType.ANALYST_ESTIMATE,
                "forward_provider": SourceType.ANALYST_ESTIMATE,
                "analyst_estimate": SourceType.ANALYST_ESTIMATE,
                "actual": SourceType.ACTUAL,
                "derived": SourceType.DERIVED,
                "fixture": SourceType.FIXTURE,
            }.get(raw_type)
            if normalized_type is None or raw_type in {"configured_fallback", "fallback", "system_default"}:
                # Invalid/fallback values stay out of the snapshot; the
                # projection layer will normalize the missing input to zero.
                continue
            notes = payload["notes"]
            if raw_type != getattr(normalized_type, "value", raw_type):
                notes = f"{notes}; original provider source_type={raw_type}" if notes else f"original provider source_type={raw_type}"
            try:
                updates[prefix] = FinancialMetric(
                    value=payload["value"],
                    unit=str(payload["unit"]),
                    period=str(payload["period"]),
                    source=str(payload["source"]),
                    source_type=normalized_type,
                    as_of=payload["as_of"],
                    confidence=float(payload["confidence"]),
                    is_estimated=(
                        bool(payload["is_estimated"])
                        if payload["is_estimated"] is not None
                        else normalized_type != SourceType.ACTUAL
                    ),
                    notes=notes,
                )
            except Exception:
                # Provider metadata validation is fail-closed: an invalid
                # forward candidate is ignored rather than falling back to
                # historical net borrowing.
                continue
        return snapshot.model_copy(update=updates) if updates else snapshot

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

        normalizer = Normalizer(strict_profile=True)
        snapshot = normalizer.normalize_provider_data(
            ticker, quote, profile, balance, cash_flow, income, estimates, multiples
        )
        return self._attach_forward_borrowing(snapshot, cash_flow, estimates)

    def supports_ticker(self, ticker: str) -> bool:
        try:
            self.get_quote(ticker)
            return True
        except ProviderError:
            return False
