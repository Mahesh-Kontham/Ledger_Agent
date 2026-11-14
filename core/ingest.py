"""4 sources -> RawBill (upload, scan, email, manual)."""
from __future__ import annotations

import email
import hashlib
import imaplib
import io
from email import policy
from pathlib import Path

from core import config
from core.models import RawBill

ALLOWED_EXT = {".pdf", ".jpg", ".jpeg", ".png"}
ATTACHMENT_TYPES = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/jpg": ".jpg",
                    "image/png": ".png"}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _store(file_bytes: bytes, filename: str) -> tuple[str, str]:
    """Save bytes under data/uploads/<hash><ext>; return (path, hash)."""
    h = sha256(file_bytes)
    ext = Path(filename).suffix.lower() or ".bin"
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path = config.UPLOAD_DIR / f"{h[:16]}{ext}"
    if not path.exists():
        path.write_bytes(file_bytes)
    return str(path), h


def ingest_upload(file_bytes: bytes, filename: str, user_entered_amount: float | None = None) -> RawBill:
    path, h = _store(file_bytes, filename)
    return RawBill(source="upload", file_path=path, file_hash=h, filename=filename,
                   user_entered_amount=user_entered_amount)


def ingest_scan(image_bytes: bytes, user_entered_amount: float | None = None) -> RawBill:
    path, h = _store(image_bytes, "scan.jpg")
    return RawBill(source="scan", file_path=path, file_hash=h, filename="camera scan",
                   user_entered_amount=user_entered_amount)


def ingest_manual(form: dict) -> RawBill:
    form = dict(form)
    uea = form.pop("user_entered_amount", None)
    return RawBill(source="manual", fields=form, file_path=None, filename="manual entry",
                   user_entered_amount=uea)


def _attachments_from_message(msg) -> list[RawBill]:
    out = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        fname = part.get_filename() or ""
        ctype = part.get_content_type()
        ext = Path(fname).suffix.lower()
        if ext not in ALLOWED_EXT:
            ext = ATTACHMENT_TYPES.get(ctype, "")
        if not ext:
            continue
        data = part.get_payload(decode=True)
        if not data:
            continue
        path, h = _store(data, fname or f"attachment{ext}")
        out.append(RawBill(source="email", file_path=path, file_hash=h,
                           filename=f"{fname or 'attachment'} (from: {msg.get('Subject', '')})"))
    return out


def _fetch_imap() -> list[RawBill]:
    out = []
    conn = imaplib.IMAP4_SSL("imap.gmail.com")
    try:
        conn.login(config.GMAIL_IMAP_USER, config.GMAIL_IMAP_APP_PASSWORD)
        conn.select("INBOX")
        typ, data = conn.search(None, "UNSEEN")
        ids = data[0].split()[-20:] if typ == "OK" and data and data[0] else []
        for mid in ids:
            typ, msg_data = conn.fetch(mid, "(RFC822)")
            if typ != "OK":
                continue
            msg = email.message_from_bytes(msg_data[0][1], policy=policy.default)
            out.extend(_attachments_from_message(msg))
    finally:
        try:
            conn.logout()
        except Exception:
            pass
    return out


def ingest_email() -> list[RawBill]:
    """IMAP inbox if credentials are set, else sample_data/inbox/*.eml. One RawBill per attachment."""
    if config.GMAIL_IMAP_USER and config.GMAIL_IMAP_APP_PASSWORD:
        return _fetch_imap()
    out = []
    for eml in sorted(config.INBOX_DIR.glob("*.eml")):
        msg = email.message_from_bytes(eml.read_bytes(), policy=policy.default)
        out.extend(_attachments_from_message(msg))
    return out


BANK_COLUMNS = ["date", "description", "amount", "currency", "type", "account"]


def import_bank_csv(text: str) -> tuple[int, int, list[str]]:
    """Import a bank/card statement CSV (columns: date,description,amount,currency,type,account).
    -> (added, skipped_existing, errors). Rows with unknown currency are rejected, not guessed."""
    import csv
    from datetime import date as _date

    from core import db
    from core.models import Transaction

    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    cols = [c.strip().lower() for c in (reader.fieldnames or [])]
    if cols != BANK_COLUMNS:
        return 0, 0, [f"Expected columns {','.join(BANK_COLUMNS)}; got {','.join(cols)}"]
    added = skipped = 0
    errors = []
    for i, row in enumerate(reader, start=2):
        row = {k.strip().lower(): (v or "").strip() for k, v in row.items()}
        try:
            _date.fromisoformat(row["date"])
            amount = float(row["amount"])
            cur = row["currency"].upper()
            typ = row["type"].upper()
            if typ not in ("DEBIT", "CREDIT"):
                raise ValueError(f"type must be DEBIT/CREDIT, got {typ}")
            rate = config.FX_TABLE.get(cur)
            if rate is None:
                raise ValueError(f"currency {cur} not in sample FX table")
            t = Transaction(None, row["date"], row["description"], amount, cur, round(amount * rate, 2),
                            typ, row["account"])
        except (ValueError, KeyError) as e:
            errors.append(f"Row {i}: {e}")
            continue
        if db.insert_transaction(t):
            added += 1
        else:
            skipped += 1
    return added, skipped, errors


def email_source_label() -> str:
    if config.GMAIL_IMAP_USER and config.GMAIL_IMAP_APP_PASSWORD:
        return f"Gmail IMAP ({config.GMAIL_IMAP_USER})"
    return "sample_data/inbox/*.eml (no Gmail credentials configured)"
