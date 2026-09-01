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
import requests
import re
import logging
from datetime import timedelta

logger = logging.getLogger(__name__)

from pyauth.auth import HasRoleAndDataPermission
from ..models import Patient, Admission, DischargeBilling, PatientNextVisitLog


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


def parse_json_field(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    if isinstance(value, str):
        try:
            parsed = _json.loads(value)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict):
                return [parsed]
            return []
        except Exception:
            return []
    return []


def _parse_dt(val):
    if not val:
        return None
    if isinstance(val, dict) and "$date" in val:
        val = val["$date"]
    if isinstance(val, _datetime):
        return val
    if isinstance(val, _date):
        return _datetime.combine(val, _datetime.min.time())
    if isinstance(val, str):
        try:
            return _datetime.fromisoformat(val.replace("Z", "+00:00"))
        except Exception:
            pass
        try:
            return _datetime.strptime(val[:19], "%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
        try:
            return _datetime.strptime(val[:10], "%Y-%m-%d")
        except Exception:
            pass
    return None


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
    "taxable_amount", "non_tax_amount",
    "gst_amount", "room_tax",
    "discount_percent", "discount_amount", "net_amount",
]


def _normalise_decimals(obj):
    """
    Re-write every DecimalField through _to_float so Djongo never receives
    a Decimal128 / smart-quoted string when validating on save().
    """
    for field in _DECIMAL_FIELDS:
        if hasattr(obj, field):
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
                "mobilePhone":    p.mobilePhone,
                "phone":          p.mobilePhone,
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
        "room_tax":          _to_float(getattr(obj, "room_tax", 0)),
        "discount_percent":  _to_float(obj.discount_percent),
        "discount_amount":   _to_float(obj.discount_amount),
        "disc_reason":       obj.disc_reason or "",
        "net_amount":        _to_float(obj.net_amount),
        "remarks":           obj.remarks or "",
        "next_visit_date":   _safe_isoformat(getattr(obj, "next_visit_date", None)),

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
    obj.room_tax         = flt("room_tax")
    obj.discount_percent = flt("discount_percent")
    obj.discount_amount  = flt("discount_amount")
    obj.disc_reason      = s("disc_reason")
    obj.net_amount       = flt("net_amount")
    obj.remarks          = s("remarks")
    obj.shiftno          = s("shiftno")

    # Handle optional next_visit_date
    nv_date = data.get("next_visit_date")
    if nv_date:
        parsed_nv = _parse_dt(nv_date)
        obj.next_visit_date = parsed_nv.date() if parsed_nv else None
    elif "next_visit_date" in data and not nv_date:
        obj.next_visit_date = None
    elif existing and getattr(existing, "next_visit_date", None):
        obj.next_visit_date = existing.next_visit_date

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
def _finalize_discharge(ip_number, user_id=None, uhid=None):
    """
    Called upon final discharge billing generation (status='Billed') or conversion from Estimate.
    1. Updates Admission:
       - is_discharged = True, is_admitted = False, status = "Discharged", ward_status = "Discharged"
       - In room_details and roomShitingDetails:
         makes is_roomActive = False, is_roomCleaned = True, sets endDateTime / end_time to now.
       - updates lastmodified_by, lastmodified_date.
    2. Updates Pharmacy Billing:
       - For outlet_code: "OLET001", matching ip_number/uhid, payment_mode: "Credit", billing_status: "Billed", is_ward_request: True
       - Updates billing_status to "Completed", lastmodified_by, lastmodified_date.
    3. Updates Invest Billing:
       - For matching ipNumber/uhid, paymentMethod: "Credit", paymentStatus: "Pending"
       - Updates paymentStatus to "Billed", lastmodified_by, lastmodified_date.
    """
    if not ip_number and not uhid:
        return

    now_dt = timezone.now()
    now_iso = now_dt.isoformat()
    user_str = str(user_id).strip() if user_id else "System"

    try:
        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        db = client[os.getenv("HMS_DB_NAME", "HMS")]

        # ── 1. Update Admission & Room Process ──────────────────────────────
        adm = None
        if ip_number:
            adm = Admission.objects.filter(ipNumber=ip_number).first()
        if not adm and uhid:
            adm = Admission.objects.filter(uhid=uhid, is_admitted=True).first()

        if adm:
            adm.is_discharged = True
            adm.is_admitted = False
            adm.lastmodified_by = user_str
            adm.lastmodified_date = now_dt

            def _to_native_list(val):
                if val is None:
                    return []
                if isinstance(val, list):
                    parsed = val
                elif isinstance(val, dict):
                    parsed = [val]
                elif isinstance(val, str):
                    s_val = val.strip()
                    if not s_val or s_val in ("null", "None", "[]", "{}"):
                        return []
                    try:
                        res = _json.loads(s_val)
                        parsed = res if isinstance(res, list) else [res] if isinstance(res, dict) else []
                    except Exception:
                        return []
                else:
                    parsed = []
                return _json.loads(_json.dumps(parsed, default=str))

            # Update room_details (strictly as native array)
            room_details = parse_json_field(adm.room_details)
            updated_room_details = []
            for r in (room_details if isinstance(room_details, list) else []):
                if isinstance(r, dict):
                    r_copy = dict(r)
                    if r_copy.get("is_roomActive"):
                        r_copy["is_roomActive"] = False
                        r_copy["is_roomCleaned"] = False
                        r_copy["endDateTime"] = now_iso
                    # Ensure no extra non-standard date variables exist
                    r_copy.pop("end_time", None)
                    r_copy.pop("endTime", None)
                    updated_room_details.append(r_copy)
                elif r:
                    updated_room_details.append(r)

            # Update roomShitingDetails (strictly as native array)
            shifts = parse_json_field(adm.roomShitingDetails)
            updated_shifts = []
            for s in (shifts if isinstance(shifts, list) else []):
                if isinstance(s, dict):
                    s_copy = dict(s)
                    if s_copy.get("is_roomActive"):
                        s_copy["is_roomActive"] = False
                        s_copy["is_roomCleaned"] = False
                        s_copy["endDateTime"] = now_iso
                    # Ensure no extra non-standard date variables exist
                    s_copy.pop("end_time", None)
                    s_copy.pop("endTime", None)
                    updated_shifts.append(s_copy)
                elif s:
                    updated_shifts.append(s)

            # Read advance_payments (strictly as native array)
            adv_payments = parse_json_field(getattr(adm, "advance_payments", []))

            rd_array = _to_native_list(updated_room_details)
            sd_array = _to_native_list(updated_shifts)
            ap_array = _to_native_list(adv_payments)

            adm.room_details       = rd_array
            adm.roomShitingDetails = sd_array
            adm.advance_payments   = ap_array

            adm.save()

            # Sync to MongoDB hospital_admission ensuring all 3 remain native BSON arrays
            db["hospital_admission"].update_one(
                {"ipNumber": str(adm.ipNumber)},
                {"$set": {
                    "is_discharged":       True,
                    "is_admitted":         False,
                    "room_details":       rd_array,
                    "roomShitingDetails": sd_array,
                    "advance_payments":   ap_array,
                    "lastmodified_by":    user_str,
                    "lastmodified_date":  now_dt,
                }}
            )

        # ── 2. Update Pharmacy Billing ───────────────────────────────────────
        # Criteria: outlet_code: "OLET001", ip_no / inpatient_number, payment_mode: "Credit", billing_status: "Billed", is_ward_request: True
        # Update: billing_status -> "Completed"
        pharm_ip_filter = []
        if ip_number:
            pharm_ip_filter.extend([
                {"inpatient_number": str(ip_number)},
                {"ipNumber": str(ip_number)},
                {"ip_number": str(ip_number)},
                {"ip_no": str(ip_number)},
            ])
        if uhid:
            pharm_ip_filter.append({"uhid": str(uhid)})

        pharm_match = {
            "$and": [
                {"$or": pharm_ip_filter},
                {
                    "$or": [
                        {"outlet_code": "OLET001"},
                        {"outlet_code": {"$regex": "OLET", "$options": "i"}},
                    ]
                },
                {"billing_status": "Billed"},
                {"is_ward_request": True},
                {
                    "$or": [
                        {"payment_mode": {"$regex": "^credit$", "$options": "i"}},
                        {"paymentMethod": {"$regex": "^credit$", "$options": "i"}},
                        {"payment_details.payment_mode": {"$regex": "^credit$", "$options": "i"}},
                    ]
                }
            ]
        }

        # Update in HMS DB hospital_pharmacybilling
        db["hospital_pharmacybilling"].update_many(
            pharm_match,
            {"$set": {
                "billing_status": "Completed",
                "lastmodified_by": user_str,
                "lastmodified_date": now_dt,
            }}
        )

        # Also update in secondary pharmacy DB if present
        try:
            pharm_client = MongoClient(os.getenv("PHARMACY_DB_HOST", os.getenv("GLOBAL_DB_HOST")))
            pharm_db = pharm_client[os.getenv("PHARMACY_DB_NAME", "pharmacy")]
            pharm_db["pharmacy_billing"].update_many(
                pharm_match,
                {"$set": {
                    "billing_status": "Completed",
                    "lastmodified_by": user_str,
                    "lastmodified_date": now_dt,
                }}
            )
        except Exception:
            pass

        # ── 3. Update Invest Billing ─────────────────────────────────────────
        # Criteria: ipNumber, paymentMethod: "Credit", paymentStatus: "Pending"
        # Update: paymentStatus -> "Billed"
        invest_ip_filter = []
        if ip_number:
            invest_ip_filter.extend([
                {"ipNumber": str(ip_number)},
                {"inpatient_number": str(ip_number)},
                {"ip_number": str(ip_number)},
            ])
        if uhid:
            invest_ip_filter.append({"uhid": str(uhid)})

        invest_match = {
            "$and": [
                {"$or": invest_ip_filter},
                {
                    "$or": [
                        {"paymentMethod": {"$regex": "^credit$", "$options": "i"}},
                        {"payment_method": {"$regex": "^credit$", "$options": "i"}},
                    ]
                },
                {
                    "$or": [
                        {"paymentStatus": "Pending"},
                        {"payment_status": "Pending"},
                    ]
                }
            ]
        }
        db["hospital_investbilling"].update_many(
            invest_match,
            {"$set": {
                "paymentStatus": "Billed",
                "payment_status": "Billed",
                "lastmodified_by": user_str,
                "lastmodified_date": now_dt,
            }}
        )

    except Exception as e:
        import traceback
        print(f"Error in _finalize_discharge for IP {ip_number}: {e}")
        traceback.print_exc()


