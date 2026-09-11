"""
AVGO TEST/DEMO fixture provider.

Implements all 7 abstract FinancialDataProvider methods.
Serves fixed synthetic data for Broadcom Inc. (AVGO) only.
All values are fixture-sourced; fixture date is intentionally STATIC.
Clearly labeled DEMO with LOW data quality.
Unknown tickers return TickerNotFoundError — AVGO data is never cloned.

Fixture values per spec:
  price=343.83, shares=4940000000, cash=24000000000, debt=59400000000
  forward_eps=19.21, forward_EBITDA=118300000000
  FCFE (equity FCF, for FCF yield model) = 89600000000
  FCFF (firm FCF, for DCF at WACC)       = 79000000000  (separately labeled)
"""
from __future__ import annotations

from decimal import Decimal
from datetime import date, datetime
from typing import Any

from app.models.domain import (
    CompanyFinancialSnapshot,
    DataQuality,
    FinancialMetric,
    SourceType,
)
from app.providers.base import (
    FinancialDataProvider,
    TickerNotFoundError,
    QuoteData,
    CompanyProfileData,
    BalanceSheetData,
    CashFlowData,
    IncomeStatementData,
    ForwardEstimatesData,
    HistoricalMultiplesData,
)

# Fixed fixture date — intentionally static, never auto-refreshed
FIXTURE_DATE = date(2025, 1, 15)
FIXTURE_TIMESTAMP = datetime(2025, 1, 15, 16, 0, 0)

SUPPORTED_DEMO_TICKERS = frozenset({"AVGO"})

_DEMO_NOTE = "Synthetic fixture value for testing/demo only. Not real market data."


def _fm(value: str, unit: str, period: str, notes: str = "") -> FinancialMetric:
    return FinancialMetric(
        value=Decimal(value),
        unit=unit,
        period=period,
        source="AVGO TEST/DEMO fixture",
        source_type=SourceType.FIXTURE,
        as_of=FIXTURE_DATE,
        confidence=0.5,
        is_estimated=True,
        notes=notes or _DEMO_NOTE,
    )


def _check_ticker(ticker: str) -> str:
    t = ticker.strip().upper()
    if t not in SUPPORTED_DEMO_TICKERS:
        raise TickerNotFoundError(
            f"Ticker '{ticker}' not found. "
            f"This demo provider only supports: {', '.join(sorted(SUPPORTED_DEMO_TICKERS))}. "
            "Unknown tickers are never cloned from AVGO data."
        )
    return t


