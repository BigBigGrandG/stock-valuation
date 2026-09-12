"""Data fetch, normalization, caching and valuation orchestration."""
from __future__ import annotations

import re
import time
from datetime import date, datetime, time as datetime_time
from decimal import Decimal
from typing import Any, Callable, Mapping, Optional, Protocol, Type

from pydantic import BaseModel, ValidationError

from app.config import (
    CACHE_TTL_SECONDS,
    DEFAULT_ASSUMPTIONS,
    DCF_TERMINAL_GROWTH_MAX,
)
from app.engines.composite import run_composite
from app.engines.dcf import run_dcf
from app.engines.ev_ebitda import run_ev_ebitda
from app.engines.fcf_yield import run_fcf_yield
from app.engines.forward_pe import run_forward_pe
from app.services.multiples import resolve_multiple_assumptions
from app.services.projections import derive_request_projections
from app.models.domain import (
    CompanyFinancialSnapshot,
    CompositeValuation,
    DataQuality,
    FinancialMetric,
    ModelValuation,
    SourceType,
    ValuationAssumptions,
    ValuationResponse,
    net_debt_metric,
)
from app.models.overrides import OverrideValidationError
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
    QuoteData,
    UnsupportedCompanyError,
)
from app.providers.yfinance_provider import _RequestBudget, current_request_budget


class CacheProtocol(Protocol):
    def get(self, key: str) -> Any: ...
    def set(self, key: str, data: Any, ttl: int) -> None: ...
    def invalidate(self, key: str) -> None: ...
    def clear(self) -> None: ...


class _CacheEntry:
    def __init__(self, data: Any, expires_at: float):
        self.data = data
        self.expires_at = expires_at


