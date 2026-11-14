"""SQLite schema creation (PRD Section 7) + queries."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Iterable, Optional

import contextvars

from core import config
from core.models import (Alert, Bill, BILL_FIELD_NAMES, Budget, JournalLine,
                         Transaction, TRANSIENT_BILL_FIELDS)

SCHEMA = """
CREATE TABLE IF NOT EXISTS bills (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  source TEXT NOT NULL CHECK (source IN ('upload','scan','email','manual')),
  file_path TEXT,
  file_hash TEXT,
  merchant_raw TEXT,
  merchant_normalized TEXT,
  category TEXT,
  bill_date TEXT,
  invoice_number TEXT,
  total_amount REAL,
  tax_amount REAL,
  currency TEXT,
  payment_mode TEXT,
  gstin TEXT,
  user_entered_amount REAL,
  line_items_json TEXT,
  fee_items_json TEXT,
  field_confidence_json TEXT,
  low_confidence_fields_json TEXT,
  total_amount_inr REAL,
  fx_rate REAL,
  fx_rate_date TEXT,
  fx_source TEXT,
  fraud_score INTEGER,
  fraud_signals_json TEXT,
  duplicate_of INTEGER,
  matched_transaction_id INTEGER,
  match_status TEXT,
  variance_inr REAL,
  variance_reason TEXT,
  missing_fields_json TEXT,
  status TEXT NOT NULL,
  status_reasons_json TEXT,
  review_priority TEXT,
  reviewed_by TEXT,
  reviewed_at TEXT,
  mode TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  txn_date TEXT NOT NULL,
  description TEXT NOT NULL,
  amount REAL NOT NULL,
  currency TEXT NOT NULL,
  amount_inr REAL NOT NULL,
  type TEXT NOT NULL CHECK (type IN ('DEBIT','CREDIT')),
  account_name TEXT NOT NULL,
  matched_bill_id INTEGER
);

CREATE TABLE IF NOT EXISTS journal_lines (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  entry_id TEXT NOT NULL,
  bill_id INTEGER NOT NULL,
  entry_date TEXT NOT NULL,
  account TEXT NOT NULL,
  debit REAL NOT NULL DEFAULT 0,
  credit REAL NOT NULL DEFAULT 0,
  note TEXT
);

CREATE TABLE IF NOT EXISTS budgets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  category TEXT NOT NULL,
  monthly_limit_inr REAL NOT NULL,
  mode TEXT NOT NULL,
  UNIQUE (user_id, category, mode)
);

CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  alert_type TEXT NOT NULL,
  category TEXT,
  bill_id INTEGER,
  message TEXT NOT NULL,
  period_key TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS merchant_aliases (
  alias TEXT PRIMARY KEY,
  merchant_normalized TEXT NOT NULL,
  category TEXT NOT NULL
);

-- PRD Section 18 (roles amendment)
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('ADMIN','BUSINESS','INDIVIDUAL')),
  org_name TEXT,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  action TEXT NOT NULL,
  target TEXT,
  created_at TEXT NOT NULL
);

-- PRD Section 19: per-user mailbox connection (Google sign-in) and processed-message tracking
CREATE TABLE IF NOT EXISTS mail_accounts (
  user_id INTEGER PRIMARY KEY,
  provider TEXT NOT NULL,
  email TEXT NOT NULL,
  token_json TEXT NOT NULL,
  connected_at TEXT NOT NULL,
  last_sync_at TEXT
);

CREATE TABLE IF NOT EXISTS mail_seen (
  user_id INTEGER NOT NULL,
  message_id TEXT NOT NULL,
  seen_at TEXT NOT NULL,
  PRIMARY KEY (user_id, message_id)
);

