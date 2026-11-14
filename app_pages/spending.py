import pandas as pd
import streamlit as st

from core import db, ledger
from ui.components import (empty_state, fmt_date, money, money_table, month_label, page_header,
                           section_header)

mode = db.get_mode()
page_header("Spending", "Where your money went - only checked bills are counted.")

months = ledger.months(mode)
if not months:
    empty_state("No spending yet", "Upload a receipt and we'll check it against your bank. It shows up here once it's verified.",
                ":material/pie_chart:")
    st.stop()

with st.container(horizontal=True, vertical_alignment="bottom"):
    month = st.selectbox("Month", months, format_func=month_label, width=200)
    accountant = st.toggle("Accountant view", help="Show the double-entry journal and trial balance.")

cat = ledger.category_totals(mode, month)
section_header("By category")
if cat.empty:
    st.caption("Nothing this month.")
else:
    st.bar_chart(cat.rename(columns={"category": "Category", "total_inr": "₹"}), x="Category", y="₹",
                 horizontal=True, height=260)

section_header("By shop", "Tap a shop to see its bills.")
g = ledger.merchant_groups(mode)
for _, r in g.iterrows():
    with st.expander(f"**{r['merchant']}** · {r['bills']} bill{'s' if r['bills'] != 1 else ''} · {money(r['total_inr'], 0)}"):
        rows = [{"Date": b.bill_date, "Amount": b.total_amount_inr,
                 "Bank check": "Checked" if b.match_status in ("MATCHED", "VARIANCE_EXPLAINED") else "Receipt only"}
                for b in db.list_bills(["VERIFIED"], mode) if b.merchant_normalized == r["merchant"]]
        view, cfg = money_table(pd.DataFrame(rows), ["Amount"], ["Date"])
        st.dataframe(view, hide_index=True, column_config=cfg, alt=f"Bills from {r['merchant']}")

if accountant:
    st.divider()
    section_header("Accountant view", "Double-entry journal. Debits always equal credits.")
    tb, d, c = ledger.trial_balance(mode)
    st.badge("Balanced" if d == c else "Not balanced", color="green" if d == c else "red",
             icon=":material/check_circle:" if d == c else ":material/error:")
    jdf = ledger.journal_df(mode, month)
    view, cfg = money_table(jdf[["entry_id", "entry_date", "account", "debit", "credit", "note"]].rename(columns={
        "entry_id": "Entry", "entry_date": "Date", "account": "Account", "debit": "Debit", "credit": "Credit",
        "note": "Note"}), ["Debit", "Credit"], ["Date"])
    st.dataframe(view, hide_index=True, column_config=cfg, alt="Journal")
    view, cfg = money_table(tb.rename(columns={"account": "Account", "debit": "Debit", "credit": "Credit"}),
                            ["Debit", "Credit"])
    st.dataframe(view, hide_index=True, column_config=cfg, alt="Trial balance")
    st.caption(f"Totals · Debits {money(d)} · Credits {money(c)}")
