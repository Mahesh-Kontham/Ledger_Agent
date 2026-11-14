"""Rule-based anomaly flags (PRD Section 11.2). Each creates an ANOMALY alert."""
from __future__ import annotations

from datetime import date, timedelta

from core import config, db
from core.models import Alert, Bill
from core.verify import fmt_inr


def _verified_others(bill: Bill) -> list[Bill]:
    return [b for b in db.list_bills(["VERIFIED"], bill.mode)
            if b.id != bill.id and b.total_amount_inr is not None and b.bill_date]


def run_anomalies(bill: Bill) -> list[Alert]:
    if bill.total_amount_inr is None or not bill.bill_date:
        return []
    others = _verified_others(bill)
    amt, d = bill.total_amount_inr, date.fromisoformat(bill.bill_date)
    period = bill.bill_date[:7]
    found: list[str] = []

    # 1. spike vs category 30-day average
    window = [b for b in others if b.category == bill.category and b.id < bill.id
              and 0 <= (d - date.fromisoformat(b.bill_date)).days <= 30]
    if len(window) >= config.SPIKE_MIN_HISTORY:
        avg = sum(b.total_amount_inr for b in window) / len(window)
        if amt > config.SPIKE_FACTOR * avg:
            found.append(f"Spike: {bill.merchant_normalized} {fmt_inr(amt)} is more than "
                         f"{config.SPIKE_FACTOR:g}x the {bill.category} 30-day average ({fmt_inr(round(avg, 2))}).")

    # 2. first bill from a new merchant with a high amount
    same_merchant = [b for b in others if b.merchant_normalized == bill.merchant_normalized]
    if not same_merchant and amt >= config.NEW_MERCHANT_HIGH_AMOUNT_INR:
        found.append(f"New merchant: first bill from {bill.merchant_normalized} is {fmt_inr(amt)}.")

    # 3. same merchant, same day, two or more verified bills
    same_day = [b for b in same_merchant if b.bill_date == bill.bill_date]
    if same_day:
        found.append(f"Same-day repeat: {len(same_day) + 1} verified bills from "
                     f"{bill.merchant_normalized} on {bill.bill_date}.")

    # 4. subscription price increase vs previous bill from same merchant
    if bill.category == "Subscriptions":
        prev = sorted([b for b in same_merchant if b.bill_date <= bill.bill_date and b.id < bill.id],
                      key=lambda b: (b.bill_date, b.id))
        if prev and amt > (1 + config.SUBSCRIPTION_INCREASE_PCT) * prev[-1].total_amount_inr:
            found.append(f"Price increase: {bill.merchant_normalized} {fmt_inr(amt)} vs previous "
                         f"{fmt_inr(prev[-1].total_amount_inr)}.")

    new = []
    for msg in found:
        a = db.insert_alert_if_new(Alert("ANOMALY", msg, period, category=bill.category, bill_id=bill.id),
                                   dedupe_on_bill=True)
        if a:
            new.append(a)
    return new
