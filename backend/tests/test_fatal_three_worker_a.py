"""Worker A contract tests for the retired cross-model composite surface."""

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def _walk_keys(value: object, path: str = ""):
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            yield child_path, key
            yield from _walk_keys(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_keys(child, f"{path}[{index}]")


def test_public_valuation_has_only_independent_model_scenarios():
    response = client.get("/api/v1/valuation/AVGO")

    assert response.status_code == 200
    payload = response.json()
    assert "composite" not in payload
    assert set(payload["valuations"]) == {"forward_pe", "ev_ebitda", "fcf_yield", "dcf"}

    for model in payload["valuations"].values():
        if model["available"]:
            assert {"low", "base", "high"}.issubset(model)

    forbidden = {
        path
        for path, key in _walk_keys(payload)
        if any(token in key.lower() for token in ("composite", "fair_value", "effective_weights", "weights_used", "selected_weights"))
    }
    assert forbidden == set()


def test_public_schema_does_not_publish_composite_or_model_weights():
    schemas = app.openapi()["components"]["schemas"]
    response_properties = schemas["ValuationResponse"]["properties"]
    assumptions_properties = schemas["ValuationAssumptionsResponse"]["properties"]
    override_properties = schemas["ValuationOverrideRequest"]["properties"]

    assert "composite" not in response_properties
    assert not any("weight" in name for name in assumptions_properties)
    assert "weights" not in override_properties


def test_public_post_rejects_retired_weight_override():
    response = client.post("/api/v1/valuation/AVGO", json={"weights": {"weight_pe": 1.0}})

    assert response.status_code == 422
