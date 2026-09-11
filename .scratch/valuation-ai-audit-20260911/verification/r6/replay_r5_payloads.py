"""Replay the historical R5 live provider payloads through the production path.

This is deliberately an offline replay of the seven raw responses captured by
the R5 bounded live run.  It does not call Yahoo Finance and does not consume
the R5 valuation response as an oracle: each case runs the replay provider,
FinancialDataService normalizer, request projections, all engines, and the
ValuationService response assembly afresh.
"""
from __future__ import annotations

import copy
import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[4]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.providers.base import FinancialDataProvider
from app.services.valuation_service import FinancialDataService, MemoryTTLCache, ValuationService


INPUT_PATH = ROOT / ".scratch" / "valuation-ai-audit-20260911" / "verification" / "r5" / "live-validation-r5.json"
OUTPUT_PATH = Path(__file__).with_name("replay-r5-payloads-r6.json")
TICKERS = ("AMD", "META", "GOOG", "NVDA")
RAW_CATEGORIES = (
    "quote",
    "profile",
    "balance_sheet",
    "cash_flow",
    "income_statement",
    "forward_estimates",
    "historical_multiples",
)


class _ReplayProvider(FinancialDataProvider):
    """Seven-method provider seam backed only by one ticker's captured payloads."""

    is_demo = False
    timeout = 25.0

    def __init__(self, raw_sources: Mapping[str, Any]):
        self.raw_sources = raw_sources
        self.calls: list[str] = []

    def _payload(self, category: str) -> Any:
        item = self.raw_sources.get(category) or {}
        if item.get("status") != "ok":
            raise RuntimeError(f"R5 raw category {category} is not replayable: {item.get('status')}")
        self.calls.append(category)
        return copy.deepcopy(item.get("payload"))

    def get_quote(self, ticker: str):
        return self._payload("quote")

    def get_company_profile(self, ticker: str):
        return self._payload("profile")

    def get_balance_sheet(self, ticker: str):
        return self._payload("balance_sheet")

    def get_cash_flow(self, ticker: str):
        return self._payload("cash_flow")

    def get_income_statement(self, ticker: str):
        return self._payload("income_statement")

    def get_forward_estimates(self, ticker: str):
        return self._payload("forward_estimates")

    def get_historical_multiples(self, ticker: str):
        return self._payload("historical_multiples")


def _metric_value(metric: Any) -> Any:
    if not isinstance(metric, Mapping):
        return None
    return metric.get("value")


def _consistency(response: Mapping[str, Any]) -> dict[str, Any]:
    """Validate available DCF bridge values, periods, dates and engine inputs."""

    bridge = response.get("financial_bridge") or {}
    dcf = (response.get("valuations") or {}).get("dcf") or {}
    forecasts = bridge.get("dcf_forecasts") or []
    input_metrics = dcf.get("input_metrics") or {}
    errors: list[str] = []

    if not dcf.get("available"):
        leaked_inputs = sorted(
            key
            for key in input_metrics
            if key in {"fcff_ttm", "forward_fcff_1y", "forward_fcff_2y"}
        )
        if leaked_inputs:
            errors.append(f"unavailable DCF leaked FCFF engine inputs: {leaked_inputs}")
        return {
            "status": "ok" if not errors else "failed",
            "dcf_available": False,
            "forecast_count": len(forecasts),
            "engine_fcff_input_keys": leaked_inputs,
            "checks": [
                {
                    "name": "unavailable_dcf_has_no_forward_fcff_inputs",
                    "passed": not leaked_inputs,
                }
            ],
            "errors": errors,
        }

    if len(forecasts) != 2:
        errors.append(f"available DCF must expose exactly FY1/FY2 bridge forecasts, got {len(forecasts)}")
    checks: list[dict[str, Any]] = []
    for forecast in forecasts:
        year = forecast.get("year")
        key = f"forward_fcff_{year}y"
        engine_metric = input_metrics.get(key)
        period = str(forecast.get("period") or "")
        check = {
            "year": year,
            "engine_key": key,
            "bridge_value": forecast.get("value"),
            "bridge_period": forecast.get("period"),
            "engine_value": _metric_value(engine_metric),
            "engine_period": engine_metric.get("period") if isinstance(engine_metric, Mapping) else None,
            "bridge_as_of": forecast.get("as_of"),
            "engine_as_of": engine_metric.get("as_of") if isinstance(engine_metric, Mapping) else None,
            "start_date": forecast.get("start_date"),
            "end_date": forecast.get("end_date"),
        }
        if engine_metric is None:
            errors.append(f"missing DCF engine input {key}")
        else:
            for field in ("value", "period", "as_of"):
                if forecast.get(field) != engine_metric.get(field):
                    errors.append(
                        f"{field} mismatch for {key}: bridge={forecast.get(field)} engine={engine_metric.get(field)}"
                    )
        if not period.upper().startswith("FY") or "TTM" in period.upper() or "NTM" in period.upper():
            errors.append(f"DCF forecast {key} is not a full fiscal-year period: {period}")
        if not forecast.get("start_date") or not forecast.get("end_date"):
            errors.append(f"DCF forecast {key} is missing fiscal start/end dates")
        checks.append(check)

    return {
        "status": "ok" if not errors else "failed",
        "dcf_available": True,
        "forecast_count": len(forecasts),
        "engine_fcff_input_keys": sorted(key for key in input_metrics if "fcff" in key),
        "checks": checks,
        "errors": errors,
    }


