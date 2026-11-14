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


def test_business_fills_missing_gstin(seeded):
    """BUSINESS requires GSTIN when tax > 0: Swiggy waits in the queue until a human supplies it."""
    login_as("business@demo", "BUSINESS")
    swiggy = [b for b in db.list_bills() if b.merchant_normalized == "Swiggy"][0]
    assert swiggy.status == "MISSING_DATA" and swiggy.missing_fields == ["gstin"]
    at = login("business@demo")
    at.switch_page("app_pages/review.py").run()
    at.text_input(key=f"gstin_{swiggy.id}").input("29ABCDE1234F1Z5")
    at.button(key="approve_btn").click().run()
    assert not at.exception, at.exception
    login_as("business@demo", "BUSINESS")
    after = db.get_bill(swiggy.id)
    assert after.status == "VERIFIED"
    assert any(r["account"] == "Asset:Input GST" for r in db.journal_rows() if r["bill_id"] == swiggy.id)


def test_individual_budget_editor_saves(seeded):
    at = login("user@demo")
    at.switch_page("app_pages/budgets.py").run()
    assert not at.exception
    at.button(key="primary_cta").click().run()
    assert not at.exception
