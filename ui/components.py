"""Reusable LedgerTruth UI components (design system, PRD Section 18).

Status colours are used ONLY for status: green = verified, orange (amber) = needs you / missing data,
gray = duplicate, red = rejected / high fraud risk. Everything else uses the single accent colour.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Optional

import streamlit as st

from core import config, db
from core.extract import extract_fields
from core.models import Bill
from core.pipeline import process_bill
from core.verify import indian_number

ROOT = Path(__file__).resolve().parent.parent

STATUS_STYLE = {
    "VERIFIED": ("green", ":material/verified:"),
    "NEEDS_REVIEW": ("orange", ":material/visibility:"),
    "MISSING_DATA": ("orange", ":material/edit_note:"),
    "DUPLICATE": ("gray", ":material/content_copy:"),
    "REJECTED": ("red", ":material/block:"),
}
STATUS_LABEL = {
    "INDIVIDUAL": {"VERIFIED": "Verified", "NEEDS_REVIEW": "Needs you", "MISSING_DATA": "Needs you",
                   "DUPLICATE": "Duplicate", "REJECTED": "Rejected"},
    "BUSINESS": {"VERIFIED": "Verified", "NEEDS_REVIEW": "Needs review", "MISSING_DATA": "Missing data",
                 "DUPLICATE": "Duplicate", "REJECTED": "Rejected"},
}
FIELD_LABEL = {"merchant": "shop name", "bill_date": "date", "total_amount": "total", "currency": "currency",
               "payment_mode": "payment method", "invoice_number": "invoice number", "tax_amount": "tax amount",
               "gstin": "GSTIN", "fx_rate": "exchange rate"}


# ---------------- formatting ----------------
def money(x: Optional[float], decimals: int = 2) -> str:
    """₹ with Indian digit grouping: money(123456) -> '₹1,23,456.00'."""
    if x is None:
        return "—"
    return f"₹{indian_number(round(float(x), decimals), decimals)}"


def fmt_date(d: Optional[str]) -> str:
    """'2026-11-14' (or ISO datetime) -> '14 Nov 2026'."""
    if not d:
        return "—"
    try:
        dt = datetime.fromisoformat(d) if "T" in d else datetime.combine(date.fromisoformat(d[:10]), datetime.min.time())
        return f"{dt.day} {dt:%b %Y}" + (f", {dt:%H:%M}" if "T" in d else "")
    except ValueError:
        return d


def month_label(m: str) -> str:
    """'2026-11' -> 'Nov 2026'."""
    try:
        return datetime.strptime(m[:7], "%Y-%m").strftime("%b %Y")
    except ValueError:
        return m


def role() -> str:
    u = db.current_user() or {}
    return u.get("role", "INDIVIDUAL")


def is_individual() -> bool:
    return role() == "INDIVIDUAL"


def this_month() -> str:
    return date.today().strftime("%Y-%m")


def bill_month(b: Bill) -> str:
    return (b.bill_date or b.created_at or "")[:7]


def money_table(df, money_cols: Iterable[str], date_cols: Iterable[str] = ()):
    """Format ₹ columns as Indian-grouped strings (right-aligned) and dates as '14 Nov 2026'.
    Returns (df, column_config) for st.dataframe."""
    df = df.copy()
    cfg = {}
    for c in money_cols:
        if c in df.columns:
            df[c] = [("" if v is None or v != v or (isinstance(v, (int, float)) and v == 0 and c in ("debit", "credit", "Debit", "Credit"))
                      else money(v)) for v in df[c]]
            cfg[c] = st.column_config.TextColumn(c.replace("_", " ").capitalize(), alignment="right")
    for c in date_cols:
        if c in df.columns:
            df[c] = [fmt_date(v) for v in df[c]]
            cfg[c] = st.column_config.TextColumn(c.replace("_", " ").capitalize())
    return df, cfg


# ---------------- layout primitives ----------------
def inject_css() -> None:
    st.html(ROOT / "assets" / "styles.css")


def page_header(title: str, subtitle: str) -> None:
    st.title(title)
    st.caption(subtitle)


def section_header(title: str, subtitle: Optional[str] = None) -> None:
    st.subheader(title)
    if subtitle:
        st.caption(subtitle)


def kpi_card(label: str, value: str, caption: Optional[str] = None, *, key: str,
             help: Optional[str] = None) -> None:
    with st.container(border=True, key=f"kpi_{key}", height="stretch"):
        st.metric(label, value, help=help)
        st.caption(caption or " ")


def empty_state(title: str, body: str, icon: str = ":material/inbox:") -> None:
    with st.container(border=True):
        st.markdown(f"#### {icon} {title}")
        st.caption(body)


def status_badge(status: str, reason: Optional[str] = None, priority: Optional[str] = None) -> None:
    """Badge + its reason text. A status is never shown without a reason."""
    color, icon = STATUS_STYLE.get(status, ("gray", ":material/help:"))
    label = STATUS_LABEL.get(role(), STATUS_LABEL["BUSINESS"]).get(status, status)
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        st.badge(label, icon=icon, color=color)
        if priority == "HIGH":
            st.badge("High priority", icon=":material/priority_high:", color="red")
        if reason:
            st.caption(reason)


def reason_list(reasons: Iterable[str]) -> None:
    items = [r for r in reasons if r]
    if items:
        st.markdown("\n".join(f"- {r}" for r in items))


# ---------------- plain-language reasons (individual) ----------------
def match_label(b: Bill) -> str:
    ind = is_individual()
    v = b.variance_inr
    if b.match_status == "MATCHED":
        return "Checked against your bank" if ind else f"Matched to bank debit #{b.matched_transaction_id}"
    if b.match_status == "VARIANCE_EXPLAINED":
        if b.variance_reason == "Forex markup":
            return (f"Paid in {b.currency}; the extra {money(v)} is your bank's conversion fee" if ind
                    else f"Forex markup {money(v)} vs debit #{b.matched_transaction_id}")
        if (b.variance_reason or "").startswith("Probable card fee"):
            return (f"Your bank charged {money(v)} more, probably a card fee. Worth a quick check." if ind
                    else f"Probable card fee {money(v)} vs debit #{b.matched_transaction_id} (confirm)")
        return f"{money(v)} difference explained: {b.variance_reason}"
    if b.match_status == "VARIANCE_UNEXPLAINED":
        return (f"Your bank charged a different amount ({money(abs(v or 0))} gap) and we can't tell why" if ind
                else f"{b.variance_reason} vs debit #{b.matched_transaction_id}")
    if b.match_status == "NO_MATCH":
        return "Not in your bank statement yet" if ind else "No bank/card debit found"
    return ""


def plain_reasons(b: Bill) -> list[str]:
    """Calm, jargon-free reasons for INDIVIDUAL users, derived from the stored check results."""
    out: list[str] = []
    approved = any(r.startswith("Approved by") for r in b.status_reasons)
    if b.status == "DUPLICATE":
        out.append(f"You've already added this bill (#{b.duplicate_of}). We kept the copy aside so it isn't counted twice.")
    elif b.status == "MISSING_DATA":
        if any("Extraction failed" in r for r in b.status_reasons):
            out.append("We couldn't read this image clearly.")
        n = len(b.missing_fields) or 1
        fields = ", ".join(FIELD_LABEL.get(f, f) for f in b.missing_fields) or "exchange rate"
        out.append(f"We never guess numbers. {n} field{'s' if n > 1 else ''} need{'' if n > 1 else 's'} you: {fields}.")
    elif b.status == "NEEDS_REVIEW":
        if (b.fraud_score or 0) >= 40:
            sig = "; ".join(b.fraud_signals) or "unusual file details"
            out.append(f"This image may have been edited ({sig}). Take a quick look before we add it.")
        elif b.match_status in ("VARIANCE_UNEXPLAINED", "NO_MATCH"):
            out.append(match_label(b) + ".")
    elif b.status == "REJECTED":
        out.append("You rejected this bill. It isn't counted anywhere.")
    else:  # VERIFIED
        if approved:
            out.append("You checked and approved this bill.")
        if b.match_status:
            ml = match_label(b)
            out.append(ml if ml.endswith(".") else ml + ".")
        if any(r.startswith("Fraud risk warning") for r in b.status_reasons):
            out.append("Small chance the image was altered. We added it, but keep an eye on it.")
    return out or list(b.status_reasons)


def reasons_for(b: Bill) -> list[str]:
    return plain_reasons(b) if is_individual() else list(b.status_reasons)


def primary_reason(b: Bill) -> str:
    r = reasons_for(b)
    return r[0] if r else ""


# ---------------- bill pieces ----------------
def three_way_compare(b: Bill) -> None:
    txn = db.get_transaction(b.matched_transaction_id)
    inv = (money(b.total_amount) if b.currency in (None, "INR") else
           f"{b.currency} {indian_number(b.total_amount)}" if b.total_amount is not None else "—")
    with st.container(horizontal=True, gap="small"):
        for label, val, cap in [
            ("You entered", money(b.user_entered_amount) if b.user_entered_amount is not None else "—",
             "What you remember paying"),
            ("Invoice", inv, "Printed on the bill"),
            ("Bank debited", money(txn.amount_inr) if txn else "—",
             f"{txn.account_name}, {fmt_date(txn.txn_date)}" if txn else "No matching debit"),
        ]:
            with st.container(border=True):
                st.metric(label, val)
                st.caption(cap)


def bill_summary_line(b: Bill) -> str:
    amt = money(b.total_amount_inr) if b.total_amount_inr is not None else (
        f"{b.currency or ''} {b.total_amount}" if b.total_amount is not None else "amount missing")
    return f"**{b.merchant_normalized or 'Unknown shop'}** · {fmt_date(b.bill_date)} · {amt}"


def bill_details(b: Bill) -> None:
    """Progressive disclosure: technical details inside an expander."""
    with st.expander("Details"):
        ind = is_individual()
        cols = st.columns(4)
        cols[0].markdown(f"**{'Shop' if ind else 'Merchant'}**  \n{b.merchant_normalized or '—'} · {b.category or '—'}")
        cols[1].markdown(f"**Date**  \n{fmt_date(b.bill_date)}")
        cols[2].markdown(f"**Total**  \n{b.currency or ''} {indian_number(b.total_amount) if b.total_amount is not None else '— (not read)'}")
        cols[3].markdown(f"**Paid by**  \n{(b.payment_mode or '—').title() if ind else (b.payment_mode or '—')}")
        if b.currency and b.currency != config.BASE_CURRENCY and b.fx_rate:
            st.caption(f"{b.currency} {b.total_amount} × {b.fx_rate} (sample rate, {fmt_date(b.fx_rate_date)}) "
                       f"= {money(b.total_amount_inr)} · source: {b.fx_source}")
        if b.source == "manual":
            st.caption("Fraud check: manual entry, no document")
        else:
            label = "Demo fraud check (mock)" if not config.FRAUD_MCP_URL else "Fraud check (MCP)"
            st.caption(f"{label}: score {b.fraud_score} · {'; '.join(b.fraud_signals) or 'no signals'}")
        if b.match_status:
            st.caption(f"Bank match: {match_label(b)}")
        if not ind:
            st.caption("Pipeline reasons: " + " | ".join(b.status_reasons))
        if b.field_confidence:
            st.dataframe(
                [{"field": FIELD_LABEL.get(f, f) if ind else f,
                  "value": str(b.merchant_raw if f == "merchant" else getattr(b, f, None)),
                  "confidence": c} for f, c in b.field_confidence.items()],
                hide_index=True, alt="Extracted fields and confidence",
                column_config={"confidence": st.column_config.ProgressColumn("confidence", min_value=0.0,
                                                                            max_value=1.0, format="%.2f")})
        if not ind:
            with st.popover("Raw DB record"):
                st.json(db.get_bill_row(b.id) or {})


def bill_card(b: Bill, title: Optional[str] = None) -> None:
    with st.container(border=True):
        st.markdown(f"{bill_summary_line(b)}" + (f" · {title}" if title else ""))
        status_badge(b.status, primary_reason(b), b.review_priority if not is_individual() else None)
        rest = reasons_for(b)[1:]
        if rest:
            reason_list(rest)
        if b.user_entered_amount is not None:
            three_way_compare(b)
        bill_details(b)


# ---------------- alerts ----------------
def toast_once(alerts, *, per_visit_key: Optional[str] = None) -> None:
    """At most one toast per page load; INDIVIDUAL: at most one budget toast per visit (session)."""
    alerts = list(alerts or [])
    if not alerts:
        return
    if per_visit_key or is_individual():
        k = per_visit_key or "budget_toast_shown"
        if st.session_state.get(k):
            return
        st.session_state[k] = True
    a = alerts[0]
    st.toast(a.message, icon=":material/notifications:")


def alert_list(alerts) -> None:
    icons = {"BUDGET_BREACH": (":material/error:", "red"), "BUDGET_WARNING": (":material/warning:", "orange"),
             "BUDGET_PACE": (":material/speed:", "orange"), "ANOMALY": (":material/insights:", "blue")}
    for a in alerts:
        icon, color = icons.get(a.alert_type, (":material/info:", "gray"))
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            st.badge(a.alert_type.replace("BUDGET_", "").replace("_", " ").title(), icon=icon,
                     color=color if a.alert_type == "BUDGET_BREACH" or not is_individual() else "gray")
            st.markdown(a.message)
        st.caption(fmt_date(a.created_at))


# ---------------- pipeline with visible steps ----------------
def process_with_progress(raw, label: str) -> Bill:
    """Show the pipeline while it works. The pipeline itself is unchanged (core.pipeline.process_bill)."""
    ind = is_individual()
    with st.status(f"Checking {label}…", expanded=True) as s:
        with st.container(key=f"pipeline_steps_{abs(hash((label, raw.file_hash, id(raw))))}"):
            st.write(":material/document_scanner: Reading bill…")
            ext = extract_fields(raw)
            if ext.error:
                st.write(":material/error: Couldn't read this image clearly - nothing was guessed.")
            else:
                st.write(":material/check: Read the bill")
            bill = process_bill(raw, extractor=lambda _raw: ext)
            st.write(":material/content_copy: Checking duplicates → "
                     + (f"already added (#{bill.duplicate_of})" if bill.duplicate_of else "new bill"))
            st.write(":material/shield: Fraud check → "
                     + (f"score {bill.fraud_score}" + (f" · {'; '.join(bill.fraud_signals)}" if bill.fraud_signals else "")))
            st.write(":material/account_balance: Matching bank debit → " + (match_label(bill) or "skipped"))
            posted = bill.status == "VERIFIED"
            st.write(":material/menu_book: Posting to ledger → "
                     + ("posted" if posted else ("held - needs you" if ind else f"held ({bill.status})")))
        state = "complete" if bill.status in ("VERIFIED", "NEEDS_REVIEW", "MISSING_DATA", "DUPLICATE") else "error"
        s.update(label=f"{label}: {STATUS_LABEL.get(role(), STATUS_LABEL['BUSINESS']).get(bill.status, bill.status)}",
                 state=state, expanded=False)
    db.log_action("upload", f"bill #{bill.id} via {raw.source} -> {bill.status}")
    return bill
