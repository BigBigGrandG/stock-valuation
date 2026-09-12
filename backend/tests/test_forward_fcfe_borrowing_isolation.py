"""Regression coverage for forward FCFE borrowing provenance.

Historical ``net_borrowing_ttm`` is a display/audit fact.  It must not become
the forward FCFE debt-flow driver unless a request override or explicit
provider forward metric supplies the forecast value.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from app.engines.fcf_yield import run_fcf_yield
from app.models.domain import CompanyFinancialSnapshot, FinancialMetric, SourceType, ValuationAssumptions
from app.providers.base import FinancialDataProvider
from app.providers.statement_aggregator import aggregate_ttm_cashflow
from app.services.projections import derive_request_projections


AS_OF = date(2026, 9, 12)
NEXT_FY_END = date(2026, 12, 31)


def _metric(
    value: object,
    *,
    period: str = "TTM",
    source_type: SourceType = SourceType.DERIVED,
    unit: str = "USD",
    notes: str | None = None,
) -> FinancialMetric:
    return FinancialMetric(
        value=Decimal(str(value)),
        unit=unit,
        period=period,
        source="forward-borrowing-test",
        source_type=source_type,
        as_of=AS_OF,
        confidence=0.9,
        is_estimated=source_type != SourceType.ACTUAL,
        notes=notes,
    )


def _snapshot(**updates: object) -> CompanyFinancialSnapshot:
    fields: dict[str, object] = {
        "ticker": "BORROW",
        "company_name": "Borrowing Test Co",
        "currency": "USD",
        "current_price": _metric("100", period="2026-09-12", source_type=SourceType.ACTUAL),
        "price_timestamp": datetime(2026, 9, 12, 12, 0),
        "diluted_shares": _metric("1000", unit="shares", source_type=SourceType.ACTUAL),
        "cash": _metric("100", source_type=SourceType.ACTUAL),
        "total_debt": _metric("200", source_type=SourceType.ACTUAL),
        "revenue_ttm": _metric("1000"),
        "ebitda_ttm": _metric("200"),
        "eps_ttm": _metric("5", unit="USD/share"),
        "tax_rate": _metric("0.20", unit="ratio"),
        "capex_ttm": _metric("50"),
        "nwc_change_ttm": _metric("10"),
        "da_ttm": _metric("30"),
        "interest_ttm": _metric("20"),
        "net_borrowing_ttm": _metric("500", notes="Historical TTM only"),
        "revenue_estimate_1y": _metric("1200", period="0y", source_type=SourceType.ANALYST_ESTIMATE),
        "revenue_estimate_2y": _metric("1400", period="+1y", source_type=SourceType.ANALYST_ESTIMATE),
        "forward_eps_1y": _metric("6", period="0y", source_type=SourceType.ANALYST_ESTIMATE),
        "forward_eps_2y": _metric("7", period="+1y", source_type=SourceType.ANALYST_ESTIMATE),
        "forecast_fiscal_year_end": NEXT_FY_END,
        "country": "US",
        "security_type": "COMMON_STOCK",
        "sector": "Technology",
        "industry": "Software",
        "is_profitable": True,
    }
    fields.update(updates)
    return CompanyFinancialSnapshot(**fields)


def _bridge(snapshot: CompanyFinancialSnapshot, assumptions: ValuationAssumptions | None = None):
    projection = derive_request_projections(snapshot, assumptions or ValuationAssumptions())
    assert projection.financial_bridge is not None
    return projection, projection.financial_bridge


def test_case_a_ttm_borrowing_is_not_used_and_missing_forward_normalizes_zero():
    projection, bridge = _bridge(_snapshot())

    assert projection.forward_net_borrowing is None
    assert projection.forward_net_borrowing_status == "missing_normalized_zero"
    assert Decimal(bridge["forward_net_borrowing"]) == Decimal("0")
    assert Decimal(bridge["net_borrowing"]) == Decimal("0")
    assert Decimal(bridge["historical_net_borrowing"]) == Decimal("500")
    assert bridge["historical_net_borrowing_period"] == "TTM"
    assert bridge["forward_net_borrowing_period"] == "forward_unavailable"
    assert any("TTM" in warning and "display-only" in warning for warning in projection.warnings)
    assert "500" not in (projection.forward_fcfe_1y.source if projection.forward_fcfe_1y else "")


def test_case_b_user_forward_override_is_the_only_debt_flow_used():
    projection, bridge = _bridge(
        _snapshot(),
        ValuationAssumptions(driver_net_borrowing=Decimal("123")),
    )

    assert projection.forward_net_borrowing_status == "user_override"
    assert Decimal(bridge["forward_net_borrowing"]) == Decimal("123")
    assert Decimal(bridge["net_borrowing"]) == Decimal("123")
    assert bridge["forward_net_borrowing_source"] == "user_override"
    assert bridge["forward_net_borrowing_period"] == "forward_user_override"
    assert bridge["historical_net_borrowing"] == "500"


def test_case_c_explicit_provider_forward_borrowing_is_used_with_metadata():
    provider_forward = _metric(
        "321",
        period="FY2026E",
        source_type=SourceType.ANALYST_ESTIMATE,
        notes="Explicit provider forward net borrowing; not derived from TTM.",
    )
    snapshot = _snapshot().model_copy(update={"forward_net_borrowing_1y": provider_forward})
    projection, bridge = _bridge(snapshot)

    assert projection.forward_net_borrowing is not None
    assert projection.forward_net_borrowing_status == "provider_forward"
    assert projection.forward_net_borrowing.period == "FY2026E"
    assert Decimal(bridge["forward_net_borrowing"]) == Decimal("321")
    assert Decimal(bridge["net_borrowing"]) == Decimal("321")
    assert bridge["forward_net_borrowing_source"] == "provider_forward"
    assert Decimal(bridge["historical_net_borrowing"]) == Decimal("500")


def test_provider_boundary_carries_explicit_forward_borrowing_without_ttm_fallback():
    attached = FinancialDataProvider._attach_forward_borrowing(
        _snapshot(),
        {
            "net_borrowing": Decimal("500"),
            "period": "TTM",
            "as_of": AS_OF,
            "forward_net_borrowing_1y": Decimal("321"),
            "forward_net_borrowing_1y_period": "FY2026E",
            "forward_net_borrowing_1y_source": "provider replay",
            "forward_net_borrowing_1y_source_type": "provider_forward",
            "forward_net_borrowing_1y_as_of": AS_OF,
            "forward_net_borrowing_1y_currency": "USD",
            "forward_net_borrowing_1y_notes": "Explicit provider replay; not TTM.",
        },
        {},
    )
    projection, bridge = _bridge(attached)

    assert projection.forward_net_borrowing is not None
    assert projection.forward_net_borrowing.value == Decimal("321")
    assert Decimal(bridge["forward_net_borrowing"]) == Decimal("321")
    assert Decimal(bridge["historical_net_borrowing"]) == Decimal("500")


def test_historical_ttm_fallback_is_not_high_quality_forward_fcfe():
    snapshot = _snapshot(
        revenue_estimate_1y=None,
        revenue_estimate_2y=None,
        forward_eps_1y=None,
        forward_eps_2y=None,
        fcf_ttm=_metric("900", notes="Historical FCFE TTM"),
    )
    result = run_fcf_yield(snapshot, ValuationAssumptions())

    assert result.available
    assert result.data_quality.value == "LOW"
    assert result.inputs["forward_fcfe_is_historical_proxy"] is True
    assert any("historical TTM FCFE" in warning for warning in result.warnings)


def test_statement_aggregator_does_not_populate_forward_borrowing_from_empty_history():
    result = aggregate_ttm_cashflow(None, None, None, None, default_as_of=AS_OF)

    assert result["net_borrowing"] is None
    assert result["forward_net_borrowing_1y"] is None
    assert result["forward_net_borrowing_2y"] is None
    assert "not promoted" in result["forward_net_borrowing_warning"]
