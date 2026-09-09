# Raw-Source-to-Normalized Reconciliation for NVDA: NVIDIA Corporation

- **Current Market Price**: `$223.85` (Source: `Yahoo Finance live quote (NVDA)`, Timestamp: `2026-09-09T16:27:41`)
- **Diluted Shares**: `24147000000` shares (Source: `Yahoo Finance info.sharesOutstanding (NVDA)`, Period: `latest`, Notes: `Common shares outstanding approximation; not weighted-average diluted shares`)

## 1. Balance Sheet Reconciliation
- **Latest Balance Sheet Statement Column Date**: `2026-01-31 00:00:00`
- **Raw Balance Sheet Statement Rows**:
```json
{
  "Cash Cash Equivalents And Short Term Investments": "62556000000.0",
  "Cash And Cash Equivalents": "10605000000.0",
  "Other Short Term Investments": "51951000000.0"
}
{
  "Total Debt": "11040000000.0",
  "Long Term Debt": "7469000000.0",
  "Current Debt": "999000000.0"
}
```
- **Normalized Cash**: `62556000000.0` (Source: `Yahoo Finance balance sheet (NVDA)`, Period: `FY2026`, Units: `USD`)
- **Normalized Total Debt**: `11040000000.0` (Source: `Yahoo Finance balance sheet (NVDA)`, Period: `FY2026`, Units: `USD`)
- **Normalized Net Debt**: `-51516000000.0` (Formula: `total_debt - cash` = 11040000000.0 - 62556000000.0 = -51516000000.0)

## 2. Cash Flow Reconciliation & FCFE / FCFF Formulas
- **Latest Cash Flow Column Date**: `2026-01-31 00:00:00`
- **Raw Cash Flow Statement Rows**:
```json
{
  "Operating Cash Flow": "102718000000.0",
  "Cash Flow From Continuing Operating Activities": "102718000000.0",
  "Capital Expenditure": "-6042000000.0",
  "Purchase Of PPE": "-6042000000.0",
  "Net Issuance Payments Of Debt": "0.0",
  "Net Long Term Debt Issuance": "0.0",
  "Issuance Of Debt": "nan",
  "Repayment Of Debt": "0.0"
}
```
- **Matching Income Statement (2026-01-31)**: Interest Expense = `259000000.0`, Tax Rate = `0.15117`
- **Forward FCFE (FCF Yield Engine)**: `135346400000.00` (Period: `0y`, Notes: `Derived forward FCFE for FY2027E (0y) from base FY2026 annual FCFE (96676000000.0) as of 2026-01-31; raw_growth=0.9512, capped_growth=0.40, formula=FY2026_FCFE × (1 + g)`)
- **Forward FCFF Year 1 (DCF Engine)**: `135654185758.00` (Label: `Forward FCFF 0y [Yahoo Finance forward estimates (NVDA)]`)
- **Forward FCFF Year 2 (DCF Engine)**: `189915860061.20` (Label: `Forward FCFF +1y [Yahoo Finance forward estimates (NVDA)]`)
- **Exact DCF Formula**: `EV = Σ FCFF_t/(1+WACC)^t + TV/(1+WACC)^5; Equity = EV − Net Debt; Price = Equity/Shares`
- **Exact FCF Yield Formula**: `Equity Value = Forward FCFE / Yield Rate; Price = Equity / Shares`

# Raw-Source-to-Normalized Reconciliation for KO: Coca-Cola Company (The)

- **Current Market Price**: `$88.11` (Source: `Yahoo Finance live quote (KO)`, Timestamp: `2026-09-09T16:27:48`)
- **Diluted Shares**: `4302549243` shares (Source: `Yahoo Finance info.sharesOutstanding (KO)`, Period: `latest`, Notes: `Common shares outstanding approximation; not weighted-average diluted shares`)

## 1. Balance Sheet Reconciliation
- **Latest Balance Sheet Statement Column Date**: `2025-12-31 00:00:00`
- **Raw Balance Sheet Statement Rows**:
```json
{
  "Cash Cash Equivalents And Short Term Investments": "15806000000.0",
  "Cash And Cash Equivalents": "10270000000.0",
  "Other Short Term Investments": "5536000000.0"
}
{
  "Total Debt": "45492000000.0",
  "Long Term Debt": "42119000000.0",
  "Current Debt": "3373000000.0"
}
```
- **Normalized Cash**: `15806000000.0` (Source: `Yahoo Finance balance sheet (KO)`, Period: `FY2025`, Units: `USD`)
- **Normalized Total Debt**: `45492000000.0` (Source: `Yahoo Finance balance sheet (KO)`, Period: `FY2025`, Units: `USD`)
- **Normalized Net Debt**: `29686000000.0` (Formula: `total_debt - cash` = 45492000000.0 - 15806000000.0 = 29686000000.0)

