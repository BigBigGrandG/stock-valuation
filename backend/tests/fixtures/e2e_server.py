"""Deterministic FastAPI server for fullstack Playwright E2E testing.

Runs an isolated FastAPI app instance with deterministic mock bundles wired to the
real production pipeline on an isolated test port (default 18082).
Allows test port 13002 via CORS strictly on this test app instance.
"""
import os
import sys
from pathlib import Path

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.main import app as main_app, _live_provider
from tests.fixtures.mock_bundles import get_mock_bundle_for_ticker

# Inject deterministic bundle routing into the production YFinanceProvider instance
_live_provider._get_bundle = get_mock_bundle_for_ticker

# Create dedicated test FastAPI app inheriting all production routes
app = FastAPI(
    title="E2E Test Valuation API",
    description="Isolated test instance for fullstack browser verification",
    version="0.2.0-test",
    routes=main_app.routes,
)

# Configure CORS strictly on this test app instance to permit isolated frontend port 13002
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:13002",
        "http://127.0.0.1:13002",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/e2e/health")
def e2e_health() -> dict[str, object]:
    return {
        "status": "ok",
        "service": "deterministic-e2e-fixture",
        "port": int(os.getenv("PORT", "18082")),
        "scenarios": ["growth", "annual_fallback", "conflict"],
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "18082"))
    uvicorn.run(app, host="127.0.0.1", port=port)
