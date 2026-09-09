# Real US ticker valuation (user correction)

The user explicitly requires entering an arbitrary US stock ticker and receiving valuation analysis. AVGO-only synthetic demo acceptance is insufficient. This specification supersedes earlier demo-only scope and lookup guards that reject all loss-making or financial equities before any analysis.

## Delivery

- Default application uses real market/financial data, with no finite ticker whitelist, synthetic fallback, or AVGO cloning. Offline demo is explicit opt-in for tests/demo use.
- General listed equity lookup resolves the actual company/quote and uses applicable models. Missing data or inappropriate model assumptions remain unavailable with a specific reason; never invent a numeric target merely to fill four cards. Distinguish supported security lookup from individual model applicability.
- Initially validate a keyless yfinance source against actual NVDA/AAPL/MSFT requests. Preserve replaceable provider interface for later data vendors. Record upstream failures honestly and bound request time/cache/retries.
- Each input carries units, source, source type, actual period/date and estimate/confidence metadata. Quote timestamps must not make old statements look current. Annual vs TTM must be explicit. Derived forward estimates must expose the calculation and must not be labelled analyst consensus.
- FCFE and FCFF remain distinct. Avoid zero-imputing missing cash/debt/shares/interest/tax/borrowing data. Explain approximations and disable models when reliable derivation is not possible.
- UI accepts arbitrary ticker (including common share-class spelling), displays live/demo appropriately, differentiates user-input/data coverage/upstream/network/model errors, and maintains cancel/reset/stale-response protection.
- No commits or pushes. User prefers Antigravity Gemini 3.8 Flash High for workers and explicitly authorized full access/no confirmation subject to platform restrictions.

## Acceptance

- Default HTTP NVDA, AAPL, MSFT, AVGO and one non-tech stock return distinct real company/quote/provenance with is_demo=false and at least one valid valuation model where data permit.
- Exercise a financial equity, a loss-making equity, share-class ticker and invalid/unlisted ticker. Return useful applicable analysis or specific data/applicability explanation; no AVGO-only messages.
- Offline tests cover vendor mappings, missing/NaN fields, period/currency consistency, FCFE/FCFF derivation, upstream429/503/404, cache isolation, and preservation of existing financial invariants. No network access in ordinary pytest.
- Frontend typecheck/build plus actual browser NVDA and subsequent AAPL/MSFT lookup; override/reset and error recovery remain functional.
- Coordinator defines independent checks, delegates their execution to workers, and reviews source and preserved evidence before completion. This follows the user's clarified coordination preference. A successful demo or mocked request alone is not acceptance. See `coordinator-verification-plan.md` for concrete checks.

## Ownership

- Backend correction and verification: task_1562fda510f2 / ctx_d6e7e927e568 / term_d1452db2-3a82-4a67-b3ce-be459cd361d4. Own backend, root README and dependency manifests. See `backend-round2.md`.
- Frontend verification: task_ca954ac243af / ctx_d25b0ad729bc / term_53f5a7d6-2b19-4cf1-ad03-d57cb257e0d5. Own frontend. See `frontend-evidence-gap.md`.
- Coordinator: independent validation, source research and this issue/spec.

## Documentation checked

- https://ranaroussi.github.io/yfinance/reference/yfinance.analysis.html
- https://ranaroussi.github.io/yfinance/reference/yfinance.financials.html
- Context7 library /ranaroussi/yfinance: earnings_estimate periods 0q,+1q,0y,+1y (not automatic two upcoming fiscal years); calendar/filing periods require correct mapping.
- SEC companyfacts API is a potential audited-statement source, not a quote/analyst-estimate API: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
