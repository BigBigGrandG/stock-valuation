import json
import yfinance as yf
from decimal import Decimal
from pathlib import Path

reconciliation = []

for ticker in ["NVDA", "KO", "TSM"]:
    t = yf.Ticker(ticker)
    bs = t.balance_sheet
    cf = t.cashflow
    fin = t.financials
    info = t.info

    # Load normalized response
    norm_path = Path(f"D:/workshop/stock-valuation/.scratch/live-tickers/coordinator-live/{ticker}.json")
    with open(norm_path, encoding="utf-8") as f:
        norm = json.load(f)

    shared_inputs = (
        norm.get("valuations", {}).get("ev_ebitda", {}).get("input_metrics", {})
        or norm.get("valuations", {}).get("forward_pe", {}).get("input_metrics", {})
    )
    norm_shares = shared_inputs.get("diluted_shares", {})
    norm_price = shared_inputs.get("current_price", {})

    reconciliation.append(f"# Raw-Source-to-Normalized Reconciliation for {ticker}: {norm.get('company_name')}\n")
    reconciliation.append(f"- **Current Market Price**: `${norm.get('current_price')}` (Source: `{norm_price.get('source')}`, Timestamp: `{norm.get('price_timestamp')}`)")
    reconciliation.append(f"- **Diluted Shares**: `{norm_shares.get('value')}` {norm_shares.get('unit')} (Source: `{norm_shares.get('source')}`, Period: `{norm_shares.get('period')}`, Notes: `{norm_shares.get('notes')}`)\n")
    if ticker == "TSM":
        reconciliation.append("## ADR & Currency Basis Analysis (TSM)")
        reconciliation.append("- **Security Type**: American Depositary Receipt (ADR) listed on NYSE (NYQ)")
        reconciliation.append("- **Quote Currency**: `USD` ($439.00)")
        reconciliation.append("- **Financial Statement Currency**: `TWD` (Taiwan New Dollars)")
        reconciliation.append("- **Share Basis**: 5,180,000,000 ADSs (1 ADS represents 5 underlying TWSE:2330 ordinary shares)")
        reconciliation.append("- **Forward EPS**: `$16.93` (0y) / `$21.93` (+1y) denominated in USD per ADS")
        reconciliation.append("- **Engine Isolation**: Forward P/E is **AVAILABLE** because EPS and Price share the identical USD/ADS basis. EV/EBITDA, FCF Yield, and DCF are **DISABLED** with explicit reason 'Currency mismatch: quote currency (USD) differs from statement reporting currency (TWD) without FX conversion'. Fictitious FX conversions are never invented.\n")

    # 1. Balance Sheet Reconciliation
    reconciliation.append("## 1. Balance Sheet Reconciliation")
    if bs is not None and not bs.empty:
        col = bs.columns[0]
        reconciliation.append(f"- **Latest Balance Sheet Statement Column Date**: `{col}`")
        s = bs[col]
        
        raw_cash_fields = {}
        for k in ["Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents", "Cash Financial", "Other Short Term Investments"]:
            if k in s.index:
                raw_cash_fields[k] = s.loc[k]
        
        raw_debt_fields = {}
        for k in ["Total Debt", "Long Term Debt", "Current Debt", "Short Long Term Debt"]:
            if k in s.index:
                raw_debt_fields[k] = s.loc[k]

        reconciliation.append(f"- **Raw Balance Sheet Statement Rows**:\n```json\n{json.dumps({k: str(v) for k, v in raw_cash_fields.items()}, indent=2)}\n{json.dumps({k: str(v) for k, v in raw_debt_fields.items()}, indent=2)}\n```")
        
        norm_cash = shared_inputs.get("cash", {})
        norm_debt = shared_inputs.get("total_debt", {})
        norm_net_debt = shared_inputs.get("net_debt", {})
        reconciliation.append(f"- **Normalized Cash**: `{norm_cash.get('value')}` (Source: `{norm_cash.get('source')}`, Period: `{norm_cash.get('period')}`, Units: `{norm_cash.get('unit')}`)")
        reconciliation.append(f"- **Normalized Total Debt**: `{norm_debt.get('value')}` (Source: `{norm_debt.get('source')}`, Period: `{norm_debt.get('period')}`, Units: `{norm_debt.get('unit')}`)")
        reconciliation.append(f"- **Normalized Net Debt**: `{norm_net_debt.get('value')}` (Formula: `total_debt - cash` = {norm_debt.get('value')} - {norm_cash.get('value')} = {norm_net_debt.get('value')})\n")

    # 2. Cash Flow Reconciliation
    reconciliation.append("## 2. Cash Flow Reconciliation & FCFE / FCFF Formulas")
    if cf is not None and not cf.empty:
        col = cf.columns[0]
        reconciliation.append(f"- **Latest Cash Flow Column Date**: `{col}`")
        s = cf[col]
        
        raw_cf_fields = {}
        for k in ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities", "Capital Expenditure", "Purchase Of PPE", "Net Issuance Payments Of Debt", "Net Long Term Debt Issuance", "Issuance Of Debt", "Repayment Of Debt"]:
            if k in s.index:
                raw_cf_fields[k] = s.loc[k]
        
        reconciliation.append(f"- **Raw Cash Flow Statement Rows**:\n```json\n{json.dumps({k: str(v) for k, v in raw_cf_fields.items()}, indent=2)}\n```")

        # Income statement for matching date
        fin_int = None
        fin_tax = None
        if fin is not None and not fin.empty:
            for f_col in fin.columns:
                if str(f_col)[:10] == str(col)[:10]:
                    f_s = fin[f_col]
                    if "Interest Expense" in f_s.index:
                        fin_int = f_s.loc["Interest Expense"]
                    if "Tax Rate For Calcs" in f_s.index:
                        fin_tax = f_s.loc["Tax Rate For Calcs"]
                    break
        reconciliation.append(f"- **Matching Income Statement ({str(col)[:10]})**: Interest Expense = `{fin_int}`, Tax Rate = `{fin_tax}`")

        fcf_inputs = norm.get("valuations", {}).get("fcf_yield", {}).get("input_metrics", {})
        dcf_inputs = norm.get("valuations", {}).get("dcf", {}).get("inputs", {})
        norm_fcfe = fcf_inputs.get("forward_fcfe", {})

        reconciliation.append(f"- **Forward FCFE (FCF Yield Engine)**: `{norm_fcfe.get('value')}` (Period: `{norm_fcfe.get('period')}`, Notes: `{norm_fcfe.get('notes')}`)")
        reconciliation.append(f"- **Forward FCFF Year 1 (DCF Engine)**: `{dcf_inputs.get('fcff_y1')}` (Label: `{dcf_inputs.get('fcff_y1_label')}`)")
        reconciliation.append(f"- **Forward FCFF Year 2 (DCF Engine)**: `{dcf_inputs.get('fcff_y2')}` (Label: `{dcf_inputs.get('fcff_y2_label')}`)")
        reconciliation.append(f"- **Exact DCF Formula**: `{norm.get('valuations', {}).get('dcf', {}).get('formula')}`")
        reconciliation.append(f"- **Exact FCF Yield Formula**: `{norm.get('valuations', {}).get('fcf_yield', {}).get('formula')}`\n")

report_text = "\n".join(reconciliation)
Path("D:/workshop/stock-valuation/.scratch/live-tickers/reconciliation_report.md").write_text(report_text, encoding="utf-8")
print("Reconciliation report successfully updated!")
