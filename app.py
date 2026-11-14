"""LedgerTruth entry point: login gate + role-based navigation (PRD Section 18).

Run:  python -m streamlit run app.py
"""
import streamlit as st

from core import auth, db
from ui.components import inject_css, notification_center

st.set_page_config(page_title="LedgerTruth", page_icon=":material/verified_user:", layout="wide")
db.init_db()
if db.user_count() == 0:          # first run: create the demo accounts from .env
    auth.seed_demo_users()
inject_css()

# ---- session user (re-validated every run; deactivated users are signed out) ----
user = st.session_state.get("user")
if user:
    fresh = db.get_user(user["id"])
    if not fresh or not fresh["is_active"]:
        st.session_state.pop("user", None)
        user = None
    else:
        user = fresh
        st.session_state["user"] = fresh
db.set_current_user(user)


def P(file, title, icon, help, **kw):
    return st.Page(f"app_pages/{file}", title=title, icon=f":material/{icon}:", help=help, **kw)


if not user:
    st.navigation([P("login.py", "Sign in", "login", "Sign in to LedgerTruth.", url_path="login")],
                  position="hidden").run()
    st.stop()

ROLE_PAGES = {
    "INDIVIDUAL": [
        P("home.py", "Home", "home", "Your month at a glance: spending, budgets and anything that needs you.",
          default=True),
        P("add_bills.py", "Add bill", "add_circle", "Upload, scan, forward from email or type in a bill."),
        P("review.py", "Needs you", "task_alt", "Bills we couldn't finish without you. We never guess numbers."),
        P("spending.py", "Spending", "pie_chart", "Where your money went, by category and shop."),
        P("budgets.py", "Budgets", "savings", "Set monthly limits and see how you're pacing."),
        P("settings.py", "Settings", "settings", "Bank statement, account and data."),
    ],
    "BUSINESS": [
        P("dashboard.py", "Dashboard", "dashboard", "Are the books correct and is anyone cheating?", default=True),
        P("add_bills.py", "Add bills", "add_circle", "Upload, scan, fetch email or enter bills manually."),
        P("review.py", "Review queue", "fact_check", "Approve or reject flagged bills. HIGH priority first."),
        P("ledger.py", "Ledger", "menu_book", "Journal, category, merchants, trial balance and GST."),
        P("budgets.py", "Budgets", "savings", "Monthly limits per category with pace alerts."),
        P("reports.py", "Reports & export", "download", "Monthly summary and journal CSV export."),
        P("settings.py", "Settings", "settings", "Bank statement import, account and data."),
    ],
    "ADMIN": [
        P("admin_overview.py", "Overview", "monitoring", "Platform health at a glance.", default=True),
        P("admin_users.py", "Users", "group", "Create, list and deactivate users."),
        P("admin_health.py", "Pipeline health", "health_and_safety", "Status mix, fraud scores and thresholds."),
        P("admin_audit.py", "Audit log", "history", "Who did what, newest first."),
    ],
}
ROLE_NAME = {"INDIVIDUAL": "Personal", "BUSINESS": "Business", "ADMIN": "Admin"}


def _logout():
    db.log_action("logout", user["email"])
    for k in list(st.session_state.keys()):
        del st.session_state[k]


with st.sidebar:
    st.markdown("### LedgerTruth")
    st.caption("Your money, verified.")
    with st.container(border=True):
        st.markdown(f"**{user['name']}**")
        st.caption(user.get("org_name") or user["email"])
        st.badge(ROLE_NAME[user["role"]], icon=":material/badge:", color="blue")
    notif_slot = st.container() if user["role"] != "ADMIN" else None
    st.button("Sign out", icon=":material/logout:", on_click=_logout, width="stretch")

page = st.navigation(ROLE_PAGES[user["role"]], position="sidebar")
try:
    page.run()
finally:
    # Filled after the page ran, so alerts created on this page load (posting, approving,
    # saving budgets) are already counted - the bell is always in sync.
    if notif_slot is not None:
        with notif_slot:
            n = db.review_queue_count()
            st.caption(("Nothing needs you" if n == 0 else f"{n} bill{'s' if n != 1 else ''} need{'s' if n == 1 else ''} you")
                       if user["role"] == "INDIVIDUAL" else f"Review queue: {n}")
            notification_center()
