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
    selected_weights = {
        "forward_pe": assumptions.weight_pe,
        "ev_ebitda": assumptions.weight_ev_ebitda,
        "fcf_yield": assumptions.weight_fcf_yield,
        "dcf": assumptions.weight_dcf,
    }
    model_configs = [
        ("forward_pe", pe_result, selected_weights["forward_pe"]),
        ("ev_ebitda", ev_result, selected_weights["ev_ebitda"]),
        ("fcf_yield", fcf_result, selected_weights["fcf_yield"]),
        ("dcf", dcf_result, selected_weights["dcf"]),
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
            selected_weights=selected_weights,
            cashflow_group_max_weight=assumptions.cashflow_group_max_weight,
        )
    if not valid:
        return CompositeValuation(
            current_price=current_price,
            available=False,
            unavailable_reason="No complete positive three-scenario valuation models available",
            data_quality=DataQuality.LOW,
            selected_weights=selected_weights,
            cashflow_group_max_weight=assumptions.cashflow_group_max_weight,
        )

    cf_models = [m for m in valid if m[0] in {"fcf_yield", "dcf"}]
    non_cf_models = [m for m in valid if m[0] not in {"fcf_yield", "dcf"}]
    cf_max = getattr(assumptions, "cashflow_group_max_weight", Decimal("0.40"))

    # If only cash flow models are available:
    if not non_cf_models:
        cf_raw_total = sum(w for _, _, w in cf_models)
        cf_effective = {}
        for idx, (name, _, w) in enumerate(cf_models):
            if idx == len(cf_models) - 1:
                cf_effective[name] = (ONE - sum(cf_effective.values())).quantize(FOUR, ROUND_HALF_UP)
            else:
                cf_effective[name] = (w / cf_raw_total).quantize(FOUR, ROUND_HALF_UP)
        sensitivity = {name: res.base.price_per_share for name, res, _ in cf_models if res.base}
        cf_policy_msg = (
            f"仅现金流模型可用策略：根据估值保真约束，在仅现金流模型（FCF Yield / DCF）有效而倍数模型缺失时，"
            f"系统遵守 {cf_max:.0%} 现金流组权重上限，不合成伪综合公允价值，"
            "直接提供纯现金流敏感性结果供决策参考。"
        )
        if cf_max < ONE:
            return CompositeValuation(
                current_price=current_price,
                available=False,
                unavailable_reason=f"Only cashflow models available under cashflow group weight cap ({cf_max:.0%}); non-cashflow models are missing",
                data_quality=DataQuality.LOW,
                selected_weights=selected_weights,
                effective_weights=cf_effective,
                weights_used=cf_effective,
                cashflow_group_weight=ONE,
                cashflow_group_max_weight=cf_max,
                cashflow_sensitivity=sensitivity,
                cashflow_group_policy_message=cf_policy_msg,
                available_models=[m[0] for m in cf_models],
            )

    # Both non-CF and CF models or only non-CF models:
    raw_total = sum(weight for _, _, weight in valid)
    if raw_total <= ZERO:
        return CompositeValuation(
            current_price=current_price,
            available=False,
            unavailable_reason="Available model weights sum to zero",
            data_quality=DataQuality.LOW,
            selected_weights=selected_weights,
            cashflow_group_max_weight=cf_max,
        )

    cf_raw_sum = sum(w for name, _, w in cf_models)
    non_cf_raw_sum = sum(w for name, _, w in non_cf_models)
    cf_share = (cf_raw_sum / raw_total) if raw_total > ZERO else ZERO

    effective_unrounded: dict[str, Decimal] = {}
    if cf_models and non_cf_models and cf_share > cf_max:
        # Cap cashflow group total weight to cf_max
        for name, _, w in cf_models:
            effective_unrounded[name] = (w / cf_raw_sum) * cf_max
        rem = ONE - cf_max
        for name, _, w in non_cf_models:
            effective_unrounded[name] = (w / non_cf_raw_sum) * rem
    else:
        for name, _, w in valid:
            effective_unrounded[name] = w / raw_total

    # Reconcile display rounding so consumers can safely sum them to 1.0000
    normalized: dict[str, Decimal] = {}
    valid_names = [name for name, _, _ in valid]
    for index, name in enumerate(valid_names):
        if index == len(valid_names) - 1:
            rounded = (ONE - sum(normalized.values())).quantize(FOUR, ROUND_HALF_UP)
        else:
            rounded = effective_unrounded[name].quantize(FOUR, ROUND_HALF_UP)
        normalized[name] = rounded

    low = sum(result.low.price_per_share * normalized[name] for name, result, _ in valid).quantize(TWO, ROUND_HALF_UP)
    base = sum(result.base.price_per_share * normalized[name] for name, result, _ in valid).quantize(TWO, ROUND_HALF_UP)
    high = sum(result.high.price_per_share * normalized[name] for name, result, _ in valid).quantize(TWO, ROUND_HALF_UP)
    mos = ((base - current_price) / base).quantize(FOUR, ROUND_HALF_UP)
    upside = ((base - current_price) / current_price).quantize(FOUR, ROUND_HALF_UP)
    premium_discount = ((current_price - base) / base).quantize(FOUR, ROUND_HALF_UP)
    classification = classify_valuation(current_price, base)

    cf_effective_weight = sum(normalized.get(k, ZERO) for k in ("fcf_yield", "dcf"))

    qualities = [result.data_quality for _, result, _ in valid]
    quality = DataQuality.LOW if DataQuality.LOW in qualities else (
        DataQuality.MEDIUM if DataQuality.MEDIUM in qualities else DataQuality.HIGH
    )
    steps = [
        f"Complete models used: {', '.join(name for name, _, _ in valid)}",
        f"Selected weights = {selected_weights}",
        f"Effective weights = {normalized}",
        f"Cash flow group weight = {cf_effective_weight} (cap = {cf_max})",
        f"Composite low = weighted low values = {low}",
        f"Composite base = weighted base values = {base}",
        f"Composite high = weighted high values = {high}",
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
        selected_weights=selected_weights,
        effective_weights=normalized,
        cashflow_group_weight=cf_effective_weight,
        cashflow_group_max_weight=cf_max,
        available_models=[name for name, _, _ in valid],
        classification=classification,
        margin_of_safety=mos,
        upside_downside=upside,
        premium_discount_pct=premium_discount,
        calculation_steps=steps,
        data_quality=quality,
        available=True,
    )
