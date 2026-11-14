"""PRD Section 19: flexible tax, budget sync + notifications, data consistency, Gmail incremental sync."""
import base64
from datetime import date
from pathlib import Path

from conftest import upload
from streamlit.testing.v1 import AppTest

from core import auth, budgets, db, extract, ingest, ledger, mail
from core.pipeline import process_bill

TODAY = date(2026, 11, 14)


# ---------------- flexible tax ----------------
def _obj(tax=None, tax_conf=0.99, tax_lines=(), line_items=()):
    return {"merchant": {"value": "Cafe", "confidence": 0.99}, "total_amount": {"value": 246, "confidence": 0.99},
            "tax_amount": {"value": tax, "confidence": tax_conf},
            "tax_lines": [{"description": d, "amount": a} for d, a in tax_lines],
            "line_items": [{"description": d, "amount": a} for d, a in line_items]}


def test_cgst_plus_sgst_become_tax_amount():
    ext = extract.postprocess(_obj(tax_lines=[("CGST @9%", 23), ("SGST @9%", 23)]))
    assert ext.values["tax_amount"] == 46.0


def test_model_returning_one_component_is_corrected():
    ext = extract.postprocess(_obj(tax=23, tax_lines=[("CGST 9%", 23), ("SGST 9%", 23)]))
    assert ext.values["tax_amount"] == 46.0


def test_printed_total_tax_wins_and_igst_cess_and_vat_count():
    assert extract.postprocess(_obj(tax_lines=[("CGST", 23), ("SGST", 23), ("Total GST", 46)])).values["tax_amount"] == 46
    assert extract.postprocess(_obj(tax_lines=[("IGST 18%", 36), ("Cess 1%", 2)])).values["tax_amount"] == 38
    assert extract.postprocess(_obj(line_items=[("Pizza", 200), ("VAT 5%", 10)])).values["tax_amount"] == 10


def test_non_tax_lines_ignored_and_no_tax_never_invented():
    ext = extract.postprocess(_obj(line_items=[("Taxable value", 200), ("Tax Invoice", 1), ("GSTIN 29AB", 0)]))
    assert ext.values["tax_amount"] is None


def test_gstin_variants_normalised_or_rejected():
    o = _obj()
    o["gstin"] = {"value": "GST No: 29abcde1234f1z5", "confidence": 0.99}
    assert extract.postprocess(o).values["gstin"] == "29ABCDE1234F1Z5"
    o["gstin"] = {"value": "29ABC", "confidence": 0.99}
    e = extract.postprocess(o)
    assert e.values["gstin"] is None and "gstin" in e.low_confidence_fields


def test_manual_tax_components_and_business_gst_split(fresh_db):
    from conftest import login_as
    login_as("biz@example.com", "BUSINESS")
    raw = ingest.ingest_manual(dict(merchant="Google Ads", bill_date="2026-11-03", invoice_number="GA1",
                                    total_amount=1180.0, currency="INR", payment_mode="CARD",
                                    gstin="29ABCDE1234F1Z5",
                                    tax_lines=[{"description": "CGST", "amount": 90.0},
                                               {"description": "SGST / UTGST", "amount": 90.0}]))
    b = process_bill(raw, mode="BUSINESS")
    assert b.tax_amount == 180.0
    from core.models import Bill
    bb = Bill(**{**b.__dict__, "status": "VERIFIED", "match_status": "NO_MATCH", "id": b.id})
    rows = {(l.account, l.debit) for l in ledger.build_journal(bb, None)}
    assert ("Asset:Input GST", 180.0) in rows and ("Expense:Advertising", 1000.0) in rows


# ---------------- budget sync + notifications ----------------
def test_crossing_limit_raises_breach_and_unread_notification(fresh_db):
    db.upsert_budget("Transport", 150, "INDIVIDUAL")
    b2 = upload("bill2_rapido.png", user_entered_amount=120, today=TODAY)       # 125 / 150 = 83%
    assert [a.alert_type for a in b2.new_alerts] == ["BUDGET_WARNING"]
    raw = ingest.ingest_manual(dict(merchant="Uber", bill_date="2026-11-13", invoice_number="UB1",
                                    total_amount=60.0, currency="INR", payment_mode="UPI"))
    b = process_bill(raw, mode="INDIVIDUAL", today=TODAY)                      # 185 / 150 -> crossed
    assert "BUDGET_BREACH" in [a.alert_type for a in b.new_alerts]
    unread = db.unread_alerts()
    assert {a.alert_type for a in unread} >= {"BUDGET_WARNING", "BUDGET_BREACH"}
    db.mark_alerts_read()
    assert db.unread_alerts() == []


