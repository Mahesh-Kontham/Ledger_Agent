"""Merchant normalization + category mapping (alias substring, longest alias first)."""
from __future__ import annotations

from typing import Optional

from core import db


def _aliases() -> list[tuple[str, str, str]]:
    rows = [(r["alias"], r["merchant_normalized"], r["category"]) for r in db.list_aliases()]
    return sorted(rows, key=lambda r: len(r[0]), reverse=True)


def find_alias(name: Optional[str]) -> Optional[tuple[str, str, str]]:
    if not name:
        return None
    low = name.lower()
    for alias, norm, cat in _aliases():
        if alias in low:
            return alias, norm, cat
    return None


def normalize_merchant(name: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """raw merchant -> (merchant_normalized, category). None stays None (never guessed)."""
    if not name:
        return None, None
    hit = find_alias(name)
    if hit:
        return hit[1], hit[2]
    return name.strip().title(), "Other"


def match_key(merchant_raw: Optional[str], merchant_normalized: Optional[str]) -> Optional[str]:
    """Lowercase string to look for in a bank description: the alias, else the normalized name."""
    hit = find_alias(merchant_raw) or find_alias(merchant_normalized)
    if hit:
        return hit[0]
    return merchant_normalized.lower() if merchant_normalized else None
