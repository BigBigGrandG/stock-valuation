"""Independent HTTP acceptance checks; run against the final local API."""
import json
import sys
from decimal import Decimal as D, ROUND_HALF_UP
from urllib.request import Request, urlopen
from urllib.error import HTTPError

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8002"

def request(path, body=None):
    req = Request(BASE + path, data=None if body is None else json.dumps(body).encode(),
                  headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=15) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, error.read().decode()

def rounded(value, places="0.01"):
    return value.quantize(D(places), rounding=ROUND_HALF_UP)

path = "/api/v1/valuation/AVGO"
status, default = request(path)
assert status == 200, (status, default)
assert default["is_demo"] and default["data_quality"] == "LOW"
status, snapshot = request("/api/v1/company/AVGO/snapshot")
assert status == 200 and "net_debt" in snapshot
for name, model in default["valuations"].items():
    assert model["available"], (name, model)
    prices = [D(model[s]["price_per_share"]) for s in ("low", "base", "high")]
    assert 0 < prices[0] <= prices[1] <= prices[2], (name, prices)
    assert model["formula"] and model["calculation_steps"]
    for group in ("input_metrics", "assumption_metrics"):
        assert model.get(group), (name, group)
        for key, metric in model[group].items():
            assert {"value", "unit", "period", "source", "source_type", "as_of", "is_estimated"} <= metric.keys(), (name, key, metric)
            assert metric["source_type"] not in {"actual", "analyst_estimate"}, ("demo mislabeled as real source", name, key, metric)

body = {"forward_pe": {"low": 18, "base": 20, "high": 22},
        "ev_ebitda": {"low": 18, "base": 22, "high": 26},
        "fcf_yield": {"low": 0.055, "base": 0.05, "high": 0.045}}
status, overridden = request(path, body)
assert status == 200, (status, overridden)
expected = {
    "forward_pe": [D("19.21") * multiple for multiple in map(D, (18, 20, 22))],
    "ev_ebitda": [(D(118300000000) * multiple - D(35400000000)) / D(4940000000) for multiple in map(D, (18, 22, 26))],
    "fcf_yield": [D(89600000000) / rate / D(4940000000) for rate in map(D, ("0.055", "0.05", "0.045"))],
}
for name, values in expected.items():
    actual = [D(overridden["valuations"][name][scenario]["price_per_share"]) for scenario in ("low", "base", "high")]
    assert actual == list(map(rounded, values)), (name, actual, values)

for scenario in overridden["valuations"]["dcf"]["dcf_scenarios"]:
    flows = list(map(D, scenario["fcff_projections"]))
    wacc, growth = D(scenario["wacc"]), D(scenario["terminal_growth"])
    assert len(flows) == 5 and wacc > growth
    assert growth <= D("0.05"), ("terminal growth exceeds cap", growth)
    assert D(scenario["growth_metric"]["value"]) == D(scenario["growth_rate"]), ("effective growth metadata mismatch", scenario["name"] if "name" in scenario else scenario["growth_rate"])
    pvs = [rounded(flow / (1 + wacc) ** year) for year, flow in enumerate(flows, 1)]
    assert list(map(D, scenario["pv_projections"])) == pvs
    tv = rounded(flows[-1] * (1 + growth) / (wacc - growth))
    pv_tv = rounded(tv / (1 + wacc) ** 5)
    assert D(scenario["terminal_value"]) == tv
    assert abs(D(scenario["pv_terminal_value"]) - pv_tv) <= D("0.01")
    enterprise = sum(pvs) + pv_tv
    assert abs(D(scenario["enterprise_value"]) - enterprise) <= D("0.03")
    equity = enterprise - D(snapshot["total_debt"]["value"]) + D(snapshot["cash"]["value"])
    assert abs(D(scenario["equity_value"]) - equity) <= D("0.03")
    assert D(scenario["price_per_share"]) == rounded(equity / D(snapshot["diluted_shares"]["value"]))
    assert len(scenario["projection_metrics"]) == 5
    periods = scenario["projection_periods"]
    years = [int(period.removeprefix("FY").removesuffix("E")) for period in periods]
    assert years == list(range(years[0], years[0] + 5)), ("nonconsecutive fiscal years", periods)

comp = overridden["composite"]
fv, price = D(comp["fair_value_base"]), D(overridden["current_price"])
assert D(comp["margin_of_safety"]) == rounded((fv-price)/fv, "0.0001")
assert D(comp["upside_downside"]) == rounded((fv-price)/price, "0.0001")
assert abs(sum(map(D, comp["weights_used"].values())) - 1) <= D("0.0001")
status, reset = request(path)
assert status == 200 and reset == default, "POST changed cached defaults"
for invalid in [{"forward_pe": {"base": True}}, {"forward_pe": {"base": []}},
                {"forward_pe": {"base": 200}}, {"ev_ebitda": {"base": 200}},
                {"fcf_yield": {"base": 0.5}},
                {"forward_pe": {"typo": 20}}, {"dcf": {"wacc": 0.01}},
                {"dcf": {"wacc": 0.03, "terminal_growth": 0.03}},
                {"dcf": {"terminal_growth": 0.06}}, {"unknown": 1}]:
    status, response = request(path, invalid)
    assert status == 422, (invalid, status, response)
assert request("/api/v1/valuation/UNKNOWN")[0] == 404
assert request("/api/v1/valuation/INVALID!")[0] == 422
print("PASS: live HTTP, demo provenance, ordered scenarios, independent PE/EV/FCFE arithmetic, MOS/upside, override isolation, invalid requests")