-- Not in PRD Section 7; needed for "mode stored in a settings row" (PRD Section 15). See DECISIONS.md.
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT
);
"""

ALIAS_SEED = [
    ("rapido", "Rapido", "Transport"),
    ("uber", "Uber", "Transport"),
    ("ola", "Ola", "Transport"),
    ("swiggy", "Swiggy", "Food"),
    ("zomato", "Zomato", "Food"),
    ("amazon", "Amazon", "Shopping"),
    ("flipkart", "Flipkart", "Shopping"),
    ("notion", "Notion", "Subscriptions"),
    ("netflix", "Netflix", "Subscriptions"),
    ("spotify", "Spotify", "Subscriptions"),
    ("google ads", "Google Ads", "Advertising"),
    ("meta ads", "Meta Ads", "Advertising"),
    ("airtel", "Airtel", "Utilities"),
    ("jio", "Jio", "Utilities"),
]

JSON_FIELDS = {
    "line_items": "line_items_json",
    "fee_items": "fee_items_json",
    "field_confidence": "field_confidence_json",
    "low_confidence_fields": "low_confidence_fields_json",
    "fraud_signals": "fraud_signals_json",
    "missing_fields": "missing_fields_json",
    "status_reasons": "status_reasons_json",
}


USER_TABLES = ["bills", "transactions", "journal_lines", "budgets", "alerts"]
MAIL_TABLES = ["mail_accounts", "mail_seen"]
DEMO_BUSINESS_EMAIL = "business@demo"

# The logged-in user for the current script run. Set once per Streamlit run (app.py) or per test.
# A ContextVar is per-thread/per-run, so concurrent sessions never see each other's user.
_current_user: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar("ledgertruth_user", default=None)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def get_conn() -> sqlite3.Connection:
    path = config.db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------- session user / scoping ----------------
def set_current_user(user: Optional[dict]) -> None:
    _current_user.set(dict(user) if user else None)


def current_user() -> Optional[dict]:
    return _current_user.get()


def _uid() -> int:
    """Logged-in user id. Fails closed: no user -> no data access."""
    u = _current_user.get()
    if not u:
        raise PermissionError("Not logged in")
    return int(u["id"])


def _require_admin() -> None:
    u = _current_user.get()
    if not u or u.get("role") != "ADMIN":
        raise PermissionError("Admin only")


def get_mode() -> str:
    """Mode is derived from the role (PRD Section 18): BUSINESS -> BUSINESS, INDIVIDUAL -> INDIVIDUAL."""
    u = _current_user.get()
    if not u or u.get("role") not in config.MODES:
        raise PermissionError("Only BUSINESS and INDIVIDUAL users have a bookkeeping mode")
    return u["role"]


# ---------------- schema / migration ----------------
def _columns(conn, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _migrate(conn) -> None:
    for t in ["bills", "transactions", "journal_lines", "alerts"]:
        if "user_id" not in _columns(conn, t):
            conn.execute(f"ALTER TABLE {t} ADD COLUMN user_id INTEGER")
    if "user_id" not in _columns(conn, "budgets"):     # rebuild to change UNIQUE(category, mode)
        conn.execute("ALTER TABLE budgets RENAME TO budgets_old")
        conn.execute("""CREATE TABLE budgets (
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, category TEXT NOT NULL,
          monthly_limit_inr REAL NOT NULL, mode TEXT NOT NULL, UNIQUE (user_id, category, mode))""")
        conn.execute("INSERT INTO budgets (category, monthly_limit_inr, mode) "
                     "SELECT category, monthly_limit_inr, mode FROM budgets_old")
        conn.execute("DROP TABLE budgets_old")


def assign_orphans() -> int:
    """Pre-roles data (user_id NULL) belongs to the demo business user. Returns rows updated."""
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM users WHERE email=?", (DEMO_BUSINESS_EMAIL,)).fetchone()
        if not row:
            return 0
        n = 0
        for t in USER_TABLES:
            n += conn.execute(f"UPDATE {t} SET user_id=? WHERE user_id IS NULL", (row["id"],)).rowcount
        return n


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.executemany(
            "INSERT OR IGNORE INTO merchant_aliases (alias, merchant_normalized, category) VALUES (?,?,?)",
            ALIAS_SEED,
        )
    assign_orphans()


def clear_my_data() -> None:
    """Delete only the logged-in user's bills, transactions, journal, budgets and alerts."""
    uid = _uid()
    with get_conn() as conn:
        for t in USER_TABLES:
            conn.execute(f"DELETE FROM {t} WHERE user_id=?", (uid,))
        conn.execute("DELETE FROM mail_seen WHERE user_id=?", (uid,))


