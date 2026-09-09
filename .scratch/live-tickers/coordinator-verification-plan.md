# Coordinator acceptance strategy

Workers execute checks and preserve evidence; the coordinator reviews the evidence and decides acceptance. A worker completion message alone is not acceptance.

## Backend correction and verification

1. Reproduce missing cash/debt/CFO/capex/interest/tax, a newest-column NaN with prior-year values, and mismatched quote/financial currencies using mocked vendor responses. Assert no invented zero, no mixed-period calculation, and no USD/currency mixing. Keep unaffected models usable.
2. Test derived forward EBITDA/FCFE/FCFF source type, notes/formula, raw and capped growth, and fiscal-year mapping. Analyst EPS 0y is current fiscal year, +1y is next fiscal year; neither implies two rolling years ahead. Avoid applying annual growth to a mismatched TTM base.
3. Current trailing PE and EV/EBITDA must not populate historical forward-multiple fields. Defaults remain explicit configured assumptions.
4. Exercise source failures 429, 503, timeout, missing fields and absent symbol. A swallowed upstream exception must not become false 404 or a fabricated valid statement. Bound upstream waits and concurrency, including fallback history requests.
5. Run the full offline pytest suite and preserve output. Existing Decimal, net-debt, sparse override, terminal-growth and weight invariants remain required.
6. Restart the default live API and run `.venv/Scripts/python.exe .scratch/live-tickers/verify_live.py`. Preserve all five raw responses. Test JPM, BRK.B/BRK-B, RIVN, an ADR with non-USD statements, SPY and an invalid/unknown code. Unsupported models require specific reasons, not copied AVGO data.
7. For NVDA and KO, reconcile one raw source statement column with normalized cash/debt/FCFE/FCFF and the exact formulas. Record period, units and actual source fields. Do not merely compare the application with itself.

## Frontend correction and verification

1. Run typecheck/build; start the production frontend. Search NVDA then AAPL and MSFT. Preserve requests, responses and screenshots showing correct company identity.
2. Override and reset: check request counts, reset is one GET, fields clear, default result restored. 429/503 must not trigger automatic duplicate reset requests.
3. Simulate delayed headers and delayed JSON body, then timeout/cancel/switch ticker; stale result/error must not overwrite current ticker and spinner must terminate.
4. Exercise BRK.B, ETF, invalid code and unknown code. Labels must match backend support; LIVE must say prices may be delayed, with quote timestamp separate from report period.
5. Report command exit codes and assertions, test evidence paths, and any unresolved behavior. Do not claim tests were executed when only reasoned about.

## Acceptance decision

Coordinator reviews changed source and evidence, requests bounded corrections for failures, and closes the issue only after the real-ticker requirement and the above applicable checks pass. No commits or pushes.
