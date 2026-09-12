"""R2 safety regressions for Issue 03 company/industry multiple arbitration.

These tests deliberately exercise the provider -> normalizer -> service path
and are expected to expose the R1 gaps before the stricter validator exists.
The DCF fade contract remains covered by the R1 regression module.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal

from app.services.multiples import lookup_industry_benchmark

from .test_audit_issues_03_04_regression import _CandidateProvider, _service


def _evidenced_pe_row(
    observed_at: date,
    value: str,
    *,
    index: int = 0,
    vintage_as_of: date | None = None,
    period_end: date | None = None,
    include_basis: bool = True,
) -> dict[str, object]:
    """Build a candidate with the R2 point-in-time evidence contract."""

    multiple = Decimal(value)
    price = Decimal("100") + Decimal(index)
    forward_eps = price / multiple
    row: dict[str, object] = {
        "value": value,
        "as_of": observed_at.isoformat(),
        "forecast_period": f"FY{(period_end or date(observed_at.year + 1, 12, 31)).year}E",
        "forecast_period_end": (period_end or date(observed_at.year + 1, 12, 31)).isoformat(),
        "forecast_vintage_as_of": (vintage_as_of or (observed_at - timedelta(days=30))).isoformat(),
        "is_forward": True,
        "price": str(price),
        "price_as_of": observed_at.isoformat(),
        "price_currency": "USD",
        "forward_eps": str(forward_eps),
        "forward_eps_currency": "USD",
        "price_unit": "USD/share",
        "forward_eps_unit": "USD/share",
        "price_basis": "diluted_common_share",
        "forward_eps_basis": "diluted_common_share",
        "source": "Archived analyst consensus and historical close",
        "source_url": f"https://example.test/company-pe/price/{observed_at.isoformat()}-{index}",
        "forecast_source": "Archived analyst consensus",
        "forecast_source_url": f"https://example.test/company-pe/forecast/{observed_at.isoformat()}-{index}",
    }
    if not include_basis:
        for key in (
            "forecast_period_end",
            "forecast_vintage_as_of",
            "is_forward",
            "price_currency",
            "forward_eps_currency",
            "price_unit",
            "forward_eps_unit",
            "price_basis",
            "forward_eps_basis",
            "forecast_source_url",
        ):
            row.pop(key, None)
    return row


def _provider_with_pe_rows(rows: list[dict[str, object]]) -> _CandidateProvider:
    provider = _CandidateProvider()
    original = provider.get_historical_multiples

    def get(ticker: str):
        raw = deepcopy(original(ticker))
        raw["company_forward_pe_observations"] = deepcopy(rows)
        raw["company_ev_ebitda_observations"] = []
        return raw

    provider.get_historical_multiples = get  # type: ignore[method-assign]
    return provider


def _evidenced_ev_row(
    observed_at: date,
    value: str,
    *,
    index: int = 0,
    vintage_as_of: date | None = None,
    period_end: date | None = None,
) -> dict[str, object]:
    """Build a contemporaneous, forward operating-EBITDA observation."""

    multiple = Decimal(value)
    enterprise_value = Decimal("1000") + Decimal(index * 25)
    forward_ebitda = enterprise_value / multiple
    return {
        "value": value,
        "as_of": observed_at.isoformat(),
        "forecast_period": f"FY{(period_end or date(observed_at.year + 1, 12, 31)).year}E",
        "forecast_period_end": (period_end or date(observed_at.year + 1, 12, 31)).isoformat(),
        "forecast_vintage_as_of": (vintage_as_of or (observed_at - timedelta(days=30))).isoformat(),
        "is_forward": True,
        "enterprise_value": str(enterprise_value),
        "enterprise_value_as_of": observed_at.isoformat(),
        "enterprise_value_currency": "USD",
        "enterprise_value_unit": "USD total",
        "enterprise_value_basis": "enterprise_value",
        "forward_ebitda": str(forward_ebitda),
        "forward_ebitda_as_of": observed_at.isoformat(),
        "forward_ebitda_currency": "USD",
        "forward_ebitda_unit": "USD total",
        "forward_ebitda_basis": "forward_operating_ebitda",
        "forward_ebitda_forecast_type": "forward",
        "source": "Archived enterprise value and analyst operating EBITDA",
        "source_url": f"https://example.test/company-ev/price/{observed_at.isoformat()}-{index}",
        "forecast_source": "Archived analyst operating EBITDA",
        "forecast_source_url": f"https://example.test/company-ev/forecast/{observed_at.isoformat()}-{index}",
    }


def _provider_with_ev_rows(rows: list[dict[str, object]]) -> _CandidateProvider:
    provider = _CandidateProvider()
    original = provider.get_historical_multiples

    def get(ticker: str):
        raw = deepcopy(original(ticker))
        raw["company_forward_pe_observations"] = []
        raw["company_ev_ebitda_observations"] = deepcopy(rows)
        return raw

    provider.get_historical_multiples = get  # type: ignore[method-assign]
    return provider


def test_r2_company_history_requires_vintage_basis_and_explicit_forward_end():
    """FY text plus a price ratio must not pass without point-in-time proof."""

    rows = [
        _evidenced_pe_row(date(2023, 1, 1), "20", index=0, include_basis=False),
        _evidenced_pe_row(date(2024, 1, 1), "21", index=1, include_basis=False),
        _evidenced_pe_row(date(2026, 6, 30), "22", index=2, include_basis=False),
    ]
    result = _service(_provider_with_pe_rows(rows)).compute("AVGO")

    # R1 accepted these rows as company history; R2 must degrade to the
    # independently validated industry P/E candidate instead.
    assert result.assumptions_used.pe_selection_layer == "industry"
    assert "company history unavailable" in result.assumptions_used.pe_source_label.lower()


def test_r2_history_requires_three_year_coverage_not_one_year():
    rows = [
        _evidenced_pe_row(date(2024, 1, 1), "20", index=0),
        _evidenced_pe_row(date(2025, 1, 1), "21", index=1),
        _evidenced_pe_row(date(2026, 6, 30), "22", index=2),
    ]
    result = _service(_provider_with_pe_rows(rows)).compute("AVGO")

    # The rows span less than three years even though they satisfy R1's
    # one-year rule and are otherwise fully evidenced.
    assert result.assumptions_used.pe_selection_layer == "industry"
    assert "three" in result.assumptions_used.pe_source_label.lower() or "3" in result.assumptions_used.pe_source_label


def test_r2_repeated_dates_are_deduplicated_before_count_validation():
    rows = [
        _evidenced_pe_row(date(2023, 1, 1), "20", index=0),
        _evidenced_pe_row(date(2023, 1, 1), "22", index=1),
        _evidenced_pe_row(date(2026, 6, 30), "21", index=2),
    ]
    result = _service(_provider_with_pe_rows(rows)).compute("AVGO")

    # Two unique observation dates are not the required three retained
    # samples; duplicate rows must not inflate the sample count.
    assert result.assumptions_used.pe_selection_layer == "industry"


def test_r2_dense_history_is_sampled_across_full_window():
    rows = [
        _evidenced_pe_row(date(2022 + (index // 3), 1 + (index % 3) * 4, 1), str(20 + index % 3), index=index)
        for index in range(13)
    ]
    result = _service(_provider_with_pe_rows(rows)).compute("AVGO")

    # R1 kept only the latest five dense rows, collapsing coverage below a
    # year. R2 must select a deterministic spread across the full history.
    assert result.assumptions_used.pe_selection_layer == "company_historical"
    assert result.assumptions_used.pe_selection_sample_size == 5


def test_r2_post_filter_endpoint_outlier_rechecks_coverage():
    rows = [
        _evidenced_pe_row(date(2023, 1, 1), "100", index=0),
        _evidenced_pe_row(date(2024, 1, 1), "20", index=1),
        _evidenced_pe_row(date(2025, 1, 1), "21", index=2),
        _evidenced_pe_row(date(2026, 1, 1), "22", index=3),
        _evidenced_pe_row(date(2026, 6, 30), "23", index=4),
    ]
    result = _service(_provider_with_pe_rows(rows)).compute("AVGO")

    # Removing the oldest MAD outlier leaves less than three years of valid
    # coverage; that post-filter set must degrade rather than pass silently.
    assert result.assumptions_used.pe_selection_layer == "industry"


def test_r2_observed_all_firms_ev_is_not_forward_operating_ebitda_target():
    provider = _CandidateProvider()
    original = provider.get_historical_multiples

    def get(ticker: str):
        raw = deepcopy(original(ticker))
        raw["company_forward_pe_observations"] = []
        raw["company_ev_ebitda_observations"] = []
        return raw

    provider.get_historical_multiples = get  # type: ignore[method-assign]
    result = _service(provider).compute("AVGO")

    assert result.assumptions_used.pe_selection_layer == "industry"
    assert result.assumptions_used.ev_ebitda_selection_layer == "system"
    assert any("operating" in warning.lower() or "basis" in warning.lower() for warning in result.warnings)


def test_r2_broad_industry_label_does_not_match_arbitrary_row():
    assert lookup_industry_benchmark("Technology", "Software") is None
    # Yahoo's taxonomy label is not itself evidence of economic equivalence
    # to the separately defined Damodaran Software (Internet) row; degrade.
    assert lookup_industry_benchmark("Technology", "Internet Content & Information") is None
    assert lookup_industry_benchmark("Technology", "Semiconductors") is not None


def test_r2_zero_mad_retains_full_spread_sample():
    rows = [
        _evidenced_pe_row(date(2022, 1, 1), "20", index=0),
        _evidenced_pe_row(date(2023, 1, 1), "20", index=1),
        _evidenced_pe_row(date(2024, 1, 1), "20", index=2),
        _evidenced_pe_row(date(2025, 1, 1), "20", index=3),
        _evidenced_pe_row(date(2026, 6, 30), "20", index=4),
    ]
    result = _service(_provider_with_pe_rows(rows)).compute("AVGO")

    assert result.assumptions_used.pe_selection_layer == "company_historical"
    assert result.assumptions_used.pe_selection_sample_size == 5
    assert "zero_mad=True" in result.assumptions_used.pe_source_label


def test_r2_forecast_vintage_and_target_period_must_be_point_in_time_forward():
    rows = [
        _evidenced_pe_row(
            date(2023, 1, 1),
            "20",
            index=0,
            vintage_as_of=date(2023, 1, 2),
            period_end=date(2023, 1, 1),
        ),
        _evidenced_pe_row(
            date(2024, 1, 1),
            "21",
            index=1,
            vintage_as_of=date(2024, 1, 2),
            period_end=date(2024, 1, 1),
        ),
        _evidenced_pe_row(
            date(2026, 6, 30),
            "22",
            index=2,
            vintage_as_of=date(2026, 7, 1),
            period_end=date(2026, 6, 30),
        ),
    ]
    result = _service(_provider_with_pe_rows(rows)).compute("AVGO")

    assert result.assumptions_used.pe_selection_layer == "industry"
    reason = result.assumptions_used.pe_source_label.lower()
    assert "vintage" in reason or "target fiscal period" in reason


def test_r2_currency_mismatch_degrades_company_history():
    rows = [_evidenced_pe_row(date(2022, 1, 1), "20", index=0),
            _evidenced_pe_row(date(2023, 1, 1), "21", index=1),
            _evidenced_pe_row(date(2026, 6, 30), "22", index=2)]
    for row in rows:
        row["price_currency"] = "EUR"
        row["forward_eps_currency"] = "EUR"
    result = _service(_provider_with_pe_rows(rows)).compute("AVGO")

    assert result.assumptions_used.pe_selection_layer == "industry"
    assert "currency" in result.assumptions_used.pe_source_label.lower()


def test_r2_compatible_operating_ev_history_can_be_selected_independently():
    rows = [
        _evidenced_ev_row(date(2022, 1, 1), "20", index=0),
        _evidenced_ev_row(date(2023, 1, 1), "21", index=1),
        _evidenced_ev_row(date(2024, 1, 1), "22", index=2),
        _evidenced_ev_row(date(2025, 1, 1), "23", index=3),
        _evidenced_ev_row(date(2026, 6, 30), "24", index=4),
    ]
    result = _service(_provider_with_ev_rows(rows)).compute("AVGO")

    assert result.assumptions_used.pe_selection_layer == "industry"
    assert result.assumptions_used.ev_ebitda_selection_layer == "company_historical"
    assert result.assumptions_used.ev_ebitda_selection_sample_size == 5
    assert "operating" in result.assumptions_used.ev_ebitda_source_label.lower()