def reset_db() -> None:
    """Drop everything (tests/tooling only - not exposed in the UI)."""
    with get_conn() as conn:
        for t in USER_TABLES + MAIL_TABLES + ["merchant_aliases", "settings", "users", "audit_log"]:
            conn.execute(f"DROP TABLE IF EXISTS {t}")
    init_db()


# ---------------- users ----------------
def _public_user(row) -> Optional[dict]:
    if not row:
        return None
    d = dict(row)
    d.pop("password_hash", None)
    return d


def insert_user(name: str, email: str, password_hash: str, role: str, org_name: Optional[str] = None) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO users (name, email, password_hash, role, org_name, is_active, created_at) "
            "VALUES (?,?,?,?,?,1,?)", (name, email.strip().lower(), password_hash, role, org_name, now_iso()))
        return cur.lastrowid


def get_user_for_login(email: str) -> Optional[dict]:
    """Includes password_hash - only for core.auth."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE email=?", (email.strip().lower(),)).fetchone()
    return dict(row) if row else None


def get_user(user_id: int) -> Optional[dict]:
    with get_conn() as conn:
        return _public_user(conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())


def user_count() -> int:
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def demo_emails() -> list[dict]:
    """Seeded demo accounts for the login helper (emails + roles only, never passwords)."""
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT email, role FROM users WHERE email LIKE '%@demo' AND is_active=1 "
            "ORDER BY CASE role WHEN 'BUSINESS' THEN 0 WHEN 'INDIVIDUAL' THEN 1 ELSE 2 END").fetchall()]


# ---------------- audit ----------------
def log_action(action: str, target: Optional[str] = None, user_id: Optional[int] = None) -> None:
    uid = user_id if user_id is not None else (_current_user.get() or {}).get("id")
    with get_conn() as conn:
        conn.execute("INSERT INTO audit_log (user_id, action, target, created_at) VALUES (?,?,?,?)",
                     (uid, action, target, now_iso()))


# ---------------- settings (global, non-user data) ----------------
def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with get_conn() as conn:
        conn.execute("INSERT INTO settings (key, value) VALUES (?,?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


# ---------------- aliases (global reference data) ----------------
def list_aliases() -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM merchant_aliases").fetchall()


# ---------------- bills ----------------
def _bill_to_row(bill: Bill) -> dict:
    row = {}
    for name in BILL_FIELD_NAMES:
        if name in TRANSIENT_BILL_FIELDS or name in ("id", "user_id"):
            continue
        val = getattr(bill, name)
        if name in JSON_FIELDS:
            row[JSON_FIELDS[name]] = json.dumps(val, ensure_ascii=False)
        else:
            row[name] = val
    return row


def row_to_bill(row: sqlite3.Row) -> Bill:
    d = dict(row)
    kwargs = {}
    for name in BILL_FIELD_NAMES:
        if name in TRANSIENT_BILL_FIELDS:
            continue
        if name in JSON_FIELDS:
            raw = d.get(JSON_FIELDS[name])
            kwargs[name] = json.loads(raw) if raw else ({} if name == "field_confidence" else [])
        else:
            kwargs[name] = d.get(name)
    return Bill(**kwargs)


def insert_bill(bill: Bill) -> int:
    uid = _uid()
    if not bill.created_at:
        bill.created_at = now_iso()
    bill.user_id = uid
    row = _bill_to_row(bill)
    row["user_id"] = uid
    cols = ", ".join(row)
    qs = ", ".join("?" for _ in row)
    with get_conn() as conn:
        cur = conn.execute(f"INSERT INTO bills ({cols}) VALUES ({qs})", list(row.values()))
        bill.id = cur.lastrowid
    return bill.id


def update_bill(bill: Bill) -> None:
    row = _bill_to_row(bill)
    sets = ", ".join(f"{k}=?" for k in row)
    with get_conn() as conn:
        cur = conn.execute(f"UPDATE bills SET {sets} WHERE id=? AND user_id=?",
                           list(row.values()) + [bill.id, _uid()])
        if cur.rowcount != 1:
            raise PermissionError(f"Bill #{bill.id} not found for this user")


def get_bill(bill_id: int) -> Optional[Bill]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM bills WHERE id=? AND user_id=?", (bill_id, _uid())).fetchone()
    return row_to_bill(row) if row else None


def get_bill_row(bill_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM bills WHERE id=? AND user_id=?", (bill_id, _uid())).fetchone()
    return dict(row) if row else None


def list_bills(statuses: Optional[Iterable[str]] = None, mode: Optional[str] = None) -> list[Bill]:
    q, params = "SELECT * FROM bills WHERE user_id=?", [_uid()]
    if statuses:
        statuses = list(statuses)
        q += f" AND status IN ({','.join('?' for _ in statuses)})"
        params += statuses
    if mode:
        q += " AND mode=?"
        params.append(mode)
    q += " ORDER BY id"
    with get_conn() as conn:
        return [row_to_bill(r) for r in conn.execute(q, params).fetchall()]


def find_duplicate_id(clauses: list[str], params: list, exclude_id: Optional[int]) -> Optional[int]:
    """Used by verify.check_duplicate - scoped to the logged-in user's bills."""
    q = ("SELECT id FROM bills WHERE user_id=? AND status NOT IN ('REJECTED','DUPLICATE') "
         f"AND ({' OR '.join(clauses)})")
    params = [_uid()] + list(params)
    if exclude_id is not None:
        q += " AND id != ?"
        params.append(exclude_id)
    q += " ORDER BY id LIMIT 1"
    with get_conn() as conn:
        row = conn.execute(q, params).fetchone()
    return row["id"] if row else None


