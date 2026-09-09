# Financial Correctness Review — US Stock Valuation MVP (v2 — Corrected)

**Reviewer:** Independent financial-correctness agent (read-only)
**Original review:** 2026-09-07 (v1)
**Corrected review:** 2026-09-07 (v2 — arithmetic errors in numeric tables corrected; D1/D5 severity recalibrated; D2 status updated)
**Oracle:** `.scratch/valuation-mvp/math_oracle.py` (run with `python math_oracle.py`)

**Files reviewed:**
- `.scratch/valuation-mvp/spec.md`
- `backend/app/models/domain.py` (current state, D2 already fixed)
- `backend/app/engines/forward_pe.py`, `ev_ebitda.py`, `fcf_yield.py`, `dcf.py`, `composite.py`
- `backend/tests/` — all 5 test files; 44 tests pass as of this review

**Pending (not defects):**
- Provider/fixture layer, API routers, override handler, cache layer, frontend

---

## 0. Arithmetic Corrections from v1

The v1 review contained LLM-arithmetic errors in the numeric acceptance tables. All figures below are derived from `math_oracle.py` using Python `Decimal` with `ROUND_HALF_UP`. The corrected values match those independently computed by the coordinator.

| Table | v1 (wrong) | v2 (Decimal-correct) |
|-------|-----------|----------------------|
| EV/EBITDA base price (×22) | $519.88 | **$519.68** |
| EV/EBITDA low price (×18) | $424.09 | **$423.89** |
| EV/EBITDA high price (×26) | $615.67 | **$615.47** |
| FCF Yield low price (yield=0.055) | $329.98 | **$329.78** |
| DCF base price | $297.74 | **$297.78** |

---

## 1. Test Suite Status

All 44 tests pass:
```
44 passed in 0.14s
```

| Test file | Tests | Status |
|-----------|-------|--------|
| test_forward_pe.py | ~6 | PASS |
| test_ev_ebitda.py | ~5 | PASS |
| test_fcf_yield.py | ~6 | PASS |
| test_dcf.py | ~8 | PASS |
| test_composite_classification.py | ~12 | PASS |

---

## 2. D2 — Classification Boundary — RESOLVED ✅

**Status: Fixed. Not a defect in current code.**

The v1 review flagged that `ratio == 1.00` was incorrectly classified as `SLIGHTLY_UNDERVALUED`. This has been corrected in `domain.py`. The current implementation uses explicit `if/elif` guards instead of the boundary table loop:

```python
# domain.py lines 286–298 (current)
if ratio <= Decimal("0.80"):
    return ValuationClassification.SIGNIFICANTLY_UNDERVALUED
if ratio <= Decimal("0.90"):
    return ValuationClassification.UNDERVALUED
if ratio < Decimal("1.00"):                 # strict <
    return ValuationClassification.SLIGHTLY_UNDERVALUED
if ratio <= Decimal("1.10"):                # includes ratio == 1.00
    return ValuationClassification.FAIRLY_VALUED
...
```

`test_composite_classification.py` line 64 verifies: `("100", "100", ValuationClassification.FAIRLY_VALUED)` — **this test passes**.

---

## 3. D1 — DCF Rounding — RECLASSIFIED: Minor Rounding Policy (LOW)

**Status: Reclassified from HIGH to LOW. No measurable error for AVGO fixture.**

The v1 review claimed the iterative growth compounding loop in `dcf.py` lines 120–127 accumulated material rounding error and marked it HIGH severity. This was unsubstantiated.

### Decimal-computed evidence

Running `math_oracle.py` with AVGO fixture (FCFF=89,600,000,000, g=0.08, WACC=0.10) shows **zero difference** between the iterative and power-formula approaches:

| Year | FCFF [iter] | FCFF [power] | ΔPV |
|------|-------------|--------------|-----|
| 1 | 89,600,000,000.00 | 89,600,000,000.00 | 0.00 |
| 2 | 96,768,000,000.00 | 96,768,000,000.00 | 0.00 |
| 3 | 104,509,440,000.00 | 104,509,440,000.00 | 0.00 |
| 4 | 112,870,195,200.00 | 112,870,195,200.00 | 0.00 |
| 5 | 121,899,810,816.00 | 121,899,810,816.00 | 0.00 |
| **ΔPrice** | | | **$0.00** |

