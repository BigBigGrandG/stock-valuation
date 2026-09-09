"""Read-only coordinator probe of provider data availability and periods."""
import json
from pathlib import Path
import yfinance as yf

company = yf.Ticker("NVDA")
info = company.get_info()
keys = ["symbol", "shortName", "currency", "financialCurrency", "exchange", "quoteType",
        "regularMarketPrice", "regularMarketTime", "sharesOutstanding", "forwardEps",
        "trailingEps", "totalCash", "totalDebt", "lastFiscalYearEnd", "nextFiscalYearEnd",
        "mostRecentQuarter", "earningsGrowth", "revenueGrowth"]
output = {"info": {k: info.get(k) for k in keys}}
print(json.dumps(output), flush=True)
for category, method in [("cash_flow", company.get_cash_flow), ("income", company.get_income_stmt),
                         ("balance", company.get_balance_sheet)]:
    frame = method(freq="yearly")
    output[category] = json.loads(frame.to_json(date_format="iso"))
    print(category, "columns", [str(c) for c in frame.columns], "rows", list(frame.index), flush=True)
Path(__file__).with_name("source-NVDA.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
