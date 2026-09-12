# US Stock Valuation Engine

This repository contains a deterministic, provenance-rich stock valuation engine
for US listed equities. It exposes four independent valuation models through
FastAPI and a Next.js client: Forward P/E, EV/EBITDA, FCF yield using FCFE, and
a five-year DCF using FCFF. Each model remains independently available or
unavailable with an explicit reason; no cross-model composite is calculated.

The default configuration ingests live US equity market data via `yfinance`. An
explicit offline demo fixture (`AVGO`) is preserved for deterministic, network-free
testing and offline demonstrations (`DATA_PROVIDER="demo"` or `?provider=demo`).

## Architecture

`backend/app/providers` defines the vendor-neutral seven-method
`FinancialDataProvider` boundary:
- `get_quote(ticker)`: Real-time price, change, volume, diluted shares, market cap.
- `get_company_profile(ticker)`: Company name, sector, industry, country, quote type.
- `get_balance_sheet(ticker)`: Total cash, total debt, net debt, balance sheet items.
- `get_cash_flow(ticker)`: Operating cash flow, capex, interest, taxes, FCFE, FCFF.
- `get_income_statement(ticker)`: Revenue, operating income, EBITDA, net income, EPS.
- `get_forward_estimates(ticker)`: Forward EPS, forward revenue, forward EBITDA, forward FCF.
- `get_historical_multiples(ticker)`: Forward P/E, EV/EBITDA 5-year median history.

### Live Market Data Provider (`YFinanceProvider`)
- Keyless live US equity data ingestion using pinned `yfinance==1.7.0`.
- **Bounded Concurrency**: Thread-safe execution using `threading.BoundedSemaphore(5)` to prevent provider rate limits.
- **Request Bundle Cache**: 30-second in-memory bundle cache ensuring a single unified network fetch across all seven provider methods.
- **Category TTL Caching**: Layered caching in `FinancialDataService`:
  - Quotes: 120 seconds TTL.
  - Financial Statements (Balance Sheet, Cash Flow, Income Statement): 24 hours TTL.
  - Forward Estimates & Historical Multiples: 12 hours TTL.
  - Company Profiles: 7 days TTL.
- **Non-blocking Async Endpoints**: All synchronous provider calls and engine computations run via `await asyncio.to_thread(...)` so the FastAPI event loop is never blocked.
- **Ticker Normalization**: Handles US share classes by normalizing dot notation to Yahoo Finance hyphens (e.g., `BRK.B` -> `BRK-B`, `BF.B` -> `BF-B`), trimming whitespace, and uppercasing.

### Offline Demo Fixture (`AvgoFixtureProvider`)
- Fixed AVGO fixture dated 2025-01-15 for 100% offline, deterministic testing.
- Activated by setting `DATA_PROVIDER=demo` in the environment or appending query parameter `?provider=demo`.

All money is in actual currency units (USD). Rates are `Decimal` values (`0.05`
means 5%). Decimal values are serialized as JSON strings to preserve exact
rounding. Every model response has legacy flat `inputs`/`assumptions` aliases
plus stable `input_metrics` and `assumption_metrics` dictionaries. Each
metric contains `value`, `unit`, `period`, `source`, `source_type`, `as_of`,
`confidence`, `is_estimated`, and optional notes.

## Formulas and conventions

Forward P/E:

```text
price = forward EPS × target P/E
```

Historical forward-P/E median is preferred when available (low = 0.9×,
base = median, high = 1.1×). Otherwise the configured fallback or a request
override is used.

EV/EBITDA:

```text
market cap = current price × diluted shares
net debt = total debt - cash
EV = forward EBITDA × target multiple
equity value = EV - net debt
price/share = equity value / diluted shares
```

FCF yield uses FCFE only:

```text
FCFE = Operating Cash Flow - Capital Expenditures + Net Debt Issued
equity value = forward FCFE / yield
price/share = equity value / diluted shares
```

The low valuation uses the highest yield (default 5.5%), and the high
valuation uses the lowest yield (default 4.5%). FCFE is never discounted at
WACC.

DCF uses FCFF only:

```text
FCFF = Operating Cash Flow + Interest Expense × (1 - Tax Rate) - Capital Expenditures
PV_t = FCFF_t / (1 + WACC)^t
TV = FCFF_5 × (1 + terminal_growth) / (WACC - terminal_growth)
PVTV = TV / (1 + WACC)^5
EV = sum(PV_1..PV_5) + PVTV
equity value = EV - debt + cash
price/share = equity value / diluted shares
```

