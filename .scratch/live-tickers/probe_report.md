# Live Market Data Probe and Acceptance Report

**Date:** 2026-09-09  
**Source Provider:** Yahoo Finance via `yfinance` (v1.7.0, keyless public market data)  
**Storage Directory:** `.scratch/live-tickers/`  

---

## 1. Executive Summary & Live Source Verification

A keyless live market data provider (`YFinanceProvider`) was implemented and tested against real-world US equities. Official Yahoo Finance endpoints provide full real-time price quotes, shares outstanding, balance sheet statements, cash flow statements, income statements, analyst consensus estimates, and historical valuation multiples without requiring API keys.

All live queries execute via `YFinanceProvider` implementing all 7 abstract methods of `FinancialDataProvider`:
1. `get_quote`
2. `get_company_profile`
3. `get_balance_sheet`
4. `get_cash_flow`
5. `get_income_statement`
6. `get_forward_estimates`
7. `get_historical_multiples`

Public network failures are handled honestly with typed exceptions:
- **HTTP 404**: Unlisted or delisted tickers (`TickerNotFoundError`)
- **HTTP 422**: Malformed ticker syntax (`InvalidTickerError`) or unsupported security types (`UnsupportedCompanyError`)
- **HTTP 429**: Rate limiting (`ProviderRateLimitError`)
- **HTTP 503**: Upstream unavailable or network disconnect (`ProviderUnavailableError`)
- **Zero fixture fallbacks**: The live provider never silently falls back to AVGO fixture data or clones synthetic data under arbitrary tickers.

---

## 2. Live Acceptance Evidence (Real Market Tickers)

| Ticker | Company Name | Live Price | Data Quality | Forward P/E (Base) | EV/EBITDA (Base) | FCF Yield (Base) | DCF (Base) | Composite Fair Value | Classification |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **NVDA** | NVIDIA Corporation | $225.92 | MEDIUM | $266.27 | $322.68 | $112.10 | $199.10 | **$218.86** | `fairly_valued` |
| **AAPL** | Apple Inc. | $316.22 | MEDIUM | $318.75 | $365.96 | $146.16 | $141.72 | **$231.94** | `significantly_overvalued` |
| **MSFT** | Microsoft Corporation | $491.85 | MEDIUM | $492.00 | $528.87 | $195.83 | $326.79 | **$376.12** | `significantly_overvalued` |
| **AVGO** | Broadcom Inc. (Live) | $369.33 | MEDIUM | $369.34 | $333.19 | $337.81 | $244.64 | **$314.93** | `overvalued` |
| **KO** | Coca-Cola Company | $88.07 | MEDIUM | $87.29 | $91.44 | $27.16 | $13.96 | **$51.09** | `significantly_overvalued` |
| **JPM** | JP Morgan Chase & Co. | $355.58 | MEDIUM | $368.72 | *N/A (Bank)* | *N/A (Neg FCF)* | *N/A (Bank)* | **$368.72** | `slightly_undervalued` |
| **BRK.B** | Berkshire Hathaway | $505.43 | MEDIUM | $483.92 | *N/A (Financial)* | *N/A* | *N/A (Financial)* | **$483.92** | `fairly_valued` |
| **RIVN** | Rivian Automotive | $16.12 | LOW | *N/A (Neg EPS)* | *N/A (Neg EBITDA)* | *N/A (Neg FCF)* | *N/A (Neg FCFF)* | *Unavailable* | `unclassified` |

### Key Observations:
1. **Live AVGO vs Demo Fixture**:
   - Live AVGO reports current price $369.33, forward EPS $19.39, EBITDA $52.06B.
   - Demo AVGO fixture remains locked to static date 2025-01-15 (price $343.83, forward EPS $19.21, EBITDA $118.30B, LOW quality).
2. **Financial Institutions & Banks (JPM, BRK.B)**:
   - Operating debt and deposit structures make EV/EBITDA and FCFF DCF inapplicable.
   - The engines explicitly report `available=False` with informative reasons:
     - `EV/EBITDA is not applicable to banks and financial institutions due to operating debt and deposit structures`
     - `FCFF DCF is not applicable to banks and financial institutions (operating debt structure is inseparable from operating cash flow)`
   - The applicable equity model (Forward P/E) runs cleanly and renormalizes to 100% composite weight. No blanket rejection.
3. **Loss-makers (RIVN)**:
   - Snapshot is successfully fetched and normalized without rejection.
   - Models honestly indicate why valuation cannot be performed (e.g. `Forward EPS is non-positive (-2.44)`).
   - Composite reports `No complete positive three-scenario valuation models available`.
4. **Share-Class Normalization**:
   - `BRK.B`, `BRK-B`, and `brk.b` all normalize to the same live equity and return identical verified values.

---

## 3. Negative & Error Test Evidence

1. **Non-Equity Assets (SPY - ETF)**:
   - Request: `GET /api/v1/company/SPY/snapshot`
   - Response: `HTTP 422 Unprocessable Entity`
   - Body: `{"detail": {"error": "unsupported_company_type", "ticker": "SPY", "reason": "etf", "detail": "Non-equity security type: ETF"}}`
2. **Unlisted Tickers (ZZZZZ)**:
   - Request: `GET /api/v1/company/ZZZZZ/snapshot`
   - Response: `HTTP 404 Not Found`
   - Body: `{"detail": "Ticker 'ZZZZZ' not found or has no market price on Yahoo Finance"}`
3. **Malformed Syntax (INV!ALID)**:
   - Request: `GET /api/v1/company/INV!ALID/snapshot`
   - Response: `HTTP 422 Unprocessable Entity`
   - Body: `{"detail": {"error": "invalid_ticker", "detail": "Invalid ticker syntax: 'INV!ALID'"}}`

---

## 4. Cash Flow Lineage: FCFE vs FCFF

The live provider strictly computes and labels both cash flow definitions:
- **FCFE (Free Cash Flow to Equity)**:
  $$\text{FCFE} = \text{CFO} - \text{Capex} + \text{Net Borrowing}$$
  *(If Net Borrowing is not reported in cash flow statements, the approximation is explicitly labelled: `FCFE = CFO - capex (approximation: net borrowing component not reported)`)*
- **FCFF (Free Cash Flow to Firm / Unlevered)**:
  $$\text{FCFF} = \text{CFO} + \text{Interest} \times (1 - \text{Tax Rate}) - \text{Capex}$$
  *(Unlevered firm cash flow discounted at WACC in the 5-year DCF engine)*

Neither cash flow is ever silently substituted for the other.

---

## 5. Non-Blocking Concurrency & Category TTL Cache

- **Category TTL**:
  - Quote: 120s
  - Financial Statements: 86,400s (24 hours)
  - Forward Estimates: 43,200s (12 hours)
  - Valuation Multiples: 86,400s (24 hours)
- **Async Concurrency**:
  - Upstream synchronous network requests run in worker threads via `asyncio.to_thread`.
  - The FastAPI event loop is never blocked, allowing simultaneous requests across different tickers without freezing.
  - Upstream requests are bounded by `threading.BoundedSemaphore` to prevent rate-limiting floods.
