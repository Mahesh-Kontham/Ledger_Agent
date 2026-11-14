from conftest import fake_extractor, upload

from core import db, ingest, ledger
from core.models import Bill, Transaction
from core.pipeline import approve_bill, process_bill, reject_bill, submit_missing_fields


def lines_for(bill_id):
    return [r for r in db.journal_rows() if r["bill_id"] == bill_id]


def test_rapido_entry_matches_prd_example(fresh_db):
    b = upload("bill2_rapido.png", user_entered_amount=120)
    rows = {(r["account"], r["debit"], r["credit"]) for r in lines_for(b.id)}
    assert rows == {("Expense:Transport", 125.0, 0.0), ("Expense:Bank Charges", 5.0, 0.0),
                    ("Liability:Credit Card - HDFC Credit Card", 0.0, 130.0)}
    assert lines_for(b.id)[0]["entry_id"] == f"JE-{b.id:06d}"


def test_notion_forex_entry(fresh_db):
    b = process_bill(ingest.ingest_email()[0], mode="INDIVIDUAL", extractor=fake_extractor)
    rows = {(r["account"], r["debit"], r["credit"]) for r in lines_for(b.id)}
    assert rows == {("Expense:Subscriptions", 850.0, 0.0), ("Expense:Forex Charges", 20.0, 0.0),
                    ("Liability:Credit Card - HDFC Credit Card", 0.0, 870.0)}


def test_approve_posts_and_reject_never_posts(fresh_db):
    b4 = upload("bill4_amazon_edited.png")
    assert not db.has_journal(b4.id)
    approved = approve_bill(b4.id)
    assert approved.status == "VERIFIED" and approved.reviewed_at
    rows = {(r["account"], r["debit"], r["credit"]) for r in lines_for(b4.id)}
    assert ("Asset:Bank - HDFC Bank Account", 0.0, 1299.0) in rows
    b5 = upload("bill5_zomato_blank.png")
    reject_bill(b5.id)
    assert db.get_bill(b5.id).status == "REJECTED" and not db.has_journal(b5.id)


def test_fill_missing_fields_reverifies(fresh_db):
    b5 = upload("bill5_zomato_blank.png")
    after = submit_missing_fields(b5.id, {"bill_date": "2026-11-05", "total_amount": 300.0})
    assert after.status == "VERIFIED"
    assert after.field_confidence["bill_date"] == 1.0
    assert "Single source - not bank-verified" in after.status_reasons
    assert db.has_journal(b5.id)


def test_trial_balance_always_balances(fresh_db):
    upload("bill1_swiggy.png")
    upload("bill2_rapido.png", user_entered_amount=120)
    upload("bill2_rapido.png")
    b4 = upload("bill4_amazon_edited.png")
    approve_bill(b4.id)
    process_bill(ingest.ingest_email()[0], mode="INDIVIDUAL", extractor=fake_extractor)
    _, d, c = ledger.trial_balance(None)
    assert d == c and d > 0


def test_business_gst_split(fresh_db):
    b = Bill(id=99, source="manual", mode="BUSINESS", status="VERIFIED", merchant_normalized="Google Ads",
             category="Advertising", bill_date="2026-11-03", total_amount=1180.0, total_amount_inr=1180.0,
             tax_amount=180.0, fx_rate=1.0, gstin="29ABCDE1234F1Z5", currency="INR", payment_mode="CARD",
             match_status="NO_MATCH")
    rows = {(l.account, l.debit, l.credit) for l in ledger.build_journal(b, None)}
    assert rows == {("Expense:Advertising", 1000.0, 0.0), ("Asset:Input GST", 180.0, 0.0),
                    ("Liability:Credit Card - Unspecified", 0.0, 1180.0)}


def test_negative_variance_still_balances():
    b = Bill(id=7, source="upload", mode="INDIVIDUAL", status="VERIFIED", category="Food", bill_date="2026-11-10",
             total_amount_inr=500.0, match_status="MATCHED", payment_mode="UPI")
    t = Transaction(3, "2026-11-10", "X", 499.0, "INR", 499.0, "DEBIT", "HDFC Bank Account")
    lines = ledger.build_journal(b, t)
    assert round(sum(l.debit for l in lines), 2) == round(sum(l.credit for l in lines), 2) == 500.0