Forward FCFF1 and FCFF2 are used as explicit FY estimates when present. If a
TTM FCFF value is the only starting point, Year 1 is derived and labelled as
a new forecast period; TTM is never relabelled as forecast. Years 3-5 use
capped deterministic FCFF growth. Every DCF scenario includes five
`projection_metrics`, PV years, formulas, and calculation steps. WACC is
calculated with CAPM and equity/debt weighting when all inputs exist;
otherwise the response says `wacc_source=fallback` and exposes the fallback
metric. A request override says `user_override`. Every scenario validates
`WACC > terminal_growth`, and terminal growth is capped at 5%.

The four models are deliberately not synthesized: each exposes its own
low/base/high price estimates, assumptions, provenance, and calculation
steps. When a model lacks inputs or is not applicable, only that model is
marked unavailable; other model outputs are not reweighted or altered.

## Company Scope & Financial Applicability

- **Profitable Operating Equities** (e.g. `NVDA`, `AAPL`, `MSFT`, `AVGO`, `KO`):
  All four valuation models can run independently when their inputs are complete.
- **US-Listed Foreign ADRs** (e.g. `TSM` on NYSE `NYQ`):
  Supported for Forward P/E based on per-ADS USD quotes and analyst forward EPS.
  Financial statement models (EV/EBITDA, FCF yield, DCF) are cleanly isolated
  when statements are denominated in foreign currency (e.g. TWD) without fabricating
  unproven foreign exchange conversions.
- **Financial Institutions & Banks** (e.g. `JPM`, `BAC`, `C`):
  Banks maintain deposit liabilities that serve as core operations, rendering
  standard EV/EBITDA and FCFF DCF economically meaningless. Rather than returning a
  blanket rejection, EV/EBITDA and DCF report `available=False` with explicit reasons
  (`EV/EBITDA is not applicable to banks and financial institutions...`), while
  Forward P/E remains active. There is no aggregate result to reweight.
- **Loss-Makers & Early-Stage Companies** (e.g. `RIVN`, `SNAP`):
  Equities are ingested normally. Models requiring positive earnings or cash flows
  report honest model-specific `unavailable_reason` flags (e.g. negative forward EBITDA)
  without crashing or returning generic 422 rejections.
- **Unsupported Asset Classes**:
  Non-equities (ETFs like `SPY`, crypto assets like `BTC-USD`, mutual funds, SPACs)
  and non-US securities are rejected with typed `UnsupportedCompanyError` (HTTP 422).

## Setup

Python 3.12 or newer is required. The reproducible root environment is
`.venv`; dependencies are listed in `backend/requirements.txt` and pinned in
`backend/requirements.lock` (including `yfinance==1.7.0`).

```powershell
# from repository root
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.lock
```

Environment settings can be configured in `backend/.env` (see `backend/.env.example`):
- `DATA_PROVIDER=live` (default: live market data via `yfinance`)
- `DATA_PROVIDER=demo` (offline AVGO fixture)

## Run and verify

```powershell
# tests (250 tests, run offline with isolated demo provider)
.\.venv\Scripts\python.exe -m pytest backend/tests/ -v

# live multi-ticker and special ticker verification
.\.venv\Scripts\python.exe .scratch/live-tickers/verify_live.py
.\.venv\Scripts\python.exe .scratch/live-tickers/verify_special_tickers.py

# backend development server (defaults to live provider, port 8002)
Set-Location backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8002
```

Run the frontend from a second terminal at `http://localhost:3000`:

```powershell
Set-Location frontend
npm ci
npm run dev
```

Before delivery, run its checks from `frontend/`:

```powershell
npm run typecheck
npm run lint
npm run build
```

Full-stack integration verification suites:

```powershell
# API streaming deadline, cancellation and reset contract test (6 checks)
node --experimental-strip-types .scratch/live-tickers/test_api_deep.mjs

# End-to-end browser acceptance test (14 verification checks)
python .scratch/live-tickers/browser_acceptance.py
```

The frontend targets `http://127.0.0.1:8002` by default.

## API

Interactive OpenAPI documentation is available at `GET /docs` and health check at `GET /health`.
The financial snapshot endpoint is `GET /api/v1/company/{ticker}/snapshot`.
Valuation endpoints are:

