"""R3 Regression tests for 01/02 audit issues.

Covers the 6 failure points from rework-01-02-r3.md:
1. EBITDA growth cleanup in provider & projections (EBITDA = revenue * margin).
2. Consensus EBITDA/FCFF/FCFE integrity, reconciliation difference, no fake identity.
3. DCF timeline: consistent FY1E/FY2E periods (no NTM stub as FY1), horizon labeling.
4. Date boundaries: full FY start/end for current_fy, leap-day Feb 29 offline safety, structured driver metadata.
5. NWC CFS sign conversion (cash outflow -> positive delta NWC -> reduces FCFF), exclusion of Other WC as total, D&A annual fallback period disclosure.
6. Operating EBITDA (Operating Income + D&A) isolating non-operating gains (GOOG $98.8B security gain).
"""
from datetime import date
from decimal import Decimal
import pandas as pd
import pytest

from app.models.domain import (
    CompanyFinancialSnapshot,
    FinancialMetric,
    SourceType,
    ValuationAssumptions,
)
from app.models.overrides import ValuationOverrideRequest
from app.providers.statement_aggregator import (
    aggregate_ttm_cashflow,
    aggregate_ttm_income,
)
from app.providers.yfinance_provider import (
    _TickerBundle,
    YFinanceProvider,
    _RequestBudget,
)
from app.services.projections import (
    RequestProjections,
    derive_request_projections,
)
from app.engines.dcf import run_dcf
from app.services.valuation_service import (
    ValuationService,
    FinancialDataService,
)


from datetime import datetime

def _snap(**kwargs):
    defaults = {
        'company_name': 'Test Co',
        'current_price': _m(100),
        'price_timestamp': datetime(2026, 6, 30, 0, 0),
        'diluted_shares': _m(1000000),
    }
    defaults.update(kwargs)
    return CompanyFinancialSnapshot(**defaults)

def _m(val, unit="USD", period="TTM", source="test", st=SourceType.ACTUAL, as_of=date(2026, 6, 30)):
    if val is None:
        return None
    return FinancialMetric(
        value=Decimal(str(val)),
        unit=unit,
        period=period,
        source=source,
        source_type=st,
        as_of=as_of,
        confidence=1.0,
    )


# ----------------------------------------------------------------------------
# 1. EBITDA: No synthetic (1 + g) formula in provider; projections default = rev * margin
# ----------------------------------------------------------------------------

def test_r3_provider_does_not_synthesize_forward_ebitda_via_growth_formula(monkeypatch):
    """Provider must not generate forward_ebitda_1y or 2y by multiplying ebitda * (1 + g)."""
    from tests.fixtures.mock_bundles import build_mock_bundle
    p = YFinanceProvider()
    budget = _RequestBudget(timeout=15.0)

    bundle = build_mock_bundle(ticker="AAPL")
    monkeypatch.setattr(p, "_get_bundle", lambda ticker: bundle)

    estimates = p.get_forward_estimates("AAPL", budget=budget)
    assert estimates.get("forward_ebitda_1y") is None, (
        "Provider must not synthesize forward_ebitda_1y via formula; "
        "only genuine analyst consensus or None"
    )
    assert estimates.get("forward_ebitda_2y") is None


def test_r3_projections_non_consensus_ebitda_not_grown_and_defaults_to_rev_times_margin():
    """Non-consensus forward EBITDA from snapshot is not grown via base*(1+g).
    Default forward EBITDA must equal fwd_rev_val * ebitda_margin (quantized).
    """
    snapshot = _snap(
        ticker="TEST",
        revenue_ttm=_m(1000),
        ebitda_ttm=_m(200),
        forward_revenue=_m(1200, period="FY1E"),
        revenue_estimate_1y=_m(1200, period="FY1E"),
        forward_ebitda_1y=_m(220, period="forward_1y", st=SourceType.DERIVED),
        revenue_growth=_m("0.30", unit="ratio"),
        tax_rate=_m("0.20", unit="ratio"),
        capex_ttm=_m(50),
        nwc_change_ttm=_m(10),
        da_ttm=_m(30),
    )
    assumptions = ValuationAssumptions()
    proj = derive_request_projections(snapshot, assumptions)

    assert proj.forward_ebitda is not None
    assert proj.forward_ebitda.value == Decimal("240"), (
        f"Forward EBITDA must equal revenue ({proj.forward_revenue.value}) * margin (20%) = 240, "
        f"got {proj.forward_ebitda.value}"
    )


# ----------------------------------------------------------------------------
# 2. Consensus EBITDA / FCFF / FCFE integrity & reconciliation difference
# ----------------------------------------------------------------------------

