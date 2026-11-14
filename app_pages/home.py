from datetime import date

import streamlit as st

from core import budgets, config, db, ledger
from ui.components import (empty_state, kpi_card, money, month_label, page_header, section_header,
                           this_month)

mode = db.get_mode()
user = db.current_user()
today = date.today()
month = this_month()

cat = ledger.category_totals(mode, month)
spent = float(cat["total_inr"].sum()) if not cat.empty else 0.0
brows = budgets.budget_rows(mode, today)
left = sum(max(r["limit"] - r["spent"], 0) for r in brows)
need = db.review_queue_count()
over = [r for r in brows if r["spent_pct"] >= config.BUDGET_BREACH_PCT]
ahead = [r for r in brows if r not in over and (r["spent_pct"] >= config.BUDGET_WARNING_PCT or (
    today.day >= config.PACE_MIN_DAY and r["spent_pct"] > config.PACE_FACTOR * r["elapsed_pct"]))]

if over:
    mood = f"{over[0]['category']} is over its limit - no stress, it's just worth knowing."
elif ahead:
    mood = f"mostly on track. {ahead[0]['category']} is moving a little faster than usual."
elif brows:
    mood = "on track."
else:
    mood = "set a budget to see how you're pacing."

page_header(f"Hi {user['name'].split()[0]}", f"{month_label(month)} · day {today.day}")
st.markdown(f"### You've spent {money(spent, 0)} this month – {mood}")

if st.button("Add a bill", type="primary", key="primary_cta", icon=":material/add_circle:", width="stretch"):
    st.switch_page("app_pages/add_bills.py")

k = st.columns(3)
with k[0]:
    kpi_card("Spent this month", money(spent, 0), "Only checked bills are counted", key="spent")
with k[1]:
    kpi_card("Left in budgets", money(left, 0) if brows else "—",
             f"Across {len(brows)} budget{'s' if len(brows) != 1 else ''}" if brows else "No budgets yet", key="left")
with k[2]:
    kpi_card("Bills needing you", str(need), "We never guess numbers - a quick look finishes them" if need
             else "Nothing needs you", key="need")
if need:
    st.page_link("app_pages/review.py", label=f"Finish {need} bill{'s' if need != 1 else ''}", icon=":material/arrow_forward:")

c1, c2 = st.columns([3, 2], gap="large")
with c1:
    section_header("Budgets", "The bar is what you've spent; 'expected' is where you'd be at an even pace.")
    if not brows:
        empty_state("No budgets yet", "Set a monthly limit for things like Food or Transport, and we'll keep an eye on the pace for you.",
                    ":material/savings:")
        st.page_link("app_pages/budgets.py", label="Set a budget", icon=":material/arrow_forward:")
    for r in brows:
        pct = r["spent_pct"]
        label = ("Over limit" if pct >= 1 else "Moving faster than usual" if r in ahead else "On track")
        st.progress(min(pct, 1.0), text=f"**{r['category']}** · {money(r['spent'], 0)} of {money(r['limit'], 0)} · {label}")
        st.caption(f"Expected by today: {r['elapsed_pct']:.0%} · used: {pct:.0%}")
with c2:
    section_header("Where it went", "Top shops this month")
    g = ledger.merchant_groups(mode)
    if g.empty:
        empty_state("No spending yet", "Upload a receipt and we'll check it against your bank.", ":material/receipt_long:")
    for _, r in g.head(5).iterrows():
        with st.container(horizontal=True, vertical_alignment="center"):
            st.markdown(f"**{r['merchant']}**")
            st.caption(f"{r['bills']} bill{'s' if r['bills'] != 1 else ''}")
            st.markdown(money(r["total_inr"], 0), width="content", text_alignment="right")
