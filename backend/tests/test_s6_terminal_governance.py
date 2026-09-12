"""S6 regression tests for post-calculation DCF terminal governance."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.engines.dcf import run_dcf
from app.engines.terminal_governance import (
    TERMINAL_VALUE_CONCENTRATION_THRESHOLD,
    apply_terminal_governance,
)
from app.models.domain import (
    CompanyFinancialSnapshot,
    DataQuality,
    DCFScenario,
    DCFSensitivityMatrix,
    FinancialMetric,
    ModelValuation,
    PriceEstimate,
    SourceType,
    ValuationAssumptions,
)


AS_OF = date(2025, 1, 1)


def _metric(value: str, *, source_type: SourceType = SourceType.FIXTURE, period: str = "TTM") -> FinancialMetric:
    return FinancialMetric(
        value=Decimal(value),
        unit="USD",
        period=period,
        source="S6 test fixture",
        source_type=source_type,
        as_of=AS_OF,
        is_estimated=source_type != SourceType.ACTUAL,
    )


def _snapshot(*, is_demo: bool = False) -> CompanyFinancialSnapshot:
    return CompanyFinancialSnapshot(
        ticker="S6TEST",
        company_name="S6 Test Company",
        current_price=_metric("100", period="quote"),
        price_timestamp=datetime(2025, 1, 1),
        diluted_shares=_metric("1", period="shares"),
        cash=_metric("0"),
        total_debt=_metric("0"),
        forward_fcff_1y=_metric("100", source_type=SourceType.ANALYST_ESTIMATE, period="FY2025E"),
        is_demo=is_demo,
    )


def _scenario(name: str, pv_terminal_value: str, enterprise_value: str) -> DCFScenario:
    pvtv = Decimal(pv_terminal_value)
    ev = Decimal(enterprise_value)
    return DCFScenario(
        scenario=name,  # type: ignore[arg-type]
        wacc=Decimal("0.10"),
        terminal_growth=Decimal("0.03"),
        fcff_year1=Decimal("100"),
        fcff_projections=[Decimal("100")] * 5,
        pv_projections=[Decimal("10")] * 5,
        terminal_value=pvtv,
        pv_terminal_value=pvtv,
        enterprise_value=ev,
        total_debt=Decimal("0"),
        cash=Decimal("0"),
        net_debt=Decimal("0"),
        equity_value=ev,
        diluted_shares=Decimal("1"),
        price_per_share=ev,
        upside_pct=Decimal("0"),
        premium_discount_pct=Decimal("0"),
    )


def _assumption_metric(value: Decimal, source_type: SourceType, source: str) -> dict:
    return FinancialMetric(
        value=value,
        unit="rate",
        period="valuation assumption",
        source=source,
        source_type=source_type,
        as_of=AS_OF,
        confidence=1.0 if source_type == SourceType.USER_OVERRIDE else 0.8,
        is_estimated=source_type != SourceType.USER_OVERRIDE,
    ).model_dump(mode="json")


def _model(
    ratios: tuple[str, str, str] = ("0.50", "0.50", "0.50"),
    *,
    source_type: SourceType = SourceType.DERIVED,
    assumption_metrics: dict | None = None,
    data_quality: DataQuality = DataQuality.HIGH,
) -> ModelValuation:
    scenarios = [
        _scenario(name, str((Decimal(ratio) * Decimal("100")).quantize(Decimal("0.01"))), "100")
        for name, ratio in zip(("bear", "base", "bull"), ratios)
    ]
    metrics = assumption_metrics
    if metrics is None:
        metrics = {}
        for scenario in scenarios:
            metrics[f"wacc_{scenario.scenario}"] = _assumption_metric(
                scenario.wacc, source_type, f"S6 {source_type.value} WACC"
            )
            metrics[f"terminal_growth_{scenario.scenario}"] = _assumption_metric(
                scenario.terminal_growth, source_type, f"S6 {source_type.value} terminal growth"
            )
    estimates = {
        "low": PriceEstimate(
            price_per_share=scenarios[0].price_per_share,
            upside_pct=Decimal("0"),
            premium_discount_pct=Decimal("0"),
        ),
        "base": PriceEstimate(
            price_per_share=scenarios[1].price_per_share,
            upside_pct=Decimal("0"),
            premium_discount_pct=Decimal("0"),
        ),
        "high": PriceEstimate(
            price_per_share=scenarios[2].price_per_share,
            upside_pct=Decimal("0"),
            premium_discount_pct=Decimal("0"),
        ),
    }
    return ModelValuation(
        formula="S6 test DCF",
        formula_description="S6 test DCF",
        inputs={"fixture": True},
        assumptions={
            "wacc_source_type": source_type.value,
            "wacc_source": source_type.value,
            "terminal_growth_source": source_type.value,
        },
        assumption_metrics=metrics,
        calculation_steps=["S6 fixture calculation"],
        low=estimates["low"],
        base=estimates["base"],
        high=estimates["high"],
        dcf_scenarios=scenarios,
        sensitivity_matrix=DCFSensitivityMatrix(
            wacc_range=[Decimal("0.10")],
            terminal_growth_range=[Decimal("0.03")],
            cells=[],
            base_tv_ratio=Decimal(ratios[1]),
        ),
        data_quality=data_quality,
    )


def test_configured_fallback_withholds_public_prices_but_keeps_structured_evidence():
    model = _model(source_type=SourceType.CONFIGURED_FALLBACK)
    result = apply_terminal_governance(model, _snapshot(), ValuationAssumptions())

    assert model.available and model.base is not None and model.dcf_scenarios is not None
    assert not result.available
    assert result.low is None and result.base is None and result.high is None
    assert result.dcf_scenarios is None and result.sensitivity_matrix is None
    assert result.data_quality == DataQuality.LOW
    assert "configured fallback" in (result.unavailable_reason or "").lower()
    governance = result.assumptions["terminal_governance"]
    assert governance["status"] == "blocked"
    assert governance["reason_code"] == "fallback_or_unknown_parameter"
    assert governance["evaluated_scenarios"] == 3
    assert len(governance["scenario_diagnostics"]) == 3
    assert governance["concentration_threshold"] == "0.75"
    assert all(Decimal(item["tv_ratio"]) == Decimal("0.5") for item in governance["scenarios"])
    # The structured record must survive the same JSON-mode serialization used
    # by the API response path.
    payload = result.model_dump(mode="json")
    assert payload["assumptions"]["terminal_governance"]["status"] == "blocked"
    assert Decimal(payload["assumptions"]["terminal_governance"]["scenarios"][0]["tv_ratio"]) == Decimal("0.5")


def test_missing_effective_provenance_is_unknown_and_fails_closed():
    model = _model(assumption_metrics={})
    model = model.model_copy(update={"assumptions": {}})
    assumptions = ValuationAssumptions.model_construct(
        dcf_wacc_source=None,
        dcf_terminal_growth_source=None,
        dcf_wacc_source_label=None,
        dcf_terminal_growth_source_label=None,
    )

    result = apply_terminal_governance(model, _snapshot(), assumptions)

    assert not result.available
    governance = result.assumptions["terminal_governance"]
    assert governance["reason_code"] == "fallback_or_unknown_parameter"
    assert governance["fallback_parameters"] == []
    assert len(governance["unknown_parameters"]) == 6
    assert "unknown" in (result.unavailable_reason or "").lower()


def test_derived_source_type_cannot_override_an_explicit_fallback_source_label():
    metrics = _model(source_type=SourceType.DERIVED).assumption_metrics
    conflicted = {key: dict(value) for key, value in metrics.items()}
    for value in conflicted.values():
        value["source"] = "Configured fallback: system terminal assumption"

    model = _model(
        source_type=SourceType.DERIVED,
        assumption_metrics=conflicted,
    )
    result = apply_terminal_governance(model, _snapshot(), ValuationAssumptions())

    assert not result.available
    governance = result.assumptions["terminal_governance"]
    assert governance["reason_code"] == "fallback_or_unknown_parameter"
    assert len(governance["fallback_parameters"]) == 6
    assert all(
        item["wacc_provenance"]["status"] == "fallback"
        and item["terminal_growth_provenance"]["status"] == "fallback"
        for item in governance["scenarios"]
    )


def test_explicit_user_override_is_exception_to_conflicting_fallback_label():
    metrics = _model(source_type=SourceType.USER_OVERRIDE).assumption_metrics
    conflicted = {key: dict(value) for key, value in metrics.items()}
    for value in conflicted.values():
        value["source"] = "Configured fallback label retained for comparison"

    model = _model(
        source_type=SourceType.USER_OVERRIDE,
        assumption_metrics=conflicted,
    )
    assumptions = ValuationAssumptions(
        dcf_wacc_source=SourceType.USER_OVERRIDE,
        dcf_terminal_growth_source=SourceType.USER_OVERRIDE,
    )
    result = apply_terminal_governance(model, _snapshot(), assumptions)

    assert result.available
    governance = result.assumptions["terminal_governance"]
    assert governance["status"] == "approved"
    assert governance["fallback_parameters"] == []
    assert governance["unknown_parameters"] == []


def test_fixture_provenance_is_isolated_to_demo_snapshots():
    model = _model(source_type=SourceType.FIXTURE)
    live_result = apply_terminal_governance(model, _snapshot(is_demo=False), ValuationAssumptions())
    demo_result = apply_terminal_governance(model, _snapshot(is_demo=True), ValuationAssumptions())

    assert not live_result.available
    live_governance = live_result.assumptions["terminal_governance"]
    assert len(live_governance["unknown_parameters"]) == 6
    assert "fixture provenance" in (live_result.unavailable_reason or "").lower()
    assert demo_result.available
    demo_governance = demo_result.assumptions["terminal_governance"]
    assert demo_governance["status"] == "approved"
    assert all(
        item["wacc_provenance"]["status"] == "supported"
        and item["terminal_growth_provenance"]["status"] == "supported"
        for item in demo_governance["scenarios"]
    )


@pytest.mark.parametrize(
    ("metric_key", "claimed_value"),
    [
        ("wacc_base", "0.11"),
        ("terminal_growth_base", "NaN"),
    ],
)
def test_claimed_effective_metric_must_match_scenario_value(
    metric_key: str,
    claimed_value: str,
):
    metrics = _model(source_type=SourceType.DERIVED).assumption_metrics
    conflicted = {key: dict(value) for key, value in metrics.items()}
    conflicted[metric_key]["value"] = claimed_value
    model = _model(
        source_type=SourceType.DERIVED,
        assumption_metrics=conflicted,
    )

    result = apply_terminal_governance(model, _snapshot(), ValuationAssumptions())

    assert not result.available
    assert result.low is None and result.base is None and result.high is None
    governance = result.assumptions["terminal_governance"]
    assert governance["reason_code"] == "invalid_effective_parameter_metric"
    parameter_name = "base.wacc" if metric_key == "wacc_base" else "base.terminal_growth"
    assert any(parameter_name in item for item in governance["invalid_parameters"])
    diagnostic = next(item for item in governance["scenarios"] if item["scenario"] == "base")
    provenance_key = "wacc_provenance" if metric_key == "wacc_base" else "terminal_growth_provenance"
    assert diagnostic[provenance_key]["status"] == "invalid"
    assert diagnostic[provenance_key]["validation_error"]


def test_explicit_overrides_at_inclusive_threshold_remain_available_but_limited():
    model = _model(
        ratios=("0.75", "0.75", "0.75"),
        source_type=SourceType.USER_OVERRIDE,
    )
    assumptions = ValuationAssumptions(
        dcf_wacc_source=SourceType.USER_OVERRIDE,
        dcf_wacc_source_label="S6 user override WACC",
        dcf_terminal_growth_source=SourceType.USER_OVERRIDE,
        dcf_terminal_growth_source_label="S6 user override terminal growth",
    )

    result = apply_terminal_governance(model, _snapshot(), assumptions)

    assert result.available
    assert result.low is not None and result.base is not None and result.high is not None
    assert result.dcf_scenarios is not None and result.sensitivity_matrix is not None
    assert result.data_quality == DataQuality.MEDIUM
    governance = result.assumptions["terminal_governance"]
    assert governance["status"] == "limited"
    assert governance["reason_code"] == "high_terminal_value_concentration"
    assert governance["concentration_scenarios"] == ["bear", "base", "bull"]
    assert all(item["concentration_attention"] for item in governance["scenarios"])
    assert TERMINAL_VALUE_CONCENTRATION_THRESHOLD == Decimal("0.75")
    assert any("quality is downgraded" in warning for warning in result.warnings)


def test_supported_ratio_just_below_threshold_is_approved_without_quality_downgrade():
    model = _model(
        ratios=("0.7499", "0.7499", "0.7499"),
        source_type=SourceType.DERIVED,
    )
    result = apply_terminal_governance(model, _snapshot(), ValuationAssumptions())

    assert result.available
    assert result.data_quality == DataQuality.HIGH
    governance = result.assumptions["terminal_governance"]
    assert governance["status"] == "approved"
    assert governance["concentration_scenarios"] == []
    assert all(item["tv_ratio"] == "0.7499" for item in governance["scenarios"])


@pytest.mark.parametrize("enterprise_value", ["0", "-1"])
def test_nonpositive_enterprise_value_blocks_even_when_provenance_is_supported(enterprise_value: str):
    scenarios = [
        _scenario(name, "75", enterprise_value)
        for name in ("bear", "base", "bull")
    ]
    model = _model(source_type=SourceType.DERIVED).model_copy(update={"dcf_scenarios": scenarios})

    result = apply_terminal_governance(model, _snapshot(), ValuationAssumptions())

    assert not result.available
    assert result.low is None and result.dcf_scenarios is None
    governance = result.assumptions["terminal_governance"]
    assert governance["reason_code"] == "invalid_terminal_value_inputs"
    assert governance["evaluated_scenarios"] == 3
    assert set(governance["invalid_scenarios"]) == {"bear", "base", "bull"}
    assert all(
        any("enterprise value must be positive" in reason for reason in item["invalid_reasons"])
        for item in governance["scenarios"]
    )


def test_one_invalid_scenario_does_not_short_circuit_other_scenario_evaluations():
    scenarios = [
        _scenario("bear", "75", "100"),
        _scenario("base", "75", "0"),
        _scenario("bull", "75", "100"),
    ]
    model = _model(source_type=SourceType.DERIVED).model_copy(update={"dcf_scenarios": scenarios})

    result = apply_terminal_governance(model, _snapshot(), ValuationAssumptions())

    assert not result.available
    governance = result.assumptions["terminal_governance"]
    assert governance["evaluated_scenarios"] == 3
    assert governance["invalid_scenarios"] == ["base"]
    assert governance["concentration_scenarios"] == ["bear", "bull"]
    assert [item["scenario"] for item in governance["scenarios"]] == ["bear", "base", "bull"]


def test_real_dcf_with_configured_wacc_and_growth_fallback_is_blocked():
    model = run_dcf(_snapshot(), ValuationAssumptions())
    # run_dcf is integrated with the helper; do not apply governance a second
    # time in this direct-path check.
    assert not model.available
    assert model.assumptions["terminal_governance"]["fallback_parameters"]
    assert model.low is None and model.base is None and model.high is None
    assert model.dcf_scenarios is None and model.sensitivity_matrix is None


def test_real_dcf_with_explicit_wacc_and_growth_overrides_remains_publishable():
    assumptions = ValuationAssumptions(
        dcf_wacc=ValuationAssumptions().dcf_wacc,
        dcf_terminal_growth=ValuationAssumptions().dcf_terminal_growth,
        dcf_wacc_source=SourceType.USER_OVERRIDE,
        dcf_wacc_source_label="S6 user override WACC",
        dcf_terminal_growth_source=SourceType.USER_OVERRIDE,
        dcf_terminal_growth_source_label="S6 user override terminal growth",
    )
    model = run_dcf(_snapshot(), assumptions)
    assert model.available

    # The integrated run_dcf result is already governed; no second helper
    # invocation is allowed in this acceptance check.
    governance = model.assumptions["terminal_governance"]
    assert governance["fallback_parameters"] == []
    assert governance["unknown_parameters"] == []
    assert model.low is not None and model.base is not None and model.high is not None


def test_integrated_run_dcf_and_api_serialization_apply_governance_once():
    model = run_dcf(_snapshot(), ValuationAssumptions())
    assert not model.available
    assert sum("Terminal governance:" in step for step in model.calculation_steps) == 1

    payload = model.model_dump(mode="json")
    assert payload["assumptions"]["terminal_governance"]["status"] == "blocked"
    assert payload["low"] is None
    assert payload["dcf_scenarios"] is None
    assert payload["sensitivity_matrix"] is None
    assert payload["assumption_metrics"]["wacc_base"]["source_type"] == "configured_fallback"

    response = TestClient(__import__("app.main", fromlist=["app"]).app).get(
        "/api/v1/valuation/AVGO?provider=demo"
    )
    assert response.status_code == 200
    api_dcf = response.json()["valuations"]["dcf"]
    assert api_dcf["available"] is False
    assert api_dcf["low"] is None
    assert api_dcf["base"] is None
    assert api_dcf["high"] is None
    assert api_dcf["dcf_scenarios"] is None
    assert api_dcf["sensitivity_matrix"] is None
    assert api_dcf["assumptions"]["terminal_governance"]["status"] == "blocked"
    assert api_dcf["assumption_metrics"]["wacc_base"]["source_type"] == "configured_fallback"
    assert sum("Terminal governance:" in step for step in api_dcf["calculation_steps"]) == 1
