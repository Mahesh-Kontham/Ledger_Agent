"""Duplicate, cross-verification and mandatory-field checks (PRD Section 9.1, 9.3, 9.4)."""
from __future__ import annotations

from datetime import date
from typing import Optional

from core import config, db, merchants
from core.models import Bill, MatchResult


def indian_number(x: float, decimals: int = 2) -> str:
    """1234567.5 -> '12,34,567.50' (Indian digit grouping)."""
    neg = x < 0
    s = f"{abs(x):.{decimals}f}"
    whole, _, frac = s.partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return ("-" if neg else "") + whole + (f".{frac}" if frac else "")


def fmt_inr(x: Optional[float]) -> str:
    if x is None:
        return "₹—"
    x = round(float(x), 2)
    return f"₹{indian_number(x, 0)}" if x == int(x) else f"₹{indian_number(x, 2)}"


def tolerance(total_inr: float) -> float:
    return max(config.TOLERANCE_ABS_INR, config.TOLERANCE_PCT * total_inr)


# ---------------- 9.1 duplicate ----------------
def check_duplicate(bill: Bill) -> Optional[int]:
    """Return id of the original bill this one duplicates, else None."""
    clauses, params = [], []
    if bill.file_hash:
        clauses.append("file_hash = ?")
        params.append(bill.file_hash)
    if bill.merchant_normalized and bill.invoice_number:
        clauses.append("(merchant_normalized = ? AND invoice_number = ?)")
        params += [bill.merchant_normalized, bill.invoice_number]
    if bill.merchant_normalized and bill.total_amount is not None and bill.bill_date:
        clauses.append("(merchant_normalized = ? AND total_amount = ? AND bill_date = ?)")
        params += [bill.merchant_normalized, bill.total_amount, bill.bill_date]
    if not clauses:
        return None
    return db.find_duplicate_id(clauses, params, bill.id)


# ---------------- 9.3 cross-verification ----------------
def _days_apart(a: str, b: str) -> int:
    return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)


def cross_verify(bill: Bill) -> MatchResult:
    result = MatchResult(match_status="NO_MATCH")
    if bill.bill_date and bill.total_amount_inr is not None:
        candidates = [t for t in db.list_transactions(unmatched_debits_only=True)
                      if _days_apart(t.txn_date, bill.bill_date) <= config.MATCH_DATE_WINDOW_DAYS]
        key = merchants.match_key(bill.merchant_raw, bill.merchant_normalized)
        preferred = [t for t in candidates if key and key in t.description.lower()]
        # PRD Section 19: a debit whose description does NOT name the merchant is only accepted when the
        # amount itself matches (within tolerance). Otherwise an unrelated debit nearby would be paired,
        # flagged as an "unexplained gap", and the bill would never reach the ledger or the budget.
        pool = preferred or [t for t in candidates
                             if abs(t.amount_inr - bill.total_amount_inr) <= tolerance(bill.total_amount_inr)]
        if pool:
            base = bill.total_amount_inr
            txn = min(pool, key=lambda t: (abs(t.amount_inr - base), t.id))
            variance = round(txn.amount_inr - base, 2)
            result = classify_variance(bill, variance)
            result.transaction = txn
            result.variance_inr = variance

    # 6. user-recalled amount (informational only)
    if bill.user_entered_amount is not None and bill.total_amount is not None:
        tol = tolerance(bill.total_amount_inr if bill.total_amount_inr is not None else bill.total_amount)
        if abs(bill.user_entered_amount - bill.total_amount) > tol:
            bank = (f"bank debited {fmt_inr(result.transaction.amount_inr)}" if result.transaction
                    else "no bank debit found")
            result.info_note = (f"You entered {fmt_inr(bill.user_entered_amount)}; invoice shows "
                                f"{fmt_inr(bill.total_amount)}; {bank}")
    return result


def classify_variance(bill: Bill, variance: float) -> MatchResult:
    base = bill.total_amount_inr
    if abs(variance) <= tolerance(base):
        return MatchResult("MATCHED")
    fees = bill.fee_items or []
    if fees and abs(sum(f["amount"] for f in fees) - variance) <= 0.01:
        return MatchResult("VARIANCE_EXPLAINED",
                           variance_reason="Fee on bill: " + ", ".join(f["description"] for f in fees))
    if bill.currency and bill.currency != config.BASE_CURRENCY and 0 < variance <= config.FOREX_MARKUP_MAX_PCT * base:
        return MatchResult("VARIANCE_EXPLAINED", variance_reason="Forex markup")
    if bill.payment_mode == "CARD" and 0 < variance <= max(config.CARD_FEE_MAX_ABS_INR, config.CARD_FEE_MAX_PCT * base):
        return MatchResult("VARIANCE_EXPLAINED", variance_reason="Probable card fee - confirm")
    return MatchResult("VARIANCE_UNEXPLAINED", variance_reason=f"Unexplained gap of {fmt_inr(abs(variance))}")


# ---------------- 9.4 mandatory fields ----------------
def check_mandatory(bill: Bill, mode: str) -> list[str]:
    missing = [f for f in config.MANDATORY_FIELDS[mode] if bill.field_value(f) is None]
    if bill.total_amount is not None and bill.currency is None:
        missing.append("currency")      # needed to convert to INR - never assumed
    return missing
