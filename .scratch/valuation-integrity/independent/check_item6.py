"""
Independent check for Item 6: Model Weights, Sparse Overrides, Cashflow Cap, & Export Response Fields
"""
from decimal import Decimal
import sys

sys.path.insert(0, "backend")

from app.models.overrides import ValuationOverrideRequest, WeightOverride
from app.engines.composite import run_composite
from app.services.valuation_service import (
    ValuationService,
    FinancialDataService,
    MemoryTTLCache,
)
from app.providers.avgo_fixture import AVGOFixtureProvider
from app.config import DEFAULT_ASSUMPTIONS
from app.models.domain import ModelValuation, PriceEstimate, DataQuality

print("=== CHECK ITEM 6: WEIGHTS & EXPORT FIELDS ===")

data_svc = FinancialDataService(AVGOFixtureProvider(), MemoryTTLCache(), DEFAULT_ASSUMPTIONS)
val_svc = ValuationService(data_svc, default_assumptions=DEFAULT_ASSUMPTIONS)

# Test 6.1: Sparse override { "weight_dcf": 0 }
req_sparse = ValuationOverrideRequest(weights=WeightOverride(weight_dcf=Decimal("0")))
res_sparse = val_svc.compute("AVGO", overrides=req_sparse.to_override_dict())
comp_sparse = res_sparse.composite
print(f"Test 6.1 (Sparse override weight_dcf=0):")
print(f"   selected_weights: {comp_sparse.selected_weights}")
print(f"   effective_weights: {comp_sparse.effective_weights}")
print(f"   DCF in available_models: {'dcf' in comp_sparse.available_models}")
assert comp_sparse.effective_weights.get('dcf', Decimal("0")) == Decimal("0"), "DCF weight must be 0 after sparse override"
assert 'dcf' not in comp_sparse.available_models, "DCF must be excluded from available_models when weight is 0"

# Test 6.2: PE only override
req_pe = ValuationOverrideRequest(weights=WeightOverride(
    weight_pe=Decimal("1.0"),
    weight_ev_ebitda=Decimal("0.0"),
    weight_fcf_yield=Decimal("0.0"),
    weight_dcf=Decimal("0.0"),
))
res_pe = val_svc.compute("AVGO", overrides=req_pe.to_override_dict())
comp_pe = res_pe.composite
print(f"Test 6.2 (PE only override):")
print(f"   effective_weights: {comp_pe.effective_weights}")
print(f"   available: {comp_pe.available}, base price: {comp_pe.base}")
assert comp_pe.effective_weights.get('forward_pe') == Decimal("1.0"), "PE weight must be normalized to 1.0"
assert comp_pe.available is True, "PE only composite must be available"
assert comp_pe.base == res_pe.valuations['forward_pe'].base.price_per_share

# Test 6.3: Only cashflow models available under 40% cap
def _dummy_model(price=100.0, avail=True):
    p = Decimal(str(price))
    pe = PriceEstimate(price_per_share=p, upside_pct=Decimal("0.1"), premium_discount_pct=Decimal("-0.1"))
    return ModelValuation(
        formula="test", formula_description="test", inputs={}, assumptions={},
        calculation_steps=[], available=avail, low=pe, base=pe, high=pe, data_quality=DataQuality.HIGH
    )

comp_cf_only = run_composite(
    current_price=Decimal("100"),
    pe_result=_dummy_model(avail=False),
    ev_result=_dummy_model(avail=False),
    fcf_result=_dummy_model(price=120.0),
    dcf_result=_dummy_model(price=130.0),
    assumptions=DEFAULT_ASSUMPTIONS,
)
print(f"Test 6.3 (Only CF models available under 40% cap):")
print(f"   composite available: {comp_cf_only.available}")
print(f"   unavailable_reason: {comp_cf_only.unavailable_reason}")
print(f"   policy_message: {comp_cf_only.cashflow_group_policy_message}")
print(f"   cashflow_sensitivity: {comp_cf_only.cashflow_sensitivity}")
assert not comp_cf_only.available, "Composite must degrade when only cashflow models exist under 40% cap"
assert comp_cf_only.cashflow_group_policy_message is not None, "Must produce cashflow group policy message"
assert comp_cf_only.cashflow_sensitivity is not None, "Must provide cashflow sensitivity summary"

# Test 6.4: Backend ValuationResponse fields vs Snapshot fields
res = val_svc.compute("AVGO")
snap = data_svc.get_snapshot("AVGO")
print(f"Test 6.4 (API Response fields for UI / Markdown export):")
print(f"   Snapshot has shares_basis: {getattr(snap, 'shares_basis', None)}")
print(f"   Snapshot has statement_basis: {getattr(snap, 'statement_basis', None)}")
print(f"   Snapshot has annual_fallback: {getattr(snap, 'annual_fallback', None)}")
print(f"   ValuationResponse has shares_basis: {hasattr(res, 'shares_basis')}")
print(f"   ValuationResponse has statement_basis: {hasattr(res, 'statement_basis')}")
print(f"   ValuationResponse has annual_fallback: {hasattr(res, 'annual_fallback')}")
assert hasattr(res, "shares_basis") and res.shares_basis is not None, "ValuationResponse must include shares_basis"
assert hasattr(res, "statement_basis") and res.statement_basis is not None, "ValuationResponse must include statement_basis"
assert hasattr(res, "annual_fallback") and res.annual_fallback is not None, "ValuationResponse must include annual_fallback"
assert res.shares_basis == "ALL_CLASS_RECONCILED"
assert res.statement_basis == "TTM"

print("ALL ITEM 6 CHECKS AND ASSERTIONS PASSED!")
