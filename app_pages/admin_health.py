import pandas as pd
import streamlit as st

from core import config, db
from ui.components import empty_state, kpi_card, page_header, section_header

page_header("Pipeline health", "How bills move through extract → verify → route, across all users (counts only).")

stats = db.admin_bill_stats()
if not stats:
    empty_state("No bills processed yet", "Once users add bills, the status mix and fraud scores show up here.",
                ":material/health_and_safety:")
else:
    order = ["VERIFIED", "NEEDS_REVIEW", "MISSING_DATA", "DUPLICATE", "REJECTED"]
    counts = pd.DataFrame({"Status": order, "Bills": [sum(1 for s in stats if s["status"] == o) for o in order]})
    scores = [s["fraud_score"] for s in stats if s["fraud_score"] is not None]
    k = st.columns(3)
    with k[0]:
        kpi_card("Bills processed", str(len(stats)), "All time, all users", key="h_n")
    with k[1]:
        kpi_card("Average fraud score", f"{sum(scores) / len(scores):.0f}" if scores else "—",
                 "0-100 · demo mock unless MCP is configured", key="h_fraud")
    with k[2]:
        hi = sum(1 for s in scores if s >= 70)
        kpi_card("High fraud risk", str(hi), "Score ≥ 70 - always held for a human", key="h_hi")
    section_header("Status breakdown")
    st.bar_chart(counts, x="Status", y="Bills", sort=False, height=300,
                 alt="Number of bills per pipeline status")
    match = pd.Series([s["match_status"] or "—" for s in stats]).value_counts().rename_axis("Bank match").reset_index(name="Bills")
    st.dataframe(match, hide_index=True, alt="Bills by bank match result")

section_header("Thresholds (read-only)", "From core/config.py - copied exactly from the PRD. Change them in code, not here.")
rows = [
    ("Confidence threshold", config.CONFIDENCE_THRESHOLD),
    ("Match date window (days)", config.MATCH_DATE_WINDOW_DAYS),
    ("Tolerance", f"max(₹{config.TOLERANCE_ABS_INR:.2f}, {config.TOLERANCE_PCT:.0%})"),
    ("Card fee band", f"max(₹{config.CARD_FEE_MAX_ABS_INR:.2f}, {config.CARD_FEE_MAX_PCT:.0%})"),
    ("Forex markup max", f"{config.FOREX_MARKUP_MAX_PCT:.0%}"),
    ("Fraud - individual", f"warn ≥ {config.FRAUD['INDIVIDUAL']['warn']}, review ≥ {config.FRAUD['INDIVIDUAL']['review']}"),
    ("Fraud - business", f"review ≥ {config.FRAUD['BUSINESS']['review']}, high ≥ {config.FRAUD['BUSINESS']['high']}"),
    ("Mandatory - individual", ", ".join(config.MANDATORY_FIELDS["INDIVIDUAL"])),
    ("Mandatory - business", ", ".join(config.MANDATORY_FIELDS["BUSINESS"]) + " (+ gstin if tax > 0)"),
    ("Budget pace", f"spent% > {config.PACE_FACTOR} × elapsed%, from day {config.PACE_MIN_DAY}"),
    ("Budget warning / breach", f"{config.BUDGET_WARNING_PCT:.0%} / {config.BUDGET_BREACH_PCT:.0%}"),
    ("Spike anomaly", f"> {config.SPIKE_FACTOR}× 30-day avg, needs ≥ {config.SPIKE_MIN_HISTORY} bills"),
    ("New merchant high amount", f"≥ ₹{config.NEW_MERCHANT_HIGH_AMOUNT_INR:,}"),
    ("Subscription increase", f"> {config.SUBSCRIPTION_INCREASE_PCT:.0%}"),
    ("FX (sample rates)", ", ".join(f"{k} {v}" for k, v in config.FX_TABLE.items()) + f" · as of {config.FX_TABLE_DATE}"),
]
st.table(pd.DataFrame(rows, columns=["Setting", "Value"]).astype(str).set_index("Setting"))
