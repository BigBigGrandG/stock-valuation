"""Single source of truth for valuation assumptions and service policy."""
from __future__ import annotations

from decimal import Decimal

import os

from app.models.domain import ScenarioValues, SourceType, ValuationAssumptions

# Data provider configuration: "live" (default) or "demo" (explicit opt-in for offline tests)
DATA_PROVIDER = os.getenv("DATA_PROVIDER", "live").lower()

# Default model assumptions. Rates are decimals (0.05 == 5%).
DEFAULT_PE_TARGET = ScenarioValues(low=Decimal("18"), base=Decimal("20"), high=Decimal("22"))
DEFAULT_EV_EBITDA_MULTIPLE = ScenarioValues(
    low=Decimal("18"), base=Decimal("22"), high=Decimal("26")
)
DEFAULT_FCF_YIELD = ScenarioValues(
    low=Decimal("0.055"), base=Decimal("0.050"), high=Decimal("0.045")
)
DEFAULT_DCF_WACC = ScenarioValues(
    low=Decimal("0.12"), base=Decimal("0.10"), high=Decimal("0.08")
)
DEFAULT_DCF_TERMINAL_GROWTH = ScenarioValues(
    low=Decimal("0.03"), base=Decimal("0.03"), high=Decimal("0.04")
)

DCF_TERMINAL_GROWTH_MAX = Decimal("0.05")
FCF_GROWTH_CAP_BEAR = Decimal("0.25")
FCF_GROWTH_CAP_BASE = Decimal("0.30")
FCF_GROWTH_CAP_BULL = Decimal("0.35")
FCF_GROWTH_FLOOR = Decimal("-0.10")
DEFAULT_DCF_FCF_GROWTH_FALLBACK = ScenarioValues(
    low=Decimal("0.05"), base=Decimal("0.08"), high=Decimal("0.12")
)


# Composite weights are deliberately defined in one place.
DEFAULT_WEIGHT_PE = Decimal("0.25")
DEFAULT_WEIGHT_EV_EBITDA = Decimal("0.20")
DEFAULT_WEIGHT_FCF_YIELD = Decimal("0.25")
DEFAULT_WEIGHT_DCF = Decimal("0.30")
DEFAULT_CASHFLOW_GROUP_MAX_WEIGHT = Decimal("0.40")
DEFAULT_GROWTH_FLOOR = Decimal("-0.20")
DEFAULT_GROWTH_CAP = Decimal("0.40")
DEFAULT_FORECAST_HORIZON = "ntm"
assert (
    DEFAULT_WEIGHT_PE
    + DEFAULT_WEIGHT_EV_EBITDA
    + DEFAULT_WEIGHT_FCF_YIELD
    + DEFAULT_WEIGHT_DCF
) == Decimal("1.00")


# Classification ratio = current_price / fair_value.
CLASSIFICATION_SIGNIFICANTLY_UNDERVALUED_MAX = Decimal("0.80")
CLASSIFICATION_UNDERVALUED_MAX = Decimal("0.90")
CLASSIFICATION_SLIGHTLY_UNDERVALUED_STRICT_MAX = Decimal("1.00")
CLASSIFICATION_FAIRLY_VALUED_MAX = Decimal("1.10")
CLASSIFICATION_OVERVALUED_MAX = Decimal("1.25")


DEFAULT_ASSUMPTIONS = ValuationAssumptions(
    pe_target=DEFAULT_PE_TARGET,
    pe_source=SourceType.CONFIGURED_FALLBACK,
    pe_source_label="Configured fallback: 18x/20x/22x (low/base/high)",
    ev_ebitda_multiple=DEFAULT_EV_EBITDA_MULTIPLE,
    ev_ebitda_source=SourceType.CONFIGURED_FALLBACK,
    ev_ebitda_source_label="Configured fallback: 18x/22x/26x (low/base/high)",
    fcf_yield=DEFAULT_FCF_YIELD,
    fcf_yield_source=SourceType.CONFIGURED_FALLBACK,
    fcf_yield_source_label="Configured fallback: 5.5%/5.0%/4.5% (low=high yield=conservative)",
    dcf_wacc=DEFAULT_DCF_WACC,
    dcf_terminal_growth=DEFAULT_DCF_TERMINAL_GROWTH,
    dcf_fcf_growth=None,
    dcf_wacc_source=SourceType.CONFIGURED_FALLBACK,
    dcf_wacc_source_label="Configured fallback: 12%/10%/8% (bear/base/bull)",
    dcf_terminal_growth_source=SourceType.CONFIGURED_FALLBACK,
    dcf_terminal_growth_source_label="Configured fallback terminal growth",
    weight_pe=DEFAULT_WEIGHT_PE,
    weight_ev_ebitda=DEFAULT_WEIGHT_EV_EBITDA,
    weight_fcf_yield=DEFAULT_WEIGHT_FCF_YIELD,
    weight_dcf=DEFAULT_WEIGHT_DCF,
    cashflow_group_max_weight=DEFAULT_CASHFLOW_GROUP_MAX_WEIGHT,
    growth_floor=DEFAULT_GROWTH_FLOOR,
    growth_cap=DEFAULT_GROWTH_CAP,
    forecast_horizon=DEFAULT_FORECAST_HORIZON,
)


# Per-category TTL policy. FinancialDataService uses these values for raw
# provider results; a monotonic clock is injected into the cache for tests.
TTL_QUOTE_SECONDS = 120
TTL_STATEMENTS_SECONDS = 86400
TTL_ESTIMATES_SECONDS = 43200
TTL_MULTIPLES_SECONDS = 86400
TTL_PROFILE_SECONDS = 86400
TTL_DEMO_SECONDS = 60
CACHE_TTL_SECONDS = {
    "quote": TTL_QUOTE_SECONDS,
    "profile": TTL_PROFILE_SECONDS,
    "statements": TTL_STATEMENTS_SECONDS,
    "balance_sheet": TTL_STATEMENTS_SECONDS,
    "cash_flow": TTL_STATEMENTS_SECONDS,
    "income_statement": TTL_STATEMENTS_SECONDS,
    "estimates": TTL_ESTIMATES_SECONDS,
    "multiples": TTL_MULTIPLES_SECONDS,
}
