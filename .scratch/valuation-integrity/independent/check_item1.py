"""
Independent check for Item 1: Quarter Aggregation & Balance Sheet Integration
"""
from datetime import date, datetime
from decimal import Decimal
import pandas as pd
import sys

sys.path.insert(0, "backend")

from app.providers.statement_aggregator import (
    aggregate_ttm_cashflow,
    aggregate_ttm_income,
    detect_and_handle_ytd,
    extract_latest_balance_sheet,
    verify_consecutive_quarters,
    _sort_cols_descending,
)

print("=== CHECK ITEM 1: QUARTER AGGREGATION & BALANCE SHEET ===")

# Test 1.1: Duplicate column dates
cols_with_dup = [
    datetime(2024, 9, 30),
    datetime(2024, 6, 30),
    datetime(2024, 6, 30),
    datetime(2024, 3, 31),
    datetime(2023, 12, 31),
]
df_dup = pd.DataFrame([[1, 2, 2, 3, 4]], columns=cols_with_dup, index=["Total Revenue"])
sorted_cols = _sort_cols_descending(df_dup)
valid, reason = verify_consecutive_quarters(sorted_cols)
print(f"Test 1.1 (Duplicate column dates): valid={valid}, reason={reason}")
assert valid, f"Expected deduplication to yield valid consecutive quarters, got: {reason}"
assert len(sorted_cols) == 4, f"Expected 4 deduplicated unique columns, got {len(sorted_cols)}"

# Test 1.2: Discrete growing quarterly revenues [100, 200, 300, 400] -> sum = 1000
discrete_growing_rev = [
    Decimal("100"),
    Decimal("200"),
    Decimal("300"),
    Decimal("400"),
]
handled_values, is_ytd = detect_and_handle_ytd(discrete_growing_rev)
print(f"Test 1.2 (Growing discrete revenues [100, 200, 300, 400]):")
print(f"   is_ytd detected: {is_ytd}")
print(f"   original sum: {sum(discrete_growing_rev)} (expected: 1000)")
print(f"   result values: {handled_values}, sum: {sum(handled_values)}")
assert not is_ytd, "Growing discrete revenue must NOT be falsely identified as YTD without metadata"
assert sum(handled_values) == Decimal("1000"), f"Discrete sum must be 1000, got {sum(handled_values)}"
assert handled_values == discrete_growing_rev, "Discrete quarterly figures must remain untouched"

# Test 1.3: Missing EBITDA in one quarter triggers annual fallback
q_dates = [datetime(2024, 12, 31), datetime(2024, 9, 30), datetime(2024, 6, 30), datetime(2024, 3, 31)]
a_dates = [datetime(2024, 12, 31), datetime(2023, 12, 31)]

q_inc_df = pd.DataFrame(
    {
        q_dates[0]: [Decimal("1000"), Decimal("200")],
        q_dates[1]: [Decimal("1100"), Decimal("220")],
        q_dates[2]: [Decimal("1050"), None],  # Missing EBITDA in Q3
        q_dates[3]: [Decimal("950"), Decimal("190")],
    },
    index=["Total Revenue", "EBITDA"],
)
a_inc_df = pd.DataFrame(
    {
        a_dates[0]: [Decimal("4100"), Decimal("830")],
    },
    index=["Total Revenue", "EBITDA"],
)
res_inc = aggregate_ttm_income(q_inc_df, a_inc_df)
print(f"Test 1.3 (Missing EBITDA in Q3):")
print(f"   statement_basis: {res_inc['statement_basis']}")
print(f"   annual_fallback: {res_inc['annual_fallback']}")
print(f"   revenue: {res_inc['revenue']}")
print(f"   ebitda: {res_inc['ebitda']}")
assert res_inc["annual_fallback"] is True, "Must fall back to annual when quarterly EBITDA is missing"
assert res_inc["statement_basis"] == "ANNUAL_FALLBACK"
assert res_inc["ebitda"] == Decimal("830"), f"EBITDA must fall back to annual statement (830), got {res_inc['ebitda']}"
assert res_inc["revenue"] == Decimal("4100"), f"Revenue must match TTM sum 4100, got {res_inc['revenue']}"

