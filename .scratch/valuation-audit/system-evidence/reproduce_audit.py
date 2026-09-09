"""
Reproduction and Evidence Verification Harness for Valuation System Audit.
Consists of two distinct, modular verification suites:
1. SNAPSHOT CONSISTENCY: Asserts fidelity of captured JSON snapshots from the running
   service against user-critique reported figures.
2. PRODUCTION ENGINE PROBE: Imports and executes backend valuation engines (run_dcf,
   _compute_dcf_scenario) to deterministically test calendar-discounting cash flow math
   and verify that projection period label changes alone do not affect DCF arithmetic.

Read-only execution: does not alter server state or application codebase.
"""
from decimal import Decimal
import json
from pathlib import Path
import sys

DIR = Path(__file__).resolve().parent

# Import probe_dcf_engine
from probe_dcf_engine import run_dcf_probe

def run_snapshot_consistency():
    print("\n=================================================================")
    print("       PART 1: SNAPSHOT CONSISTENCY VERIFICATION                  ")
    print("=================================================================")

    # 1. AMD Reproduction
    amd_val = json.loads((DIR / 'AMD-api-valuation.json').read_text(encoding='utf-8'))
    amd_price = Decimal(amd_val['current_price'])
    amd_comp = Decimal(amd_val['composite']['base'])
    amd_pe = Decimal(amd_val['valuations']['forward_pe']['base']['price_per_share'])
    amd_ev = Decimal(amd_val['valuations']['ev_ebitda']['base']['price_per_share'])
    amd_fcf = Decimal(amd_val['valuations']['fcf_yield']['base']['price_per_share'])
    amd_dcf = Decimal(amd_val['valuations']['dcf']['base']['price_per_share'])

    print(f"[AMD] Captured Live Price={amd_price} (User critique reported: ~$523.58)")
    print(f"[AMD] Composite Base={amd_comp} (User critique reported: $164.32)")
    print(f"[AMD] Forward P/E={amd_pe} (User critique reported: $151.40)")
    print(f"[AMD] EV/EBITDA={amd_ev} (User critique reported: $141.37)")
    print(f"[AMD] FCF Yield={amd_fcf} (User critique reported: $141.09)")
    print(f"[AMD] DCF={amd_dcf} (User critique reported: $209.73)")

    assert amd_comp == Decimal("164.32"), f"AMD composite mismatch: {amd_comp}"
    assert amd_pe == Decimal("151.40"), f"AMD PE mismatch: {amd_pe}"
    assert amd_ev == Decimal("141.37"), f"AMD EV mismatch: {amd_ev}"
    assert amd_fcf == Decimal("141.09"), f"AMD FCF mismatch: {amd_fcf}"
    assert amd_dcf == Decimal("209.73"), f"AMD DCF mismatch: {amd_dcf}"

    # 2. META Reproduction
    meta_val = json.loads((DIR / 'META-api-valuation.json').read_text(encoding='utf-8'))
    meta_price = Decimal(meta_val['current_price'])
    meta_comp = Decimal(meta_val['composite']['base'])
    meta_pe = Decimal(meta_val['valuations']['forward_pe']['base']['price_per_share'])
    meta_ev = Decimal(meta_val['valuations']['ev_ebitda']['base']['price_per_share'])
    meta_fcf = Decimal(meta_val['valuations']['fcf_yield']['base']['price_per_share'])
    meta_dcf = Decimal(meta_val['valuations']['dcf']['base']['price_per_share'])

    print(f"\n[META] Captured Live Price={meta_price} (User critique reported: ~$650.41)")
    print(f"[META] Composite Base={meta_comp} (User critique reported: ~$845)")
    print(f"[META] Forward P/E={meta_pe} (User critique reported: $628.60)")
    print(f"[META] EV/EBITDA={meta_ev} (User critique reported: ~$1,333)")
    print(f"[META] FCF Yield={meta_fcf} (User critique reported: $891.84)")
    print(f"[META] DCF={meta_dcf} (User critique reported: $662.58)")

    assert Decimal("845.00") <= meta_comp <= Decimal("846.00"), f"META composite mismatch: {meta_comp}"
    assert meta_pe == Decimal("628.60"), f"META PE mismatch: {meta_pe}"
    assert meta_ev == Decimal("1333.01"), f"META EV mismatch: {meta_ev}"
    assert meta_fcf == Decimal("891.84"), f"META FCF mismatch: {meta_fcf}"
    assert meta_dcf == Decimal("662.58"), f"META DCF mismatch: {meta_dcf}"

    # 3. META Share Count Inconsistency Evidence
    meta_snap = json.loads((DIR / 'META-api-snapshot.json').read_text(encoding='utf-8'))
    meta_shares = meta_snap['diluted_shares']['value']
    meta_raw = json.loads((DIR / 'META-raw-yfinance.json').read_text(encoding='utf-8'))
    raw_shares_out = meta_raw['info'].get('sharesOutstanding')
    raw_implied_shares = meta_raw['info'].get('impliedSharesOutstanding')

    print(f"[META Shares] Ingested diluted_shares = {meta_shares} (matches raw sharesOutstanding={raw_shares_out})")
    print(f"[META Shares] Upstream impliedSharesOutstanding = {raw_implied_shares}")
    print(f"[META Shares] Discrepancy proves multi-class risk: {raw_implied_shares - raw_shares_out:,} uncounted shares")
    assert meta_shares == "2205128509", f"META share count mismatch: {meta_shares}"

    # 4. GOOG Reproduction
    goog_val = json.loads((DIR / 'GOOG-api-valuation.json').read_text(encoding='utf-8'))
    goog_price = Decimal(goog_val['current_price'])
    goog_comp = Decimal(goog_val['composite']['base'])
    goog_pe = Decimal(goog_val['valuations']['forward_pe']['base']['price_per_share'])
    goog_ev_avail = goog_val['valuations']['ev_ebitda']['available']
    goog_fcf = Decimal(goog_val['valuations']['fcf_yield']['base']['price_per_share'])
    goog_dcf = Decimal(goog_val['valuations']['dcf']['base']['price_per_share'])

    print(f"\n[GOOG] Captured Live Price={goog_price} (User critique reported: ~$328.28)")
    print(f"[GOOG] Composite Base={goog_comp} (User critique reported: $226.96)")
    print(f"[GOOG] Forward P/E={goog_pe} (User critique reported: $412.00)")
    print(f"[GOOG] EV/EBITDA available={goog_ev_avail} (User critique reported: unavailable)")
    print(f"[GOOG] FCF Yield={goog_fcf} (User critique reported: ~$174)")
    print(f"[GOOG] DCF={goog_dcf} (User critique reported: $116.57)")

    assert goog_comp == Decimal("226.96"), f"GOOG composite mismatch: {goog_comp}"
    assert goog_pe == Decimal("412.00"), f"GOOG PE mismatch: {goog_pe}"
    assert goog_ev_avail is False, "GOOG EV/EBITDA should be unavailable in captured state"
    assert goog_fcf == Decimal("174.39"), f"GOOG FCF mismatch: {goog_fcf}"
    assert goog_dcf == Decimal("116.57"), f"GOOG DCF mismatch: {goog_dcf}"

    # Model Dispersion check for GOOG
    goog_spread = (goog_pe - goog_dcf) / goog_dcf
    print(f"[GOOG Dispersion] Spread (PE vs DCF) = {goog_spread:.2%} (or ratio: {goog_pe / goog_dcf:.2f}x)")
    assert Decimal("2.50") <= goog_spread <= Decimal("2.55"), f"Unexpected GOOG dispersion: {goog_spread}"

    # 5. GOOG DCF Forecast Period Defect
    dcf_scenarios = goog_val['valuations']['dcf']['dcf_scenarios']
    y1_period = dcf_scenarios[0]['projection_periods'][0]
    print(f"[GOOG DCF Metadata] First forecast period label = {y1_period}")
    assert y1_period == "FY2025E", f"Expected FY2025E, got {y1_period}"

    # 6. Terminal Value Ratios
    for name, data in [('AMD', amd_val), ('META', meta_val), ('GOOG', goog_val)]:
        base_s = data['valuations']['dcf']['dcf_scenarios'][1]
        ev = Decimal(str(base_s['enterprise_value']))
        pv_tv = Decimal(str(base_s['pv_terminal_value']))
        ratio = pv_tv / ev
        print(f"[{name} DCF] TV Ratio = {ratio:.2%}")
        assert Decimal("0.70") <= ratio <= Decimal("0.85"), f"{name} TV ratio outside 70-85%: {ratio}"

    # 7. Stale Warning (253 Days)
    for name, data in [('AMD', amd_val), ('META', meta_val), ('GOOG', goog_val)]:
        stale_warn = any("253 days" in w for w in data['warnings'])
        assert stale_warn, f"{name} missing 253 days stale warning"

    print("\n>> PART 1: SNAPSHOT CONSISTENCY CONFIRMED ACROSS ALL CRITIQUED METRICS.")

def run_all():
    print("=================================================================")
    print("      VALUATION SYSTEM AUDIT: DUAL REPRODUCTION HARNESS          ")
    print("=================================================================")
    run_snapshot_consistency()
    run_dcf_probe()
    print("=================================================================")
    print("      ALL REPRODUCTION AND ENGINE PROBE TESTS COMPLETED          ")
    print("=================================================================")

if __name__ == "__main__":
    run_all()
