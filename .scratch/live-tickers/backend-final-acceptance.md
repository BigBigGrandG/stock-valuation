# Backend Final Acceptance Report (Round 3)

**Execution Timestamp**: `2026-09-10T00:28:30+08:00` (UTC: `2026-09-09T16:28:30Z`)  
**Task ID**: `task_def0fed44b44`  
**Dispatch ID**: `ctx_7bf99ac3b8e7`  
**Coordinator Terminal**: `term_d2a16072-40cd-41fe-925a-bdaa0d153321`  
**Worker Terminal**: `term_d1452db2-3a82-4a67-b3ce-be459cd361d4`  
**Live API Service**: `http://127.0.0.1:8002` (PID: `50736`, Python 3.12.13, uvicorn started at `2026-09-10 00:26:55+08:00`)  

---

## 1. Executive Summary

All concrete requirements from `.scratch/live-tickers/backend-final-round3.md` have been fully implemented, verified, and grounded against both the live API service and the complete test suite:

1. **Real Bounded Upstream Resources**:
   - `_fetch_property` in `YFinanceProvider` now bounds both submitted and running work: admission semaphore (`_SEMAPHORE`, capacity 5) is acquired before thread pool execution and released **strictly upon actual future completion** via `future.add_done_callback(_on_future_done)`.
   - Callers timing out outside the lock return promptly within their requested deadline (`rem = req_budget.remaining`) without prematurely releasing admission slots while background work continues.
   - In-flight property fetches are tracked and deduplicated in `_TickerBundle._inflight`. Retries and concurrent requests for the same property attach to the existing running future without launching duplicate upstream requests or overflowing queues.
   - Bundle eviction during TTL expiry checks `bundle.has_inflight()` to prevent abandoning in-flight work.
   - Tested with event-blocked upstream, 5 saturating workers, 6th request timing out cleanly on semaphore wait, and immediate non-leaking recovery after the event unblocks.

2. **Total Incoming Valuation Budget Across Service/API Aggregation Path**:
   - A thread-safe, async-safe `current_request_budget` (`ContextVar[Optional[_RequestBudget]]`) is established in `yfinance_provider.py`.
   - `FinancialDataService.get_snapshot` creates and binds a single request-level `_RequestBudget` across the entire aggregation path: checking deadlines before category cache lookup, before each of the 7 serial provider calls, inside bundle locks, during concurrency semaphore acquisition, and during future waits.
   - Real service and API tests (`test_total_incoming_valuation_budget_across_service_path` and `test_api_valuation_endpoint_total_budget_timeout`) prove that cumulative short delays across categories exceeding a small total budget abort with HTTP 503 `ProviderUnavailableError`.
   - Cached and partial-cache requests return within budget without unnecessary upstream waits.

3. **Forecast Alignment Strictly Without Projection**:
   - Eliminated lines 197–203 projection fallback in `_verify_forecast_alignment`. Genuine `nextFiscalYearEnd` metadata from upstream `info` is strictly required; absence results in `forecast horizon unproven`.
   - Proved that the consensus 0y estimate horizon maps directly to `nextFiscalYearEnd` (e.g. current in-progress fiscal year).
   - Enforces calendar boundaries: rejects stale horizons (`days_to_next < 180`), distant/non-adjacent horizons (`days_to_next > 450`), and date mismatches (`nextFiscalYearEnd <= lastFiscalYearEnd`).
   - Non-annual statement periods (e.g. Q3 or TTM) are cleanly rejected for forward growth projections.

4. **ADR Currency & Share Basis Evidence Enforcement**:
   - In `YFinanceProvider.get_forward_estimates`, per-row `currency` and share basis (`ADS` for ADRs vs `share` for domestic equities) are validated against `earnings_estimate`.
   - ADR forward EPS is rejected with explicit explanatory notes if earnings estimate currency is missing, unknown, or does not match quote currency (e.g. TWD or EUR).
   - Grounded TSM live evidence captured directly from Yahoo Finance into `.scratch/live-tickers/tsm_raw_capture.json`: verifies `currency: "USD"` for all estimate rows, quote price in USD per ADS ($433.66), preserving a valid USD/ADS Forward P/E ($16.93 EPS × 20x = $338.60 base fair value).
   - Statement models (EV/EBITDA, FCF yield, DCF) remain safely disabled for TSM due to underlying statement reporting in TWD.

