import streamlit as st

from core import config, db, ingest
from ui.components import (bill_card, empty_state, is_individual, page_header, process_with_progress,
                           toast_once)

ind = is_individual()
page_header("Add a bill" if ind else "Add bills",
            "We read it, check it against your bank, and only then add it to your books." if ind else
            "Every bill runs: read → duplicate check → fraud check → bank match → post. Only verified bills post.")

if not db.list_transactions():
    st.info("Load your bank statement in **Settings** so we can check bills against it.",
            icon=":material/account_balance:")

st.session_state.setdefault("results", [])


def run(raws):
    new_alerts = []
    ids = []
    for raw in raws:
        bill = process_with_progress(raw, raw.filename or raw.source)
        ids.append(bill.id)
        new_alerts += bill.new_alerts
    st.session_state["results"] = ids + st.session_state["results"]
    toast_once(new_alerts)


def amount_input(label, key):
    return st.number_input(label, min_value=0.0, value=None, step=1.0, format="%.2f", key=key,
                           help="Optional. Only used to show you a comparison - it never changes the result.")


tab_up, tab_scan, tab_mail, tab_manual = st.tabs(["Upload", "Scan", "Email", "Type it in" if ind else "Manual entry"])

with tab_up:
    files = st.file_uploader("Receipts or invoices (PNG, JPG, PDF)", type=["png", "jpg", "jpeg", "pdf"],
                             accept_multiple_files=True)
    amounts = {}
    for i, f in enumerate(files or []):
        amounts[i] = amount_input(f"Amount you paid for {f.name} (₹, optional)", key=f"uea_{i}_{f.name}")
    if st.button("Check bills" if not ind else "Check my bill", type="primary", disabled=not files,
                 key="primary_cta", icon=":material/fact_check:", width="stretch"):
        run([ingest.ingest_upload(f.getvalue(), f.name, amounts.get(i)) for i, f in enumerate(files)])

with tab_scan:
    shot = st.camera_input("Point your camera at the receipt")
    uea = amount_input("Amount you paid (₹, optional)", key="uea_scan")
    if st.button("Check scan", type="primary", disabled=shot is None, key="scan_go", width="stretch"):
        run([ingest.ingest_scan(shot.getvalue(), uea)])

with tab_mail:
    st.caption(f"Source: {ingest.email_source_label()} · one bill per PDF, JPG or PNG attachment.")
    if st.button("Fetch email bills", type="primary", key="mail_go", icon=":material/mail:", width="stretch"):
        try:
            raws = ingest.ingest_email()
        except Exception as e:
            st.error(f"Couldn't reach the mailbox: {e}")
            raws = []
        if not raws:
            st.info("No bill attachments found in the inbox.")
        run(raws)

with tab_manual:
    with st.form("manual"):
        c1, c2 = st.columns(2)
        merchant = c1.text_input("Shop or merchant")
        bill_date = c2.date_input("Bill date", value=None, format="DD/MM/YYYY")
        invoice = c1.text_input("Invoice or order number")
        total = c2.number_input("Total amount", min_value=0.0, value=None, step=1.0, format="%.2f")
        tax = c1.number_input("Tax amount (GST)", min_value=0.0, value=None, step=1.0, format="%.2f")
        currency = c2.selectbox("Currency", list(config.FX_TABLE), index=None, placeholder="Choose")
        pay = c1.selectbox("Paid by", config.PAYMENT_MODES, index=None, placeholder="Choose")
        gstin = c2.text_input("GSTIN")
        uea_m = c1.number_input("Amount you paid (optional)", min_value=0.0, value=None, step=1.0, format="%.2f")
        st.caption("Leave anything you don't know empty. We store it as missing - we never guess.")
        if st.form_submit_button("Save bill", type="primary", width="stretch"):
            form = {"merchant": merchant or None, "bill_date": bill_date.isoformat() if bill_date else None,
                    "invoice_number": invoice or None, "total_amount": total, "tax_amount": tax,
                    "currency": currency, "payment_mode": pay, "gstin": gstin or None,
                    "user_entered_amount": uea_m}
            run([ingest.ingest_manual(form)])

st.divider()
results = [b for b in (db.get_bill(i) for i in st.session_state["results"]) if b]
with st.container(horizontal=True, vertical_alignment="center"):
    st.subheader("Just checked")
    if results and st.button("Clear list", icon=":material/clear_all:", key="clear_results"):
        st.session_state["results"] = []
        st.rerun()
if not results:
    empty_state("No bills checked yet",
                "Upload a receipt and we'll read it, check it against your bank, and show you exactly what we found.",
                ":material/receipt_long:")
for b in results:
    bill_card(b)
