# Independent Financial Fact-Check & Valuation Critique Audit

**Document Reference**: `.scratch/valuation-audit/financial-audit.md`  
**Audit As-Of Date**: September 9–10, 2026  
**Auditor**: Independent Dispatched Financial Worker (Context `ctx_e083e169cee4` / Task `task_0cd7186c8940`)  
**Scope**: Forensic review of financial assertions, primary regulatory filings, share capital structures, cross-market listing identifiers, arithmetic derivations, and valuation methodology across Advanced Micro Devices (AMD), Meta Platforms (META), Alphabet (GOOG/GOOGL), and US Treasury macro benchmarks.  
**Constraint Notice**: Strictly an audit of evidence, facts, and valuation arithmetic. No application code, test suite, or server changes implemented. This document does not provide investment recommendations or certify target prices.

---

## 1. Executive Summary

An external AI critique challenged the automated valuation outputs produced by the educational `stock-valuation` engine as of September 9, 2026, proposing revised valuation ranges for **AMD** ($451 / $516 / $582), **META** ($618 / $687 / $755), and **GOOG** ($289 / $335 / $363).

This audit investigated each contested assertion against primary regulatory filings (SEC Forms 10-Q and 10-K), official earnings releases, conference call transcripts, and U.S. Treasury public bulletins.

### Core Audit Conclusions:
1. **Fact-Checking Individual Claims**: Claims were individually investigated and classified. While official reported Q2 2026 operational figures (AMD revenue $11,536M, Data Center revenue $6,700M, FCF $1.56B; Meta CFO $31,862M, CapEx $31,078M, FCF $784M; Alphabet revenue $119.8B, CapEx $44.9B, negative FCF -$5.86B, cash & marketables $242.47B, total shares 12.230B) are verified from primary source statements, several key assertions (such as the specific "$6.26" EPS gain impact, and the non-GAAP status of consensus estimates) are **unverified derived estimates** or lack vendor metadata.
2. **Application Share Count Findings**:
   - **Alphabet**: Forensic analysis of the application's captured baseline proves that the engine used **12.088B shares** (Alphabet's stale FY2025 ending share count: $105.4B FCF / 12.088B shares / 0.05 yield = $174.39 ≈ $174). The engine did **not** use a 5.527B Class C denominator in that run. In Q2 2026, the official share count increased to **12.230B shares** across Class A, B, and C following $49.6B in equity capital raises.
   - **Meta Platforms**: The application snapshot exhibited an internal inconsistency: a raw `diluted_shares` field of **2,205,128,509** (Class A common stock only) alongside an implied share count from upstream Market Cap of **2,547,506,225** (basic common stock). Replacing the raw share denominator with the official diluted weighted-average count of **2,566 million** conditionally reduces the base composite valuation from **$845.49** to **$751.49** (-11.1%). The 16.4% denominator inflation applied strictly to the three share-divided models (EV/EBITDA, FCF Yield, DCF), while the Forward P/E model (based on per-share Forward EPS) was unchanged.
3. **Consensus Basis & Double-Counting Disclosures**:
   - The accounting basis (GAAP vs. Non-GAAP) of the cited FY26 ($20.60) and FY27 ($14.85) consensus EPS is **unverified** without explicit vendor metadata.
   - Alphabet recognized $98.0B in total Other Income, which included $99.0B in net equity gains under ASC 321. If FY27 consensus EPS ($14.85) already reflects operating earnings excluding non-operating marks, subtracting an additional $6.26 would be a double deduction.
   - Furthermore, because $242.47B in cash and marketable securities is added to Enterprise Value in the equity bridge, non-operating returns from those assets must not be capitalized in operating multiples.
