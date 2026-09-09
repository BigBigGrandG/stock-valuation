"""Regression tests for the backend acceptance revisions."""
from __future__ import annotations

from datetime import date, datetime, time as datetime_time, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.engines.composite import run_composite
from app.engines.dcf import run_dcf
from app.main import app
from app.models.domain import DataQuality, FinancialMetric, ModelValuation, PriceEstimate, SourceType, ValuationAssumptions
from app.models.overrides import OverrideValidationError
from app.providers.avgo_fixture import AVGOFixtureProvider
from app.providers.base import (
    FinancialDataProvider,
    FinancialDataValidationError,
    InvalidTickerError,
    ProviderRateLimitError,
    ProviderUnavailableError,
    TickerNotFoundError,
    UnsupportedCompanyError,
)
from app.services import valuation_service as valuation_service_module
from app.services.valuation_service import FinancialDataService, MemoryTTLCache, Normalizer, ValuationService, apply_overrides, normalize_snapshot, run_all_engines


def test_api_rejects_string_override_and_unknown_nested_value():
    client = TestClient(app)
    assert client.post("/api/v1/valuation/AVGO", json={"forward_pe": {"base": "20"}}).status_code == 422
    assert client.post("/api/v1/valuation/AVGO", json={"forward_pe": {"base": [20]}}).status_code == 422
    assert client.post("/api/v1/valuation/AVGO", json={"forward_pe": {"typo": 20}}).status_code == 422


def test_sparse_fcf_yield_override_derives_inverse_bounds_and_is_request_scoped():
    client = TestClient(app)
    response = client.post("/api/v1/valuation/AVGO", json={"fcf_yield": {"base": 0.05}})
    assert response.status_code == 200
    fcf = response.json()["valuations"]["fcf_yield"]
    assert Decimal(fcf["assumptions"]["yield_low"]) == Decimal("0.055")
    assert Decimal(fcf["assumptions"]["yield_high"]) == Decimal("0.045")
    default = client.get("/api/v1/valuation/AVGO").json()
    assert default["valuations"]["fcf_yield"]["assumptions"]["yield_base"] == "0.050"


def test_effective_wacc_validation_catches_sparse_base_override():
    with pytest.raises(OverrideValidationError):
        apply_overrides(ValuationAssumptions(), {"dcf.wacc": Decimal("0.01")})


def test_memory_cache_uses_injected_monotonic_clock():
    now = [100.0]
    cache = MemoryTTLCache(clock=lambda: now[0])
    cache.set("quote:AVGO", {"price": 1}, 2)
    assert cache.get("quote:AVGO") == {"price": 1}
    now[0] = 102.0
    assert cache.get("quote:AVGO") is None


def test_service_calls_seven_provider_categories_once_when_cached():
    class CountingProvider(AVGOFixtureProvider):
        def __init__(self):
            self.calls = {name: 0 for name in ("quote", "profile", "balance", "cash_flow", "income", "estimates", "multiples")}

        def get_quote(self, ticker):
            self.calls["quote"] += 1
            return super().get_quote(ticker)

        def get_company_profile(self, ticker):
            self.calls["profile"] += 1
            return super().get_company_profile(ticker)

        def get_balance_sheet(self, ticker):
            self.calls["balance"] += 1
            return super().get_balance_sheet(ticker)

        def get_cash_flow(self, ticker):
            self.calls["cash_flow"] += 1
            return super().get_cash_flow(ticker)

        def get_income_statement(self, ticker):
            self.calls["income"] += 1
            return super().get_income_statement(ticker)

        def get_forward_estimates(self, ticker):
            self.calls["estimates"] += 1
            return super().get_forward_estimates(ticker)

        def get_historical_multiples(self, ticker):
            self.calls["multiples"] += 1
            return super().get_historical_multiples(ticker)

    provider = CountingProvider()
    service = FinancialDataService(provider, cache=MemoryTTLCache())
    service.get_snapshot("AVGO")
    service.get_snapshot("AVGO")
    assert provider.calls == {key: 1 for key in provider.calls}


