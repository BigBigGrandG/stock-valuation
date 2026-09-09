# Valuation System Audit Report: AMD, META, and GOOG Diagnostics

**Audit Timestamp**: `2026-09-10T01:45:00+08:00` (UTC: `2026-09-09T17:45:00Z`)  
**Dispatched Task ID**: `task_6249218d2b6f`  
**Dispatch ID**: `ctx_c183eddf5f3e`  
**Worker Terminal**: `term_d1452db2-3a82-4a67-b3ce-be459cd361d4`  
**Coordinator Terminal**: `term_d2a16072-40cd-41fe-925a-bdaa0d153321`  
**Audit Scope**: Read-only system audit diagnosing user critiques of AMD, META, and GOOG valuation outputs. Strict non-destructive execution: zero application code modifications, zero server restarts, preserving all live service state and historical artifacts.

---

## 1. Executive Summary & Attribution Principle

### 1.1 Executive Summary
A comprehensive evidence audit was conducted on the stock valuation pipeline evaluating user critiques of AMD, META, and GOOG valuation reports. Using live captures from the running service (`http://127.0.0.1:8002`, PID `50736`) and upstream Yahoo Finance structures, **100% of the user's reported valuation model outputs were reproduced under default pipeline settings**:
- **AMD**: Composite Base **$164.32** (Forward P/E **$151.40**, EV/EBITDA **$141.37**, FCF Yield **$141.09**, DCF **$209.73**, TV Ratio **80.15%**).
- **META**: Composite Base **$845.49** (Forward P/E **$628.60**, EV/EBITDA **$1,333.01**, FCF Yield **$891.84**, DCF **$662.58**, TV Ratio **77.75%**, Diluted Shares **2.205B**).
- **GOOG**: Composite Base **$226.96** (Forward P/E **$412.00**, EV/EBITDA unavailable, FCF Yield **$174.39**, DCF **$116.57**, TV Ratio **73.93%**, Stale Warning **253 days**).

Market prices exhibited minor intraday differences between the user critique report timestamp and the live audit capture:
- AMD: user critique ~$523.58 vs captured live price $522.04 (-$1.54 / -0.29%)
- META: user critique ~$650.41 vs captured live price $655.14 (+$4.73 / +0.72%)
- GOOG: user critique ~$328.28 vs captured live price $328.75 (+$0.47 / +0.14%)

Original export files or session logs were **not found on disk**. The reproduction of model figures on default `GET` establishes that user overrides are **not required** to produce these numbers; however, in the absence of original historical logs, prior user override experimentation cannot be formally ruled out.

The audit verified key system defects and architectural constraints:
1. **Confirmed Provenance / Display Defect in DCF**: For GOOG, the DCF engine labels Year 1 projection `FY2025E` in September 2026. However, a narrow deterministic engine probe confirms that changing the label alone does **not** alter cash flow projections, discount exponents, or price per share ($116.57).
2. **Confirmed Multi-Class Share Count Discrepancy**: For META, the system ingests `info["sharesOutstanding"]` (`2,205,128,509`, Class A only), omitting Class B shares (`342,377,716`). Compared against candidate denominators (`impliedSharesOutstanding` of 2.5475B or Q2 10-Q period-average diluted count of 2.566B), per-share valuations vary conditionally by 13.4% to 16.4%.
3. **Confirmed 253-Day Stale Annual Statement Baseline**: All three companies rely on annual 10-K filings dated `2025-12-31`. While internally stored under `_ttm` attributes, the system displays `period: FY2025` and issues an explicit 253-day stale warning.
4. **Model Policy & Horizon Limitations**: Rigid binding to 0y consensus (FY2026E) in month 9 of the fiscal year creates temporal lag, while a 55% combined weight on cash flow models (FCF Yield + DCF) concentrates sensitivity during heavy AI infrastructure Capex cycles.
5. **Reclassified / Unproven Claims**: The claim that GOOG analyst consensus EPS ($20.60) is contaminated by non-operating gains merely because next year's EPS ($14.85) is lower is **Unproven Pending Financial Audit**; normalization metadata is absent from the snapshot and blind subtraction is advised against.