def test_lowering_limit_below_spent_alerts_immediately(fresh_db):
    upload("bill2_rapido.png", today=TODAY)
    db.upsert_budget("Transport", 50, "INDIVIDUAL")
    new = budgets.run_budget_checks("INDIVIDUAL", TODAY)       # what the Budgets page runs on save
    assert [a.alert_type for a in new] == ["BUDGET_BREACH"]


def test_numbers_agree_across_views(fresh_db):
    """Home spent == category ledger == journal expense lines; budget spent == category total."""
    upload("bill1_swiggy.png")
    upload("bill2_rapido.png", user_entered_amount=120)
    process_bill(ingest.ingest_email()[0], mode="INDIVIDUAL", extractor=__import__("conftest").fake_extractor)
    month = "2026-11"
    cat = ledger.category_totals("INDIVIDUAL", month)
    j = ledger.journal_df("INDIVIDUAL", month)
    exp = j[j["account"].str.startswith("Expense:")]
    assert round(cat["total_inr"].sum(), 2) == round(exp["debit"].sum() - exp["credit"].sum(), 2)
    for c in ["Food", "Transport", "Subscriptions"]:
        assert budgets.category_spent(c, "INDIVIDUAL", 2026, 11) == float(cat.loc[cat["category"] == c, "total_inr"].sum())
    _, d, c = ledger.trial_balance("INDIVIDUAL")
    assert d == c
    # every VERIFIED bill has exactly one balanced entry; nothing else is posted
    posted = {r["bill_id"] for r in db.journal_rows()}
    assert posted == {b.id for b in db.list_bills(["VERIFIED"])}


# ---------------- Gmail incremental sync ----------------
class FakeResp:
    def __init__(self, data):
        self._d = data

    def json(self):
        return self._d

    def raise_for_status(self):
        pass


class FakeGmail:
    def __init__(self, pdf: bytes):
        self.pdf = base64.urlsafe_b64encode(pdf).decode().rstrip("=")

    def get(self, url, params=None, timeout=None):
        if url.endswith("/messages"):
            return FakeResp({"messages": [{"id": "m1"}]})
        if url.endswith("/messages/m1"):
            return FakeResp({"id": "m1", "payload": {"headers": [{"name": "Subject", "value": "Invoice NT6006"}],
                                                     "parts": [{"filename": "", "body": {}},
                                                               {"filename": "notion_invoice.pdf",
                                                                "body": {"attachmentId": "a1"}}]}})
        if url.endswith("/attachments/a1"):
            return FakeResp({"data": self.pdf})
        raise AssertionError(url)


def test_gmail_fetches_only_new_messages(fresh_db):
    from core import config
    fake = FakeGmail((config.SAMPLE_DIR / "notion_invoice.pdf").read_bytes())
    db.save_mail_account("gmail", "me@gmail.com", "{}")
    raws, handled = mail.fetch_new_bills(session=fake)
    assert len(raws) == 1 and raws[0].source == "email" and handled == ["m1"]
    assert Path(raws[0].file_path).read_bytes()[:4] == b"%PDF"
    mail.finish_sync(handled)
    raws2, handled2 = mail.fetch_new_bills(session=fake)
    assert raws2 == [] and handled2 == []                    # already imported -> skipped
    assert mail.connected_account()["last_sync_at"]
    assert "token_json" not in mail.connected_account()     # token never leaves the db layer


def test_mail_connection_is_per_user(fresh_db):
    from conftest import login_as
    db.save_mail_account("gmail", "a@gmail.com", "{}")
    login_as("other@example.com", "INDIVIDUAL")
    assert db.get_mail_account() is None


# ---------------- scan: camera only while needed ----------------
APP = str(Path(__file__).resolve().parent.parent / "app.py")


