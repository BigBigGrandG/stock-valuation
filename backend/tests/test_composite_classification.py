"""
test_composite_classification.py
Tests classification boundaries, MOS vs upside, partial models, weight normalization,
overrides/default isolation, bad domains, provenance, FCF definition.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from decimal import Decimal
from datetime import date, datetime
from app.models.domain import (
    CompanyFinancialSnapshot, FinancialMetric, SourceType, ValuationAssumptions,
    ScenarioValues, ModelValuation, DataQuality, PriceEstimate,
    classify_valuation, ValuationClassification, FCFType,
)
from app.engines.composite import run_composite

FIXTURE_DATE = date(2025, 1, 1)

def _m(v, u="USD") -> FinancialMetric:
    return FinancialMetric(
        value=Decimal(v), unit=u, period="TTM", source="fixture",
        source_type=SourceType.FIXTURE, as_of=FIXTURE_DATE
    )

def _estimate(price: str) -> PriceEstimate:
    return PriceEstimate(
        price_per_share=Decimal(price),
        upside_pct=Decimal("0.1"),
        premium_discount_pct=Decimal("-0.1"),
    )

def _avail_model(price_low: str, price_base: str, price_high: str) -> ModelValuation:
    return ModelValuation(
        formula="Test",
        formula_description="Test model",
        inputs={}, assumptions={}, calculation_steps=[],
        low=_estimate(price_low),
        base=_estimate(price_base),
        high=_estimate(price_high),
        available=True,
    )

def _unavail_model() -> ModelValuation:
    return ModelValuation(
        formula="Test",
        formula_description="Test",
        inputs={}, assumptions={}, calculation_steps=[],
        available=False,
        unavailable_reason="Test unavailable",
    )


# --- Classification boundary tests ---

@pytest.mark.parametrize("current,fv,expected", [
    ("80", "100", ValuationClassification.SIGNIFICANTLY_UNDERVALUED),   # ratio=0.80
    ("79", "100", ValuationClassification.SIGNIFICANTLY_UNDERVALUED),   # ratio<0.80
    ("81", "100", ValuationClassification.UNDERVALUED),                  # ratio=0.81
    ("90", "100", ValuationClassification.UNDERVALUED),                  # ratio=0.90
    ("91", "100", ValuationClassification.SLIGHTLY_UNDERVALUED),         # ratio=0.91
    ("99", "100", ValuationClassification.SLIGHTLY_UNDERVALUED),         # ratio=0.99
    ("100", "100", ValuationClassification.FAIRLY_VALUED),               # ratio=1.00 exact -> fairly_valued
    ("105", "100", ValuationClassification.FAIRLY_VALUED),               # ratio=1.05
    ("110", "100", ValuationClassification.FAIRLY_VALUED),               # ratio=1.10
    ("111", "100", ValuationClassification.OVERVALUED),                  # ratio=1.11
    ("125", "100", ValuationClassification.OVERVALUED),                  # ratio=1.25
    ("126", "100", ValuationClassification.SIGNIFICANTLY_OVERVALUED),    # ratio=1.26
])
def test_classification_boundaries(current, fv, expected):
    result = classify_valuation(Decimal(current), Decimal(fv))
    assert result == expected, f"price={current}, fv={fv}: expected {expected}, got {result}"


def test_margin_of_safety_vs_upside_downside():
    """
    margin_of_safety = (FV - price) / FV
    upside_downside  = (FV - price) / price
    These are different calculations and must not be confused.
    """
    current = Decimal("80")
    fv = Decimal("100")
    expected_mos = (fv - current) / fv        # 0.20
    expected_upside = (fv - current) / current  # 0.25
    assert expected_mos != expected_upside
    assert expected_mos == Decimal("0.20")
    assert expected_upside == Decimal("0.25")


def test_composite_margin_of_safety_correct():
    """Composite should compute correct margin_of_safety."""
    current_price = Decimal("343.83")
    model = _avail_model("300", "400", "500")
    composite = run_composite(
        current_price=current_price,
        pe_result=model,
        ev_result=_unavail_model(),
        fcf_result=_unavail_model(),
        dcf_result=_unavail_model(),
        assumptions=ValuationAssumptions(),
    )
    assert composite.available
    fv_base = composite.base
    # margin_of_safety = (FV - price) / FV
    expected_mos = ((fv_base - current_price) / fv_base).quantize(Decimal("0.0001"))
    assert composite.margin_of_safety == expected_mos
    # upside_downside = (FV - price) / price
    expected_upside = ((fv_base - current_price) / current_price).quantize(Decimal("0.0001"))
    assert composite.upside_downside == expected_upside


def test_weight_normalization_partial_models():
    """When some models unavailable, weights should be renormalized so they sum to 1."""
    assumptions = ValuationAssumptions(
        weight_pe=Decimal("0.25"),
        weight_ev_ebitda=Decimal("0.20"),
        weight_fcf_yield=Decimal("0.25"),
        weight_dcf=Decimal("0.30"),
    )
    composite = run_composite(
        current_price=Decimal("100"),
        pe_result=_avail_model("90", "110", "130"),
        ev_result=_unavail_model(),
        fcf_result=_unavail_model(),
        dcf_result=_unavail_model(),
        assumptions=assumptions,
    )
    assert composite.available
    assert composite.available_models == ["forward_pe"]
    # Renormalized weight for PE should be 1.0
    assert composite.weights_used.get("forward_pe") == Decimal("1.0000")
    assert composite.base == Decimal("110")


def test_all_models_unavailable():
    """No models available -> composite unavailable."""
    composite = run_composite(
        current_price=Decimal("100"),
        pe_result=_unavail_model(),
        ev_result=_unavail_model(),
        fcf_result=_unavail_model(),
        dcf_result=_unavail_model(),
        assumptions=ValuationAssumptions(),
    )
    assert not composite.available
    assert composite.unavailable_reason is not None


def test_all_models_weights_sum_to_one():
    """With all models available, normalized weights should sum to ~1."""
    composite = run_composite(
        current_price=Decimal("100"),
        pe_result=_avail_model("90", "110", "130"),
        ev_result=_avail_model("85", "105", "125"),
        fcf_result=_avail_model("88", "108", "128"),
        dcf_result=_avail_model("92", "112", "132"),
        assumptions=ValuationAssumptions(),
    )
    assert composite.available
    assert len(composite.available_models) == 4
    total_w = sum(composite.weights_used.values())
    assert abs(total_w - Decimal("1")) < Decimal("0.001")


def test_fcfe_not_fcff_provenance():
    """FCFE and FCFF must be distinct enum values with separate labels."""
    assert FCFType.FCFE != FCFType.FCFF
    assert FCFType.FCFE.value == "FCFE"
    assert FCFType.FCFF.value == "FCFF"


def test_financial_metric_rejects_nan():
    """FinancialMetric should reject NaN values."""
    from decimal import Decimal
    with pytest.raises(Exception):
        FinancialMetric(
            value=Decimal("NaN"), unit="USD", period="TTM",
            source="test", source_type=SourceType.FIXTURE, as_of=FIXTURE_DATE
        )


def test_financial_metric_rejects_infinity():
    """FinancialMetric should reject Infinity."""
    with pytest.raises(Exception):
        FinancialMetric(
            value=Decimal("Infinity"), unit="USD", period="TTM",
            source="test", source_type=SourceType.FIXTURE, as_of=FIXTURE_DATE
        )


def test_source_type_enum_complete():
    """SourceType enum should cover all provenance categories."""
    types = {st.value for st in SourceType}
    for required in ("actual", "analyst_estimate", "derived", "configured_fallback",
                     "user_override", "fixture"):
        assert required in types, f"Missing source type: {required}"


def test_net_debt_metric_in_snapshot():
    """normalize_snapshot should populate net_debt_metric as a FinancialMetric."""
    from app.services.valuation_service import normalize_snapshot
    snap = CompanyFinancialSnapshot(
        ticker="TEST", company_name="Test Co",
        current_price=_m("100"),
        price_timestamp=datetime(2025, 1, 1),
        diluted_shares=_m("1000000", "shares"),
        cash=_m("5000000"),
        total_debt=_m("15000000"),
        revenue_ttm=_m("20000000"),
        ebitda_ttm=_m("5000000"),
        eps_ttm=_m("5.00"),
        is_demo=True,
    )
    normalized = normalize_snapshot(snap)
    assert normalized.net_debt_metric is not None
    assert normalized.net_debt_metric.value == Decimal("10000000")
    assert normalized.net_debt_metric.source_type == SourceType.DERIVED


def test_overrides_do_not_mutate_defaults():
    """Applying overrides must not mutate DEFAULT_ASSUMPTIONS."""
    from app.config import DEFAULT_ASSUMPTIONS
    from app.services.valuation_service import apply_overrides
    original_base = DEFAULT_ASSUMPTIONS.pe_target.base
    overridden = apply_overrides(DEFAULT_ASSUMPTIONS, {"forward_pe.base": 30.0})
    # Original must be unchanged
    assert DEFAULT_ASSUMPTIONS.pe_target.base == original_base
    # Override must be applied to new instance
    assert overridden.pe_target.base == Decimal("30")


def test_unknown_override_field_rejected():
    """Unknown override fields must be rejected with ValueError."""
    from app.config import DEFAULT_ASSUMPTIONS
    from app.services.valuation_service import apply_overrides
    with pytest.raises(ValueError, match="Unknown override"):
        apply_overrides(DEFAULT_ASSUMPTIONS, {"unknown.field": 5.0})
