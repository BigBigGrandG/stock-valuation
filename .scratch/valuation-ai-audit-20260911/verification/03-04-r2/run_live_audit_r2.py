"""Bounded live Issue 03/04 audit with raw response capture.

This deliberately writes into the R2 evidence directory so the prior R1 live
capture remains immutable.  It queries four unrelated US tickers through the
production provider/service path and records the full JSON response, including
multiple-source metadata and DCF fade trajectories.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.environ["DATA_PROVIDER"] = "live"

from app.config import DEFAULT_ASSUMPTIONS  # noqa: E402
from app.providers.yfinance_provider import YFinanceProvider  # noqa: E402
from app.services.valuation_service import (  # noqa: E402
    FinancialDataService,
    MemoryTTLCache,
    ValuationService,
)


class Encoder(json.JSONEncoder):
    def default(self, value):
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        return super().default(value)


def run() -> None:
    tickers = ["NVDA", "GOOG", "AMD", "META"]
    provider = YFinanceProvider(timeout=15.0)
    data_service = FinancialDataService(
        provider=provider,
        cache=MemoryTTLCache(),
        default_assumptions=DEFAULT_ASSUMPTIONS,
    )
    valuation_service = ValuationService(
        data_service,
        default_assumptions=DEFAULT_ASSUMPTIONS,
    )
    results: dict[str, object] = {}
    print(f"Starting R2 live audit for tickers: {tickers} (timeout=15s)")
    for ticker in tickers:
        started = datetime.now()
        try:
            response = valuation_service.compute(ticker)
            elapsed = (datetime.now() - started).total_seconds()
            payload = response.model_dump(mode="json")
            results[ticker] = {
                "summary": {
                    "status": "success",
                    "elapsed_seconds": elapsed,
                    "ticker": response.ticker,
                    "company_name": response.company_name,
                    "current_price": str(response.current_price),
                    "currency": response.currency,
                    "statement_basis": response.statement_basis,
                    "shares_basis": response.shares_basis,
                    "models": {
                        key: {
                            "available": model.available,
                            "base": str(model.base.price_per_share) if model.base else None,
                            "unavailable_reason": model.unavailable_reason,
                        }
                        for key, model in response.valuations.items()
                    },
                    "selection_layers": {
                        "pe": response.assumptions_used.pe_selection_layer,
                        "ev_ebitda": response.assumptions_used.ev_ebitda_selection_layer,
                    },
                    "fade_contract": [
                        {
                            "scenario": scenario.scenario,
                            "growth_start": str(scenario.growth_start),
                            "projection_growth_rates": [
                                str(rate) if rate is not None else None
                                for rate in scenario.projection_growth_rates
                            ],
                            "terminal_growth": str(scenario.terminal_growth),
                            "formula": scenario.growth_fade_formula,
                        }
                        for scenario in (response.valuations.get("dcf").dcf_scenarios or [])
                    ]
                    if response.valuations.get("dcf")
                    and response.valuations["dcf"].dcf_scenarios
                    else [],
                    "warnings_count": len(response.warnings),
                },
                "raw_response": payload,
            }
            print(
                f"[{ticker}] SUCCESS ({elapsed:.2f}s) price={response.current_price} "
                f"layers=PE:{response.assumptions_used.pe_selection_layer},"
                f"EV:{response.assumptions_used.ev_ebitda_selection_layer}"
            )
        except Exception as exc:  # noqa: BLE001 - preserve per-ticker evidence
            elapsed = (datetime.now() - started).total_seconds()
            results[ticker] = {
                "summary": {
                    "status": "error",
                    "elapsed_seconds": elapsed,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
                "raw_response": None,
            }
            print(f"[{ticker}] ERROR ({elapsed:.2f}s): {type(exc).__name__}: {exc}")

    output = Path(__file__).with_name("live_results.json")
    output.write_text(
        json.dumps(results, cls=Encoder, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"R2 live results written to {output}")


if __name__ == "__main__":
    run()
