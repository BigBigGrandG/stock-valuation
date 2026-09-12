# Issue 03 R4 implementation report — FCFE yield fallback disclosure

Date: 2026-09-12 (Asia/Shanghai)  
Worker ownership: Issue 03 R4 FCFE-yield warning, API/UI/Markdown regression, and verification evidence.  
Runtime: `codex / gpt-5.6-luna / max` reused per task contract; no Antigravity probe or runtime fallback was performed.

## Objective and scope

Completed the final R4 gap from `rework-03-r4.md`: when no compatible company/industry FCFE-yield benchmark is available, the effective configured system yield remains explicit and the user receives one truthful specificity warning. User overrides are request-scoped and do not receive the configured-fallback warning. No formulas, benchmark mappings, DCF behavior, numeric assumptions, or Issue 04 work were changed.

## Baseline and protected state

- Baseline: `master` at `d0a7d62` (`origin/master` matched at task start).
- The worktree already contained R1–R3 product edits, tests, reports, and untracked evidence. Those were preserved; the already-dirty `frontend/tests/e2e_valuation_integrity.spec.ts` received only additive R4 assertions.
- No `git clean`, `git reset --hard`, commit, push, deployment, or nested worker was used.
- Issue 03 remains `pending coordinator acceptance`; Issue 04 remains accepted/closed by `acceptance-03-04-r3.md`.

## Implementation

- `backend/app/engines/fcf_yield.py`: adds one canonical fallback warning and appends it only after valid positive FCFE/yield inputs are established and only for `SourceType.CONFIGURED_FALLBACK`. Unavailable models do not claim a fallback valuation was used, and `USER_OVERRIDE` does not match the branch.
- `backend/tests/test_audit_issues_03_04_rework_r4.py`: production FastAPI-path regressions cover configured fallback propagation/deduplication and user override isolation.
- `frontend/tests/e2e_valuation_integrity.spec.ts`: additive real-browser assertions cover API JSON, rendered FCF-yield warning, and downloaded Markdown after override/reset workflows.
- `.scratch/valuation-ai-audit-20260911/verification/03-r4/`: raw command stdout/stderr, cwd, and exit evidence.

Canonical warning:

> No compatible company/industry-specific FCFE-yield benchmark is available; using the configured system yield fallback because parameter specificity is insufficient.

## Acceptance

| Requirement | Result |
| --- | --- |
| Configured fallback remains explicit and warns about missing compatible FCFE-yield benchmark | PASS — model assumptions retain `yield_source=fallback` and `fcf_yield_source=configured_fallback`; focused test finds exactly one semantic warning in model and aggregate API lists. |
| User override is not mislabelled as system fallback | PASS — API POST with `fcf_yield.base` returns `user_override` at both assumption layers and no fallback warning. |
| API/UI/Markdown propagation | PASS — backend API regression plus real-browser JSON, DOM, and downloaded Markdown assertions. |
| Preserve formulas, unavailable semantics, R1–R3, and accepted Issue 04 | PASS — only warning branch/tests changed; full backend and retained Issue 03/04 regressions pass. |
| Issue lifecycle | PASS — Issue 03 intentionally remains pending coordinator close; no status change made in R4. |

## Verification commands

All commands ran from the stated cwd; raw output is under `verification/03-r4/`.

| Command | cwd | Result / exit | Artifact |
| --- | --- | --- | --- |
| `\.venv\Scripts\python.exe -m pytest backend/tests/test_audit_issues_03_04_rework_r4.py -q` (before fix) | repo root | EXPECTED RED — 1 failed, 1 passed; exit 1 | `focused-red-command.log` |
| `\.venv\Scripts\python.exe -m pytest backend/tests/test_audit_issues_03_04_rework_r4.py -q` | repo root | PASS — 2 passed, 2 dependency deprecation warnings; exit 0 | `focused-green-command.log` |
| `\.venv\Scripts\python.exe -m pytest backend/tests/test_audit_issues_03_04_rework_r4.py backend/tests/test_audit_issues_03_04_rework_r3.py backend/tests/test_audit_issues_03_04_rework_r2.py backend/tests/test_audit_issues_03_04_regression.py -q` | repo root | PASS — 25 passed, 2 warnings; exit 0 | `backend-targeted-command.log` |
| `\.venv\Scripts\python.exe -m pytest backend/tests -q` | repo root | PASS — 371 passed, 2 warnings; exit 0 | `backend-full-command.log` |
| `\.venv\Scripts\python.exe -m compileall -q backend/app backend/tests` | repo root | PASS; exit 0 | `compileall-command.log` |
| `npm run typecheck` | `frontend/` | PASS; exit 0 | `frontend-typecheck-command.log` |
| `npm run lint` | `frontend/` | PASS; exit 0 | `frontend-lint-command.log` |
| `npx playwright test tests/contract_export.spec.ts --reporter=line` | `frontend/` | PASS — 3 passed; exit 0 | `frontend-contract-export-command.log` |
| `npx playwright test tests/e2e_valuation_integrity.spec.ts --reporter=line` | `frontend/` | PASS — 3 passed; exit 0 | `frontend-e2e-warning-command.log` |
| `git diff --check` | repo root | PASS; exit 0 (Git emitted existing LF/CRLF conversion notices only) | `git-diff-check-command.log` |

The backend warnings are the pre-existing Starlette/httpx deprecation notices. Playwright logs contain the existing Node `NO_COLOR` notice. No new debug instrumentation remains.

## Risks and pending items

- The current data contract has no credible compatible company/industry FCFE-yield benchmark; the conservative configured system yield remains intentionally in force and is now disclosed. This is an explicit limitation, not a fabricated benchmark.
- The existing UI/export architecture renders aggregate data reminders and model-level warnings in their respective contexts; the engine adds the new warning only once and the aggregate API list is deduplicated.
- NOT RUN: new live network capture or six-ticker replay (explicitly out of R4 scope; R3 evidence was accepted), frontend production build (no frontend production source changed), commit/push/deployment, and manual product acceptance.

## Resume / handoff

Coordinator should review the report and `verification/03-r4/`, then decide whether to close Issue 03. No further worker action is pending for this dispatch.