def review_queue() -> list[Bill]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM bills WHERE user_id=? AND status IN ('NEEDS_REVIEW','MISSING_DATA') "
            "ORDER BY CASE review_priority WHEN 'HIGH' THEN 0 ELSE 1 END, created_at, id", (_uid(),)
        ).fetchall()
    return [row_to_bill(r) for r in rows]


def review_queue_count() -> int:
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM bills WHERE user_id=? AND status IN "
                            "('NEEDS_REVIEW','MISSING_DATA')", (_uid(),)).fetchone()[0]


# ---------------- transactions ----------------
def _row_to_txn(r) -> Transaction:
    d = dict(r)
    d.pop("user_id", None)
    return Transaction(**d)


def insert_transaction(t: Transaction) -> Optional[int]:
    """Insert a transaction; skips exact duplicates (same date, description, amount, account)."""
    uid = _uid()
    with get_conn() as conn:
        exists = conn.execute(
            "SELECT id FROM transactions WHERE user_id=? AND txn_date=? AND description=? AND amount=? "
            "AND currency=? AND type=? AND account_name=?",
            (uid, t.txn_date, t.description, t.amount, t.currency, t.type, t.account_name)).fetchone()
        if exists:
            return None
        cur = conn.execute(
            "INSERT INTO transactions (user_id, txn_date, description, amount, currency, amount_inr, type, "
            "account_name, matched_bill_id) VALUES (?,?,?,?,?,?,?,?,?)",
            (uid, t.txn_date, t.description, t.amount, t.currency, t.amount_inr, t.type,
             t.account_name, t.matched_bill_id))
        return cur.lastrowid


def list_transactions(unmatched_debits_only: bool = False) -> list[Transaction]:
    q = "SELECT * FROM transactions WHERE user_id=?"
    if unmatched_debits_only:
        q += " AND type='DEBIT' AND matched_bill_id IS NULL"
    q += " ORDER BY txn_date, id"
    with get_conn() as conn:
        return [_row_to_txn(r) for r in conn.execute(q, (_uid(),)).fetchall()]


def get_transaction(txn_id: Optional[int]) -> Optional[Transaction]:
    if txn_id is None:
        return None
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM transactions WHERE id=? AND user_id=?", (txn_id, _uid())).fetchone()
    return _row_to_txn(r) if r else None


def set_transaction_matched(txn_id: int, bill_id: int) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE transactions SET matched_bill_id=? WHERE id=? AND user_id=?",
                     (bill_id, txn_id, _uid()))


