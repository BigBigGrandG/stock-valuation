"""Service-independent acceptance regression tests.

Each section targets a specific backend-revisions.md requirement without
modifying implementation sources.  All tests are offline — no network calls,
no reliance on other test suites, no database state.

Sections
--------
1. Seven-public-method provider compatibility
2. Fresh quote + old balance/estimate dates and source/period metadata
3. Explicit zero confidence including estimated values
4. Explicit incompatible FCFE/FCFF types rejected
5. Bank/insurance/REIT/SPAC/ETF/non-US/loss/Financial Services rejection
6. Provider 429/503/404 vs invalid-financial-data 422 via actual API TestClient
7. Injected monotonic category TTL expiry
8. Model exception isolation
"""
from __future__ import annotations

import sys
import os
import time
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

import pytest
from pydantic import ValidationError

# Ensure backend root is importable.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import (
    CACHE_TTL_SECONDS,
    DEFAULT_ASSUMPTIONS,
    TTL_ESTIMATES_SECONDS,
    TTL_MULTIPLES_SECONDS,
    TTL_QUOTE_SECONDS,
    TTL_STATEMENTS_SECONDS,
)
from app.models.domain import (
    CompanyFinancialSnapshot,
    DataQuality,
    FCFType,
    FinancialMetric,
    SourceType,
    ValuationAssumptions,
)
from app.models.overrides import ValuationOverrideRequest
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
    ProviderRateLimitError,
    ProviderUnavailableError,
    QuoteData,
    TickerNotFoundError,
    UnsupportedCompanyError,
)
from app.services.valuation_service import (
    FinancialDataService,
    MemoryTTLCache,
    Normalizer,
    ValuationService,
    normalize_snapshot,
    run_all_engines,
)

# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------

FIXTURE_DATE = date(2025, 1, 15)
FIXTURE_TS = datetime(2025, 1, 15, 16, 0, 0)

OLD_BALANCE_DATE = date(2024, 6, 30)
OLD_ESTIMATE_DATE = date(2024, 9, 15)


def _fm(
    value: str,
    unit: str = "USD",
    period: str = "FY2024",
    source: str = "test-fixture",
    source_type: SourceType = SourceType.FIXTURE,
    as_of: date = FIXTURE_DATE,
    confidence: float = 0.5,
    is_estimated: bool = True,
    notes: str = "test",
) -> FinancialMetric:
    return FinancialMetric(
        value=Decimal(value),
        unit=unit,
        period=period,
        source=source,
        source_type=source_type,
        as_of=as_of,
        confidence=confidence,
        is_estimated=is_estimated,
        notes=notes,
    )


def _make_snapshot(
    *,
    ticker: str = "TEST",
    company_name: str = "Test Inc.",
    price: str = "100",
    shares: str = "1000000000",
    cash: str = "5000000000",
    debt: str = "10000000000",
    forward_eps_1y: str = "5.00",
    forward_ebitda_1y: str = "20000000000",
    forward_fcfe_1y: str = "15000000000",
    forward_fcff_1y: str = "13000000000",
    country: str = "US",
    security_type: str = "COMMON_STOCK",
    sector: str = "Technology",
    industry: str = "Semiconductors",
    is_profitable: bool = True,
    is_demo: bool = True,
    extra: dict[str, Any] | None = None,
) -> CompanyFinancialSnapshot:
    nd = Decimal(debt) - Decimal(cash)
    fields: dict[str, Any] = dict(
        ticker=ticker,
        company_name=company_name,
        currency="USD",
        current_price=_fm(price, period=str(FIXTURE_DATE)),
        price_timestamp=FIXTURE_TS,
        diluted_shares=_fm(shares, unit="shares"),
        cash=_fm(cash),
        total_debt=_fm(debt),
        net_debt=_fm(str(nd), source="derived", source_type=SourceType.DERIVED),
        revenue_ttm=_fm("30000000000"),
        ebitda_ttm=_fm("18000000000"),
        eps_ttm=_fm("4.00", unit="USD/share"),
        fcf_ttm=_fm("12000000000", notes="FCFE TTM"),
        forward_fcf_1y=_fm(forward_fcfe_1y, period="FY2025E", notes="FCFE"),
        forward_fcf_2y=_fm("17000000000", period="FY2026E", notes="FCFE"),
        fcff_ttm=_fm("11000000000", notes="FCFF TTM"),
        forward_fcff_1y=_fm(forward_fcff_1y, period="FY2025E", notes="FCFF"),
        forward_fcff_2y=_fm("15000000000", period="FY2026E", notes="FCFF"),
        forward_eps_1y=_fm(forward_eps_1y, unit="USD/share", period="FY2025E"),
        forward_eps_2y=_fm("6.00", unit="USD/share", period="FY2026E"),
        forward_ebitda_1y=_fm(forward_ebitda_1y, period="FY2025E"),
        forward_ebitda_2y=_fm("25000000000", period="FY2026E"),
        historical_forward_pe=_fm("20", unit="ratio", period="5Y median"),
        historical_ev_ebitda=_fm("22", unit="ratio", period="5Y median"),
        revenue_growth=_fm("0.15", unit="ratio", period="growth"),
        eps_growth=_fm("0.20", unit="ratio", period="growth"),
        fcf_growth=_fm("0.18", unit="ratio", period="growth"),
        fcff_growth=_fm("0.16", unit="ratio", period="growth"),
        country=country,
        security_type=security_type,
        sector=sector,
        industry=industry,
        is_profitable=is_profitable,
        data_quality=DataQuality.LOW,
        is_demo=is_demo,
        warnings=["TEST DATA"],
    )
    if extra:
        fields.update(extra)
    return CompanyFinancialSnapshot(**fields)


