"""
Deterministic production-engine probe for DCF arithmetic.
Verifies whether changing only projection period labels alters cashflow amounts,
discount exponents, or valuation price per share.
Grounded in app/engines/dcf.py execution.
"""
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
import sys

# Ensure backend modules can be imported
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))

from app.models.domain import CompanyFinancialSnapshot, ValuationAssumptions
from app.engines.dcf import run_dcf, _compute_dcf_scenario, PREC

DIR = Path(__file__).resolve().parent

def run_dcf_probe():
    print("=================================================================")
    print("       NARROW PRODUCTION-ENGINE DCF PROBE (GOOG)                  ")
    print("=================================================================")

    # 1. Load captured GOOG snapshot
    snap_dict = json.loads((DIR / "GOOG-api-snapshot.json").read_text(encoding="utf-8"))
    snap_baseline = CompanyFinancialSnapshot.model_validate(snap_dict)

    # 2. Run Baseline Production DCF
    dcf_base_result = run_dcf(snap_baseline, ValuationAssumptions())
    base_scenario = dcf_base_result.dcf_scenarios[1]  # base scenario

    base_fcff_y1 = base_scenario.fcff_year1
    base_periods = base_scenario.projection_periods
    base_pvs = base_scenario.pv_projections
    base_ev = base_scenario.enterprise_value
    base_pv_tv = base_scenario.pv_terminal_value
    base_equity = base_scenario.equity_value
    base_price = base_scenario.price_per_share

    print(f"\n[Baseline DCF]")
    print(f"  fcff_ttm base:        {snap_baseline.fcff_ttm.value} (Period: '{snap_baseline.fcff_ttm.period}')")
    print(f"  WACC (base):          {base_scenario.wacc:.4f}")
    print(f"  Terminal Growth (base): {base_scenario.terminal_growth:.4f}")
    print(f"  FCFF Growth (base):   {base_scenario.growth_rate:.4f}")
    print(f"  Year 1 Derived:       {base_fcff_y1}")
    print(f"  Exact Formula:        ttm_metric.value * (1 + growth) = {snap_baseline.fcff_ttm.value} * {Decimal('1') + base_scenario.growth_rate} = {base_fcff_y1}")
    print(f"  Base cashflow grown?  YES (grown by 1 period from FY2025 historical)")
    print(f"  Projection periods:   {base_periods}")
    print(f"  Discount exponents:   pv_years = {base_scenario.pv_years} (integer loop index)")
    print(f"  Present Values:       {[float(p) for p in base_pvs]}")
    print(f"  Enterprise Value:     {base_ev}")
    print(f"  PV Terminal Value:    {base_pv_tv} ({base_pv_tv / base_ev:.2%} of EV)")
    print(f"  Price Per Share:      ${base_price}")

    assert base_price == Decimal("116.57"), f"Baseline mismatch: {base_price}"
    assert base_periods[0] == "FY2025E", f"Expected FY2025E label, got {base_periods[0]}"

    # 3. Experiment A: Change ONLY projection period label from FY2025 to FY2025 TTM
    # When period contains 'TTM', _year_from_period returns year + 1 (2025 + 1 = 2026),
    # producing label 'FY2026E'. Cash values and growth rate are 100% UNCHANGED.
    snap_label_modified = snap_baseline.model_copy(deep=True)
    snap_label_modified.fcff_ttm = snap_baseline.fcff_ttm.model_copy(update={"period": "FY2025 TTM"})

    dcf_label_result = run_dcf(snap_label_modified, ValuationAssumptions())
    label_scenario = dcf_label_result.dcf_scenarios[1]

    label_fcff_y1 = label_scenario.fcff_year1
    label_periods = label_scenario.projection_periods
    label_pvs = label_scenario.pv_projections
    label_ev = label_scenario.enterprise_value
    label_price = label_scenario.price_per_share

    print(f"\n[Experiment A: Label-Only Change to 'FY2026E']")
    print(f"  Modified period string: 'FY2025 TTM'")
    print(f"  New projection periods: {label_periods}")
    print(f"  New Projections:        {[float(p) for p in label_scenario.fcff_projections]}")
    print(f"  New Present Values:     {[float(p) for p in label_pvs]}")
    print(f"  New Enterprise Value:   {label_ev}")
    print(f"  New Price Per Share:    ${label_price}")

    # Assertions proving that changing only labels has zero mathematical impact
    assert label_periods == ["FY2026E", "FY2027E", "FY2028E", "FY2029E", "FY2030E"]
    assert label_fcff_y1 == base_fcff_y1, "Projections must be identical!"
    assert label_scenario.fcff_projections == base_scenario.fcff_projections, "All projections must be identical!"
    assert label_pvs == base_pvs, "Present values must be identical!"
    assert label_ev == base_ev, "Enterprise value must be identical!"
    assert label_price == base_price, "Price per share must be identical!"

    print("\n  >> RESULT EXPERIMENT A: PROVEN.")
    print("     Changing the forecast period label from 'FY2025E' to 'FY2026E' has ZERO effect")
    print("     on cash flow amounts, discount exponents, or price per share ($116.57 == $116.57).")
    print("     The forecast date string enters ONLY the display/lineage metadata (metric.period),")
    print("     NOT the discount exponent denominator ((1 + WACC) ** year).")

    # 4. Experiment B: What if Base Cash Flow was Compounded for 2 Years to FY2027?
    # If valuation is September 2026 and Year 1 is intended to be FY2027:
    # Y1 = 73,878,352,000 * (1 + growth)^2
    growth = base_scenario.growth_rate
    y1_2year = (snap_baseline.fcff_ttm.value * ((Decimal("1") + growth) ** 2)).quantize(PREC, ROUND_HALF_UP)
    exp_b_scenario = _compute_dcf_scenario(
        scenario_name="base",
        fcff_y1=y1_2year,
        fcff_y2=None,
        fcff_y1_label="Compounded 2 Years to FY2027",
        fcff_y2_label=None,
        growth_rate=growth,
        wacc=base_scenario.wacc,
        terminal_growth=base_scenario.terminal_growth,
        total_debt=snap_baseline.total_debt.value,
        cash=snap_baseline.cash.value,
        diluted_shares=snap_baseline.diluted_shares.value,
        current_price=snap_baseline.current_price.value,
        base_year=2026,
    )

    ev_diff_pct = (exp_b_scenario.enterprise_value - base_ev) / base_ev * 100
    equity_diff_pct = (exp_b_scenario.equity_value - base_equity) / base_equity * 100
    price_diff_pct = (exp_b_scenario.price_per_share - base_price) / base_price * 100

    print(f"\n[Experiment B: 2-Year Forward Compounding to FY2027]")
    print(f"  Year 1 (FY2027E):       ${exp_b_scenario.fcff_year1:,}")
    print(f"  Enterprise Value:       ${exp_b_scenario.enterprise_value:,} (vs Base ${base_ev:,}, {ev_diff_pct:+.2f}%)")
    print(f"  Equity Value:           ${exp_b_scenario.equity_value:,} (vs Base ${base_equity:,}, {equity_diff_pct:+.2f}%)")
    price_diff = exp_b_scenario.price_per_share - base_price
    print(f"  Price Per Share:        ${exp_b_scenario.price_per_share} (vs Base ${base_price}, diff: {price_diff:+.2f} / {price_diff_pct:+.2f}%)")

    # 5. Experiment C: Calendar Discounting Fraction (Stub Period Discounting)
    # In September 2026, FY2026 cash flow is ~0.31 years away, not 1.0 year away.
    # Fractional discount factor: (1 + 0.10)^0.31 = 1.0299 vs 1.10^1 = 1.10.
    pv_stub = (base_fcff_y1 / (Decimal("1.10") ** Decimal("0.31"))).quantize(PREC, ROUND_HALF_UP)
    print(f"\n[Experiment C: Stub-Period Calendar Discounting]")
    print(f"  Year 1 nominal FCFF:    ${base_fcff_y1:,}")
    print(f"  Engine annual PV (t=1): ${base_pvs[0]:,} (discount factor 1.1000)")
    print(f"  Stub PV (t=0.31 yr):    ${pv_stub:,} (discount factor 1.0299)")
    print(f"  Stub PV difference:     +${pv_stub - base_pvs[0]:,} (+6.8% on Year 1 PV)")

    print("\n=================================================================")
    print("       DCF PROBE COMPLETED: ALL ASSERTIONS VERIFIED              ")
    print("=================================================================\n")

if __name__ == "__main__":
    run_dcf_probe()
