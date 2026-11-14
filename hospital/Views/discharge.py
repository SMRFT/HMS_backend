import os
import re
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
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from django.http import JsonResponse
import traceback
import requests
import re
import logging
from datetime import timedelta

logger = logging.getLogger(__name__)

from pyauth.auth import HasRoleAndDataPermission
from ..models import Patient, Admission, DischargeBilling, PatientNextVisitLog, Billing


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


try:
    from zoneinfo import ZoneInfo as _ZoneInfo
    _IST_TZ = _ZoneInfo("Asia/Kolkata")
except Exception:
    _IST_TZ = _dt_module.timezone(timedelta(hours=5, minutes=30))


def _to_ist_dt(val):
    dt = _parse_dt(val)
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt_module.timezone.utc)
    return dt.astimezone(_IST_TZ)


# ─────────────────────────────────────────────────────────────────────────────
# Raw PyMongo — InvestBilling ONLY
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# High Performance MongoDB Pool & Indexing
# ─────────────────────────────────────────────────────────────────────────────
from .mongo_utils import get_hms_db

_discharge_indexes_ensured = False

def ensure_discharge_indexes():
    global _discharge_indexes_ensured
    if _discharge_indexes_ensured:
        return
    try:
        _, db = get_hms_db()
        def _idx(coll, keys):
            try:
                db[coll].create_index(keys, background=True)
            except Exception:
                pass

        _idx("hospital_dischargebilling", [("status", 1), ("bill_date", -1)])
        _idx("hospital_dischargebilling", [("discharge_id", 1)])
        _idx("hospital_dischargebilling", [("ip_number", 1), ("status", 1)])
        _idx("hospital_dischargebilling", [("uhid", 1)])
        _idx("hospital_dischargebilling", [("bill_no", 1)])
        _idx("hospital_dischargebilling", [("estimate_number", 1)])
        _idx("hospital_dischargebilling", [("created_date", -1)])

        _idx("hospital_admission", [("ipNumber", 1)])
        _idx("hospital_admission", [("uhid", 1), ("is_admitted", 1)])
        _idx("hospital_patient", [("uhid", 1)])
        _idx("hospital_investbilling", [("ipNumber", 1), ("paymentMethod", 1), ("paymentStatus", 1)])
        _idx("hospital_pharmacybilling", [("inpatient_number", 1), ("is_deleted", 1)])
        _idx("hospital_pharmacybilling", [("ipNumber", 1)])
        _idx("hospital_salesreturn", [("inpatient_number", 1)])
        _idx("hospital_surgeryschedule", [("ip_number", 1), ("status", 1)])
        _idx("hospital_patientdietorder", [("inpatient_number", 1), ("status", 1)])
        _idx("hospital_laundrywardrequest", [("ipNumber", 1), ("status", 1)])
        _idx("hospital_room", [("room_number", 1)])
        _discharge_indexes_ensured = True
    except Exception:
        pass


def _invest_col():
    _, db = get_hms_db()
    return db["hospital_investbilling"]


# ─────────────────────────────────────────────────────────────────────────────
# High-Speed Number generators (Native PyMongo index-sorted queries)
# ─────────────────────────────────────────────────────────────────────────────

def _financial_year():
    today = _date.today()
    y = today.year
    if today.month >= 4:
        return f"{str(y)[2:]}{str(y + 1)[2:]}"
    return f"{str(y - 1)[2:]}{str(y)[2:]}"


def generate_estimate_number():
    """EST/YYMM/000001 — resets each calendar month (sub-millisecond indexed query)."""
    today  = _date.today()
    prefix = f"EST/{str(today.year)[2:]}{str(today.month).zfill(2)}/"
    seq = 1
    try:
        _, db = get_hms_db()
        latest = db["hospital_dischargebilling"].find_one(
            {"estimate_number": {"$regex": f"^{re.escape(prefix)}"}},
            projection={"estimate_number": 1},
            sort=[("estimate_number", -1)]
        )
        if latest and latest.get("estimate_number"):
            seq_str = str(latest["estimate_number"]).split("/")[-1]
            seq = int(seq_str) + 1
    except Exception:
        seq = 1
    return f"{prefix}{str(seq).zfill(6)}"


def generate_bill_number():
    """Continuous sequential bill number via atomic counter service, continuing seamlessly without slash (e.g. 2627005691)."""
    from ..counter_service import get_next_discharge_bill_no
    val = get_next_discharge_bill_no()
    return str(val).replace("/", "") if val else val


def _clean_insurance_prefix(name_or_code):
    if not name_or_code:
        return "INS"
    s = str(name_or_code).strip()
    s_upper = s.upper()
    if "CGHS" in s_upper and "RAILWAY" not in s_upper:
        return "CGHS"
    if "RAILWAY" in s_upper or "CTSE" in s_upper:
        return "RAILWAYCTSE"
    if "ECHS" in s_upper:
        return "ECHS"
    if "CM" in s_upper and "SCHEME" in s_upper:
        return "CMSCHEME"
    if "NHIS" in s_upper:
        return "NHIS"
    if "GIPSA" in s_upper:
        return "GENERALGIPSA"
    if "IMPLANT" in s_upper:
        return "IMPLANTS"
    clean = re.sub(r'[^A-Za-z0-9]', '', s).upper()
    return clean or "INS"


def generate_insurance_bill_number(insurance_name_or_code):
    """
    Generate separate sequential bill number for each insurance scheme/company.
    e.g. CGHS-2627000001, RAILWAYCTSE-2627000001.
    """
    clean_prefix = _clean_insurance_prefix(insurance_name_or_code)
    fy = _financial_year()
    prefix = f"{clean_prefix}-{fy}"
    seq = 1
    try:
        _, db = get_hms_db()
        regex_pattern = f"^{re.escape(prefix)}"
        cursor = db["hospital_dischargebilling"].find(
            {"insurance_bill_number": {"$regex": regex_pattern}},
            {"insurance_bill_number": 1}
        )
        max_seq = 0
        for doc in cursor:
            val = str(doc.get("insurance_bill_number") or "")
            if "/" in val:
                parts = val.split("/")
                try:
                    num = int(parts[-1])
                    if num > max_seq:
                        max_seq = num
                except ValueError:
                    pass
            elif val.startswith(prefix):
                try:
                    num = int(val[len(prefix):])
                    if num > max_seq:
                        max_seq = num
                except ValueError:
                    pass
        seq = max_seq + 1
    except Exception as e:
        print(f"Error generating insurance bill number: {e}")
        seq = 1
    return f"{prefix}{str(seq).zfill(6)}".replace("/", "")



# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_pk(discharge_id):
    """
    Return DischargeBilling or None, looked up by discharge_id.
    Uses indexed integer PK or fast Mongo lookup fallback.
    """
    if discharge_id is None:
        return None
    try:
        d_id = int(discharge_id)
        return DischargeBilling.objects.get(discharge_id=d_id)
    except (ValueError, TypeError, DischargeBilling.DoesNotExist):
        pass
    except Exception:
        pass

    try:
        _, db = get_hms_db()
        doc = db["hospital_dischargebilling"].find_one({
            "$or": [
                {"discharge_id": int(discharge_id) if str(discharge_id).isdigit() else discharge_id},
                {"discharge_id": str(discharge_id)},
                {"id": int(discharge_id) if str(discharge_id).isdigit() else discharge_id},
                {"id": str(discharge_id)},
            ]
        }, projection={"discharge_id": 1})
        if doc and "discharge_id" in doc:
            return DischargeBilling.objects.get(discharge_id=int(doc["discharge_id"]))
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
        "code":             str(it.get("code") or it.get("test_id") or ""),
        "nabh_code":        str(it.get("nabh_code") or it.get("nabhCode") or "").strip(),
        "nabh_rate":        _to_float(it.get("nabh_rate", 0)) if it.get("nabh_rate") is not None else None,
        "non_nabh_rate":    _to_float(it.get("non_nabh_rate", 0)) if it.get("non_nabh_rate") is not None else None,
        "quantity":         it.get("quantity", 1),
        "rate":             it.get("rate") if it.get("rate") is not None else it.get("price", 0),
        "discount":         _to_float(it.get("discount", 0)),
        "amount":           _to_float(it.get("amount", 0)),
        "doctor":           str(it.get("doctor") or ""),
        "doctor_fee":       str(it.get("doctor_fee") or ""),
        "bill_type":        it.get("bill_type") if (it.get("bill_type") is not None and str(it.get("bill_type")).strip() != "") else 2,
        "billTypeNo":       str(it.get("billTypeNo") or "DIS01"),
        "item_description": str(it.get("item_description") or "") if str(it.get("item_description") or "").strip() not in ["DIS01", str(it.get("billTypeNo") or "").strip()] else "",
        "package_name":     str(it.get("package_name") or ""),
        "rate_category":    str(it.get("rate_category") or it.get("_rateCategory") or "").strip(),
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
        _, db = get_hms_db()

        if isinstance(obj_or_id, DischargeBilling):
            obj = obj_or_id
            discharge_id = obj.discharge_id
            items = _resolve_items_doctor_names(_parse_items(obj.items))
            update_dict = {"items": items}
            if getattr(obj, "created_by", None): update_dict["created_by"] = str(obj.created_by)
            if getattr(obj, "created_date", None): update_dict["created_date"] = obj.created_date
            if getattr(obj, "bill_date", None):
                bd_val = obj.bill_date
                if isinstance(bd_val, _date) and not isinstance(bd_val, _datetime):
                    bd_val = _datetime(bd_val.year, bd_val.month, bd_val.day, tzinfo=_dt_module.timezone.utc)
                update_dict["bill_date"] = bd_val
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
            if getattr(obj, "is_insurance_bill", None) is not None: update_dict["is_insurance_bill"] = bool(obj.is_insurance_bill)
            if getattr(obj, "claim_number", None) is not None: update_dict["claim_number"] = str(obj.claim_number)
            if getattr(obj, "id_card_number", None) is not None: update_dict["id_card_number"] = str(obj.id_card_number)
            if getattr(obj, "insurance_bill_number", None) is not None: update_dict["insurance_bill_number"] = str(obj.insurance_bill_number)
            if getattr(obj, "company_name", None) is not None: update_dict["company_name"] = str(obj.company_name)
            if getattr(obj, "implant_amount", None) is not None: update_dict["implant_amount"] = _to_float(obj.implant_amount)
            if getattr(obj, "payment_method", None) is not None: update_dict["payment_method"] = str(obj.payment_method)
            update_dict["billTypeNo"] = str(getattr(obj, "billTypeNo", None) or "DIS01")
            update_dict["bill_type"] = int(getattr(obj, "bill_type")) if getattr(obj, "bill_type", None) is not None else 2

            db["hospital_dischargebilling"].update_one(
                {"discharge_id": int(discharge_id)},
                {"$set": update_dict}
            )
        else:
            discharge_id = obj_or_id
            items = _resolve_items_doctor_names(_parse_items(raw_items))
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
    "total_amount", "advance_amount", "sales_return", "medicines_amount", "implant_amount",
    "taxable_amount", "non_tax_amount",
    "gst_amount", "room_tax",
    "discount_percent", "discount_amount", "net_amount",
]


def _normalise_decimals(obj):
    for field in _DECIMAL_FIELDS:
        if hasattr(obj, field):
            setattr(obj, field, _to_float(getattr(obj, field, None)))


_employee_name_cache = {}
_employee_designation_cache = {}
_manager_cache = {}
_dept_cache = {}

def _resolve_department_name(dept_code):
    if not dept_code:
        return ""
    code_str = str(dept_code).strip()
    if not code_str:
        return ""
    if code_str in _dept_cache:
        return _dept_cache[code_str]
    try:
        client, db = get_hms_db()
        g_db = client["Global"]
        dept = g_db["backend_diagnostics_Departments"].find_one({
            "$or": [
                {"department_code": code_str},
                {"department_code": {"$regex": f"^{re.escape(code_str)}$", "$options": "i"}}
            ]
        })
        if dept:
            d_name = (dept.get("department_name") or dept.get("description") or "").strip()
            if d_name:
                _dept_cache[code_str] = d_name
                return d_name
        dept_h = db["hospital_department"].find_one({
            "$or": [
                {"department_id": code_str},
                {"department_name": {"$regex": f"^{re.escape(code_str)}$", "$options": "i"}}
            ]
        })
        if dept_h:
            d_name = (dept_h.get("department_name") or "").strip()
            if d_name:
                _dept_cache[code_str] = d_name
                return d_name
    except Exception:
        pass
    return code_str

def _resolve_doctor_and_department(doc_id):
    if not doc_id:
        return "", ""
    doc_str = str(doc_id).strip()
    try:
        client, _ = get_hms_db()
        g_db = client["Global"]
        profile = g_db["backend_diagnostics_profile"].find_one({"employeeId": doc_str})
        if profile:
            doc_name = (profile.get("employeeName") or f"{profile.get('firstName', '')} {profile.get('lastName', '')}".strip() or "").strip()
            dept_code = profile.get("department") or ""
            dept_name = _resolve_department_name(dept_code) if dept_code else ""
            return doc_name, dept_name
    except Exception:
        pass
    return _resolve_employee_name(doc_id), ""

def _resolve_employee_name(emp_id):
    if not emp_id:
        return ""
    emp_str = str(emp_id).strip()
    if not emp_str:
        return ""
    clean_emp = re.sub(r'^(dr[.\s]*)+', '', emp_str, flags=re.IGNORECASE).strip()
    lookup_keys = [emp_str]
    if clean_emp and clean_emp != emp_str:
        lookup_keys.append(clean_emp)
    for k in lookup_keys:
        if k in _employee_name_cache:
            return _employee_name_cache[k]
    try:
        client, _ = get_hms_db()
        db = client["Global"]
        or_conds = []
        for k in lookup_keys:
            or_conds.append({"employeeId": k})
            if k.isdigit():
                or_conds.append({"employeeId": int(k)})
        profile = db["backend_diagnostics_profile"].find_one(
            {"$or": or_conds} if len(or_conds) > 1 else or_conds[0],
            {"employeeName": 1, "firstName": 1, "lastName": 1}
        )
        if profile:
            name = profile.get("employeeName") or f"{profile.get('firstName', '')} {profile.get('lastName', '')}".strip()
            if name:
                for k in lookup_keys:
                    _employee_name_cache[k] = name
                return name
    except Exception:
        pass
    return emp_str


