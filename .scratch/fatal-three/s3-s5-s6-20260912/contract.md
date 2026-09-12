# S3 / S5 / S6 execution contract

Date: 2026-09-12 Asia/Shanghai. Baseline master / 7aaec80, existing dirty and untracked F1/S1/S2 work is protected. See baseline-status.txt, baseline-untracked.txt, baseline.patch. Historical HANDOFF section 13 is closed historical delivery, not current verification.

User explicitly requests three Codex Luna Max workers; launch codex / gpt-5.6-luna / max. This is a user-selected execution route, not quota fallback. Actual launch evidence must be recorded; resets_at not applicable. No commit/push, cleanup, nested workers, invented prices/FX, missing-to-zero conversion, or unrelated changes.

## Shared decisions

System configured fallback parameters alone must not produce a normally available valuation. Preserve lineage and unavailable reasons. Explicit user overrides remain user scenarios, never relabelled company evidence. Demonstration fixtures may remain deterministic explicitly isolated examples, never a production bypass. Keep four models independent and existing API shape where possible.

FY1 stub uses aligned full-year forecast minus actual FCFF for exactly the elapsed fiscal interval. Quarterly data ending before valuation date does not cover the missing gap. Never relabel TTM, FCFE, mixed currency, unknown period or incomplete YTD as actual FCFF. Without trustworthy coverage, disable affected live DCF with a specific reason; no silent day-ratio fallback. Preserve full-year growth anchors and terminal timeline.

Terminal governance is a pure post-calculation helper: backend/app/engines/terminal_governance.py exposes apply_terminal_governance(model: ModelValuation, snapshot: CompanyFinancialSnapshot, assumptions: ValuationAssumptions) -> ModelValuation. S6 owns its implementation; S5 imports/calls it on the final successful run_dcf result. No helper-to-dcf import. S6 blocks effective fallback/unknown WACC or terminal growth, clears public price/scenario/sensitivity values when unavailable, retains explanatory metadata. Evaluate every scenario PVTV/EV; nonpositive/invalid denominator must not evade guard. Define 0.75 as explicit conservative policy attention threshold, not empirically universal law: high concentration with weak parameters is unavailable; adequately supported/user-explicit parameters still require structured concentration limitation and quality downgrade. No horizon extension or invented company assumptions.

## S3 task

- Goal: close fallback-parameter-governance issue end to end for multiples/yield and API delivery; DCF policy implemented by S6 helper called by S5.
- Scope/Ownership: backend/app/engines/forward_pe.py, ev_ebitda.py, fcf_yield.py; optional new parameter_governance.py; backend/app/services/valuation_service.py only if necessary; own test_s3_*.py, S3 issue, s3-report.md and s3 evidence here. Preserve preexisting fcf_yield edits. Do not edit dcf.py, domain.py, projections.py, provider, config.py, frontend, shared tests, S5/S6 files.
- Acceptance: fallback blocked even for direct engine calls; reliable selected parameters and explicit user overrides remain usable as applicable; independent models not disabled together; API JSON has no normal target price for rejected fallback and preserves provenance. Targeted pytest with demo environment and mocked live snapshots, code review, logs/exit codes. Existing test expectation updates proposed in report unless ownership approved.

## S5 task

- Goal: close FY1-stub-proration-no-ytd end to end including input acquisition/normalization and DCF cash-flow timing.
- Scope/Ownership: backend/app/engines/dcf.py, backend/app/models/domain.py, backend/app/providers/yfinance_provider.py; optional new services/fiscal_ytd.py; own test_s5_*.py, S5 issue, s5-report.md and evidence here. Optional additive snapshot fields authorized with defaults, no removal/API breaking change. Do not edit projections.py, valuation_service.py, other engines/config/frontend/shared tests or S3/S6 files. Preserve existing provider edits.
- Acceptance: concentrated CapEx/seasonal synthetic actuals prove full-year minus YTD; missing/incomplete/stale/mismatched/FCFE/nonfinite inputs do not become false actuals or zero; fiscal/leap boundaries and full-year anchors correct; source metadata reaches model/API JSON. Wire S6 helper only once its real file exists, do not author a stub or overwrite it. Targeted pytest and regression logs. Report any interface need to coordinator.

## S6 task

- Goal: close terminal-value-fallback-dependence with enforceable governance, structured diagnostics and tests.
- Scope/Ownership: new backend/app/engines/terminal_governance.py, own test_s6_*.py, S6 issue, s6-report.md/evidence here. Do not edit dcf.py or any other production file. S5 owns helper integration; tell coordinator when helper ready.
- Acceptance: test actual ModelValuation/DCFs with low/base/high shares, threshold boundaries, negative/zero EV, WACC/g effective provenance, explicit overrides and fallback. Rejected models expose no target/scenario/sensitivity prices but keep governance evidence. Test full run_dcf after S5 integration when available, otherwise label that pending rather than claiming closure.

## Completion

Each worker first reads git status/log/diff for owned paths and project constraints plus own issue, snapshots preexisting owned files, implements and verifies within ownership. Commands cwd D:/workshop/stock-valuation, use .venv/Scripts/python.exe and isolated DATA_PROVIDER=demo for tests. Reports include baseline, actual model/provider/time, ownership, changed files separated from prior work, commands/exit codes, PASS/FAIL/NOT RUN acceptance, financial provenance chain, risk/pending items. Update only own issue with evidence; final acceptance reserved for coordinator. Send exactly one valid worker_done with current task/dispatch, outcome, three sentences, files and report path; then stop. Escalate only substantive decision/ownership conflict. No routine permission questions.