class StubProvider(FinancialDataProvider):
    """Minimal seven-method provider returning dictionaries."""

    def __init__(self, *, overrides: dict[str, Any] | None = None):
        self._overrides = overrides or {}

    def _quote(self) -> dict[str, Any]:
        return {
            "price": Decimal("100"),
            "currency": "USD",
            "timestamp": FIXTURE_TS,
            "as_of": FIXTURE_DATE,
            "source": "stub-fixture",
        }

    def _profile(self) -> dict[str, Any]:
        return {
            "name": "Stub Co.",
            "diluted_shares": Decimal("1000000000"),
            "currency": "USD",
            "country": "US",
            "security_type": "COMMON_STOCK",
            "sector": "Technology",
            "industry": "Software",
            "is_profitable": True,
            "as_of": FIXTURE_DATE,
            "source": "stub-fixture",
        }

    def _balance(self) -> dict[str, Any]:
        return {
            "cash": Decimal("5000000000"),
            "total_debt": Decimal("10000000000"),
            "period": "FY2024",
            "as_of": FIXTURE_DATE,
            "source": "stub-fixture",
        }

    def _cash_flow(self) -> dict[str, Any]:
        return {
            "fcfe_ttm": Decimal("12000000000"),
            "fcfe_definition": "FCFE equity cash flow",
            "fcff_ttm": Decimal("11000000000"),
            "fcff_definition": "FCFF unlevered cash flow",
            "forward_fcfe_1y": Decimal("15000000000"),
            "forward_fcfe_2y": Decimal("17000000000"),
            "forward_fcff_1y": Decimal("13000000000"),
            "forward_fcff_2y": Decimal("15000000000"),
            "period": "TTM",
            "as_of": FIXTURE_DATE,
            "source": "stub-fixture",
        }

    def _income(self) -> dict[str, Any]:
        return {
            "revenue_ttm": Decimal("30000000000"),
            "ebitda_ttm": Decimal("18000000000"),
            "eps_ttm": Decimal("4.00"),
            "period": "TTM",
            "as_of": FIXTURE_DATE,
            "source": "stub-fixture",
        }

    def _estimates(self) -> dict[str, Any]:
        return {
            "forward_eps_1y": Decimal("5.00"),
            "forward_eps_2y": Decimal("6.00"),
            "forward_ebitda_1y": Decimal("20000000000"),
            "forward_ebitda_2y": Decimal("25000000000"),
            "forward_fcfe_1y": Decimal("15000000000"),
            "forward_fcfe_2y": Decimal("17000000000"),
            "forward_fcff_1y": Decimal("13000000000"),
            "forward_fcff_2y": Decimal("15000000000"),
            "period_1y": "FY2025E",
            "period_2y": "FY2026E",
            "as_of": FIXTURE_DATE,
            "source": "stub-fixture",
        }

    def _multiples(self) -> dict[str, Any]:
        return {
            "historical_forward_pe": Decimal("20"),
            "historical_ev_ebitda": Decimal("22"),
            "period": "5Y median",
            "as_of": FIXTURE_DATE,
            "source": "stub-fixture",
        }

    def _apply(self, base: dict[str, Any], category: str) -> dict[str, Any]:
        out = dict(base)
        for key, val in self._overrides.items():
            if key.startswith(category + "."):
                out[key.split(".", 1)[1]] = val
        return out

    def get_quote(self, ticker: str) -> QuoteData:
        return self._apply(self._quote(), "quote")

    def get_company_profile(self, ticker: str) -> CompanyProfileData:
        return self._apply(self._profile(), "profile")

    def get_balance_sheet(self, ticker: str) -> BalanceSheetData:
        return self._apply(self._balance(), "balance")

    def get_cash_flow(self, ticker: str) -> CashFlowData:
        return self._apply(self._cash_flow(), "cashflow")

    def get_income_statement(self, ticker: str) -> IncomeStatementData:
        return self._apply(self._income(), "income")

    def get_forward_estimates(self, ticker: str) -> ForwardEstimatesData:
        return self._apply(self._estimates(), "estimates")

    def get_historical_multiples(self, ticker: str) -> HistoricalMultiplesData:
        return self._apply(self._multiples(), "multiples")


class FailingProvider(FinancialDataProvider):
    """Provider that raises a configurable error on every method."""

    def __init__(self, error: Exception):
        self._error = error

    def _raise(self) -> Any:
        raise self._error

    def get_quote(self, ticker: str) -> QuoteData:
        return self._raise()

    def get_company_profile(self, ticker: str) -> CompanyProfileData:
        return self._raise()

    def get_balance_sheet(self, ticker: str) -> BalanceSheetData:
        return self._raise()

    def get_cash_flow(self, ticker: str) -> CashFlowData:
        return self._raise()

    def get_income_statement(self, ticker: str) -> IncomeStatementData:
        return self._raise()

    def get_forward_estimates(self, ticker: str) -> ForwardEstimatesData:
        return self._raise()

    def get_historical_multiples(self, ticker: str) -> HistoricalMultiplesData:
        return self._raise()


# ===================================================================
# 1. Seven-public-method provider compatibility
# ===================================================================

class TestSevenMethodProviderCompatibility:
    """The abstract provider defines exactly 7 methods; stub satisfies them."""

    def test_abstract_methods_are_seven(self):
        abstracts = [
            name
            for name in dir(FinancialDataProvider)
            if getattr(getattr(FinancialDataProvider, name, None), "__isabstractmethod__", False)
        ]
        assert len(abstracts) == 7, f"Expected 7 abstract methods, found {len(abstracts)}: {abstracts}"
        expected = {
            "get_quote", "get_company_profile", "get_balance_sheet",
            "get_cash_flow", "get_income_statement", "get_forward_estimates",
            "get_historical_multiples",
        }
        assert set(abstracts) == expected

    def test_stub_provider_satisfies_interface(self):
        provider = StubProvider()
        assert isinstance(provider, FinancialDataProvider)

    def test_stub_get_snapshot_assembles(self):
        provider = StubProvider()
        snapshot = provider.get_snapshot("TEST")
        assert isinstance(snapshot, CompanyFinancialSnapshot)
        assert snapshot.ticker == "TEST"
        assert snapshot.current_price.value == Decimal("100")

    def test_normalizer_accepts_stub_data(self):
        provider = StubProvider()
        normalizer = Normalizer(strict_profile=True)
        q = provider.get_quote("TEST")
        p = provider.get_company_profile("TEST")
        b = provider.get_balance_sheet("TEST")
        cf = provider.get_cash_flow("TEST")
        inc = provider.get_income_statement("TEST")
        est = provider.get_forward_estimates("TEST")
        mult = provider.get_historical_multiples("TEST")
        snapshot = normalizer.normalize_provider_data("TEST", q, p, b, cf, inc, est, mult)
        assert isinstance(snapshot, CompanyFinancialSnapshot)

    def test_data_service_uses_all_seven_methods(self):
        """FinancialDataService calls all 7 provider methods for a snapshot."""
        called: list[str] = []

        class TrackerProvider(StubProvider):
            def get_quote(self, ticker):
                called.append("get_quote")
                return super().get_quote(ticker)

            def get_company_profile(self, ticker):
                called.append("get_company_profile")
                return super().get_company_profile(ticker)

            def get_balance_sheet(self, ticker):
                called.append("get_balance_sheet")
                return super().get_balance_sheet(ticker)

            def get_cash_flow(self, ticker):
                called.append("get_cash_flow")
                return super().get_cash_flow(ticker)

            def get_income_statement(self, ticker):
                called.append("get_income_statement")
                return super().get_income_statement(ticker)

            def get_forward_estimates(self, ticker):
                called.append("get_forward_estimates")
                return super().get_forward_estimates(ticker)

            def get_historical_multiples(self, ticker):
                called.append("get_historical_multiples")
                return super().get_historical_multiples(ticker)

        svc = FinancialDataService(
            provider=TrackerProvider(),
            cache=MemoryTTLCache(),
            default_assumptions=DEFAULT_ASSUMPTIONS,
        )
        svc.get_snapshot("TEST")
        assert sorted(called) == sorted([
            "get_quote", "get_company_profile", "get_balance_sheet",
            "get_cash_flow", "get_income_statement", "get_forward_estimates",
            "get_historical_multiples",
        ])


