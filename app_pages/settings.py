import pandas as pd
import streamlit as st

from core import config, db, ingest, mail
from ui.components import empty_state, fmt_date, is_individual, money_table, page_header, section_header

ind = is_individual()
user = db.current_user()
page_header("Settings", "Your bank statement, account and data.")

flash = st.session_state.pop("set_flash", None)
if flash:
    getattr(st, flash[0])(flash[1])

section_header("Bank statement", "We match each bill against these debits. Only you can see them.")
with st.container(horizontal=True, vertical_alignment="bottom"):
    if st.button("Load sample bank statement", type="primary", key="primary_cta", icon=":material/upload_file:"):
        if not config.BANK_CSV.exists():
            st.session_state["set_flash"] = ("error", "Sample file missing - run `python scripts/make_samples.py`.")
        else:
            a, s, e = ingest.import_bank_csv(config.BANK_CSV.read_text(encoding="utf-8"))
            db.log_action("csv_import", f"sample statement: {a} added, {s} skipped")
            st.session_state["set_flash"] = ("success", f"Imported {a} transaction(s), skipped {s} already present.")
        st.rerun()
up = st.file_uploader("Or upload a CSV (date, description, amount, currency, type, account)", type=["csv"])
if up and st.button("Import CSV", icon=":material/upload:", key="import_csv"):
    a, s, e = ingest.import_bank_csv(up.getvalue().decode("utf-8", errors="replace"))
    db.log_action("csv_import", f"{up.name}: {a} added, {s} skipped, {len(e)} errors")
    st.session_state["set_flash"] = ("success" if not e else "warning",
                                     f"Imported {a}, skipped {s}." + (f" Problems: {'; '.join(e)}" if e else ""))
    st.rerun()

txns = db.list_transactions()
if txns:
    df = pd.DataFrame([{"Date": t.txn_date, "Description": t.description, "Amount": t.amount_inr,
                        "Type": t.type.title(), "Account": t.account_name,
                        "Matched bill": f"#{t.matched_bill_id}" if t.matched_bill_id else "—"} for t in txns])
    df, cfg = money_table(df, ["Amount"], ["Date"])
    st.dataframe(df, hide_index=True, column_config=cfg, alt="Imported bank transactions")
else:
    empty_state("No bank statement yet",
                "Load the sample statement or upload your own CSV. Bills are then checked against real debits.",
                ":material/account_balance:")

st.divider()
section_header("Connected email", "Sign in with Google so we can pick up bill attachments from Gmail (read-only).")
acc = mail.connected_account()
with st.container(border=True):
    if acc:
        with st.container(horizontal=True, vertical_alignment="center"):
            st.badge("Connected", icon=":material/mark_email_read:", color="green")
            st.markdown(f"**{acc['email']}** · last checked "
                        + (fmt_date(acc["last_sync_at"]) if acc.get("last_sync_at") else "never"))
        if st.button("Disconnect Gmail", icon=":material/link_off:", key="mail_disconnect"):
            mail.disconnect()
            db.log_action("email_disconnect", acc["email"])
            st.session_state["set_flash"] = ("success", "Gmail disconnected and access revoked.")
            st.rerun()
    elif mail.oauth_configured():
        st.caption("Not connected.")
        if st.button("Sign in with Google", icon=":material/login:", key="mail_connect"):
            with st.spinner("A Google sign-in tab has opened - finish signing in there…"):
                try:
                    email = mail.connect_gmail()
                    db.log_action("email_connect", email)
                    st.session_state["set_flash"] = ("success", f"Gmail connected: {email}")
                except Exception as e:
                    st.session_state["set_flash"] = ("error", f"Sign-in didn't complete: {e}")
            st.rerun()
    else:
        st.caption(f"Google sign-in isn't set up yet. Add the OAuth client file `{mail.client_file().name}` "
                   "to the project folder (README → Gmail sign-in), then refresh.")

st.divider()
section_header("Account")
with st.container(border=True):
    st.markdown(f"**{user['name']}** · {user['email']}")
    st.caption(f"{'Personal' if ind else 'Business'} account" + (f" · {user['org_name']}" if user.get("org_name") else "")
               + f" · Bookkeeping mode: {db.get_mode()} (set by your role)")

st.divider()
section_header("Your data", "Clearing removes only your bills, bank lines, ledger, budgets and alerts.")
confirm = st.checkbox("I understand this permanently deletes my data.")
if st.button("Clear my data", disabled=not confirm, icon=":material/delete:", key="clear_data"):
    db.clear_my_data()
    db.log_action("clear_data", user["email"])
    st.session_state.pop("results", None)
    st.session_state["set_flash"] = ("success", "Your data was cleared.")
    st.rerun()
