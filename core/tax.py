"""Flexible tax recognition (PRD Section 19).

Indian bills print tax under many names: GST, CGST, SGST, UTGST, IGST, cess, VAT, service tax,
"GST @18%", "Output CGST 9%", "Tax"... All of these are tax. This module recognises such printed
lines and adds them up. It only ever sums amounts that are printed on the bill - it never estimates
tax from a rate or from the total.
"""
from __future__ import annotations

import re
from typing import Optional

# Words that make a line a tax line
_TAX = re.compile(
    r"(?<![a-z])(?:c|s|i|ut)?\s*gst(?![a-z])"          # GST, CGST, SGST, IGST, UTGST, "C GST"
    r"|(?<![a-z])vat(?![a-z])"
    r"|(?<![a-z])cess(?![a-z])"
    r"|service\s+tax|sales\s+tax|swachh\s+bharat|krishi\s+kalyan"
    r"|(?<![a-z])tax(?:es)?(?![a-z])",
    re.I)
# Lines that mention tax words but are NOT tax amounts
_NOT_TAX = re.compile(
    r"gstin|gst\s*(?:no|number|reg|registration|#|id)|uin|tax\s+invoice|taxable|"
    r"incl(?:usive|\.|uding)?\s*(?:of\s*)?(?:all\s*)?tax|before\s+tax|pre[-\s]?tax|"
    r"excl(?:usive|\.|uding)?\s*(?:of\s*)?tax|tax\s*(?:id|code|rate|%)|hsn|sac|"
    r"round(?:ing|ed)?\s*off|amount\s+in\s+words|(?<![a-z])tds(?![a-z])",
    re.I)
# A printed tax total ("Total GST", "Total tax", "GST total", "Net tax")
_TOTAL = re.compile(r"total|(?<![a-z])sum(?![a-z])|net\s+tax|tax\s+amount", re.I)

COMPONENTS = [("CGST", r"(?<![a-z])c\s*gst"), ("SGST", r"(?<![a-z])s\s*gst"), ("UTGST", r"ut\s*gst"),
              ("IGST", r"(?<![a-z])i\s*gst"), ("CESS", r"cess"), ("VAT", r"(?<![a-z])vat"),
              ("GST", r"gst"), ("TAX", r"tax")]

GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


def is_tax_line(description: str) -> bool:
    d = description or ""
    return bool(_TAX.search(d)) and not _NOT_TAX.search(d)


def component_of(description: str) -> str:
    d = (description or "").lower()
    for name, pat in COMPONENTS:
        if re.search(pat, d):
            return name
    return "TAX"


def normalize_gstin(value) -> Optional[str]:
    """Accept 'GSTIN: 29abcde1234f1z5' / with spaces; return the 15-char GSTIN or None if invalid."""
    if not value:
        return None
    v = re.sub(r"[^0-9A-Za-z]", "", str(value)).upper()
    v = re.sub(r"^(GSTIN|GSTNO|GST|UIN)", "", v) if len(v) > 15 else v
    return v if GSTIN_RE.match(v) else None


def tax_breakdown(lines: list[dict]) -> list[dict]:
    """Printed tax lines (deduplicated) as [{'component', 'description', 'amount', 'is_total'}]."""
    seen, out = set(), []
    for it in lines or []:
        desc, amt = str(it.get("description", "")), it.get("amount")
        if not isinstance(amt, (int, float)) or isinstance(amt, bool) or not is_tax_line(desc):
            continue
        key = (re.sub(r"\s+", " ", desc.strip().lower()), round(float(amt), 2))
        if key in seen:
            continue
        seen.add(key)
        out.append({"component": component_of(desc), "description": desc, "amount": round(float(amt), 2),
                    "is_total": bool(_TOTAL.search(desc))})
    return out


def tax_from_lines(lines: list[dict]) -> Optional[float]:
    """Total tax from printed lines: a printed tax total wins; else the sum of printed components."""
    br = tax_breakdown(lines)
    totals = [b["amount"] for b in br if b["is_total"]]
    comps = [b["amount"] for b in br if not b["is_total"]]
    if totals:
        return round(totals[-1], 2)
    if comps:
        return round(sum(comps), 2)
    return None
