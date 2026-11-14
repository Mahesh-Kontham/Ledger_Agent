"""A user can never see another user's bills (PRD Section 18)."""
import pytest
from conftest import login_as, upload

from core import auth, config, db, ingest, ledger
from core.pipeline import approve_bill, reject_bill, submit_missing_fields


def load_bank():
    ingest.import_bank_csv(config.BANK_CSV.read_text(encoding="utf-8"))


def test_bills_are_invisible_to_other_users(fresh_db):
    a = login_as("a@example.com", "BUSINESS")
    load_bank()
    b1 = upload("bill1_swiggy.png", mode="BUSINESS")
    b4 = upload("bill4_amazon_edited.png", mode="BUSINESS")
    assert len(db.list_bills()) == 2

    login_as("b@example.com", "INDIVIDUAL")
    assert db.list_bills() == []
    assert db.get_bill(b1.id) is None and db.get_bill_row(b1.id) is None
    assert db.review_queue() == [] and db.review_queue_count() == 0
    assert db.journal_rows() == []
    assert ledger.trial_balance(None)[1:] == (0.0, 0.0)
    assert db.list_transactions() == []          # A's bank statement is not B's
    assert db.list_alerts() == []
    with pytest.raises(ValueError):
        approve_bill(b4.id)
    with pytest.raises(ValueError):
        reject_bill(b4.id)
    with pytest.raises(ValueError):
        submit_missing_fields(b4.id, {"bill_date": "2026-11-01"})

    login_as(a["email"], a["role"])
    assert db.get_bill(b4.id).status == b4.status          # untouched by B


def test_duplicate_check_is_per_user(fresh_db):
    login_as("a@example.com", "INDIVIDUAL")
    load_bank()
    first = upload("bill1_swiggy.png")
    login_as("b@example.com", "INDIVIDUAL")
    load_bank()
    same_file = upload("bill1_swiggy.png")
    assert same_file.status == "VERIFIED" and same_file.duplicate_of is None
    assert same_file.id != first.id


def test_bank_match_never_uses_other_users_transactions(fresh_db):
    login_as("a@example.com", "INDIVIDUAL")
    load_bank()
    login_as("b@example.com", "INDIVIDUAL")         # B has no statement
    b = upload("bill1_swiggy.png")
    assert b.match_status == "NO_MATCH"


def test_budgets_are_per_user(fresh_db):
    login_as("a@example.com", "INDIVIDUAL")
    db.upsert_budget("Food", 1000, "INDIVIDUAL")
    login_as("b@example.com", "INDIVIDUAL")
    assert db.list_budgets("INDIVIDUAL") == []


def test_unauthenticated_has_no_access(fresh_db):
    db.set_current_user(None)
    for fn in (db.list_bills, db.review_queue, db.journal_rows, db.list_transactions):
        with pytest.raises(PermissionError):
            fn()


def test_admin_sees_aggregates_not_bills(fresh_db):
    login_as("a@example.com", "BUSINESS")
    load_bank()
    upload("bill1_swiggy.png", mode="BUSINESS")
    login_as("admin@example.com", "ADMIN")
    assert db.list_bills() == []                    # admin has no access to users' bills
    stats = db.admin_bill_stats()
    assert len(stats) == 1 and "file_path" not in stats[0] and "merchant_normalized" not in stats[0]
    assert {u["email"] for u in db.admin_list_users()} >= {"a@example.com", "admin@example.com"}
    login_as("a@example.com", "BUSINESS")
    with pytest.raises(PermissionError):
        db.admin_bill_stats()


def test_mode_derived_from_role(fresh_db):
    login_as("biz@example.com", "BUSINESS")
    assert db.get_mode() == "BUSINESS"
    login_as("ind@example.com", "INDIVIDUAL")
    assert db.get_mode() == "INDIVIDUAL"


def test_passwords_hashed_and_login(fresh_db):
    auth.create_user("Z", "z@example.com", "s3cret-pass", "INDIVIDUAL")
    row = db.get_user_for_login("z@example.com")
    assert row["password_hash"] != "s3cret-pass" and row["password_hash"].startswith("$2")
    assert auth.login("z@example.com", "wrong-pass") is None
    u = auth.login("Z@example.com", "s3cret-pass")
    assert u and "password_hash" not in u
    db.set_current_user(u)
    with db.get_conn() as conn:
        conn.execute("UPDATE users SET is_active=0 WHERE id=?", (u["id"],))
    assert auth.login("z@example.com", "s3cret-pass") is None     # deactivated


def test_migration_assigns_orphans_to_demo_business(fresh_db):
    with db.get_conn() as conn:
        conn.execute("INSERT INTO transactions (txn_date, description, amount, currency, amount_inr, type, "
                     "account_name) VALUES ('2026-11-01','OLD',1,'INR',1,'DEBIT','X')")
    biz = login_as("business@demo", "BUSINESS")
    assert db.assign_orphans() >= 1
    assert any(t.description == "OLD" for t in db.list_transactions())
    assert biz["role"] == "BUSINESS"
