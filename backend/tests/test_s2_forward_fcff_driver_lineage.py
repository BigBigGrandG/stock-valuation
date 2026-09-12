"""Regression coverage for S2 forward-FCFF driver provenance and quality."""

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from app.models.domain import CompanyFinancialSnapshot, FinancialMetric, SourceType, ValuationAssumptions
from app.services.projections import calculate_ntm_weights, derive_request_projections


AS_OF = date(2026, 9, 10)
FY_END = date(2026, 12, 31)


def _metric(
    value: Decimal | str,
    *,
    unit: str = "USD",
    period: str = "TTM",
    source: str = "S2 test",
    source_type: SourceType = SourceType.ACTUAL,
    as_of: date = AS_OF,
    estimated: bool = False,
) -> FinancialMetric:
    return FinancialMetric(
        value=Decimal(str(value)),
        unit=unit,
        period=period,
        source=source,
        source_type=source_type,
        as_of=as_of,
        confidence=0.95 if not estimated else 0.75,
        is_estimated=estimated,
    )


def _snapshot(**updates: Any) -> CompanyFinancialSnapshot:
    fields: dict[str, Any] = {
        "ticker": "S2",
        "company_name": "S2 Test Co",
        "currency": "USD",
        "current_price": _metric("100", period="2026-09-10"),
        "price_timestamp": datetime(2026, 9, 10, 12, 0),
        "diluted_shares": _metric("100", unit="shares", period="latest"),
        "forecast_fiscal_year_end": FY_END,
        "revenue_ttm": _metric("1000", period="TTM"),
        "ebitda_ttm": _metric("200", period="TTM"),
        "da_ttm": _metric("50", period="TTM"),
        "capex_ttm": _metric("80", period="TTM"),
        "nwc_change_ttm": _metric("20", period="TTM"),
        "tax_rate": _metric("0.20", unit="ratio", period="TTM"),
        "interest_ttm": _metric("10", period="TTM"),
        "forward_revenue": _metric("1200", period="NTM", source_type=SourceType.ANALYST_ESTIMATE, estimated=True),
    }
    fields.update(updates)
    return CompanyFinancialSnapshot(**fields)


def test_s2_single_ttm_ratios_are_explicitly_degraded_and_traceable():
    projection = derive_request_projections(_snapshot(), ValuationAssumptions(forecast_horizon="ntm"))

    assert projection.forward_fcff_1y is not None
    bridge = projection.financial_bridge
    assert bridge is not None
    assert Decimal(bridge["ebitda"]) == Decimal("240")
    assert Decimal(bridge["da"]) == Decimal("60")
    assert Decimal(bridge["capex"]) == Decimal("96")
    assert Decimal(bridge["nwc_change"]) == Decimal("24")
    assert Decimal(bridge["tax_rate"]) == Decimal("0.20")

    driver_source = bridge["drivers_source"]
    for name in ("ebitda_margin", "da", "capex", "nwc_change"):
        assert driver_source[name]["type"] == "historical_ttm_ratio"
        assert driver_source[name]["source_type"] == SourceType.DERIVED.value
        assert driver_source[name]["is_estimated"] is True
        assert "TTM" in driver_source[name]["lineage"]
        assert driver_source[name]["period"] == "TTM"
    assert driver_source["tax_rate"]["type"] == "historical_ttm_rate"
    assert driver_source["tax_rate"]["source_type"] == SourceType.ACTUAL.value
    assert driver_source["tax_rate"]["is_estimated"] is True
    assert any("single-period TTM ratio" in warning for warning in projection.warnings)
    assert any("estimated/degraded" in warning for warning in projection.warnings)
    assert bridge["warnings"] == list(projection.warnings)


