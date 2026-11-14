"""Budget pace logic + alerts (PRD Section 11.1)."""
from __future__ import annotations

import calendar
from datetime import date
from typing import Iterable, Optional

from core import config, db
from core.models import Alert
from core.verify import fmt_inr


def category_spent(category: str, mode: str, year: int, month: int) -> float:
    return db.expense_spent(category, mode, f"{year:04d}-{month:02d}")


def budget_rows(mode: str, today: Optional[date] = None) -> list[dict]:
    today = today or date.today()
    dim = calendar.monthrange(today.year, today.month)[1]
    rows = []
    for b in db.list_budgets(mode):
        spent = category_spent(b.category, mode, today.year, today.month)
        rows.append({
            "category": b.category, "limit": b.monthly_limit_inr, "spent": spent,
            "projected": round(spent / today.day * dim, 2),
            "spent_pct": spent / b.monthly_limit_inr if b.monthly_limit_inr else 0.0,
            "elapsed_pct": today.day / dim, "day": today.day, "days_in_month": dim,
        })
    return rows


def evaluate_budget(row: dict, today: date) -> Optional[Alert]:
    cat, sp, el = row["category"], row["spent_pct"], row["elapsed_pct"]
    week = today.isocalendar()
    week_key = f"{week[0]}-W{week[1]:02d}"
    month_key = f"{today.year:04d}-{today.month:02d}"
    if sp >= config.BUDGET_BREACH_PCT:
        return Alert("BUDGET_BREACH", f"{cat}: budget exceeded - {fmt_inr(row['spent'])} spent vs "
                     f"{fmt_inr(row['limit'])} limit ({sp:.0%}).", month_key, category=cat)
    if sp >= config.BUDGET_WARNING_PCT:
        return Alert("BUDGET_WARNING", f"{cat}: {sp:.0%} of budget used ({fmt_inr(row['spent'])} of "
                     f"{fmt_inr(row['limit'])}).", week_key, category=cat)
    if today.day >= config.PACE_MIN_DAY and sp > config.PACE_FACTOR * el:
        return Alert("BUDGET_PACE", f"{cat}: {sp:.0%} of budget used by day {today.day} ({el:.0%} of month). "
                     f"Projected {fmt_inr(round(row['projected']))} vs {fmt_inr(row['limit'])} limit.",
                     week_key, category=cat)
    return None


def run_budget_checks(mode: str, today: Optional[date] = None,
                      categories: Optional[Iterable[str]] = None) -> list[Alert]:
    """Check budgets and store new alerts (deduped per period). Returns only newly created alerts."""
    today = today or date.today()
    cats = set(categories) if categories else None
    new = []
    for row in budget_rows(mode, today):
        if cats and row["category"] not in cats:
            continue
        alert = evaluate_budget(row, today)
        if alert and db.insert_alert_if_new(alert):
            new.append(alert)
    return new
