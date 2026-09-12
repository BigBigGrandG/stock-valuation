"""Red-first regression coverage for audit Issues 03 and 04.

These tests intentionally exercise the production provider -> normalizer ->
service -> API path where possible.  They are written before the implementation
so the current baseline demonstrates the audited failures rather than merely
testing a new helper in isolation.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import DEFAULT_ASSUMPTIONS
from app.main import app
from app.models.domain import FinancialMetric, ScenarioValues, SourceType, ValuationAssumptions
from app.providers.avgo_fixture import AVGOFixtureProvider
from app.services.valuation_service import FinancialDataService, MemoryTTLCache, Normalizer, ValuationService
from app.engines.dcf import _compute_dcf_scenario, run_dcf


VALUATION_DATE = date(2026, 9, 12)


def _metric(value: str, unit: str = "USD", *, period: str = "FY2026E") -> FinancialMetric:
    return FinancialMetric(
        value=Decimal(value),
        unit=unit,
        period=period,
        source="regression fixture",
        source_type=SourceType.FIXTURE,
        as_of=VALUATION_DATE,
        is_estimated=True,
    )


class _CandidateProvider(AVGOFixtureProvider):
    """A deterministic provider whose raw categories match production calls."""

    def _dated(self, method, ticker: str):
        value = dict(method(ticker))
        value["as_of"] = VALUATION_DATE
        return value

    def get_quote(self, ticker: str):
        value = self._dated(super().get_quote, ticker)
        value["timestamp"] = datetime(2026, 9, 12, 16, tzinfo=timezone.utc)
        return value

    def get_company_profile(self, ticker: str):
        value = self._dated(super().get_company_profile, ticker)
        value["industry"] = "Semiconductors"
        value["sector"] = "Technology"
        return value

    def get_balance_sheet(self, ticker: str):
        return self._dated(super().get_balance_sheet, ticker)

    def get_cash_flow(self, ticker: str):
        return self._dated(super().get_cash_flow, ticker)

    def get_income_statement(self, ticker: str):
        return self._dated(super().get_income_statement, ticker)

    def get_forward_estimates(self, ticker: str):
        return self._dated(super().get_forward_estimates, ticker)

    def get_historical_multiples(self, ticker: str):
        company_pe_rows = [
            {
                "value": "20",
                "as_of": "2023-01-01",
                "forecast_period": "FY2024E",
                "price": "100",
                "price_as_of": "2023-01-01",
                "forward_eps": "5",
                "source": "Archived analyst consensus + historical close",
                "source_url": "https://example.test/company-pe/2023",
            },
            {
                "value": "21",
                "as_of": "2024-12-31",
                "forecast_period": "FY2025E",
                "price": "105",
                "price_as_of": "2024-12-31",
                "forward_eps": "5",
                "source": "Archived analyst consensus + historical close",
                "source_url": "https://example.test/company-pe/2024",
            },
            {
                "value": "22",
                "as_of": "2025-12-31",
                "forecast_period": "FY2026E",
                "price": "110",
                "price_as_of": "2025-12-31",
                "forward_eps": "5",
                "source": "Archived analyst consensus + historical close",
                "source_url": "https://example.test/company-pe/2025",
            },
            {
                "value": "23",
                "as_of": "2026-01-31",
                "forecast_period": "FY2027E",
                "price": "115",
                "price_as_of": "2026-01-31",
                "forward_eps": "5",
                "source": "Archived analyst consensus + historical close",
                "source_url": "https://example.test/company-pe/2026-01",
            },
            {
                "value": "24",
                "as_of": "2026-06-30",
                "forecast_period": "FY2027E",
                "price": "120",
                "price_as_of": "2026-06-30",
                "forward_eps": "5",
                "source": "Archived analyst consensus + historical close",
                "source_url": "https://example.test/company-pe/2026-06",
            },
        ]
        for row in company_pe_rows:
            observed = date.fromisoformat(str(row["as_of"]))
            row.update({
                "forecast_period_end": f"{int(str(row['forecast_period'])[2:6])}-12-31",
                "forecast_vintage_as_of": (observed - timedelta(days=30)).isoformat(),
                "is_forward": True,
                "price_currency": "USD",
                "forward_eps_currency": "USD",
                "price_unit": "USD/share",
                "forward_eps_unit": "USD/share",
                "price_basis": "diluted_common_share",
                "forward_eps_basis": "diluted_common_share",
                "forecast_source": "Archived analyst consensus",
                "forecast_source_url": f"{row['source_url']}/consensus",
            })
        return {
            "historical_forward_pe": None,
            "historical_ev_ebitda": None,
            "company_forward_pe_observations": company_pe_rows,
            # Intentionally malformed: it must not poison the independently
            # valid P/E company selection or make EV use the P/E level.
            "company_ev_ebitda_observations": [
                {
                    "value": "17",
                    "as_of": "2026-06-30",
                    "forecast_period": "FY2027E",
                    "enterprise_value": "1700",
                    "enterprise_value_as_of": "2025-06-30",
                    "forward_ebitda": "100",
                    "source": "Mismatched EV archive",
                    "source_url": "https://example.test/company-ev/2026",
                }
            ],
            "industry_name": "Semiconductor",
            "industry_forward_pe": "37.29",
            "industry_ev_ebitda": "42.70",
            "industry_sample_size": 66,
            "industry_as_of": "2026-01-01",
            "industry_period": "January 2026 US industry aggregate",
            "industry_currency": "USD",
            "industry_forward_pe_currency": "USD",
            "industry_ev_ebitda_currency": "USD",
            "industry_forward_pe_unit": "multiple",
            "industry_ev_ebitda_unit": "multiple",
            "industry_forward_pe_basis": "forward_consensus_eps",
            "industry_forward_pe_forecast_type": "forward",
            "industry_ev_ebitda_basis": "observed_all_firms_ebitda",
            "industry_ev_ebitda_forecast_type": "observed",
            "industry_ev_ebitda_denominator_scope": "all_firms",
            "industry_mapping_key": "semiconductors",
            "industry_mapping_source": "Controlled upstream industry label mapped to named public row",
            "industry_forward_pe_source": "Damodaran US Industry PE (Forward PE)",
            "industry_forward_pe_source_url": "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/pedata.html",
            "industry_ev_ebitda_source": "Damodaran US Industry EV/EBITDA (all firms)",
            "industry_ev_ebitda_source_url": "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/vebitda.htm",
            "industry_is_estimated": True,
            "industry_notes": "Observed aggregate; scenario range is a configured ±10% spread, not a percentile.",
            "as_of": VALUATION_DATE,
            "source": "controlled 03/04 regression provider",
        }


def _service(provider: _CandidateProvider) -> ValuationService:
    data_service = FinancialDataService(
        provider=provider,
        cache=MemoryTTLCache(),
        default_assumptions=DEFAULT_ASSUMPTIONS,
        normalizer=Normalizer(strict_profile=False, allow_all_equities=True),
    )
    return ValuationService(data_service, default_assumptions=DEFAULT_ASSUMPTIONS)


def test_issue03_production_api_selects_company_and_industry_independently():
    service = _service(_CandidateProvider())
    with patch("app.main._resolve_valuation_service", return_value=service):
        response = TestClient(app).get("/api/v1/valuation/AVGO")

    assert response.status_code == 200
    payload = response.json()
    assumptions = payload["assumptions_used"]
    # P/E has 5 valid contemporaneous observations, while EV/EBITDA must
    # independently fall back because the public row is observed all-firms,
    # not a forward operating-EBITDA target.
    assert assumptions["pe_source"] == "derived"
    assert assumptions["pe_target"]["base"] == "22.0000"
    assert "company historical" in assumptions["pe_source_label"].lower()
    assert assumptions["ev_ebitda_source"] == "configured_fallback"
    assert assumptions["ev_ebitda_multiple"]["base"] == "22"
    assert "system fallback" in assumptions["ev_ebitda_source_label"].lower()
    assert "observed" in assumptions["ev_ebitda_source_label"].lower()
    # AVGO fixture's NTM EPS is 19.21; the selected company-history median is
    # 22x, so the service path must use 19.21 × 22 = 422.62.
    assert payload["valuations"]["forward_pe"]["base"]["price_per_share"] == "422.62"
    assert payload["valuations"]["ev_ebitda"]["base"]["intermediates"]["multiple"] == "22"


def test_issue03_unknown_industry_uses_explicit_risk_disclosed_system_fallback():
    provider = _CandidateProvider()
    original = provider.get_historical_multiples

    def unknown(ticker: str):
        raw = original(ticker)
        raw["industry_name"] = None
        raw["industry_forward_pe"] = None
        raw["industry_ev_ebitda"] = None
        # Remove company candidates too: this test is specifically the
        # unknown-industry/system-fallback boundary, not company-history.
        raw["company_forward_pe_observations"] = []
        raw["company_ev_ebitda_observations"] = []
        raw["industry_unavailable_reason"] = "No mapped source row for upstream industry Unknown test"
        return raw

    provider.get_historical_multiples = unknown  # type: ignore[method-assign]
    response = _service(provider).compute("AVGO")
    assert response.assumptions_used.pe_source == SourceType.CONFIGURED_FALLBACK
    assert response.assumptions_used.ev_ebitda_source == SourceType.CONFIGURED_FALLBACK
    warning_text = " ".join(response.warnings).lower()
    assert "specificity" in warning_text
    assert "industry" in warning_text


def test_issue03_user_override_precedes_candidates_and_does_not_leak_after_reset():
    service = _service(_CandidateProvider())
    overridden = service.compute("AVGO", overrides={"forward_pe.base": "30"})
    assert overridden.assumptions_used.pe_source == SourceType.USER_OVERRIDE
    assert overridden.assumptions_used.pe_selection_layer == "user_override"
    assert overridden.assumptions_used.pe_target.base == Decimal("30")
    # EV remains independently degraded because the industry denominator is
    # observed all-firms EBITDA rather than forward operating EBITDA.
    assert overridden.assumptions_used.ev_ebitda_selection_layer == "system"

    reset = service.compute("AVGO")
    assert reset.assumptions_used.pe_selection_layer == "company_historical"
    assert reset.assumptions_used.pe_target.base == Decimal("22.0000")
    assert reset.assumptions_used.ev_ebitda_selection_layer == "system"


def test_issue03_invalid_industry_currency_falls_back_only_for_ev():
    provider = _CandidateProvider()
    original = provider.get_historical_multiples

    def bad_ev_currency(ticker: str):
        raw = original(ticker)
        raw["industry_currency"] = "EUR"
        return raw

    provider.get_historical_multiples = bad_ev_currency  # type: ignore[method-assign]
    response = _service(provider).compute("AVGO")
    assert response.assumptions_used.pe_selection_layer == "company_historical"
    assert response.assumptions_used.ev_ebitda_selection_layer == "system"
    assert response.assumptions_used.ev_ebitda_source == SourceType.CONFIGURED_FALLBACK
    assert any("currency" in warning.lower() for warning in response.warnings)


@pytest.mark.parametrize(
    ("growth_start", "terminal_growth"),
    [
        ("0.20", "0.03"),
        ("-0.05", "0.03"),
        ("0.03", "0.03"),
        ("-0.10", "-0.04"),
    ],
)
def test_issue04_linear_fade_supports_down_up_equal_and_negative_rates(
    growth_start: str, terminal_growth: str
):
    scenario = _compute_dcf_scenario(
        scenario_name="base",
        fcff_y1=Decimal("100"),
        fcff_y2=Decimal("110"),
        fcff_y1_label="test Y1",
        fcff_y2_label="test Y2",
        growth_rate=Decimal(growth_start),
        wacc=Decimal("0.12"),
        terminal_growth=Decimal(terminal_growth),
        total_debt=Decimal("0"),
        cash=Decimal("0"),
        diluted_shares=Decimal("100"),
        current_price=Decimal("10"),
    )
    start = Decimal(growth_start)
    terminal = Decimal(terminal_growth)
    expected_rates = [
        start + (Decimal(str(year - 2)) / Decimal("3")) * (terminal - start)
        for year in (3, 4)
    ] + [terminal]
    assert scenario.projection_growth_rates[2:] == expected_rates
    assert scenario.projection_growth_rates[4] == Decimal(terminal_growth)
    assert scenario.growth_fade_formula and "g_terminal" in scenario.growth_fade_formula


def _dcf_snapshot() -> object:
    base = AVGOFixtureProvider().get_snapshot("AVGO")
    net_debt = _metric("0")
    return base.model_copy(
        update={
            "is_demo": False,
            "current_price": _metric("100"),
            "price_timestamp": datetime(2026, 9, 12, tzinfo=timezone.utc),
            "forward_fcff_1y": _metric("100", period="FY2027E"),
            "forward_fcff_2y": _metric("120", period="FY2028E"),
            "cash": _metric("0"),
            "total_debt": _metric("0"),
            "net_debt": net_debt,
            "net_debt_metric": net_debt,
        }
    )


def test_issue04_dcf_growth_fade_reaches_each_scenario_terminal_rate():
    snapshot = _dcf_snapshot()
    assumptions = ValuationAssumptions(
        dcf_wacc=ScenarioValues(low=Decimal("0.12"), base=Decimal("0.10"), high=Decimal("0.08")),
        dcf_terminal_growth=ScenarioValues(low=Decimal("0.03"), base=Decimal("0.03"), high=Decimal("0.04")),
        dcf_fcf_growth=ScenarioValues(low=Decimal("0.20"), base=Decimal("0.20"), high=Decimal("0.20")),
    )
    result = run_dcf(snapshot, assumptions)
    assert result.available
    base = next(item for item in result.dcf_scenarios or [] if item.scenario == "base")
    assert base.projection_growth_rates[0] is None
    assert base.projection_growth_rates[1] == Decimal("0.20")
    assert base.projection_growth_rates[2] == Decimal("0.1433333333333333333333333333")
    assert base.projection_growth_rates[3] == Decimal("0.0866666666666666666666666667")
    assert base.projection_growth_rates[4] == Decimal("0.03")
    assert base.fcff_projections[2] == Decimal("137.20")
    assert base.fcff_projections[3] == Decimal("149.09")
    assert base.fcff_projections[4] == Decimal("153.56")
    assert base.fcff_year6 == base.fcff_projections[-1] * (Decimal("1") + base.terminal_growth)


def test_issue04_sensitivity_recomputes_growth_path_for_changed_terminal_rate():
    snapshot = _dcf_snapshot()
    assumptions = ValuationAssumptions(
        dcf_wacc=ScenarioValues(low=Decimal("0.12"), base=Decimal("0.10"), high=Decimal("0.08")),
        dcf_terminal_growth=ScenarioValues(low=Decimal("0.03"), base=Decimal("0.03"), high=Decimal("0.04")),
        dcf_fcf_growth=ScenarioValues(low=Decimal("0.20"), base=Decimal("0.20"), high=Decimal("0.20")),
    )
    result = run_dcf(snapshot, assumptions)
    matrix = result.sensitivity_matrix
    assert matrix is not None
    # The center is the base scenario.  The +0.5pp terminal column must have
    # a different Year 3-5 trajectory, not merely a TV formula change.
    center = matrix.cells[1][1]
    higher_terminal = matrix.cells[1][2]
    assert center.fcff_projections == next(
        item.fcff_projections for item in result.dcf_scenarios or [] if item.scenario == "base"
    )
    assert higher_terminal.fcff_projections[0:2] == center.fcff_projections[0:2]
    assert higher_terminal.fcff_projections[2:] != center.fcff_projections[2:]
    assert higher_terminal.projection_growth_rates[-1] == higher_terminal.terminal_growth
    assert higher_terminal.fcff_year6 == higher_terminal.fcff_projections[-1] * (
        Decimal("1") + higher_terminal.terminal_growth
    )
