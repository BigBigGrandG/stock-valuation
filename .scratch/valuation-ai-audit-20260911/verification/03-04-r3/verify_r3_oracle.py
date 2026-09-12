"""Assert R3 mapping boundaries and numerically replay saved live inputs.

The script has two deliberately separate checks:

* ``api_output_checks`` inspect the newly captured HTTP response and verify
  the fade recurrence and cash-flow arithmetic with Decimal values.
* ``raw_input_replay`` rebuilds provider boundary models from the saved raw
  provider outputs, then runs the real Normalizer -> FinancialDataService ->
  ValuationService path offline and compares key API results.

``--corrupt-demo`` writes a separate controlled copy, changes one saved growth
rate, and runs the same oracle so the failure path is proven nonzero without
touching the original live artifact.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[4]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.environ["DATA_PROVIDER"] = "live"

from app.config import DEFAULT_ASSUMPTIONS  # noqa: E402
from app.providers.base import (  # noqa: E402
    BalanceSheetData,
    CashFlowData,
    CompanyProfileData,
    ForwardEstimatesData,
    HistoricalMultiplesData,
    IncomeStatementData,
    QuoteData,
)
from app.services.multiples import industry_multiple_payload, lookup_industry_benchmark  # noqa: E402
from app.services.valuation_service import (  # noqa: E402
    FinancialDataService,
    MemoryTTLCache,
    ValuationService,
)


def _decimal(value: Any) -> Decimal:
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise AssertionError(f"not a finite decimal: {value!r}") from exc
    if not parsed.is_finite():
        raise AssertionError(f"not a finite decimal: {value!r}")
    return parsed


def _close(left: Any, right: Any, tolerance: Decimal = Decimal("0.02")) -> bool:
    return abs(_decimal(left) - _decimal(right)) <= tolerance


def _assert_decimal(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def _check_scenario(scenario: Mapping[str, Any], *, ticker: str, failures: list[str]) -> dict[str, Any]:
    name = str(scenario.get("scenario"))
    rates = scenario.get("projection_growth_rates") or []
    projections = scenario.get("fcff_projections") or []
    start = scenario.get("growth_start")
    terminal = scenario.get("terminal_growth")
    numeric: dict[str, Any] = {
        "scenario": name,
        "rates_count": len(rates),
        "cashflows_count": len(projections),
        "g3_expected": None,
        "g4_expected": None,
        "g5_expected": None,
        "cashflow_checks": [],
        "passed": True,
    }
    if len(rates) != 5 or len(projections) != 5 or rates[0] is not None:
        failures.append(f"{ticker}/{name}: expected five rates/cashflows with g1=null")
        numeric["passed"] = False
        return numeric
    try:
        growth_start = _decimal(start)
        terminal_growth = _decimal(terminal)
        expected_rates = [
            None,
            _decimal(rates[1]),
            growth_start + (Decimal(1) / Decimal(3)) * (terminal_growth - growth_start),
            growth_start + (Decimal(2) / Decimal(3)) * (terminal_growth - growth_start),
            terminal_growth,
        ]
        numeric["g3_expected"] = str(expected_rates[2])
        numeric["g4_expected"] = str(expected_rates[3])
        numeric["g5_expected"] = str(expected_rates[4])
        for index in (2, 3, 4):
            passed = _close(rates[index], expected_rates[index], Decimal("0.0000000000000000000001"))
            _assert_decimal(passed, f"{ticker}/{name}: g{index + 1}={rates[index]!r} != expected {expected_rates[index]}", failures)
            numeric["passed"] = numeric["passed"] and passed

        for index in range(2, 5):
            expected_cashflow = _decimal(projections[index - 1]) * (Decimal(1) + _decimal(rates[index]))
            passed = _close(projections[index], expected_cashflow)
            cashflow_check = {
                "year": index + 1,
                "expected": str(expected_cashflow),
                "actual": str(projections[index]),
                "passed": passed,
            }
            numeric["cashflow_checks"].append(cashflow_check)
            _assert_decimal(
                passed,
                f"{ticker}/{name}: FCFF year {index + 1}={projections[index]!r} != prior-growth result {expected_cashflow}",
                failures,
            )
            numeric["passed"] = numeric["passed"] and passed

        year6 = scenario.get("fcff_year6")
        expected_year6 = _decimal(projections[4]) * (Decimal(1) + terminal_growth)
        year6_passed = _close(year6, expected_year6)
        numeric["year6"] = {
            "expected": str(expected_year6),
            "actual": str(year6),
            "passed": year6_passed,
        }
        _assert_decimal(year6_passed, f"{ticker}/{name}: FCFF year 6 does not use g5 terminal growth", failures)
        numeric["passed"] = numeric["passed"] and year6_passed
    except (AssertionError, IndexError, TypeError, ValueError) as exc:
        failures.append(f"{ticker}/{name}: numeric replay error: {exc}")
        numeric["passed"] = False
    return numeric


def _api_output_checks(live: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    failures: list[str] = []
    checks: dict[str, Any] = {}
    for ticker, result in (live.get("results") or {}).items():
        result = result or {}
        summary = result.get("summary") or {}
        api_response = result.get("api_response") or {}
        body = api_response.get("body") if isinstance(api_response, Mapping) else None
        ticker_checks: dict[str, Any] = {
            "status_code": summary.get("status_code"),
            "provider_method_count": len(result.get("provider_raw_inputs") or {}),
            "scenarios": [],
            "passed": True,
        }
        if ticker_checks["provider_method_count"] != 7:
            failures.append(f"{ticker}: raw provider input omitted one of seven methods")
            ticker_checks["passed"] = False
        if summary.get("status_code") != 200 or not isinstance(body, Mapping):
            failures.append(f"{ticker}: expected HTTP 200 API response for output replay")
            ticker_checks["passed"] = False
            checks[ticker] = ticker_checks
            continue
        valuations = body.get("valuations") or {}
        dcf = valuations.get("dcf") or {}
        if dcf.get("available"):
            for scenario in dcf.get("dcf_scenarios") or []:
                numeric = _check_scenario(scenario, ticker=ticker, failures=failures)
                ticker_checks["scenarios"].append(numeric)
                ticker_checks["passed"] = ticker_checks["passed"] and numeric["passed"]
            if not ticker_checks["scenarios"]:
                failures.append(f"{ticker}: DCF marked available without scenarios")
                ticker_checks["passed"] = False
        else:
            ticker_checks["dcf_unavailable_reason"] = dcf.get("unavailable_reason")
            # Unavailability is valid only when the API explains the model
            # gate; this includes the expected bank boundary and missing FCFF.
            reason = str(dcf.get("unavailable_reason") or "").lower()
            gate_ok = any(term in reason for term in ("not applicable", "no fcff", "fcfe cannot"))
            _assert_decimal(gate_ok, f"{ticker}: DCF unavailable without an eligibility reason", failures)
            ticker_checks["passed"] = ticker_checks["passed"] and gate_ok
        checks[ticker] = ticker_checks
    return checks, failures


class ReplayProvider:
    """Provider made only from the saved live raw boundary models."""

    is_demo = False
    timeout = 25.0

    def __init__(self, raw: Mapping[str, Any]):
        self.raw = raw

    def _value(self, method: str, model: Any) -> Any:
        data = self.raw.get(method)
        if not isinstance(data, Mapping):
            raise AssertionError(f"missing raw replay input {method}")
        return model.model_validate(data)

    def get_quote(self, ticker: str, budget: Any = None) -> QuoteData:
        return self._value("get_quote", QuoteData)

    def get_company_profile(self, ticker: str, budget: Any = None) -> CompanyProfileData:
        return self._value("get_company_profile", CompanyProfileData)

    def get_balance_sheet(self, ticker: str, budget: Any = None) -> BalanceSheetData:
        return self._value("get_balance_sheet", BalanceSheetData)

    def get_cash_flow(self, ticker: str, budget: Any = None) -> CashFlowData:
        return self._value("get_cash_flow", CashFlowData)

    def get_income_statement(self, ticker: str, budget: Any = None) -> IncomeStatementData:
        return self._value("get_income_statement", IncomeStatementData)

    def get_forward_estimates(self, ticker: str, budget: Any = None) -> ForwardEstimatesData:
        return self._value("get_forward_estimates", ForwardEstimatesData)

    def get_historical_multiples(self, ticker: str, budget: Any = None) -> HistoricalMultiplesData:
        return self._value("get_historical_multiples", HistoricalMultiplesData)


def _raw_input_replay(live: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    failures: list[str] = []
    replay_checks: dict[str, Any] = {}
    for ticker, result in (live.get("results") or {}).items():
        result = result or {}
        raw = result.get("provider_raw_inputs") or {}
        api_response = result.get("api_response") or {}
        body = api_response.get("body") if isinstance(api_response, Mapping) else None
        if result.get("summary", {}).get("status_code") != 200 or not isinstance(body, Mapping):
            replay_checks[ticker] = {"skipped": True, "reason": "API response was not HTTP 200"}
            continue
        try:
            service = ValuationService(
                FinancialDataService(
                    provider=ReplayProvider(raw),
                    cache=MemoryTTLCache(),
                    default_assumptions=DEFAULT_ASSUMPTIONS,
                ),
                default_assumptions=DEFAULT_ASSUMPTIONS,
            )
            replayed = service.compute(ticker)
            replayed_body = replayed.model_dump(mode="json")
            expected_assumptions = body.get("assumptions_used") or {}
            actual_assumptions = replayed_body.get("assumptions_used") or {}
            checks = {
                "ticker_matches": replayed_body.get("ticker") == body.get("ticker"),
                "pe_layer_matches": actual_assumptions.get("pe_selection_layer") == expected_assumptions.get("pe_selection_layer"),
                "ev_layer_matches": actual_assumptions.get("ev_ebitda_selection_layer") == expected_assumptions.get("ev_ebitda_selection_layer"),
                "dcf_available_matches": (replayed_body.get("valuations", {}).get("dcf", {}).get("available"))
                == (body.get("valuations", {}).get("dcf", {}).get("available")),
            }
            api_dcf = (body.get("valuations") or {}).get("dcf") or {}
            replay_dcf = (replayed_body.get("valuations") or {}).get("dcf") or {}
            if api_dcf.get("available") and replay_dcf.get("available"):
                checks["dcf_base_price_matches"] = _close(
                    (replay_dcf.get("base") or {}).get("price_per_share"),
                    (api_dcf.get("base") or {}).get("price_per_share"),
                )
            passed = all(checks.values())
            checks["passed"] = passed
            replay_checks[ticker] = checks
            if not passed:
                failures.append(f"{ticker}: raw-input replay mismatch: {checks}")
        except Exception as exc:  # noqa: BLE001 - capture per-ticker replay failure
            replay_checks[ticker] = {"passed": False, "error_type": type(exc).__name__, "error": str(exc)}
            failures.append(f"{ticker}: raw-input replay raised {type(exc).__name__}: {exc}")
    return replay_checks, failures


def _mapping_checks() -> tuple[list[dict[str, Any]], list[str]]:
    cases = [
        {"sector": "Technology", "industry": "Software", "expected": None},
        {
            "sector": "Communication Services",
            "industry": "Internet Content & Information",
            "expected": None,
        },
        {"sector": "Technology", "industry": "Semiconductors", "expected": "Semiconductor"},
        {
            "sector": "Consumer Defensive",
            "industry": "Beverages - Non-Alcoholic",
            "expected": None,
        },
    ]
    checks: list[dict[str, Any]] = []
    failures: list[str] = []
    for case in cases:
        benchmark = lookup_industry_benchmark(case["sector"], case["industry"])
        payload = industry_multiple_payload(case["sector"], case["industry"])
        actual = benchmark.name if benchmark else None
        passed = actual == case["expected"]
        checks.append(
            {
                "input": case,
                "actual": actual,
                "expected_match": passed,
                "mapping_key": payload.get("industry_mapping_key"),
                "mapping_source": payload.get("industry_mapping_source"),
                "unavailable_reason": payload.get("industry_unavailable_reason"),
            }
        )
        if not passed:
            failures.append(f"mapping {case}: actual={actual!r}, expected={case['expected']!r}")
    return checks, failures


def _corrupt_copy(live_path: Path) -> Path:
    corrupted_path = live_path.with_name("live_results_r3.corrupt-control.json")
    corrupted = json.loads(live_path.read_text(encoding="utf-8"))
    for result in (corrupted.get("results") or {}).values():
        body = ((result.get("api_response") or {}).get("body") or {})
        dcf = ((body.get("valuations") or {}).get("dcf") or {})
        scenarios = dcf.get("dcf_scenarios") or []
        if dcf.get("available") and scenarios:
            # Change only the copied API result; provider raw inputs and the
            # original live_results_r3.json stay untouched.
            rates = scenarios[0].get("projection_growth_rates") or []
            if len(rates) >= 3:
                rates[2] = "999"
                corrupted_path.write_text(
                    json.dumps(corrupted, indent=2, ensure_ascii=False), encoding="utf-8"
                )
                return corrupted_path
    raise RuntimeError("could not find an available DCF scenario to corrupt")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path(__file__).with_name("live_results_r3.json"))
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("oracle_r3.json"))
    parser.add_argument("--corrupt-demo", action="store_true")
    args = parser.parse_args()

    input_path = args.input
    if args.corrupt_demo:
        input_path = _corrupt_copy(input_path)
    live = json.loads(input_path.read_text(encoding="utf-8"))
    mapping, mapping_failures = _mapping_checks()
    api_checks, api_failures = _api_output_checks(live)
    raw_replay, raw_failures = _raw_input_replay(live)
    failures = [*mapping_failures, *api_failures, *raw_failures]
    output = {
        "input": str(input_path.relative_to(ROOT)) if input_path.is_relative_to(ROOT) else str(input_path),
        "corrupt_demo": args.corrupt_demo,
        "mapping_checks": mapping,
        "api_output_checks": api_checks,
        "raw_input_replay": raw_replay,
        "failures": failures,
        "passed": not failures,
    }
    args.output.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"R3 oracle input: {input_path}")
    print(f"R3 oracle output: {args.output}")
    print(f"mapping_checks={len(mapping)} api_tickers={len(api_checks)} raw_replay_tickers={len(raw_replay)}")
    if failures:
        print(f"R3 oracle FAIL ({len(failures)} failures)")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("R3 oracle PASS: mapping boundaries and numeric raw-input replay verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
