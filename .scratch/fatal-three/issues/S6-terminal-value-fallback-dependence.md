# S6（严重）：终值占比高且与 fallback WACC/g 联合暴露

状态：resolved / 治理措施经主控验收通过（2026-09-12）

最终证据：[联合验收](../s3-s5-s6-20260912/final-acceptance.md)。主控全量后端 455 passed、退出码 0；终值集中风险被明确限制与隔离，并非消除 DCF 固有模型风险。以下阶段记录保留为历史证据。

最新 live 报告显示 DCF Base TV 占比约 0.77（各情景/标的约 0.74–0.82），同时 WACC lineage 为 fallback。故多数价值由未公司化的终值参数决定；现有 sensitivity warning 不能消除该依赖。

后续方案：强化公司化 WACC/terminal-growth 来源、扩大显式预测期或在终值占比/参数质量超阈值时明确限制或 unavailable。

## S6 worker implementation evidence (2026-09-12)

状态：implementation complete; final integration pending S5.

- Added pure helper [`backend/app/engines/terminal_governance.py`](../../backend/app/engines/terminal_governance.py) with the required `apply_terminal_governance(model, snapshot, assumptions)` signature. It has no `dcf.py` import.
- Configured fallback or unknown effective WACC/terminal-growth lineage fails closed. Public `low/base/high`, `dcf_scenarios`, and `sensitivity_matrix` values are cleared while structured diagnostics remain under `assumptions["terminal_governance"]`.
- Every scenario is evaluated for finite positive PVTV/EV and WACC > terminal growth. Non-positive EV denominators fail closed. The inclusive `PVTV/EV >= 0.75` boundary is a documented conservative policy-attention threshold; supported/user-explicit high concentration remains available as `limited` with a one-level data-quality downgrade.
- Added [`backend/tests/test_s6_terminal_governance.py`](../../backend/tests/test_s6_terminal_governance.py), 9 tests passing in demo isolation. DCF regression `backend/tests/test_dcf.py` also passed 9 tests; compileall and `git diff --check` exited 0.
- Durable details: [`s6-report.md`](../s3-s5-s6-20260912/s6-report.md) and [`s6-evidence.md`](../s3-s5-s6-20260912/s6-evidence.md). Full `run_dcf` integration/API validation is `NOT RUN / PENDING S5`, which owns `dcf.py`.

## S6 continuation evidence (task_dc94fd6c9d4e, 2026-09-12)

状态：continuation implementation complete; integrated direct/API acceptance verified; shared legacy DCF expectations remain coordinator review items.

- Hardened `_provenance_descriptor`: any source label containing `fallback` is rejected before `derived`/`actual`/`fixture` acceptance, with explicit `user_override` as the sole exception.
- Fixture WACC/terminal-growth lineage is valid only for `snapshot.is_demo=True`; live fixture lineage becomes unknown and fails closed.
- Effective metric values are validated against each scenario's WACC and terminal growth. Mismatched, missing, or non-finite claims cannot justify supported provenance and public prices remain withheld with structured `invalid_parameters` diagnostics.
- Added continuation tests for all three boundaries plus direct integrated `run_dcf` and API serialization; owned suite passes 15/15. Raw stdout/exit artifacts are [`s6-continuation-owned.stdout.txt`](../s3-s5-s6-20260912/s6-continuation-owned.stdout.txt) and [`s6-continuation-owned.exit-code.txt`](../s3-s5-s6-20260912/s6-continuation-owned.exit-code.txt).
- Shared `test_dcf.py` was not edited; it exits 1 on three old assertions expecting fallback-backed DCF availability after S5 integration. Raw failure evidence is [`s6-continuation-dcf.stdout.txt`](../s3-s5-s6-20260912/s6-continuation-dcf.stdout.txt) with exit artifact [`s6-continuation-dcf.exit-code.txt`](../s3-s5-s6-20260912/s6-continuation-dcf.exit-code.txt).
