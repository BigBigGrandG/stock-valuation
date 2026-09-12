"""
test_api_integration.py
Integration tests for the FastAPI endpoints using httpx TestClient.
Tests: GET/POST valuation, snapshot, invalid ticker, nested overrides,
WACC<=g rejection, extra fields rejection, reset, demo marker, errors.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import json
from decimal import Decimal
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_root():
    r = client.get("/")
    assert r.status_code == 200
    data = r.json()
    assert "service" in data
    assert "AVGO" in data.get("demo_ticker", "")


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_get_snapshot_avgo():
    r = client.get("/api/v1/company/AVGO/snapshot")
    assert r.status_code == 200
    data = r.json()
    assert data["ticker"] == "AVGO"
    assert data["is_demo"] is True
    assert data["data_quality"] == "LOW"
    # net_debt_metric must be a full provenance object
    ndm = data.get("net_debt_metric")
    assert ndm is not None, "net_debt_metric must be serialized"
    assert "value" in ndm
    assert "source_type" in ndm


def test_snapshot_unknown_ticker_404():
    r = client.get("/api/v1/company/ZZZZZ/snapshot")
    assert r.status_code == 404
    assert "ZZZZZ" in r.text or "not found" in r.text.lower()


def test_get_valuation_avgo():
    r = client.get("/api/v1/valuation/AVGO")
    assert r.status_code == 200
    data = r.json()

    assert data["ticker"] == "AVGO"
    assert data["is_demo"] is True
    assert data["data_quality"] == "LOW"

    # as_of must be fixture date (2025-01-15), not server time
    assert "2025-01-15" in data["as_of"]

    # valuations dict with all 4 models
    vals = data.get("valuations", {})
    assert set(vals.keys()) == {"forward_pe", "ev_ebitda", "fcf_yield", "dcf"}

    # Each model exposes only its own low/base/high scenario values.
    for model_name, model in vals.items():
        assert "base" in model, f"{model_name} missing base scenario"
        assert "low" in model or model.get("available") is False
        assert "high" in model or model.get("available") is False

    # Cross-model synthesis and weight metadata are not part of the API.
    assert "composite" not in data
    assert not any(key.startswith("weight_") for key in data["assumptions_used"])


def test_valuation_unknown_ticker_404():
    r = client.get("/api/v1/valuation/ZZZZZ")
    assert r.status_code == 404


def test_post_valuation_nested_override():
    """POST with nested JSON body as specified in backend-revisions.md."""
    body = {
        "forward_pe": {"base": 18},
        "fcf_yield": {"base": 0.05},
        "dcf": {"wacc": 0.095, "terminal_growth": 0.035},
    }
    r = client.post("/api/v1/valuation/AVGO", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["ticker"] == "AVGO"
    vals = data["valuations"]
    # PE base should reflect override (18x * 19.21 = 345.78)
    pe_base = vals["forward_pe"]["base"]["price_per_share"]
    assert pe_base == "345.78", f"PE base with override 18x: expected 345.78, got {pe_base}"


def test_post_valuation_sparse_base_auto_derives_bounds():
    """Sparse base-only PE override should auto-derive low/high bounds."""
    body = {"forward_pe": {"base": 20}}
    r = client.post("/api/v1/valuation/AVGO", json=body)
    assert r.status_code == 200
    data = r.json()
    pe = data["valuations"]["forward_pe"]
    low = Decimal(pe["low"]["price_per_share"])
    base_val = Decimal(pe["base"]["price_per_share"])
    high = Decimal(pe["high"]["price_per_share"])
    assert low < base_val < high, f"low={low} base={base_val} high={high}"


def test_post_valuation_unknown_field_rejected():
    """Extra/unknown fields must be rejected with 422."""
    body = {"unknown_model": {"base": 5}}
    r = client.post("/api/v1/valuation/AVGO", json=body)
    assert r.status_code == 422


def test_post_valuation_nested_unknown_field_rejected():
    """Unknown nested fields must be rejected with 422."""
    body = {"forward_pe": {"median": 18}}
    r = client.post("/api/v1/valuation/AVGO", json=body)
    assert r.status_code == 422


def test_post_valuation_wacc_le_g_rejected():
    """WACC <= terminal_growth must return 422."""
    body = {"dcf": {"wacc": 0.03, "terminal_growth": 0.04}}
    r = client.post("/api/v1/valuation/AVGO", json=body)
    assert r.status_code == 422


def test_post_valuation_invalid_pe_range():
    """P/E > 200 must return 422."""
    body = {"forward_pe": {"base": 250}}
    r = client.post("/api/v1/valuation/AVGO", json=body)
    assert r.status_code == 422


def test_post_valuation_unknown_ticker():
    body = {"forward_pe": {"base": 18}}
    r = client.post("/api/v1/valuation/ZZZZZ", json=body)
    assert r.status_code == 404


def test_reset_clears_cache():
    """Reset endpoint returns fresh valuation with defaults."""
    r = client.get("/api/v1/valuation/AVGO/reset")
    assert r.status_code == 200
    data = r.json()
    assert data["ticker"] == "AVGO"
    assert "composite" not in data
    assert data["valuations"]["forward_pe"]["base"]["price_per_share"] is not None


def test_decimal_fields_are_strings():
    """All Decimal fields must be serialized as strings."""
    r = client.get("/api/v1/valuation/AVGO")
    assert r.status_code == 200
    data = r.json()
    # current_price should be a string
    assert isinstance(data["current_price"], str)
    assert isinstance(data["valuations"]["forward_pe"]["base"]["price_per_share"], str)


def test_demo_marker_always_present():
    """is_demo must always be True for AVGO fixture."""
    r = client.get("/api/v1/valuation/AVGO")
    assert r.json()["is_demo"] is True


def test_avgo_not_cloned_for_unknown_ticker():
    """Unknown tickers must never return AVGO data."""
    r = client.get("/api/v1/valuation/MSFT")
    assert r.status_code == 404
    body = r.json()
    # Should not contain AVGO data
    assert "Broadcom" not in str(body)


def test_snapshot_net_debt_value():
    """net_debt_metric.value should equal total_debt - cash."""
    r = client.get("/api/v1/company/AVGO/snapshot")
    data = r.json()
    # From fixture: 59400000000 - 24000000000 = 35400000000
    ndm = data["net_debt_metric"]
    assert ndm["value"] == "35400000000"


def test_fcf_yield_inverse_order():
    """FCF yield override inverse validation: low_rate must >= high_rate."""
    # Valid: low=0.06, high=0.04 (conservative to optimistic)
    body = {"fcf_yield": {"low": 0.06, "base": 0.05, "high": 0.04}}
    r = client.post("/api/v1/valuation/AVGO", json=body)
    assert r.status_code == 200

    # Invalid: low < high (would mean conservative has lower yield than optimistic)
    body2 = {"fcf_yield": {"low": 0.04, "high": 0.06}}
    r2 = client.post("/api/v1/valuation/AVGO", json=body2)
    assert r2.status_code == 422
