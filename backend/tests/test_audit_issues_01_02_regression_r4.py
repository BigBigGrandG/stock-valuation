"""R4 regression tests for the 01/02 continuation boundary.

These tests intentionally exercise the projection -> engine and provider ->
normalizer -> projection seams that were still unverified after R3.
"""
from datetime import date, datetime
from decimal import Decimal

from app.models.domain import CompanyFinancialSnapshot, FinancialMetric, SourceType, ValuationAssumptions
from app.services.projections import derive_request_projections
from app.services.valuation_service import Normalizer, run_all_engines


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
        source="r4-test",
        source_type=source_type,
        as_of=as_of,
        confidence=1.0,
        is_estimated=source_type != SourceType.ACTUAL,
    )


def _snapshot(**updates: object) -> CompanyFinancialSnapshot:
    fields: dict[str, object] = {
        "ticker": "R4",
        "company_name": "R4 Test Co",
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
    }
    fields.update(updates)
    return CompanyFinancialSnapshot(**fields)


def test_r4_run_all_engines_clears_stale_nonconsensus_values_when_projection_fails():
    """A failed bridge must not let stale derived fields re-enter any engine."""
    snapshot = _snapshot(
        revenue_ttm=None,
        ebitda_ttm=None,
        da_ttm=None,
        capex_ttm=None,
        nwc_change_ttm=None,
        interest_ttm=None,
        net_borrowing_ttm=None,
        revenue_estimate_1y=None,
        revenue_estimate_2y=None,
        forward_revenue=None,
        forward_ebitda_1y=_m("999", period="FY2027E"),
        forward_ebitda_2y=_m("1000", period="FY2028E"),
        forward_fcf_1y=_m("888", period="FY2027E"),
        forward_fcff_1y=_m("777", period="FY2027E"),
        forward_fcff_2y=_m("778", period="FY2028E"),
        fcff_ttm=_m("700"),
    )

    results = run_all_engines(snapshot, ValuationAssumptions())

    assert results["ev_ebitda"].available is False
    assert results["fcf_yield"].available is False
    assert results["dcf"].available is False
    assert "No forward EBITDA" in results["ev_ebitda"].unavailable_reason
    assert "No forward FCFE" in results["fcf_yield"].unavailable_reason
    assert "No FCFF data" in results["dcf"].unavailable_reason


def test_r4_dcf_driver_override_beats_direct_consensus_for_both_years():
    """Changing a bridge driver must change DCF explicit FY1/FY2 inputs."""
    snapshot = _snapshot(
        forward_fcff_1y=_m("900", period="FY2027E", source_type=SourceType.ANALYST_ESTIMATE),
        forward_fcff_2y=_m("1100", period="FY2028E", source_type=SourceType.ANALYST_ESTIMATE),
    )
    assumptions = ValuationAssumptions(driver_capex=Decimal("90"))

    projection = derive_request_projections(snapshot, assumptions)

    assert projection.dcf_fcff_1y is not None
    assert projection.dcf_fcff_2y is not None
    assert projection.dcf_fcff_1y.source_type == SourceType.USER_OVERRIDE
    assert projection.dcf_fcff_2y.source_type == SourceType.USER_OVERRIDE
    assert projection.dcf_fcff_1y.value != Decimal("900")
    assert projection.dcf_fcff_2y.value != Decimal("1100")


def test_r4_dcf_does_not_relabel_ntm_revenue_as_fy1_without_verified_fy1():
    """An NTM-only revenue metric is not a valid explicit DCF FY1 driver."""
    snapshot = _snapshot(
        revenue_estimate_1y=None,
        revenue_estimate_2y=_m("1400", period="FY2028E"),
        forward_revenue=_m("1200", period="NTM"),
    )

    projection = derive_request_projections(snapshot, ValuationAssumptions())

    assert projection.forward_ebitda is not None
    assert projection.dcf_fcff_1y is None
    # An independently anchored FY2 estimate may remain visible, but the
    # missing FY1 must never be synthesized from the NTM revenue amount.
    assert projection.dcf_fcff_2y is not None
    assert projection.dcf_fcff_2y.period == "FY2E"


def test_r4_annual_da_metadata_survives_normalizer_and_is_not_scaled_as_ttm_ratio():
    """Annual fallback D&A remains FY-dated through normalization and bridge."""
    normalizer = Normalizer(strict_profile=False, allow_all_equities=True)
    as_of = date(2026, 6, 30)
    annual_da_date = date(2025, 12, 31)
    snapshot = normalizer.normalize_provider_data(
        "DA",
        {"price": Decimal("100"), "currency": "USD", "as_of": as_of, "source": "r4"},
        {
            "name": "DA Test Co",
            "diluted_shares": Decimal("1000"),
            "currency": "USD",
            "country": "US",
            "exchange": "NYSE",
            "market": "us_market",
            "security_type": "EQUITY",
            "is_profitable": True,
            "as_of": as_of,
            "source": "r4",
        },
        {"cash": Decimal("100"), "total_debt": Decimal("200"), "period": "Q_2026-06-30", "as_of": as_of, "source": "r4"},
        {
            "cfo": Decimal("300"),
            "capex": Decimal("50"),
            "nwc_change": Decimal("10"),
            "interest": Decimal("20"),
            "net_borrowing": Decimal("5"),
            "period": "TTM",
            "as_of": as_of,
            "source": "r4",
        },
        {
            "revenue_ttm": Decimal("1000"),
            "ebitda_ttm": Decimal("200"),
            "eps_ttm": Decimal("5"),
            "da": Decimal("15"),
            "da_period": "FY2025",
            "da_as_of": annual_da_date,
            "period": "TTM",
            "as_of": as_of,
            "source": "r4",
        },
        {
            "forward_revenue_1y": Decimal("1200"),
            "forward_revenue_2y": Decimal("1400"),
            "period_1y": "FY2027E",
            "period_2y": "FY2028E",
            "as_of": as_of,
            "source": "r4",
        },
        {"period": "historical", "as_of": as_of, "source": "r4"},
    )
    assert snapshot.da_ttm is not None
    assert snapshot.da_ttm.period == "FY2025"
    assert snapshot.da_ttm.as_of == annual_da_date

    projection = derive_request_projections(snapshot, ValuationAssumptions())
    assert projection.financial_bridge is not None
    assert projection.financial_bridge["da"] == "15"
    assert projection.financial_bridge["drivers_source"]["da"]["period"] == "FY2025"


def test_r4_bridge_checks_fcff_and_fcfe_consensus_reconciliation_separately():
    """Independent FCFF/FCFE consensus gaps are both visible and not identity=True."""
    snapshot = _snapshot(
        forward_fcff_1y=_m("900", period="FY2027E", source_type=SourceType.ANALYST_ESTIMATE),
        forward_fcf_1y=_m("1234", period="FY2027E", source_type=SourceType.ANALYST_ESTIMATE),
    )

    projection = derive_request_projections(snapshot, ValuationAssumptions())
    bridge = projection.financial_bridge

    assert bridge is not None
    assert bridge["bridge_fcff"] is not None
    assert bridge["bridge_fcfe"] is not None
    assert bridge["fcff_identity_holds"] is False
    assert bridge["fcfe_identity_holds"] is False
    assert bridge["identity_holds"] is False
    assert bridge["reconciliation_difference"] != "0"
    assert bridge["fcfe_reconciliation_difference"] != "0"
