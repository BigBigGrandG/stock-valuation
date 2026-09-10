"""
Independent check for Item 5: Growth Cap Override in API / ValuationService Pipeline
"""
from datetime import date
from decimal import Decimal
import sys

sys.path.insert(0, "backend")

from app.models.overrides import ValuationOverrideRequest, DCFOverride
from app.services.projections import derive_request_projections
from app.services.valuation_service import (
    ValuationService,
    FinancialDataService,
    MemoryTTLCache,
    apply_overrides,
)
from app.providers.avgo_fixture import AVGOFixtureProvider
from app.config import DEFAULT_ASSUMPTIONS

print("=== CHECK ITEM 5: GROWTH CAP OVERRIDE PIPELINE ===")

# Test 5.1: AVGO Fixture / Live Pipeline with growth_cap 0.80 vs 0.40
data_svc = FinancialDataService(AVGOFixtureProvider(), MemoryTTLCache(), DEFAULT_ASSUMPTIONS)
val_svc = ValuationService(data_svc, default_assumptions=DEFAULT_ASSUMPTIONS)

# 1. Baseline valuation (growth_cap default is 0.40)
res_default = val_svc.compute("AVGO")

# 2. Valuation with growth_cap = 0.80 override
req_override_80 = ValuationOverrideRequest(
    dcf=DCFOverride(growth_cap=Decimal("0.80"))
)
res_80 = val_svc.compute("AVGO", overrides=req_override_80.to_override_dict())

# 3. Valuation with growth_cap = 0.40 override
req_override_40 = ValuationOverrideRequest(
    dcf=DCFOverride(growth_cap=Decimal("0.40"))
)
res_40 = val_svc.compute("AVGO", overrides=req_override_40.to_override_dict())

# 4. Post-check default (cache stability)
res_default_after = val_svc.compute("AVGO")

print(f"Test 5.1a (Growth cap override effect on AVGO DCF price):")
p_def = res_default.valuations['dcf'].base.price_per_share
p_80 = res_80.valuations['dcf'].base.price_per_share
p_40 = res_40.valuations['dcf'].base.price_per_share
p_after = res_default_after.valuations['dcf'].base.price_per_share
print(f"   res_default DCF price: {p_def}")
print(f"   res_80 DCF price:      {p_80}")
print(f"   res_40 DCF price:      {p_40}")
print(f"   res_default_after:     {p_after}")
assert p_80 > p_40, f"DCF price at growth_cap=0.80 ({p_80}) must exceed price at growth_cap=0.40 ({p_40})"
assert p_def == p_after, f"Cache leakage detected: baseline after override ({p_after}) does not match default ({p_def})"
assert p_def == p_40, "Default (0.40) should match explicit 0.40 override"

# Check forward EBITDA in EV/EBITDA model
print(f"Test 5.1b (Growth cap override effect on EV/EBITDA model):")
ev_def = res_default.valuations['ev_ebitda'].base.price_per_share
ev_80 = res_80.valuations['ev_ebitda'].base.price_per_share
ev_40 = res_40.valuations['ev_ebitda'].base.price_per_share
print(f"   ev_default: {ev_def}, ev_80: {ev_80}, ev_40: {ev_40}")
assert ev_80 > ev_40, f"EV/EBITDA target at 0.80 cap ({ev_80}) must exceed 0.40 cap ({ev_40})"
assert ev_def == res_default_after.valuations['ev_ebitda'].base.price_per_share

# Check FCF Yield model
print(f"Test 5.1c (Growth cap override effect on FCF Yield model):")
fcf_def = res_default.valuations['fcf_yield'].base.price_per_share
fcf_80 = res_80.valuations['fcf_yield'].base.price_per_share
fcf_40 = res_40.valuations['fcf_yield'].base.price_per_share
print(f"   fcf_default: {fcf_def}, fcf_80: {fcf_80}, fcf_40: {fcf_40}")
assert fcf_80 > fcf_40, f"FCF Yield target at 0.80 cap ({fcf_80}) must exceed 0.40 cap ({fcf_40})"
assert fcf_def == res_default_after.valuations['fcf_yield'].base.price_per_share

# Test 5.2: AVGO snapshot growth fields presence
snap = data_svc.get_snapshot("AVGO")
print(f"Test 5.2 (AVGO snapshot growth fields):")
print(f"   ebitda_growth: {snap.ebitda_growth.value if snap.ebitda_growth else None}")
print(f"   revenue_growth: {snap.revenue_growth.value if snap.revenue_growth else None}")
print(f"   fcff_growth: {snap.fcff_growth.value if snap.fcff_growth else None}")
assert snap.ebitda_growth is not None, "ebitda_growth must be present in snapshot"
assert snap.revenue_growth is not None, "revenue_growth must be present in snapshot"
assert snap.fcff_growth is not None, "fcff_growth must be present in snapshot"

# Test 5.3: Single-sided growth bounds validation
from pydantic import ValidationError
floor_gt_cap_rejected = False
try:
    DCFOverride(growth_floor=Decimal("0.50"), growth_cap=Decimal("0.30"))
except (ValidationError, ValueError) as exc:
    floor_gt_cap_rejected = True
    print(f"Test 5.3 (growth_floor > growth_cap rejected properly): {exc}")

assert floor_gt_cap_rejected, "growth_floor > growth_cap must be rejected by model validation"

print("ALL ITEM 5 CHECKS AND ASSERTIONS PASSED!")