5. **Test Suite & Live Oracle Verification**:
   - Pytest suite: **250 passed, 0 failed** in both default and isolated `DATA_PROVIDER=demo` mode.
   - Live Core verification (`verify_live.py`): **PASS** for `NVDA`, `AAPL`, `MSFT`, `AVGO`, `KO`.
   - Live Special verification (`verify_special_tickers.py`): **PASS** for `JPM`, `BRK.B`, `RIVN`, `TSM`, `SPY`, `INVALIDZZZZ`.
   - Reconciliation report (`generate_reconciliation.py`): **PASS** updating `.scratch/live-tickers/reconciliation_report.md`.

---

## 2. Verification Artifacts & Test Evidence

### A. Full Pytest Execution (250 Passed)
- **Command**: `D:\workshop\stock-valuation\.venv\Scripts\python.exe -m pytest backend/tests/ -v`
- **Exit Code**: `0`
- **Results**: `250 passed, 2 warnings in 4.35s`
- **Isolated Demo Mode**: `$env:DATA_PROVIDER="demo"; pytest backend/tests/` -> `250 passed in 4.32s`

### B. Round 3 Dedicated Acceptance Suite (`backend/tests/test_round3_acceptance.py`)
- **Command**: `D:\workshop\stock-valuation\.venv\Scripts\python.exe -m pytest backend/tests/test_round3_acceptance.py -v`
- **Exit Code**: `0`
- **Results**: `8 passed in 1.29s`
- **Test Matrix**:
  1. `test_bounded_upstream_resources_event_blocked_and_recovery`: 5 threads block on event, 6th fails cleanly on semaphore budget; event release frees slots; 7th recovers immediately.
  2. `test_same_ticker_inflight_reuse_no_duplicate_submissions`: 5 concurrent threads requesting same bundle property trigger exactly 1 upstream submission.
  3. `test_total_incoming_valuation_budget_across_service_path`: cumulative serial delays exceeding 0.15s total budget abort with ProviderUnavailableError.
  4. `test_api_valuation_endpoint_total_budget_timeout`: FastAPI endpoint returns HTTP 503 Provider unavailable on total deadline exceeded.
  5. `test_cached_and_partial_cache_requests_succeed_within_budget`: cached data returns within 0.05s budget without hitting upstream.
  6. `test_verify_forecast_alignment_missing_next_fiscal_year`: missing `nextFiscalYearEnd` disables forward derived models without projection.
  7. `test_verify_forecast_alignment_stale_and_non_calendar_and_mismatch`: covers non-annual, date mismatch (next <= last), stale (<180d), and non-adjacent (>450d).
  8. `test_adr_currency_validation_rejects_non_usd_or_missing_currency`: verifies per-row ADR estimate currency validation, rejecting non-USD or missing currencies, and enabling valid USD/ADS basis.

### C. Live Core Equities Verification (`.scratch/live-tickers/verify_live.py`)
- **Command**: `D:\workshop\stock-valuation\.venv\Scripts\python.exe .scratch/live-tickers/verify_live.py`
- **Exit Code**: `0`
- **Live Results**:
  ```text
  PASS NVDA: NVIDIA Corporation; quote=223.85; models=forward_pe,ev_ebitda,fcf_yield,dcf
  PASS AAPL: Apple Inc.; quote=313.54; models=forward_pe,ev_ebitda,fcf_yield
  PASS MSFT: Microsoft Corporation; quote=491.54; models=forward_pe,ev_ebitda,fcf_yield,dcf
  PASS AVGO: Broadcom Inc.; quote=359.45; models=forward_pe,ev_ebitda,fcf_yield,dcf
  PASS KO: Coca-Cola Company (The); quote=88.11; models=forward_pe,ev_ebitda,fcf_yield,dcf
  PASS: real distinct multi-ticker lookup, metadata, applicable models, DCF arithmetic and composite
  ```

