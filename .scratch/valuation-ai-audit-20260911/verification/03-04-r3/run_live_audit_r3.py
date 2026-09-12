"""Bounded live R3 audit through provider -> normalizer -> service -> API.

The R2 capture called ``ValuationService`` directly and covered four tickers.
R3 exercises the production FastAPI handlers with a recording live provider,
then stores the provider outputs (the raw inputs entering normalization) and
the newly evaluated HTTP responses together.  No demo bundle or fabricated
financial value is injected.  KO is an additional operating-company industry
case and JPM is an additional bank/applicability boundary.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[4]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.environ["DATA_PROVIDER"] = "live"

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main_module  # noqa: E402
from app.config import DEFAULT_ASSUMPTIONS  # noqa: E402
from app.providers.yfinance_provider import YFinanceProvider  # noqa: E402
from app.services.valuation_service import (  # noqa: E402
    FinancialDataService,
    MemoryTTLCache,
    ValuationService,
)


METHODS = (
    "get_quote",
    "get_company_profile",
    "get_balance_sheet",
    "get_cash_flow",
    "get_income_statement",
    "get_forward_estimates",
    "get_historical_multiples",
)


def _jsonable(value: Any) -> Any:
    """Serialize provider models without retaining headers or credentials."""

    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump(mode="python"))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


class RecordingLiveProvider(YFinanceProvider):
    """Capture each raw provider result while retaining production behavior."""

    def __init__(self, *, timeout: float = 15.0):
        super().__init__(timeout=timeout)
        self.raw_inputs: dict[str, dict[str, Any]] = {}
        for method_name in METHODS:
            original = getattr(self, method_name)

            def wrapped(
                ticker: str,
                budget: Any = None,
                *,
                _original=original,
                _method_name=method_name,
            ):
                try:
                    result = _original(ticker, budget=budget)
                except Exception as exc:
                    self.raw_inputs.setdefault(ticker, {})[_method_name] = {
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    }
                    raise
                self.raw_inputs.setdefault(ticker, {})[_method_name] = _jsonable(result)
                return result

            setattr(self, method_name, wrapped)


def _selection_summary(body: Mapping[str, Any]) -> dict[str, Any]:
    assumptions = body.get("assumptions_used") or {}
    valuations = body.get("valuations") or {}
    result: dict[str, Any] = {
        "selection_layers": {
            "pe": assumptions.get("pe_selection_layer"),
            "ev_ebitda": assumptions.get("ev_ebitda_selection_layer"),
        },
        "source_labels": {
            "pe": assumptions.get("pe_source_label"),
            "ev_ebitda": assumptions.get("ev_ebitda_source_label"),
        },
        "warnings": body.get("warnings") or [],
        "models": {},
    }
    for name, model in valuations.items():
        model = model or {}
        result["models"][name] = {
            "available": model.get("available"),
            "unavailable_reason": model.get("unavailable_reason"),
            "base_price": (model.get("base") or {}).get("price_per_share"),
        }
    dcf = valuations.get("dcf") or {}
    result["dcf"] = {
        "available": dcf.get("available"),
        "unavailable_reason": dcf.get("unavailable_reason"),
        "scenario_count": len(dcf.get("dcf_scenarios") or []),
    }
    return result


def run() -> None:
    tickers = ["NVDA", "GOOG", "AMD", "META", "KO", "JPM"]
    provider = RecordingLiveProvider(timeout=15.0)
    cache = MemoryTTLCache()
    data_service = FinancialDataService(
        provider=provider,
        cache=cache,
        default_assumptions=DEFAULT_ASSUMPTIONS,
    )
    valuation_service = ValuationService(
        data_service,
        default_assumptions=DEFAULT_ASSUMPTIONS,
    )

    # The handlers and error mapping are production app routes.  Rebinding
    # only this process's live graph avoids a second server and leaves source
    # code and external state untouched.
    main_module._live_provider = provider
    main_module._live_data_service = data_service
    main_module._live_valuation_service = valuation_service
    main_module._data_service = data_service
    main_module._valuation_service = valuation_service
    main_module._provider = provider
    main_module._cache = cache

    results: dict[str, Any] = {}
    print(f"Starting R3 live API audit for tickers: {tickers} (timeout=15s)")
    with TestClient(main_module.app) as client:
        for ticker in tickers:
            provider.raw_inputs.pop(ticker, None)
            started = datetime.now()
            request = {
                "method": "GET",
                "path": f"/api/v1/valuation/{ticker}",
                "query": {},
                "provider": "live",
            }
            try:
                response = client.get(request["path"])
                elapsed = (datetime.now() - started).total_seconds()
                try:
                    body = response.json()
                except ValueError:
                    body = {"raw_text": response.text}
                summary = {
                    "status_code": response.status_code,
                    "elapsed_seconds": elapsed,
                    "ticker": ticker,
                    "provenance": "live Yahoo Finance provider through production FastAPI route",
                }
                if response.status_code == 200 and isinstance(body, Mapping):
                    summary.update(_selection_summary(body))
                    summary["ticker"] = body.get("ticker", ticker)
                else:
                    summary["error_body"] = body
                results[ticker] = {
                    "request": request,
                    "provider_raw_inputs": provider.raw_inputs.get(ticker, {}),
                    "api_response": {
                        "status_code": response.status_code,
                        "body": body,
                    },
                    "summary": summary,
                }
                print(
                    f"[{ticker}] HTTP {response.status_code} ({elapsed:.2f}s) "
                    f"provider_methods={len(provider.raw_inputs.get(ticker, {}))} "
                    f"layers={summary.get('selection_layers')}"
                )
            except Exception as exc:  # noqa: BLE001 - preserve bounded evidence
                elapsed = (datetime.now() - started).total_seconds()
                results[ticker] = {
                    "request": request,
                    "provider_raw_inputs": provider.raw_inputs.get(ticker, {}),
                    "api_response": None,
                    "summary": {
                        "status_code": None,
                        "elapsed_seconds": elapsed,
                        "ticker": ticker,
                        "provenance": "live Yahoo Finance provider through production FastAPI route",
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    },
                }
                print(f"[{ticker}] ERROR ({elapsed:.2f}s): {type(exc).__name__}: {exc}")

    output = Path(__file__).with_name("live_results_r3.json")
    output.write_text(
        json.dumps(
            {
                "run_metadata": {
                    "provider": "live",
                    "source": "Yahoo Finance",
                    "execution_path": "YFinanceProvider -> Normalizer -> FinancialDataService -> ValuationService -> FastAPI app.main route",
                    "core_tickers": ["NVDA", "GOOG", "AMD", "META"],
                    "additional_tickers": ["KO", "JPM"],
                    "demo_used": False,
                    "started_at_local": datetime.now().astimezone().isoformat(),
                },
                "results": results,
            },
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"R3 live API results written to {output}")


if __name__ == "__main__":
    run()