# ===================================================================
# 2. Fresh quote + old balance/estimate dates and source/period metadata
# ===================================================================

class TestMetadataProvenance:
    """Verify that different as_of dates and source/period from each category
    are preserved through to the normalized snapshot."""

    def _build_mixed_date_provider(self):

        class MixedDateProvider(StubProvider):
            def get_quote(self, ticker):
                d = super().get_quote(ticker)
                d["as_of"] = date(2025, 6, 1)
                d["timestamp"] = datetime(2025, 6, 1, 16, 0, 0)
                d["source"] = "quote-source"
                return d

            def get_balance_sheet(self, ticker):
                d = super().get_balance_sheet(ticker)
                d["as_of"] = OLD_BALANCE_DATE
                d["period"] = "FY2024-Q2"
                d["source"] = "balance-source"
                return d

            def get_forward_estimates(self, ticker):
                d = super().get_forward_estimates(ticker)
                d["as_of"] = OLD_ESTIMATE_DATE
                d["source"] = "estimate-source"
                return d

            def get_income_statement(self, ticker):
                d = super().get_income_statement(ticker)
                d["as_of"] = date(2024, 12, 31)
                d["source"] = "income-source"
                return d

            def get_historical_multiples(self, ticker):
                d = super().get_historical_multiples(ticker)
                d["as_of"] = date(2024, 11, 1)
                d["source"] = "multiples-source"
                return d

        return MixedDateProvider()

    def test_quote_date_preserved(self):
        provider = self._build_mixed_date_provider()
        svc = FinancialDataService(
            provider=provider, cache=MemoryTTLCache(), default_assumptions=DEFAULT_ASSUMPTIONS,
        )
        snap = svc.get_snapshot("TEST")
        assert snap.current_price.as_of == date(2025, 6, 1)

    def test_balance_date_older_than_quote(self):
        provider = self._build_mixed_date_provider()
        svc = FinancialDataService(
            provider=provider, cache=MemoryTTLCache(), default_assumptions=DEFAULT_ASSUMPTIONS,
        )
        snap = svc.get_snapshot("TEST")
        assert snap.cash.as_of == OLD_BALANCE_DATE
        assert snap.total_debt.as_of == OLD_BALANCE_DATE

    def test_estimate_date_older_than_quote(self):
        provider = self._build_mixed_date_provider()
        svc = FinancialDataService(
            provider=provider, cache=MemoryTTLCache(), default_assumptions=DEFAULT_ASSUMPTIONS,
        )
        snap = svc.get_snapshot("TEST")
        assert snap.forward_eps_1y.as_of == OLD_ESTIMATE_DATE

    def test_source_string_preserved_on_metrics(self):
        provider = self._build_mixed_date_provider()
        svc = FinancialDataService(
            provider=provider, cache=MemoryTTLCache(), default_assumptions=DEFAULT_ASSUMPTIONS,
        )
        snap = svc.get_snapshot("TEST")
        assert "quote-source" in snap.current_price.source
        assert "balance-source" in snap.cash.source

    def test_balance_period_preserved(self):
        provider = self._build_mixed_date_provider()
        svc = FinancialDataService(
            provider=provider, cache=MemoryTTLCache(), default_assumptions=DEFAULT_ASSUMPTIONS,
        )
        snap = svc.get_snapshot("TEST")
        # The balance sheet period should propagate to cash/debt metrics.
        assert "FY2024" in snap.cash.period

    def test_estimate_period_preserved(self):
        provider = self._build_mixed_date_provider()
        svc = FinancialDataService(
            provider=provider, cache=MemoryTTLCache(), default_assumptions=DEFAULT_ASSUMPTIONS,
        )
        snap = svc.get_snapshot("TEST")
        assert "FY2025E" in snap.forward_eps_1y.period


# ===================================================================
# 3. Explicit zero confidence including estimated values
# ===================================================================

class TestZeroConfidenceAndEstimated:
    """FinancialMetric must allow confidence=0 alongside is_estimated=True."""

    def test_zero_confidence_metric_accepted(self):
        m = FinancialMetric(
            value=Decimal("10"),
            unit="USD",
            period="TTM",
            source="test",
            source_type=SourceType.FIXTURE,
            as_of=FIXTURE_DATE,
            confidence=0.0,
            is_estimated=True,
        )
        assert m.confidence == 0.0
        assert m.is_estimated is True

    def test_zero_confidence_in_snapshot(self):
        snap = _make_snapshot(
            extra={
                "forward_eps_1y": _fm(
                    "5.00", unit="USD/share", period="FY2025E",
                    confidence=0.0, is_estimated=True,
                ),
            }
        )
        assert snap.forward_eps_1y.confidence == 0.0
        assert snap.forward_eps_1y.is_estimated is True

    def test_fixture_metrics_are_estimated(self):
        """Fixture source type always sets is_estimated=True."""
        snap = _make_snapshot()
        for field_name in ("current_price", "cash", "total_debt", "forward_eps_1y"):
            m = getattr(snap, field_name)
            assert m.is_estimated is True, f"{field_name}.is_estimated should be True"

    def test_confidence_rejects_above_one(self):
        with pytest.raises(ValidationError):
            FinancialMetric(
                value=Decimal("10"),
                unit="USD",
                period="TTM",
                source="test",
                source_type=SourceType.FIXTURE,
                as_of=FIXTURE_DATE,
                confidence=1.5,
                is_estimated=False,
            )

    def test_confidence_rejects_negative(self):
        with pytest.raises(ValidationError):
            FinancialMetric(
                value=Decimal("10"),
                unit="USD",
                period="TTM",
                source="test",
                source_type=SourceType.FIXTURE,
                as_of=FIXTURE_DATE,
                confidence=-0.1,
                is_estimated=False,
            )