def test_r3_consensus_ebitda_margin_implied_from_consensus():
    """When analyst consensus EBITDA is present, ebitda_margin must be implied
    from consensus_ebitda / forward_revenue, NOT from historical margin.
    """
    snapshot = _snap(
        ticker="TEST",
        revenue_ttm=_m(1000),
        ebitda_ttm=_m(200),
        forward_revenue=_m(1200, period="FY1E"),
        revenue_estimate_1y=_m(1200, period="FY1E"),
        forward_ebitda_1y=_m(360, period="FY1E", st=SourceType.ANALYST_ESTIMATE),
        tax_rate=_m("0.20", unit="ratio"),
        capex_ttm=_m(50),
        nwc_change_ttm=_m(10),
        da_ttm=_m(30),
    )
    assumptions = ValuationAssumptions()
    proj = derive_request_projections(snapshot, assumptions)

    assert proj.forward_ebitda.value == Decimal("360")
    bridge = proj.financial_bridge
    assert bridge is not None
    assert Decimal(bridge["ebitda_margin"]) == Decimal("0.3000"), (
        f"EBITDA margin must be implied from consensus EBITDA (30%), got {bridge['ebitda_margin']}"
    )


def test_r3_consensus_fcff_differs_from_driver_bridge_reports_reconciliation_gap():
    """When analyst consensus FCFF is present and differs from driver bridge NOPAT+D&A-CapEx-ΔNWC:
    1. Valuation model input retains consensus FCFF.
    2. Bridge reports reconciliation_difference and identity_holds is False.
    3. It does NOT falsely claim 5 identities hold without gap.
    """
    snapshot = _snap(
        ticker="TEST",
        revenue_ttm=_m(1000),
        ebitda_ttm=_m(300),
        forward_revenue=_m(1000, period="FY1E"),
        revenue_estimate_1y=_m(1000, period="FY1E"),
        tax_rate=_m("0.20", unit="ratio"),
        capex_ttm=_m(60),
        nwc_change_ttm=_m(20),
        da_ttm=_m(50),
        forward_fcff_1y=_m(210, period="FY1E", st=SourceType.ANALYST_ESTIMATE),
    )
    assumptions = ValuationAssumptions()
    proj = derive_request_projections(snapshot, assumptions)

    assert proj.forward_fcff_1y.value == Decimal("210")
    bridge = proj.financial_bridge
    assert bridge is not None
    assert bridge.get("identity_holds") is False, (
        "When direct consensus FCFF differs from driver bridge, identity_holds must be False"
    )
    assert bridge.get("reconciliation_difference") is not None
    assert Decimal(bridge["reconciliation_difference"]) == Decimal("40")


def test_r3_missing_drivers_isolated_and_no_nonconsensus_raw_fcff_leak():
    """When key drivers (D&A or CapEx) are missing and raw_forward_fcff is NOT consensus,
    projections must NOT fall back to raw_forward_fcff; FCFF must be None (fail-closed).
    """
    snapshot = _snap(
        ticker="TEST",
        revenue_ttm=_m(1000),
        ebitda_ttm=_m(200),
        forward_revenue=_m(1000, period="FY1E"),
        capex_ttm=None,
        da_ttm=None,
        forward_fcff_1y=_m(150, period="FY1E", st=SourceType.DERIVED),
    )
    assumptions = ValuationAssumptions()
    proj = derive_request_projections(snapshot, assumptions)

    assert proj.forward_fcff_1y is None, (
        "Non-consensus raw_forward_fcff must not bypass missing driver isolation; "
        "forward_fcff_1y must be None"
    )


# ----------------------------------------------------------------------------
# 3. DCF Timeline: Consistent annual periods (no NTM stub as FY1), Horizon labeling
# ----------------------------------------------------------------------------

def test_r3_dcf_timeline_uses_consistent_annual_periods_not_ntm_stub():
    """When horizon='ntm', multi-period DCF must receive full fiscal year periods
    (FY1E and FY2E), not an NTM rolling stub as Year 1 paired with FY2E.
    """
    snapshot = _snap(
        ticker="TEST",
        revenue_ttm=_m(1000),
        ebitda_ttm=_m(200),
        revenue_estimate_1y=_m(1100, period="FY1E"),
        revenue_estimate_2y=_m(1250, period="FY2E"),
        forward_revenue=_m(1050, period="NTM"),
        tax_rate=_m("0.20", unit="ratio"),
        capex_ttm=_m(50),
        nwc_change_ttm=_m(10),
        da_ttm=_m(30),
        forecast_fiscal_year_end=date(2027, 12, 31),
    )
    assumptions = ValuationAssumptions(forecast_horizon="ntm")
    proj = derive_request_projections(snapshot, assumptions)

    assert hasattr(proj, "dcf_fcff_1y"), "proj must have dcf_fcff_1y for DCF"
    assert proj.dcf_fcff_1y is not None
    assert proj.dcf_fcff_1y.period == "FY1E", (
        f"DCF Year 1 must be full FY1E, got {proj.dcf_fcff_1y.period}"
    )
    assert proj.dcf_fcff_2y is not None
    assert proj.dcf_fcff_2y.period == "FY2E", (
        f"DCF Year 2 must be full FY2E, got {proj.dcf_fcff_2y.period}"
    )


