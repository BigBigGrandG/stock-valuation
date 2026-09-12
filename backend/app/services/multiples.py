"""Auditable company/industry multiple selection.

The live provider cannot reconstruct historical forward multiples from the
current Yahoo Finance quote summary.  This module therefore treats company
history as an optional *archived* input with strict contemporaneous evidence,
and uses a versioned public industry snapshot only when its provenance and
currency/period metadata are complete.  A missing or invalid candidate falls
back independently for each metric to the configured system assumption.

Industry snapshot provenance (retrieved 2026-09-12; data used as of Jan 2026):
  * Forward P/E: https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/pedata.html
  * EV/EBITDA: https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/vebitda.htm

The EV/EBITDA page reports observed industry aggregates (all firms), not a
company-specific forward forecast.  Scenario low/high values are an explicit
configured +/-10% spread and are never described as percentiles.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from typing import Any, Mapping, Optional

from app.models.domain import CompanyFinancialSnapshot, ScenarioValues, SourceType, ValuationAssumptions


INDUSTRY_DATA_AS_OF = date(2026, 1, 1)
INDUSTRY_DATA_RETRIEVED_AT = date(2026, 9, 12)
INDUSTRY_MAX_AGE_DAYS = 548
INDUSTRY_MIN_SAMPLE_SIZE = 10
COMPANY_HISTORY_MIN_SAMPLES = 3
COMPANY_HISTORY_MAX_SAMPLES = 5
COMPANY_HISTORY_MIN_COVERAGE_DAYS = 3 * 365
COMPANY_HISTORY_MAX_COVERAGE_DAYS = 5 * 366
COMPANY_HISTORY_MAX_LOOKBACK_DAYS = 5 * 366
COMPANY_HISTORY_MAX_LATEST_AGE_DAYS = 730
MULTIPLE_SCENARIO_SPREAD = Decimal("0.10")
MULTIPLE_PRECISION = Decimal("0.0001")
RATIO_TOLERANCE = Decimal("0.02")

PE_SOURCE_URL = "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/pedata.html"
EV_EBITDA_SOURCE_URL = "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/vebitda.htm"


@dataclass(frozen=True)
class IndustryBenchmark:
    name: str
    sample_size: int
    forward_pe: Optional[Decimal]
    ev_ebitda: Optional[Decimal]
    # The Damodaran EV/EBITDA table is an observed all-firms aggregate.  It is
    # intentionally marked incompatible with the forward operating-EBITDA
    # target used by this engine unless a provider supplies a separately
    # evidenced compatible basis.
    pe_basis: str = "forward_consensus_eps"
    pe_forecast_type: str = "forward"
    ev_ebitda_basis: str = "observed_all_firms_ebitda"
    ev_forecast_type: str = "observed"
    ev_denominator_scope: str = "all_firms"


# Values are copied from the January 2026 US industry tables cited above.  A
# small, explicit snapshot keeps request latency bounded and is straightforward
# to update when the upstream table changes; it is not a ticker allow-list.
INDUSTRY_BENCHMARKS: dict[str, IndustryBenchmark] = {
    "aerospace/defense": IndustryBenchmark("Aerospace/Defense", 79, Decimal("45.87"), Decimal("33.42")),
    "auto & truck": IndustryBenchmark("Auto & Truck", 33, Decimal("49.04"), Decimal("51.85")),
    "beverage (soft)": IndustryBenchmark("Beverage (Soft)", 27, Decimal("23.70"), Decimal("18.24")),
    "biotechnology": IndustryBenchmark("Drugs (Biotechnology)", 496, Decimal("63.76"), Decimal("51.49")),
    "computers/peripherals": IndustryBenchmark("Computers/Peripherals", 36, Decimal("36.15"), Decimal("26.18")),
    "entertainment": IndustryBenchmark("Entertainment", 92, Decimal("42.73"), Decimal("24.39")),
    "food processing": IndustryBenchmark("Food Processing", 78, Decimal("17.23"), Decimal("9.63")),
    "machinery": IndustryBenchmark("Machinery", 105, Decimal("24.06"), Decimal("17.46")),
    "pharmaceuticals": IndustryBenchmark("Drugs (Pharmaceutical)", 228, Decimal("24.19"), Decimal("18.58")),
    "retail (general)": IndustryBenchmark("Retail (General)", 23, Decimal("23.97"), Decimal("20.87")),
    "semiconductor": IndustryBenchmark("Semiconductor", 66, Decimal("37.29"), Decimal("42.70")),
    "semiconductor equip": IndustryBenchmark("Semiconductor Equip", 31, Decimal("41.58"), Decimal("26.18")),
    "software (entertainment)": IndustryBenchmark("Software (Entertainment)", 77, Decimal("18.52"), Decimal("26.16")),
    "software (internet)": IndustryBenchmark("Software (Internet)", 29, Decimal("64.81"), Decimal("100.45")),
    "software (system & application)": IndustryBenchmark("Software (System & Application)", 309, Decimal("34.13"), Decimal("31.75")),
}


def _normalise_label(value: Any) -> str:
    text = " ".join(str(value or "").strip().lower().split())
    return text.replace("–", "-").replace("—", "-")


# Only a direct singular/plural label normalization is retained here.  A
# descriptive label from a different upstream taxonomy is not evidence that
# it is economically comparable to a named Damodaran row; such labels must
# degrade until a source-backed mapping policy is added.
INDUSTRY_ALIASES: dict[str, str] = {
    "semiconductors": "semiconductor",
}


def lookup_industry_benchmark(sector: Any, industry: Any) -> Optional[IndustryBenchmark]:
    """Map an exact upstream industry/sector label to a public snapshot row.

    The mapping is deliberately exact after whitespace/case normalisation.
    Broad labels such as ``Software`` or ``Technology`` do not select an
    arbitrary row by substring; they must degrade to the configured fallback.
    """

    industry_key = _normalise_label(industry)
    sector_key = _normalise_label(sector)
    for key in (industry_key, sector_key):
        if not key:
            continue
        canonical = INDUSTRY_ALIASES.get(key)
        if canonical is None and key in INDUSTRY_BENCHMARKS:
            canonical = key
        if canonical in INDUSTRY_BENCHMARKS:
            return INDUSTRY_BENCHMARKS[canonical]
    return None


def industry_multiple_payload(sector: Any, industry: Any, *, as_of: Optional[date] = None) -> dict[str, Any]:
    """Return raw provider fields for the mapped industry benchmark."""

    benchmark = lookup_industry_benchmark(sector, industry)
    category_as_of = as_of or INDUSTRY_DATA_RETRIEVED_AT
    industry_key = _normalise_label(industry)
    sector_key = _normalise_label(sector)
    mapping_key = industry_key if industry_key in INDUSTRY_ALIASES or industry_key in INDUSTRY_BENCHMARKS else sector_key
    payload: dict[str, Any] = {
        "industry_name": benchmark.name if benchmark else None,
        "industry_forward_pe": benchmark.forward_pe if benchmark else None,
        "industry_ev_ebitda": benchmark.ev_ebitda if benchmark else None,
        "industry_sample_size": benchmark.sample_size if benchmark else None,
        "industry_as_of": INDUSTRY_DATA_AS_OF if benchmark else None,
        "industry_period": "January 2026 US industry aggregate" if benchmark else None,
        "industry_currency": "USD" if benchmark else None,
        "industry_forward_pe_currency": "USD" if benchmark else None,
        "industry_ev_ebitda_currency": "USD" if benchmark else None,
        "industry_forward_pe_unit": "multiple" if benchmark else None,
        "industry_ev_ebitda_unit": "multiple" if benchmark else None,
        "industry_forward_pe_basis": benchmark.pe_basis if benchmark else None,
        "industry_forward_pe_forecast_type": benchmark.pe_forecast_type if benchmark else None,
        "industry_ev_ebitda_basis": benchmark.ev_ebitda_basis if benchmark else None,
        "industry_ev_ebitda_forecast_type": benchmark.ev_forecast_type if benchmark else None,
        "industry_ev_ebitda_denominator_scope": benchmark.ev_denominator_scope if benchmark else None,
        "industry_mapping_key": mapping_key if benchmark else None,
        "industry_mapping_source": (
            "Yahoo Finance profile industry/sector exact label mapped to the named NYU Stern/Damodaran row"
            if benchmark
            else None
        ),
        "industry_forward_pe_source": "Aswath Damodaran / NYU Stern US Industry PE (Forward PE)" if benchmark else None,
        "industry_forward_pe_source_url": PE_SOURCE_URL if benchmark else None,
        "industry_ev_ebitda_source": "Aswath Damodaran / NYU Stern US Industry EV/EBITDA (all firms)" if benchmark else None,
        "industry_ev_ebitda_source_url": EV_EBITDA_SOURCE_URL if benchmark else None,
        "industry_is_estimated": True if benchmark else None,
        "industry_notes": (
            "Forward PE is the cited industry forward-PE aggregate; EV/EBITDA is the cited all-firms observed aggregate. "
            "The observed all-firms EV/EBITDA denominator is not a forward operating-EBITDA target and is rejected unless "
            "a compatible basis is explicitly evidenced. Scenario low/high use a configured +/-10% spread, not a percentile."
            if benchmark
            else None
        ),
        "as_of": category_as_of,
    }
    if benchmark is None:
        payload["industry_unavailable_reason"] = (
            f"No public snapshot row mapped from upstream sector={sector!r}, industry={industry!r}"
        )
    return payload


def _decimal(value: Any) -> Optional[Decimal]:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return parsed if parsed.is_finite() else None


def _date(value: Any) -> Optional[date]:
    if isinstance(value, date):
        return value
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _median(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / Decimal("2")


def _scenario_values(base: Decimal) -> ScenarioValues:
    return ScenarioValues(
        low=(base * (Decimal("1") - MULTIPLE_SCENARIO_SPREAD)).quantize(MULTIPLE_PRECISION, ROUND_HALF_UP),
        base=base.quantize(MULTIPLE_PRECISION, ROUND_HALF_UP),
        high=(base * (Decimal("1") + MULTIPLE_SCENARIO_SPREAD)).quantize(MULTIPLE_PRECISION, ROUND_HALF_UP),
    )


def _valid_ratio(value: Decimal, numerator: Decimal, denominator: Decimal) -> bool:
    if numerator <= 0 or denominator <= 0:
        return False
    expected = numerator / denominator
    return abs(value - expected) / expected <= RATIO_TOLERANCE


def _compact_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _is_per_share_unit(value: Any) -> bool:
    unit = _compact_text(value)
    return unit in {
        "per_share",
        "share",
        "shares",
        "usd_share",
        "usd_per_share",
        "usd_ads",
        "ads",
        "per_ads",
    } or ("share" in unit or "ads" in unit) and "usd" in unit


def _is_total_value_unit(value: Any) -> bool:
    unit = _compact_text(value)
    return unit in {
        "total",
        "currency",
        "usd",
        "usd_total",
        "usd_currency",
        "currency_total",
        "enterprise_value",
        "ebitda",
    } or ("total" in unit and "share" not in unit)


def _compatible_currency(observation: Mapping[str, Any], keys: tuple[str, ...], expected: Optional[str]) -> tuple[bool, str]:
    provided = [str(observation.get(key) or "").strip().upper() for key in keys]
    if any(not currency for currency in provided):
        return False, "currency evidence is missing"
    currencies = set(provided)
    if len(currencies) != 1:
        return False, f"currency evidence is inconsistent ({sorted(currencies)})"
    currency = next(iter(currencies))
    if expected and currency != expected.upper():
        return False, f"currency {currency} does not match valuation currency {expected.upper()}"
    return True, currency


def _compatible_pe_basis(observation: Mapping[str, Any]) -> tuple[bool, str]:
    price_basis = _compact_text(observation.get("price_basis") or observation.get("share_basis"))
    eps_basis = _compact_text(observation.get("forward_eps_basis") or observation.get("eps_basis"))
    if not price_basis or not eps_basis:
        return False, "price/EPS per-share basis evidence is missing"
    if not ("share" in price_basis or "ads" in price_basis):
        return False, f"price basis {price_basis} is not per-share"
    if not ("share" in eps_basis or "ads" in eps_basis):
        return False, f"forward EPS basis {eps_basis} is not per-share"
    if ("ads" in price_basis) != ("ads" in eps_basis):
        return False, "price and forward EPS depositary-share basis is inconsistent"
    return True, f"price_basis={price_basis}; forward_eps_basis={eps_basis}"


def _compatible_ev_basis(observation: Mapping[str, Any]) -> tuple[bool, str]:
    enterprise_basis = _compact_text(
        observation.get("enterprise_value_basis") or observation.get("ev_basis")
    )
    ebitda_basis = _compact_text(
        observation.get("forward_ebitda_basis") or observation.get("ebitda_basis")
    )
    forecast_type = _compact_text(
        observation.get("forward_ebitda_forecast_type")
        or observation.get("ebitda_forecast_type")
        or observation.get("forecast_ebitda_type")
    )
    if not enterprise_basis or not ebitda_basis or not forecast_type:
        return False, "enterprise value/forward EBITDA accounting-basis evidence is missing"
    if "enterprise" not in enterprise_basis and enterprise_basis not in {"ev", "ev_total"}:
        return False, f"enterprise value basis {enterprise_basis} is incompatible"
    if "ebitda" not in ebitda_basis or "operating" not in ebitda_basis:
        return False, f"forward EBITDA basis {ebitda_basis} is not operating EBITDA"
    if "forward" not in forecast_type or any(term in forecast_type for term in ("observed", "trailing", "historical")):
        return False, f"forward EBITDA forecast type {forecast_type} is not forward"
    return True, (
        f"enterprise_value_basis={enterprise_basis}; forward_ebitda_basis={ebitda_basis}; "
        f"forecast_type={forecast_type}"
    )


def _company_history_median(
    observations: Any,
    *,
    metric: str,
    valuation_date: date,
    expected_currency: Optional[str] = None,
) -> tuple[Optional[Decimal], dict[str, Any], str]:
    """Validate archived forward observations and return a robust median.

    Every accepted row is a point-in-time record: the forecast vintage must be
    dated on or before the observed quote date, the target fiscal period must
    end after that date, and both the quote and forecast evidence must carry
    explicit source, currency, unit and accounting-basis metadata.  Rows are
    deduplicated by observation date, then at most five evenly-spaced rows are
    retained across the full three-to-five-year window.  Median/MAD filtering
    happens before the final count, age and coverage checks; a zero MAD keeps
    all retained rows because no robust outlier threshold can be inferred.
    """

    if not isinstance(observations, list):
        return None, {}, "company history is missing or not a list"
    valid_by_date: dict[date, tuple[date, Decimal, Mapping[str, Any]]] = {}
    valid_row_count = 0
    rejected: list[str] = []
    for index, observation in enumerate(observations):
        if not isinstance(observation, Mapping):
            rejected.append(f"row {index} is not an object")
            continue
        observed_at = _date(observation.get("as_of"))
        source = str(observation.get("source") or "").strip()
        source_url = str(observation.get("source_url") or "").strip()
        forecast_source = str(observation.get("forecast_source") or "").strip()
        forecast_source_url = str(
            observation.get("forecast_source_url") or observation.get("forecast_url") or ""
        ).strip()
        period = str(observation.get("forecast_period") or observation.get("period") or "").strip()
        period_end = _date(
            observation.get("forecast_period_end")
            or observation.get("target_period_end")
            or observation.get("forecast_end")
        )
        vintage_as_of = _date(
            observation.get("forecast_vintage_as_of")
            or observation.get("forecast_as_of")
            or observation.get("estimate_as_of")
        )
        value = _decimal(observation.get("value"))
        if observed_at is None:
            rejected.append(f"row {index} has invalid as_of")
            continue
        if observed_at > valuation_date:
            rejected.append(f"row {index} is dated after valuation date")
            continue
        if (valuation_date - observed_at).days > COMPANY_HISTORY_MAX_LOOKBACK_DAYS:
            rejected.append(f"row {index} is outside the five-year lookback")
            continue
        if not source or not source_url.startswith("https://"):
            rejected.append(f"row {index} lacks a verifiable source URL")
            continue
        if not forecast_source or not forecast_source_url.startswith("https://"):
            rejected.append(f"row {index} lacks a verifiable forecast source URL")
            continue
        if not period or "FY" not in period.upper() or "TTM" in period.upper() or "HISTORICAL" in period.upper():
            rejected.append(f"row {index} is not a forward fiscal-year observation")
            continue
        if observation.get("is_forward") is not True:
            rejected.append(f"row {index} lacks explicit forward=true evidence")
            continue
        if vintage_as_of is None:
            rejected.append(f"row {index} lacks forecast vintage date")
            continue
        if vintage_as_of > observed_at:
            rejected.append(f"row {index} forecast vintage is after observation date")
            continue
        if period_end is None:
            rejected.append(f"row {index} lacks target fiscal period end")
            continue
        if period_end <= observed_at:
            rejected.append(f"row {index} target fiscal period is not forward at observation date")
            continue
        if value is None or value <= 0:
            rejected.append(f"row {index} has a non-positive/non-finite multiple")
            continue

        if metric == "pe":
            price = _decimal(observation.get("price"))
            price_as_of = _date(observation.get("price_as_of"))
            forward_eps = _decimal(observation.get("forward_eps"))
            if price is None or price <= 0 or forward_eps is None or forward_eps <= 0 or price_as_of != observed_at:
                rejected.append(f"row {index} lacks contemporaneous price/forward-EPS evidence")
                continue
            currencies_ok, currency_detail = _compatible_currency(
                observation,
                ("price_currency", "forward_eps_currency"),
                expected_currency,
            )
            if not currencies_ok:
                rejected.append(f"row {index} P/E {currency_detail}")
                continue
            if not _is_per_share_unit(observation.get("price_unit")) or not _is_per_share_unit(
                observation.get("forward_eps_unit")
            ):
                rejected.append(f"row {index} P/E per-share unit evidence is missing/incompatible")
                continue
            basis_ok, basis_detail = _compatible_pe_basis(observation)
            if not basis_ok:
                rejected.append(f"row {index} P/E {basis_detail}")
                continue
            if not _valid_ratio(value, price, forward_eps):
                rejected.append(f"row {index} P/E does not match contemporaneous price / forward EPS")
                continue
        else:
            enterprise_value = _decimal(observation.get("enterprise_value"))
            ev_as_of = _date(observation.get("enterprise_value_as_of"))
            forward_ebitda = _decimal(observation.get("forward_ebitda"))
            if (
                enterprise_value is None
                or enterprise_value <= 0
                or forward_ebitda is None
                or forward_ebitda <= 0
                or ev_as_of != observed_at
            ):
                rejected.append(f"row {index} lacks contemporaneous EV/forward-EBITDA evidence")
                continue
            currencies_ok, currency_detail = _compatible_currency(
                observation,
                ("enterprise_value_currency", "forward_ebitda_currency"),
                expected_currency,
            )
            if not currencies_ok:
                rejected.append(f"row {index} EV/EBITDA {currency_detail}")
                continue
            if not _is_total_value_unit(observation.get("enterprise_value_unit")) or not _is_total_value_unit(
                observation.get("forward_ebitda_unit")
            ):
                rejected.append(f"row {index} EV/EBITDA total-value unit evidence is missing/incompatible")
                continue
            basis_ok, basis_detail = _compatible_ev_basis(observation)
            if not basis_ok:
                rejected.append(f"row {index} EV/EBITDA {basis_detail}")
                continue
            if not _valid_ratio(value, enterprise_value, forward_ebitda):
                rejected.append(f"row {index} EV/EBITDA does not match contemporaneous EV / forward EBITDA")
                continue
        valid_row_count += 1
        candidate = (observed_at, value, observation)
        existing = valid_by_date.get(observed_at)
        if existing is None:
            valid_by_date[observed_at] = candidate
        else:
            # Repeated dates count once. Prefer the row with the latest
            # point-in-time forecast vintage, then a stable source URL tie
            # break so selection is deterministic across provider orderings.
            existing_vintage = _date(
                existing[2].get("forecast_vintage_as_of")
                or existing[2].get("forecast_as_of")
                or existing[2].get("estimate_as_of")
            )
            new_rank = (
                vintage_as_of or date.min,
                forecast_source_url,
                source_url,
            )
            old_rank = (
                existing_vintage or date.min,
                str(existing[2].get("forecast_source_url") or existing[2].get("forecast_url") or ""),
                str(existing[2].get("source_url") or ""),
            )
            if new_rank > old_rank:
                valid_by_date[observed_at] = candidate

    valid = sorted(valid_by_date.values(), key=lambda item: item[0])
    if not valid:
        reason = "no valid contemporaneous company observations"
        if rejected:
            reason += "; " + "; ".join(rejected[:3])
        return None, {}, reason
    if len(valid) < COMPANY_HISTORY_MIN_SAMPLES:
        return None, {}, f"only {len(valid)} unique valid observations; at least {COMPANY_HISTORY_MIN_SAMPLES} are required"

    if len(valid) <= COMPANY_HISTORY_MAX_SAMPLES:
        selected = valid
    else:
        # Keep the endpoints and evenly-spaced interior observations.  This
        # makes dense monthly/quarterly histories retain the full window
        # rather than collapsing to five adjacent latest rows.
        max_index = len(valid) - 1
        indexes = sorted({(slot * max_index) // (COMPANY_HISTORY_MAX_SAMPLES - 1) for slot in range(COMPANY_HISTORY_MAX_SAMPLES)})
        selected = [valid[index] for index in indexes]

    values = [item[1] for item in selected]
    center = _median(values)
    deviations = [abs(value - center) for value in values]
    mad = _median(deviations)
    if mad > 0:
        filtered_entries = [
            item for item in selected if abs(item[1] - center) <= mad * Decimal("3")
        ]
    else:
        # Identical medians are not evidence of an outlier; retain the full
        # sample so three equal observations remain a valid history.
        filtered_entries = selected
    if len(filtered_entries) < COMPANY_HISTORY_MIN_SAMPLES:
        return None, {}, "outlier filtering left fewer than three observations"

    filtered_entries.sort(key=lambda item: item[0])
    first_date, last_date = filtered_entries[0][0], filtered_entries[-1][0]
    coverage_days = (last_date - first_date).days
    if coverage_days < COMPANY_HISTORY_MIN_COVERAGE_DAYS:
        return None, {}, (
            f"post-filter observations cover {coverage_days} days; at least "
            f"{COMPANY_HISTORY_MIN_COVERAGE_DAYS} days (three years) are required"
        )
    if coverage_days > COMPANY_HISTORY_MAX_COVERAGE_DAYS:
        return None, {}, (
            f"post-filter observations cover {coverage_days} days; at most "
            f"{COMPANY_HISTORY_MAX_COVERAGE_DAYS} days (five years) are allowed"
        )
    if (valuation_date - last_date).days > COMPANY_HISTORY_MAX_LATEST_AGE_DAYS:
        return None, {}, f"latest valid observation is older than {COMPANY_HISTORY_MAX_LATEST_AGE_DAYS} days"

    filtered = [item[1] for item in filtered_entries]
    median = _median(filtered)
    metadata = {
        "sample_count": len(filtered_entries),
        "raw_sample_count": valid_row_count,
        "valid_unique_count": len(valid),
        "selected_count": len(selected),
        "deduplicated_count": valid_row_count - len(valid_by_date),
        "first_as_of": first_date,
        "last_as_of": last_date,
        "coverage_days": coverage_days,
        "source_urls": sorted({str(item[2].get("source_url")) for item in filtered_entries}),
        "forecast_source_urls": sorted({str(item[2].get("forecast_source_url") or item[2].get("forecast_url")) for item in filtered_entries}),
        "sources": sorted({str(item[2].get("source")) for item in filtered_entries}),
        "forecast_sources": sorted({str(item[2].get("forecast_source")) for item in filtered_entries}),
        "periods": [str(item[2].get("forecast_period") or item[2].get("period")) for item in filtered_entries],
        "period_ends": [
            str(
                item[2].get("forecast_period_end")
                or item[2].get("target_period_end")
                or item[2].get("forecast_end")
            )
            for item in filtered_entries
        ],
        "forecast_vintages": [
            str(
                item[2].get("forecast_vintage_as_of")
                or item[2].get("forecast_as_of")
                or item[2].get("estimate_as_of")
            )
            for item in filtered_entries
        ],
        "outliers_removed": len(selected) - len(filtered_entries),
        "zero_mad": mad == 0,
        "currency": str(
            filtered_entries[0][2].get("price_currency")
            or filtered_entries[0][2].get("enterprise_value_currency")
            or ""
        ).upper(),
        "units": sorted({
            str(
                item[2].get("price_unit")
                or item[2].get("enterprise_value_unit")
                or ""
            )
            for item in filtered_entries
        }),
        "basis": sorted({
            str(
                item[2].get("forward_eps_basis")
                or item[2].get("forward_ebitda_basis")
                or ""
            )
            for item in filtered_entries
        }),
    }
    detail = (
        f"{len(filtered_entries)} retained unique contemporaneous observations from {first_date} to {last_date}; "
        f"coverage_days={coverage_days}; outliers_removed={metadata['outliers_removed']}; "
        f"deduplicated={metadata['deduplicated_count']}; zero_mad={metadata['zero_mad']}"
    )
    if rejected:
        detail += f"; rejected={len(rejected)}"
    return median, metadata, detail


def _industry_metric(
    candidates: Mapping[str, Any],
    *,
    metric: str,
    valuation_date: date,
    expected_currency: Optional[str] = None,
) -> tuple[Optional[Decimal], dict[str, Any], str]:
    value_key = "industry_forward_pe" if metric == "pe" else "industry_ev_ebitda"
    source_key = "industry_forward_pe_source" if metric == "pe" else "industry_ev_ebitda_source"
    url_key = "industry_forward_pe_source_url" if metric == "pe" else "industry_ev_ebitda_source_url"
    currency_key = "industry_forward_pe_currency" if metric == "pe" else "industry_ev_ebitda_currency"
    unit_key = "industry_forward_pe_unit" if metric == "pe" else "industry_ev_ebitda_unit"
    basis_key = "industry_forward_pe_basis" if metric == "pe" else "industry_ev_ebitda_basis"
    forecast_type_key = (
        "industry_forward_pe_forecast_type"
        if metric == "pe"
        else "industry_ev_ebitda_forecast_type"
    )
    value = _decimal(candidates.get(value_key))
    source = str(candidates.get(source_key) or "").strip()
    source_url = str(candidates.get(url_key) or "").strip()
    industry_name = str(candidates.get("industry_name") or "").strip()
    sample_size = candidates.get("industry_sample_size")
    try:
        sample_int = int(sample_size)
    except (TypeError, ValueError):
        sample_int = 0
    as_of = _date(candidates.get("industry_as_of"))
    currency = str(
        candidates.get(currency_key) or candidates.get("industry_currency") or ""
    ).strip().upper()
    generic_currency = str(candidates.get("industry_currency") or "").strip().upper()
    unit = _compact_text(candidates.get(unit_key))
    basis = _compact_text(candidates.get(basis_key))
    forecast_type = _compact_text(candidates.get(forecast_type_key))
    period = str(candidates.get("industry_period") or "").strip()
    unavailable_reason = str(candidates.get("industry_unavailable_reason") or "").strip()
    if value is None or value <= 0:
        return None, {}, unavailable_reason or "industry benchmark is missing/non-positive"
    if not industry_name or sample_int < INDUSTRY_MIN_SAMPLE_SIZE:
        return None, {}, f"industry benchmark sample is missing or below {INDUSTRY_MIN_SAMPLE_SIZE} firms"
    if as_of is None:
        return None, {}, "industry benchmark is missing as_of"
    if as_of > valuation_date:
        return None, {}, "industry benchmark is dated after valuation date"
    if (valuation_date - as_of).days > INDUSTRY_MAX_AGE_DAYS:
        return None, {}, f"industry benchmark is older than {INDUSTRY_MAX_AGE_DAYS} days"
    if currency != "USD":
        return None, {}, f"industry benchmark currency must be USD, got {currency or 'unknown'}"
    if expected_currency and currency != expected_currency.upper():
        return None, {}, (
            f"industry benchmark currency {currency} does not match valuation "
            f"currency {expected_currency.upper()}"
        )
    if generic_currency and generic_currency != currency:
        return None, {}, "industry benchmark currency metadata is inconsistent"
    if not source or not source_url.startswith("https://") or not period:
        return None, {}, "industry benchmark lacks verifiable source/period metadata"
    if unit not in {"multiple", "ratio", "x"}:
        return None, {}, f"industry {metric} unit must identify a multiple, got {unit or 'unknown'}"
    if metric == "pe":
        if "forward" not in basis or not any(term in basis for term in ("eps", "earnings")):
            return None, {}, (
                "industry P/E basis must identify forward EPS/earnings; "
                f"got {basis or 'unknown'}"
            )
        if "forward" not in forecast_type or any(
            term in forecast_type for term in ("observed", "trailing", "historical")
        ):
            return None, {}, (
                "industry P/E forecast type must be forward; "
                f"got {forecast_type or 'unknown'}"
            )
    else:
        # Damodaran's all-firms observed EV/EBITDA row is useful context but
        # is not a forward operating-EBITDA target. Only an explicitly
        # evidenced compatible denominator may enter this engine.
        if "ebitda" not in basis or "operating" not in basis:
            return None, {}, (
                "industry EV/EBITDA denominator basis is incompatible with "
                f"forward operating EBITDA ({basis or 'unknown'})"
            )
        if "forward" not in forecast_type or any(
            term in forecast_type for term in ("observed", "trailing", "historical")
        ):
            return None, {}, (
                "industry EV/EBITDA forecast type is not forward operating EBITDA; "
                f"got {forecast_type or 'unknown'}"
            )
    metadata = {
        "industry_name": industry_name,
        "sample_size": sample_int,
        "as_of": as_of,
        "period": period,
        "currency": currency,
        "unit": unit,
        "basis": basis,
        "forecast_type": forecast_type,
        "denominator_scope": str(candidates.get("industry_ev_ebitda_denominator_scope") or "").strip(),
        "mapping_key": str(candidates.get("industry_mapping_key") or "").strip(),
        "mapping_source": str(candidates.get("industry_mapping_source") or "").strip(),
        "source": source,
        "source_url": source_url,
        "notes": str(candidates.get("industry_notes") or "").strip(),
        "is_estimated": bool(candidates.get("industry_is_estimated", True)),
    }
    return value, metadata, "valid versioned public industry snapshot"


def _source_label(layer: str, metric_name: str, base: Decimal, metadata: Mapping[str, Any], detail: str) -> str:
    if layer == "company_historical":
        urls = ", ".join(str(url) for url in metadata.get("source_urls", []))
        forecast_urls = ", ".join(str(url) for url in metadata.get("forecast_source_urls", []))
        periods = ", ".join(str(period) for period in metadata.get("periods", []))
        vintages = ", ".join(str(vintage) for vintage in metadata.get("forecast_vintages", []))
        period_ends = ", ".join(str(period_end) for period_end in metadata.get("period_ends", []))
        units = ", ".join(str(unit) for unit in metadata.get("units", []))
        bases = ", ".join(str(basis) for basis in metadata.get("basis", []))
        return (
            f"Company historical forward {metric_name} median={base.quantize(MULTIPLE_PRECISION)}x; "
            f"{detail}; basis={periods or 'forward FY estimates'}; period_ends={period_ends or 'unknown'}; "
            f"forecast_vintages={vintages or 'unknown'}; currency={metadata.get('currency') or 'unknown'}; "
            f"units={units or 'unknown'}; accounting_basis={bases or 'unknown'}; "
            f"price_source_urls={urls}; forecast_source_urls={forecast_urls}; "
            f"scenario spread=±{MULTIPLE_SCENARIO_SPREAD:.0%} configured (not percentile)."
        )
    if layer == "industry":
        return (
            f"Industry benchmark {metadata.get('industry_name')} {metric_name}={base.quantize(MULTIPLE_PRECISION)}x; "
            f"sample={metadata.get('sample_size')}; data_as_of={metadata.get('as_of')}; period={metadata.get('period')}; "
            f"unit={metadata.get('unit')}; basis={metadata.get('basis')}; forecast_type={metadata.get('forecast_type')}; "
            f"mapping={metadata.get('mapping_key') or 'exact upstream label'}; "
            f"source={metadata.get('source')}; source_url={metadata.get('source_url')}; "
            f"scenario spread=±{MULTIPLE_SCENARIO_SPREAD:.0%} configured (not percentile)."
        )
    return f"System fallback {metric_name}={base.quantize(MULTIPLE_PRECISION)}x; parameter specificity insufficient; {detail}."


def _select_one(
    snapshot: CompanyFinancialSnapshot,
    assumptions: ValuationAssumptions,
    *,
    metric: str,
) -> tuple[ScenarioValues, SourceType, str, str, Optional[str], dict[str, Any]]:
    if metric == "pe":
        field = "pe_target"
        source_field = "pe_source"
        label_field = "pe_source_label"
        history_key = "company_forward_pe_observations"
        industry_name = "P/E"
    else:
        field = "ev_ebitda_multiple"
        source_field = "ev_ebitda_source"
        label_field = "ev_ebitda_source_label"
        history_key = "company_ev_ebitda_observations"
        industry_name = "EV/EBITDA"

    current = getattr(assumptions, source_field)
    current_values = getattr(assumptions, field)
    if current == SourceType.USER_OVERRIDE:
        return current_values, current, getattr(assumptions, label_field), "user_override", None, {}

    candidates = getattr(snapshot, "multiple_candidates", {}) or {}
    valuation_date = snapshot.current_price.as_of
    expected_currency = str(snapshot.currency or "USD").strip().upper()
    company_base, company_meta, company_detail = _company_history_median(
        candidates.get(history_key),
        metric=metric,
        valuation_date=valuation_date,
        expected_currency=expected_currency,
    )
    if company_base is not None:
        return (
            _scenario_values(company_base),
            SourceType.DERIVED,
            _source_label("company_historical", industry_name, company_base, company_meta, company_detail),
            "company_historical",
            None,
            {
                "as_of": company_meta.get("last_as_of"),
                "sample_size": company_meta.get("sample_count"),
                "basis": ", ".join(str(period) for period in company_meta.get("periods", [])),
            },
        )

    industry_base, industry_meta, industry_detail = _industry_metric(
        candidates,
        metric=metric,
        valuation_date=valuation_date,
        expected_currency=expected_currency,
    )
    if industry_base is not None:
        reason = f"company history unavailable ({company_detail})"
        return (
            _scenario_values(industry_base),
            SourceType.DERIVED,
            _source_label("industry", industry_name, industry_base, industry_meta, industry_detail)
            + f"; {reason}.",
            "industry",
            None,
            {
                "as_of": industry_meta.get("as_of"),
                "sample_size": industry_meta.get("sample_size"),
                "basis": industry_meta.get("period"),
            },
        )

    fallback_reason = f"company history unavailable ({company_detail}); {industry_detail}"
    return (
        current_values,
        SourceType.CONFIGURED_FALLBACK,
        _source_label("system", industry_name, current_values.base, {}, fallback_reason),
        "system",
        f"{industry_name} parameter specificity insufficient; using configured system fallback: {fallback_reason}",
        {},
    )


def resolve_multiple_assumptions(
    snapshot: CompanyFinancialSnapshot,
    assumptions: ValuationAssumptions,
) -> tuple[ValuationAssumptions, list[str]]:
    """Resolve P/E and EV/EBITDA independently without mutating defaults."""

    updates: dict[str, Any] = {}
    warnings: list[str] = []
    for metric, field, source_field, label_field, layer_field in (
        ("pe", "pe_target", "pe_source", "pe_source_label", "pe_selection_layer"),
        ("ev_ebitda", "ev_ebitda_multiple", "ev_ebitda_source", "ev_ebitda_source_label", "ev_ebitda_selection_layer"),
    ):
        values, source, label, layer, warning, metadata = _select_one(snapshot, assumptions, metric=metric)
        updates[field] = values
        updates[source_field] = source
        updates[label_field] = label
        updates[layer_field] = layer
        prefix = "pe" if metric == "pe" else "ev_ebitda"
        updates[f"{prefix}_selection_as_of"] = metadata.get("as_of")
        updates[f"{prefix}_selection_sample_size"] = metadata.get("sample_size")
        updates[f"{prefix}_selection_basis"] = metadata.get("basis")
        if warning:
            warnings.append(warning)
    return assumptions.model_copy(update=updates), warnings