def _resolve_employee_designation(emp_id):
    """
    Match created_by id with profile, get the designation field (e.g. DESIG003),
    match with backend_diagnostics_Designation collection on Designation_code,
    and format designation for discharge bill (e.g. INSURANCE ASSISTANT MANAGER).
    """
    if not emp_id:
        return ""
    emp_str = str(emp_id).strip()
    if not emp_str:
        return ""
    if emp_str in _employee_designation_cache:
        return _employee_designation_cache[emp_str]
    try:
        client, _ = get_hms_db()
        db = client["Global"]
        profile = db["backend_diagnostics_profile"].find_one(
            {"employeeId": emp_str},
            {"designation": 1, "department": 1}
        )
        if profile:
            desig_code = profile.get("designation")
            if desig_code:
                desig_doc = db["backend_diagnostics_Designation"].find_one(
                    {"Designation_code": str(desig_code).strip()}
                )
                if not desig_doc:
                    desig_doc = db["backend_diagnostics_Designation"].find_one(
                        {"Designation_code": {"$regex": f"^{re.escape(str(desig_code).strip())}$", "$options": "i"}}
                    )
                if desig_doc:
                    desig_name = (desig_doc.get("designation") or desig_doc.get("decription") or "").strip()
                    if desig_name:
                        upper_desig = desig_name.upper()
                        if "INSURANCE" not in upper_desig:
                            final_desig = f"INSURANCE {upper_desig}"
                        else:
                            final_desig = upper_desig
                        _employee_designation_cache[emp_str] = final_desig
                        return final_desig
    except Exception as e:
        logger.error(f"Error resolving employee designation for {emp_id}: {e}")

    return ""


def _resolve_insurance_manager():
    """
    department: 'DEPT017', designation: 'DESIG027' in profile.
    Get and display name in the right side of the page with GENERAL INSURANCE MANAGER.
    """
    try:
        client, _ = get_hms_db()
        db = client["Global"]
        profile = db["backend_diagnostics_profile"].find_one({
            "$or": [
                {"department": "DEPT017", "designation": "DESIG027"},
                {"department": {"$regex": "^DEPT017$", "$options": "i"}, "designation": {"$regex": "^DESIG027$", "$options": "i"}},
                {"department": {"$regex": "insurance", "$options": "i"}, "designation": {"$regex": "^DESIG027$", "$options": "i"}},
                {"department": {"$in": ["DEPT017", "Insurance"]}, "employeeId": "50012"},
                {"department": {"$in": ["DEPT017", "Insurance"]}, "employeeName": {"$regex": "Kausalya", "$options": "i"}}
            ]
        })
        if not profile:
            profile = db["backend_diagnostics_profile"].find_one({
                "$or": [
                    {"employeeId": "50012"},
                    {"employeeName": {"$regex": "Kausalya", "$options": "i"}},
                    {"department": {"$in": ["DEPT017", "Insurance"]}}
                ]
            })
        if profile:
            name = (profile.get("employeeName") or f"{profile.get('firstName', '')} {profile.get('lastName', '')}".strip() or "").strip()
            if name:
                return {
                    "name": name.upper(),
                    "designation": "GENERAL INSURANCE MANAGER"
                }
    except Exception as e:
        logger.error(f"Error resolving insurance manager: {e}")

    return {
        "name": "",
        "designation": "GENERAL INSURANCE MANAGER"
    }


def _batch_resolve_employees(emp_ids):
    if not emp_ids:
        return
    cleaned_set = set()
    for e in emp_ids:
        if not e: continue
        s_val = str(e).strip()
        if not s_val: continue
        cleaned_set.add(s_val)
        c = re.sub(r'^(dr[.\s]*)+', '', s_val, flags=re.IGNORECASE).strip()
        if c: cleaned_set.add(c)
        if c.isdigit(): cleaned_set.add(int(c))
    missing = [e for e in cleaned_set if str(e) not in _employee_name_cache]
    if not missing:
        return
    try:
        client, _ = get_hms_db()
        db_global = client["Global"]
        profiles = list(db_global["backend_diagnostics_profile"].find(
            {"employeeId": {"$in": missing}},
            {"employeeId": 1, "employeeName": 1, "firstName": 1, "lastName": 1}
        ))
        for p in profiles:
            eid = str(p.get("employeeId", "")).strip()
            name = p.get("employeeName") or f"{p.get('firstName', '')} {p.get('lastName', '')}".strip()
            if eid and name:
                _employee_name_cache[eid] = name
                _employee_name_cache[f"DR.{eid}"] = name
                _employee_name_cache[f"DR. {eid}"] = name
    except Exception:
        pass


def _resolve_items_doctor_names(items):
    """Ensure doctor ids (e.g. '50978', 'DR.50978') on items are resolved to actual doctor names"""
    if not isinstance(items, list):
        return items
    doc_ids_to_fetch = set()
    for it in items:
        if not isinstance(it, dict):
            continue
        d_val = str(it.get("doctor") or it.get("doctor_name") or "").strip()
        if d_val:
            clean_id = re.sub(r'^(dr[.\s]*)+', '', d_val, flags=re.IGNORECASE).strip()
            if clean_id.isdigit() or (clean_id.startswith("5") and len(clean_id) == 5):
                doc_ids_to_fetch.add(clean_id)
        s_val = str(it.get("surgeon_id") or "").strip()
        if s_val and (s_val.isdigit() or (s_val.startswith("5") and len(s_val) == 5)):
            doc_ids_to_fetch.add(s_val)

    if doc_ids_to_fetch:
        _batch_resolve_employees(list(doc_ids_to_fetch))

    for it in items:
        if not isinstance(it, dict):
            continue
        d_val = str(it.get("doctor") or it.get("doctor_name") or "").strip()
        if d_val:
            clean_id = re.sub(r'^(dr[.\s]*)+', '', d_val, flags=re.IGNORECASE).strip()
            resolved = _resolve_employee_name(clean_id)
            if resolved and resolved != clean_id:
                it["doctor"] = resolved
                it["doctor_name"] = resolved
        elif it.get("surgeon_id"):
            s_val = str(it.get("surgeon_id")).strip()
            resolved = _resolve_employee_name(s_val)
            if resolved and resolved != s_val:
                it["doctor"] = resolved
                it["doctor_name"] = resolved
    return items




def _resolve_insurance_member_details(uhid=None, patient_name=None, member_number=None, card_no=None):
    """
    Lookup Claim number (referral_number) and ID card number (card_no)
    from hospital_insurancemember (and hospital_insurancemembervisit).
    card_no is id card no, and referral_number is Claim number.
    """
    claim_number = ""
    id_card_number = ""
    member_doc = None

    try:
        client, db = get_hms_db()
        mem_col = db["hospital_insurancemember"]
        visit_col = db["hospital_insurancemembervisit"]

        # 1. By member_number if provided
        if member_number:
            m = mem_col.find_one({"member_number": {"$regex": f"^{re.escape(str(member_number).strip())}$", "$options": "i"}})
            if m:
                member_doc = m
                id_card_number = str(m.get("card_no") or m.get("echs_card") or "").strip()
                claim_number = str(m.get("referral_number") or "").strip()

        # 2. By card_no if provided
        if not id_card_number and card_no:
            rgx = re.compile(f"^{re.escape(str(card_no).strip())}$", re.IGNORECASE)
            m = mem_col.find_one({"$or": [{"card_no": rgx}, {"echs_card": rgx}]})
            if m:
                member_doc = m
                id_card_number = str(m.get("card_no") or m.get("echs_card") or "").strip()
                claim_number = str(m.get("referral_number") or "").strip()

        # 3. By UHID directly in hospital_insurancemember
        if (not id_card_number or not claim_number) and uhid:
            u_clean = str(uhid).strip()
            if u_clean:
                rgx = re.compile(f"^{re.escape(u_clean)}$", re.IGNORECASE)
                m = mem_col.find_one({"uhid": rgx})
                if m:
                    member_doc = member_doc or m
                    if not id_card_number:
                        id_card_number = str(m.get("card_no") or m.get("echs_card") or "").strip()
                    if not claim_number:
                        claim_number = str(m.get("referral_number") or "").strip()

        # 4. By UHID via hospital_insurancemembervisit
        if (not id_card_number or not claim_number) and uhid:
            u_clean = str(uhid).strip()
            if u_clean:
                rgx = re.compile(f"^{re.escape(u_clean)}$", re.IGNORECASE)
                v = visit_col.find_one({"uhid": rgx}, sort=[("visit_date", -1), ("created_date", -1)])
                if v:
                    if not claim_number and v.get("referral_number"):
                        claim_number = str(v.get("referral_number")).strip()
                    m_num = v.get("member_number")
                    if m_num and not id_card_number:
                        m = mem_col.find_one({"member_number": m_num})
                        if m:
                            member_doc = member_doc or m
                            id_card_number = str(m.get("card_no") or m.get("echs_card") or "").strip()
                            if not claim_number and m.get("referral_number"):
                                claim_number = str(m.get("referral_number")).strip()

        # 5. By Patient Name via visit and member
        if (not id_card_number or not claim_number) and patient_name:
            p_clean = str(patient_name).strip()
            if p_clean and p_clean != "—":
                rgx = re.compile(f"^{re.escape(p_clean)}$", re.IGNORECASE)
                v = visit_col.find_one({"patient_name": rgx}, sort=[("visit_date", -1), ("created_date", -1)])
                if v:
                    if not claim_number and v.get("referral_number"):
                        claim_number = str(v.get("referral_number")).strip()
                    m_num = v.get("member_number")
                    if m_num and not id_card_number:
                        m = mem_col.find_one({"member_number": m_num})
                        if m:
                            member_doc = member_doc or m
                            id_card_number = str(m.get("card_no") or m.get("echs_card") or "").strip()
                            if not claim_number and m.get("referral_number"):
                                claim_number = str(m.get("referral_number")).strip()
                if not id_card_number:
                    m = mem_col.find_one({"$or": [{"member_name": rgx}, {"member_first_name": rgx}]})
                    if m:
                        member_doc = member_doc or m
                        id_card_number = str(m.get("card_no") or m.get("echs_card") or "").strip()
                        if not claim_number and m.get("referral_number"):
                            claim_number = str(m.get("referral_number")).strip()

    except Exception as e:
        print(f"Error resolving insurance member details: {e}")

    return {
        "claim_number": claim_number,
        "id_card_number": id_card_number,
        "card_no": id_card_number,
        "referral_number": claim_number,
        "member_number": member_doc.get("member_number", "") if member_doc else "",
    }


def _extract_adm_room_and_date(adm):
    if not adm:
        return "", ""
    adm_dt = adm.get("admissionDateTime")
    adm_ist = _to_ist_dt(adm_dt)
    if adm_ist:
        adm_str = adm_ist.strftime("%d-%m-%Y %I:%M %p")
    elif isinstance(adm_dt, _date):
        adm_str = adm_dt.strftime("%d-%m-%Y")
    elif isinstance(adm_dt, str) and adm_dt:
        adm_str = adm_dt
    else:
        adm_str = ""

    current_room = ""
    rd = parse_json_field(adm.get("room_details", []))
    if isinstance(rd, list) and rd:
        last_room = rd[-1]
        if isinstance(last_room, dict):
            current_room = str(last_room.get("roomNo") or last_room.get("roomNumber") or last_room.get("room_number") or "")
    sd = parse_json_field(adm.get("roomShitingDetails", []))
    if isinstance(sd, list) and sd:
        active_shifts = [s for s in sd if isinstance(s, dict) and s.get("is_roomActive")]
        target_shift = active_shifts[-1] if active_shifts else (sd[-1] if isinstance(sd[-1], dict) else None)
        if target_shift and target_shift.get("newRoomNo"):
            current_room = str(target_shift.get("newRoomNo"))
    return adm_str, current_room