4. **Target Valuation Recomputations & Discrepancies**:
   - The external AI's price targets reproduce with minor rounding deltas:
     - **AMD**: Recomputed $451.82 / $517.44 / $583.07 vs. claimed $451 / $516 / $582 (using 1.632B basic shares; base 28x EV multiple is circularly justified by current 27x market trading).
     - **META**: Recomputed $618.10 / $686.70 / $755.30 vs. claimed $618 / $687 / $755 (requires **inferred assumptions** of $33.90 EPS and +$6.16B net cash, and a discretionary 70/30 weighting).
     - **GOOG**: Recomputed $289.84 / $336.01 / $363.55 vs. claimed $289.00 / $335.00 / $363.00 (deltas: +$0.84, +$1.01, +$0.55). The net cash bridge uses only Long-Term Debt ($98.17B), which is incomplete without current debt obligations ($1,999M notes + $1.3B credit facilities).
   - **None of these target values are certified as accurate price targets**.

---

## 2. Master Financial Fact-Check Matrix

| # | Topic / Metric | Claimed Assertion | Primary Source & Section Identifier | Primary Source Reality / Exact Finding | As-Of Date | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | Macro Benchmark | 10-Year US Treasury Yield at 4.85% | Market Benchmark Feed / Treasury Bulletin | 10-Year Treasury Yield closed at **4.85%** on September 9, 2026. | Sep 09, 2026 | **VERIFIED** |
| **2** | Macro Benchmark | US Treasury $6B Buyback Operation | U.S. Treasury Public Bulletin (Sep 09, 2026); Reuters Dispatch | Treasury announced a buyback operation of up to **$6.0 billion** of 10Y/20Y nominal coupon debt scheduled for Sep 10, 2026. | Operation: Sep 10, 2026 | **VERIFIED** |
| **3** | AMD | Q2 2026 Revenue $11.54B (+50% YoY) | AMD Form 10-Q & PR (Aug 04, 2026), Condensed Statement of Operations | Net revenue was **$11,536 million** (Q2 2026) vs. **$7,685 million** (Q2 2025), Up **50.1%** YoY. | Three months ended Jun 27, 2026 | **VERIFIED** |
| **4** | AMD | Data Center Revenue +107% YoY (58% of Rev) | AMD Form 10-Q & PR, Segment Information | Data Center segment revenue was **$6,700 million** (+107.0% YoY from $3,237M), representing **58.1%** of total revenue. | Three months ended Jun 27, 2026 | **VERIFIED** |
| **5** | AMD | Q2 FCF $1.56B; H1 FCF $4.12B | AMD Form 10-Q & PR, Non-GAAP FCF Reconciliation | Operating Cash Flow was $1,810M less $250M CapEx = **$1,560 million** ($1.56B) Q2 FCF; Six-month FCF was **$4,120 million** ($4.12B). | Periods ended Jun 27, 2026 | **VERIFIED** |
| **6** | AMD | Cash & ST Investments $13.11B; Total Debt $3.23B | AMD Form 10-Q, Condensed Consolidated Balance Sheets | Cash & equiv: $6,840M; ST inv: $6,270M (Total: **$13,110M**). Short-term debt: $750M; LT debt: $2,480M (Total: **$3,230M**). Net cash: **+$9,880M**. | As of Jun 27, 2026 | **VERIFIED** |
| **7** | AMD | Common Shares Outstanding 1.632B | AMD Form 10-Q, Balance Sheet & Cover Page | Common stock issued & outstanding was **1,632 million** basic shares (Q2 diluted weighted shares was 1,666 million). | As of Jun 27, 2026 | **VERIFIED (Basic)** |
| **8** | AMD | Consensus 2026–28 Rev/EBITDA & FY27 EPS $15.45 | Secondary Aggregator Consensus | Compilations show averages: FY26E $50.8B/$13.4B; FY27E $87.7B/$29.12B; FY28E $120.4B/$43.6B; EPS $15.45. | Forward Estimates | **UNPROVEN (Secondary)** |
| **9** | META | Q2 2026 CFO $31.86B; CapEx $31.08B; FCF $0.784B | Meta Platforms Form 10-Q, Statement of Cash Flows & Release | CFO was **$31,862 million**; PPE purchases were **$30,116 million**; lease principal was **$962 million** (CapEx = **$31,078 million**). FCF was **$784 million**. | Three months ended Jun 30, 2026 | **VERIFIED** |
| **10** | META | 2026 Full-Year CapEx Guidance $130–$145B | Meta Platforms Q2 2026 Earnings Release, Outlook Section | Guidance narrowed to **$130–$145 billion** (updated from prior $125B–$145B). | Full Year 2026 Outlook | **VERIFIED** |
| **11** | META | Diluted Weighted-Average Shares 2,566M | Meta Platforms Form 10-Q, Statement of Operations | Weighted-average shares used to compute diluted EPS was **2,566 million**. | Three months ended Jun 30, 2026 | **VERIFIED** |
| **12** | META | App Shares 2.205B vs. Implied 2.5475B | Application Snapshot & Upstream Market Cap | Raw snapshot `diluted_shares` = **2,205,128,509** (Class A only); implied shares from Market Cap ($1.657T / $650.41) = **2,547,506,225**. | Captured Baseline | **VERIFIED (Discrepancy)** |
| **13** | META | FY27 Consensus EBITDA $180.8B & EPS ~$34 | Secondary Aggregator Consensus | Third-party consensus figures. Underlying vendor adjustments are unprovided. | Forward Estimates | **UNPROVEN (Secondary)** |
| **14** | GOOG | Q2 Revenue +24%; Cloud +82%; OpMargin 34% | Alphabet Form 10-Q, Statement of Income & Segment Note | Revenues were **$119.8B** (+24.1% YoY); Google Cloud was **$24.8B** (+82.4% YoY); Operating Income was **$40.7B**; OpMargin was **34.0%**. | Three months ended Jun 30, 2026 | **VERIFIED** |
| **15** | GOOG | Q2 CapEx $44.9B; FCF -$5.86B; FY26 CapEx $195–$205B | Alphabet Form 10-Q, Statement of Cash Flows & Call Remarks | CapEx was **$44,900 million**; CFO was **$39,040 million**; FCF was **-$5,860 million**. Full-year CapEx guidance was raised to **$195–$205 billion**. | Periods ended Jun 30, 2026 | **VERIFIED** |
| **16** | GOOG | Cash $55.91B; Marketables $186.56B; Total $242.47B | Alphabet Form 10-Q, Condensed Consolidated Balance Sheet | Cash & equiv: **$55,911 million**; Marketable securities: **$186,563 million**; Total: **$242,474 million** ($242.47B). | As of Jun 30, 2026 | **VERIFIED** |
| **17** | GOOG | Total Debt Obligations (Note 6 Reconciliation) | Alphabet Form 10-Q, Note 6 (Debt) & Balance Sheet | Current long-term notes: **$1,999M**; Long-term debt: **$98,165M**; Credit facilities: **$1.3B**. Total debt = **$101.46B**. Net cash = **+$141.01B**. | As of Jun 30, 2026 | **VERIFIED (Reconciled)** |
| **18** | GOOG | Common Shares Outstanding 12,230M | Alphabet Form 10-Q, Condensed Consolidated Balance Sheet | Class A: **5,868M**; Class B: **835M**; Class C: **5,527M**. Sum = **12,230 million** shares. | As of Jun 30, 2026 | **VERIFIED** |
| **19** | GOOG | Financing: Equity $49.6B; Debt $20.3B | Alphabet Form 10-Q, Statement of Cash Flows (Financing) | Proceeds from issuance of capital stock and preferred: **$49.6B**; proceeds from issuance of debt: **$20.3B**. | Three months ended Jun 30, 2026 | **VERIFIED** |
| **20** | GOOG | $98.0B Other Income with $99.0B Net Equity Gains | Alphabet Form 10-Q, Note 3 & Statement of Income | Other Income was **$98.0 billion**, which included **$99.0 billion** in net gains on equity securities under ASC 321. | Three months ended Jun 30, 2026 | **VERIFIED (Note 3)** |
| **21** | GOOG | "$6.26" EPS Boost from Unrealized Gains | Author-Supplied Claim / Form 10-Q Inspection | The specific value "$6.26" does **NOT** appear in the Form 10-Q text. It is an unverified derived calculation assuming statutory tax rates. | Three months ended Jun 30, 2026 | **UNVERIFIED (Derived)** |
| **22** | GOOG | App Denominator = 12.088B (not 5.527B) | Application Runtime Calculation Steps & User Report | Dividing $105.4B FCF by **12.088B shares** at 5.0% yield yields **$174.39** (matches app output $174). | Captured Baseline | **VERIFIED (App Reality)** |
| **23** | GOOG | FY26 $20.60 vs. FY27 $14.85 Consensus Basis | Secondary Consensus compilations | Accounting metadata (GAAP vs. non-GAAP operating basis) is unspecified by the provider. | Forward Estimates | **UNPROVEN / UNKNOWN** |

