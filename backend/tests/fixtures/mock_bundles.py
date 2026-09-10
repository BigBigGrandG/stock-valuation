"""Deterministic mock bundles for E2E and integration testing.

Extracts deterministic upstream ticker tables from test_production_pipeline_contract
and provides them as an importable module for tests and isolated test servers.
"""
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock
import pandas as pd

from app.providers.yfinance_provider import _TickerBundle


VAL_DATE = date(2026, 9, 10)
VAL_TIMESTAMP = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)
FY_END_DATE = date(2026, 10, 31)

Q_DATES = [
    datetime(2026, 7, 31),
    datetime(2026, 4, 30),
    datetime(2026, 1, 31),
    datetime(2025, 10, 31),
]
ANNUAL_DATES = [
    datetime(2025, 10, 31),
    datetime(2024, 10, 31),
]


def build_mock_bundle(
    ticker: str = "AVGO",
    shares_conflict: bool = False,
    missing_quarter: bool = False,
    missing_ebitda_quarter: bool = False,
) -> MagicMock:
    """Construct deterministic ticker bundle with controlled financials."""
    bundle = MagicMock(spec=_TickerBundle)
    bundle.raw_ticker = ticker
    bundle.query_symbol = ticker

    last_fy_ts = int(datetime(2025, 10, 31, tzinfo=timezone.utc).timestamp())
    next_fy_ts = int(datetime(2026, 10, 31, tzinfo=timezone.utc).timestamp())

    reported_shares = 1_000_000_000
    market_cap = 200_000_000_000 if shares_conflict else 100_000_000_000
    price = 100.0

    company_names = {
        "AVGO": ("Broadcom Inc.", "Broadcom Inc."),
        "OCTO": ("October Fiscal Co", "October Fiscal Corporation"),
        "ANN": ("Annual Fallback Corp", "Annual Fallback Corporation"),
        "CONF": ("Share Conflict Corp", "Share Conflict Corporation"),
    }
    short_name, long_name = company_names.get(ticker, (f"{ticker} Inc.", f"{ticker} Corporation"))

    info: dict[str, Any] = {
        "shortName": short_name,
        "longName": long_name,
        "currency": "USD",
        "financialCurrency": "USD",
        "quoteType": "EQUITY",
        "regularMarketPrice": price,
        "currentPrice": price,
        "regularMarketTime": int(VAL_TIMESTAMP.timestamp()),
        "sharesOutstanding": reported_shares,
        "marketCap": market_cap,
        "lastFiscalYearEnd": last_fy_ts,
        "nextFiscalYearEnd": next_fy_ts,
        "trailingEps": 5.0,
        "forwardEps": 6.5,
        "beta": 1.1,
        "sector": "Technology",
        "industry": "Semiconductors",
    }
    bundle.get_info.return_value = info

    # Quarterly financials: 4 discrete quarters revenues: 400 (Q3), 300 (Q2), 200 (Q1), 100 (Q4) -> sum = 1000
    q_cols = Q_DATES[:3] if missing_quarter else Q_DATES
    q_revs = [Decimal("400000000"), Decimal("300000000"), Decimal("200000000")] if missing_quarter else [
        Decimal("400000000"), Decimal("300000000"), Decimal("200000000"), Decimal("100000000")
    ]
    q_ebitdas = [
        Decimal("160000000"),
        Decimal("120000000"),
        None if missing_ebitda_quarter else Decimal("80000000"),
        Decimal("40000000"),
    ]
    if missing_quarter:
        q_ebitdas = q_ebitdas[:3]

    fin_dict = {
        col: [rev, ebitda] for col, rev, ebitda in zip(q_cols, q_revs, q_ebitdas)
    }
    q_fin_df = pd.DataFrame(fin_dict, index=["Total Revenue", "EBITDA"])
    bundle.get_quarterly_financials.return_value = q_fin_df

    # Annual financials
    a_fin_df = pd.DataFrame(
        {
            ANNUAL_DATES[0]: [Decimal("900000000"), Decimal("350000000"), Decimal("50000000"), Decimal("30000000"), Decimal("150000000")],
            ANNUAL_DATES[1]: [Decimal("750000000"), Decimal("280000000"), Decimal("45000000"), Decimal("25000000"), Decimal("120000000")],
        },
        index=["Total Revenue", "EBITDA", "Interest Expense", "Tax Provision", "Pretax Income"],
    )
    bundle.get_financials.return_value = a_fin_df

    # Quarterly cashflow
    q_cf_df = pd.DataFrame(
        {
            c: [Decimal("120000000"), Decimal("30000000")] for c in q_cols
        },
        index=["Operating Cash Flow", "Capital Expenditure"],
    )
    bundle.get_quarterly_cashflow.return_value = q_cf_df

    # Annual cashflow
    a_cf_df = pd.DataFrame(
        {
            ANNUAL_DATES[0]: [Decimal("400000000"), Decimal("100000000")],
        },
        index=["Operating Cash Flow", "Capital Expenditure"],
    )
    bundle.get_cashflow.return_value = a_cf_df

    # Balance sheet: quarterly has latest 2026-07-31
    q_bs_df = pd.DataFrame(
        {
            Q_DATES[0]: [Decimal("5000000000"), Decimal("1000000000"), Decimal("1000000000")],
            Q_DATES[1]: [Decimal("4500000000"), Decimal("1050000000"), Decimal("1000000000")],
        },
        index=["Cash And Cash Equivalents", "Total Debt", "Ordinary Shares Number"],
    )
    bundle.get_quarterly_balance_sheet.return_value = q_bs_df

    a_bs_df = pd.DataFrame(
        {
            ANNUAL_DATES[0]: [Decimal("4000000000"), Decimal("1200000000"), Decimal("1000000000")],
        },
        index=["Cash And Cash Equivalents", "Total Debt", "Ordinary Shares Number"],
    )
    bundle.get_balance_sheet.return_value = a_bs_df

    # Earnings estimate
    ee_df = pd.DataFrame(
        {
            "avg": [Decimal("6.50"), Decimal("7.80")],
            "currency": ["USD", "USD"],
        },
        index=["0y", "+1y"],
    )
    bundle.get_earnings_estimate.return_value = ee_df

    # Revenue estimate
    re_df = pd.DataFrame(
        {
            "avg": [Decimal("1500000000"), Decimal("1800000000")],
            "growth": [Decimal("0.70"), Decimal("0.20")],
        },
        index=["0y", "+1y"],
    )
    bundle.get_revenue_estimate.return_value = re_df

    return bundle


def get_mock_bundle_for_ticker(ticker: str) -> MagicMock:
    """Route ticker to corresponding deterministic scenario."""
    normalized = ticker.upper()
    if normalized in ("ANN", "FALLB", "ANNUAL"):
        return build_mock_bundle(ticker=normalized, missing_quarter=True)
    if normalized in ("CONF", "CONFL", "CONFLICT"):
        return build_mock_bundle(ticker=normalized, shares_conflict=True)
    # Default scenario: AVGO, OCTO, and general tickers get high growth scenario
    return build_mock_bundle(ticker=normalized)
