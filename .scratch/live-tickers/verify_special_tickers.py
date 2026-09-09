import json
import urllib.request
import urllib.error
from pathlib import Path

BASE = "http://127.0.0.1:8002"
OUT = Path("D:/workshop/stock-valuation/.scratch/live-tickers/coordinator-live")
OUT.mkdir(exist_ok=True)

def fetch(ticker):
    url = f"{BASE}/api/v1/valuation/{ticker}"
    req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
            return r.status, data
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode())
        except Exception:
            body = e.read().decode()
        return e.code, body
    except Exception as e:
        return 500, str(e)

results = {}

# 1. JPM (Bank)
status, data = fetch("JPM")
print(f"JPM: status={status}")
if status == 200:
    print(f"  JPM Company: {data.get('company_name')}, price: {data.get('current_price')}")
    for k, m in data.get("valuations", {}).items():
        print(f"    {k}: available={m.get('available')}, reason={m.get('unavailable_reason')}")
    OUT.joinpath("JPM.json").write_text(encoding="utf-8", data=json.dumps(data, indent=2, ensure_ascii=False))
results["JPM"] = {"status": status, "data": data}

# 2. BRK.B / BRK-B (Dual-class / Insurance)
status, data = fetch("BRK.B")
print(f"BRK.B: status={status}")
if status == 200:
    print(f"  BRK.B Company: {data.get('company_name')}, price: {data.get('current_price')}")
    for k, m in data.get("valuations", {}).items():
        print(f"    {k}: available={m.get('available')}, reason={m.get('unavailable_reason')}")
    OUT.joinpath("BRK_B.json").write_text(encoding="utf-8", data=json.dumps(data, indent=2, ensure_ascii=False))
results["BRK.B"] = {"status": status, "data": data}

# 3. RIVN (Loss-maker)
status, data = fetch("RIVN")
print(f"RIVN: status={status}")
if status == 200:
    print(f"  RIVN Company: {data.get('company_name')}, price: {data.get('current_price')}")
    for k, m in data.get("valuations", {}).items():
        print(f"    {k}: available={m.get('available')}, reason={m.get('unavailable_reason')}")
    OUT.joinpath("RIVN.json").write_text(encoding="utf-8", data=json.dumps(data, indent=2, ensure_ascii=False))
results["RIVN"] = {"status": status, "data": data}

# 4. TSM (ADR non-USD statements)
status, data = fetch("TSM")
print(f"TSM: status={status}")
if status == 200:
    print(f"  TSM Company: {data.get('company_name')}, price: {data.get('current_price')}")
    for k, m in data.get("valuations", {}).items():
        print(f"    {k}: available={m.get('available')}, reason={m.get('unavailable_reason')}")
    OUT.joinpath("TSM.json").write_text(encoding="utf-8", data=json.dumps(data, indent=2, ensure_ascii=False))
results["TSM"] = {"status": status, "data": data}

# 5. SPY (ETF -> expect 422)
status, data = fetch("SPY")
print(f"SPY: status={status}, data={data}")
OUT.joinpath("SPY.json").write_text(encoding="utf-8", data=json.dumps({"status": status, "response": data}, indent=2, ensure_ascii=False))
results["SPY"] = {"status": status, "data": data}

# 6. INVALIDZZZZ (Unknown -> expect 404)
status, data = fetch("INVALIDZZZZ")
print(f"INVALIDZZZZ: status={status}, data={data}")
OUT.joinpath("INVALIDZZZZ.json").write_text(encoding="utf-8", data=json.dumps({"status": status, "response": data}, indent=2, ensure_ascii=False))
results["INVALIDZZZZ"] = {"status": status, "data": data}

print("\n--- Summary of Special Checks ---")
assert results["SPY"]["status"] == 422, f"SPY must return 422, got {results['SPY']['status']}"
assert results["INVALIDZZZZ"]["status"] == 404, f"INVALIDZZZZ must return 404, got {results['INVALIDZZZZ']['status']}"

# TSM: Listed ADR in USD -> 200 OK; Forward P/E available in USD; statement-dependent models disabled with currency mismatch reason
assert results["TSM"]["status"] == 200, f"TSM must return 200, got {results['TSM']['status']}"
tsm_val = results["TSM"]["data"]["valuations"]
assert tsm_val["forward_pe"]["available"] is True, "TSM Forward P/E must be available (both Quote and Forward EPS in USD per ADS)"
assert tsm_val["ev_ebitda"]["available"] is False, "TSM EV/EBITDA must be disabled due to statement currency mismatch"
assert "currency mismatch" in tsm_val["ev_ebitda"]["unavailable_reason"].lower(), "TSM EV/EBITDA must give currency mismatch reason"
assert tsm_val["fcf_yield"]["available"] is False, "TSM FCF Yield must be disabled due to statement currency mismatch"
assert tsm_val["dcf"]["available"] is False, "TSM DCF must be disabled due to statement currency mismatch"
assert results["TSM"]["data"]["composite"]["available"] is True, "TSM composite must be available using Forward P/E"

# JPM: Bank -> 200 OK, Forward P/E available, others disabled for banks
assert results["JPM"]["status"] == 200, f"JPM must return 200, got {results['JPM']['status']}"
assert results["JPM"]["data"]["valuations"]["forward_pe"]["available"] is True
assert results["JPM"]["data"]["valuations"]["ev_ebitda"]["available"] is False

# BRK.B: Dual-class / Insurance -> 200 OK, Forward P/E available, others disabled for insurance
assert results["BRK.B"]["status"] == 200, f"BRK.B must return 200, got {results['BRK.B']['status']}"
assert results["BRK.B"]["data"]["valuations"]["forward_pe"]["available"] is True
assert results["BRK.B"]["data"]["valuations"]["ev_ebitda"]["available"] is False

# RIVN: Loss-maker -> 200 OK, models unavailable
assert results["RIVN"]["status"] == 200, f"RIVN must return 200, got {results['RIVN']['status']}"
assert results["RIVN"]["data"]["valuations"]["forward_pe"]["available"] is False

print("ALL SPECIAL TICKER ASSERTIONS PASSED!")

