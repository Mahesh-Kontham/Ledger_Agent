import streamlit as st

from core import config, db, ingest, mail
from ui.components import (bill_card, empty_state, fmt_date, is_individual, page_header, process_with_progress,
                           toast_once)

ind = is_individual()
page_header("Add a bill" if ind else "Add bills",
            "We read it, check it against your bank, and only then add it to your books." if ind else
            "Every bill runs: read → duplicate check → fraud check → bank match → post. Only verified bills post.")

if not db.list_transactions():
    st.info("Load your bank statement in **Settings** so we can check bills against it.",
            icon=":material/account_balance:")

st.session_state.setdefault("results", [])
st.session_state.setdefault("scan_stage", "idle")      # idle -> live -> captured
st.session_state.setdefault("scan_n", 0)               # new camera widget key per session = fresh camera

flash = st.session_state.pop("add_flash", None)
if flash:
    getattr(st, flash[0])(flash[1])


def run(raws):
    new_alerts, ids = [], []
    for raw in raws:
        bill = process_with_progress(raw, raw.filename or raw.source)
        ids.append(bill.id)
        new_alerts += bill.new_alerts
    st.session_state["results"] = ids + st.session_state["results"]
    toast_once(new_alerts)


def amount_input(label, key):
    return st.number_input(label, min_value=0.0, value=None, step=1.0, format="%.2f", key=key,
                           help="Optional. Only used to show you a comparison - it never changes the result.")


# A segmented control (not tabs): only the chosen source is rendered, so the camera is never
# switched on in the background while you use another source.
SOURCES = ["Upload", "Scan", "Email", "Type it in" if ind else "Manual entry"]
source = st.segmented_control("Add from", SOURCES, default="Upload", key="add_source", required=True,
                              label_visibility="collapsed")
if source != "Scan" and st.session_state["scan_stage"] == "live":
    st.session_state["scan_stage"] = "idle"           # leaving Scan turns the camera off

# ---------------- Upload ----------------
if source == "Upload":
    files = st.file_uploader("Receipts or invoices (PNG, JPG, PDF)", type=["png", "jpg", "jpeg", "pdf"],
                             accept_multiple_files=True)
    amounts = {}
    for i, f in enumerate(files or []):
        amounts[i] = amount_input(f"Amount you paid for {f.name} (₹, optional)", key=f"uea_{i}_{f.name}")
    if st.button("Check my bill" if ind else "Check bills", type="primary", disabled=not files,
                 key="primary_cta", icon=":material/fact_check:", width="stretch"):
        run([ingest.ingest_upload(f.getvalue(), f.name, amounts.get(i)) for i, f in enumerate(files)])

# ---------------- Scan: open -> capture (camera stops) -> preview -> check / retake ----------------
elif source == "Scan":
    stage = st.session_state["scan_stage"]

    def open_camera():
        st.session_state["scan_n"] += 1
        st.session_state["scan_stage"] = "live"
        st.session_state.pop("scan_bytes", None)

    def on_capture():
        shot = st.session_state.get(f"cam_{st.session_state['scan_n']}")
        if shot is not None:
            st.session_state["scan_bytes"] = shot.getvalue()
            st.session_state["scan_stage"] = "captured"   # camera widget is no longer rendered -> camera off

    def close_camera():
        st.session_state["scan_stage"] = "idle"
        st.session_state.pop("scan_bytes", None)

    if stage == "idle":
        empty_state("Scan a paper receipt", "Open the camera, hold the receipt flat in good light, then press "
                    "Take Photo. The camera switches off as soon as the photo is taken.", ":material/photo_camera:")
        st.button("Open camera", type="primary", key="primary_cta", icon=":material/photo_camera:",
                  on_click=open_camera, width="stretch")
    elif stage == "live":
        st.camera_input("Point your camera at the receipt and press Take Photo",
                        key=f"cam_{st.session_state['scan_n']}", on_change=on_capture)
        st.button("Cancel", key="cam_cancel", icon=":material/close:", on_click=close_camera)
    else:  # captured - camera is off, show the photo
        st.image(st.session_state["scan_bytes"], caption="Captured receipt", width=420)
        uea = amount_input("Amount you paid (₹, optional)", key="uea_scan")
        c1, c2 = st.columns(2)
        check = c1.button("Check this bill", type="primary", key="primary_cta", icon=":material/fact_check:",
                          width="stretch")
        c2.button("Retake", key="cam_retake", icon=":material/restart_alt:", on_click=open_camera, width="stretch")
        if check:
            data = st.session_state.pop("scan_bytes")
            st.session_state["scan_stage"] = "idle"
            run([ingest.ingest_scan(data, uea)])

