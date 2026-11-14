"""LLM extraction (PRD Section 6) -> ExtractedFields with per-field confidence.

Never guesses: low-confidence or invalid values become None.
"""
from __future__ import annotations

import base64
import io
import json
import re
from datetime import date
from pathlib import Path
from typing import Callable, Optional

from core import config
from core.models import ExtractedFields, RawBill

SYSTEM_PROMPT = """You extract data from a single receipt or invoice image. Return ONLY a JSON object, no prose.
Rules:
- If a value is not clearly visible, return null for "value". NEVER guess, infer, calculate or default a value.
- "confidence" is your certainty from 0.0 to 1.0 that "value" is exactly what is printed.
- Dates in YYYY-MM-DD. Amounts as numbers without currency symbols or commas.
- currency as ISO 4217 code (INR, USD, EUR...). If no symbol or code is printed, value = null.
- line_items: only lines actually printed. fee_items: printed lines that are fees, tips, surcharges or convenience charges.
Schema:
{
 "merchant":       {"value": string|null, "confidence": number},
 "bill_date":      {"value": string|null, "confidence": number},
 "invoice_number": {"value": string|null, "confidence": number},
 "total_amount":   {"value": number|null, "confidence": number},
 "tax_amount":     {"value": number|null, "confidence": number},
 "currency":       {"value": string|null, "confidence": number},
 "payment_mode":   {"value": "CARD"|"UPI"|"CASH"|"NETBANKING"|"WALLET"|null, "confidence": number},
 "gstin":          {"value": string|null, "confidence": number},
 "line_items":     [{"description": string, "amount": number}],
 "fee_items":      [{"description": string, "amount": number}]
}"""

FIELDS = ["merchant", "bill_date", "invoice_number", "total_amount", "tax_amount",
          "currency", "payment_mode", "gstin"]
NUMERIC = {"total_amount", "tax_amount"}

_client = None


def _get_client():
    global _client
    if _client is None:
        from google import genai
        if not config.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set")
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


# ---------------- image preparation ----------------
def _pdf_page1_png(path: str) -> bytes:
    try:
        from pdf2image import convert_from_path
        pages = convert_from_path(path, first_page=1, last_page=1, dpi=150)
        buf = io.BytesIO()
        pages[0].save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        import pymupdf
        doc = pymupdf.open(path)
        pix = doc[0].get_pixmap(dpi=150)
        return pix.tobytes("png")


def image_for_llm(path: str) -> tuple[bytes, str]:
    """Return (bytes, media_type) for the model. PDF -> page 1 PNG."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".pdf":
        return _pdf_page1_png(path), "image/png"
    data = p.read_bytes()
    media = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(ext)
    if media is None or len(data) > 4_500_000:
        from PIL import Image
        img = Image.open(io.BytesIO(data)).convert("RGB")
        img.thumbnail((2000, 2000))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        return buf.getvalue(), "image/jpeg"
    return data, media


# ---------------- LLM call ----------------
def _call_llm(image_bytes: bytes, media_type: str) -> str:
    from google.genai import types
    client = _get_client()
    resp = client.models.generate_content(
        model=config.LLM_MODEL,
        contents=[types.Part.from_bytes(data=image_bytes, mime_type=media_type),
                  "Extract the fields from this receipt/invoice."],
        config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT, temperature=0,
                                           response_mime_type="application/json"),
    )
    text = resp.text
    if not text:
        raise RuntimeError("Model returned no text (possibly blocked)")
    return text


def _parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object in response")
    obj = json.loads(text[start:end + 1])
    if not isinstance(obj, dict):
        raise ValueError("JSON is not an object")
    return obj


# ---------------- post-processing ----------------
def _coerce(field: str, value):
    """Validate type/format. Returns (value, ok). Invalid -> (None, False). Never repairs or guesses."""
    if value is None:
        return None, True
    if field in NUMERIC:
        if isinstance(value, bool):
            return None, False
        if isinstance(value, (int, float)):
            return float(value), True
        return None, False
    if field == "bill_date":
        try:
            date.fromisoformat(str(value))
            return str(value), True
        except ValueError:
            return None, False
    if field == "currency":
        v = str(value).strip().upper()
        return (v, True) if re.fullmatch(r"[A-Z]{3}", v) else (None, False)
    if field == "payment_mode":
        v = str(value).strip().upper()
        return (v, True) if v in config.PAYMENT_MODES else (None, False)
    v = str(value).strip()
    return (v, True) if v else (None, True)


def _items(raw) -> list:
    out = []
    for it in raw or []:
        if isinstance(it, dict) and isinstance(it.get("amount"), (int, float)) and not isinstance(it.get("amount"), bool):
            out.append({"description": str(it.get("description", "")), "amount": float(it["amount"])})
    return out


def postprocess(obj: dict) -> ExtractedFields:
    values, conf, low = {}, {}, []
    for f in FIELDS:
        entry = obj.get(f) if isinstance(obj.get(f), dict) else {}
        raw_val = entry.get("value")
        try:
            c = float(entry.get("confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            c = 0.0
        conf[f] = c
        val, ok = _coerce(f, raw_val)
        if not ok:
            low.append(f)
            val = None
        elif val is not None and c < config.CONFIDENCE_THRESHOLD:
            low.append(f)
            val = None
        values[f] = val
    return ExtractedFields(values=values, confidence=conf, low_confidence_fields=low,
                           line_items=_items(obj.get("line_items")),
                           fee_items=_items(obj.get("fee_items")), raw_response=obj)


def failed_extraction(error: str) -> ExtractedFields:
    return ExtractedFields(values={f: None for f in FIELDS}, confidence={f: 0.0 for f in FIELDS},
                           error=error)


def extract_fields(raw: RawBill, llm: Optional[Callable[[bytes, str], str]] = None) -> ExtractedFields:
    """RawBill -> ExtractedFields. Manual: fields copied, every confidence = 1.0."""
    if raw.source == "manual":
        values = {}
        for f in FIELDS:
            v, ok = _coerce(f, (raw.fields or {}).get(f))
            values[f] = v if ok else None
        return ExtractedFields(values=values, confidence={f: 1.0 for f in FIELDS},
                               line_items=_items((raw.fields or {}).get("line_items")),
                               fee_items=_items((raw.fields or {}).get("fee_items")))

    llm = llm or _call_llm
    try:
        img, media = image_for_llm(raw.file_path)
    except Exception as e:  # unreadable file
        return failed_extraction(f"Extraction failed: could not read file ({e})")

    last_err = None
    for _attempt in range(2):           # parse failure -> retry once
        try:
            text = llm(img, media)
        except Exception as e:          # API / auth / network error: no point retrying parse
            return failed_extraction(f"Extraction failed: {type(e).__name__}: {e}")
        try:
            return postprocess(_parse_json(text))
        except (ValueError, json.JSONDecodeError) as e:
            last_err = e
    return failed_extraction(f"Extraction failed: invalid JSON ({last_err})")
