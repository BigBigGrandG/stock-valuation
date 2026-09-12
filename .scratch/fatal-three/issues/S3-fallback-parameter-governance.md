# S3（严重）：固定 fallback 参数仍直接产出正常价格

状态：resolved / 主控验收通过（2026-09-12）

最终证据：[联合验收](../s3-s5-s6-20260912/final-acceptance.md)。主控全量后端 455 passed、退出码 0；以下阶段记录保留为历史证据。

`backend/app/config.py:14-26` 定义全市场固定 P/E、EV/EBITDA、FCF yield、WACC/terminal growth。live 报告出现 `selection_layer: system` 与 `WACC lineage: fallback`，模型仍返回价格。

后续方案：保留 lineage/warning，明确标注 reference scenario；无足够公司/行业依据时考虑 unavailable 或单独隔离参考情景。

## 2026-09-12 S3 worker evidence

- `forward_pe.py`、`ev_ebitda.py` 和 `fcf_yield.py` now fail closed when the
  effective parameter source is `configured_fallback`; rejected models expose
  no low/base/high prices while retaining source label, source type, selected
  layer, governance marker, warnings, and provenance-rich input/assumption
  metrics.
- Source-backed historical/company or industry selections remain available
  independently. Explicit request/user scenarios remain available and are
  serialized as `user_override`; they are never relabelled as company evidence.
- Shared policy helper: `backend/app/engines/parameter_governance.py`.
- Regression/API coverage: `backend/tests/test_s3_parameter_governance.py`.
  Targeted run after concurrent S5/S6 changes: `13 passed, 2 warnings` in
  `.scratch/fatal-three/s3-s5-s6-20260912/s3-targeted-pytest-post-parallel.log`.
- Full suite was run in isolated `DATA_PROVIDER=demo`; it reported `391 passed,
  34 failed`. The failures are legacy expectations that configured P/E,
  EV/EBITDA, FCFE-yield, or DCF fallback parameters still produce prices, plus
  concurrent S5/S6 DCF integration expectations; no S3-owned targeted test
  failed. Full output: `.scratch/fatal-three/s3-s5-s6-20260912/s3-full-pytest-final.log`.

## 2026-09-12 integration follow-up

The shared parameter gate now follows the S6 fail-closed provenance rules:

- `model_fields_set` is no longer used to infer that an unlabelled
  `ScenarioValues` field is a user override. Direct callers must deliberately
  set `SourceType.USER_OVERRIDE` (or arrive through `apply_overrides`).
- A fallback source label cannot be rescued by declaring `derived`, `industry`,
  or another non-fallback source type. Unknown source tokens are unavailable.
- `SourceType.FIXTURE` is accepted only when `snapshot.is_demo` is explicitly
  true; production snapshots with fixture assumptions are unavailable.
- The demo flag is passed into all three S3 engines, and rejected results keep
  source label/type, input/assumption metrics, warning, and unavailable reason
  while clearing all prices.

The original 33 integration failures in
`.scratch/fatal-three/s3-s5-s6-20260912/coordinator-full-pytest.log` are
classified individually in `integration-report.md`. Each is either a
policy-aware expectation/fixture adjustment (deliberate user assumptions,
explicit demo markers, or aligned FY1 actual-YTD metadata) or an assertion
that the configured fallback is unavailable; no production formula or source
lineage was weakened.
No tests were deleted, skipped, xfailed, or weakened.

Evidence from this follow-up:

- `integration-targeted-pytest.log` / `.exit.txt`: 281 passed, exit 0 (current
  pre-S5-rework snapshot).
- `integration-full-pytest.log` / `.exit.txt`: 450 passed, exit 0 (current
  pre-S5-rework snapshot).
- `integration-owned-diff-review.txt` / `.exit.txt`: owned diff review and
  `git diff --check`, exit 0.

Coordinator follow-up notes that S5 is reworking YTD date/currency acquisition
and cumulative cash-flow normalization; coordinator must rerun the integrated
suite after that worker's changes. This does not change the S3 gate or its
owned regression evidence.
