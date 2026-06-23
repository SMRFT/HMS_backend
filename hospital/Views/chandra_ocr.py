from __future__ import annotations
from django.shortcuts import render
from rest_framework.response import Response
from django.http import JsonResponse
from rest_framework import status
from pymongo import MongoClient
from django.utils.timezone import now
from rest_framework.parsers import MultiPartParser, FormParser
from bson import Decimal128, ObjectId
from datetime import datetime
from decimal import Decimal, InvalidOperation
from django.utils import timezone
import traceback
import logging
import json
import os
import io
import re
from typing import Any
from rest_framework.decorators import api_view, permission_classes,parser_classes
from django.views.decorators.csrf import csrf_exempt
import pytesseract
import shutil

# Auto-detect Tesseract binary path dynamically based on platform and PATH
tesseract_in_path = shutil.which("tesseract")
if tesseract_in_path:
    pytesseract.pytesseract.tesseract_cmd = tesseract_in_path
elif os.path.exists("/usr/bin/tesseract"):
    pytesseract.pytesseract.tesseract_cmd = "/usr/bin/tesseract"
elif os.path.exists("/opt/homebrew/bin/tesseract"):
    pytesseract.pytesseract.tesseract_cmd = "/opt/homebrew/bin/tesseract"
else:
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

try:
    print("Tesseract Version:", pytesseract.get_tesseract_version())
except Exception as e:
    print("Warning: Tesseract version could not be retrieved:", e)
# Auth/permissions
from pyauth.auth import HasRoleAndDataPermission

# Logger setup
logger = logging.getLogger(__name__)


"""
grn_ocr_view.py  —  OCR endpoint for GRN auto-fill
────────────────────────────────────────────────────
Accepts: multipart/form-data  →  field "file" (image or PDF)
Returns: JSON with extracted GRN fields + line items

Dependencies:
    pip install chandra-ocr Pillow pdf2image pytesseract

Chandra OCR wraps Tesseract and provides structured invoice parsing.
Falls back gracefully if chandra_ocr is not installed.
"""



# ─── Optional heavy imports — handle gracefully ────────────────────────────

def _import_pillow():
    try:
        from PIL import Image
        return Image
    except ImportError:
        return None

def _import_pdf2image():
    try:
        import pdf2image
        return pdf2image
    except ImportError:
        return None

def _import_chandra():
    """
    Try to import chandra OCR package.
    """
    try:
        import chandra
        return chandra
    except ImportError:
        return None

def _import_pytesseract():
    try:
        import pytesseract

        tesseract_in_path = shutil.which("tesseract")

        if tesseract_in_path:
            pytesseract.pytesseract.tesseract_cmd = tesseract_in_path

        elif os.path.exists("/usr/bin/tesseract"):
            pytesseract.pytesseract.tesseract_cmd = "/usr/bin/tesseract"

        elif os.path.exists("/opt/homebrew/bin/tesseract"):
            pytesseract.pytesseract.tesseract_cmd = "/opt/homebrew/bin/tesseract"

        elif os.path.exists(r"C:\Program Files\Tesseract-OCR\tesseract.exe"):
            pytesseract.pytesseract.tesseract_cmd = (
                r"C:\Program Files\Tesseract-OCR\tesseract.exe"
            )

        else:
            logger.warning("Tesseract binary not found")
            return None

        try:
            logger.info(
                "Tesseract Version: %s",
                pytesseract.get_tesseract_version()
            )
        except Exception as e:
            logger.warning(
                "Tesseract version could not be retrieved: %s",
                e
            )

        return pytesseract

    except ImportError:
        logger.warning("pytesseract is not installed")
        return None


# ─── Month helpers ────────────────────────────────────────────────────────────

MONTH_MAP = {
    "jan":"01","feb":"02","mar":"03","apr":"04","may":"05","jun":"06",
    "jul":"07","aug":"08","sep":"09","oct":"10","nov":"11","dec":"12",
    "january":"01","february":"02","march":"03","april":"04","june":"06",
    "july":"07","august":"08","september":"09","october":"10",
    "november":"11","december":"12",
}

