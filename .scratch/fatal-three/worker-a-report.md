# Worker A implementation report

## Objective

Remove the cross-model composite valuation from the public product contract end to end while retaining the four independent model outputs (`forward_pe`, `ev_ebitda`, `fcf_yield`, and `dcf`) and their Low/Base/High scenarios.  Composite/weight terminology is no longer emitted by the real API, frontend valuation surface, or Markdown export; unavailable models remain unavailable instead of causing other models to be reweighted.

Task: `task_2c8af1e06d44`  
Dispatch: `ctx_9c489ff60e50`  
Ownership: Worker A implementation, tests, and scoped documentation.  
Requested runtime: Codex Luna Max (max); runtime provider/model introspection is **Not verified**.

## Baseline and repository safety

Baseline was captured before edits:

- Branch: `master...origin/master`
- HEAD: `68e98d4 (HEAD -> master, origin/master) 修复两个严重问题`
- Initial tracked diff: none
- Initial untracked artifact: `.scratch/fatal-three-implementation.md`
- No commit, push, reset, clean, or destructive cleanup was performed.

The final shared worktree also contains concurrent Worker B/C edits and reports.  Those changes were preserved; they are listed separately below and are not part of Worker A's intentional implementation.

## Implementation

Worker A intentionally changed:

- Backend public response/override boundary: `backend/app/models/domain.py`, `backend/app/models/overrides.py`, `backend/app/services/valuation_service.py`, and `backend/app/main.py`.
- Frontend public types, page, styles, and export: `frontend/lib/types.ts`, `frontend/app/valuation/[ticker]/page.tsx`, `frontend/app/globals.css`, and `frontend/lib/exportMarkdown.ts`.
- Contract/regression coverage: `backend/tests/test_api_integration.py`, `backend/tests/test_audit_issues_01_02_regression_r5.py`, `backend/tests/test_e2e_valuation_integrity_export.py`, `backend/tests/test_p0_p1_integrity.py`, `backend/tests/test_fatal_three_worker_a.py`, `frontend/tests/contract_export.spec.ts`, `frontend/tests/e2e_valuation_integrity.spec.ts`, and `frontend/tests/fixtures/contract_avgo_response.json`.
- Scoped product documentation: `README.md` and `docs/agents/project-constraints.md`.

The service no longer invokes `run_composite`; `ValuationResponse` has no public `composite` field; public assumptions and override schemas have no composite weight fields; and retired fair-value aliases are not synthesized by `_enrich`.  The UI no longer renders aggregate/fair-value/classification/weight sections, and Markdown export contains only the four independent model scenario tables.  The legacy composite engine and internal legacy model/override classes remain import-compatible but are outside the public HTTP/schema path, as documented in code.

## Verification

All commands below were run in the stated working directory and exited 0 unless noted.

| Working directory | Command/result |
| --- | --- |
| `D:\workshop\stock-valuation` | `.\.venv\Scripts\python.exe -m compileall -q backend/app` — pass |
| `D:\workshop\stock-valuation` | Real API/OpenAPI smoke script — GET `/api/v1/valuation/AVGO` returned 200 without `composite`, fair-value aliases, or public weight keys; POST with `weights` returned 422; OpenAPI omitted composite/weight schemas; all four models exposed `low`, `base`, `high` — pass |
| `D:\workshop\stock-valuation` | `.\.venv\Scripts\python.exe -m pytest backend/tests/test_api_integration.py -q` — **19 passed**, 2 warnings |
| `D:\workshop\stock-valuation` | `.\.venv\Scripts\python.exe -m pytest backend/tests/ -q` — **379 passed**, 2 warnings |
| `D:\workshop\stock-valuation` | `.\.venv\Scripts\python.exe -m pytest backend/tests/test_fatal_three_worker_a.py -q` — **3 passed**, 2 warnings |
| `D:\workshop\stock-valuation\frontend` | `npx playwright test tests/contract_export.spec.ts --reporter=line` — **3 passed** |
| `D:\workshop\stock-valuation\frontend` | `npx playwright test --reporter=line` — **6 passed** |
| `D:\workshop\stock-valuation\frontend` | `npm run typecheck` — pass |
| `D:\workshop\stock-valuation\frontend` | `npm run lint` — pass |
| `D:\workshop\stock-valuation\frontend` | `npm run build` — pass; Next.js compiled and generated static pages |
| `D:\workshop\stock-valuation` | `node` fixture JSON validation — no composite/fair-value/assumption-weight keys — pass |
| `D:\workshop\stock-valuation` | `git diff --check` — pass; Git emitted only LF/CRLF conversion warnings |

Not run: live-provider/network verification against production data, deployment, commit, or push.  Tests use the repository's controlled test/demo provider as required for deterministic regression coverage.

## Concurrent files and merge boundary

The following modified/untracked files appeared from Worker B/C in the shared worktree and were not intentionally changed by Worker A: `backend/app/engines/dcf.py`, `backend/app/engines/fcf_yield.py`, `backend/app/providers/base.py`, `backend/app/providers/statement_aggregator.py`, `backend/app/providers/yfinance_provider.py`, `backend/app/services/projections.py`, `frontend/components/DCFScenarios.tsx`, `backend/tests/test_fatal_three_worker_c.py`, and `backend/tests/test_forward_fcfe_borrowing_isolation.py`.

`frontend/lib/types.ts` and `frontend/lib/exportMarkdown.ts` are shared surfaces: Worker A removed composite/weight output there while preserving the concurrent DCF timeline additions.  Coordinator review is required before final acceptance of those shared hunks.

## Risks and remaining work

- Legacy `CompositeValuation`, internal weight fields, `WeightOverride`, classification helpers, and `app/engines/composite.py` remain for direct/import compatibility; they are not exposed through the public response or override schema.  Hard deletion would be a separate compatibility decision.
- Root `AGENTS.md` and historical `HANDOFF.md` were not rewritten because they are governing/historical instructions; older composite wording may remain there.
- Coordinator should review the shared frontend files and combine Worker B/C changes before final delivery.

## Resume here

Worker A implementation and validation are complete.  The only required follow-up is coordinator-level review/acceptance of concurrent Worker B/C changes and the shared frontend merge boundary; no Worker A command remains pending.
