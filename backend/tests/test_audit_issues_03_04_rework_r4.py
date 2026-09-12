"""R4 regression coverage for the FCFE-yield fallback disclosure.

Issue 03's multiple resolver has separate P/E and EV/EBITDA warnings, but
FCFE yield has no compatible company/industry benchmark in the current data
contract.  These tests keep the warning at the model seam and verify that it
survives the production service/API response without being emitted for a
request-scoped user override.
"""
from __future__ import annotations

from fastapi.testclient import TestClient
from unittest.mock import patch

from app.config import DEFAULT_ASSUMPTIONS
from app.main import app
from app.providers.avgo_fixture import AVGOFixtureProvider
from app.services.valuation_service import (
    FinancialDataService,
    MemoryTTLCache,
    Normalizer,
    ValuationService,
)


_FALLBACK_WARNING_MARKERS = (
    "fcfe",
    "company",
    "industry",
    "benchmark",
    "configured",
    "specificity",
)


def _fixture_service() -> ValuationService:
    data_service = FinancialDataService(
        provider=AVGOFixtureProvider(),
        cache=MemoryTTLCache(),
        default_assumptions=DEFAULT_ASSUMPTIONS,
        normalizer=Normalizer(strict_profile=False, allow_all_equities=True),
    )
    return ValuationService(data_service, default_assumptions=DEFAULT_ASSUMPTIONS)


def _yield_fallback_warnings(warnings: list[str]) -> list[str]:
    return [
        warning
        for warning in warnings
        if all(marker in warning.lower() for marker in _FALLBACK_WARNING_MARKERS)
    ]


def test_issue03_r4_configured_fcf_yield_fallback_warning_reaches_api_once():
    service = _fixture_service()
    with patch("app.main._resolve_valuation_service", return_value=service):
        response = TestClient(app).get("/api/v1/valuation/AVGO")

    assert response.status_code == 200
    payload = response.json()
    fcf_yield = payload["valuations"]["fcf_yield"]
    assert payload["assumptions_used"]["fcf_yield_source"] == "configured_fallback"
    assert fcf_yield["assumptions"]["yield_source"] == "fallback"

    model_warnings = _yield_fallback_warnings(fcf_yield["warnings"])
    response_warnings = _yield_fallback_warnings(payload["warnings"])
    assert len(model_warnings) == 1
    assert response_warnings == model_warnings


def test_issue03_r4_user_override_has_no_misleading_fallback_warning():
    service = _fixture_service()
    with patch("app.main._resolve_valuation_service", return_value=service):
        response = TestClient(app).post(
            "/api/v1/valuation/AVGO",
            json={"fcf_yield": {"base": 0.05}},
        )

    assert response.status_code == 200
    payload = response.json()
    fcf_yield = payload["valuations"]["fcf_yield"]
    assert payload["assumptions_used"]["fcf_yield_source"] == "user_override"
    assert fcf_yield["assumptions"]["yield_source"] == "user_override"
    assert _yield_fallback_warnings(fcf_yield["warnings"]) == []
    assert _yield_fallback_warnings(payload["warnings"]) == []
