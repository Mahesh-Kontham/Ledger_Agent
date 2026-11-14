"""Currency conversion using the SAMPLE FX table (not live market data)."""
from __future__ import annotations

from typing import Optional

from core import config
from core.models import Transaction


def to_inr(amount: Optional[float], currency: Optional[str], date: Optional[str],
           matched_txn: Optional[Transaction] = None):
    """-> (amount_inr, fx_rate, fx_rate_date, fx_source). Unknown currency -> all None (never guessed)."""
    if currency is None:
        return None, None, None, None
    if currency == config.BASE_CURRENCY:
        return (round(amount, 2) if amount is not None else None), 1.0, date, "INR"
    rate = config.FX_TABLE.get(currency)
    if rate is None:
        return None, None, None, None
    amount_inr = round(amount * rate, 2) if amount is not None else None
    source = "card_debit" if matched_txn is not None else "config_table"
    return amount_inr, rate, config.FX_TABLE_DATE, source
