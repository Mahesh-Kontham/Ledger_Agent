from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import budgets, config, db
from ui.components import (alert_list, empty_state, is_individual, money, page_header, section_header,
                           toast_once)

ind = is_individual()
mode = db.get_mode()
today = date.today()
page_header("Budgets", f"{today:%B %Y} · day {today.day} of the month. "
            + ("Set a limit and we'll tell you calmly if you're spending faster than usual." if ind else
               "Monthly limits per category, with pace, warning and breach alerts."))

flash = st.session_state.pop("bud_flash", None)
if flash:
    st.success(flash)
toast_once(st.session_state.pop("bud_alerts", None))

rows = {r["category"]: r for r in budgets.budget_rows(mode, today)}
spent = {c: budgets.category_spent(c, mode, today.year, today.month) for c in config.CATEGORIES}


def status_text(cat):
    r = rows.get(cat)
    if not r:
        return "No limit"
    if r["spent_pct"] >= config.BUDGET_BREACH_PCT:
        return "Over budget"
    if r["spent_pct"] >= config.BUDGET_WARNING_PCT:
        return f"{r['spent_pct']:.0%} used"
    if today.day >= config.PACE_MIN_DAY and r["spent_pct"] > config.PACE_FACTOR * r["elapsed_pct"]:
        return "Ahead of pace"
    return "On track"


ordered = sorted(config.CATEGORIES, key=lambda c: (c not in rows and spent[c] == 0, config.CATEGORIES.index(c)))
df = pd.DataFrame([{"Category": c, "Monthly limit ₹": rows[c]["limit"] if c in rows else None,
                    "Spent": money(spent[c], 0), "Status": status_text(c)} for c in ordered])

section_header("Your limits" if ind else "Limits", "Edit the limit column. Leave it empty for no budget.")
edited = st.data_editor(
    df, hide_index=True, key="budget_editor", disabled=["Category", "Spent", "Status"],
    alt="Monthly budget limits by category",
    column_config={
        "Monthly limit ₹": st.column_config.NumberColumn("Monthly limit ₹", min_value=0, step=100, format="%.0f"),
        "Spent": st.column_config.TextColumn("Spent this month", alignment="right"),
    })
if st.button("Save budgets", type="primary", key="primary_cta", icon=":material/save:"):
    changes = []
    for _, r in edited.iterrows():
        cat, lim = r["Category"], r["Monthly limit ₹"]
        old = rows[cat]["limit"] if cat in rows else None
        lim = None if lim is None or pd.isna(lim) or lim <= 0 else float(lim)
        if lim != old:
            if lim:
                db.upsert_budget(cat, lim, mode)
            else:
                db.delete_budget(cat, mode)
            changes.append(f"{cat}: {money(old, 0) if old else 'none'} -> {money(lim, 0) if lim else 'none'}")
    if changes:
        db.log_action("budget_change", "; ".join(changes))
    st.session_state["bud_alerts"] = budgets.run_budget_checks(mode, today)
    st.session_state["bud_flash"] = "Budgets saved." if changes else "No changes."
    st.rerun()

section_header("This month so far", "Spent, projected month-end at the current pace, and your limit.")
br = budgets.budget_rows(mode, today)
if not br:
    empty_state("No limits yet", "Add a monthly limit above - for example Transport ₹5,000 - and we'll track your pace.",
                ":material/savings:")
else:
    cats = [r["category"] for r in br]
    fig = go.Figure()
    fig.add_bar(name="Spent", x=cats, y=[r["spent"] for r in br], marker_color="#2F5BEA")
    fig.add_bar(name="Projected month-end", x=cats, y=[r["projected"] for r in br], marker_color="#93A8F4")
    fig.add_scatter(name="Limit", x=cats, y=[r["limit"] for r in br], mode="markers",
                    marker=dict(symbol="line-ew-open", size=56, line=dict(width=4, color="#64708A")))
    fig.update_layout(barmode="group", yaxis_title="₹", height=380, margin=dict(t=10, b=10, l=10, r=10),
                      legend=dict(orientation="h", y=1.12), separators=".,")
    st.plotly_chart(fig, width="stretch")

c1, c2 = st.columns(2, gap="large")
with c1:
    section_header("Budget alerts")
    ba = db.list_alerts(["BUDGET_PACE", "BUDGET_WARNING", "BUDGET_BREACH"])
    if ba:
        alert_list(ba[:10])
    else:
        st.caption("No alerts. We'll let you know if a category runs ahead of the month.")
with c2:
    section_header("Unusual spending" if ind else "Anomalies")
    an = db.list_alerts(["ANOMALY"])
    if an:
        alert_list(an[:10])
    else:
        st.caption("Nothing unusual spotted. We look for spikes, new big merchants, repeats and price rises.")
