"""Request-scoped financial projection and consensus horizon interpolation module.

Decouples raw upstream provider data from request-scoped assumptions.
Calculates:
1. Exact bounded day-weighted NTM blends (w0, w1 in [0, 1]) for EPS and Revenue across fiscal years.
2. Request-scoped growth clamping with user-configured growth_floor and growth_cap.
3. Derived forward EBITDA, FCF, and FCFF without mutating global snapshot or provider cache.
"""
from __future__ import annotations

import calendar
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from app.models.domain import (
    CompanyFinancialSnapshot,
    FinancialMetric,
    SourceType,
    ValuationAssumptions,
)

ZERO = Decimal("0")


@dataclass(frozen=True)
class RequestProjections:
    effective_horizon: str
    horizon_weight_fy1: Decimal
    horizon_weight_fy2: Decimal
    forward_eps: Optional[FinancialMetric]
    forward_revenue: Optional[FinancialMetric]
    forward_ebitda: Optional[FinancialMetric]
    forward_fcfe_1y: Optional[FinancialMetric]
    forward_fcff_1y: Optional[FinancialMetric]
    forward_fcff_2y: Optional[FinancialMetric]
    effective_growth_floor: Decimal
    effective_growth_cap: Decimal
    fallback_warning: Optional[str]
    financial_bridge: Optional[dict[str, Any]] = None
    dcf_fcff_1y: Optional[FinancialMetric] = None
    dcf_fcff_2y: Optional[FinancialMetric] = None
    # Forward borrowing is intentionally separate from ``snapshot``'s
    # historical ``net_borrowing_ttm`` field.  A missing provider estimate is
    # represented by ``forward_net_borrowing_status`` and a normalized zero in
    # the bridge, never by borrowing the historical value.
    forward_net_borrowing: Optional[FinancialMetric] = None
    forward_net_borrowing_status: str = "missing_normalized_zero"
    warnings: tuple[str, ...] = ()


def _is_leap_year(y: int) -> bool:
    return calendar.isleap(y)


def _safe_add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return date(d.year + years, d.month, 28)


def _period_year(period: object) -> Optional[int]:
    """Return the explicit fiscal year embedded in a metric period, if any."""

    match = re.search(r"FY(20\d{2})", str(period or "").upper())
    return int(match.group(1)) if match else None


def _is_explicit_fy_metric(metric: Optional[FinancialMetric], slot: int, forecast_fy_end: Optional[date]) -> bool:
    """Require a verifiable annual period before using a metric in DCF Y1/Y2."""

    if metric is None:
        return False
    period = str(metric.period or "").upper().strip()
    if "NTM" in period or "TTM" in period:
        return False

    # Relative provider labels (0y/+1y, forward_1y/2y, FY1E/FY2E) carry no
    # calendar anchor by themselves.  They become verifiable only when the
    # provider also supplied the next fiscal-year end.  This branch must run
    # before the explicit ``FY`` prefix check because the live provider uses
    # 0y/+1y for annual consensus rows.
    relative_slot = {
        "0Y": 1,
        "FORWARD_1Y": 1,
        "FY1E": 1,
        "+1Y": 2,
        "1Y": 2,
        "FORWARD_2Y": 2,
        "FY2E": 2,
    }.get(period)
    if relative_slot is not None:
        if relative_slot != slot or forecast_fy_end is None:
            return False
        explicit_year = forecast_fy_end.year + slot - 1
    else:
        # Only full-fiscal-year labels with an embedded year are accepted as
        # self-anchored annual periods; do not broaden this to arbitrary text.
        if not period.startswith("FY"):
            return False
        explicit_year = _period_year(period)
        if explicit_year is None:
            return False
    if forecast_fy_end is not None:
        expected_year = forecast_fy_end.year + slot - 1
        if explicit_year != expected_year:
            return False
    return True


def _periods_compatible(left: Optional[FinancialMetric], right: Optional[FinancialMetric]) -> bool:
    """Only scale a historical driver when its reporting period matches revenue."""

    if left is None or right is None:
        return False
    left_period = str(left.period or "").upper().strip()
    right_period = str(right.period or "").upper().strip()
    if left_period == right_period:
        return True
    if left_period.startswith("TTM") and right_period.startswith("TTM"):
        return True
    left_year = _period_year(left_period)
    right_year = _period_year(right_period)
    return left_year is not None and left_year == right_year


def _forward_borrowing_period_is_historical(period: object) -> bool:
    text = str(period or "").upper().strip()
    return not text or any(token in text for token in ("TTM", "LTM", "HISTORICAL", "TRAILING"))


def _forward_borrowing_candidate(snapshot: CompanyFinancialSnapshot, slot: int) -> Any:
    """Read an explicitly transported forward borrowing candidate.

    ``CompanyFinancialSnapshot`` remains backward compatible while providers
    roll out this field, so this resolver accepts both the canonical name and
    the short compatibility alias.  A provider may transport a FinancialMetric
    directly, a metadata mapping, or a Decimal plus companion metadata; the
    latter two forms are normalized below without consulting TTM borrowing.
    """

    suffix = f"{slot}y"
    names = (
        f"forward_net_borrowing_{suffix}",
        f"forward_borrowing_{suffix}",
        f"net_borrowing_forward_{suffix}",
    )
    for name in names:
        candidate = getattr(snapshot, name, None)
        if candidate is not None:
            return candidate

    # Accommodate a provider adapter that transports both years in a mapping.
    for container_name in ("forward_net_borrowing", "forward_borrowing"):
        container = getattr(snapshot, container_name, None)
        if isinstance(container, dict):
            for key in (slot, str(slot), f"{slot}y", f"{slot}Y", f"forward_{slot}y"):
                if key in container and container[key] is not None:
                    return container[key]
    return None


def _normalize_forward_borrowing_metric(
    snapshot: CompanyFinancialSnapshot,
    slot: int,
    as_of: date,
) -> tuple[Optional[FinancialMetric], str, Optional[str]]:
    """Validate a provider forward borrowing metric without historical fallback."""

    candidate = _forward_borrowing_candidate(snapshot, slot)
    if candidate is None:
        return None, "missing_normalized_zero", None

    original_source_type: Optional[str] = None
    if isinstance(candidate, FinancialMetric):
        metric = candidate
    else:
        payload: dict[str, Any]
        if isinstance(candidate, dict):
            payload = dict(candidate)
        else:
            payload = {"value": candidate}

        prefix = f"forward_net_borrowing_{slot}y"
        def _metadata(name: str, default: Any = None) -> Any:
            if name in payload:
                return payload[name]
            return getattr(snapshot, f"{prefix}_{name}", default)

        original_source_type = _metadata("source_type")
        raw_source_type = str(original_source_type or "analyst_estimate").strip().lower()
        source_type_aliases = {
            "provider_forward": SourceType.ANALYST_ESTIMATE,
            "provider": SourceType.ANALYST_ESTIMATE,
            "forward_provider": SourceType.ANALYST_ESTIMATE,
            "analyst": SourceType.ANALYST_ESTIMATE,
            "analyst_estimate": SourceType.ANALYST_ESTIMATE,
            "actual": SourceType.ACTUAL,
            "derived": SourceType.DERIVED,
            "reliable_model": SourceType.DERIVED,
            "reliable_model": SourceType.DERIVED,
            "fixture": SourceType.FIXTURE,
        }
        normalized_source_type = source_type_aliases.get(raw_source_type)
        if normalized_source_type is None:
            return None, "rejected_invalid_forward_source", (
                f"Forward net borrowing source_type={original_source_type!r} is not an accepted explicit provider/model source."
            )
        period = _metadata("period", f"FY{slot}E")
        source = _metadata("source", "provider forward net borrowing")
        metric_as_of = _metadata("as_of", as_of) or as_of
        unit = _metadata("unit", None) or _metadata("currency", None) or getattr(snapshot, "currency", "USD") or "USD"
        confidence = _metadata("confidence", 0.7)
        is_estimated = _metadata("is_estimated", normalized_source_type != SourceType.ACTUAL)
        notes = _metadata("notes", None)
        try:
            metric = FinancialMetric(
                value=payload.get("value"),
                unit=str(unit),
                period=str(period),
                source=str(source),
                source_type=normalized_source_type,
                as_of=metric_as_of,
                confidence=float(confidence),
                is_estimated=bool(is_estimated),
                notes=notes,
            )
        except Exception as exc:
            return None, "rejected_invalid_forward_source", f"Forward net borrowing metadata is invalid: {exc}"

    period = str(metric.period or "").upper().strip()
    if _forward_borrowing_period_is_historical(period):
        return None, "rejected_historical_forward_source", (
            f"Forward net borrowing candidate has historical period {metric.period!r}; "
            "net_borrowing_ttm remains display-only."
        )

    # Do not silently accept a configured fallback as a forward debt-flow
    # estimate.  Named forward fields and a non-historical period are required.
    source_type = getattr(metric.source_type, "value", str(metric.source_type)).lower()
    if source_type in {SourceType.CONFIGURED_FALLBACK.value, "fallback", "system_default"}:
        return None, "rejected_unreliable_forward_source", (
            "Configured fallback cannot be used as forward net borrowing; "
            "provide an explicit provider estimate or user override."
        )
    if metric.value is None or not metric.value.is_finite():
        return None, "rejected_invalid_forward_source", "Forward net borrowing must be finite."

    note = metric.notes or ""
    if original_source_type and original_source_type not in {source_type, getattr(metric.source_type, "value", source_type)}:
        note = f"{note}; original provider source_type={original_source_type}".strip("; ")
        metric = metric.model_copy(update={"notes": note})
    return metric, "provider_forward", None


def _is_ntm_borrowing_period(metric: Optional[FinancialMetric]) -> bool:
    """Return whether a borrowing metric is explicitly a rolling NTM value."""

    return metric is not None and str(metric.period or "").upper().strip().startswith("NTM")


def _is_fiscal_stub_borrowing_period(
    metric: Optional[FinancialMetric],
    forecast_fy_end: Optional[date],
) -> bool:
    """Recognize a provider-labelled current-FY stub without guessing one.

    A stub is only eligible when the provider says it is a stub and the
    current fiscal year is anchored by ``forecast_fy_end``.  A plain ``FY1E``
    is deliberately *not* treated as a stub: it is a full-year estimate and
    cannot be relabelled as a rolling NTM amount.
    """

    if metric is None or forecast_fy_end is None:
        return False
    period = str(metric.period or "").upper().strip()
    if "STUB" not in period:
        return False
    explicit_year = _period_year(period)
    if explicit_year is not None:
        return explicit_year == forecast_fy_end.year
    return any(token in period for token in ("FY1", "0Y", "CURRENT"))


def _forward_borrowing_period_matches(
    metric: Optional[FinancialMetric],
    *,
    slot: int,
    forecast_fy_end: Optional[date],
    allow_stub: bool = False,
) -> bool:
    """Check that an annual borrowing value is anchored to the requested FY.

    A stub is an NTM conversion input only; it is never a complete current-FY
    value.  Callers must opt into that narrower use with ``allow_stub``.
    """

    period = str(metric.period or "").upper().strip() if metric is not None else ""
    if slot == 1 and "STUB" in period:
        return allow_stub and _is_fiscal_stub_borrowing_period(metric, forecast_fy_end)
    return _is_explicit_fy_metric(metric, slot, forecast_fy_end)


