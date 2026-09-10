"""
Independent check for Item 4: NTM Consensus Horizon Selection & Revenue Passing
"""
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
import inspect
import sys

sys.path.insert(0, "backend")

from app.models.domain import CompanyFinancialSnapshot, FinancialMetric, SourceType, ValuationAssumptions
from app.providers.base import ForwardEstimatesData
from app.providers.yfinance_provider import YFinanceProvider
from app.services.projections import calculate_ntm_weights, derive_request_projections

print("=== CHECK ITEM 4: NTM HORIZON & FORWARD REVENUE ===")

# Test 4.1: Check if forward revenue exists on CompanyFinancialSnapshot model contract
snap_fields = CompanyFinancialSnapshot.model_fields.keys()
has_rev_est_1y = "revenue_estimate_1y" in snap_fields
has_rev_est_2y = "revenue_estimate_2y" in snap_fields
has_fwd_rev = "forward_revenue" in snap_fields
print(f"Test 4.1 (CompanyFinancialSnapshot fields):")
print(f"   revenue_estimate_1y defined: {has_rev_est_1y}")
print(f"   revenue_estimate_2y defined: {has_rev_est_2y}")
print(f"   forward_revenue defined: {has_fwd_rev}")
assert has_rev_est_1y, "revenue_estimate_1y must be defined on CompanyFinancialSnapshot"
assert has_rev_est_2y, "revenue_estimate_2y must be defined on CompanyFinancialSnapshot"
assert has_fwd_rev, "forward_revenue must be defined on CompanyFinancialSnapshot"

# Test 4.2: Check that ForwardEstimatesData type contract has forward revenue fields
fed_keys = ForwardEstimatesData.__annotations__.keys()
has_rev_in_fed = "forward_revenue_1y" in fed_keys and "forward_revenue_2y" in fed_keys
print(f"Test 4.2 (ForwardEstimatesData annotations inspection):")
print(f"   forward_revenue_1y in ForwardEstimatesData: {'forward_revenue_1y' in fed_keys}")
print(f"   forward_revenue_2y in ForwardEstimatesData: {'forward_revenue_2y' in fed_keys}")
assert has_rev_in_fed, "ForwardEstimatesData type contract must include forward_revenue_1y and forward_revenue_2y"

# Test 4.3: Check NTM weights when current FY has already ended (next_fy_end <= as_of)
as_of = date(2026, 9, 10)
past_fy_end = date(2025, 12, 31)  # Fiscal year ended prior to as_of
w0, w1, rem_days, total_days = calculate_ntm_weights(as_of, past_fy_end)
print(f"Test 4.3 (calculate_ntm_weights when fiscal year has ended: past_fy_end <= as_of):")
print(f"   as_of: {as_of}, next_fy_end: {past_fy_end}")
print(f"   w0 (current FY): {w0}, w1 (next FY): {w1}")
assert w0 == Decimal("0.0"), f"Expired FY must receive 0.0 weight, got {w0}"
assert w1 == Decimal("1.0"), f"Next FY must receive 1.0 weight on expired FY, got {w1}"
assert rem_days == 0

# Test 4.4: Check non-December fiscal year calculation (e.g. AAPL ending September 30)
# as_of = 2026-09-10, next_fy_end = 2026-09-30 (20 days left).
w0_aapl, w1_aapl, rem_aapl, tot_aapl = calculate_ntm_weights(date(2026, 9, 10), date(2026, 9, 30))
print(f"Test 4.4 (Non-Dec FY AAPL: as_of=2026-09-10, fy_end=2026-09-30):")
print(f"   remaining days: {rem_aapl}, total days: {tot_aapl}")
print(f"   w0 (FY2026): {w0_aapl:.4f}, w1 (FY2027): {w1_aapl:.4f}")
assert rem_aapl == 20, f"Remaining days in AAPL FY must be 20, got {rem_aapl}"
assert Decimal("0.0") < w0_aapl < Decimal("0.10"), f"20 days out of 365 should be ~5.5%, got {w0_aapl}"
assert (w0_aapl + w1_aapl) == Decimal("1.0"), "NTM weights must sum to exactly 1.0"

# Test 4.5: Verify day-weighted NTM revenue derivation in projections
def _m(v, period="FY2026"):
    return FinancialMetric(
        value=Decimal(str(v)),
        unit="USD",
        period=period,
        source="test",
        source_type=SourceType.ACTUAL,
        as_of=date(2026, 9, 10),
        confidence=1.0,
        is_estimated=True,
    )

snap = CompanyFinancialSnapshot(
    ticker="TEST_CO",
    company_name="Test Co",
    currency="USD",
    current_price=_m("100.00"),
    price_timestamp=datetime(2026, 9, 10, 12, 0, 0),
    diluted_shares=_m("1000000000", "shares"),
    forecast_fiscal_year_end=date(2026, 9, 30),
    revenue_estimate_1y=_m("100000000000", period="0y"),
    revenue_estimate_2y=_m("120000000000", period="+1y"),
)
proj = derive_request_projections(snap, ValuationAssumptions(forecast_horizon="ntm"))
expected_rev = (w0_aapl * Decimal("100000000000") + w1_aapl * Decimal("120000000000")).quantize(Decimal("1"), ROUND_HALF_UP)
print(f"Test 4.5 (Blended NTM revenue):")
print(f"   derived revenue: {proj.forward_revenue.value if proj.forward_revenue else None}")
print(f"   expected revenue: {expected_rev}")
assert proj.forward_revenue is not None
assert proj.forward_revenue.value == expected_rev, f"Blended revenue mismatch: {proj.forward_revenue.value} vs {expected_rev}"

print("ALL ITEM 4 CHECKS AND ASSERTIONS PASSED!")
