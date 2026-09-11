"""R6 regressions for fiscal-period eligibility and production DCF isolation.

Relative provider labels (``0y``/``+1y`` and equivalent aliases) are valid
annual estimates only when the provider supplies a fiscal-year-end anchor.
The production orchestration must also fail closed when either explicit DCF
year is missing, even though the standalone engine retains its historical
compatibility behavior for direct callers.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pytest

from app.models.domain import CompanyFinancialSnapshot, FinancialMetric, SourceType, ValuationAssumptions
from app.services.projections import _is_explicit_fy_metric, derive_request_projections
from app.services.valuation_service import run_all_engines


AS_OF = date(2026, 9, 10)
NEXT_FY_END = date(2026, 12, 31)


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
        source="r6-test",
        source_type=source_type,
        as_of=as_of,
        confidence=1.0,
        is_estimated=source_type != SourceType.ACTUAL,
    )


def _snapshot(**updates: Any) -> CompanyFinancialSnapshot:
    fields: dict[str, Any] = {
        "ticker": "R6",
        "company_name": "R6 Test Co",
        "currency": "USD",
        "current_price": _m("100", period="2026-09-10", source_type=SourceType.ACTUAL),
        "price_timestamp": datetime(2026, 9, 10, 12, 0),
        "diluted_shares": _m("1000", unit="shares", source_type=SourceType.ACTUAL),
        "cash": _m("100", source_type=SourceType.ACTUAL),
        "total_debt": _m("200", source_type=SourceType.ACTUAL),
        "revenue_ttm": _m("1000"),
        "ebitda_ttm": _m("200"),
        "eps_ttm": _m("5", unit="USD/share"),
        "tax_rate": _m("0.20", unit="ratio"),
        "capex_ttm": _m("50"),
        "nwc_change_ttm": _m("10"),
        "da_ttm": _m("30"),
        "interest_ttm": _m("20"),
        "net_borrowing_ttm": _m("5"),
        "fcff_ttm": _m("700", source_type=SourceType.ACTUAL),
        "forward_eps_1y": _m("6", period="0y", source_type=SourceType.ANALYST_ESTIMATE),
        "forward_eps_2y": _m("7", period="+1y", source_type=SourceType.ANALYST_ESTIMATE),
        "forward_revenue": _m("1200", period="0y", source_type=SourceType.ANALYST_ESTIMATE),
        "revenue_estimate_1y": _m("1200", period="0y", source_type=SourceType.ANALYST_ESTIMATE),
        "revenue_estimate_2y": _m("1400", period="+1y", source_type=SourceType.ANALYST_ESTIMATE),
        "forecast_fiscal_year_end": NEXT_FY_END,
        "country": "US",
        "security_type": "COMMON_STOCK",
        "sector": "Technology",
        "industry": "Software",
        "is_profitable": True,
        "is_demo": False,
    }
    fields.update(updates)
    return CompanyFinancialSnapshot(**fields)


@pytest.mark.parametrize(
    ("period", "slot", "anchor", "expected"),
    [
        ("0y", 1, NEXT_FY_END, True),
        ("+1y", 2, NEXT_FY_END, True),
        ("1y", 2, NEXT_FY_END, True),
        ("forward_1y", 1, NEXT_FY_END, True),
        ("forward_2y", 2, NEXT_FY_END, True),
        ("FY1E", 1, NEXT_FY_END, True),
        ("FY2E", 2, NEXT_FY_END, True),
        ("0y", 1, None, False),
        ("+1y", 1, NEXT_FY_END, False),
        ("forward_2y", 1, NEXT_FY_END, False),
        ("NTM", 1, NEXT_FY_END, False),
        ("TTM", 1, NEXT_FY_END, False),
        ("FY2027E", 1, NEXT_FY_END, False),
        ("FY2028E", 2, NEXT_FY_END, False),
    ],
)
def test_explicit_fy_period_parser_accepts_anchored_relative_labels(
    period: str,
    slot: int,
    anchor: date | None,
    expected: bool,
):
    metric = _m("100", period=period, source_type=SourceType.ANALYST_ESTIMATE)
    assert _is_explicit_fy_metric(metric, slot, anchor) is expected


def test_anchored_relative_revenue_drivers_reach_dcf_and_reconcile_inputs():
    snapshot = _snapshot()
    assumptions = ValuationAssumptions()

    projection = derive_request_projections(snapshot, assumptions)
    assert projection.dcf_fcff_1y is not None
    assert projection.dcf_fcff_2y is not None
    assert [item["period"] for item in projection.financial_bridge["dcf_forecasts"]] == ["FY1E", "FY2E"]

    dcf = run_all_engines(snapshot, assumptions)["dcf"]
    assert dcf.available is True
    bridge_forecasts = projection.financial_bridge["dcf_forecasts"]
    for forecast in bridge_forecasts:
        engine_metric = dcf.input_metrics["forward_fcff_%sy" % forecast["year"]]
        assert forecast["value"] == engine_metric["value"]
        assert forecast["period"] == engine_metric["period"]
        assert forecast["as_of"] == engine_metric["as_of"]


def test_missing_fy2_does_not_reopen_historical_growth_fallback():
    snapshot = _snapshot(
        revenue_estimate_2y=None,
        forward_eps_2y=None,
        fcff_ttm=_m("700", source_type=SourceType.ACTUAL),
    )
    assumptions = ValuationAssumptions()

    projection = derive_request_projections(snapshot, assumptions)
    assert projection.dcf_fcff_1y is not None
    assert projection.dcf_fcff_2y is None

    dcf = run_all_engines(snapshot, assumptions)["dcf"]
    assert dcf.available is False
    assert "No FCFF data" in (dcf.unavailable_reason or "")
    assert "historical" not in " ".join(dcf.calculation_steps).lower()


def test_nonpositive_projected_fcff_does_not_reopen_historical_fallback():
    snapshot = _snapshot(capex_ttm=_m("1000"), fcff_ttm=_m("700", source_type=SourceType.ACTUAL))
    assumptions = ValuationAssumptions()

    projection = derive_request_projections(snapshot, assumptions)
    assert projection.dcf_fcff_1y is not None and projection.dcf_fcff_1y.value < 0
    assert projection.dcf_fcff_2y is not None and projection.dcf_fcff_2y.value < 0

    dcf = run_all_engines(snapshot, assumptions)["dcf"]
    assert dcf.available is False
    assert "No FCFF data" in (dcf.unavailable_reason or "")
    assert "historical" not in " ".join(dcf.calculation_steps).lower()
    assert not any("fcff" in key for key in dcf.input_metrics)


def test_relative_labels_without_fiscal_anchor_remain_isolated():
    snapshot = _snapshot(
        forecast_fiscal_year_end=None,
        fcff_ttm=_m("700", source_type=SourceType.ACTUAL),
    )
    projection = derive_request_projections(snapshot, ValuationAssumptions())
    assert projection.dcf_fcff_1y is None
    assert projection.dcf_fcff_2y is None
    dcf = run_all_engines(snapshot, ValuationAssumptions())["dcf"]
    assert dcf.available is False
    assert "No FCFF data" in (dcf.unavailable_reason or "")
