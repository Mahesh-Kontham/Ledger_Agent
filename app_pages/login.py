import streamlit as st

from core import auth, db

with st.container(key="login_card"):
    st.title("LedgerTruth")
    st.markdown("##### Your money, verified.")
    st.caption("Every bill is checked against your bank before it touches your books. We never guess numbers.")

    with st.form("login", border=True):
        email = st.text_input("Email", placeholder="you@company.com", autocomplete="username", key="login_email")
        password = st.text_input("Password", type="password", autocomplete="current-password", key="login_pw")
        submitted = st.form_submit_button("Sign in", type="primary", width="stretch", key="login_submit")

    if submitted:
        user = auth.login(email, password)
        if user:
            st.session_state["user"] = user
            st.rerun()
        else:
            st.error("That email and password don't match an active account.")

    demos = db.demo_emails()
    with st.expander("Demo accounts", icon=":material/info:"):
        if demos:
            label = {"BUSINESS": "Business owner", "INDIVIDUAL": "Individual", "ADMIN": "Platform admin"}
            for d in demos:
                st.markdown(f"`{d['email']}` · {label.get(d['role'], d['role'])}")
            st.caption("Passwords are set in your .env file (DEMO_ADMIN_PW, DEMO_BUSINESS_PW, DEMO_USER_PW).")
        else:
            st.caption("No demo accounts yet. Set DEMO_*_PW in .env and run `python scripts/seed_users.py`.")
