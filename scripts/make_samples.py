"""Generate sample_data/ (PRD Section 12). The ONLY place demo values exist.

Run:  python scripts/make_samples.py
"""
from __future__ import annotations

import sys
from email.message import EmailMessage
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "sample_data"
INBOX = OUT / "inbox"

BANK_CSV = """date,description,amount,currency,type,account
2026-11-10,SWIGGY BANGALORE,456.00,INR,DEBIT,HDFC Credit Card
2026-11-11,RAPIDO RIDE,130.00,INR,DEBIT,HDFC Credit Card
2026-11-12,AMAZON PAY UPI,1299.00,INR,DEBIT,HDFC Bank Account
2026-11-12,NOTION LABS USD 10.00,870.00,INR,DEBIT,HDFC Credit Card
"""


def _font(size: int, bold: bool = False):
    candidates = (["arialbd.ttf", "DejaVuSans-Bold.ttf"] if bold else ["arial.ttf", "DejaVuSans.ttf"])
    for name in candidates:
        for base in ["C:/Windows/Fonts", "/usr/share/fonts/truetype/dejavu", "/Library/Fonts", ""]:
            try:
                return ImageFont.truetype(str(Path(base) / name) if base else name, size)
            except OSError:
                continue
    return ImageFont.load_default(size=size)


def receipt(lines: list[tuple[str, str]], width: int = 640) -> Image.Image:
    """lines: list of (style, text) where style in title|text|bold|rule|row:<left>|<right>."""
    title_f, text_f, bold_f = _font(34, True), _font(24), _font(26, True)
    height = 80 + 44 * len(lines)
    img = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(img)
    y = 40
    for style, text in lines:
        if style == "title":
            w = d.textlength(text, font=title_f)
            d.text(((width - w) / 2, y), text, fill="black", font=title_f)
        elif style == "rule":
            d.line([(30, y + 18), (width - 30, y + 18)], fill="black", width=2)
        elif style.startswith("row"):
            left, right = text.split("|")
            f = bold_f if style == "rowbold" else text_f
            d.text((40, y), left, fill="black", font=f)
            w = d.textlength(right, font=f)
            d.text((width - 40 - w, y), right, fill="black", font=f)
        else:
            d.text((40, y), text, fill="black", font=bold_f if style == "bold" else text_f)
        y += 44
    return img


def main() -> None:
    OUT.mkdir(exist_ok=True)
    INBOX.mkdir(exist_ok=True)

    # 1. Swiggy - clean bill
    receipt([
        ("title", "SWIGGY"), ("text", "Order #SW1001"), ("text", "Date: 2026-11-10"), ("rule", ""),
        ("row", "Paneer Biryani x1|320.00"), ("row", "Butter Naan x2|90.00"), ("row", "GST|46.00"),
        ("rule", ""), ("rowbold", "TOTAL (INR)|₹456.00"), ("text", "Currency: INR"),
        ("text", "Paid by: Card"),
    ]).save(OUT / "bill1_swiggy.png")

    # 2. Rapido - card debited 130 vs invoice 125
    receipt([
        ("title", "RAPIDO"), ("text", "Ride #RP2002"), ("text", "Date: 2026-11-11"), ("rule", ""),
        ("row", "Ride fare|119.05"), ("row", "GST|5.95"), ("rule", ""),
        ("rowbold", "TOTAL (INR)|₹125.00"), ("text", "Currency: INR"), ("text", "Paid by: Card"),
    ]).save(OUT / "bill2_rapido.png")

    # 4. Amazon - EXIF Software = Adobe Photoshop
    img = receipt([
        ("title", "AMAZON"), ("text", "Order #AMZ4004"), ("text", "Date: 2026-11-12"), ("rule", ""),
        ("row", "Wireless Mouse x1|1,299.00"), ("rule", ""), ("rowbold", "TOTAL (INR)|₹1,299.00"),
        ("text", "Currency: INR"), ("text", "Paid by: UPI"),
    ])
    exif = Image.Exif()
    exif[305] = "Adobe Photoshop"          # 0x0131 Software
    img.save(OUT / "bill4_amazon_edited.png", exif=exif)

    # 5. Zomato - items listed, NO date, NO total
    receipt([
        ("title", "ZOMATO"), ("text", "Order #ZO5005"), ("rule", ""),
        ("row", "Masala Dosa x1|180.00"), ("row", "Filter Coffee x2|120.00"), ("rule", ""),
        ("text", "Currency: INR"), ("text", "Paid by: UPI"),
    ]).save(OUT / "bill5_zomato_blank.png")

    # 6. Notion invoice PDF inside an .eml
    pdf_path = OUT / "notion_invoice.pdf"
    receipt([
        ("title", "Notion Labs, Inc."), ("bold", "INVOICE"), ("text", "Invoice #NT6006"),
        ("text", "Date: 2026-11-12"), ("rule", ""), ("row", "Notion Plus - monthly|USD 10.00"),
        ("rule", ""), ("rowbold", "TOTAL (USD)|$10.00"), ("text", "Currency: USD"),
        ("text", "Paid by: Card (Visa ending 4242)"),
    ]).save(pdf_path, "PDF", resolution=150)

    msg = EmailMessage()
    msg["From"] = "billing@notion.example"
    msg["To"] = "me@example.com"
    msg["Subject"] = "Your Notion invoice NT6006"
    msg["Date"] = "Thu, 12 Nov 2026 10:00:00 +0530"
    msg.set_content("Hi,\n\nPlease find your invoice attached.\n\nNotion Labs")
    msg.add_attachment(pdf_path.read_bytes(), maintype="application", subtype="pdf",
                       filename="notion_invoice.pdf")
    (INBOX / "notion.eml").write_bytes(bytes(msg))

    (OUT / "bank_statement.csv").write_text(BANK_CSV, encoding="utf-8", newline="\n")

    print("Generated:")
    for p in sorted(OUT.rglob("*")):
        if p.is_file():
            print("  ", p.relative_to(ROOT))


if __name__ == "__main__":
    sys.exit(main())
