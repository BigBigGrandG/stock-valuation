"""S3 regression coverage for configured-parameter governance.

The configured P/E, EV/EBITDA and FCFE-yield values are request defaults, not
company evidence.  They must fail closed at direct engine seams while
source-backed selections and explicit user scenarios remain independent.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import DEFAULT_ASSUMPTIONS
from app.engines.ev_ebitda import run_ev_ebitda
from app.engines.fcf_yield import run_fcf_yield
from app.engines.forward_pe import run_forward_pe
from app.engines.parameter_governance import govern_parameter
from app.main import app
from app.models.domain import (
    CompanyFinancialSnapshot,
    FinancialMetric,
    ScenarioValues,
    SourceType,
    ValuationAssumptions,
)
from app.services.valuation_service import ValuationService


AS_OF = date(2026, 9, 11)


def _metric(
    value: str,
    *,
    unit: str = "USD",
    period: str = "FY2026E",
    source: str = "analyst consensus",
    source_type: SourceType = SourceType.ANALYST_ESTIMATE,
    estimated: bool = True,
    notes: str | None = None,
) -> FinancialMetric:
    return FinancialMetric(
        value=Decimal(value),
        unit=unit,
        period=period,
        source=source,
        source_type=source_type,
        as_of=AS_OF,
        is_estimated=estimated,
        notes=notes,
    )


def _snapshot(
    *,
    historical_pe: FinancialMetric | None = None,
    historical_ev: FinancialMetric | None = None,
    is_demo: bool = False,
) -> CompanyFinancialSnapshot:
    current = _metric("100", period="valuation date", source="quote", source_type=SourceType.ACTUAL, estimated=False)
    shares = _metric("1000000", unit="shares", period="latest", source="balance sheet", source_type=SourceType.ACTUAL, estimated=False)
    return CompanyFinancialSnapshot(
        ticker="S3TEST",
        company_name="S3 Governance Test",
        currency="USD",
        financial_currency="USD",
        current_price=current,
        price_timestamp=datetime(2026, 9, 11, 20, 0, tzinfo=timezone.utc),
        diluted_shares=shares,
        cash=_metric("1000000", period="latest", source="balance sheet", source_type=SourceType.ACTUAL, estimated=False),
        total_debt=_metric("2000000", period="latest", source="balance sheet", source_type=SourceType.ACTUAL, estimated=False),
        forward_eps_1y=_metric("5", unit="USD/share"),
        forward_ebitda_1y=_metric("10000000"),
        forward_fcf_1y=_metric("8000000", notes="Explicit forward FCFE"),
        historical_forward_pe=historical_pe,
        historical_ev_ebitda=historical_ev,
        sector="Technology",
        industry="Software",
        country="US",
        exchange="NMS",
        market="us_market",
        security_type="COMMON_STOCK",
        is_profitable=True,
        is_demo=is_demo,
    )


@pytest.mark.parametrize(
    ("runner", "history_field"),
    [
        (run_forward_pe, "historical_forward_pe"),
        (run_ev_ebitda, "historical_ev_ebitda"),
    ],
)
def test_direct_multiple_engines_reject_configured_fallback(runner, history_field):
    snapshot = _snapshot()
    result = runner(snapshot, ValuationAssumptions())

    assert result.available is False
    assert result.low is None and result.base is None and result.high is None
    assert "configured fallback" in (result.unavailable_reason or "").lower()
    assert result.assumptions["governance"] == "configured_fallback_rejected"
    source_key = "pe_source" if history_field == "historical_forward_pe" else "source"
    assert result.assumptions[source_key] == SourceType.CONFIGURED_FALLBACK
    assert result.input_metrics


def test_direct_fcf_yield_rejects_configured_fallback_and_keeps_forward_lineage():
    result = run_fcf_yield(_snapshot(), ValuationAssumptions())

    assert result.available is False
    assert result.low is None and result.base is None and result.high is None
    assert "configured fallback" in (result.unavailable_reason or "").lower()
    assert result.assumptions["yield_source"] == "fallback"
    assert result.assumptions["governance"] == "configured_fallback_rejected"
    assert result.input_metrics["forward_fcfe"]["period"] == "FY2026E"
    assert result.input_metrics["forward_fcfe"]["source_type"] == SourceType.ANALYST_ESTIMATE


def test_application_default_assumptions_are_rejected_at_direct_engine_seams():
    snapshot = _snapshot()

    for result in (
        run_forward_pe(snapshot, DEFAULT_ASSUMPTIONS),
        run_ev_ebitda(snapshot, DEFAULT_ASSUMPTIONS),
        run_fcf_yield(snapshot, DEFAULT_ASSUMPTIONS),
    ):
        assert result.available is False
        assert result.base is None
        assert result.assumptions["governance"] == "configured_fallback_rejected"


def test_reliable_selected_multiples_remain_available_independently():
    snapshot = _snapshot(
        historical_pe=_metric(
            "20",
            unit="ratio",
            period="5Y median",
            source="audited company history",
            source_type=SourceType.ACTUAL,
            estimated=False,
        )
    )
    assumptions = ValuationAssumptions()

    pe = run_forward_pe(snapshot, assumptions)
    ev = run_ev_ebitda(snapshot, assumptions)

    assert pe.available is True
    assert pe.assumptions["multiple_source"] == "historical"
    assert ev.available is False
    assert ev.assumptions["governance"] == "configured_fallback_rejected"


def test_explicit_user_overrides_remain_usable_for_each_independent_model():
    snapshot = _snapshot()
    assumptions = ValuationAssumptions(
        pe_target=ScenarioValues(low=Decimal("18"), base=Decimal("20"), high=Decimal("22")),
        pe_source=SourceType.USER_OVERRIDE,
        pe_source_label="User override",
        ev_ebitda_multiple=ScenarioValues(low=Decimal("18"), base=Decimal("22"), high=Decimal("26")),
        ev_ebitda_source=SourceType.USER_OVERRIDE,
        ev_ebitda_source_label="User override",
        fcf_yield=ScenarioValues(low=Decimal("0.055"), base=Decimal("0.05"), high=Decimal("0.045")),
        fcf_yield_source=SourceType.USER_OVERRIDE,
        fcf_yield_source_label="User override",
    )

    for result in (
        run_forward_pe(snapshot, assumptions),
        run_ev_ebitda(snapshot, assumptions),
        run_fcf_yield(snapshot, assumptions),
    ):
        assert result.available is True
        assert result.base is not None
        assert not any("configured fallback" in warning.lower() for warning in result.warnings)


def test_industry_selected_parameters_are_not_treated_as_system_fallback():
    snapshot = _snapshot()
    assumptions = ValuationAssumptions(
        pe_target=ScenarioValues(low=Decimal("18"), base=Decimal("20"), high=Decimal("22")),
        pe_source=SourceType.DERIVED,
        pe_source_label="Industry benchmark P/E=20x",
        pe_selection_layer="industry",
        ev_ebitda_multiple=ScenarioValues(low=Decimal("18"), base=Decimal("22"), high=Decimal("26")),
        ev_ebitda_source=SourceType.DERIVED,
        ev_ebitda_source_label="Industry benchmark EV/EBITDA=22x",
        ev_ebitda_selection_layer="industry",
        fcf_yield=ScenarioValues(low=Decimal("0.055"), base=Decimal("0.05"), high=Decimal("0.045")),
        fcf_yield_source=SourceType.DERIVED,
        fcf_yield_source_label="Validated FCFE-yield benchmark",
    )

    assert run_forward_pe(snapshot, assumptions).available is True
    assert run_ev_ebitda(snapshot, assumptions).available is True
    assert run_fcf_yield(snapshot, assumptions).available is True


def test_fallback_source_cannot_be_rescued_by_untrusted_selection_layer():
    snapshot = _snapshot()
    assumptions = ValuationAssumptions(
        pe_selection_layer="industry",
        ev_ebitda_selection_layer="industry",
    )

    pe = run_forward_pe(snapshot, assumptions)
    ev = run_ev_ebitda(snapshot, assumptions)

    assert pe.available is False
    assert ev.available is False
    assert pe.assumptions["selection_layer"] == "industry"
    assert ev.assumptions["selection_layer"] == "industry"


def test_api_rejected_fallback_has_no_target_and_preserves_provenance():
    snapshot = _snapshot(
        historical_pe=_metric(
            "20",
            unit="ratio",
            period="5Y median",
            source="audited company history",
            source_type=SourceType.ACTUAL,
            estimated=False,
        ),
        historical_ev=_metric(
            "22",
            unit="ratio",
            period="5Y median",
            source="audited company history",
            source_type=SourceType.ACTUAL,
            estimated=False,
        ),
    )

    class _SnapshotDataService:
        _default_assumptions = ValuationAssumptions()

        def get_snapshot(self, ticker: str, bypass_cache: bool = False, budget=None):
            return snapshot

    service = ValuationService(_SnapshotDataService(), default_assumptions=ValuationAssumptions())
    with patch("app.main._resolve_valuation_service", return_value=service):
        response = TestClient(app).get("/api/v1/valuation/S3TEST")

    assert response.status_code == 200
    payload = response.json()
    fcf = payload["valuations"]["fcf_yield"]
    assert fcf["available"] is False
    assert fcf["low"] is None and fcf["base"] is None and fcf["high"] is None
    assert fcf["assumptions"]["source"] == "configured_fallback"
    assert fcf["assumptions"]["governance"] == "configured_fallback_rejected"
    assert fcf["assumption_metrics"]["yield_base"]["source_type"] == "configured_fallback"
    assert fcf["assumption_metrics"]["yield_base"]["period"] == "valuation assumption"
    assert "configured fallback" in fcf["unavailable_reason"].lower()
    assert payload["valuations"]["forward_pe"]["available"] is True
    assert payload["valuations"]["ev_ebitda"]["available"] is True


def test_direct_scenario_values_without_explicit_source_are_rejected():
    snapshot = _snapshot()
    assumptions = ValuationAssumptions(
        pe_target=ScenarioValues(low=Decimal("18"), base=Decimal("20"), high=Decimal("22")),
        ev_ebitda_multiple=ScenarioValues(low=Decimal("18"), base=Decimal("22"), high=Decimal("26")),
        fcf_yield=ScenarioValues(low=Decimal("0.055"), base=Decimal("0.05"), high=Decimal("0.045")),
    )

    pe = run_forward_pe(snapshot, assumptions)
    ev = run_ev_ebitda(snapshot, assumptions)
    fcf = run_fcf_yield(snapshot, assumptions)

    for result in (pe, ev, fcf):
        assert result.available is False
        assert result.low is None and result.base is None and result.high is None
        assert result.assumptions["governance"] == "configured_fallback_rejected"


@pytest.mark.parametrize(
    ("runner", "value_field", "source_field", "label_field", "layer_field", "values"),
    [
        (run_forward_pe, "pe_target", "pe_source", "pe_source_label", "pe_selection_layer", "pe"),
        (run_ev_ebitda, "ev_ebitda_multiple", "ev_ebitda_source", "ev_ebitda_source_label", "ev_ebitda_selection_layer", "ev"),
    ],
)
def test_fixture_parameter_requires_explicit_demo_snapshot(
    runner, value_field, source_field, label_field, layer_field, values
):
    source_values = ScenarioValues(
        low=Decimal("18"), base=Decimal("20"), high=Decimal("22")
    )
    assumptions = ValuationAssumptions(
        **{
            value_field: source_values,
            source_field: SourceType.FIXTURE,
            label_field: "Explicit demo fixture benchmark",
            layer_field: "demo_fixture",
        }
    )

    production_result = runner(_snapshot(is_demo=False), assumptions)
    assert production_result.available is False
    assert "fixture" in (production_result.unavailable_reason or "").lower()

    demo_result = runner(_snapshot(is_demo=True), assumptions)
    assert demo_result.available is True


def test_fixture_fcf_yield_requires_explicit_demo_snapshot():
    assumptions = ValuationAssumptions(
        fcf_yield=ScenarioValues(
            low=Decimal("0.055"), base=Decimal("0.05"), high=Decimal("0.045")
        ),
        fcf_yield_source=SourceType.FIXTURE,
        fcf_yield_source_label="Explicit demo fixture yield benchmark",
    )

    production_result = run_fcf_yield(_snapshot(is_demo=False), assumptions)
    assert production_result.available is False
    assert "fixture" in (production_result.unavailable_reason or "").lower()
    assert run_fcf_yield(_snapshot(is_demo=True), assumptions).available is True


def test_derived_parameter_with_fallback_label_is_rejected():
    assumptions = ValuationAssumptions(
        pe_target=ScenarioValues(low=Decimal("18"), base=Decimal("20"), high=Decimal("22")),
        pe_source=SourceType.DERIVED,
        pe_source_label="Configured fallback: 18x/20x/22x",
        pe_selection_layer="industry",
        ev_ebitda_multiple=ScenarioValues(low=Decimal("18"), base=Decimal("22"), high=Decimal("26")),
        ev_ebitda_source=SourceType.DERIVED,
        ev_ebitda_source_label="Configured fallback: 18x/22x/26x",
        ev_ebitda_selection_layer="industry",
    )
    snapshot = _snapshot()

    pe = run_forward_pe(snapshot, assumptions)
    ev = run_ev_ebitda(snapshot, assumptions)
    assert pe.available is False
    assert ev.available is False
    assert "configured fallback" in (pe.unavailable_reason or "").lower()
    assert "configured fallback" in (ev.unavailable_reason or "").lower()


def test_unknown_parameter_provenance_is_rejected_without_inference():
    decision = govern_parameter(
        ValuationAssumptions(),
        model_label="P/E",
        value_field="pe_target",
        source_field="pe_source",
        label_field="pe_source_label",
        layer_field="pe_selection_layer",
        source_type="vendor_guess",
        source_label="Vendor guess",
        selection_layer="industry",
        multiple_source="industry",
    )

    assert decision.available is False
    assert "unknown" in (decision.reason or "").lower()


def test_unknown_engine_provenance_returns_diagnostic_instead_of_raising():
    assumptions = ValuationAssumptions.model_construct(
        pe_target=ScenarioValues(low=Decimal("18"), base=Decimal("20"), high=Decimal("22")),
        pe_source="vendor_guess",
        pe_source_label="Vendor guess",
        pe_selection_layer="industry",
    )

    result = run_forward_pe(_snapshot(), assumptions)

    assert result.available is False
    assert result.assumption_metrics["pe_multiple_base"]["source_type"] == "vendor_guess"
    assert "unknown" in (result.unavailable_reason or "").lower()


def test_user_source_cannot_keep_a_configured_label_or_selection_layer():
    snapshot = _snapshot()
    assumptions = ValuationAssumptions(
        pe_target=ScenarioValues(low=Decimal("18"), base=Decimal("20"), high=Decimal("22")),
        pe_source=SourceType.USER_OVERRIDE,
        pe_selection_layer="company_historical",
    )

    result = run_forward_pe(snapshot, assumptions)

    assert result.available is True
    assert result.assumptions["pe_source"] == SourceType.USER_OVERRIDE
    assert result.assumptions["pe_source_label"] == "Explicit user scenario"
    assert result.assumptions["selection_layer"] == "user_override"
