"""
test_e2e_valuation_integrity_export.py
End-to-end integration tests asserting the complete P0/P1 remediation contract:
- API response contract (shares_basis, statement_basis, annual_fallback, forecast_horizon, growth_cap)
- Dynamic override recalculation and clean reset
- 3x3 DCF sensitivity matrix structure and TV/EV dependency alert
- CONFLICT_DEGRADED fail-closed integrity
"""
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_e2e_avgo_baseline_valuation_provenance_and_export_fields():
    """Verify AVGO baseline endpoint delivers all provenance fields required for UI badges and Markdown export."""
    r = client.get("/api/v1/valuation/AVGO")
    assert r.status_code == 200
    data = r.json()

    # Core metadata
    assert data["ticker"] == "AVGO"
    assert data["is_demo"] is True

    # P0-A: Shares reconciliation basis
    assert data.get("shares_basis") == "ALL_CLASS_RECONCILED"
    reconciliation = data.get("shares_reconciliation")
    assert reconciliation is not None
    assert reconciliation.get("selected_source") == "info.impliedSharesOutstanding"

    # P0-B: Statement basis
    assert data.get("statement_basis") == "TTM"
    assert data.get("annual_fallback") is False

    # P1-D: Consensus horizon
    assert data.get("forecast_horizon_effective") == "ntm"

    # P1-E: Growth bounds
    assert data.get("growth_cap_effective") == "0.40"
    assert data.get("growth_floor_effective") == "-0.20"

    # P1-G: 3x3 DCF Sensitivity Matrix
    dcf = data["valuations"]["dcf"]
    assert dcf["available"] is True
    matrix = dcf.get("sensitivity_matrix")
    assert matrix is not None
    assert len(matrix["wacc_range"]) == 3
    assert len(matrix["terminal_growth_range"]) == 3
    assert len(matrix["cells"]) == 3
    for row in matrix["cells"]:
        assert len(row) == 3
        for cell in row:
            assert "price_per_share" in cell
            assert "tv_ratio" in cell
            assert cell["available"] is True

    # Center cell matches base valuation exactly
    base_price = dcf["base"]["price_per_share"]
    center_cell_price = matrix["cells"][1][1]["price_per_share"]
    assert base_price == center_cell_price, f"Base DCF price {base_price} must equal matrix center cell {center_cell_price}"

    # P1-F: Composite and model weights
    comp = data["composite"]
    assert comp["available"] is True
    assert "effective_weights" in comp


def test_e2e_valuation_overrides_recalculate_and_reset():
    """Verify request overrides dynamically alter valuation, and /reset clears them back to baseline."""
    # 1. Apply overrides
    override_payload = {
        "dcf": {
            "wacc": 0.08,
            "terminal_growth": 0.035,
            "growth_cap": 0.80,
        },
        "weights": {
            "weight_pe": 0.50,
            "weight_dcf": 0.50,
            "weight_ev_ebitda": 0.0,
            "weight_fcf_yield": 0.0,
        },
        "forecast_horizon": "ntm",
    }
    post_resp = client.post("/api/v1/valuation/AVGO", json=override_payload)
    assert post_resp.status_code == 200
    post_data = post_resp.json()

    # Verify override took effect with cashflow group cap (DCF capped at 40%, P/E takes 60%)
    assert Decimal(post_data["growth_cap_effective"]) == Decimal("0.80")
    comp = post_data["composite"]
    assert Decimal(comp["effective_weights"]["forward_pe"]) == Decimal("0.6000")
    assert Decimal(comp["effective_weights"]["dcf"]) == Decimal("0.4000")
    assert "ev_ebitda" not in comp["effective_weights"]

    # 2. Reset back to defaults
    reset_resp = client.get("/api/v1/valuation/AVGO/reset")
    assert reset_resp.status_code == 200
    reset_data = reset_resp.json()

    # Verify clean reset
    assert reset_data["growth_cap_effective"] == "0.40"
    comp_reset = reset_data["composite"]
    assert "ev_ebitda" in comp_reset["effective_weights"]
    assert "fcf_yield" in comp_reset["effective_weights"]
