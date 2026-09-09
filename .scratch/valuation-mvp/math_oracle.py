"""
math_oracle.py
==============
Independent numeric oracle for AVGO fixture valuation acceptance expectations.
Run with: python math_oracle.py
All arithmetic uses Python Decimal with explicit rounding — no LLM/mental math.
"""
from decimal import Decimal, ROUND_HALF_UP

PREC = Decimal("0.01")
FOUR = Decimal("0.0001")

# ── AVGO fixture constants ──────────────────────────────────────────────────
PRICE       = Decimal("343.83")
SHARES      = Decimal("4940000000")
CASH        = Decimal("24000000000")
DEBT        = Decimal("59400000000")
NET_DEBT    = DEBT - CASH              # 35_400_000_000
EPS_FWD     = Decimal("19.21")
EBITDA_FWD  = Decimal("118300000000")
FCFE_FWD    = Decimal("89600000000")  # FCFE — FCF yield model
FCFF_FWD    = Decimal("89600000000")  # FCFF — DCF model (same value in fixture)


def sep(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)


# ── 1. Forward P/E ──────────────────────────────────────────────────────────
def forward_pe():
    sep("1. Forward P/E  (EPS=19.21, multiples 18/20/22)")
    for mult_s, label in [("18", "low"), ("20", "base"), ("22", "high")]:
        mult = Decimal(mult_s)
        price = (EPS_FWD * mult).quantize(PREC, ROUND_HALF_UP)
        print(f"  {label:5s}  {EPS_FWD} × {mult} = {price}")
    print("  Spec targets: 345.78 / 384.20 / 422.62")


# ── 2. EV/EBITDA ────────────────────────────────────────────────────────────
def ev_ebitda():
    sep("2. EV/EBITDA  (EBITDA=118,300,000,000; net_debt=35,400,000,000; shares=4,940,000,000)")
    print(f"  net_debt = {DEBT:,} - {CASH:,} = {NET_DEBT:,}")
    for mult_s, label in [("18", "low"), ("22", "base"), ("26", "high")]:
        mult = Decimal(mult_s)
        ev     = (EBITDA_FWD * mult).quantize(PREC, ROUND_HALF_UP)
        equity = ev - NET_DEBT
        price  = (equity / SHARES).quantize(PREC, ROUND_HALF_UP)
        print(f"  {label:5s} (×{mult_s}):  EV={ev:>20,}  equity={equity:>20,}  price={price}")


# ── 3. FCF Yield ─────────────────────────────────────────────────────────────
def fcf_yield():
    sep("3. FCF Yield  (FCFE=89,600,000,000; shares=4,940,000,000)")
    print("  Note: low valuation = highest yield; high valuation = lowest yield")
    for yield_s, label in [("0.055", "low (yield=5.5%)"), ("0.050", "base (yield=5.0%)"), ("0.045", "high (yield=4.5%)")]:
        y      = Decimal(yield_s)
        equity = (FCFE_FWD / y).quantize(PREC, ROUND_HALF_UP)
        price  = (equity / SHARES).quantize(PREC, ROUND_HALF_UP)
        print(f"  {label:25s}  equity={equity:>22,}  price={price}")
    print("  Constraint: high_price > low_price must hold")


