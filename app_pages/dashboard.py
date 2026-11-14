from datetime import date

import streamlit as st

from core import budgets, config, db, ledger
from ui.components import (bill_month, bill_summary_line, empty_state, kpi_card, money, page_header,
                           primary_reason, section_header, status_badge, this_month)

mode = db.get_mode()
user = db.current_user()
month = this_month()
today = date.today()
page_header("Dashboard", f"{user.get('org_name') or user['name']} · {today:%B %Y}. Are the books correct, and is anyone cheating?")

bills = db.list_bills()
queue = db.review_queue()
mb = [b for b in bills if bill_month(b) == month and b.status != "DUPLICATE"]
verified = [b for b in mb if b.status == "VERIFIED"]
verified_amt = sum(b.total_amount_inr or 0 for b in verified)
pct = len(verified) / len(mb) if mb else 0.0
high = sum(1 for b in queue if b.review_priority == "HIGH")
flagged = [b for b in bills if b.status == "NEEDS_REVIEW" and (b.fraud_score or 0) >= config.FRAUD["BUSINESS"]["review"]]
flagged_amt = sum(b.total_amount_inr or 0 for b in flagged)
gst = ledger.gst_summary(mode)
gst_month = float(gst.loc[gst["month"] == month, "input_gst_inr"].sum()) if not gst.empty else 0.0
gst_risk = [b for b in bills if b.status in ("VERIFIED", "NEEDS_REVIEW", "MISSING_DATA")
            and (b.tax_amount or 0) > 0 and not b.gstin]
gst_risk_amt = sum((b.tax_amount or 0) * (b.fx_rate or 1) for b in gst_risk)
unmatched = [b for b in bills if b.status in ("VERIFIED", "NEEDS_REVIEW") and b.match_status == "NO_MATCH"]
brows = budgets.budget_rows(mode, today)
over = [r for r in brows if r["spent_pct"] >= config.BUDGET_BREACH_PCT]
watch = [r for r in brows if r not in over and (r["spent_pct"] >= config.BUDGET_WARNING_PCT or (
    today.day >= config.PACE_MIN_DAY and r["spent_pct"] > config.PACE_FACTOR * r["elapsed_pct"]))]

# ---- one primary action ----
if queue:
    if st.button(f"Review {len(queue)} pending bill{'s' if len(queue) != 1 else ''}"
                 + (f" ({high} high priority)" if high else ""), type="primary", key="primary_cta",
                 icon=":material/fact_check:"):
        st.switch_page("app_pages/review.py")
else:
    if st.button("Add bills", type="primary", key="primary_cta", icon=":material/add_circle:"):
        st.switch_page("app_pages/add_bills.py")

r1 = st.columns(3)
with r1[0]:
    kpi_card("Verified this month", money(verified_amt, 0),
             f"{pct:.0%} of {len(mb)} bill{'s' if len(mb) != 1 else ''} auto-checked and posted" if mb else "No bills this month yet",
             key="verified")
with r1[1]:
    kpi_card("Pending review", str(len(queue)),
             (f"{high} high priority - shown first" if high else "None high priority") if queue else "Queue cleared",
             key="pending")
with r1[2]:
    kpi_card("Flagged fraud risk", money(flagged_amt, 0),
             f"{len(flagged)} bill{'s' if len(flagged) != 1 else ''} held - nothing posted until you decide"
             if flagged else "No bills flagged", key="fraud")
r2 = st.columns(3)
with r2[0]:
    kpi_card("Input GST claimable", money(gst_month, 0),
             (f"{money(gst_risk_amt, 0)} of input GST at risk – {len(gst_risk)} bill{'s' if len(gst_risk) != 1 else ''} missing GSTIN")
             if gst_risk else "No GST at risk", key="gst")
with r2[1]:
    kpi_card("Unmatched bills", str(len(unmatched)),
             "Not found in the bank statement - check before month end" if unmatched else "Every bill matched to a debit",
             key="unmatched")
with r2[2]:
    kpi_card("Budget status",
             f"{len(brows) - len(over) - len(watch)} of {len(brows)} on track" if brows else "No budgets",
             (f"Over: {', '.join(r['category'] for r in over)}. " if over else "")
             + (f"Watch: {', '.join(r['category'] for r in watch)}" if watch else "") or
             ("All within limits" if brows else "Set limits on the Budgets page"), key="budget")

c1, c2 = st.columns([3, 2], gap="large")
with c1:
    section_header("Needs attention", "Highest priority first.")
    if not queue:
        empty_state("Queue cleared", "Nothing is waiting for a decision. New flagged bills will show up here.",
                    ":material/task_alt:")
    for b in queue[:5]:
        with st.container(border=True):
            st.markdown(bill_summary_line(b))
            status_badge(b.status, primary_reason(b), b.review_priority)
with c2:
    section_header("Recent activity")
    recent = list(reversed(bills))[:8]
    if not recent:
        empty_state("No bills yet", "Upload a receipt and we'll check it against your bank.", ":material/receipt_long:")
    for b in recent:
        st.markdown(bill_summary_line(b))
        status_badge(b.status, primary_reason(b))
