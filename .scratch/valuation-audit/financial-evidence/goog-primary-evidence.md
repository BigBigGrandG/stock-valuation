# Primary Financial Evidence: GOOG / GOOGL (Alphabet Inc.)

**As-of Date**: September 9–10, 2026  
**Primary Source**: Alphabet Inc. Form 10-Q for Period Ended June 30, 2026 (SEC EDGAR Accession No. `0001652044-26-000071`, file `goog-20260630.htm`).

---

## 1. Official Balance Sheet Breakdown (June 30, 2026)

From the Condensed Consolidated Balance Sheets:
- **Cash and cash equivalents**: **$55,911 million** ($55.91B).
- **Marketable securities**: **$186,563 million** ($186.56B).
- **Total Cash, Cash Equivalents and Marketable Securities**: **$242,474 million** ($242.47B).
- *Correction Note*: Prior mention of $87,210M / $155,264M components was erroneous. The official primary components are **$55,911M** and **$186,563M**.

---

## 2. Debt Obligations (Note 6 Reconciliation)

From Note 6 (Debt) and Condensed Consolidated Balance Sheets:
- **Current portion of long-term notes**: **$1,999 million** (~$2.0B).
- **Long-term debt (notes)**: **$98,165 million** (~$98.17B).
- **Credit facilities**: **$1.3 billion** outstanding.
- **Total Debt Obligations**:
  $$\text{Total Debt} = \$1,999\text{M} + \$98,165\text{M} + \$1,300\text{M} = \mathbf{\$101,464\text{ million}} \quad (\approx \mathbf{\$101.46B})$$
- *Reconciliation & Debt Incompleteness*:
  - The external critique calculated net cash using **only** Long-Term Debt ($98.17B), yielding +$144.30B.
  - When reconciled with current long-term notes ($1,999M) and credit facilities ($1.3B), total debt is **$101.46B**, reducing net cash to:
    $$\$242,474\text{M} - \$101,464\text{M} = \mathbf{+\$141,010\text{ million}} \quad (\approx \mathbf{+\$141.01B})$$
  - Net cash is **$3.29B lower** than the author's assumption, which lowers the EV-derived price by $0.27/share.

---

## 3. Other Income & Investment Gains (Note 3)

From the Condensed Consolidated Statements of Income and Note 3 (Investments):
- **Total Other Income (Expense), Net**: **$98.0 billion** ($98,000M).
- **Net Gains on Equity Securities**: **$99.0 billion** ($99,000M), recognized under ASC 321 (offset by net charges/losses).
- *Correction on Unrealized Gain & EPS Impact*:
  - The $98.0B total Other Income included **$99.0B** in net equity gains (not $98B unrealized gains alone).
  - The specific figure **"$6.26"** does **NOT** appear in the Form 10-Q text. It is an unverified derived calculation by the critique author ($99B × (1 − ~21% tax) / 12.23B shares). It must be designated as an **UNVERIFIED DERIVED ESTIMATE**, not a verbatim 10-Q disclosure.

---

## 4. Common Share Capital & Preferred Stock Structure

From the Condensed Consolidated Balance Sheets (June 30, 2026):
- **Class A Common Stock ($0.001 par value)**: **5,868 million** shares outstanding.
- **Class B Common Stock ($0.001 par value)**: **835 million** shares outstanding.
- **Class C Capital Stock ($0.001 par value)**: **5,527 million** shares outstanding.
- **Total Common & Capital Shares Outstanding**:
  $$5,868\text{M} + 835\text{M} + 5,527\text{M} = \mathbf{12,230\text{ million shares}} \quad (\mathbf{12.230B})$$

### Preferred Equity Capital Raise:
- During Q2 2026, Alphabet raised **$49.6 billion** in equity financing (including mandatory convertible preferred stock) and **$20.3 billion** in senior notes.
- *Methodological Warning*: Because separate preferred equity claims exist, an economic common equity bridge cannot blindly add all cash from preferred financing to common equity without accounting for preferred liquidation preferences, dividend claims, or conversion dilution.

---

## 5. Application Baseline Denominator Proof (12.088B)

- In the user's captured baseline report:
  - Free Cash Flow: **$105.4B**
  - FCF Yield Model Price (5.0% yield): **$174**
  - DCF Model Price: **$116.57**
- **Forensic Verification**:
  $$\text{Implied Shares} = \frac{\$105.4\text{B}}{0.05 \times \$174.39} = \mathbf{12,088\text{ million shares}} \quad (\mathbf{12.088B})$$
  - 12,088M was Alphabet's year-end FY2025 share count.
  - The application run used this stale FY2025 share count (12.088B), **NOT** a 5.527B Class C denominator.
  - Following the Q2 2026 equity capital raises, the official share count increased to **12.230B shares**.

---

## 6. Exact Recomputation Differences vs. Claimed Targets

Using author-supplied inputs (EPS $14.85 @ 20/23/25x; EBITDA $297.2B @ 11/13/14x; simplified net cash +$144.30B; shares 12.230B; 60% P/E / 40% EV):

| Metric | Component P/E | Component EV/EBITDA | Recomputed Composite (2 dp) | Claimed Target | Difference ($) | Difference (%) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Low** | $297.00 (20x) | $279.11 (11x) | **$289.84** | **$289.00** | **+$0.84** | +0.29% |
| **Base** | $341.55 (23x) | $327.71 (13x) | **$336.01** | **$335.00** | **+$1.01** | +0.30% |
| **High** | $371.25 (25x) | $352.01 (14x) | **$363.55** | **$363.00** | **+$0.55** | +0.15% |

*Conclusion*: The external critique's targets reflect approximate intermediate rounding and incomplete debt reconciliation, not exact mathematical certainty.