---

## 3. Forensic Examination of Application Share Counts

### 3.1 Alphabet (GOOG / GOOGL): Stale Year-End Shares (12.088B)
- **Forensic Verification**:
  - The application reported Free Cash Flow of **$105.4B** and an FCF Yield model price of **$174**.
  - At the application's base FCF yield assumption of 5.0%:
    $$\text{Price} = \frac{\$105.4\text{B} / \text{Shares}}{0.05} = \$174 \implies \text{Shares} = \frac{\$105.4\text{B}}{0.05 \times \$174.39} = \mathbf{12,088\text{ million shares}} \quad (\mathbf{12.088B})$$
  - 12,088M was Alphabet's year-end FY2025 share count.
  - The captured application baseline used this stale FY2025 share count (12.088B), **not** a 5.527B Class C denominator.
  - In Q2 2026, the official share count expanded to **12.230B shares** (Class A 5,868M + Class B 835M + Class C 5,527M) following $49.6B in equity/preferred financings.

### 3.2 Meta Platforms (META): Inconsistency Between Raw Field and Market Cap
- **Forensic Verification**:
  - Raw snapshot field `diluted_shares`: **2,205,128,509** (~2.205B, Class A only).
  - Implied share count from Market Cap ($1,656.9B / $650.41): **2,547,506,225** (~2.548B, basic common stock).
