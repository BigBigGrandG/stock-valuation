# Final financial acceptance findings

Bounded read-only review of the current backend engine/model/override code, after the
coordinator's fiscal-year fix.  No backend/frontend implementation files were edited,
and no pytest or racing test suite was run.

Diagnostic command used:

```powershell
.venv\Scripts\python.exe .scratch\valuation-mvp\review-final\diagnostics.py
```

The diagnostic is an independent arithmetic script under this review directory; the
inline repros below use the same Decimal inputs and current source.

## Findings

### F1 — HIGH: supplied net debt can make EV and DCF disagree

`CompanyFinancialSnapshot` synchronizes and `net_debt_metric()` returns a supplied
`net_debt` without checking `total_debt - cash` (`backend/app/models/domain.py:167-180,
425-440`). EV/EBITDA consumes that supplied metric, while each DCF scenario recomputes
`total_debt - cash` (`backend/app/engines/ev_ebitda.py:108-119,
backend/app/engines/dcf.py:307-311`). This also makes positive-equity gating inconsistent.

Reproducible inputs (all values are Decimal): quote=100, shares=10,000, cash=100,000,
debt=200,000, supplied net_debt=100,000,000, forward EBITDA=1,000,000, forward
FCFF1=1,000,000, forward FCFF2=1,100,000, default assumptions:

```text
identity debt-cash = 100000
run_dcf(...).available = True; DCF base equity = 17822077.92
run_ev_ebitda(...).available = False; low equity = -82000000.00
```

With supplied net_debt=999,999 instead, DCF scenario `net_debt` is 100,000 but its
top-level input metric is 999,999, while EV uses 999,999. Reject a mismatched supplied
metric (or always derive net debt and retain any provider value as a separate raw
metric), then use that one value for every model and the positive-equity check.

### F2 — MEDIUM: sparse base overrides escape effective range bounds

Nested field validators cap only values explicitly present in the request, while
`to_override_dict()` derives missing bounds and `apply_overrides()` checks ordering but
not the effective range (`backend/app/models/overrides.py:141-159,
backend/app/services/valuation_service.py:432-483`). The public nested request therefore
accepts effective values outside the documented limits:

```text
{"forward_pe":{"base":200}}
  -> low=180.0, base=200, high=220; apply_overrides ACCEPTED
{"ev_ebitda":{"base":200}}
  -> low=180.0, base=200, high=220; apply_overrides ACCEPTED
{"fcf_yield":{"base":0.5}}
  -> low=0.55, base=0.5, high=0.45; apply_overrides ACCEPTED
```

The intended limits are P/E and EV/EBITDA <=200 and FCF yield <=0.5. Validate the
expanded low/base/high tuple after sparse derivation (or reject a base whose derived
bound would exceed the limit) before building effective assumptions.

### F3 — MEDIUM: DCF growth fallback ignores provenance roles

After FCFF-forward/TTM paths, `_growth_source()` selects the first non-null
`revenue_growth`, `ebitda_growth`, or `eps_growth` field, regardless of its
`source_type`, before considering `fcff_growth` (`backend/app/engines/dcf.py:135-157`).
That treats an actual/historical operational metric as an analyst proxy and can hide a
historical FCFF growth metric, contrary to the required analyst-operational-then-
historical ordering.

Reproducible inputs: positive FCFF1=1,000,000; FCFF2 absent; revenue_growth=0.40 with
`source_type=ACTUAL` and source `historical revenue`; fcff_growth=0.10 with
`source_type=ACTUAL` and source `historical FCFF`; all other growth fields absent.

```text
growth_source = derived from revenue growth (capped)
growth_rates = [0.25, 0.30, 0.35]
```

Partition candidates by explicit lineage/source type (analyst forward operational
estimate first, historical FCFF/operating growth next) or add separate fields that
cannot be confused, while retaining FCFE growth as ineligible for DCF.

### F4 — MEDIUM: DCF effective growth caps are not fully represented in provenance

