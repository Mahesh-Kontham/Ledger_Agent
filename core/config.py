"""All thresholds and constants. Values copied exactly from PRD Section 8 - do not change."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

BASE_CURRENCY = "INR"
CONFIDENCE_THRESHOLD = 0.85

# Cross-verification
MATCH_DATE_WINDOW_DAYS = 2
TOLERANCE_ABS_INR = 2.00
TOLERANCE_PCT = 0.01
CARD_FEE_MAX_ABS_INR = 10.00          # variance up to max(10, 2%) on CARD -> "Probable card fee"
CARD_FEE_MAX_PCT = 0.02
FOREX_MARKUP_MAX_PCT = 0.04           # foreign-currency bill, variance up to 4% -> "Forex markup"

# Fraud routing (score 0-100)
FRAUD = {
    "INDIVIDUAL": {"warn": 40, "review": 70},   # <40 ok, 40-69 save with warning, >=70 NEEDS_REVIEW (HIGH)
    "BUSINESS":   {"review": 40, "high": 70},   # >=40 NEEDS_REVIEW (NORMAL), >=70 NEEDS_REVIEW (HIGH)
}

MANDATORY_FIELDS = {
    "INDIVIDUAL": ["merchant", "bill_date", "total_amount", "currency", "payment_mode"],
    "BUSINESS":   ["merchant", "bill_date", "total_amount", "currency", "payment_mode",
                   "invoice_number", "tax_amount"],
}
# BUSINESS extra rule: if tax_amount > 0 then gstin is mandatory.

# Budgets
PACE_FACTOR = 1.3                     # alert if spent_pct > 1.3 * elapsed_pct
PACE_MIN_DAY = 5                      # no pace alerts before day 5 of the month
BUDGET_WARNING_PCT = 0.80
BUDGET_BREACH_PCT = 1.00

# Anomalies
SPIKE_FACTOR = 3.0                    # amount > 3x category 30-day average
SPIKE_MIN_HISTORY = 3                 # need >= 3 prior verified bills in that category
NEW_MERCHANT_HIGH_AMOUNT_INR = 5000
SUBSCRIPTION_INCREASE_PCT = 0.10

CATEGORIES = ["Transport", "Food", "Shopping", "Utilities", "Subscriptions",
              "Travel", "Advertising", "Office", "Health", "Other"]

# SAMPLE rates for the demo only - not live market data. Shown in UI as "sample rate".
FX_TABLE = {"INR": 1.0, "USD": 85.00, "EUR": 92.00, "GBP": 108.00, "AED": 23.00}
FX_TABLE_DATE = "2026-11-01"

# ---- Non-threshold settings (paths, model, env) ----
MODES = ["INDIVIDUAL", "BUSINESS"]
STATUSES = ["VERIFIED", "NEEDS_REVIEW", "MISSING_DATA", "DUPLICATE", "REJECTED"]
PAYMENT_MODES = ["CARD", "UPI", "CASH", "NETBANKING", "WALLET"]
LLM_MODEL = os.environ.get("GEMINI_MODEL", "").strip() or "gemini-3.5-flash"

DATA_DIR = ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
SAMPLE_DIR = ROOT / "sample_data"
INBOX_DIR = SAMPLE_DIR / "inbox"
BANK_CSV = SAMPLE_DIR / "bank_statement.csv"


def db_path() -> Path:
    return Path(os.environ.get("LEDGERTRUTH_DB", DATA_DIR / "ledger.db"))


GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
FRAUD_MCP_URL = os.environ.get("FRAUD_MCP_URL", "")
GMAIL_IMAP_USER = os.environ.get("GMAIL_IMAP_USER", "")
GMAIL_IMAP_APP_PASSWORD = os.environ.get("GMAIL_IMAP_APP_PASSWORD", "")