```text
GET  /api/v1/valuation/{ticker}
POST /api/v1/valuation/{ticker}
GET  /api/v1/valuation/{ticker}/reset
```

Any arbitrary US listed equity (e.g. `NVDA`, `AAPL`, `MSFT`, `KO`, `JPM`, `AVGO`)
can be queried against the default live provider. Append `?provider=demo` to any
endpoint to explicitly query against the isolated AVGO demo fixture.

The POST body is sparse and nested; unknown fields are rejected:

```json
{
  "forward_pe": {"base": 25.0},
  "ev_ebitda": {"base": 20.0},
  "fcf_yield": {"base": 0.045},
  "dcf": {"wacc": 0.09, "terminal_growth": 0.03}
}
```

Omitting low/high derives relative scenario bounds. For P/E and EV/EBITDA,
low/high are 0.9x/1.1x of base. For FCF yield the order is inverse:
low/high are 1.1x/0.9x of base. JSON strings, booleans, arrays, non-finite
values, unknown fields, out-of-range assumptions and any effective DCF
scenario with `WACC <= terminal_growth` return HTTP 422.

### Error Taxonomy
Typical errors are intentionally distinct and typed:
- **404 Not Found (`TickerNotFoundError`)**: Ticker is syntactically valid but unknown or unlisted (e.g. `ZZZZZ`).
- **422 Unprocessable Entity (`InvalidTickerError`)**: Malformed ticker syntax (e.g. spaces, special characters).
- **422 Unprocessable Entity (`UnsupportedCompanyError`)**: Asset class is unsupported (e.g. ETF `SPY`, crypto, non-US security).
- **422 Unprocessable Entity (`FinancialDataValidationError`)**: Critical financial statements missing or invalid.
- **429 Too Many Requests (`ProviderRateLimitError`)**: Upstream data provider rate limit encountered.
- **503 Service Unavailable (`ProviderUnavailableError`)**: Upstream data provider is unreachable or down.

A failing or non-applicable valuation engine (e.g. negative EBITDA or bank balance sheet)
is retained as an unavailable model (`available: false` with explanatory `unavailable_reason`)
while other models continue independently.

## AVGO Demo Fixture

The demo fixture (`AvgoFixtureProvider`) supports AVGO only and never clones its
values to another ticker. Its fixed date is 2025-01-15. Key values are price 343.83,
diluted shares 4,940,000,000, cash $24.0bn, debt $59.4bn, forward EPS 19.21, forward
EBITDA $118.3bn and forward FCFE $89.6bn. FCFE and FCFF are separate synthetic
metrics with explicit notes. All fixture-derived values are marked demo and the
aggregate quality is always LOW. The static date intentionally produces a
demo/staleness warning; it is not silently refreshed.

To activate the fixture, either set environment variable `DATA_PROVIDER=demo` or pass
query parameter `?provider=demo`.

## Estimate, Fallback and Provenance Taxonomy

- `actual`: Reported financial statement or real-time market quote from live provider.
- `analyst_estimate`: Provider consensus forward estimates (EPS, EBITDA, Revenue, FCF).
- `derived`: Lineage from mathematical formula or deterministic projection (e.g. FCFE, FCFF).
- `configured_fallback`: Documented system default (e.g. default WACC when CAPM inputs are missing).
- `user_override`: Explicit request-scoped override from POST payload.
- `fixture`: Synthetic educational input from offline demo fixture.

## Markdown Report Export
- Discoverable "⭳ 导出 Markdown" action in the valuation hero card header.
- Downloads standalone, publication-grade UTF-8 `.md` file named `{ticker}_valuation_{timestamp}.md`.
- Operates 100% in-memory from client-side valuation state: **zero extra network requests** to backend or upstream data providers.
- Full inventory coverage: company identity, currency, quotes, statements as-of, LIVE/DEMO modes, data quality, data warnings, parameter overrides comparison, four independent model summaries and exact unavailable isolation reasons, complete DCF 5-year cash flow projections and discounting bridges across all 3 scenarios, calculation steps, and educational disclaimers.
- Table safety: automatic escaping of pipes `|` and newlines to preserve Markdown table integrity.

## Limitations & Disclaimers

- Market data is ingested via `yfinance` without SLA guarantees. Upstream schema changes or IP rate limits can affect availability.
- All valuations are educational and analytical demonstrations, not investment advice or trading recommendations.
- Users must verify data, model assumptions, tax/accounting treatments, and valuation model suitability independently.
