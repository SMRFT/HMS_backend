import os
import datetime as _dt_module
from datetime import date as _date, datetime as _datetime
import json as _json
from decimal import Decimal, InvalidOperation

import django.db.models.fields.json as _json_fields

# Safe JSONField converter for Djongo / PyMongo — prevents "TypeError: must be str, bytes or bytearray, not list"
def _safe_from_db_value(self, value, expression, connection):
    if value is None:
        return value
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return _json.loads(value, cls=self.decoder)
        except Exception:
            return value
    return value

_json_fields.JSONField.from_db_value = _safe_from_db_value

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
    today = _date.today()
    y = today.year
    if today.month >= 4:
        return f"{str(y)[2:]}{str(y + 1)[2:]}"
    return f"{str(y - 1)[2:]}{str(y)[2:]}"


def generate_estimate_number():
    """EST/YYMM/000001 — resets each calendar month."""
    today  = _date.today()
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
    Return DischargeBilling or None, looked up by discharge_id.

    discharge_id is an IntegerField PK — always cast to int.
    Falls back to a full-scan string match for safety (ObjectId edge cases).
    """
    # Attempt 1: integer PK (normal path)
    try:
        obj = DischargeBilling.objects.get(discharge_id=int(discharge_id))
        return obj
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
                return obj
    except Exception:
        pass
    return None


def _sanitize_item(it):
    if not isinstance(it, dict):
        return it

    raw_doctors = it.get("doctors")
    clean_doctors = []
    if isinstance(raw_doctors, list):
        for d in raw_doctors:
            if isinstance(d, dict):
                clean_doc = {}
                for k in ["surgeon_id", "anaesthetist_id", "doctor_id", "doctor_fee"]:
                    if k in d and d[k] is not None:
                        clean_doc[k] = str(d[k])
                if clean_doc:
                    clean_doctors.append(clean_doc)

    return {
        "itemName":         str(it.get("itemName") or ""),
        "quantity":         it.get("quantity", 1),
        "rate":             it.get("rate") if it.get("rate") is not None else it.get("price", 0),
        "discount":         _to_float(it.get("discount", 0)),
        "amount":           _to_float(it.get("amount", 0)),
        "doctor":           str(it.get("doctor") or ""),
        "doctor_fee":       str(it.get("doctor_fee") or ""),
        "bill_type":        it.get("bill_type") if it.get("bill_type") is not None else 2,
        "billTypeNo":       str(it.get("billTypeNo") or ""),
        "item_description": str(it.get("item_description") or it.get("billTypeNo") or ""),
        "package_name":     str(it.get("package_name") or ""),
        "doctors":          clean_doctors,
    }


def _parse_items(raw):
    parsed = []
    if isinstance(raw, list):
        parsed = raw
    elif isinstance(raw, str):
        try:
            res = _json.loads(raw)
            if isinstance(res, list):
                parsed = res
        except Exception:
            parsed = []

    return [_sanitize_item(i) for i in parsed if isinstance(i, dict)]


def _sync_mongo_items_array(obj_or_id, raw_items=None):
    """
    Ensure the 'items' field and audit fields in hospital_dischargebilling collection in MongoDB
    are saved correctly as native BSON elements.
    """
    if not obj_or_id:
        return
    try:
        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        db = client[os.getenv("HMS_DB_NAME", "HMS")]

        if isinstance(obj_or_id, DischargeBilling):
            obj = obj_or_id
            discharge_id = obj.discharge_id
            items = _parse_items(obj.items)
            update_dict = {"items": items}
            if getattr(obj, "created_by", None): update_dict["created_by"] = str(obj.created_by)
            if getattr(obj, "created_date", None): update_dict["created_date"] = obj.created_date
            if getattr(obj, "lastmodified_by", None): update_dict["lastmodified_by"] = str(obj.lastmodified_by)
            if getattr(obj, "lastmodified_date", None): update_dict["lastmodified_date"] = obj.lastmodified_date
            if getattr(obj, "branch_code", None): update_dict["branch_code"] = str(obj.branch_code)
            if getattr(obj, "outlet_code", None): update_dict["outlet_code"] = str(obj.outlet_code)
            if getattr(obj, "hospital_code", None): update_dict["hospital_code"] = str(obj.hospital_code)
            if getattr(obj, "is_cancelled", None) is not None: update_dict["is_cancelled"] = bool(obj.is_cancelled)
            if getattr(obj, "cancelled_by", None): update_dict["cancelled_by"] = str(obj.cancelled_by)
            if getattr(obj, "cancelled_date", None): update_dict["cancelled_date"] = obj.cancelled_date
            if getattr(obj, "cancelled_reason", None): update_dict["cancelled_reason"] = str(obj.cancelled_reason)
            if getattr(obj, "edit_history", None) is not None: update_dict["edit_history"] = obj.edit_history

            db["hospital_dischargebilling"].update_one(
                {"discharge_id": int(discharge_id)},
                {"$set": update_dict}
            )
        else:
            discharge_id = obj_or_id
            items = _parse_items(raw_items)
            if isinstance(items, list):
                db["hospital_dischargebilling"].update_one(
                    {"discharge_id": int(discharge_id)},
                    {"$set": {"items": items}}
                )
    except Exception as e:
        print(f"Error syncing items array to MongoDB: {e}")


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


_employee_name_cache = {}

def _resolve_employee_name(emp_id):
    if not emp_id:
        return ""
    emp_str = str(emp_id).strip()
    if not emp_str:
        return ""
    if emp_str in _employee_name_cache:
        return _employee_name_cache[emp_str]
    try:
        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        db = client["Global"]
        profile = db["backend_diagnostics_profile"].find_one(
            {"employeeId": emp_str},
            {"employeeName": 1, "firstName": 1, "lastName": 1}
        )
        if profile:
            name = profile.get("employeeName") or f"{profile.get('firstName', '')} {profile.get('lastName', '')}".strip()
            if name:
                _employee_name_cache[emp_str] = name
                return name
    except Exception:
        pass
    return emp_str


def _obj_to_dict(obj):
    """Serialise a DischargeBilling instance to a JSON-safe dict."""
    # discharge_id is the PK — always an int (set by model.save())
    discharge_id = obj.discharge_id

    patient_details = {}
    if obj.uhid:
        try:
            p = Patient.objects.get(uhid=obj.uhid)
            addr_parts = [p.permanent_address, p.area, p.city, p.state, p.zipcode]
            full_address = ", ".join([str(x).strip() for x in addr_parts if x and str(x).strip()])

            adm = None
            if obj.ip_number:
                try:
                    adm = Admission.objects.filter(ipNumber=obj.ip_number).first()
                except Exception:
                    pass

            adm_dt = getattr(adm, "admissionDateTime", None) if adm else None
            if isinstance(adm_dt, _datetime):
                adm_str = adm_dt.strftime("%d-%m-%Y %I:%M %p")
            elif isinstance(adm_dt, _date):
                adm_str = adm_dt.strftime("%d-%m-%Y")
            elif isinstance(adm_dt, str) and adm_dt:
                adm_str = adm_dt
            else:
                adm_str = ""

            current_room = ""
            if adm and adm.room_details and isinstance(adm.room_details, list):
                last_room = adm.room_details[-1]
                if isinstance(last_room, dict):
                    current_room = last_room.get("roomNumber", "") or last_room.get("room_number", "")

            doc_id = getattr(adm, "admittingDoctor", "") if adm else ""
            doc_name = _resolve_employee_name(doc_id) if doc_id else ""

            patient_details = {
                "patient_name":   f"{p.firstName} {p.lastName}".strip(),
                "age":            p.age,
                "gender":         p.gender,
                "mobile":         p.mobilePhone,
                "address":        full_address,
                "guardian":       getattr(p, "spouse_name", "") or getattr(p, "emergency_contact", "") or "",
                "doctor":         doc_name or doc_id,
                "doctor_id":      doc_id,
                "admission_date": adm_str,
                "room_no":        current_room,
            }
        except Exception:
            pass

    created_by_val = getattr(obj, "created_by", None)
    created_by_name = _resolve_employee_name(created_by_val) if created_by_val else ""

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
        "discount_percent":  _to_float(obj.discount_percent),
        "discount_amount":   _to_float(obj.discount_amount),
        "disc_reason":       obj.disc_reason or "",
        "net_amount":        _to_float(obj.net_amount),
        "remarks":           obj.remarks or "",

        "created_by":        created_by_val,
        "created_by_name":   created_by_name,
        "created_date":      _safe_isoformat(getattr(obj, "created_date", None)),
        "lastmodified_by":   getattr(obj, "lastmodified_by", None),
        "lastmodified_date": _safe_isoformat(getattr(obj, "lastmodified_date", None)),
        "branch_code":       getattr(obj, "branch_code", None),
        "outlet_code":       getattr(obj, "outlet_code", None),
        "hospital_code":     getattr(obj, "hospital_code", None),
        "shiftno":           getattr(obj, "shiftno", "") or "",

        "patient_details":   patient_details,
    }


def _apply_fields(obj, data, existing=None, request=None):
    """
    Write financial + identity + audit fields from request data onto obj.
    Falls back to existing values for any missing key.
    _to_float() handles all types: Decimal128, Decimal, smart-quoted str, None.
    """
    old_snapshot = {}
    if existing:
        old_snapshot = {
            "total_amount":    _to_float(getattr(existing, "total_amount", 0)),
            "advance_amount":  _to_float(getattr(existing, "advance_amount", 0)),
            "discount_amount": _to_float(getattr(existing, "discount_amount", 0)),
            "net_amount":      _to_float(getattr(existing, "net_amount", 0)),
            "remarks":         str(getattr(existing, "remarks", "") or ""),
            "items":           _parse_items(getattr(existing, "items", []) or []),
        }

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
    obj.discount_percent = flt("discount_percent")
    obj.discount_amount  = flt("discount_amount")
    obj.disc_reason      = s("disc_reason")
    obj.net_amount       = flt("net_amount")
    obj.remarks          = s("remarks")
    obj.shiftno          = s("shiftno")

    # ── Audit & Organization Fields ──────────────────────────────────────────
    user_id = None
    if request:
        user_id = getattr(request, "user_id", None)
        if not user_id and isinstance(getattr(request, "data", None), dict):
            user_id = request.data.get("auth-user-id") or request.data.get("user_id") or request.data.get("created_by")
    if not user_id:
        user_id = data.get("created_by") or data.get("lastmodified_by") or data.get("user_id") or data.get("auth-user-id")

    user_id = str(user_id).strip() if user_id else None

    branch_code = data.get("branch_code") or data.get("auth-branch-code")
    if not branch_code and request:
        branch_code = getattr(request, "data", {}).get("auth-branch-code") if isinstance(getattr(request, "data", None), dict) else None
        if not branch_code and hasattr(request, "headers"):
            branch_code = request.headers.get("X-Branch-Code") or request.headers.get("branch-code")

    outlet_code = data.get("outlet_code") or data.get("auth-outlet-code")
    if not outlet_code and request:
        outlet_code = getattr(request, "data", {}).get("auth-outlet-code") if isinstance(getattr(request, "data", None), dict) else None
        if not outlet_code and hasattr(request, "headers"):
            outlet_code = request.headers.get("X-Outlet-Code") or request.headers.get("outlet-code")

    hospital_code = data.get("hospital_code") or data.get("auth-hospital-code")
    if not hospital_code and request:
        hospital_code = getattr(request, "data", {}).get("auth-hospital-code") if isinstance(getattr(request, "data", None), dict) else None
        if not hospital_code and hasattr(request, "headers"):
            hospital_code = request.headers.get("X-Hospital-Code") or request.headers.get("hospital-code")

    if existing:
        if not branch_code: branch_code = getattr(existing, "branch_code", None)
        if not outlet_code: outlet_code = getattr(existing, "outlet_code", None)
        if not hospital_code: hospital_code = getattr(existing, "hospital_code", None)

    if not getattr(obj, "created_by", None):
        if user_id:
            obj.created_by = user_id
        elif existing and getattr(existing, "created_by", None):
            obj.created_by = existing.created_by

    if not getattr(obj, "created_date", None):
        obj.created_date = timezone.now()

    if user_id:
        obj.lastmodified_by = user_id
    elif existing and getattr(existing, "lastmodified_by", None):
        obj.lastmodified_by = existing.lastmodified_by
    obj.lastmodified_date = timezone.now()

    if branch_code:
        obj.branch_code = str(branch_code).strip()
    if outlet_code:
        obj.outlet_code = str(outlet_code).strip()
    if hospital_code:
        obj.hospital_code = str(hospital_code).strip()

    # ── Edit History Tracking (Only for Billed records) ──────────────────────
    if existing and old_snapshot and getattr(existing, "status", None) == "Billed":
        changes = []
        user_id_str = user_id or getattr(existing, "lastmodified_by", None) or "System"
        edit_reason_str = str(data.get("edit_reason") or data.get("reason") or "").strip()

        track_fields = [
            ("total_amount", "Total Amount"),
            ("advance_amount", "Advance Amount"),
            ("discount_amount", "Discount Amount"),
            ("net_amount", "Net Amount"),
            ("remarks", "Remarks"),
        ]
        for f_key, f_label in track_fields:
            old_val = old_snapshot.get(f_key)
            new_val = getattr(obj, f_key, None)
            if old_val is not None and new_val is not None and str(old_val) != str(new_val):
                changes.append({
                    "edited_by": str(user_id_str),
                    "edited_date": timezone.now().isoformat(),
                    "edit_reason": edit_reason_str,
                    "field_name": f_label,
                    "before_value": str(old_val),
                    "after_value": str(new_val),
                })

        old_items = old_snapshot.get("items", []) or []
        new_items = getattr(obj, "items", []) or []
        if _json.dumps(old_items, sort_keys=True) != _json.dumps(new_items, sort_keys=True):
            changes.append({
                "edited_by": str(user_id_str),
                "edited_date": timezone.now().isoformat(),
                "edit_reason": edit_reason_str,
                "field_name": "Items List",
                "before_value": f"{len(old_items)} item(s)",
                "after_value": f"{len(new_items)} item(s)",
            })

        if not changes and edit_reason_str:
            changes.append({
                "edited_by": str(user_id_str),
                "edited_date": timezone.now().isoformat(),
                "edit_reason": edit_reason_str,
                "field_name": "Bill Update",
                "before_value": "Updated",
                "after_value": "Updated",
            })

        if changes:
            curr_history = getattr(existing, "edit_history", []) or []
            if not isinstance(curr_history, list):
                curr_history = []
def _mark_admission_discharged(ip_number):
    if not ip_number:
        return
    try:
        adm = Admission.objects.filter(ipNumber=ip_number).first()
        if adm:
            adm.ward_status = "Discharged"
            adm.status = "Discharged"
            adm.is_discharged = True
            adm.is_admitted = False
            adm.save()
    except Exception as e:
        print(f"Failed to update admission status for {ip_number}: {e}")


def _revert_admission_discharge(ip_number):
    if not ip_number:
        return
    try:
        adm = Admission.objects.filter(ipNumber=ip_number).first()
        if adm:
            adm.ward_status = "Sent for billing"
            adm.status = "Admitted"
            adm.is_discharged = False
            adm.is_admitted = True
            adm.save()
    except Exception as e:
        print(f"Failed to revert admission status for {ip_number}: {e}")


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

            all_admissions = [a for a in Admission.objects.all() if a.uhid == uhid]
            active_admissions = [
                a for a in all_admissions
                if getattr(a, "is_admitted", False) is True and not getattr(a, "is_cancelled", False)
            ]
            if not active_admissions:
                return Response({"error": "Not Admitted"}, status=status.HTTP_404_NOT_FOUND)

            active_admissions.sort(
                key=lambda a: a.admissionDateTime or _datetime.min,
                reverse=True,
            )
            admission = active_admissions[0]

        else:
            all_admissions = list(Admission.objects.all())
            matched = [a for a in all_admissions if a.ipNumber == ip_number]
            if not matched:
                return Response({"error": "Not Admitted"}, status=status.HTTP_404_NOT_FOUND)
            
            admission = matched[0]
            if not getattr(admission, "is_admitted", False) or getattr(admission, "is_cancelled", False):
                return Response({"error": "Not Admitted"}, status=status.HTTP_404_NOT_FOUND)

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

    # Verify patient discharge state: if already discharged, disallow billing again
    ward_status = str(getattr(admission, "ward_status", "") or "").strip()
    adm_status = str(getattr(admission, "status", "") or "").strip()
    is_discharged = getattr(admission, "is_discharged", False)

    if ward_status.lower() in ["discharged", "already discharged"] or adm_status.lower() == "discharged" or is_discharged is True:
        return Response(
            {"error": "Already Discharged", "message": "Patient is already discharged"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Check if an active Billed DischargeBilling record exists for this IP number
    existing_billed = [
        b for b in DischargeBilling.objects.all()
        if b.ip_number == admission.ipNumber and b.status == "Billed" and not getattr(b, "is_cancelled", False)
    ]
    if existing_billed:
        return Response(
            {"error": "Already Discharged", "message": "Discharge bill already generated for this admission"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Verify ward_status: must be "Sent for billing"
    if ward_status != "Sent for billing":
        return Response(
            {"error": "Not Ready For Billing", "ward_status": ward_status},
            status=status.HTTP_400_BAD_REQUEST,
        )

    adm_dt  = getattr(admission, "admissionDateTime", None) if admission else None
    if isinstance(adm_dt, _datetime):
        adm_str = adm_dt.strftime("%d-%m-%Y %I:%M %p")
    elif isinstance(adm_dt, _date):
        adm_str = adm_dt.strftime("%d-%m-%Y")
    elif isinstance(adm_dt, str) and adm_dt:
        try:
            parsed_dt = _datetime.fromisoformat(adm_dt.replace("Z", "+00:00"))
            adm_str = parsed_dt.strftime("%d-%m-%Y %I:%M %p")
        except Exception:
            adm_str = adm_dt
    else:
        adm_str = ""

    room_details = (admission.room_details or []) if admission else []
    current_room = ""
    if room_details and isinstance(room_details, list):
        last_room = room_details[-1]
        if isinstance(last_room, dict):
            current_room = last_room.get("roomNumber", "") or last_room.get("room_number", "")

    total_days = 0
    if adm_dt:
        try:
            today    = _date.today()
            adm_date = adm_dt.date() if isinstance(adm_dt, _datetime) else adm_dt
            total_days = (today - adm_date).days
        except Exception:
            total_days = 0

    addr_parts = [getattr(patient, "permanent_address", ""), getattr(patient, "area", ""), getattr(patient, "city", ""), getattr(patient, "state", ""), getattr(patient, "zipcode", "")]
    full_address = ", ".join([str(x).strip() for x in addr_parts if x and str(x).strip()])

    doc_id = getattr(admission, "admittingDoctor", "") if admission else ""
    doc_name = _resolve_employee_name(doc_id) if doc_id else ""

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
        "doctor":         doc_name or doc_id,
        "doctor_id":      doc_id,
        "address":        full_address,
        "guardian":       getattr(patient, "spouse_name", "") or getattr(patient, "emergency_contact", "") or "",
        "ward_status":    ward_status,
    }

    effective_ip   = ip_number or (admission.ipNumber if admission else None)
    effective_uhid = patient.uhid if patient else (uhid or (admission.uhid if admission else None))

    invest_items = []

    try:
        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        db = client[os.getenv("HMS_DB_NAME", "HMS")]

        def get_query(ip_fields, extra_filters=None):
            conditions = []
            if effective_ip:
                for f in ip_fields:
                    conditions.append({f: effective_ip})
            elif effective_uhid:
                conditions.append({"uhid": effective_uhid})
            
            if not conditions:
                return None

            match_clause = {"$or": conditions} if len(conditions) > 1 else conditions[0]
            if extra_filters:
                return {"$and": [match_clause, extra_filters]}
            return match_clause

        # ── 1. hospital_investbilling ─────────────────────────────────────────
        # get if ipNumber exists and paymentMethod: "Credit", paymentStatus: "Pending"
        inv_q = get_query(
            ["ipNumber", "inpatient_number", "ip_number"],
            {"paymentMethod": "Credit", "paymentStatus": "Pending", "is_active": {"$ne": False}}
        )
        if inv_q:
            for bill in db["hospital_investbilling"].find(inv_q):
                bill_no   = bill.get("investBillNo", "")
                doctor    = bill.get("doctor", "")
                raw_items = bill.get("item", [])
                if isinstance(raw_items, str):
                    try:
                        raw_items = _json.loads(raw_items)
                    except Exception:
                        raw_items = []
                for it in (raw_items if isinstance(raw_items, list) else []):
                    price = _to_float(it.get("price", 0) or it.get("rate", 0))
                    qty   = int(it.get("quantity", 1) or 1)
                    disc  = _to_float(it.get("discount", 0))
                    amt   = max(0.0, price * qty - disc)
                    invest_items.append({
                        "invest_bill_no": bill_no,
                        "bill_object_id": str(bill.get("_id")),
                        "itemName":       it.get("itemName", ""),
                        "price":          price,
                        "rate":           str(price),
                        "quantity":       qty,
                        "discount":       disc,
                        "amount":         amt,
                        "billTypeNo":     it.get("billTypeNo", "") or bill.get("billTypeNo", "") or "LAB01",
                        "bill_type":      bill.get("bill_type", 16),
                        "test_id":        it.get("test_id"),
                        "doctor":         doctor,
                        "payment_status": bill.get("paymentStatus", ""),
                        "package_name":   it.get("packageName", "") or bill.get("packageName", ""),
                        "source":         "hospital_investbilling",
                    })

        # ── 2. hospital_patientdietorder ──────────────────────────────────────
        # get if ipNumber exists and status: "Delivered"
        diet_q = get_query(
            ["inpatient_number", "ipNumber", "ip_number"],
            {"status": "Delivered"}
        )
        if diet_q:
            for doc in db["hospital_patientdietorder"].find(diet_q):
                tot_price = _to_float(doc.get("total_price"))
                if tot_price == 0:
                    tot_price = _to_float(doc.get("diet_price")) + _to_float(doc.get("extra_items_price"))
                
                meal_time  = doc.get("meal_time", "")
                item_label = f"Diet Food ({meal_time})" if meal_time else "Diet Food"

                invest_items.append({
                    "invest_bill_no": str(doc.get("_id")),
                    "bill_object_id": str(doc.get("_id")),
                    "itemName":       "Diet Food",
                    "price":          tot_price,
                    "rate":           str(tot_price),
                    "quantity":       1,
                    "discount":       0,
                    "amount":         tot_price,
                    "billTypeNo":     "DIS01",
                    "bill_type":      2,
                    "test_id":        None,
                    "doctor":         doc.get("ordered_by", ""),
                    "payment_status": doc.get("status", ""),
                    "package_name":   item_label,
                    "source":         "hospital_patientdietorder",
                })

        # ── 3. hospital_laundrywardrequest ────────────────────────────────────
        # get if ipNumber exists and status: "Completed"
        laundry_q = get_query(
            ["ipNumber", "inpatient_number", "ip_number"],
            {"status": "Completed"}
        )
        if laundry_q:
            for doc in db["hospital_laundrywardrequest"].find(laundry_q):
                tot_amt = _to_float(doc.get("total_amount"))
                invest_items.append({
                    "invest_bill_no": str(doc.get("id") or doc.get("_id")),
                    "bill_object_id": str(doc.get("_id")),
                    "itemName":       "Laundary",
                    "price":          tot_amt,
                    "rate":           str(tot_amt),
                    "quantity":       1,
                    "discount":       0,
                    "amount":         tot_amt,
                    "billTypeNo":     "DIS01",
                    "bill_type":      2,
                    "test_id":        None,
                    "doctor":         doc.get("requested_by", ""),
                    "payment_status": doc.get("status", ""),
                    "package_name":   "",
                    "source":         "hospital_laundrywardrequest",
                })

        # ── 4. hospital_pharmacybilling ────────────────────────────────────────
        # get if ipNumber exists and payment_mode: "Credit" -> display Medicine Charges as single payment
        pharm_q = get_query(
            ["inpatient_number", "ipNumber", "ip_number"],
            {"payment_mode": "Credit", "is_deleted": {"$ne": True}}
        )
        if pharm_q:
            pharm_docs = list(db["hospital_pharmacybilling"].find(pharm_q))
            if pharm_docs:
                total_pharm_amt = 0.0
                total_pharm_disc = 0.0
                bill_nos = []
                last_doc = pharm_docs[-1]

                for doc in pharm_docs:
                    b_no = str(doc.get("bill_no") or doc.get("Bill_id") or "").strip()
                    if b_no:
                        bill_nos.append(b_no)

                    tot_amt = _to_float(
                        doc.get("totalAmount") or doc.get("total_amount") or doc.get("net_amount") or doc.get("netAmount") or 0
                    )
                    disc_amt = _to_float(
                        doc.get("overall_discount_amount") or doc.get("discount") or 0
                    )

                    if tot_amt == 0:
                        meds = doc.get("medicine_particulars", [])
                        if isinstance(meds, list) and len(meds) > 0:
                            for med in meds:
                                if isinstance(med, dict):
                                    qty = int(med.get("qty") or med.get("quantity") or 1)
                                    rate = _to_float(med.get("rate") or med.get("price") or med.get("mrp") or 0)
                                    d_val = _to_float(med.get("discount") or 0)
                                    amt = _to_float(med.get("amount")) or max(0.0, rate * qty - d_val)
                                    tot_amt += amt
                                    disc_amt += d_val

                    total_pharm_amt += tot_amt
                    total_pharm_disc += disc_amt

                combined_bill_no = ", ".join(bill_nos) if bill_nos else str(last_doc.get("_id"))
                invest_items.append({
                    "invest_bill_no": combined_bill_no,
                    "bill_object_id": str(last_doc.get("_id")),
                    "itemName":       "Medicine Charges",
                    "price":          total_pharm_amt,
                    "rate":           str(total_pharm_amt),
                    "quantity":       1,
                    "discount":       total_pharm_disc,
                    "amount":         total_pharm_amt,
                    "billTypeNo":     "DIS01",
                    "bill_type":      last_doc.get("bill_type", 18),
                    "test_id":        None,
                    "doctor":         last_doc.get("doctor_id", ""),
                    "payment_status": last_doc.get("billing_status", "Pending"),
                    "package_name":   "",
                    "source":         "hospital_pharmacybilling",
                })

        # ── 5. hospital_surgeryschedule ────────────────────────────────────────
        # get if ip_number exists and status: "Confirmed"
        surgery_q = get_query(
            ["ip_number", "ipNumber", "inpatient_number"],
            {"status": "Confirmed", "is_active": {"$ne": False}}
        )
        if surgery_q:
            for doc in db["hospital_surgeryschedule"].find(surgery_q):
                surg_name = doc.get("surgery_name") or "Surgery"
                price     = _to_float(doc.get("rate") or doc.get("amount") or doc.get("total_amount") or doc.get("price") or 55000)
                qty       = int(doc.get("quantity", 1) or 1)
                disc      = _to_float(doc.get("discount", 0))
                amt       = _to_float(doc.get("amount")) or max(0.0, price * qty - disc)
                
                # Build doctors list with surgeon_id, anaesthetist_id, and doctor_id keys
                doctors_list = []
                seen_ids = set()

                s_id = str(doc.get("surgeon_id") or "").strip()
                if s_id and s_id not in seen_ids:
                    doctors_list.append({"surgeon_id": s_id, "doctor_fee": ""})
                    seen_ids.add(s_id)

                a_id = str(doc.get("anaesthetist_id") or "").strip()
                if a_id and a_id not in seen_ids:
                    doctors_list.append({"anaesthetist_id": a_id, "doctor_fee": ""})
                    seen_ids.add(a_id)

                add_a = doc.get("additional_anaesthetists")
                if isinstance(add_a, str) and add_a.strip():
                    try:
                        add_a = _json.loads(add_a)
                    except Exception:
                        add_a = None
                if isinstance(add_a, dict):
                    for v in add_a.values():
                        v_str = str(v or "").strip()
                        if v_str and v_str not in seen_ids:
                            doctors_list.append({"anaesthetist_id": v_str, "doctor_fee": ""})
                            seen_ids.add(v_str)
                elif isinstance(add_a, list):
                    for v in add_a:
                        v_str = str(v or "").strip()
                        if v_str and v_str not in seen_ids:
                            doctors_list.append({"anaesthetist_id": v_str, "doctor_fee": ""})
                            seen_ids.add(v_str)

                add_d = doc.get("additional_doctors")
                if isinstance(add_d, str) and add_d.strip():
                    try:
                        add_d = _json.loads(add_d)
                    except Exception:
                        add_d = None
                if isinstance(add_d, dict):
                    for v in add_d.values():
                        v_str = str(v or "").strip()
                        if v_str and v_str not in seen_ids:
                            doctors_list.append({"doctor_id": v_str, "doctor_fee": ""})
                            seen_ids.add(v_str)
                elif isinstance(add_d, list):
                    for v in add_d:
                        v_str = str(v or "").strip()
                        if v_str and v_str not in seen_ids:
                            doctors_list.append({"doctor_id": v_str, "doctor_fee": ""})
                            seen_ids.add(v_str)
                
                invest_items.append({
                    "invest_bill_no":           doc.get("reference_no", ""),
                    "bill_object_id":           str(doc.get("_id")),
                    "itemName":                 surg_name,
                    "price":                    price,
                    "rate":                     str(price),
                    "quantity":                 qty,
                    "discount":                 disc,
                    "amount":                   amt,
                    "billTypeNo":               "DIS01",
                    "bill_type":                2,
                    "surgeon_id":              doc.get("surgeon_id", ""),
                    "anaesthetist_id":         doc.get("anaesthetist_id", ""),
                    "anesthesia_id":           doc.get("anesthesia_id", ""),
                    "additional_anaesthetists": doc.get("additional_anaesthetists"),
                    "additional_doctors":      doc.get("additional_doctors"),
                    "doctors":                  doctors_list,
                    "test_id":                  None,
                    "doctor":                   doc.get("surgeon_id", ""),
                    "payment_status":           doc.get("status", ""),
                    "package_name":             doc.get("surgery_type", ""),
                    "source":                   "hospital_surgeryschedule",
                })

    except Exception as e:
        import traceback
        print(f"Error fetching discharge billing items: {e}")
        traceback.print_exc()

    return Response({
        "success": True,
        "data": {"patient": patient_info, "invest_items": invest_items}
    })


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
            if status_f and obj.status != status_f:
                continue
            if uhid_f and obj.uhid != uhid_f:
                continue
            if ip_f and obj.ip_number != ip_f:
                continue
            if from_f:
                try:
                    from_date = _date.fromisoformat(from_f)
                    bd = obj.bill_date
                    if bd and (bd if isinstance(bd, _date) else bd.date()) < from_date:
                        continue
                except ValueError:
                    pass
            if to_f:
                try:
                    to_date = _date.fromisoformat(to_f)
                    bd = obj.bill_date
                    if bd and (bd if isinstance(bd, _date) else bd.date()) > to_date:
                        continue
                except ValueError:
                    pass
            filtered.append(obj)

        def _sort_key(o):
            bd = o.bill_date
            if bd is None:
                bd = _date.min
            if isinstance(bd, _datetime):
                bd = bd.date()
            # discharge_id is always an int — safe to sort directly
            return (bd, o.discharge_id or 0)

        filtered.sort(key=_sort_key, reverse=True)
        return Response({
            "success": True,
            "data": [_obj_to_dict(o) for o in filtered]
        })

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

        if billing_status == "Billed":
            ip_num = data.get("ip_number") or data.get("ipNumber")
            if ip_num:
                existing_billed = [
                    b for b in DischargeBilling.objects.all()
                    if b.ip_number == ip_num and b.status == "Billed" and not getattr(b, "is_cancelled", False)
                ]
                if existing_billed:
                    return Response(
                        {"error": "Already Discharged", "message": "Discharge bill already exists for this admission"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

        obj = DischargeBilling()
        _apply_fields(obj, data, request=request)
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
            _sync_mongo_items_array(obj)
            if billing_status == "Billed":
                _mark_admission_discharged(obj.ip_number)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            "success": True,
            "data": _obj_to_dict(obj)
        }, status=status.HTTP_201_CREATED)


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
        return Response({
            "success": True,
            "data": _obj_to_dict(billing)
        })

    # ── PUT / PATCH  (Edit in-place & track edit history) ───────────────────
    if request.method in ["PUT", "PATCH"]:
        curr_status = billing.status
        _apply_fields(billing, request.data, existing=billing, request=request)
        if request.data.get("status"):
            billing.status = request.data.get("status")
        else:
            billing.status = curr_status
        _normalise_decimals(billing)

        try:
            billing.save()
            _sync_mongo_items_array(billing)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            "success": True,
            "data": _obj_to_dict(billing)
        })

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

    existing_billed = [
        b for b in DischargeBilling.objects.all()
        if b.ip_number == estimate.ip_number and b.status == "Billed" and getattr(b, "discharge_id", None) != estimate.discharge_id and not getattr(b, "is_cancelled", False)
    ]
    if existing_billed:
        return Response(
            {"error": "Already Discharged", "message": "Discharge bill already exists for this admission"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    _normalise_decimals(estimate)

    user_id = getattr(request, "user_id", None) or request.data.get("auth-user-id") or request.data.get("user_id") or request.data.get("created_by")
    if user_id:
        estimate.lastmodified_by = str(user_id).strip()
    estimate.lastmodified_date = timezone.now()

    estimate.status    = "Billed"
    estimate.bill_no   = generate_bill_number()
    estimate.bill_date = timezone.now().date()   # USE_TZ-safe
    estimate.shiftno   = request.data.get("shiftno")

    try:
        estimate.save()
        _sync_mongo_items_array(estimate)
        _mark_admission_discharged(estimate.ip_number)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    return Response(_obj_to_dict(estimate), status=status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def cancel_discharge_billing(request, pk):
    billing = _resolve_pk(pk)
    if billing is None:
        return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

    reason = request.data.get("cancelled_reason", "").strip()
    if not reason:
        return Response({"error": "Cancelled reason is required"}, status=status.HTTP_400_BAD_REQUEST)

    user_id = getattr(request, "user_id", None) or request.data.get("auth-user-id") or request.data.get("user_id") or request.data.get("cancelled_by") or "System"

    billing.is_cancelled      = True
    billing.status            = "Cancelled"
    billing.cancelled_by      = str(user_id).strip()
    billing.cancelled_date    = timezone.now()
    billing.cancelled_reason  = reason
    billing.lastmodified_by   = str(user_id).strip()
    billing.lastmodified_date = timezone.now()

    _normalise_decimals(billing)

    try:
        billing.save()
        _sync_mongo_items_array(billing)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    return Response({
        "success": True,
        "message": "Bill cancelled successfully",
        "data": _obj_to_dict(billing)
    }, status=status.HTTP_200_OK)




from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from django.db.models import Q
from pymongo import MongoClient
import os

from ..models import Patient, Billing
from ..serializers import PatientSerializer
from pyauth.auth import HasRoleAndDataPermission


@api_view(['GET'])
# @permission_classes([HasRoleAndDataPermission])
def dialysis_patient_details(request):

    uhid      = request.GET.get('uhid')
    ip_number = request.GET.get('ip_number')
    mobile    = request.GET.get('mobile')

    # =========================================================
    # STEP 1 : FILTER PATIENT
    # =========================================================
    if uhid:
        patients = Patient.objects.filter(
            Q(uhid__iexact=uhid) |
            Q(uhid__iendswith=f'/{uhid}')
        )

    elif ip_number:
        patients = Patient.objects.filter(ip_number=ip_number)

    elif mobile:
        patients = Patient.objects.filter(mobilePhone=mobile)

    else:
        return Response({
            "success": False,
            "message": "Please provide uhid, ip_number, or mobile."
        }, status=status.HTTP_400_BAD_REQUEST)

    # =========================================================
    # STEP 2 : MONGODB CONNECTION
    # =========================================================
    client = MongoClient(os.getenv("GLOBAL_DB_HOST"))

    global_db = client["Global"]
    hms_db    = client["HMS"]

    employee_collection = global_db["backend_diagnostics_profile"]

    insurance_collection = hms_db["hospital_insuranceprovider"]

    # =========================================================
    # STEP 3 : SERIALIZE PATIENT DATA
    # =========================================================
    serializer = PatientSerializer(patients, many=True)

    patient_data = serializer.data

    # =========================================================
    # STEP 4 : ADD BILLING + COMPANY NAME
    # =========================================================
    for patient in patient_data:

        patient_id = int(patient["id"])

        # -----------------------------------------------------
        # COMPANY NAME
        # -----------------------------------------------------
        company_code = patient.get("company_code")

        company_data = insurance_collection.find_one({
            "company_code": company_code
        })

        patient["company_name"] = (
            company_data.get("company_name")
            if company_data else None
        )

        # -----------------------------------------------------
        # BILLING DETAILS
        # -----------------------------------------------------
        billings = Billing.objects.filter(patient_id=patient_id)

        billing_list = []

        for bill in billings:

            doctor_id = bill.doctor_id

            employee = employee_collection.find_one({
                "employeeId": doctor_id
            })

            doctor_name = (
                employee["employeeName"]
                if employee else None
            )

            billing_list.append({
                "bill_number": bill.bill_number,
                "doctor_id": doctor_id,
                "doctor_name": doctor_name,
                "total_fees": str(bill.total_fees),
                "payment_status": bill.payment_status,
                "billed_date": bill.billed_date,
            })

        patient["billing"] = billing_list

    # =========================================================
    # STEP 5 : RESPONSE
    # =========================================================
    return Response({
        "success": True,
        "data": patient_data
    }, status=status.HTTP_200_OK)





from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status

import json

from ..serializers import DialysisDischargeSummarySerializer


@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def create_dialysis_discharge_summary(request):

    try:

        data = request.data

        # ============================================
        # AUTH VALUES
        # ============================================

        hospital_code = data.get("auth-hospital-code")
        branch_code   = data.get("auth-branch-code")
        outlet_code   = data.get("auth-outlet-code")
        employee_id   = data.get("auth-user-id")

        # ============================================
        # REQUIRED FIELD VALIDATION
        # ============================================

        required_fields = [
            "name",
            "age",
            "gender",
            "uhid",
            "consultant",
            "date_of_first_dialysis",
            "date_of_last_dialysis",
        ]

        missing_fields = [
            field for field in required_fields
            if not data.get(field)
        ]

        if missing_fields:

            return Response(
                {
                    "success": False,
                    "status_code": 400,
                    "message": "Required fields are missing",
                    "missing_fields": missing_fields,
                    "data": None
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # ============================================
        # PAYLOAD
        # ============================================

        payload = {
            "name":       data.get("name"),
            "age":        data.get("age"),
            "gender":     data.get("gender"),

            "uhid":       data.get("uhid"),
            "consultant": data.get("consultant"),
            "id_no":      data.get("id_no"),
            "insurance":  data.get("insurance", ""),

            "address":   data.get("address"),
            "diagnosis": data.get("diagnosis"),

            "date_of_first_dialysis": data.get("date_of_first_dialysis"),
            "date_of_last_dialysis":  data.get("date_of_last_dialysis"),

            "blood_investigations":
                json.loads(data.get("blood_investigations"))
                if isinstance(data.get("blood_investigations"), str)
                else data.get("blood_investigations", []),

            "hd_sessions":
                json.loads(data.get("hd_sessions"))
                if isinstance(data.get("hd_sessions"), str)
                else data.get("hd_sessions", []),

            "complications_during_hd":
                json.loads(data.get("complications_during_hd"))
                if isinstance(data.get("complications_during_hd"), str)
                else data.get("complications_during_hd", []),

            "condition_on_discharge": data.get("condition_on_discharge"),

            "advice_on_discharge":
                json.loads(data.get("advice_on_discharge"))
                if isinstance(data.get("advice_on_discharge"), str)
                else data.get("advice_on_discharge", []),

            "next_hd_session_on": data.get("next_hd_session_on"),
        }

        # ============================================
        # SERIALIZER
        # ============================================

        serializer = DialysisDischargeSummarySerializer(data=payload)

        # ============================================
        # SUCCESS RESPONSE
        # ============================================

        if serializer.is_valid():

            serializer.save(
                hospital_code=hospital_code,
                branch_code=branch_code,
                outlet_code=outlet_code,
                created_by=employee_id,
                lastmodified_by=employee_id,
            )

            return Response(
                {
                    "success": True,
                    "status_code": 201,
                    "message": f"Dialysis discharge summary for {payload['name']} created successfully.",
                    "data": serializer.data
                },
                status=status.HTTP_201_CREATED
            )

        # ============================================
        # VALIDATION ERROR RESPONSE
        # ============================================

        # Flatten the first error into a readable sentence
        first_field, first_msgs = next(iter(serializer.errors.items()))
        first_msg = first_msgs[0] if isinstance(first_msgs, list) else str(first_msgs)

        return Response(
            {
                "success": False,
                "status_code": 400,
                "message": f"Validation failed — {first_field}: {first_msg}",
                "errors": serializer.errors,
                "data": None
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    # ============================================
    # JSON ERROR
    # ============================================

    except json.JSONDecodeError as e:

        return Response(
            {
                "success": False,
                "status_code": 400,
                "message": "Invalid JSON format in request data.",
                "error": str(e),
                "data": None
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    # ============================================
    # SERVER ERROR
    # ============================================

    except Exception as e:

        return Response(
            {
                "success": False,
                "status_code": 500,
                "message": "An unexpected error occurred. Please try again or contact support.",
                "error": str(e),
                "data": None
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# ─────────────────────────────────────────────────────────────────────────────


from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from datetime import datetime
from ..models import DialysisDischargeSummary
from ..serializers import DialysisDischargeSummarySerializer


@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def Print_dialysis_dischargesummary(request):

    data        = request.data
    employee_id = data.get("auth-user-id")

    # ─── AUTH CODES ───────────────────────────────────────────
    hospital_code = data.get("auth-hospital-code")
    branch_code   = data.get("auth-branch-code")
    outlet_code   = data.get("auth-outlet-code")

    # ─── QUERY PARAMS ─────────────────────────────────────────
    from_date_str = request.query_params.get("from_date", "").strip()
    to_date_str   = request.query_params.get("to_date",   "").strip()

    # ─── VALIDATION ───────────────────────────────────────────
    if not from_date_str or not to_date_str:
        return Response(
            {"status": "error", "message": "Both 'from_date' and 'to_date' are required (YYYY-MM-DD)."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        from_date = datetime.strptime(from_date_str, "%Y-%m-%d").date()
        to_date   = datetime.strptime(to_date_str,   "%Y-%m-%d").date()
    except ValueError:
        return Response(
            {"status": "error", "message": "Invalid date format. Use YYYY-MM-DD."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if from_date > to_date:
        return Response(
            {"status": "error", "message": "'from_date' cannot be later than 'to_date'."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    print("AUTH:", hospital_code, branch_code, outlet_code)
    print("DATES:", from_date, to_date)
    print("ALL RECORDS:", DialysisDischargeSummary.objects.filter(
        hospital_code=hospital_code, branch_code=branch_code, outlet_code=outlet_code
    ).values("uhid", "date"))

    # ─── QUERYSET ─────────────────────────────────────────────
    try:
        queryset = DialysisDischargeSummary.objects.filter(
            hospital_code = hospital_code,
            branch_code   = branch_code,
            outlet_code   = outlet_code,
            date__gte     = from_date,
            date__lte     = to_date,
        ).order_by("-date")

    except Exception as e:
        return Response(
            {"status": "error", "message": f"Database error: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # ─── EMPTY RESULT ─────────────────────────────────────────
    if not queryset.exists():
        return Response(
            {
                "status":  "success",
                "message": "No records found for the selected date range.",
                "count":   0,
                "data":    [],
            },
            status=status.HTTP_200_OK,
        )

    # ─── SERIALIZE & RETURN ───────────────────────────────────
    serializer = DialysisDischargeSummarySerializer(queryset, many=True)

    return Response(
        {
            "status":  "success",
            "message": "Records fetched successfully.",
            "count":   queryset.count(),
            "data":    serializer.data,
        },
        status=status.HTTP_200_OK,
    )
