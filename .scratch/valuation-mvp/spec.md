# US stock valuation MVP

Coordinator: Codex. Implementation worker: existing Antigravity terminal via Orca orchestration only. Work in D:/workshop/stock-valuation. Preserve existing AGENTS.md and docs. No commits/pushes. Read repository instructions.

## Ordered delivery
1. Inspect repo (currently only agent documentation).
2. Implement Pydantic v2 domain models and provenance-rich FinancialMetric / CompanyFinancialSnapshot / ValuationResult.
3. Implement deterministic pure Python Decimal Forward P/E, EV/EBITDA, FCF Yield, 5-year DCF engines.
4. Add and run pytest for engines FIRST, before service/UI implementation.
5. Composite with configurable weights .25/.20/.25/.30, renormalize available models.
6. Abstract FinancialDataProvider and explicit fixed AVGO TEST/DEMO fixture.
7. Normalizer, FinancialDataService, replaceable memory TTL cache.
8. FastAPI GET /api/v1/company/{ticker}/snapshot, GET and POST /api/v1/valuation/{ticker}.
9. Start API and actually request AVGO.
10. Next.js TypeScript React UI.
11. Integration verification (including overrides/reset/errors).
12. Complete README and report evidence.

## Financial correctness
- Python 3.12+, FastAPI, Pydantic v2, httpx, pytest. No LLM math. No third-party API calls in engines, no valuation computation in UI.
- All money actual units, rates decimal, Decimal computations with explicit output rounding. Reject NaN/Infinity and invalid domains.
- Metric metadata: value, unit, period, source, source_type, as_of, confidence, is_estimated. Expose provenance for ALL key inputs and assumptions including derived values and fallback settings.
- Snapshot: ticker, company_name, currency, current_price, price_timestamp, diluted_shares, cash, total_debt, net_debt, revenue_ttm, ebitda_ttm, fcf_ttm, eps_ttm, forward_eps_1y/2y, forward_ebitda_1y/2y, forward_fcf_1y/2y, historical_forward_pe, historical_ev_ebitda, revenue_growth, eps_growth, fcf_growth. Optional unavailable metrics retained as missing, never invented silently.
- CRITICAL distinguish FCFE (equity FCF for yield model) from FCFF (unlevered FCF for enterprise DCF discounted at WACC). Explicit separate metrics/definitions; do not discount FCFE at WACC then subtract debt. Provider normalization must make definitions clear and reject incompatible data; fixture can explicitly contain separately labeled synthetic FCFE and FCFF.
- PE = forward EPS * target PE. Historical median if available, low=.9*base high=1.1*base; configurable fallback and user_override provenance.
- EV model: market cap=price*shares; net debt=debt-cash; EV=forward EBITDA*multiple; equity=EV-net debt; per share=equity/shares. Show ALL intermediates for each scenario.
- FCF yield: equity=forward FCFE/yield; per share=equity/shares. Low valuation uses HIGH yield, e.g .055/.05/.045; configurable/history/growth-adjusted fallback/user overrides.
- DCF bear/base/bull: explicit five annual FCFF projections, individual PV=FCFF_t/(1+WACC)^t, TV=FCFF_5*(1+g)/(WACC-g), PVTV=TV/(1+WACC)^5, EV=sum(PV)+PVTV, equity=EV-debt+cash, per-share=equity/shares. Validate WACC>g in every scenario. Show every intermediate and cash/debt/shares.
- Growth module: analyst forward FCFF first; derived analyst revenue/EBITDA/EPS growth second; capped historical growth third; user override supported. Forecast lineage, explicit cap rules and is_estimated exposed. No extreme perpetual growth. Prefer actual Year2 estimate where available, retain period accuracy.
- WACC calculated via CAPM/equity-debt weighting when all inputs available, or clearly marked configured fallback; user override allowed. Display source and inputs. A documented fallback mode satisfies MVP.
- Composite weighted low/base/high, available weights renormalized, no valid models -> explicit unavailable. MOS=(FV-price)/FV; upside=(FV-price)/price. Also expose price premium/discount relative to fair value with unambiguous labels.
- Classification centrally configured boundaries <=.80 significantly_undervalued, <=.90 undervalued, <1 slightly_undervalued, <=1.10 fairly_valued, <=1.25 overvalued, else significantly_overvalued. Chinese UI labels.