def _resolve_forward_borrowing_metric(
    snapshot: CompanyFinancialSnapshot,
    horizon: str,
    as_of: date,
    forecast_fy_end: Optional[date],
    ntm_weight_fy1: Decimal,
    ntm_weight_fy2: Decimal,
) -> tuple[Optional[FinancialMetric], str, Optional[str]]:
    """Resolve forward borrowing without crossing fiscal-horizon boundaries.

    ``forward_net_borrowing_1y`` and ``_2y`` are annual slots, not rolling
    NTM values.  For an NTM request an explicitly labelled NTM metric wins;
    otherwise both aligned fiscal-year values are required and are converted
    using the same remaining-current-FY/next-FY weights as the NTM revenue and
    EPS bridges.  A provider-labelled current-FY stub is already an amount for
    the remaining stub and is therefore added to the full next-FY amount.
    """

    normalized: dict[int, tuple[Optional[FinancialMetric], str, Optional[str]]] = {
        slot: _normalize_forward_borrowing_metric(snapshot, slot, as_of)
        for slot in (1, 2)
    }

    if horizon == "ntm":
        # An explicit rolling NTM input is the only single-period value that
        # can enter NTM FCFE.  A 1Y/2Y field with a non-NTM period is never
        # silently promoted to this branch.
        for slot in (1, 2):
            metric, _, _ = normalized[slot]
            if metric is not None and _is_ntm_borrowing_period(metric):
                return metric, "provider_forward", None

        fy1, status_1, error_1 = normalized[1]
        fy2, status_2, error_2 = normalized[2]
        fy1_aligned = _forward_borrowing_period_matches(
            fy1, slot=1, forecast_fy_end=forecast_fy_end, allow_stub=True
        )
        fy2_aligned = _forward_borrowing_period_matches(
            fy2, slot=2, forecast_fy_end=forecast_fy_end
        )

        if fy1_aligned and fy2_aligned and fy1 is not None and fy2 is not None:
            if _is_fiscal_stub_borrowing_period(fy1, forecast_fy_end):
                blended_value = (fy1.value + fy2.value).quantize(Decimal("1"), ROUND_HALF_UP)
                blended_period = "NTM (stub+FY2)"
                blend_note = (
                    "NTM borrowing converted from provider-labelled current-FY stub "
                    f"({fy1.period}) plus next FY ({fy2.period}); no FY1 full-year relabelling."
                )
            else:
                if forecast_fy_end is None:
                    return None, "rejected_period_mismatch", (
                        "NTM borrowing requires an anchored fiscal year end to convert FY1/FY2 values; "
                        "annual periods were not promoted."
                    )
                blended_value = (
                    ntm_weight_fy1 * fy1.value + ntm_weight_fy2 * fy2.value
                ).quantize(Decimal("1"), ROUND_HALF_UP)
                blended_period = f"NTM (w0={ntm_weight_fy1:.2f}, w1={ntm_weight_fy2:.2f})"
                blend_note = (
                    "NTM borrowing day-weighted conversion: "
                    f"{ntm_weight_fy1:.2f} {fy1.period} + {ntm_weight_fy2:.2f} {fy2.period}."
                )
            return (
                FinancialMetric(
                    value=blended_value,
                    unit=fy1.unit,
                    period=blended_period,
                    source=(
                        f"NTM forward borrowing blend: {fy1.value} ({fy1.period}) + "
                        f"{fy2.value} ({fy2.period})"
                    ),
                    source_type=SourceType.DERIVED,
                    as_of=as_of,
                    confidence=min(fy1.confidence, fy2.confidence),
                    is_estimated=True,
                    notes=blend_note,
                ),
                "provider_forward",
                None,
            )

        # A one-year value is an annual forecast, not a rolling NTM stub.  Be
        # explicit about the unavailable bridge so callers cannot mistake the
        # normalized zero for an observed debt-flow fact.
        observed_periods = ", ".join(
            f"FY{slot}={metric.period}" for slot, (metric, _, _) in normalized.items() if metric is not None
        ) or "none"
        normalization_errors = "; ".join(error for _, _, error in normalized.values() if error)
        detail = (
            "NTM forward borrowing unavailable: require an explicit NTM metric "
            "or aligned FY1/FY2 values with a verified fiscal year anchor; "
            f"received {observed_periods}. FY1E cannot be relabelled as rolling NTM."
        )
        if normalization_errors:
            detail += f" {normalization_errors}"
        status = (
            "rejected_period_mismatch"
            if fy1 is not None or fy2 is not None
            else next((status for status in (status_1, status_2) if status != "missing_normalized_zero"), "missing_normalized_zero")
        )
        return None, status, detail

    required_slot = 1 if horizon == "current_fy" else 2
    metric, status, error = normalized[required_slot]
    if metric is not None and _forward_borrowing_period_matches(
        metric, slot=required_slot, forecast_fy_end=forecast_fy_end
    ):
        return metric, "provider_forward", None
    if metric is not None:
        expected = "FY1/current fiscal year" if required_slot == 1 else "FY2/next fiscal year"
        return None, "rejected_period_mismatch", (
            f"{horizon} forward borrowing unavailable: candidate period {metric.period!r} "
            f"does not match required {expected}; no other fiscal slot was substituted."
        )
    other_slot = 2 if required_slot == 1 else 1
    other_metric, other_status, other_error = normalized[other_slot]
    if other_metric is not None:
        expected = "FY1/current fiscal year" if required_slot == 1 else "FY2/next fiscal year"
        return None, "rejected_period_mismatch", (
            f"{horizon} forward borrowing unavailable: required {expected} borrowing is missing; "
            f"candidate period {other_metric.period!r} from FY{other_slot} was not substituted."
        )
    if error:
        return None, status, error
    if other_error:
        return None, other_status, other_error
    return None, "missing_normalized_zero", None


@dataclass(frozen=True)
class _DriverSelection:
    """A request-scoped driver plus the evidence used to select it.

    ``value`` is an amount for operating drivers (D&A, CapEx and ΔNWC), and a
    ratio for EBITDA margin/tax rate.  ``kind`` makes that distinction explicit
    so a ratio can never be mistaken for a reported forward amount.  The FY
    values are optional per-year inputs used by the explicit DCF projection;
    they are kept separate from the request-horizon value so NTM blending does
    not relabel a single annual estimate.
    """

    value: Optional[Decimal]
    kind: str
    source: str
    as_of: Any
    period: str
    confidence: float
    is_estimated: bool
    notes: str
    metric: Optional[FinancialMetric] = None
    fy1_value: Optional[Decimal] = None
    fy2_value: Optional[Decimal] = None
    fy1_ratio: Optional[Decimal] = None
    fy2_ratio: Optional[Decimal] = None
    warnings: tuple[str, ...] = ()


def _metric_source_type_value(metric: Optional[FinancialMetric]) -> str:
    if metric is None:
        return ""
    return str(getattr(metric.source_type, "value", metric.source_type)).lower()


def _driver_metric_has_provenance(metric: Optional[FinancialMetric]) -> bool:
    """Require the metadata needed to audit a non-TTM driver observation."""

    if metric is None:
        return False
    notes = str(metric.notes or "").lower()
    return bool(
        str(metric.source or "").strip()
        and str(metric.period or "").strip()
        and getattr(metric, "as_of", None) is not None
    ) and not any(
        marker in notes for marker in ("bare adapter value", "adapter metadata incomplete")
    )


def _driver_candidate_has_provenance(candidate: Any) -> bool:
    """Check provenance before adapter defaults can turn a candidate usable."""

    if isinstance(candidate, FinancialMetric):
        return _driver_metric_has_provenance(candidate)
    if isinstance(candidate, Mapping):
        nested = candidate.get("metric") or candidate.get("candidate")
        if nested is not None:
            return _driver_candidate_has_provenance(nested)
        return bool(str(candidate.get("source") or "").strip()) and bool(
            str(candidate.get("period") or "").strip()
        ) and all(candidate.get(key) is not None for key in ("as_of", "source_type"))
    return False


def _driver_metric_kind(metric: Optional[FinancialMetric], driver: str) -> str:
    """Infer whether a forward candidate is an amount or a revenue ratio."""

    normalized_driver = str(driver or "").lower().replace(" ", "_")
    unit = str(getattr(metric, "unit", "") or "").lower() if metric is not None else ""
    if normalized_driver in {"tax_rate", "tax", "ebitda_margin", "ebitda_margin_ratio"}:
        return "ratio"
    if any(token in unit for token in ("ratio", "margin", "rate", "%", "/revenue", "percent")):
        return "ratio"
    return "amount"


def _driver_evidence_source_allowed(metric: Optional[FinancialMetric]) -> bool:
    """Exclude fixtures, fallbacks and request overrides from market evidence."""

    return _metric_source_type_value(metric) in {
        SourceType.ACTUAL.value,
        SourceType.ANALYST_ESTIMATE.value,
        SourceType.DERIVED.value,
    }


def _safe_metric_date(value: Any, default: date) -> date:
    if hasattr(value, "date") and not isinstance(value, date):
        try:
            value = value.date()
        except Exception:
            pass
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except Exception:
        return default


def _coerce_driver_metric(
    candidate: Any,
    *,
    default_unit: str,
    default_period: str,
    default_source: str,
    default_as_of: date,
) -> Optional[FinancialMetric]:
    """Coerce an optional adapter candidate while preserving its metadata.

    The normalized snapshot currently exposes only a small set of driver
    fields.  Some providers/adapters already transport richer forward or
    comparable candidates on the snapshot's extra mapping; accepting those
    shapes here lets the projection layer use them without changing the
    public model.  Bare values are intentionally low-confidence derived
    candidates and are never classified as reliable forward evidence.
    """

    if isinstance(candidate, FinancialMetric):
        return candidate
    if isinstance(candidate, Mapping):
        nested = candidate.get("metric") or candidate.get("candidate")
        if nested is not None and not isinstance(nested, (str, int, float, Decimal)):
            return _coerce_driver_metric(
                nested,
                default_unit=default_unit,
                default_period=default_period,
                default_source=default_source,
                default_as_of=default_as_of,
            )
        value_key = "value"
        if candidate.get("value") is None:
            value_key = "ratio" if "ratio" in candidate else "amount"
        value = candidate.get(value_key)
        if value is None:
            return None
        raw_type = candidate.get("source_type", SourceType.DERIVED)
        raw_type_text = str(getattr(raw_type, "value", raw_type)).strip().lower()
        if raw_type_text.startswith("sourcetype."):
            raw_type_text = raw_type_text.split(".", 1)[1]
        raw_type_aliases = {
            "analyst": SourceType.ANALYST_ESTIMATE,
            "analyst_estimate": SourceType.ANALYST_ESTIMATE,
            "provider": SourceType.ANALYST_ESTIMATE,
            "provider_forward": SourceType.ANALYST_ESTIMATE,
            "forward_provider": SourceType.ANALYST_ESTIMATE,
            "forecast": SourceType.ANALYST_ESTIMATE,
            "actual": SourceType.ACTUAL,
            "derived": SourceType.DERIVED,
            "configured_fallback": SourceType.CONFIGURED_FALLBACK,
            "fallback": SourceType.CONFIGURED_FALLBACK,
            "user_override": SourceType.USER_OVERRIDE,
            "fixture": SourceType.FIXTURE,
        }
        try:
            source_type = raw_type if isinstance(raw_type, SourceType) else raw_type_aliases.get(raw_type_text)
            if source_type is None:
                source_type = SourceType(raw_type_text)
        except (TypeError, ValueError):
            return None
        try:
            confidence = float(candidate.get("confidence", 0.5))
            explicit_unit = candidate.get("unit") or candidate.get("currency")
            inferred_unit = explicit_unit or ("ratio" if value_key == "ratio" else default_unit)
            metadata_missing = not (
                bool(str(candidate.get("source") or "").strip())
                and bool(str(candidate.get("period") or "").strip())
                and all(candidate.get(key) is not None for key in ("as_of", "source_type"))
            )
            notes = candidate.get("notes")
            if metadata_missing:
                notes = (
                    f"{notes}; " if notes else ""
                ) + "Adapter metadata incomplete; not reliable forward evidence."
            return FinancialMetric(
                value=value,
                unit=str(inferred_unit),
                period=str(candidate.get("period") or default_period),
                source=str(candidate.get("source") or default_source),
                source_type=source_type,
                as_of=_safe_metric_date(candidate.get("as_of"), default_as_of),
                confidence=confidence,
                is_estimated=bool(candidate.get("is_estimated", source_type != SourceType.ACTUAL)),
                notes=notes,
            )
        except (TypeError, ValueError, ArithmeticError):
            return None
    if candidate is None:
        return None
    # Numeric extras are accepted only as an explicitly degraded derived
    # candidate.  They cannot pass the reliable-forward gate below.
    try:
        return FinancialMetric(
            value=candidate,
            unit=default_unit,
            period=default_period,
            source=default_source,
            source_type=SourceType.DERIVED,
            as_of=default_as_of,
            confidence=0.25,
            is_estimated=True,
            notes="Bare adapter value; provenance metadata was not supplied.",
        )
    except (TypeError, ValueError, ArithmeticError):
        return None


def _driver_aliases(driver: str) -> tuple[str, ...]:
    return {
        "ebitda": ("ebitda", "ebitda_amount"),
        "ebitda_margin": ("ebitda_margin", "ebitda_margin_ratio"),
        "da": ("da", "d_and_a", "depreciation_amortization", "depreciation"),
        "capex": ("capex", "capital_expenditure", "capital_expense"),
        "nwc": ("nwc", "nwc_change", "working_capital", "working_capital_change"),
        "tax_rate": ("tax_rate", "tax"),
    }.get(driver, (driver,))


def _driver_container_names(*, industry: bool = False, historical: bool = False) -> tuple[str, ...]:
    if industry:
        return (
            "industry_driver_candidates",
            "industry_driver_ratios",
            "industry_drivers",
            "industry_comparables",
        )
    if historical:
        return (
            "historical_driver_candidates",
            "historical_driver_ratios",
            "historical_drivers",
            "driver_history",
            "financial_driver_history",
        )
    return (
        "forward_driver_candidates",
        "forward_driver_ratios",
        "forward_drivers",
        "financial_driver_candidates",
        "financial_forward_drivers",
    )


def _container_candidate(container: Any, keys: Sequence[str], slot: Optional[int] = None) -> Any:
    if not isinstance(container, Mapping):
        return None
    for key in keys:
        if key in container and container[key] is not None:
            candidate = container[key]
            if slot is not None and isinstance(candidate, Mapping):
                slot_keys = (
                    f"{slot}y",
                    f"{slot}Y",
                    str(slot),
                    f"forward_{slot}y",
                    f"FY{slot}E",
                    f"FY{slot}",
                    "current_fy" if slot == 1 else "next_fy",
                    f"fy{slot}",
                    "ntm" if slot == 0 else "",
                )
                for slot_key in slot_keys:
                    if slot_key and slot_key in candidate and candidate[slot_key] is not None:
                        return candidate[slot_key]
            return candidate
    return None


