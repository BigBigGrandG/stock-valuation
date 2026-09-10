# Independent Verification & Acceptance Report: P0/P1 Valuation Integrity

**Audit Date**: 2026-09-10  
**Status**: **ACCEPTANCE FAILED (REJECTED FOR REMEDIATION)**  
**Auditor**: Independent Coordinator-Dispatched Verification Worker  
**Scope**: High-risk financial numerical integrity, pipeline integration, and E2E contract assertions across all 7 items from `.scratch/valuation-integrity/spec.md`.

---

## 1. Executive Acceptance Matrix

| Item | Focus Area | Status | Key Substantive Defect Summary |
|---|---|:---:|---|
| **1 [P0-B]** | Quarter Aggregation & Balance Sheet | **FAIL** | False positive YTD de-accumulation on growing discrete quarters (60% revenue undercounting); missing quarterly EBITDA returns TTM with `ebitda=None` instead of falling back to annual; duplicate date columns crash consecutive check. |
| **2 [P0-A]** | Share Capital Reconciliation | **FAIL** | `CONFLICT_DEGRADED` is an unconsumed tag (DCF/EV/FCF engines blindly divide by corrupt shares without warning); fallback fabricates shares from `marketCap / price`; period hardcoded as `"point_in_time"`. |
| **3 [P0-C]** | Calendar-Anchored DCF Projection & ACT/365 | **FAIL** | Exponential ACT/365 math matches oracle, but historical base to valuation date lacks compound growth horizon conversion (only 1.0y growth over 1.69y elapsed); fiscal-year forward FCFF is blindly relabeled as anniversary window. |
| **4 [P1-D]** | NTM Consensus Horizon Selection | **FAIL** | Forward revenue estimates (`revenue_estimate_1y/2y`) do not exist on `ForwardEstimatesData` or `CompanyFinancialSnapshot` (NTM revenue blending is non-functional); expired FY gets 100% weight (`w0=1.0`). |
| **5 [P1-E]** | Configurable Growth Floor & Cap | **FAIL** | Request-level `growth_cap` override (0.80 vs 0.40) produces 0% change in valuation because snapshot growth metrics are `None`; `forward_fcfe_1y` is never re-clamped; `yfinance_provider` hardcodes 0.40 cap during ingestion. |
| **6 [P1-F]** | Multi-Model Weights & Export Schema | **FAIL** | Sparse weights & 40% cashflow cap math pass, but `ValuationResponse` omits `statement_basis`, `annual_fallback`, and `shares_basis`, rendering UI badges misleading and export lines dead code. |
| **7 [P1-G]** | Browser Evidence & Export Assertions | **FAIL** | No automated E2E assertion scripts exist in repo (only screenshots); actual Markdown export verified to completely lack statement basis and share capital basis. |

---

## 2. Top 5 Blocking Findings

### Finding 1: Request-scoped `growth_cap` override has 0% effect on valuations due to missing snapshot growth metrics and bypassed FCFE clamping
- **Path:Line**: `backend/app/services/projections.py:163-225`, `backend/app/providers/yfinance_provider.py:733-736`
- **Reproduction**: `.venv\Scripts\python .scratch/valuation-integrity/independent/check_item5.py`
- **Actual vs Expected**: Setting `growth_cap=0.80` vs `0.40` via `ValuationOverrideRequest` results in identical DCF price ($292.28), EV/EBITDA price ($567.57), and FCF Yield price ($362.75). In production/fixture snapshots, `ebitda_growth` and `revenue_growth` are `None`, so `derive_request_projections` skips recalculating forward EBITDA and FCFF. Furthermore, `forward_fcfe_1y` is never re-clamped.
- **User Impact**: User-configured growth cap overrides in Advanced Settings are completely ignored by the engine.
- **Minimal Fix**: Preserve un-clamped raw growth rates on `CompanyFinancialSnapshot`; re-clamp `forward_fcfe_1y` in `derive_request_projections`; derive forward flows whenever base metrics and growth proxies exist.

### Finding 2: `detect_and_handle_ytd` falsely de-accumulates discrete growing quarterly revenue without metadata, causing 60% revenue undercounting
- **Path:Line**: `backend/app/providers/statement_aggregator.py:85-106`
- **Reproduction**: `.venv\Scripts\python .scratch/valuation-integrity/independent/check_item1.py`
- **Actual vs Expected**: Discrete quarters with revenues `[100, 200, 300, 400]` (sum 1000) are classified as cumulative YTD and de-accumulated to `[100, 100, 100, 100]`, yielding a sum of 400 (60% loss). The function relies solely on ratio checks `[1.5-2.5, 2.4-3.6, 3.3-4.8]` without checking filing period metadata or fiscal year start.
- **User Impact**: High-growth companies have their true revenues severely cut, corrupting EV/EBITDA, P/E, and DCF.
- **Minimal Fix**: Restrict de-accumulation to verified cumulative filing metadata (e.g. SEC 10-Q 3mo vs 6mo/9mo periods); if metadata cannot confirm YTD, do not guess by amount.

