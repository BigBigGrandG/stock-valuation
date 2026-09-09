# Frontend production verification

Date: 2026-09-08 (Asia/Shanghai)

## Static verification

From `frontend/`:

```text
npm run typecheck
> tsc --noEmit
PASS (exit 0)

npm run build
> next build
PASS (exit 0)
Route (app)
/                    1.27 kB   101 kB
/_not-found           .989 kB   101 kB
/valuation/[ticker]   13.1 kB   113 kB
```

The final production server was restarted with `npm start` on `127.0.0.1:3000` after the build.

## API/schema verification

The backend health endpoint returned `status=ok`, `version=0.2.0`, and demo ticker `AVGO`.
The live AVGO response contains all four model keys (`forward_pe`, `ev_ebitda`, `fcf_yield`,
`dcf`), `input_metrics`, `assumption_metrics`, and provenance fields including source, period,
date, and estimated flags. The DCF base scenario exposes five projection periods and backend
calculation details; no valuation arithmetic is performed in the frontend.

The final live schema check reported `valuations=forward_pe,ev_ebitda,fcf_yield,dcf`, all four
models with both metric maps, and DCF base periods
`FY2025E,FY2026E,FY2027E,FY2028E,FY2029E` with `projection_metrics=5`, `pv_years=5`, and
`formulas=True`.

Direct integration checks passed:

- Nested POST override with `forward_pe.base=18`, `fcf_yield.base=0.05`,
  `dcf.wacc=0.095`, and `dcf.terminal_growth=0.035` returned those values with
  `source_type=user_override`.
- Reset uses the ordinary default `GET /api/v1/valuation/AVGO`; it restored P/E base
  `22.0000` and WACC `0.10`.
- DCF projection count is `5`; unknown ticker requests return HTTP 404.

## Browser smoke on the final build

Using the running Chrome window against `http://127.0.0.1:3000`:

- AVGO loaded `Broadcom Inc.` with all four models, provenance-rich inputs/assumptions,
  and DCF rows `FY2025E`, `FY2026E`, `FY2027E`, `FY2028E`, `FY2029E`.
- Entering P/E `18` and applying the override rendered the P/E base target `$345.78` and
  showed the input as `Value: 18`.
- Clicking `重置默认` issued the default GET, restored P/E base `$422.62`, and left all
  six override controls empty.
- Searching `MSFT` showed `查询未完成` with the backend's actionable `Ticker 'MSFT' not
  found` message and no stale AVGO valuation content. The browser was returned to AVGO,
  which again rendered `Broadcom Inc.` and the five-year DCF table.

## Backend regression

```text
backend/tests: 80 passed, 2 warnings
```