def _read_driver_candidate(
    snapshot: CompanyFinancialSnapshot,
    driver: str,
    *,
    slot: Optional[int],
    ntm: bool = False,
    industry: bool = False,
    historical: bool = False,
) -> Any:
    """Read a driver candidate from explicit attrs and adapter mappings."""

    aliases = _driver_aliases(driver)
    ratio_aliases = tuple(alias for alias in (f"{alias}_ratio" for alias in aliases) if alias not in aliases)
    names: list[str] = []
    for alias in (*aliases, *ratio_aliases):
        if ntm:
            names.extend((f"forward_{alias}_ntm", f"{alias}_forward_ntm", f"{alias}_ntm"))
        elif slot is not None and not industry and not historical:
            names.extend((
                f"forward_{alias}_{slot}y",
                f"{alias}_forward_{slot}y",
                f"forecast_{alias}_{slot}y",
                f"{alias}_{slot}y",
            ))
        elif historical:
            names.extend((
                f"{alias}_history",
                f"{alias}_historical",
                f"{alias}_ratio_history",
                f"{alias}_margin_history",
                f"historical_{alias}",
                f"historical_{alias}_ratio",
                f"historical_{alias}_margin",
                f"{alias}_history_metrics",
                f"historical_{alias}_metrics",
            ))
        elif industry:
            names.extend((
                f"industry_{alias}",
                f"industry_{alias}_ratio",
                f"industry_{alias}_margin",
            ))
    for name in names:
        candidate = getattr(snapshot, name, None)
        if candidate is not None:
            return candidate

    container_keys: list[str] = []
    for alias in (*aliases, *ratio_aliases):
        if ntm:
            container_keys.extend((f"forward_{alias}_ntm", f"{alias}_ntm", alias))
        elif slot is not None and not industry and not historical:
            container_keys.extend((f"forward_{alias}_{slot}y", f"{alias}_{slot}y", alias))
        elif industry:
            container_keys.extend((f"industry_{alias}", alias, f"{alias}_ratio"))
        elif historical:
            container_keys.extend((f"historical_{alias}", alias, f"{alias}_ratio"))
    for container_name in _driver_container_names(industry=industry, historical=historical):
        candidate = _container_candidate(
            getattr(snapshot, container_name, None),
            container_keys,
            slot=(0 if ntm else slot) if not (industry or historical) else None,
        )
        if candidate is not None:
            return candidate

    # ``multiple_candidates`` is the normalized extensibility seam used by
    # service adapters for evidence that is not yet a first-class field.
    multiple_candidates = getattr(snapshot, "multiple_candidates", None)
    if isinstance(multiple_candidates, Mapping):
        candidate = _container_candidate(
            multiple_candidates,
            container_keys,
            slot=(0 if ntm else slot) if not (industry or historical) else None,
        )
        if candidate is not None:
            return candidate
        # Some adapters group driver evidence under an explicit quality
        # bucket inside the existing extensibility mapping.
        groups = (
            ("industry", "industry_comparables", "industry_driver_ratios", "industry_drivers")
            if industry
            else (
                ("historical", "historical_driver_ratios", "historical_drivers", "driver_history")
                if historical
                else ("forward", "forward_driver_candidates", "forward_driver_ratios", "forward_drivers")
            )
        )
        for group_name in groups:
            candidate = _container_candidate(
                multiple_candidates.get(group_name),
                container_keys,
                slot=(0 if ntm else slot) if not (industry or historical) else None,
            )
            if candidate is not None:
                return candidate
    return None


def _is_reliable_forward_driver(metric: Optional[FinancialMetric]) -> bool:
    if not _driver_metric_has_provenance(metric) or metric is None or not metric.value.is_finite():
        return False
    period = str(metric.period or "").upper().strip()
    if not period or any(token in period for token in ("TTM", "LTM", "HISTORICAL", "TRAILING")):
        return False
    source_type = _metric_source_type_value(metric)
    if source_type == SourceType.ANALYST_ESTIMATE.value:
        return "adapter metadata incomplete" not in str(metric.notes or "").lower()
    # Provider adapters sometimes normalize a verified forward observation as
    # ``derived``.  The explicit forward period label is sufficient in that
    # adapter-owned forward slot; fixture, historical and bare values remain
    # excluded.
    evidence = f"{metric.source} {metric.notes or ''}".lower()
    period_looks_forward = (
        period.startswith(("NTM", "FY", "0Y", "1Y", "+1Y", "FORWARD", "FORECAST"))
        or period.endswith("E")
    )
    return (
        source_type == SourceType.DERIVED.value
        and metric.is_estimated
        and period_looks_forward
        and not any(token in evidence for token in ("historical", "trailing", "fixture"))
        and "fixture" not in evidence
        and "bare adapter value" not in evidence
        and "adapter metadata incomplete" not in evidence
    )


def _period_matches_slot(metric: Optional[FinancialMetric], slot: int, forecast_fy_end: Optional[date]) -> bool:
    if metric is None:
        return False
    period = str(metric.period or "").upper().strip()
    if period.startswith("NTM") or "TTM" in period:
        return False
    if _is_explicit_fy_metric(metric, slot, forecast_fy_end):
        return True
    # A provider's relative annual label can be accepted as a forward driver
    # when its slot field is explicit, but it remains lower-quality if there
    # is no fiscal-year anchor and is called out in lineage.
    relative = {
        "0Y": 1,
        "FORWARD_1Y": 1,
        "FY1E": 1,
        "+1Y": 2,
        "1Y": 2,
        "FORWARD_2Y": 2,
        "FY2E": 2,
    }
    return relative.get(period) == slot and forecast_fy_end is None


def _driver_default_period(horizon: str) -> str:
    return {"current_fy": "FY1E", "next_fy": "FY2E", "ntm": "NTM"}.get(horizon, "NTM")


def _blend_driver_metrics(
    first: FinancialMetric,
    second: FinancialMetric,
    *,
    w0: Decimal,
    w1: Decimal,
    as_of: date,
    label: str,
) -> FinancialMetric:
    precision = (
        Decimal("0.0001")
        if label in {"tax_rate", "ebitda_margin"}
        or "ratio" in str(first.unit).lower()
        or "rate" in str(first.unit).lower()
        else Decimal("1")
    )
    value = (w0 * first.value + w1 * second.value).quantize(precision, ROUND_HALF_UP)
    return FinancialMetric(
        value=value,
        unit=first.unit,
        period=f"NTM (w0={w0:.2f}, w1={w1:.2f})",
        source=f"NTM forward {label} blend: {first.value} ({first.period}) + {second.value} ({second.period})",
        source_type=SourceType.DERIVED,
        as_of=as_of,
        confidence=min(first.confidence, second.confidence),
        is_estimated=True,
        notes=(
            f"NTM day-weighted {label}: {w0:.2f} {first.period} + {w1:.2f} {second.period}; "
            "forward evidence retained from both annual periods."
        ),
    )


def _resolve_forward_driver_metric(
    snapshot: CompanyFinancialSnapshot,
    driver: str,
    horizon: str,
    *,
    as_of: date,
    forecast_fy_end: Optional[date],
    w0: Decimal,
    w1: Decimal,
    default_unit: str,
) -> tuple[Optional[FinancialMetric], Optional[FinancialMetric], Optional[FinancialMetric], tuple[str, ...]]:
    """Resolve verified forward candidates for a driver and horizon."""

    direct_ntm = _coerce_driver_metric(
        _read_driver_candidate(snapshot, driver, slot=None, ntm=True),
        default_unit=default_unit,
        default_period="NTM",
        default_source=f"provider forward {driver}",
        default_as_of=as_of,
    )
    if direct_ntm is not None and _is_reliable_forward_driver(direct_ntm) and str(direct_ntm.period).upper().startswith("NTM"):
        return direct_ntm, None, None, ()

    annual: dict[int, Optional[FinancialMetric]] = {}
    annual_warnings: list[str] = []
    for slot in (1, 2):
        metric = _coerce_driver_metric(
            _read_driver_candidate(snapshot, driver, slot=slot),
            default_unit=default_unit,
            default_period=f"FY{slot}E",
            default_source=f"provider forward {driver} FY{slot}",
            default_as_of=as_of,
        )
        if metric is not None and _is_reliable_forward_driver(metric) and _period_matches_slot(metric, slot, forecast_fy_end):
            annual[slot] = metric
        else:
            annual[slot] = None
            if metric is not None and _is_reliable_forward_driver(metric):
                annual_warnings.append(
                    f"Forward {driver} candidate period {metric.period!r} is not aligned to FY{slot}; it was excluded."
                )

    if horizon == "current_fy":
        return annual[1], annual[1], annual[2], tuple(annual_warnings)
    if horizon == "next_fy":
        return annual[2], annual[1], annual[2], tuple(annual_warnings)
    first, second = annual[1], annual[2]
    if first is not None and second is not None:
        return _blend_driver_metrics(first, second, w0=w0, w1=w1, as_of=as_of, label=driver), first, second, tuple(annual_warnings)
    if first is not None or second is not None:
        only = first or second
        annual_warnings.append(
            f"Forward {driver} has only one aligned annual estimate ({only.period}); "
            "NTM uses that single period as a degraded proxy."
        )
        return only, first, second, tuple(annual_warnings)
    return None, first, second, tuple(annual_warnings)


def _flatten_driver_series(raw: Any, *, default_period_prefix: str, default_unit: str, default_source: str, as_of: date) -> list[FinancialMetric]:
    """Flatten list/mapping adapter shapes into provenance-rich metrics."""

    if raw is None:
        return []
    if isinstance(raw, Mapping) and not any(key in raw for key in ("value", "ratio", "amount", "metric", "candidate")):
        for wrapper in ("metrics", "ratios", "observations", "history", "values"):
            if wrapper in raw:
                return _flatten_driver_series(
                    raw[wrapper],
                    default_period_prefix=default_period_prefix,
                    default_unit=default_unit,
                    default_source=default_source,
                    as_of=as_of,
                )
        values: list[FinancialMetric] = []
        for period, item in raw.items():
            if isinstance(item, Mapping) and not item.get("period"):
                item = {**item, "period": str(period)}
            elif not isinstance(item, Mapping):
                item = {"value": item, "period": str(period)}
            metric = _coerce_driver_metric(
                item,
                default_unit=default_unit,
                default_period=str(period),
                default_source=default_source,
                default_as_of=as_of,
            )
            if metric is not None:
                values.append(metric)
        return values
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        values = []
        for index, item in enumerate(raw, start=1):
            metric = _coerce_driver_metric(
                item,
                default_unit=default_unit,
                default_period=f"{default_period_prefix}{index}",
                default_source=default_source,
                default_as_of=as_of,
            )
            if metric is not None:
                values.append(metric)
        return values
    metric = _coerce_driver_metric(
        raw,
        default_unit=default_unit,
        default_period=f"{default_period_prefix}1",
        default_source=default_source,
        default_as_of=as_of,
    )
    return [metric] if metric is not None else []


def _history_ratio_candidates(
    snapshot: CompanyFinancialSnapshot,
    driver: str,
    *,
    as_of: date,
) -> list[FinancialMetric]:
    aliases = _driver_aliases(driver)
    raw = _read_driver_candidate(snapshot, driver, slot=None, historical=True)
    if raw is None:
        return []
    field_hint = " ".join(aliases).lower()
    series = _flatten_driver_series(
        raw,
        default_period_prefix="FY",
        default_unit="ratio" if ("ratio" in field_hint or "margin" in field_hint or driver == "tax_rate") else "USD",
        default_source=f"historical {driver} driver",
        as_of=as_of,
    )
    # A separate revenue history allows amount series (e.g. D&A dollars) to
    # become comparable ratios without inventing a TTM denominator.
    revenue_raw = None
    for name in ("revenue_history", "historical_revenue", "revenue_historical", "historical_revenue_metrics"):
        revenue_raw = getattr(snapshot, name, None)
        if revenue_raw is not None:
            break
    revenue_series = _flatten_driver_series(
        revenue_raw,
        default_period_prefix="FY",
        default_unit="USD",
        default_source="historical revenue driver",
        as_of=as_of,
    ) if revenue_raw is not None else []
    revenue_by_period = {
        str(metric.period).upper().strip(): metric
        for metric in revenue_series
        if metric.value > ZERO and _driver_metric_has_provenance(metric)
    }
    result: list[FinancialMetric] = []
    ratio_hint = "ratio" in field_hint or "margin" in field_hint or driver == "tax_rate"
    for index, metric in enumerate(series):
        if not metric.value.is_finite():
            continue
        if ratio_hint or "ratio" in str(metric.unit).lower() or "rate" in str(metric.unit).lower():
            ratio = metric.value
        else:
            revenue = revenue_by_period.get(str(metric.period).upper().strip())
            if (
                revenue is None
                and index < len(revenue_series)
                and revenue_series[index].value > ZERO
                and _driver_metric_has_provenance(revenue_series[index])
            ):
                revenue = revenue_series[index]
            if revenue is None:
                continue
            ratio = metric.value / revenue.value
        if ratio.is_finite() and _driver_metric_has_provenance(metric) and _driver_evidence_source_allowed(metric):
            result.append(metric.model_copy(update={
                "value": ratio,
                "unit": "ratio",
                "source": f"Historical {driver} ratio from {metric.source}",
                "source_type": SourceType.DERIVED,
                "is_estimated": True,
                "notes": f"Historical {driver} ratio observation; period={metric.period}; source={metric.source}.",
            }))
    # Multi-period means at least two independently dated observations; a lone
    # annual value is no more robust than a TTM ratio and is rejected here.
    distinct_periods = {str(metric.period).upper().strip() for metric in result}
    return result if len(distinct_periods) >= 2 else []


def _median_decimal(values: Sequence[Decimal]) -> Decimal:
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return ((ordered[midpoint - 1] + ordered[midpoint]) / Decimal("2")).quantize(Decimal("0.0001"), ROUND_HALF_UP)


def _resolve_historical_ratio(snapshot: CompanyFinancialSnapshot, driver: str, *, as_of: date) -> Optional[_DriverSelection]:
    candidates = _history_ratio_candidates(snapshot, driver, as_of=as_of)
    if len(candidates) < 2:
        return None
    ratio = _median_decimal([metric.value for metric in candidates])
    latest = max(candidates, key=lambda metric: metric.as_of)
    periods = ", ".join(str(metric.period) for metric in candidates)
    return _DriverSelection(
        value=ratio,
        kind="ratio",
        source="historical_multiperiod",
        as_of=latest.as_of,
        period=f"multi-period median ({periods})",
        confidence=min(metric.confidence for metric in candidates),
        is_estimated=True,
        notes=(
            f"Multi-period historical {driver} ratio median={ratio}; "
            f"observations={periods}; no single-period extrapolation used."
        ),
        metric=latest,
        fy1_ratio=ratio,
        fy2_ratio=ratio,
    )