def _normalise_month(raw: str) -> str:
    """Return 2-digit month string or empty string."""
    raw = raw.strip().lower()
    if raw in MONTH_MAP:
        return MONTH_MAP[raw]
    if raw.isdigit() and 1 <= int(raw) <= 12:
        return raw.zfill(2)
    return ""

def _parse_expiry(text: str):
    """
    Try to extract MM and YYYY from common expiry formats:
      MM/YYYY  MM-YYYY  MM/YY  MonName/YYYY  MonName-YYYY  etc.
    Returns (month_str, year_str) or ("", "")
    """
    text = text.strip()

    # MM/YYYY or MM-YYYY
    m = re.match(r"^(\d{1,2})[/\-](\d{4})$", text)
    if m:
        return m.group(1).zfill(2), m.group(2)

    # MM/YY
    m = re.match(r"^(\d{1,2})[/\-](\d{2})$", text)
    if m:
        yr = "20" + m.group(2)
        return m.group(1).zfill(2), yr

    # MonName/YYYY or MonName-YYYY
    m = re.match(r"^([A-Za-z]+)[/\-](\d{4})$", text)
    if m:
        mon = _normalise_month(m.group(1))
        return mon, m.group(2)

    # MonName/YY
    m = re.match(r"^([A-Za-z]+)[/\-](\d{2})$", text)
    if m:
        mon = _normalise_month(m.group(1))
        yr  = "20" + m.group(2)
        return mon, yr

    return "", ""


# ─── Text → structured GRN dict ──────────────────────────────────────────────

# Compiled patterns (case-insensitive)
_RE_INVOICE_NO   = re.compile(r"(?:invoice\s*(?:no|number|#)\s*[:\-]?\s*)([A-Z0-9\-/]+)", re.I)
_RE_INVOICE_DATE = re.compile(
    r"(?:invoice\s*date\s*[:\-]?\s*)(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})", re.I)
_RE_VENDOR_NAME  = re.compile(
    r"(?:(?:sold\s*by|vendor|supplier|from|bill\s*from)\s*[:\-]?\s*)([A-Za-z0-9 &.,()'\-]+)", re.I)
_RE_GST_NO       = re.compile(r"\b(\d{2}[A-Z]{5}\d{4}[A-Z]\d[Z][A-Z\d])\b")
_RE_TOTAL        = re.compile(
    r"(?:total\s*(?:amount|amt|value)?\s*[:\-]?\s*₹?\s*)([\d,]+(?:\.\d{1,4})?)", re.I)
_RE_CGST         = re.compile(
    r"(?:cgst\s*[:\-]?\s*₹?\s*)([\d,]+(?:\.\d{1,4})?)", re.I)
_RE_SGST         = re.compile(
    r"(?:sgst\s*[:\-]?\s*₹?\s*)([\d,]+(?:\.\d{1,4})?)", re.I)
_RE_TAXABLE      = re.compile(
    r"(?:taxable\s*(?:amount|value|amt)?\s*[:\-]?\s*₹?\s*)([\d,]+(?:\.\d{1,4})?)", re.I)
_RE_DISCOUNT     = re.compile(
    r"(?:(?:total\s*)?discount\s*[:\-]?\s*₹?\s*)([\d,]+(?:\.\d{1,4})?)", re.I)
_RE_NET_AMOUNT   = re.compile(
    r"(?:net\s*(?:amount|amt|total|invoice\s*amount)\s*[:\-]?\s*₹?\s*)([\d,]+(?:\.\d{1,4})?)", re.I)
_RE_PAYMENT_MODE = re.compile(r"\b(cheque|cash|dd|neft|rtgs|upi|credit|debit)\b", re.I)

