# S5 evidence — FY1 actual FCFF bridge

All commands below ran in `D:/workshop/stock-valuation` on 2026-09-12 Asia/Shanghai. The coordinator state records the effective route as user-selected Codex / `gpt-5.6-luna` / max; no provider fallback or `resets_at` occurred.

## Baseline evidence

- `git status --short --branch`, `git log -5 --oneline --decorate`, `git diff --stat`, `git ls-files --others --exclude-standard`: exit 0. Baseline was `master...origin/master`, HEAD `7aaec80 (修复三个致命问题)`.
- Baseline artifacts: [`baseline-status.txt`](baseline-status.txt), [`baseline-untracked.txt`](baseline-untracked.txt), [`baseline.patch`](baseline.patch).
- The provider already contained S1/S2 forward-borrowing edits at task start; those edits were preserved. S5 added only the YTD extraction/marker path and its `get_cash_flow` integration in that file.

## S5 verification

Command:

```powershell
$env:DATA_PROVIDER='demo'
.\.venv\Scripts\python.exe -m pytest backend/tests/test_s5_fiscal_ytd_dcf.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m py_compile backend/app/engines/dcf.py backend/app/models/domain.py backend/app/providers/yfinance_provider.py
git diff --check -- backend/app/engines/dcf.py backend/app/models/domain.py backend/app/providers/yfinance_provider.py backend/tests/test_s5_fiscal_ytd_dcf.py .scratch/fatal-three/issues/S5-fy1-stub-proration-no-ytd.md
```

Observed result: `13 passed in 0.70s`; pytest exit `0`, compile exit `0`, diff-check exit `0`.

Static integration check output: `dcf_helper_imports=1 dcf_helper_calls=1 reverse_import_matches=0`.

The concentrated-CapEx fixture has CFO `600`, after-tax interest `24`, CapEx `230`, yielding actual FCFF YTD `394`; the DCF fixture uses full-year FCFF `1000` minus actual YTD `400` to produce FY1 stub `600`, while preserving explicit FY2 `1200`. The same suite verifies missing/gapped/stale/mismatched/FCFE/nonfinite inputs fail closed, cumulative YTD de-accumulation, leap-year FY end `2028-02-29` with `366` fiscal days, a 52/53-week-style provider anchor, strict live absence of YTD, demo-only compatibility labeling, and JSON wire metadata.

Normalizer seam smoke command (no network): the marker was passed through existing `Normalizer.normalize_provider_data` without editing `valuation_service.py`.

```text
normalizer_marker_status=available
normalizer_marker_value=394
normalizer_marker_end=2026-09-30
normalizer_exit=0
```

## Overlapping regression observations

- `pytest backend/tests/test_fatal_three_worker_c.py backend/tests/test_dcf.py -q -p no:cacheprovider`: exit `1`, `6 failed, 6 passed`. The failures are old DCF expectations for fallback-backed/absent-YTD availability after S5 strict live handling and S6 final governance; shared tests are outside S5 ownership and were not weakened.
- `pytest backend/tests/test_acceptance_rejection_fixes.py backend/tests/test_audit_issues_01_02_regression.py backend/tests/test_audit_issues_01_02_regression_r3.py -q -p no:cacheprovider`: exit `1`, `2 failed, 36 passed`. Both failures are S3 forward-P/E fallback expectations; no S5-owned test failed.
- `pytest backend/tests/test_s6_terminal_governance.py -q -p no:cacheprovider`: observed exit `1`, `10 passed, 4 failed` in the current S6-owned suite. The failures concern S6 helper-owned fixture/effective-metric wording and fallback expectations; S5 did not edit `terminal_governance.py` or its tests and notified the coordinator.

No live-provider network/API or frontend verification was run by S5; it is `NOT RUN` because the contract requires deterministic demo-isolated tests and live data is not to be fabricated.