def _resolve_industry_ratio(snapshot: CompanyFinancialSnapshot, driver: str, *, as_of: date) -> Optional[_DriverSelection]:
    raw = _read_driver_candidate(snapshot, driver, slot=None, industry=True)
    # Industry evidence must carry enough provenance to be auditable.  A bare
    # number (or an incomplete mapping) is not a comparable observation and
    # must not silently acquire adapter defaults here.  Nested FinancialMetric
    # candidates are already metadata-rich and remain eligible.
    if raw is not None and not _driver_candidate_has_provenance(raw):
        return None
    metric = _coerce_driver_metric(
        raw,
        default_unit="ratio",
        default_period="industry benchmark",
        default_source=f"industry comparable {driver} driver",
        default_as_of=as_of,
    )
    if (
        not _driver_metric_has_provenance(metric)
        or metric is None
        or not metric.value.is_finite()
        or not _driver_evidence_source_allowed(metric)
    ):
        return None
    if "ratio" not in str(metric.unit).lower() and driver != "tax_rate" and driver != "ebitda_margin":
        return None
    source_text = f"{metric.source} {metric.notes or ''}".strip()
    if not source_text or not str(metric.period).strip():
        return None
    ratio = metric.value
    if driver == "tax_rate" and not ZERO <= ratio <= Decimal("0.50"):
        return None
    return _DriverSelection(
        value=ratio,
        kind="ratio",
        source="industry_comparable",
        as_of=metric.as_of,
        period=metric.period,
        confidence=min(metric.confidence, 0.7),
        is_estimated=True,
        notes=(
            f"Industry comparable {driver} ratio={ratio}; source={metric.source}; "
            f"period={metric.period}; as_of={metric.as_of.isoformat()}."
        ),
        metric=metric,
        fy1_ratio=ratio,
        fy2_ratio=ratio,
    )


def _selection_from_forward_metric(
    metric: FinancialMetric,
    first: Optional[FinancialMetric],
    second: Optional[FinancialMetric],
    warnings: Sequence[str],
    *,
    driver: str,
    kind: Optional[str] = None,
) -> _DriverSelection:
    resolved_kind = kind or _driver_metric_kind(metric, driver)
    source = "analyst_estimate" if _metric_source_type_value(metric) == SourceType.ANALYST_ESTIMATE.value else "forward_provider"
    return _DriverSelection(
        value=metric.value,
        kind=resolved_kind,
        source=source,
        as_of=metric.as_of,
        period=metric.period,
        confidence=metric.confidence,
        is_estimated=True,
        notes=f"Reliable forward {driver} candidate: {metric.source}; period={metric.period}; {metric.notes or ''}".strip(),
        metric=metric,
        fy1_value=first.value if first is not None and resolved_kind == "amount" else None,
        fy2_value=second.value if second is not None and resolved_kind == "amount" else None,
        fy1_ratio=first.value if first is not None and resolved_kind == "ratio" else None,
        fy2_ratio=second.value if second is not None and resolved_kind == "ratio" else None,
        warnings=tuple(warnings),
    )


def _ttm_ratio_selection(
    metric: Optional[FinancialMetric],
    revenue: Optional[FinancialMetric],
    *,
    driver: str,
    as_of: date,
) -> Optional[_DriverSelection]:
    if metric is None:
        return None
    if revenue is None or revenue.value <= ZERO or not _periods_compatible(metric, revenue):
        return _DriverSelection(
            value=metric.value,
            kind="amount",
            source="historical_period_mismatch",
            as_of=metric.as_of,
            period=metric.period,
            confidence=min(metric.confidence, 0.5),
            is_estimated=True,
            notes=(
                f"Historical {driver} amount retained without ratio scaling because "
                f"period {metric.period} is not compatible with revenue period {revenue.period if revenue else 'missing'}."
            ),
            metric=metric,
            warnings=(
                f"Forward FCFF driver {driver} uses a historical amount with period mismatch; "
                "it is estimated and not a verified forward forecast.",
            ),
        )
    ratio = (metric.value / revenue.value).quantize(Decimal("0.0001"), ROUND_HALF_UP)
    return _DriverSelection(
        value=ratio,
        kind="ratio",
        source="historical_ttm_ratio",
        as_of=metric.as_of,
        period=metric.period,
        confidence=min(metric.confidence, 0.5),
        is_estimated=True,
        notes=(
            f"Single-period TTM {driver}/revenue ratio={ratio} from {metric.period}; "
            "degraded fallback because no reliable forward, multi-period, or industry driver was available."
        ),
        metric=metric,
        fy1_ratio=ratio,
        fy2_ratio=ratio,
        warnings=(
            f"Forward FCFF driver {driver} fell back to a single-period TTM ratio ({metric.period}); "
            "value is estimated/degraded and may not represent the forward period.",
        ),
    )


def _resolve_operating_driver(
    snapshot: CompanyFinancialSnapshot,
    driver: str,
    horizon: str,
    *,
    as_of: date,
    forecast_fy_end: Optional[date],
    w0: Decimal,
    w1: Decimal,
    fwd_revenue: Optional[Decimal],
    ttm_revenue: Optional[FinancialMetric],
    ttm_metric: Optional[FinancialMetric],
    default_unit: str,
) -> _DriverSelection:
    """Apply forward → multi-period → industry → TTM fallback ordering."""

    forward, first, second, forward_warnings = _resolve_forward_driver_metric(
        snapshot,
        driver,
        horizon,
        as_of=as_of,
        forecast_fy_end=forecast_fy_end,
        w0=w0,
        w1=w1,
        default_unit=default_unit,
    )
    if forward is not None:
        return _selection_from_forward_metric(
            forward,
            first,
            second,
            forward_warnings,
            driver=driver,
            kind=_driver_metric_kind(forward, driver),
        )
    historical = _resolve_historical_ratio(snapshot, driver, as_of=as_of)
    if historical is not None:
        return historical
    industry = _resolve_industry_ratio(snapshot, driver, as_of=as_of)
    if industry is not None:
        return industry
    ttm = _ttm_ratio_selection(ttm_metric, ttm_revenue, driver=driver, as_of=as_of)
    if ttm is not None:
        return ttm
    return _DriverSelection(
        value=None,
        kind="amount",
        source="unavailable",
        as_of=as_of,
        period="unavailable",
        confidence=0.0,
        is_estimated=True,
        notes=f"No usable forward, multi-period historical, industry, or compatible TTM {driver} driver.",
        warnings=(f"Forward FCFF driver {driver} is unavailable; no value was fabricated.",),
    )


def _fiscal_year_bounds(
    metric: Optional[FinancialMetric],
    slot: int,
    forecast_fy_end: Optional[date],
) -> tuple[Optional[date], Optional[date]]:
    """Resolve a full-FY date range from provider metadata without guessing."""

    if not _is_explicit_fy_metric(metric, slot, forecast_fy_end):
        return None, None
    if forecast_fy_end is not None:
        end = _safe_add_years(forecast_fy_end, slot - 1)
    else:
        year = _period_year(metric.period if metric is not None else None)
        if year is None:
            return None, None
        end = date(year, 12, 31)
    start = _safe_add_years(end, -1) + timedelta(days=1)
    return start, end


def calculate_ntm_weights(
    as_of: date,
    next_fy_end: Optional[date],
) -> tuple[Decimal, Decimal, int, int]:
    """
    Calculate bounded NTM day weights w0 (current FY) and w1 (next FY).
    w0 + w1 = 1.0; 0 <= w0 <= 1.0; 0 <= w1 <= 1.0.
    """
    if next_fy_end is None:
        return Decimal("1.0"), Decimal("0.0"), 365, 365

    if next_fy_end <= as_of:
        # If next fiscal year end is in the past, current FY has expired: 100% weight on next FY
        return Decimal("0.0"), Decimal("1.0"), 0, 365

    # Determine fiscal year length
    # If the target fiscal year ends in month m, day d, previous fiscal year end was ~1 year prior
    prev_fy_year = next_fy_end.year - 1
    try:
        prev_fy_end = date(prev_fy_year, next_fy_end.month, next_fy_end.day)
    except ValueError:
        prev_fy_end = date(prev_fy_year, next_fy_end.month, 28)

    fy_length = (next_fy_end - prev_fy_end).days
    if fy_length <= 0 or fy_length > 375:
        fy_length = 366 if _is_leap_year(next_fy_end.year) else 365

    remaining_days = (next_fy_end - as_of).days
    # Clamp remaining days to [0, fy_length] to guarantee bounded weights
    clamped_days = max(0, min(remaining_days, fy_length))

    w0 = (Decimal(str(clamped_days)) / Decimal(str(fy_length))).quantize(Decimal("0.0001"), ROUND_HALF_UP)
    w0 = max(Decimal("0.0"), min(Decimal("1.0"), w0))
    w1 = Decimal("1.0") - w0

    return w0, w1, clamped_days, fy_length


