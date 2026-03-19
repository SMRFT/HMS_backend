"""
views.py — Discharge Billing
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Djongo rule:
  ✅  .objects.all()           — safe
  ✅  .objects.get(pk=pk)      — safe  (pk == discharge_id)
  ❌  .filter().order_by()     — crashes Djongo

All filtering / sorting done in Python after full-collection fetch.
InvestBilling has no Django model → raw PyMongo only.

Primary key: discharge_id (IntegerField, auto-incremented in model.save())

Flows
─────
1. Direct Bill  : POST status=Billed   → bill_no generated, estimate_number=None
2. Estimate     : POST status=Estimate → estimate_number generated, bill_no=None
3. Edit Estimate: PATCH/<discharge_id>/          → update in-place, status stays Estimate
4. Convert      : POST  /<discharge_id>/convert-to-bill/ → flip status, generate bill_no
"""

import os
import datetime
import json as _json
from decimal import Decimal, InvalidOperation

from pymongo import MongoClient

try:
    from bson import Decimal128
    _HAS_DECIMAL128 = True
except ImportError:
    _HAS_DECIMAL128 = False

from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status

from pyauth.auth import HasRoleAndDataPermission
from ..models import Patient, Admission, DischargeBilling


# ─────────────────────────────────────────────────────────────────────────────
# Safe float conversion
# Handles: Decimal128 (bson), Decimal, smart-quoted str, plain str, None
# ─────────────────────────────────────────────────────────────────────────────

def _to_float(v):
    """
    Robustly convert any value from Djongo/MongoDB to a plain Python float.

    Problem sources:
      • Decimal128          — bson type; must go through .to_decimal() first
      • Decimal             — Python decimal.Decimal from Djongo layer
      • smart-quoted strings— e.g. '"190.00"' stored in older documents
      • None / ""           — treated as 0.0
    """
    if v is None:
        return 0.0

    if _HAS_DECIMAL128 and isinstance(v, Decimal128):
        try:
            return float(v.to_decimal())
        except Exception:
            return 0.0

    if isinstance(v, Decimal):
        try:
            return float(v)
        except Exception:
            return 0.0

    if isinstance(v, str):
        cleaned = (
            v.replace("\u201c", "")
             .replace("\u201d", "")
             .replace("\u2018", "")
             .replace("\u2019", "")
             .replace('"',      "")
             .replace("'",      "")
             .strip()
        )
        if not cleaned:
            return 0.0
        try:
            return float(cleaned)
        except (ValueError, TypeError):
            return 0.0

    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Raw PyMongo — InvestBilling ONLY
# ─────────────────────────────────────────────────────────────────────────────

def _invest_col():
    client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
    db = client.HMS
    collection = db.hospital_investbilling
    return collection


# ─────────────────────────────────────────────────────────────────────────────
# Number generators  (Djongo-safe: fetch ALL, filter in Python)
# ─────────────────────────────────────────────────────────────────────────────

def _financial_year():
    today = datetime.date.today()
    y = today.year
    if today.month >= 4:
        return f"{str(y)[2:]}{str(y + 1)[2:]}"
    return f"{str(y - 1)[2:]}{str(y)[2:]}"


def generate_estimate_number():
    """EST/YYMM/000001 — resets each calendar month."""
    today  = datetime.date.today()
    prefix = f"EST/{str(today.year)[2:]}{str(today.month).zfill(2)}/"
    seq = 1
    try:
        all_nums = DischargeBilling.objects.all().values_list("estimate_number", flat=True)
        matching = [n for n in all_nums if n and n.startswith(prefix)]
        if matching:
            seqs = []
            for n in matching:
                try:
                    seqs.append(int(n.split("/")[-1]))
                except Exception:
                    pass
            if seqs:
                seq = max(seqs) + 1
    except Exception:
        seq = 1
    return f"{prefix}{str(seq).zfill(6)}"