def test_service_accepts_provider_with_only_seven_public_methods():
    fixture = AVGOFixtureProvider()

    class SevenMethodProvider(FinancialDataProvider):
        def get_quote(self, ticker):
            return fixture.get_quote(ticker)

        def get_company_profile(self, ticker):
            return fixture.get_company_profile(ticker)

        def get_balance_sheet(self, ticker):
            return fixture.get_balance_sheet(ticker)

        def get_cash_flow(self, ticker):
            return fixture.get_cash_flow(ticker)

        def get_income_statement(self, ticker):
            return fixture.get_income_statement(ticker)

        def get_forward_estimates(self, ticker):
            return fixture.get_forward_estimates(ticker)

        def get_historical_multiples(self, ticker):
            return fixture.get_historical_multiples(ticker)

    service = FinancialDataService(SevenMethodProvider(), cache=MemoryTTLCache())
    snapshot = service.get_snapshot("AVGO")
    assert snapshot.ticker == "AVGO"
    assert snapshot.net_debt.value == Decimal("35400000000")
    assert snapshot.country == "US"
    assert SevenMethodProvider().get_snapshot("AVGO").current_price.value == Decimal("343.83")


def test_service_rejects_missing_profile_metadata_instead_of_defaulting_to_us_stock():
    fixture = AVGOFixtureProvider()

    class MissingProfileProvider(FinancialDataProvider):
        def get_quote(self, ticker):
            return fixture.get_quote(ticker)

        def get_company_profile(self, ticker):
            profile = fixture.get_company_profile(ticker)
            profile.pop("country", None)
            profile.pop("security_type", None)
            profile.pop("is_profitable", None)
            return profile

        def get_balance_sheet(self, ticker):
            return fixture.get_balance_sheet(ticker)

        def get_cash_flow(self, ticker):
            return fixture.get_cash_flow(ticker)

        def get_income_statement(self, ticker):
            return fixture.get_income_statement(ticker)

        def get_forward_estimates(self, ticker):
            return fixture.get_forward_estimates(ticker)

        def get_historical_multiples(self, ticker):
            return fixture.get_historical_multiples(ticker)

    with pytest.raises(FinancialDataValidationError, match="missing required metadata"):
        FinancialDataService(MissingProfileProvider(), cache=MemoryTTLCache()).get_snapshot("AVGO")


def test_normalizer_rejects_bad_domains_and_profile_types():
    provider = AVGOFixtureProvider()
    snapshot = provider.get_snapshot("AVGO")
    with pytest.raises(FinancialDataValidationError):
        normalize_snapshot(snapshot.model_copy(update={"current_price": snapshot.current_price.model_copy(update={"value": Decimal("0")})}))
    with pytest.raises(UnsupportedCompanyError):
        normalize_snapshot(snapshot.model_copy(update={"sector": "Banks", "is_demo": False}))


def test_ttm_fcff_is_derived_into_a_new_forecast_period():
    snapshot = AVGOFixtureProvider().get_snapshot("AVGO").model_copy(update={
        "forward_fcff_1y": None,
        "forward_fcff_2y": None,
    })
    result = run_dcf(snapshot, ValuationAssumptions())
    assert result.available
    first = result.dcf_scenarios[0]
    assert first.projection_metrics[0]["period"] != "TTM"
    assert first.projection_metrics[0]["source_type"] == SourceType.DERIVED.value


def test_dcf_projection_periods_are_contiguous_and_fixture_is_not_consensus():
    snapshot = AVGOFixtureProvider().get_snapshot("AVGO")
    result = run_dcf(snapshot, ValuationAssumptions())
    assert result.available
    for scenario in result.dcf_scenarios:
        assert scenario.projection_periods == ["FY2025E", "FY2026E", "FY2027E", "FY2028E", "FY2029E"]
        assert all("analyst consensus" not in metric.get("source", "").lower() for metric in scenario.projection_metrics)
        assert all(metric["source_type"] == SourceType.FIXTURE.value for metric in scenario.projection_metrics[:2])


