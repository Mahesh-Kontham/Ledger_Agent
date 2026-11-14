"""Gmail via Google sign-in (OAuth 2.0, read-only) - PRD Section 19.

Each user connects their own mailbox. "Fetch new bills" pulls only messages that were not
imported before (tracked in mail_seen), so repeated syncs pick up just the updated emails.

Setup (one time, by whoever runs the app):
  1. Google Cloud console -> APIs & Services -> enable "Gmail API".
  2. OAuth consent screen (External, add yourself as a test user).
  3. Credentials -> Create OAuth client ID -> "Desktop app" -> download JSON.
  4. Save it as google_oauth_client.json in the project root (or set GOOGLE_OAUTH_CLIENT_FILE).
The sign-in opens in the browser of the machine running Streamlit, so this flow is for local use.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Optional

from core import config, db, ingest
from core.models import RawBill

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
API = "https://gmail.googleapis.com/gmail/v1/users/me"
ATTACHMENT_EXT = {".pdf", ".jpg", ".jpeg", ".png"}
SEARCH = "has:attachment newer_than:{days}d (filename:pdf OR filename:jpg OR filename:jpeg OR filename:png)"


def client_file() -> Path:
    return Path(config.GOOGLE_OAUTH_CLIENT_FILE)


def oauth_configured() -> bool:
    return client_file().exists()


def connected_account() -> Optional[dict]:
    acc = db.get_mail_account()
    if acc:
        acc = {k: v for k, v in acc.items() if k != "token_json"}
    return acc


# ---------------- sign-in ----------------
def connect_gmail(timeout_seconds: int = 180) -> str:
    """Open Google sign-in in the browser, store the read-only token for the current user. Returns the email."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not oauth_configured():
        raise RuntimeError(f"Google sign-in is not set up: {client_file()} not found")
    flow = InstalledAppFlow.from_client_secrets_file(str(client_file()), SCOPES)
    creds = flow.run_local_server(
        port=0, open_browser=True, timeout_seconds=timeout_seconds, prompt="consent", access_type="offline",
        authorization_prompt_message="",
        success_message="Gmail connected to LedgerTruth. You can close this tab and go back to the app.")
    from google.auth.transport.requests import AuthorizedSession
    email = AuthorizedSession(creds).get(f"{API}/profile", timeout=20).json().get("emailAddress", "")
    db.save_mail_account("gmail", email, creds.to_json())
    return email


def disconnect() -> None:
    acc = db.get_mail_account()
    if acc:
        try:  # best effort: revoke the token at Google
            import requests
            token = json.loads(acc["token_json"]).get("refresh_token") or json.loads(acc["token_json"]).get("token")
            requests.post("https://oauth2.googleapis.com/revoke", params={"token": token}, timeout=10)
        except Exception:
            pass
    db.delete_mail_account()


def _session():
    from google.auth.transport.requests import AuthorizedSession, Request
    from google.oauth2.credentials import Credentials

    acc = db.get_mail_account()
    if not acc:
        raise RuntimeError("No mailbox connected")
    creds = Credentials.from_authorized_user_info(json.loads(acc["token_json"]), SCOPES)
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
        db.update_mail_token(creds.to_json())
    return AuthorizedSession(creds)


# ---------------- parsing (pure, unit-tested) ----------------
def header(message: dict, name: str) -> str:
    for h in message.get("payload", {}).get("headers", []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def attachment_parts(message: dict) -> list[dict]:
    """Walk a Gmail 'full' message and return bill attachments: [{filename, attachment_id | data}]."""
    out = []

    def walk(part):
        fname = part.get("filename") or ""
        body = part.get("body") or {}
        if fname and Path(fname).suffix.lower() in ATTACHMENT_EXT and (body.get("attachmentId") or body.get("data")):
            out.append({"filename": fname, "attachment_id": body.get("attachmentId"), "data": body.get("data")})
        for p in part.get("parts") or []:
            walk(p)

    walk(message.get("payload") or {})
    return out


def _b64url(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


# ---------------- sync ----------------
def fetch_new_bills(days: int = 30, max_messages: int = 25, session=None) -> tuple[list[RawBill], list[str]]:
    """New (not yet imported) bill attachments from the connected Gmail.
    Returns (raw bills, message ids to mark as seen once processed)."""
    s = session or _session()
    seen = db.mail_seen_ids()
    resp = s.get(f"{API}/messages", params={"q": SEARCH.format(days=days), "maxResults": max_messages}, timeout=30)
    resp.raise_for_status()
    ids = [m["id"] for m in resp.json().get("messages", []) if m["id"] not in seen]
    raws, handled = [], []
    for mid in ids:
        msg = s.get(f"{API}/messages/{mid}", params={"format": "full"}, timeout=30)
        msg.raise_for_status()
        msg = msg.json()
        subject = header(msg, "Subject")
        for att in attachment_parts(msg):
            data = att["data"]
            if not data and att["attachment_id"]:
                a = s.get(f"{API}/messages/{mid}/attachments/{att['attachment_id']}", timeout=30)
                a.raise_for_status()
                data = a.json().get("data")
            if not data:
                continue
            path, h = ingest._store(_b64url(data), att["filename"])
            raws.append(RawBill(source="email", file_path=path, file_hash=h,
                                filename=f"{att['filename']} (from: {subject})"))
        handled.append(mid)
    return raws, handled


def finish_sync(handled_ids: list[str]) -> None:
    db.mark_mail_seen(handled_ids)
    db.touch_mail_sync()