# ── 4. DCF Base Scenario (with both iterative and power formulas) ────────────
def dcf_base_scenario(g_s="0.08", wacc_s="0.10", tg_s="0.03", label="base"):
    g    = Decimal(g_s)
    wacc = Decimal(wacc_s)
    tg   = Decimal(tg_s)
    n    = 5

    sep(f"4. DCF {label} scenario  (FCFF={FCFF_FWD:,}  g={g_s}  WACC={wacc_s}  tg={tg_s})")

    # ---- Iterative (current engine behaviour) --------------------------------
    print("\n  [A] Iterative method (current engine code):")
    pv_iter  = []
    ff_iter  = []
    fcff_t   = FCFF_FWD
    for t in range(1, n + 1):
        if t > 1:
            fcff_t = (fcff_t * (1 + g)).quantize(PREC, ROUND_HALF_UP)
        ff_r = fcff_t.quantize(PREC, ROUND_HALF_UP)
        pv   = (ff_r / (1 + wacc) ** t).quantize(PREC, ROUND_HALF_UP)
        ff_iter.append(ff_r)
        pv_iter.append(pv)
        print(f"    Year {t}: FCFF={ff_r:>22,}  PV={pv:>22,}")

    fcff5_i  = ff_iter[-1]
    tv_i     = (fcff5_i * (1 + tg) / (wacc - tg)).quantize(PREC, ROUND_HALF_UP)
    pvtv_i   = (tv_i / (1 + wacc) ** n).quantize(PREC, ROUND_HALF_UP)
    ev_i     = (sum(pv_iter) + pvtv_i).quantize(PREC, ROUND_HALF_UP)
    eq_i     = ev_i - NET_DEBT
    price_i  = (eq_i / SHARES).quantize(PREC, ROUND_HALF_UP)
    print(f"    TV={tv_i:,}   PVTV={pvtv_i:,}")
    print(f"    EV={ev_i:,}   equity={eq_i:,}   price={price_i}")

    # ---- Power formula (recommended fix) ------------------------------------
    print("\n  [B] Power formula (proposed fix):")
    pv_pow  = []
    ff_pow  = []
    for t in range(1, n + 1):
        ff_t = (FCFF_FWD * (1 + g) ** (t - 1)).quantize(PREC, ROUND_HALF_UP)
        pv   = (ff_t / (1 + wacc) ** t).quantize(PREC, ROUND_HALF_UP)
        ff_pow.append(ff_t)
        pv_pow.append(pv)
        print(f"    Year {t}: FCFF={ff_t:>22,}  PV={pv:>22,}")

    fcff5_p  = ff_pow[-1]
    tv_p     = (fcff5_p * (1 + tg) / (wacc - tg)).quantize(PREC, ROUND_HALF_UP)
    pvtv_p   = (tv_p / (1 + wacc) ** n).quantize(PREC, ROUND_HALF_UP)
    ev_p     = (sum(pv_pow) + pvtv_p).quantize(PREC, ROUND_HALF_UP)
    eq_p     = ev_p - NET_DEBT
    price_p  = (eq_p / SHARES).quantize(PREC, ROUND_HALF_UP)
    print(f"    TV={tv_p:,}   PVTV={pvtv_p:,}")
    print(f"    EV={ev_p:,}   equity={eq_p:,}   price={price_p}")

    # ---- Coordinator-supplied exact PVs for base scenario -------------------
    if label == "base":
        print("\n  [C] Coordinator-supplied exact PVs (high-precision, no intermediate round):")
        coord_pvs = [
            Decimal("81454545454.55"),
            Decimal("79973553719.01"),
            Decimal("78519489105.94"),
            Decimal("77091862031.28"),
            Decimal("75690191812.53"),
        ]
        coord_tv   = Decimal("1793668644864")
        coord_pvtv = Decimal("1113727108098.6768")
        for ti, pv in enumerate(coord_pvs, 1):
            print(f"    Year {ti}: PV={pv:>22,}")
        print(f"    TV={coord_tv:,}   PVTV={coord_pvtv:,}")
        coord_ev    = (sum(coord_pvs) + coord_pvtv).quantize(PREC, ROUND_HALF_UP)
        coord_eq    = coord_ev - NET_DEBT
        coord_price = (coord_eq / SHARES).quantize(PREC, ROUND_HALF_UP)
        print(f"    EV={coord_ev:,}   equity={coord_eq:,}   price={coord_price}")

    # ---- Differences --------------------------------------------------------
    print("\n  [D] FCFF differences (iterative - power, per year):")
    total_pv_diff = Decimal("0")
    for t in range(n):
        diff_ff = ff_iter[t] - ff_pow[t]
        diff_pv = pv_iter[t] - pv_pow[t]
        total_pv_diff += diff_pv
        print(f"    Year {t+1}: ΔFCFF={diff_ff}  ΔPV={diff_pv}")
    print(f"    ΔTV={tv_i - tv_p}  ΔPVTV={pvtv_i - pvtv_p}")
    print(f"    ΔEV={ev_i - ev_p}  ΔPrice={price_i - price_p} (cents: {(price_i - price_p)*100})")

    return {
        "iter_price": price_i,
        "pow_price":  price_p,
        "iter_tv": tv_i,
        "pow_tv": tv_p,
        "iter_pvtv": pvtv_i,
        "pow_pvtv": pvtv_p,
    }