# ===================================================================
# 4. Explicit incompatible FCFE/FCFF types rejected
# ===================================================================

class TestFCFEFCFFTypeRejection:
    """Normalizer rejects cross-wired FCFE/FCFF type labels."""

    def test_fcfe_typed_as_fcff_rejected(self):
        """Cash flow with FCFE value labelled FCFF must be rejected."""

        class BadTypeFCFE(StubProvider):
            def get_cash_flow(self, ticker):
                d = super().get_cash_flow(ticker)
                d["fcfe_type"] = "FCFF"
                return d

        provider = BadTypeFCFE()
        svc = FinancialDataService(
            provider=provider, cache=MemoryTTLCache(), default_assumptions=DEFAULT_ASSUMPTIONS,
        )
        with pytest.raises(FinancialDataValidationError):
            svc.get_snapshot("TEST")

    def test_fcff_typed_as_fcfe_rejected(self):

        class BadTypeFCFF(StubProvider):
            def get_cash_flow(self, ticker):
                d = super().get_cash_flow(ticker)
                d["fcff_type"] = "FCFE"
                return d

        provider = BadTypeFCFF()
        svc = FinancialDataService(
            provider=provider, cache=MemoryTTLCache(), default_assumptions=DEFAULT_ASSUMPTIONS,
        )
        with pytest.raises(FinancialDataValidationError):
            svc.get_snapshot("TEST")

    def test_fcfe_definition_mentioning_only_fcff_rejected(self):
        """A definition on the FCFE path that says 'Free Cash Flow to Firm'
        without mentioning FCFE is incompatible and must be rejected.
        Spec requires the normalizer to catch natural-language cross-wiring,
        not only acronym substrings."""

        class BadDefFCFE(StubProvider):
            def get_cash_flow(self, ticker):
                d = super().get_cash_flow(ticker)
                d["fcfe_definition"] = "Free Cash Flow to Firm unlevered only"
                return d

        provider = BadDefFCFE()
        svc = FinancialDataService(
            provider=provider, cache=MemoryTTLCache(), default_assumptions=DEFAULT_ASSUMPTIONS,
        )
        with pytest.raises(FinancialDataValidationError):
            svc.get_snapshot("TEST")

    def test_fcfe_definition_with_fcff_acronym_rejected(self):
        """A definition on the FCFE path containing literal 'FCFF' is rejected."""

        class BadDefFCFEAcronym(StubProvider):
            def get_cash_flow(self, ticker):
                d = super().get_cash_flow(ticker)
                d["fcfe_definition"] = "FCFF unlevered cash flow only"
                return d

        provider = BadDefFCFEAcronym()
        svc = FinancialDataService(
            provider=provider, cache=MemoryTTLCache(), default_assumptions=DEFAULT_ASSUMPTIONS,
        )
        with pytest.raises(FinancialDataValidationError):
            svc.get_snapshot("TEST")

    def test_estimates_mixed_fcff_types_rejected(self):
        """Estimates forward_fcff_1y_type=FCFF with forward_fcff_2y_type=FCFE is rejected."""

        class MixedFCFFEstimates(StubProvider):
            def get_forward_estimates(self, ticker):
                d = super().get_forward_estimates(ticker)
                d["forward_fcff_1y_type"] = "FCFF"
                d["forward_fcff_2y_type"] = "FCFE"
                return d

        provider = MixedFCFFEstimates()
        svc = FinancialDataService(
            provider=provider, cache=MemoryTTLCache(), default_assumptions=DEFAULT_ASSUMPTIONS,
        )
        with pytest.raises(FinancialDataValidationError):
            svc.get_snapshot("TEST")

    def test_cash_flow_fallback_fcff_with_fcfe_type_rejected(self):
        """forward_fcff_1y supplied from cash_flow fallback with type FCFE is rejected."""

        class FallbackFCFE(StubProvider):
            def get_forward_estimates(self, ticker):
                d = super().get_forward_estimates(ticker)
                d.pop("forward_fcff_1y", None)
                return d

            def get_cash_flow(self, ticker):
                d = super().get_cash_flow(ticker)
                d["forward_fcff_1y"] = Decimal("13000000000")
                d["forward_fcff_1y_type"] = "FCFE"
                return d

        provider = FallbackFCFE()
        svc = FinancialDataService(
            provider=provider, cache=MemoryTTLCache(), default_assumptions=DEFAULT_ASSUMPTIONS,
        )
        with pytest.raises(FinancialDataValidationError):
            svc.get_snapshot("TEST")

    def test_estimates_mixed_fcfe_types_rejected(self):
        """Estimates forward_fcfe_1y_type=FCFE with forward_fcfe_2y_type=FCFF is rejected."""

        class MixedFCFEEstimates(StubProvider):
            def get_forward_estimates(self, ticker):
                d = super().get_forward_estimates(ticker)
                d["forward_fcfe_1y_type"] = "FCFE"
                d["forward_fcfe_2y_type"] = "FCFF"
                return d

        provider = MixedFCFEEstimates()
        svc = FinancialDataService(
            provider=provider, cache=MemoryTTLCache(), default_assumptions=DEFAULT_ASSUMPTIONS,
        )
        with pytest.raises(FinancialDataValidationError):
            svc.get_snapshot("TEST")

    def test_cash_flow_fallback_fcfe_with_fcff_type_rejected(self):
        """forward_fcfe_1y supplied from cash_flow fallback with type FCFF is rejected."""

        class FallbackFCFF(StubProvider):
            def get_forward_estimates(self, ticker):
                d = super().get_forward_estimates(ticker)
                d.pop("forward_fcfe_1y", None)
                return d

            def get_cash_flow(self, ticker):
                d = super().get_cash_flow(ticker)
                d["forward_fcfe_1y"] = Decimal("15000000000")
                d["forward_fcfe_1y_type"] = "FCFF"
                return d

        provider = FallbackFCFF()
        svc = FinancialDataService(
            provider=provider, cache=MemoryTTLCache(), default_assumptions=DEFAULT_ASSUMPTIONS,
        )
        with pytest.raises(FinancialDataValidationError):
            svc.get_snapshot("TEST")

    def test_fcff_definition_mentioning_only_fcfe_rejected(self):
        """A definition on the FCFF path mentioning only Free Cash Flow to Equity is rejected."""

        class BadDefFCFF(StubProvider):
            def get_cash_flow(self, ticker):
                d = super().get_cash_flow(ticker)
                d["fcff_definition"] = "Free Cash Flow to Equity after debt service"
                return d

        provider = BadDefFCFF()
        svc = FinancialDataService(
            provider=provider, cache=MemoryTTLCache(), default_assumptions=DEFAULT_ASSUMPTIONS,
        )
        with pytest.raises(FinancialDataValidationError):
            svc.get_snapshot("TEST")

    def test_fcf_type_enum_values(self):
        assert FCFType.FCFE.value == "FCFE"
        assert FCFType.FCFF.value == "FCFF"

    def test_snapshot_has_separate_fcfe_and_fcff(self):
        """Snapshot must carry both FCFE (fcf_ttm) and FCFF (fcff_ttm)."""
        snap = _make_snapshot()
        assert snap.fcf_ttm is not None, "fcf_ttm (FCFE) missing"
        assert snap.fcff_ttm is not None, "fcff_ttm (FCFF) missing"
        assert snap.fcf_ttm.value != snap.fcff_ttm.value, "FCFE and FCFF should differ"


