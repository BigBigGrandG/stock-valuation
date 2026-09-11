"""Bounded live 01/02 R5 evidence collector.

Run from the repository root with:

    .venv/Scripts/python.exe .scratch/valuation-ai-audit-20260911/verification/r5/run_live_validation.py

The script uses the live Yahoo provider only, records every raw provider
category consumed by the service, records the complete valuation response, and
fails when an available DCF bridge cannot be reconciled to its engine inputs.
Provider/network failures are recorded per ticker and return a non-zero exit
code; no prior R2/R3 response is read or reused.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping

from pydantic import BaseModel


ROOT = Path(__file__).resolve().parents[4]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.providers.base import FinancialDataProvider
from app.providers.yfinance_provider import _RequestBudget, YFinanceProvider
from app.services.valuation_service import FinancialDataService, MemoryTTLCache, ValuationService


TICKERS = ("AMD", "META", "GOOG", "NVDA")
DEFAULT_TIMEOUT_SECONDS = 25.0
OUTPUT_PATH = Path(__file__).with_name("live-validation-r5.json")


def _jsonable(value: Any) -> Any:
    """Convert provider/model values to JSON without losing Decimal precision."""

    if isinstance(value, BaseModel):
        return _jsonable(value.model_dump(mode="python"))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


class _RecordingLiveProvider(FinancialDataProvider):
    """Record the seven live provider payloads while preserving the real seam."""

    is_demo = False

    def __init__(self, provider: YFinanceProvider):
        self.provider = provider
        self.timeout = provider.timeout
        self.raw_sources: dict[str, dict[str, Any]] = {}

    def _call(self, category: str, ticker: str, method: Callable[[str], Any]) -> Any:
        try:
            payload = method(ticker)
            self.raw_sources[category] = {
                "status": "ok",
                "provider_method": method.__name__,
                "payload": _jsonable(payload),
            }
            return payload
        except Exception as exc:
            self.raw_sources[category] = {
                "status": "error",
                "provider_method": method.__name__,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
            raise

    def get_quote(self, ticker: str):
        return self._call("quote", ticker, self.provider.get_quote)

    def get_company_profile(self, ticker: str):
        return self._call("profile", ticker, self.provider.get_company_profile)

    def get_balance_sheet(self, ticker: str):
        return self._call("balance_sheet", ticker, self.provider.get_balance_sheet)

    def get_cash_flow(self, ticker: str):
        return self._call("cash_flow", ticker, self.provider.get_cash_flow)

    def get_income_statement(self, ticker: str):
        return self._call("income_statement", ticker, self.provider.get_income_statement)

    def get_forward_estimates(self, ticker: str):
        return self._call("forward_estimates", ticker, self.provider.get_forward_estimates)

    def get_historical_multiples(self, ticker: str):
        return self._call("historical_multiples", ticker, self.provider.get_historical_multiples)


def _metric_value(metric: Any) -> Any:
    if not isinstance(metric, Mapping):
        return None
    return metric.get("value")


def _validate_bridge_consistency(response: Mapping[str, Any]) -> dict[str, Any]:
    """Assert bridge-to-engine period/input lineage from the collected response."""

    bridge = response.get("financial_bridge")
    dcf = (response.get("valuations") or {}).get("dcf") or {}
    if not bridge:
        return {
            "status": "not_applicable",
            "reason": "financial_bridge is absent; no bridge lineage to compare",
            "checks": [],
        }

    forecasts = bridge.get("dcf_forecasts") or []
    input_metrics = dcf.get("input_metrics") or {}
    if not dcf.get("available"):
        leaked_inputs = {
            key: value
            for key, value in input_metrics.items()
            if key in {"fcff_ttm", "forward_fcff_1y", "forward_fcff_2y"}
        }
        errors = []
        if forecasts:
            errors.append("DCF is unavailable but financial_bridge contains dcf_forecasts")
        if leaked_inputs:
            errors.append(f"DCF is unavailable but engine FCFF inputs leaked: {sorted(leaked_inputs)}")
        return {
            "status": "ok" if not errors else "failed",
            "reason": "DCF is unavailable; production isolation left no engine FCFF inputs",
            "checks": [
                {
                    "name": "unavailable_dcf_has_no_forward_fcff_inputs",
                    "passed": not errors,
                    "forecast_count": len(forecasts),
                    "engine_fcff_input_keys": sorted(leaked_inputs),
                }
            ],
            "errors": errors,
            "bridge_period": bridge.get("period"),
            "bridge_forecast_range": {
                "start": bridge.get("forecast_start_date"),
                "end": bridge.get("forecast_end_date"),
            },
            "dcf_available": dcf.get("available"),
        }

    checks: list[dict[str, Any]] = []
    errors: list[str] = []

    if not forecasts:
        errors.append("financial_bridge has no dcf_forecasts while DCF is available")

    bridge_start = bridge.get("forecast_start_date")
    bridge_end = bridge.get("forecast_end_date")
    if not bridge_start or not bridge_end:
        errors.append("financial_bridge forecast range is incomplete")

    for forecast in forecasts:
        year = forecast.get("year")
        key = f"forward_fcff_{year}y"
        engine_metric = input_metrics.get(key)
        period = str(forecast.get("period") or "")
        period_upper = period.upper()
        check: dict[str, Any] = {
            "year": year,
            "engine_key": key,
            "bridge_value": forecast.get("value"),
            "bridge_period": forecast.get("period"),
            "engine_value": _metric_value(engine_metric),
            "engine_period": engine_metric.get("period") if isinstance(engine_metric, Mapping) else None,
        }
        if engine_metric is None:
            errors.append(f"missing DCF engine input {key} for bridge forecast year {year}")
        else:
            if forecast.get("value") != engine_metric.get("value"):
                errors.append(f"value mismatch for {key}: bridge={forecast.get('value')} engine={engine_metric.get('value')}")
            if forecast.get("period") != engine_metric.get("period"):
                errors.append(f"period mismatch for {key}: bridge={forecast.get('period')} engine={engine_metric.get('period')}")
            if forecast.get("as_of") != engine_metric.get("as_of"):
                errors.append(f"as_of mismatch for {key}: bridge={forecast.get('as_of')} engine={engine_metric.get('as_of')}")
        if period_upper.startswith(("TTM", "NTM")):
            errors.append(f"DCF bridge forecast {key} has non-annual period {period}")
        start_date = forecast.get("start_date")
        end_date = forecast.get("end_date")
        if not start_date or not end_date:
            errors.append(f"DCF bridge forecast {key} is missing fiscal start/end dates")
        checks.append(check)

    return {
        "status": "ok" if not errors else "failed",
        "checks": checks,
        "errors": errors,
        "bridge_period": bridge.get("period"),
        "bridge_forecast_range": {"start": bridge_start, "end": bridge_end},
        "dcf_available": dcf.get("available"),
    }


def _run_ticker(ticker: str, timeout_seconds: float) -> tuple[dict[str, Any], bool]:
    provider = _RecordingLiveProvider(YFinanceProvider(timeout=timeout_seconds))
    data_service = FinancialDataService(
        provider=provider,
        cache=MemoryTTLCache(),
        timeout=timeout_seconds,
    )
    valuation_service = ValuationService(data_service)
    started = time.monotonic()
    item: dict[str, Any] = {
        "ticker": ticker,
        "provider_kind": "live",
        "provider_class": "YFinanceProvider",
        "is_demo": False,
        "timeout_seconds": timeout_seconds,
        "raw_sources": provider.raw_sources,
        "response": None,
    }
    try:
        response = valuation_service.compute(
            ticker,
            bypass_cache=True,
            budget=_RequestBudget(timeout_seconds),
        )
        response_json = response.model_dump(mode="json")
        consistency = _validate_bridge_consistency(response_json)
        item.update(
            {
                "status": "ok" if consistency["status"] in {"ok", "not_applicable"} else "consistency_error",
                "elapsed_seconds": round(time.monotonic() - started, 2),
                "response": response_json,
                "consistency": consistency,
            }
        )
        return item, item["status"] == "ok"
    except Exception as exc:
        item.update(
            {
                "status": "provider_error",
                "elapsed_seconds": round(time.monotonic() - started, 2),
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        )
        return item, False


def main() -> int:
    raw_timeout = os.getenv("LIVE_VALIDATION_TIMEOUT", str(DEFAULT_TIMEOUT_SECONDS))
    timeout_seconds = float(raw_timeout)
    if not 1.0 <= timeout_seconds <= 60.0:
        raise SystemExit("LIVE_VALIDATION_TIMEOUT must be between 1 and 60 seconds")

    started_at = datetime.now(timezone.utc).isoformat()
    results: list[dict[str, Any]] = []
    all_ok = True
    for ticker in TICKERS:
        result, ok = _run_ticker(ticker, timeout_seconds)
        results.append(result)
        all_ok = all_ok and ok
        print(
            json.dumps(
                {
                    "ticker": ticker,
                    "status": result.get("status"),
                    "elapsed_seconds": result.get("elapsed_seconds"),
                    "consistency": result.get("consistency"),
                    "error_type": result.get("error_type"),
                },
                ensure_ascii=False,
                default=str,
            ),
            flush=True,
        )

    artifact = {
        "schema": "valuation-ai-audit-r5-live-v1",
        "collected_at": started_at,
        "provider_kind": "live",
        "provider_class": "YFinanceProvider",
        "is_demo": False,
        "timeout_seconds": timeout_seconds,
        "tickers": list(TICKERS),
        "results": results,
        "overall_status": "ok" if all_ok else "failed",
    }
    OUTPUT_PATH.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"artifact": str(OUTPUT_PATH), "overall_status": artifact["overall_status"]}, ensure_ascii=False), flush=True)
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