def generate_bill_number():
    """YYYY-YY/DCH/000001 — resets each financial year."""
    prefix = f"{_financial_year()}/DCH/"
    seq = 1
    try:
        all_nums = DischargeBilling.objects.all().values_list("bill_no", flat=True)
        matching = [n for n in all_nums if n and n.startswith(prefix)]
        if matching:
            seqs = []
            for n in matching:
                try:
                    seqs.append(int(n.split("/")[-1]))
                except Exception:
                    pass
            if seqs:
                seq = max(seqs) + 1
    except Exception:
        seq = 1
    return f"{prefix}{str(seq).zfill(6)}"


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_pk(discharge_id):
    """
    Return an active DischargeBilling or None, looked up by discharge_id.

    discharge_id is an IntegerField PK — always cast to int.
    Falls back to a full-scan string match for safety (ObjectId edge cases).
    """
    # Attempt 1: integer PK (normal path)
    try:
        obj = DischargeBilling.objects.get(discharge_id=int(discharge_id))
        return obj if obj.is_active else None
    except (ValueError, TypeError):
        pass
    except DischargeBilling.DoesNotExist:
        return None
    except Exception:
        pass

    # Attempt 2: string scan fallback
    try:
        for obj in DischargeBilling.objects.all():
            if str(obj.discharge_id) == str(discharge_id):
                return obj if obj.is_active else None
    except Exception:
        pass
    return None


def _parse_items(raw):
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            parsed = _json.loads(raw)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


def _safe_isoformat(dt):
    if dt is None:
        return None
    try:
        return dt.isoformat()
    except Exception:
        return None


# DecimalField names — used by _normalise_decimals before every .save()
_DECIMAL_FIELDS = [
    "total_amount", "advance_amount", "sales_return", "medicines_amount",
    "taxable_amount", "non_tax_amount", "gst_amount", "room_tax",
    "discount_percent", "discount_amount", "item_disc", "total_disc", "net_amount",
]


def _normalise_decimals(obj):
    """
    Re-write every DecimalField through _to_float so Djongo never receives
    a Decimal128 / smart-quoted string when validating on save().
    """
    for field in _DECIMAL_FIELDS:
        setattr(obj, field, _to_float(getattr(obj, field, None)))


def _obj_to_dict(obj):
    """Serialise a DischargeBilling instance to a JSON-safe dict."""
    # discharge_id is the PK — always an int (set by model.save())
    discharge_id = obj.discharge_id

    patient_details = {}
    if obj.uhid:
        try:
            p = Patient.objects.get(uhid=obj.uhid)
            patient_details = {
                "patient_name": f"{p.firstName} {p.lastName}".strip(),
                "age":    p.age,
                "gender": p.gender,
                "mobile": p.mobilePhone,
            }
        except Exception:
            pass

    return {
        # Expose both "id" (frontend compat) and "discharge_id" (canonical)
        "id":                discharge_id,
        "discharge_id":      discharge_id,

        "status":            obj.status,
        "estimate_number":   obj.estimate_number,
        "bill_no":           obj.bill_no,

        "uhid":              obj.uhid,
        "ip_number":         obj.ip_number,

        "bill_date":         _safe_isoformat(obj.bill_date),
        "items":             _parse_items(obj.items),

        "total_amount":      _to_float(obj.total_amount),
        "advance_amount":    _to_float(obj.advance_amount),
        "sales_return":      _to_float(obj.sales_return),
        "medicines_amount":  _to_float(obj.medicines_amount),
        "taxable_amount":    _to_float(obj.taxable_amount),
        "non_tax_amount":    _to_float(obj.non_tax_amount),
        "gst_amount":        _to_float(obj.gst_amount),
        "room_tax":          _to_float(obj.room_tax),
        "discount_percent":  _to_float(obj.discount_percent),
        "discount_amount":   _to_float(obj.discount_amount),
        "disc_reason":       obj.disc_reason or "",
        "item_disc":         _to_float(obj.item_disc),
        "total_disc":        _to_float(obj.total_disc),
        "net_amount":        _to_float(obj.net_amount),
        "remarks":           obj.remarks or "",

        "converted_from_id": obj.converted_from_id,
        "is_active":         obj.is_active,

        "hospital_code":     getattr(obj, "hospital_code", "") or "",
        "created_date":      _safe_isoformat(getattr(obj, "created_date", None)),
        "lastmodified_date": _safe_isoformat(getattr(obj, "lastmodified_date", None)),

        "patient_details":   patient_details,
    }