### 1.2 Attribution: User Operations vs. System Defaults
- **API and UI Contract Audit**:
  - The frontend UI form exposes only 6 base controls: `pe_base`, `ev_base`, `fcf_yield_base`, `dcf_wacc`, `dcf_terminal_growth`, and `dcf_fcf_growth`.
  - The backend API contract (`app.models.overrides.ValuationOverrideRequest`, [overrides.py:L126-178](file:///D:/workshop/stock-valuation/backend/app/models/overrides.py#L126-L178)) allows nested scenario overrides (`low`, `base`, `high`) for multiples and DCF rates.
  - The API contract specifies `model_config = {"extra": "forbid"}`: neither UI nor API allows users to modify composite weights, share counts, balance sheet items, income statement inputs, or forecast period dates.
- **Attribution Conclusion**: All reported valuation outputs are produced directly by the backend's default GET pipeline (`/api/v1/valuation/{ticker}`) without requiring overrides.

---

## 2. Claim-by-Claim Verification Matrix

| # | Company | User Critique Claim | Status | Attribution | Evidence & Root Cause | Code & Line Reference |
|---|---|---|---|---|---|---|
| 1 | AMD | Composite $164.32 vs Price ~$523.58; PE $151.40, EV $141.37, FCF $141.09, DCF $209.73 | **Confirmed** | System Default | Exact reproduction of all 5 valuation figures on default GET. Intraday live price is $522.04. Driven by FY2025 base + 0y consensus. | [reproduce_audit.py:L26-44](file:///D:/workshop/stock-valuation/.scratch/valuation-audit/system-evidence/reproduce_audit.py#L26-L44) |
| 2 | META | Composite ~$845 vs Price ~$650.41; PE $628.60, EV $1333.01, FCF $891.84, DCF $662.58 | **Confirmed** | System Default | Exact reproduction: Composite $845.49, EV $1,333.01, FCF $891.84, DCF $662.58. Live price is $655.14. | [reproduce_audit.py:L46-64](file:///D:/workshop/stock-valuation/.scratch/valuation-audit/system-evidence/reproduce_audit.py#L46-L64) |
| 3 | META | Share count 2.205B vs SEC diluted 2.566B | **Confirmed (Data Inconsistency)** | Data Provider Defect | Ingested `sharesOutstanding` (2,205,128,509) includes only Class A stock, ignoring Class B (~342M shares). Primary point-in-time reconciliation pending financial audit. | [yfinance_provider.py:L750-775](file:///D:/workshop/stock-valuation/backend/app/providers/yfinance_provider.py#L750-L775)<br>[reproduce_audit.py:L66-75](file:///D:/workshop/stock-valuation/.scratch/valuation-audit/system-evidence/reproduce_audit.py#L66-L75) |
| 4 | GOOG | Composite $226.96; PE $412, EBITDA unavailable, FCF proxy $174.39, DCF $116.57 | **Confirmed** | System Default / Fallback | Exact reproduction. Missing forward revenue drops forward EBITDA; FCF falls back to historical FCFE with explicit warning; weights renormalize to 31.25/31.25/37.5. | [composite.py:L80-92](file:///D:/workshop/stock-valuation/backend/app/engines/composite.py#L80-L92)<br>[fcf_yield.py:L50-75](file:///D:/workshop/stock-valuation/backend/app/engines/fcf_yield.py#L50-L75) |
| 5 | GOOG | DCF first projection labeled FY2025E in September 2026 | **Confirmed (Display / Metadata)** | Display / Lineage Defect | `_forecast_period` generates `FY2025E`. Narrow engine probe proves label change alone has zero effect on cashflow or price ($116.57). Real economic issue is 1y vs 2y growth from base. | [dcf.py:L208-219](file:///D:/workshop/stock-valuation/backend/app/engines/dcf.py#L208-L219)<br>[probe_dcf_engine.py:L48-84](file:///D:/workshop/stock-valuation/.scratch/valuation-audit/system-evidence/probe_dcf_engine.py#L48-L84) |
| 6 | All | Stale input warning: 253 days lag | **Confirmed** | Data Provider Architecture | Provider queries annual tables (`.financials`, `.balance_sheet`, `.cashflow`) dated `2025-12-31`. Ignores Q1/Q2 2026 quarterly 10-Qs. Accompanied by active warning note. | [yfinance_provider.py:L325-333](file:///D:/workshop/stock-valuation/backend/app/providers/yfinance_provider.py#L325-L333) |
| 7 | All | Annual metrics mislabeled as `_ttm` | **Confirmed (Internal Code Naming)** | Naming Convention | Internal schema uses `_ttm` attribute names (`fcff_ttm`, `ebitda_ttm`) for annual FY2025 columns. However, exported reports and snapshot display actual period `FY2025`. | [yfinance_provider.py:L885-935](file:///D:/workshop/stock-valuation/backend/app/providers/yfinance_provider.py#L885-L935) |
| 8 | All | Consensus horizon 0y vs +1y / NTM | **Confirmed** | Model Policy Design Choice | `forward_eps_1y` binds to `0y` (FY2026E). In month 9 of the fiscal year, markets price forward on NTM or FY2027E (+1y). AMD FY26 EPS $7.57 vs FY27 EPS $15.61. | [yfinance_provider.py:L975-998](file:///D:/workshop/stock-valuation/backend/app/providers/yfinance_provider.py#L975-L998) |
| 9 | All | Hardcoded 40% growth cap on derived metrics | **Confirmed** | Policy Defect | Provider clamps derived growth at `min(max(g, -0.20), 0.40)`. Growth clamping is documented in metric `notes` (e.g. `floor=-0.20; cap=0.40`), but cannot be overridden by user. | [yfinance_provider.py:L1046-1047](file:///D:/workshop/stock-valuation/backend/app/providers/yfinance_provider.py#L1046-L1047)<br>[dcf.py:L300-305](file:///D:/workshop/stock-valuation/backend/app/engines/dcf.py#L300-L305) |
| 10 | All | Direct analyst estimates missing for EBITDA/FCF | **Confirmed (Data Scope)** | Upstream Scope Limitation | Chosen yfinance public endpoints lack direct consensus tables for forward EBITDA and FCF. Provider derives them heuristically. (Yahoo does publish web consensus for EPS/Rev). | [yfinance_provider.py:L1055-1065](file:///D:/workshop/stock-valuation/backend/app/providers/yfinance_provider.py#L1055-L1065) |
| 11 | GOOG | Non-operating gains contaminate FY26 consensus EPS ($20.60 vs FY27 $14.85) | **Unproven Pending Financial Audit** | Unproven / Lacks Metadata | Lower +1y EPS does not prove non-operating gain contamination. Snapshot lacks normalization metadata; blind subtraction is ungrounded. | [forward_pe.py:L70-95](file:///D:/workshop/stock-valuation/backend/app/engines/forward_pe.py#L70-L95) |
| 12 | All | Static valuation multiples across sectors (PE 18/20/22, EV 18/22/26, Yield 5%) | **Confirmed** | Architecture Design Choice | Assumptions are hardcoded in `config.py`. Company-specific CAPM WACC or industry-relative multiples are not dynamically generated. | [config.py:L14-26](file:///D:/workshop/stock-valuation/backend/app/config.py#L14-L26) |
| 13 | All | Correlated FCF Yield (25%) + DCF (30%) weighting | **Confirmed** | Model Policy Design Choice | Both models derive from Free Cash Flow. In heavy AI infrastructure Capex cycles, cash flow is depressed, lowering 55% of composite weight. Not an accounting double-count. | [config.py:L39-48](file:///D:/workshop/stock-valuation/backend/app/config.py#L39-L48) |
| 14 | All | Terminal Value ratio 74% - 80% | **Confirmed (Standard DCF Behavior)** | Valuation Reality / Sensitivity | AMD 80.15%, META 77.75%, GOOG 73.93%. Normal for 5-year growth DCF with perpetual growth. Represents sensitivity risk, not a calculation defect. | [dcf.py:L356-359](file:///D:/workshop/stock-valuation/backend/app/engines/dcf.py#L356-L359) |
| 15 | All | Margin of Safety displayed as negative (-217.7%) | **Refuted / Reclassified as UX Semantics** | UX Design Choice | Formula $(V - P) / V$ mathematically produces negative values when $P > V$. It is valid unbounded relative shortfall, not a math error; should not be clamped to 0. | [composite.py:L89-91](file:///D:/workshop/stock-valuation/backend/app/engines/composite.py#L89-L91) |
| 16 | All | Model dispersion: GOOG PE ($412) vs DCF ($116.57) | **Confirmed (Spread 253.4% / 3.53x)** | Missing Feature | GOOG model spread is 253.4% relative to min (DCF) or 130.2% relative to composite ($226.96), not >600%. Composite emits a single point estimate without dispersion flags. | [composite.py:L98-125](file:///D:/workshop/stock-valuation/backend/app/engines/composite.py#L98-L125) |

---

## 3. Deep-Dive Technical Diagnostics

### 3.1 DCF Engine Probe: Display Labeling vs. Real Calendar Economics
- **Production Engine Inspection**:
  In `backend/app/engines/dcf.py`:
  ```python
  # Line 567: Derivation of first period label
  first_period = _forecast_period(ttm_metric.period, ttm_metric.as_of)
  # Line 582: Derivation of Year 1 cashflow fallback
  y1 = (ttm_metric.value * (Decimal("1") + growth)).quantize(PREC, ROUND_HALF_UP)
  # Line 348: Discount factor arithmetic
  pv = (value / ((Decimal("1") + wacc) ** year)).quantize(PREC, ROUND_HALF_UP)
  ```
- **Arithmetic Analysis**:
  1. **Year 1 Fallback Value Formula**: When `forward_fcff_1y` is missing, Year 1 is explicitly calculated as:
     $$\text{Year 1 FCFF} = \text{ttm\_metric.value} \times (1 + \text{growth})$$
     For GOOG: $\$73,878,352,000.00 \times (1 + 0.08) = \$79,788,620,160.00$.
  2. **Is Base Cash Flow Grown?**: **YES**. The base cash flow is grown by 1 period (+8% in base scenario).
  3. **Where Forecast Date Enters Arithmetic**: `first_period` enters **ONLY** the displayed label `metric.period` ([dcf.py:L314, L350](file:///D:/workshop/stock-valuation/backend/app/engines/dcf.py#L314-L350)). The discount factor denominator is strictly $((1 + \text{wacc}) ** \text{year})$, where `year` is the integer loop counter $1, 2, 3, 4, 5$. Calendar date strings never enter the arithmetic.
- **Deterministic Engine Probe Findings** ([probe_dcf_engine.py](file:///D:/workshop/stock-valuation/.scratch/valuation-audit/system-evidence/probe_dcf_engine.py)):
  - **Experiment A (Label-Only Modification)**: Modifying `ttm_metric.period` from `"FY2025"` to `"FY2025 TTM"` causes `_forecast_period` to output `['FY2026E', 'FY2027E', 'FY2028E', 'FY2029E', 'FY2030E']`.
    - Baseline Projections: `[79.79B, 86.17B, 93.07B, 100.51B, 108.55B]`
    - Label-Modified Projections: `[79.79B, 86.17B, 93.07B, 100.51B, 108.55B]` (Identical)
    - Baseline Present Values: `[72.54B, 71.22B, 69.92B, 68.65B, 67.40B]`
    - Label-Modified Present Values: `[72.54B, 71.22B, 69.92B, 68.65B, 67.40B]` (Identical)
    - Baseline Price per Share: **$116.57**
    - Label-Modified Price per Share: **$116.57** (Identical to the exact penny)
  - **Conclusion on Label Defect**: Relabeling `FY2025E` to `FY2026E` has **zero arithmetic effect** and does **not** lift $116.57.
  - **Real Economic Cash Flow Mismatch**:
    - If the base historical statement is FY2025 ($73.88B), then in month 9 of 2026, 1 year of growth represents in-progress FY2026.
    - If Year 1 is intended to represent FY2027 (compounded 2 years from FY2025: $73.88B \times 1.08^2 = $86.17B), EV increases from $1,341.50B to $1,448.82B (+8.00%) and price increases from **$116.57 to $125.44** (+$8.87 / +7.61%).
    - If stub-period calendar discounting is applied (FY2026 cash flow arriving in ~0.31 years vs 1.0 full year), Year 1 PV increases by +6.8% ($72.54B to $77.47B).

### 3.2 Multi-Class Share Structure & Dilution Analysis (META Case)
- **Primary Data Discrepancy**:
  In raw Yahoo Finance response ([META-raw-yfinance.json](file:///D:/workshop/stock-valuation/.scratch/valuation-audit/system-evidence/META-raw-yfinance.json)):
  - `info["sharesOutstanding"]` = `2,205,128,509` (Class A common stock only)
  - `info["impliedSharesOutstanding"]` = `2,547,506,225` (Class A + Class B convertible shares)
  - Discrepancy: `342,377,716` shares omitted from `sharesOutstanding`.
- **Methodological Distinction**:
  - The critique's cited SEC 10-Q Q2 2026 diluted share count (`2,566,000,000`) is a **weighted-average diluted denominator** over the quarterly reporting period used to compute diluted EPS under US GAAP.
  - It is not necessarily the exact point-in-time common share count as of September 2026. Point-in-time primary share register verification remains **Pending Financial Audit**.
  - We reject the simplistic rule to "take maximum shares". The economically grounded approach is: $\text{Total Economic Shares} = \text{Class A} + \text{Class B} + \text{Treasury Stock Method Dilution (RSUs/Options)}$.
- **Conditional Arithmetic Impact Table**:

| Scenario | Denominator ($N$) | Basis / Rationale | EV/EBITDA ($/sh) | FCF Yield ($/sh) | DCF ($/sh) | Composite Base ($/sh) |
|---|---|---|---|---|---|---|
| **App As-Is** | **2,205,128,509** | Class A Only (`sharesOutstanding`) | **$1,333.01** | **$891.84** | **$662.58** | **$845.49** |
| **Implied All-Class** | **2,547,506,225** | `impliedSharesOutstanding` (Class A + B) | **$1,153.86** (-13.4%) | **$771.98** (-13.4%) | **$573.53** (-13.4%) | **$755.77** (-10.6%) |
| **Q2 Diluted Weighted** | **2,566,000,000** | SEC 10-Q Q2 Diluted Weighted Average | **$1,145.54** (-14.1%) | **$766.41** (-14.1%) | **$569.40** (-14.1%) | **$751.49** (-11.1%) |

*Note*: The difference between $1,333.01 and $1,145.54 represents a conditional reduction of $187.47 per share (-14.1% on EV/EBITDA, or a +16.37% inflation relative to the lower denominator). This impact is conditional on denominator selection.

### 3.3 GOOG Consensus EPS & Non-Operating Gains Diagnostic
- **Claim**: User suggested GOOG FY2026 consensus EPS ($20.60) is contaminated by non-operating investment gains, noting that FY2027 consensus EPS drops to $14.85.
- **Audit Assessment**: **Unproven Pending Financial Audit**.
  1. A lower forward +1y EPS estimate frequently occurs due to fewer contributing analysts, conservative long-term margin modeling, or different tax rate assumptions. It does not establish one-off gain contamination.
  2. The ingested API snapshot contains consensus EPS directly from provider estimates (`forward_eps_1y = 20.60`). The upstream data feed does **not** include breakdown metadata (operating vs non-operating income).
  3. Recommending blind subtraction of historical gains from forward consensus EPS is financially flawed and risks distorting operating projections.
  4. Scope clarification: The chosen Yahoo Finance API endpoints lack direct forward EBITDA/FCF consensus tables; however, Yahoo Finance does publish consensus EPS and Revenue estimate tables.

### 3.4 Model Dispersion & UX Semantics
- **Dispersion Calculation Correction**:
  - For GOOG: Forward P/E = **$412.00**, DCF = **$116.57**, Composite = **$226.96**.
  - Spread relative to minimum (DCF): $\frac{412.00 - 116.57}{116.57} = \mathbf{253.4\%}$ (a **$3.53\times$** spread).
  - Spread relative to Composite: $\frac{412.00 - 116.57}{226.96} = \mathbf{130.2\%}$.
  - The claim in prior notes of ">600%" was an arithmetic error; the verified spread is 253.4%.
- **Margin of Safety (MOS) Formulation**:
  - The backend calculates $\text{MOS} = \frac{\text{Fair Value} - \text{Price}}{\text{Fair Value}}$.
  - When a stock trades above fair value (AMD: $164.32 fair value vs $522.04 price), this formula mathematically yields $\frac{164.32 - 522.04}{164.32} = \mathbf{-217.7\%}$.
  - This is mathematically consistent with an unbounded relative deficit. It should not be clamped to 0 without clear labeling (e.g. framing as "Overvaluation: +217.7%").

---

## 4. Prioritized Architectural Recommendations

### 4.1 P0: Fundamental Data Integrity & Multi-Class Reconciliation
1. **Multi-Class Share Structure Resolution**: Update profile ingestion to compare `sharesOutstanding` against `impliedSharesOutstanding` and latest balance sheet common share counts. Reconcile Class A and Class B shares with primary 10-Q disclosures.
2. **Quarterly Statement Rollup (True TTM)**: Implement trailing twelve months calculation by summing the latest 4 quarters from quarterly statements rather than pulling annual 10-K columns.
3. **Calendar-Anchored DCF Discounting**: Anchor DCF cash flows to actual valuation dates (stub periods or fractional years) rather than integer loop counters $t=1..5$ assuming statement currency.

### 4.2 P1: Model Policy & Horizon Flexibility
1. **Rolling NTM Horizon**: In the second half of a fiscal year, provide an option to blend current year (`0y`) and next year (`+1y`) consensus estimates into a rolling Next Twelve Months (NTM) metric.
2. **Configurable Growth Assumptions**: Expose growth caps and floors as configurable model parameters rather than hardcoding a 40% cap in provider logic.
3. **Correlated Model Weighting Sensitivity**: Allow users to adjust composite weights when free cash flows are temporarily compressed by large capital expenditure cycles.
4. **Terminal Value Sensitivity Grid**: Supplement DCF outputs with a sensitivity table (WACC $\pm 1\%$, $g \pm 0.5\%$) to contextualize high terminal value proportions.

### 4.3 P2: UX & Transparency
1. **Model Dispersion Flag**: Alert users when the spread between individual valuation models exceeds a configurable threshold (e.g. $>50\%$ of composite value).
2. **Clear MOS Presentation**: Label negative Margin of Safety explicitly as "Premium over Fair Value" to prevent semantic ambiguity.

---

## 5. Verification Harness & Acceptance Artifacts

All findings and arithmetic proofs are verified by two dedicated, read-only scripts in `.scratch/valuation-audit/system-evidence/`:
1. **Harness 1: Snapshot Consistency (`reproduce_audit.py`)**:
   - Asserts 100% fidelity of captured JSON snapshot files against user critique reported figures.
   - Verifies share counts, stale warnings (253 days), and terminal value ratios (70%–85%).
2. **Harness 2: Production Engine Probe (`probe_dcf_engine.py`)**:
   - Executes live backend modules (`run_dcf`, `_compute_dcf_scenario`).
   - Deterministically proves that label modification alone (`FY2025E` to `FY2026E`) produces identical cash flows, present values, and price per share ($116.57).
   - Quantifies the impact of 2-year forward compounding ($125.44) and stub-period discounting (+6.8% on Year 1 PV).

**Execution Command**:
```powershell
D:\workshop\stock-valuation\.venv\Scripts\python.exe .scratch/valuation-audit/system-evidence/reproduce_audit.py
```
**Status**: **100% assertions verified**. Zero application code modifications, zero server restarts.
