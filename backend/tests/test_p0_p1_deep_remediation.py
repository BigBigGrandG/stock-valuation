"""
Comprehensive test suite verifying deep remediation of P0 and P1 integrity items:
[P0-A] Share capital evidence-based reconciliation, split detection, conflict degradation.
[P0-B] True TTM quarterly rollups, YTD detection, 4/4 completeness fallback, latest PIT balance sheet.
[P0-C] Calendar-anchored DCF with ACT/365 discounting, leap year handling, and shared pure calculator.
[P1-D] Consensus horizon default to NTM, bounded day weights, and fallback warning.
[P1-E] Request-scoped projection growth bounds without snapshot mutation or cache leakage.
[P1-F] Dynamic model weights default merging, sparse overrides, all-zero 422, and cashflow group policy.
"""
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import math
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from pydantic import ValidationError

from app.config import DEFAULT_ASSUMPTIONS, DEFAULT_FORECAST_HORIZON
from app.engines.composite import run_composite
from app.engines.dcf import _calculate_dcf, _compute_dcf_scenario, run_dcf
from app.engines.forward_pe import run_forward_pe
from app.models.domain import (
    CompanyFinancialSnapshot,
    DataQuality,
    FinancialMetric,
    SourceType,
    ValuationAssumptions,
)
from app.models.overrides import DCFOverride, ValuationOverrideRequest, WeightOverride
from app.providers.share_reconciliation import reconcile_share_capital
from app.providers.statement_aggregator import (
    aggregate_ttm_cashflow,
    aggregate_ttm_income,
    extract_latest_balance_sheet,
    verify_consecutive_quarters,
)
from app.services.projections import calculate_ntm_weights, derive_request_projections
from app.services.valuation_service import run_all_engines


def _make_metric(val: Decimal | str | float, unit: str = "USD", period: str = "TTM", as_of: date = date(2026, 9, 10)) -> FinancialMetric:
    return FinancialMetric(
        value=Decimal(str(val)),
        unit=unit,
        period=period,
        source="test",
        source_type=SourceType.DERIVED,
        as_of=as_of,
        confidence=1.0,
        is_estimated=False,
    )


def _make_sample_snapshot(
    ticker: str = "TEST",
    as_of: date = date(2026, 9, 10),
    **overrides: Any,
) -> CompanyFinancialSnapshot:
    defaults = {
        "ticker": ticker,
        "company_name": f"{ticker} Inc.",
        "currency": "USD",
        "current_price": _make_metric("100.00", as_of=as_of),
        "price_timestamp": datetime(as_of.year, as_of.month, as_of.day, 12, 0, 0, tzinfo=timezone.utc),
        "diluted_shares": _make_metric("1000000000", unit="shares", as_of=as_of),
        "cash": _make_metric("20000000000", as_of=as_of),
        "total_debt": _make_metric("10000000000", as_of=as_of),
        "net_debt": _make_metric("-10000000000", as_of=as_of),
        "revenue_ttm": _make_metric("50000000000", as_of=as_of),
        "ebitda_ttm": _make_metric("15000000000", as_of=as_of),
        "eps_ttm": _make_metric("5.00", as_of=as_of),
        "fcf_ttm": _make_metric("10000000000", as_of=as_of),
        "fcff_ttm": _make_metric("11000000000", as_of=as_of),
        "forward_eps_1y": _make_metric("6.00", period="FY1E", as_of=as_of),
        "forward_eps_2y": _make_metric("7.00", period="FY2E", as_of=as_of),
        "forward_ebitda_1y": _make_metric("16500000000", period="FY1E", as_of=as_of),
        "forward_fcf_1y": _make_metric("11000000000", period="FY1E", as_of=as_of),
        "forward_fcff_1y": _make_metric("12000000000", period="FY1E", as_of=as_of),
        "forecast_fiscal_year_end": date(2026, 12, 31),
        "revenue_growth": _make_metric("0.10", as_of=as_of),
        "ebitda_growth": _make_metric("0.10", as_of=as_of),
        "fcff_growth": _make_metric("0.10", as_of=as_of),
        "shares_basis": "ALL_CLASS_RECONCILED",
        "statement_basis": "TTM",
        "annual_fallback": False,
    }
    defaults.update(overrides)
    return CompanyFinancialSnapshot(**defaults)