# ===================================================================
# 5. Unsupported company type rejection
# ===================================================================

class TestUnsupportedCompanyRejection:
    """Support guard in normalizer rejects forbidden profiles."""

    @pytest.mark.parametrize(
        "sector,industry,security_type,reason_fragment",
        [
            ("Financials", "Banks", "COMMON_STOCK", "financial"),
            ("Financial Services", "Banking", "COMMON_STOCK", "financial"),
            ("Financials", "Insurance", "COMMON_STOCK", "financial"),
            ("Real Estate", "REIT", "REIT", "reit"),
            ("Blank Check", "SPAC", "SPAC", "spac"),
            ("Index", "ETF", "ETF", "etf"),
        ],
    )
    def test_normalize_rejects_sector(self, sector, industry, security_type, reason_fragment):
        snap = _make_snapshot(sector=sector, industry=industry, security_type=security_type)
        with pytest.raises(UnsupportedCompanyError):
            normalize_snapshot(snap, strict_profile=True)

    def test_non_us_rejected(self):
        snap = _make_snapshot(country="CN")
        with pytest.raises(UnsupportedCompanyError) as exc_info:
            normalize_snapshot(snap, strict_profile=True)
        assert "non_us" in str(exc_info.value).lower() or "non_us" in getattr(exc_info.value, "reason", "")

    def test_unprofitable_rejected(self):
        snap = _make_snapshot(is_profitable=False)
        with pytest.raises(UnsupportedCompanyError):
            normalize_snapshot(snap, strict_profile=True)

    def test_bank_via_provider(self):
        class BankProvider(StubProvider):
            def get_company_profile(self, ticker):
                d = super().get_company_profile(ticker)
                d["sector"] = "Financials"
                d["industry"] = "Banks"
                return d

        svc = FinancialDataService(
            provider=BankProvider(), cache=MemoryTTLCache(), default_assumptions=DEFAULT_ASSUMPTIONS,
        )
        with pytest.raises(UnsupportedCompanyError):
            svc.get_snapshot("TEST")

    def test_insurance_via_provider(self):
        class InsuranceProvider(StubProvider):
            def get_company_profile(self, ticker):
                d = super().get_company_profile(ticker)
                d["sector"] = "Insurance"
                d["industry"] = "Life Insurance"
                return d

        svc = FinancialDataService(
            provider=InsuranceProvider(), cache=MemoryTTLCache(), default_assumptions=DEFAULT_ASSUMPTIONS,
        )
        with pytest.raises(UnsupportedCompanyError):
            svc.get_snapshot("TEST")

    def test_reit_via_provider(self):
        class REITProvider(StubProvider):
            def get_company_profile(self, ticker):
                d = super().get_company_profile(ticker)
                d["sector"] = "Real Estate"
                d["security_type"] = "REIT"
                d["industry"] = "Equity REIT"
                return d

        svc = FinancialDataService(
            provider=REITProvider(), cache=MemoryTTLCache(), default_assumptions=DEFAULT_ASSUMPTIONS,
        )
        with pytest.raises(UnsupportedCompanyError):
            svc.get_snapshot("TEST")

    def test_etf_via_provider(self):
        class ETFProvider(StubProvider):
            def get_company_profile(self, ticker):
                d = super().get_company_profile(ticker)
                d["security_type"] = "ETF"
                d["sector"] = "ETF"
                return d

        svc = FinancialDataService(
            provider=ETFProvider(), cache=MemoryTTLCache(), default_assumptions=DEFAULT_ASSUMPTIONS,
        )
        with pytest.raises(UnsupportedCompanyError):
            svc.get_snapshot("TEST")

    def test_spac_via_provider(self):
        class SPACProvider(StubProvider):
            def get_company_profile(self, ticker):
                d = super().get_company_profile(ticker)
                d["security_type"] = "SPAC"
                d["sector"] = "Blank Check / SPAC"
                return d

        svc = FinancialDataService(
            provider=SPACProvider(), cache=MemoryTTLCache(), default_assumptions=DEFAULT_ASSUMPTIONS,
        )
        with pytest.raises(UnsupportedCompanyError):
            svc.get_snapshot("TEST")

    def test_non_us_via_provider(self):
        class NonUSProvider(StubProvider):
            def get_company_profile(self, ticker):
                d = super().get_company_profile(ticker)
                d["country"] = "GB"
                return d

        svc = FinancialDataService(
            provider=NonUSProvider(), cache=MemoryTTLCache(), default_assumptions=DEFAULT_ASSUMPTIONS,
        )
        with pytest.raises(UnsupportedCompanyError):
            svc.get_snapshot("TEST")

    def test_loss_via_provider(self):
        class LossProvider(StubProvider):
            def get_company_profile(self, ticker):
                d = super().get_company_profile(ticker)
                d["is_profitable"] = False
                return d

        svc = FinancialDataService(
            provider=LossProvider(), cache=MemoryTTLCache(), default_assumptions=DEFAULT_ASSUMPTIONS,
        )
        with pytest.raises(UnsupportedCompanyError):
            svc.get_snapshot("TEST")

    def test_financial_services_sector_rejected(self):
        """'Financial Services' sector must be explicitly caught."""
        class FinSvcProvider(StubProvider):
            def get_company_profile(self, ticker):
                d = super().get_company_profile(ticker)
                d["sector"] = "Financial Services"
                d["industry"] = "Capital Markets"
                return d

        svc = FinancialDataService(
            provider=FinSvcProvider(), cache=MemoryTTLCache(), default_assumptions=DEFAULT_ASSUMPTIONS,
        )
        with pytest.raises(UnsupportedCompanyError):
            svc.get_snapshot("TEST")