def _apply_fields(obj, data, existing=None):
    """
    Write financial + identity fields from request data onto obj.
    Falls back to existing values for any missing key.
    _to_float() handles all types: Decimal128, Decimal, smart-quoted str, None.
    """
    def flt(key):
        val = data.get(key)
        if val is None and existing:
            val = getattr(existing, key, None)
        return _to_float(val)

    def s(key, default=""):
        val = data.get(key)
        if val is None and existing:
            val = getattr(existing, key, default)
        return str(val) if val is not None else default

    raw_items = data.get("items")
    if raw_items is None and existing:
        raw_items = existing.items
    items = _parse_items(raw_items)

    obj.uhid             = s("uhid")
    obj.ip_number        = s("ip_number")
    obj.items            = items
    obj.total_amount     = flt("total_amount")
    obj.advance_amount   = flt("advance_amount")
    obj.sales_return     = flt("sales_return")
    obj.medicines_amount = flt("medicines_amount")
    obj.taxable_amount   = flt("taxable_amount")
    obj.non_tax_amount   = flt("non_tax_amount")
    obj.gst_amount       = flt("gst_amount")
    obj.room_tax         = flt("room_tax")
    obj.discount_percent = flt("discount_percent")
    obj.discount_amount  = flt("discount_amount")
    obj.disc_reason      = s("disc_reason")
    obj.item_disc        = flt("item_disc")
    obj.total_disc       = flt("total_disc")
    obj.net_amount       = flt("net_amount")
    obj.remarks          = s("remarks")
    obj.is_active        = True


