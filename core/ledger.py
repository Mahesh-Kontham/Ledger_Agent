"""Double-entry posting (PRD Section 10) + ledger views."""
from __future__ import annotations

from typing import Optional

import pandas as pd

from core import db
from core.models import Bill, JournalLine, Transaction


class UnbalancedEntryError(Exception):
    pass


def credit_account(bill: Bill, txn: Optional[Transaction]) -> str:
    if txn is not None:
        if "card" in txn.account_name.lower():
            return f"Liability:Credit Card - {txn.account_name}"
        return f"Asset:Bank - {txn.account_name}"
    if bill.payment_mode == "CASH":
        return "Asset:Cash"
    if bill.payment_mode == "CARD":
        return "Liability:Credit Card - Unspecified"
    return "Asset:Bank - Unspecified"


def build_journal(bill: Bill, txn: Optional[Transaction]) -> list[JournalLine]:
    """Pure: VERIFIED bill (+ its usable matched txn or None) -> balanced lines. Raises if unbalanced."""
    if bill.total_amount_inr is None or not bill.bill_date:
        raise ValueError(f"Bill #{bill.id} lacks amount/date; cannot post")
    entry_id = f"JE-{bill.id:06d}"
    name = bill.merchant_normalized or bill.merchant_raw or "Bill"

    def line(account, debit=0.0, credit=0.0, note=None):
        return JournalLine(entry_id=entry_id, bill_id=bill.id, entry_date=bill.bill_date, account=account,
                           debit=round(debit, 2), credit=round(credit, 2), note=note)

    base = round(bill.total_amount_inr, 2)
    lines: list[JournalLine] = []
    tax_inr = round((bill.tax_amount or 0) * (bill.fx_rate or 1.0), 2)
    expense_acct = f"Expense:{bill.category or 'Other'}"
    if bill.mode == "BUSINESS" and bill.gstin and tax_inr > 0:
        lines.append(line(expense_acct, debit=base - tax_inr, note=f"{name} invoice (net of GST)"))
        lines.append(line("Asset:Input GST", debit=tax_inr, note=f"GSTIN {bill.gstin}"))
    else:
        lines.append(line(expense_acct, debit=base, note=f"{name} invoice"))

    if txn is not None:
        variance = round(txn.amount_inr - base, 2)
        if variance != 0:
            if bill.match_status == "VARIANCE_EXPLAINED":
                acct = "Expense:Forex Charges" if bill.variance_reason == "Forex markup" else "Expense:Bank Charges"
                note = bill.variance_reason
            else:  # MATCHED within tolerance - post the small difference so the entry balances
                acct, note = "Expense:Bank Charges", "Difference within tolerance"
            lines.append(line(acct, debit=variance, note=note) if variance > 0
                         else line(acct, credit=-variance, note=note))
        lines.append(line(credit_account(bill, txn), credit=txn.amount_inr, note=f"Matched txn #{txn.id}"))
    else:
        lines.append(line(credit_account(bill, None), credit=base,
                          note=f"No bank match - {bill.payment_mode or 'unknown mode'}"))

    debits = round(sum(l.debit for l in lines), 2)
    credits = round(sum(l.credit for l in lines), 2)
    if debits != credits:
        raise UnbalancedEntryError(f"{entry_id}: debits {debits} != credits {credits}")
    assert debits == credits
    return lines


def usable_transaction(bill: Bill) -> Optional[Transaction]:
    if bill.match_status in ("MATCHED", "VARIANCE_EXPLAINED") and bill.matched_transaction_id:
        txn = db.get_transaction(bill.matched_transaction_id)
        if txn and txn.matched_bill_id in (None, bill.id):
            return txn
    return None


def post_to_ledger(bill: Bill) -> list[JournalLine]:
    if bill.status != "VERIFIED":
        raise ValueError(f"Only VERIFIED bills post (bill #{bill.id} is {bill.status})")
    if db.has_journal(bill.id):
        return []
    lines = build_journal(bill, usable_transaction(bill))
    db.insert_journal_lines(lines)
    return lines


# ---------------- views ----------------
def journal_df(mode: Optional[str] = None, month: Optional[str] = None) -> pd.DataFrame:
    df = pd.DataFrame(db.journal_rows(mode))
    if df.empty:
        return pd.DataFrame(columns=["entry_id", "bill_id", "entry_date", "account", "debit", "credit", "note"])
    if month:
        df = df[df["entry_date"].str.startswith(month)]
    return df


def months(mode: Optional[str] = None) -> list[str]:
    df = journal_df(mode)
    return sorted({d[:7] for d in df["entry_date"]}, reverse=True) if not df.empty else []


def category_totals(mode: Optional[str], month: Optional[str]) -> pd.DataFrame:
    df = journal_df(mode, month)
    df = df[df["account"].str.startswith("Expense:")] if not df.empty else df
    if df.empty:
        return pd.DataFrame(columns=["category", "total_inr"])
    out = df.groupby("account", as_index=False)["debit"].sum()
    cred = df.groupby("account", as_index=False)["credit"].sum()
    out = out.merge(cred, on="account")
    out["total_inr"] = (out["debit"] - out["credit"]).round(2)
    out["category"] = out["account"].str.replace("Expense:", "", regex=False)
    return out[["category", "total_inr"]].sort_values("total_inr", ascending=False)


def merchant_groups(mode: Optional[str]) -> pd.DataFrame:
    bills = [b for b in db.list_bills(["VERIFIED"], mode) if db.has_journal(b.id)]
    if not bills:
        return pd.DataFrame(columns=["merchant", "bills", "total_inr", "first_date", "last_date"])
    df = pd.DataFrame([{"merchant": b.merchant_normalized, "bill_id": b.id, "date": b.bill_date,
                        "total_inr": b.total_amount_inr} for b in bills])
    g = df.groupby("merchant").agg(bills=("bill_id", "count"), total_inr=("total_inr", "sum"),
                                   first_date=("date", "min"), last_date=("date", "max")).reset_index()
    return g.sort_values("total_inr", ascending=False)


def trial_balance(mode: Optional[str]) -> tuple[pd.DataFrame, float, float]:
    df = journal_df(mode)
    if df.empty:
        return pd.DataFrame(columns=["account", "debit", "credit"]), 0.0, 0.0
    tb = df.groupby("account", as_index=False)[["debit", "credit"]].sum().round(2)
    return tb, round(tb["debit"].sum(), 2), round(tb["credit"].sum(), 2)


def gst_summary(mode: Optional[str]) -> pd.DataFrame:
    df = journal_df(mode)
    df = df[df["account"] == "Asset:Input GST"] if not df.empty else df
    if df.empty:
        return pd.DataFrame(columns=["month", "input_gst_inr"])
    df = df.assign(month=df["entry_date"].str[:7])
    out = df.groupby("month", as_index=False)["debit"].sum().rename(columns={"debit": "input_gst_inr"})
    return out.sort_values("month", ascending=False)