## 2. Cash Flow Reconciliation & FCFE / FCFF Formulas
- **Latest Cash Flow Column Date**: `2025-12-31 00:00:00`
- **Raw Cash Flow Statement Rows**:
```json
{
  "Operating Cash Flow": "7408000000.0",
  "Cash Flow From Continuing Operating Activities": "7408000000.0",
  "Capital Expenditure": "-2112000000.0",
  "Purchase Of PPE": "-2112000000.0",
  "Net Issuance Payments Of Debt": "13000000.0",
  "Net Long Term Debt Issuance": "13000000.0",
  "Issuance Of Debt": "4980000000.0",
  "Repayment Of Debt": "-4967000000.0"
}
```
- **Matching Income Statement (2025-12-31)**: Interest Expense = `1654000000.0`, Tax Rate = `0.178835`
- **Forward FCFE (FCF Yield Engine)**: `5842554500.00` (Period: `0y`, Notes: `Derived forward FCFE for FY2026E (0y) from base FY2025 annual FCFE (5309000000.0) as of 2025-12-31; raw_growth=0.1005, capped_growth=0.1005, formula=FY2025_FCFE × (1 + g)`)
- **Forward FCFF Year 1 (DCF Engine)**: `6884442469.09` (Label: `Forward FCFF 0y [Yahoo Finance forward estimates (KO)]`)
- **Forward FCFF Year 2 (DCF Engine)**: `6901653575.26` (Label: `Forward FCFF +1y [Yahoo Finance forward estimates (KO)]`)
- **Exact DCF Formula**: `EV = Σ FCFF_t/(1+WACC)^t + TV/(1+WACC)^5; Equity = EV − Net Debt; Price = Equity/Shares`
- **Exact FCF Yield Formula**: `Equity Value = Forward FCFE / Yield Rate; Price = Equity / Shares`

# Raw-Source-to-Normalized Reconciliation for TSM: Taiwan Semiconductor Manufactur

- **Current Market Price**: `$433.66` (Source: `Yahoo Finance live quote (TSM)`, Timestamp: `2026-09-09T16:27:57`)
- **Diluted Shares**: `5186474013` shares (Source: `Yahoo Finance info.sharesOutstanding (TSM)`, Period: `latest`, Notes: `Common shares outstanding approximation; not weighted-average diluted shares`)

## ADR & Currency Basis Analysis (TSM)
- **Security Type**: American Depositary Receipt (ADR) listed on NYSE (NYQ)
- **Quote Currency**: `USD` ($439.00)
- **Financial Statement Currency**: `TWD` (Taiwan New Dollars)
- **Share Basis**: 5,180,000,000 ADSs (1 ADS represents 5 underlying TWSE:2330 ordinary shares)
- **Forward EPS**: `$16.93` (0y) / `$21.93` (+1y) denominated in USD per ADS
- **Engine Isolation**: Forward P/E is **AVAILABLE** because EPS and Price share the identical USD/ADS basis. EV/EBITDA, FCF Yield, and DCF are **DISABLED** with explicit reason 'Currency mismatch: quote currency (USD) differs from statement reporting currency (TWD) without FX conversion'. Fictitious FX conversions are never invented.

## 1. Balance Sheet Reconciliation
- **Latest Balance Sheet Statement Column Date**: `2025-12-31 00:00:00`
- **Raw Balance Sheet Statement Rows**:
```json
{
  "Cash Cash Equivalents And Short Term Investments": "3128068100000.0",
  "Cash And Cash Equivalents": "2767856400000.0",
  "Cash Financial": "2761829900000.0",
  "Other Short Term Investments": "360211700000.0"
}
{
  "Total Debt": "1064582700000.0",
  "Long Term Debt": "896062000000.0",
  "Current Debt": "136925700000.0"
}
```
- **Normalized Cash**: `3128068100000.0` (Source: `Yahoo Finance balance sheet (TSM)`, Period: `FY2025`, Units: `TWD`)
- **Normalized Total Debt**: `1064582700000.0` (Source: `Yahoo Finance balance sheet (TSM)`, Period: `FY2025`, Units: `TWD`)
- **Normalized Net Debt**: `-2063485400000.0` (Formula: `total_debt - cash` = 1064582700000.0 - 3128068100000.0 = -2063485400000.0)

## 2. Cash Flow Reconciliation & FCFE / FCFF Formulas
- **Latest Cash Flow Column Date**: `2025-12-31 00:00:00`
- **Raw Cash Flow Statement Rows**:
```json
{
  "Operating Cash Flow": "2274975600000.0",
  "Cash Flow From Continuing Operating Activities": "2274975600000.0",
  "Capital Expenditure": "-1282597200000.0",
  "Purchase Of PPE": "-1272450300000.0",
  "Net Issuance Payments Of Debt": "37377000000.0",
  "Net Long Term Debt Issuance": "37041900000.0",
  "Issuance Of Debt": "97893500000.0",
  "Repayment Of Debt": "-60516500000.0"
}
```
- **Matching Income Statement (2025-12-31)**: Interest Expense = `12370400000.0`, Tax Rate = `0.16973`
- **Forward FCFE (FCF Yield Engine)**: `None` (Period: `None`, Notes: `None`)
- **Forward FCFF Year 1 (DCF Engine)**: `None` (Label: `None`)
- **Forward FCFF Year 2 (DCF Engine)**: `None` (Label: `None`)
- **Exact DCF Formula**: `EV = Σ FCFF_t/(1+WACC)^t + TV/(1+WACC)^5; Equity = EV − Net Debt; Price = Equity/Shares`
- **Exact FCF Yield Formula**: `Equity Value = Forward FCFE / Yield Rate; Price = Equity / Shares`