# ---------------- journal ----------------
def insert_journal_lines(lines: list[JournalLine]) -> None:
    uid = _uid()
    with get_conn() as conn:
        conn.executemany(
            "INSERT INTO journal_lines (user_id, entry_id, bill_id, entry_date, account, debit, credit, note) "
            "VALUES (?,?,?,?,?,?,?,?)",
            [(uid, l.entry_id, l.bill_id, l.entry_date, l.account, l.debit, l.credit, l.note) for l in lines])


def has_journal(bill_id: int) -> bool:
    with get_conn() as conn:
        return conn.execute("SELECT 1 FROM journal_lines WHERE bill_id=? AND user_id=? LIMIT 1",
                            (bill_id, _uid())).fetchone() is not None


def journal_rows(mode: Optional[str] = None) -> list[dict]:
    q = ("SELECT j.id, j.entry_id, j.bill_id, j.entry_date, j.account, j.debit, j.credit, j.note, "
         "b.mode AS mode, b.merchant_normalized AS merchant FROM journal_lines j "
         "JOIN bills b ON b.id=j.bill_id AND b.user_id=j.user_id WHERE j.user_id=?")
    params: list = [_uid()]
    if mode:
        q += " AND b.mode=?"
        params.append(mode)
    q += " ORDER BY j.entry_id DESC, j.id"
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(q, params).fetchall()]