def _mark_admission_discharged(ip_number, user_id=None, uhid=None):
    _finalize_discharge(ip_number, user_id=user_id, uhid=uhid)


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

    # Resolve latest room / bed and room category
    room_details = parse_json_field(getattr(admission, "room_details", [])) if admission else []
    current_room = ""
    current_bed = ""
    current_room_cat = "GENERAL WARD"
    if room_details and isinstance(room_details, list):
        last_room = room_details[-1]
        if isinstance(last_room, dict):
            current_room = str(last_room.get("roomNo") or last_room.get("roomNumber") or last_room.get("room_number") or "")
            current_bed  = str(last_room.get("bedNo") or last_room.get("bedNumber") or last_room.get("bed_number") or "")

    shiftings_details = parse_json_field(getattr(admission, "roomShitingDetails", [])) if admission else []
    if shiftings_details and isinstance(shiftings_details, list):
        active_shifts = [s for s in shiftings_details if isinstance(s, dict) and s.get("is_roomActive")]
        if active_shifts:
            last_shift = active_shifts[-1]
            current_room = str(last_shift.get("newRoomNo") or current_room)
            current_bed  = str(last_shift.get("newBedNo") or current_bed)

    total_days = 0
    if adm_dt:
        try:
            today    = _date.today()
            adm_date = adm_dt.date() if isinstance(adm_dt, _datetime) else (adm_dt if isinstance(adm_dt, _date) else _parse_dt(adm_dt).date())
            total_days = max(1, (today - adm_date).days)
        except Exception:
            total_days = 1
    else:
        total_days = 1

    # Advance Payments calculation
    total_advance = 0.0
    adv_payments = parse_json_field(getattr(admission, "advance_payments", [])) if admission else []
    for adv in adv_payments:
        if isinstance(adv, dict) and adv.get("is_advanceActive") and str(adv.get("status", "")).lower() != "cancelled":
            amt = _to_float(adv.get("advance_amount", 0))
            refunds = adv.get("refund_details", [])
            ref_amt = 0.0
            if isinstance(refunds, list):
                for r in refunds:
                    if isinstance(r, dict):
                        ref_amt += _to_float(r.get("refunded_amount", 0))
            total_advance += max(0.0, amt - ref_amt)

    addr_parts = [getattr(patient, "permanent_address", ""), getattr(patient, "area", ""), getattr(patient, "city", ""), getattr(patient, "state", ""), getattr(patient, "zipcode", "")]
    full_address = ", ".join([str(x).strip() for x in addr_parts if x and str(x).strip()])

    doc_id = getattr(admission, "admittingDoctor", "") if admission else ""
    doc_name = _resolve_employee_name(doc_id) if doc_id else ""

    # Resolve full insurance company name
    raw_company = getattr(admission, "company_code", "") or getattr(patient, "company_code", "") or getattr(admission, "insurance_company", "") or getattr(patient, "company_name", "") or ""
    company_name = ""
    if raw_company:
        try:
            from ..models import InsuranceProvider
            prov = InsuranceProvider.objects.filter(company_code=str(raw_company)).first()
            if prov and prov.company_name:
                company_name = prov.company_name
            else:
                prov2 = InsuranceProvider.objects.filter(company_name__iexact=str(raw_company)).first()
                if prov2 and prov2.company_name:
                    company_name = prov2.company_name
                else:
                    client_temp = MongoClient(os.getenv("GLOBAL_DB_HOST"))
                    db_temp = client_temp[os.getenv("HMS_DB_NAME", "HMS")]
                    ins_doc = db_temp["hospital_insuranceprovider"].find_one({"company_code": str(raw_company)})
                    if ins_doc and ins_doc.get("company_name"):
                        company_name = ins_doc.get("company_name")
                    else:
                        company_name = str(raw_company)
        except Exception:
            company_name = str(raw_company)

    patient_info = {
        "uhid":                 patient.uhid,
        "patient_name":         f"{patient.firstName} {patient.lastName}".strip(),
        "age":                  patient.age,
        "gender":               patient.gender,
        "mobile":               patient.mobilePhone,
        "ip_number":            admission.ipNumber if admission else None,
        "ipNumber":             admission.ipNumber if admission else None,
        "admission_date":       adm_str,
        "patient_type":         getattr(patient, "customer_type", "") or getattr(admission, "patient_type", ""),
        "company":              company_name,
        "company_code":         raw_company,
        "room_no":              current_room,
        "bed_no":               current_bed,
        "room_category":        current_room_cat,
        "total_days":           total_days,
        "advance_amount":       total_advance,
        "doctor":               doc_name or doc_id,
        "doctor_id":            doc_id,
        "address":              full_address,
        "guardian":             getattr(patient, "spouse_name", "") or getattr(patient, "emergency_contact", "") or "",
        "ward_status":          ward_status,
        "is_ready_for_billing": ward_status == "Sent for billing",
    }

    effective_ip   = ip_number or (admission.ipNumber if admission else None)
    effective_uhid = patient.uhid if patient else (uhid or (admission.uhid if admission else None))

    invest_items = []

    try:
        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        db = client[os.getenv("HMS_DB_NAME", "HMS")]

        # ── 0. Room Charges (Services & Room Kits) ───────────────────────────
        try:
            raw_movements = []
            adm_start_dt = _parse_dt(adm_dt) or _datetime.now()

            for r in room_details:
                if isinstance(r, dict):
                    r_no = str(r.get("roomNo") or r.get("roomNumber") or r.get("room_number") or "").strip()
                    b_no = str(r.get("bedNo") or r.get("bedNumber") or r.get("bed_number") or "").strip()
                    s_dt = _parse_dt(r.get("startDateTime")) or adm_start_dt
                    e_dt = _parse_dt(r.get("endDateTime"))
                    if r_no:
                        raw_movements.append({
                            "room_no": r_no,
                            "bed_no": b_no,
                            "start_dt": s_dt,
                            "end_dt": e_dt,
                        })

            for s in shiftings_details:
                if isinstance(s, dict):
                    r_no = str(s.get("newRoomNo") or "").strip()
                    b_no = str(s.get("newBedNo") or "").strip()
                    s_dt = _parse_dt(s.get("shiftingDateTime") or s.get("startDateTime")) or adm_start_dt
                    e_dt = _parse_dt(s.get("endDateTime"))
                    if r_no:
                        raw_movements.append({
                            "room_no": r_no,
                            "bed_no": b_no,
                            "start_dt": s_dt,
                            "end_dt": e_dt,
                        })

            raw_movements.sort(key=lambda x: x["start_dt"] or adm_start_dt)

            # Merge contiguous movements in the same room (e.g. bed shifting inside the same room)
            room_stays = []
            for mov in raw_movements:
                if room_stays and room_stays[-1]["room_no"] == mov["room_no"]:
                    room_stays[-1]["end_dt"] = mov["end_dt"]
                    room_stays[-1]["bed_no"] = mov["bed_no"]
                else:
                    room_stays.append(dict(mov))

            now_dt = _datetime.now()
            accumulated_days = 0

            # If no room stays were in room_details or shifts, but current_room exists:
            if not room_stays and current_room:
                room_stays.append({
                    "room_no": current_room,
                    "bed_no": current_bed,
                    "start_dt": adm_start_dt,
                    "end_dt": now_dt,
                })

            for stay in room_stays:
                r_no = stay["room_no"]
                s_dt = stay["start_dt"] or adm_start_dt
                e_dt = stay["end_dt"] or now_dt

                # Stay calculation: calculate days patient stayed; minimum 1 day even if vacated within an hour
                days_diff = (e_dt.date() - s_dt.date()).days
                stay_days = max(1, days_diff)
                accumulated_days += stay_days

                room_doc = db["hospital_room"].find_one({"room_number": r_no})
                if not room_doc:
                    room_doc = db["hospital_room"].find_one({"room_number": str(r_no)})

                if room_doc:
                    room_cat = room_doc.get("room_category", "")
                    if room_cat:
                        patient_info["room_category"] = room_cat

                    # A. Room Services (e.g. ROOM RENT, NURSING CHARGES)
                    services = room_doc.get("services", [])
                    if isinstance(services, str):
                        try:
                            services = _json.loads(services)
                        except Exception:
                            services = []

                    for srv in (services if isinstance(services, list) else []):
                        if isinstance(srv, dict):
                            srv_desc = str(srv.get("description") or srv.get("service_name") or "Room Rent").strip()
                            srv_rate = _to_float(srv.get("amount") or srv.get("price") or 0)
                            srv_amt  = srv_rate * stay_days
                            invest_items.append({
                                "invest_bill_no": f"ROOM-{r_no}",
                                "bill_object_id": str(room_doc.get("_id", "")),
                                "itemName":       srv_desc,
                                "price":          srv_rate,
                                "rate":           str(srv_rate),
                                "quantity":       stay_days,
                                "discount":       0,
                                "amount":         srv_amt,
                                "billTypeNo":     "DIS01",
                                "bill_type":      2,
                                "test_id":        None,
                                "doctor":         doc_name or doc_id,
                                "payment_status": "Pending",
                                "package_name":   f"Room {r_no} ({room_cat})" if room_cat else f"Room {r_no}",
                                "source":         "hospital_room_services",
                            })

                    # B. Room Kits (e.g. Bed Sheet, etc.)
                    kits = room_doc.get("room_kits", [])
                    if isinstance(kits, str):
                        try:
                            kits = _json.loads(kits)
                        except Exception:
                            kits = []

                    for kit in (kits if isinstance(kits, list) else []):
                        if isinstance(kit, dict):
                            kit_name = str(kit.get("kit_item") or kit.get("name") or "Room Kit").strip()
                            kit_rate = _to_float(kit.get("amount") or kit.get("price") or 0)
                            invest_items.append({
                                "invest_bill_no": f"KIT-{r_no}",
                                "bill_object_id": str(room_doc.get("_id", "")),
                                "itemName":       kit_name,
                                "price":          kit_rate,
                                "rate":           str(kit_rate),
                                "quantity":       1,
                                "discount":       0,
                                "amount":         kit_rate,
                                "billTypeNo":     "DIS01",
                                "bill_type":      2,
                                "test_id":        None,
                                "doctor":         doc_name or doc_id,
                                "payment_status": "Pending",
                                "package_name":   f"Room {r_no} Kit",
                                "source":         "hospital_room_kits",
                            })

            if accumulated_days > 0:
                patient_info["total_days"] = accumulated_days

        except Exception as e:
            import traceback
            print(f"Error fetching room charges: {e}")
            traceback.print_exc()

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
        # Calculate Medicine Charges from pharmacy bills for this IP stay
        pharm_q = get_query(
            ["inpatient_number", "ipNumber", "ip_number"],
            {"is_deleted": {"$ne": True}}
        )
        total_pharm_amt = 0.0
        if pharm_q:
            pharm_docs = list(db["hospital_pharmacybilling"].find(pharm_q))
            for doc in pharm_docs:
                tot_amt = _to_float(
                    doc.get("netAmount") or doc.get("net_amount") or doc.get("totalAmount") or doc.get("total_amount") or 0
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
                total_pharm_amt += tot_amt

        patient_info["medicines_amount"] = total_pharm_amt

        # ── 5. hospital_salesreturn ───────────────────────────────────────────
        # Calculate Sales Return amount from pharmacy returns for this IP stay
        sr_q = get_query(
            ["inpatient_number", "ipNumber", "ip_number"],
            {"is_deleted": {"$ne": True}}
        )
        total_sales_return = 0.0
        if sr_q:
            sr_docs = list(db["hospital_salesreturn"].find(sr_q))
            for doc in sr_docs:
                sr_amt = _to_float(
                    doc.get("return_amount") or doc.get("refund_amount") or doc.get("net_amount") or doc.get("total_amount") or 0
                )
                total_sales_return += sr_amt

        patient_info["sales_return"] = total_sales_return

        # ── 6. hospital_surgeryschedule ────────────────────────────────────────
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

        try:
            obj.save()
            _sync_mongo_items_array(obj)
            if billing_status == "Billed":
                _mark_admission_discharged(obj.ip_number, user_id=obj.created_by or obj.lastmodified_by, uhid=obj.uhid)
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
            if billing.status == "Billed":
                _mark_admission_discharged(billing.ip_number, user_id=billing.lastmodified_by, uhid=billing.uhid)
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
        _mark_admission_discharged(estimate.ip_number, user_id=estimate.lastmodified_by, uhid=estimate.uhid)
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


# ─────────────────────────────────────────────────────────────────────────────
# WHATSAPP DISCHARGE NEXT VISIT REMINDERS
# ─────────────────────────────────────────────────────────────────────────────

def get_discharge_visit_template_name():
    from pathlib import Path
    from dotenv import load_dotenv
    env_path = Path(__file__).resolve().parent.parent.parent / '.env'
    if env_path.exists():
        load_dotenv(env_path, override=True)
    return (os.getenv("BOTIFY_DISCHARGE_VISIT_TEMPLATE_NAME") or os.getenv("BOTIFY_VISIT_REMINDER_TEMPLATE_NAME") or "discharge_nextvisit_reminder").strip()


def send_whatsapp_discharge_visit_reminder(uhid, patient_name, phone, next_visit_date_val, doctor_name="", force=False, ip_number="", bill_no="", discharge_id=None):
    """
    Sends WhatsApp Next Visit Reminder using Botify API.
    Template: discharge_nextvisit_reminder
    Variables:
      {{1}} = Patient Name
      {{2}} = Next Visit Date (DD/MM/YYYY)
      {{3}} = Consulting Doctor
    Logs outcome only in dedicated PatientNextVisitLog model.
    """
    clean_phone = re.sub(r'\D', '', str(phone or ''))
    if len(clean_phone) == 10:
        clean_phone = f"91{clean_phone}"

    template_name = get_discharge_visit_template_name()
    botify_apikey = (os.getenv("BOTIFY_API_KEY") or "").strip()

    # Formatted visit date string (e.g. 30/08/2026)
    formatted_visit_date = ""
    iso_visit_date = ""
    d_obj = None
    if isinstance(next_visit_date_val, (_date, _datetime)):
        d_obj = next_visit_date_val if isinstance(next_visit_date_val, _date) else next_visit_date_val.date()
        formatted_visit_date = d_obj.strftime('%d/%m/%Y')
        iso_visit_date = d_obj.strftime('%Y-%m-%d')
    elif isinstance(next_visit_date_val, str) and next_visit_date_val.strip():
        s = next_visit_date_val.strip()[:10]
        try:
            d_obj = _datetime.strptime(s, '%Y-%m-%d').date()
            formatted_visit_date = d_obj.strftime('%d/%m/%Y')
            iso_visit_date = d_obj.strftime('%Y-%m-%d')
        except Exception:
            formatted_visit_date = s
            iso_visit_date = s

    if not clean_phone or len(clean_phone) < 10:
        err_msg = f"Invalid mobile phone number: '{phone}' for patient {patient_name} (UHID: {uhid})"
        logger.warning(err_msg)
        try:
            PatientNextVisitLog.objects.create(
                uhid=str(uhid or ''),
                ip_number=str(ip_number or ''),
                patient_name=str(patient_name or uhid or ''),
                type="WhatsApp",
                sender=os.getenv("WHATSAPP_SENDER_NUMBER", "WhatsApp API"),
                recipient=str(phone or ''),
                status="Failed",
                details=err_msg,
                template_name=template_name,
                created_by="system",
                branch_code="SHB001",
                hospital_code="SH001"
            )
        except Exception as log_ex:
            logger.error(f"Error logging failed PatientNextVisitLog: {str(log_ex)}")
        return {"success": False, "error": err_msg}

    # Duplicate check in PatientNextVisitLog: prevent sending multiple times for the same visit date
    if not force:
        try:
            already_sent = PatientNextVisitLog.objects.filter(
                uhid=str(uhid or ''),
                status="Success",
                details__icontains=str(formatted_visit_date)
            ).exists()

            if not already_sent and iso_visit_date:
                already_sent = PatientNextVisitLog.objects.filter(
                    uhid=str(uhid or ''),
                    status="Success",
                    details__icontains=str(iso_visit_date)
                ).exists()

            if already_sent:
                msg = f"Visit reminder already sent previously for patient {patient_name} ({uhid}) for visit on {formatted_visit_date}"
                logger.info(msg)
                return {"success": True, "skipped": True, "message": msg}
        except Exception as dup_ex:
            logger.warning(f"Duplicate check warning: {str(dup_ex)}")

    if botify_apikey.startswith("Bearer "):
        clean_api_key = botify_apikey[7:].strip()
        auth_header = botify_apikey
    else:
        clean_api_key = botify_apikey
        auth_header = f"Bearer {botify_apikey}"

    botify_url = "https://login.botify.in/api/whatsapp/external"
    headers = {
        "Authorization": auth_header,
        "Content-Type": "application/json"
    }

    p_name = str(patient_name or uhid or "Valued Patient").strip()
    doc_name = str(doctor_name or "Consulting Doctor").strip()

    # 3 parameters matching discharge_nextvisit_reminder: {{1}}=Name, {{2}}=Visit Date, {{3}}=Consulting Doctor
    template_data = [
        p_name,
        str(formatted_visit_date),
        doc_name
    ]

    components = [
        {
            "type": "body",
            "parameters": [
                {"type": "text", "text": str(p)} for p in template_data
            ]
        }
    ]

    body_payload = {
        "to": clean_phone,
        "type": "template",
        "templateName": template_name,
        "templateData": template_data,
        "components": components
    }

    try:
        r = requests.post(botify_url, json=body_payload, headers=headers, timeout=20)
        try:
            response_json = r.json()
            is_success = r.status_code in [200, 201] and (
                response_json.get("success") is True or
                response_json.get("status") in [True, "success", "200", 200] or
                response_json.get("result") == "success"
            )
        except ValueError:
            response_json = {}
            is_success = r.status_code in [200, 201]

        # Fallback if language is en_US
        if not is_success and "does not exist in en" in r.text:
            alt_lang_payload = {
                "to": clean_phone,
                "type": "template",
                "templateName": template_name,
                "templateData": template_data,
                "components": components,
                "language": {"code": "en_US"}
            }
            r_lang = requests.post(botify_url, json=alt_lang_payload, headers=headers, timeout=20)
            try:
                if r_lang.status_code in [200, 201] and (r_lang.json().get("success") is True or r_lang.json().get("status") in [True, "success", "200", 200]):
                    r = r_lang
                    response_json = r_lang.json()
                    is_success = True
            except Exception:
                pass

        # Fallback 1: 4-parameter template (legacy)
        if not is_success and "does not match the expected number of params" in r.text:
            alt4_template_data = [p_name, str(formatted_visit_date), doc_name, str(formatted_visit_date)]
            alt4_components = [{"type": "body", "parameters": [{"type": "text", "text": str(p)} for p in alt4_template_data]}]
            r_alt4 = requests.post(botify_url, json={
                "to": clean_phone,
                "type": "template",
                "templateName": template_name,
                "templateData": alt4_template_data,
                "components": alt4_components
            }, headers=headers, timeout=20)
            try:
                if r_alt4.status_code in [200, 201]:
                    r = r_alt4
                    response_json = r_alt4.json()
                    is_success = True
            except Exception:
                pass

        # Fallback 2: 2-parameter template
        if not is_success and "does not match the expected number of params" in r.text:
            alt2_template_data = [p_name, str(formatted_visit_date)]
            alt2_components = [{"type": "body", "parameters": [{"type": "text", "text": str(p)} for p in alt2_template_data]}]
            r_alt2 = requests.post(botify_url, json={
                "to": clean_phone,
                "type": "template",
                "templateName": template_name,
                "templateData": alt2_template_data,
                "components": alt2_components
            }, headers=headers, timeout=20)
            try:
                if r_alt2.status_code in [200, 201]:
                    r = r_alt2
                    response_json = r_alt2.json()
                    is_success = True
            except Exception:
                pass

        status_str = "Success" if is_success else "Failed"
        details_text = f"Discharge Next Visit Reminder for {formatted_visit_date} (Dr: {doc_name}). Botify Response: {r.text}"

        # Dedicated log entry for Discharge Next Visit
        PatientNextVisitLog.objects.create(
            uhid=str(uhid or ''),
            ip_number=str(ip_number or ''),
            patient_name=str(patient_name or uhid or ''),
            type="WhatsApp",
            sender=os.getenv("WHATSAPP_SENDER_NUMBER", "WhatsApp API"),
            recipient=clean_phone,
            status=status_str,
            details=details_text,
            template_name=template_name,
            created_by="system",
            branch_code="SHB001",
            hospital_code="SH001"
        )

        return {"success": is_success, "recipient": clean_phone, "response": response_json, "status_code": r.status_code}

    except Exception as e:
        err_text = f"Exception sending Discharge Visit Reminder WhatsApp to {clean_phone}: {str(e)}"
        logger.error(err_text)
        try:
            PatientNextVisitLog.objects.create(
                uhid=str(uhid or ''),
                ip_number=str(ip_number or ''),
                patient_name=str(patient_name or uhid or ''),
                type="WhatsApp",
                sender=os.getenv("WHATSAPP_SENDER_NUMBER", "WhatsApp API"),
                recipient=clean_phone,
                status="Failed",
                details=err_text,
                template_name=template_name,
                created_by="system",
                branch_code="SHB001",
                hospital_code="SH001"
            )
        except Exception:
            pass
        return {"success": False, "error": err_text}



def process_pending_discharge_visit_reminders(target_date=None, force=False):
    """
    Finds all DischargeBilling records where next_visit_date matches target_date (default: tomorrow, 1 day prior)
    and sends the WhatsApp next visit reminder.
    """
    if not target_date:
        tomorrow = timezone.now().date() + _dt_module.timedelta(days=1)
        target_date_str = tomorrow.strftime("%Y-%m-%d")
        target_date_obj = tomorrow
    else:
        if isinstance(target_date, str):
            target_date_str = target_date.strip()[:10]
            try:
                target_date_obj = _datetime.strptime(target_date_str, "%Y-%m-%d").date()
            except Exception:
                target_date_obj = None
        elif isinstance(target_date, (_date, _datetime)):
            target_date_obj = target_date if isinstance(target_date, _date) else target_date.date()
            target_date_str = target_date_obj.strftime("%Y-%m-%d")
        else:
            target_date_str = str(target_date)
            target_date_obj = None

    all_bills = list(DischargeBilling.objects.all())
    matching_bills = []

    for b in all_bills:
        if getattr(b, "is_cancelled", False):
            continue
        nvd = getattr(b, "next_visit_date", None)
        if not nvd:
            continue
        nvd_str = ""
        if isinstance(nvd, (_date, _datetime)):
            nvd_str = (nvd if isinstance(nvd, _date) else nvd.date()).strftime("%Y-%m-%d")
        elif isinstance(nvd, str):
            nvd_str = nvd.strip()[:10]

        if nvd_str == target_date_str:
            matching_bills.append(b)

    total_checked = len(matching_bills)
    reminders_sent = 0
    reminders_skipped = 0
    failed_sends = 0
    details_list = []

    for bill in matching_bills:
        uhid = bill.uhid or ""
        ip_num = bill.ip_number or ""
        doc_name = getattr(bill, "attending_doctor", "") or getattr(bill, "doctor_id", "") or ""
        bill_num = bill.bill_no or bill.estimate_number or ""

        # If doc_name is empty, check bill items
        if not doc_name:
            items_list = getattr(bill, "items", []) or []
            for itm in items_list:
                if isinstance(itm, dict) and itm.get("doctor"):
                    doc_name = itm.get("doctor")
                    break

        # If still empty, check Admission record
        if not doc_name and ip_num:
            try:
                adm = Admission.objects.filter(ipNumber=ip_num).first()
                if adm:
                    doc_name = adm.consultingDoctor or adm.admittingDoctor or ""
            except Exception:
                pass

        if doc_name:
            doc_name = str(doc_name).strip()
            if not doc_name.lower().startswith("dr.") and not doc_name.lower().startswith("dr "):
                doc_name = f"Dr. {doc_name}"
        else:
            doc_name = "Consulting Doctor"

        # Fetch mobilePhone directly from Patient model
        p_name = getattr(bill, "patient_name", "") or ""
        phone = ""

        if uhid:
            try:
                pat = Patient.objects.filter(uhid=uhid).first()
                if pat:
                    if not p_name:
                        p_name = f"{pat.firstName or ''} {pat.lastName or ''}".strip()
                    phone = getattr(pat, "mobilePhone", "") or getattr(pat, "home_phone", "") or ""
            except Exception as pat_ex:
                logger.warning(f"Error fetching Patient model for uhid {uhid}: {str(pat_ex)}")

        # Fallback to bill phone if still missing
        if not phone:
            phone = getattr(bill, "phone_number", "") or getattr(bill, "mobile_number", "") or ""

        res = send_whatsapp_discharge_visit_reminder(
            uhid=uhid,
            patient_name=p_name,
            phone=phone,
            next_visit_date_val=bill.next_visit_date,
            doctor_name=doc_name,
            force=force,
            ip_number=ip_num,
            bill_no=bill_num,
            discharge_id=bill.discharge_id
        )

        if res.get("skipped"):
            reminders_skipped += 1
        elif res.get("success"):
            reminders_sent += 1
        else:
            failed_sends += 1

        details_list.append({
            "discharge_id": bill.discharge_id,
            "bill_no": bill_num,
            "uhid": uhid,
            "patient_name": p_name,
            "phone": phone,
            "next_visit_date": target_date_str,
            "result": res
        })

    return {
        "success": True,
        "target_date": target_date_str,
        "total_patients_checked": total_checked,
        "reminders_sent": reminders_sent,
        "reminders_skipped": reminders_skipped,
        "failed_sends": failed_sends,
        "details": details_list
    }


@api_view(["POST", "GET"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def send_discharge_visit_reminders_api(request):
    """
    API endpoint to trigger pending next visit reminder messages for a target date (default tomorrow).
    Body: { "date": "YYYY-MM-DD", "force": false }
    """
    target_date = request.data.get("date") or request.GET.get("date")
    force = bool(request.data.get("force") or request.GET.get("force") in [True, "true", "1"])

    results = process_pending_discharge_visit_reminders(target_date=target_date, force=force)
    return Response(results, status=status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def send_single_discharge_visit_reminder_api(request):
    """
    API endpoint to trigger a single next visit reminder WhatsApp message.
    Body: { "uhid": "...", "patient_name": "...", "phone": "...", "next_visit_date": "YYYY-MM-DD", "doctor_name": "...", "force": false }
    """
    data = request.data
    uhid = data.get("uhid") or ""
    ip_num = data.get("ip_number") or ""
    p_name = data.get("patient_name") or ""
    phone = data.get("phone") or data.get("mobile") or data.get("phone_number") or ""
    next_visit = data.get("next_visit_date") or data.get("date")
    doc_name = data.get("doctor_name") or data.get("attending_doctor") or ""
    bill_num = data.get("bill_no") or ""
    disc_id = data.get("discharge_id")
    force = bool(data.get("force", False))

    if not next_visit:
        return Response({"success": False, "error": "next_visit_date is required"}, status=status.HTTP_400_BAD_REQUEST)

    # Fetch directly from Patient model
    if uhid:
        try:
            pat = Patient.objects.filter(uhid=uhid).first()
            if pat:
                if not p_name:
                    p_name = f"{pat.firstName or ''} {pat.lastName or ''}".strip()
                if not phone:
                    phone = getattr(pat, "mobilePhone", "") or getattr(pat, "home_phone", "") or ""
        except Exception:
            pass

    res = send_whatsapp_discharge_visit_reminder(
        uhid=uhid,
        patient_name=p_name,
        phone=phone,
        next_visit_date_val=next_visit,
        doctor_name=doc_name,
        force=force,
        ip_number=ip_num,
        bill_no=bill_num,
        discharge_id=disc_id
    )

    return Response(res, status=status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def patient_next_visit_logs_api(request):
    """
    Query log history from PatientNextVisitLog.
    Query params: uhid, from_date, to_date, status
    """
    uhid_f = request.GET.get("uhid")
    status_f = request.GET.get("status")
    from_date_str = request.GET.get("from_date")
    to_date_str = request.GET.get("to_date")

    logs = list(PatientNextVisitLog.objects.all().order_by("-created_date"))
    filtered = []

    for l in logs:
        if uhid_f and l.uhid != uhid_f:
            continue
        if status_f and l.status != status_f:
            continue
        if from_date_str:
            try:
                fd = _datetime.strptime(from_date_str[:10], "%Y-%m-%d").date()
                ld = l.created_date.date() if isinstance(l.created_date, _datetime) else l.created_date
                if ld < fd:
                    continue
            except Exception:
                pass
        if to_date_str:
            try:
                td = _datetime.strptime(to_date_str[:10], "%Y-%m-%d").date()
                ld = l.created_date.date() if isinstance(l.created_date, _datetime) else l.created_date
                if ld > td:
                    continue
            except Exception:
                pass
        filtered.append({
            "id": str(getattr(l, "id", "")),
            "uhid": l.uhid,
            "ip_number": l.ip_number,
            "patient_name": l.patient_name,
            "type": l.type,
            "recipient": l.recipient,
            "status": l.status,
            "details": l.details,
            "template_name": l.template_name,
            "created_date": l.created_date.isoformat() if hasattr(l.created_date, "isoformat") else str(l.created_date)
        })

    return Response({
        "success": True,
        "count": len(filtered),
        "data": filtered
    }, status=status.HTTP_200_OK)



