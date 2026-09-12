"""R5 regression tests for production DCF projection isolation.

The standalone DCF engine may retain a documented historical-input fallback
for explicit engine-level tests.  The production orchestration boundary must
not use that fallback when the request projection cannot produce a qualified
FY1/FY2 FCFF forecast because a required driver (such as CapEx) is missing.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import main
from app.models.domain import CompanyFinancialSnapshot, FinancialMetric, SourceType, ValuationAssumptions
from app.services.projections import derive_request_projections
from app.services.valuation_service import ValuationService, run_all_engines


AS_OF = date(2026, 6, 30)


def _m(
    value: object,
    *,
    period: str = "TTM",
    source_type: SourceType = SourceType.DERIVED,
    as_of: date = AS_OF,
    unit: str = "USD",
) -> FinancialMetric:
    return FinancialMetric(
        value=Decimal(str(value)),
        unit=unit,
        period=period,
        source="r5-test",
        source_type=source_type,
        as_of=as_of,
        confidence=1.0,
        is_estimated=source_type != SourceType.ACTUAL,
    )


def _snapshot(**updates: Any) -> CompanyFinancialSnapshot:
    fields: dict[str, Any] = {
        "ticker": "R5",
        "company_name": "R5 Test Co",
        "currency": "USD",
        "current_price": _m("100", period="2026-06-30", source_type=SourceType.ACTUAL),
        "price_timestamp": datetime(2026, 6, 30, 12, 0),
        "diluted_shares": _m("1000", unit="shares", source_type=SourceType.ACTUAL),
        "cash": _m("100", source_type=SourceType.ACTUAL),
        "total_debt": _m("200", source_type=SourceType.ACTUAL),
        "revenue_ttm": _m("1000"),
        "ebitda_ttm": _m("200"),
        "eps_ttm": _m("5", unit="USD/share"),
        "forward_eps_1y": _m("6", period="FY2027E"),
        "forward_eps_2y": _m("7", period="FY2028E"),
        "forward_ebitda_1y": _m("240", period="FY2027E"),
        "forward_fcf_1y": _m("180", period="FY2027E"),
        "forward_fcff_1y": _m("170", period="FY2027E"),
        "forward_fcff_2y": _m("190", period="FY2028E"),
        "revenue_estimate_1y": _m("1200", period="FY2027E"),
        "revenue_estimate_2y": _m("1400", period="FY2028E"),
        "forecast_fiscal_year_end": date(2027, 12, 31),
        "tax_rate": _m("0.20", unit="ratio"),
        "capex_ttm": _m("50"),
        "nwc_change_ttm": _m("10"),
        "da_ttm": _m("30"),
        "interest_ttm": _m("20"),
        "net_borrowing_ttm": _m("5"),
        "country": "US",
        "security_type": "COMMON_STOCK",
        "sector": "Technology",
        "industry": "Software",
        "is_profitable": True,
        "is_demo": False,
    }
    fields.update(updates)
    return CompanyFinancialSnapshot(**fields)


@pytest.mark.parametrize("source_type", [SourceType.ACTUAL, SourceType.DERIVED, SourceType.FIXTURE])
@pytest.mark.parametrize("with_revenue_forecast", [True, False])
def test_r5_run_all_engines_isolates_missing_capex_for_every_fcff_source(
    source_type: SourceType,
    with_revenue_forecast: bool,
):
    """Missing CapEx must not fall through to historical FCFF×growth in production orchestration."""
    updates: dict[str, Any] = {
        "capex_ttm": None,
        "fcff_ttm": _m("700", source_type=source_type),
    }
    if not with_revenue_forecast:
        updates.update(
            {
                "revenue_estimate_1y": None,
                "revenue_estimate_2y": None,
                "forward_revenue": None,
            }
        )
    snapshot = _snapshot(**updates)
    assumptions = ValuationAssumptions()

    projection = derive_request_projections(snapshot, assumptions)
    assert projection.dcf_fcff_1y is None

    dcf = run_all_engines(snapshot, assumptions)["dcf"]
    assert dcf.available is False
    assert "No FCFF data" in (dcf.unavailable_reason or "")
    assert "configured fallback FCFF growth" not in " ".join(dcf.calculation_steps)


def test_r5_only_fy2_consensus_cannot_retain_historical_fcff_fallback():
    """FY2-only FCFF consensus still lacks the required production FY1 input."""
    snapshot = _snapshot(
        capex_ttm=None,
        fcff_ttm=_m("700", source_type=SourceType.ACTUAL),
        revenue_estimate_1y=None,
        revenue_estimate_2y=_m("1400", period="FY2028E", source_type=SourceType.ANALYST_ESTIMATE),
        forward_fcff_1y=None,
        forward_fcff_2y=_m("190", period="FY2028E", source_type=SourceType.ANALYST_ESTIMATE),
    )

    projection = derive_request_projections(snapshot, ValuationAssumptions())
    assert projection.dcf_fcff_1y is None
    assert projection.dcf_fcff_2y is not None

    dcf = run_all_engines(snapshot, ValuationAssumptions())["dcf"]
    assert dcf.available is False
    assert "No FCFF data" in (dcf.unavailable_reason or "")


class _SnapshotDataService:
    """Minimal data-service seam so the actual API route exercises production orchestration."""

    _default_assumptions = ValuationAssumptions()

    def __init__(self, snapshot: CompanyFinancialSnapshot):
        self.snapshot = snapshot

    def get_snapshot(self, ticker: str, **_: Any) -> CompanyFinancialSnapshot:
        return self.snapshot


@pytest.mark.parametrize("source_type", [SourceType.ACTUAL, SourceType.DERIVED, SourceType.FIXTURE])
def test_r5_api_isolates_missing_capex_in_production_response(monkeypatch: pytest.MonkeyPatch, source_type: SourceType):
    """HTTP valuation output must expose DCF unavailability, not a historical estimate."""
    snapshot = _snapshot(
        capex_ttm=None,
        fcff_ttm=_m("700", source_type=source_type),
    )
    service = ValuationService(_SnapshotDataService(snapshot), default_assumptions=ValuationAssumptions())
    monkeypatch.setattr(main, "_resolve_valuation_service", lambda provider=None: service)

    response = TestClient(main.app).get("/api/v1/valuation/R5")

    assert response.status_code == 200
    payload = response.json()
    dcf = payload["valuations"]["dcf"]
    assert dcf["available"] is False
    assert "No FCFF data" in (dcf.get("unavailable_reason") or "")
    assert "composite" not in payload
    assert payload["valuations"]["forward_pe"]["available"] is True
