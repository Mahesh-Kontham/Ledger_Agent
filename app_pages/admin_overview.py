from datetime import date

import streamlit as st

from core import config, db
from ui.components import kpi_card, page_header, section_header

page_header("Overview", "Is the platform healthy and trustworthy? Aggregates only - admins never see users' bills.")

users = db.admin_list_users()
stats = db.admin_bill_stats()
today = date.today().isoformat()
month = today[:7]
real = [s for s in stats if s["status"] != "DUPLICATE"]
auto = [s for s in real if s["status"] == "VERIFIED" and not s["human_reviewed"]]
to_review = [s for s in real if s["status"] in ("NEEDS_REVIEW", "MISSING_DATA") or s["human_reviewed"]]
fails = sum(s["extraction_failed"] for s in stats)

by_role = {r: sum(1 for u in users if u["role"] == r and u["is_active"]) for r in ("BUSINESS", "INDIVIDUAL", "ADMIN")}
k = st.columns(3)
with k[0]:
    kpi_card("Active users", str(sum(by_role.values())),
             f"{by_role['BUSINESS']} business · {by_role['INDIVIDUAL']} individual · {by_role['ADMIN']} admin", key="users")
with k[1]:
    kpi_card("Bills processed", str(sum(1 for s in stats if s["created_at"][:7] == month)),
             f"{sum(1 for s in stats if s['created_at'][:10] == today)} today · this month", key="bills")
with k[2]:
    kpi_card("Auto-verified", f"{len(auto) / len(real):.0%}" if real else "—",
             f"{len(to_review) / len(real):.0%} sent to human review" if real else "No bills yet", key="auto")
k2 = st.columns(3)
with k2[0]:
    kpi_card("Extraction failures", str(fails),
             "Bills the model could not read - routed to MISSING_DATA, never guessed", key="fails")
with k2[1]:
    kpi_card("Fraud checker", "MCP connected" if config.FRAUD_MCP_URL else "Mock",
             config.FRAUD_MCP_URL or "Demo fraud check (mock) - set FRAUD_MCP_URL to connect", key="fraud")
with k2[2]:
    kpi_card("Extraction model", config.LLM_MODEL,
             "API key set" if config.GEMINI_API_KEY else "API key missing - uploads will need manual input", key="model")

section_header("Shortcuts")
with st.container(horizontal=True):
    st.page_link("app_pages/admin_users.py", label="Manage users", icon=":material/group:")
    st.page_link("app_pages/admin_health.py", label="Pipeline health", icon=":material/health_and_safety:")
    st.page_link("app_pages/admin_audit.py", label="Audit log", icon=":material/history:")
