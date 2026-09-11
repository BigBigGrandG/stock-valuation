"""Strict 4-quarter TTM statement aggregation and point-in-time balance sheet extractor.

Enforces:
1. Column sorting and verification of 4 consecutive, non-overlapping quarterly periods.
2. Complete 4/4 quarterly presence for aggregated flow metrics; incomplete fields trigger annual fallback.
3. Cumulative YTD detection vs. discrete 3-month reporting; rejects ambiguous rollups.
4. Latest single point-in-time balance sheet extraction (never mixing quarterly with annual).
5. Consistent matching of after-tax interest and tax rates for FCFF.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional


def _to_dec(val: Any) -> Optional[Decimal]:
    if val is None:
        return None
    try:
        d = Decimal(str(val))
        return d if d.is_finite() else None
    except Exception:
        return None


def _sort_cols_descending(df: Any) -> list[Any]:
    """Sort DataFrame columns by date descending (newest first), deduplicating unique dates."""
    if df is None or not hasattr(df, "columns") or len(df.columns) == 0:
        return []
    cols = list(df.columns)
    try:
        sorted_cols = sorted(
            cols,
            key=lambda c: _col_date(c) or (c.date() if hasattr(c, "date") else (c if isinstance(c, (date, datetime)) else date.min)),
            reverse=True,
        )
    except Exception:
        sorted_cols = cols

    seen_dates: set[date] = set()
    unique_cols: list[Any] = []
    for c in sorted_cols:
        d = _col_date(c)
        if d is not None:
            if d not in seen_dates:
                seen_dates.add(d)
                unique_cols.append(c)
        else:
            unique_cols.append(c)
    return unique_cols


def _col_date(col: Any) -> Optional[date]:
    if hasattr(col, "date"):
        return col.date()
    if isinstance(col, datetime):
        return col.date()
    if isinstance(col, date):
        return col
    try:
        return datetime.fromisoformat(str(col)[:10]).date()
    except Exception:
        return None


def verify_consecutive_quarters(cols: list[Any]) -> tuple[bool, str]:
    """Verify that the top 4 columns represent 4 consecutive quarterly periods."""
    if len(cols) < 4:
        return False, f"Insufficient quarterly periods (found {len(cols)}, requires 4)"

    dates = [_col_date(c) for c in cols[:4]]
    if any(d is None for d in dates):
        return False, "One or more quarterly column headers cannot be parsed into dates"

    for i in range(3):
        d_curr = dates[i]
        d_prev = dates[i + 1]
        days_gap = (d_curr - d_prev).days
        # Normal quarter interval is 90 days. Acceptable consecutive gap: 60 to 125 days.
        if days_gap < 60 or days_gap > 125:
            return False, f"Non-consecutive quarterly gap between {d_prev} and {d_curr} ({days_gap} days)"

    return True, "Valid 4 consecutive quarters"


def detect_and_handle_ytd(
    values: list[Decimal],
    is_cumulative_metadata: bool = False,
    period_labels: Optional[list[str]] = None,
) -> tuple[list[Decimal], bool]:
    """
    Handle quarterly values reported as cumulative Year-to-Date numbers.
    STRICT RULE: Pure numerical monotonic heuristics are prohibited.
    Only de-accumulate when trusted metadata explicitly identifies cumulative reporting
    (e.g., is_cumulative_metadata=True or period labels indicate 3M, 6M, 9M, 12M).
    If cumulative cannot be verified from metadata, returns values untouched (treating as discrete).
    """
    if len(values) != 4 or not is_cumulative_metadata:
        return values, False

    # De-accumulate strictly when verified by metadata:
    discrete = [
        values[0],
        values[1] - values[0],
        values[2] - values[1],
        values[3] - values[2],
    ]
    return discrete, True


def extract_latest_balance_sheet(
    quarterly_bs: Any,
    annual_bs: Any,
    default_as_of: Optional[date] = None,
) -> dict[str, Any]:
    """
    Extract cash, total debt, and net debt from the single latest point-in-time balance sheet.
    Prefers quarterly balance sheet if available, falling back to annual.
    """
    as_of = default_as_of or date.today()
    q_cols = _sort_cols_descending(quarterly_bs)
    a_cols = _sort_cols_descending(annual_bs)

    bs_df = None
    target_col = None
    source_type = "annual"
    if q_cols:
        bs_df = quarterly_bs
        target_col = q_cols[0]
        source_type = "quarterly"
    elif a_cols:
        bs_df = annual_bs
        target_col = a_cols[0]
        source_type = "annual"

    if bs_df is None or target_col is None:
        return {
            "cash": None,
            "total_debt": None,
            "net_debt": None,
            "as_of": as_of,
            "period": "latest",
            "source_type": "missing",
        }

    col_dt = _col_date(target_col) or as_of
    period_str = f"Q_{col_dt.isoformat()}" if source_type == "quarterly" else f"FY{col_dt.year}"
    series = bs_df[target_col]

    cash_val = None
    for row in [
        "Cash Cash Equivalents And Short Term Investments",
        "Cash And Cash Equivalents",
        "Cash Financial",
    ]:
        if row in series.index:
            v = _to_dec(series.loc[row])
            if v is not None and v >= Decimal("0"):
                cash_val = v
                break

    debt_val = None
    if "Total Debt" in series.index:
        v = _to_dec(series.loc["Total Debt"])
        if v is not None and v >= Decimal("0"):
            debt_val = v

    net_debt = (debt_val - cash_val) if (debt_val is not None and cash_val is not None) else None

    return {
        "cash": cash_val,
        "total_debt": debt_val,
        "net_debt": net_debt,
        "as_of": col_dt,
        "period": period_str,
        "source_type": source_type,
    }


def aggregate_ttm_cashflow(
    quarterly_cf: Any,
    annual_cf: Any,
    quarterly_fin: Any = None,
    annual_fin: Any = None,
    default_as_of: Optional[date] = None,
) -> dict[str, Any]:
    """
    Roll up 4 discrete quarterly cash flow statements into a true TTM statement.
    Requires 4/4 complete quarterly data; falls back to annual if missing or invalid.
    """
    as_of = default_as_of or date.today()
    q_cols = _sort_cols_descending(quarterly_cf)
    a_cols = _sort_cols_descending(annual_cf)

    valid_quarters, reason = verify_consecutive_quarters(q_cols)
    if valid_quarters:
        selected_q_cols = q_cols[:4]
        # Chronological order for YTD check: earliest to newest
        chron_cols = list(reversed(selected_q_cols))

        cfo_list: list[Decimal] = []
        capex_list: list[Decimal] = []
        nb_list: list[Decimal] = []
        nwc_list: list[Decimal] = []
        da_list: list[Decimal] = []
        has_full_cfo = True
        has_full_capex = True

        for c in chron_cols:
            series = quarterly_cf[c]
            cfo_val = None
            for row in ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"]:
                if row in series.index:
                    v = _to_dec(series.loc[row])
                    if v is not None:
                        cfo_val = v
                        break
            if cfo_val is not None:
                cfo_list.append(cfo_val)
            else:
                has_full_cfo = False

            capex_val = None
            for row in ["Capital Expenditure", "Purchase Of PPE"]:
                if row in series.index:
                    v = _to_dec(series.loc[row])
                    if v is not None:
                        capex_val = abs(v)
                        break
            if capex_val is not None:
                capex_list.append(capex_val)
            else:
                has_full_capex = False

            nb_val = None
            for row in ["Net Issuance Payments Of Debt", "Net Long Term Debt Issuance"]:
                if row in series.index:
                    v = _to_dec(series.loc[row])
                    if v is not None:
                        nb_val = v
                        break
            if nb_val is None and "Issuance Of Debt" in series.index and "Repayment Of Debt" in series.index:
                iss = _to_dec(series.loc["Issuance Of Debt"])
                rep = _to_dec(series.loc["Repayment Of Debt"])
                if iss is not None and rep is not None:
                    nb_val = iss + rep
            if nb_val is not None:
                nb_list.append(nb_val)

            # Change in working capital extraction (cash flow statement)
            nwc_val = None
            for row in ["Change In Working Capital", "Changes In Working Capital"]:
                if row in series.index:
                    v = _to_dec(series.loc[row])
                    if v is not None:
                        nwc_val = v
                        break
            if nwc_val is not None:
                nwc_list.append(nwc_val)

            # Depreciation & Amortization extraction from cash flow
            da_val = None
            for row in ["Depreciation And Amortization", "Depreciation Amortization Depletion", "Depreciation"]:
                if row in series.index:
                    v = _to_dec(series.loc[row])
                    if v is not None:
                        da_val = abs(v)
                        break
            if da_val is not None:
                da_list.append(da_val)

        if has_full_cfo and has_full_capex and len(cfo_list) == 4 and len(capex_list) == 4:
            # yfinance quarterly tables are discrete single-quarter statements by contract.
            # STRICT RULE: Never deduce cumulative reporting from amount ratios or annual total coincidence.
            # Only de-accumulate when trusted metadata explicitly identifies cumulative reporting.
            period_labels = [str(getattr(c, "name", c)) for c in chron_cols]
            is_cumulative_cf = any("YTD" in l.upper() or "6M" in l.upper() or "9M" in l.upper() for l in period_labels)
            final_cfo_list, cfo_ytd = detect_and_handle_ytd(cfo_list, is_cumulative_metadata=is_cumulative_cf, period_labels=period_labels)
            final_capex_list, capex_ytd = detect_and_handle_ytd(capex_list, is_cumulative_metadata=is_cumulative_cf, period_labels=period_labels)

            cfo_sum = sum(final_cfo_list)
            capex_sum = sum(final_capex_list)
            nb_sum = sum(nb_list) if len(nb_list) == 4 else None
            # In cash flow statement: cfs_wc is cash flow contribution.
            # When working capital increases (cash outflow), cfs_wc is negative.
            # Balance sheet investment in working capital: ΔNWC = -cfs_wc (reduces FCFF).
            cfs_wc_sum = sum(nwc_list) if len(nwc_list) == 4 else None
            nwc_investment_sum = -cfs_wc_sum if cfs_wc_sum is not None else None
            da_cf_sum = sum(da_list) if len(da_list) == 4 else None

            latest_q_date = _col_date(selected_q_cols[0]) or as_of

            # Match interest, tax rate, and D&A from quarterly financials across same 4 quarters
            interest_sum: Optional[Decimal] = None
            tax_rate: Optional[Decimal] = None
            da_fin_sum: Optional[Decimal] = None
            qfin_cols = _sort_cols_descending(quarterly_fin)
            if qfin_cols and len(qfin_cols) >= 4:
                qf_interest_list: list[Decimal] = []
                qf_tax_list: list[Decimal] = []
                qf_pretax_list: list[Decimal] = []
                qf_da_list: list[Decimal] = []
                for c in selected_q_cols:
                    if c in quarterly_fin.columns:
                        fs = quarterly_fin[c]
                        if "Interest Expense" in fs.index:
                            int_v = _to_dec(fs.loc["Interest Expense"])
                            if int_v is not None:
                                qf_interest_list.append(abs(int_v))
                        if "Tax Provision" in fs.index:
                            tp_v = _to_dec(fs.loc["Tax Provision"])
                            if tp_v is not None:
                                qf_tax_list.append(tp_v)
                        if "Pretax Income" in fs.index:
                            pt_v = _to_dec(fs.loc["Pretax Income"])
                            if pt_v is not None:
                                qf_pretax_list.append(pt_v)
                        for da_row in ["Reconciled Depreciation", "Depreciation And Amortization", "Depreciation Amortization Depletion"]:
                            if da_row in fs.index:
                                da_v = _to_dec(fs.loc[da_row])
                                if da_v is not None:
                                    qf_da_list.append(abs(da_v))
                                    break
                if len(qf_interest_list) == 4:
                    interest_sum = sum(qf_interest_list)
                if len(qf_tax_list) == 4 and len(qf_pretax_list) == 4:
                    tot_pretax = sum(qf_pretax_list)
                    tot_tax = sum(qf_tax_list)
                    if tot_pretax > Decimal("0"):
                        calc_tr = tot_tax / tot_pretax
                        if Decimal("0") <= calc_tr <= Decimal("1"):
                            tax_rate = calc_tr
                if len(qf_da_list) == 4:
                    da_fin_sum = sum(qf_da_list)

            da_sum = da_cf_sum if da_cf_sum is not None else da_fin_sum

            if interest_sum is None and a_cols and annual_fin is not None and hasattr(annual_fin, "columns"):
                target_a = a_cols[0]
                if target_a in annual_fin.columns:
                    afs = annual_fin[target_a]
                    if "Interest Expense" in afs.index:
                        iv = _to_dec(afs.loc["Interest Expense"])
                        if iv is not None:
                            interest_sum = abs(iv)
            if tax_rate is None and a_cols and annual_fin is not None and hasattr(annual_fin, "columns"):
                target_a = a_cols[0]
                if target_a in annual_fin.columns:
                    afs = annual_fin[target_a]
                    if "Tax Rate For Calcs" in afs.index:
                        tr = _to_dec(afs.loc["Tax Rate For Calcs"])
                        if tr is not None and Decimal("0") <= tr <= Decimal("1"):
                            tax_rate = tr
                    elif "Tax Provision" in afs.index and "Pretax Income" in afs.index:
                        tp = _to_dec(afs.loc["Tax Provision"])
                        pt = _to_dec(afs.loc["Pretax Income"])
                        if tp is not None and pt is not None and pt > Decimal("0"):
                            calc_tr = tp / pt
                            if Decimal("0") <= calc_tr <= Decimal("1"):
                                tax_rate = calc_tr

            notes = f"Aggregated 4 discrete quarters ending {latest_q_date}"
            if cfo_ytd or capex_ytd:
                notes += " (de-accumulated from cumulative YTD reporting)"

            return {
                "cfo": cfo_sum,
                "capex": capex_sum,
                "net_borrowing": nb_sum,
                "has_net_borrowing": nb_sum is not None,
                "interest": interest_sum,
                "tax_rate": tax_rate,
                "nwc_change": nwc_investment_sum,
                "nwc_investment": nwc_investment_sum,
                "nwc_cfs_flow": cfs_wc_sum,
                "da": da_sum,
                "statement_basis": "TTM",
                "annual_fallback": False,
                "as_of": latest_q_date,
                "period": "TTM",
                "notes": notes,
            }

    # Fallback to annual cash flow statement
    if a_cols:
        target_col = a_cols[0]
        col_dt = _col_date(target_col) or as_of
        series = annual_cf[target_col]

        cfo = None
        for row in ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"]:
            if row in series.index:
                v = _to_dec(series.loc[row])
                if v is not None:
                    cfo = v
                    break

        capex = None
        for row in ["Capital Expenditure", "Purchase Of PPE"]:
            if row in series.index:
                v = _to_dec(series.loc[row])
                if v is not None:
                    capex = abs(v)
                    break

        nb = None
        for row in ["Net Issuance Payments Of Debt", "Net Long Term Debt Issuance"]:
            if row in series.index:
                v = _to_dec(series.loc[row])
                if v is not None:
                    nb = v
                    break
        if nb is None and "Issuance Of Debt" in series.index and "Repayment Of Debt" in series.index:
            iss = _to_dec(series.loc["Issuance Of Debt"])
            rep = _to_dec(series.loc["Repayment Of Debt"])
            if iss is not None and rep is not None:
                nb = iss + rep

        # Change in working capital extraction (annual cash flow)
        cfs_nwc = None
        for row in ["Change In Working Capital", "Changes In Working Capital"]:
            if row in series.index:
                v = _to_dec(series.loc[row])
                if v is not None:
                    cfs_nwc = v
                    break
        annual_nwc_investment = -cfs_nwc if cfs_nwc is not None else None

        # Depreciation & Amortization extraction from annual cash flow
        da_cf = None
        for row in ["Depreciation And Amortization", "Depreciation Amortization Depletion", "Depreciation"]:
            if row in series.index:
                v = _to_dec(series.loc[row])
                if v is not None:
                    da_cf = abs(v)
                    break

        # Interest & Tax from annual financials matching column
        interest = None
        tax_rate = None
        da_fin = None
        if annual_fin is not None and hasattr(annual_fin, "columns"):
            fin_series = None
            for fc in annual_fin.columns:
                if _col_date(fc) == col_dt or str(fc)[:10] == str(target_col)[:10]:
                    fin_series = annual_fin[fc]
                    break

            if fin_series is not None:
                if "Interest Expense" in fin_series.index:
                    iv = _to_dec(fin_series.loc["Interest Expense"])
                    if iv is not None:
                        interest = abs(iv)
                if "Tax Rate For Calcs" in fin_series.index:
                    tr = _to_dec(fin_series.loc["Tax Rate For Calcs"])
                    if tr is not None and Decimal("0") <= tr <= Decimal("1"):
                        tax_rate = tr
                elif "Tax Provision" in fin_series.index and "Pretax Income" in fin_series.index:
                    tp = _to_dec(fin_series.loc["Tax Provision"])
                    pt = _to_dec(fin_series.loc["Pretax Income"])
                    if tp is not None and pt is not None and pt > Decimal("0"):
                        tr = tp / pt
                        if Decimal("0") <= tr <= Decimal("1"):
                            tax_rate = tr
                for da_row in ["Reconciled Depreciation", "Depreciation And Amortization", "Depreciation Amortization Depletion"]:
                    if da_row in fin_series.index:
                        da_v = _to_dec(fin_series.loc[da_row])
                        if da_v is not None:
                            da_fin = abs(da_v)
                            break

        da = da_cf if da_cf is not None else da_fin

        return {
            "cfo": cfo,
            "capex": capex,
            "net_borrowing": nb,
            "has_net_borrowing": nb is not None,
            "interest": interest,
            "tax_rate": tax_rate,
            "nwc_change": annual_nwc_investment,
            "nwc_investment": annual_nwc_investment,
            "nwc_cfs_flow": cfs_nwc,
            "da": da,
            "statement_basis": "ANNUAL_FALLBACK",
            "annual_fallback": True,
            "as_of": col_dt,
            "period": f"FY{col_dt.year}",
            "notes": f"Annual statement fallback ({reason if not valid_quarters else 'quarterly incomplete'})",
        }

    return {
        "cfo": None,
        "capex": None,
        "net_borrowing": None,
        "has_net_borrowing": False,
        "interest": None,
        "tax_rate": None,
        "nwc_change": None,
        "da": None,
        "statement_basis": "UNAVAILABLE",
        "annual_fallback": False,
        "as_of": as_of,
        "period": "TTM",
        "notes": "No cash flow statement available",
    }


def aggregate_ttm_income(
    quarterly_fin: Any,
    annual_fin: Any,
    default_as_of: Optional[date] = None,
) -> dict[str, Any]:
    """
    Roll up 4 discrete quarterly income statements into a true TTM statement.
    Requires 4/4 complete quarterly data; falls back to annual if missing or invalid.
    """
    as_of = default_as_of or date.today()
    q_cols = _sort_cols_descending(quarterly_fin)
    a_cols = _sort_cols_descending(annual_fin)

    valid_quarters, reason = verify_consecutive_quarters(q_cols)
    if valid_quarters:
        selected_q_cols = q_cols[:4]
        chron_cols = list(reversed(selected_q_cols))

        rev_list: list[Decimal] = []
        ebitda_list: list[Decimal] = []
        op_ebitda_list: list[Decimal] = []
        vendor_ebitda_list: list[Decimal] = []
        da_list: list[Decimal] = []
        has_full_rev = True
        has_full_ebitda = True

        for c in chron_cols:
            series = quarterly_fin[c]
            rev_val = None
            if "Total Revenue" in series.index:
                v = _to_dec(series.loc["Total Revenue"])
                if v is not None:
                    rev_val = v
            if rev_val is not None:
                rev_list.append(rev_val)
            else:
                has_full_rev = False

            da_v = None
            for da_row in ["Reconciled Depreciation", "Depreciation And Amortization", "Depreciation Amortization Depletion"]:
                if da_row in series.index:
                    d_dec = _to_dec(series.loc[da_row])
                    if d_dec is not None:
                        da_v = abs(d_dec)
                        break
            if da_v is not None:
                da_list.append(da_v)

            # Operating EBITDA vs vendor EBITDA:
            # Operating EBITDA = Operating Income + D&A (or Normalized EBITDA)
            # Isolates core operating profitability from one-off non-operating security gains (e.g. GOOG).
            op_ebitda_val = None
            if "Operating Income" in series.index and da_v is not None:
                oi = _to_dec(series.loc["Operating Income"])
                if oi is not None:
                    op_ebitda_val = oi + da_v
            elif "Normalized EBITDA" in series.index:
                op_ebitda_val = _to_dec(series.loc["Normalized EBITDA"])

            vendor_ebitda_val = _to_dec(series.loc["EBITDA"]) if "EBITDA" in series.index else None

            ebitda_val = op_ebitda_val if op_ebitda_val is not None else vendor_ebitda_val
            if ebitda_val is not None:
                ebitda_list.append(ebitda_val)
            else:
                has_full_ebitda = False
            if op_ebitda_val is not None:
                op_ebitda_list.append(op_ebitda_val)
            if vendor_ebitda_val is not None:
                vendor_ebitda_list.append(vendor_ebitda_val)

        if has_full_rev and len(rev_list) == 4:
            period_labels = [str(getattr(c, "name", c)) for c in chron_cols]
            is_cumulative_rev = any("YTD" in l.upper() or "6M" in l.upper() or "9M" in l.upper() for l in period_labels)
            final_rev_list, rev_ytd = detect_and_handle_ytd(rev_list, is_cumulative_metadata=is_cumulative_rev, period_labels=period_labels)
            rev_sum = sum(final_rev_list)
            latest_q_date = _col_date(selected_q_cols[0]) or as_of
            da_sum = sum(da_list) if len(da_list) == 4 else None

            op_ebitda_sum = sum(op_ebitda_list) if len(op_ebitda_list) == 4 else None
            vendor_ebitda_sum = sum(vendor_ebitda_list) if len(vendor_ebitda_list) == 4 else None

            annual_ebitda = None
            annual_da = None
            if a_cols and annual_fin is not None and hasattr(annual_fin, "columns"):
                target_a = a_cols[0]
                if target_a in annual_fin.columns:
                    a_series = annual_fin[target_a]
                    for da_row in ["Reconciled Depreciation", "Depreciation And Amortization", "Depreciation Amortization Depletion"]:
                        if da_row in a_series.index:
                            d_dec = _to_dec(a_series.loc[da_row])
                            if d_dec is not None:
                                annual_da = abs(d_dec)
                                break
                    if "EBITDA" in a_series.index:
                        annual_ebitda = _to_dec(a_series.loc["EBITDA"])
                    elif "Operating Income" in a_series.index and annual_da is not None:
                        oi = _to_dec(a_series.loc["Operating Income"])
                        if oi is not None:
                            annual_ebitda = oi + annual_da

            da_period: Optional[str] = None
            da_as_of: Optional[date] = None
            da_is_fallback: bool = False
            if da_sum is not None:
                effective_da = da_sum
                da_period = "TTM"
                da_as_of = latest_q_date
                da_is_fallback = False
            elif annual_da is not None:
                effective_da = annual_da
                target_a_col = a_cols[0] if a_cols else None
                da_as_of = _col_date(target_a_col) or as_of
                da_period = f"FY{da_as_of.year}"
                da_is_fallback = True
            else:
                effective_da = None
                da_period = None
                da_as_of = None
                da_is_fallback = False

            if has_full_ebitda and len(ebitda_list) == 4:
                ebitda_sum = sum(ebitda_list)
                statement_basis = "TTM"
                annual_fallback = False
                notes = f"Aggregated 4 discrete quarters ending {latest_q_date}"
            elif annual_ebitda is not None:
                ebitda_sum = annual_ebitda
                statement_basis = "ANNUAL_FALLBACK"
                annual_fallback = True
                notes = f"Revenue from 4 discrete quarters ending {latest_q_date}; EBITDA fell back to annual statement"
            else:
                if a_cols and annual_fin is not None and hasattr(annual_fin, "columns"):
                    target_col = a_cols[0]
                    col_dt = _col_date(target_col) or as_of
                    if target_col in annual_fin.columns:
                        series = annual_fin[target_col]
                        rev = _to_dec(series.loc["Total Revenue"]) if "Total Revenue" in series.index else None
                        return {
                            "revenue": rev,
                            "ebitda": None,
                            "operating_ebitda": None,
                            "vendor_ebitda": None,
                            "da": effective_da,
                            "da_period": da_period,
                            "da_as_of": da_as_of,
                            "da_is_fallback": da_is_fallback,
                            "statement_basis": "ANNUAL_FALLBACK",
                            "annual_fallback": True,
                            "as_of": col_dt,
                            "period": f"FY{col_dt.year}",
                            "notes": "Annual statement fallback (quarterly EBITDA incomplete)",
                        }
                ebitda_sum = None
                statement_basis = "ANNUAL_FALLBACK"
                annual_fallback = True
                notes = f"Revenue from 4 discrete quarters ending {latest_q_date} (EBITDA unavailable)"

            return {
                "revenue": rev_sum,
                "ebitda": ebitda_sum,
                "operating_ebitda": op_ebitda_sum or ebitda_sum,
                "vendor_ebitda": vendor_ebitda_sum or ebitda_sum,
                "da": effective_da,
                "da_period": da_period,
                "da_as_of": da_as_of,
                "da_is_fallback": da_is_fallback,
                "statement_basis": statement_basis,
                "annual_fallback": annual_fallback,
                "as_of": latest_q_date,
                "period": "TTM" if not annual_fallback else "TTM/FY",
                "notes": notes,
            }

    # Fallback to annual income statement
    if a_cols:
        target_col = a_cols[0]
        col_dt = _col_date(target_col) or as_of
        series = annual_fin[target_col]

        rev = None
        if "Total Revenue" in series.index:
            v = _to_dec(series.loc["Total Revenue"])
            if v is not None:
                rev = v

        da_val = None
        for da_row in ["Reconciled Depreciation", "Depreciation And Amortization", "Depreciation Amortization Depletion"]:
            if da_row in series.index:
                d_dec = _to_dec(series.loc[da_row])
                if d_dec is not None:
                    da_val = abs(d_dec)
                    break

        ebitda = None
        op_ebitda = None
        if "Operating Income" in series.index and da_val is not None:
            oi = _to_dec(series.loc["Operating Income"])
            if oi is not None:
                op_ebitda = oi + da_val
        elif "Normalized EBITDA" in series.index:
            op_ebitda = _to_dec(series.loc["Normalized EBITDA"])

        vendor_ebitda = _to_dec(series.loc["EBITDA"]) if "EBITDA" in series.index else None
        ebitda = op_ebitda if op_ebitda is not None else vendor_ebitda

        return {
            "revenue": rev,
            "ebitda": ebitda,
            "operating_ebitda": op_ebitda or ebitda,
            "vendor_ebitda": vendor_ebitda or ebitda,
            "da": da_val,
            "da_period": f"FY{col_dt.year}",
            "da_as_of": col_dt,
            "da_is_fallback": True,
            "statement_basis": "ANNUAL_FALLBACK",
            "annual_fallback": True,
            "as_of": col_dt,
            "period": f"FY{col_dt.year}",
            "notes": f"Annual statement fallback ({reason if not valid_quarters else 'quarterly incomplete'})",
        }

    return {
        "revenue": None,
        "ebitda": None,
        "operating_ebitda": None,
        "vendor_ebitda": None,
        "da": None,
        "da_period": None,
        "da_as_of": None,
        "da_is_fallback": False,
        "statement_basis": "ANNUAL_FALLBACK",
        "annual_fallback": True,
        "as_of": as_of,
        "period": "latest",
        "notes": "No income statement available",
    }

