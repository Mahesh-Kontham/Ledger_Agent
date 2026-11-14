"""Headless UI checks: each role logs in, sees only its pages, and every page renders without errors."""
from pathlib import Path

import pytest
from conftest import fake_extractor, login_as, upload
from streamlit.testing.v1 import AppTest

from core import auth, config, db, ingest
from core.pipeline import process_bill

APP = str(Path(__file__).resolve().parent.parent / "app.py")
PAGES = {
    "INDIVIDUAL": ["home", "add_bills", "review", "spending", "budgets", "settings"],
    "BUSINESS": ["dashboard", "add_bills", "review", "ledger", "budgets", "reports", "settings"],
    "ADMIN": ["admin_overview", "admin_users", "admin_health", "admin_audit"],
}


@pytest.fixture()
def seeded(fresh_db):
    for email, name, role, org in [("admin@demo", "Admin", "ADMIN", None),
                                   ("business@demo", "Ravi Kumar", "BUSINESS", "Kumar Traders"),
                                   ("user@demo", "Priya Sharma", "INDIVIDUAL", None)]:
        auth.create_user(name, email, "demo-pass-123", role, org)
    login_as("business@demo", "BUSINESS")
    ingest.import_bank_csv(config.BANK_CSV.read_text(encoding="utf-8"))
    for f in ["bill1_swiggy.png", "bill2_rapido.png", "bill4_amazon_edited.png", "bill5_zomato_blank.png"]:
        upload(f, mode="BUSINESS")
    process_bill(ingest.ingest_email()[0], mode="BUSINESS", extractor=fake_extractor)
    login_as("user@demo", "INDIVIDUAL")
    ingest.import_bank_csv(config.BANK_CSV.read_text(encoding="utf-8"))
    db.upsert_budget("Transport", 150, "INDIVIDUAL")
    upload("bill2_rapido.png", user_entered_amount=120)
    upload("bill4_amazon_edited.png")
    db.set_current_user(None)
    return fresh_db


def login(email):
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    at.text_input[0].input(email)
    at.text_input[1].input("demo-pass-123")
    at.button(key="login_submit").click().run()
    assert not at.exception, at.exception
    return at


def test_unauthenticated_sees_only_login(seeded):
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert at.title[0].value == "LedgerTruth"
    assert "user" not in at.session_state


def test_wrong_password_rejected(seeded):
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.text_input[0].input("business@demo")
    at.text_input[1].input("nope-nope")
    at.button(key="login_submit").click().run()
    assert "user" not in at.session_state and at.error


@pytest.mark.parametrize("email,role", [("user@demo", "INDIVIDUAL"), ("business@demo", "BUSINESS"),
                                        ("admin@demo", "ADMIN")])
def test_each_role_renders_all_its_pages(seeded, email, role):
    at = login(email)
    assert at.session_state["user"]["role"] == role
    for page in PAGES[role]:
        at.switch_page(f"app_pages/{page}.py").run()
        assert not at.exception, (role, page, at.exception)


def test_individual_approves_flagged_bill(seeded):
    """AT-4 in the UI: the photoshop-edited Amazon bill is held, Approve posts it."""
    at = login("user@demo")
    at.switch_page("app_pages/review.py").run()
    assert not at.exception
    at.button(key="approve_btn").click().run()       # HIGH priority bill is selected first
    assert not at.exception
    login_as("user@demo", "INDIVIDUAL")
    amazon = [b for b in db.list_bills() if b.merchant_normalized == "Amazon"][0]
    assert amazon.status == "VERIFIED" and db.has_journal(amazon.id)
    login_as("admin@demo", "ADMIN")
    assert any(r["action"] == "approve" for r in db.admin_audit_log())


def test_business_approves_flagged_and_fills_missing(seeded):
    """BUSINESS: the edited Amazon bill is HIGH priority (approve posts it); Zomato needs date + total."""
    from datetime import date
    login_as("business@demo", "BUSINESS")
    by = {b.merchant_normalized: b for b in db.list_bills()}
    assert by["Amazon"].status == "NEEDS_REVIEW" and by["Amazon"].review_priority == "HIGH"
    assert by["Zomato"].status == "MISSING_DATA" and by["Zomato"].missing_fields == ["bill_date", "total_amount"]
    assert by["Swiggy"].status == "VERIFIED"          # GSTIN no longer mandatory
    at = login("business@demo")
    at.switch_page("app_pages/review.py").run()
    at.button(key="approve_btn").click().run()       # HIGH first -> Amazon
    assert not at.exception, at.exception
    z = by["Zomato"].id
    at.date_input(key=f"bill_date_{z}").set_value(date(2026, 11, 5))
    at.number_input(key=f"total_amount_{z}").set_value(300.0)
    at.button(key="approve_btn").click().run()
    assert not at.exception, at.exception
    login_as("business@demo", "BUSINESS")
    assert db.get_bill(by["Amazon"].id).status == "VERIFIED" and db.has_journal(by["Amazon"].id)
    after = db.get_bill(z)
    assert after.bill_date == "2026-11-05" and after.total_amount == 300.0
    assert after.status in ("VERIFIED", "NEEDS_REVIEW")   # re-verified, never auto-approved


def test_individual_budget_editor_saves(seeded):
    at = login("user@demo")
    at.switch_page("app_pages/budgets.py").run()
    assert not at.exception
    at.button(key="primary_cta").click().run()
    assert not at.exception