def test_r3_next_fy_horizon_labels_and_stub_vs_full_year():
    """When horizon='next_fy', metric period is FY2E (not FY1E).
    When horizon='current_fy', forecast start and end match full fiscal year.
    """
    snapshot = _snap(
        ticker="TEST",
        current_price=_m(100, as_of=date(2026, 9, 11)),
        revenue_ttm=_m(1000),
        ebitda_ttm=_m(200),
        forward_eps_1y=_m("3.00", period="FY1E"),
        forward_eps_2y=_m("3.50", period="FY2E"),
        revenue_estimate_1y=_m(1100, period="FY1E"),
        revenue_estimate_2y=_m(1250, period="FY2E"),
        forecast_fiscal_year_end=date(2026, 12, 31),
        tax_rate=_m("0.20", unit="ratio"),
        capex_ttm=_m(50),
        nwc_change_ttm=_m(10),
        da_ttm=_m(30),
        forward_revenue=_m(1100, period="NTM"),
    )

    assumptions_next = ValuationAssumptions(forecast_horizon="next_fy")
    proj_next = derive_request_projections(snapshot, assumptions_next)
    bridge_next = proj_next.financial_bridge
    assert bridge_next is not None
    assert bridge_next["period"] == "next_fy"
    assert proj_next.forward_ebitda.period == "FY2E", (
        f"next_fy forward_ebitda period must be FY2E, got {proj_next.forward_ebitda.period}"
    )

    assumptions_curr = ValuationAssumptions(forecast_horizon="current_fy")
    proj_curr = derive_request_projections(snapshot, assumptions_curr)
    bridge_curr = proj_curr.financial_bridge
    assert bridge_curr is not None
    assert bridge_curr["forecast_start_date"] == "2026-01-01", (
        f"current_fy start must be fiscal year start 2026-01-01, got {bridge_curr['forecast_start_date']}"
    )
    assert bridge_curr["forecast_end_date"] == "2026-12-31"


# ----------------------------------------------------------------------------
# 4. Dates: Leap-year Feb 29 offline safety & Structured Driver Metadata
# ----------------------------------------------------------------------------

def test_r3_safe_date_leap_year_handling():
    """Advancing leap day date(2024, 2, 29) by 1 year must not throw ValueError."""
    snapshot = _snap(
        ticker="TEST",
        as_of=date(2024, 2, 29),
        current_price=_m(100, as_of=date(2024, 2, 29)),
        revenue_ttm=_m(1000, as_of=date(2024, 2, 29)),
        ebitda_ttm=_m(200, as_of=date(2024, 2, 29)),
        forward_revenue=_m(1100, period="NTM", as_of=date(2024, 2, 29)),
        tax_rate=_m("0.20", unit="ratio"),
        capex_ttm=_m(50),
        nwc_change_ttm=_m(10),
        da_ttm=_m(30),
    )
    assumptions = ValuationAssumptions(forecast_horizon="ntm")
    proj = derive_request_projections(snapshot, assumptions)
    bridge = proj.financial_bridge
    assert bridge is not None
    assert bridge["forecast_start_date"] == "2024-02-29"
    assert bridge["forecast_end_date"] == "2025-02-28"


def test_r3_drivers_source_contains_structured_metadata():
    """drivers_source in financial bridge must contain structured metadata:
    type, as_of, period (not just a bare string).
    """
    snapshot = _snap(
        ticker="TEST",
        revenue_ttm=_m(1000, period="TTM", as_of=date(2026, 6, 30)),
        ebitda_ttm=_m(200, period="TTM", as_of=date(2026, 6, 30)),
        tax_rate=_m("0.20", unit="ratio"),
        capex_ttm=_m(50, period="TTM", as_of=date(2026, 6, 30)),
        nwc_change_ttm=_m(10, period="TTM", as_of=date(2026, 6, 30)),
        da_ttm=_m(30, period="TTM", as_of=date(2026, 6, 30)),
        forward_revenue=_m(1100, period="NTM", as_of=date(2026, 6, 30)),
    )
    assumptions = ValuationAssumptions()
    proj = derive_request_projections(snapshot, assumptions)
    bridge = proj.financial_bridge
    assert bridge is not None
    ds = bridge["drivers_source"]
    assert isinstance(ds, dict)
    for driver_name in ["ebitda_margin", "da", "tax_rate", "capex", "nwc_change"]:
        meta = ds.get(driver_name)
        assert isinstance(meta, dict), f"driver {driver_name} must be a dict with metadata, got {meta}"
        assert "type" in meta
        assert "as_of" in meta
        assert "period" in meta


