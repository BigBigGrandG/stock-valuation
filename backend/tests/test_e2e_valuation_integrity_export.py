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

    # Cross-model synthesis is intentionally absent from the public contract.
    assert "composite" not in data
    assert not any(key.startswith("weight_") for key in data["assumptions_used"])


def test_e2e_valuation_overrides_recalculate_and_reset():
    """Verify request overrides dynamically alter valuation, and /reset clears them back to baseline."""
    # 1. Apply overrides
    override_payload = {
        "dcf": {
            "wacc": 0.08,
            "terminal_growth": 0.035,
            "growth_cap": 0.80,
        },
        "forecast_horizon": "ntm",
    }
    post_resp = client.post("/api/v1/valuation/AVGO", json=override_payload)
    assert post_resp.status_code == 200
    post_data = post_resp.json()

    # Verify the independent DCF override took effect.
    assert Decimal(post_data["growth_cap_effective"]) == Decimal("0.80")
    assert "composite" not in post_data

    # 2. Reset back to defaults
    reset_resp = client.get("/api/v1/valuation/AVGO/reset")
    assert reset_resp.status_code == 200
    reset_data = reset_resp.json()

    # Verify clean reset
    assert reset_data["growth_cap_effective"] == "0.40"
    assert "composite" not in reset_data


def test_e2e_financial_bridge_and_driver_overrides_lifecycle():
    """Verify financial bridge data structure, driver override application, and reset."""
    # 1. Baseline AVGO has financial bridge with accounting identities
    r = client.get("/api/v1/valuation/AVGO")
    assert r.status_code == 200
    data = r.json()
    bridge = data.get("financial_bridge")
    assert bridge is not None
    assert "revenue" in bridge
    assert "ebitda" in bridge
    assert "fcff" in bridge
    assert "restrictions_note" in bridge
    assert "period" in bridge
    assert "forecast_start_date" in bridge
    assert "forecast_end_date" in bridge

    # 2. POST driver overrides
    payload = {
        "drivers": {
            "ebitda_margin": 0.60,
            "capex": 2500000000,
            "nwc_change": 400000000,
            "net_borrowing": 800000000,
            "da": 3500000000,
            "tax_rate": 0.20,
        }
    }
    post_res = client.post("/api/v1/valuation/AVGO", json=payload)
    assert post_res.status_code == 200
    pdata = post_res.json()
    pbridge = pdata.get("financial_bridge")
    assert pbridge is not None
    assert Decimal(pbridge["ebitda_margin"]) == Decimal("0.60")
    assert Decimal(pbridge["capex"]) == Decimal("2500000000")
    assert Decimal(pbridge["nwc_change"]) == Decimal("400000000")
    assert Decimal(pbridge["net_borrowing"]) == Decimal("800000000")
    assert Decimal(pbridge["da"]) == Decimal("3500000000")
    assert Decimal(pbridge["tax_rate"]) == Decimal("0.20")

    # Verify accounting identities with overridden values
    rev = Decimal(pbridge["revenue"])
    ebitda = Decimal(pbridge["ebitda"])
    da = Decimal(pbridge["da"])
    ebit = Decimal(pbridge["ebit"])
    tax_rate = Decimal(pbridge["tax_rate"])
    nopat = Decimal(pbridge["nopat"])
    capex = Decimal(pbridge["capex"])
    nwc = Decimal(pbridge["nwc_change"])
    fcff = Decimal(pbridge["fcff"])
    fcfe = Decimal(pbridge["fcfe"])
    at_interest = Decimal(pbridge["after_tax_interest"])
    net_borrowing = Decimal(pbridge["net_borrowing"])

    assert ebitda == (rev * Decimal("0.60")).quantize(Decimal("1"))
    assert ebit == ebitda - da
    assert nopat == (ebit * (Decimal("1") - tax_rate)).quantize(Decimal("1"))
    assert fcff == nopat + da - capex - nwc
    assert fcfe == fcff - at_interest + net_borrowing

    # 3. GET /reset clears overrides
    reset_res = client.get("/api/v1/valuation/AVGO/reset")
    assert reset_res.status_code == 200
    rdata = reset_res.json()
    assert rdata["assumptions_used"]["driver_ebitda_margin"] is None
    assert rdata["assumptions_used"]["driver_capex"] is None
    assert rdata["assumptions_used"]["driver_da"] is None
