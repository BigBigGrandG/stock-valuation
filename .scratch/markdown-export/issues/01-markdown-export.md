# Issue 01: Valuation Markdown Export

Type: task
Status: resolved

## Description

User request: "增加一个导出功能，可以把已经做完估值的内容导出为markdown格式文本，需要包含估值页面的完整信息。"

Implement complete Markdown text export of the valuation results currently displayed on the valuation page (`/valuation/[ticker]`).
The feature allows users to download a comprehensive, standalone Markdown document containing the entire valuation state:
- Company identity, market price, quote timestamp, financial as-of date, provider, demo/live status, and data quality.
- Comprehensive input metrics table with unit, period, source, confidence, estimation flag, and notes.
- Effective model assumptions, baseline values, applied overrides (distinguishing default vs user-applied).
- Four independent valuation models (Forward P/E, EV/EBITDA, FCF Yield, DCF): formulas, inputs, assumptions, calculation steps, low/base/high targets, upside %, and warnings. If a model is unavailable, clearly document availability status and exact reasons (e.g., currency isolation, financial institution structural mismatch).
- Complete DCF 5-year projections across Bear, Base, and Bull scenarios, including discount factors, PV of cash flows, terminal values, net debt adjustments, and per-share bridges.
- Composite valuation summary: target price range, MOS %, upside/downside %, Chinese valuation classification, weights used, and step-by-step composite calculation.
- Educational and model verification disclaimer, plus explicit export generation timestamp.

## Acceptance Criteria

1. Discoverable button "导出 Markdown" in hero/header area of `/valuation/[ticker]`.
2. Downloads UTF-8 `.md` file named `{ticker}_valuation_{timestamp}.md`.
3. Operates purely in-memory from existing client-side valuation state without triggering any additional API/backend queries.
4. Button is safely disabled when loading, when data is null, or in error states.
5. Markdown escaping for table cells (pipes, newlines) to prevent formatting breakage from company names or notes.
6. Automated formatter unit tests, Playwright browser export verification, and frontend typecheck/lint/build passing.
7. Local production server on port 3000 running the updated code.

## Answer

The Markdown export feature has been implemented, validated, and deployed to the local production server:
1. Created `frontend/lib/exportMarkdown.ts` providing `generateValuationMarkdown(data, options)` and `downloadMarkdown(filename, content)`:
   - Covers 100% of the valuation page information: identity, quotes, as-of dates, provider, LIVE/DEMO status, quality badges, warnings, assumptions & effective overrides, all four models (Forward P/E, EV/EBITDA, FCF Yield, DCF) with formulas, inputs with full provenance (unit, period, source, confidence, estimation flag, notes), assumptions with provenance, calculation steps, DCF 5-year projections and discounting breakdown across Bear/Base/Bull scenarios, EV-to-equity bridges, composite target price range, MOS %, upside %, Chinese valuation classification, weights distribution, step-by-step composite calculation, and educational disclaimers.
   - Separate explicit export timestamp (`exportTime`) from data timestamps.
   - Robust escaping of `|` and newlines to preserve Markdown table integrity.
   - Generates safe filenames matching `{TICKER}_valuation_{YYYYMMDD}_{HHMMSS}.md` (preserving dots for share classes like `BRK.B`).
   - Clean Object URL disposal (`URL.revokeObjectURL`).
2. Integrated discoverable Chinese action button `⭳ 导出 Markdown` in the hero card header of `frontend/app/valuation/[ticker]/page.tsx` (`hero-heading-right`).
   - Operates 100% in-memory from client-side state without triggering any backend or external API requests.
   - Properly disabled during loading or null data states, and absent during error states.
3. Added automated unit tests (`.scratch/markdown-export/test_export_formatter.js`) covering escaping, filename generation, provenance formatting, full 4-model fixture (NVDA), ADR unavailable model isolation fixture (TSM), DEMO fixture (AVGO), and table structure integrity.
4. Added automated Playwright browser tests (`.scratch/markdown-export/browser_test_export.py`) verifying button visibility, real browser download interaction, correct UTF-8 encoding, exact 0 network requests during export, override propagation, reset restoration, and error page safety.
5. Frontend quality gates passed: `npm run typecheck`, `npm run lint`, `npm run build` all passed (0 errors). Production server on port 3000 restarted and verified live.
6. Documentation and acceptance report updated in `.scratch/markdown-export/acceptance.md`.

