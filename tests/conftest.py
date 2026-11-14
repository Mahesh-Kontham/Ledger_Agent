"""Test fixtures: an isolated temp DB loaded with the sample bank statement.

The fake extractor below returns exactly what is printed on each generated sample receipt
(PRD Section 12), so the pipeline can be tested without calling the LLM.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import config, db, ingest  # noqa: E402
from core.extract import FIELDS  # noqa: E402
from core.models import ExtractedFields  # noqa: E402

PRINTED = {
    "bill1_swiggy.png": dict(merchant="SWIGGY", bill_date="2026-11-10", invoice_number="SW1001",
                             total_amount=456.0, tax_amount=46.0, currency="INR", payment_mode="CARD"),
    "bill2_rapido.png": dict(merchant="RAPIDO", bill_date="2026-11-11", invoice_number="RP2002",
                             total_amount=125.0, tax_amount=5.95, currency="INR", payment_mode="CARD"),
    "bill4_amazon_edited.png": dict(merchant="AMAZON", bill_date="2026-11-12", invoice_number="AMZ4004",
                                    total_amount=1299.0, currency="INR", payment_mode="UPI"),
    "bill5_zomato_blank.png": dict(merchant="ZOMATO", invoice_number="ZO5005", currency="INR",
                                   payment_mode="UPI"),
    "notion_invoice.pdf": dict(merchant="Notion Labs, Inc.", bill_date="2026-11-12", invoice_number="NT6006",
                               total_amount=10.0, currency="USD", payment_mode="CARD"),
}


def fake_extractor(raw):
    key = Path(raw.filename.split(" (from")[0]).name
    printed = PRINTED[key]
    values = {f: printed.get(f) for f in FIELDS}
    return ExtractedFields(values=values, confidence={f: (0.99 if values[f] is not None else 0.0) for f in FIELDS})


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setenv("LEDGERTRUTH_DB", str(tmp_path / "test.db"))
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(config, "FRAUD_MCP_URL", "")
    db.init_db()
    uid = db.insert_user("Test User", "test@example.com", "x", "INDIVIDUAL")
    db.set_current_user(db.get_user(uid))
    if not config.BANK_CSV.exists():
        import subprocess
        subprocess.run([sys.executable, str(ROOT / "scripts" / "make_samples.py")], check=True)
    added, _, errors = ingest.import_bank_csv(config.BANK_CSV.read_text(encoding="utf-8"))
    assert added == 4 and not errors
    yield tmp_path
    db.set_current_user(None)


def login_as(email, role, name="User"):
    """Create (if needed) and switch to a user; returns the user dict."""
    row = db.get_user_for_login(email)
    uid = row["id"] if row else db.insert_user(name, email, "x", role)
    user = db.get_user(uid)
    db.set_current_user(user)
    return user


def upload(name, mode="INDIVIDUAL", user_entered_amount=None, today=None):
    from core.pipeline import process_bill
    path = config.SAMPLE_DIR / name
    raw = ingest.ingest_upload(path.read_bytes(), name, user_entered_amount)
    return process_bill(raw, mode=mode, extractor=fake_extractor, today=today)