def _format_raw_bill_doc(doc, patient_map=None, adm_map=None):
    """
    Ultra-fast in-memory serializer for DischargeBilling raw MongoDB document.
    Uses pre-fetched patient_map and adm_map for zero additional database queries.
    """
    discharge_id = doc.get("discharge_id") or doc.get("id")
    uhid = str(doc.get("uhid") or "").strip()
    ip_number = str(doc.get("ip_number") or "").strip()

    patient_details = {}
    if uhid:
        p = patient_map.get(uhid) if patient_map else None
        if not p:
            try:
                _, db = get_hms_db()
                p = db["hospital_patient"].find_one({"uhid": uhid})
            except Exception:
                p = None

        if p:
            addr_parts = [p.get("permanent_address"), p.get("area"), p.get("city"), p.get("state"), p.get("zipcode")]
            full_address = ", ".join([str(x).strip() for x in addr_parts if x and str(x).strip()])

            adm = (adm_map.get(ip_number) if adm_map else None) if ip_number else None
            if not adm and ip_number:
                try:
                    _, db = get_hms_db()
                    adm = db["hospital_admission"].find_one({"ipNumber": ip_number})
                except Exception:
                    adm = None

            adm_str, current_room = _extract_adm_room_and_date(adm)

            doc_id = str(adm.get("admittingDoctor") or "") if adm else ""
            doc_name, dept_name = _resolve_doctor_and_department(doc_id)
            if not doc_name:
                doc_name = _resolve_employee_name(doc_id) if doc_id else ""
            if not dept_name and adm:
                dept_name = _resolve_department_name(adm.get("department") or adm.get("admittingDepartment") or "")

            disch_dt = adm.get("dischargeDateTime") or adm.get("discharge_date") if adm else None
            disch_str = ""
            if isinstance(disch_dt, _datetime):
                disch_str = disch_dt.strftime("%d-%m-%Y")
            elif isinstance(disch_dt, _date):
                disch_str = disch_dt.strftime("%d-%m-%Y")
            elif isinstance(disch_dt, str) and disch_dt:
                disch_str = disch_dt[:10]

            guardian_val = p.get("guardian_name") or p.get("spouse_name") or p.get("father_name") or p.get("emergency_contact") or ""
            guardian_type_val = p.get("guardian_type") or ("W/o" if str(p.get("gender", "")).lower() == "female" and p.get("spouse_name") else "S/o")

            raw_comp = (adm.get("company_code") or p.get("company_code") or adm.get("insurance_company") or p.get("company_name") or "") if adm else (p.get("company_code") or p.get("company_name") or "")
            company_name_p = ""
            if raw_comp:
                try:
                    _, db_conn = get_hms_db()
                    ins_doc = db_conn["hospital_insuranceprovider"].find_one({
                        "$or": [{"company_code": str(raw_comp)}, {"company_name": str(raw_comp)}]
                    })
                    company_name_p = ins_doc.get("company_name") if ins_doc else str(raw_comp)
                except Exception:
                    company_name_p = str(raw_comp)

            patient_details = {
                "patient_name":   f"{p.get('firstName', '')} {p.get('lastName', '')}".strip(),
                "age":            p.get("age", ""),
                "gender":         p.get("gender", ""),
                "mobile":         p.get("mobilePhone", ""),
                "mobilePhone":    p.get("mobilePhone", ""),
                "phone":          p.get("mobilePhone", ""),
                "address":        full_address,
                "guardian":       f"{guardian_type_val} {guardian_val}".strip() if guardian_val and not str(guardian_val).startswith(("W/o", "S/o", "D/o", "C/o")) else guardian_val,
                "guardian_type":  guardian_type_val,
                "guardian_name":  guardian_val,
                "spouse_name":    p.get("spouse_name", ""),
                "father_name":    p.get("father_name", ""),
                "doctor":         doc_name or p.get("doctorName") or doc_id,
                "doctor_id":      doc_id,
                "department":     dept_name,
                "admission_date": adm_str,
                "discharge_date": disch_str,
                "room_no":        current_room,
                "company":        doc.get("company_name") or company_name_p or str(raw_comp),
                "company_code":   str(raw_comp),
            }

    created_by_val = doc.get("created_by")
    created_by_name = _resolve_employee_name(created_by_val) if created_by_val else ""
    created_by_designation = _resolve_employee_designation(created_by_val) if created_by_val else ""
    mgr = _resolve_insurance_manager()
    manager_name = mgr.get("name", "")
    manager_designation = mgr.get("designation", "GENERAL INSURANCE MANAGER")

    bd = doc.get("bill_date")
    if isinstance(bd, _datetime):
        bd_ist = _to_ist_dt(bd)
        bd_str = bd_ist.isoformat() if bd_ist is not None else bd.isoformat()
    elif isinstance(bd, _date):
        bd_str = bd.isoformat()
    else:
        bd_str = str(bd) if bd else None

    return {
        "id":                discharge_id,
        "discharge_id":      discharge_id,
        "status":            doc.get("status"),
        "estimate_number":   doc.get("estimate_number"),
        "bill_no":           (str(doc.get("bill_no")).replace("/", "") if doc.get("bill_no") else None),
        "uhid":              doc.get("uhid"),
        "ip_number":         doc.get("ip_number"),
        "billTypeNo":        str(doc.get("billTypeNo") or "DIS01"),
        "bill_type":         doc.get("bill_type") if doc.get("bill_type") is not None else 2,
        "bill_date":         bd_str,
        "items":             _resolve_items_doctor_names(_parse_items(doc.get("items"))),
        "total_amount":      _to_float(doc.get("total_amount")),
        "advance_amount":    _to_float(doc.get("advance_amount")),
        "sales_return":      _to_float(doc.get("sales_return")),
        "medicines_amount":  _to_float(doc.get("medicines_amount")),
        "pharmacy_medicines": doc.get("pharmacy_medicines") or [],
        "implant_amount":    _to_float(doc.get("implant_amount")),
        "taxable_amount":    _to_float(doc.get("taxable_amount")),
        "non_tax_amount":    _to_float(doc.get("non_tax_amount")),
        "gst_amount":        _to_float(doc.get("gst_amount")),
        "room_tax":          _to_float(doc.get("room_tax", 0)),
        "discount_percent":  _to_float(doc.get("discount_percent")),
        "discount_amount":   _to_float(doc.get("discount_amount")),
        "disc_reason":       doc.get("disc_reason") or "",
        "net_amount":        _to_float(doc.get("net_amount")),
        "remarks":           doc.get("remarks") or "",
        "next_visit_date":   _safe_isoformat(doc.get("next_visit_date")),
        "is_insurance_bill":     bool(doc.get("is_insurance_bill", False)),
        "claim_number":          doc.get("claim_number") or "",
        "id_card_number":        doc.get("id_card_number") or "",
        "insurance_bill_number": (str(doc.get("insurance_bill_number")).replace("/", "") if doc.get("insurance_bill_number") else ""),
        "company_name":          doc.get("company_name") or "",
        "payment_method":        doc.get("payment_method") or "Cash",
        "created_by":             created_by_val,
        "created_by_name":        created_by_name,
        "created_by_designation": created_by_designation,
        "manager_name":           manager_name,
        "manager_designation":    manager_designation,
        "created_date":      _safe_isoformat(doc.get("created_date")),
        "lastmodified_by":   doc.get("lastmodified_by"),
        "lastmodified_date": _safe_isoformat(doc.get("lastmodified_date")),
        "branch_code":       doc.get("branch_code"),
        "outlet_code":       doc.get("outlet_code"),
        "hospital_code":     doc.get("hospital_code"),
        "shiftno":           doc.get("shiftno", "") or "",
        "patient_details":   patient_details,
    }


