import pandas as pd
import streamlit as st

from core import auth, db
from ui.components import fmt_date, page_header, section_header

page_header("Users", "Everyone on the platform. Deactivated users can't sign in; their data is kept.")

flash = st.session_state.pop("usr_flash", None)
if flash:
    getattr(st, flash[0])(flash[1])

users = db.admin_list_users()
df = pd.DataFrame([{"Name": u["name"], "Email": u["email"], "Role": u["role"].title(), "Org": u["org_name"] or "—",
                    "Bills": u["bills"], "Last active": fmt_date(u["last_active"]) if u["last_active"] else "Never",
                    "Status": "Active" if u["is_active"] else "Deactivated"} for u in users])
st.dataframe(df, hide_index=True, alt="Users",
             column_config={"Bills": st.column_config.NumberColumn("Bills", alignment="right")})

c1, c2 = st.columns(2, gap="large")
with c1:
    section_header("Create user")
    with st.form("new_user"):
        name = st.text_input("Full name")
        email = st.text_input("Email")
        role = st.segmented_control("Role", ["BUSINESS", "INDIVIDUAL", "ADMIN"], default="BUSINESS",
                                    format_func=str.title)
        org = st.text_input("Organisation (business users)")
        pw = st.text_input("Temporary password (min 8 characters)", type="password")
        if st.form_submit_button("Create user", type="primary", key="primary_cta", icon=":material/person_add:"):
            try:
                auth.create_user(name, email, pw, role or "BUSINESS", org)
                db.log_action("user_create", f"{email.strip().lower()} ({role})")
                st.session_state["usr_flash"] = ("success", f"Created {email}.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))
with c2:
    section_header("Activate or deactivate")
    me = db.current_user()["id"]
    others = [u for u in users if u["id"] != me]
    if others:
        target = st.selectbox("User", others, format_func=lambda u: f"{u['email']} · "
                              + ("active" if u["is_active"] else "deactivated"))
        label = "Deactivate" if target["is_active"] else "Reactivate"
        if st.button(label, icon=":material/person_off:" if target["is_active"] else ":material/person:",
                     key="toggle_user"):
            db.admin_set_user_active(target["id"], not target["is_active"])
            db.log_action("user_deactivate" if target["is_active"] else "user_reactivate", target["email"])
            st.session_state["usr_flash"] = ("success", f"{label}d {target['email']}.")
            st.rerun()
