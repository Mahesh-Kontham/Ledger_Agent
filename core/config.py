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

# Reduced by product decision (PRD Section 19). Same four fields for both modes.
MANDATORY_FIELDS = {
    "INDIVIDUAL": ["merchant", "bill_date", "invoice_number", "total_amount"],
    "BUSINESS":   ["merchant", "bill_date", "invoice_number", "total_amount"],
}
# Not mandatory, but never guessed: if a total is printed without a currency we cannot convert it to INR,
# so "currency" is requested (see verify.check_mandatory).

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
# Tried in order when the main model is out of quota or unavailable (each model has its own free-tier quota)
GEMINI_FALLBACK_MODELS = [m.strip() for m in (os.environ.get("GEMINI_FALLBACK_MODELS", "") or "gemini-3.8-flash,gemini-3.5-flash-lite,gemini-3.1-flash-lite").split(",") if m.strip()]

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
GOOGLE_OAUTH_CLIENT_FILE = os.environ.get("GOOGLE_OAUTH_CLIENT_FILE", "").strip() or str(ROOT / "google_oauth_client.json")
