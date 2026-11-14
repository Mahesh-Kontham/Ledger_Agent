from pathlib import Path

import streamlit as st

from core import config, db, extract
from core.pipeline import approve_bill, reject_bill, submit_missing_fields
from ui.components import (FIELD_LABEL, bill_details, bill_summary_line, empty_state, fmt_date, is_individual,
                           money, page_header, reason_list, reasons_for, status_badge, three_way_compare,
                           toast_once)

ind = is_individual()
page_header("Needs you" if ind else "Review queue",
            "Bills we couldn't finish on our own. We never guess numbers." if ind else
            "Approve or reject flagged bills. HIGH priority first, then oldest.")

flash = st.session_state.pop("rq_flash", None)
if flash:
    getattr(st, flash[0])(flash[1])
toast_once(st.session_state.pop("rq_alerts", None))

queue = db.review_queue()
if not queue:
    empty_state("You're all caught up" if ind else "Queue cleared",
                "Nothing needs you right now. New bills that need a decision will appear here." if ind else
                "Every bill is either posted, rejected or set aside as a duplicate. Add more bills to keep going.",
                ":material/task_alt:")
    st.stop()

ids = [b.id for b in queue]
sel = st.session_state.get("review_sel")
if sel not in ids:
    sel = ids[0]
bill = next(b for b in queue if b.id == sel)


def pick(bid):
    st.session_state["review_sel"] = bid


def done(kind, msg, alerts=None):
    st.session_state["rq_flash"] = (kind, msg)
    st.session_state["rq_alerts"] = alerts or []
    st.session_state.pop("review_sel", None)


left, right = st.columns([2, 5], gap="large")

with left:
    st.caption(f"{len(queue)} waiting")
    for b in queue:
        tag = ("High priority · " if b.review_priority == "HIGH" and not ind else "")
        amt = money(b.total_amount_inr, 0) if b.total_amount_inr is not None else "amount missing"
        st.button(f"{b.merchant_normalized or 'Unknown shop'} · {amt}", key=f"qsel_{b.id}", width="stretch",
                  type="primary" if b.id == sel else "secondary", on_click=pick, args=(b.id,),
                  icon=":material/priority_high:" if b.review_priority == "HIGH" and not ind else None)
        st.caption(tag + (reasons_for(b)[0][:70] if reasons_for(b) else ""))

with right:
    st.markdown(bill_summary_line(bill) + f" · #{bill.id} · added {fmt_date(bill.created_at)}")
    status_badge(bill.status, None, bill.review_priority if not ind else None)
    img_col, info_col = st.columns([2, 3], gap="medium")

    with img_col:
        if bill.file_path and Path(bill.file_path).exists():
            if bill.file_path.lower().endswith(".pdf"):
                img, _ = extract.image_for_llm(bill.file_path)
                st.image(img, caption="PDF page 1", width="stretch")
            else:
                st.image(bill.file_path, width="stretch")
        else:
            empty_state("No document", "This bill was typed in by hand.", ":material/edit_document:")

    with info_col:
        with st.container(border=True):
            st.markdown("**Why it's here**")
            reason_list(reasons_for(bill))
        if bill.fraud_signals and bill.source != "manual":
            high = (bill.fraud_score or 0) >= 70
            with st.container(border=True):
                with st.container(horizontal=True, vertical_alignment="center"):
                    st.markdown("**Fraud signals**")
                    st.badge(f"Risk {bill.fraud_score}%", color="red" if high else "orange",
                             icon=":material/gpp_maybe:")
                reason_list(bill.fraud_signals)
                if not config.FRAUD_MCP_URL:
                    st.caption("Demo fraud check (mock)")

    st.markdown("**You entered · Invoice · Bank debited**")
    three_way_compare(bill)

    if bill.status == "NEEDS_REVIEW":
        a, r = st.columns(2)
        if a.button("Looks right - add it" if ind else "Approve and post", type="primary", key="approve_btn",
                    icon=":material/check_circle:", width="stretch"):
            b = approve_bill(bill.id, reviewer=db.current_user()["email"])
            db.log_action("approve", f"bill #{b.id}")
            done("success", "Added to your books." if ind else f"Bill #{b.id} approved and posted to the ledger.",
                 b.new_alerts)
            st.rerun()
        if r.button("Not mine - reject" if ind else "Reject", key="reject_btn", icon=":material/block:",
                    width="stretch"):
            reject_bill(bill.id, reviewer=db.current_user()["email"])
            db.log_action("reject", f"bill #{bill.id}")
            done("info", "Rejected. It won't be counted." if ind else f"Bill #{bill.id} rejected - never posted.")
            st.rerun()
    else:  # MISSING_DATA: only the missing fields
        n = len(bill.missing_fields)
        st.info(f"We never guess numbers. {n} field{'s' if n != 1 else ''} need{'' if n != 1 else 's'} you.",
                icon=":material/verified_user:")
        with st.form(f"fill_{bill.id}"):
            vals = {}
            for f in bill.missing_fields:
                label = FIELD_LABEL.get(f, f).capitalize() if ind else f
                k = f"{f}_{bill.id}"
                if f in ("total_amount", "tax_amount"):
                    vals[f] = st.number_input(label, min_value=0.0, value=None, step=1.0, format="%.2f", key=k)
                elif f == "bill_date":
                    d = st.date_input(label, value=None, format="DD/MM/YYYY", key=k)
                    vals[f] = d.isoformat() if d else None
                elif f == "currency":
                    vals[f] = st.selectbox(label, list(config.FX_TABLE), index=None, key=k)
                elif f == "payment_mode":
                    vals[f] = st.selectbox(label, config.PAYMENT_MODES, index=None, key=k)
                else:
                    vals[f] = st.text_input(label, key=k) or None
            c1, c2 = st.columns(2)
            submitted = c1.form_submit_button("Save and re-check", type="primary", width="stretch",
                                              key="approve_btn")
            rejected = c2.form_submit_button("Reject bill", width="stretch", key="reject_btn")
        if submitted:
            if not vals or any(v is None for v in vals.values()):
                st.error("Fill in every field above, or reject the bill.")
            else:
                b = submit_missing_fields(bill.id, vals)
                db.log_action("complete_fields", f"bill #{b.id}: {', '.join(vals)} -> {b.status}")
                done("success" if b.status == "VERIFIED" else "info",
                     f"Re-checked: {reasons_for(b)[0] if reasons_for(b) else b.status}", b.new_alerts)
                st.rerun()
        if rejected:
            reject_bill(bill.id, reviewer=db.current_user()["email"])
            db.log_action("reject", f"bill #{bill.id}")
            done("info", f"Bill #{bill.id} rejected.")
            st.rerun()

    bill_details(bill)
