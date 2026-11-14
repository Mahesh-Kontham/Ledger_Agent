import pandas as pd
import streamlit as st

from core import db
from ui.components import empty_state, fmt_date, page_header

page_header("Audit log", "Every sign-in, upload, approval, rejection, budget change and CSV import. Newest first.")

log = db.admin_audit_log()
if not log:
    empty_state("No activity yet", "Actions appear here as soon as someone signs in.", ":material/history:")
    st.stop()

df = pd.DataFrame(log)
with st.container(horizontal=True, vertical_alignment="bottom"):
    actions = st.multiselect("Action", sorted(df["action"].unique()), placeholder="All actions")
    who = st.selectbox("User", ["Everyone"] + sorted(df["email"].dropna().unique()))
    text = st.text_input("Search target", placeholder="e.g. bill #4")
if actions:
    df = df[df["action"].isin(actions)]
if who != "Everyone":
    df = df[df["email"] == who]
if text:
    df = df[df["target"].fillna("").str.contains(text, case=False, regex=False)]

df = df.assign(When=[fmt_date(x) for x in df["created_at"]])[["When", "email", "role", "action", "target"]]
st.caption(f"{len(df)} event{'s' if len(df) != 1 else ''}")
st.dataframe(df.rename(columns={"email": "User", "role": "Role", "action": "Action", "target": "Target"}),
             hide_index=True, alt="Audit log events")
