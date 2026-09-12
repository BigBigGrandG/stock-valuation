"""Worker C fiscal-year DCF time-axis acceptance tests."""

from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from app.engines.dcf import run_dcf
from app.models.domain import (
    CompanyFinancialSnapshot,
    FinancialMetric,
    ScenarioValues,
    SourceType,
    ValuationAssumptions,
)


VAL_DATE = date(2026, 9, 11)
FY1_END = date(2026, 12, 31)


def _metric(value: str, *, period: str, unit: str = "USD") -> FinancialMetric:
    return FinancialMetric(
        value=Decimal(value),
        unit=unit,
        period=period,
        source="Worker C fixture",
        source_type=SourceType.FIXTURE,
        as_of=VAL_DATE,
        is_estimated=True,
    )


def _snapshot(*, valuation_date: date = VAL_DATE, fiscal_end: date | None = FY1_END) -> CompanyFinancialSnapshot:
    def metric(value: str, period: str = "TTM", unit: str = "USD") -> FinancialMetric:
        return FinancialMetric(
            value=Decimal(value),
            unit=unit,
            period=period,
            source="Worker C fixture",
            source_type=SourceType.FIXTURE,
            as_of=valuation_date,
            is_estimated=True,
        )

    net_debt = metric("0")
    return CompanyFinancialSnapshot(
        ticker="TEST",
        company_name="Worker C Fixture",
        current_price=metric("100", "valuation date"),
        price_timestamp=datetime.combine(valuation_date, datetime.min.time(), tzinfo=timezone.utc),
        diluted_shares=metric("10", "valuation date", "shares"),
        cash=metric("0"),
        total_debt=metric("0"),
        net_debt=net_debt,
        net_debt_metric=net_debt,
        forward_fcff_1y=metric("100", "FY2026E"),
        forward_fcff_2y=metric("120", "FY2027E"),
        forecast_fiscal_year_end=fiscal_end,
    )


def _assumptions() -> ValuationAssumptions:
    return ValuationAssumptions(
        dcf_wacc=ScenarioValues(low=Decimal("0.12"), base=Decimal("0.10"), high=Decimal("0.08")),
        dcf_terminal_growth=ScenarioValues(low=Decimal("0.02"), base=Decimal("0.03"), high=Decimal("0.04")),
        dcf_fcf_growth=ScenarioValues(low=Decimal("0.05"), base=Decimal("0.05"), high=Decimal("0.05")),
    )


def test_fiscal_year_dcf_uses_stub_and_true_endpoint_times():
    result = run_dcf(_snapshot(), _assumptions())
    assert result.available
    scenario = next(item for item in result.dcf_scenarios or [] if item.scenario == "base")

    assert scenario.period_start_dates[:2] == ["2026-09-11", "2027-01-01"]
    assert scenario.period_end_dates[:2] == ["2026-12-31", "2027-12-31"]
    remaining_days = (date(2026, 12, 31) - VAL_DATE).days
    assert remaining_days == 111
    assert scenario.projection_proration_factors[0] == (
        Decimal(str(remaining_days)) / Decimal("365")
    ).quantize(Decimal("0.00000001"), ROUND_HALF_UP)
    assert scenario.period_is_stub[0] is True
    assert scenario.fcff_projections[0] == Decimal("30.41")
    assert scenario.fcff_projections[1] == Decimal("120")

    assert scenario.year_fractions[0] == (
        Decimal(str(remaining_days)) / Decimal("365")
    ).quantize(Decimal("0.00000001"), ROUND_HALF_UP)
    assert scenario.year_fractions[0] < Decimal("1")
    fy2_days_to_end = (date(2027, 12, 31) - VAL_DATE).days
    assert scenario.year_fractions[1] == (
        Decimal(str(fy2_days_to_end)) / Decimal("365")
    ).quantize(Decimal("0.00000001"), ROUND_HALF_UP)
    assert scenario.year_fractions[1] > Decimal("1.3")
    assert scenario.terminal_period_end_date == "2030-12-31"
    assert scenario.terminal_discount_time == scenario.year_fractions[-1]
    assert scenario.discount_factors[0] > Decimal("1")
    assert scenario.projection_metrics[0]["is_stub"] is True
    assert scenario.projection_metrics[0]["period_start"] == "2026-09-11"
    assert scenario.projection_metrics[0]["period_end"] == "2026-12-31"
    assert scenario.projection_metrics[0]["t"] == str(scenario.year_fractions[0])
    assert scenario.projection_metrics[0]["discount_factor"] == str(scenario.discount_factors[0])

    # The center sensitivity cell must retain the same fiscal schedule and
    # exact timeline while changing only the sensitivity assumptions.
    matrix = result.sensitivity_matrix
    assert matrix is not None
    center = matrix.cells[1][1]
    assert center.period_start_dates == scenario.period_start_dates
    assert center.period_end_dates == scenario.period_end_dates
    assert center.discount_times == scenario.discount_times
    assert center.pv_projections == scenario.pv_projections


def test_fiscal_start_keeps_full_fy1_without_proration():
    valuation_date = date(2026, 1, 1)
    result = run_dcf(_snapshot(valuation_date=valuation_date, fiscal_end=date(2026, 12, 31)), _assumptions())
    assert result.available
    scenario = next(item for item in result.dcf_scenarios or [] if item.scenario == "base")
    assert scenario.period_start_dates[0] == "2026-01-01"
    assert scenario.period_end_dates[0] == "2026-12-31"
    assert scenario.projection_proration_factors[0] == Decimal("1.00000000")
    assert scenario.period_is_stub[0] is False
    assert scenario.fcff_projections[0] == Decimal("100")


def test_api_model_dump_contains_fiscal_timeline_fields():
    result = run_dcf(_snapshot(), _assumptions())
    payload = result.model_dump(mode="json")
    scenario = next(item for item in payload["dcf_scenarios"] if item["scenario"] == "base")
    assert scenario["period_start_dates"][0] == "2026-09-11"
    assert scenario["period_end_dates"][0] == "2026-12-31"
    assert scenario["discount_times"][0] < "1"
    assert scenario["terminal_period_end_date"] == "2030-12-31"
