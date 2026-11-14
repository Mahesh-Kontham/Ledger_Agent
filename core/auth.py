"""Authentication: bcrypt password hashing, login, demo-user seeding (PRD Section 18)."""
from __future__ import annotations

import os
import re
from typing import Optional

import bcrypt

from core import db

ROLES = ["ADMIN", "BUSINESS", "INDIVIDUAL"]

# (email, name, role, org, env var holding the password)
DEMO_USERS = [
    ("admin@demo", "Platform Admin", "ADMIN", "LedgerTruth", "DEMO_ADMIN_PW"),
    ("business@demo", "Ravi Kumar", "BUSINESS", "Kumar Traders Pvt Ltd", "DEMO_BUSINESS_PW"),
    ("user@demo", "Priya Sharma", "INDIVIDUAL", None, "DEMO_USER_PW"),
]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        return False


def create_user(name: str, email: str, password: str, role: str, org_name: Optional[str] = None) -> int:
    email = email.strip().lower()
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+", email):
        raise ValueError("Enter a valid email")
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    if db.get_user_for_login(email):
        raise ValueError("A user with this email already exists")
    return db.insert_user(name.strip(), email, hash_password(password), role, org_name or None)


def login(email: str, password: str) -> Optional[dict]:
    """Returns the public user dict on success (and logs it), else None. Same error for every failure."""
    row = db.get_user_for_login(email or "")
    if not row or not row.get("is_active") or not verify_password(password or "", row["password_hash"]):
        return None
    user = {k: v for k, v in row.items() if k != "password_hash"}
    db.log_action("login", user["email"], user_id=user["id"])
    return user


def seed_demo_users(verbose: bool = False) -> list[str]:
    """Create the 3 demo accounts from DEMO_*_PW env vars (skips existing or missing passwords)."""
    db.init_db()
    created = []
    for email, name, role, org, env in DEMO_USERS:
        pw = os.environ.get(env, "").strip()
        if db.get_user_for_login(email):
            if verbose:
                print(f"  exists   {email}")
            continue
        if not pw:
            if verbose:
                print(f"  SKIPPED  {email}: set {env} in .env")
            continue
        create_user(name, email, pw, role, org)
        created.append(email)
        if verbose:
            print(f"  created  {email} ({role})")
    moved = db.assign_orphans()
    if verbose and moved:
        print(f"  assigned {moved} pre-existing row(s) to business@demo")
    return created