# ===================================================================
# 6. Provider error → HTTP status via actual API TestClient
# ===================================================================

class TestHTTPErrorMapping:
    """FastAPI TestClient tests: provider errors produce correct HTTP codes."""

    @pytest.fixture(autouse=True)
    def _setup_client(self):
        from fastapi.testclient import TestClient
        from app.main import app
        self.client = TestClient(app)

    # -- AVGO must work (200) --
    def test_avgo_get_valuation_200(self):
        r = self.client.get("/api/v1/valuation/AVGO")
        assert r.status_code == 200, f"AVGO GET failed: {r.status_code} {r.text[:300]}"

    def test_avgo_snapshot_200(self):
        r = self.client.get("/api/v1/company/AVGO/snapshot")
        assert r.status_code == 200

    # -- Unknown ticker → 404 --
    def test_unknown_ticker_404(self):
        r = self.client.get("/api/v1/valuation/ZZZZZ")
        assert r.status_code == 404, f"Expected 404 for unknown ticker, got {r.status_code}"

    # -- Invalid ticker syntax → 422 --
    def test_invalid_ticker_422(self):
        r = self.client.get("/api/v1/valuation/INVALID!")
        assert r.status_code == 422

    # -- POST nested override contract --
    def test_post_nested_override_accepted(self):
        body = {
            "forward_pe": {"base": 18},
            "fcf_yield": {"base": 0.05},
            "dcf": {"wacc": 0.095, "terminal_growth": 0.035},
        }
        r = self.client.post("/api/v1/valuation/AVGO", json=body)
        assert r.status_code == 200, f"POST override failed: {r.status_code} {r.text[:300]}"

    def test_post_unknown_fields_rejected(self):
        body = {"unknown_field": 42}
        r = self.client.post("/api/v1/valuation/AVGO", json=body)
        assert r.status_code == 422

    def test_post_wacc_lte_terminal_growth_rejected(self):
        body = {"dcf": {"wacc": 0.03, "terminal_growth": 0.04}}
        r = self.client.post("/api/v1/valuation/AVGO", json=body)
        assert r.status_code == 422

    # -- Provider rate limit → 429 via actual API request --
    def test_rate_limit_maps_to_429_via_api(self, monkeypatch):
        import app.main as main_mod
        failing_svc = FinancialDataService(
            provider=FailingProvider(ProviderRateLimitError("rate limited")),
            cache=MemoryTTLCache(),
            default_assumptions=DEFAULT_ASSUMPTIONS,
        )
        monkeypatch.setattr(main_mod, "_data_service", failing_svc)
        monkeypatch.setattr(main_mod, "_valuation_service", ValuationService(failing_svc, default_assumptions=DEFAULT_ASSUMPTIONS))
        r = self.client.get("/api/v1/valuation/AVGO")
        assert r.status_code == 429

    # -- Provider unavailable → 503 via actual API request --
    def test_unavailable_maps_to_503_via_api(self, monkeypatch):
        import app.main as main_mod
        failing_svc = FinancialDataService(
            provider=FailingProvider(ProviderUnavailableError("upstream down")),
            cache=MemoryTTLCache(),
            default_assumptions=DEFAULT_ASSUMPTIONS,
        )
        monkeypatch.setattr(main_mod, "_data_service", failing_svc)
        monkeypatch.setattr(main_mod, "_valuation_service", ValuationService(failing_svc, default_assumptions=DEFAULT_ASSUMPTIONS))
        r = self.client.get("/api/v1/valuation/AVGO")
        assert r.status_code == 503

    # -- Ticker not found → 404 via actual API request --
    def test_not_found_maps_to_404_via_api(self, monkeypatch):
        import app.main as main_mod
        failing_svc = FinancialDataService(
            provider=FailingProvider(TickerNotFoundError("ticker missing")),
            cache=MemoryTTLCache(),
            default_assumptions=DEFAULT_ASSUMPTIONS,
        )
        monkeypatch.setattr(main_mod, "_data_service", failing_svc)
        monkeypatch.setattr(main_mod, "_valuation_service", ValuationService(failing_svc, default_assumptions=DEFAULT_ASSUMPTIONS))
        r = self.client.get("/api/v1/company/AVGO/snapshot")
        assert r.status_code == 404

    # -- Financial data validation → 422 via actual API request --
    def test_financial_data_validation_maps_to_422_via_api(self, monkeypatch):
        import app.main as main_mod
        failing_svc = FinancialDataService(
            provider=FailingProvider(FinancialDataValidationError("corrupt data")),
            cache=MemoryTTLCache(),
            default_assumptions=DEFAULT_ASSUMPTIONS,
        )
        monkeypatch.setattr(main_mod, "_data_service", failing_svc)
        monkeypatch.setattr(main_mod, "_valuation_service", ValuationService(failing_svc, default_assumptions=DEFAULT_ASSUMPTIONS))
        r = self.client.get("/api/v1/valuation/AVGO")
        assert r.status_code == 422
        assert "financial_data_validation" in r.text

    # -- Invalid ticker → 422 via actual API request --
    def test_invalid_ticker_maps_to_422_via_api(self, monkeypatch):
        import app.main as main_mod
        failing_svc = FinancialDataService(
            provider=FailingProvider(InvalidTickerError("malformed ticker")),
            cache=MemoryTTLCache(),
            default_assumptions=DEFAULT_ASSUMPTIONS,
        )
        monkeypatch.setattr(main_mod, "_data_service", failing_svc)
        monkeypatch.setattr(main_mod, "_valuation_service", ValuationService(failing_svc, default_assumptions=DEFAULT_ASSUMPTIONS))
        r = self.client.get("/api/v1/valuation/AVGO")
        assert r.status_code == 422
        assert "invalid_ticker" in r.text

    # -- Health endpoint --
    def test_health_endpoint(self):
        r = self.client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"

    # -- Reset endpoint --
    def test_reset_endpoint_200(self):
        r = self.client.get("/api/v1/valuation/AVGO/reset")
        assert r.status_code == 200


