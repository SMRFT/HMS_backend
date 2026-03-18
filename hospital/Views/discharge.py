"""
views.py — Discharge Billing
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Djongo translates Django ORM to MongoDB via a SQL layer that crashes on
any complex query (.order_by, __startswith, __gte, multi-field filters).

Rule applied throughout this file:
  ✅  DischargeBilling.objects.all()          — safe (full collection scan)
  ✅  DischargeBilling.objects.get(pk=pk)     — safe (PK lookup only)
  ❌  .filter(status=...).order_by(...)       — crashes Djongo

All filtering, sorting, and searching is done in plain Python after
fetching the full queryset.  Collections are small enough for this to
be fine; add a dedicated MongoDB view layer later if scale demands it.

InvestBilling has no Django model → raw PyMongo only (as required).
"""

import os
import datetime
import json as _json
from decimal import Decimal, InvalidOperation

from pymongo import MongoClient, DESCENDING

from django.utils.timezone import now
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status

from pyauth.auth import HasRoleAndDataPermission
from ..models import Patient, Admission, DischargeBilling


# ─────────────────────────────────────────────────────────────────────────────
# Raw PyMongo — InvestBilling ONLY (no Django model exists for it)
# ─────────────────────────────────────────────────────────────────────────────

def _invest_col():
    client = MongoClient(os.getenv("GLOBAL_DB_HOST", "mongodb://localhost:27017"))
    return client["HMS"]["hospital_investbilling"]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError, InvalidOperation):
        return 0.0


def _to_dec(v, default=Decimal("0.00")):
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError):
        return default