class MemoryTTLCache:
    """Replaceable in-memory TTL cache with an injectable monotonic clock."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._store: dict[str, _CacheEntry] = {}

    def get(self, key: str) -> Any:
        entry = self._store.get(key)
        if entry is None:
            return None
        if self._clock() >= entry.expires_at:
            self._store.pop(key, None)
            return None
        return entry.data

    def set(self, key: str, data: Any, ttl: int) -> None:
        self._store[key] = _CacheEntry(data, self._clock() + ttl)

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()


def _metric_iter(snapshot: CompanyFinancialSnapshot) -> list[FinancialMetric]:
    metrics: list[FinancialMetric] = []
    for name, value in snapshot.__dict__.items():
        if isinstance(value, FinancialMetric):
            metrics.append(value)
    return metrics


def _support_guard(
    snapshot: CompanyFinancialSnapshot,
    *,
    strict_profile: bool = False,
    allow_all_equities: bool = False,
) -> None:
    """Reject unsupported securities from profile facts, not ticker deny-lists."""

    missing = [
        name for name, value in (
            ("country", snapshot.country),
            ("security_type", snapshot.security_type),
            ("is_profitable", snapshot.is_profitable),
        ) if value is None or (isinstance(value, str) and not value.strip())
    ]
    if missing and strict_profile:
        raise FinancialDataValidationError(
            "Provider profile is missing required metadata: " + ", ".join(missing)
        )

    # US listing check: live service supports all US-listed equities quoted in USD.
    # Non-US listings (e.g. quoted on foreign exchanges or non-USD quotes) are unsupported.
    currency = (snapshot.currency or "").strip().upper()
    if currency and currency != "USD":
        raise UnsupportedCompanyError(snapshot.ticker, "non_us_listing", f"Security is not quoted in USD (currency={snapshot.currency})")

    _US_EXCHANGES = {
        "NYQ", "NMS", "NGS", "NCM", "ASE", "PCX", "BATS", "IEX", "OTC", "PNK", "OQX", "OBB",
        "NYSE", "NASDAQ", "AMEX", "ARCA", "BATS GLOBAL MARKETS", "NEW YORK STOCK EXCHANGE",
    }
    _NON_US_EXCHANGES = {
        "LSE", "IOB", "TOR", "VAN", "TSX", "FRA", "GER", "PAR", "AMS", "BRU", "SWX", "EBS",
        "TA", "TLV", "HKG", "SHH", "SHZ", "TWO", "TAI", "KSC", "KOE", "ASX", "NZE", "MEX",
        "SAO", "BUE", "JNB", "STO", "HEL", "CPH", "OSL", "MIL", "MCE", "VIE", "ATH", "IST",
    }

    exchange = (snapshot.exchange or "").strip().upper()
    market = (snapshot.market or "").strip().lower()

    is_us_exchange = exchange in _US_EXCHANGES or market in {"us_market", "us"}
    is_non_us_exchange = exchange in _NON_US_EXCHANGES or (market and market not in {"us_market", "us"} and "us" not in market)

    if is_non_us_exchange:
        raise UnsupportedCompanyError(
            snapshot.ticker,
            "non_us_listing",
            f"Security is listed on non-US exchange (exchange={snapshot.exchange}, market={snapshot.market})"
        )

    country = (snapshot.country or "").strip().upper()
    is_us_hq = country in {"US", "USA", "UNITED STATES", "UNITED STATES OF AMERICA"}

    # In strict/demo mode (allow_all_equities=False), reject foreign headquarters
    if not allow_all_equities:
        if country and not is_us_hq:
            raise UnsupportedCompanyError(snapshot.ticker, "non_us", f"country={snapshot.country}")

    # In allow_all_equities mode, foreign-headquartered companies require verified US listing evidence (e.g. US ADRs)
    if allow_all_equities and country and not is_us_hq:
        if not is_us_exchange:
            if not exchange and not market:
                is_adr = "adr" in f"{snapshot.security_type or ''} {snapshot.company_name or ''}".lower()
                if not is_adr:
                    raise UnsupportedCompanyError(
                        snapshot.ticker,
                        "unknown_listing",
                        f"Foreign company (country={snapshot.country}) has unknown listing evidence (exchange missing)"
                    )
            else:
                raise UnsupportedCompanyError(
                    snapshot.ticker,
                    "non_us_listing",
                    f"Foreign company (country={snapshot.country}) listed on unverified exchange ({snapshot.exchange})"
                )
    security = f"{snapshot.security_type or ''} {snapshot.sector or ''} {snapshot.industry or ''}".lower()

    # Non-equities (ETFs, mutual funds, indices, SPACs, crypto) are ALWAYS unsupported:
    for needle, reason in (
        ("spac", "spac"),
        ("etf", "etf"),
        ("exchange traded fund", "etf"),
        ("mutual fund", "etf"),
        ("index", "etf"),
        ("cryptocurrency", "etf"),
        ("crypto", "etf"),
    ):
        if needle in security:
            raise UnsupportedCompanyError(snapshot.ticker, reason, f"profile={security.strip()}")

    # Unless arbitrary listed equities are allowed, reject financial services, banks, insurance, REITs, and loss-makers:
    if not allow_all_equities:
        for needle, reason in (
            ("financial services", "financial_services"),
            ("financials", "financial_services"),
            ("bank", "bank_or_insurance"),
            ("insurance", "bank_or_insurance"),
            ("reit", "reit"),
            ("real estate investment trust", "reit"),
        ):
            if needle in security:
                raise UnsupportedCompanyError(snapshot.ticker, reason, f"profile={security.strip()}")
        if snapshot.is_profitable is False:
            raise UnsupportedCompanyError(snapshot.ticker, "long_term_loss", "provider profile marks the company unprofitable")
        # A negative trailing EPS is a useful safety signal when no explicit
        # profitability flag was supplied, but a missing EPS remains permissible.
        if snapshot.is_profitable is None and snapshot.eps_ttm is not None and snapshot.eps_ttm.value < 0:
            raise UnsupportedCompanyError(snapshot.ticker, "long_term_loss", "negative trailing EPS")


def normalize_snapshot(
    snapshot: CompanyFinancialSnapshot,
    *,
    strict_profile: bool = False,
    allow_all_equities: bool = False,
) -> CompanyFinancialSnapshot:
    """Validate provider data, attach derived net debt, and compute quality."""

    warnings = list(snapshot.warnings)
    ticker = snapshot.ticker.strip().upper()
    if not ticker:
        raise FinancialDataValidationError("Ticker must not be empty")
    if snapshot.current_price.value <= 0:
        raise FinancialDataValidationError(f"Quote must be > 0, got {snapshot.current_price.value}")
    if snapshot.diluted_shares.value <= 0:
        raise FinancialDataValidationError(f"Diluted shares must be > 0, got {snapshot.diluted_shares.value}")
    if snapshot.cash is not None and snapshot.cash.value < 0:
        raise FinancialDataValidationError(f"Cash must be >= 0, got {snapshot.cash.value}")
    if snapshot.total_debt is not None and snapshot.total_debt.value < 0:
        raise FinancialDataValidationError(f"Total debt must be >= 0, got {snapshot.total_debt.value}")
    if snapshot.cash is None or snapshot.total_debt is None:
        warnings.append("Balance sheet is missing cash or total debt; dependent models (EV/EBITDA, DCF) will be disabled.")
    if snapshot.financial_currency and snapshot.financial_currency.upper() != snapshot.currency.upper():
        warnings.append(
            f"Currency mismatch: quote currency is {snapshot.currency} while financial statements are reported in {snapshot.financial_currency}; statement-dependent models will be disabled."
        )
    _support_guard(snapshot, strict_profile=strict_profile, allow_all_equities=allow_all_equities)
    if not strict_profile:
        profile_missing = [
            name for name, value in (
                ("country", snapshot.country),
                ("security_type", snapshot.security_type),
                ("is_profitable", snapshot.is_profitable),
            ) if value is None or (isinstance(value, str) and not value.strip())
        ]
        if profile_missing:
            warnings.append("Profile metadata incomplete: " + ", ".join(profile_missing))

    try:
        nd_metric = net_debt_metric(snapshot)
    except ValueError as exc:
        raise FinancialDataValidationError(str(exc)) from exc
    # All input dates matter for stale warnings, not just the quote date.
    if not snapshot.is_demo:
        today = date.today()
        stale = sorted({(today - metric.as_of).days for metric in _metric_iter(snapshot) if (today - metric.as_of).days > 7})
        if stale:
            warnings.append(
                f"Financial inputs are stale (oldest age {max(stale)} days); quote, statements and estimates should be refreshed."
            )

    metrics = _metric_iter(snapshot)
    missing_key = any(
        metric is None
        for metric in (
            snapshot.cash,
            snapshot.total_debt,
            snapshot.forward_eps_1y,
            snapshot.forward_ebitda_1y,
            snapshot.forward_fcf_1y,
            snapshot.forward_fcff_1y,
        )
    )
    any_estimated = any(metric.is_estimated for metric in metrics)
    any_weak_provenance = any(
        metric.source_type in {SourceType.CONFIGURED_FALLBACK, SourceType.DERIVED} or not metric.source
        for metric in metrics
    )
    if snapshot.is_demo:
        quality = DataQuality.LOW
    elif missing_key:
        quality = DataQuality.LOW
    elif any_estimated or any_weak_provenance:
        quality = DataQuality.MEDIUM
    else:
        quality = DataQuality.HIGH

    # Dedupe while preserving provider warning order.
    warnings = list(dict.fromkeys(warnings))
    return snapshot.model_copy(update={
        "ticker": ticker,
        "net_debt": nd_metric,
        "net_debt_metric": nd_metric,
        "data_quality": quality,
        "warnings": warnings,
    })


class Normalizer:
    """Validate raw provider categories, assemble a snapshot, then normalize."""

    def __init__(self, *, strict_profile: bool = True, allow_all_equities: bool = False):
        self.strict_profile = strict_profile
        self.allow_all_equities = allow_all_equities

    def normalize(self, snapshot: CompanyFinancialSnapshot) -> CompanyFinancialSnapshot:
        return normalize_snapshot(
            snapshot,
            strict_profile=self.strict_profile,
            allow_all_equities=self.allow_all_equities,
        )

    @staticmethod
    def _mapping(raw: Any, label: str) -> dict[str, Any]:
        if isinstance(raw, BaseModel):
            return raw.model_dump()
        if isinstance(raw, Mapping):
            return dict(raw)
        raise FinancialDataValidationError(f"Provider {label} response must be a mapping or typed container")

    @classmethod
    def _validated(cls, raw: Any, model: Type[BaseModel], label: str) -> dict[str, Any]:
        try:
            return model.model_validate(cls._mapping(raw, label)).model_dump()
        except (ValidationError, ValueError, TypeError) as exc:
            raise FinancialDataValidationError(f"Invalid provider {label} data: {exc}") from exc

    @staticmethod
    def _fcf_type(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip().upper().replace("FREE CASH FLOW TO EQUITY", "FCFE")
        text = text.replace("FREE CASH FLOW TO FIRM", "FCFF")
        text = text.replace("FREE CASH FLOW", "FCF")
        if "." in text:
            text = text.rsplit(".", 1)[-1]
        if text not in {"FCFE", "FCFF", "FCF"}:
            raise FinancialDataValidationError(f"Unknown cash-flow type: {value}")
        return text

    @classmethod
    def _validate_cash_flow_types(
        cls,
        mapping: Mapping[str, Any],
        *,
        expected: str,
        keys: tuple[str, ...],
        label: str,
    ) -> None:
        """Reject a provider's explicit FCFE/FCFF cross-wiring.

        The aliases ``fcf_ttm`` and ``forward_fcf_*`` are accepted for legacy
        providers, but an explicit type flag or definition remains binding.
        A provider cannot label a field FCFF while supplying it through the
        FCFE path (or vice versa).
        """

        if expected == "FCFE":
            family_type_keys = ("fcfe_type", "fcf_type", "cash_flow_type")
            family_definition_keys = ("fcfe_definition", "fcf_definition")
        else:
            family_type_keys = ("fcff_type", "cash_flow_type")
            family_definition_keys = ("fcff_definition",)

        for key in keys:
            if mapping.get(key) is None:
                continue
            raw_type = mapping.get(f"{key}_type")
            if raw_type is None:
                raw_type = cls._first([mapping], *family_type_keys)
            normalized = cls._fcf_type(raw_type)
            if normalized is not None and normalized not in {expected, "FCF"}:
                raise FinancialDataValidationError(
                    f"Provider {label} field {key} is typed {normalized}, incompatible with {expected}"
                )
            definition_keys = (f"{key}_definition", *family_definition_keys)
            definition = cls._first([mapping], *definition_keys)
            if definition is None:
                continue
            text = str(definition).upper()
            fcfe_marker = "FCFE" in text or "FREE CASH FLOW TO EQUITY" in text
            fcff_marker = "FCFF" in text or "FREE CASH FLOW TO FIRM" in text
            wrong_marker = fcff_marker if expected == "FCFE" else fcfe_marker
            expected_marker = fcfe_marker if expected == "FCFE" else fcff_marker
            if wrong_marker and not expected_marker:
                raise FinancialDataValidationError(
                    f"Provider {label} field {key} definition is incompatible with {expected}"
                )

    @staticmethod
    def _first(maps: list[Mapping[str, Any]], *keys: str) -> Any:
        for mapping in maps:
            for key in keys:
                if key in mapping and mapping[key] is not None:
                    return mapping[key]
        return None

    @staticmethod
    def _value_mapping(maps: list[Mapping[str, Any]], keys: tuple[str, ...]) -> Mapping[str, Any]:
        """Return the category containing the selected value.

        A few providers expose FCFE/FCFF in different categories (for
        example, estimates may fall back to cash flow).  Looking up source,
        date and period from the category that actually supplied the value
        prevents metadata from one category being attached to another.
        """

        for mapping in maps:
            if any(mapping.get(key) is not None for key in keys):
                return mapping
        return maps[0] if maps else {}

    @classmethod
    def _metric(
        cls,
        maps: list[Mapping[str, Any]],
        keys: tuple[str, ...],
        *,
        unit: str,
        period: str,
        source: str,
        as_of: date,
        source_type: SourceType | None = None,
        estimated: bool = False,
        notes: str | None = None,
        required: bool = False,
        period_keys: tuple[str, ...] = (),
    ) -> Optional[FinancialMetric]:
        value = cls._first(maps, *keys)
        if value is None:
            if required:
                raise FinancialDataValidationError(f"Provider did not supply required metric: {keys[0]}")
            return None
        if isinstance(value, FinancialMetric):
            return value
        try:
            decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
        except Exception as exc:
            raise FinancialDataValidationError(f"Metric {keys[0]} is not numeric") from exc
        if not decimal_value.is_finite():
            raise FinancialDataValidationError(f"Metric {keys[0]} must be finite")
        value_mapping = cls._value_mapping(maps, keys)
        # Per-metric metadata wins, then category metadata, then the explicit
        # fallback supplied by the caller.  Never use ``or`` for metadata:
        # confidence=0 and is_estimated=False are meaningful provider facts.
        metric_source = (
            cls._first([value_mapping], *(f"{key}_source" for key in keys))
            or value_mapping.get("source")
            or cls._first(maps, *(f"{key}_source" for key in keys), "source")
            or source
        )
        metric_as_of = (
            cls._first([value_mapping], *(f"{key}_as_of" for key in keys), "as_of")
            or cls._first(maps, *(f"{key}_as_of" for key in keys), "as_of")
            or as_of
        )
        if isinstance(metric_as_of, datetime):
            metric_as_of = metric_as_of.date()
        if not isinstance(metric_as_of, date):
            metric_as_of = date.fromisoformat(str(metric_as_of)[:10])
        metric_period = (
            cls._first([value_mapping], *(f"{key}_period" for key in keys), *period_keys, "period")
            or cls._first(maps, *(f"{key}_period" for key in keys), *period_keys, "period")
            or period
        )
        raw_type = (
            cls._first([value_mapping], *(f"{key}_source_type" for key in keys), "source_type")
            or cls._first(maps, *(f"{key}_source_type" for key in keys), "source_type")
        )
        if raw_type is not None:
            try:
                metric_source_type = raw_type if isinstance(raw_type, SourceType) else SourceType(str(raw_type))
            except ValueError as exc:
                raise FinancialDataValidationError(f"Unknown source_type for metric {keys[0]}") from exc
        elif source_type is not None:
            metric_source_type = source_type
        elif "fixture" in str(metric_source).lower():
            metric_source_type = SourceType.FIXTURE
        elif estimated:
            # Forward estimate fields without an explicit provider type are
            # estimates, never silently relabelled as actuals.
            metric_source_type = SourceType.ANALYST_ESTIMATE
        else:
            metric_source_type = SourceType.ACTUAL
        raw_estimated = cls._first(
            [value_mapping], *(f"{key}_is_estimated" for key in keys), "is_estimated"
        )
        if raw_estimated is None:
            raw_estimated = cls._first(maps, *(f"{key}_is_estimated" for key in keys), "is_estimated")
        metric_estimated = bool(estimated if raw_estimated is None else raw_estimated)
        metric_notes = (
            cls._first([value_mapping], *(f"{key}_notes" for key in keys), "notes")
            or cls._first(maps, *(f"{key}_notes" for key in keys), "notes")
            or notes
        )
        raw_confidence = cls._first(
            [value_mapping], *(f"{key}_confidence" for key in keys), "confidence"
        )
        if raw_confidence is None:
            raw_confidence = cls._first(maps, *(f"{key}_confidence" for key in keys), "confidence")
        confidence = (
            (0.5 if metric_estimated else 1.0)
            if raw_confidence is None
            else float(raw_confidence)
        )
        return FinancialMetric(
            value=decimal_value,
            unit=unit,
            period=str(metric_period),
            source=str(metric_source),
            source_type=metric_source_type,
            as_of=metric_as_of,
            confidence=confidence,
            is_estimated=metric_estimated,
            notes=metric_notes,
        )

    def normalize_provider_data(
        self,
        ticker: str,
        quote: Any,
        profile: Any,
        balance: Any,
        cash_flow: Any,
        income: Any,
        estimates: Any,
        multiples: Any,
    ) -> CompanyFinancialSnapshot:
        """Convert the seven public provider responses into a domain snapshot."""

        q = self._validated(quote, QuoteData, "quote")
        p = self._validated(profile, CompanyProfileData, "company profile")
        b = self._validated(balance, BalanceSheetData, "balance sheet")
        cf = self._validated(cash_flow if cash_flow is not None else {}, CashFlowData, "cash flow")
        inc = self._validated(income if income is not None else {}, IncomeStatementData, "income statement")
        est = self._validated(estimates if estimates is not None else {}, ForwardEstimatesData, "forward estimates")
        mult = self._validated(multiples if multiples is not None else {}, HistoricalMultiplesData, "historical multiples")
        maps = [q, p, b, cf, inc, est, mult]
        all_sources = " ".join(str(item.get("source", "")) for item in maps).lower()

        self._validate_cash_flow_types(
            cf, expected="FCFE", keys=("fcfe_ttm", "fcf_ttm"), label="FCFE TTM"
        )
        self._validate_cash_flow_types(
            cf, expected="FCFF", keys=("fcff_ttm",), label="FCFF TTM"
        )
        # Forward estimates are normally returned by ``estimates`` but some
        # providers expose one or both years in cash flow. Validate both
        # selected categories, field by field, before the fallback merge.
        for category, category_label in ((est, "forward estimates"), (cf, "cash-flow fallback")):
            self._validate_cash_flow_types(
                category,
                expected="FCFE",
                keys=("forward_fcfe_1y", "forward_fcfe_2y", "forward_fcf_1y", "forward_fcf_2y"),
                label=f"{category_label} FCFE",
            )
            self._validate_cash_flow_types(
                category,
                expected="FCFF",
                keys=("forward_fcff_1y", "forward_fcff_2y"),
                label=f"{category_label} FCFF",
            )

        timestamp = q.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        quote_as_of = q.get("as_of")
        if quote_as_of is None and isinstance(timestamp, datetime):
            quote_as_of = timestamp.date()
        fallback_as_of = self._first(maps, "as_of")
        if quote_as_of is None:
            quote_as_of = fallback_as_of
        if isinstance(quote_as_of, datetime):
            quote_as_of = quote_as_of.date()
        if not isinstance(quote_as_of, date):
            raise FinancialDataValidationError("Provider responses must include an as_of date")
        if timestamp is None:
            timestamp = datetime.combine(quote_as_of, datetime_time.min)
        if not isinstance(timestamp, datetime):
            raise FinancialDataValidationError("Provider quote timestamp must be a datetime")

        def category_as_of(mapping: Mapping[str, Any]) -> date:
            value = mapping.get("as_of") or quote_as_of
            if isinstance(value, datetime):
                value = value.date()
            if not isinstance(value, date):
                raise FinancialDataValidationError("Provider category as_of must be a date")
            return value

        profile_as_of = category_as_of(p)
        balance_as_of = category_as_of(b)
        cash_flow_as_of = category_as_of(cf)
        income_as_of = category_as_of(inc)
        estimates_as_of = category_as_of(est)
        multiples_as_of = category_as_of(mult)

        company_name = p.get("name")
        shares_value = p.get("diluted_shares")
        if shares_value is None:
            raise FinancialDataValidationError("Provider profile missing diluted_shares")
        period_balance = b.get("period", "latest")
        period_income = inc.get("period", "TTM")
        period_est_1 = est.get("period_1y", "FY1E")
        period_est_2 = est.get("period_2y", "FY2E")
        fixture = bool(p.get("is_demo", False) or "fixture" in all_sources)
        default_source = p.get("source") or q.get("source") or "provider"

        fin_curr = str(p.get("financial_currency") or q.get("currency") or "USD")
        quote_curr = str(q.get("currency") or "USD")

        # ADR currency & share basis validation
        est_basis = str(est.get("forward_eps_basis") or ("ADS" if (p.get("security_type") == "ADR" or "ADR" in str(company_name).upper()) else "share"))
        est_1y_curr = est.get("forward_eps_1y_currency")
        est_2y_curr = est.get("forward_eps_2y_currency")

        # If foreign currency reporting company/ADR:
        # Validate that forward EPS currency matches quote currency (e.g. USD)
        is_adr_or_foreign = (fin_curr.upper() != quote_curr.upper())
        if is_adr_or_foreign:
            if est.get("forward_eps_1y") is not None and est_1y_curr is not None and est_1y_curr.upper() != quote_curr.upper():
                est = dict(est)
                est["forward_eps_1y"] = None
                est_1y_curr = None
            if est.get("forward_eps_2y") is not None and est_2y_curr is not None and est_2y_curr.upper() != quote_curr.upper():
                est = dict(est)
                est["forward_eps_2y"] = None
                est_2y_curr = None

        eps1_unit = f"{est_1y_curr or quote_curr}/{est_basis}"
        eps2_unit = f"{est_2y_curr or quote_curr}/{est_basis}"
        current_price = self._metric([q], ("price",), unit=quote_curr, period=str(quote_as_of), source=str(q.get("source", default_source)), as_of=quote_as_of, required=True)
        diluted_shares = self._metric([p], ("diluted_shares",), unit="shares", period=period_balance, source=str(p.get("source", default_source)), as_of=profile_as_of, required=True)
        cash = self._metric([b], ("cash",), unit=fin_curr, period=period_balance, source=str(b.get("source", default_source)), as_of=balance_as_of, required=False)
        total_debt = self._metric([b], ("total_debt",), unit=fin_curr, period=period_balance, source=str(b.get("source", default_source)), as_of=balance_as_of, required=False)
        income_maps = [inc]
        estimate_maps = [est, cf]
        return CompanyFinancialSnapshot(
            ticker=ticker.upper(),
            company_name=str(company_name),
            currency=quote_curr,
            financial_currency=p.get("financial_currency"),
            current_price=current_price,
            price_timestamp=timestamp,
            diluted_shares=diluted_shares,
            cash=cash,
            total_debt=total_debt,
            revenue_ttm=self._metric(income_maps, ("revenue_ttm",), unit=fin_curr, period=period_income, source=str(inc.get("source", default_source)), as_of=income_as_of),
            ebitda_ttm=self._metric(income_maps, ("ebitda_ttm",), unit=fin_curr, period=period_income, source=str(inc.get("source", default_source)), as_of=income_as_of),
            eps_ttm=self._metric(income_maps, ("eps_ttm",), unit=f"{fin_curr}/share", period=period_income, source=str(inc.get("source", default_source)), as_of=income_as_of),
            fcf_ttm=self._metric([cf], ("fcfe_ttm", "fcf_ttm"), unit=fin_curr, period=str(cf.get("period", "TTM")), source=str(cf.get("source", default_source)), as_of=cash_flow_as_of, notes=str(cf.get("fcfe_definition", "FCFE; FCF-yield model only."))),
            cfo_ttm=self._metric([cf], ("cfo", "cfo_ttm", "operating_cash_flow"), unit=fin_curr, period=str(cf.get("period", "TTM")), source=str(cf.get("source", default_source)), as_of=cash_flow_as_of),
            capex_ttm=self._metric([cf], ("capex", "capex_ttm", "capital_expenditure"), unit=fin_curr, period=str(cf.get("period", "TTM")), source=str(cf.get("source", default_source)), as_of=cash_flow_as_of),
            net_borrowing_ttm=self._metric([cf], ("net_borrowing", "net_borrowing_ttm"), unit=fin_curr, period=str(cf.get("period", "TTM")), source=str(cf.get("source", default_source)), as_of=cash_flow_as_of),
            da_ttm=self._metric([inc, cf], ("da", "da_ttm", "reconciled_depreciation"), unit=fin_curr, period=str(inc.get("da_period") or cf.get("da_period") or period_income), source=str(inc.get("source", default_source)), as_of=inc.get("da_as_of") or cf.get("da_as_of") or income_as_of),
            nwc_change_ttm=self._metric([cf], ("nwc_change", "nwc_change_ttm", "change_in_working_capital"), unit=fin_curr, period=str(cf.get("period", "TTM")), source=str(cf.get("source", default_source)), as_of=cash_flow_as_of),
            interest_ttm=self._metric([cf, inc], ("interest", "interest_ttm", "interest_expense"), unit=fin_curr, period=str(cf.get("period", period_income)), source=str(cf.get("source", default_source)), as_of=cash_flow_as_of),
            forward_fcf_1y=self._metric(estimate_maps, ("forward_fcfe_1y", "forward_fcf_1y"), unit=fin_curr, period=period_est_1, period_keys=("period_1y",), source=str(est.get("source", default_source)), as_of=estimates_as_of, estimated=True, notes="Forward FCFE; FCF-yield model only."),
            forward_fcf_2y=self._metric(estimate_maps, ("forward_fcfe_2y", "forward_fcf_2y"), unit=fin_curr, period=period_est_2, period_keys=("period_2y",), source=str(est.get("source", default_source)), as_of=estimates_as_of, estimated=True, notes="Forward FCFE; FCF-yield model only."),
            fcff_ttm=self._metric([cf], ("fcff_ttm",), unit=fin_curr, period=str(cf.get("period", "TTM")), source=str(cf.get("source", default_source)), as_of=cash_flow_as_of, notes=str(cf.get("fcff_definition", "FCFF; DCF model only."))),
            forward_fcff_1y=self._metric(estimate_maps, ("forward_fcff_1y",), unit=fin_curr, period=period_est_1, period_keys=("period_1y",), source=str(est.get("source", default_source)), as_of=estimates_as_of, estimated=True, notes="Forward FCFF; DCF model only."),
            forward_fcff_2y=self._metric(estimate_maps, ("forward_fcff_2y",), unit=fin_curr, period=period_est_2, period_keys=("period_2y",), source=str(est.get("source", default_source)), as_of=estimates_as_of, estimated=True, notes="Forward FCFF; DCF model only."),
            forward_eps_1y=self._metric([est], ("forward_eps_1y",), unit=eps1_unit, period=period_est_1, period_keys=("period_1y",), source=str(est.get("source", default_source)), as_of=estimates_as_of, estimated=True),
            forward_eps_2y=self._metric([est], ("forward_eps_2y",), unit=eps2_unit, period=period_est_2, period_keys=("period_2y",), source=str(est.get("source", default_source)), as_of=estimates_as_of, estimated=True),
            forward_ebitda_1y=self._metric([est], ("forward_ebitda_1y",), unit=fin_curr, period=period_est_1, period_keys=("period_1y",), source=str(est.get("source", default_source)), as_of=estimates_as_of, estimated=True),
            forward_ebitda_2y=self._metric([est], ("forward_ebitda_2y",), unit=fin_curr, period=period_est_2, period_keys=("period_2y",), source=str(est.get("source", default_source)), as_of=estimates_as_of, estimated=True),
            revenue_estimate_1y=self._metric([est], ("forward_revenue_1y", "revenue_estimate_1y"), unit=fin_curr, period=period_est_1, period_keys=("period_1y",), source=str(est.get("source", default_source)), as_of=estimates_as_of, estimated=True),
            revenue_estimate_2y=self._metric([est], ("forward_revenue_2y", "revenue_estimate_2y"), unit=fin_curr, period=period_est_2, period_keys=("period_2y",), source=str(est.get("source", default_source)), as_of=estimates_as_of, estimated=True),
            forward_revenue=self._metric([est], ("forward_revenue_1y", "revenue_estimate_1y", "forward_revenue"), unit=fin_curr, period=period_est_1, period_keys=("period_1y",), source=str(est.get("source", default_source)), as_of=estimates_as_of, estimated=True),

            historical_forward_pe=self._metric([mult], ("historical_forward_pe",), unit="ratio", period=str(mult.get("period", "historical")), source=str(mult.get("source", default_source)), as_of=multiples_as_of),
            historical_ev_ebitda=self._metric([mult], ("historical_ev_ebitda",), unit="ratio", period=str(mult.get("period", "historical")), source=str(mult.get("source", default_source)), as_of=multiples_as_of),
            multiple_candidates={
                key: value
                for key, value in {
                    "company_forward_pe_observations": mult.get("company_forward_pe_observations"),
                    "company_ev_ebitda_observations": mult.get("company_ev_ebitda_observations"),
                    "industry_name": mult.get("industry_name"),
                    "industry_forward_pe": mult.get("industry_forward_pe"),
                    "industry_ev_ebitda": mult.get("industry_ev_ebitda"),
                    "industry_sample_size": mult.get("industry_sample_size"),
                    "industry_as_of": mult.get("industry_as_of"),
                    "industry_period": mult.get("industry_period"),
                    "industry_currency": mult.get("industry_currency"),
                    "industry_forward_pe_currency": mult.get("industry_forward_pe_currency"),
                    "industry_ev_ebitda_currency": mult.get("industry_ev_ebitda_currency"),
                    "industry_forward_pe_unit": mult.get("industry_forward_pe_unit"),
                    "industry_ev_ebitda_unit": mult.get("industry_ev_ebitda_unit"),
                    "industry_forward_pe_basis": mult.get("industry_forward_pe_basis"),
                    "industry_forward_pe_forecast_type": mult.get("industry_forward_pe_forecast_type"),
                    "industry_ev_ebitda_basis": mult.get("industry_ev_ebitda_basis"),
                    "industry_ev_ebitda_forecast_type": mult.get("industry_ev_ebitda_forecast_type"),
                    "industry_ev_ebitda_denominator_scope": mult.get("industry_ev_ebitda_denominator_scope"),
                    "industry_mapping_key": mult.get("industry_mapping_key"),
                    "industry_mapping_source": mult.get("industry_mapping_source"),
                    "industry_forward_pe_source": mult.get("industry_forward_pe_source"),
                    "industry_forward_pe_source_url": mult.get("industry_forward_pe_source_url"),
                    "industry_ev_ebitda_source": mult.get("industry_ev_ebitda_source"),
                    "industry_ev_ebitda_source_url": mult.get("industry_ev_ebitda_source_url"),
                    "industry_is_estimated": mult.get("industry_is_estimated"),
                    "industry_notes": mult.get("industry_notes"),
                    "industry_unavailable_reason": mult.get("industry_unavailable_reason"),
                }.items()
                if value is not None
            },
            revenue_growth=self._metric(maps, ("revenue_growth",), unit="ratio", period="growth", source=str(default_source), as_of=quote_as_of, estimated=True),
            ebitda_growth=self._metric(maps, ("ebitda_growth",), unit="ratio", period="growth", source=str(default_source), as_of=quote_as_of, estimated=True),
            eps_growth=self._metric(maps, ("eps_growth",), unit="ratio", period="growth", source=str(default_source), as_of=quote_as_of, estimated=True),
            fcf_growth=self._metric(maps, ("fcf_growth",), unit="ratio", period="growth", source=str(default_source), as_of=quote_as_of, estimated=True, notes="FCFE growth; never a DCF FCFF proxy."),
            fcff_growth=self._metric(maps, ("fcff_growth",), unit="ratio", period="growth", source=str(default_source), as_of=quote_as_of, estimated=True),
            risk_free_rate=self._metric(maps, ("risk_free_rate",), unit="rate", period="assumption", source=str(default_source), as_of=quote_as_of),
            beta=self._metric(maps, ("beta",), unit="ratio", period="assumption", source=str(default_source), as_of=quote_as_of),
            equity_risk_premium=self._metric(maps, ("equity_risk_premium",), unit="rate", period="assumption", source=str(default_source), as_of=quote_as_of),
            pre_tax_cost_of_debt=self._metric(maps, ("pre_tax_cost_of_debt",), unit="rate", period="assumption", source=str(default_source), as_of=quote_as_of),
            tax_rate=self._metric(maps, ("tax_rate",), unit="rate", period="assumption", source=str(default_source), as_of=quote_as_of),
            country=p.get("country"),
            exchange=p.get("exchange") or q.get("exchange"),
            market=p.get("market") or q.get("market"),
            security_type=p.get("security_type"),
            sector=p.get("sector"),
            industry=p.get("industry"),
            is_profitable=p.get("is_profitable"),
            shares_basis=p.get("shares_basis", "point_in_time_all_classes"),
            shares_reconciliation=p.get("shares_reconciliation"),
            statement_basis=inc.get("statement_basis") or cf.get("statement_basis") or ("ANNUAL_FALLBACK" if (inc.get("annual_fallback") or cf.get("annual_fallback")) else "TTM"),
            annual_fallback=bool(inc.get("annual_fallback") or cf.get("annual_fallback")),
            forecast_fiscal_year_end=est.get("forecast_fiscal_year_end"),
            ntm_weights=est.get("ntm_weights"),
            data_quality=DataQuality.LOW if fixture else DataQuality.HIGH,
            is_demo=fixture,
            warnings=list(p.get("warnings") or [])
            + (["DEMO DATA: values come from a fixed fixture."] if fixture else [])
            + ([f"currency_mismatch: quote in {quote_curr}, financial statements in {p.get('financial_currency')}"] if (p.get("financial_currency") and str(p.get("financial_currency")).upper() != quote_curr.upper()) else []),
        )


def _decimal_override(value: object, field: str) -> Decimal:
    if isinstance(value, bool):
        raise OverrideValidationError(f"{field} must be a finite number")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except Exception as exc:
        raise OverrideValidationError(f"{field} must be numeric") from exc
    if not result.is_finite():
        raise OverrideValidationError(f"{field} must be finite")
    return result


def apply_overrides(base_assumptions: ValuationAssumptions, overrides: Optional[dict]) -> ValuationAssumptions:
    """Apply sparse flattened overrides without mutating defaults or caches."""

    if not overrides:
        return base_assumptions
    allowed = {
        "forward_pe.base", "forward_pe.low", "forward_pe.high",
        "ev_ebitda.base", "ev_ebitda.low", "ev_ebitda.high",
        "fcf_yield.base", "fcf_yield.low", "fcf_yield.high",
        "dcf.wacc", "dcf.terminal_growth", "dcf.fcf_growth",
        "dcf.growth_floor", "dcf.growth_cap",
        "weights.weight_pe", "weights.weight_ev_ebitda",
        "weights.weight_fcf_yield", "weights.weight_dcf",
        "weights.cashflow_group_max_weight",
        "forecast_horizon",
        "drivers.ebitda_margin",
        "drivers.capex",
        "drivers.capex_ratio",
        "drivers.nwc_change",
        "drivers.nwc_ratio",
        "drivers.net_borrowing",
        "drivers.da",
        "drivers.da_ratio",
        "drivers.tax_rate",
    }
    unknown = set(overrides) - allowed
    if unknown:
        raise OverrideValidationError(f"Unknown override fields: {sorted(unknown)}")
    data = base_assumptions.model_dump()

    # Process driver overrides
    driver_fields = (
        ("drivers.ebitda_margin", "driver_ebitda_margin"),
        ("drivers.capex", "driver_capex"),
        ("drivers.capex_ratio", "driver_capex_ratio"),
        ("drivers.nwc_change", "driver_nwc_change"),
        ("drivers.nwc_ratio", "driver_nwc_ratio"),
        ("drivers.net_borrowing", "driver_net_borrowing"),
        ("drivers.da", "driver_da"),
        ("drivers.da_ratio", "driver_da_ratio"),
        ("drivers.tax_rate", "driver_tax_rate"),
    )
    for override_key, data_field in driver_fields:
        if override_key in overrides:
            val = _decimal_override(overrides[override_key], override_key)
            if override_key in ("drivers.ebitda_margin", "drivers.tax_rate") and not (Decimal("-1.0") <= val <= Decimal("1.0")):
                raise OverrideValidationError(f"{override_key} must be between -1.0 and 1.0")
            if override_key in ("drivers.capex_ratio", "drivers.da_ratio") and not (Decimal("0") <= val <= Decimal("2.0")):
                raise OverrideValidationError(f"{override_key} must be between 0 and 2.0")
            data[data_field] = val

    def update_scenarios(field: str, prefix: str, inverse: bool = False) -> None:
        sv = dict(data[field])
        values = {name: _decimal_override(overrides[f"{prefix}.{name}"], f"{prefix}.{name}") for name in ("low", "base", "high") if f"{prefix}.{name}" in overrides}
        if "base" in values:
            values.setdefault("low", values["base"] * (Decimal("1.1") if inverse else Decimal("0.9")))
            values.setdefault("high", values["base"] * (Decimal("0.9") if inverse else Decimal("1.1")))
        sv.update(values)
        data[field] = sv

    if any(key.startswith("forward_pe.") for key in overrides):
        update_scenarios("pe_target", "forward_pe")
        data["pe_source"] = SourceType.USER_OVERRIDE
        data["pe_source_label"] = "User override"
        data["pe_selection_layer"] = "user_override"
    if any(key.startswith("ev_ebitda.") for key in overrides):
        update_scenarios("ev_ebitda_multiple", "ev_ebitda")
        data["ev_ebitda_source"] = SourceType.USER_OVERRIDE
        data["ev_ebitda_source_label"] = "User override"
        data["ev_ebitda_selection_layer"] = "user_override"
    if any(key.startswith("fcf_yield.") for key in overrides):
        update_scenarios("fcf_yield", "fcf_yield", inverse=True)
        data["fcf_yield_source"] = SourceType.USER_OVERRIDE
        data["fcf_yield_source_label"] = "User override"
    if "dcf.wacc" in overrides:
        wacc = _decimal_override(overrides["dcf.wacc"], "dcf.wacc")
        if not (ZERO < wacc <= Decimal("0.5")):
            raise OverrideValidationError("dcf.wacc must be > 0 and <= 0.5")
        sv = dict(data["dcf_wacc"])
        sv["base"] = wacc
        data["dcf_wacc"] = sv
        data["dcf_wacc_source"] = SourceType.USER_OVERRIDE
        data["dcf_wacc_source_label"] = "User override"
    if "dcf.terminal_growth" in overrides:
        growth = _decimal_override(overrides["dcf.terminal_growth"], "dcf.terminal_growth")
        if not (ZERO <= growth <= DCF_TERMINAL_GROWTH_MAX):
            raise OverrideValidationError(f"dcf.terminal_growth must be between 0 and {DCF_TERMINAL_GROWTH_MAX}")
        sv = dict(data["dcf_terminal_growth"])
        sv["base"] = growth
        data["dcf_terminal_growth"] = sv
        data["dcf_terminal_growth_source"] = SourceType.USER_OVERRIDE
        data["dcf_terminal_growth_source_label"] = "User override"
    if "dcf.fcf_growth" in overrides:
        growth = _decimal_override(overrides["dcf.fcf_growth"], "dcf.fcf_growth")
        if not (Decimal("-0.5") <= growth <= Decimal("0.5")):
            raise OverrideValidationError("dcf.fcf_growth must be between -0.5 and 0.5")
        data["dcf_fcf_growth"] = {"low": growth, "base": growth, "high": growth}
    if "dcf.growth_floor" in overrides:
        g_floor = _decimal_override(overrides["dcf.growth_floor"], "dcf.growth_floor")
        if not (Decimal("-1.0") < g_floor <= Decimal("2.0")):
            raise OverrideValidationError("dcf.growth_floor must be > -1.0 and <= 2.0")
        data["growth_floor"] = g_floor
    if "dcf.growth_cap" in overrides:
        g_cap = _decimal_override(overrides["dcf.growth_cap"], "dcf.growth_cap")
        if not (Decimal("-1.0") < g_cap <= Decimal("2.0")):
            raise OverrideValidationError("dcf.growth_cap must be > -1.0 and <= 2.0")
        data["growth_cap"] = g_cap
    if data.get("growth_floor", Decimal("-0.20")) > data.get("growth_cap", Decimal("0.40")):
        raise OverrideValidationError("growth_floor must be <= growth_cap")

    if "weights.weight_pe" in overrides:
        w = _decimal_override(overrides["weights.weight_pe"], "weights.weight_pe")
        if w < ZERO:
            raise OverrideValidationError("weight_pe must be >= 0")
        data["weight_pe"] = w
    if "weights.weight_ev_ebitda" in overrides:
        w = _decimal_override(overrides["weights.weight_ev_ebitda"], "weights.weight_ev_ebitda")
        if w < ZERO:
            raise OverrideValidationError("weight_ev_ebitda must be >= 0")
        data["weight_ev_ebitda"] = w
    if "weights.weight_fcf_yield" in overrides:
        w = _decimal_override(overrides["weights.weight_fcf_yield"], "weights.weight_fcf_yield")
        if w < ZERO:
            raise OverrideValidationError("weight_fcf_yield must be >= 0")
        data["weight_fcf_yield"] = w
    if "weights.weight_dcf" in overrides:
        w = _decimal_override(overrides["weights.weight_dcf"], "weights.weight_dcf")
        if w < ZERO:
            raise OverrideValidationError("weight_dcf must be >= 0")
        data["weight_dcf"] = w
    if "weights.cashflow_group_max_weight" in overrides:
        w = _decimal_override(overrides["weights.cashflow_group_max_weight"], "weights.cashflow_group_max_weight")
        if not (ZERO <= w <= Decimal("1.0")):
            raise OverrideValidationError("cashflow_group_max_weight must be between 0 and 1.0")
        data["cashflow_group_max_weight"] = w

    if any(k.startswith("weights.weight_") for k in overrides):
        if (
            data["weight_pe"] <= ZERO
            and data["weight_ev_ebitda"] <= ZERO
            and data["weight_fcf_yield"] <= ZERO
            and data["weight_dcf"] <= ZERO
        ):
            raise OverrideValidationError("At least one model weight must be greater than 0")

    if "forecast_horizon" in overrides:
        horizon = str(overrides["forecast_horizon"]).lower()
        if horizon not in {"ntm", "current_fy", "next_fy"}:
            raise OverrideValidationError(f"Invalid forecast_horizon: {horizon}")
        data["forecast_horizon"] = horizon

    result = ValuationAssumptions(**data)
    for label, values, maximum in (
        ("P/E", result.pe_target, Decimal("200")),
        ("EV/EBITDA", result.ev_ebitda_multiple, Decimal("200")),
        ("FCF yield", result.fcf_yield, Decimal("0.5")),
    ):
        if any(value <= ZERO or value > maximum for value in (values.low, values.base, values.high)):
            raise OverrideValidationError(
                f"Effective {label} assumptions must be > 0 and <= {maximum}"
            )
    if not (
        result.pe_target.low <= result.pe_target.base <= result.pe_target.high
        and result.ev_ebitda_multiple.low <= result.ev_ebitda_multiple.base <= result.ev_ebitda_multiple.high
        and result.fcf_yield.low >= result.fcf_yield.base >= result.fcf_yield.high > ZERO
    ):
        raise OverrideValidationError("Effective model scenario assumptions are out of order")
    for label, wacc, growth in (
        ("bear", result.dcf_wacc.low, result.dcf_terminal_growth.low),
        ("base", result.dcf_wacc.base, result.dcf_terminal_growth.base),
        ("bull", result.dcf_wacc.high, result.dcf_terminal_growth.high),
    ):
        if wacc <= growth:
            raise OverrideValidationError(f"DCF {label}: WACC ({wacc}) must be greater than terminal_growth ({growth})")
    return result


def _failed_model(name: str, exc: Exception) -> ModelValuation:
    formulas = {
        "forward_pe": "Price = Forward EPS × Target P/E",
        "ev_ebitda": "EV = Forward EBITDA × Multiple; Price = (EV - Net Debt) / Shares",
        "fcf_yield": "Equity Value = Forward FCFE / Yield Rate; Price = Equity / Shares",
        "dcf": "EV = Σ FCFF_t/(1+WACC)^t + TV/(1+WACC)^5; Equity = EV − Net Debt; Price = Equity/Shares",
    }
    return ModelValuation(
        formula=formulas.get(name, name),
        formula_description=f"{name} model unavailable",
        inputs={},
        assumptions={},
        calculation_steps=[],
        available=False,
        unavailable_reason=f"{type(exc).__name__}: {exc}",
        data_quality=DataQuality.LOW,
    )


ZERO = Decimal("0")


def run_all_engines(snapshot: CompanyFinancialSnapshot, assumptions: ValuationAssumptions) -> dict[str, ModelValuation]:
    """Run each engine independently; one bad model cannot erase others."""
    proj = derive_request_projections(snapshot, assumptions)
    req_updates: dict[str, Any] = {}

    def _source_type(field: str) -> SourceType | None:
        metric = getattr(snapshot, field, None)
        return getattr(metric, "source_type", None)

    if proj.forward_eps is not None:
        req_updates["forward_eps_1y"] = proj.forward_eps
    elif _source_type("forward_eps_1y") != SourceType.ANALYST_ESTIMATE:
        req_updates["forward_eps_1y"] = None

    if proj.forward_revenue is not None:
        req_updates["revenue_estimate_1y"] = proj.forward_revenue
        req_updates["forward_revenue"] = proj.forward_revenue

    if proj.forward_ebitda is not None:
        req_updates["forward_ebitda_1y"] = proj.forward_ebitda
    elif _source_type("forward_ebitda_1y") != SourceType.ANALYST_ESTIMATE:
        req_updates["forward_ebitda_1y"] = None
        if _source_type("forward_ebitda_2y") != SourceType.ANALYST_ESTIMATE:
            req_updates["forward_ebitda_2y"] = None

    if proj.forward_fcfe_1y is not None:
        req_updates["forward_fcf_1y"] = proj.forward_fcfe_1y
    elif _source_type("forward_fcf_1y") != SourceType.ANALYST_ESTIMATE:
        req_updates["forward_fcf_1y"] = None

    # DCF is the only consumer of FCFF. The request projection is the
    # authority for explicit FY1/FY2 eligibility and driver overrides; do not
    # re-introduce an NTM/derived metric (or a stale cached metric) when that
    # projection is unavailable. A complete production DCF requires both
    # explicit forecast years: submitting only FY1 would let the standalone
    # engine synthesize FY2 from historical FCFF/growth, which is not a
    # verified second-year driver. The standalone ``run_dcf`` engine may retain
    # its documented historical fallback for explicit direct callers, but no
    # partial request projection can reach that fallback here.
    dcf_projection_complete = all(
        metric is not None and metric.value.is_finite() and metric.value > ZERO
        for metric in (proj.dcf_fcff_1y, proj.dcf_fcff_2y)
    )
    if dcf_projection_complete:
        req_updates["forward_fcff_1y"] = proj.dcf_fcff_1y
        req_updates["forward_fcff_2y"] = proj.dcf_fcff_2y
    else:
        req_updates["forward_fcff_1y"] = None
        req_updates["forward_fcff_2y"] = None
        req_updates["fcff_ttm"] = None
    req_snapshot = snapshot.model_copy(update=req_updates)
    runners = {
        "forward_pe": run_forward_pe,
        "ev_ebitda": run_ev_ebitda,
        "fcf_yield": run_fcf_yield,
        "dcf": run_dcf,
    }
    results: dict[str, ModelValuation] = {}
    for name, runner in runners.items():
        try:
            results[name] = runner(req_snapshot, assumptions)
        except Exception as exc:
            results[name] = _failed_model(name, exc)
    return results


def assemble_response(
    snapshot: CompanyFinancialSnapshot,
    valuations: dict[str, ModelValuation],
    composite: CompositeValuation,
    assumptions: ValuationAssumptions,
    financial_bridge: Optional[dict[str, Any]] = None,
) -> ValuationResponse:
    active_quality = [model.data_quality for model in valuations.values() if model.available]
    if snapshot.is_demo or not active_quality or DataQuality.LOW in active_quality:
        quality = DataQuality.LOW
    elif DataQuality.MEDIUM in active_quality:
        quality = DataQuality.MEDIUM
    else:
        quality = DataQuality.HIGH
    warnings = list(snapshot.warnings)
    for model in valuations.values():
        warnings.extend(model.warnings)
    return ValuationResponse(
        ticker=snapshot.ticker,
        company_name=snapshot.company_name,
        current_price=snapshot.current_price.value,
        currency=snapshot.currency,
        as_of=snapshot.price_timestamp,
        price_timestamp=snapshot.price_timestamp,
        valuations=valuations,
        composite=composite,
        is_demo=snapshot.is_demo,
        data_quality=quality,
        warnings=list(dict.fromkeys(warnings)),
        assumptions_used=assumptions,
        provider=getattr(snapshot, "provider", None),
        provider_label=getattr(snapshot, "provider_label", None),
        shares_basis=getattr(snapshot, "shares_basis", None),
        shares_reconciliation=getattr(snapshot, "shares_reconciliation", None),
        statement_basis=getattr(snapshot, "statement_basis", None),
        annual_fallback=getattr(snapshot, "annual_fallback", False),
        forecast_fiscal_year_end=getattr(snapshot, "forecast_fiscal_year_end", None),
        ntm_weights=getattr(snapshot, "ntm_weights", None),
        forecast_horizon_effective=getattr(assumptions, "forecast_horizon", "ntm"),
        growth_cap_effective=getattr(assumptions, "growth_cap", None),
        growth_floor_effective=getattr(assumptions, "growth_floor", None),
        financial_bridge=financial_bridge,
    )


# Keep syntax permissive enough to distinguish an unknown alphabetic ticker
# (404) from malformed input such as ``INVALID!`` (422). Provider support,
# rather than this client-side length hint, determines existence.
_TICKER_RE = re.compile(r"^[A-Z]{1,12}(?:[.-][A-Z0-9]{1,4})?$")


class FinancialDataService:
    """Provider -> raw category cache -> normalizer -> engines."""

    def __init__(
        self,
        provider: FinancialDataProvider,
        cache: Optional[CacheProtocol] = None,
        default_assumptions: Optional[ValuationAssumptions] = None,
        normalizer: Optional[Normalizer] = None,
        timeout: Optional[float] = None,
    ):
        self._provider = provider
        self._cache = cache if cache is not None else MemoryTTLCache()
        self._default_assumptions = default_assumptions or DEFAULT_ASSUMPTIONS
        is_demo_provider = getattr(provider, "is_demo", True)
        self._normalizer = normalizer or Normalizer(
            strict_profile=is_demo_provider,
            allow_all_equities=not is_demo_provider,
        )
        self._timeout = timeout if timeout is not None else getattr(provider, "timeout", 25.0)

    def _validate_ticker(self, ticker: str) -> str:
        value = ticker.strip().upper()
        if not _TICKER_RE.fullmatch(value):
            raise InvalidTickerError(f"Invalid ticker syntax: {ticker!r}")
        return value

    def _raw(self, category: str, ticker: str, fetch: Callable[[str], Any], budget: Optional[Any] = None) -> Any:
        active_budget = budget or current_request_budget.get()
        if active_budget is not None:
            active_budget.check(ticker, f"before checking cache for {category}")

        key = f"{category}:{ticker}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        if active_budget is not None:
            active_budget.check(ticker, f"before fetching category {category}")

        value = fetch(ticker)
        self._cache.set(key, value, CACHE_TTL_SECONDS.get(category, 86400))
        return value

    def get_snapshot(
        self,
        ticker: str,
        bypass_cache: bool = False,
        budget: Optional[Any] = None,
    ) -> CompanyFinancialSnapshot:
        active_budget = budget or current_request_budget.get() or _RequestBudget(self._timeout)
        token = current_request_budget.set(active_budget)
        try:
            active_budget.check(ticker, "start get_snapshot")
            normalized_ticker = self._validate_ticker(ticker)
            snapshot_key = f"snapshot:{normalized_ticker}"
            if not bypass_cache:
                cached = self._cache.get(snapshot_key)
                if cached is not None:
                    return cached
            if bypass_cache:
                self._cache.invalidate(snapshot_key)
                for category in CACHE_TTL_SECONDS:
                    self._cache.invalidate(f"{category}:{normalized_ticker}")

            # The service consumes exactly the seven documented public provider
            # methods under ONE unified incoming valuation deadline.
            quote = self._raw("quote", normalized_ticker, self._provider.get_quote, budget=active_budget)
            profile = self._raw("profile", normalized_ticker, self._provider.get_company_profile, budget=active_budget)
            balance = self._raw("balance_sheet", normalized_ticker, self._provider.get_balance_sheet, budget=active_budget)
            cash_flow = self._raw("cash_flow", normalized_ticker, self._provider.get_cash_flow, budget=active_budget)
            income = self._raw("income_statement", normalized_ticker, self._provider.get_income_statement, budget=active_budget)
            estimates = self._raw("estimates", normalized_ticker, self._provider.get_forward_estimates, budget=active_budget)
            multiples = self._raw("multiples", normalized_ticker, self._provider.get_historical_multiples, budget=active_budget)
            active_budget.check(normalized_ticker, "before normalizer")
            raw_snapshot = self._normalizer.normalize_provider_data(
                normalized_ticker, quote, profile, balance, cash_flow, income, estimates, multiples
            )
            normalized = self._normalizer.normalize(raw_snapshot)
            # Snapshot aggregation follows the quote category TTL; raw statement,
            # estimate and multiples entries retain their longer category TTLs.
            self._cache.set(snapshot_key, normalized, CACHE_TTL_SECONDS["quote"])
            return normalized
        finally:
            current_request_budget.reset(token)

    def compute_valuation(
        self,
        ticker: str,
        overrides: Optional[dict] = None,
        bypass_cache: bool = False,
        budget: Optional[Any] = None,
    ) -> ValuationResponse:
        """Backward-compatible alias; valuation orchestration lives in ValuationService."""
        return ValuationService(self, default_assumptions=self._default_assumptions).compute(
            ticker, overrides=overrides, bypass_cache=bypass_cache, budget=budget
        )


class ValuationService:
    """Pure calculation orchestrator over a FinancialDataService snapshot source."""

    def __init__(
        self,
        data_service: FinancialDataService,
        *,
        default_assumptions: Optional[ValuationAssumptions] = None,
    ):
        self._data_service = data_service
        self._default_assumptions = default_assumptions or data_service._default_assumptions

    def compute(
        self,
        ticker: str,
        overrides: Optional[dict] = None,
        bypass_cache: bool = False,
        budget: Optional[Any] = None,
    ) -> ValuationResponse:
        snapshot = self._data_service.get_snapshot(ticker, bypass_cache=bypass_cache, budget=budget)
        assumptions = apply_overrides(self._default_assumptions, overrides)
        # Multiple arbitration belongs at the normalized snapshot boundary so
        # the selected company/industry/system source reaches every engine,
        # composite result, API response, and Markdown export consistently.
        assumptions, multiple_warnings = resolve_multiple_assumptions(snapshot, assumptions)
        if multiple_warnings:
            snapshot = snapshot.model_copy(update={
                "warnings": list(dict.fromkeys([*snapshot.warnings, *multiple_warnings]))
            })
        valuations = run_all_engines(snapshot, assumptions)
        composite = run_composite(
            current_price=snapshot.current_price.value,
            pe_result=valuations["forward_pe"],
            ev_result=valuations["ev_ebitda"],
            fcf_result=valuations["fcf_yield"],
            dcf_result=valuations["dcf"],
            assumptions=assumptions,
        )
        proj = derive_request_projections(snapshot, assumptions)
        return assemble_response(snapshot, valuations, composite, assumptions, financial_bridge=proj.financial_bridge)

    # Familiar name for callers that previously invoked FinancialDataService.
    def compute_valuation(
        self,
        ticker: str,
        overrides: Optional[dict] = None,
        bypass_cache: bool = False,
        budget: Optional[Any] = None,
    ) -> ValuationResponse:
        return self.compute(ticker, overrides=overrides, bypass_cache=bypass_cache, budget=budget)