def _case(
    ticker: str,
    source_result: Mapping[str, Any],
    missing_year: int | None = None,
) -> tuple[dict[str, Any], bool]:
    raw_sources = copy.deepcopy(source_result["raw_sources"])
    if missing_year is not None:
        estimates = raw_sources["forward_estimates"]["payload"]
        for key in (
            f"forward_revenue_{missing_year}y",
            f"forward_revenue_{missing_year}y_source_type",
            f"forward_revenue_{missing_year}y_period",
            f"forward_revenue_{missing_year}y_notes",
        ):
            estimates[key] = None

    provider = _ReplayProvider(raw_sources)
    data_service = FinancialDataService(provider, cache=MemoryTTLCache(), timeout=provider.timeout)
    response = ValuationService(data_service).compute(ticker, bypass_cache=True)
    response_json = response.model_dump(mode="json")
    dcf = response_json["valuations"]["dcf"]
    consistency = _consistency(response_json)
    bridge_forecasts = (response_json.get("financial_bridge") or {}).get("dcf_forecasts") or []
    projected_values = [Decimal(str(item["value"])) for item in bridge_forecasts if item.get("value") is not None]
    expected_available = (
        missing_year is None
        and len(projected_values) == 2
        and all(value.is_finite() and value > Decimal("0") for value in projected_values)
    )
    errors: list[str] = []
    if len(provider.calls) != len(RAW_CATEGORIES) or set(provider.calls) != set(RAW_CATEGORIES):
        errors.append(f"replay did not traverse all seven provider methods: {provider.calls}")
    if dcf.get("available") != expected_available:
        errors.append(
            f"unexpected DCF availability for missing_fy{missing_year}: "
            f"expected={expected_available} actual={dcf.get('available')}"
        )
    if consistency["status"] != "ok":
        errors.extend(consistency.get("errors") or [])
    snapshot = data_service.get_snapshot(ticker)
    result = {
        "ticker": ticker,
        "case": "complete" if missing_year is None else f"missing_fy{missing_year}",
        "input_kind": "historical_r5_live_provider_payload_replay",
        "source_raw_categories": sorted(raw_sources),
        "provider_calls": provider.calls,
        "snapshot": {
            "forecast_fiscal_year_end": snapshot.forecast_fiscal_year_end.isoformat() if snapshot.forecast_fiscal_year_end else None,
            "revenue_estimate_1y_period": snapshot.revenue_estimate_1y.period if snapshot.revenue_estimate_1y else None,
            "revenue_estimate_2y_period": snapshot.revenue_estimate_2y.period if snapshot.revenue_estimate_2y else None,
            "revenue_estimate_1y_source_type": snapshot.revenue_estimate_1y.source_type.value if snapshot.revenue_estimate_1y else None,
            "revenue_estimate_2y_source_type": snapshot.revenue_estimate_2y.source_type.value if snapshot.revenue_estimate_2y else None,
        },
        "dcf": {
            "available": dcf.get("available"),
            "expected_available": expected_available,
            "unavailable_reason": dcf.get("unavailable_reason"),
            "input_metrics": dcf.get("input_metrics"),
        },
        "consistency": consistency,
        "response": response_json,
        "status": "ok" if not errors else "failed",
        "errors": errors,
    }
    return result, not errors


def main() -> int:
    artifact = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    by_ticker = {item["ticker"]: item for item in artifact.get("results", [])}
    results: list[dict[str, Any]] = []
    all_ok = True
    for ticker in TICKERS:
        source_result = by_ticker.get(ticker)
        if source_result is None:
            result = {"ticker": ticker, "status": "failed", "errors": ["missing R5 source result"]}
            results.append(result)
            all_ok = False
            continue
        for missing_year in (None, 1, 2):
            try:
                result, ok = _case(ticker, source_result, missing_year=missing_year)
            except Exception as exc:
                result = {
                    "ticker": ticker,
                    "case": "complete" if missing_year is None else f"missing_fy{missing_year}",
                    "status": "failed",
                    "errors": [f"{type(exc).__name__}: {exc}"],
                }
                ok = False
            results.append(result)
            all_ok = all_ok and ok
            print(
                json.dumps(
                    {
                        "ticker": ticker,
                        "case": result.get("case"),
                        "status": result.get("status"),
                        "dcf_available": (result.get("dcf") or {}).get("available"),
                        "snapshot_periods": result.get("snapshot"),
                        "consistency": result.get("consistency"),
                        "errors": result.get("errors"),
                    },
                    ensure_ascii=False,
                    default=str,
                ),
                flush=True,
            )

    output = {
        "schema": "valuation-ai-audit-r6-replay-v1",
        "input_artifact": str(INPUT_PATH.relative_to(ROOT)).replace("\\", "/"),
        "input_collected_at": artifact.get("collected_at"),
        "input_provider_kind": artifact.get("provider_kind"),
        "replay_provider_kind": "offline_replay_of_historical_live_payload",
        "is_demo": False,
        "tickers": list(TICKERS),
        "cases_per_ticker": ["complete", "missing_fy1", "missing_fy2"],
        "results": results,
        "overall_status": "ok" if all_ok else "failed",
    }
    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {"artifact": str(OUTPUT_PATH), "overall_status": output["overall_status"]},
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