def _parse_items(raw):
    """Always return a Python list regardless of input type."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            parsed = _json.loads(raw)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


# ─────────────────────────────────────────────────────────────────────────────
# Patient details — simplest possible ORM call Djongo can handle
# ─────────────────────────────────────────────────────────────────────────────

def _get_patient_details(uhid):
    if not uhid:
        return {}
    try:
        # .get() with a single PK-equivalent field — Djongo handles this
        p = Patient.objects.get(uhid=uhid)
        return {
            "patient_name": f"{p.firstName} {p.lastName}".strip(),
            "age":          p.age,
            "gender":       p.gender,
            "mobile":       p.mobilePhone,
        }
    except Patient.DoesNotExist:
        return {}
    except Exception:
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# Serialise a DischargeBilling instance → JSON-safe dict
# ─────────────────────────────────────────────────────────────────────────────

def _billing_to_dict(obj):
    return {
        "id":               obj.pk,
        "status":           obj.status,
        "estimate_number":  obj.estimate_number,
        "bill_no":          obj.bill_no,
        "uhid":             obj.uhid,
        "ip_number":        obj.ip_number,
        "bill_date":        obj.bill_date.isoformat() if obj.bill_date else None,
        "items":            _parse_items(obj.items),
        "total_amount":     _to_float(obj.total_amount),
        "advance_amount":   _to_float(obj.advance_amount),
        "sales_return":     _to_float(obj.sales_return),
        "medicines_amount": _to_float(obj.medicines_amount),
        "taxable_amount":   _to_float(obj.taxable_amount),
        "non_tax_amount":   _to_float(obj.non_tax_amount),
        "gst_amount":       _to_float(obj.gst_amount),
        "room_tax":         _to_float(obj.room_tax),
        "discount_percent": _to_float(obj.discount_percent),
        "discount_amount":  _to_float(obj.discount_amount),
        "disc_reason":      obj.disc_reason or "",
        "item_disc":        _to_float(obj.item_disc),
        "total_disc":       _to_float(obj.total_disc),
        "net_amount":       _to_float(obj.net_amount),
        "remarks":          obj.remarks or "",
        "converted_from_id": obj.converted_from_id,
        "is_active":        obj.is_active,
        "hospital_code":    obj.hospital_code or "",
        "created_date":     obj.created_date.isoformat() if obj.created_date else None,
        "lastmodified_date": obj.lastmodified_date.isoformat() if obj.lastmodified_date else None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Number generators — fetch ALL then find max in Python (Djongo-safe)
# ─────────────────────────────────────────────────────────────────────────────

def _financial_year():
    today = datetime.date.today()
    y = today.year
    if today.month >= 4:
        return f"{str(y)[2:]}{str(y + 1)[2:]}"
    return f"{str(y - 1)[2:]}{str(y)[2:]}"


def generate_estimate_number():
    today  = datetime.date.today()
    prefix = f"EST/{str(today.year)[2:]}{str(today.month).zfill(2)}/"

    # Fetch ALL, filter in Python — avoids Djongo __startswith crash
    seq = 1
    try:
        all_nums = (
            DischargeBilling.objects
            .all()
            .values_list("estimate_number", flat=True)
        )
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
    prefix = f"{_financial_year()}/DCH/"

    seq = 1
    try:
        all_nums = (
            DischargeBilling.objects
            .all()
            .values_list("bill_no", flat=True)
        )
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
# Build field kwargs for create / update
# ─────────────────────────────────────────────────────────────────────────────

def _build_kwargs(data, existing=None):
    def flt(key):
        val = data.get(key)
        if val is None and existing:
            val = getattr(existing, key, None)
        return _to_dec(val)

    def s(key, default=""):
        val = data.get(key)
        if val is None and existing:
            val = getattr(existing, key, default)
        return str(val) if val is not None else default

    raw_items = data.get("items")
    if raw_items is None and existing:
        raw_items = existing.items
    items = _parse_items(raw_items)

    return dict(
        uhid             = s("uhid"),
        ip_number        = s("ip_number"),
        items            = items,
        total_amount     = flt("total_amount"),
        advance_amount   = flt("advance_amount"),
        sales_return     = flt("sales_return"),
        medicines_amount = flt("medicines_amount"),
        taxable_amount   = flt("taxable_amount"),
        non_tax_amount   = flt("non_tax_amount"),
        gst_amount       = flt("gst_amount"),
        room_tax         = flt("room_tax"),
        discount_percent = flt("discount_percent"),
        discount_amount  = flt("discount_amount"),
        disc_reason      = s("disc_reason"),
        item_disc        = flt("item_disc"),
        total_disc       = flt("total_disc"),
        net_amount       = flt("net_amount"),
        remarks          = s("remarks"),
        is_active        = True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Search Discharge Patient
# GET /search-discharge-patient/?uhid=…  OR  ?ipNumber=…
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
            # .get() on a single field — Djongo handles this fine
            try:
                patient = Patient.objects.get(uhid=uhid)
            except Patient.DoesNotExist:
                return Response({"error": "Patient not found"}, status=status.HTTP_404_NOT_FOUND)

            # Fetch all admissions for this uhid, sort in Python
            admissions = list(Patient.objects.get(uhid=uhid) and
                              Admission.objects.all())
            # Filter in Python to avoid Djongo filter crash
            admissions = [a for a in Admission.objects.all() if a.uhid == uhid]
            admissions.sort(key=lambda a: a.admissionDateTime or datetime.datetime.min, reverse=True)
            admission = admissions[0] if admissions else None

        else:
            # Find admission by ipNumber in Python
            all_admissions = list(Admission.objects.all())
            matched = [a for a in all_admissions if a.ipNumber == ip_number]
            if not matched:
                return Response({"error": "Admission not found"}, status=status.HTTP_404_NOT_FOUND)
            admission = matched[0]

            # Find patient by uhid
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

    # Build patient info
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
            today = datetime.date.today()
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

    # Fetch pending invest-billing items — raw PyMongo (no model)
    effective_ip = ip_number or (admission.ipNumber if admission else None)
    query = {"paymentMethod": "Credit", "paymentStatus": "Pending", "is_active": True}
    if effective_ip:
        query["ipNumber"] = effective_ip
    else:
        query["uhid"] = patient.uhid

    invest_items = []
    try:
        for bill in _invest_col().find(query):
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
                    "price":          float(it.get("price", 0) or 0),
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
# POST /discharge-billing/
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

        # ✅ Only .all() — Djongo handles full collection scan safely
        all_records = list(DischargeBilling.objects.all())

        # ✅ All filtering done in Python — zero Djongo query complexity
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

        # Sort newest bill_date first, then newest pk first — in Python
        def _sort_key(obj):
            bd = obj.bill_date
            if bd is None:
                bd = datetime.date.min
            if isinstance(bd, datetime.datetime):
                bd = bd.date()
            return (bd, obj.pk or 0)

        filtered.sort(key=_sort_key, reverse=True)

        result = []
        for obj in filtered:
            row = _billing_to_dict(obj)
            row["patient_details"] = _get_patient_details(obj.uhid)
            result.append(row)

        return Response(result)

    # ── POST ──────────────────────────────────────────────────────────────────
    if request.method == "POST":
        data           = request.data
        billing_status = data.get("status", "Estimate")

        kwargs = _build_kwargs(data)
        kwargs["status"]    = billing_status
        kwargs["bill_date"] = datetime.date.today()

        if billing_status == "Estimate":
            kwargs["estimate_number"] = generate_estimate_number()
            kwargs["bill_no"]         = None
        else:
            kwargs["bill_no"]         = generate_bill_number()
            kwargs["estimate_number"] = None
            kwargs["status"]          = "Billed"

        try:
            obj = DischargeBilling(**kwargs)
            obj.save()
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        row = _billing_to_dict(obj)
        row["patient_details"] = _get_patient_details(obj.uhid)
        return Response(row, status=status.HTTP_201_CREATED)


# ─────────────────────────────────────────────────────────────────────────────
# RETRIEVE / UPDATE / DELETE
# GET    /discharge-billing/<pk>/
# PATCH  /discharge-billing/<pk>/
# PUT    /discharge-billing/<pk>/
# DELETE /discharge-billing/<pk>/
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET", "PUT", "PATCH", "DELETE"])
@permission_classes([HasRoleAndDataPermission])
def discharge_billing_detail(request, pk):

    # ✅ .get(pk=pk) — single PK lookup, Djongo handles this reliably
    try:
        billing = DischargeBilling.objects.get(pk=pk)
    except DischargeBilling.DoesNotExist:
        return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    if not billing.is_active:
        return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

    # ── GET ───────────────────────────────────────────────────────────────────
    if request.method == "GET":
        row = _billing_to_dict(billing)
        row["patient_details"] = _get_patient_details(billing.uhid)
        return Response(row)

    # ── PUT / PATCH ───────────────────────────────────────────────────────────
    if request.method in ["PUT", "PATCH"]:
        if billing.status == "Billed":
            return Response(
                {"error": "Final bill cannot be edited"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        kwargs = _build_kwargs(request.data, existing=billing)
        # Lock status — only the convert endpoint sets "Billed"
        kwargs["status"] = "Estimate"

        for field, value in kwargs.items():
            setattr(billing, field, value)

        try:
            billing.save()
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        row = _billing_to_dict(billing)
        row["patient_details"] = _get_patient_details(billing.uhid)
        return Response(row)

    # ── DELETE ────────────────────────────────────────────────────────────────
    if request.method == "DELETE":
        billing.is_active = False
        billing.save(update_fields=["is_active"])
        return Response({"message": "Record deleted"})


# ─────────────────────────────────────────────────────────────────────────────
# CONVERT ESTIMATE → BILL  (in-place, same row)
# POST /discharge-billing/<pk>/convert-to-bill/
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def convert_estimate_to_bill(request, pk):
    """
    Mutates the SAME row in-place:
      status    → "Billed"
      bill_no   → newly generated sequential number
      bill_date → today
    No new row is created.
    """
    try:
        estimate = DischargeBilling.objects.get(pk=pk)
    except DischargeBilling.DoesNotExist:
        return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    if not estimate.is_active:
        return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

    if estimate.status != "Estimate":
        return Response(
            {"error": "Only an Estimate can be converted to a Bill"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    estimate.status    = "Billed"
    estimate.bill_no   = generate_bill_number()
    estimate.bill_date = datetime.date.today()

    try:
        # ✅ save() with no update_fields — let Djongo write the whole doc
        # update_fields causes Djongo to generate a partial UPDATE which it
        # sometimes translates incorrectly; a full save() is safer.
        estimate.save()
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    row = _billing_to_dict(estimate)
    row["patient_details"] = _get_patient_details(estimate.uhid)
    return Response(row, status=status.HTTP_200_OK)