"""Replay saved live outputs and record exact industry-mapping boundaries."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.multiples import industry_multiple_payload, lookup_industry_benchmark


def main() -> None:
    root = ROOT
    live_path = Path(__file__).with_name("live_results.json")
    live = json.loads(live_path.read_text(encoding="utf-8"))

    boundary_inputs = [
        {"sector": "Technology", "industry": "Software", "expected": None},
        {
            "sector": "Technology",
            "industry": "Internet Content & Information",
            "expected": "Software (Internet)",
        },
        {"sector": "Technology", "industry": "Semiconductors", "expected": "Semiconductor"},
    ]
    boundaries = []
    for item in boundary_inputs:
        benchmark = lookup_industry_benchmark(item["sector"], item["industry"])
        payload = industry_multiple_payload(item["sector"], item["industry"])
        boundaries.append(
            {
                "input": item,
                "result": benchmark.name if benchmark else None,
                "sample_size": benchmark.sample_size if benchmark else None,
                "forward_pe": str(benchmark.forward_pe) if benchmark else None,
                "mapping_key": payload.get("industry_mapping_key"),
                "mapping_source": payload.get("industry_mapping_source"),
                "ev_basis": payload.get("industry_ev_ebitda_basis"),
                "expected_match": benchmark is not None
                and benchmark.name == item["expected"],
            }
        )

    replay = {}
    for ticker, value in live.items():
        summary = value.get("summary", {})
        raw = value.get("raw_response") or {}
        dcf = (raw.get("valuations") or {}).get("dcf") or {}
        scenarios = dcf.get("dcf_scenarios") or []
        fade_checks = []
        for scenario in scenarios:
            rates = scenario.get("projection_growth_rates") or []
            terminal = scenario.get("terminal_growth")
            fade_checks.append(
                {
                    "scenario": scenario.get("scenario"),
                    "five_rates": len(rates) == 5,
                    "g5_equals_terminal": bool(rates) and rates[-1] == terminal,
                    "formula_contains_g_start": "g_start" in str(
                        scenario.get("growth_fade_formula")
                        or (scenario.get("formulas") or {}).get("growth_fade")
                    ),
                }
            )
        replay[ticker] = {
            "input_source": str(live_path.relative_to(root)),
            "status": summary.get("status"),
            "selection_layers": summary.get("selection_layers"),
            "raw_response_replayed": bool(raw),
            "dcf_available": bool(dcf.get("available")),
            "fade_checks": fade_checks,
            "fade_checks_applicable": bool(dcf.get("available")),
            "all_fade_checks_pass": not dcf.get("available")
            or bool(fade_checks)
            and all(
                check["five_rates"]
                and check["g5_equals_terminal"]
                and check["formula_contains_g_start"]
                for check in fade_checks
            ),
        }

    output = Path(__file__).with_name("boundary_replay.json")
    output.write_text(
        json.dumps(
            {"boundaries": boundaries, "replay": replay},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"Boundary/replay evidence written to {output}")
    for item in boundaries:
        print(
            f"{item['input']['industry']!r}: result={item['result']!r}; "
            f"expected_match={item['expected_match']}"
        )
    for ticker, item in replay.items():
        print(
            f"{ticker}: status={item['status']}; raw_response_replayed="
            f"{item['raw_response_replayed']}; dcf_available={item['dcf_available']}; "
            f"fade_pass={item['all_fade_checks_pass']}"
        )


if __name__ == "__main__":
    main()