def _obj_to_dict(obj):
    """Serialise a DischargeBilling instance to a JSON-safe dict."""
    if isinstance(obj, dict):
        return _format_raw_bill_doc(obj)

    discharge_id = obj.discharge_id

    patient_details = {}
    if obj.uhid:
        try:
            _, db = get_hms_db()
            p = db["hospital_patient"].find_one({"uhid": str(obj.uhid).strip()})
            if not p:
                p = Patient.objects.get(uhid=obj.uhid)
                p = {
                    "firstName": p.firstName, "lastName": p.lastName, "age": p.age,
                    "gender": p.gender, "mobilePhone": p.mobilePhone,
                    "permanent_address": p.permanent_address, "area": p.area,
                    "city": p.city, "state": p.state, "zipcode": p.zipcode,
                    "spouse_name": getattr(p, "spouse_name", ""),
                    "emergency_contact": getattr(p, "emergency_contact", ""),
                }

            addr_parts = [p.get("permanent_address"), p.get("area"), p.get("city"), p.get("state"), p.get("zipcode")]
            full_address = ", ".join([str(x).strip() for x in addr_parts if x and str(x).strip()])

            adm = None
            if obj.ip_number:
                try:
                    adm = db["hospital_admission"].find_one({"ipNumber": str(obj.ip_number).strip()})
                except Exception:
                    pass

            adm_str, current_room = _extract_adm_room_and_date(adm)

            doc_id = str(adm.get("admittingDoctor") or "") if adm else ""
            doc_name, dept_name = _resolve_doctor_and_department(doc_id)
            if not doc_name:
                doc_name = _resolve_employee_name(doc_id) if doc_id else ""
            if not dept_name and adm:
                dept_name = _resolve_department_name(adm.get("department") or adm.get("admittingDepartment") or "")

            disch_dt = adm.get("dischargeDateTime") or adm.get("discharge_date") if adm else None
            disch_str = ""
            if isinstance(disch_dt, _datetime):
                disch_str = disch_dt.strftime("%d-%m-%Y")
            elif isinstance(disch_dt, _date):
                disch_str = disch_dt.strftime("%d-%m-%Y")
            elif isinstance(disch_dt, str) and disch_dt:
                disch_str = disch_dt[:10]

            guardian_val = p.get("guardian_name") or p.get("spouse_name") or p.get("father_name") or p.get("emergency_contact") or ""
            guardian_type_val = p.get("guardian_type") or ("W/o" if str(p.get("gender", "")).lower() == "female" and p.get("spouse_name") else "S/o")

            raw_comp = (adm.get("company_code") or p.get("company_code") or adm.get("insurance_company") or p.get("company_name") or "") if adm else (p.get("company_code") or p.get("company_name") or "")
            company_name_p = ""
            if raw_comp:
                try:
                    _, db_conn = get_hms_db()
                    ins_doc = db_conn["hospital_insuranceprovider"].find_one({
                        "$or": [{"company_code": str(raw_comp)}, {"company_name": str(raw_comp)}]
                    })
                    company_name_p = ins_doc.get("company_name") if ins_doc else str(raw_comp)
                except Exception:
                    company_name_p = str(raw_comp)

            patient_details = {
                "patient_name":   f"{p.get('firstName', '')} {p.get('lastName', '')}".strip(),
                "age":            p.get("age", ""),
                "gender":         p.get("gender", ""),
                "mobile":         p.get("mobilePhone", ""),
                "mobilePhone":    p.get("mobilePhone", ""),
                "phone":          p.get("mobilePhone", ""),
                "address":        full_address,
                "guardian":       f"{guardian_type_val} {guardian_val}".strip() if guardian_val and not str(guardian_val).startswith(("W/o", "S/o", "D/o", "C/o")) else guardian_val,
                "guardian_type":  guardian_type_val,
                "guardian_name":  guardian_val,
                "spouse_name":    p.get("spouse_name", ""),
                "father_name":    p.get("father_name", ""),
                "doctor":         doc_name or p.get("doctorName") or doc_id,
                "doctor_id":      doc_id,
                "department":     dept_name,
                "admission_date": adm_str,
                "discharge_date": disch_str,
                "room_no":        current_room,
                "company":        getattr(obj, "company_name", None) or company_name_p or str(raw_comp),
                "company_code":   str(raw_comp),
            }
        except Exception:
            pass

    created_by_val = getattr(obj, "created_by", None)
    created_by_name = _resolve_employee_name(created_by_val) if created_by_val else ""
    created_by_designation = _resolve_employee_designation(created_by_val) if created_by_val else ""
    mgr = _resolve_insurance_manager()
    manager_name = mgr.get("name", "")
    manager_designation = mgr.get("designation", "GENERAL INSURANCE MANAGER")

    return {
        "id":                discharge_id,
        "discharge_id":      discharge_id,
        "status":            obj.status,
        "estimate_number":   obj.estimate_number,
        "bill_no":           obj.bill_no,
        "uhid":              obj.uhid,
        "ip_number":         obj.ip_number,
        "bill_date":         _safe_isoformat(_to_ist_dt(obj.bill_date) if isinstance(obj.bill_date, _datetime) else obj.bill_date),
        "items":             _resolve_items_doctor_names(_parse_items(obj.items)),
        "total_amount":      _to_float(obj.total_amount),
        "advance_amount":    _to_float(obj.advance_amount),
        "sales_return":      _to_float(obj.sales_return),
        "medicines_amount":  _to_float(obj.medicines_amount),
        "implant_amount":    _to_float(getattr(obj, "implant_amount", 0)),
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
        "is_insurance_bill":     bool(getattr(obj, "is_insurance_bill", False)),
        "claim_number":          getattr(obj, "claim_number", "") or "",
        "id_card_number":        getattr(obj, "id_card_number", "") or "",
        "insurance_bill_number": getattr(obj, "insurance_bill_number", "") or "",
        "company_name":          getattr(obj, "company_name", "") or "",
        "payment_method":        getattr(obj, "payment_method", "Cash") or "Cash",
        "billTypeNo":            getattr(obj, "billTypeNo", None) or "DIS01",
        "bill_type":             getattr(obj, "bill_type") if getattr(obj, "bill_type", None) is not None else 2,
        "created_by":             created_by_val,
        "created_by_name":        created_by_name,
        "created_by_designation": created_by_designation,
        "manager_name":           manager_name,
        "manager_designation":    manager_designation,
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
    items = _resolve_items_doctor_names(_parse_items(raw_items))

    obj.uhid             = s("uhid")
    obj.ip_number        = s("ip_number")
    obj.items            = items

    items_sum = sum(_to_float(it.get("amount", 0)) for it in items)
    meds_val  = flt("medicines_amount")
    imp_val   = flt("implant_amount") if data.get("implant_amount") is not None else flt("implants")
    tax_val   = flt("taxable_amount") + flt("gst_amount") + flt("room_tax")
    gross_calculated = round(items_sum + meds_val + imp_val + tax_val, 2)

    passed_total = flt("total_amount")
    if gross_calculated > passed_total and (meds_val > 0 or imp_val > 0):
        obj.total_amount = gross_calculated
    else:
        obj.total_amount = passed_total if passed_total > 0 else gross_calculated

    obj.advance_amount   = flt("advance_amount")
    obj.sales_return     = flt("sales_return")
    obj.medicines_amount = meds_val
    obj.implant_amount   = imp_val
    obj.taxable_amount   = flt("taxable_amount")
    obj.non_tax_amount   = flt("non_tax_amount") or obj.total_amount
    obj.gst_amount       = flt("gst_amount")
    obj.room_tax         = flt("room_tax")
    obj.discount_percent = flt("discount_percent")
    obj.discount_amount  = flt("discount_amount")
    obj.disc_reason      = s("disc_reason")

    expected_net = round(obj.total_amount - obj.discount_amount - obj.advance_amount - obj.sales_return, 2)
    passed_net   = flt("net_amount")
    obj.net_amount = passed_net if abs(passed_net - expected_net) < 0.01 else expected_net
    obj.remarks          = s("remarks")
    obj.shiftno          = s("shiftno")
    obj.payment_method   = s("payment_method", "Cash")

    raw_btn = data.get("billTypeNo")
    if raw_btn is not None and str(raw_btn).strip() != "":
        obj.billTypeNo = str(raw_btn).strip()
    elif not existing or not getattr(existing, "billTypeNo", None):
        obj.billTypeNo = "DIS01"

    raw_bt = data.get("bill_type")
    if raw_bt is not None and str(raw_bt).strip() != "":
        try:
            obj.bill_type = int(raw_bt)
        except (ValueError, TypeError):
            obj.bill_type = 2
    elif not existing or getattr(existing, "bill_type", None) is None:
        obj.bill_type = 2

    # ── Insurance Fields ─────────────────────────────────────────────────────
    if "is_insurance_bill" in data:
        obj.is_insurance_bill = bool(data.get("is_insurance_bill"))
    elif existing and hasattr(existing, "is_insurance_bill"):
        obj.is_insurance_bill = existing.is_insurance_bill

    if "claim_number" in data and s("claim_number"):
        obj.claim_number = s("claim_number")
    elif existing and getattr(existing, "claim_number", None):
        obj.claim_number = existing.claim_number

    if "id_card_number" in data and s("id_card_number"):
        obj.id_card_number = s("id_card_number")
    elif existing and getattr(existing, "id_card_number", None):
        obj.id_card_number = existing.id_card_number

    if getattr(obj, "is_insurance_bill", False):
        if not getattr(obj, "claim_number", None) or not getattr(obj, "id_card_number", None):
            pd_info = data.get("patient_details") or {}
            uhid_val = getattr(obj, "uhid", "") or (pd_info.get("uhid") if isinstance(pd_info, dict) else "")
            pname_val = pd_info.get("patient_name", "") if isinstance(pd_info, dict) else ""
            auto_ins = _resolve_insurance_member_details(uhid=uhid_val, patient_name=pname_val)
            if not getattr(obj, "claim_number", None) and auto_ins.get("claim_number"):
                obj.claim_number = auto_ins["claim_number"]
            if not getattr(obj, "id_card_number", None) and auto_ins.get("id_card_number"):
                obj.id_card_number = auto_ins["id_card_number"]

    if "company_name" in data and s("company_name"):
        obj.company_name = s("company_name")
    elif existing and getattr(existing, "company_name", None):
        obj.company_name = existing.company_name

    if "insurance_bill_number" in data and s("insurance_bill_number"):
        obj.insurance_bill_number = s("insurance_bill_number")
    elif existing and getattr(existing, "insurance_bill_number", None):
        obj.insurance_bill_number = existing.insurance_bill_number
    elif getattr(obj, "is_insurance_bill", False):
        if not getattr(obj, "insurance_bill_number", None):
            ins_name = getattr(obj, "company_name", None) or (data.get("patient_details") or {}).get("company") or (data.get("patient_details") or {}).get("company_code") or "INS"
            obj.insurance_bill_number = generate_insurance_bill_number(ins_name)

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

    outlet_code = request.data.get('auth-outlet-code') if (request and hasattr(request, "data")) else data.get('auth-outlet-code')

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
        # ── 2. Update Pharmacy Billing ────────────────────────────────────────
        # Update billing_status: Pending / Billed --> Completed
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
                {"is_deleted": {"$ne": True}},
                {
                    "$or": [
                        {"billing_status": "Pending"},
                        {"billing_status": "Billed"},
                        {"billing_status": {"$regex": "^pending$", "$options": "i"}},
                        {"billing_status": {"$regex": "^billed$", "$options": "i"}},
                    ]
                },
                {
                    "$or": [
                        {"payment_mode": {"$regex": "^credit$", "$options": "i"}},
                        {"paymentMethod": {"$regex": "^credit$", "$options": "i"}},
                        {"payment_details.payment_mode": {"$regex": "^credit$", "$options": "i"}},
                        {"is_ward_request": True},
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
        # Criteria: ipNumber/uhid, paymentMethod: "Credit", paymentStatus: "Pending" or "Billed"
        # Update: paymentStatus -> "Completed"
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
                {"is_active": {"$ne": False}},
                {
                    "$or": [
                        {"paymentStatus": {"$in": ["Pending", "Billed", "pending", "billed"]}},
                        {"payment_status": {"$in": ["Pending", "Billed", "pending", "billed"]}},
                        {"paymentStatus": {"$regex": "^(pending|billed)$", "$options": "i"}},
                        {"payment_status": {"$regex": "^(pending|billed)$", "$options": "i"}},
                    ]
                }
            ]
        }
        db["hospital_investbilling"].update_many(
            invest_match,
            {"$set": {
                "paymentStatus": "Completed",
                "payment_status": "Completed",
                "lastmodified_by": user_str,
                "lastmodified_date": now_dt,
            }}
        )

        # ── 4. Update Implant Request ─────────────────────────────────────────
        # Criteria: inpatient_number/uhid, status: "Pending", is_active: True
        # Update: status -> "Completed"
        implant_ip_filter = []
        if ip_number:
            implant_ip_filter.extend([
                {"inpatient_number": str(ip_number)},
                {"ipNumber": str(ip_number)},
                {"ip_number": str(ip_number)},
            ])
        if uhid:
            implant_ip_filter.append({"uhid": str(uhid)})

        implant_match = {
            "$and": [
                {"$or": implant_ip_filter},
                {"is_active": {"$ne": False}},
                {
                    "$or": [
                        {"status": "Pending"},
                        {"status": {"$regex": "^pending$", "$options": "i"}},
                    ]
                }
            ]
        }
        db["hospital_implant_request"].update_many(
            implant_match,
            {"$set": {
                "status": "Completed",
                "lastmodified_by": user_str,
                "lastmodified_date": now_dt,
            }}
        )

        # ── 5. Update Consultation Billing (hospital_billing) ─────────────────
        # Criteria: uhid, payment_status: "Pending"
        # Update: payment_status -> "Completed"
        if not uhid and ip_number:
            try:
                temp_adm = db["hospital_admission"].find_one({"ipNumber": str(ip_number)})
                if temp_adm and temp_adm.get("uhid"):
                    uhid = temp_adm.get("uhid")
            except Exception:
                pass

        if uhid:
            uhid_str = str(uhid).strip()
            db["hospital_billing"].update_many(
                {
                    "uhid": uhid_str,
                    "payment_status": {"$in": ["Pending", "pending", "PENDING"]},
                },
                {"$set": {
                    "payment_status": "Completed",
                    "lastmodified_by": user_str,
                    "lastmodified_date": now_dt,
                }}
            )
            try:
                Billing.objects.filter(
                    patient__uhid=uhid_str,
                    payment_status__iexact="pending"
                ).update(
                    payment_status="Completed",
                    lastmodified_by=user_str,
                    lastmodified_date=now_dt
                )
            except Exception:
                pass

        # Also update by bill_number if discharge items reference specific consultation bill numbers
        if ip_number:
            try:
                disch_doc = db["hospital_dischargebilling"].find_one({
                    "ip_number": str(ip_number),
                    "status": "Billed",
                    "is_cancelled": {"$ne": True}
                }, sort=[("bill_date", -1)])
                if disch_doc:
                    for itm in disch_doc.get("items") or []:
                        if isinstance(itm, dict):
                            if itm.get("source") == "hospital_billing" or itm.get("itemName") == "Consultation OPD":
                                b_no = itm.get("invest_bill_no")
                                if b_no:
                                    db["hospital_billing"].update_one(
                                        {"bill_number": str(b_no), "payment_status": {"$in": ["Pending", "pending", "PENDING"]}},
                                        {"$set": {
                                            "payment_status": "Completed",
                                            "lastmodified_by": user_str,
                                            "lastmodified_date": now_dt,
                                        }}
                                    )
            except Exception:
                pass

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

# ─────────────────────────────────────────────────────────────────────────────
# Search Discharge Patient
# GET /search-discharge-patient/?uhid=… OR ?ipNumber=…
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def search_discharge_patient(request):
    ensure_discharge_indexes()
    client, db = get_hms_db()

    uhid      = request.GET.get("uhid",     "").strip()
    ip_number = request.GET.get("ipNumber", "").strip()

    if not uhid and not ip_number:
        return Response(
            {"error": "Provide uhid or ipNumber"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    for_print = request.GET.get("for_print") in ["true", "1", "True"]
    patient_doc   = None
    admission_doc = None

    try:
        if uhid:
            patient_doc = db["hospital_patient"].find_one({"uhid": uhid})
            if not patient_doc:
                return Response({"error": "Patient not found"}, status=status.HTTP_404_NOT_FOUND)

            admission_doc = db["hospital_admission"].find_one(
                {"uhid": uhid, "is_admitted": True, "is_cancelled": {"$ne": True}},
                sort=[("admissionDateTime", -1)]
            )
            if not admission_doc:
                admission_doc = db["hospital_admission"].find_one(
                    {"uhid": uhid},
                    sort=[("admissionDateTime", -1)]
                )
            if not for_print and (not admission_doc or not admission_doc.get("is_admitted") or admission_doc.get("is_cancelled")):
                return Response({"error": "Not Admitted"}, status=status.HTTP_404_NOT_FOUND)
            elif for_print and (not admission_doc or admission_doc.get("is_cancelled")):
                return Response({"error": "Admission record not found"}, status=status.HTTP_404_NOT_FOUND)

        else:
            admission_doc = db["hospital_admission"].find_one({"ipNumber": ip_number})
            if not for_print and (not admission_doc or not admission_doc.get("is_admitted") or admission_doc.get("is_cancelled")):
                return Response({"error": "Not Admitted"}, status=status.HTTP_404_NOT_FOUND)
            elif for_print and (not admission_doc or admission_doc.get("is_cancelled")):
                return Response({"error": "Admission record not found"}, status=status.HTTP_404_NOT_FOUND)

            p_uhid = admission_doc.get("uhid")
            patient_doc = db["hospital_patient"].find_one({"uhid": p_uhid}) if p_uhid else None
            if not patient_doc:
                return Response({"error": "Patient not found"}, status=status.HTTP_404_NOT_FOUND)

    except Exception as e:
        return Response(
            {"error": f"Lookup failed: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    ward_status = str(admission_doc.get("ward_status") or "").strip()
    if not for_print:
        # Verify patient discharge state: if already discharged, disallow billing again
        adm_status = str(admission_doc.get("status") or "").strip()
        is_discharged = bool(admission_doc.get("is_discharged", False))

        if ward_status.lower() in ["discharged", "already discharged"] or adm_status.lower() == "discharged" or is_discharged is True:
            return Response(
                {"error": "Already Discharged", "message": "Patient is already discharged"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check if an active Billed DischargeBilling record exists for this IP number (indexed fast query)
        ip_num_str = str(admission_doc.get("ipNumber") or "").strip()
        existing_billed = db["hospital_dischargebilling"].find_one({
            "ip_number": ip_num_str,
            "status": "Billed",
            "is_cancelled": {"$ne": True}
        })
        if existing_billed:
            return Response(
                {"error": "Already Discharged", "message": "Discharge bill already generated for this admission"},
                status=status.HTTP_400_BAD_REQUEST,
            )

    adm_dt = admission_doc.get("admissionDateTime")
    adm_ist = _to_ist_dt(adm_dt)
    if adm_ist:
        adm_str = adm_ist.strftime("%d-%m-%Y %I:%M %p")
    elif isinstance(adm_dt, _date):
        adm_str = adm_dt.strftime("%d-%m-%Y")
    elif isinstance(adm_dt, str) and adm_dt:
        adm_str = adm_dt
    else:
        adm_str = ""

    # Resolve latest room / bed and room category
    room_details = parse_json_field(admission_doc.get("room_details", []))
    current_room = ""
    current_bed = ""
    current_room_cat = "GENERAL WARD"
    if room_details and isinstance(room_details, list):
        last_room = room_details[-1]
        if isinstance(last_room, dict):
            current_room = str(last_room.get("roomNo") or last_room.get("roomNumber") or last_room.get("room_number") or "")
            current_bed  = str(last_room.get("bedNo") or last_room.get("bedNumber") or last_room.get("bed_number") or "")

    shiftings_details = parse_json_field(admission_doc.get("roomShitingDetails", []))
    if shiftings_details and isinstance(shiftings_details, list):
        active_shifts = [s for s in shiftings_details if isinstance(s, dict) and s.get("is_roomActive")]
        if active_shifts:
            last_shift = active_shifts[-1]
            current_room = str(last_shift.get("newRoomNo") or current_room)
            current_bed  = str(last_shift.get("newBedNo") or current_bed)

    total_days = 0
    if adm_ist:
        today = _datetime.now(_IST_TZ).date()
        total_days = max(1, (today - adm_ist.date()).days)
    elif adm_dt:
        try:
            today = _datetime.now(_IST_TZ).date()
            adm_date = adm_dt if isinstance(adm_dt, _date) else _parse_dt(adm_dt).date()
            total_days = max(1, (today - adm_date).days)
        except Exception:
            total_days = 1
    else:
        total_days = 1

    # Advance Payments calculation
    total_advance = 0.0
    adv_payments = parse_json_field(admission_doc.get("advance_payments", []))
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

    addr_parts = [patient_doc.get("permanent_address", ""), patient_doc.get("area", ""), patient_doc.get("city", ""), patient_doc.get("state", ""), patient_doc.get("zipcode", "")]
    full_address = ", ".join([str(x).strip() for x in addr_parts if x and str(x).strip()])

    doc_id = str(admission_doc.get("admittingDoctor") or "")
    doc_name, dept_name = _resolve_doctor_and_department(doc_id)
    if not doc_name:
        doc_name = _resolve_employee_name(doc_id) if doc_id else ""
    if not dept_name:
        dept_name = _resolve_department_name(admission_doc.get("department") or admission_doc.get("admittingDepartment") or "")

    disch_dt = admission_doc.get("dischargeDateTime") or admission_doc.get("discharge_date")
    disch_str = ""
    if isinstance(disch_dt, _datetime):
        disch_str = disch_dt.strftime("%d-%m-%Y")
    elif isinstance(disch_dt, _date):
        disch_str = disch_dt.strftime("%d-%m-%Y")
    elif isinstance(disch_dt, str) and disch_dt:
        disch_str = disch_dt[:10]

    guardian_val = patient_doc.get("guardian_name") or patient_doc.get("spouse_name") or patient_doc.get("father_name") or patient_doc.get("emergency_contact") or ""
    guardian_type_val = patient_doc.get("guardian_type") or ("W/o" if str(patient_doc.get("gender", "")).lower() == "female" and patient_doc.get("spouse_name") else "S/o")

    # Resolve full insurance company name
    raw_company = admission_doc.get("company_code") or patient_doc.get("company_code") or admission_doc.get("insurance_company") or patient_doc.get("company_name") or ""
    company_name = ""
    if raw_company:
        try:
            ins_doc = db["hospital_insuranceprovider"].find_one({
                "$or": [
                    {"company_code": str(raw_company)},
                    {"company_name": str(raw_company)},
                ]
            })
            if ins_doc and ins_doc.get("company_name"):
                company_name = ins_doc.get("company_name")
            else:
                company_name = str(raw_company)
        except Exception:
            company_name = str(raw_company)

    patient_info = {
        "uhid":                 patient_doc.get("uhid"),
        "patient_name":         f"{patient_doc.get('firstName', '')} {patient_doc.get('lastName', '')}".strip(),
        "age":                  patient_doc.get("age"),
        "gender":               patient_doc.get("gender"),
        "mobile":               patient_doc.get("mobilePhone"),
        "ip_number":            admission_doc.get("ipNumber"),
        "ipNumber":             admission_doc.get("ipNumber"),
        "admission_date":       adm_str,
        "discharge_date":       disch_str,
        "patient_type":         admission_doc.get("customer_type") or patient_doc.get("customer_type") or admission_doc.get("patient_type", ""),
        "customer_type":        admission_doc.get("customer_type") or patient_doc.get("customer_type") or "",
        "insurance_company":    admission_doc.get("insurance_company") or "",
        "company":              company_name,
        "company_code":         raw_company,
        "room_no":              current_room,
        "bed_no":               current_bed,
        "room_category":        current_room_cat,
        "total_days":           total_days,
        "advance_amount":       total_advance,
        "doctor":               doc_name or patient_doc.get("doctorName") or doc_id,
        "doctor_id":            doc_id,
        "department":           dept_name,
        "address":              full_address,
        "guardian":             f"{guardian_type_val} {guardian_val}".strip() if guardian_val and not str(guardian_val).startswith(("W/o", "S/o", "D/o", "C/o")) else guardian_val,
        "guardian_type":        guardian_type_val,
        "guardian_name":        guardian_val,
        "spouse_name":          patient_doc.get("spouse_name") or "",
        "father_name":          patient_doc.get("father_name") or "",
        "ward_status":          ward_status,
        "is_ready_for_billing": ward_status == "Sent for billing",
    }

    # Resolve Claim No (referral_number) and ID Card No (card_no) from hospital_insurancemember
    ins_info = _resolve_insurance_member_details(
        uhid=patient_doc.get("uhid") or uhid,
        patient_name=f"{patient_doc.get('firstName', '')} {patient_doc.get('lastName', '')}".strip()
    )
    patient_info["claim_number"]    = ins_info["claim_number"]
    patient_info["id_card_number"]  = ins_info["id_card_number"]
    patient_info["card_no"]         = ins_info["card_no"]
    patient_info["referral_number"] = ins_info["referral_number"]
    patient_info["member_number"]   = ins_info["member_number"]

    effective_ip   = ip_number or admission_doc.get("ipNumber")
    effective_uhid = patient_doc.get("uhid") or uhid

    invest_items = []

    try:
        # ── 0. Room Charges (Services & Room Kits) ───────────────────────────
        try:
            raw_movements = []
            now_dt = _datetime.now(_IST_TZ)
            adm_start_dt = _to_ist_dt(adm_dt) or now_dt

            for r in room_details:
                if isinstance(r, dict):
                    r_no = str(r.get("roomNo") or r.get("roomNumber") or r.get("room_number") or "").strip()
                    b_no = str(r.get("bedNo") or r.get("bedNumber") or r.get("bed_number") or "").strip()
                    s_dt = _to_ist_dt(r.get("startDateTime")) or adm_start_dt
                    e_dt = _to_ist_dt(r.get("endDateTime"))
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
                    s_dt = _to_ist_dt(s.get("shiftingDateTime") or s.get("startDateTime")) or adm_start_dt
                    e_dt = _to_ist_dt(s.get("endDateTime"))
                    if r_no:
                        raw_movements.append({
                            "room_no": r_no,
                            "bed_no": b_no,
                            "start_dt": s_dt,
                            "end_dt": e_dt,
                        })

            raw_movements.sort(key=lambda x: x["start_dt"] or adm_start_dt)

            room_stays = []
            for mov in raw_movements:
                if room_stays and room_stays[-1]["room_no"] == mov["room_no"]:
                    room_stays[-1]["end_dt"] = mov["end_dt"]
                    room_stays[-1]["bed_no"] = mov["bed_no"]
                else:
                    room_stays.append(dict(mov))

            accumulated_days = 0

            if not room_stays and current_room:
                room_stays.append({
                    "room_no": current_room,
                    "bed_no": current_bed,
                    "start_dt": adm_start_dt,
                    "end_dt": now_dt,
                })

            # Batch pre-fetch all room documents in ONE query!
            room_numbers_set = list({s["room_no"] for s in room_stays if s.get("room_no")})
            room_docs_cursor = list(db["hospital_room"].find({"room_number": {"$in": room_numbers_set}})) if room_numbers_set else []
            room_doc_map = {str(rd.get("room_number")).strip(): rd for rd in room_docs_cursor if rd.get("room_number")}
            room_doc_lower_map = {k.lower(): v for k, v in room_doc_map.items()}

            for stay in room_stays:
                r_no = stay["room_no"]
                s_dt = stay["start_dt"] or adm_start_dt
                e_dt = stay["end_dt"] or now_dt

                days_diff = (e_dt.date() - s_dt.date()).days
                stay_days = max(1, days_diff)
                accumulated_days += stay_days

                room_doc = room_doc_map.get(str(r_no).strip()) or room_doc_lower_map.get(str(r_no).strip().lower())

                if room_doc:
                    room_cat = room_doc.get("room_category", "")
                    if room_cat:
                        patient_info["room_category"] = room_cat

                    # A. Room Services
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
                                "doctor":         "",
                                "payment_status": "Pending",
                                "package_name":   "",
                                "source":         "hospital_room_services",
                            })

                    # B. Room Kits
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
                                "doctor":         "",
                                "payment_status": "Pending",
                                "package_name":   "",
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
        inv_q = get_query(
            ["ipNumber", "inpatient_number", "ip_number"],
            {"paymentMethod": "Credit", "paymentStatus": "Pending", "is_active": {"$ne": False}}
        )
        if inv_q:
            is_insurance_patient = str(patient_info.get("patient_type") or "").strip().lower() == "insurance"
            nabh_tid_map, nabh_code_map = {}, {}
            if is_insurance_patient:
                try:
                    nabh_records = list(db["hospital_lab_nabh_rate"].find(
                        {},
                        {"_id": 0, "test_id": 1, "nabh_code": 1, "nabh_rate": 1, "non_nabh_rate": 1, "test_name": 1, "sl_no": 1}
                    ))
                    for n_rec in nabh_records:
                        tid = n_rec.get("test_id")
                        if tid is not None and str(tid).strip() != "":
                            t_str = str(tid).strip()
                            nabh_tid_map[t_str] = n_rec
                            try:
                                nabh_tid_map[str(int(t_str))] = n_rec
                            except Exception:
                                pass
                        c = n_rec.get("nabh_code")
                        if c and str(c).strip():
                            nabh_code_map[str(c).strip().upper()] = n_rec
                except Exception as e:
                    print(f"Error prefetching hospital_lab_nabh_rate: {e}")

            for bill in db["hospital_investbilling"].find(inv_q):
                bill_no   = bill.get("investBillNo", "")
                doc_raw   = str(bill.get("doctor") or "").strip()
                doctor    = _resolve_employee_name(doc_raw) if doc_raw else ""
                raw_items = bill.get("item", [])
                if isinstance(raw_items, str):
                    try:
                        raw_items = _json.loads(raw_items)
                    except Exception:
                        raw_items = []
                for it in (raw_items if isinstance(raw_items, list) else []):
                    matched_n = None
                    item_btn  = str(it.get("billTypeNo", "") or bill.get("billTypeNo", "") or "LAB01").strip().upper()
                    item_name = it.get("itemName", "")
                    test_id   = it.get("test_id") or it.get("item_id")
                    nabh_code = str(it.get("nabh_code", "") or "").strip()
                    price     = _to_float(it.get("price", 0) or it.get("rate", 0))

                    if is_insurance_patient and (item_btn.startswith("LAB") or str(bill.get("bill_type")) == "16" or test_id is not None):
                        matched_n = None
                        if test_id is not None and str(test_id).strip() != "":
                            t_s = str(test_id).strip()
                            matched_n = nabh_tid_map.get(t_s)
                            if not matched_n:
                                try:
                                    matched_n = nabh_tid_map.get(str(int(t_s)))
                                except Exception:
                                    pass
                        if not matched_n and nabh_code:
                            matched_n = nabh_code_map.get(nabh_code.upper())

                        if matched_n:
                            if matched_n.get("test_name"):
                                item_name = matched_n.get("test_name")
                            if matched_n.get("nabh_code"):
                                nabh_code = str(matched_n.get("nabh_code")).strip()
                            if item_btn == "LAB02" and matched_n.get("nabh_rate") is not None:
                                price = _to_float(matched_n.get("nabh_rate"))
                            elif item_btn == "LAB03" and matched_n.get("non_nabh_rate") is not None:
                                price = _to_float(matched_n.get("non_nabh_rate"))

                    qty   = int(it.get("quantity", 1) or 1)
                    disc  = _to_float(it.get("discount", 0))
                    amt   = max(0.0, price * qty - disc)
                    invest_items.append({
                        "invest_bill_no": bill_no,
                        "bill_object_id": str(bill.get("_id")),
                        "itemName":       item_name,
                        "price":          price,
                        "rate":           str(price),
                        "quantity":       qty,
                        "discount":       disc,
                        "amount":         amt,
                        "billTypeNo":     item_btn,
                        "bill_type":      bill.get("bill_type", 16),
                        "test_id":        test_id,
                        "nabh_code":      nabh_code,
                        "nabh_rate":      _to_float(matched_n.get("nabh_rate")) if matched_n and matched_n.get("nabh_rate") is not None else None,
                        "non_nabh_rate":  _to_float(matched_n.get("non_nabh_rate")) if matched_n and matched_n.get("non_nabh_rate") is not None else None,
                        "doctor":         doctor,
                        "payment_status": bill.get("paymentStatus", ""),
                        "package_name":   it.get("packageName", "") or bill.get("packageName", ""),
                        "source":         "hospital_investbilling",
                    })

        # ── 2. hospital_patientdietorder ──────────────────────────────────────
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
                    "doctor":         _resolve_employee_name(str(doc.get("ordered_by") or "").strip()) if doc.get("ordered_by") else "",
                    "payment_status": doc.get("status", ""),
                    "package_name":   item_label,
                    "source":         "hospital_patientdietorder",
                })

        # ── 3. hospital_laundrywardrequest ────────────────────────────────────
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
                    "doctor":         _resolve_employee_name(str(doc.get("requested_by") or "").strip()) if doc.get("requested_by") else "",
                    "payment_status": doc.get("status", ""),
                    "package_name":   "",
                    "source":         "hospital_laundrywardrequest",
                })

        # ── 4. hospital_pharmacybilling ────────────────────────────────────────
        pharm_q = get_query(
            ["inpatient_number", "ipNumber", "ip_number"],
            {"is_deleted": {"$ne": True}}
        )
        total_pharm_amt = 0.0
        pharm_docs = []
        pharmacy_medicines = []
        if pharm_q:
            pharm_docs = list(db["hospital_pharmacybilling"].find(pharm_q, {
                "netAmount": 1, "net_amount": 1, "totalAmount": 1, "total_amount": 1,
                "medicine_particulars": 1, "pending_returns": 1, "bill_no": 1, "Bill_id": 1
            }))
            # Gather item names if missing
            missing_ids = set()
            for doc in pharm_docs:
                for med in (doc.get("medicine_particulars") or []):
                    if isinstance(med, dict) and not med.get("item_name") and med.get("item_id"):
                        try:
                            missing_ids.add(int(med["item_id"]))
                        except Exception:
                            pass
            name_cache = {}
            if missing_ids:
                try:
                    for pi in db["hospital_pharmacyitem"].find({"item_id": {"$in": list(missing_ids)}}, {"item_id": 1, "item_name": 1, "name": 1}):
                        name_cache[str(pi.get("item_id"))] = str(pi.get("item_name") or pi.get("name") or "")
                except Exception:
                    pass

            for doc in pharm_docs:
                tot_amt = _to_float(
                    doc.get("netAmount") or doc.get("net_amount") or doc.get("totalAmount") or doc.get("total_amount") or 0
                )
                bill_no = str(doc.get("bill_no") or "")
                meds = doc.get("medicine_particulars", [])
                calc_tot = 0.0
                if isinstance(meds, list) and len(meds) > 0:
                    for med in meds:
                        if isinstance(med, dict):
                            qty = float(med.get("qty") or med.get("quantity") or 1)
                            rate = _to_float(med.get("price") or med.get("rate") or med.get("mrp") or 0)
                            d_val = _to_float(med.get("discount") or 0)
                            amt = _to_float(med.get("amount") or med.get("calculated_price")) or max(0.0, rate * qty - d_val)
                            calc_tot += amt
                            iid = str(med.get("item_id") or "")
                            iname = str(med.get("item_name") or name_cache.get(iid) or f"Medicine {iid}").strip()
                            batch = str(med.get("batch_number") or "").strip()
                            pharmacy_medicines.append({
                                "item_id": iid,
                                "itemName": iname,
                                "name": iname,
                                "item_name": iname,
                                "batch_number": batch,
                                "quantity": qty,
                                "rate": rate,
                                "price": rate,
                                "discount": d_val,
                                "amount": amt,
                                "bill_no": bill_no,
                                "category": "MEDICINE / PHARMACY CHARGES",
                                "source": "pharmacy",
                                "item_description": f"Batch: {batch}" if batch else "",
                            })
                if tot_amt == 0:
                    tot_amt = calc_tot
                total_pharm_amt += tot_amt

        patient_info["medicines_amount"] = total_pharm_amt
        patient_info["pharmacy_medicines"] = pharmacy_medicines

        # ── 5. Sales Returns & Ward Returns ──────────────────────────────────
        total_sales_return = 0.0
        seen_return_bills = set()

        # 5a. hospital_wardreturndetails (Approved ward returns)
        wr_q = get_query(
            ["inpatient_number", "ipNumber", "ip_number"],
            {"status": {"$ne": "Rejected"}}
        )
        if wr_q:
            for wr_doc in db["hospital_wardreturndetails"].find(wr_q):
                w_no = str(wr_doc.get("ward_return_bill_no") or "").strip()
                if w_no:
                    seen_return_bills.add(w_no)
                r_amt = _to_float(wr_doc.get("return_amount") or 0)
                if r_amt == 0:
                    for it in wr_doc.get("medicine_particulars") or []:
                        if isinstance(it, dict):
                            r_amt += _to_float(
                                it.get("return_amount") or it.get("amount") or
                                (_to_float(it.get("return_qty") or 0) * _to_float(it.get("price") or it.get("mrp") or 0))
                            )
                total_sales_return += r_amt

        # 5b. hospital_pharmacybilling pending_returns
        if pharm_docs:
            for doc in pharm_docs:
                meds = doc.get("medicine_particulars") or []
                price_map = {}
                for m in meds:
                    if isinstance(m, dict):
                        iid = str(m.get("item_id"))
                        p = _to_float(m.get("price") or m.get("rate") or m.get("mrp") or 0)
                        price_map[iid] = p
                        batch = str(m.get("batch_number") or "").strip()
                        if batch:
                            price_map[f"{iid}_{batch}"] = p

                pending_returns = doc.get("pending_returns") or []
                for pr in pending_returns:
                    if not isinstance(pr, dict):
                        continue
                    if str(pr.get("status") or "").strip().lower() == "rejected":
                        continue
                    ret_bill_no = str(pr.get("return_bill_no") or "").strip()
                    if ret_bill_no and ret_bill_no in seen_return_bills:
                        continue
                    
                    pr_amt = 0.0
                    for it in pr.get("items") or []:
                        if isinstance(it, dict):
                            qty = _to_float(it.get("return_qty") or it.get("quantity") or 0)
                            iid = str(it.get("item_id"))
                            batch = str(it.get("batch_number") or "").strip()
                            unit_p = _to_float(it.get("price") or it.get("rate") or it.get("mrp") or 0)
                            if unit_p == 0:
                                unit_p = price_map.get(f"{iid}_{batch}", price_map.get(iid, 0.0))
                            item_amt = _to_float(it.get("return_amount") or it.get("amount") or (qty * unit_p))
                            pr_amt += item_amt
                    
                    total_sales_return += pr_amt
                    if ret_bill_no:
                        seen_return_bills.add(ret_bill_no)

        # 5c. hospital_salesreturn (Direct sales returns)
        sr_q = get_query(
            ["inpatient_number", "ipNumber", "ip_number"],
            {"is_deleted": {"$ne": True}}
        )
        if sr_q:
            for doc in db["hospital_salesreturn"].find(sr_q, {
                "return_amount": 1, "refund_amount": 1, "net_amount": 1, "total_amount": 1
            }):
                sr_amt = _to_float(
                    doc.get("return_amount") or doc.get("refund_amount") or doc.get("net_amount") or doc.get("total_amount") or 0
                )
                total_sales_return += sr_amt

        patient_info["sales_return"] = round(total_sales_return, 2)

        # ── 6. hospital_surgeryschedule ────────────────────────────────────────
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
                    "doctor":                   _resolve_employee_name(str(doc.get("surgeon_id") or "").strip()) if doc.get("surgeon_id") else "",
                    "payment_status":           doc.get("status", ""),
                    "package_name":             doc.get("surgery_type", ""),
                    "source":                   "hospital_surgeryschedule",
                })

        # ── 7. hospital_implant_request ───────────────────────────────────────
        implant_q = get_query(
            ["inpatient_number", "ipNumber", "ip_number"],
            {"status": "Pending", "is_active": {"$ne": False}}
        )
        total_implant_amt = 0.0
        if implant_q:
            for imp_doc in db["hospital_implant_request"].find(implant_q):
                raw_imp_items = imp_doc.get("items", [])
                if isinstance(raw_imp_items, str):
                    try:
                        raw_imp_items = _json.loads(raw_imp_items)
                    except Exception:
                        raw_imp_items = []
                for imp_item in (raw_imp_items if isinstance(raw_imp_items, list) else []):
                    if not isinstance(imp_item, dict):
                        continue
                    item_id_val = imp_item.get("item_id")
                    qty = int(imp_item.get("quantity") or imp_item.get("qty") or 1)

                    v_stock = None
                    try:
                        if item_id_val is not None:
                            v_stock = db["hospital_velavan_stock"].find_one(
                                {"item_id": int(item_id_val)},
                                sort=[("created_date", -1)]
                            )
                    except Exception:
                        pass
                    if not v_stock and item_id_val is not None:
                        v_stock = db["hospital_velavan_stock"].find_one({"item_id": str(item_id_val)})

                    rate = 0.0
                    if v_stock:
                        rate = _to_float(v_stock.get("unitSellingCost") or v_stock.get("mrp") or v_stock.get("sellingCost") or 0)

                    total_implant_amt += (rate * qty)

        patient_info["implant_amount"] = round(total_implant_amt, 2)

        # ── 8. hospital_billing (Consultation OPD) ───────────────────────────
        if effective_uhid:
            try:
                c_conditions = [{"uhid": str(effective_uhid)}]
                p_id = patient_doc.get("id") or patient_doc.get("patient_id") if patient_doc else None
                if p_id:
                    try:
                        c_conditions.append({"patient_id": int(p_id)})
                    except Exception:
                        pass
                c_query = {
                    "$or": c_conditions,
                    "payment_status": {"$in": ["Pending", "pending", "PENDING"]},
                }
                for c_doc in db["hospital_billing"].find(c_query):
                    c_amt = _to_float(c_doc.get("total_fees") or c_doc.get("consulting_fee") or 0)
                    doc_id_val = str(c_doc.get("doctor_id") or "").strip()
                    c_doctor_name = ""
                    if doc_id_val and doc_id_val.lower() not in ("none", "null", ""):
                        c_doctor_name, _ = _resolve_doctor_and_department(doc_id_val)
                        if not c_doctor_name:
                            c_doctor_name = _resolve_employee_name(doc_id_val)

                    invest_items.append({
                        "invest_bill_no": str(c_doc.get("bill_number") or c_doc.get("id") or c_doc.get("_id")),
                        "bill_object_id": str(c_doc.get("_id")),
                        "itemName":       "Consultation OPD",
                        "price":          c_amt,
                        "rate":           str(c_amt),
                        "quantity":       1,
                        "discount":       0,
                        "amount":         c_amt,
                        "billTypeNo":     str(c_doc.get("billTypeNo") or "REG01"),
                        "bill_type":      c_doc.get("bill_type", 5) if c_doc.get("bill_type") is not None else 5,
                        "test_id":        None,
                        "doctor":         c_doctor_name or (doc_id_val if doc_id_val and doc_id_val.lower() not in ("none", "null") else ""),
                        "payment_status": c_doc.get("payment_status", "Pending"),
                        "package_name":   "",
                        "source":         "hospital_billing",
                    })
            except Exception as e:
                print(f"Error fetching consultation opd items from hospital_billing: {e}")

    except Exception as e:
        import traceback
        print(f"Error fetching discharge billing items: {e}")
        traceback.print_exc()

    return Response({
        "success": True,
        "data": {
            "patient": patient_info,
            "invest_items": invest_items,
            "pharmacy_medicines": pharmacy_medicines,
        }
    })


