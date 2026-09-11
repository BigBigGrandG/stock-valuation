"""Bounded live audit script for Issue 01 & 02 verification.
Queries NVDA, GOOG, AMD, META using live YFinanceProvider,
verifies statement basis (TTM vs annual), financial bridge,
model availabilities, periods, and records raw responses.
"""
import json
import os
import sys
from datetime import date, datetime
from decimal import Decimal

# Add backend to sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "backend"))

# Force live provider
os.environ["DATA_PROVIDER"] = "live"

from app.config import DEFAULT_ASSUMPTIONS
from app.providers.yfinance_provider import YFinanceProvider
from app.services.valuation_service import FinancialDataService, MemoryTTLCache, ValuationService


class DecimalAndDateEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        return super().default(obj)


def run_live_audit():
    tickers = ["NVDA", "GOOG", "AMD", "META"]
    provider = YFinanceProvider(timeout=15.0)
    cache = MemoryTTLCache()
    data_svc = FinancialDataService(provider=provider, cache=cache, default_assumptions=DEFAULT_ASSUMPTIONS)
    val_svc = ValuationService(data_svc, default_assumptions=DEFAULT_ASSUMPTIONS)

    results = {}
    print(f"Starting live audit for tickers: {tickers}...")

    for ticker in tickers:
        print(f"Querying {ticker} (timeout=15s)...")
        start_t = datetime.now()
        try:
            resp = val_svc.compute(ticker)
            elapsed = (datetime.now() - start_t).total_seconds()
            resp_dict = resp.model_dump(mode="json")
            
            # Extract high-level audit summary
            summary = {
                "status": "success",
                "elapsed_seconds": elapsed,
                "ticker": resp.ticker,
                "company_name": resp.company_name,
                "current_price": str(resp.current_price),
                "currency": resp.currency,
                "is_demo": resp.is_demo,
                "statement_basis": resp.statement_basis,
                "annual_fallback": resp.annual_fallback,
                "shares_basis": resp.shares_basis,
                "forecast_fiscal_year_end": str(resp.forecast_fiscal_year_end) if resp.forecast_fiscal_year_end else None,
                "models": {
                    k: {
                        "available": v.available,
                        "fair_value_base": str(v.base.price_per_share) if v.base else None,
                        "unavailable_reason": v.unavailable_reason if not v.available else None,
                    }
                    for k, v in resp.valuations.items()
                },
                "financial_bridge": resp.financial_bridge,
                "warnings_count": len(resp.warnings),
            }
            results[ticker] = {
                "summary": summary,
                "raw_response": resp_dict,
            }
            print(f"[{ticker}] SUCCESS ({elapsed:.2f}s) - Price: {resp.current_price} {resp.currency} - Basis: {resp.statement_basis} - Bridge present: {resp.financial_bridge is not None}")
        except Exception as e:
            elapsed = (datetime.now() - start_t).total_seconds()
            print(f"[{ticker}] ERROR ({elapsed:.2f}s): {type(e).__name__}: {e}")
            results[ticker] = {
                "summary": {
                    "status": "error",
                    "elapsed_seconds": elapsed,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                },
                "raw_response": None,
            }

    out_path = os.path.join(os.path.dirname(__file__), "live_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, cls=DecimalAndDateEncoder, indent=2, ensure_ascii=False)
    print(f"Audit results written to {out_path}")


if __name__ == "__main__":
    run_live_audit()
