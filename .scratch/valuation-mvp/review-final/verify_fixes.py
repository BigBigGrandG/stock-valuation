"""Coordinator verification of the original F1-F7 reproductions."""
from datetime import date
from decimal import Decimal as D
from diagnostics import (
    DEFAULT_ASSUMPTIONS, ScenarioValues, SourceType, ValuationOverrideRequest,
    apply_overrides, metric, model, run_composite, run_dcf, run_ev_ebitda,
    run_forward_pe, snapshot,
)

try:
    snapshot(net_debt="100000000")
except ValueError:
    pass
else:
    raise AssertionError("F1: inconsistent net debt accepted")

for body in ({"forward_pe": {"base": 200}}, {"ev_ebitda": {"base": 200}},
             {"fcf_yield": {"base": 0.5}}):
    try:
        apply_overrides(DEFAULT_ASSUMPTIONS, ValuationOverrideRequest.model_validate(body).to_override_dict())
    except ValueError:
        pass
    else:
        raise AssertionError(("F2: expanded bounds accepted", body))

historical = run_dcf(snapshot(y2=None, revenue_growth="0.40", fcff_growth="0.10"), DEFAULT_ASSUMPTIONS)
assert historical.available
assert historical.dcf_scenarios[1].growth_rate == D("0.10"), "F3: historical FCFF precedence"

for raw in ("1100000", "1400000"):
    result = run_dcf(snapshot(y2=raw), DEFAULT_ASSUMPTIONS)
    assert result.available
    for scenario in result.dcf_scenarios:
        assert D(scenario.growth_metric["value"]) == scenario.growth_rate, "F4: effective metric mismatch"
        assert "cap=" in scenario.growth_metric["notes"] and "floor=" in scenario.growth_metric["notes"]
        assert D(scenario.growth_metric_raw["value"]) == D(raw) / D("1000000") - 1

history = metric("20", "ratio", "5Y median", "history vendor").model_copy(update={
    "source_type": SourceType.ANALYST_ESTIMATE, "as_of": date(2024, 12, 31),
    "is_estimated": True, "confidence": 0.4,
})
data = snapshot().model_copy(update={
    "forward_eps_1y": metric("10"), "forward_ebitda_1y": metric("1000000"),
    "historical_forward_pe": history, "historical_ev_ebitda": history,
})
for engine, key in ((run_forward_pe, "pe_multiple_base"), (run_ev_ebitda, "multiple_base")):
    result = engine(data, DEFAULT_ASSUMPTIONS)
    candidates = result.assumption_metrics
    if key not in candidates:
        key = next(k for k in candidates if k.endswith("_base"))
    observed = candidates[key]
    assert observed["as_of"] == "2024-12-31" and observed["period"] == "5Y median", ("F5", observed)
    assert observed["source_type"] == "analyst_estimate" and observed["confidence"] == 0.4

bad = DEFAULT_ASSUMPTIONS.model_copy(update={
    "dcf_wacc": ScenarioValues(low=D("0.12"), base=D("0.11"), high=D("0.10")),
    "dcf_terminal_growth": ScenarioValues(low=D("0.06"), base=D("0.07"), high=D("0.08")),
})
assert not run_dcf(snapshot(), bad).available, "F6: terminal cap only warns"

equal_weights = DEFAULT_ASSUMPTIONS.model_copy(update={
    "weight_pe": D(1), "weight_ev_ebitda": D(1),
    "weight_fcf_yield": D(1), "weight_dcf": D(0),
})
complete = model("80", "100", "120")
composite = run_composite(D(100), complete, complete, complete, complete, equal_weights)
assert composite.available and sum(composite.weights_used.values()) == D(1), "F7: normalized weights do not sum to one"

print("PASS: original F1-F7 reproductions now reject invalid data or preserve correct calculation/provenance")
