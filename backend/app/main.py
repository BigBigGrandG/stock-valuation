"""FastAPI HTTP surface for the educational stock-valuation MVP."""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import DEFAULT_ASSUMPTIONS, CACHE_TTL_SECONDS, DATA_PROVIDER
from app.models.domain import (
    CompanyFinancialSnapshot,
    ValuationResponse,
)
from app.models.overrides import OverrideValidationError, ValuationOverrideRequest
from app.providers.avgo_fixture import AVGOFixtureProvider
from app.providers.yfinance_provider import YFinanceProvider
from app.providers.base import (
    FinancialDataProvider,
    FinancialDataValidationError,
    InvalidTickerError,
    ProviderError,
    ProviderRateLimitError,
    ProviderUnavailableError,
    StaleDataError,
    TickerNotFoundError,
    UnsupportedCompanyError,
)
from app.services.valuation_service import FinancialDataService, MemoryTTLCache, ValuationService


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    demo_tickers: list[str]


class _DecimalEncoder(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        if isinstance(obj, Decimal):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def _json_response(data: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        content=json.loads(json.dumps(data, cls=_DecimalEncoder, default=str)),
        status_code=status_code,
    )


app = FastAPI(
    title="US Stock Valuation API",
    description=(
        "Educational US stock valuation API. Four deterministic Decimal models: "
        "Forward P/E, EV/EBITDA, FCF Yield (FCFE) and DCF (FCFF). "
        "AVGO is a fixed demo fixture; this is not investment advice. "
        "Decimal fields are serialized as JSON strings."
    ),
    version="0.2.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_demo_provider = AVGOFixtureProvider()
_live_provider = YFinanceProvider()

_demo_data_service = FinancialDataService(provider=_demo_provider, cache=MemoryTTLCache(), default_assumptions=DEFAULT_ASSUMPTIONS)
_demo_valuation_service = ValuationService(_demo_data_service, default_assumptions=DEFAULT_ASSUMPTIONS)

_live_data_service = FinancialDataService(provider=_live_provider, cache=MemoryTTLCache(), default_assumptions=DEFAULT_ASSUMPTIONS)
_live_valuation_service = ValuationService(_live_data_service, default_assumptions=DEFAULT_ASSUMPTIONS)

_initial_mode = os.getenv("DATA_PROVIDER", DATA_PROVIDER).lower()
_data_service: FinancialDataService = _demo_data_service if _initial_mode == "demo" else _live_data_service
_valuation_service: ValuationService = _demo_valuation_service if _initial_mode == "demo" else _live_valuation_service
_provider: FinancialDataProvider = _data_service._provider
_cache = _data_service._cache


def _resolve_data_service(provider_override: Optional[str] = None) -> FinancialDataService:
    if provider_override:
        return _demo_data_service if provider_override.lower() == "demo" else _live_data_service
    return _data_service


def _resolve_valuation_service(provider_override: Optional[str] = None) -> ValuationService:
    if provider_override:
        return _demo_valuation_service if provider_override.lower() == "demo" else _live_valuation_service
    return _valuation_service


def _enrich(data: dict[str, Any]) -> dict[str, Any]:
    """Return the public response without retired composite aliases."""

    return data


def _raise_http(exc: Exception) -> None:
    if isinstance(exc, TickerNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, InvalidTickerError):
        raise HTTPException(status_code=422, detail={"error": "invalid_ticker", "detail": str(exc)})
    if isinstance(exc, UnsupportedCompanyError):
        raise HTTPException(status_code=422, detail={
            "error": "unsupported_company_type",
            "ticker": exc.ticker,
            "reason": exc.reason,
            "detail": exc.detail,
        })
    if isinstance(exc, FinancialDataValidationError):
        raise HTTPException(status_code=422, detail={"error": "financial_data_validation", "detail": str(exc)})
    if isinstance(exc, OverrideValidationError):
        raise HTTPException(status_code=422, detail={"error": "invalid_override", "detail": str(exc)})
    if isinstance(exc, ProviderRateLimitError):
        raise HTTPException(status_code=429, detail=str(exc))
    if isinstance(exc, (ProviderUnavailableError, StaleDataError)):
        raise HTTPException(status_code=503, detail=f"Provider unavailable: {exc}")
    if isinstance(exc, ProviderError):
        raise HTTPException(status_code=503, detail=f"Provider unavailable: {exc}")
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=422, detail=str(exc))
    raise exc


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", service="US Stock Valuation API", version="0.2.0", demo_tickers=["AVGO"])


@app.get("/")
async def root() -> dict[str, Any]:
    return {
        "service": "US Stock Valuation API",
        "version": "0.2.0",
        "docs": "/docs",
        "health": "/health",
        "demo_ticker": "AVGO",
        "note": "DEMO data only. Not for real investment decisions.",
        "decimal_note": "All Decimal fields are serialized as JSON strings for precision.",
        "endpoints": [
            "GET /health",
            "GET /api/v1/company/{ticker}/snapshot",
            "GET /api/v1/valuation/{ticker}",
            "POST /api/v1/valuation/{ticker}",
            "GET /api/v1/valuation/{ticker}/reset",
        ],
    }


@app.get("/api/v1/company/{ticker}/snapshot", response_model=CompanyFinancialSnapshot)
async def get_snapshot(ticker: str, provider: Optional[str] = None) -> JSONResponse:
    try:
        svc = _resolve_data_service(provider)
        snapshot = await asyncio.to_thread(svc.get_snapshot, ticker)
        return _json_response(snapshot.model_dump(mode="json"))
    except Exception as exc:
        _raise_http(exc)
        raise AssertionError("unreachable")


@app.get("/api/v1/valuation/{ticker}", response_model=ValuationResponse)
async def get_valuation(ticker: str, provider: Optional[str] = None) -> JSONResponse:
    try:
        svc = _resolve_valuation_service(provider)
        response = await asyncio.to_thread(svc.compute, ticker)
        return _json_response(_enrich(response.model_dump(mode="json")))
    except Exception as exc:
        _raise_http(exc)
        raise AssertionError("unreachable")


@app.post("/api/v1/valuation/{ticker}", response_model=ValuationResponse)
async def post_valuation(
    ticker: str,
    body: ValuationOverrideRequest,
    provider: Optional[str] = None,
) -> JSONResponse:
    try:
        svc = _resolve_valuation_service(provider)
        response = await asyncio.to_thread(
            svc.compute, ticker, overrides=body.to_override_dict()
        )
        return _json_response(_enrich(response.model_dump(mode="json")))
    except Exception as exc:
        _raise_http(exc)
        raise AssertionError("unreachable")


@app.get("/api/v1/valuation/{ticker}/reset", response_model=ValuationResponse)
async def reset_valuation(ticker: str, provider: Optional[str] = None) -> JSONResponse:
    try:
        svc = _resolve_valuation_service(provider)
        response = await asyncio.to_thread(
            svc.compute, ticker, bypass_cache=True
        )
        return _json_response(_enrich(response.model_dump(mode="json")))
    except Exception as exc:
        _raise_http(exc)
        raise AssertionError("unreachable")


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"error": "internal_server_error", "detail": str(exc)})
