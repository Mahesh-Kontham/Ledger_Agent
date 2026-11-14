"""process_bill: ingest -> extract -> normalize -> verify -> route -> post -> anomalies -> budgets.
Plus human review actions (PRD Section 9.6)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Callable, Optional

from core import anomalies, budgets, db, extract, fx, ledger, merchants, route, verify
from core.fraud import check_fraud
from core.models import Bill, ExtractedFields, RawBill


def build_bill(raw: RawBill, ext: ExtractedFields, mode: str) -> Bill:
    v = ext.values
    return Bill(
        source=raw.source, mode=mode, file_path=raw.file_path, file_hash=raw.file_hash,
        merchant_raw=v.get("merchant"), bill_date=v.get("bill_date"), invoice_number=v.get("invoice_number"),
        total_amount=v.get("total_amount"), tax_amount=v.get("tax_amount"), currency=v.get("currency"),
        payment_mode=v.get("payment_mode"), gstin=v.get("gstin"),
        user_entered_amount=raw.user_entered_amount, line_items=ext.line_items, fee_items=ext.fee_items,
        field_confidence=ext.confidence, low_confidence_fields=ext.low_confidence_fields,
        extraction_error=ext.error,
    )


def evaluate(bill: Bill) -> Bill:
    """normalize + fx + verify + route. Mutates and returns bill (not saved)."""
    bill.merchant_normalized, bill.category = merchants.normalize_merchant(bill.merchant_raw)
    bill.total_amount_inr, bill.fx_rate, bill.fx_rate_date, bill.fx_source = fx.to_inr(
        bill.total_amount, bill.currency, bill.bill_date)

    bill.duplicate_of = verify.check_duplicate(bill)
    fr = check_fraud(bill)
    bill.fraud_score, bill.fraud_signals, bill.fraud_is_mock = fr.score, fr.signals, fr.is_mock

    bill.matched_transaction_id = bill.match_status = bill.variance_inr = bill.variance_reason = None
    bill.info_note = None
    if bill.duplicate_of is None:
        m = verify.cross_verify(bill)
        bill.match_status, bill.variance_inr, bill.variance_reason = m.match_status, m.variance_inr, m.variance_reason
        bill.matched_transaction_id = m.transaction.id if m.transaction else None
        bill.info_note = m.info_note
        if m.transaction is not None:
            _, _, _, bill.fx_source = fx.to_inr(bill.total_amount, bill.currency, bill.bill_date, m.transaction)

    bill.missing_fields = verify.check_mandatory(bill, bill.mode)
    bill.status, bill.status_reasons, bill.review_priority = route.decide(bill, bill.mode)
    return bill


def finalize_verified(bill: Bill, today: Optional[date] = None) -> Bill:
    """Link txn, post balanced journal, run anomalies + budget checks. Bill must be VERIFIED and saved."""
    txn = ledger.usable_transaction(bill)
    if txn is None and bill.match_status in ("MATCHED", "VARIANCE_EXPLAINED", "VARIANCE_UNEXPLAINED"):
        # unexplained gap approved by a human, or txn taken meanwhile: post as unmatched
        bill.status_reasons.append("Posted without bank match (transaction not linked)")
        bill.matched_transaction_id, bill.match_status = None, "NO_MATCH"
        bill.variance_inr = bill.variance_reason = None
    if txn is not None:
        db.set_transaction_matched(txn.id, bill.id)
    ledger.post_to_ledger(bill)
    db.update_bill(bill)
    bill.new_alerts = anomalies.run_anomalies(bill) + budgets.run_budget_checks(
        bill.mode, today=today, categories=[bill.category])
    return bill


def process_bill(raw: RawBill, mode: Optional[str] = None,
                 extractor: Callable[[RawBill], ExtractedFields] = extract.extract_fields,
                 today: Optional[date] = None) -> Bill:
    mode = mode or db.get_mode()
    ext = extractor(raw)
    bill = evaluate(build_bill(raw, ext, mode))
    db.insert_bill(bill)
    if bill.status == "VERIFIED":
        finalize_verified(bill, today)
    return bill


# ---------------- human review ----------------
def approve_bill(bill_id: int, reviewer: str = "reviewer", today: Optional[date] = None) -> Bill:
    bill = db.get_bill(bill_id)
    if bill is None or bill.status != "NEEDS_REVIEW":
        raise ValueError("Only NEEDS_REVIEW bills can be approved")
    bill.status, bill.review_priority = "VERIFIED", None
    bill.reviewed_by, bill.reviewed_at = reviewer, datetime.now().isoformat(timespec="seconds")
    bill.status_reasons = [f"Approved by {reviewer}"] + bill.status_reasons
    db.update_bill(bill)
    return finalize_verified(bill, today)


def reject_bill(bill_id: int, reviewer: str = "reviewer") -> Bill:
    bill = db.get_bill(bill_id)
    if bill is None or bill.status not in ("NEEDS_REVIEW", "MISSING_DATA"):
        raise ValueError("Only queued bills can be rejected")
    bill.status, bill.review_priority = "REJECTED", None
    bill.reviewed_by, bill.reviewed_at = reviewer, datetime.now().isoformat(timespec="seconds")
    bill.status_reasons = [f"Rejected by {reviewer}"] + bill.status_reasons
    db.update_bill(bill)
    return bill


def submit_missing_fields(bill_id: int, values: dict, today: Optional[date] = None) -> Bill:
    """Human fills missing fields (confidence 1.0) -> re-run verify + route. Not auto-verified."""
    bill = db.get_bill(bill_id)
    if bill is None or bill.status != "MISSING_DATA":
        raise ValueError("Only MISSING_DATA bills take field input")
    for f, val in values.items():
        if val is None or val == "":
            continue
        setattr(bill, "merchant_raw" if f == "merchant" else f, val)
        bill.field_confidence[f] = 1.0
        if f in bill.low_confidence_fields:
            bill.low_confidence_fields.remove(f)
    evaluate(bill)
    db.update_bill(bill)
    if bill.status == "VERIFIED":
        finalize_verified(bill, today)
    return bill