@api_view(["GET"])
@permission_classes([AllowAny])
def get_discharge_bill_medicines(request):
    """
    Fetch patient medicines bought from pharmacy for Discharge Bill printing.
    Accepts bill_no, bill_number, ipNumber, or uhid.
    """
    client = None
    try:
        client, db = get_hms_db()
        bill_no = (request.GET.get("bill_no") or request.GET.get("bill_number") or "").strip()
        ip_number = (request.GET.get("ipNumber") or request.GET.get("ip_number") or "").strip()
        uhid = (request.GET.get("uhid") or "").strip()

        # 1. If bill_no is given, check if hospital_dischargebilling already has cached pharmacy_medicines
        if bill_no:
            b_doc = db["hospital_dischargebilling"].find_one({
                "$or": [{"bill_no": bill_no}, {"bill_number": bill_no}]
            })
            if b_doc:
                if not ip_number:
                    ip_number = str(b_doc.get("ip_number") or "")
                if not uhid:
                    uhid = str(b_doc.get("uhid") or "")
                meds = b_doc.get("pharmacy_medicines")
                if isinstance(meds, list) and len(meds) > 0:
                    if client: client.close()
                    return JsonResponse({"success": True, "pharmacy_medicines": meds})

        # 2. Query hospital_pharmacybilling
        or_clauses = []
        if ip_number:
            clean_ip = str(ip_number).strip()
            or_clauses.extend([
                {"inpatient_number": clean_ip},
                {"ipNumber": clean_ip},
                {"ip_number": clean_ip},
            ])
        if uhid:
            clean_uhid = str(uhid).strip()
            or_clauses.append({"uhid": clean_uhid})

        if not or_clauses:
            if client: client.close()
            return JsonResponse({"success": True, "pharmacy_medicines": []})

        pharm_q = {"$or": or_clauses, "is_deleted": {"$ne": True}}
        pharm_docs = list(db["hospital_pharmacybilling"].find(pharm_q, {
            "netAmount": 1, "net_amount": 1, "totalAmount": 1, "total_amount": 1,
            "medicine_particulars": 1, "bill_no": 1, "Bill_id": 1
        }))

        missing_ids = set()
        for doc in pharm_docs:
            for med in (doc.get("medicine_particulars") or []):
                if isinstance(med, dict) and not med.get("item_name") and med.get("item_id"):
                    try:
                        missing_ids.add(int(med["item_id"]))
                    except Exception:
                        pass
        name_cache = {}
        if missing_ids:
            try:
                for pi in db["hospital_pharmacyitem"].find({"item_id": {"$in": list(missing_ids)}}, {"item_id": 1, "item_name": 1, "name": 1}):
                    name_cache[str(pi.get("item_id"))] = str(pi.get("item_name") or pi.get("name") or "")
            except Exception:
                pass

        pharmacy_medicines = []
        for doc in pharm_docs:
            b_num = str(doc.get("bill_no") or doc.get("Bill_id") or "")
            meds = doc.get("medicine_particulars", [])
            if isinstance(meds, list):
                for med in meds:
                    if isinstance(med, dict):
                        qty = float(med.get("qty") or med.get("quantity") or 1)
                        rate = _to_float(med.get("price") or med.get("rate") or med.get("mrp") or 0)
                        d_val = _to_float(med.get("discount") or 0)
                        amt = _to_float(med.get("amount") or med.get("calculated_price")) or max(0.0, rate * qty - d_val)
                        iid = str(med.get("item_id") or "")
                        iname = str(med.get("item_name") or name_cache.get(iid) or f"Medicine {iid}").strip()
                        batch = str(med.get("batch_number") or "").strip()
                        pharmacy_medicines.append({
                            "item_id": iid,
                            "itemName": iname,
                            "name": iname,
                            "item_name": iname,
                            "batch_number": batch,
                            "quantity": qty,
                            "rate": rate,
                            "price": rate,
                            "discount": d_val,
                            "amount": amt,
                            "bill_no": b_num,
                            "category": "MEDICINE / PHARMACY CHARGES",
                            "source": "pharmacy",
                            "item_description": f"Batch: {batch}" if batch else "",
                        })

        # Cache on discharge bill if found
        if bill_no and pharmacy_medicines:
            try:
                db["hospital_dischargebilling"].update_one(
                    {"$or": [{"bill_no": bill_no}, {"bill_number": bill_no}]},
                    {"$set": {"pharmacy_medicines": pharmacy_medicines}}
                )
            except Exception:
                pass

        if client: client.close()
        return JsonResponse({"success": True, "pharmacy_medicines": pharmacy_medicines})
    except Exception as e:
        traceback.print_exc()
        if client: client.close()
        return JsonResponse({"success": False, "error": str(e), "pharmacy_medicines": []}, status=500)