def derive_request_projections(
    snapshot: CompanyFinancialSnapshot,
    assumptions: ValuationAssumptions,
) -> RequestProjections:
    """
    Derive request-scoped forward metrics and projections with configured growth bounds
    and consensus horizon without modifying the input snapshot.
    """
    as_of = getattr(snapshot, "as_of", None) or (snapshot.current_price.as_of if getattr(snapshot, "current_price", None) else date.today())
    horizon = getattr(assumptions, "forecast_horizon", "ntm") or "ntm"
    growth_floor = getattr(assumptions, "growth_floor", Decimal("-0.20"))
    growth_cap = getattr(assumptions, "growth_cap", Decimal("0.40"))

    def clamp(g: Decimal) -> Decimal:
        return min(max(g, growth_floor), growth_cap)

    # Calculate NTM day weights
    next_fy_end = getattr(snapshot, "forecast_fiscal_year_end", None) or getattr(snapshot, "next_fiscal_year_end", None)
    w0, w1, remaining_days, fy_len = calculate_ntm_weights(as_of, next_fy_end)

    effective_horizon = horizon
    fallback_warning: Optional[str] = None

    # Forward EPS resolution
    fy1_eps = getattr(snapshot, "forward_eps_1y", None) or getattr(snapshot, "forward_eps", None)
    fy2_eps = getattr(snapshot, "forward_eps_2y", None) or getattr(snapshot, "forward_eps_next_fy", None)

    blended_eps: Optional[FinancialMetric] = None
    if horizon == "current_fy":
        blended_eps = fy1_eps
    elif horizon == "next_fy":
        if fy2_eps is not None and fy2_eps.value.is_finite():
            blended_eps = fy2_eps
        else:
            blended_eps = fy1_eps
            effective_horizon = "current_fy"
            fallback_warning = "Next FY (+2y) EPS estimate unavailable; fell back to current FY"
    elif horizon == "ntm":
        if fy1_eps is not None and fy2_eps is not None and fy1_eps.value.is_finite() and fy2_eps.value.is_finite():
            # Interpolate NTM EPS
            blended_val = (w0 * fy1_eps.value + w1 * fy2_eps.value).quantize(Decimal("0.01"), ROUND_HALF_UP)
            blended_eps = FinancialMetric(
                value=blended_val,
                unit="USD",
                period=f"NTM (w0={w0:.2f}, w1={w1:.2f})",
                source=f"NTM day-weighted blend: {w0:.1%} FY1 ({fy1_eps.value}) + {w1:.1%} FY2 ({fy2_eps.value})",
                source_type=SourceType.DERIVED,
                as_of=as_of,
                confidence=min(fy1_eps.confidence, fy2_eps.confidence),
                is_estimated=True,
                notes=f"Calculated from {remaining_days}/{fy_len} remaining days in fiscal year",
            )
        elif fy1_eps is not None:
            blended_eps = fy1_eps
            effective_horizon = "current_fy"
            fallback_warning = "NTM interpolation unavailable (missing +2y estimate); fell back to current FY"

    # Forward Revenue resolution.  A trailing TTM amount is a base input, not
    # an explicit FY1 estimate; keeping it out of ``fy1_rev`` prevents the
    # DCF path from relabelling NTM/TTM revenue as FY1E.
    fy1_rev = getattr(snapshot, "revenue_estimate_1y", None)
    fy2_rev = getattr(snapshot, "revenue_estimate_2y", None)
    raw_forward_revenue = getattr(snapshot, "forward_revenue", None)
    if fy1_rev is None and _is_explicit_fy_metric(raw_forward_revenue, 1, next_fy_end):
        fy1_rev = raw_forward_revenue
    blended_rev: Optional[FinancialMetric] = None
    if horizon == "current_fy":
        blended_rev = fy1_rev
    elif horizon == "next_fy":
        blended_rev = fy2_rev
    elif horizon == "ntm":
        if fy1_rev is not None and fy2_rev is not None and fy1_rev.value.is_finite() and fy2_rev.value.is_finite():
            blended_r_val = (w0 * fy1_rev.value + w1 * fy2_rev.value).quantize(Decimal("1"), ROUND_HALF_UP)
            blended_rev = FinancialMetric(
                value=blended_r_val,
                unit="USD",
                period=f"NTM (w0={w0:.2f}, w1={w1:.2f})",
                source=f"NTM day-weighted revenue: {w0:.1%} FY1 + {w1:.1%} FY2",
                source_type=SourceType.DERIVED,
                as_of=as_of,
                confidence=min(fy1_rev.confidence, fy2_rev.confidence),
                is_estimated=True,
                notes=f"Calculated from {remaining_days}/{fy_len} remaining days in fiscal year",
            )
        elif fy1_rev is not None:
            blended_rev = fy1_rev
        elif raw_forward_revenue is not None and str(raw_forward_revenue.period or "").upper().startswith("NTM"):
            blended_rev = raw_forward_revenue

    # With no independently forecast revenue, NTM can still be estimated from
    # an explicitly sourced historical revenue growth rate.  This is an NTM
    # bridge only; it is never exposed as FY1E/FY2E for DCF.
    if blended_rev is None and horizon == "ntm":
        base_revenue = getattr(snapshot, "revenue_ttm", None)
        raw_revenue_growth = getattr(snapshot, "revenue_growth", None)
        if (
            base_revenue is not None
            and base_revenue.value > Decimal("0")
            and raw_revenue_growth is not None
            and raw_revenue_growth.value.is_finite()
        ):
            effective_revenue_growth = clamp(raw_revenue_growth.value)
            derived_revenue = (
                base_revenue.value * (Decimal("1") + effective_revenue_growth)
            ).quantize(Decimal("1"), ROUND_HALF_UP)
            blended_rev = FinancialMetric(
                value=derived_revenue,
                unit=base_revenue.unit,
                period="NTM",
                source=f"Derived NTM revenue: {base_revenue.value} × (1 + {effective_revenue_growth})",
                source_type=SourceType.DERIVED,
                as_of=as_of,
                confidence=min(base_revenue.confidence, raw_revenue_growth.confidence),
                is_estimated=True,
                notes=(
                    f"Historical revenue growth continuation; raw={raw_revenue_growth.value}, "
                    f"effective={effective_revenue_growth}; not an explicit FY1 estimate."
                ),
            )

    # ------------------------------------------------------------------
    # Forward Financial Drivers & Auditable Bridge (Issue 01 remediation)
    # Bridge:
    # 1. EBITDA = Forecast Revenue * EBITDA Margin
    # 2. EBIT = EBITDA - D&A
    # 3. NOPAT = EBIT * (1 - TaxRate)
    # 4. FCFF = NOPAT + D&A - CapEx - ΔNWC
    # 5. FCFE = FCFF - Interest * (1 - TaxRate) + NetBorrowing
    # ------------------------------------------------------------------

    # Resolve Forecast Revenue
    fwd_rev_val: Optional[Decimal] = None
    if blended_rev is not None and blended_rev.value > Decimal("0"):
        fwd_rev_val = blended_rev.value
    elif fy1_rev is not None and fy1_rev.value > Decimal("0"):
        fwd_rev_val = fy1_rev.value
    elif raw_forward_revenue is not None and raw_forward_revenue.value > Decimal("0") and horizon == "ntm":
        fwd_rev_val = raw_forward_revenue.value

    # Resolve forward financial drivers.  The order is intentional: explicit
    # request overrides, reliable forward candidates, multi-period historical
    # ratios, industry comparables, then a clearly degraded single-period TTM
    # ratio.  A TTM ratio remains usable for continuity, but it is never
    # presented as a high-quality forward fact.
    base_ebitda = getattr(snapshot, "ebitda_ttm", None) or getattr(snapshot, "ebitda", None)
    raw_forward_ebitda = getattr(snapshot, "forward_ebitda_1y", None) or getattr(snapshot, "forward_ebitda", None)
    if raw_forward_ebitda is not None and not isinstance(raw_forward_ebitda, FinancialMetric):
        raw_forward_ebitda = _coerce_driver_metric(
            raw_forward_ebitda,
            default_unit=getattr(snapshot, "currency", "USD") or "USD",
            default_period="FY1E",
            default_source="provider forward ebitda",
            default_as_of=as_of,
        )

    has_forward_revenue_est = (
        getattr(snapshot, "revenue_estimate_1y", None) is not None
        or getattr(snapshot, "revenue_estimate_2y", None) is not None
        or getattr(snapshot, "forward_revenue", None) is not None
    )

    has_driver_overrides_ebitda = getattr(assumptions, "driver_ebitda_margin", None) is not None
    driver_selections: dict[str, _DriverSelection] = {}
    driver_warnings: list[str] = []

    forward_ebitda_metric, forward_ebitda_fy1, forward_ebitda_fy2, forward_ebitda_warnings = _resolve_forward_driver_metric(
        snapshot,
        "ebitda",
        horizon,
        as_of=as_of,
        forecast_fy_end=next_fy_end,
        w0=w0,
        w1=w1,
        default_unit=getattr(snapshot, "currency", "USD") or "USD",
    )
    forward_ebitda_margin_metric, forward_ebitda_margin_fy1, forward_ebitda_margin_fy2, forward_ebitda_margin_warnings = _resolve_forward_driver_metric(
        snapshot,
        "ebitda_margin",
        horizon,
        as_of=as_of,
        forecast_fy_end=next_fy_end,
        w0=w0,
        w1=w1,
        default_unit="ratio",
    )

    ebitda_margin: Optional[Decimal] = None
    ebitda_margin_source = "unavailable"
    ebitda_margin_as_of = getattr(snapshot, "income_statement_as_of", None) or as_of
    ebitda_margin_period = getattr(getattr(snapshot, "revenue_ttm", None), "period", "TTM")
    direct_forward_ebitda_metric: Optional[FinancialMetric] = None

    if has_driver_overrides_ebitda:
        ebitda_margin = assumptions.driver_ebitda_margin
        ebitda_margin_source = "user_override"
        ebitda_margin_period = "user_override"
        ebitda_margin_as_of = as_of
        driver_selections["ebitda_margin"] = _DriverSelection(
            value=ebitda_margin,
            kind="ratio",
            source="user_override",
            as_of=as_of,
            period="user_override",
            confidence=1.0,
            is_estimated=False,
            notes="EBITDA margin supplied by request override.",
            fy1_ratio=ebitda_margin,
            fy2_ratio=ebitda_margin,
        )
    elif forward_ebitda_metric is not None and _driver_metric_kind(forward_ebitda_metric, "ebitda") == "ratio":
        # A provider may publish the forward EBITDA driver directly as a
        # margin.  Preserve that ratio and its FY observations rather than
        # treating it as an amount and dividing by request-horizon revenue.
        forward_selection = _selection_from_forward_metric(
            forward_ebitda_metric,
            forward_ebitda_fy1,
            forward_ebitda_fy2,
            forward_ebitda_warnings,
            driver="EBITDA margin",
            kind="ratio",
        )
        ebitda_margin = forward_selection.value
        driver_selections["ebitda_margin"] = forward_selection
        ebitda_margin_source = forward_selection.source
        ebitda_margin_as_of = forward_selection.as_of
        ebitda_margin_period = forward_selection.period
    elif forward_ebitda_metric is not None and fwd_rev_val is not None and fwd_rev_val > ZERO:
        # A direct forward EBITDA amount is converted to a margin only against
        # the same request-horizon revenue amount.  The amount itself remains
        # available so a reliable analyst estimate is not replaced by a TTM
        # ratio merely to construct the bridge identity.
        ebitda_margin = (forward_ebitda_metric.value / fwd_rev_val).quantize(Decimal("0.0001"), ROUND_HALF_UP)
        forward_selection = _selection_from_forward_metric(
            forward_ebitda_metric,
            forward_ebitda_fy1,
            forward_ebitda_fy2,
            forward_ebitda_warnings,
            driver="EBITDA",
            kind="amount",
        )
        driver_selections["ebitda_margin"] = forward_selection
        direct_forward_ebitda_metric = forward_ebitda_metric
        ebitda_margin_source = forward_selection.source
        ebitda_margin_as_of = forward_selection.as_of
        ebitda_margin_period = forward_selection.period
    elif forward_ebitda_margin_metric is not None:
        forward_selection = _selection_from_forward_metric(
            forward_ebitda_margin_metric,
            forward_ebitda_margin_fy1,
            forward_ebitda_margin_fy2,
            forward_ebitda_margin_warnings,
            driver="EBITDA margin",
            kind="ratio",
        )
        ebitda_margin = forward_selection.value
        driver_selections["ebitda_margin"] = forward_selection
        ebitda_margin_source = forward_selection.source
        ebitda_margin_as_of = forward_selection.as_of
        ebitda_margin_period = forward_selection.period
    else:
        historical_margin = _resolve_historical_ratio(snapshot, "ebitda_margin", as_of=as_of)
        if historical_margin is not None:
            ebitda_margin = historical_margin.value
            driver_selections["ebitda_margin"] = historical_margin
        else:
            industry_margin = _resolve_industry_ratio(snapshot, "ebitda_margin", as_of=as_of)
            if industry_margin is not None:
                ebitda_margin = industry_margin.value
                driver_selections["ebitda_margin"] = industry_margin
        if "ebitda_margin" not in driver_selections and base_ebitda is not None and getattr(snapshot, "revenue_ttm", None) is not None and snapshot.revenue_ttm.value > ZERO:
            # The TTM ratio is the final fallback.  It is retained for
            # continuity, but lineage/warnings explicitly downgrade it.
            ttm_margin = _ttm_ratio_selection(
                base_ebitda,
                snapshot.revenue_ttm,
                driver="EBITDA margin",
                as_of=as_of,
            )
            if ttm_margin is not None:
                ebitda_margin = ttm_margin.value if ttm_margin.kind == "ratio" else (
                    ttm_margin.value / snapshot.revenue_ttm.value
                    if snapshot.revenue_ttm.value > ZERO else None
                )
                driver_selections["ebitda_margin"] = ttm_margin
        elif (
            raw_forward_ebitda is not None
            and fwd_rev_val is not None
            and fwd_rev_val > ZERO
            and _driver_metric_has_provenance(raw_forward_ebitda)
            and _driver_evidence_source_allowed(raw_forward_ebitda)
        ):
            # A non-consensus forward EBITDA candidate is not promoted to a
            # reliable forecast, but is preferable to silently claiming a
            # high-quality TTM margin when no historical base exists.
            ebitda_margin = (raw_forward_ebitda.value / fwd_rev_val).quantize(Decimal("0.0001"), ROUND_HALF_UP)
            driver_selections["ebitda_margin"] = _DriverSelection(
                value=ebitda_margin,
                kind="ratio",
                source="forward_unverified",
                as_of=raw_forward_ebitda.as_of,
                period=raw_forward_ebitda.period,
                confidence=min(raw_forward_ebitda.confidence, 0.35),
                is_estimated=True,
                notes=(
                    f"Forward EBITDA candidate {raw_forward_ebitda.source} was not accepted as reliable; "
                    "margin is an explicitly degraded ratio proxy."
                ),
                warnings=(
                    "Forward EBITDA was not accepted as reliable provider/analyst evidence; "
                    "the implied margin is estimated/degraded.",
                ),
            )

    ebitda_selection = driver_selections.get("ebitda_margin")
    if ebitda_selection is not None:
        ebitda_margin_source = ebitda_selection.source
        ebitda_margin_as_of = ebitda_selection.as_of
        ebitda_margin_period = ebitda_selection.period
        driver_warnings.extend(ebitda_selection.warnings)
    else:
        driver_warnings.append(
            "Forward FCFF EBITDA margin is unavailable; no value was fabricated."
        )

    # Explicit forward EBITDA is authoritative only when it passed the
    # reliability gate; direct fixture/derived placeholders still flow
    # through the degraded bridge path below.

    target_metric_period = (
        blended_rev.period
        if blended_rev is not None and str(blended_rev.period or "").upper().startswith(("FY", "NTM"))
        else ("FY1E" if horizon == "current_fy" else ("FY2E" if horizon == "next_fy" else "NTM"))
    )

    # Derive forward EBITDA (EBITDA = Revenue * Margin; no base*(1+g)
    # extrapolation).  A reliable forward amount is preserved as-is; ratio
    # based selections are calculated from the request-horizon revenue.
    derived_ebitda: Optional[FinancialMetric] = None
    if direct_forward_ebitda_metric is not None and not has_driver_overrides_ebitda:
        derived_ebitda = direct_forward_ebitda_metric
    elif fwd_rev_val is not None and ebitda_margin is not None:
        calc_ebitda_val = (fwd_rev_val * ebitda_margin).quantize(Decimal("1"), ROUND_HALF_UP)
        selection = driver_selections.get("ebitda_margin")
        derived_ebitda = FinancialMetric(
            value=calc_ebitda_val,
            unit=getattr(snapshot, "currency", "USD") or "USD",
            period=target_metric_period,
            source=f"Financial driver bridge: Revenue ({fwd_rev_val}) × EBITDA Margin ({ebitda_margin:.2%})",
            source_type=SourceType.USER_OVERRIDE if has_driver_overrides_ebitda else SourceType.DERIVED,
            as_of=as_of,
            confidence=selection.confidence if selection is not None else 0.35,
            is_estimated=not has_driver_overrides_ebitda,
            notes=(
                f"EBITDA margin source: {ebitda_margin_source}; "
                f"{selection.notes if selection is not None else 'no driver provenance'}"
            ),
        )

    # Resolve D&A using the same forward/multi-period/industry/TTM hierarchy.
    da_selection: _DriverSelection
    if getattr(assumptions, "driver_da", None) is not None:
        da_selection = _DriverSelection(
            value=assumptions.driver_da,
            kind="amount",
            source="user_override",
            as_of=as_of,
            period="user_override",
            confidence=1.0,
            is_estimated=False,
            notes="D&A amount supplied by request override.",
            fy1_value=assumptions.driver_da,
            fy2_value=assumptions.driver_da,
        )
    elif getattr(assumptions, "driver_da_ratio", None) is not None:
        da_ratio = assumptions.driver_da_ratio
        da_selection = _DriverSelection(
            value=da_ratio,
            kind="ratio",
            source="user_override",
            as_of=as_of,
            period="user_override",
            confidence=1.0,
            is_estimated=False,
            notes="D&A/revenue ratio supplied by request override.",
            fy1_ratio=da_ratio,
            fy2_ratio=da_ratio,
        )
    else:
        da_selection = _resolve_operating_driver(
            snapshot,
            "da",
            horizon,
            as_of=as_of,
            forecast_fy_end=next_fy_end,
            w0=w0,
            w1=w1,
            fwd_revenue=fwd_rev_val,
            ttm_revenue=getattr(snapshot, "revenue_ttm", None),
            ttm_metric=getattr(snapshot, "da_ttm", None),
            default_unit=getattr(snapshot, "currency", "USD") or "USD",
        )
    driver_selections["da"] = da_selection
    driver_warnings.extend(da_selection.warnings)
    da_val: Optional[Decimal] = None
    if da_selection.value is not None:
        da_val = (
            fwd_rev_val * da_selection.value
            if da_selection.kind == "ratio" and fwd_rev_val is not None
            else da_selection.value
        )
        if da_selection.kind == "ratio":
            da_val = da_val.quantize(Decimal("1"), ROUND_HALF_UP)
    da_source = da_selection.source
    da_as_of: Any = da_selection.as_of
    da_period_str: str = da_selection.period

    # EBIT = EBITDA - D&A (requires both EBITDA and D&A; never fabricate D&A)
    ebit_val = (derived_ebitda.value - da_val) if (derived_ebitda is not None and da_val is not None) else None

    # Resolve Tax Rate.  Tax is already a ratio, so no revenue scaling is
    # applied.  Forward/multi-period/industry evidence outranks a one-period
    # effective rate; the statutory default remains an explicit policy fallback.
    tax_rate_val = Decimal("0.21")
    tax_source = "statutory_default"
    tax_as_of: Any = getattr(snapshot, "income_statement_as_of", None) or as_of
    tax_period_str: str = "statutory"
    tax_selection: Optional[_DriverSelection] = None
    if getattr(assumptions, "driver_tax_rate", None) is not None:
        tax_rate_val = assumptions.driver_tax_rate
        tax_source = "user_override"
        tax_period_str = "user_override"
        tax_as_of = as_of
        tax_selection = _DriverSelection(
            value=tax_rate_val,
            kind="ratio",
            source="user_override",
            as_of=as_of,
            period="user_override",
            confidence=1.0,
            is_estimated=False,
            notes="Tax rate supplied by request override.",
            fy1_ratio=tax_rate_val,
            fy2_ratio=tax_rate_val,
        )
    else:
        forward_tax, forward_tax_fy1, forward_tax_fy2, forward_tax_warnings = _resolve_forward_driver_metric(
            snapshot,
            "tax_rate",
            horizon,
            as_of=as_of,
            forecast_fy_end=next_fy_end,
            w0=w0,
            w1=w1,
            default_unit="ratio",
        )
        if forward_tax is not None and ZERO <= forward_tax.value <= Decimal("0.50"):
            tax_selection = _selection_from_forward_metric(
                forward_tax,
                forward_tax_fy1,
                forward_tax_fy2,
                forward_tax_warnings,
                driver="tax rate",
                kind="ratio",
            )
        else:
            historical_tax = _resolve_historical_ratio(snapshot, "tax_rate", as_of=as_of)
            if historical_tax is not None and ZERO <= historical_tax.value <= Decimal("0.50"):
                tax_selection = historical_tax
            else:
                industry_tax = _resolve_industry_ratio(snapshot, "tax_rate", as_of=as_of)
                if industry_tax is not None and industry_tax.value <= Decimal("0.50"):
                    tax_selection = industry_tax
        if tax_selection is None:
            ttm_tax = getattr(snapshot, "tax_rate", None)
            if ttm_tax is not None and ZERO <= ttm_tax.value <= Decimal("0.50"):
                tax_selection = _DriverSelection(
                    value=ttm_tax.value,
                    kind="ratio",
                    source="historical_ttm_rate",
                    as_of=ttm_tax.as_of,
                    period=ttm_tax.period,
                    confidence=min(ttm_tax.confidence, 0.5),
                    is_estimated=True,
                    notes=(
                        f"Single-period TTM effective tax rate={ttm_tax.value} from {ttm_tax.period}; "
                        "degraded fallback because no reliable forward, multi-period, or industry rate was available."
                    ),
                    metric=ttm_tax,
                    fy1_ratio=ttm_tax.value,
                    fy2_ratio=ttm_tax.value,
                    warnings=(
                        f"Forward FCFF tax rate fell back to a single-period TTM effective rate ({ttm_tax.period}); "
                        "value is estimated/degraded and may not represent the forward period.",
                    ),
                )
        if tax_selection is not None:
            tax_rate_val = tax_selection.value
            tax_source = tax_selection.source
            tax_as_of = tax_selection.as_of
            tax_period_str = tax_selection.period
        else:
            tax_selection = _DriverSelection(
                value=tax_rate_val,
                kind="ratio",
                source="statutory_default",
                as_of=tax_as_of,
                period=tax_period_str,
                confidence=0.35,
                is_estimated=True,
                notes="Configured statutory tax default; company-specific forward tax evidence unavailable.",
                fy1_ratio=tax_rate_val,
                fy2_ratio=tax_rate_val,
                warnings=(
                    "Forward FCFF tax rate uses the configured statutory default; "
                    "company-specific forward tax evidence is unavailable.",
                ),
            )
    driver_selections["tax_rate"] = tax_selection
    driver_warnings.extend(tax_selection.warnings)

    # NOPAT = EBIT * (1 - TaxRate)
    nopat_val = (ebit_val * (Decimal("1") - tax_rate_val)).quantize(Decimal("1"), ROUND_HALF_UP) if ebit_val is not None else None

    # Resolve CapEx and ΔNWC through the same hierarchy.  Ratio selections are
    # applied only when a valid forward revenue amount exists; otherwise the
    # driver remains unavailable instead of being filled with zero.
    def _override_or_driver(
        driver: str,
        amount_attr: str,
        ratio_attr: str,
        snapshot_attr: str,
    ) -> _DriverSelection:
        amount = getattr(assumptions, amount_attr, None)
        if amount is not None:
            return _DriverSelection(
                value=amount,
                kind="amount",
                source="user_override",
                as_of=as_of,
                period="user_override",
                confidence=1.0,
                is_estimated=False,
                notes=f"{driver} amount supplied by request override.",
                fy1_value=amount,
                fy2_value=amount,
            )
        ratio = getattr(assumptions, ratio_attr, None)
        if ratio is not None:
            return _DriverSelection(
                value=ratio,
                kind="ratio",
                source="user_override",
                as_of=as_of,
                period="user_override",
                confidence=1.0,
                is_estimated=False,
                notes=f"{driver}/revenue ratio supplied by request override.",
                fy1_ratio=ratio,
                fy2_ratio=ratio,
            )
        return _resolve_operating_driver(
            snapshot,
            driver,
            horizon,
            as_of=as_of,
            forecast_fy_end=next_fy_end,
            w0=w0,
            w1=w1,
            fwd_revenue=fwd_rev_val,
            ttm_revenue=getattr(snapshot, "revenue_ttm", None),
            ttm_metric=getattr(snapshot, snapshot_attr, None),
            default_unit=getattr(snapshot, "currency", "USD") or "USD",
        )

    capex_selection = _override_or_driver("capex", "driver_capex", "driver_capex_ratio", "capex_ttm")
    nwc_selection = _override_or_driver("nwc", "driver_nwc_change", "driver_nwc_ratio", "nwc_change_ttm")
    driver_selections["capex"] = capex_selection
    driver_selections["nwc_change"] = nwc_selection
    driver_warnings.extend(capex_selection.warnings)
    driver_warnings.extend(nwc_selection.warnings)

    def _selection_amount(selection: _DriverSelection) -> Optional[Decimal]:
        if selection.value is None:
            return None
        if selection.kind == "ratio":
            if fwd_rev_val is None or fwd_rev_val <= ZERO:
                return None
            return (fwd_rev_val * selection.value).quantize(Decimal("1"), ROUND_HALF_UP)
        return selection.value

    capex_val: Optional[Decimal] = _selection_amount(capex_selection)
    nwc_change_val: Optional[Decimal] = _selection_amount(nwc_selection)
    capex_source: Optional[str] = capex_selection.source
    nwc_source: Optional[str] = nwc_selection.source
    capex_as_of: Any = capex_selection.as_of
    nwc_as_of: Any = nwc_selection.as_of
    capex_period_str: str = capex_selection.period
    nwc_period_str: str = nwc_selection.period

    # FCFF = NOPAT + D&A - CapEx - ΔNWC
    raw_forward_fcff = getattr(snapshot, "forward_fcff_1y", None)
    is_fcff_consensus = (
        raw_forward_fcff is not None
        and getattr(raw_forward_fcff, "source_type", None) == SourceType.ANALYST_ESTIMATE
    )

    has_driver_overrides_fcff = any(
        getattr(assumptions, k, None) is not None
        for k in ("driver_ebitda_margin", "driver_capex", "driver_capex_ratio", "driver_nwc_change", "driver_nwc_ratio", "driver_da", "driver_da_ratio", "driver_tax_rate")
    )

    bridge_fcff: Optional[Decimal] = None
    if nopat_val is not None and da_val is not None and capex_val is not None and nwc_change_val is not None:
        bridge_fcff = (nopat_val + da_val - capex_val - nwc_change_val).quantize(Decimal("1"), ROUND_HALF_UP)

    derived_fcff_1y: Optional[FinancialMetric] = None
    derived_fcff_2y: Optional[FinancialMetric] = None

    if is_fcff_consensus and not has_driver_overrides_fcff:
        derived_fcff_1y = raw_forward_fcff
        if getattr(snapshot, "forward_fcff_2y", None) is not None and snapshot.forward_fcff_2y.source_type == SourceType.ANALYST_ESTIMATE:
            derived_fcff_2y = snapshot.forward_fcff_2y
    elif bridge_fcff is not None and (has_driver_overrides_fcff or has_forward_revenue_est or fwd_rev_val is not None):
        bridge_driver_note = " ".join(driver_warnings)
        derived_fcff_1y = FinancialMetric(
            value=bridge_fcff,
            unit=getattr(snapshot, "currency", "USD") or "USD",
            period=target_metric_period,
            source=f"Financial driver bridge: NOPAT ({nopat_val}) + D&A ({da_val}) - CapEx ({capex_val}) - ΔNWC ({nwc_change_val})",
            source_type=SourceType.USER_OVERRIDE if has_driver_overrides_fcff else SourceType.DERIVED,
            as_of=as_of,
            confidence=0.8,
            is_estimated=True,
            notes=(
                "FCFF = EBIT*(1-T) + D&A - CapEx - ΔNWC; excludes net borrowing. "
                + bridge_driver_note
                if bridge_driver_note else "FCFF = EBIT*(1-T) + D&A - CapEx - ΔNWC; excludes net borrowing."
            ),
        )

    # ------------------------------------------------------------------
    # Construct DCF explicit forecast Year 1 and Year 2 as consistent,
    # non-overlapping full fiscal years (FY1E and FY2E).
    # ------------------------------------------------------------------
    dcf_fcff_1y: Optional[FinancialMetric] = None
    dcf_fcff_2y: Optional[FinancialMetric] = None

    fy1_revenue_is_explicit = _is_explicit_fy_metric(fy1_rev, 1, next_fy_end)
    fy2_revenue_is_explicit = _is_explicit_fy_metric(fy2_rev, 2, next_fy_end)

    def _driver_amount_for_year(
        selection: _DriverSelection,
        slot: int,
        revenue_value: Decimal,
    ) -> Optional[Decimal]:
        """Resolve one explicit FY driver without hiding a period mismatch."""

        if selection.kind == "ratio":
            ratio = selection.fy1_ratio if slot == 1 else selection.fy2_ratio
            # An explicit rolling NTM ratio cannot be relabelled as a full
            # fiscal-year ratio.  Annual blends carry per-year ratios above;
            # TTM, industry and user-ratio selections may use their stated
            # ratio as an explicitly degraded/selected driver.
            if ratio is None and str(selection.period).upper().strip().startswith("NTM"):
                return None
            ratio = ratio if ratio is not None else selection.value
            if ratio is None:
                return None
            return (revenue_value * ratio).quantize(Decimal("1"), ROUND_HALF_UP)
        explicit = selection.fy1_value if slot == 1 else selection.fy2_value
        if explicit is not None:
            return explicit
        # Amounts are not safely scalable across periods.  In particular, an
        # NTM amount is not a full-FY amount, and a lone annual estimate cannot
        # stand in for the other fiscal slot.  The period-mismatch historical
        # path intentionally retains its stated amount for compatibility, but
        # never applies a hidden revenue scale.
        if selection.source == "historical_period_mismatch":
            return selection.value
        return None

    def _driver_ratio_for_year(
        selection: Optional[_DriverSelection],
        slot: int,
        fallback: Optional[Decimal],
    ) -> Optional[Decimal]:
        if selection is None:
            return fallback
        ratio = selection.fy1_ratio if slot == 1 else selection.fy2_ratio
        if ratio is not None:
            return ratio
        if str(selection.period).upper().strip().startswith("NTM"):
            return None
        return fallback

    def _ebitda_amount_for_year(selection: Optional[_DriverSelection], slot: int, revenue_value: Decimal) -> Optional[Decimal]:
        if selection is not None and selection.kind == "amount":
            explicit = selection.fy1_value if slot == 1 else selection.fy2_value
            if explicit is not None:
                return explicit
            # A single aligned annual EBITDA estimate may provide a clearly
            # degraded implied margin for the other FY, preserving the legacy
            # DCF continuation while the selection warning makes the proxy
            # visible.  An explicitly rolling NTM amount is never relabelled
            # as a full fiscal year.
            if str(selection.period).upper().strip().startswith("NTM"):
                return None
        return (revenue_value * ebitda_margin).quantize(Decimal("1"), ROUND_HALF_UP) if ebitda_margin is not None else None

    ebitda_margin_selection = driver_selections.get("ebitda_margin")

    # A direct FCFF estimate is eligible for DCF only when it identifies a
    # concrete FY1 period. Relative 0y/forward_1y labels become concrete only
    # with a fiscal-year-end anchor; NTM/TTM remain ineligible. Driver
    # overrides take precedence over direct consensus for both years.
    if (
        is_fcff_consensus
        and not has_driver_overrides_fcff
        and _is_explicit_fy_metric(raw_forward_fcff, 1, next_fy_end)
    ):
        dcf_fcff_1y = raw_forward_fcff
    elif (
        fy1_revenue_is_explicit
        and ebitda_margin is not None
        and da_val is not None
        and capex_val is not None
        and nwc_change_val is not None
    ):
        fy1_revenue_val = fy1_rev.value
        if fy1_revenue_val > Decimal("0"):
            ebitda_fy1 = _ebitda_amount_for_year(ebitda_margin_selection, 1, fy1_revenue_val)
            da_fy1 = _driver_amount_for_year(da_selection, 1, fy1_revenue_val)
            capex_fy1 = _driver_amount_for_year(capex_selection, 1, fy1_revenue_val)
            nwc_fy1 = _driver_amount_for_year(nwc_selection, 1, fy1_revenue_val)
            tax_fy1 = _driver_ratio_for_year(tax_selection, 1, tax_rate_val)
            if (
                ebitda_fy1 is not None
                and da_fy1 is not None
                and capex_fy1 is not None
                and nwc_fy1 is not None
                and tax_fy1 is not None
            ):
                ebit_fy1 = ebitda_fy1 - da_fy1
                nopat_fy1 = (ebit_fy1 * (Decimal("1") - tax_fy1)).quantize(Decimal("1"), ROUND_HALF_UP)
                fcff_fy1 = (nopat_fy1 + da_fy1 - capex_fy1 - nwc_fy1).quantize(Decimal("1"), ROUND_HALF_UP)
                dcf_fcff_1y = FinancialMetric(
                    value=fcff_fy1,
                    unit=getattr(snapshot, "currency", "USD") or "USD",
                    period="FY1E",
                    source=f"DCF FY1E driver bridge: NOPAT ({nopat_fy1}) + D&A ({da_fy1}) - CapEx ({capex_fy1}) - ΔNWC ({nwc_fy1})",
                    source_type=SourceType.USER_OVERRIDE if has_driver_overrides_fcff else SourceType.DERIVED,
                    as_of=as_of,
                    confidence=min(
                        selection.confidence
                        for selection in (ebitda_margin_selection, da_selection, tax_selection, capex_selection, nwc_selection)
                        if selection is not None
                    ),
                    is_estimated=True,
                    notes="DCF Year 1 explicit full fiscal year forecast (not NTM rolling stub).",
                )
    if (
        getattr(snapshot, "forward_fcff_2y", None) is not None
        and snapshot.forward_fcff_2y.source_type == SourceType.ANALYST_ESTIMATE
        and not has_driver_overrides_fcff
        and _is_explicit_fy_metric(snapshot.forward_fcff_2y, 2, next_fy_end)
    ):
        dcf_fcff_2y = snapshot.forward_fcff_2y
        derived_fcff_2y = snapshot.forward_fcff_2y
    elif (
        fy2_revenue_is_explicit
        and fy2_rev.value > Decimal("0")
        and ebitda_margin is not None
        and fwd_rev_val
        and fwd_rev_val > Decimal("0")
        and da_val is not None
        and capex_val is not None
        and nwc_change_val is not None
    ):
        fy2_rev_val = fy2_rev.value
        ebitda_2y = _ebitda_amount_for_year(ebitda_margin_selection, 2, fy2_rev_val)
        da_2y = _driver_amount_for_year(da_selection, 2, fy2_rev_val)
        capex_2y = _driver_amount_for_year(capex_selection, 2, fy2_rev_val)
        nwc_2y = _driver_amount_for_year(nwc_selection, 2, fy2_rev_val)
        tax_2y = _driver_ratio_for_year(tax_selection, 2, tax_rate_val)
        if ebitda_2y is not None and da_2y is not None and capex_2y is not None and nwc_2y is not None and tax_2y is not None:
            ebit_2y = ebitda_2y - da_2y
            nopat_2y = (ebit_2y * (Decimal("1") - tax_2y)).quantize(Decimal("1"), ROUND_HALF_UP)
            fcff_2y_calc = (nopat_2y + da_2y - capex_2y - nwc_2y).quantize(Decimal("1"), ROUND_HALF_UP)
            dcf_fcff_2y = FinancialMetric(
                value=fcff_2y_calc,
                unit=getattr(snapshot, "currency", "USD") or "USD",
                period="FY2E",
                source=f"DCF FY2E driver projection: NOPAT ({nopat_2y}) + D&A ({da_2y}) - CapEx ({capex_2y}) - ΔNWC ({nwc_2y})",
                source_type=SourceType.USER_OVERRIDE if has_driver_overrides_fcff else SourceType.DERIVED,
                as_of=as_of,
                confidence=min(
                    selection.confidence
                    for selection in (ebitda_margin_selection, da_selection, tax_selection, capex_selection, nwc_selection)
                    if selection is not None
                ),
                is_estimated=True,
                notes="DCF Year 2 explicit full fiscal year forecast.",
            )
            derived_fcff_2y = dcf_fcff_2y

    # Resolve Interest and After-Tax Interest
    interest_val: Optional[Decimal] = None
    interest_source: Optional[str] = None
    interest_as_of: Any = getattr(snapshot, "cash_flow_as_of", None) or getattr(snapshot, "income_statement_as_of", None) or as_of
    interest_period_str: str = "TTM"
    if getattr(snapshot, "interest_ttm", None) is not None:
        interest_val = snapshot.interest_ttm.value
        interest_source = "derived_historical"
        interest_as_of = snapshot.interest_ttm.as_of
        interest_period_str = snapshot.interest_ttm.period
    after_tax_interest = (interest_val * (Decimal("1") - tax_rate_val)).quantize(Decimal("1"), ROUND_HALF_UP) if interest_val is not None else None

    # Resolve forward Net Borrowing.  The historical TTM field is deliberately
    # not a fallback: it remains available on the snapshot for display/audit,
    # but cannot enter the forward FCFE bridge.
    net_borrowing_val: Decimal = ZERO
    net_borrowing_source: str = "normalized_zero_missing_forward"
    net_borrowing_source_type: Optional[str] = None
    net_borrowing_as_of: Any = as_of
    net_borrowing_period_str: str = "forward_unavailable"
    forward_borrowing_metric: Optional[FinancialMetric] = None
    forward_borrowing_status = "missing_normalized_zero"
    forward_borrowing_warnings: list[str] = []
    # A user-provided debt-flow override is already an explicit request-scoped
    # input.  Do not let an ignored provider candidate create a misleading
    # period-mismatch warning beside the authoritative override.
    if getattr(assumptions, "driver_net_borrowing", None) is not None:
        normalized_forward_borrowing, forward_borrowing_error = None, None
    else:
        normalized_forward_borrowing, forward_borrowing_status, forward_borrowing_error = _resolve_forward_borrowing_metric(
            snapshot,
            horizon,
            as_of,
            next_fy_end,
            w0,
            w1,
        )
    if forward_borrowing_error:
        forward_borrowing_warnings.append(forward_borrowing_error)

    if getattr(assumptions, "driver_net_borrowing", None) is not None:
        net_borrowing_val = assumptions.driver_net_borrowing
        net_borrowing_source = "user_override"
        net_borrowing_source_type = SourceType.USER_OVERRIDE.value
        net_borrowing_as_of = as_of
        net_borrowing_period_str = "forward_user_override"
        forward_borrowing_status = "user_override"
    elif normalized_forward_borrowing is not None:
        forward_borrowing_metric = normalized_forward_borrowing
        net_borrowing_val = normalized_forward_borrowing.value
        net_borrowing_source = "provider_forward"
        net_borrowing_source_type = getattr(normalized_forward_borrowing.source_type, "value", str(normalized_forward_borrowing.source_type))
        net_borrowing_as_of = normalized_forward_borrowing.as_of
        net_borrowing_period_str = normalized_forward_borrowing.period
        forward_borrowing_status = "provider_forward"
    else:
        # This zero is a normalization decision, not an observed cash-flow
        # fact.  Preserve the historical metric separately in the bridge and
        # emit a warning so downstream quality/risk displays stay honest.
        historical_borrowing = getattr(snapshot, "net_borrowing_ttm", None)
        history_label = historical_borrowing.period if historical_borrowing is not None else "TTM"
        forward_borrowing_warnings.append(
            "No explicit forward net borrowing is available; normalized forward borrowing to 0. "
            f"Historical net_borrowing_ttm ({history_label}) is display-only and was not used in forward FCFE."
        )

    # FCFE = FCFF - After-Tax Interest + Net Borrowing
    raw_forward_fcfe = getattr(snapshot, "forward_fcf_1y", None) or getattr(snapshot, "forward_fcfe_1y", None)
    is_fcfe_consensus = (
        raw_forward_fcfe is not None
        and getattr(raw_forward_fcfe, "source_type", None) == SourceType.ANALYST_ESTIMATE
    )

    has_driver_overrides_fcfe = has_driver_overrides_fcff or getattr(assumptions, "driver_net_borrowing", None) is not None

    derived_fcfe_1y: Optional[FinancialMetric] = None
    if is_fcfe_consensus and not has_driver_overrides_fcfe:
        derived_fcfe_1y = raw_forward_fcfe
    elif derived_fcff_1y is not None and after_tax_interest is not None and net_borrowing_val is not None:
        fcfe_calc = (derived_fcff_1y.value - after_tax_interest + net_borrowing_val).quantize(Decimal("1"), ROUND_HALF_UP)
        borrowing_note = " ".join(forward_borrowing_warnings)
        derived_fcfe_1y = FinancialMetric(
            value=fcfe_calc,
            unit=getattr(snapshot, "currency", "USD") or "USD",
            period=target_metric_period,
            source=f"Financial driver bridge: FCFF ({derived_fcff_1y.value}) - Interest*(1-T) ({after_tax_interest}) + NetBorrowing ({net_borrowing_val})",
            source_type=SourceType.USER_OVERRIDE if has_driver_overrides_fcfe else SourceType.DERIVED,
            as_of=as_of,
            confidence=0.8,
            is_estimated=True,
            notes=(
                "FCFE derived from FCFF with debt cash flow adjustment. "
                + borrowing_note
                if borrowing_note else "FCFE derived from FCFF with debt cash flow adjustment."
            ),
        )

    # A direct analyst FCFE estimate remains authoritative, but still carries
    # the borrowing-evidence warning when no explicit forward debt-flow input
    # exists.  This prevents the response from implying that historical TTM
    # borrowing reconciled the direct estimate.
    if (
        derived_fcfe_1y is not None
        and is_fcfe_consensus
        and forward_borrowing_warnings
        and not has_driver_overrides_fcfe
    ):
        prior_notes = derived_fcfe_1y.notes or ""
        derived_fcfe_1y = derived_fcfe_1y.model_copy(update={
            "notes": (prior_notes + " " if prior_notes else "") + " ".join(forward_borrowing_warnings)
        })

    # FCFE's reconciliation is deliberately separate from FCFF's.  Net
    # borrowing is an equity cash-flow adjustment and must never enter FCFF.
    bridge_fcfe: Optional[Decimal] = None
    if bridge_fcff is not None and after_tax_interest is not None:
        bridge_fcfe = (bridge_fcff - after_tax_interest + net_borrowing_val).quantize(Decimal("1"), ROUND_HALF_UP)

    projection_warnings = list(dict.fromkeys([*driver_warnings, *forward_borrowing_warnings]))

    # Build comprehensive financial bridge report payload
    financial_bridge_dict: Optional[dict[str, Any]] = None
    if fwd_rev_val is not None and derived_ebitda is not None:
        val_as_of = as_of
        fy1_start, fy1_end = _fiscal_year_bounds(fy1_rev, 1, next_fy_end)
        fy2_start, fy2_end = _fiscal_year_bounds(fy2_rev, 2, next_fy_end)
        if horizon == "current_fy" and fy1_start is not None and fy1_end is not None:
            forecast_start, forecast_end = fy1_start, fy1_end
        elif horizon == "next_fy" and fy2_start is not None and fy2_end is not None:
            forecast_start, forecast_end = fy2_start, fy2_end
        elif horizon == "current_fy" and next_fy_end is not None:
            forecast_end = next_fy_end
            forecast_start = _safe_add_years(forecast_end, -1) + timedelta(days=1)
        elif horizon == "next_fy" and next_fy_end is not None:
            forecast_start = next_fy_end + timedelta(days=1)
            forecast_end = _safe_add_years(next_fy_end, 1)
        else:
            forecast_start = val_as_of
            forecast_end = _safe_add_years(val_as_of, 1)

        # Check each accounting identity independently.  ``None`` means the
        # evidence needed for that identity was not available; it is never
        # reported as a successful reconciliation.
        ebitda_identity: Optional[bool] = None
        if ebitda_margin is not None and fwd_rev_val is not None and derived_ebitda is not None:
            ebitda_identity = derived_ebitda.value == (fwd_rev_val * ebitda_margin).quantize(Decimal("1"), ROUND_HALF_UP)
        ebit_identity: Optional[bool] = None
        if derived_ebitda is not None and da_val is not None and ebit_val is not None:
            ebit_identity = ebit_val == derived_ebitda.value - da_val
        nopat_identity: Optional[bool] = None
        if ebit_val is not None and nopat_val is not None:
            nopat_identity = nopat_val == (ebit_val * (Decimal("1") - tax_rate_val)).quantize(Decimal("1"), ROUND_HALF_UP)
        fcff_identity: Optional[bool] = None
        if bridge_fcff is not None and derived_fcff_1y is not None:
            fcff_identity = derived_fcff_1y.value == bridge_fcff
        fcfe_identity: Optional[bool] = None
        if bridge_fcfe is not None and derived_fcfe_1y is not None:
            fcfe_identity = derived_fcfe_1y.value == bridge_fcfe

        identity_checks: dict[str, Optional[bool]] = {
            "ebitda": ebitda_identity,
            "ebit": ebit_identity,
            "nopat": nopat_identity,
            "fcff": fcff_identity,
            "fcfe": fcfe_identity,
        }
        known_checks = [value for value in identity_checks.values() if value is not None]
        if any(value is False for value in known_checks):
            identity_holds: Optional[bool] = False
        elif len(known_checks) == len(identity_checks) and all(known_checks):
            identity_holds = True
        else:
            # Partial evidence is not a successful reconciliation.  Keep the
            # unknown state explicit so API/export/UI consumers cannot mistake
            # a single passing identity for five passing identities.
            identity_holds = None

        reconciliation_difference: Optional[str] = None
        fcfe_reconciliation_difference: Optional[str] = None
        reconciliation_messages: list[str] = []
        if is_fcff_consensus:
            if bridge_fcff is not None and derived_fcff_1y is not None:
                reconciliation_difference = str(derived_fcff_1y.value - bridge_fcff)
                if fcff_identity is False:
                    reconciliation_messages.append(
                        f"Direct analyst consensus FCFF ({derived_fcff_1y.value}) differs from operational driver bridge ({bridge_fcff}) by {derived_fcff_1y.value - bridge_fcff} USD; valuation uses consensus."
                    )
            else:
                reconciliation_messages.append(
                    "FCFF consensus was supplied, but the driver bridge is incomplete; FCFF identity cannot be verified."
                )
        if is_fcfe_consensus:
            if bridge_fcfe is not None and derived_fcfe_1y is not None:
                fcfe_reconciliation_difference = str(derived_fcfe_1y.value - bridge_fcfe)
                if fcfe_identity is False:
                    reconciliation_messages.append(
                        f"Direct analyst consensus FCFE ({derived_fcfe_1y.value}) differs from FCFF - after-tax interest + net borrowing ({bridge_fcfe}) by {derived_fcfe_1y.value - bridge_fcfe} USD; valuation uses consensus."
                    )
            else:
                reconciliation_messages.append(
                    "FCFE consensus was supplied, but FCFF, interest, or net borrowing evidence is incomplete; FCFE identity cannot be verified."
                )
        if identity_holds is None and not reconciliation_messages:
            reconciliation_messages.append("Accounting identities cannot be fully verified because one or more driver inputs are unavailable.")
        if projection_warnings:
            reconciliation_messages.extend(projection_warnings)
        reconciliation_note = " ".join(reconciliation_messages) or None

        dcf_forecasts: list[dict[str, Any]] = []
        # A partial FY1/FY2 projection is not a production DCF input.  Keep
        # FCFF bridge calculations available for FCFE reconciliation, but do
        # not expose a partial ``dcf_forecasts`` payload that looks eligible
        # for DCF valuation.
        dcf_projection_complete = all(
            metric is not None and metric.value.is_finite() and metric.value > ZERO
            for metric in (dcf_fcff_1y, dcf_fcff_2y)
        )
        if dcf_projection_complete:
            for year, metric, start_date, end_date in (
                (1, dcf_fcff_1y, fy1_start, fy1_end),
                (2, dcf_fcff_2y, fy2_start, fy2_end),
            ):
                dcf_forecasts.append({
                    "year": year,
                    "value": str(metric.value),
                    "period": metric.period,
                    "as_of": metric.as_of.isoformat(),
                    "source": metric.source,
                    "source_type": metric.source_type,
                    "start_date": start_date.isoformat() if start_date is not None else None,
                    "end_date": end_date.isoformat() if end_date is not None else None,
                })

        def _driver_metadata(
            key: str,
            *,
            fallback_source: str,
            fallback_as_of: Any,
            fallback_period: Any,
            description: str,
        ) -> dict[str, Any]:
            selection = driver_selections.get(key)
            metric = selection.metric if selection is not None else None
            selected_as_of = selection.as_of if selection is not None else fallback_as_of
            selected_source = (
                metric.source
                if metric is not None
                else (
                    "request override"
                    if selection is not None and selection.source == "user_override"
                    else (
                        "configured statutory tax default"
                        if selection is not None and selection.source == "statutory_default"
                        else None
                    )
                )
            )
            selected_source_type = _metric_source_type_value(metric) or None
            if selection is not None and selection.source == "user_override":
                selected_source_type = SourceType.USER_OVERRIDE.value
            elif selection is not None and selection.source == "statutory_default":
                selected_source_type = SourceType.CONFIGURED_FALLBACK.value
            elif selection is not None and selection.source in {"historical_multiperiod", "historical_ttm_ratio"}:
                selected_source_type = SourceType.DERIVED.value
            return {
                "type": selection.source if selection is not None else fallback_source,
                "source": selected_source,
                "source_type": selected_source_type,
                "as_of": str(selected_as_of.isoformat() if hasattr(selected_as_of, "isoformat") else selected_as_of),
                "period": str(selection.period if selection is not None else fallback_period),
                "confidence": selection.confidence if selection is not None else None,
                "is_estimated": selection.is_estimated if selection is not None else True,
                "kind": selection.kind if selection is not None else None,
                "lineage": selection.notes if selection is not None else None,
                "warnings": list(selection.warnings) if selection is not None else [],
                "description": description,
            }

        financial_bridge_dict = {
            "period": effective_horizon,
            "forecast_start_date": forecast_start.isoformat(),
            "forecast_end_date": forecast_end.isoformat(),
            "as_of": val_as_of.isoformat(),
            "currency": getattr(snapshot, "currency", "USD") or "USD",
            "revenue": str(fwd_rev_val),
            "ebitda_margin": str(ebitda_margin) if ebitda_margin is not None else None,
            "ebitda": str(derived_ebitda.value),
            "da": str(da_val) if da_val is not None else None,
            "ebit": str(ebit_val) if ebit_val is not None else None,
            "tax_rate": str(tax_rate_val),
            "nopat": str(nopat_val) if nopat_val is not None else None,
            "capex": str(capex_val) if capex_val is not None else None,
            "nwc_change": str(nwc_change_val) if nwc_change_val is not None else None,
            "fcff": str(derived_fcff_1y.value) if derived_fcff_1y is not None else None,
            "bridge_fcff": str(bridge_fcff) if bridge_fcff is not None else None,
            "bridge_fcfe": str(bridge_fcfe) if bridge_fcfe is not None else None,
            "identity_holds": identity_holds,
            "identity_checks": identity_checks,
            "ebitda_identity_holds": ebitda_identity,
            "ebit_identity_holds": ebit_identity,
            "nopat_identity_holds": nopat_identity,
            "fcff_identity_holds": fcff_identity,
            "fcfe_identity_holds": fcfe_identity,
            "reconciliation_difference": reconciliation_difference,
            "fcfe_reconciliation_difference": fcfe_reconciliation_difference,
            "reconciliation_note": reconciliation_note,
            "interest": str(interest_val) if interest_val is not None else None,
            "after_tax_interest": str(after_tax_interest) if after_tax_interest is not None else None,
            # ``net_borrowing`` is retained as a compatibility alias for the
            # value used by the FCFE identity, but the explicit names below
            # make its forward-only semantics unambiguous.
            "net_borrowing": str(net_borrowing_val),
            "forward_net_borrowing": str(net_borrowing_val),
            "forward_net_borrowing_status": forward_borrowing_status,
            "forward_net_borrowing_source": net_borrowing_source,
            "forward_net_borrowing_source_type": net_borrowing_source_type,
            "forward_net_borrowing_period": str(net_borrowing_period_str),
            "forward_net_borrowing_as_of": str(net_borrowing_as_of.isoformat() if hasattr(net_borrowing_as_of, "isoformat") else net_borrowing_as_of),
            "forward_net_borrowing_unit": getattr(snapshot, "currency", "USD") or "USD",
            "forward_net_borrowing_is_estimated": (
                True if forward_borrowing_metric is None or forward_borrowing_metric.is_estimated else False
            ),
            "forward_net_borrowing_confidence": (
                str(forward_borrowing_metric.confidence) if forward_borrowing_metric is not None else None
            ),
            "forward_net_borrowing_warnings": list(forward_borrowing_warnings),
            "warnings": projection_warnings,
            "driver_warnings": list(driver_warnings),
            "historical_net_borrowing": (
                str(getattr(snapshot, "net_borrowing_ttm", None).value)
                if getattr(snapshot, "net_borrowing_ttm", None) is not None else None
            ),
            "historical_net_borrowing_period": (
                str(getattr(snapshot, "net_borrowing_ttm", None).period)
                if getattr(snapshot, "net_borrowing_ttm", None) is not None else None
            ),
            "historical_net_borrowing_as_of": (
                str(getattr(snapshot, "net_borrowing_ttm", None).as_of.isoformat())
                if getattr(snapshot, "net_borrowing_ttm", None) is not None else None
            ),
            "fcfe": str(derived_fcfe_1y.value) if derived_fcfe_1y is not None else None,
            "dcf_forecasts": dcf_forecasts,
            "restrictions_note": (
                "Financial bridge isolates operating business cash flows from non-operating items. "
                "Operating EBITDA is defined as Operating Income + D&A to isolate core operations "
                "from non-operating investment gains/losses (e.g. securities sales). "
                "Excludes stock-based compensation (SBC), operating lease capitalizations, "
                "and non-operating investment gains/losses from operating free cash flows."
            ),
            "drivers_source": {
                "ebitda_margin": _driver_metadata(
                    "ebitda_margin",
                    fallback_source=ebitda_margin_source,
                    fallback_as_of=ebitda_margin_as_of,
                    fallback_period=ebitda_margin_period,
                    description=f"EBITDA margin: {ebitda_margin:.2%}" if ebitda_margin is not None else "N/A",
                ),
                "da": _driver_metadata(
                    "da",
                    fallback_source=da_source or "unavailable",
                    fallback_as_of=da_as_of,
                    fallback_period=da_period_str,
                    description=f"D&A: {da_val} USD" if da_val is not None else "N/A",
                ),
                "tax_rate": _driver_metadata(
                    "tax_rate",
                    fallback_source=tax_source,
                    fallback_as_of=tax_as_of,
                    fallback_period=tax_period_str,
                    description=f"Effective tax rate: {tax_rate_val:.2%}",
                ),
                "capex": _driver_metadata(
                    "capex",
                    fallback_source=capex_source or "unavailable",
                    fallback_as_of=capex_as_of,
                    fallback_period=capex_period_str,
                    description=f"CapEx: {capex_val} USD" if capex_val is not None else "N/A",
                ),
                "nwc_change": _driver_metadata(
                    "nwc_change",
                    fallback_source=nwc_source or "unavailable",
                    fallback_as_of=nwc_as_of,
                    fallback_period=nwc_period_str,
                    description=f"ΔNWC investment: {nwc_change_val} USD (cash outflow when positive)" if nwc_change_val is not None else "N/A",
                ),
                "net_borrowing": {
                    "type": net_borrowing_source,
                    "source_type": net_borrowing_source_type,
                    "as_of": str(net_borrowing_as_of.isoformat() if hasattr(net_borrowing_as_of, "isoformat") else net_borrowing_as_of),
                    "period": str(net_borrowing_period_str),
                    "description": (
                        f"Forward net debt issuance: {net_borrowing_val} USD"
                        if forward_borrowing_status in {"provider_forward", "user_override"}
                        else "Forward net borrowing unavailable; normalized to 0. Historical TTM value is display-only."
                    ),
                    "warnings": list(forward_borrowing_warnings),
                },
            },
        }

    return RequestProjections(
        effective_horizon=effective_horizon,
        horizon_weight_fy1=w0,
        horizon_weight_fy2=w1,
        forward_eps=blended_eps,
        forward_revenue=blended_rev,
        forward_ebitda=derived_ebitda,
        forward_fcfe_1y=derived_fcfe_1y,
        forward_fcff_1y=derived_fcff_1y,
        forward_fcff_2y=derived_fcff_2y,
        effective_growth_floor=growth_floor,
        effective_growth_cap=growth_cap,
        fallback_warning=fallback_warning,
        financial_bridge=financial_bridge_dict,
        dcf_fcff_1y=dcf_fcff_1y,
        dcf_fcff_2y=dcf_fcff_2y,
        forward_net_borrowing=forward_borrowing_metric,
        forward_net_borrowing_status=forward_borrowing_status,
        warnings=tuple(projection_warnings),
    )

