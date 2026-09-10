"""
Independent check for Item 3: DCF ACT/365, Growth Horizon Conversion, & Sensitivity Matrix
"""
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
import math
import sys

sys.path.insert(0, "backend")

from app.engines.dcf import _calculate_dcf, _compute_dcf_scenario, run_dcf
from app.models.domain import (
    CompanyFinancialSnapshot,
    FinancialMetric,
    SourceType,
    ValuationAssumptions,
)

print("=== CHECK ITEM 3: DCF ACT/365 & CALENDAR ANCHORING ===")

# Test 3.1: Independent Math Oracle for ACT/365 Exponential Discounting
projections = [Decimal("100"), Decimal("110"), Decimal("121"), Decimal("133.1"), Decimal("146.41")]
year_fractions = [
    Decimal("365") / Decimal("365"),
    Decimal("731") / Decimal("365"),
    Decimal("1096") / Decimal("365"),
    Decimal("1461") / Decimal("365"),
    Decimal("1826") / Decimal("365"),
]
wacc = Decimal("0.10")
terminal_growth = Decimal("0.03")
net_debt = Decimal("50")
shares = Decimal("10")

pvs, tv, pv_tv, ev, eq, price, tv_ratio = _calculate_dcf(
    projections, year_fractions, wacc, terminal_growth, net_debt, shares
)

oracle_pvs = []
ln_wacc = (Decimal("1") + wacc).ln()
for p, f in zip(projections, year_fractions):
    df = (f * ln_wacc).exp()
    oracle_pvs.append((p / df).quantize(Decimal("0.01"), ROUND_HALF_UP))
oracle_tv = (projections[-1] * (Decimal("1") + terminal_growth) / (wacc - terminal_growth)).quantize(Decimal("0.01"), ROUND_HALF_UP)
oracle_pv_tv = (oracle_tv / (year_fractions[-1] * ln_wacc).exp()).quantize(Decimal("0.01"), ROUND_HALF_UP)
oracle_ev = (sum(oracle_pvs) + oracle_pv_tv).quantize(Decimal("0.01"), ROUND_HALF_UP)
oracle_price = ((oracle_ev - net_debt) / shares).quantize(Decimal("0.01"), ROUND_HALF_UP)

print(f"Test 3.1 (ACT/365 exponential math vs oracle):")
print(f"   EV: code={ev}, oracle={oracle_ev}, match={ev == oracle_ev}")
print(f"   Price: code={price}, oracle={oracle_price}, match={price == oracle_price}")
assert ev == oracle_ev, f"EV mismatch: {ev} vs {oracle_ev}"
assert price == oracle_price, f"Price mismatch: {price} vs {oracle_price}"

def _m(val, unit="USD", period="FY2025", as_of=date(2025, 12, 31)):
    return FinancialMetric(
        value=Decimal(str(val)),
        unit=unit,
        period=period,
        source="filing",
        source_type=SourceType.ACTUAL,
        as_of=as_of,
        confidence=1.0,
        is_estimated=False,
    )

snap_hist = CompanyFinancialSnapshot(
    ticker="HIST_CO",
    company_name="Historical Base Co",
    currency="USD",
    current_price=_m("100.00", as_of=date(2026, 9, 10)),
    price_timestamp=datetime(2026, 9, 10, 12, 0, 0),
    diluted_shares=_m("1000000000", unit="shares", as_of=date(2026, 9, 10)),
    cash=_m("10000000000", as_of=date(2026, 9, 10)),
    total_debt=_m("10000000000", as_of=date(2026, 9, 10)),
    net_debt=_m("0", as_of=date(2026, 9, 10)),
    fcff_ttm=_m("10000000000", period="FY2025", as_of=date(2025, 12, 31)),
    fcff_growth=_m("0.10", as_of=date(2026, 9, 10)),
    statement_basis="ANNUAL_FALLBACK",
    annual_fallback=True,
)