# ===================================================================
# 7. Injected monotonic category TTL expiry
# ===================================================================

class TestMonotonicCategoryTTL:
    """MemoryTTLCache with injectable clock for category TTL tests."""

    def test_config_ttl_values(self):
        assert TTL_QUOTE_SECONDS == 120
        assert TTL_STATEMENTS_SECONDS == 86400
        assert TTL_ESTIMATES_SECONDS == 43200
        assert TTL_MULTIPLES_SECONDS == 86400

    def test_cache_miss_after_ttl(self):
        t = [0.0]
        cache = MemoryTTLCache(clock=lambda: t[0])
        cache.set("k", "v", 60)
        assert cache.get("k") == "v"
        t[0] = 60.0  # exactly at expiry
        assert cache.get("k") is None

    def test_cache_hit_before_ttl(self):
        t = [0.0]
        cache = MemoryTTLCache(clock=lambda: t[0])
        cache.set("k", "v", 60)
        t[0] = 59.9
        assert cache.get("k") == "v"

    def test_quote_ttl_120_expires(self):
        """Quote category (120s) expires while statements (86400s) remain."""
        t = [0.0]
        cache = MemoryTTLCache(clock=lambda: t[0])
        provider = StubProvider()
        call_count = {"quote": 0}

        class CountingProvider(StubProvider):
            def get_quote(self, ticker):
                call_count["quote"] += 1
                return super().get_quote(ticker)

        svc = FinancialDataService(
            provider=CountingProvider(),
            cache=cache,
            default_assumptions=DEFAULT_ASSUMPTIONS,
        )
        svc.get_snapshot("TEST")
        first_count = call_count["quote"]
        # Advance past quote TTL (120s) but not statements (86400s).
        t[0] = 130.0
        # Must invalidate the snapshot cache for the service to re-fetch.
        cache.invalidate("snapshot:TEST")
        svc.get_snapshot("TEST")
        assert call_count["quote"] > first_count, "Quote should be re-fetched after 120s TTL"

    def test_statements_ttl_86400_survives_short_advance(self):
        t = [0.0]
        cache = MemoryTTLCache(clock=lambda: t[0])
        call_count = {"balance": 0}

        class CountingProvider(StubProvider):
            def get_balance_sheet(self, ticker):
                call_count["balance"] += 1
                return super().get_balance_sheet(ticker)

        svc = FinancialDataService(
            provider=CountingProvider(),
            cache=cache,
            default_assumptions=DEFAULT_ASSUMPTIONS,
        )
        svc.get_snapshot("TEST")
        first_count = call_count["balance"]
        # Advance 130s — beyond quote TTL but well within statements TTL.
        t[0] = 130.0
        cache.invalidate("snapshot:TEST")
        svc.get_snapshot("TEST")
        assert call_count["balance"] == first_count, "Balance should still be cached at 130s"

    def test_estimates_ttl_43200(self):
        t = [0.0]
        cache = MemoryTTLCache(clock=lambda: t[0])
        call_count = {"est": 0}

        class CountingProvider(StubProvider):
            def get_forward_estimates(self, ticker):
                call_count["est"] += 1
                return super().get_forward_estimates(ticker)

        svc = FinancialDataService(
            provider=CountingProvider(),
            cache=cache,
            default_assumptions=DEFAULT_ASSUMPTIONS,
        )
        svc.get_snapshot("TEST")
        first_count = call_count["est"]
        # Advance past estimates TTL.
        t[0] = 43201.0
        cache.invalidate("snapshot:TEST")
        svc.get_snapshot("TEST")
        assert call_count["est"] > first_count, "Estimates should be re-fetched after 43200s"

    def test_multiples_ttl_86400(self):
        t = [0.0]
        cache = MemoryTTLCache(clock=lambda: t[0])
        call_count = {"mult": 0}

        class CountingProvider(StubProvider):
            def get_historical_multiples(self, ticker):
                call_count["mult"] += 1
                return super().get_historical_multiples(ticker)

        svc = FinancialDataService(
            provider=CountingProvider(),
            cache=cache,
            default_assumptions=DEFAULT_ASSUMPTIONS,
        )
        svc.get_snapshot("TEST")
        first = call_count["mult"]
        # Advance past multiples TTL.
        t[0] = 86401.0
        cache.invalidate("snapshot:TEST")
        svc.get_snapshot("TEST")
        assert call_count["mult"] > first

    def test_cache_invalidate_and_clear(self):
        cache = MemoryTTLCache()
        cache.set("a", 1, 9999)
        cache.set("b", 2, 9999)
        cache.invalidate("a")
        assert cache.get("a") is None
        assert cache.get("b") == 2
        cache.clear()
        assert cache.get("b") is None


# ===================================================================
# 8. Model exception isolation
# ===================================================================

