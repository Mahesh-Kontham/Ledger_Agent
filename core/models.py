"""Dataclasses: Bill, Transaction, JournalLine, Budget, Alert (+ pipeline helper types)."""
from __future__ import annotations

from dataclasses import dataclass, field, fields as dc_fields
from typing import Any, Optional


@dataclass
class RawBill:
    source: str                                  # upload | scan | email | manual
    file_path: Optional[str] = None
    file_hash: Optional[str] = None
    fields: Optional[dict] = None                # manual entry values
    filename: Optional[str] = None
    user_entered_amount: Optional[float] = None


@dataclass
class ExtractedFields:
    values: dict                                 # field -> value | None (after confidence filter)
    confidence: dict                             # field -> float
    low_confidence_fields: list = field(default_factory=list)
    line_items: list = field(default_factory=list)
    fee_items: list = field(default_factory=list)
    error: Optional[str] = None
    raw_response: Optional[Any] = None


@dataclass
class FraudResult:
    score: int
    signals: list = field(default_factory=list)
    is_mock: bool = True


@dataclass
class Transaction:
    id: Optional[int]
    txn_date: str
    description: str
    amount: float
    currency: str
    amount_inr: float
    type: str
    account_name: str
    matched_bill_id: Optional[int] = None


@dataclass
class MatchResult:
    match_status: str                            # MATCHED | VARIANCE_EXPLAINED | VARIANCE_UNEXPLAINED | NO_MATCH
    transaction: Optional[Transaction] = None
    variance_inr: Optional[float] = None
    variance_reason: Optional[str] = None
    info_note: Optional[str] = None


@dataclass
class Bill:
    source: str
    mode: str
    status: str = "MISSING_DATA"
    id: Optional[int] = None
    file_path: Optional[str] = None
    file_hash: Optional[str] = None
    merchant_raw: Optional[str] = None
    merchant_normalized: Optional[str] = None
    category: Optional[str] = None
    bill_date: Optional[str] = None
    invoice_number: Optional[str] = None
    total_amount: Optional[float] = None
    tax_amount: Optional[float] = None
    currency: Optional[str] = None
    payment_mode: Optional[str] = None
    gstin: Optional[str] = None
    user_entered_amount: Optional[float] = None
    line_items: list = field(default_factory=list)
    fee_items: list = field(default_factory=list)
    field_confidence: dict = field(default_factory=dict)
    low_confidence_fields: list = field(default_factory=list)
    total_amount_inr: Optional[float] = None
    fx_rate: Optional[float] = None
    fx_rate_date: Optional[str] = None
    fx_source: Optional[str] = None
    fraud_score: Optional[int] = None
    fraud_signals: list = field(default_factory=list)
    duplicate_of: Optional[int] = None
    matched_transaction_id: Optional[int] = None
    match_status: Optional[str] = None
    variance_inr: Optional[float] = None
    variance_reason: Optional[str] = None
    missing_fields: list = field(default_factory=list)
    status_reasons: list = field(default_factory=list)
    review_priority: Optional[str] = None
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None
    created_at: Optional[str] = None
    user_id: Optional[int] = None
    # --- transient (not stored) ---
    extraction_error: Optional[str] = None
    info_note: Optional[str] = None
    fraud_is_mock: bool = True
    new_alerts: list = field(default_factory=list)

    @property
    def merchant(self):
        return self.merchant_raw

    def field_value(self, name: str):
        return self.merchant_raw if name == "merchant" else getattr(self, name)


TRANSIENT_BILL_FIELDS = {"extraction_error", "info_note", "fraud_is_mock", "new_alerts"}
BILL_FIELD_NAMES = [f.name for f in dc_fields(Bill)]


@dataclass
class JournalLine:
    entry_id: str
    bill_id: int
    entry_date: str
    account: str
    debit: float = 0.0
    credit: float = 0.0
    note: Optional[str] = None
    id: Optional[int] = None


@dataclass
class Budget:
    category: str
    monthly_limit_inr: float
    mode: str
    id: Optional[int] = None


@dataclass
class Alert:
    alert_type: str                              # BUDGET_PACE | BUDGET_WARNING | BUDGET_BREACH | ANOMALY
    message: str
    period_key: str
    category: Optional[str] = None
    bill_id: Optional[int] = None
    created_at: Optional[str] = None
    id: Optional[int] = None
