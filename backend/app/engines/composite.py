"""Composite valuation over complete positive three-scenario model results."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from app.models.domain import (
    CompositeValuation,
    DataQuality,
    ModelValuation,
    ValuationAssumptions,
    classify_valuation,
)

FOUR = Decimal("0.0001")
TWO = Decimal("0.01")
ZERO = Decimal("0")
ONE = Decimal("1")


def _complete_positive(result: ModelValuation) -> bool:
    """Only a full low/base/high result can contribute to a composite."""

    if not result.available or result.low is None or result.base is None or result.high is None:
        return False
    values = (result.low.price_per_share, result.base.price_per_share, result.high.price_per_share)
    if any(not value.is_finite() or value <= ZERO for value in values):
        return False
    # DCF partial paths are never silently treated as zero or as base-only.
    if result.dcf_scenarios is not None and len(result.dcf_scenarios) != 3:
        return False
    return values[0] <= values[1] <= values[2]


def run_composite(
    current_price: Decimal,
    pe_result: ModelValuation,
    ev_result: ModelValuation,
    fcf_result: ModelValuation,
    dcf_result: ModelValuation,
    assumptions: ValuationAssumptions,
) -> CompositeValuation:
    model_configs = [
        ("forward_pe", pe_result, assumptions.weight_pe),
        ("ev_ebitda", ev_result, assumptions.weight_ev_ebitda),
        ("fcf_yield", fcf_result, assumptions.weight_fcf_yield),
        ("dcf", dcf_result, assumptions.weight_dcf),
    ]
    valid = [
        (name, result, weight)
        for name, result, weight in model_configs
        if weight > ZERO and _complete_positive(result)
    ]
    if current_price <= ZERO or not current_price.is_finite():
        return CompositeValuation(
            current_price=current_price,
            available=False,
            unavailable_reason="Current quote must be positive",
            data_quality=DataQuality.LOW,
        )
    if not valid:
        return CompositeValuation(
            current_price=current_price,
            available=False,
            unavailable_reason="No complete positive three-scenario valuation models available",
            data_quality=DataQuality.LOW,
        )

    total_weight = sum(weight for _, _, weight in valid)
    if total_weight <= ZERO:
        return CompositeValuation(
            current_price=current_price,
            available=False,
            unavailable_reason="Available model weights sum to zero",
            data_quality=DataQuality.LOW,
        )
    # Expose the same normalized weights used by the arithmetic, while
    # reconciling display rounding so consumers can safely sum them to 1.0000.
    normalized: dict[str, Decimal] = {}
    for index, (name, _, weight) in enumerate(valid):
        raw = weight / total_weight
        if index == len(valid) - 1:
            rounded = (ONE - sum(normalized.values())).quantize(FOUR, ROUND_HALF_UP)
        else:
            rounded = raw.quantize(FOUR, ROUND_HALF_UP)
        normalized[name] = rounded
    low = (sum(result.low.price_per_share * weight for _, result, weight in valid) / total_weight).quantize(TWO, ROUND_HALF_UP)
    base = (sum(result.base.price_per_share * weight for _, result, weight in valid) / total_weight).quantize(TWO, ROUND_HALF_UP)
    high = (sum(result.high.price_per_share * weight for _, result, weight in valid) / total_weight).quantize(TWO, ROUND_HALF_UP)
    mos = ((base - current_price) / base).quantize(FOUR, ROUND_HALF_UP)
    upside = ((base - current_price) / current_price).quantize(FOUR, ROUND_HALF_UP)
    premium_discount = ((current_price - base) / base).quantize(FOUR, ROUND_HALF_UP)
    classification = classify_valuation(current_price, base)

    qualities = [result.data_quality for _, result, _ in valid]
    quality = DataQuality.LOW if DataQuality.LOW in qualities else (
        DataQuality.MEDIUM if DataQuality.MEDIUM in qualities else DataQuality.HIGH
    )
    steps = [
        f"Complete models used: {', '.join(name for name, _, _ in valid)}",
        f"Raw weights = {', '.join(f'{name}:{weight}' for name, _, weight in valid)}; total = {total_weight}",
        f"Normalized weights = {normalized}",
        f"Composite low = weighted low values / {total_weight} = {low}",
        f"Composite base = weighted base values / {total_weight} = {base}",
        f"Composite high = weighted high values / {total_weight} = {high}",
        f"MOS = (fair value base - current price) / fair value base = {mos}",
        f"Upside = (fair value base - current price) / current price = {upside}",
    ]
    return CompositeValuation(
        current_price=current_price,
        low=low,
        base=base,
        high=high,
        fair_value_low=low,
        fair_value_base=base,
        fair_value_high=high,
        weights_used=normalized,
        available_models=[name for name, _, _ in valid],
        classification=classification,
        margin_of_safety=mos,
        upside_downside=upside,
        premium_discount_pct=premium_discount,
        calculation_steps=steps,
        data_quality=quality,
        available=True,
    )
