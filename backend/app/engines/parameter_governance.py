"""Shared governance for valuation parameters.

Configured values in :mod:`app.config` are useful defaults for request
construction, but they are not company evidence.  The model seam must reject
those values instead of allowing a warning to accompany a normal-looking
price target.  This module deliberately has no imports from any valuation
engine so the policy remains a small, reusable post-selection boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models.domain import SourceType


@dataclass(frozen=True)
class ParameterGovernance:
    """Decision and normalized provenance for one model parameter family."""

    available: bool
    source_type: SourceType | str
    source_label: str
    selection_layer: str
    multiple_source: str
    reason: str | None = None
    warning: str | None = None


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
        # Keep the same explicitly recognized aliases as terminal governance
        # for direct callers that carry an effective source token instead of
        # a domain enum.  Arbitrary tokens remain unknown and fail closed.
        "calculated",
        "company_specific",
        "peer",
        "historical",
    }
)


def _source_type_text(value: Any) -> str | None:
    raw = getattr(value, "value", value)
    if raw is None:
        return None
    text = str(raw).strip().lower()
    return text or None


def govern_parameter(
    assumptions: Any,
    *,
    model_label: str,
    value_field: str,
    source_field: str,
    label_field: str,
    layer_field: str,
    source_type: SourceType,
    source_label: str,
    selection_layer: str,
    multiple_source: str,
    snapshot_is_demo: bool = False,
) -> ParameterGovernance:
    """Fail closed for unsupported parameter provenance.

    The effective source type and source label are evaluated together.  A
    fallback label cannot be rescued by a derived/industry selection layer,
    fixture provenance is accepted only for an explicitly isolated demo
    snapshot, and unknown source tokens are unavailable.  Deliberate user
    overrides are the one source that may carry a human label containing
    ``fallback`` because the explicit source enum is the request's intent.
    """

    source_label = str(source_label or "").strip() or "Configured fallback"
    selection_layer = str(selection_layer or "system").strip() or "system"
    multiple_source = str(multiple_source or "fallback").strip() or "fallback"
    source_type_value = _source_type_text(source_type)

    if source_type_value == SourceType.USER_OVERRIDE.value:
        # A direct caller may set only the source enum and leave the model's
        # configured label in place.  Do not expose that contradictory label
        # as though the user override were system evidence.
        if source_label.lower().startswith("configured fallback"):
            source_label = "Explicit user scenario"
        return ParameterGovernance(
            available=True,
            source_type=SourceType.USER_OVERRIDE,
            source_label=source_label,
            selection_layer="user_override",
            multiple_source="user_override",
        )

    # Check source-label conflicts before source-type support, matching the
    # terminal governance helper.  This catches derived/fixture/analyst
    # metadata that still points at an application fallback.
    if "fallback" in source_label.lower() or source_type_value in _FALLBACK_SOURCE_TYPES:
        source_type_for_output: SourceType | str = (
            source_type if isinstance(source_type, SourceType) else str(source_type)
        )
        reason = (
            f"{model_label} parameter is unavailable: configured fallback parameters "
            "are not company- or industry-specific evidence; provide a validated "
            "source-backed parameter or an explicit user override."
        )
        warning = (
            f"{model_label} valuation rejected configured fallback parameters "
            "because no compatible company/industry-specific benchmark was available "
            "(FCFE-yield benchmark where applicable; parameter specificity insufficient; "
            f"source_type={source_type_value or source_type}, source={source_label}, "
            f"selection_layer={selection_layer}); no normal target price was produced."
        )
        return ParameterGovernance(
            available=False,
            source_type=source_type_for_output,
            source_label=source_label,
            selection_layer=selection_layer,
            multiple_source=multiple_source,
            reason=reason,
            warning=warning,
        )

    if source_type_value == SourceType.FIXTURE.value and not snapshot_is_demo:
        source_type_for_output = (
            source_type if isinstance(source_type, SourceType) else str(source_type)
        )
        reason = (
            f"{model_label} parameter is unavailable: fixture provenance is valid "
            "only for an explicitly isolated demo snapshot; provide a validated "
            "source-backed parameter or an explicit user override."
        )
        warning = (
            f"{model_label} valuation rejected fixture parameter provenance outside "
            "an explicitly isolated demo snapshot "
            f"(source_type={source_type_value}, source={source_label}, "
            f"selection_layer={selection_layer}); no normal target price was produced."
        )
        return ParameterGovernance(
            available=False,
            source_type=source_type_for_output,
            source_label=source_label,
            selection_layer=selection_layer,
            multiple_source=multiple_source,
            reason=reason,
            warning=warning,
        )

    if source_type_value not in _SUPPORTED_SOURCE_TYPES:
        source_type_for_output = (
            source_type if isinstance(source_type, SourceType) else str(source_type)
        )
        reason = (
            f"{model_label} parameter is unavailable: source provenance is unknown "
            "or unsupported; provide a validated source-backed parameter or an "
            "explicit user override."
        )
        warning = (
            f"{model_label} valuation rejected unknown parameter provenance "
            f"(source_type={source_type_value or source_type}, source={source_label}, "
            f"selection_layer={selection_layer}); no normal target price was produced."
        )
        return ParameterGovernance(
            available=False,
            source_type=source_type_for_output,
            source_label=source_label,
            selection_layer=selection_layer,
            multiple_source=multiple_source,
            reason=reason,
            warning=warning,
        )

    # For supported non-fallback sources, retain the declared provenance and
    # avoid calling an explicitly supplied value a system fallback.
    normalized_source = multiple_source
    if normalized_source == "fallback":
        normalized_source = "provided"
    return ParameterGovernance(
        available=True,
        source_type=(
            SourceType(source_type_value)
            if source_type_value in {item.value for item in SourceType}
            else source_type_value
        ),
        source_label=source_label,
        selection_layer=selection_layer,
        multiple_source=normalized_source,
    )