# Test 1.4: Missing interest in quarterly financials falls back to annual financials
q_cf_df = pd.DataFrame(
    {
        q_dates[0]: [Decimal("500"), Decimal("100")],
        q_dates[1]: [Decimal("500"), Decimal("100")],
        q_dates[2]: [Decimal("500"), Decimal("100")],
        q_dates[3]: [Decimal("500"), Decimal("100")],
    },
    index=["Operating Cash Flow", "Capital Expenditure"],
)
q_fin_df = pd.DataFrame(
    {
        q_dates[0]: [Decimal("50"), Decimal("30"), Decimal("150")],
        q_dates[1]: [Decimal("50"), Decimal("30"), Decimal("150")],
        q_dates[2]: [Decimal("50"), Decimal("30"), Decimal("150")],
        q_dates[3]: [None, Decimal("30"), Decimal("150")],  # Missing interest in Q4
    },
    index=["Interest Expense", "Tax Provision", "Pretax Income"],
)
a_cf_df = pd.DataFrame(
    {
        a_dates[0]: [Decimal("2000"), Decimal("400")],
    },
    index=["Operating Cash Flow", "Capital Expenditure"],
)
a_fin_df = pd.DataFrame(
    {
        a_dates[0]: [Decimal("200"), Decimal("120"), Decimal("600")],
    },
    index=["Interest Expense", "Tax Provision", "Pretax Income"],
)
res_cf = aggregate_ttm_cashflow(q_cf_df, a_cf_df, q_fin_df, a_fin_df)
print(f"Test 1.4 (Missing quarterly interest in Q4):")
print(f"   statement_basis: {res_cf['statement_basis']}")
print(f"   interest: {res_cf['interest']}")
print(f"   tax_rate: {res_cf['tax_rate']}")
assert res_cf["statement_basis"] == "TTM"
assert res_cf["interest"] == Decimal("200"), f"Interest must fall back to annual statement (200), got {res_cf['interest']}"
assert res_cf["tax_rate"] == Decimal("0.2"), f"Tax rate must be computed from annual statement (0.2), got {res_cf['tax_rate']}"

# Test 1.5: Missing quarter cannot under-sum and claim TTM
q_dates_3 = [datetime(2024, 12, 31), datetime(2024, 9, 30), datetime(2024, 6, 30)]  # Only 3 quarters!
q_inc_3q = pd.DataFrame(
    {
        q_dates_3[0]: [Decimal("100"), Decimal("20")],
        q_dates_3[1]: [Decimal("200"), Decimal("40")],
        q_dates_3[2]: [Decimal("300"), Decimal("60")],
    },
    index=["Total Revenue", "EBITDA"],
)
res_3q = aggregate_ttm_income(q_inc_3q, a_inc_df)
print(f"Test 1.5 (Only 3 quarters available):")
print(f"   statement_basis: {res_3q['statement_basis']}")
print(f"   annual_fallback: {res_3q['annual_fallback']}")
assert res_3q["statement_basis"] == "ANNUAL_FALLBACK", "Missing 4th quarter must trigger annual fallback"
assert res_3q["annual_fallback"] is True
assert res_3q["revenue"] == Decimal("4100"), "Must use annual revenue instead of partial 3-quarter under-sum"

# Test 1.6: Single latest balance sheet extraction without cross-quarter mixing
q_bs_df = pd.DataFrame(
    {
        q_dates[0]: [Decimal("5000"), Decimal("12000")],
        q_dates[1]: [Decimal("4500"), Decimal("13000")],
    },
    index=["Cash And Cash Equivalents", "Total Debt"],
)
a_bs_df = pd.DataFrame(
    {
        a_dates[0]: [Decimal("4000"), Decimal("14000")],
    },
    index=["Cash And Cash Equivalents", "Total Debt"],
)
bs_res = extract_latest_balance_sheet(q_bs_df, a_bs_df)
print(f"Test 1.6 (Latest balance sheet point in time):")
print(f"   cash: {bs_res['cash']}, debt: {bs_res['total_debt']}, net_debt: {bs_res['net_debt']}")
print(f"   source_type: {bs_res['source_type']}, period: {bs_res['period']}")
assert bs_res["cash"] == Decimal("5000"), "Must extract latest quarterly cash without mixing"
assert bs_res["total_debt"] == Decimal("12000"), "Must extract latest quarterly debt without mixing"
assert bs_res["net_debt"] == Decimal("7000"), "Net debt must be 12000 - 5000 = 7000"
assert bs_res["source_type"] == "quarterly"
assert bs_res["period"] == f"Q_{q_dates[0].date().isoformat()}"

print("ALL ITEM 1 CHECKS AND ASSERTIONS PASSED!")