### Finding 3: `CONFLICT_DEGRADED` is an unconsumed status; valuation engines blindly divide equity value by conflicted share denominators
- **Path:Line**: `backend/app/providers/share_reconciliation.py:279-295`, `backend/app/engines/dcf.py:598`, `backend/app/engines/ev_ebitda.py`, `backend/app/engines/fcf_yield.py`
- **Reproduction**: `.venv\Scripts\python .scratch/valuation-integrity/independent/check_item2.py`
- **Actual vs Expected**: Under severe share discrepancies (>15%-50%), `shares_basis="CONFLICT_DEGRADED"` is recorded, but DCF, EV/EBITDA, and FCF Yield return `available=True` and output authoritative target prices without any warning or degradation. In addition, line 287 fabricates shares from `marketCap / price` when reported shares are missing.
- **User Impact**: Users are shown standard target prices calculated with known erroneous share counts without warning.
- **Minimal Fix**: In `dcf.py`, `ev_ebitda.py`, and `fcf_yield.py`, check `snapshot.shares_basis == "CONFLICT_DEGRADED"` and downgrade `data_quality=LOW` with explicit warning, or mark model unavailable; eliminate `cap_price_shares` fabrication fallback.

### Finding 4: Forward revenue estimate fields are completely absent from provider and snapshot, making NTM revenue blending a non-functional facade
- **Path:Line**: `backend/app/providers/base.py`, `backend/app/providers/yfinance_provider.py:1005-1050`, `backend/app/models/domain.py:120-160`, `backend/app/services/projections.py:138-139`
- **Reproduction**: `.venv\Scripts\python .scratch/valuation-integrity/independent/check_item4.py`
- **Actual vs Expected**: `CompanyFinancialSnapshot` lacks `revenue_estimate_1y` and `revenue_estimate_2y`. `ForwardEstimatesData` has zero revenue fields. `projections.py:138-139` accesses non-existent attributes, falling back to `revenue_ttm` and `None`.
- **User Impact**: Analyst consensus forward revenue is never passed or blended; forward revenue calculations are a dead facade.
- **Minimal Fix**: Add `forward_revenue_1y` and `forward_revenue_2y` to `ForwardEstimatesData` and `CompanyFinancialSnapshot`; populate them in `yfinance_provider.py` from `revenue_estimate` avg; update `valuation_service.py` to forward them into `req_snapshot`.

### Finding 5: `ValuationResponse` omits `shares_basis`, `statement_basis`, and `annual_fallback`, breaking UI badges and export provenance
- **Path:Line**: `backend/app/models/domain.py:411-426`, `backend/app/services/valuation_service.py:910-923`, `frontend/lib/exportMarkdown.ts:319-325`, `frontend/app/valuation/[ticker]/page.tsx:769-780`
- **Reproduction**: `npx --prefix frontend jiti .scratch/valuation-integrity/independent/check_item7_export.ts`
- **Actual vs Expected**: Exported Markdown audit reports `Has '财务报表统计口径': false` and `Has '总股本口径': false`. In the frontend UI, `data.annual_fallback` is `undefined`, so it always displays "连续 4 季度 (TTM)" even when annual fallback occurred.
- **User Impact**: Users cannot see if annual fallback occurred or what share basis was used; Markdown exports omit required financial provenance.
- **Minimal Fix**: Add `shares_basis`, `shares_reconciliation`, `statement_basis`, and `annual_fallback` to `ValuationResponse` and populate them in `assemble_response()`.

---

## 3. Secondary Deficiencies Observed

1. **Incomplete quarterly EBITDA rollup**: In `aggregate_ttm_income()`, if EBITDA is missing in 1 of 4 quarters, it returns `statement_basis="TTM"` with `ebitda=None` instead of falling back to the annual statement (`statement_aggregator.py:447-468`).
2. **Expired fiscal year weight clamping**: In `calculate_ntm_weights()`, when `next_fy_end <= as_of`, it sets `w0=1.0, w1=0.0`, assigning 100% weight to an already-expired fiscal year (`projections.py:53-56`).
3. **DCF historical base growth horizon**: In `dcf.py:739-750`, historical annual FCFF (e.g. 2025-12-31) is grown by exactly 1.0 year of growth rather than compounding over the 1.69 years elapsed to the Year 1 window end (2027-09-10).