def test_composite_excludes_partial_dcf_without_counting_missing_as_zero():
    estimate = lambda value: PriceEstimate(price_per_share=Decimal(value), upside_pct=Decimal("0"), premium_discount_pct=Decimal("0"))
    full = ModelValuation(formula="x", formula_description="x", inputs={}, assumptions={}, calculation_steps=[], low=estimate("90"), base=estimate("100"), high=estimate("110"))
    partial_dcf = full.model_copy(update={"dcf_scenarios": []})
    composite = run_composite(Decimal("100"), full, full, full, partial_dcf, ValuationAssumptions())
    assert composite.available_models == ["forward_pe", "ev_ebitda", "fcf_yield"]
    assert composite.weights_used["forward_pe"] == Decimal("0.3571")


@pytest.mark.parametrize(
    ("updates", "reason"),
    [
        ({"sector": "Banks"}, "bank_or_insurance"),
        ({"industry": "Insurance"}, "bank_or_insurance"),
        ({"sector": "Real Estate Investment Trusts"}, "reit"),
        ({"security_type": "SPAC"}, "spac"),
        ({"security_type": "ETF"}, "etf"),
        ({"sector": "Financial Services"}, "financial_services"),
        ({"sector": "Financials"}, "financial_services"),
        ({"country": "GB"}, "non_us"),
        ({"is_profitable": False}, "long_term_loss"),
    ],
)
def test_support_guard_rejects_profile_variants(updates, reason):
    snapshot = AVGOFixtureProvider().get_snapshot("AVGO").model_copy(update={"is_demo": False, **updates})
    with pytest.raises(UnsupportedCompanyError, match=reason):
        normalize_snapshot(snapshot, strict_profile=True)


def test_net_debt_mismatch_is_financial_data_validation():
    snapshot = AVGOFixtureProvider().get_snapshot("AVGO")
    bad_metric = snapshot.net_debt.model_copy(update={"value": Decimal("999999")})
    bad_snapshot = snapshot.model_copy(update={"net_debt": bad_metric})
    with pytest.raises(FinancialDataValidationError, match="net_debt"):
        normalize_snapshot(bad_snapshot)


def test_dcf_growth_exposes_raw_and_effective_capped_metrics():
    snapshot = AVGOFixtureProvider().get_snapshot("AVGO").model_copy(update={
        "forward_fcff_2y": AVGOFixtureProvider().get_snapshot("AVGO").forward_fcff_2y.model_copy(
            update={"value": Decimal("110600000000")}
        )
    })
    result = run_dcf(snapshot, ValuationAssumptions())
    assert result.available
    base = next(scenario for scenario in result.dcf_scenarios if scenario.scenario == "base")
    assert base.growth_metric_raw["value"] == "0.4"
    assert base.growth_metric["value"] == str(base.growth_rate)
    assert base.growth_cap == Decimal("0.30")
    assert "cap=0.30" in base.growth_metric["notes"]


def test_dcf_prefers_historical_fcff_over_actual_operating_growth():
    fixture = AVGOFixtureProvider().get_snapshot("AVGO")
    actual = lambda value, label: FinancialMetric(
        value=Decimal(value),
        unit="ratio",
        period="FY2024",
        source=label,
        source_type=SourceType.ACTUAL,
        as_of=date(2024, 12, 31),
    )
    snapshot = fixture.model_copy(update={
        "is_demo": False,
        "forward_fcff_2y": None,
        "fcff_ttm": None,
        "revenue_growth": actual("0.40", "historical revenue"),
        "fcff_growth": actual("0.10", "historical FCFF"),
    })
    result = run_dcf(snapshot, ValuationAssumptions())
    assert result.available
    assert "historical FCFF" in result.assumptions["growth_source"]


