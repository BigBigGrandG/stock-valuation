# S5（严重）：FY1 stub 仍使用均匀分布比例而非 YTD actual

状态：resolved / 主控验收通过（2026-09-12）

最终证据：[联合验收](../s3-s5-s6-20260912/final-acceptance.md)。主控全量后端 455 passed、退出码 0；仅显式 demo 允许无 YTD 合约时的兼容日比例，live 缺少可信实际覆盖则不可用。以下阶段记录保留为历史证据。

`backend/app/engines/dcf.py` now uses `FCFF_1,stub = FCFF_1,full − FCFF_actual_YTD` for an in-progress live fiscal year when aligned actual coverage reaches the valuation date. Live snapshots without a trustworthy YTD contract fail closed with no price/scenario output; demo/direct snapshots retain an explicitly labelled compatibility day-ratio path. The DCF result carries the bridge formula, full-year/YTD metric provenance, coverage dates, stub basis, and preserved fiscal timeline/growth anchor.

后续方案：有 YTD actual 时使用 `Full FY forecast − YTD actual`；否则保留 estimated 标记并考虑不可用阈值。

Evidence:

- [`s5-report.md`](../s3-s5-s6-20260912/s5-report.md) — implementation, ownership, acceptance matrix, and risks.
- [`s5-evidence.md`](../s3-s5-s6-20260912/s5-evidence.md) — commands, exit codes, and raw observed results.
- [`s5-rework-report.md`](../s3-s5-s6-20260912/s5-rework-report.md) — strict coverage/currency/basis rework, acceptance matrix, and final verification.
- [`s5-rework-owned-pytest.stdout.txt`](../s3-s5-s6-20260912/s5-rework-owned-pytest.stdout.txt) and [`s5-rework-owned-pytest.exit-code.txt`](../s3-s5-s6-20260912/s5-rework-owned-pytest.exit-code.txt) — 18 owned S5 tests, exit 0.
- [`s5-rework-s6-pytest.stdout.txt`](../s3-s5-s6-20260912/s5-rework-s6-pytest.stdout.txt) and [`s5-rework-s6-pytest.exit-code.txt`](../s3-s5-s6-20260912/s5-rework-s6-pytest.exit-code.txt) — 15 S6 tests, exit 0.
- [`s5-rework-full-backend.stdout.txt`](../s3-s5-s6-20260912/s5-rework-full-backend.stdout.txt) and [`s5-rework-full-backend.exit-code.txt`](../s3-s5-s6-20260912/s5-rework-full-backend.exit-code.txt) — 455 backend tests, exit 0.
- [`test_s5_fiscal_ytd_dcf.py`](../../../../backend/tests/test_s5_fiscal_ytd_dcf.py) — 18 focused tests covering seasonal/concentrated CapEx, explicit coverage, statement currency, mixed basis, varying tax, nonfinite inputs, and leap/non-calendar fiscal boundaries.