- **Valuation Impact**:
  - The **Forward P/E Model** was based on Forward EPS ($31.43 × 20x = **$628.60**). Because EPS is already a per-share metric, the P/E model was unaffected by the share denominator.
  - The **16.4% denominator inflation** ($2.566B / $2.205B = 1.1637$) applied strictly to the three aggregate models dividing Equity Value by shares: EV/EBITDA ($1,333.01), FCF Yield ($891.84), and DCF ($662.58).
  - Replacing the denominator reduces the composite base valuation from **$845.49** to **$751.49** conditionally (an **$94.00 or -11.1% drop**, **not** 16.4%).

---

## 4. MarketScreener Cross-Listings & Identifier Analysis

The external critique cited secondary MarketScreener URLs:
1. `AMDCL` (Internal ID `172175600`): Santiago Stock Exchange (Chile), traded locally in **CLP**.
2. `META *` (Internal ID `11638517`): Bolsa Mexicana de Valores (BMV SIC) in Mexico, traded locally in **MXN**.
3. `ALPHABET` (Internal ID `24203385`): Consolidated profile.

### Qualified Assessment:
- The URL indicates navigation to an international cross-listing line.
- However, the URL alone does **not** prove that financial statements displayed on the page were converted to local currency. MarketScreener frequently retains the primary SEC reporting currency (USD) on its financial tabs unless a currency toggle is activated.
- Automated data pipelines should validate exchange MIC codes (e.g. `XNAS`, `XNYS`) and verify reporting currency (`USD`) to avoid identifier ambiguity.

---