def test_historical_multiple_provenance_is_preserved_for_base_and_derived_ranges():
    fixture = AVGOFixtureProvider().get_snapshot("AVGO")
    history = FinancialMetric(
        value=Decimal("20"),
        unit="multiple",
        period="5Y median",
        source="history vendor",
        source_type=SourceType.ANALYST_ESTIMATE,
        as_of=date(2024, 12, 31),
        confidence=Decimal("0.7"),
        is_estimated=True,
    )
    snapshot = fixture.model_copy(update={
        "is_demo": False,
        "historical_forward_pe": history,
        "historical_ev_ebitda": history,
    })
    results = run_all_engines(snapshot, ValuationAssumptions())
    for model, key in ((results["forward_pe"], "pe_multiple_"), (results["ev_ebitda"], "multiple_")):
        base = model.assumption_metrics[key + "base"]
        low = model.assumption_metrics[key + "low"]
        assert base["source"] == "history vendor"
        assert base["source_type"] == SourceType.ANALYST_ESTIMATE.value
        assert base["period"] == "5Y median"
        assert base["as_of"] == "2024-12-31"
        assert low["source_type"] == SourceType.DERIVED.value
        assert low["as_of"] == "2024-12-31"


def test_dcf_rejects_terminal_growth_above_configured_cap():
    snapshot = AVGOFixtureProvider().get_snapshot("AVGO")
    assumptions = ValuationAssumptions(
        dcf_wacc={"low": Decimal("0.12"), "base": Decimal("0.11"), "high": Decimal("0.10")},
        dcf_terminal_growth={"low": Decimal("0.06"), "base": Decimal("0.07"), "high": Decimal("0.08")},
    )
    result = run_dcf(snapshot, assumptions)
    assert not result.available
    assert "exceeds configured max" in result.unavailable_reason


def test_composite_display_weights_reconcile_to_one():
    estimate = lambda value: PriceEstimate(
        price_per_share=Decimal(value),
        upside_pct=Decimal("0"),
        premium_discount_pct=Decimal("0"),
    )
    model = ModelValuation(
        formula="x",
        formula_description="x",
        inputs={},
        assumptions={},
        calculation_steps=[],
        low=estimate("90"),
        base=estimate("100"),
        high=estimate("110"),
    )
    assumptions = ValuationAssumptions(
        weight_pe=Decimal("1"),
        weight_ev_ebitda=Decimal("1"),
        weight_fcf_yield=Decimal("1"),
        weight_dcf=Decimal("0"),
    )
    composite = run_composite(Decimal("100"), model, model, model, model, assumptions)
    assert sum(composite.weights_used.values()) == Decimal("1.0000")


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"forward_pe": {"base": 200}}, 422),
        ({"ev_ebitda": {"base": 200}}, 422),
        ({"fcf_yield": {"base": 0.5}}, 422),
    ],
)
def test_sparse_override_derived_bounds_stay_within_effective_ranges(body, expected):
    response = TestClient(app).post("/api/v1/valuation/AVGO", json=body)
    assert response.status_code == expected


class _ErrorProvider(FinancialDataProvider):
    def __init__(self, error_type):
        self.error_type = error_type

    def _raise(self):
        raise self.error_type("provider test error")

    def get_quote(self, ticker): self._raise()
    def get_company_profile(self, ticker): self._raise()
    def get_balance_sheet(self, ticker): self._raise()
    def get_cash_flow(self, ticker): self._raise()
    def get_income_statement(self, ticker): self._raise()
    def get_forward_estimates(self, ticker): self._raise()
    def get_historical_multiples(self, ticker): self._raise()


