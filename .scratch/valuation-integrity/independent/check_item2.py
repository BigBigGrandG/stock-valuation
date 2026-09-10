"""
Independent check for Item 2: Share Reconciliation & Conflict Handling
"""
from datetime import date, datetime
from decimal import Decimal
import sys

sys.path.insert(0, "backend")

from app.providers.share_reconciliation import reconcile_share_capital
from app.engines.dcf import run_dcf
from app.engines.ev_ebitda import run_ev_ebitda
from app.engines.fcf_yield import run_fcf_yield
from app.engines.forward_pe import run_forward_pe
from app.models.domain import (
    CompanyFinancialSnapshot,
    FinancialMetric,
    SourceType,
    ValuationAssumptions,
)

print("=== CHECK ITEM 2: SHARE RECONCILIATION ===")

# Test 2.1: Severe conflict degradation behavior
info_conflict = {
    "sharesOutstanding": 1_000_000_000,
    "marketCap": 200_000_000_000,
    "currentPrice": 100.0,  # Implies 2B shares vs 1B reported -> 50% conflict
}
res_recon = reconcile_share_capital(info_conflict, ticker="CONFLICT_CO")
print(f"Test 2.1a (Reconciliation result on severe conflict):")
print(f"   basis: {res_recon.basis}")
print(f"   shares: {res_recon.shares}")
assert res_recon.basis == "CONFLICT_DEGRADED", "Severe divergence must trigger CONFLICT_DEGRADED"

def _m(val, unit="USD"):
    return FinancialMetric(
        value=Decimal(str(val)),
        unit=unit,
        period="TTM",
        source="test",
        source_type=SourceType.DERIVED,
        as_of=date(2026, 9, 10),
        confidence=1.0,
        is_estimated=False,
    )

snap_conflict = CompanyFinancialSnapshot(
    ticker="CONFLICT_CO",
    company_name="Conflict Corp",
    currency="USD",
    current_price=_m("100.00"),
    price_timestamp=datetime(2026, 9, 10, 12, 0, 0),
    diluted_shares=_m(str(res_recon.shares), unit="shares"),
    shares_basis=res_recon.basis,
    cash=_m("10000000000"),
    total_debt=_m("10000000000"),
    net_debt=_m("0"),
    revenue_ttm=_m("50000000000"),
    ebitda_ttm=_m("20000000000"),
    forward_ebitda_1y=_m("22000000000"),
    fcf_ttm=_m("10000000000"),
    forward_fcf_1y=_m("11000000000"),
    fcff_ttm=_m("10000000000"),
    forward_fcff_1y=_m("11000000000"),
    forward_eps_1y=_m("5.00"),
    statement_basis="TTM",
    annual_fallback=False,
)

assumptions = ValuationAssumptions()
dcf_out = run_dcf(snap_conflict, assumptions)
ev_out = run_ev_ebitda(snap_conflict, assumptions)
fcf_out = run_fcf_yield(snap_conflict, assumptions)
pe_out = run_forward_pe(snap_conflict, assumptions)

print(f"Test 2.1b (Engine execution under CONFLICT_DEGRADED shares):")
print(f"   DCF available: {dcf_out.available}")
print(f"   EV/EBITDA available: {ev_out.available}")
print(f"   FCF Yield available: {fcf_out.available}")
print(f"   Forward P/E available: {pe_out.available}")
assert not dcf_out.available, "DCF must fail closed on CONFLICT_DEGRADED"
assert not ev_out.available, "EV/EBITDA must fail closed on CONFLICT_DEGRADED"
assert not fcf_out.available, "FCF Yield must fail closed on CONFLICT_DEGRADED"
assert pe_out.available, "Forward P/E should remain available as per-share flow"

# Test 2.2: Refusing to fabricate shares from marketCap / price
info_no_shares = {
    "marketCap": 100_000_000_000,
    "currentPrice": 50.0,
}
fabricated = False
try:
    reconcile_share_capital(info_no_shares, ticker="NO_SHARES_CO")
    fabricated = True
except ValueError as exc:
    print(f"Test 2.2 (Refusal to fabricate shares from marketCap/price):")
    print(f"   Successfully rejected share fabrication: {exc}")
    assert "Synthesizing shares from marketCap/price is prohibited" in str(exc)

assert not fabricated, "Reconciliation must refuse to fabricate synthetic shares from marketCap/price"

# Test 2.3: Checking recorded source period and multi-class reconciliation
info_meta = {
    "sharesOutstanding": 2_205_128_509,
    "impliedSharesOutstanding": 2_547_506_225,
    "marketCap": 1_300_000_000_000,
    "currentPrice": 510.0,
}
res_meta = reconcile_share_capital(info_meta, default_as_of=date(2026, 9, 10), ticker="META")
print(f"Test 2.3 (Metadata on reconciled META shares):")
print(f"   as_of: {res_meta.as_of}")
print(f"   period: {res_meta.period}")
print(f"   basis: {res_meta.basis}")
assert res_meta.basis == "ALL_CLASS_RECONCILED", "META multi-class shares must reconcile to ALL_CLASS_RECONCILED"
assert res_meta.shares == Decimal("2547506225")
assert res_meta.as_of == date(2026, 9, 10)

print("ALL ITEM 2 CHECKS AND ASSERTIONS PASSED!")