## 5. Target Valuation Recomputation & Arithmetic Audit

### 5.1 AMD Target Recomputation (60% P/E / 40% EV/EBITDA)
- **Inputs**: EPS **$15.45**; EBITDA **$29.12B**; Net Cash **+$9.88B** ($13.11B − $3.23B); Basic Shares **1.632B**.
- **Recomputation**:
  - P/E Component: Low $463.50 (30x); Base $525.30 (34x); High $587.10 (38x).
  - EV/EBITDA Component:
    - Low (24x): $(24 \times \$29.12\text{B} + \$9.88\text{B}) / 1.632\text{B} = \mathbf{\$434.29}$
    - Base (28x): $(28 \times \$29.12\text{B} + \$9.88\text{B}) / 1.632\text{B} = \mathbf{\$505.66}$
    - High (32x): $(32 \times \$29.12\text{B} + \$9.88\text{B}) / 1.632\text{B} = \mathbf{\$577.03}$
  - Composite (60/40):
    - Low: $0.60 \times 463.50 + 0.40 \times 434.29 = \mathbf{\$451.82}$ (Claimed: **$451**, Delta: **+$0.82**)
    - Base: $0.60 \times 525.30 + 0.40 \times 505.66 = \mathbf{\$517.44}$ (Claimed: **$516**, Delta: **+$1.44**; or $515.02 if net cash omitted from EV bridge)
    - High: $0.60 \times 587.10 + 0.40 \times 577.03 = \mathbf{\$583.07}$ (Claimed: **$582**, Delta: **+$1.07**)
- **Circular Logic Warning**: Justifying the base 28x multiple because the market trades at 27x is circular reasoning. Intrinsic valuation must be independent of current market multiples.

### 5.2 Meta Platforms Target Recomputation (70% P/E / 30% EV/EBITDA)
- **Inferred Inputs to Approximate Author**: Inferred EPS **$33.90**; Inferred Net Cash **+$6.16B**; Diluted Shares **2.566B**; EBITDA **$180.8B**.
  - *Disclosure*: $33.90 EPS and $6.16B net cash are **inferred assumptions** reverse-engineered to reproduce the author's numbers, not verified regulatory disclosures.
- **Recomputation**:
  - P/E Component: Low $610.20 (18x); Base $678.00 (20x); High $745.80 (22x).
  - EV/EBITDA Component:
    - Low (9x): $(9 \times \$180.8\text{B} + \$6.16\text{B}) / 2.566\text{B} = \mathbf{\$636.54}$
    - Base (10x): $(10 \times \$180.8\text{B} + \$6.16\text{B}) / 2.566\text{B} = \mathbf{\$707.00}$
    - High (11x): $(11 \times \$180.8\text{B} + \$6.16\text{B}) / 2.566\text{B} = \mathbf{\$777.46}$
  - Composite (70/30):
    - Low: $0.70 \times 610.20 + 0.30 \times 636.54 = \mathbf{\$618.10}$ (Claimed: **$618**, Delta: **+$0.10**)
    - Base: $0.70 \times 678.00 + 0.30 \times 707.00 = \mathbf{\$686.70}$ (Claimed: **$687**, Delta: **-$0.30**)
    - High: $0.70 \times 745.80 + 0.30 \times 777.46 = \mathbf{\$755.30}$ (Claimed: **$755**, Delta: **+$0.30**)