# ---------------- Email ----------------
elif source == "Email":
    acc = mail.connected_account()
    if acc:
        with st.container(border=True):
            with st.container(horizontal=True, vertical_alignment="center"):
                st.badge("Gmail connected", icon=":material/mark_email_read:", color="green")
                st.markdown(f"**{acc['email']}**")
            st.caption("Last checked: " + (fmt_date(acc["last_sync_at"]) if acc.get("last_sync_at") else "never")
                       + " · we only import emails with a PDF, JPG or PNG attachment from the last 30 days, "
                         "and never the same email twice.")
        if st.button("Fetch new email bills", type="primary", key="primary_cta", icon=":material/sync:",
                     width="stretch"):
            try:
                with st.spinner("Checking your inbox for new bills…"):
                    raws, handled = mail.fetch_new_bills()
            except Exception as e:
                st.error(f"Couldn't read your mailbox: {e}. Try signing in again from Settings.")
                raws, handled = [], []
            else:
                if raws:
                    run(raws)
                mail.finish_sync(handled)
                db.log_action("email_sync", f"{acc['email']}: {len(handled)} new email(s), {len(raws)} bill(s)")
                if not raws:
                    st.info("No new bills in your inbox since the last check.")
    else:
        with st.container(border=True):
            st.markdown("**Connect your Gmail**")
            st.caption("Sign in with Google to let LedgerTruth read bill attachments (read-only). "
                       "Each user connects their own mailbox; you can disconnect any time in Settings.")
            if mail.oauth_configured():
                if st.button("Sign in with Google", type="primary", key="primary_cta", icon=":material/login:",
                             width="stretch"):
                    with st.spinner("A Google sign-in tab has opened - finish signing in there…"):
                        try:
                            email = mail.connect_gmail()
                            db.log_action("email_connect", email)
                            st.session_state["add_flash"] = ("success", f"Gmail connected: {email}")
                        except Exception as e:
                            st.session_state["add_flash"] = ("error", f"Sign-in didn't complete: {e}")
                    st.rerun()
            else:
                st.caption(f"Google sign-in isn't set up on this server yet: add the OAuth client file "
                           f"`{mail.client_file().name}` (see README → Gmail sign-in).")
        if config.GMAIL_IMAP_USER and config.GMAIL_IMAP_APP_PASSWORD:
            label = f"Fetch from {config.GMAIL_IMAP_USER} (app password)"
        else:
            label = "Use the demo inbox"
        st.caption("No Gmail? " + ("Use the IMAP app-password account configured in .env."
                                   if config.GMAIL_IMAP_USER else "Try the sample inbox that ships with the demo."))
        if st.button(label, key="mail_go", icon=":material/inbox:"):
            try:
                raws = ingest.ingest_email()
            except Exception as e:
                st.error(f"Couldn't reach the mailbox: {e}")
                raws = []
            if not raws:
                st.info("No bill attachments found in the inbox.")
            run(raws)

# ---------------- Manual ----------------
else:
    with st.form("manual"):
        c1, c2 = st.columns(2)
        merchant = c1.text_input("Shop or merchant")
        bill_date = c2.date_input("Bill date", value=None, format="DD/MM/YYYY")
        invoice = c1.text_input("Invoice or order number")
        total = c2.number_input("Total amount", min_value=0.0, value=None, step=1.0, format="%.2f")
        currency = c1.selectbox("Currency", list(config.FX_TABLE), index=None, placeholder="Choose")
        pay = c2.selectbox("Paid by", config.PAYMENT_MODES, index=None, placeholder="Choose")
        gstin = c1.text_input("GSTIN / GST No.")
        uea_m = c2.number_input("Amount you paid (optional)", min_value=0.0, value=None, step=1.0, format="%.2f")
        st.markdown("**Tax** - enter the total tax, or the parts printed on the bill (we add them up)")
        t = st.columns(5)
        tax_total = t[0].number_input("Total tax", min_value=0.0, value=None, step=1.0, format="%.2f")
        parts = {name: t[i + 1].number_input(name, min_value=0.0, value=None, step=1.0, format="%.2f")
                 for i, name in enumerate(["CGST", "SGST / UTGST", "IGST", "Cess"])}
        st.caption("Leave anything you don't know empty. We store it as missing - we never guess.")
        if st.form_submit_button("Save bill", type="primary", width="stretch"):
            form = {"merchant": merchant or None, "bill_date": bill_date.isoformat() if bill_date else None,
                    "invoice_number": invoice or None, "total_amount": total, "tax_amount": tax_total,
                    "currency": currency, "payment_mode": pay, "gstin": gstin or None,
                    "tax_lines": [{"description": k, "amount": v} for k, v in parts.items() if v],
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