**Why:** AVGO's FCFF values (multiples of $89.6B × clean growth rates) happen to produce exact Decimal representations with at most 2 decimal places at each step. No rounding loss occurs.

### Revised assessment

The concern is a **theoretical rounding policy observation** (not an empirical defect for this fixture): for inputs where `fcff_year1 × (1+g)^k` produces more than 2 decimal places before the `quantize` step, the iterative approach and power approach could diverge by at most a few cents per year. In practice:
- The spec does not mandate a power formula specifically.
- The `test_dcf.py` suite correctly uses `_compute_dcf_scenario` and independently verifies each year's PV against the expected formula — the engine's behavior is tested and verified.
- The coordinator-supplied exact PVs (81,454,545,454.55 / 79,973,553,719.01 / 78,519,489,105.94 / 77,091,862,031.28 / 75,690,191,812.53) match both approaches for AVGO.

**Revised severity: LOW — rounding policy improvement, not a functional defect.**
**Recommendation:** Note in comments that the iterative approach may accumulate rounding on non-round FCFF inputs. No code change required for MVP.

---

## 4. D5 — Growth-Cliff Warning — RECLASSIFIED: Optional Enhancement (INFO)

**Status: Reclassified from LOW defect to optional enhancement. Not a required bug.**

The v1 review flagged that DCF does not warn when the 5-year growth rate greatly exceeds terminal growth. The spec says "no extreme perpetual growth" (referring to terminal growth), and the cap rules in `_get_fcff_growth` enforce limits (25%/30%/35%). There is no spec requirement for a growth-cliff warning. Adding such a warning would be a quality-of-life enhancement for the UI, not a correctness defect.

**Recommendation:** Consider as a future enhancement if users report confusing valuation narratives. No action required for MVP.

---

## 5. FCFE vs FCFF Separation — PASS ✅

All three separation concerns pass correctly:

| Check | Engine | Status |
|-------|--------|--------|
| FCFE fields used in FCF yield | `fcf_yield.py` L49, L52 | PASS |
| FCFF fields used in DCF | `dcf.py` L179 | PASS |
| FCFE detected in DCF path → explicit error | `dcf.py` L182–185 | PASS |
| FCFType enum defined | `domain.py` L42–50 | PASS |
| `test_fcfe_not_fcff_provenance` | test_composite_classification.py L166–171 | PASS |

---

## 6. D4 — DCF Growth Fallback Uses FCFE Field — MEDIUM (Remains Open)

**Location:** `dcf.py` line 78. **Status: Still open.**

```python
growth_proxy = snapshot.fcff_growth or snapshot.fcf_growth or snapshot.eps_growth or snapshot.revenue_growth
```

`snapshot.fcf_growth` is an FCFE-side field (`domain.py` L119). Its inclusion in the DCF (FCFF-only) growth fallback chain violates the spec's stated priority order (spec line 29) and may produce materially incorrect projections for leveraged companies where FCFE growth and FCFF growth diverge.

**Acceptance expectation:** The DCF growth fallback should use only `fcff_growth` (and `eps_growth`/`revenue_growth` as proxies). `fcf_growth` (FCFE) should be removed or annotated with a warning.

---

## 7. D3 — Composite Partial Low/High Accumulation — MEDIUM (Remains Open)

**Location:** `composite.py` lines 50–58. **Status: Still open.**

```python
for name, result, weight in model_configs:
    if result.available and result.base is not None:
        total_weight += weight          # always adds full weight
        if result.low is not None:
            weighted_low += result.low.price_per_share * weight   # may skip
```

If a model has `base` but missing `low`/`high` (e.g., one DCF scenario fails), the full weight is added to `total_weight` but zero contributed to `weighted_low`/`weighted_high`. The renormalized composite `low`/`high` will be underweighted by that model's share.

**Acceptance expectation:**
- All models available (AVGO full fixture): `final_low = (pe_low×0.25 + ev_low×0.20 + fcf_low×0.25 + dcf_bear×0.30) / 1.00` — correct
- If DCF has base but no bear: currently `final_low = (pe_low×0.25 + ev_low×0.20 + fcf_low×0.25) / 1.00` — missing 30% contribution — **incorrect**
- Correct: `final_low = (pe_low×0.25 + ev_low×0.20 + fcf_low×0.25) / 0.70`