## Provider / errors / API
- Provider abstract methods get_quote, get_company_profile, get_balance_sheet, get_cash_flow, get_income_statement, get_forward_estimates, get_historical_multiples. Swappable providers without vendor leakage. No fragile scraping or keys required; do not pretend real data support.
- AVGO fixed TEST/DEMO: price343.83, shares4940000000, cash24000000000, debt59400000000, forward EPS19.21, EBITDA118300000000, equity FCF89600000000. All values including name and estimates are fixture-sourced; fixture date fixed, not falsely updated on each request. Synthetic extra values clearly documented. Unknown demo tickers return clear not found; never clone AVGO under arbitrary ticker.
- Support US listed profitable nonfinancial operating companies; reject banks/insurance/REIT/SPAC/ETF/long-term loss with unsupported_company_type and reason. Guard metadata availability and metric domains.
- Separate provider failure from model failure. Handle invalid ticker, not found, unsupported, missing EPS/forward, negative EBITDA/FCF, provider unavailable/rate limit, stale/bad data, invalid DCF assumptions. Partial model failure retained as unavailable with reason, other models run.
- Data quality HIGH/MEDIUM/LOW based on provenance/missing/estimated inputs; demo ALWAYS clearly demo and LOW. Surface stale dates/warnings (fixture dates intentional).
- Cache interface and per category TTL quote 1-5min, statements24h, estimates12-24h, multiples24h. Overrides per request only and never mutate cached snapshot/defaults.
- POST supports sparse overrides forward_pe.base, ev_ebitda.base, fcf_yield.base, dcf.wacc, dcf.terminal_growth, optional dcf.fcf_growth. Validate ranges/order, unknown fields rejected. Preserve defaults for absent fields and label overrides.
- Response includes ticker/company/current_price/currency/as_of, four valuations each formula/formula_description/inputs/assumptions/calculation_steps/warnings/data_quality/low/base/high/upside; DCF scenario objects; composite; warnings/data_quality/demo marker. JSON numeric representation documented if Decimal strings.

## UI
- / ticker search -> /valuation/AVGO. Dense clean desktop layout, Chinese labels, obvious Demo Data banner and quality/date. Quote/company/ticker/currency, composite low/base/high, MOS/upside/classification.
- Four independent model cards low/base/high/current, full formula, all input values+unit+period+source+as_of+estimated status, assumptions, full step-by-step calculations and price premium/discount. DCF bear/base/bull expandable each all five annual cash flows/PVs/TV/PVTV/EV/equity/debt/cash/shares/value.
- Controls PE, EV multiple, yield, WACC, terminal growth, optional growth. Recalculate POST, Reset default GET AND clear controls. Loading and actionable errors, partial models supported. Frontend formats only.
- Lockfile, .gitignore, env examples, reproducible start instructions. Build/typecheck and browser smoke if available. No login/portfolio/trading/news/chat/database/docker complexity.

## Tests and final report
- test_forward_pe.py exact 19.21*18/20/22 ->345.78/384.20/422.62.
- test_ev_ebitda.py EV/net debt/equity/per-share; test_fcf_yield.py .045 higher than .055; test_dcf.py all discounted years, TV/PVTV/EV/equity/share independent expected math; WACC<=g raises validation error.
- Test classification boundaries, MOS vs upside, partial models and weight normalization, overrides/default isolation, bad domains, unsupported types, provider errors, provenance/FCF definition, cache TTL. Offline fixtures only.
- README purpose, architecture, all formulas/parameters/FCFE-vs-FCFF, installation/start backend/frontend/test commands, demo and replacing with real vendor, support/limitations/errors, APIs/AVGO example, estimate/fallback taxonomy, educational not investment advice.
- Report actual commands/test counts/build status/live endpoint summary, key files, unresolved issues. Do not claim success without actual runs. Send Orca completion using live preamble. Do not start other agents or modify other projects.