# ─────────────────────────────────────────────────────────────────────────────
# Search Discharge Patient
# GET /search-discharge-patient/?uhid=… OR ?ipNumber=…
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def search_discharge_patient(request):
    uhid      = request.GET.get("uhid",     "").strip()
    ip_number = request.GET.get("ipNumber", "").strip()

    if not uhid and not ip_number:
        return Response(
            {"error": "Provide uhid or ipNumber"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    patient   = None
    admission = None

    try:
        if uhid:
            try:
                patient = Patient.objects.get(uhid=uhid)
            except Patient.DoesNotExist:
                return Response({"error": "Patient not found"}, status=status.HTTP_404_NOT_FOUND)

            admissions = [a for a in Admission.objects.all() if a.uhid == uhid]
            admissions.sort(
                key=lambda a: a.admissionDateTime or datetime.datetime.min,
                reverse=True,
            )
            admission = admissions[0] if admissions else None

        else:
            all_admissions = list(Admission.objects.all())
            matched = [a for a in all_admissions if a.ipNumber == ip_number]
            if not matched:
                return Response({"error": "Admission not found"}, status=status.HTTP_404_NOT_FOUND)
            admission = matched[0]

            all_patients = list(Patient.objects.all())
            matched_p = [p for p in all_patients if p.uhid == admission.uhid]
            if not matched_p:
                return Response({"error": "Patient not found"}, status=status.HTTP_404_NOT_FOUND)
            patient = matched_p[0]

    except Exception as e:
        return Response(
            {"error": f"Lookup failed: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    adm_dt  = getattr(admission, "admissionDateTime", None) if admission else None
    adm_str = adm_dt.isoformat() if adm_dt else ""

    room_details = (admission.room_details or []) if admission else []
    current_room = ""
    if room_details and isinstance(room_details, list):
        last_room = room_details[-1]
        if isinstance(last_room, dict):
            current_room = last_room.get("roomNumber", "") or last_room.get("room_number", "")

    total_days = 0
    if adm_dt:
        try:
            today    = datetime.date.today()
            adm_date = adm_dt.date() if isinstance(adm_dt, datetime.datetime) else adm_dt
            total_days = (today - adm_date).days
        except Exception:
            total_days = 0

    patient_info = {
        "uhid":           patient.uhid,
        "patient_name":   f"{patient.firstName} {patient.lastName}".strip(),
        "age":            patient.age,
        "gender":         patient.gender,
        "mobile":         patient.mobilePhone,
        "ip_number":      admission.ipNumber if admission else None,
        "ipNumber":       admission.ipNumber if admission else None,
        "admission_date": adm_str,
        "patient_type":   getattr(patient, "customer_type", ""),
        "company":        getattr(patient, "company_code", "") or "",
        "room_no":        current_room,
        "total_days":     total_days,
        "doctor":         getattr(admission, "admittingDoctor", "") if admission else "",
    }

    effective_ip = ip_number or (admission.ipNumber if admission else None)
    query = {"paymentMethod": "Credit", "paymentStatus": "Pending", "is_active": True}
    if effective_ip:
        query["ipNumber"] = effective_ip
    else:
        query["uhid"] = patient.uhid

    invest_items = []
    try:
        col = _invest_col()
        for bill in col.find(query):
            bill_no   = bill.get("investBillNo", "")
            doctor    = bill.get("doctor", "")
            raw_items = bill.get("item", [])
            if isinstance(raw_items, str):
                try:
                    raw_items = _json.loads(raw_items)
                except Exception:
                    raw_items = []
            for it in raw_items:
                invest_items.append({
                    "invest_bill_no": bill_no,
                    "bill_object_id": str(bill.get("_id")),
                    "itemName":       it.get("itemName", ""),
                    "price":          _to_float(it.get("price", 0)),
                    "quantity":       int(it.get("quantity", 1) or 1),
                    "billTypeNo":     it.get("billTypeNo", ""),
                    "test_id":        it.get("test_id"),
                    "doctor":         doctor,
                    "payment_status": bill.get("paymentStatus", ""),
                    "package_name":   it.get("packageName", "") or bill.get("packageName", ""),
                })
    except Exception:
        invest_items = []

    return Response({"patient": patient_info, "invest_items": invest_items})


# ─────────────────────────────────────────────────────────────────────────────
# LIST + CREATE
# GET  /discharge-billing/
# POST /discharge-billing/   → Flow 1 (Billed) or Flow 2 (Estimate)
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def discharge_billing_list_create(request):

    # ── GET ───────────────────────────────────────────────────────────────────
    if request.method == "GET":
        status_f = request.GET.get("status")
        uhid_f   = request.GET.get("uhid")
        ip_f     = request.GET.get("ip_number")
        from_f   = request.GET.get("from_date")
        to_f     = request.GET.get("to_date")

        all_records = list(DischargeBilling.objects.all())

        filtered = []
        for obj in all_records:
            if not obj.is_active:
                continue
            if status_f and obj.status != status_f:
                continue
            if uhid_f and obj.uhid != uhid_f:
                continue
            if ip_f and obj.ip_number != ip_f:
                continue
            if from_f:
                try:
                    from_date = datetime.date.fromisoformat(from_f)
                    bd = obj.bill_date
                    if bd and (bd if isinstance(bd, datetime.date) else bd.date()) < from_date:
                        continue
                except ValueError:
                    pass
            if to_f:
                try:
                    to_date = datetime.date.fromisoformat(to_f)
                    bd = obj.bill_date
                    if bd and (bd if isinstance(bd, datetime.date) else bd.date()) > to_date:
                        continue
                except ValueError:
                    pass
            filtered.append(obj)

        def _sort_key(o):
            bd = o.bill_date
            if bd is None:
                bd = datetime.date.min
            if isinstance(bd, datetime.datetime):
                bd = bd.date()
            # discharge_id is always an int — safe to sort directly
            return (bd, o.discharge_id or 0)

        filtered.sort(key=_sort_key, reverse=True)
        return Response([_obj_to_dict(o) for o in filtered])

    # ── POST ──────────────────────────────────────────────────────────────────
    # Flow 1: status="Billed"    → bill_no generated, estimate_number=None
    # Flow 2: status="Estimate"  → estimate_number generated, bill_no=None
    if request.method == "POST":
        data           = request.data
        billing_status = data.get("status", "Estimate")

        if billing_status not in ("Estimate", "Billed"):
            return Response(
                {"error": "status must be 'Estimate' or 'Billed'"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        obj = DischargeBilling()
        _apply_fields(obj, data)
        obj.status    = billing_status
        obj.bill_date = timezone.now().date()

        if billing_status == "Estimate":
            obj.estimate_number = generate_estimate_number()
            obj.bill_no         = None
        else:
            obj.bill_no         = generate_bill_number()
            obj.estimate_number = None

        # discharge_id is set by model.save() via auto-increment — do not set it here
        try:
            obj.save()
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(_obj_to_dict(obj), status=status.HTTP_201_CREATED)


# ─────────────────────────────────────────────────────────────────────────────
# RETRIEVE / UPDATE / DELETE
# GET    /discharge-billing/<discharge_id>/
# PATCH  /discharge-billing/<discharge_id>/  → Flow 3: edit estimate in-place
# PUT    /discharge-billing/<discharge_id>/  → same as PATCH
# DELETE /discharge-billing/<discharge_id>/  → soft delete
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET", "PUT", "PATCH", "DELETE"])
@permission_classes([HasRoleAndDataPermission])
def discharge_billing_detail(request, pk):
    """
    URL parameter is named <pk> in urls.py for consistency,
    but it maps directly to discharge_id (IntegerField PK).
    """
    billing = _resolve_pk(pk)
    if billing is None:
        return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

    # ── GET ───────────────────────────────────────────────────────────────────
    if request.method == "GET":
        return Response(_obj_to_dict(billing))

    # ── PUT / PATCH  (Flow 3: edit estimate in-place) ─────────────────────────
    if request.method in ["PUT", "PATCH"]:
        if billing.status == "Billed":
            return Response(
                {"error": "Final bill cannot be edited"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        _apply_fields(billing, request.data, existing=billing)
        # Normalise any Decimal128 / smart-quoted values that came back from
        # MongoDB on the existing record before writing back.
        _normalise_decimals(billing)
        billing.status = "Estimate"   # status locked via PATCH — use convert endpoint to bill

        try:
            billing.save()
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(_obj_to_dict(billing))

    # ── DELETE (soft) ─────────────────────────────────────────────────────────
    if request.method == "DELETE":
        billing.is_active = False
        billing.save(update_fields=["is_active"])
        return Response({"message": "Record deleted"})


# ─────────────────────────────────────────────────────────────────────────────
# CONVERT ESTIMATE → BILL  (Flow 4, in-place)
# POST /discharge-billing/<discharge_id>/convert-to-bill/
#
# Frontend workflow:
#   1. PATCH /<discharge_id>/                   — save latest items + financials
#   2. POST  /<discharge_id>/convert-to-bill/   — flip status, generate bill_no
#
# estimate_number is preserved on the same document for audit.
# No new document is created.
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def convert_estimate_to_bill(request, pk):
    estimate = _resolve_pk(pk)
    if estimate is None:
        return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

    if estimate.status != "Estimate":
        return Response(
            {"error": "Only an Estimate can be converted to a Bill"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Re-normalise all DecimalFields before saving.
    # Djongo may return Decimal128 / smart-quoted strings when reading back
    # the document; passing them straight to DecimalField.validate() causes:
    #   '"190.00" value must be a decimal number'
    _normalise_decimals(estimate)

    estimate.status    = "Billed"
    estimate.bill_no   = generate_bill_number()
    estimate.bill_date = timezone.now().date()   # USE_TZ-safe

    try:
        estimate.save()
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    return Response(_obj_to_dict(estimate), status=status.HTTP_200_OK)