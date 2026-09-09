# Primary Financial Evidence: META (Meta Platforms, Inc.)

**As-of Date**: September 9–10, 2026  
**Primary Source**: Meta Platforms Q2 2026 Form 10-Q & Earnings Release (period ended June 30, 2026).

---

## 1. Official Q2 2026 Free Cash Flow Reconciliation

From the Condensed Consolidated Statements of Cash Flows and Non-GAAP Free Cash Flow Reconciliation:
- **Net cash provided by operating activities (CFO)**: **$31,862 million** ($31.86B).
- **Purchases of property and equipment (PPE)**: **$30,116 million**.
- **Principal payments on finance leases**: **$962 million**.
- **Total Capital Expenditures (including lease principal)**:
  $$\text{CapEx} = \$30,116\text{M} + \$962\text{M} = \mathbf{\$31,078\text{ million}} \quad (\approx \mathbf{\$31.08B})$$
- **Free Cash Flow (Q2 2026)**:
  $$\text{FCF} = \$31,862\text{M} - \$30,116\text{M} - \$962\text{M} = \mathbf{\$784\text{ million}} \quad (\mathbf{\$0.784B})$$
- **First Half (H1) 2026 Free Cash Flow**: **$13,170 million** ($13.17B).
- **Full-Year 2026 CapEx Guidance**: **$130 billion to $145 billion** (updated from prior $125B–$145B).

---

## 2. Share Count: Weighted-Average Diluted vs. Point-in-Time

- **Diluted Weighted-Average Common Shares** (Three Months Ended June 30, 2026): **2,566 million** shares.
- **Point-in-Time Common Shares Outstanding** (Form 10-Q Cover Page as of mid-2026):
  - Class A common stock: **2,205 million** shares (~2,205,128,509 shares).
  - Class B common stock: **343 million** shares.
  - Total basic common shares: **2,548 million** shares.

---

## 3. Impact of Share Denominator Correction on Valuation Models

### The Mechanics of the Composite Drop from $845.49 to $751.49:
- The application's captured snapshot contained:
  - Raw `diluted_shares` field: **2,205,128,509** (Class A only).
  - Model weights: Forward P/E 25%, EV/EBITDA 20%, FCF Yield 25%, DCF 30%.
- **Critical Model Distinction**:
  - The **Forward P/E Model** applies the P/E multiple directly to Forward EPS ($31.43 × 20x = **$628.60**). Because EPS is already a per-share metric, the P/E model does **NOT** divide by the snapshot share count and is completely unaffected by replacing the share denominator.
  - The **16.4% denominator inflation** ($2.566B / $2.205B = 1.1637$) applies **exclusively** to the three aggregate models that divide Equity Value by shares: EV/EBITDA ($1,333.01), FCF Yield ($891.84), and DCF ($662.58).
- **Composite Recomputation**:
  - Replacing the denominator in the three share-divided models reduces the overall composite base valuation from **$845.49** to **$751.49** conditionally.
  - This is an **$94.00 drop (-11.1%)**, **NOT** a 16.4% reduction. Claiming that the entire composite was inflated by 16.4% was a mathematical error.

---

## 4. Recomputation of Revised Targets & Inferred Assumptions

The external critique reported target valuations of **$618 / $687 / $755** based on 70% P/E and 30% EV/EBITDA.

### Inferred Inputs Required to Reproduce Author's Numbers:
- **Inferred Normalized EPS**: **$33.90** (generates P/E values: 18 × $33.90 = $610.20; 20 × $33.90 = $678.00; 22 × $33.90 = $745.80).
- **Inferred Net Cash**: **+$6.16B** (generates Base EV/EBITDA: (10 × $180.8B + $6.16B) / 2.566B = $707.00).
- *Disclosure*: These two inputs are **inferred assumptions** reverse-engineered to match the critique author's math, **NOT** verified primary regulatory figures.

### Exact 2-Decimal Recomputation:
| Scenario | Component P/E | Component EV/EBITDA | Recomputed Composite (2 dp) | Claimed Target | Delta ($) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Low** | $610.20 (18x) | $636.54 (9x) | **$618.10** | **$618.00** | **+$0.10** |
| **Base** | $678.00 (20x) | $707.00 (10x) | **$686.70** | **$687.00** | **-$0.30** |
| **High** | $745.80 (22x) | $777.46 (11x) | **$755.30** | **$755.00** | **+$0.30** |

*Conclusion*: Discarding FCF Yield and DCF in favor of a 70/30 P/E & EV blend is a discretionary choice. The targets are conditional approximations.
