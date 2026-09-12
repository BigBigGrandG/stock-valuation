"""Post-calculation governance for DCF terminal-value dependence.

The DCF engine owns the cash-flow and discounting mathematics.  This module
is deliberately independent of that engine: it consumes a completed
``ModelValuation`` and decides whether the resulting terminal-value exposure
is fit to publish.  In particular, a configured WACC or terminal-growth
fallback may be useful for a deterministic scenario, but it is not company
evidence and must not produce a normal target price.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping, Optional

from app.models.domain import (
    CompanyFinancialSnapshot,
    DataQuality,
    ModelValuation,
    SourceType,
    ValuationAssumptions,
)


# This is an explicit conservative policy-attention threshold.  It is not an
# empirical universal law about DCFs.  The inclusive comparison is intentional
# so that the boundary is deterministic and testable.
TERMINAL_VALUE_CONCENTRATION_THRESHOLD = Decimal("0.75")
TV_RATIO_POLICY_THRESHOLD = TERMINAL_VALUE_CONCENTRATION_THRESHOLD
POLICY_VERSION = "s6-terminal-governance-v1"

_ZERO = Decimal("0")
_FALLBACK_SOURCE_TYPES = frozenset(
    {
        SourceType.CONFIGURED_FALLBACK.value,
        "fallback",
        "system_default",
        "system_fallback",
        "default",
    }
)
_SUPPORTED_SOURCE_TYPES = frozenset(
    {
        SourceType.ACTUAL.value,
        SourceType.ANALYST_ESTIMATE.value,
        SourceType.DERIVED.value,
        SourceType.USER_OVERRIDE.value,
        SourceType.FIXTURE.value,
        # Some direct callers use the human-readable effective source rather
        # than the domain enum.  These aliases retain compatibility without
        # weakening the explicit fallback guard above.
        "calculated",
        "company_specific",
        "peer",
        "historical",
    }
)


def _as_decimal(value: Any) -> Optional[Decimal]:
    """Convert a value to a finite Decimal, returning None when invalid."""

    if value is None or isinstance(value, bool):
        return None
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def _text(value: Any) -> Optional[str]:
    """Return a stable string for enum/string provenance values."""

    if value is None:
        return None
    raw = getattr(value, "value", value)
    if raw is None:
        return None
    return str(raw)


def _normalise_source_type(value: Any) -> Optional[str]:
    raw = _text(value)
    return raw.strip().lower() if raw and raw.strip() else None


def _provenance_descriptor(
    *,
    source_type: Any,
    source: Any,
    origin: str,
    is_estimated: Any = None,
    confidence: Any = None,
    allow_fixture: bool = False,
) -> dict[str, Any]:
    """Classify one effective assumption's provenance.

    A source label containing ``fallback`` is rejected before considering the
    declared source type, except for an explicit user override.  This catches
    inconsistent metadata such as ``source_type=derived`` paired with a
    configured-fallback label.  Fixture lineage is supported only for an
    explicitly isolated demo snapshot; a fixture cannot justify a live
    valuation.
    """

    source_type_value = _normalise_source_type(source_type)
    source_value = _text(source)
    source_label = (source_value or "").strip().lower()

    if source_type_value == SourceType.USER_OVERRIDE.value:
        status = "supported"
    elif "fallback" in source_label:
        status = "fallback"
    elif source_type_value in _FALLBACK_SOURCE_TYPES:
        status = "fallback"
    elif source_type_value == SourceType.FIXTURE.value and not allow_fixture:
        status = "unknown"
    elif source_type_value in _SUPPORTED_SOURCE_TYPES:
        status = "supported"
    else:
        status = "unknown"

    descriptor: dict[str, Any] = {
        "status": status,
        "source_type": source_type_value,
        "source": source_value,
        "origin": origin,
    }
    if source_type_value == SourceType.FIXTURE.value and not allow_fixture:
        descriptor["validation_error"] = (
            "fixture provenance is valid only for an explicitly isolated demo snapshot"
        )
    if is_estimated is not None:
        descriptor["is_estimated"] = bool(is_estimated)
    if confidence is not None:
        confidence_value = _as_decimal(confidence)
        descriptor["confidence"] = str(confidence_value) if confidence_value is not None else _text(confidence)
    return descriptor


def _mapping_value(mapping: Any, key: str) -> Any:
    if isinstance(mapping, Mapping):
        return mapping.get(key)
    return None


def _scenario_assumption_value(
    assumptions: ValuationAssumptions,
    kind: str,
    scenario_name: str,
) -> Any:
    """Read the low/base/high value corresponding to bear/base/bull."""

    field = "dcf_wacc" if kind == "wacc" else "dcf_terminal_growth"
    scenario_field = {"bear": "low", "base": "base", "bull": "high"}.get(scenario_name)
    values = getattr(assumptions, field, None)
    return getattr(values, scenario_field, None) if values is not None and scenario_field else None


def _validate_claimed_value(
    descriptor: dict[str, Any],
    *,
    claimed_value: Any,
    effective_value: Any,
    label: str,
) -> dict[str, Any]:
    """Require a provenance metric value to equal the effective scenario value."""

    effective = _as_decimal(effective_value)
    claimed = _as_decimal(claimed_value)
    descriptor["claimed_value"] = _text(claimed_value)
    descriptor["effective_value"] = _text(effective)
    if claimed is None:
        descriptor["validation_error"] = f"{label} effective metric value is missing or non-finite"
        if descriptor["status"] == "supported":
            descriptor["status"] = "invalid"
    elif effective is None:
        descriptor["validation_error"] = f"{label} scenario value is missing or non-finite"
        if descriptor["status"] == "supported":
            descriptor["status"] = "invalid"
    elif claimed != effective:
        descriptor["validation_error"] = (
            f"{label} effective metric value {claimed} does not match scenario value {effective}"
        )
        if descriptor["status"] == "supported":
            descriptor["status"] = "invalid"
    else:
        descriptor["value"] = str(claimed)
    return descriptor


def _resolve_provenance(
    model: ModelValuation,
    assumptions: ValuationAssumptions,
    kind: str,
    scenario_name: str,
    effective_value: Any = None,
    snapshot_is_demo: bool = False,
) -> dict[str, Any]:
    """Resolve effective WACC/g lineage for a scenario.

    Final ``assumption_metrics`` are preferred because they describe what the
    DCF actually used.  The flat assumptions dictionaries and the assumptions
    object are compatibility fallbacks for direct engine callers and focused
    tests.  Missing lineage remains ``unknown`` and is never inferred as
    company evidence.
    """

    metric_key = f"{kind}_{scenario_name}"
    metric = _mapping_value(model.assumption_metrics, metric_key)
    if isinstance(metric, Mapping):
        # An explicitly empty metric is evidence of missing provenance, even
        # if the caller also supplied a generic assumptions object.
        metric_source_type = metric.get("source_type")
        metric_source = metric.get("source")
        descriptor = _provenance_descriptor(
            source_type=metric_source_type,
            source=metric_source,
            origin=f"assumption_metrics.{metric_key}",
            is_estimated=metric.get("is_estimated"),
            confidence=metric.get("confidence"),
            allow_fixture=snapshot_is_demo,
        )
        return _validate_claimed_value(
            descriptor,
            claimed_value=metric.get("value"),
            effective_value=effective_value,
            label=f"{scenario_name} {kind}",
        )

    # DCF's flat public assumptions use ``wacc_source_type`` and
    # ``terminal_growth_source``.  Accept a source token as a type when direct
    # callers only provide ``wacc_source``/``terminal_growth_source``.
    flat = model.assumptions if isinstance(model.assumptions, Mapping) else {}
    if kind == "wacc":
        type_key = "wacc_source_type"
        source_key = "wacc_source_label"
        token_key = "wacc_source"
        value_key = f"wacc_{scenario_name}"
        assumption_attr = "dcf_wacc_source"
        label_attr = "dcf_wacc_source_label"
    else:
        type_key = "terminal_growth_source_type"
        source_key = "terminal_growth_source_label"
        token_key = "terminal_growth_source"
        value_key = f"terminal_growth_{scenario_name}"
        assumption_attr = "dcf_terminal_growth_source"
        label_attr = "dcf_terminal_growth_source_label"

    source_type = _mapping_value(flat, type_key)
    source_token = _mapping_value(flat, token_key)
    source = _mapping_value(flat, source_key)
    if source_type is None:
        # For terminal growth, the current DCF flat field is itself a
        # SourceType.  For direct callers, a known source token is likewise a
        # usable type; arbitrary labels still resolve to unknown below.
        token_type = _normalise_source_type(source_token)
        if token_type in _FALLBACK_SOURCE_TYPES or token_type in _SUPPORTED_SOURCE_TYPES:
            source_type = source_token
        elif source_token is not None and source is None:
            source = source_token

    if source is None:
        source = source_token
    if source_type is not None or source is not None:
        descriptor = _provenance_descriptor(
            source_type=source_type,
            source=source,
            origin=f"assumptions.{type_key if source_type is not None else token_key}",
            allow_fixture=snapshot_is_demo,
        )
        claimed_value = _mapping_value(flat, value_key)
        if claimed_value is None:
            claimed_value = _scenario_assumption_value(assumptions, kind, scenario_name)
        return _validate_claimed_value(
            descriptor,
            claimed_value=claimed_value,
            effective_value=effective_value,
            label=f"{scenario_name} {kind}",
        )

    assumption_source_type = getattr(assumptions, assumption_attr, None)
    assumption_source = getattr(assumptions, label_attr, None)
    if assumption_source_type is not None or assumption_source is not None:
        descriptor = _provenance_descriptor(
            source_type=assumption_source_type,
            source=assumption_source,
            origin=f"ValuationAssumptions.{assumption_attr}",
            allow_fixture=snapshot_is_demo,
        )
        return _validate_claimed_value(
            descriptor,
            claimed_value=_scenario_assumption_value(assumptions, kind, scenario_name),
            effective_value=effective_value,
            label=f"{scenario_name} {kind}",
        )

    descriptor = _provenance_descriptor(
        source_type=None,
        source=None,
        origin="missing provenance",
        allow_fixture=snapshot_is_demo,
    )
    return _validate_claimed_value(
        descriptor,
        claimed_value=None,
        effective_value=effective_value,
        label=f"{scenario_name} {kind}",
    )


def _downgrade_quality(quality: DataQuality) -> DataQuality:
    """Apply one explicit quality downgrade for policy-limited concentration."""

    if quality == DataQuality.HIGH:
        return DataQuality.MEDIUM
    return DataQuality.LOW


def _unique_warnings(existing: list[str], *new_items: str) -> list[str]:
    return list(dict.fromkeys([*existing, *new_items]))


def _base_governance(
    *,
    model: ModelValuation,
    snapshot: CompanyFinancialSnapshot,
    scenario_diagnostics: list[dict[str, Any]],
    status: str,
    reason_code: str,
    reason: str,
    concentration_scenarios: list[str],
    fallback_parameters: list[str],
    unknown_parameters: list[str],
    invalid_parameters: list[str],
    invalid_scenarios: list[str],
) -> dict[str, Any]:
    as_of = getattr(getattr(snapshot, "current_price", None), "as_of", None)
    as_of_text = as_of.isoformat() if hasattr(as_of, "isoformat") else _text(as_of)
    quality_before = model.data_quality.value if isinstance(model.data_quality, DataQuality) else _text(model.data_quality)
    quality_after = quality_before
    return {
        "policy_version": POLICY_VERSION,
        "status": status,
        "available": status in {"approved", "limited"},
        "reason_code": reason_code,
        "reason": reason,
        "ticker": getattr(snapshot, "ticker", None),
        "valuation_as_of": as_of_text,
        "concentration_threshold": str(TERMINAL_VALUE_CONCENTRATION_THRESHOLD),
        "tv_ratio_policy_threshold": str(TERMINAL_VALUE_CONCENTRATION_THRESHOLD),
        "threshold_operator": ">=",
        "threshold_policy": "Conservative policy-attention threshold; not empirically universal.",
        "evaluated_scenarios": len(scenario_diagnostics),
        "evaluation_complete": bool(scenario_diagnostics)
        and not invalid_scenarios
        and not invalid_parameters,
        "concentration_scenarios": concentration_scenarios,
        "fallback_parameters": fallback_parameters,
        "unknown_parameters": unknown_parameters,
        "invalid_parameters": invalid_parameters,
        "invalid_scenarios": invalid_scenarios,
        "quality_before": quality_before,
        "quality_after": quality_after,
        "scenarios": scenario_diagnostics,
        # A named alias makes the structured record easy for API consumers to
        # discover without changing the stable ModelValuation schema.
        "scenario_diagnostics": scenario_diagnostics,
    }


def _with_governance_metadata(
    model: ModelValuation,
    governance: dict[str, Any],
    *,
    warnings: list[str],
    calculation_step: str,
    data_quality: Optional[DataQuality] = None,
) -> ModelValuation:
    assumptions = dict(model.assumptions or {})
    assumptions["terminal_governance"] = governance
    assumptions["terminal_governance_status"] = governance["status"]
    assumptions["terminal_value_concentration_threshold"] = str(
        TERMINAL_VALUE_CONCENTRATION_THRESHOLD
    )
    if data_quality is not None:
        governance["quality_after"] = data_quality.value
    steps = list(model.calculation_steps or [])
    steps.append(calculation_step)
    return model.model_copy(
        update={
            "assumptions": assumptions,
            "warnings": _unique_warnings(list(model.warnings or []), *warnings),
            "calculation_steps": steps,
            **({"data_quality": data_quality} if data_quality is not None else {}),
        }
    )


def _blocked_model(
    model: ModelValuation,
    governance: dict[str, Any],
    *,
    reason: str,
    warning: str,
) -> ModelValuation:
    updated = _with_governance_metadata(
        model,
        governance,
        warnings=[warning],
        calculation_step=(
            "Terminal governance: DCF target/scenario/sensitivity prices withheld; "
            f"{reason}"
        ),
        data_quality=DataQuality.LOW,
    )
    return updated.model_copy(
        update={
            "low": None,
            "base": None,
            "high": None,
            "dcf_scenarios": None,
            "sensitivity_matrix": None,
            "available": False,
            "unavailable_reason": (
                "Terminal governance blocked DCF publication: "
                f"{reason} Public target, scenario, and sensitivity prices are withheld."
            ),
        }
    )


def apply_terminal_governance(
    model: ModelValuation,
    snapshot: CompanyFinancialSnapshot,
    assumptions: ValuationAssumptions,
) -> ModelValuation:
    """Apply terminal-value governance to a completed DCF result.

    The function is pure: it never mutates ``model`` and returns a copied
    result.  A DCF already unavailable for an upstream reason is returned
    unchanged because there is no successful calculation to govern; S5 calls
    this helper only after a successful ``run_dcf`` result.
    """

    if not model.available:
        return model

    scenarios = list(model.dcf_scenarios or [])
    if not scenarios:
        diagnostics: list[dict[str, Any]] = []
        reason = "no completed DCF scenarios were available for PVTV/EV evaluation"
        governance = _base_governance(
            model=model,
            snapshot=snapshot,
            scenario_diagnostics=diagnostics,
            status="blocked",
            reason_code="missing_scenarios",
            reason=reason,
            concentration_scenarios=[],
            fallback_parameters=[],
            unknown_parameters=["wacc", "terminal_growth"],
            invalid_parameters=[],
            invalid_scenarios=[],
        )
        return _blocked_model(
            model,
            governance,
            reason=reason,
            warning=(
                "Terminal governance blocked DCF target prices because no completed "
                "scenario values were available for audit."
            ),
        )

    diagnostics = []
    concentration_scenarios: list[str] = []
    fallback_parameters: list[str] = []
    unknown_parameters: list[str] = []
    invalid_parameters: list[str] = []
    invalid_scenarios: list[str] = []

    for index, scenario in enumerate(scenarios):
        scenario_name = _text(getattr(scenario, "scenario", None)) or f"scenario_{index + 1}"
        wacc_provenance = _resolve_provenance(
            model,
            assumptions,
            "wacc",
            scenario_name,
            effective_value=getattr(scenario, "wacc", None),
            snapshot_is_demo=bool(getattr(snapshot, "is_demo", False)),
        )
        growth_provenance = _resolve_provenance(
            model,
            assumptions,
            "terminal_growth",
            scenario_name,
            effective_value=getattr(scenario, "terminal_growth", None),
            snapshot_is_demo=bool(getattr(snapshot, "is_demo", False)),
        )
        pv_terminal_value = _as_decimal(getattr(scenario, "pv_terminal_value", None))
        enterprise_value = _as_decimal(getattr(scenario, "enterprise_value", None))
        wacc = _as_decimal(getattr(scenario, "wacc", None))
        terminal_growth = _as_decimal(getattr(scenario, "terminal_growth", None))

        invalid_reasons: list[str] = []
        ratio: Optional[Decimal] = None
        if wacc is None:
            invalid_reasons.append("WACC is missing or non-finite")
        elif wacc <= _ZERO:
            invalid_reasons.append("WACC must be positive")
        if terminal_growth is None:
            invalid_reasons.append("terminal growth is missing or non-finite")
        if wacc is not None and terminal_growth is not None and wacc <= terminal_growth:
            invalid_reasons.append("WACC must be greater than terminal growth")
        if pv_terminal_value is None:
            invalid_reasons.append("PVTV is missing or non-finite")
        elif pv_terminal_value <= _ZERO:
            invalid_reasons.append("PVTV must be positive")
        if enterprise_value is None:
            invalid_reasons.append("enterprise value is missing or non-finite")
        elif enterprise_value <= _ZERO:
            # Never divide by zero or allow a negative denominator to bypass
            # the concentration policy.
            invalid_reasons.append("enterprise value must be positive for PVTV/EV")
        if pv_terminal_value is not None and enterprise_value is not None and enterprise_value > _ZERO:
            ratio = pv_terminal_value / enterprise_value
            if not ratio.is_finite():
                invalid_reasons.append("PVTV/EV ratio is non-finite")
            elif ratio < _ZERO:
                invalid_reasons.append("PVTV/EV ratio must not be negative")

        if ratio is not None and ratio.is_finite() and ratio >= TERMINAL_VALUE_CONCENTRATION_THRESHOLD:
            concentration_scenarios.append(scenario_name)

        if wacc_provenance["status"] == "fallback":
            fallback_parameters.append(f"{scenario_name}.wacc")
        elif wacc_provenance["status"] == "unknown":
            unknown_parameters.append(f"{scenario_name}.wacc")
        if growth_provenance["status"] == "fallback":
            fallback_parameters.append(f"{scenario_name}.terminal_growth")
        elif growth_provenance["status"] == "unknown":
            unknown_parameters.append(f"{scenario_name}.terminal_growth")
        if wacc_provenance["status"] == "invalid":
            invalid_parameters.append(
                f"{scenario_name}.wacc: {wacc_provenance.get('validation_error', 'invalid effective metric')}"
            )
        if growth_provenance["status"] == "invalid":
            invalid_parameters.append(
                f"{scenario_name}.terminal_growth: {growth_provenance.get('validation_error', 'invalid effective metric')}"
            )
        if invalid_reasons:
            invalid_scenarios.append(scenario_name)

        diagnostics.append(
            {
                "scenario": scenario_name,
                "wacc": _text(wacc),
                "terminal_growth": _text(terminal_growth),
                "pv_terminal_value": _text(pv_terminal_value),
                "enterprise_value": _text(enterprise_value),
                "tv_ratio": _text(ratio),
                "pv_terminal_value_to_enterprise_value": _text(ratio),
                "concentration_attention": bool(
                    ratio is not None
                    and ratio.is_finite()
                    and ratio >= TERMINAL_VALUE_CONCENTRATION_THRESHOLD
                ),
                "wacc_provenance": wacc_provenance,
                "terminal_growth_provenance": growth_provenance,
                # Flat aliases are useful to clients and make each scenario's
                # lineage readable without traversing nested objects.
                "wacc_source_type": wacc_provenance.get("source_type"),
                "wacc_source": wacc_provenance.get("source"),
                "terminal_growth_source_type": growth_provenance.get("source_type"),
                "terminal_growth_source": growth_provenance.get("source"),
                "invalid_reasons": invalid_reasons,
            }
        )

    fallback_parameters = list(dict.fromkeys(fallback_parameters))
    unknown_parameters = list(dict.fromkeys(unknown_parameters))
    invalid_parameters = list(dict.fromkeys(invalid_parameters))
    invalid_scenarios = list(dict.fromkeys(invalid_scenarios))

    if invalid_scenarios:
        reason = (
            "invalid terminal-value inputs in scenario(s) "
            + ", ".join(invalid_scenarios)
            + "; every scenario must have finite positive PVTV and enterprise value "
            "with WACC greater than terminal growth"
        )
        if invalid_parameters:
            reason += "; effective metric validation: " + "; ".join(invalid_parameters)
        governance = _base_governance(
            model=model,
            snapshot=snapshot,
            scenario_diagnostics=diagnostics,
            status="blocked",
            reason_code="invalid_terminal_value_inputs",
            reason=reason,
            concentration_scenarios=concentration_scenarios,
            fallback_parameters=fallback_parameters,
            unknown_parameters=unknown_parameters,
            invalid_parameters=invalid_parameters,
            invalid_scenarios=invalid_scenarios,
        )
        return _blocked_model(
            model,
            governance,
            reason=reason,
            warning=(
                "Terminal governance blocked DCF target prices because PVTV/EV "
                "could not be safely evaluated for every scenario."
            ),
        )

    if invalid_parameters:
        reason = (
            "effective WACC/terminal-growth metric validation failed: "
            + "; ".join(invalid_parameters)
        )
        governance = _base_governance(
            model=model,
            snapshot=snapshot,
            scenario_diagnostics=diagnostics,
            status="blocked",
            reason_code="invalid_effective_parameter_metric",
            reason=reason,
            concentration_scenarios=concentration_scenarios,
            fallback_parameters=fallback_parameters,
            unknown_parameters=unknown_parameters,
            invalid_parameters=invalid_parameters,
            invalid_scenarios=invalid_scenarios,
        )
        return _blocked_model(
            model,
            governance,
            reason=reason,
            warning=(
                "Terminal governance blocked DCF target prices because an effective "
                "WACC or terminal-growth metric did not match the scenario value."
            ),
        )

    if fallback_parameters or unknown_parameters:
        lineage_parts: list[str] = []
        if fallback_parameters:
            lineage_parts.append(
                "configured fallback lineage: " + ", ".join(fallback_parameters)
            )
        if unknown_parameters:
            lineage_parts.append(
                "unknown WACC/terminal-growth provenance: " + ", ".join(unknown_parameters)
            )
            unknown_details = [
                f"{diagnostic['scenario']}.{parameter}: {provenance['validation_error']}"
                for diagnostic in diagnostics
                for parameter, provenance in (
                    ("wacc", diagnostic["wacc_provenance"]),
                    ("terminal_growth", diagnostic["terminal_growth_provenance"]),
                )
                if provenance.get("status") == "unknown" and provenance.get("validation_error")
            ]
            if unknown_details:
                lineage_parts.append("lineage details: " + "; ".join(dict.fromkeys(unknown_details)))
        reason = (
            "; ".join(lineage_parts)
            + "; terminal assumptions are not sufficiently company-specific for a normal DCF target price"
        )
        governance = _base_governance(
            model=model,
            snapshot=snapshot,
            scenario_diagnostics=diagnostics,
            status="blocked",
            reason_code="fallback_or_unknown_parameter",
            reason=reason,
            concentration_scenarios=concentration_scenarios,
            fallback_parameters=fallback_parameters,
            unknown_parameters=unknown_parameters,
            invalid_parameters=invalid_parameters,
            invalid_scenarios=[],
        )
        return _blocked_model(
            model,
            governance,
            reason=reason,
            warning=(
                "Terminal governance blocked DCF target prices: effective WACC and/or "
                "terminal growth uses configured fallback or unknown provenance."
            ),
        )

    if concentration_scenarios:
        quality_after = _downgrade_quality(model.data_quality)
        reason = (
            "PVTV/EV meets or exceeds the conservative 0.75 policy-attention threshold "
            "in scenario(s) "
            + ", ".join(concentration_scenarios)
            + "; explicit/company-supported WACC and terminal-growth parameters permit publication "
            "with a structured concentration limitation"
        )
        governance = _base_governance(
            model=model,
            snapshot=snapshot,
            scenario_diagnostics=diagnostics,
            status="limited",
            reason_code="high_terminal_value_concentration",
            reason=reason,
            concentration_scenarios=concentration_scenarios,
            fallback_parameters=[],
            unknown_parameters=[],
            invalid_parameters=[],
            invalid_scenarios=[],
        )
        return _with_governance_metadata(
            model,
            governance,
            warnings=[
                (
                    "Terminal-value concentration limitation: PVTV/EV is at or above "
                    "the 0.75 conservative policy threshold; DCF remains available only "
                    "with supported/user-explicit terminal parameters and data quality is downgraded."
                )
            ],
            calculation_step=(
                "Terminal governance: evaluated PVTV/EV for every scenario; "
                f"policy threshold >= {TERMINAL_VALUE_CONCENTRATION_THRESHOLD}; "
                "high concentration retained as a structured limitation with quality downgrade."
            ),
            data_quality=quality_after,
        )

    reason = (
        "all scenarios passed finite positive PVTV/EV checks and effective WACC/terminal-growth "
        "provenance is supported"
    )
    governance = _base_governance(
        model=model,
        snapshot=snapshot,
        scenario_diagnostics=diagnostics,
        status="approved",
        reason_code="supported_parameters",
        reason=reason,
        concentration_scenarios=[],
        fallback_parameters=[],
        unknown_parameters=[],
        invalid_parameters=[],
        invalid_scenarios=[],
    )
    return _with_governance_metadata(
        model,
        governance,
        warnings=[],
        calculation_step=(
            "Terminal governance: evaluated PVTV/EV for every scenario; "
            f"all ratios are below the >= {TERMINAL_VALUE_CONCENTRATION_THRESHOLD} "
            "conservative policy-attention threshold with supported parameter lineage."
        ),
    )


__all__ = [
    "POLICY_VERSION",
    "TERMINAL_VALUE_CONCENTRATION_THRESHOLD",
    "TV_RATIO_POLICY_THRESHOLD",
    "apply_terminal_governance",
]
