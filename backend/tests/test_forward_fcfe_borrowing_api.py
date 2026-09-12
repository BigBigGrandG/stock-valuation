"""API regression for explicit provider forward borrowing transport."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient
import pytest

from app import main
from app.providers.base import FinancialDataProvider
from app.services.valuation_service import FinancialDataService, MemoryTTLCache, ValuationService
from app.models.domain import ValuationAssumptions


AS_OF = "2026-09-12"


class _ExplicitForwardBorrowingProvider(FinancialDataProvider):
    """Raw provider fixture that keeps historical and forward debt flows distinct."""

    is_demo = False

    def __init__(self, *, missing_year: int | None = None):
        self.missing_year = missing_year

    def get_quote(self, ticker: str) -> dict[str, Any]:
        return {
            "price": Decimal("100"),
            "currency": "USD",
            "timestamp": f"{AS_OF}T12:00:00",
            "as_of": AS_OF,
            "source": "case-c-provider",
            "exchange": "NASDAQ",
            "market": "US",
        }

    def get_company_profile(self, ticker: str) -> dict[str, Any]:
        return {
            "name": "Case C Provider Co",
            "diluted_shares": Decimal("1000"),
            "currency": "USD",
            "financial_currency": "USD",
            "country": "US",
            "exchange": "NASDAQ",
            "market": "US",
            "security_type": "COMMON_STOCK",
            "sector": "Technology",
            "industry": "Software",
            "is_profitable": True,
            "as_of": AS_OF,
            "source": "case-c-provider",
        }

    def get_balance_sheet(self, ticker: str) -> dict[str, Any]:
        return {
            "cash": Decimal("100"),
            "total_debt": Decimal("200"),
            "period": "FY2025",
            "as_of": AS_OF,
            "source": "case-c-provider",
        }

    def get_cash_flow(self, ticker: str) -> dict[str, Any]:
        return {
            "cfo": Decimal("300"),
            "capex": Decimal("50"),
            "net_borrowing": Decimal("500"),
            "interest": Decimal("20"),
            "tax_rate": Decimal("0.20"),
            "nwc_change": Decimal("10"),
            "period": "TTM",
            "as_of": AS_OF,
            "source": "case-c-provider",
        }

    def get_income_statement(self, ticker: str) -> dict[str, Any]:
        return {
            "revenue_ttm": Decimal("1000"),
            "ebitda_ttm": Decimal("200"),
            "eps_ttm": Decimal("5"),
            "da": Decimal("30"),
            "period": "TTM",
            "as_of": AS_OF,
            "source": "case-c-provider",
        }

    def get_forward_estimates(self, ticker: str) -> dict[str, Any]:
        return {
            "forward_revenue_1y": None if self.missing_year == 1 else Decimal("1200"),
            "forward_revenue_2y": None if self.missing_year == 2 else Decimal("1400"),
            "revenue_growth": Decimal("0.10"),
            "forward_eps_1y": Decimal("6"),
            "forward_eps_2y": Decimal("7"),
            "forward_net_borrowing_1y": Decimal("321"),
            "forward_net_borrowing_1y_period": "NTM",
            "forward_net_borrowing_1y_source": "case-c-provider consensus",
            "forward_net_borrowing_1y_source_type": "provider_forward",
            "forward_net_borrowing_1y_as_of": AS_OF,
            "forward_net_borrowing_1y_currency": "USD",
            "forward_net_borrowing_1y_confidence": 0.85,
            "forward_net_borrowing_1y_is_estimated": True,
            "forward_net_borrowing_1y_notes": "Explicit provider forward value; not derived from TTM.",
            "period_1y": "FY2026E",
            "period_2y": "FY2027E",
            "forecast_fiscal_year_end": "2026-12-31",
            "as_of": AS_OF,
            "source": "case-c-provider",
        }

    def get_historical_multiples(self, ticker: str) -> dict[str, Any]:
        return {
            "period": "historical",
            "as_of": AS_OF,
            "source": "case-c-provider",
        }


def test_case_c_api_preserves_explicit_forward_borrowing_metadata(monkeypatch):
    """The production API path must carry provider forward borrowing into its bridge."""
    provider = _ExplicitForwardBorrowingProvider()
    data_service = FinancialDataService(
        provider,
        cache=MemoryTTLCache(),
        default_assumptions=ValuationAssumptions(),
    )
    service = ValuationService(data_service, default_assumptions=ValuationAssumptions())
    monkeypatch.setattr(main, "_resolve_valuation_service", lambda provider=None: service)

    response = TestClient(main.app).get("/api/v1/valuation/CASEC")

    assert response.status_code == 200, response.text
    bridge = response.json()["financial_bridge"]
    assert Decimal(bridge["forward_net_borrowing"]) == Decimal("321")
    assert bridge["forward_net_borrowing_status"] == "provider_forward"
    assert bridge["forward_net_borrowing_period"] == "NTM"
    assert bridge["forward_net_borrowing_source"] == "provider_forward"
    assert bridge["forward_net_borrowing_source_type"] == "analyst_estimate"
    assert Decimal(bridge["historical_net_borrowing"]) == Decimal("500")
    assert bridge["historical_net_borrowing_period"] == "TTM"


@pytest.mark.parametrize("missing_year", [1, 2])
def test_api_incomplete_fy_forecast_hides_dcf_bridge_inputs(monkeypatch, missing_year):
    """An unavailable production DCF must not leak partial FCFF forecasts."""
    provider = _ExplicitForwardBorrowingProvider(missing_year=missing_year)
    data_service = FinancialDataService(
        provider,
        cache=MemoryTTLCache(),
        default_assumptions=ValuationAssumptions(),
    )
    service = ValuationService(data_service, default_assumptions=ValuationAssumptions())
    monkeypatch.setattr(main, "_resolve_valuation_service", lambda provider=None: service)

    response = TestClient(main.app).get(f"/api/v1/valuation/CASE-M{missing_year}")

    assert response.status_code == 200, response.text
    payload = response.json()
    dcf = payload["valuations"]["dcf"]
    bridge = payload["financial_bridge"]
    assert dcf["available"] is False
    assert bridge["dcf_forecasts"] == []
    assert not any(
        key in {"fcff_ttm", "forward_fcff_1y", "forward_fcff_2y"}
        for key in (dcf.get("input_metrics") or {})
    )
    assert bridge["fcfe"] is not None
    assert Decimal(bridge["forward_net_borrowing"]) == Decimal("321")
    assert Decimal(bridge["historical_net_borrowing"]) == Decimal("500")