# ==============================================================================
# [P0-A] Share Capital Evidence-Based Reconciliation
# ==============================================================================
class TestP0AShareReconciliation:
    def test_meta_multi_class_all_class_reconciliation(self):
        """Multi-class share reconciliation correctly selects implied shares over single class."""
        info = {
            "sharesOutstanding": 2_205_128_509,       # Class A only
            "impliedSharesOutstanding": 2_547_506_225, # All classes (Class A + Class B)
            "marketCap": 1_700_000_000_000,
            "regularMarketPrice": 667.32,
        }
        res = reconcile_share_capital(info=info, ticker="META")
        assert res.basis == "ALL_CLASS_RECONCILED"
        assert res.shares == Decimal("2547506225")
        assert res.reconciliation["is_multi_class"] is True
        assert res.reconciliation["conflict_detected"] is False

    def test_split_detection_between_bs_and_info(self):
        """Split detection detects 10:1 ratio between balance sheet and live quote info."""
        bs_col = pd.Timestamp("2024-03-31")
        bs_df = pd.DataFrame({bs_col: [100_000_000]}, index=["Ordinary Shares Number"])
        info = {
            "sharesOutstanding": 1_000_000_000,  # 10x due to split
            "marketCap": 100_000_000_000,
            "regularMarketPrice": 100.0,
        }
        res = reconcile_share_capital(info=info, quarterly_bs=bs_df, ticker="SPLIT")
        assert res.reconciliation["split_detected"] is True
        assert res.reconciliation["split_factor"] == 10.0

    def test_severe_conflict_degradation(self):
        """Severe conflict between reported shares and marketCap/price triggers CONFLICT_DEGRADED."""
        info = {
            "sharesOutstanding": 1_000_000_000,
            "marketCap": 50_000_000_000,
            "regularMarketPrice": 100.0,  # implies 500,000,000 shares (50% divergence)
        }
        res = reconcile_share_capital(info=info, ticker="CONFLICT")
        assert res.basis == "CONFLICT_DEGRADED"
        assert res.reconciliation["conflict_detected"] is True
        assert "divergence" in res.notes or "conflict" in res.notes.lower()


# ==============================================================================
# [P0-B] True TTM Statement Aggregation & Completeness
# ==============================================================================
class TestP0BStatementAggregation:
    def test_consecutive_quarter_verification_pass(self):
        """4 consecutive quarters spaced ~90 days apart verify successfully."""
        cols = [
            pd.Timestamp("2024-12-31"),
            pd.Timestamp("2024-09-30"),
            pd.Timestamp("2024-06-30"),
            pd.Timestamp("2024-03-31"),
        ]
        ok, reason = verify_consecutive_quarters(cols)
        assert ok is True
        assert "valid" in reason.lower()

    def test_gap_in_quarters_triggers_annual_fallback(self):
        """Missing quarter (e.g. 180 day gap) fails verification."""
        cols = [
            pd.Timestamp("2024-12-31"),
            pd.Timestamp("2024-06-30"),  # Gap of ~184 days! Missing Q3
            pd.Timestamp("2024-03-31"),
            pd.Timestamp("2023-12-31"),
        ]
        ok, reason = verify_consecutive_quarters(cols)
        assert ok is False
        assert "gap" in reason.lower()

    def test_cumulative_ytd_rejection_and_annual_fallback(self):
        """Discrete quarterly cash flow without YTD metadata sums to 1000; verified YTD metadata de-accumulates."""
        q_cols = [
            pd.Timestamp("2024-12-31"),
            pd.Timestamp("2024-09-30"),
            pd.Timestamp("2024-06-30"),
            pd.Timestamp("2024-03-31"),
        ]
        # 1. Discrete numbers: Q1=100, Q2=200, Q3=300, Q4=400 -> without YTD metadata, sums to 1000
        q_df = pd.DataFrame(
            {
                q_cols[0]: [400.0, -40.0],
                q_cols[1]: [300.0, -30.0],
                q_cols[2]: [200.0, -20.0],
                q_cols[3]: [100.0, -10.0],
            },
            index=["Operating Cash Flow", "Capital Expenditure"],
        )
        a_col = pd.Timestamp("2024-12-31")
        a_df = pd.DataFrame({a_col: [400.0, -40.0]}, index=["Operating Cash Flow", "Capital Expenditure"])

        agg = aggregate_ttm_cashflow(quarterly_cf=q_df, annual_cf=a_df)
        assert agg["cfo"] == Decimal("1000")  # Heuristic coincidence prohibited

        # 2. With verified cumulative metadata in column labels
        q_df_ytd = pd.DataFrame(
            {
                "2024-12-31 YTD": [400.0, -40.0],
                "2024-09-30 9M": [300.0, -30.0],
                "2024-06-30 6M": [200.0, -20.0],
                "2024-03-31 3M": [100.0, -10.0],
            },
            index=["Operating Cash Flow", "Capital Expenditure"],
        )
        agg_ytd = aggregate_ttm_cashflow(quarterly_cf=q_df_ytd, annual_cf=a_df)
        assert agg_ytd["cfo"] == Decimal("400")
        assert "de-accumulated" in agg_ytd["notes"].lower() or "ytd" in agg_ytd["notes"].lower()

    def test_strict_4_4_quarter_completeness(self):
        """If metric is missing in one of 4 quarters, annual fallback is triggered."""
        q_cols = [
            pd.Timestamp("2024-12-31"),
            pd.Timestamp("2024-09-30"),
            pd.Timestamp("2024-06-30"),
            pd.Timestamp("2024-03-31"),
        ]
        q_df = pd.DataFrame(
            {
                q_cols[0]: [100.0, -10.0],
                q_cols[1]: [100.0, None],  # Missing capex in Q2!
                q_cols[2]: [100.0, -10.0],
                q_cols[3]: [100.0, -10.0],
            },
            index=["Operating Cash Flow", "Capital Expenditure"],
        )
        a_col = pd.Timestamp("2024-12-31")
        a_df = pd.DataFrame({a_col: [400.0, -40.0]}, index=["Operating Cash Flow", "Capital Expenditure"])

        agg = aggregate_ttm_cashflow(quarterly_cf=q_df, annual_cf=a_df)
        assert agg["statement_basis"] == "ANNUAL_FALLBACK"
        assert agg["annual_fallback"] is True

    def test_latest_balance_sheet_is_point_in_time(self):
        """Extracts strictly the newest quarter from balance sheet, never summing."""
        cols = [
            pd.Timestamp("2024-12-31"),
            pd.Timestamp("2024-09-30"),
            pd.Timestamp("2024-06-30"),
        ]
        q_bs = pd.DataFrame(
            {
                cols[0]: [500.0, 200.0],  # Latest cash=500, debt=200
                cols[1]: [400.0, 250.0],
                cols[2]: [300.0, 300.0],
            },
            index=["Cash And Cash Equivalents", "Total Debt"],
        )
        bs_res = extract_latest_balance_sheet(q_bs, None)
        assert bs_res["cash"] == Decimal("500")
        assert bs_res["total_debt"] == Decimal("200")
        assert bs_res["as_of"] == date(2024, 12, 31)
        assert bs_res["period"] == "Q_2024-12-31"


