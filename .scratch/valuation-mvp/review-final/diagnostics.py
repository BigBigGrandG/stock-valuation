"""Read-only acceptance diagnostics for the final valuation backend review.

Run from the repository root with ``.venv/Scripts/python.exe
.scratch/valuation-mvp/review-final/diagnostics.py``.  This is deliberately
not a pytest module and does not modify backend files or call the API.
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from decimal import Decimal

sys.path.insert(0, "backend")

from app.config import DEFAULT_ASSUMPTIONS
from app.engines.composite import run_composite
from app.engines.dcf import run_dcf
from app.engines.ev_ebitda import run_ev_ebitda
from app.engines.forward_pe import run_forward_pe
from app.models.domain import (
    CompanyFinancialSnapshot,
    DataQuality,
    FinancialMetric,
    ModelValuation,
    PriceEstimate,
    ScenarioValues,
    SourceType,
)
from app.models.overrides import ValuationOverrideRequest
from app.services.valuation_service import apply_overrides, normalize_snapshot


AS_OF = date(2025, 1, 15)


def metric(value: str, unit: str = "USD", period: str = "TTM", source: str = "diagnostic") -> FinancialMetric:
    return FinancialMetric(
        value=Decimal(value),
        unit=unit,
        period=period,
        source=source,
        source_type=SourceType.ACTUAL,
        as_of=AS_OF,
        is_estimated=False,
    )


def snapshot(
    *,
    y1: str | None = "1000000",
    y2: str | None = "1100000",
    y1_period: str = "FY2025E",
    y2_period: str = "FY2026E",
    revenue_growth: str | None = None,
    fcff_growth: str | None = None,
    net_debt: str | None = None,
    with_capm: bool = False,
) -> CompanyFinancialSnapshot:
    kwargs: dict[str, object] = {
        "ticker": "TEST",
        "company_name": "Diagnostic Co",
        "current_price": metric("100"),
        "price_timestamp": datetime(2025, 1, 15),
        "diluted_shares": metric("10000", "shares"),
        "cash": metric("100000"),
        "total_debt": metric("200000"),
        "forward_fcff_1y": metric(y1, "USD", y1_period) if y1 is not None else None,
        "forward_fcff_2y": metric(y2, "USD", y2_period) if y2 is not None else None,
    }
    if revenue_growth is not None:
        kwargs["revenue_growth"] = metric(revenue_growth, "ratio", "FY2024", "historical revenue")
    if fcff_growth is not None:
        kwargs["fcff_growth"] = metric(fcff_growth, "ratio", "FY2024", "historical FCFF")
    if net_debt is not None:
        kwargs["net_debt"] = metric(net_debt)
    if with_capm:
        kwargs.update(
            {
                "risk_free_rate": metric("0.04", "rate", "FY2024", "CAPM"),
                "beta": metric("1.1", "ratio", "FY2024", "CAPM"),
                "equity_risk_premium": metric("0.05", "rate", "FY2024", "CAPM"),
                "pre_tax_cost_of_debt": metric("0.05", "rate", "FY2024", "CAPM"),
                "tax_rate": metric("0.20", "rate", "FY2024", "CAPM"),
            }
        )
    return CompanyFinancialSnapshot(**kwargs)


def model(price_low: str, price_base: str, price_high: str) -> ModelValuation:
    def estimate(value: str) -> PriceEstimate:
        return PriceEstimate(
            price_per_share=Decimal(value),
            upside_pct=Decimal("0"),
            premium_discount_pct=Decimal("0"),
        )

    return ModelValuation(
        formula="diagnostic",
        formula_description="diagnostic",
        inputs={},
        assumptions={},
        calculation_steps=[],
        low=estimate(price_low),
        base=estimate(price_base),
        high=estimate(price_high),
        available=True,
        data_quality=DataQuality.HIGH,
    )


def main() -> None:
    print("[DCF periods and growth provenance]")
    dcf = run_dcf(snapshot(), DEFAULT_ASSUMPTIONS)
    print("available:", dcf.available)
    for scenario in dcf.dcf_scenarios or []:
        gm = scenario.growth_metric or {}
        print(
            scenario.scenario,
            "periods=",
            scenario.projection_periods,
            "growth_rate=",
            scenario.growth_rate,
            "growth_metric.value=",
            gm.get("value"),
        )

    print("\n[DCF declining growth ordering]")
    declining = run_dcf(
        snapshot(y1="1000000", y2="900000"),
        DEFAULT_ASSUMPTIONS,
    )
    print(
        [
            (s.scenario, s.growth_rate, s.price_per_share)
            for s in (declining.dcf_scenarios or [])
        ]
    )

    print("\n[DCF historical fallback precedence]")
    historical = run_dcf(
        snapshot(y1="1000000", y2=None, revenue_growth="0.40", fcff_growth="0.10"),
        DEFAULT_ASSUMPTIONS,
    )
    print(
        "growth_source=",
        historical.assumptions.get("growth_source"),
        "growth_rates=",
        [s.growth_rate for s in (historical.dcf_scenarios or [])],
    )

    print("\n[Terminal-growth-only provenance]")
    tg_override = apply_overrides(
        DEFAULT_ASSUMPTIONS,
        {"dcf.terminal_growth": Decimal("0.035")},
    )
    tg_result = run_dcf(snapshot(with_capm=True), tg_override)
    print(
        "wacc_source=",
        tg_result.assumptions.get("wacc_source"),
        "terminal_growth.base=",
        tg_result.assumption_metrics.get("terminal_growth_base"),
    )

    print("\n[Net-debt consistency]")
    inconsistent = normalize_snapshot(snapshot(y1=None, y2=None, net_debt="999999"))
    ev = run_ev_ebitda(
        inconsistent.model_copy(
            update={"forward_ebitda_1y": metric("1000000", "USD", "FY2025E")}
        ),
        DEFAULT_ASSUMPTIONS,
    )
    print(
        "normalized.net_debt=",
        inconsistent.net_debt.value if inconsistent.net_debt else None,
        "expected identity=",
        inconsistent.total_debt.value - inconsistent.cash.value,
        "EV input net_debt=",
        ev.input_metrics.get("net_debt") if ev.available else ev.unavailable_reason,
    )

    print("\n[Composite normalized weights]")
    assumptions = DEFAULT_ASSUMPTIONS.model_copy(
        update={
            "weight_pe": Decimal("1"),
            "weight_ev_ebitda": Decimal("1"),
            "weight_fcf_yield": Decimal("1"),
            "weight_dcf": Decimal("0"),
        }
    )
    composite = run_composite(
        Decimal("100"),
        model("90", "100", "110"),
        model("90", "100", "110"),
        model("90", "100", "110"),
        model("90", "100", "110"),
        assumptions,
    )
    print("weights_used=", composite.weights_used, "sum=", sum(composite.weights_used.values()))

    print("\n[Historical multiple provenance]")
    dated_history = snapshot(y1=None, y2=None)
    dated_history = dated_history.model_copy(
        update={
            "forward_eps_1y": metric("10", "USD/share", "FY2025E", "EPS source"),
            "historical_forward_pe": FinancialMetric(
                value=Decimal("20"),
                unit="multiple",
                period="5Y median",
                source="historical source",
                source_type=SourceType.ACTUAL,
                as_of=date(2024, 12, 31),
                is_estimated=False,
            ),
        }
    )
    pe = run_forward_pe(dated_history, DEFAULT_ASSUMPTIONS)
    print("multiple_source=", pe.assumptions.get("multiple_source"))
    print("multiple_metric=", pe.assumption_metrics.get("pe_multiple_base"))

    print("\n[Strict nested override input types]")
    for payload in (
        {"forward_pe": {"base": "18"}},
        {"forward_pe": {"base": True}},
        {"dcf": {"wacc": "NaN"}},
    ):
        try:
            ValuationOverrideRequest.model_validate(payload)
            print(payload, "ACCEPTED")
        except Exception as exc:  # noqa: BLE001 - diagnostic output only
            print(payload, "REJECTED", type(exc).__name__)

    print("\n[Effective DCF WACC validation]")
    try:
        apply_overrides(DEFAULT_ASSUMPTIONS, {"dcf.wacc": Decimal("0.02")})
        print("0.02 WACC ACCEPTED")
    except Exception as exc:  # noqa: BLE001 - diagnostic output only
        print("0.02 WACC REJECTED", type(exc).__name__, str(exc))

    print("\n[Derived override bound escape]")
    for payload in (
        {"forward_pe": {"base": 200}},
        {"ev_ebitda": {"base": 200}},
        {"fcf_yield": {"base": 0.5}},
    ):
        request = ValuationOverrideRequest.model_validate(payload)
        flattened = request.to_override_dict()
        try:
            effective = apply_overrides(DEFAULT_ASSUMPTIONS, flattened)
            print(payload, "ACCEPTED", flattened, "effective=", effective.model_dump(mode="json"))
        except Exception as exc:  # noqa: BLE001 - diagnostic output only
            print(payload, "REJECTED", type(exc).__name__, str(exc))


if __name__ == "__main__":
    main()