def expense_spent(category: str, mode: str, month_prefix: str) -> float:
    """Net debit on Expense:<category> for the user's bills in one month (used by budgets)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(j.debit),0) - COALESCE(SUM(j.credit),0) FROM journal_lines j "
            "JOIN bills b ON b.id=j.bill_id WHERE j.user_id=? AND j.account=? AND b.mode=? "
            "AND substr(j.entry_date,1,7)=?", (_uid(), f"Expense:{category}", mode, month_prefix)).fetchone()
    return round(row[0] or 0.0, 2)


# ---------------- budgets ----------------
def upsert_budget(category: str, limit: float, mode: str) -> None:
    with get_conn() as conn:
        conn.execute("INSERT INTO budgets (user_id, category, monthly_limit_inr, mode) VALUES (?,?,?,?) "
                     "ON CONFLICT(user_id, category, mode) DO UPDATE SET "
                     "monthly_limit_inr=excluded.monthly_limit_inr", (_uid(), category, limit, mode))


def delete_budget(category: str, mode: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM budgets WHERE user_id=? AND category=? AND mode=?", (_uid(), category, mode))


def list_budgets(mode: str) -> list[Budget]:
    with get_conn() as conn:
        rows = conn.execute("SELECT id, category, monthly_limit_inr, mode FROM budgets "
                            "WHERE user_id=? AND mode=? ORDER BY category", (_uid(), mode)).fetchall()
    return [Budget(**dict(r)) for r in rows]


# ---------------- alerts ----------------
def insert_alert_if_new(alert: Alert, dedupe_on_bill: bool = False) -> Optional[Alert]:
    uid = _uid()
    with get_conn() as conn:
        if dedupe_on_bill:
            exists = conn.execute(
                "SELECT 1 FROM alerts WHERE user_id=? AND alert_type=? AND bill_id IS ? AND message=?",
                (uid, alert.alert_type, alert.bill_id, alert.message)).fetchone()
        else:
            exists = conn.execute(
                "SELECT 1 FROM alerts WHERE user_id=? AND alert_type=? AND category IS ? AND period_key=?",
                (uid, alert.alert_type, alert.category, alert.period_key)).fetchone()
        if exists:
            return None
        alert.created_at = alert.created_at or now_iso()
        cur = conn.execute(
            "INSERT INTO alerts (user_id, alert_type, category, bill_id, message, period_key, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (uid, alert.alert_type, alert.category, alert.bill_id, alert.message, alert.period_key,
             alert.created_at))
        alert.id = cur.lastrowid
    return alert


def list_alerts(types: Optional[Iterable[str]] = None) -> list[Alert]:
    q = ("SELECT id, alert_type, category, bill_id, message, period_key, created_at "
         "FROM alerts WHERE user_id=?")
    params: list = [_uid()]
    if types:
        types = list(types)
        q += f" AND alert_type IN ({','.join('?' for _ in types)})"
        params += types
    q += " ORDER BY id DESC"
    with get_conn() as conn:
        return [Alert(**dict(r)) for r in conn.execute(q, params).fetchall()]


# ---------------- ADMIN: aggregates only (no bill images, file paths, merchants or amounts) ----------------
def admin_list_users() -> list[dict]:
    _require_admin()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT u.id, u.name, u.email, u.role, u.org_name, u.is_active, u.created_at, "
            "(SELECT COUNT(*) FROM bills b WHERE b.user_id=u.id) AS bills, "
            "(SELECT MAX(created_at) FROM audit_log a WHERE a.user_id=u.id) AS last_active "
            "FROM users u ORDER BY u.id").fetchall()
    return [dict(r) for r in rows]


def admin_set_user_active(user_id: int, active: bool) -> None:
    _require_admin()
    if user_id == _uid() and not active:
        raise ValueError("You cannot deactivate your own account")
    with get_conn() as conn:
        conn.execute("UPDATE users SET is_active=? WHERE id=?", (1 if active else 0, user_id))


def admin_bill_stats() -> list[dict]:
    """One row per bill with non-sensitive pipeline fields only."""
    _require_admin()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT b.id, b.user_id, u.role, b.status, b.fraud_score, b.match_status, b.created_at, "
            "CASE WHEN b.status_reasons_json LIKE '%Extraction failed%' THEN 1 ELSE 0 END AS extraction_failed, "
            "CASE WHEN b.reviewed_at IS NOT NULL THEN 1 ELSE 0 END AS human_reviewed "
            "FROM bills b LEFT JOIN users u ON u.id=b.user_id").fetchall()
    return [dict(r) for r in rows]


def admin_audit_log(limit: int = 1000) -> list[dict]:
    _require_admin()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT a.id, a.created_at, u.email, u.role, a.action, a.target FROM audit_log a "
            "LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


# ---------------- mail connection (per user) ----------------
def get_mail_account() -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM mail_accounts WHERE user_id=?", (_uid(),)).fetchone()
    return dict(row) if row else None


def save_mail_account(provider: str, email: str, token_json: str) -> None:
    with get_conn() as conn:
        conn.execute("INSERT INTO mail_accounts (user_id, provider, email, token_json, connected_at) "
                     "VALUES (?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET provider=excluded.provider, "
                     "email=excluded.email, token_json=excluded.token_json, connected_at=excluded.connected_at",
                     (_uid(), provider, email, token_json, now_iso()))


def update_mail_token(token_json: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE mail_accounts SET token_json=? WHERE user_id=?", (token_json, _uid()))


def touch_mail_sync() -> None:
    with get_conn() as conn:
        conn.execute("UPDATE mail_accounts SET last_sync_at=? WHERE user_id=?", (now_iso(), _uid()))


def delete_mail_account() -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM mail_accounts WHERE user_id=?", (_uid(),))


def mail_seen_ids() -> set:
    with get_conn() as conn:
        return {r[0] for r in conn.execute("SELECT message_id FROM mail_seen WHERE user_id=?", (_uid(),)).fetchall()}


def mark_mail_seen(message_ids) -> None:
    uid, now = _uid(), now_iso()
    with get_conn() as conn:
        conn.executemany("INSERT OR IGNORE INTO mail_seen (user_id, message_id, seen_at) VALUES (?,?,?)",
                         [(uid, m, now) for m in message_ids])


# ---------------- notifications (unread alerts, per user) ----------------
def _alerts_seen_key() -> str:
    return f"alerts_seen:{_uid()}"


def unread_alerts() -> list[Alert]:
    last = int(get_setting(_alerts_seen_key(), "0") or 0)
    return [a for a in list_alerts() if a.id > last]


def mark_alerts_read() -> None:
    with get_conn() as conn:
        row = conn.execute("SELECT COALESCE(MAX(id), 0) FROM alerts WHERE user_id=?", (_uid(),)).fetchone()
    set_setting(_alerts_seen_key(), str(row[0]))