dcf_hist_res = run_dcf(snap_hist, ValuationAssumptions())
assert dcf_hist_res.available, "DCF from historical base must be available"
base_scenario = next(s for s in dcf_hist_res.dcf_scenarios if s.scenario == "base")
print(f"Test 3.2 (Historical annual 2025-12-31 to valuation as_of 2026-09-10):")
print(f"   Historical base FCFF: 10,000,000,000 (FY2025 as of 2025-12-31)")
print(f"   Scenario Year 1 FCFF projection: {base_scenario.fcff_projections[0]}")
print(f"   Scenario Year 1 start/end dates: {base_scenario.period_start_dates[0]} to {base_scenario.period_end_dates[0]}")
print(f"   Compound horizon text: {base_scenario.growth_compound_horizon}")

ratio = base_scenario.fcff_projections[0] / Decimal("10000000000")
print(f"   Growth applied to base: {ratio} (ratio - 1 = {ratio - 1})")
assert base_scenario.period_start_dates[0] == "2026-09-10", "Year 1 must start on valuation date"
assert base_scenario.period_end_dates[0] == "2027-09-10", "Year 1 must end on anniversary date"
assert base_scenario.year_fractions[0] == Decimal("1.0"), "Year 1 discounting must be 1.0 year"
dt = Decimal("618") / Decimal("365")
expected_growth = (dt * (Decimal("1") + Decimal("0.10")).ln()).exp()
expected_y1 = (Decimal("10000000000") * expected_growth).quantize(Decimal("0.01"), ROUND_HALF_UP)
assert base_scenario.fcff_projections[0] == expected_y1, f"Y1 projection mismatch: {base_scenario.fcff_projections[0]} vs {expected_y1}"
assert ratio > Decimal("1.10"), "Must reflect 618 days of compounding (> 1.10)"

# Test 3.3: Forward Fiscal Year FCFF Blind Relabeling Protection
snap_fwd = CompanyFinancialSnapshot(
    ticker="FWD_CO",
    company_name="Forward Co",
    currency="USD",
    current_price=_m("100.00", as_of=date(2026, 9, 10)),
    price_timestamp=datetime(2026, 9, 10, 12, 0, 0),
    diluted_shares=_m("1000000000", unit="shares", as_of=date(2026, 9, 10)),
    cash=_m("10000000000", as_of=date(2026, 9, 10)),
    total_debt=_m("10000000000", as_of=date(2026, 9, 10)),
    net_debt=_m("0", as_of=date(2026, 9, 10)),
    forward_fcff_1y=_m("12000000000", period="FY2026E", as_of=date(2026, 9, 10)),
    fcff_growth=_m("0.10", as_of=date(2026, 9, 10)),
    statement_basis="TTM",
    annual_fallback=False,
)
dcf_fwd_res = run_dcf(snap_fwd, ValuationAssumptions())
print(f"Test 3.3 (Forward Fiscal Year FCFF labeling without FY2 or historical proxy):")
print(f"   dcf available: {dcf_fwd_res.available}")
print(f"   unavailable reason: {dcf_fwd_res.unavailable_reason}")
assert not dcf_fwd_res.available, "DCF must fail closed on discrete forward FY without blending or proxy"
assert "Without a +2y estimate" in dcf_fwd_res.unavailable_reason

# When FY2 estimate is also available, verify reliable NTM day-weighted blending
snap_fwd_with_y2 = snap_fwd.model_copy(update={
    "forward_fcff_2y": _m("14000000000", period="FY2027E", as_of=date(2026, 9, 10)),
})
dcf_blended_res = run_dcf(snap_fwd_with_y2, ValuationAssumptions())
assert dcf_blended_res.available, "DCF with FY1 and FY2 must be available via NTM blending"
base_blended = next(s for s in dcf_blended_res.dcf_scenarios if s.scenario == "base")
assert base_blended.period_start_dates[0] == "2026-09-10"
assert base_blended.period_end_dates[0] == "2027-09-10"
assert base_blended.year_fractions[0] == Decimal("1.0")

# Test 3.4: Sensitivity Matrix Base Identity & Invalid Cell Assertions
mat = dcf_hist_res.sensitivity_matrix
assert mat is not None, "Sensitivity matrix must be generated"
assert mat.cells[1][1].available, "Center cell must be available"
assert mat.cells[1][1].price_per_share == base_scenario.price_per_share, (
    f"Matrix center cell price ({mat.cells[1][1].price_per_share}) must exactly match base scenario ({base_scenario.price_per_share})"
)

print("ALL ITEM 3 CHECKS AND ASSERTIONS PASSED!")