# ----------------------------------------------------------------------------
# 5. NWC Sign, Change In Other Working Capital exclusion, D&A Period Disclosure
# ----------------------------------------------------------------------------

def test_r3_working_capital_cfs_sign_and_no_other_wc_alone():
    idx = ["Operating Cash Flow", "Capital Expenditure", "Change In Other Working Capital"]
    data = {
        pd.Timestamp("2026-06-30"): [100.0, -20.0, 5.0],
        pd.Timestamp("2026-03-31"): [100.0, -20.0, 5.0],
        pd.Timestamp("2025-12-31"): [100.0, -20.0, 5.0],
        pd.Timestamp("2025-09-30"): [100.0, -20.0, 5.0],
    }
    df_cf = pd.DataFrame(data, index=idx)
    agg = aggregate_ttm_cashflow(df_cf, None, default_as_of=date(2026, 6, 30))
    assert agg.get("nwc_change") is None, (
        "Change In Other Working Capital alone must NOT be returned as total nwc_change"
    )

    idx2 = ["Operating Cash Flow", "Capital Expenditure", "Change In Working Capital"]
    data2 = {
        pd.Timestamp("2026-06-30"): [100.0, -20.0, -12.5],
        pd.Timestamp("2026-03-31"): [100.0, -20.0, -12.5],
        pd.Timestamp("2025-12-31"): [100.0, -20.0, -12.5],
        pd.Timestamp("2025-09-30"): [100.0, -20.0, -12.5],
    }
    df_cf2 = pd.DataFrame(data2, index=idx2)
    agg2 = aggregate_ttm_cashflow(df_cf2, None, default_as_of=date(2026, 6, 30))
    assert agg2.get("nwc_investment") == Decimal("50.0") or agg2.get("nwc_change") == Decimal("50.0"), (
        "Working capital investment ΔNWC must be +50 when CFS change is -50 (cash outflow)"
    )


def test_r3_da_annual_fallback_discloses_distinct_period_and_as_of():
    q_data = {
        pd.Timestamp("2026-06-30"): [100.0, 20.0],
        pd.Timestamp("2026-03-31"): [100.0, 20.0],
        pd.Timestamp("2025-12-31"): [100.0, 20.0],
        pd.Timestamp("2025-09-30"): [100.0, 20.0],
    }
    df_q = pd.DataFrame(q_data, index=["Total Revenue", "Operating Income"])

    a_data = {
        pd.Timestamp("2025-12-31"): [400.0, 80.0, 15.0],
    }
    df_a = pd.DataFrame(a_data, index=["Total Revenue", "Operating Income", "Depreciation And Amortization"])

    res = aggregate_ttm_income(df_q, df_a, default_as_of=date(2026, 6, 30))
    assert res.get("da") == Decimal("15.0")
    assert res.get("da_period") is not None
    assert "FY" in res.get("da_period") or "2025" in res.get("da_period"), (
        f"da_period must disclose annual period, got {res.get('da_period')}"
    )
    assert res.get("da_as_of") == date(2025, 12, 31)


# ----------------------------------------------------------------------------
# 6. Operating EBITDA: Isolate non-operating investment gains (GOOG breakdown)
# ----------------------------------------------------------------------------

def test_r3_operating_ebitda_isolates_non_operating_investment_gains_goog():
    q_cols = [
        pd.Timestamp("2026-06-30"),
        pd.Timestamp("2026-03-31"),
        pd.Timestamp("2025-12-31"),
        pd.Timestamp("2025-09-30"),
    ]
    data = {
        q_cols[0]: [119.8, 40.77, 7.10, 147.13, 98.8],
        q_cols[1]: [109.9, 39.70, 7.00, 46.70, 0.0],
        q_cols[2]: [113.8, 41.50, 7.20, 48.70, 0.0],
        q_cols[3]: [105.0, 38.00, 6.90, 44.90, 0.0],
    }
    idx = ["Total Revenue", "Operating Income", "Reconciled Depreciation", "EBITDA", "Gain On Sale Of Security"]
    df_q = pd.DataFrame(data, index=idx)

    res = aggregate_ttm_income(df_q, None, default_as_of=date(2026, 6, 30))
    assert res.get("operating_ebitda") is not None or res.get("ebitda") == Decimal("188.17")
    effective_op_ebitda = res.get("operating_ebitda") or res.get("ebitda")
    margin = effective_op_ebitda / res["revenue"]
    assert margin < Decimal("0.50"), (
        f"Operating EBITDA margin must be around 42% isolating non-operating gains, got {margin:.2%}"
    )