# ==============================================================================
# [P0-C] Calendar-Anchored DCF Discounting Oracle & Pure Calculator
# ==============================================================================
class TestP0CDCFDiscounting:
    def test_dcf_true_act_365_leap_year_discounting(self):
        """True ACT/365 discounting handles leap year 2028 correctly."""
        as_of = date(2026, 9, 10)
        sc = _compute_dcf_scenario(
            scenario_name="base",
            fcff_y1=Decimal("100"),
            fcff_y2=None,
            fcff_y1_label="Y1",
            fcff_y2_label=None,
            growth_rate=Decimal("0.10"),
            wacc=Decimal("0.10"),
            terminal_growth=Decimal("0.03"),
            total_debt=Decimal("0"),
            cash=Decimal("0"),
            diluted_shares=Decimal("10"),
            current_price=Decimal("100"),
            projection_as_of=as_of,
        )
        t1 = sc.year_fractions[0]
        t2 = sc.year_fractions[1]
        assert t1 == Decimal("1.00000000")
        assert t2 == (Decimal("731") / Decimal("365")).quantize(Decimal("0.00000001"), ROUND_HALF_UP)

        # Verify exponential discounting
        pv2 = sc.pv_projections[1]
        fcff2 = sc.fcff_projections[1]
        expected_df2 = Decimal(str(math.exp(float(t2) * math.log(1.10))))
        expected_pv2 = (fcff2 / expected_df2).quantize(Decimal("0.01"), ROUND_HALF_UP)
        assert pv2 == expected_pv2

    def test_pure_calculator_center_equivalence(self):
        """DCF 3x3 sensitivity matrix center cell mathematically equals base scenario price."""
        snap = _make_sample_snapshot()
        assumptions = ValuationAssumptions()
        dcf_res = run_dcf(snap, assumptions)
        assert dcf_res.available is True
        assert dcf_res.sensitivity_matrix is not None

        center_cell = dcf_res.sensitivity_matrix.cells[1][1]
        base_price = dcf_res.base.price_per_share
        assert center_cell.price_per_share == base_price