@pytest.mark.parametrize(
    ("error_type", "expected"),
    [
        (ProviderRateLimitError, 429),
        (ProviderUnavailableError, 503),
        (TickerNotFoundError, 404),
        (InvalidTickerError, 422),
        (FinancialDataValidationError, 422),
    ],
)
def test_provider_error_taxonomy_maps_to_distinct_http_status(monkeypatch, error_type, expected):
    import app.main as main_module

    data_service = FinancialDataService(_ErrorProvider(error_type), cache=MemoryTTLCache())
    monkeypatch.setattr(main_module, "_data_service", data_service)
    monkeypatch.setattr(main_module, "_valuation_service", ValuationService(data_service))
    response = TestClient(main_module.app).get("/api/v1/valuation/AVGO")
    assert response.status_code == expected


def test_category_ttls_refresh_monotonically_without_refetching_long_lived_data():
    class CountingProvider(AVGOFixtureProvider):
        def __init__(self):
            self.calls = {key: 0 for key in ("quote", "profile", "balance", "cash_flow", "income", "estimates", "multiples")}

        def _call(self, key, method, ticker):
            self.calls[key] += 1
            return method(ticker)

        def get_quote(self, ticker): return self._call("quote", super().get_quote, ticker)
        def get_company_profile(self, ticker): return self._call("profile", super().get_company_profile, ticker)
        def get_balance_sheet(self, ticker): return self._call("balance", super().get_balance_sheet, ticker)
        def get_cash_flow(self, ticker): return self._call("cash_flow", super().get_cash_flow, ticker)
        def get_income_statement(self, ticker): return self._call("income", super().get_income_statement, ticker)
        def get_forward_estimates(self, ticker): return self._call("estimates", super().get_forward_estimates, ticker)
        def get_historical_multiples(self, ticker): return self._call("multiples", super().get_historical_multiples, ticker)

    now = [0.0]
    provider = CountingProvider()
    service = FinancialDataService(provider, cache=MemoryTTLCache(clock=lambda: now[0]))
    service.get_snapshot("AVGO")
    now[0] = 121
    service.get_snapshot("AVGO")
    assert provider.calls["quote"] == 2
    assert provider.calls["balance"] == provider.calls["cash_flow"] == provider.calls["income"] == 1
    assert provider.calls["estimates"] == provider.calls["multiples"] == provider.calls["profile"] == 1
    now[0] = 43201
    service.get_snapshot("AVGO")
    assert provider.calls["quote"] == 3
    assert provider.calls["estimates"] == 2
    assert provider.calls["balance"] == provider.calls["multiples"] == provider.calls["profile"] == 1
    now[0] = 86401
    service.get_snapshot("AVGO")
    assert provider.calls["balance"] == provider.calls["cash_flow"] == provider.calls["income"] == 2
    assert provider.calls["multiples"] == provider.calls["profile"] == 2


def test_normalizer_preserves_category_dates_and_marks_stale_financial_inputs():
    fixture = AVGOFixtureProvider()
    today = date.today()
    old = today - timedelta(days=30)

    class DatedProvider(FinancialDataProvider):
        def _copy(self, method, *, as_of):
            value = dict(method("AVGO"))
            value["as_of"] = as_of
            value["source"] = "vendor"
            return value

        def get_quote(self, ticker):
            return {"price": Decimal("100"), "currency": "USD", "timestamp": datetime.combine(today, datetime_time.min), "as_of": today, "source": "vendor"}
        def get_company_profile(self, ticker): return self._copy(fixture.get_company_profile, as_of=today)
        def get_balance_sheet(self, ticker): return self._copy(fixture.get_balance_sheet, as_of=old)
        def get_cash_flow(self, ticker): return self._copy(fixture.get_cash_flow, as_of=old)
        def get_income_statement(self, ticker): return self._copy(fixture.get_income_statement, as_of=old)
        def get_forward_estimates(self, ticker): return self._copy(fixture.get_forward_estimates, as_of=old)
        def get_historical_multiples(self, ticker): return self._copy(fixture.get_historical_multiples, as_of=old)

    snapshot = FinancialDataService(DatedProvider(), cache=MemoryTTLCache()).get_snapshot("AVGO")
    assert snapshot.current_price.as_of == today
    assert snapshot.cash.as_of == old
    assert snapshot.forward_eps_1y.as_of == old
    assert any("Financial inputs are stale" in warning for warning in snapshot.warnings)


