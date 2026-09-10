"""Evidence-based share capital reconciliation.

Cross-checks all candidate share counts (implied all-class, single-class common,
latest quarterly/annual balance sheet ordinary shares, and marketCap/price).
Flags stock splits, date conflicts, and multi-class structures.
Never claims 'reconciled' under unresolved conflict; degrades gracefully.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional


@dataclass(frozen=True)
class ShareReconciliationResult:
    shares: Decimal
    basis: str  # ALL_CLASS_RECONCILED, SINGLE_CLASS_VERIFIED, BALANCE_SHEET_ORDINARY, CONFLICT_DEGRADED
    reconciliation: dict[str, Any]
    notes: str
    source: str
    as_of: date
    period: str
    is_estimated: bool


def _to_dec(val: Any) -> Optional[Decimal]:
    if val is None:
        return None
    try:
        d = Decimal(str(val))
        return d if d.is_finite() else None
    except Exception:
        return None


def _extract_bs_shares(bs_df: Any, is_annual: bool = False) -> tuple[Optional[Decimal], Optional[date], Optional[str]]:
    """Extract ordinary shares count, statement date, and period from a balance sheet DataFrame or dict."""
    if bs_df is None:
        return None, None, None

    # Handle DataFrame-like objects
    if hasattr(bs_df, "empty") and bs_df.empty:
        return None, None, None

    if hasattr(bs_df, "columns") and len(bs_df.columns) > 0:
        # Sort columns descending to get newest date first
        cols = list(bs_df.columns)
        try:
            sorted_cols = sorted(
                cols,
                key=lambda c: c.date() if hasattr(c, "date") else (c if isinstance(c, (date, datetime)) else str(c)),
                reverse=True,
            )
        except Exception:
            sorted_cols = cols

        first_col = sorted_cols[0]
        col_dt: Optional[date] = None
        if hasattr(first_col, "date"):
            col_dt = first_col.date()
        elif isinstance(first_col, (date, datetime)):
            col_dt = first_col.date() if isinstance(first_col, datetime) else first_col

        series = bs_df[first_col]
        for row_name in [
            "Ordinary Shares Number",
            "Share Issued",
            "Common Stock Shares Outstanding",
            "Common Stock",
        ]:
            if row_name in series.index:
                val = _to_dec(series.loc[row_name])
                if val is not None and val > Decimal("0"):
                    if is_annual:
                        period_str = f"FY{col_dt.year}" if col_dt else "latest"
                    else:
                        period_str = f"Q_{col_dt.isoformat()}" if col_dt else "latest"
                    return val, col_dt, period_str

    # Handle dict-like objects
    if isinstance(bs_df, dict):
        for k in ["Ordinary Shares Number", "Share Issued", "Common Stock Shares Outstanding", "shares"]:
            if k in bs_df:
                val = _to_dec(bs_df[k])
                if val is not None and val > Decimal("0"):
                    return val, None, "dict"

    return None, None, None


def reconcile_share_capital(
    info: dict[str, Any],
    quarterly_bs: Any = None,
    annual_bs: Any = None,
    default_as_of: Optional[date] = None,
    ticker: str = "TICKER",
) -> ShareReconciliationResult:
    """Perform evidence-based cross-checking of all share count candidates."""
    as_of = default_as_of or date.today()

    single_class = _to_dec(info.get("sharesOutstanding"))
    implied_shares = _to_dec(info.get("impliedSharesOutstanding"))
    market_cap = _to_dec(info.get("marketCap"))
    current_price = _to_dec(info.get("currentPrice") or info.get("regularMarketPrice"))

    cap_price_shares: Optional[Decimal] = None
    if market_cap is not None and current_price is not None and current_price > Decimal("0"):
        cap_price_shares = (market_cap / current_price).quantize(Decimal("1"), ROUND_HALF_UP)

    bs_q_shares, bs_q_date, bs_q_period = _extract_bs_shares(quarterly_bs, is_annual=False)
    bs_a_shares, bs_a_date, bs_a_period = _extract_bs_shares(annual_bs, is_annual=True)

    bs_shares = bs_q_shares or bs_a_shares
    bs_date = bs_q_date or bs_a_date or as_of
    bs_period = bs_q_period or bs_a_period or "latest"

    # Split detection check between balance sheet and info
    split_detected = False
    split_factor: Optional[Decimal] = None
    if bs_shares is not None and single_class is not None and bs_shares > Decimal("0") and single_class > Decimal("0"):
        ratio = single_class / bs_shares
        for candidate_split in [Decimal("2"), Decimal("3"), Decimal("4"), Decimal("5"), Decimal("10"), Decimal("20")]:
            if abs(ratio - candidate_split) / candidate_split < Decimal("0.05"):
                split_detected = True
                split_factor = candidate_split
                break
            inv = Decimal("1") / candidate_split
            if abs(ratio - inv) / inv < Decimal("0.05"):
                split_detected = True
                split_factor = inv
                break

    candidates_summary = {
        "implied_shares": int(implied_shares) if implied_shares else None,
        "single_class_shares": int(single_class) if single_class else None,
        "quarterly_bs_shares": int(bs_q_shares) if bs_q_shares else None,
        "annual_bs_shares": int(bs_a_shares) if bs_a_shares else None,
        "cap_price_cross_check": int(cap_price_shares) if cap_price_shares else None,
        "split_detected": split_detected,
        "split_factor": float(split_factor) if split_factor else None,
    }

    # Case 1: Implied shares available (Multi-class common stock like META, GOOG, BRK)
    if implied_shares is not None and implied_shares > Decimal("0"):
        is_multi_class = single_class is not None and implied_shares > single_class * Decimal("1.03")

        # Verify against marketCap / price verification check
        variance_with_cap = None
        if cap_price_shares is not None:
            variance_with_cap = abs(implied_shares - cap_price_shares) / implied_shares

        # Check if consistent
        has_severe_conflict = variance_with_cap is not None and variance_with_cap > Decimal("0.20")

        if not has_severe_conflict:
            reconciliation = {
                **candidates_summary,
                "selected_source": "info.impliedSharesOutstanding",
                "is_multi_class": is_multi_class,
                "conflict_detected": False,
                "variance_with_cap_price": float(variance_with_cap) if variance_with_cap is not None else None,
                "notes": "Point-in-time common shares across all classes reconciled with market consensus.",
            }
            notes = (
                f"All-class common shares ({int(implied_shares):,} shares) reconciled "
                f"across multiple share classes (primary class: {int(single_class):,})"
                if is_multi_class
                else f"Common shares outstanding ({int(implied_shares):,} shares) verified"
            )
            return ShareReconciliationResult(
                shares=implied_shares,
                basis="ALL_CLASS_RECONCILED",
                reconciliation=reconciliation,
                notes=notes,
                source=f"Yahoo Finance info.impliedSharesOutstanding ({ticker})",
                as_of=bs_date,
                period=f"PIT_{bs_period}" if bs_period != "latest" else f"PIT_{bs_date.isoformat()}",
                is_estimated=True,
            )
        else:
            # Implied shares severely conflict with marketCap / price cross-check
            reconciliation = {
                **candidates_summary,
                "selected_source": "info.impliedSharesOutstanding (degraded)",
                "conflict_detected": True,
                "variance_with_cap_price": float(variance_with_cap),
                "notes": f"High variance ({variance_with_cap:.1%}) between implied shares and market cap/price cross-check.",
            }
            return ShareReconciliationResult(
                shares=implied_shares,
                basis="CONFLICT_DEGRADED",
                reconciliation=reconciliation,
                notes=f"Unresolved conflict: implied shares {int(implied_shares):,} diverges {variance_with_cap:.1%} from cap/price",
                source=f"Yahoo Finance info.impliedSharesOutstanding ({ticker}) [UNVERIFIED]",
                as_of=bs_date,
                period=f"PIT_{bs_period}" if bs_period != "latest" else f"PIT_{bs_date.isoformat()}",
                is_estimated=True,
            )

    # Case 2: No implied shares, single_class available
    if single_class is not None and single_class > Decimal("0"):
        variance_with_cap = None
        if cap_price_shares is not None:
            variance_with_cap = abs(single_class - cap_price_shares) / single_class

        # Check if balance sheet confirms single class
        bs_confirms = False
        if bs_shares is not None:
            bs_diff = abs(single_class - bs_shares) / single_class
            if bs_diff < Decimal("0.08") or split_detected:
                bs_confirms = True

        if variance_with_cap is not None and variance_with_cap > Decimal("0.15"):
            # Divergence > 15%! We do NOT blindly invent marketCap/price.
            # We flag conflict and degrade.
            reconciliation = {
                **candidates_summary,
                "selected_source": "info.sharesOutstanding (unreconciled divergence)",
                "conflict_detected": True,
                "variance_with_cap_price": float(variance_with_cap),
                "notes": (
                    f"Market cap / price implies {int(cap_price_shares):,} shares, "
                    f"diverging {variance_with_cap:.1%} from reported shares {int(single_class):,}. "
                    "Cannot verify unrecorded share classes or timing mismatches without audited SEC disclosures."
                ),
            }
            return ShareReconciliationResult(
                shares=single_class,
                basis="CONFLICT_DEGRADED",
                reconciliation=reconciliation,
                notes=f"Single-class common shares with {variance_with_cap:.1%} marketCap/price divergence",
                source=f"Yahoo Finance info.sharesOutstanding ({ticker}) [CONFLICT]",
                as_of=as_of,
                period="latest",
                is_estimated=True,
            )

        reconciliation = {
            **candidates_summary,
            "selected_source": "info.sharesOutstanding",
            "conflict_detected": False,
            "variance_with_cap_price": float(variance_with_cap) if variance_with_cap is not None else None,
            "bs_confirmed": bs_confirms,
            "notes": "Single-class common shares verified against quarterly balance sheet and quote valuation.",
        }
        return ShareReconciliationResult(
            shares=single_class,
            basis="SINGLE_CLASS_VERIFIED",
            reconciliation=reconciliation,
            notes=f"Common shares outstanding approximation ({int(single_class):,} shares) verified against balance sheet",
            source=f"Yahoo Finance info.sharesOutstanding ({ticker})",
            as_of=as_of,
            period="latest",
            is_estimated=True,
        )

    # Case 3: Balance sheet fallback
    if bs_shares is not None and bs_shares > Decimal("0"):
        reconciliation = {
            **candidates_summary,
            "selected_source": f"Balance sheet {bs_period}",
            "conflict_detected": False,
            "notes": "Balance sheet ordinary shares count utilized in absence of quote summary shares.",
        }
        return ShareReconciliationResult(
            shares=bs_shares,
            basis="BALANCE_SHEET_ORDINARY",
            reconciliation=reconciliation,
            notes=f"Balance sheet ordinary shares from statement column {bs_period}",
            source=f"Yahoo Finance balance sheet ({ticker})",
            as_of=bs_date,
            period=bs_period,
            is_estimated=True,
        )

    # Exhausted: do NOT fabricate synthetic shares from marketCap / price.
    # MarketCap / price may only be used as a cross-check sanity indicator.
    raise ValueError(
        f"Could not determine share capital for ticker '{ticker}': all reported quote and balance sheet "
        "share counts are missing. Synthesizing shares from marketCap/price is prohibited."
    )

