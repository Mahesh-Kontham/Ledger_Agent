"""Status decision (PRD Section 9.5) - first rule that applies wins."""
from __future__ import annotations

from core import config
from core.models import Bill
from core.verify import fmt_inr


def _fraud_text(bill: Bill) -> str:
    sig = "; ".join(bill.fraud_signals or [])
    return f"Fraud risk {bill.fraud_score}%" + (f": {sig}" if sig else "")


def _match_text(bill: Bill) -> str | None:
    if bill.match_status in (None, "NO_MATCH"):
        return None
    txt = f"Bank/card debit txn #{bill.matched_transaction_id} (variance {fmt_inr(bill.variance_inr)})"
    if bill.match_status == "MATCHED":
        return "Matched bank/card debit" + txt[len("Bank/card debit"):]
    if bill.match_status == "VARIANCE_EXPLAINED":
        return f"Variance explained: {bill.variance_reason} — {txt}"
    return None


def decide(bill: Bill, mode: str) -> tuple[str, list[str], str | None]:
    """-> (status, reasons, review_priority)."""
    score = bill.fraud_score or 0
    notes = [f"Note: {bill.info_note}"] if bill.info_note else []
    low = ([f"Low-confidence fields nulled: {', '.join(bill.low_confidence_fields)}"]
           if bill.low_confidence_fields else [])

    if bill.duplicate_of is not None:
        return "DUPLICATE", [f"Duplicate of bill #{bill.duplicate_of}"], None
    if bill.missing_fields:
        head = ["Extraction failed"] if bill.extraction_error else []
        return "MISSING_DATA", head + [f"Missing: {', '.join(bill.missing_fields)}"] + low + notes, "NORMAL"
    if bill.total_amount_inr is None:   # currency not in sample FX table
        return ("MISSING_DATA", [f"Missing: fx_rate (currency {bill.currency} not in sample FX table)"] + notes,
                "NORMAL")

    match = [m for m in [_match_text(bill)] if m]
    t = config.FRAUD[mode]
    if mode == "INDIVIDUAL" and score >= t["review"]:
        return "NEEDS_REVIEW", [_fraud_text(bill)] + match + notes, "HIGH"
    if mode == "BUSINESS" and score >= t["high"]:
        return "NEEDS_REVIEW", [_fraud_text(bill)] + match + notes, "HIGH"
    if mode == "BUSINESS" and score >= t["review"]:
        return "NEEDS_REVIEW", [_fraud_text(bill)] + match + notes, "NORMAL"
    if bill.match_status == "VARIANCE_UNEXPLAINED":
        return ("NEEDS_REVIEW", [f"{bill.variance_reason} vs bank/card debit txn #{bill.matched_transaction_id}"]
                + notes, "NORMAL")
    if mode == "BUSINESS" and bill.match_status == "NO_MATCH":
        return "NEEDS_REVIEW", ["No bank/card debit found"] + notes, "NORMAL"

    reasons = match[:] or []
    if mode == "INDIVIDUAL" and t["warn"] <= score < t["review"]:
        reasons.append(f"Fraud risk warning ({score}%)")
    if mode == "INDIVIDUAL" and bill.match_status == "NO_MATCH":
        reasons.append("Single source - not bank-verified")
    if not reasons:
        reasons.append("All checks passed")
    return "VERIFIED", reasons + notes, None


def decide_status(bill: Bill, mode: str) -> tuple[str, list[str]]:
    status, reasons, _ = decide(bill, mode)
    return status, reasons
