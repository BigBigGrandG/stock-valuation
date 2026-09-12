# Issue 03 R4 — final FCFE yield fallback disclosure

## Goal
Complete the original implementation-03-04.md constraint 03.1: FCFE yield without compatible credible benchmark retains explicit configured fallback AND risk warning. Main R3 acceptance is acceptance-03-04-r3.md; 04 is now closed, all major R3 corrections accepted.

## Scope / Ownership
One worker end-to-end: minimal backend FCFE yield warning, related API/export tests and evidence, issue 03 pending status, implementation-report-03-r4.md. No taxonomy or DCF rewrite; preserve all R1–R3 work and accepted04. No 05–08/commit/push/deployment/nested workers. Baseline master d0a7d62, current dirty/untracked work protected.

## Constraints / Evidence
fcf_yield.py currently marks yield_source=fallback, but warnings do not disclose lack of company/industry-specific yield benchmark. multiples.py only resolves/warns PE/EV. A PE/EV warning is not a substitute for a yield-specific one. Add truthful user-visible risk (no compatible company/industry FCFE-yield benchmark; configured system yield, specificity insufficient), propagated through existing API/UI/Markdown warning paths. Do not falsely warn user_override yield is system fallback. Do not alter formulas or fabricate benchmark; avoid duplicate warnings. Keep unavailable model semantics honest.

## Acceptance
Red then green focused tests proving configured fallback warns and user override does not get misleading fallback warning. Assert API and Markdown propagation (existing rendering may need no change). Full backend regression; relevant frontend export/browser checks, raw stdout/stderr command/cwd/exits in verification/03-r4/. No new six-ticker capture necessary: R3 evidence accepted, no financial numeric change intended. Compact report list modified files, test status, risks. Keep03 pending until coordinator closes. Reuse Codex Luna Max session per user instruction. Send one standard new-task/dispatch worker_done, then stop.
