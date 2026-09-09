# Service-independent acceptance test review

## Summary

Wrote 82 compact offline regression tests in
`backend/tests/test_service_independent_acceptance.py` covering all 8
requested acceptance areas. All **82 pass** on current backend code (0.49 s).

## Test inventory

| # | Area | Tests | Status |
|---|------|-------|--------|
| 1 | Seven-public-method provider compatibility | 5 | ✅ all pass |
| 2 | Fresh quote + old balance/estimate dates, source/period metadata | 6 | ✅ all pass |
| 3 | Explicit zero confidence including estimated values | 5 | ✅ all pass |
| 4 | Explicit incompatible FCFE/FCFF types rejected | 11 | ✅ all pass |
| 5 | Bank/insurance/REIT/SPAC/ETF/non-US/loss/Financial Services rejection | 16 | ✅ all pass |
| 6 | Provider 429/503/404 vs invalid-financial-data 422 via TestClient | 14 | ✅ all pass |
| 7 | Injected monotonic category TTL expiry | 8 | ✅ all pass |
| 8 | Model exception isolation | 7 | ✅ all pass |
| — | Cross-cutting (demo quality, net debt, override contract) | 10 | ✅ all pass |
| **Total** | | **82** | **82 passed, 0 failed** |

## Implementation details & corrections applied

1. **Precise validation exceptions**: Replaced all broad `raises(Exception)`
   and generic `ValueError` checks with exact exception types:
   - `pydantic.ValidationError` for metric field bounds (`confidence` out of [0, 1]) and override schema validation (`extra="forbid"`, inverse yield ordering, non-numeric values).
   - `FinancialDataValidationError` for all normalizer cash-flow type cross-wiring and data invariant violations.
   - `UnsupportedCompanyError` for all company-profile support guard rejections (sector/industry, non-US, unprofitable).

2. **Actual TestClient API error requests**: Replaced no-op patch / direct `_raise_http` unit calls with real HTTP requests using FastAPI's `TestClient` against the live FastAPI app with injected `FailingProvider`:
   - `test_rate_limit_maps_to_429_via_api`: verifies HTTP 429 when provider raises `ProviderRateLimitError`.
   - `test_unavailable_maps_to_503_via_api`: verifies HTTP 503 when provider raises `ProviderUnavailableError`.
   - `test_not_found_maps_to_404_via_api`: verifies HTTP 404 when provider raises `TickerNotFoundError`.
   - `test_financial_data_validation_maps_to_422_via_api`: verifies HTTP 422 when provider raises `FinancialDataValidationError`.
   - `test_invalid_ticker_maps_to_422_via_api`: verifies HTTP 422 when provider raises `InvalidTickerError`.

3. **Cash-flow definition cross-wiring**: Retained the natural-language definition rejection test (`test_fcfe_definition_mentioning_only_fcff_rejected`), which asserts that `"Free Cash Flow to Firm unlevered only"` on the FCFE path raises `FinancialDataValidationError`. The backend normalizer now normalizes natural-language phrases before checking, and the test passes cleanly. Added matching test for the FCFF path (`test_fcff_definition_mentioning_only_fcfe_rejected`).

4. **Cash-flow metadata normalization tests**: Added compact normalization tests in Section 4:
   - `test_estimates_mixed_fcff_types_rejected`: estimates with `forward_fcff_1y_type=FCFF` and `forward_fcff_2y_type=FCFE` is rejected with `FinancialDataValidationError`.
   - `test_cash_flow_fallback_fcff_with_fcfe_type_rejected`: `forward_fcff_1y` supplied from cash-flow fallback with `forward_fcff_1y_type=FCFE` is rejected with `FinancialDataValidationError`.
   - `test_estimates_mixed_fcfe_types_rejected`: inverse estimates test with `forward_fcfe_1y_type=FCFE` and `forward_fcfe_2y_type=FCFF` rejected.
   - `test_cash_flow_fallback_fcfe_with_fcff_type_rejected`: inverse fallback test with `forward_fcfe_1y` typed as `FCFF` rejected.

5. **Monotonic category TTL expiry**: Injected a monotonic clock (`lambda: t[0]`) into `MemoryTTLCache` to deterministically verify that quotes expire after 120s while balance sheets and statements survive past 120s up to 86400s, estimates expire after 43200s, and multiples expire after 86400s.

## How to run

```bash
D:\workshop\stock-valuation\.venv\Scripts\python.exe -m pytest backend/tests/test_service_independent_acceptance.py -v --tb=short
```

## Files modified

- `backend/tests/test_service_independent_acceptance.py`
- `.scratch/valuation-mvp/service-independent-review.md`