class TestModelExceptionIsolation:
    """One failing engine must not prevent others from producing results."""

    def test_run_all_engines_isolates_failures(self):
        """Simulate a snapshot where DCF would fail but others succeed."""
        # Build a snapshot missing FCFF data so DCF fails.
        snap = _make_snapshot(extra={"fcff_ttm": None, "forward_fcff_1y": None, "forward_fcff_2y": None})
        results = run_all_engines(snap, DEFAULT_ASSUMPTIONS)
        assert "forward_pe" in results
        assert "ev_ebitda" in results
        assert "fcf_yield" in results
        assert "dcf" in results
        # At least PE should succeed (it only needs forward EPS).
        assert results["forward_pe"].available is True
        # DCF may be unavailable due to missing FCFF.
        # The key invariant: other models are NOT suppressed.
        available_count = sum(1 for v in results.values() if v.available)
        assert available_count >= 1, "At least one model should succeed"

    def test_pe_failure_does_not_block_others(self):
        """Missing forward EPS makes PE fail; others should proceed."""
        snap = _make_snapshot(extra={
            "forward_eps_1y": None,
            "forward_eps_2y": None,
        })
        results = run_all_engines(snap, DEFAULT_ASSUMPTIONS)
        assert results["forward_pe"].available is False
        # EV/EBITDA should still work.
        assert results["ev_ebitda"].available is True

    def test_ev_ebitda_failure_does_not_block_others(self):
        snap = _make_snapshot(extra={
            "forward_ebitda_1y": None,
            "forward_ebitda_2y": None,
            # Remove the independent bridge inputs as well; otherwise the
            # service is correctly allowed to derive EBITDA from revenue ×
            # historical margin, so the test would not represent an EV-only
            # failure.
            "revenue_ttm": None,
            "ebitda_ttm": None,
            "revenue_growth": None,
            "forward_revenue": None,
            "revenue_estimate_1y": None,
            "revenue_estimate_2y": None,
        })
        results = run_all_engines(snap, DEFAULT_ASSUMPTIONS)
        assert results["ev_ebitda"].available is False
        assert results["forward_pe"].available is True

    def test_fcf_yield_failure_does_not_block_others(self):
        snap = _make_snapshot(extra={
            "fcf_ttm": None,
            "forward_fcf_1y": None,
            "forward_fcf_2y": None,
        })
        results = run_all_engines(snap, DEFAULT_ASSUMPTIONS)
        assert results["fcf_yield"].available is False
        assert results["forward_pe"].available is True

    def test_failed_model_has_reason(self):
        snap = _make_snapshot(extra={"forward_eps_1y": None, "forward_eps_2y": None})
        results = run_all_engines(snap, DEFAULT_ASSUMPTIONS)
        pe = results["forward_pe"]
        assert pe.available is False
        assert pe.unavailable_reason is not None
        assert len(pe.unavailable_reason) > 0

    def test_all_four_engines_present(self):
        snap = _make_snapshot()
        results = run_all_engines(snap, DEFAULT_ASSUMPTIONS)
        assert set(results.keys()) == {"forward_pe", "ev_ebitda", "fcf_yield", "dcf"}

    def test_valuation_service_propagates_partial_results(self):
        """ValuationService.compute should return a response even with partial failures."""
        # Missing forward EPS → PE fails, but response should still build.
        class PartialProvider(StubProvider):
            def get_forward_estimates(self, ticker):
                d = super().get_forward_estimates(ticker)
                d.pop("forward_eps_1y", None)
                d.pop("forward_eps_2y", None)
                return d

        svc = FinancialDataService(
            provider=PartialProvider(), cache=MemoryTTLCache(), default_assumptions=DEFAULT_ASSUMPTIONS,
        )
        vs = ValuationService(svc, default_assumptions=DEFAULT_ASSUMPTIONS)
        response = vs.compute("TEST")
        assert response.ticker == "TEST"
        assert "forward_pe" in response.valuations
        assert response.valuations["forward_pe"].available is False
        # Other models should still be available.
        other_available = sum(
            1 for k, v in response.valuations.items() if k != "forward_pe" and v.available
        )
        assert other_available >= 1


# ===================================================================
# Additional cross-cutting regression checks
# ===================================================================

class TestDemoDataQualityAlwaysLow:
    """Demo data is always LOW quality regardless of provenance."""

    def test_avgo_fixture_is_demo_and_low(self):
        from app.providers.avgo_fixture import AVGOFixtureProvider
        snap = AVGOFixtureProvider().get_snapshot("AVGO")
        assert snap.is_demo is True
        assert snap.data_quality == DataQuality.LOW

    def test_demo_quality_after_normalize(self):
        snap = _make_snapshot(is_demo=True)
        normalized = normalize_snapshot(snap, strict_profile=False)
        assert normalized.data_quality == DataQuality.LOW


class TestNetDebtConsistency:
    """net_debt must equal total_debt - cash."""

    def test_net_debt_value_equals_identity(self):
        snap = _make_snapshot(cash="5000000000", debt="10000000000")
        assert snap.get_net_debt() == Decimal("5000000000")

    def test_net_debt_metric_present(self):
        snap = _make_snapshot()
        assert snap.net_debt is not None
        assert snap.net_debt_metric is not None

    def test_inconsistent_net_debt_rejected(self):
        with pytest.raises(ValueError):
            _make_snapshot(
                extra={
                    "net_debt": _fm("999999", source="wrong", source_type=SourceType.DERIVED),
                }
            )


class TestOverrideContract:
    """POST override Pydantic models enforce the nested contract."""

    def test_nested_json_accepted(self):
        req = ValuationOverrideRequest.model_validate({
            "forward_pe": {"base": 18},
            "fcf_yield": {"base": 0.05},
            "dcf": {"wacc": 0.095, "terminal_growth": 0.035},
        })
        flat = req.to_override_dict()
        assert "forward_pe.base" in flat
        assert flat["forward_pe.base"] == Decimal("18")

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            ValuationOverrideRequest.model_validate({"unknown": 42})

    def test_dcf_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            ValuationOverrideRequest.model_validate({"dcf": {"wacc": 0.1, "extra": 0.1}})

    def test_sparse_base_derives_low_high(self):
        req = ValuationOverrideRequest.model_validate({"forward_pe": {"base": 20}})
        flat = req.to_override_dict()
        assert "forward_pe.low" in flat
        assert "forward_pe.high" in flat
        assert flat["forward_pe.low"] <= flat["forward_pe.base"] <= flat["forward_pe.high"]

    def test_yield_inverse_order_enforced(self):
        """FCF yield low (conservative) must be >= high (optimistic)."""
        with pytest.raises(ValidationError):
            ValuationOverrideRequest.model_validate({
                "fcf_yield": {"low": 0.03, "high": 0.06}
            })