def test_normalizer_rejects_incompatible_fcf_type_and_preserves_zero_confidence():
    fixture = AVGOFixtureProvider()
    bad_cash_flow = dict(fixture.get_cash_flow("AVGO"))
    bad_cash_flow["fcff_ttm_type"] = "FCFE"
    with pytest.raises(FinancialDataValidationError, match="incompatible"):
        Normalizer().normalize_provider_data(
            "AVGO",
            fixture.get_quote("AVGO"),
            fixture.get_company_profile("AVGO"),
            fixture.get_balance_sheet("AVGO"),
            bad_cash_flow,
            fixture.get_income_statement("AVGO"),
            fixture.get_forward_estimates("AVGO"),
            fixture.get_historical_multiples("AVGO"),
        )

    estimates = dict(fixture.get_forward_estimates("AVGO"))
    estimates["forward_eps_1y_confidence"] = 0
    estimates["forward_eps_1y_is_estimated"] = False
    snapshot = Normalizer().normalize_provider_data(
        "AVGO",
        fixture.get_quote("AVGO"),
        fixture.get_company_profile("AVGO"),
        fixture.get_balance_sheet("AVGO"),
        fixture.get_cash_flow("AVGO"),
        fixture.get_income_statement("AVGO"),
        estimates,
        fixture.get_historical_multiples("AVGO"),
    )
    assert snapshot.forward_eps_1y.confidence == 0
    assert snapshot.forward_eps_1y.is_estimated is False
    assert snapshot.forward_eps_1y.source_type == SourceType.FIXTURE


def test_normalizer_checks_each_forward_year_and_cash_flow_fallback_type():
    fixture = AVGOFixtureProvider()
    estimates = dict(fixture.get_forward_estimates("AVGO"))
    estimates["forward_fcfe_1y_type"] = "FCFE"
    estimates["forward_fcfe_2y_type"] = "FCFF"
    with pytest.raises(FinancialDataValidationError, match="forward_fcfe_2y"):
        Normalizer().normalize_provider_data(
            "AVGO",
            fixture.get_quote("AVGO"),
            fixture.get_company_profile("AVGO"),
            fixture.get_balance_sheet("AVGO"),
            fixture.get_cash_flow("AVGO"),
            fixture.get_income_statement("AVGO"),
            estimates,
            fixture.get_historical_multiples("AVGO"),
        )

    cash_flow = dict(fixture.get_cash_flow("AVGO"))
    cash_flow["forward_fcff_2y_type"] = "FCFE"
    with pytest.raises(FinancialDataValidationError, match="cash-flow fallback FCFF.*forward_fcff_2y"):
        Normalizer().normalize_provider_data(
            "AVGO",
            fixture.get_quote("AVGO"),
            fixture.get_company_profile("AVGO"),
            fixture.get_balance_sheet("AVGO"),
            cash_flow,
            fixture.get_income_statement("AVGO"),
            {},
            fixture.get_historical_multiples("AVGO"),
        )


def test_model_exception_isolation_preserves_other_valuations(monkeypatch):
    snapshot = AVGOFixtureProvider().get_snapshot("AVGO")

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic P/E failure")

    monkeypatch.setattr(valuation_service_module, "run_forward_pe", fail)
    results = run_all_engines(snapshot, ValuationAssumptions())
    assert not results["forward_pe"].available
    assert "synthetic P/E failure" in results["forward_pe"].unavailable_reason
    assert results["ev_ebitda"].available
    assert results["fcf_yield"].available
    assert results["dcf"].available