def get_discharge_investigation_items(request):
    """
    Fetch investigation items for Discharge Billing.
    If customer_type is Insurance and lab bill type is selected,
    compare test_id and nabh_code with hospital_lab_nabh_rate to get test_name and nabh_code.
    """
    bill_type_no = request.GET.get("billTypeNo", "")
    bill_type = request.GET.get("billType")
    item_name = request.GET.get("itemName", "")
    customer_type = str(request.GET.get("customer_type", "")).strip()

    if bill_type is None or bill_type == 'undefined' or bill_type == 'null':
        return JsonResponse({
            "error": "billType parameter is required",
            "received": bill_type
        }, status=400)

    try:
        bill_type = int(bill_type)
    except (ValueError, TypeError):
        return JsonResponse({
            "error": "billType must be a valid integer",
            "billType": bill_type
        }, status=400)

    btn_upper = str(bill_type_no).upper().strip()
    is_insurance = customer_type.lower() == "insurance"

    # Special case: billTypeNo = "LAB01" or "LAB02" or "LAB03" (or any LAB category)
    if btn_upper in ["LAB01", "LAB02", "LAB03"] or btn_upper.startswith("LAB"):
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))

        # 1. Fetch active lab tests from Diagnostics database -> core_testdetails
        diag_db = client['Diagnostics']
        test_collection = diag_db['core_testdetails']

        query = {"is_active": True}
        if item_name:
            query["test_name"] = {"$regex": item_name, "$options": "i"}

        tests = list(test_collection.find(
            query,
            {
                "test_id": 1,
                "test_name": 1,
                "SH_Rate": 1,
                "Credit_Rate": 1,
                "_id": 0
            }
        ))

        # 2. Fetch NABH codes & rates from HMS database -> hospital_lab_nabh_rate
        hms_db = client['HMS']
        nabh_collection = hms_db['hospital_lab_nabh_rate']
        nabh_records = list(nabh_collection.find(
            {},
            {"_id": 0, "test_id": 1, "nabh_code": 1, "nabh_rate": 1, "non_nabh_rate": 1, "test_name": 1, "sl_no": 1}
        ))

        client.close()

        # Build lookup dictionary by test_id and nabh_code
        nabh_map = {}
        nabh_code_map = {}
        for n_rec in nabh_records:
            tid = n_rec.get('test_id')
            if tid is not None and str(tid).strip() != '':
                tid_str = str(tid).strip()
                nabh_map[tid_str] = n_rec
                try:
                    nabh_map[str(int(tid_str))] = n_rec
                except Exception:
                    pass
            n_code = n_rec.get('nabh_code')
            if n_code and str(n_code).strip():
                nabh_code_map[str(n_code).strip().upper()] = n_rec

        formatted_items = []
        for test in tests:
            t_id = test.get('test_id', '')
            t_id_str = str(t_id).strip() if t_id is not None else ''

            # Find matching NABH record by test_id
            nabh_info = nabh_map.get(t_id_str)
            if not nabh_info:
                try:
                    nabh_info = nabh_map.get(str(int(t_id_str)))
                except Exception:
                    nabh_info = None

            if btn_upper == "LAB01":
                # LAB01: price from SH_Rate
                nabh_code = str(nabh_info.get('nabh_code', '')).strip() if nabh_info else ""
                price = test.get('SH_Rate', '0')

            elif btn_upper == "LAB02":
                # LAB02: NABH rate & NABH code
                if not nabh_info:
                    continue
                nabh_code = str(nabh_info.get('nabh_code', '')).strip()
                nabh_rate = nabh_info.get('nabh_rate')
                if nabh_rate is not None and str(nabh_rate).strip() != "" and str(nabh_rate).strip().lower() != "none":
                    price = str(nabh_rate).strip()
                else:
                    price = "0"

            elif btn_upper == "LAB03":
                # LAB03: Non-NABH rate & NABH code
                if not nabh_info:
                    continue
                nabh_code = str(nabh_info.get('nabh_code', '')).strip()
                non_nabh_rate = nabh_info.get('non_nabh_rate')
                if non_nabh_rate is not None and str(non_nabh_rate).strip() != "" and str(non_nabh_rate).strip().lower() != "none":
                    price = str(non_nabh_rate).strip()
                else:
                    price = "0"

            else:
                nabh_code = str(nabh_info.get('nabh_code', '')).strip() if nabh_info else ""
                price = test.get('SH_Rate', '0')

            # CRUCIAL: If customer type is Insurance, compare test_id & nabh_code with hospital_lab_nabh_rate
            # and get test_name from hospital_lab_nabh_rate to display in discharge billing
            if is_insurance and nabh_info and nabh_info.get('test_name'):
                display_name = nabh_info.get('test_name')
                if not nabh_code and nabh_info.get('nabh_code'):
                    nabh_code = str(nabh_info.get('nabh_code')).strip()
            else:
                display_name = test.get('test_name', '')

            if price is None or str(price).strip().lower() == 'none' or str(price).strip() == '':
                price = "0"

            formatted_items.append({
                "itemName": display_name,
                "price": str(price),
                "test_id": t_id,
                "nabh_code": nabh_code,
                "nabh_rate": _to_float(nabh_info.get("nabh_rate")) if nabh_info and nabh_info.get("nabh_rate") is not None else None,
                "non_nabh_rate": _to_float(nabh_info.get("non_nabh_rate")) if nabh_info and nabh_info.get("non_nabh_rate") is not None else None,
            })

        # If customer is insurance, also append any NABH tests from hospital_lab_nabh_rate not in core_testdetails
        if is_insurance:
            seen_codes = {it.get("nabh_code") for it in formatted_items if it.get("nabh_code")}
            seen_names = {it.get("itemName", "").strip().lower() for it in formatted_items if it.get("itemName")}
            for n_rec in nabh_records:
                n_code = str(n_rec.get("nabh_code", "")).strip()
                t_name = str(n_rec.get("test_name", "")).strip()
                if not t_name:
                    continue
                if (n_code and n_code in seen_codes) or (t_name.lower() in seen_names):
                    continue
                if btn_upper == "LAB03":
                    r = n_rec.get("non_nabh_rate")
                else:
                    r = n_rec.get("nabh_rate") or n_rec.get("non_nabh_rate") or "0"
                formatted_items.append({
                    "itemName": t_name,
                    "price": str(r) if r is not None else "0",
                    "test_id": n_rec.get("test_id") or 0,
                    "nabh_code": n_code,
                    "nabh_rate": _to_float(n_rec.get("nabh_rate")) if n_rec.get("nabh_rate") is not None else None,
                    "non_nabh_rate": _to_float(n_rec.get("non_nabh_rate")) if n_rec.get("non_nabh_rate") is not None else None,
                })

        return JsonResponse({"items": formatted_items}, safe=True)

    # Regular case: Fetch from hospital_investigationprice
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    db = client['HMS']
    collection = db['hospital_investigationprice']
    investigation_data = collection.find_one(
        {"billTypeNo": bill_type_no},
        {"_id": 0, "Items": 1, "BillType": 1}
    )
    client.close()

    if investigation_data and "Items" in investigation_data:
        items = investigation_data["Items"]
        is_surgery_type = btn_upper.startswith("SUR")
        formatted_items = []
        for item in items:
            it_name = item.get("itemName", "")
            item_id = item.get("item_id", "")
            val = item.get(str(bill_type))
            price = "0"
            nabh_code = ""

            if is_surgery_type:
                if isinstance(val, dict):
                    price = str(val.get("price", "0")).strip()
                    nabh_code = str(val.get("nabh_code", "")).strip()
                elif val is not None:
                    price = str(val).strip()
                if it_name:
                    formatted_items.append({
                        "itemName": it_name,
                        "item_id": item_id,
                        "price": price if (price and price.lower() != "none") else "0",
                        "nabh_code": nabh_code
                    })
            else:
                if val is None:
                    continue
                if isinstance(val, dict):
                    price = str(val.get("price", "")).strip()
                    nabh_code = str(val.get("nabh_code", "")).strip()
                else:
                    price = str(val).strip()
                    nabh_code = ""
                if price and price != "0" and price.lower() != "none" and it_name:
                    formatted_items.append({
                        "itemName": it_name,
                        "item_id": item_id,
                        "price": price,
                        "nabh_code": nabh_code
                    })

        return JsonResponse({"items": formatted_items}, safe=True)

    return JsonResponse({"items": []}, safe=True)