def test_s2_reliable_forward_driver_candidates_outrank_ttm_and_ntm_blend():
    snapshot = _snapshot(
        revenue_estimate_1y=_metric("1300", period="FY1E", source_type=SourceType.ANALYST_ESTIMATE, estimated=True),
        revenue_estimate_2y=_metric("1500", period="FY2E", source_type=SourceType.ANALYST_ESTIMATE, estimated=True),
    ).model_copy(
        update={
            "forward_ebitda_1y": _metric("300", period="FY1E", source_type=SourceType.ANALYST_ESTIMATE, estimated=True),
            "forward_ebitda_2y": _metric("390", period="FY2E", source_type=SourceType.ANALYST_ESTIMATE, estimated=True),
            "forward_da_1y": _metric("70", period="FY1E", source_type=SourceType.ANALYST_ESTIMATE, estimated=True),
            "forward_da_2y": _metric("90", period="FY2E", source_type=SourceType.ANALYST_ESTIMATE, estimated=True),
            "forward_capex_1y": _metric("100", period="FY1E", source_type=SourceType.ANALYST_ESTIMATE, estimated=True),
            "forward_capex_2y": _metric("120", period="FY2E", source_type=SourceType.ANALYST_ESTIMATE, estimated=True),
            "forward_nwc_change_1y": _metric("25", period="FY1E", source_type=SourceType.ANALYST_ESTIMATE, estimated=True),
            "forward_nwc_change_2y": _metric("35", period="FY2E", source_type=SourceType.ANALYST_ESTIMATE, estimated=True),
            "forward_tax_rate_1y": _metric("0.22", unit="ratio", period="FY1E", source_type=SourceType.ANALYST_ESTIMATE, estimated=True),
            "forward_tax_rate_2y": _metric("0.24", unit="ratio", period="FY2E", source_type=SourceType.ANALYST_ESTIMATE, estimated=True),
        }
    )
    projection = derive_request_projections(snapshot, ValuationAssumptions(forecast_horizon="ntm"))
    bridge = projection.financial_bridge
    assert bridge is not None
    w0, w1, _, _ = calculate_ntm_weights(AS_OF, FY_END)
    assert Decimal(bridge["ebitda"]) == (w0 * Decimal("300") + w1 * Decimal("390")).quantize(Decimal("1"))
    assert Decimal(bridge["da"]) == (w0 * Decimal("70") + w1 * Decimal("90")).quantize(Decimal("1"))
    assert Decimal(bridge["capex"]) == (w0 * Decimal("100") + w1 * Decimal("120")).quantize(Decimal("1"), ROUND_HALF_UP)
    assert Decimal(bridge["nwc_change"]) == (w0 * Decimal("25") + w1 * Decimal("35")).quantize(Decimal("1"), ROUND_HALF_UP)
    assert Decimal(bridge["tax_rate"]) == (w0 * Decimal("0.22") + w1 * Decimal("0.24")).quantize(Decimal("0.0001"), ROUND_HALF_UP)
    assert bridge["drivers_source"]["da"]["type"] in {"analyst_estimate", "forward_provider"}
    assert bridge["drivers_source"]["capex"]["type"] in {"analyst_estimate", "forward_provider"}
    assert bridge["drivers_source"]["nwc_change"]["type"] in {"analyst_estimate", "forward_provider"}
    assert bridge["drivers_source"]["tax_rate"]["type"] in {"analyst_estimate", "forward_provider"}
    assert not any("single-period TTM ratio" in warning for warning in projection.warnings)


def test_s2_multi_period_history_beats_ttm_ratio_and_keeps_periods():
    snapshot = _snapshot().model_copy(
        update={
            "historical_driver_ratios": {
                "ebitda_margin": [
                    _metric("0.18", unit="ratio", period="FY2024"),
                    _metric("0.22", unit="ratio", period="FY2025"),
                ],
                "da": [
                    _metric("0.06", unit="ratio", period="FY2024"),
                    _metric("0.08", unit="ratio", period="FY2025"),
                ],
                "capex": [
                    _metric("0.09", unit="ratio", period="FY2024"),
                    _metric("0.11", unit="ratio", period="FY2025"),
                ],
                "nwc_change": [
                    _metric("0.01", unit="ratio", period="FY2024"),
                    _metric("0.03", unit="ratio", period="FY2025"),
                ],
                "tax_rate": [
                    _metric("0.19", unit="ratio", period="FY2024"),
                    _metric("0.21", unit="ratio", period="FY2025"),
                ],
            }
        }
    )
    projection = derive_request_projections(snapshot, ValuationAssumptions(forecast_horizon="ntm"))
    bridge = projection.financial_bridge
    assert bridge is not None
    assert Decimal(bridge["ebitda_margin"]) == Decimal("0.2000")
    assert Decimal(bridge["da"]) == Decimal("84")
    assert Decimal(bridge["capex"]) == Decimal("120")
    assert Decimal(bridge["nwc_change"]) == Decimal("24")
    assert Decimal(bridge["tax_rate"]) == Decimal("0.2000")
    for name in ("ebitda_margin", "da", "capex", "nwc_change", "tax_rate"):
        metadata = bridge["drivers_source"][name]
        assert metadata["type"] == "historical_multiperiod"
        assert "FY2024" in metadata["period"] and "FY2025" in metadata["period"]
        assert "single-period TTM ratio" not in metadata["lineage"]
    assert not any("single-period TTM ratio" in warning for warning in projection.warnings)