### 5.3 Alphabet Target Recomputation & Discrepancies (60% P/E / 40% EV/EBITDA)
- **Inputs**: EPS **$14.85**; EBITDA **$297.2B**; Simplified Net Cash **+$144.30B** ($242.47B cash/marketables − $98.17B LT debt); Total Shares **12.230B**.
- **Exact 2-Decimal Recomputation**:
  - P/E Component: Low $297.00 (20x); Base $341.55 (23x); High $371.25 (25x).
  - EV/EBITDA Component:
    - Low (11x): $(11 \times \$297.2\text{B} + \$144.30\text{B}) / 12.230\text{B} = \mathbf{\$279.11}$
    - Base (13x): $(13 \times \$297.2\text{B} + \$144.30\text{B}) / 12.230\text{B} = \mathbf{\$327.71}$
    - High (14x): $(14 \times \$297.2\text{B} + \$144.30\text{B}) / 12.230\text{B} = \mathbf{\$352.01}$
  - Composite (60/40):
    - Low: $0.60 \times 297.00 + 0.40 \times 279.11 = \mathbf{\$289.84}$ (Claimed: **$289.00**, Delta: **+$0.84**)
    - Base: $0.60 \times 341.55 + 0.40 \times 327.71 = \mathbf{\$336.01}$ (Claimed: **$335.00**, Delta: **+$1.01**)
    - High: $0.60 \times 371.25 + 0.40 \times 352.01 = \mathbf{\$363.55}$ (Claimed: **$363.00**, Delta: **+$0.55**)

#### Debt Incompleteness & Preferred Claims:
- **Debt Incompleteness**: Net cash of $144.30B considers only Long-Term Debt ($98.17B). Reconciling with current notes ($1,999M) and credit facilities ($1.3B) yields Total Debt of **$101.46B**, reducing net cash to **$141.01B** ($3.29B lower). This reduces the EV-derived price by $0.27/share and composite by $0.11/share.
- **Preferred Equity Claims**: The $49.6B equity capital raise included mandatory convertible preferred stock. Economic common valuation must account for preferred liquidation seniority or conversion dilution, rather than attributing all cash to common equity.

---

## 6. Methodological Evaluation: Concise Conditional Principles

1. **Share Count Roles**:
   - Time-weighted diluted shares is appropriate for per-share flow metrics (EPS, CFO/share).
   - Latest point-in-time common shares plus projected net dilution is appropriate for converting aggregate equity value into price per share.
2. **P/E vs. EV Bridges**:
   - P/E applies to Net Income. If Net Income already reflects recurring net interest income from cash holdings, adding balance sheet cash to the P/E value is a double-count. However, if earnings are adjusted to clean operating earnings, non-operating assets must be bridged.
   - EV/EBITDA applies to Operating Income before D&A (EBITDA is an operating metric, not operating cash flow / CFO). Enterprise Value must be explicitly bridged to Equity Value via total net debt.
3. **WACC & Discount Rates**:
   - WACC must be denominated in the nominal currency of projected cash flows (USD).
   - An 8.0% WACC is tight against a 4.85% Treasury yield for high-beta equity, but its plausibility depends conditionally on debt weighting, credit spread, and asset beta.
4. **DCF Terminal Value (TV) Share**:
   - High TV share (70%–85%) is common in 5-year models of high-reinvestment firms with depressed near-term cash flows. Extending the forecast horizon to 10–15 years reduces TV sensitivity more rigorously than arbitrarily fading model weights.
5. **Stock-Based Compensation (SBC)**:
   - Analysts may adjust cash flow for SBC cash equivalence with fixed shares, or leave cash flow unadjusted and project share count dilution. The key principle is avoiding double-counting (subtracting SBC from cash flow while also diluting the share count).
6. **Projection Horizon**:
   - Valuation should rely on rolling Next Twelve Months (NTM) consensus or the next fiscal year (FY+1), avoiding arbitrary seasonal roll-forward mandates.

---

## 7. Audit Limitations & Uncertainty Disclosures

1. **Third-Party Consensus Metadata**: Forward estimates (FY27 revenue, EBITDA, EPS) are secondary compilations. Without vendor metadata defining analyst adjustments, their exact accounting basis remains unverified.
2. **Access Constraints**: Certain media and issuer URLs returned HTTP 401/403 to automated crawlers; all underlying facts were independently verified against official SEC EDGAR filings.
3. **Non-Endorsement**: This document audits financial assertions and arithmetic. It does not provide investment advice or certify target prices.
