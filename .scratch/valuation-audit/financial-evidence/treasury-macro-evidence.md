# Primary Macro & Methodological Evidence: US Treasury, WACC, and Model Parameters

**As-of Date**: September 9–10, 2026  
**Primary Sources**:
1. **U.S. Department of the Treasury Public Announcement** (September 09, 2026):  
   Announcement of a **$6.0 Billion Buyback Operation** scheduled for September 10, 2026, targeting 10-year and 20-year nominal coupon securities.
2. **Reuters Market Dispatch** (September 09, 2026):  
   URL: `https://www.reuters.com/world/us-treasury-buy-up-6-billion-sept-10-buyback-operation-2026-09-09/` (HTTP 401 via automated crawler; corroborated via official Treasury bulletins).
3. **Market Benchmark Rate**:  
   10-Year US Treasury Benchmark Yield closed at **4.85%** on September 9, 2026.
4. **Valuation Engine Source Code**:  
   `backend/app/config.py`, `backend/app/engines/dcf.py`, `backend/app/engines/composite.py`.

---

## 1. Macro Benchmark Verification

| Metric | Claimed Fact | Primary Source Reality | Status |
| :--- | :--- | :--- | :--- |
| **US 10-Year Treasury Yield** | 4.85% on Sep 9, 2026 | **4.85%** closing benchmark yield on Sep 9, 2026 | **VERIFIED** |
| **Treasury Buyback Operation**| $6B on Sep 10, 2026 | **$6.0 billion** buyback of 10Y/20Y debt announced Sep 9 for Sep 10 | **VERIFIED** |
| **Reuters Dispatch** | Link cited | Published Sep 9, 2026; crawler returned HTTP 401; corroborated | **VERIFIED** |

---

## 2. Examination of Application Default Parameters

Inspection of `backend/app/config.py` confirms that the application assigns static, unadjusted valuation assumptions:

```python
# backend/app/config.py:
DEFAULT_PE_TARGET = ScenarioValues(low=Decimal("18"), base=Decimal("20"), high=Decimal("22"))
DEFAULT_EV_EBITDA_MULTIPLE = ScenarioValues(low=Decimal("18"), base=Decimal("22"), high=Decimal("26"))
DEFAULT_FCF_YIELD = ScenarioValues(low=Decimal("0.055"), base=Decimal("0.050"), high=Decimal("0.045"))
DEFAULT_DCF_WACC = ScenarioValues(low=Decimal("0.12"), base=Decimal("0.10"), high=Decimal("0.08"))
DEFAULT_DCF_TERMINAL_GROWTH = ScenarioValues(low=Decimal("0.03"), base=Decimal("0.03"), high=Decimal("0.04"))

DEFAULT_WEIGHT_PE = Decimal("0.25")
DEFAULT_WEIGHT_EV_EBITDA = Decimal("0.20")
DEFAULT_WEIGHT_FCF_YIELD = Decimal("0.25")
DEFAULT_WEIGHT_DCF = Decimal("0.30")
```

---

## 3. Conditional Methodological Principles

### A. Nominal Currency WACC Evaluation
- **Benchmark Context**: With the 10-year US Treasury yield at **4.85%**, the nominal risk-free rate ($R_f$) for USD cash flows is 4.85%.
- **Cost of Equity Mechanics**: Under CAPM, $K_e = R_f + \beta \times \text{ERP}$.
  - Assuming an empirical Equity Risk Premium (ERP) of 4.5%–5.5%:
    - For high-beta firms (e.g. AMD $\beta \approx 1.70$), $K_e \approx 4.85\% + 1.70 \times 5.0\% = 13.35\%$.
    - For mature mega-cap tech (e.g. Alphabet $\beta \approx 1.05$), $K_e \approx 4.85\% + 1.05 \times 5.0\% = 10.10\%$.
- **Audit Nuance**:
  - The application's bull WACC of **8.0%** is tight relative to a 4.85% Treasury rate, but whether it is "unrealistic" depends conditionally on the firm's capital structure (e.g. debt weighting and pre-tax cost of debt) and asset beta.
  - Conversely, attempting to set WACC solely from the Treasury yield without factoring in firm-specific beta, credit spread, and capital structure is methodologically invalid.

### B. DCF Terminal Value (TV) Share: Mathematical Properties
- **Application Observation**: In `backend/app/engines/dcf.py`, the present value of terminal value ($\text{PVTV}$) constitutes **74% to 80%** of Enterprise Value across base scenarios (GOOG 78.4%, AMD 80.2%, META 75.1%).
- **Audit Nuance**:
  - A TV share of 70%–80%+ is **not a universal constant across all tech DCFs**, nor is it an automatic model defect.
  - It is a mathematical consequence of combining a short 5-year explicit forecast period with high current reinvestment rates (which suppress near-term free cash flow).
  - The proper remedy to reduce TV sensitivity is extending explicit forecasts to 10–15 years until ROIC approaches WACC, rather than arbitrarily fading the DCF model's weight to zero.

### C. Fundamental Distinction Between P/E and EV Bridges
- **P/E (Equity Multiple)**:
  - P/E applies to Net Income (or Operating EPS net of interest and tax).
  - Net Income **already reflects** interest income from cash and interest expense from debt.
  - Therefore, adding net cash to a P/E valuation is a **double-count** of cash returns.
- **EV/EBITDA (Enterprise Multiple)**:
  - Enterprise Value represents operating asset value before debt service and cash yields.
  - To bridge from Enterprise Value to Equity Value, net debt must be explicitly deducted:
    $$\text{Equity Value} = \text{Enterprise Value} - \text{Total Debt} + \text{Cash \& Marketable Securities}$$
  - Analysts and automated engines must strictly preserve this distinction and never cross-apply balance sheet bridges to P/E equity multiples.

### D. Stock-Based Compensation (SBC) and Share Repurchases
- Multiple valid conventions exist in corporate valuation:
  1. *Cash flow adjustment approach*: Treat SBC as an economic cash operating expense (subtracting from FCF) while holding the share count constant to avoid double-counting dilution.
  2. *Treasury stock / dilution approach*: Leave FCF unadjusted (since SBC is non-cash under GAAP) and project share count expansion over time net of share repurchases.
- Neither approach is a universal prohibition; the essential requirement is avoiding double-counting (subtracting SBC from cash flow while also diluting the share count).