---

## 8. Remaining Minor Defects (LOW) — Status Unchanged

| ID | File | Lines | Description |
|----|------|-------|-------------|
| D6 | `forward_pe.py` | 52 | No warning when `forward_eps_2y` substituted for `forward_eps_1y` |
| D7 | `composite.py` | 72 | Normalized weights may not sum to 1.0000 due to per-weight rounding (display only) |
| D8 | `domain.py` | 125–126 | `net_debt` is a computed property; no `FinancialMetric` with independent `as_of` provenance |
| D9 | All engines | shares division | No guard that `diluted_shares.value > 0`; malformed fixture causes unhandled exception |

---

## 9. Invalid Domain Guards — PASS ✅

| Guard | Engine | Location | Status |
|-------|--------|----------|--------|
| Forward EPS ≤ 0 → unavailable | PE | `forward_pe.py` L66 | PASS |
| Forward EBITDA ≤ 0 → unavailable | EV | `ev_ebitda.py` L57 | PASS |
| Forward FCFE ≤ 0 → unavailable | FCF Yield | `fcf_yield.py` L66 | PASS |
| FCFF ≤ 0 → unavailable | DCF | `dcf.py` L198 | PASS |
| WACC ≤ g → raises ValueError | DCF | `dcf.py` L111 | PASS |
| Equity value ≤ 0 → warning only | DCF | `dcf.py` L142 | PASS |
| yield_rate ≤ 0 → raises ValueError | FCF Yield | `fcf_yield.py` L85 | PASS |
| NaN/Infinity in FinancialMetric | Domain | `domain.py` L79–82 | PASS |
| fair_value ≤ 0 in classify | Domain | `domain.py` L280 | PASS |
| FCFE used in DCF → explicit error | DCF | `dcf.py` L182–185 | PASS |
| diluted_shares > 0 | All | Missing | OPEN (D9) |

---

## 10. Corrected Independent Numeric Acceptance Expectations

**All values computed by `math_oracle.py` using Python `Decimal` with `ROUND_HALF_UP`.**

### 10.1 Forward P/E (EPS=19.21, multiples 18/20/22)

| Scenario | Formula | Price |
|----------|---------|-------|
| Low | 19.21 × 18 | **$345.78** |
| Base | 19.21 × 20 | **$384.20** |
| High | 19.21 × 22 | **$422.62** |

### 10.2 EV/EBITDA (EBITDA=118,300,000,000; net_debt=35,400,000,000; shares=4,940,000,000)

| Scenario | Multiple | EV | Equity | Price |
|----------|----------|----|--------|-------|
| Low | 18 | 2,129,400,000,000 | 2,094,000,000,000 | **$423.89** |
| Base | 22 | 2,602,600,000,000 | 2,567,200,000,000 | **$519.68** |
| High | 26 | 3,075,800,000,000 | 3,040,400,000,000 | **$615.47** |

*(v1 errors: low was $424.09, base was $519.88, high was $615.67 — all incorrect)*

### 10.3 FCF Yield (FCFE=89,600,000,000; shares=4,940,000,000)

| Scenario | Yield | Equity | Price |
|----------|-------|--------|-------|
| Low (highest yield) | 0.055 | 1,629,090,909,090.91 | **$329.78** |
| Base | 0.050 | 1,792,000,000,000.00 | **$362.75** |
| High (lowest yield) | 0.045 | 1,991,111,111,111.11 | **$403.06** |

Constraint: high_price ($403.06) > low_price ($329.78) ✅
*(v1 error: low was $329.98 — incorrect)*

### 10.4 DCF — Year-by-Year (Base: FCFF=89,600,000,000, g=8%, WACC=10%, tg=3%)

| Year t | FCFF | PV = FCFF/(1.10)^t |
|--------|------|--------------------|
| 1 | 89,600,000,000.00 | **81,454,545,454.55** |
| 2 | 96,768,000,000.00 | **79,973,553,719.01** |
| 3 | 104,509,440,000.00 | **78,519,489,105.94** |
| 4 | 112,870,195,200.00 | **77,091,862,031.28** |
| 5 | 121,899,810,816.00 | **75,690,191,812.53** |