Each `DCFScenario` exposes an effective `growth_rate` but receives the same raw
`growth_metric` object (`backend/app/engines/dcf.py:331-340`); the assumption map merely
clones that metric with a new value (`backend/app/engines/dcf.py:584-585`). For FCFF1=
1,000,000 and FCFF2=1,400,000, raw growth is 0.40 but the effective rates are capped to
0.25/0.30/0.35; each scenario's `growth_metric.value` remains 0.40. The normal 10%
case likewise reports rates 0.085/0.10/0.115 while each scenario metric value is 0.10.

Expose raw and effective growth separately (or produce one metric per scenario), and
include the selected cap/floor and lineage in source/notes so a consumer can explain
why the forecast differs from the source rate. The current `growth_metric` alone does
not satisfy “explicit cap rules and is_estimated exposed.”

### F5 — MEDIUM: historical multiple metrics overwrite provider provenance

When a historical P/E or EV/EBITDA metric is selected, both engines force its effective
assumption `source_type` to ACTUAL and build a new metric with period `valuation
assumption`, `as_of` taken from forward EPS/EBITDA, and `is_estimated=True`
(`backend/app/engines/forward_pe.py:101-131`,
`backend/app/engines/ev_ebitda.py:92-145`). This discards the historical metric's own
source type/date and labels generated +/-10% ranges as if they were the historical
observation.

Reproducible input: historical multiple value=20, period=`5Y median`, source=`history
vendor`, source_type=ANALYST_ESTIMATE, as_of=2024-12-31, is_estimated=True; forward EPS
and EBITDA as_of=2025-01-15. Current output for both base assumption metrics is:

```text
source_type = actual
period = valuation assumption
as_of = 2025-01-15
is_estimated = True
```

Preserve the selected historical metric's source/source_type/as_of/period for the base
observation, and mark generated ranges DERIVED with explicit lineage and the historical
date. The demo top-level fixture source-type branch is now correct; this non-demo
lineage loss remains.

### F6 — MEDIUM: DCF engine warns about terminal growth above the hard cap but still values it

The public override model rejects terminal growth above 0.05, but `run_dcf()` only adds
a warning and continues when directly supplied assumptions exceed that cap
(`backend/app/engines/dcf.py:435-440`). Repro: WACC=(0.12,0.11,0.10), terminal growth
=(0.06,0.07,0.08), FCFF1=1,000,000, FCFF2=1,100,000, quote=100, shares=1,000, cash=
debt=0.

```text
available = True
prices = [18.32, 27.67, 55.75]
warnings = terminal_growth (0.06/0.07/0.08) exceeds configured max (0.05)
```

Reject/mark the DCF unavailable when effective terminal growth exceeds the configured
maximum, including assumptions constructed internally, rather than producing a
materially inflated valuation with a warning only.

### F7 — LOW: exposed composite normalized weights do not sum to one

`run_composite()` rounds each normalized weight independently to four places, while
fair values use the unrounded denominator (`backend/app/engines/composite.py:67-81`).
With three complete models and raw weights 1,1,1 (DCF weight 0), the output is

```text
weights_used = {forward_pe: 0.3333, ev_ebitda: 0.3333, fcf_yield: 0.3333}
sum(weights_used.values()) = 0.9999
```

Reconcile the last displayed bucket to `1 - sum(previous)` or expose unrounded
normalized weights; otherwise the UI's stated weighting formula and displayed weights
are inconsistent by one basis point.

## Checks that passed

- FCFE and FCFF are separate in the current snapshot/engine paths; FCF-yield does not
  substitute FCFF and DCF does not substitute FCFE.
- DCF uses five explicit annual periods and the supplied FCFF1/FCFF2 when present; the
  previously skipped-fiscal-year issue is fixed in the current source and the live
  arithmetic diagnostic passes.
- Declining growth values remain bear/base/bull ordered in the exercised case, caps and
  floor are deterministic, and WACC > terminal growth is enforced for normal/public
  override paths.
- Positive-equity failures are retained as unavailable per model, partial composites
  exclude incomplete models and renormalize the remaining raw weights, and centralized
  classification boundaries produce the specified exact-boundary classes.
- Nested override strings/bools/NaN and unknown fields are rejected; terminal-growth-
  only overrides retain WACC provenance and effective WACC > g is rejected.