def test_camera_is_off_until_opened_and_after_capture(fresh_db):
    auth.create_user("P", "p@demo", "demo-pass-123", "INDIVIDUAL")
    db.set_current_user(None)
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.text_input(key="login_email").input("p@demo")
    at.text_input(key="login_pw").input("demo-pass-123")
    at.button(key="login_submit").click().run()
    at.switch_page("app_pages/add_bills.py").run()
    assert not at.exception
    assert len(at.get("camera_input")) == 0                   # Upload view: camera not mounted
    at.segmented_control(key="add_source").set_value("Scan").run()
    assert len(at.get("camera_input")) == 0                   # Scan idle: still off
    at.button(key="primary_cta").click().run()               # Open camera
    assert len(at.get("camera_input")) == 1 and at.session_state["scan_stage"] == "live"
    # simulate the photo being taken
    at.session_state["scan_bytes"] = (Path(__file__).resolve().parent.parent / "sample_data" / "bill1_swiggy.png").read_bytes()
    at.session_state["scan_stage"] = "captured"
    at.run()
    assert len(at.get("camera_input")) == 0                   # camera released after capture
    assert not at.exception
    at.segmented_control(key="add_source").set_value("Upload").run()
    assert at.session_state["scan_stage"] == "captured" or len(at.get("camera_input")) == 0


def test_unrelated_nearby_debit_is_not_paired(fresh_db):
    """A ₹60 Uber bill must not be matched to a ₹870 Notion debit just because the dates are close."""
    raw = ingest.ingest_manual(dict(merchant="Uber", bill_date="2026-11-12", invoice_number="UB2",
                                    total_amount=60.0, currency="INR", payment_mode="UPI"))
    b = process_bill(raw, mode="INDIVIDUAL")
    assert b.match_status == "NO_MATCH" and b.status == "VERIFIED"


def test_debit_without_merchant_name_still_matches_on_exact_amount(fresh_db):
    from core.models import Transaction
    db.insert_transaction(Transaction(None, "2026-11-20", "POS 4532 XX19", 640.0, "INR", 640.0, "DEBIT", "HDFC Bank Account"))
    raw = ingest.ingest_manual(dict(merchant="Local Pharmacy", bill_date="2026-11-20", invoice_number="P1",
                                    total_amount=640.0, currency="INR", payment_mode="CARD"))
    b = process_bill(raw, mode="INDIVIDUAL")
    assert b.match_status == "MATCHED"


# ---------------- Gemini quota handling ----------------
class _QuotaErr(Exception):
    code = 429


def test_daily_quota_falls_back_to_next_model(monkeypatch):
    from types import SimpleNamespace
    from core import config
    calls = []

    def generate_content(model, contents, config):
        calls.append(model)
        if model == "main-model":
            raise _QuotaErr("429 RESOURCE_EXHAUSTED per day. Please retry in 21h57m17s. 'retryDelay': '79037s'")
        return SimpleNamespace(text='{"merchant": {"value": "X", "confidence": 0.99}}')

    fake = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    monkeypatch.setattr(extract, "_get_client", lambda: fake)
    monkeypatch.setattr(config, "LLM_MODEL", "main-model")
    monkeypatch.setattr(config, "GEMINI_FALLBACK_MODELS", ["backup-model"])
    assert '"X"' in extract._call_llm(b"img", "image/png")
    assert calls == ["main-model", "backup-model"]          # no 22-hour wait, straight to the backup


def test_per_minute_limit_waits_then_retries(monkeypatch):
    from types import SimpleNamespace
    from core import config
    calls, slept = [], []

    def generate_content(model, contents, config):
        calls.append(model)
        if len(calls) == 1:
            raise _QuotaErr("429 RESOURCE_EXHAUSTED per minute. Please retry in 3.5s.")
        return SimpleNamespace(text="{}")

    monkeypatch.setattr(extract, "_get_client", lambda: SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)))
    monkeypatch.setattr(config, "LLM_MODEL", "main-model")
    monkeypatch.setattr("time.sleep", lambda s: slept.append(s))
    extract._call_llm(b"img", "image/png")
    assert calls == ["main-model", "main-model"] and slept and slept[0] < 10
