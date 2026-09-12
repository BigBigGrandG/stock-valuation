"""S5 acceptance tests for actual fiscal-YTD FCFF stub construction."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal

import pandas as pd
import pytest

from app.engines.dcf import run_dcf
from app.models.domain import (
    CompanyFinancialSnapshot,
    FinancialMetric,
    ScenarioValues,
    SourceType,
    ValuationAssumptions,
)
from app.providers.yfinance_provider import _extract_fiscal_ytd_fcff


VAL_DATE = date(2026, 9, 30)
FY_END = date(2026, 12, 31)


def _metric(
    value: object,
    period: str,
    *,
    source: str = "S5 test",
    source_type: SourceType = SourceType.ACTUAL,
    as_of: date = VAL_DATE,
    unit: str = "USD",
    is_estimated: bool = False,
    notes: str | None = None,
) -> FinancialMetric:
    return FinancialMetric(
        value=Decimal(str(value)),
        unit=unit,
        period=period,
        source=source,
        source_type=source_type,
        as_of=as_of,
        is_estimated=is_estimated,
        notes=notes,
    )


def _assumptions() -> ValuationAssumptions:
    return ValuationAssumptions(
        dcf_wacc=ScenarioValues(low=Decimal("0.12"), base=Decimal("0.10"), high=Decimal("0.08")),
        dcf_terminal_growth=ScenarioValues(
            low=Decimal("0.02"), base=Decimal("0.03"), high=Decimal("0.04")
        ),
        dcf_fcf_growth=ScenarioValues(
            low=Decimal("0.05"), base=Decimal("0.05"), high=Decimal("0.05")
        ),
        dcf_wacc_source=SourceType.USER_OVERRIDE,
        dcf_wacc_source_label="S5 explicit WACC scenario",
        dcf_terminal_growth_source=SourceType.USER_OVERRIDE,
        dcf_terminal_growth_source_label="S5 explicit terminal-growth scenario",
    )


def _snapshot(**updates: object) -> CompanyFinancialSnapshot:
    current = _metric("100", "2026-09-30", as_of=VAL_DATE)
    cash = _metric("0", "latest")
    debt = _metric("0", "latest")
    fields: dict[str, object] = {
        "ticker": "S5",
        "company_name": "S5 Fixture",
        "currency": "USD",
        "current_price": current,
        "price_timestamp": datetime(2026, 9, 30, tzinfo=timezone.utc),
        "diluted_shares": _metric("10", "point-in-time", unit="shares"),
        "cash": cash,
        "total_debt": debt,
        "net_debt": _metric("0", "derived"),
        "forward_fcff_1y": _metric(
            "1000", "FY2026E", source_type=SourceType.ANALYST_ESTIMATE, is_estimated=True
        ),
        "forward_fcff_2y": _metric(
            "1200", "FY2027E", source_type=SourceType.ANALYST_ESTIMATE, is_estimated=True
        ),
        "forecast_fiscal_year_end": FY_END,
        "is_demo": False,
        "fiscal_ytd_required": True,
        "fiscal_ytd_status": "available",
        "fiscal_ytd_fcff": _metric("400", "FY2026 YTD", source="quarterly actual"),
        "fiscal_ytd_start": date(2026, 1, 1),
        "fiscal_ytd_end": VAL_DATE,
        "fiscal_ytd_fiscal_year_end": FY_END,
    }
    fields.update(updates)
    return CompanyFinancialSnapshot(**fields)


def test_full_year_minus_ytd_actual_replaces_uniform_day_ratio_and_preserves_anchor():
    result = run_dcf(_snapshot(), _assumptions())

    assert result.available is True
    base = next(item for item in result.dcf_scenarios or [] if item.scenario == "base")
    assert base.fcff_projections[0] == Decimal("600.00")
    assert base.fcff_projections[1] == Decimal("1200.00")
    assert base.fcff_projections[0] != Decimal("1000") * Decimal("92") / Decimal("365")
    assert base.projection_proration_factors[0] == Decimal("1.00000000")
    assert base.projection_stub_basis[0] == "full_year_forecast_minus_actual_ytd"
    assert base.formulas["stub_cashflow"] == "FCFF_1,stub = FCFF_1,full − FCFF_actual_YTD"
    assert base.projection_metrics[0]["fiscal_ytd_actual"]["value"] == "400"
    assert result.inputs["fcff_y1_full_year"] == "1000"
    assert result.input_metrics["fiscal_ytd_fcff"]["source_type"] == SourceType.ACTUAL.value
    assert result.inputs["stub_cashflow_basis"] == "full_year_minus_actual_ytd"
    wire = result.model_dump(mode="json")
    assert wire["input_metrics"]["fiscal_ytd_fcff"]["period"] == "FY2026 YTD"
    assert wire["dcf_scenarios"][1]["fiscal_ytd_actual"]["source"] == "quarterly actual"
    ytd_wire = wire["input_metrics"]["fiscal_ytd_fcff"]
    assert {
        "unit",
        "period",
        "source",
        "source_type",
        "as_of",
        "confidence",
        "is_estimated",
    }.issubset(ytd_wire)


def test_missing_ytd_contract_fails_closed_without_zero_or_day_ratio_fallback():
    result = run_dcf(
        _snapshot(
            fiscal_ytd_fcff=None,
            fiscal_ytd_status="unavailable",
            fiscal_ytd_unavailable_reason="Latest quarter ends before valuation date",
        ),
        _assumptions(),
    )

    assert result.available is False
    assert "aligned actual FCFF YTD" in (result.unavailable_reason or "")
    assert "Latest quarter ends before valuation date" in (result.unavailable_reason or "")
    assert result.low is None and result.base is None and result.high is None
    assert result.dcf_scenarios is None


def test_live_in_progress_fy_without_any_ytd_contract_fails_closed():
    result = run_dcf(
        _snapshot(
            fiscal_ytd_fcff=None,
            fiscal_ytd_fcff_actual=None,
            ytd_fcff_actual=None,
            fiscal_ytd_required=None,
            fiscal_ytd_status=None,
            fiscal_ytd_start=None,
            fiscal_ytd_end=None,
            fiscal_ytd_fiscal_year_end=None,
            fiscal_ytd_unavailable_reason=None,
        ),
        _assumptions(),
    )

    assert result.available is False
    assert "no day-ratio fallback" in (result.unavailable_reason or "")
    assert result.low is None and result.base is None and result.high is None


def test_live_ytd_missing_coverage_does_not_use_metric_as_of_or_inferred_end():
    result = run_dcf(
        _snapshot(
            fiscal_ytd_start=None,
            fiscal_ytd_end=None,
            fiscal_ytd_fiscal_year_end=None,
            fiscal_ytd_prior_fiscal_year_end=None,
            fiscal_ytd_fcff=_metric("400", "FY2026 YTD", as_of=VAL_DATE),
        ),
        _assumptions(),
    )

    assert result.available is False
    assert "explicit" in (result.unavailable_reason or "").lower()
    assert "coverage" in (result.unavailable_reason or "").lower()


def test_demo_without_ytd_uses_explicit_compatibility_basis_only():
    result = run_dcf(
        _snapshot(
            is_demo=True,
            fiscal_ytd_fcff=None,
            fiscal_ytd_fcff_actual=None,
            ytd_fcff_actual=None,
            fiscal_ytd_required=None,
            fiscal_ytd_status=None,
            fiscal_ytd_start=None,
            fiscal_ytd_end=None,
            fiscal_ytd_fiscal_year_end=None,
            fiscal_ytd_unavailable_reason=None,
        ),
        _assumptions(),
    )

    assert result.available is True
    base = next(item for item in result.dcf_scenarios or [] if item.scenario == "base")
    assert base.projection_stub_basis[0] == "day_ratio_compatibility"
    assert base.fcff_projections[0] == (
        Decimal("1000") * Decimal("92") / Decimal("365")
    ).quantize(Decimal("0.01"))


@pytest.mark.parametrize(
    ("updates", "needle"),
    [
        (
            {
                "fiscal_ytd_fcff": _metric(
                    "400", "FY2026 YTD", notes="FCFE only; not FCFF"
                )
            },
            "FCFE",
        ),
        (
            {
                "fiscal_ytd_fcff": _metric("400", "FY2026 YTD", as_of=date(2026, 6, 30)),
                "fiscal_ytd_end": date(2026, 6, 30),
            },
            "ends 2026-06-30",
        ),
        (
            {"fiscal_ytd_fcff": _metric("400", "FY2026 YTD", unit="EUR")},
            "unit",
        ),
    ],
)
def test_mismatched_ytd_inputs_are_not_relabelled_as_actual_fcff(updates: dict[str, object], needle: str):
    result = run_dcf(_snapshot(**updates), _assumptions())
    assert result.available is False
    assert needle.lower() in (result.unavailable_reason or "").lower()


def test_domain_marker_restores_typed_ytd_provenance_through_existing_normalizer_seam():
    payload = {
        "status": "available",
        "value": "394",
        "unit": "USD",
        "period": "FY2026 YTD",
        "source": "Yahoo Finance quarterly cash-flow statements",
        "source_type": "actual",
        "as_of": "2026-09-30",
        "confidence": 1.0,
        "is_estimated": False,
        "notes": "aligned actual",
        "start": "2026-01-01",
        "end": "2026-09-30",
        "prior_fiscal_year_end": "2025-12-31",
        "fiscal_year_end": "2026-12-31",
    }
    marker = "S5_FISCAL_YTD_V1:" + json.dumps(payload)
    snapshot = CompanyFinancialSnapshot(
        ticker="S5",
        company_name="S5 Marker",
        current_price=_metric("100", "quote"),
        price_timestamp=datetime(2026, 9, 30),
        diluted_shares=_metric("10", "shares", unit="shares"),
        cash=_metric("0", "latest"),
        total_debt=_metric("0", "latest"),
        cfo_ttm=_metric("600", "TTM", notes=marker),
    )

    assert snapshot.fiscal_ytd_status == "available"
    assert snapshot.fiscal_ytd_required is True
    assert snapshot.fiscal_ytd_fcff is not None
    assert snapshot.fiscal_ytd_fcff.value == Decimal("394")
    assert snapshot.fiscal_ytd_fcff.source_type == SourceType.ACTUAL
    assert snapshot.fiscal_ytd_start == date(2026, 1, 1)
    assert snapshot.fiscal_ytd_end == VAL_DATE
    assert snapshot.fiscal_ytd_prior_fiscal_year_end == date(2025, 12, 31)


def test_domain_marker_without_explicit_unit_or_as_of_is_unavailable():
    payload = {
        "status": "available",
        "value": "394",
        "period": "FY2026 YTD",
        "source": "Yahoo Finance quarterly cash-flow statements",
        "source_type": "actual",
        "confidence": 1.0,
        "is_estimated": False,
        "start": "2026-01-01",
        "end": "2026-09-30",
        "fiscal_year_end": "2026-12-31",
    }
    marker = "S5_FISCAL_YTD_V1:" + json.dumps(payload)
    snapshot = CompanyFinancialSnapshot(
        ticker="S5",
        company_name="S5 Marker Missing Provenance",
        current_price=_metric("100", "quote"),
        price_timestamp=datetime(2026, 9, 30),
        diluted_shares=_metric("10", "shares", unit="shares"),
        cash=_metric("0", "latest"),
        total_debt=_metric("0", "latest"),
        cfo_ttm=_metric("600", "TTM", notes=marker),
    )

    assert snapshot.fiscal_ytd_status == "unavailable"
    assert snapshot.fiscal_ytd_fcff is None
    assert "metric" in (snapshot.fiscal_ytd_unavailable_reason or "").lower()


def test_provider_extracts_concentrated_capex_actual_fcff_and_rejects_gap():
    info = {
        "regularMarketTime": int(datetime(2026, 9, 30, tzinfo=timezone.utc).timestamp()),
        "nextFiscalYearEnd": int(datetime(2026, 12, 31, tzinfo=timezone.utc).timestamp()),
        "lastFiscalYearEnd": int(datetime(2025, 12, 31, tzinfo=timezone.utc).timestamp()),
        "financialCurrency": "USD",
        "currency": "USD",
    }
    cols = pd.to_datetime(["2026-03-31", "2026-06-30", "2026-09-30"])
    quarterly_cf = pd.DataFrame(
        {
            cols[0]: [100, -10],
            cols[1]: [200, -20],
            cols[2]: [300, -200],
        },
        index=["Operating Cash Flow", "Capital Expenditure"],
    )
    quarterly_fin = pd.DataFrame(
        {
            cols[0]: [10, Decimal("0.20")],
            cols[1]: [10, Decimal("0.20")],
            cols[2]: [10, Decimal("0.20")],
        },
        index=["Interest Expense", "Tax Rate For Calcs"],
    )

    actual = _extract_fiscal_ytd_fcff(info, quarterly_cf, quarterly_fin)
    assert actual["status"] == "available"
    # CFO 600 + after-tax interest 24 - CapEx 230 = 394.
    assert actual["value"] == Decimal("394.00")
    assert actual["period"] == "FY2026 YTD"
    assert actual["source_type"] == "actual"
    assert actual["unit"] == "USD"
    assert actual["as_of"] == VAL_DATE
    assert actual["is_estimated"] is False
    assert actual["start"] == date(2026, 1, 1)
    assert actual["end"] == VAL_DATE

    gap_info = dict(info)
    gap_info["regularMarketTime"] = int(datetime(2026, 9, 12, tzinfo=timezone.utc).timestamp())
    unavailable = _extract_fiscal_ytd_fcff(gap_info, quarterly_cf, quarterly_fin)
    assert unavailable["status"] == "unavailable"
    assert "before valuation date" in unavailable["reason"]


def test_provider_requires_financial_currency_even_when_quote_currency_is_usd():
    info = {
        "regularMarketTime": int(datetime(2026, 9, 30, tzinfo=timezone.utc).timestamp()),
        "nextFiscalYearEnd": int(datetime(2026, 12, 31, tzinfo=timezone.utc).timestamp()),
        "lastFiscalYearEnd": int(datetime(2025, 12, 31, tzinfo=timezone.utc).timestamp()),
        "currency": "USD",
    }
    cols = pd.to_datetime(["2026-03-31", "2026-06-30", "2026-09-30"])
    quarterly_cf = pd.DataFrame(
        {
            cols[0]: [100, -10],
            cols[1]: [200, -20],
            cols[2]: [300, -200],
        },
        index=["Operating Cash Flow", "Capital Expenditure"],
    )
    quarterly_fin = pd.DataFrame(
        {
            column: [10, Decimal("0.20")]
            for column in cols
        },
        index=["Interest Expense", "Tax Rate For Calcs"],
    )

    actual = _extract_fiscal_ytd_fcff(info, quarterly_cf, quarterly_fin)

    assert actual["status"] == "unavailable"
    assert "financialcurrency" in actual["reason"].lower()


def test_provider_deaccumulates_cumulative_ytd_without_double_counting_quarters():
    info = {
        "regularMarketTime": int(datetime(2026, 9, 30, tzinfo=timezone.utc).timestamp()),
        "nextFiscalYearEnd": int(datetime(2026, 12, 31, tzinfo=timezone.utc).timestamp()),
        "lastFiscalYearEnd": int(datetime(2025, 12, 31, tzinfo=timezone.utc).timestamp()),
        "financialCurrency": "USD",
    }
    cols = ["2026-03-31 3M", "2026-06-30 6M", "2026-09-30 9M"]
    quarterly_cf = pd.DataFrame(
        {
            cols[0]: [100, -10],
            cols[1]: [300, -30],
            cols[2]: [600, -230],
        },
        index=["Operating Cash Flow", "Capital Expenditure"],
    )
    quarterly_fin = pd.DataFrame(
        {
            cols[0]: [10, 10, 100],
            cols[1]: [20, 50, 300],
            cols[2]: [30, 140, 600],
        },
        index=["Interest Expense", "Tax Provision", "Pretax Income"],
    )

    actual = _extract_fiscal_ytd_fcff(info, quarterly_cf, quarterly_fin)

    assert actual["status"] == "available"
    assert actual["value"] == Decimal("394.00")
    assert "cumulative-YTD de-accumulated" in actual["notes"]


def test_provider_rejects_cumulative_cashflow_with_discrete_financial_statements():
    info = {
        "regularMarketTime": int(datetime(2026, 9, 30, tzinfo=timezone.utc).timestamp()),
        "nextFiscalYearEnd": int(datetime(2026, 12, 31, tzinfo=timezone.utc).timestamp()),
        "lastFiscalYearEnd": int(datetime(2025, 12, 31, tzinfo=timezone.utc).timestamp()),
        "financialCurrency": "USD",
    }
    cf_cols = ["2026-03-31 YTD", "2026-06-30 6M", "2026-09-30 9M"]
    fin_cols = pd.to_datetime(["2026-03-31", "2026-06-30", "2026-09-30"])
    quarterly_cf = pd.DataFrame(
        {
            cf_cols[0]: [100, -10],
            cf_cols[1]: [300, -30],
            cf_cols[2]: [600, -230],
        },
        index=["Operating Cash Flow", "Capital Expenditure"],
    )
    quarterly_fin = pd.DataFrame(
        {
            fin_cols[0]: [10, Decimal("0.10")],
            fin_cols[1]: [10, Decimal("0.20")],
            fin_cols[2]: [10, Decimal("0.30")],
        },
        index=["Interest Expense", "Tax Rate For Calcs"],
    )

    actual = _extract_fiscal_ytd_fcff(info, quarterly_cf, quarterly_fin)

    assert actual["status"] == "unavailable"
    assert "basis" in actual["reason"].lower()


def test_provider_rejects_short_first_period_as_ambiguous_quarterly_basis():
    info = {
        "regularMarketTime": int(datetime(2026, 9, 30, tzinfo=timezone.utc).timestamp()),
        "nextFiscalYearEnd": int(datetime(2026, 12, 31, tzinfo=timezone.utc).timestamp()),
        "lastFiscalYearEnd": int(datetime(2025, 12, 31, tzinfo=timezone.utc).timestamp()),
        "financialCurrency": "USD",
    }
    cols = pd.to_datetime(["2026-01-31", "2026-04-30", "2026-07-30", "2026-09-30"])
    quarterly_cf = pd.DataFrame(
        {
            column: [100, -10]
            for column in cols
        },
        index=["Operating Cash Flow", "Capital Expenditure"],
    )
    quarterly_fin = pd.DataFrame(
        {
            column: [10, Decimal("0.20")]
            for column in cols
        },
        index=["Interest Expense", "Tax Rate For Calcs"],
    )

    actual = _extract_fiscal_ytd_fcff(info, quarterly_cf, quarterly_fin)

    assert actual["status"] == "unavailable"
    assert "first quarterly" in actual["reason"].lower()


def test_provider_nonfinite_quarterly_actual_fails_closed():
    info = {
        "regularMarketTime": int(datetime(2026, 9, 30, tzinfo=timezone.utc).timestamp()),
        "nextFiscalYearEnd": int(datetime(2026, 12, 31, tzinfo=timezone.utc).timestamp()),
        "lastFiscalYearEnd": int(datetime(2025, 12, 31, tzinfo=timezone.utc).timestamp()),
        "financialCurrency": "USD",
    }
    cols = pd.to_datetime(["2026-03-31", "2026-06-30", "2026-09-30"])
    quarterly_cf = pd.DataFrame(
        {
            cols[0]: [100, -10],
            cols[1]: [200, -20],
            cols[2]: [float("nan"), -200],
        },
        index=["Operating Cash Flow", "Capital Expenditure"],
    )
    quarterly_fin = pd.DataFrame(
        {column: [10, Decimal("0.20")] for column in cols},
        index=["Interest Expense", "Tax Rate For Calcs"],
    )

    actual = _extract_fiscal_ytd_fcff(info, quarterly_cf, quarterly_fin)

    assert actual["status"] == "unavailable"
    assert "CFO and CapEx" in actual["reason"]


def test_fiscal_boundary_uses_exact_leap_year_anchor():
    valuation_date = date(2027, 9, 30)
    fiscal_end = date(2028, 2, 29)
    ytd = _metric("400", "FY2028 YTD", as_of=valuation_date)
    snapshot = _snapshot(
        current_price=_metric("100", "2027-09-30", as_of=valuation_date),
        price_timestamp=datetime(2027, 9, 30),
        forward_fcff_1y=_metric("1000", "FY2028E", source_type=SourceType.ANALYST_ESTIMATE, is_estimated=True, as_of=valuation_date),
        forward_fcff_2y=_metric("1200", "FY2029E", source_type=SourceType.ANALYST_ESTIMATE, is_estimated=True, as_of=valuation_date),
        forecast_fiscal_year_end=fiscal_end,
        fiscal_ytd_fcff=ytd,
        fiscal_ytd_start=date(2027, 3, 1),
        fiscal_ytd_end=valuation_date,
        fiscal_ytd_fiscal_year_end=fiscal_end,
    )
    result = run_dcf(snapshot, _assumptions())
    assert result.available is True
    base = next(item for item in result.dcf_scenarios or [] if item.scenario == "base")
    assert base.fcff_projections[0] == Decimal("600.00")
    assert base.period_start_dates[0] == "2027-09-30"
    assert base.period_end_dates[0] == "2028-02-29"
    assert base.fiscal_year_days[0] == 366


def test_provider_week_fiscal_anchor_is_not_rewritten_to_calendar_anniversary():
    valuation_date = date(2026, 9, 30)
    fiscal_end = date(2026, 12, 27)
    prior_fiscal_end = date(2025, 12, 28)
    snapshot = _snapshot(
        current_price=_metric("100", "2026-09-30", as_of=valuation_date),
        price_timestamp=datetime(2026, 9, 30),
        forward_fcff_1y=_metric(
            "1000", "FY2026E", source_type=SourceType.ANALYST_ESTIMATE,
            is_estimated=True, as_of=valuation_date,
        ),
        forward_fcff_2y=_metric(
            "1200", "FY2027E", source_type=SourceType.ANALYST_ESTIMATE,
            is_estimated=True, as_of=valuation_date,
        ),
        forecast_fiscal_year_end=fiscal_end,
        fiscal_ytd_fcff=_metric("400", "FY2026 YTD", as_of=valuation_date),
        fiscal_ytd_start=prior_fiscal_end.replace(day=29),
        fiscal_ytd_end=valuation_date,
        fiscal_ytd_prior_fiscal_year_end=prior_fiscal_end,
        fiscal_ytd_fiscal_year_end=fiscal_end,
    )

    result = run_dcf(snapshot, _assumptions())

    assert result.available is True
    base = next(item for item in result.dcf_scenarios or [] if item.scenario == "base")
    assert base.period_start_dates[0] == "2026-09-30"
    assert base.period_end_dates[0] == "2026-12-27"
    assert base.fiscal_year_days[0] == 364
    assert base.fcff_projections[0] == Decimal("600.00")
