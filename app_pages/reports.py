import streamlit as st

from core import db, ledger
from ui.components import empty_state, fmt_date, kpi_card, month_label, money, money_table, page_header, section_header

mode = db.get_mode()
page_header("Reports & export", "A monthly summary for your accountant, and the full journal as CSV.")

months = ledger.months(mode)
if not months:
    empty_state("Nothing to report yet", "Once bills are verified and posted, monthly reports appear here.",
                ":material/summarize:")
    st.stop()

month = st.selectbox("Month", months, format_func=month_label, width=220)
jdf = ledger.journal_df(mode, month)
cdf = ledger.category_totals(mode, month)
gst = ledger.gst_summary(mode)
gst_m = float(gst.loc[gst["month"] == month, "input_gst_inr"].sum()) if not gst.empty else 0.0
cols = ["entry_id", "entry_date", "account", "debit", "credit", "note", "bill_id"]

st.download_button(f"Download journal CSV ({month_label(month)})",
                   jdf[cols].to_csv(index=False).encode("utf-8"), file_name=f"journal_{month}.csv",
                   mime="text/csv", type="primary", key="primary_cta", icon=":material/download:")

k = st.columns(3)
with k[0]:
    kpi_card("Total expenses", money(cdf["total_inr"].sum() if not cdf.empty else 0), "All Expense accounts", key="r_exp")
with k[1]:
    kpi_card("Input GST", money(gst_m), "Claimable this month", key="r_gst")
with k[2]:
    kpi_card("Entries posted", str(jdf["entry_id"].nunique()), "Balanced journal entries", key="r_n")

section_header("By category")
view, cfg = money_table(cdf.rename(columns={"category": "Category", "total_inr": "Total"}), ["Total"])
st.dataframe(view, hide_index=True, column_config=cfg, alt="Expenses by category for the month")

with st.expander("Preview journal lines"):
    view, cfg = money_table(jdf[cols].rename(columns={"entry_id": "Entry", "entry_date": "Date", "account": "Account",
                                                     "debit": "Debit", "credit": "Credit", "note": "Note",
                                                     "bill_id": "Bill"}), ["Debit", "Credit"], ["Date"])
    st.dataframe(view, hide_index=True, column_config=cfg, alt="Journal preview")

st.download_button("Download full journal CSV (all months)",
                   ledger.journal_df(mode)[cols].to_csv(index=False).encode("utf-8"),
                   file_name="journal_all.csv", mime="text/csv", icon=":material/download:", key="all_csv")
