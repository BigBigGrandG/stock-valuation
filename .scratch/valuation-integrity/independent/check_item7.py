"""
Independent check for Item 7: Browser Evidence, Network Payloads & Export Markdown Content Assertions
"""
import json
import sys

sys.path.insert(0, "backend")

from app.services.valuation_service import (
    ValuationService,
    FinancialDataService,
    MemoryTTLCache,
)
from app.providers.avgo_fixture import AVGOFixtureProvider
from app.config import DEFAULT_ASSUMPTIONS

print("=== CHECK ITEM 7: BROWSER EVIDENCE & EXPORT CONTENT ===")

data_svc = FinancialDataService(AVGOFixtureProvider(), MemoryTTLCache(), DEFAULT_ASSUMPTIONS)
val_svc = ValuationService(data_svc, default_assumptions=DEFAULT_ASSUMPTIONS)

# Compute valuation for AVGO and dump json for node export check
res = val_svc.compute("AVGO")
res_dict = res.model_dump(mode="json")

# Write to independent scratch
with open(".scratch/valuation-integrity/independent/avgo_response.json", "w", encoding="utf-8") as f:
    json.dump(res_dict, f, indent=2)

print(f"Dumped backend response to .scratch/valuation-integrity/independent/avgo_response.json")
print(f"Keys in response: {list(res_dict.keys())}")
print(f"Is statement_basis in response: {'statement_basis' in res_dict}")
print(f"Is shares_basis in response: {'shares_basis' in res_dict}")
print(f"Is annual_fallback in response: {'annual_fallback' in res_dict}")

assert "statement_basis" in res_dict, "statement_basis must be in serialized response"
assert "shares_basis" in res_dict, "shares_basis must be in serialized response"
assert "annual_fallback" in res_dict, "annual_fallback must be in serialized response"
assert res_dict["statement_basis"] == "TTM"
assert res_dict["shares_basis"] == "ALL_CLASS_RECONCILED"
assert res_dict["annual_fallback"] is False
assert "dcf" in res_dict["valuations"]
assert res_dict["valuations"]["dcf"]["sensitivity_matrix"] is not None

print("ALL ITEM 7 BACKEND SERIALIZATION ASSERTIONS PASSED!")