### D. Live Special Tickers Verification (`.scratch/live-tickers/verify_special_tickers.py`)
- **Command**: `D:\workshop\stock-valuation\.venv\Scripts\python.exe .scratch/live-tickers/verify_special_tickers.py`
- **Exit Code**: `0`
- **Live Results**:
  - `JPM` (Bank): status 200, Forward P/E available ($354.82), EV/EBITDA, FCF yield, DCF disabled due to banking structure.
  - `BRK.B` (Dual-class / Insurance): status 200, Forward P/E available ($507.10), statement models disabled due to insurance structure.
  - `RIVN` (Loss-maker): status 200, Forward EPS non-positive (-$2.44), models safely unavailable.
  - `TSM` (ADR): status 200, Forward P/E available in USD ($433.66 price, $16.93 forward EPS per ADS); EV/EBITDA, FCF yield, DCF disabled due to TWD statement currency mismatch.
  - `SPY` (ETF): status 422, rejected with `unsupported_company_type: etf`.
  - `INVALIDZZZZ` (Delisted/Unknown): status 404, rejected cleanly.
  - Summary: `ALL SPECIAL TICKER ASSERTIONS PASSED!`

### E. Empirical Raw TSM Capture (`.scratch/live-tickers/tsm_raw_capture.json`)
- Direct capture from `yfinance.Ticker("TSM")`:
  - `currency`: `"USD"`
  - `financialCurrency`: `"TWD"`
  - `regularMarketPrice`: `433.7057`
  - `earnings_estimate_records`:
    - `period: "0y", avg: 16.93389, currency: "USD", numberOfAnalysts: 13, growth: 0.59`
    - `period: "+1y", avg: 21.9251, currency: "USD", numberOfAnalysts: 13, growth: 0.2947`
  - Validates per-row USD currency and ADS basis, proving why TSM Forward P/E is mathematically sound while statement models are isolated.

---

## 3. Source File SHA256 Hashes

| File | SHA256 Hash |
|---|---|
| `backend/app/providers/yfinance_provider.py` | `B9184095944AF034458B236A5E4EE7F50BDE48A8A4EBEE0CE36435E112DD8E50` |
| `backend/app/services/valuation_service.py` | `6AD7571F6CBF760D048C608FE28FBF67F3D671F851C15BAC3B78DA8C444DC57E` |
| `backend/tests/test_round2_acceptance.py` | `47C4552DADE2EC47AB615E05CABA25FAFD380EB56A713144A92000026EB41AF0` |
| `backend/tests/test_round3_acceptance.py` | `32CBE000805AA744601367AF7B3496CDD0FB19012C361A95FFD376BC26654173` |
| `.scratch/live-tickers/tsm_raw_capture.json` | `74654B64A6C28871018173151CD3D9065B05818A2FAA5B76B4AA674B904F55DB` |
| `.scratch/live-tickers/verify_live.py` | `0AFA59427E1D3A1D3E7D32AE642983B846DA8CD7CEDABF00FF1272C06B39DC5E` |
| `.scratch/live-tickers/verify_special_tickers.py` | `18B5F75776895BD3E6555CC216624D23F8A32030F445DB8D7E8DBB655D82A071` |
| `.scratch/live-tickers/generate_reconciliation.py` | `1A4F5689E368BD752D45CE5E3CA44BCB5B62209B02B2571B6AEFC66B4DD74A32` |

---

## 4. Git Repository Baseline Status

- **Status**: The repository currently has **no commits yet** on `master` (`On branch master, No commits yet`).
- **Limitation**: Standard `git diff HEAD` is unavailable because no initial root commit exists in the repository.
- In strict adherence to dispatch constraints, zero git commits, resets, or pushes were initiated. All files are cleanly tracked in the working directory.