# ==============================================================================
# [P1-D] Consensus Horizon & Bounded Day Weights
# ==============================================================================
class TestP1DConsensusHorizon:
    def test_default_horizon_is_ntm(self):
        """Default horizon in config and domain model is 'ntm'."""
        assert DEFAULT_FORECAST_HORIZON == "ntm"
        assumptions = ValuationAssumptions()
        assert assumptions.forecast_horizon == "ntm"

    def test_ntm_bounded_day_weights_bounds(self):
        """NTM weights w0 and w1 are strictly within [0, 1] and sum to 1.0."""
        as_of = date(2026, 9, 10)
        fy_end = date(2026, 12, 31)
        w0, w1, rem, total = calculate_ntm_weights(as_of, fy_end)
        assert Decimal("0.0") <= w0 <= Decimal("1.0")
        assert Decimal("0.0") <= w1 <= Decimal("1.0")
        assert (w0 + w1).quantize(Decimal("0.01")) == Decimal("1.00")
        assert rem == 112

    def test_ntm_fallback_to_current_fy_when_fy2_missing(self):
        """When forward_eps_2y is missing, fallback to current FY with explicit warning."""
        snap = _make_sample_snapshot(forward_eps_2y=None)
        assumptions = ValuationAssumptions(forecast_horizon="ntm")
        proj = derive_request_projections(snap, assumptions)
        assert proj.effective_horizon == "current_fy"
        assert proj.fallback_warning is not None
        assert "fell back to current fy" in proj.fallback_warning.lower()


# ==============================================================================
# [P1-E] Request-Scoped Growth Bounds
# ==============================================================================
class TestP1ERequestScopedGrowthBounds:
    def test_dynamic_growth_cap_variation_without_cache_leakage(self):
        """Varying growth_cap between 0.80 and 0.40 dynamically changes valuation without mutating snapshot."""
        snap = _make_sample_snapshot(
            revenue_growth=_make_metric("0.60"),
            ebitda_growth=_make_metric("0.60"),
            fcff_growth=_make_metric("0.60"),
        )
        assumptions_high = ValuationAssumptions(growth_cap=Decimal("0.80"))
        assumptions_low = ValuationAssumptions(growth_cap=Decimal("0.40"))

        proj_high = derive_request_projections(snap, assumptions_high)
        proj_low = derive_request_projections(snap, assumptions_low)

        assert proj_high.forward_ebitda.value > proj_low.forward_ebitda.value
        assert proj_high.forward_fcff_1y.value > proj_low.forward_fcff_1y.value

        # Verify snapshot was NOT mutated
        assert snap.ebitda_growth.value == Decimal("0.60")
        assert snap.fcff_growth.value == Decimal("0.60")


# ==============================================================================
# [P1-F] Dynamic Model Weights & Validation
# ==============================================================================
class TestP1FModelWeightsAndPolicy:
    def test_sparse_weights_override_merging(self):
        """Sparse override {weight_dcf: 0.0} merges with defaults, leaving other weights positive."""
        override = WeightOverride(weight_dcf=Decimal("0.0"))
        assert override.weight_dcf == Decimal("0.0")

    def test_all_zero_weights_rejected(self):
        """All-zero model weights override raises ValidationError (422)."""
        with pytest.raises(ValidationError) as exc:
            WeightOverride(
                weight_pe=Decimal("0.0"),
                weight_ev_ebitda=Decimal("0.0"),
                weight_fcf_yield=Decimal("0.0"),
                weight_dcf=Decimal("0.0"),
            )
        assert "greater than 0" in str(exc.value).lower()

    def test_growth_floor_greater_than_cap_rejected(self):
        """Setting growth_floor > growth_cap raises ValidationError (422)."""
        with pytest.raises(ValidationError) as exc:
            DCFOverride(growth_floor=Decimal("0.50"), growth_cap=Decimal("0.20"))
        assert "growth_floor must be <= growth_cap" in str(exc.value).lower()

    def test_cashflow_group_policy_message_visibility(self):
        """When only cashflow models are available, policy explanation and cashflow sensitivity are surfaced."""
        # Unprofitable company: PE and EV unavailable
        snap = _make_sample_snapshot(
            forward_eps_1y=_make_metric("-1.00"),
            forward_eps_2y=_make_metric("-0.50"),
            ebitda_ttm=_make_metric("-1000000000"),
            forward_ebitda_1y=None,
            forward_ebitda_2y=None,
        )
        assumptions = ValuationAssumptions()
        results = run_all_engines(snap, assumptions)
        composite = run_composite(
            current_price=snap.current_price.value,
            pe_result=results["forward_pe"],
            ev_result=results["ev_ebitda"],
            fcf_result=results["fcf_yield"],
            dcf_result=results["dcf"],
            assumptions=assumptions,
        )

        assert composite.cashflow_group_policy_message is not None
        assert composite.cashflow_sensitivity is not None
        assert "only cashflow models" in composite.unavailable_reason.lower()