def test_s2_industry_comparable_ratio_beats_ttm_when_history_missing():
    snapshot = _snapshot().model_copy(
        update={
            "industry_driver_ratios": {
                "capex": _metric(
                    "0.07",
                    unit="ratio",
                    period="2026 US industry benchmark",
                    source="Public industry capex/revenue benchmark",
                    source_type=SourceType.ACTUAL,
                )
            }
        }
    )
    projection = derive_request_projections(snapshot, ValuationAssumptions(forecast_horizon="ntm"))
    bridge = projection.financial_bridge
    assert bridge is not None
    assert Decimal(bridge["capex"]) == Decimal("84")
    metadata = bridge["drivers_source"]["capex"]
    assert metadata["type"] == "industry_comparable"
    assert metadata["source"] == "Public industry capex/revenue benchmark"
    assert metadata["period"] == "2026 US industry benchmark"
    assert metadata["is_estimated"] is True
    assert not any("capex" in warning.lower() and "single-period ttm ratio" in warning.lower() for warning in projection.warnings)


def test_s2_industry_ebitda_margin_is_used_before_ttm_margin():
    snapshot = _snapshot().model_copy(
        update={
            "industry_driver_ratios": {
                "ebitda_margin": _metric(
                    "0.28",
                    unit="ratio",
                    period="2026 US industry benchmark",
                    source="Public industry EBITDA margin benchmark",
                    source_type=SourceType.ACTUAL,
                )
            }
        }
    )
    projection = derive_request_projections(snapshot, ValuationAssumptions(forecast_horizon="ntm"))
    bridge = projection.financial_bridge
    assert bridge is not None
    assert Decimal(bridge["ebitda_margin"]) == Decimal("0.28")
    metadata = bridge["drivers_source"]["ebitda_margin"]
    assert metadata["type"] == "industry_comparable"
    assert metadata["source"] == "Public industry EBITDA margin benchmark"
    assert metadata["is_estimated"] is True
    assert not any("ebitda margin" in warning.lower() and "ttm ratio" in warning.lower() for warning in projection.warnings)


def test_s2_missing_driver_stays_unavailable_without_zero_fill():
    snapshot = _snapshot(da_ttm=None, capex_ttm=None, nwc_change_ttm=None)
    projection = derive_request_projections(snapshot, ValuationAssumptions(forecast_horizon="ntm"))
    bridge = projection.financial_bridge
    assert bridge is not None
    assert bridge["da"] is None
    assert bridge["capex"] is None
    assert bridge["nwc_change"] is None
    assert projection.forward_fcff_1y is None
    assert bridge["drivers_source"]["da"]["type"] == "unavailable"
    assert bridge["drivers_source"]["capex"]["type"] == "unavailable"
    assert any("no value was fabricated" in warning.lower() for warning in projection.warnings)


def test_s2_metadata_poor_history_does_not_become_synthetic_multi_period_evidence():
    snapshot = _snapshot(
        historical_driver_ratios={
            "capex": [
                {"value": "0.05", "period": "FY2024"},
                {"value": "0.06", "period": "FY2025"},
            ]
        }
    )
    projection = derive_request_projections(snapshot, ValuationAssumptions(forecast_horizon="ntm"))
    bridge = projection.financial_bridge
    assert bridge is not None
    assert bridge["drivers_source"]["capex"]["type"] == "historical_ttm_ratio"
    assert any("capex" in warning.lower() and "single-period ttm ratio" in warning.lower() for warning in projection.warnings)
