from datetime import date

from conftest import upload

from core import anomalies, budgets, db
from core.models import Bill

TODAY = date(2026, 11, 14)


def test_pace_message_format():
    row = {"category": "Transport", "limit": 5000.0, "spent": 2600.0, "projected": 7800.0,
           "spent_pct": 0.52, "elapsed_pct": 10 / 30, "day": 10, "days_in_month": 30}
    a = budgets.evaluate_budget(row, date(2026, 11, 10))
    assert a.alert_type == "BUDGET_PACE"
    assert a.message == ("Transport: 52% of budget used by day 10 (33% of month). "
                         "Projected ₹7,800 vs ₹5,000 limit.")
    assert a.period_key == "2026-W46"


def test_no_pace_before_day_5():
    row = {"category": "Food", "limit": 5000.0, "spent": 1000.0, "projected": 10000.0,
           "spent_pct": 0.2, "elapsed_pct": 3 / 30, "day": 3, "days_in_month": 30}
    assert budgets.evaluate_budget(row, date(2026, 11, 3)) is None


def test_breach_after_rapido(fresh_db):
    db.upsert_budget("Transport", 100.0, "INDIVIDUAL")
    b = upload("bill2_rapido.png", user_entered_amount=120, today=TODAY)
    assert any(a.alert_type == "BUDGET_BREACH" for a in b.new_alerts)
    # at most once per category per month
    assert budgets.run_budget_checks("INDIVIDUAL", TODAY) == []


def test_warning_at_150_limit(fresh_db):
    db.upsert_budget("Transport", 150.0, "INDIVIDUAL")
    b = upload("bill2_rapido.png", user_entered_amount=120, today=TODAY)
    kinds = [a.alert_type for a in b.new_alerts]
    assert kinds == ["BUDGET_WARNING"]          # 125/150 = 83%
    rows = budgets.budget_rows("INDIVIDUAL", TODAY)
    assert rows[0]["spent"] == 125.0 and rows[0]["projected"] == round(125 / 14 * 30, 2)


def test_new_merchant_high_amount_anomaly(fresh_db):
    b = Bill(source="manual", mode="INDIVIDUAL", status="VERIFIED", merchant_normalized="Meta Ads",
             category="Advertising", bill_date="2026-11-13", total_amount_inr=6000.0)
    db.insert_bill(b)
    msgs = [a.message for a in anomalies.run_anomalies(b)]
    assert any(m.startswith("New merchant") for m in msgs)


def test_subscription_price_increase(fresh_db):
    prev = Bill(source="manual", mode="INDIVIDUAL", status="VERIFIED", merchant_normalized="Netflix",
                category="Subscriptions", bill_date="2026-10-05", total_amount_inr=500.0)
    db.insert_bill(prev)
    cur = Bill(source="manual", mode="INDIVIDUAL", status="VERIFIED", merchant_normalized="Netflix",
               category="Subscriptions", bill_date="2026-11-05", total_amount_inr=600.0)
    db.insert_bill(cur)
    assert any(a.message.startswith("Price increase") for a in anomalies.run_anomalies(cur))