# ── 5. DCF all 3 scenarios (bear/base/bull) ──────────────────────────────────
def dcf_all_scenarios():
    sep("5. DCF All Scenarios (FCFF=89,600,000,000; net_debt=35,400,000,000)")
    params = [
        ("bear", "0.05", "0.12", "0.03"),
        ("base", "0.08", "0.10", "0.03"),
        ("bull", "0.12", "0.08", "0.04"),
    ]
    for label, g_s, wacc_s, tg_s in params:
        g    = Decimal(g_s)
        wacc = Decimal(wacc_s)
        tg   = Decimal(tg_s)
        ff_t = FCFF_FWD
        pvs  = []
        ffs  = []
        for t in range(1, 6):
            if t > 1:
                ff_t = (ff_t * (1 + g)).quantize(PREC, ROUND_HALF_UP)
            ff_r = ff_t.quantize(PREC, ROUND_HALF_UP)
            pv   = (ff_r / (1 + wacc) ** t).quantize(PREC, ROUND_HALF_UP)
            ffs.append(ff_r)
            pvs.append(pv)
        tv    = (ffs[-1] * (1 + tg) / (wacc - tg)).quantize(PREC, ROUND_HALF_UP)
        pvtv  = (tv / (1 + wacc) ** 5).quantize(PREC, ROUND_HALF_UP)
        ev    = (sum(pvs) + pvtv).quantize(PREC, ROUND_HALF_UP)
        eq    = ev - NET_DEBT
        price = (eq / SHARES).quantize(PREC, ROUND_HALF_UP)
        print(f"  {label:5s} (g={g_s} WACC={wacc_s} tg={tg_s}): price=${price}")


# ── 6. Classification boundary expectations ──────────────────────────────────
def classification_boundaries():
    sep("6. Classification Boundary Expectations")
    cases = [
        ("79",  "100", "SIGNIFICANTLY_UNDERVALUED"),
        ("80",  "100", "SIGNIFICANTLY_UNDERVALUED"),
        ("81",  "100", "UNDERVALUED"),
        ("90",  "100", "UNDERVALUED"),
        ("91",  "100", "SLIGHTLY_UNDERVALUED"),
        ("99",  "100", "SLIGHTLY_UNDERVALUED"),
        ("100", "100", "FAIRLY_VALUED"),           # D2 fix: exact 1.00 → fairly_valued
        ("105", "100", "FAIRLY_VALUED"),
        ("110", "100", "FAIRLY_VALUED"),
        ("111", "100", "OVERVALUED"),
        ("125", "100", "OVERVALUED"),
        ("126", "100", "SIGNIFICANTLY_OVERVALUED"),
    ]
    for cur, fv, expected in cases:
        ratio = Decimal(cur) / Decimal(fv)
        print(f"  price={cur:>3s}, fv={fv}, ratio={ratio:.2f} → {expected}")


if __name__ == "__main__":
    forward_pe()
    ev_ebitda()
    fcf_yield()
    dcf_all_scenarios()
    dcf_base_scenario()
    classification_boundaries()
    print("\nDone.")
