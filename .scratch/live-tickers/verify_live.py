"""Coordinator live acceptance: arbitrary ticker lookup must use real inputs."""
import json
import sys
from decimal import Decimal as D, ROUND_HALF_UP
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

BASE = "http://127.0.0.1:8002"
TICKERS = sys.argv[1:] or ["NVDA", "AAPL", "MSFT", "AVGO", "KO"]
OUT = Path(__file__).parent / "coordinator-live"
OUT.mkdir(exist_ok=True)

def fetch(ticker, body=None):
    req = Request(BASE + "/api/v1/valuation/" + ticker,
                  data=None if body is None else json.dumps(body).encode(),
                  headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=90) as r:
            return r.status, json.load(r)
    except HTTPError as e:
        return e.code, e.read().decode()

def rounded(v):
    return v.quantize(D("0.01"), rounding=ROUND_HALF_UP)

names, quotes = set(), set()
for ticker in TICKERS:
    status, data = fetch(ticker)
    assert status == 200, (ticker, status, data)
    assert data["ticker"] == ticker and data["is_demo"] is False, (ticker, "not real result")
    assert D(data["current_price"]) > 0
    assert "2025-01-15" not in str(data["as_of"]), "old fixture timestamp reused"
    assert "only supports: AVGO" not in json.dumps(data)
    names.add(data["company_name"])
    quotes.add(data["current_price"])
    available = []
    for key, model in data["valuations"].items():
        if not model["available"]:
            assert model.get("unavailable_reason"), (ticker, key, "missing failure explanation")
            continue
        available.append(key)
        values = [D(model[s]["price_per_share"]) for s in ("low", "base", "high")]
        assert 0 < values[0] <= values[1] <= values[2], (ticker, key, values)
        assert model["formula"] and model["calculation_steps"]
        for mapping in ("input_metrics", "assumption_metrics"):
            assert model.get(mapping)
            for metric in model[mapping].values():
                assert metric["source_type"] != "fixture", (ticker, key, metric)
                assert {"source", "period", "as_of", "unit", "value", "is_estimated", "confidence"} <= metric.keys()
        if key == "dcf":
            for scenario in model["dcf_scenarios"]:
                flows = list(map(D, scenario["fcff_projections"]))
                wacc, g = D(scenario["wacc"]), D(scenario["terminal_growth"])
                assert len(flows) == 5 and wacc > g and g <= D("0.05")
                pvs = [rounded(v / (1 + wacc) ** n) for n, v in enumerate(flows, 1)]
                assert list(map(D, scenario["pv_projections"])) == pvs
                assert D(scenario["terminal_value"]) == rounded(flows[-1] * (1+g) / (wacc-g))
    assert available, (ticker, "no usable model", data.get("warnings"))
    composite = data["composite"]
    assert composite["available"]
    assert sum(map(D, composite["weights_used"].values())) == 1
    OUT.joinpath(ticker + ".json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"PASS {ticker}: {data['company_name']}; quote={data['current_price']}; models={','.join(available)}", flush=True)

assert len(names) == len(TICKERS) and len(quotes) == len(TICKERS), "ticker values appear cloned"
print("PASS: real distinct multi-ticker lookup, metadata, applicable models, DCF arithmetic and composite")
