# Enable real valuation lookup for arbitrary US stock tickers

Status: resolved
Type: task
Specification: ../spec.md

## Problem

User entered NVDA and received AVGO-only demo-provider 404. The delivered offline MVP did not fulfill the user's intended general US stock lookup requirement.

## Acceptance

Real default provider, applicable-model analysis, robust missing/error handling, no cloned or invented data, independent multi-ticker API/browser verification. See spec.

## Answer

All acceptance criteria for enabling real valuation lookup for arbitrary US stock tickers have been fulfilled, verified, and certified:

1. **Default Live Provider**: Replaced the AVGO-only demo provider with keyless `YFinanceProvider` as default, preserving the AVGO fixture strictly for offline demo testing (`DATA_PROVIDER=demo` or `?provider=demo`).
2. **Applicable-Model Isolation**: Implemented deterministic four-model engines (Forward P/E, EV/EBITDA, FCFE Yield, FCFF DCF) with dynamic weight renormalization for available models. Financial institutions (JPM, BRK.B), loss-makers (RIVN), and foreign ADRs with statement currency mismatches (TSM) cleanly report explicit typed unavailable reasons rather than failing or inventing numbers.
3. **Foreign ADR Support**: Foreign companies trading in USD on US exchanges (e.g. TSM on NYSE) are recognized and supported for Forward P/E based on per-ADS USD quotes and estimates, while non-USD statement models are isolated without fabricated FX conversions.
4. **Interactive Overrides & Clean Reset**: Tested real numerical override calculations and single-request reset behavior (GET without `/reset` suffix) clearing all 6 controls under nominal, 429 rate-limit, and 503 unavailable conditions.
5. **Quality & Test Coverage**:
   - Backend pytest suite: 250 passed, 0 failed in both live and isolated demo modes.
   - API streaming & cancellation deep test suite: 6 passed, 0 failed.
   - Live browser acceptance suite: 14 checks passed, 0 failed, with 18 screenshots and 6 live production JSON responses captured.

Full acceptance mapping and evidence details are recorded in [.scratch/live-tickers/final-acceptance.md](file:///D:/workshop/stock-valuation/.scratch/live-tickers/final-acceptance.md).