class AVGOFixtureProvider(FinancialDataProvider):
    """
    Fixed AVGO test/demo fixture provider implementing all 7 required abstract methods.
    Only AVGO is supported; all other tickers raise TickerNotFoundError.
    """

    # ------------------------------------------------------------------
    # 7 abstract method implementations
    # ------------------------------------------------------------------

    def get_quote(self, ticker: str) -> QuoteData:
        _check_ticker(ticker)
        return {
            "price": Decimal("343.83"),
            "currency": "USD",
            "timestamp": FIXTURE_TIMESTAMP,
            "as_of": FIXTURE_DATE,
            "source": "AVGO TEST/DEMO fixture",
            "note": "Fixture price. Intentionally stale — not real-time data.",
        }

    def get_company_profile(self, ticker: str) -> CompanyProfileData:
        _check_ticker(ticker)
        return {
            "name": "Broadcom Inc.",
            "ticker": "AVGO",
            "exchange": "NASDAQ",
            "sector": "Technology",
            "industry": "Semiconductors",
            "description": "Broadcom Inc. designs, develops and supplies semiconductor and infrastructure software solutions.",
            "currency": "USD",
            "country": "US",
            "security_type": "COMMON_STOCK",
            "is_profitable": True,
            "diluted_shares": Decimal("4940000000"),
            "shares_basis": "ALL_CLASS_RECONCILED",
            "shares_reconciliation": {
                "selected_source": "info.impliedSharesOutstanding",
                "is_multi_class": False,
                "conflict_detected": False,
                "implied_shares": 4940000000,
                "single_class_shares": 4940000000,
                "reconciliation_notes": "Single-class common stock verified fixture",
            },
            "as_of": FIXTURE_DATE,
            "source": "AVGO TEST/DEMO fixture",
        }

    def get_balance_sheet(self, ticker: str) -> BalanceSheetData:
        _check_ticker(ticker)
        return {
            "cash": Decimal("24000000000"),
            "total_debt": Decimal("59400000000"),
            "net_debt": Decimal("35400000000"),   # total_debt - cash; also stored for provenance
            "period": "FY2024",
            "as_of": FIXTURE_DATE,
            "source": "AVGO TEST/DEMO fixture",
            "note": _DEMO_NOTE,
        }

    def get_cash_flow(self, ticker: str) -> CashFlowData:
        """
        Returns BOTH FCFE and FCFF with EXPLICIT separate labels.
        FCFE = Free Cash Flow to Equity (equity CF after debt service) — FCF yield model only.
        FCFF = Free Cash Flow to Firm (unlevered) — DCF model at WACC only.
        These are DIFFERENT values; do NOT substitute one for the other.
        """
        _check_ticker(ticker)
        return {
            # FCFE — equity FCF for FCF yield model
            "fcfe_ttm": Decimal("80000000000"),
            "fcfe_definition": "Free Cash Flow to Equity: net income + D&A - capex - ΔNWC + net borrowing. FCF yield model ONLY.",
            "forward_fcfe_1y": Decimal("89600000000"),
            "forward_fcfe_2y": Decimal("100000000000"),
            # FCFF — firm/unlevered FCF for DCF model at WACC
            "fcff_ttm": Decimal("70000000000"),
            "fcff_definition": "Free Cash Flow to Firm: EBIT*(1-tax) + D&A - capex - ΔNWC. DCF model ONLY (discounted at WACC).",
            "forward_fcff_1y": Decimal("79000000000"),
            "forward_fcff_2y": Decimal("88000000000"),
            "cfo": Decimal("25000000000"),
            "capex": Decimal("3000000000"),
            "net_borrowing": Decimal("1000000000"),
            "nwc_change": Decimal("500000000"),
            "da": Decimal("4000000000"),
            "da_period": "TTM",
            "da_as_of": FIXTURE_DATE,
            "da_is_fallback": False,
            "interest": Decimal("2000000000"),
            "fcf_growth": Decimal("0.51"),
            "fcff_growth": Decimal("0.50"),
            "period": "TTM/FY2025E",
            "statement_basis": "TTM",
            "annual_fallback": False,
            "as_of": FIXTURE_DATE,
            "source": "AVGO TEST/DEMO fixture",
            "note": "FCFE and FCFF are separately labeled synthetic values with different economic definitions. Do not confuse.",
        }

    def get_income_statement(self, ticker: str) -> IncomeStatementData:
        _check_ticker(ticker)
        return {
            "revenue_ttm": Decimal("51574000000"),
            "ebitda_ttm": Decimal("28000000000"),
            "eps_ttm": Decimal("15.00"),
            "da": Decimal("4000000000"),
            "da_period": "TTM",
            "da_as_of": FIXTURE_DATE,
            "da_is_fallback": False,
            "revenue_growth": Decimal("0.51"),
            "ebitda_growth": Decimal("0.45"),
            "eps_growth": Decimal("0.25"),
            "period": "TTM",
            "statement_basis": "TTM",
            "annual_fallback": False,
            "as_of": FIXTURE_DATE,
            "source": "AVGO TEST/DEMO fixture",
            "note": _DEMO_NOTE,
        }

    def get_forward_estimates(self, ticker: str) -> ForwardEstimatesData:
        _check_ticker(ticker)
        return {
            "forward_revenue_1y": Decimal("65000000000"),
            "forward_revenue_2y": Decimal("75000000000"),
            "forward_eps_1y": Decimal("19.21"),
            "forward_eps_2y": Decimal("22.50"),
            "forward_ebitda_1y": Decimal("118300000000"),
            "forward_ebitda_2y": Decimal("135000000000"),
            # FCFE forward estimates (equity FCF — FCF yield model)
            "forward_fcfe_1y": Decimal("89600000000"),
            "forward_fcfe_2y": Decimal("100000000000"),
            # FCFF forward estimates (firm FCF — DCF model at WACC)
            "forward_fcff_1y": Decimal("79000000000"),
            "forward_fcff_2y": Decimal("88000000000"),
            "period_1y": "FY2025E",
            "period_2y": "FY2026E",
            "as_of": FIXTURE_DATE,
            "source": "AVGO TEST/DEMO fixture (synthetic forward estimates)",
            "note": _DEMO_NOTE,
        }

    def get_historical_multiples(self, ticker: str) -> HistoricalMultiplesData:
        _check_ticker(ticker)
        return {
            "historical_forward_pe": Decimal("22"),
            "historical_ev_ebitda": Decimal("24"),
            "period": "5Y median",
            "as_of": FIXTURE_DATE,
            "source": "AVGO TEST/DEMO fixture",
            "note": _DEMO_NOTE,
        }

    # ------------------------------------------------------------------
    # Snapshot assembly (overrides base _assemble_snapshot)
    # ------------------------------------------------------------------

    def _assemble_snapshot(
        self,
        ticker: str,
        quote: QuoteData,
        profile: CompanyProfileData,
        balance: BalanceSheetData,
        cash_flow: CashFlowData,
        income: IncomeStatementData,
        estimates: ForwardEstimatesData,
        multiples: HistoricalMultiplesData,
    ) -> CompanyFinancialSnapshot:
        """Assemble CompanyFinancialSnapshot from the 7 raw fetch results."""
        d = FIXTURE_DATE

        def fm(value: Decimal, unit: str, period: str, notes: str = "") -> FinancialMetric:
            return FinancialMetric(
                value=value,
                unit=unit,
                period=period,
                source=quote.get("source", "AVGO TEST/DEMO fixture"),
                source_type=SourceType.FIXTURE,
                as_of=d,
                confidence=0.5,
                is_estimated=True,
                notes=notes or _DEMO_NOTE,
            )

        cash_val = balance["cash"]
        debt_val = balance["total_debt"]
        net_debt_val = debt_val - cash_val

        return CompanyFinancialSnapshot(
            ticker="AVGO",
            company_name=profile["name"],
            currency=profile["currency"],

            # Price
            current_price=fm(quote["price"], "USD", str(d),
                             "Fixture price. Intentionally stale — not real-time data."),
            price_timestamp=FIXTURE_TIMESTAMP,
            diluted_shares=fm(profile["diluted_shares"], "shares", balance["period"],
                              "Synthetic diluted share count"),

            # Balance sheet
            cash=fm(cash_val, "USD", balance["period"], "Synthetic cash & equivalents"),
            total_debt=fm(debt_val, "USD", balance["period"], "Synthetic total debt"),

            # net_debt is derived from the two balance-sheet metrics.  It is
            # exposed under both the stable ``net_debt`` key and the legacy
            # ``net_debt_metric`` alias by CompanyFinancialSnapshot.
            net_debt=FinancialMetric(
                value=net_debt_val, unit="USD", period=balance["period"],
                source="Derived from AVGO TEST/DEMO balance sheet",
                source_type=SourceType.DERIVED, as_of=d, confidence=0.5,
                is_estimated=True,
                notes=(
                    f"net_debt = total_debt ({debt_val:,.0f}) - cash ({cash_val:,.0f}); "
                    "derived metric, not a provider quote."
                ),
            ),

            # Income statement
            revenue_ttm=fm(income["revenue_ttm"], "USD", income["period"]),
            ebitda_ttm=fm(income["ebitda_ttm"], "USD", income["period"]),
            eps_ttm=fm(income["eps_ttm"], "USD/share", income["period"]),
            da_ttm=FinancialMetric(
                value=income.get("da", Decimal("4000000000")),
                unit="USD",
                period=str(income.get("da_period") or income["period"]),
                source=quote.get("source", "AVGO TEST/DEMO fixture"),
                source_type=SourceType.FIXTURE,
                as_of=income.get("da_as_of") or d,
                confidence=0.5,
                is_estimated=True,
                notes=_DEMO_NOTE,
            ),
            cfo_ttm=fm(cash_flow.get("cfo", Decimal("25000000000")), "USD", cash_flow["period"]),
            capex_ttm=fm(cash_flow.get("capex", Decimal("3000000000")), "USD", cash_flow["period"]),
            net_borrowing_ttm=fm(cash_flow.get("net_borrowing", Decimal("1000000000")), "USD", cash_flow["period"]),
            nwc_change_ttm=fm(cash_flow.get("nwc_change", Decimal("500000000")), "USD", cash_flow["period"]),
            interest_ttm=fm(cash_flow.get("interest", Decimal("2000000000")), "USD", cash_flow["period"]),

            # FCFE (equity FCF — FCF yield model only)
            fcf_ttm=FinancialMetric(
                value=cash_flow["fcfe_ttm"], unit="USD", period="TTM",
                source="AVGO TEST/DEMO fixture",
                source_type=SourceType.FIXTURE, as_of=d, confidence=0.5, is_estimated=True,
                notes="FCFE (equity FCF). " + cash_flow["fcfe_definition"],
            ),
            forward_fcf_1y=FinancialMetric(
                value=estimates["forward_fcfe_1y"], unit="USD",
                period=estimates["period_1y"],
                source="AVGO TEST/DEMO fixture",
                source_type=SourceType.FIXTURE, as_of=d, confidence=0.5, is_estimated=True,
                notes="Synthetic forward FCFE Y1 estimate (mock analyst-style concept; not actual consensus). FCF yield model only.",
            ),
            forward_fcf_2y=FinancialMetric(
                value=estimates["forward_fcfe_2y"], unit="USD",
                period=estimates["period_2y"],
                source="AVGO TEST/DEMO fixture",
                source_type=SourceType.FIXTURE, as_of=d, confidence=0.5, is_estimated=True,
                notes="Synthetic forward FCFE Y2 estimate (mock analyst-style concept; not actual consensus). FCF yield model only.",
            ),

            # FCFF (firm FCF — DCF model at WACC only)
            fcff_ttm=FinancialMetric(
                value=cash_flow["fcff_ttm"], unit="USD", period="TTM",
                source="AVGO TEST/DEMO fixture",
                source_type=SourceType.FIXTURE, as_of=d, confidence=0.5, is_estimated=True,
                notes="FCFF (firm/unlevered FCF). " + cash_flow["fcff_definition"],
            ),
            forward_fcff_1y=FinancialMetric(
                value=estimates["forward_fcff_1y"], unit="USD",
                period=estimates["period_1y"],
                source="AVGO TEST/DEMO fixture",
                source_type=SourceType.FIXTURE, as_of=d, confidence=0.5, is_estimated=True,
                notes="Synthetic forward FCFF Y1 estimate (mock analyst-style concept; not actual consensus). DCF model only (discounted at WACC).",
            ),
            forward_fcff_2y=FinancialMetric(
                value=estimates["forward_fcff_2y"], unit="USD",
                period=estimates["period_2y"],
                source="AVGO TEST/DEMO fixture",
                source_type=SourceType.FIXTURE, as_of=d, confidence=0.5, is_estimated=True,
                notes="Synthetic forward FCFF Y2 estimate (mock analyst-style concept; not actual consensus). DCF model only (discounted at WACC).",
            ),

            # Forward estimates — EPS & EBITDA
            forward_eps_1y=FinancialMetric(
                value=estimates["forward_eps_1y"], unit="USD/share",
                period=estimates["period_1y"],
                source="AVGO TEST/DEMO fixture",
                source_type=SourceType.FIXTURE, as_of=d, confidence=0.5, is_estimated=True,
                notes="Synthetic forward EPS Y1 estimate (mock analyst-style concept; not actual consensus).",
            ),
            forward_eps_2y=FinancialMetric(
                value=estimates["forward_eps_2y"], unit="USD/share",
                period=estimates["period_2y"],
                source="AVGO TEST/DEMO fixture",
                source_type=SourceType.FIXTURE, as_of=d, confidence=0.5, is_estimated=True,
                notes="Synthetic forward EPS Y2 estimate (mock analyst-style concept; not actual consensus).",
            ),
            forward_ebitda_1y=FinancialMetric(
                value=estimates["forward_ebitda_1y"], unit="USD",
                period=estimates["period_1y"],
                source="AVGO TEST/DEMO fixture",
                source_type=SourceType.FIXTURE, as_of=d, confidence=0.5, is_estimated=True,
                notes="Synthetic forward EBITDA Y1 estimate (mock analyst-style concept; not actual consensus).",
            ),
            forward_ebitda_2y=FinancialMetric(
                value=estimates["forward_ebitda_2y"], unit="USD",
                period=estimates["period_2y"],
                source="AVGO TEST/DEMO fixture",
                source_type=SourceType.FIXTURE, as_of=d, confidence=0.5, is_estimated=True,
                notes="Synthetic forward EBITDA Y2 estimate (mock analyst-style concept; not actual consensus).",
            ),
            revenue_estimate_1y=fm(
                estimates.get("forward_revenue_1y", Decimal("65000000000")), "USD", estimates["period_1y"],
                "Synthetic forward revenue Y1 estimate."
            ),
            revenue_estimate_2y=fm(
                estimates.get("forward_revenue_2y", Decimal("75000000000")), "USD", estimates["period_2y"],
                "Synthetic forward revenue Y2 estimate."
            ),
            forward_revenue=fm(
                estimates.get("forward_revenue_1y", Decimal("65000000000")), "USD", estimates["period_1y"],
                "Synthetic forward revenue estimate."
            ),

            # Historical multiples
            historical_forward_pe=fm(
                multiples["historical_forward_pe"], "ratio", multiples["period"],
                "Synthetic 5-year median forward P/E"
            ),
            historical_ev_ebitda=fm(
                multiples["historical_ev_ebitda"], "ratio", multiples["period"],
                "Synthetic 5-year median EV/EBITDA"
            ),

            # Growth metrics (derived from fixture)
            revenue_growth=fm(Decimal("0.51"), "ratio", "YoY FY2024",
                              "Synthetic revenue YoY growth (includes VMware acquisition)"),
            ebitda_growth=fm(Decimal("0.45"), "ratio", "YoY FY2024",
                             "Synthetic EBITDA YoY growth"),
            eps_growth=fm(Decimal("0.25"), "ratio", "YoY FY2024",
                          "Synthetic EPS YoY growth"),
            fcf_growth=fm(Decimal("0.51"), "ratio", "YoY FY2024",
                          "Synthetic FCFE YoY growth"),
            fcff_growth=fm(Decimal("0.50"), "ratio", "YoY FY2024",
                           "Synthetic FCFF YoY growth"),


            data_quality=DataQuality.LOW,
            is_demo=True,
            country=profile.get("country", "US"),
            security_type=profile.get("security_type", "COMMON_STOCK"),
            sector=profile.get("sector"),
            industry=profile.get("industry"),
            is_profitable=profile.get("is_profitable", True),
            warnings=[
                "DEMO DATA: All values are synthetic fixtures for testing/educational purposes only.",
                "Fixture date 2025-01-15 is intentionally static and will NOT be auto-updated.",
                "FCFE and FCFF are separately labeled with distinct economic definitions.",
                "net_debt = total_debt - cash exposed as provenance-rich metric.",
                "Do not use for real investment decisions.",
            ],
        )

    def supports_ticker(self, ticker: str) -> bool:
        return ticker.strip().upper() in SUPPORTED_DEMO_TICKERS