Sum PV = 392,729,642,123.31
TV = FCFF_5 × 1.03 / 0.07 = **1,793,668,644,864.00**
PVTV = TV / (1.10)^5 = **1,113,727,108,098.68** (coordinator high-precision: 1,113,727,108,098.6768)
EV = sum(PV) + PVTV = **1,506,456,750,221.99**
Net debt = 35,400,000,000
Equity = **1,471,056,750,221.99**
Price = Equity / 4,940,000,000 = **$297.78**

*(v1 error: price was $297.74 — incorrect)*

### 10.5 DCF All Scenarios (AVGO fixture, iterative engine)

| Scenario | g | WACC | tg | Price |
|----------|---|------|----|-------|
| Bear (low) | 5% | 12% | 3% | **$207.46** |
| Base | 8% | 10% | 3% | **$297.78** |
| Bull (high) | 12% | 8% | 4% | **$588.28** |

WACC validation: 0.12 > 0.03 ✅, 0.10 > 0.03 ✅, 0.08 > 0.04 ✅

### 10.6 Classification Boundaries (per test_composite_classification.py)

| price | fv | ratio | Expected |
|-------|----|-------|---------|
| 79 | 100 | 0.79 | SIGNIFICANTLY_UNDERVALUED |
| 80 | 100 | 0.80 | SIGNIFICANTLY_UNDERVALUED |
| 81 | 100 | 0.81 | UNDERVALUED |
| 90 | 100 | 0.90 | UNDERVALUED |
| 91 | 100 | 0.91 | SLIGHTLY_UNDERVALUED |
| 99 | 100 | 0.99 | SLIGHTLY_UNDERVALUED |
| **100** | **100** | **1.00** | **FAIRLY_VALUED** ← D2 fixed |
| 105 | 100 | 1.05 | FAIRLY_VALUED |
| 110 | 100 | 1.10 | FAIRLY_VALUED |
| 111 | 100 | 1.11 | OVERVALUED |
| 125 | 100 | 1.25 | OVERVALUED |
| 126 | 100 | 1.26 | SIGNIFICANTLY_OVERVALUED |

---

## 11. Defect Summary (Updated)

| ID | Severity | File | Lines | Description | Status |
|----|----------|------|-------|-------------|--------|
| D1 | ~~HIGH~~ **LOW** | `dcf.py` | 120–127 | Iterative growth: zero measurable error for AVGO fixture; theoretical rounding policy concern only | Open (Low) |
| D2 | ~~HIGH~~ **RESOLVED** | `domain.py` | 286–298 | Classification `ratio==1.00` fix | Fixed ✅ |
| D3 | MEDIUM | `composite.py` | 50–58 | Partial low/high underweights composite when model has base but missing scenario | Open |
| D4 | MEDIUM | `dcf.py` | 78 | `fcf_growth` (FCFE) in DCF growth fallback; FCFF-only required | Open |
| D5 | ~~LOW~~ **INFO** | `dcf.py` | 111 | Growth-cliff warning: optional enhancement, not a required bug | Enhancement |
| D6 | LOW | `forward_pe.py` | 52 | No warning when `forward_eps_2y` substituted | Open |
| D7 | LOW | `composite.py` | 72 | Normalized weights display may not sum to 1.0000 | Open |
| D8 | LOW | `domain.py` | 125–126 | `net_debt` has no FinancialMetric provenance | Open |
| D9 | LOW | All engines | — | No `diluted_shares > 0` guard | Open |

**Open defects requiring code changes: D3 (MEDIUM), D4 (MEDIUM), D6–D9 (LOW)**

---

## 12. WACC Override Risk (Pending)

The WACC `ScenarioValues` inversion (`low=0.12` = bear, `high=0.08` = bull) is internally consistent in the engine but risks misinterpretation if a POST override handler exposes these as `low`/`base`/`high` keys to users. This remains a **pending review item** — the override handler is not yet present.

---

*Review v2 complete. All numeric values verified by `python .scratch/valuation-mvp/math_oracle.py`. No source files were modified.*