# Line-item pattern: tries to capture description + qty + rate + amount
_RE_LINE_ITEM = re.compile(
    r"^(?P<name>[A-Za-z][A-Za-z0-9 &.,\-()%/]+?)"           # item name
    r"\s+(?:(?P<hsn>\d{4,8})\s+)?"                           # optional HSN
    r"(?P<qty>[\d.]+)\s+"                                     # quantity
    r"(?:(?P<free>[\d.]+)\s+)?"                               # optional free qty
    r"(?:(?P<batch>[A-Z]{0,3}\d{3,}[A-Z0-9\-]*)\s+)?"        # optional batch
    r"(?:(?P<expiry>\d{1,2}[/\-]\d{2,4}|[A-Za-z]{3}[/\-]\d{2,4})\s+)?"  # optional expiry
    r"(?P<rate>[\d,]+(?:\.\d{1,4})?)[\s\t]+"                 # rate / packing price
    r"(?P<amount>[\d,]+(?:\.\d{1,4})?)$",                    # line total
    re.MULTILINE,
)

def _clean_num(s: str) -> str:
    return s.replace(",", "").strip() if s else "0"


def _parse_date_to_iso(raw: str) -> str:
    """Convert DD/MM/YYYY or DD-MM-YYYY to YYYY-MM-DD."""
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y"):
        try:
            return datetime.strptime(raw.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return raw.strip()


def _extract_fields(text: str) -> dict[str, Any]:
    """
    Parse raw OCR text and return a dict matching the GRN form fields.
    All fields are best-effort; missing fields return empty string / "0.00".
    """
    result: dict[str, Any] = {
        # Header
        "invoice_no":           "",
        "invoice_date":         "",
        "vendor_name":          "",          # for UI hint (vendor lookup)
        "vendor_gstin":         "",
        "payment_mode":         "CHEQUE",    # sensible default
        # Financials
        "taxable_amount":       "0.00",
        "cgst":                 "0.00",
        "sgst":                 "0.00",
        "total_discount":       "0.00",
        "total_amount":         "0.00",
        "net_invoice_amount":   "0.00",
        # Items
        "items":                [],
        # Raw text for debugging
        "_raw_text_preview":    text[:500],
    }

    # ── Header fields ──────────────────────────────────────────────────────
    m = _RE_INVOICE_NO.search(text)
    if m:
        result["invoice_no"] = m.group(1).strip()

    m = _RE_INVOICE_DATE.search(text)
    if m:
        result["invoice_date"] = _parse_date_to_iso(m.group(1))

    m = _RE_VENDOR_NAME.search(text)
    if m:
        result["vendor_name"] = m.group(1).strip()[:80]

    m = _RE_GST_NO.search(text)
    if m:
        result["vendor_gstin"] = m.group(1)

    m = _RE_PAYMENT_MODE.search(text)
    if m:
        pm = m.group(1).upper()
        if pm in ("CHEQUE", "CASH", "DD"):
            result["payment_mode"] = pm
        else:
            result["payment_mode"] = "CHEQUE"   # unmapped → default

    # ── Financials ─────────────────────────────────────────────────────────
    for pattern, key in [
        (_RE_TAXABLE,   "taxable_amount"),
        (_RE_CGST,      "cgst"),
        (_RE_SGST,      "sgst"),
        (_RE_DISCOUNT,  "total_discount"),
        (_RE_TOTAL,     "total_amount"),
        (_RE_NET_AMOUNT,"net_invoice_amount"),
    ]:
        m = pattern.search(text)
        if m:
            result[key] = _clean_num(m.group(1))

    # ── Line items ─────────────────────────────────────────────────────────
    items = []
    for m in _RE_LINE_ITEM.finditer(text):
        g = m.groupdict()
        name      = g["name"].strip()
        qty_str   = _clean_num(g.get("qty", "0"))
        rate_str  = _clean_num(g.get("rate", "0"))
        amount_str= _clean_num(g.get("amount", "0"))
        expiry_raw= g.get("expiry") or ""

        exp_month, exp_year = _parse_expiry(expiry_raw)

        try:
            qty  = float(qty_str)
            rate = float(rate_str)
        except ValueError:
            qty, rate = 0.0, 0.0

        # Skip header-like lines
        if not name or name.lower() in ("description","item","particulars","product"):
            continue

        item_dict = {
            "name":          name,
            "item_id":       "",            # must be resolved by frontend lookup
            "hsn":           g.get("hsn") or "",
            "batch":         g.get("batch") or "",
            "expiry_month":  exp_month,
            "expiry_year":   exp_year,
            "expiry":        f"{exp_month}/{exp_year}" if exp_month and exp_year else "",
            "packing":       "1",           # default — user adjusts
            "unit":          str(int(qty)) if qty == int(qty) else str(qty),
            "quantity":      str(qty),
            "free":          _clean_num(g.get("free", "0")) or "0",
            "packing_price": rate_str,
            "item_value":    amount_str,
            # Purchase tax defaults (user must confirm)
            "purchase_tax_label": "RATE OF 5%",
            "purchase_tax_rate":  "5",
            "cgst_percent":       "2.50",
            "sgst_percent":       "2.50",
            "cgst_amt":           "0.00",
            "sgst_amt":           "0.00",
            "purchase_discount":  "0",
            "purchase_discount_amt": "0.00",
            "deduct_discount_for_tax": True,
            "purchase_cost":      amount_str,
            # Selling defaults
            "mrp":                rate_str,    # starting guess
            "selling_discount":   "0",
            "selling_price":      rate_str,
            "tax_inclusive":      True,
            "selling_tax_label":  "RATE OF 5%",
            "selling_tax_rate":   "5",
            "selling_cgst_percent":"2.50",
            "selling_sgst_percent":"2.50",
            "selling_cgst_amt":   "0.0000",
            "selling_sgst_amt":   "0.0000",
        }
        items.append(item_dict)

    result["items"] = items
    return result


# ─── OCR engine: Chandra OCR → Tesseract fallback ────────────────────────────

def _ocr_with_chandra(image_bytes: bytes, mime: str) -> str:
    """
    Use Chandra OCR library for structured text extraction.
    Returns extracted plain text.
    """
    chandra = _import_chandra()
    Image   = _import_pillow()

    if chandra is None or Image is None:
        raise ImportError("chandra_ocr or Pillow not installed")

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")

    # Chandra OCR API:  chandra_ocr.extract(image: PIL.Image) -> str
    # Some versions accept file path; handle both:
    try:
        text = chandra.extract(img)
    except TypeError:
        # Fallback: save temp file and pass path
        import tempfile, pathlib
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
            img.save(tf.name)
            tmp_path = tf.name
        try:
            text = chandra.extract(tmp_path)
        finally:
            pathlib.Path(tmp_path).unlink(missing_ok=True)

    return text if isinstance(text, str) else str(text)


def _ocr_with_tesseract(image_bytes: bytes) -> str:
    """Fallback: raw pytesseract."""
    pytesseract = _import_pytesseract()
    Image       = _import_pillow()

    if pytesseract is None or Image is None:
        raise ImportError("pytesseract or Pillow not installed")

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    return pytesseract.image_to_string(img, lang="eng")


import os
import shutil

def _pdf_to_images(pdf_bytes: bytes) -> list[bytes]:
    """Convert each page of a PDF to PNG bytes."""
    pdf2image = _import_pdf2image()
    if pdf2image is None:
        raise ImportError("pdf2image not installed")

    # Dynamic poppler path detection: check PATH, then macOS, Ubuntu, and Windows candidates
    poppler_in_path = shutil.which("pdftoppm")
    poppler_path = None

    if not poppler_in_path:
        if os.path.exists("/opt/homebrew/bin/pdftoppm"):
            poppler_path = "/opt/homebrew/bin"
        elif os.path.exists("/usr/bin/pdftoppm"):
            poppler_path = "/usr/bin"
        else:
            candidates = [
                r"C:\poppler\Library\bin",
                r"C:\poppler\bin",
                r"C:\Program Files\poppler\Library\bin",
                r"C:\Program Files\poppler\bin",
            ]
            for candidate in candidates:
                if os.path.isfile(os.path.join(candidate, "pdfinfo.exe")):
                    poppler_path = candidate
                    break

    # If still not found, let pdf2image try PATH (will raise clear error if missing)
    kwargs = {"dpi": 300}
    if poppler_path:
        kwargs["poppler_path"] = poppler_path

    pages = pdf2image.convert_from_bytes(pdf_bytes, **kwargs)

    result = []
    for page in pages:
        buf = io.BytesIO()
        page.save(buf, format="PNG")
        result.append(buf.getvalue())

    return result

def _run_ocr(file_bytes: bytes, content_type: str) -> str:
    """
    Master OCR runner.
    1. Convert PDF → images if needed
    2. Try Chandra OCR first
    3. Fall back to Tesseract
    """
    mime = content_type.lower()

    # PDF → PNG pages
    if "pdf" in mime:
        pages = _pdf_to_images(file_bytes)
        texts = []
        for page_bytes in pages:
            try:
                texts.append(_ocr_with_chandra(page_bytes, "image/png"))
            except Exception:
                try:
                    texts.append(_ocr_with_tesseract(page_bytes))
                except Exception as e:
                    logger.warning("OCR failed for page: %s", e)
        return "\n".join(texts)

    # Image
    try:
        return _ocr_with_chandra(file_bytes, mime)
    except Exception as e:
        logger.warning("Chandra OCR failed (%s), falling back to Tesseract", e)
        return _ocr_with_tesseract(file_bytes)


# ─── Django view ─────────────────────────────────────────────────────────────

@api_view(["POST"])
# @permission_classes([HasRoleAndDataPermission])
@parser_classes([MultiPartParser, FormParser])
def grn_ocr_scan(request):
    """
    POST /api/pharmacy/grn-ocr/
    Body (multipart): file=<image|pdf>

    Returns:
    {
        "success": true,
        "data": {
            "invoice_no": "...",
            "invoice_date": "YYYY-MM-DD",
            "vendor_name": "...",
            "vendor_gstin": "...",
            "payment_mode": "CHEQUE",
            "taxable_amount": "...",
            "cgst": "...",
            "sgst": "...",
            "total_discount": "...",
            "total_amount": "...",
            "net_invoice_amount": "...",
            "items": [ { ...item fields... }, ... ]
        },
        "warnings": ["..."]  // non-fatal issues
    }
    """
    uploaded = request.FILES.get("file")
    if not uploaded:
        return Response(
            {"success": False, "error": "No file provided. Send field 'file' as multipart."},
            status=400,
        )

    content_type = uploaded.content_type or ""
    allowed = ("image/", "application/pdf")
    if not any(content_type.startswith(a) for a in allowed):
        return Response(
            {"success": False, "error": f"Unsupported file type: {content_type}. Send an image or PDF."},
            status=415,
        )

    max_size = 15 * 1024 * 1024   # 15 MB
    if uploaded.size > max_size:
        return Response(
            {"success": False, "error": "File too large. Maximum allowed size is 15 MB."},
            status=413,
        )

    warnings: list[str] = []

    try:
        file_bytes = uploaded.read()
        raw_text   = _run_ocr(file_bytes, content_type)
    except ImportError as e:
        return Response(
            {
                "success": False,
                "error": (
                    f"OCR library not installed on server: {e}. "
                    "Run: pip install chandra-ocr Pillow pdf2image pytesseract"
                ),
            },
            status=503,
        )
    except Exception as e:
        logger.exception("OCR processing error")
        return Response({"success": False, "error": f"OCR processing failed: {e}"}, status=500)

    if not raw_text or not raw_text.strip():
        warnings.append("OCR returned empty text — image quality may be too low.")

    extracted = _extract_fields(raw_text)

    if not extracted["invoice_no"]:
        warnings.append("Invoice number could not be detected — please fill manually.")
    if not extracted["items"]:
        warnings.append("No line items detected — please add items manually.")

    return Response({
        "success":  True,
        "data":     extracted,
        "warnings": warnings,
    })
