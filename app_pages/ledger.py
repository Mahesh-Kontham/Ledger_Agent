import streamlit as st

from core import db, ledger
from ui.components import empty_state, fmt_date, money, money_table, month_label, page_header

mode = db.get_mode()
page_header("Ledger", "Double-entry books in INR. Every entry balances - debits always equal credits.")

months = ledger.months(mode)
with st.container(horizontal=True, vertical_alignment="bottom"):
    month = st.selectbox("Month", ["All months"] + months, index=1 if months else 0,
                         format_func=lambda m: m if m == "All months" else month_label(m),
                         width=220)
    tb, d, c = ledger.trial_balance(mode)
    if d == c:
        st.badge(f"Balanced · {money(d)}", icon=":material/check_circle:", color="green")
    else:
        st.badge(f"Out of balance: {money(d)} vs {money(c)}", icon=":material/error:", color="red")
m = None if month == "All months" else month

t_j, t_c, t_m, t_tb, t_gst = st.tabs(["Journal", "Category", "Merchants", "Trial balance", "GST"])

with t_j:
    jdf = ledger.journal_df(mode, m)
    if jdf.empty:
        empty_state("No journal entries yet", "Verified bills post here automatically as balanced entries.",
                    ":material/menu_book:")
    else:
        view = jdf[["entry_id", "entry_date", "account", "debit", "credit", "note", "bill_id"]].rename(columns={
            "entry_id": "Entry", "entry_date": "Date", "account": "Account", "debit": "Debit", "credit": "Credit",
            "note": "Note", "bill_id": "Bill"})
        view, cfg = money_table(view, ["Debit", "Credit"], ["Date"])
        st.dataframe(view, hide_index=True, column_config=cfg, alt="Journal lines grouped by entry")

with t_c:
    cdf = ledger.category_totals(mode, m)
    if cdf.empty:
        empty_state("No expenses in this period", "Pick another month or add bills.", ":material/category:")
    else:
        view, cfg = money_table(cdf.rename(columns={"category": "Category", "total_inr": "Total"}), ["Total"])
        st.dataframe(view, hide_index=True, column_config=cfg, alt="Expense totals by category")

with t_m:
    g = ledger.merchant_groups(mode)
    if g.empty:
        empty_state("No merchants yet", "Merchants appear once their bills are posted.", ":material/storefront:")
    for _, r in g.iterrows():
        with st.expander(f"**{r['merchant']}** · {r['bills']} bill{'s' if r['bills'] != 1 else ''} · "
                         f"{money(r['total_inr'])} · {fmt_date(r['first_date'])} → {fmt_date(r['last_date'])}"):
            rows = [{"Bill": f"#{b.id}", "Date": b.bill_date, "Invoice": b.invoice_number or "—",
                     "Amount": b.total_amount_inr, "Bank match": b.match_status or "—", "Source": b.source}
                    for b in db.list_bills(["VERIFIED"], mode) if b.merchant_normalized == r["merchant"]]
            import pandas as pd
            view, cfg = money_table(pd.DataFrame(rows), ["Amount"], ["Date"])
            st.dataframe(view, hide_index=True, column_config=cfg, alt=f"Bills from {r['merchant']}")

with t_tb:
    if tb.empty:
        empty_state("Nothing posted yet", "The trial balance fills in as bills are verified.", ":material/balance:")
    else:
        view, cfg = money_table(tb.rename(columns={"account": "Account", "debit": "Debit", "credit": "Credit"}),
                                ["Debit", "Credit"])
        st.dataframe(view, hide_index=True, column_config=cfg, alt="Trial balance by account")
        with st.container(horizontal=True, vertical_alignment="center"):
            st.markdown(f"**Grand total** · Debits {money(d)} · Credits {money(c)}")
            st.badge("Balanced" if d == c else "Not balanced", color="green" if d == c else "red",
                     icon=":material/check_circle:" if d == c else ":material/error:")

with t_gst:
    gst = ledger.gst_summary(mode)
    st.caption("Total `Asset:Input GST` per month - GST you can claim back.")
    if gst.empty:
        empty_state("No input GST yet", "GST is split out when a bill has a GSTIN and a tax amount above zero.",
                    ":material/receipt:")
    else:
        view, cfg = money_table(gst.rename(columns={"month": "Month", "input_gst_inr": "Input GST"}), ["Input GST"])
        st.dataframe(view, hide_index=True, column_config=cfg, alt="Input GST by month")
