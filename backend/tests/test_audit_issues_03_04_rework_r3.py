"""R3 acceptance regressions for conservative taxonomy mapping and replay oracles."""

from app.services.multiples import industry_multiple_payload, lookup_industry_benchmark


def test_r3_unsubstantiated_internet_taxonomy_alias_degrades_conservatively():
    """A Yahoo label is not enough evidence for a Damodaran row equivalence."""

    assert lookup_industry_benchmark("Communication Services", "Internet Content & Information") is None
    payload = industry_multiple_payload("Communication Services", "Internet Content & Information")
    assert payload["industry_name"] is None
    assert "No public snapshot row" in payload["industry_unavailable_reason"]


def test_r3_unsubstantiated_beverage_taxonomy_alias_degrades_conservatively():
    """A descriptive similarity does not prove the public rows are comparable."""

    assert lookup_industry_benchmark("Consumer Defensive", "Beverages - Non-Alcoholic") is None