# ─────────────────────────────────────────────────────────────────────────────
# LIST + CREATE
# GET  /discharge-billing/
# POST /discharge-billing/   → Flow 1 (Billed) or Flow 2 (Estimate)
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def discharge_billing_list_create(request):
    ensure_discharge_indexes()
    client, db = get_hms_db()

    # ── GET ───────────────────────────────────────────────────────────────────
    if request.method == "GET":
        action = request.GET.get("action")
        if action == "investigation_items" or request.GET.get("get_investigation_items"):
            return get_discharge_investigation_items(request)

        status_f = request.GET.get("status")
        uhid_f   = request.GET.get("uhid")
        ip_f     = request.GET.get("ip_number")
        from_f   = request.GET.get("from_date")
        to_f     = request.GET.get("to_date")
        search_f = request.GET.get("search") or request.GET.get("q")

        q = {}
        if status_f:
            q["status"] = status_f
            if status_f == "Estimate":
                q["is_cancelled"] = {"$ne": True}
        if uhid_f:
            q["uhid"] = str(uhid_f).strip()
        if ip_f:
            q["ip_number"] = str(ip_f).strip()

        if from_f or to_f:
            date_filter = {}
            if from_f:
                try:
                    from_dt_ist = _datetime.strptime(str(from_f).strip(), "%Y-%m-%d").replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=_IST_TZ)
                    date_filter["$gte"] = from_dt_ist.astimezone(_dt_module.timezone.utc)
                except Exception:
                    date_filter["$gte"] = str(from_f).strip()
            if to_f:
                try:
                    to_dt_ist = _datetime.strptime(str(to_f).strip(), "%Y-%m-%d").replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=_IST_TZ)
                    date_filter["$lte"] = to_dt_ist.astimezone(_dt_module.timezone.utc)
                except Exception:
                    date_filter["$lte"] = str(to_f).strip()
            if date_filter:
                q["bill_date"] = date_filter

        if search_f:
            s = str(search_f).strip()
            # Match patients by name or mobile or uhid
            p_matches = list(db["hospital_patient"].find({
                "$or": [
                    {"patient_name": {"$regex": s, "$options": "i"}},
                    {"mobile": {"$regex": s, "$options": "i"}},
                    {"uhid": {"$regex": s, "$options": "i"}},
                ]
            }, {"uhid": 1}).limit(100))
            matched_uhids = [str(p["uhid"]).strip() for p in p_matches if p.get("uhid")]

            or_clauses = [
                {"bill_no": {"$regex": s, "$options": "i"}},
                {"estimate_number": {"$regex": s, "$options": "i"}},
                {"uhid": {"$regex": s, "$options": "i"}},
                {"ip_number": {"$regex": s, "$options": "i"}},
                {"doctor": {"$regex": s, "$options": "i"}},
            ]
            if s.isdigit() and 1990 <= int(s) <= 2100:
                yr = int(s)
                or_clauses.append({
                    "bill_date": {
                        "$gte": datetime(yr, 1, 1, 0, 0, 0),
                        "$lte": datetime(yr, 12, 31, 23, 59, 59)
                    }
                })
            if matched_uhids:
                or_clauses.append({"uhid": {"$in": matched_uhids}})
            q["$or"] = or_clauses

        # Limit to 300 if no date range and no search is specified for instant response
        limit_val = 0
        if not (from_f or to_f or search_f or uhid_f or ip_f):
            limit_val = 300

        cursor = db["hospital_dischargebilling"].find(q).sort([("discharge_id", -1)])
        if limit_val > 0:
            cursor = cursor.limit(limit_val)
        raw_bills = list(cursor)

        if not raw_bills:
            return Response({
                "success": True,
                "data": []
            })

        # Batch prefetch Patients, Admissions, and Employees to eliminate N+1 queries!
        uhids = list({str(b.get("uhid")).strip() for b in raw_bills if b.get("uhid")})
        ip_numbers = list({str(b.get("ip_number")).strip() for b in raw_bills if b.get("ip_number")})

        patient_docs = list(db["hospital_patient"].find({"uhid": {"$in": uhids}})) if uhids else []
        patient_map = {str(p.get("uhid")).strip(): p for p in patient_docs if p.get("uhid")}

        adm_docs = list(db["hospital_admission"].find({"ipNumber": {"$in": ip_numbers}})) if ip_numbers else []
        adm_map = {str(a.get("ipNumber")).strip(): a for a in adm_docs if a.get("ipNumber")}

        emp_ids = set()
        for b in raw_bills:
            if b.get("created_by"):
                emp_ids.add(str(b.get("created_by")).strip())
        for a in adm_docs:
            if a.get("admittingDoctor"):
                emp_ids.add(str(a.get("admittingDoctor")).strip())
        _batch_resolve_employees(list(emp_ids))

        results = [_format_raw_bill_doc(b, patient_map, adm_map) for b in raw_bills]

        return Response({
            "success": True,
            "data": results
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
                existing_billed = db["hospital_dischargebilling"].find_one({
                    "ip_number": str(ip_num).strip(),
                    "status": "Billed",
                    "is_cancelled": {"$ne": True}
                })
                if existing_billed:
                    return Response(
                        {"error": "Already Discharged", "message": "Discharge bill already exists for this admission"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

        obj = DischargeBilling()
        _apply_fields(obj, data, request=request)
        obj.status    = billing_status
        obj.bill_date = timezone.now()

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
    estimate.bill_date = timezone.now()   # full datetime matching admissionDateTime
    estimate.shiftno   = request.data.get("shiftno")
    if request.data.get("payment_method"):
        estimate.payment_method = str(request.data.get("payment_method")).strip()
    if getattr(estimate, "is_insurance_bill", False) and not getattr(estimate, "insurance_bill_number", None):
        ins_name = getattr(estimate, "company_name", None) or "INS"
        estimate.insurance_bill_number = generate_insurance_bill_number(ins_name)

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


@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def convert_bill_to_insurance(request, pk):
    billing = _resolve_pk(pk)
    if billing is None:
        return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

    claim_number = str(request.data.get("claim_number") or "").strip()
    id_card_number = str(request.data.get("id_card_number") or "").strip()
    insurance_bill_number = str(request.data.get("insurance_bill_number") or "").strip()
    company_name = str(request.data.get("company_name") or "").strip()

    if not claim_number or not id_card_number:
        pd = billing.patient_details or {} if hasattr(billing, "patient_details") else {}
        uhid_val = billing.uhid or (pd.get("uhid") if isinstance(pd, dict) else "")
        pname_val = (pd.get("patient_name") if isinstance(pd, dict) else "") or ""
        auto_ins = _resolve_insurance_member_details(uhid=uhid_val, patient_name=pname_val)
        if not claim_number and auto_ins.get("claim_number"):
            claim_number = auto_ins["claim_number"]
        if not id_card_number and auto_ins.get("id_card_number"):
            id_card_number = auto_ins["id_card_number"]

    if company_name:
        billing.company_name = company_name

    if not insurance_bill_number:
        ins_name = company_name or getattr(billing, "company_name", None) or (billing.patient_details or {}).get("company") or (billing.patient_details or {}).get("company_code") or "INS"
        insurance_bill_number = generate_insurance_bill_number(ins_name)

    billing.is_insurance_bill = True
    billing.claim_number = claim_number
    billing.id_card_number = id_card_number
    billing.insurance_bill_number = insurance_bill_number

    user_id = getattr(request, "user_id", None) or request.data.get("auth-user-id") or request.data.get("user_id") or request.data.get("created_by")
    if user_id:
        billing.lastmodified_by = str(user_id).strip()
    billing.lastmodified_date = timezone.now()

    _normalise_decimals(billing)
    try:
        billing.save()
        _sync_mongo_items_array(billing)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    return Response({
        "success": True,
        "message": "Bill converted to insurance successfully",
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
    name      = request.GET.get('name')

    # =========================================================
    # STEP 1 : FILTER PATIENT
    # =========================================================
    patients = Patient.objects.none()

    if uhid:
        clean_uhid = str(uhid).strip()
        if clean_uhid:
            uhid_cond = (
                Q(uhid__iexact=clean_uhid) |
                Q(uhid__iendswith=clean_uhid) |
                Q(uhid__iendswith=f'/{clean_uhid}') |
                Q(uhid__icontains=clean_uhid)
            )

            if '/' in clean_uhid:
                parts = clean_uhid.split('/', 1)
                prefix, num_part = parts[0].strip(), parts[1].strip()
                if num_part.isdigit():
                    padded_num = num_part.zfill(6)
                    if prefix:
                        uhid_cond |= Q(uhid__iexact=f'{prefix}/{padded_num}')
                    else:
                        uhid_cond |= Q(uhid__iendswith=f'/{padded_num}')
            elif clean_uhid.isdigit():
                padded_num = clean_uhid.zfill(6)
                uhid_cond |= Q(uhid__iendswith=f'/{padded_num}')
                if len(clean_uhid) == 10:
                    uhid_cond |= (Q(mobilePhone__icontains=clean_uhid) | Q(mobilePhone__iendswith=clean_uhid))

            patients = Patient.objects.filter(uhid_cond)

    elif ip_number:
        clean_ip = str(ip_number).strip()
        if clean_ip:
            patients = Patient.objects.filter(ip_number=clean_ip)

    elif mobile:
        mobile_str = str(mobile).strip()
        digits_only = re.sub(r'\D', '', mobile_str)
        ten_digit = digits_only
        if len(digits_only) == 12 and digits_only.startswith('91'):
            ten_digit = digits_only[2:]
        elif len(digits_only) == 11 and digits_only.startswith('0'):
            ten_digit = digits_only[1:]
        elif len(digits_only) > 10:
            ten_digit = digits_only[-10:]

        mobile_q = Q(mobilePhone__icontains=mobile_str) | Q(mobilePhone=mobile_str)
        if ten_digit:
            mobile_q |= (
                Q(mobilePhone__icontains=ten_digit) |
                Q(mobilePhone=ten_digit) |
                Q(mobilePhone=f"+91{ten_digit}") |
                Q(mobilePhone=f"+91 {ten_digit}") |
                Q(mobilePhone=f"0{ten_digit}")
            )
        patients = Patient.objects.filter(mobile_q)

    elif name:
        name_str = str(name).strip()
        if name_str:
            clean_digits = re.sub(r'\D', '', name_str)
            name_q = Q(firstName__icontains=name_str) | Q(lastName__icontains=name_str)
            if clean_digits:
                name_q |= Q(mobilePhone__icontains=clean_digits)
            patients = Patient.objects.filter(name_q)

    else:
        patients = Patient.objects.all()

    # Apply name filter if supplied alongside uhid/ip/mobile
    if name and uhid:
        name_str = str(name).strip()
        if name_str:
            clean_digits = re.sub(r'\D', '', name_str)
            name_q = Q(firstName__icontains=name_str) | Q(lastName__icontains=name_str)
            if clean_digits:
                name_q |= Q(mobilePhone__icontains=clean_digits)
            patients = patients.filter(name_q)

    patients = patients.order_by('-id')[:50]

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

    # Check if this patient already has a dialysis discharge summary saved today
    today = timezone.localdate()
    saved_today = False
    if uhid:
        saved_today = DialysisDischargeSummary.objects.filter(
            uhid__iexact=str(uhid).strip(),
            date=today
        ).exists()

    # =========================================================
    # STEP 5 : RESPONSE
    # =========================================================
    return Response({
        "success": True,
        "already_saved_today": saved_today,
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

        icd_val = data.get("icd") or data.get("id_no")
        raw_advice = data.get("advice_on_discharge")
        if isinstance(raw_advice, str):
            raw_s = raw_advice.strip()
            if raw_s.startswith("[") and raw_s.endswith("]"):
                try:
                    parsed_advice = json.loads(raw_s)
                except Exception:
                    parsed_advice = raw_advice
            else:
                parsed_advice = raw_advice
        elif isinstance(raw_advice, list):
            parsed_advice = raw_advice
        else:
            parsed_advice = str(raw_advice or "")

        payload = {
            "name":       data.get("name"),
            "age":        data.get("age"),
            "gender":     data.get("gender"),

            "uhid":       data.get("uhid"),
            "consultant": data.get("consultant"),
            "icd":        icd_val,
            "id_no":      icd_val,
            "insurance":  data.get("insurance", ""),

            "address":   data.get("address"),
            "diagnosis": data.get("diagnosis"),
            "date":      data.get("date") or timezone.localdate().isoformat(),

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

            "advice_on_discharge": parsed_advice,

            "next_hd_session_on": data.get("next_hd_session_on"),
        }

        # ============================================
        # CHECK IF ALREADY SAVED FOR THIS DATE
        # ============================================
        today_date = timezone.localdate()
        target_date_str = payload.get("date")
        if target_date_str:
            try:
                target_date = _datetime.strptime(str(target_date_str)[:10], "%Y-%m-%d").date()
            except Exception:
                target_date = today_date
        else:
            target_date = today_date

        existing_today = DialysisDischargeSummary.objects.filter(
            uhid__iexact=str(payload["uhid"]).strip(),
            date=target_date
        ).first()

        if existing_today:
            return Response(
                {
                    "success": False,
                    "status_code": 400,
                    "message": f"Dialysis discharge summary for {payload['name']} (UHID: {payload['uhid']}) has already been saved for {target_date}. Duplicate summary cannot be created for the same date.",
                    "data": None
                },
                status=status.HTTP_400_BAD_REQUEST
            )

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





@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_discharge_signatories(request):
    """
    Returns the resolved signatories for Discharge Billing:
    - Left side: Bill Prepared By (name + designation resolved from backend_diagnostics_Designation)
    - Right side: General Insurance Manager (profile with department: DEPT017 & designation: DESIG027)
    """
    created_by = (
        request.GET.get("created_by") or
        request.data.get("auth-user-id") or
        request.headers.get("auth-user-id") or
        request.headers.get("User-Id") or
        ""
    )
    prepared_by_name = _resolve_employee_name(created_by) if created_by else ""
    prepared_by_desig = _resolve_employee_designation(created_by) if created_by else ""
    mgr = _resolve_insurance_manager()

    return Response({
        "success": True,
        "data": {
            "prepared_by": {
                "id": str(created_by),
                "name": (prepared_by_name or "").upper(),
                "designation": prepared_by_desig.upper()
            },
            "manager": {
                "name": (mgr.get("name") or "").upper(),
                "designation": mgr.get("designation", "GENERAL INSURANCE MANAGER").upper()
            }
        }
    })


@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_discharge_requests(request):
    """
    List active admissions ready for discharge billing:
    is_admitted=True, ward_status='Sent for billing', not discharged/cancelled,
    and no active Billed record in hospital_dischargebilling.
    """
    ensure_discharge_indexes()
    client, db = get_hms_db()
    g_db = client["Global"]

    date_param = (request.GET.get("date") or "all").strip()
    search_param = (request.GET.get("search") or "").strip().lower()
    hospital_code = (request.GET.get("hospital_code") or "").strip()

    adm_query = {
        "is_admitted": True,
        "ward_status": "Sent for billing",
        "is_discharged": {"$ne": True},
        "is_cancelled": {"$ne": True},
    }
    if hospital_code:
        adm_query["hospital_code"] = hospital_code

    admissions = list(
        db["hospital_admission"].find(
            adm_query,
            {
                "uhid": 1,
                "ipNumber": 1,
                "admittingDoctor": 1,
                "consultingDoctor": 1,
                "admissionDateTime": 1,
                "lastmodified_date": 1,
                "created_date": 1,
                "customer_type": 1,
                "insurance_company": 1,
                "room_details": 1,
                "roomShitingDetails": 1,
                "ward_status": 1,
                "age": 1,
                "age_type": 1,
            },
        )
    )

    if not admissions:
        return Response({"success": True, "count": 0, "data": []}, status=status.HTTP_200_OK)

    ip_list = [str(a.get("ipNumber") or "").strip() for a in admissions if a.get("ipNumber")]
    billed_ips = set()
    if ip_list:
        for b in db["hospital_dischargebilling"].find(
            {"ip_number": {"$in": ip_list}, "status": "Billed", "is_cancelled": {"$ne": True}},
            {"ip_number": 1},
        ):
            if b.get("ip_number"):
                billed_ips.add(str(b["ip_number"]).strip())

    uhid_list = list({str(a.get("uhid") or "").strip() for a in admissions if a.get("uhid")})
    patient_map = {}
    if uhid_list:
        for p in db["hospital_patient"].find(
            {"uhid": {"$in": uhid_list}},
            {
                "uhid": 1,
                "salutation": 1,
                "firstName": 1,
                "lastName": 1,
                "age": 1,
                "age_type": 1,
                "gender": 1,
                "mobile": 1,
            },
        ):
            patient_map[str(p.get("uhid") or "").strip()] = p

    doc_ids = list({
        str(a.get("admittingDoctor") or a.get("consultingDoctor") or "").strip()
        for a in admissions
        if (a.get("admittingDoctor") or a.get("consultingDoctor"))
    })
    doc_map = {}
    if doc_ids:
        for d in g_db["backend_diagnostics_profile"].find(
            {"employeeId": {"$in": doc_ids}},
            {"employeeId": 1, "employeeName": 1, "firstName": 1, "lastName": 1},
        ):
            eid = str(d.get("employeeId") or "").strip()
            name = (d.get("employeeName") or f"{d.get('firstName', '')} {d.get('lastName', '')}".strip()).strip()
            if eid:
                doc_map[eid] = name

    results = []
    for a in admissions:
        ip_num = str(a.get("ipNumber") or "").strip()
        if ip_num and ip_num in billed_ips:
            continue

        uhid = str(a.get("uhid") or "").strip()
        p = patient_map.get(uhid, {})
        salutation = str(p.get("salutation") or "").strip()
        full_name = f"{p.get('firstName', '')} {p.get('lastName', '')}".strip() or uhid
        display_name = f"{salutation} {full_name}".strip() if salutation else full_name

        age_val = a.get("age") if a.get("age") not in (None, "") else p.get("age", "")
        age_type = a.get("age_type") or p.get("age_type") or "Y"
        gender = p.get("gender") or ""

        doc_id = str(a.get("admittingDoctor") or a.get("consultingDoctor") or "").strip()
        doc_name = doc_map.get(doc_id) or (_resolve_employee_name(doc_id) if doc_id else "")

        room_no = ""
        bed_no = ""
        room_details = parse_json_field(a.get("room_details", []))
        if isinstance(room_details, list) and room_details:
            active_rooms = [r for r in room_details if isinstance(r, dict) and r.get("is_roomActive")]
            chosen_room = active_rooms[-1] if active_rooms else (room_details[-1] if isinstance(room_details[-1], dict) else {})
            room_no = str(chosen_room.get("roomNo") or chosen_room.get("roomNumber") or chosen_room.get("room_number") or "")
            bed_no = str(chosen_room.get("bedNo") or chosen_room.get("bedNumber") or chosen_room.get("bed_number") or "")

        shift_details = parse_json_field(a.get("roomShitingDetails", []))
        if isinstance(shift_details, list) and shift_details:
            active_shifts = [s for s in shift_details if isinstance(s, dict) and s.get("is_roomActive")]
            if active_shifts:
                last_shift = active_shifts[-1]
                room_no = str(last_shift.get("newRoomNo") or room_no)
                bed_no = str(last_shift.get("newBedNo") or bed_no)

        req_dt = (
            _to_ist_dt(a.get("lastmodified_date"))
            or _to_ist_dt(a.get("admissionDateTime"))
            or _to_ist_dt(a.get("created_date"))
        )
        adm_dt = _to_ist_dt(a.get("admissionDateTime"))

        req_date_str = req_dt.strftime("%Y-%m-%d") if req_dt else ""
        if date_param and date_param.lower() != "all" and req_date_str != date_param:
            continue

        row = {
            "id": str(a.get("_id") or ip_num or uhid),
            "uhid": uhid,
            "ipNumber": ip_num,
            "patientName": display_name,
            "age": age_val,
            "age_type": age_type,
            "gender": gender,
            "mobile": p.get("mobile") or "",
            "doctorId": doc_id,
            "doctorName": doc_name,
            "roomNo": room_no,
            "bedNo": bed_no,
            "customerType": a.get("customer_type") or "General",
            "insuranceCompany": a.get("insurance_company") or "",
            "wardStatus": a.get("ward_status") or "",
            "requestDate": req_date_str,
            "requestDateDisplay": req_dt.strftime("%d/%m/%Y") if req_dt else "",
            "requestTime": req_dt.strftime("%I:%M %p") if req_dt else "",
            "admissionDateDisplay": adm_dt.strftime("%d/%m/%Y %I:%M %p") if adm_dt else "",
            "_sort_ts": req_dt.timestamp() if req_dt else 0,
        }

        if search_param:
            haystack = " ".join([
                row["uhid"],
                row["ipNumber"],
                row["patientName"],
                row["doctorName"],
                row["roomNo"],
                row["customerType"],
                row["insuranceCompany"],
            ]).lower()
            if search_param not in haystack:
                continue

        results.append(row)

    results.sort(key=lambda r: r["_sort_ts"], reverse=True)
    for r in results:
        r.pop("_sort_ts", None)

    return Response({"success": True, "count": len(results), "data": results}, status=status.HTTP_200_OK)
