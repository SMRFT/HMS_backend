from decimal import Decimal, InvalidOperation
import os
import re
import mimetypes
import gridfs
from bson.objectid import ObjectId
from pymongo import MongoClient
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from django.http import JsonResponse, FileResponse, HttpResponse
from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from pyauth.auth import HasRoleAndDataPermission
from ..models import Admission, Room, Patient, InsuranceProvider, RoomBooking, IpAdvance_Refund
from ..serializers import AdmissionSerializer
import traceback
import json
import ast
from datetime import datetime, date


# ─────────────────────────────────────────────────────────────────────────────
# Database connection helper
# ─────────────────────────────────────────────────────────────────────────────
def _get_hms_db():
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    hms_db = client[os.getenv("HMS_DB_NAME", "HMS")]
    return client, hms_db


# ─────────────────────────────────────────────────────────────────────────────
# GridFS MLC Document Helpers & Endpoint
# ─────────────────────────────────────────────────────────────────────────────
def _upload_to_gridfs(file_obj):
    """Uploads a file object to MongoDB GridFS in 'HMS' database and returns str(file_id)"""
    client, hms_db = _get_hms_db()
    try:
        fs = gridfs.GridFS(hms_db)
        safe_name = re.sub(r'[^a-zA-Z0-9_\.\-]', '_', getattr(file_obj, 'name', 'mlc_doc'))
        content_type = getattr(file_obj, 'content_type', None) or mimetypes.guess_type(safe_name)[0] or 'application/octet-stream'
        file_id = fs.put(file_obj, filename=safe_name, content_type=content_type)
        return str(file_id)
    finally:
        if client:
            client.close()


@api_view(['GET'])
@permission_classes([AllowAny])
def get_mlc_doc(request, filename):
    """Serves MLC Document directly from MongoDB GridFS, with local fallback for legacy records"""
    client, hms_db = _get_hms_db()
    try:
        raw_id = str(filename or "").replace("mlc_docs/", "").replace("mlc_docs\\", "").strip()
        fs = gridfs.GridFS(hms_db)

        grid_file = None
        # 1. Try GridFS ObjectId lookup
        try:
            if ObjectId.is_valid(raw_id):
                grid_file = fs.get(ObjectId(raw_id))
        except Exception:
            grid_file = None

        # 2. Try GridFS filename lookup
        if not grid_file:
            grid_file = fs.find_one({"filename": raw_id})

        if grid_file:
            c_type = getattr(grid_file, 'content_type', None) or mimetypes.guess_type(grid_file.filename)[0] or 'application/octet-stream'
            response = HttpResponse(grid_file.read(), content_type=c_type)
            response["Content-Disposition"] = f'inline; filename="{grid_file.filename}"'
            return response

        # 3. Fallback to local file if it was previously saved on disk
        file_path = os.path.join(settings.BASE_DIR, "mlc_docs", raw_id)
        if not os.path.exists(file_path):
            file_path = os.path.join(settings.BASE_DIR, filename)
        if os.path.exists(file_path) and os.path.isfile(file_path):
            mime_type, _ = mimetypes.guess_type(file_path)
            mime_type = mime_type or 'application/octet-stream'
            response = FileResponse(open(file_path, 'rb'), content_type=mime_type)
            response["Content-Disposition"] = f'inline; filename="{os.path.basename(file_path)}"'
            return response

        return JsonResponse({"error": "File not found"}, status=404)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
    finally:
        if client:
            client.close()


# ─────────────────────────────────────────────────────────────────────────────
# Safe JSON field parser
# ─────────────────────────────────────────────────────────────────────────────
def parse_json_field(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return []
        try:
            return json.loads(value)
        except Exception:
            try:
                return ast.literal_eval(value)
            except Exception:
                return []
    return value if isinstance(value, list) else []


def _safe_list(value):
    result = parse_json_field(value)
    return result if isinstance(result, list) else []


def _normalize_age_type(val):
    if not val:
        return "Y"
    v = str(val).strip().upper()
    if v.startswith("Y"):
        return "Y"
    elif v.startswith("M"):
        return "M"
    elif v.startswith("D"):
        return "D"
    return "Y"


# ─────────────────────────────────────────────────────────────────────────────
# Age from DOB helper
# Returns (age_number, age_type) e.g. (25, "Y") or (6, "M") or (15, "D")
# ─────────────────────────────────────────────────────────────────────────────
def _calc_age_and_type_from_dob(dob_value):
    """
    Accepts a date, datetime, or ISO string.
    Calculates age and unit: Y for years, M for months, D for days.
    Returns: (age_number, age_type) e.g. (25, "Y"), (6, "M"), (15, "D")
    """
    if not dob_value:
        return None, ""
    try:
        if isinstance(dob_value, datetime):
            dob = dob_value.date()
        elif isinstance(dob_value, date):
            dob = dob_value
        elif isinstance(dob_value, str):
            dob_value = dob_value.strip()
            if not dob_value:
                return None, ""
            if "T" in dob_value:
                dob = parse_datetime(dob_value)
                if dob:
                    dob = dob.date()
                else:
                    return None, ""
            else:
                for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
                    try:
                        dob = datetime.strptime(dob_value, fmt).date()
                        break
                    except ValueError:
                        continue
                else:
                    return None, ""
        else:
            return None, ""

        today = date.today()
        years  = today.year  - dob.year
        months = today.month - dob.month
        days   = today.day   - dob.day

        if days < 0:
            months -= 1
            days += 30  # approximate
        if months < 0:
            years  -= 1
            months += 12

        if years >= 1:
            return years, "Y"
        elif months >= 1:
            return months, "M"
        else:
            return max(0, days), "D"
    except Exception:
        return None, ""


def _calc_age_from_dob(dob_value):
    """
    Accepts a date, datetime, or ISO string.
    Returns a formatted age string like "25 Years" or "6 Months" or "15 Days".
    """
    num, unit = _calc_age_and_type_from_dob(dob_value)
    if num is not None and unit:
        return f"{num} {unit}"
    return None


# ─────────────────────────────────────────────────────────────────────────────
# _sync_to_mongo
# ─────────────────────────────────────────────────────────────────────────────
def _sync_to_mongo(ip, room_details=None, shifting_details=None, advance_payments=None, extra_fields=None):
    client, hms_db = _get_hms_db()
    try:
        update_doc = {}
        if room_details is not None:
            update_doc["room_details"] = room_details if isinstance(room_details, list) else _safe_list(room_details)
        if shifting_details is not None:
            update_doc["roomShitingDetails"] = shifting_details if isinstance(shifting_details, list) else _safe_list(shifting_details)
        if advance_payments is not None:
            update_doc["advance_payments"] = advance_payments if isinstance(advance_payments, list) else _safe_list(advance_payments)
        if extra_fields and isinstance(extra_fields, dict):
            update_doc.update(extra_fields)

        # Unset legacy single-edit fields from MongoDB document
        unset_doc = {}
        for legacy_f in ["is_edited", "edited_by", "edited_Reason"]:
            if legacy_f in update_doc:
                del update_doc[legacy_f]
            unset_doc[legacy_f] = ""

        mongo_update = {"$set": update_doc}
        if unset_doc:
            mongo_update["$unset"] = unset_doc

        hms_db["hospital_admission"].update_one(
            {"ipNumber": str(ip)},
            mongo_update
        )
    except Exception as ex:
        print(f"[_sync_to_mongo] Failed for {ip}: {ex}")
    finally:
        if client:
            client.close()


def _sync_advance_to_mongo(ip, payments_list, employee_id=None):
    client, hms_db = _get_hms_db()
    try:
        clean_ap = payments_list if isinstance(payments_list, list) else _safe_list(payments_list)
        up_doc = {"advance_payments": clean_ap}
        if employee_id:
            up_doc["lastmodified_by"] = employee_id
            up_doc["lastmodified_date"] = timezone.now()
        hms_db["hospital_admission"].update_one(
            {"ipNumber": str(ip)},
            {"$set": up_doc}
        )
    except Exception as ex:
        print(f"[_sync_advance_to_mongo] Failed for {ip}: {ex}")
    finally:
        if client:
            client.close()


def _save_admission(adm, room_details, shifting_details, advance_payments, extra_fields=None):
    rd  = room_details       if isinstance(room_details,       list) else _safe_list(room_details)
    sd  = shifting_details   if isinstance(shifting_details,   list) else _safe_list(shifting_details)
    ap  = advance_payments   if isinstance(advance_payments,   list) else _safe_list(advance_payments)
    eh  = _safe_list(getattr(adm, "edit_history", []))

    adm.room_details       = rd
    adm.roomShitingDetails = sd
    adm.advance_payments   = ap
    adm.edit_history       = eh

    adm.save()
    sync_extra = {
        "customer_type":      getattr(adm, "customer_type", "General") or "General",
        "company_code":       getattr(adm, "company_code", "") or "",
        "insurance_company":  getattr(adm, "insurance_company", "") or "",
        "age":                getattr(adm, "age", None),
        "age_type":           getattr(adm, "age_type", "") or "Y",
        "mlc_type":           getattr(adm, "mlc_type", "") or "",
        "mlc_doc":            getattr(adm, "mlc_doc", "") or "",
        "mlc_remarks":        getattr(adm, "mlc_remarks", "") or "",
        "attender_name":         getattr(adm, "attender_name", "") or "",
        "attender_relationship": getattr(adm, "attender_relationship", "") or "",
        "attender_phone":        getattr(adm, "attender_phone", "") or "",
        "is_high_risk":       bool(getattr(adm, "is_high_risk", False)),
        "high_risk_reason":   getattr(adm, "high_risk_reason", None),
        "high_risk_date":     getattr(adm, "high_risk_date", None).isoformat() if hasattr(getattr(adm, "high_risk_date", None), "isoformat") else (str(getattr(adm, "high_risk_date", "")) if getattr(adm, "high_risk_date", None) else None),
        "edit_history":       eh,
        "is_cancelled":       getattr(adm, "is_cancelled", False),
        "cancelled_by":       getattr(adm, "cancelled_by", None),
        "cancelled_Reason":   getattr(adm, "cancelled_Reason", None),
    }
    if extra_fields and isinstance(extra_fields, dict):
        sync_extra.update(extra_fields)
    _sync_to_mongo(adm.ipNumber, rd, sd, ap, sync_extra)


# ─────────────────────────────────────────────────────────────────────────────
# High-Performance Batch Patient & Insurance Enrichment
# ─────────────────────────────────────────────────────────────────────────────
def _enrich_admissions_batch(adm_list, hospital_code=None):
    """Enriches a list of admission dicts with Patient and Insurance details in batch"""
    if not adm_list:
        return adm_list
    
    uhids = list(filter(None, {str(d.get("uhid") or "").strip() for d in adm_list}))
    patient_map = {}
    if uhids:
        client, hms_db = _get_hms_db()
        try:
            pt_query = {"uhid": {"$in": uhids}}
            if hospital_code and hospital_code != "system":
                pt_query["hospital_code"] = hospital_code
            
            pt_cursor = hms_db["hospital_patient"].find(pt_query)
            for pt in pt_cursor:
                u_key = str(pt.get("uhid") or "").strip()
                if u_key:
                    patient_map[u_key] = pt

            # Extract company codes for insurance provider lookup
            company_codes = set()
            for d in adm_list:
                c = str(d.get("company_code") or "").strip()
                if c:
                    company_codes.add(c)
            for pt in patient_map.values():
                c = str(pt.get("company_code") or "").strip()
                if c:
                    company_codes.add(c)

            ins_map = {}
            if company_codes:
                ins_cursor = hms_db["hospital_insuranceprovider"].find({"company_code": {"$in": list(company_codes)}})
                for ins in ins_cursor:
                    c_code = str(ins.get("company_code") or "").strip()
                    if c_code:
                        ins_map[c_code] = ins.get("company_name", "") or c_code
        except Exception as ex:
            print(f"[_enrich_admissions_batch] Error during batch lookup: {ex}")
        finally:
            if client:
                client.close()

    for adm_data in adm_list:
        uhid = str(adm_data.get("uhid") or "").strip()
        pt = patient_map.get(uhid)
        if not pt:
            continue
        
        company_code = str(adm_data.get("company_code") or pt.get("company_code") or "").strip()
        ins_name = str(adm_data.get("insurance_company") or adm_data.get("insuranceCompanyName") or "").strip()
        if not ins_name and company_code:
            ins_name = ins_map.get(company_code, company_code)

        dob = pt.get("dob") or pt.get("dateOfBirth")
        calc_num, calc_unit = _calc_age_and_type_from_dob(dob)

        adm_data["salutation"]           = pt.get("salutation") or ""
        adm_data["firstName"]            = pt.get("firstName") or ""
        adm_data["middleName"]           = pt.get("middleName") or ""
        adm_data["lastName"]             = pt.get("lastName") or ""
        adm_data["dob"]                  = str(dob or "")
        if calc_num is not None:
            adm_data["age"]              = calc_num
            adm_data["age_type"]         = _normalize_age_type(calc_unit or "Y")
        else:
            if adm_data.get("age") is None:
                adm_data["age"]          = pt.get("age")
            adm_data["age_type"]         = _normalize_age_type(adm_data.get("age_type") or pt.get("age_type") or "Y")
        adm_data["gender"]               = pt.get("gender") or ""
        adm_data["mobilePhone"]          = pt.get("mobilePhone") or ""
        adm_data["permanent_address"]    = pt.get("permanent_address") or ""
        adm_data["area"]                 = pt.get("area") or ""
        adm_data["zipcode"]              = pt.get("zipcode") or ""
        adm_data["city"]                 = pt.get("city") or ""
        adm_data["state"]                = pt.get("state") or ""
        if not adm_data.get("customerType") and not adm_data.get("customer_type"):
            c_type = str(pt.get("customer_type") or pt.get("customerType") or "General")
            adm_data["customerType"]     = c_type
            adm_data["customer_type"]    = c_type
        else:
            c_type = adm_data.get("customerType") or adm_data.get("customer_type")
            adm_data["customerType"]     = c_type
            adm_data["customer_type"]    = c_type
        adm_data["insuranceCompanyName"] = ins_name
        adm_data["insurance_company"]    = ins_name
        adm_data["company_code"]         = company_code

    return adm_list


def _enrich_with_patient(adm_data, hospital_code):
    """Single admission enrichment helper"""
    _enrich_admissions_batch([adm_data], hospital_code)
    return adm_data


def _get_current_room(adm):
    details = _safe_list(adm.room_details if hasattr(adm, 'room_details') else adm.get("room_details", []))
    for r in reversed(details):
        if isinstance(r, dict) and r.get("is_roomActive"):
            return r
    return details[0] if details else {}


# ─────────────────────────────────────────────────────────────────────────────
# GET /admission-ip-preview/ (and next IP generator)
# ─────────────────────────────────────────────────────────────────────────────
@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def get_next_ip_number(request):
    try:
        hospital_code = (request.data.get("auth-hospital-code") or request.headers.get("auth-hospital-code") or "system")
        branch_code   = (request.data.get("auth-branch-code")   or request.headers.get("Branch-Code")        or "system")
        outlet_code   = (request.data.get("auth-outlet-code")   or request.headers.get("Outlet-Code")        or "system")
        now     = datetime.now()
        fy      = (now.year - 2001) if now.month < 4 else (now.year - 2000)
        prefix  = f"S{fy:03d}"
        max_num = 500000

        q = {"ipNumber": {"$regex": f"^{prefix}/"}}
        if hospital_code and hospital_code != "system":
            q["hospital_code"] = hospital_code
        if branch_code and branch_code != "system":
            q["branch_code"] = branch_code
        if outlet_code and outlet_code != "system":
            q["outlet_code"] = outlet_code

        client, hms_db = _get_hms_db()
        try:
            top_adms = list(hms_db["hospital_admission"].find(q, {"ipNumber": 1}).sort("ipNumber", -1).limit(20))
            for adm in top_adms:
                ip = adm.get("ipNumber") or ""
                if "/" in ip:
                    try:
                        p, n = ip.split("/")
                        if p == prefix:
                            max_num = max(max_num, int(n))
                    except Exception:
                        continue
        finally:
            if client:
                client.close()

        return JsonResponse({"success": True, "next_ipNumber": f"{prefix}/{max_num + 1:06d}"})
    except Exception as e:
        traceback.print_exc()
        return JsonResponse({"success": False, "error": str(e)}, status=500)


# ─────────────────────────────────────────────────────────────────────────────
# GET /admission-room-search/
# ─────────────────────────────────────────────────────────────────────────────
@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def search_rooms(request):
    try:
        hospital_code = (request.data.get("auth-hospital-code") or request.headers.get("auth-hospital-code") or "system")
        result        = []
        
        client, hms_db = _get_hms_db()
        try:
            # Query ONLY active / occupied / recently discharged uncleaned admissions
            recent_dt = datetime.now() - timezone.timedelta(days=7)
            adm_query = {
                "$or": [
                    {"is_admitted": True, "is_discharged": False, "is_cancelled": {"$ne": True}},
                    {"is_discharged": True, "lastmodified_date": {"$gte": recent_dt}, "room_details.is_roomCleaned": False},
                    {"is_discharged": True, "lastmodified_date": {"$gte": recent_dt}, "roomShitingDetails.is_roomCleaned": False}
                ]
            }
            if hospital_code and hospital_code != "system":
                adm_query["hospital_code"] = hospital_code

            active_admissions = list(hms_db["hospital_admission"].find(adm_query))
            
            # Extract UHIDs
            uhids = list(filter(None, {str(a.get("uhid") or "").strip() for a in active_admissions}))
            patient_map = {}
            if uhids:
                pt_cursor = hms_db["hospital_patient"].find({"uhid": {"$in": uhids}})
                for patient in pt_cursor:
                    key = str(patient.get("uhid") or "").strip()
                    if not key:
                        continue
                    dob = patient.get("dob") or patient.get("dateOfBirth")
                    calc_num, calc_unit = _calc_age_and_type_from_dob(dob)
                    patient_map[key] = {
                        "uhid":                 key,
                        "salutation":           str(patient.get("salutation") or ""),
                        "firstName":            str(patient.get("firstName") or ""),
                        "middleName":           str(patient.get("middleName") or ""),
                        "lastName":             str(patient.get("lastName") or ""),
                        "dob":                  str(dob or ""),
                        "age":                  calc_num if calc_num is not None else patient.get("age"),
                        "age_type":             calc_unit or str(patient.get("age_type") or "Years"),
                        "gender":               str(patient.get("gender") or ""),
                        "mobilePhone":          str(patient.get("mobilePhone") or ""),
                        "permanent_address":    str(patient.get("permanent_address") or ""),
                        "area":                 str(patient.get("area") or ""),
                        "zipcode":              str(patient.get("zipcode") or ""),
                        "city":                 str(patient.get("city") or ""),
                        "state":                str(patient.get("state") or ""),
                        "customerType":         str(patient.get("customer_type") or patient.get("customerType") or "General"),
                        "insuranceCompanyName": "",
                        "company_code":         str(patient.get("company_code") or ""),
                    }

            # Fetch active bookings
            booking_map = {}
            try:
                for booking in hms_db["hospital_roombooking"].find({"is_active": True}):
                    rno = str(booking.get("room_number") or "").strip()
                    bno = str(booking.get("bed_number") or "").strip()
                    if rno and bno:
                        b_dt = booking.get("booking_date")
                        booking_map[(rno, bno)] = {
                            "ip_number": str(booking.get("ipNumber") or ""),
                            "booking_date": b_dt.isoformat() if hasattr(b_dt, "isoformat") else str(b_dt or ""),
                        }
            except Exception:
                pass

            # Fetch rooms
            room_query = {}
            if hospital_code and hospital_code != "system":
                room_query["hospital_code"] = hospital_code
            all_rooms = list(hms_db["hospital_room"].find(room_query))
        finally:
            if client:
                client.close()

        admission_map = {}
        for admission in active_admissions:
            details = _safe_list(admission.get("room_details", []))
            shifts  = _safe_list(admission.get("roomShitingDetails", []))
            is_discharged = bool(admission.get("is_discharged", False))
            is_cancelled  = bool(admission.get("is_cancelled", False))
            is_admitted   = bool(admission.get("is_admitted", False))
            is_active_adm = is_admitted and not is_cancelled and not is_discharged

            has_unclean_room = any(not bool(x.get("is_roomCleaned", False)) for x in (details + shifts))
            if not has_unclean_room and (is_discharged or not is_active_adm):
                continue

            uhid         = str(admission.get("uhid") or "").strip()
            ip_number    = str(admission.get("ipNumber") or "")
            patient_info = dict(patient_map.get(uhid, {"uhid": uhid}))
            patient_info["is_high_risk"] = bool(admission.get("is_high_risk", False))
            patient_info["high_risk_reason"] = admission.get("high_risk_reason") or ""
            hr_dt = admission.get("high_risk_date")
            patient_info["high_risk_date"] = hr_dt.isoformat() if hasattr(hr_dt, "isoformat") else str(hr_dt or "")
            
            active_shifts = [s for s in shifts if bool(s.get("is_roomActive", False))]
            active_shift  = None
            if active_shifts:
                try:
                    active_shift = max(active_shifts, key=lambda s: int(str(s.get("shifting_id", "0")).replace("SH", "")))
                except Exception:
                    active_shift = active_shifts[-1]
            for shift in shifts:
                room_no = str(shift.get("newRoomNo", "")).strip()
                bed_no  = str(shift.get("newBedNo",  "")).strip()
                if not room_no or not bed_no:
                    continue
                s_active  = bool(shift.get("is_roomActive",  False))
                s_cleaned = bool(shift.get("is_roomCleaned", False))
                if active_shift and shift == active_shift:
                    status = "Occupied"; patient_data = patient_info
                elif s_cleaned:
                    status = "Available"; patient_data = {}
                else:
                    status = "Available - Not Cleaned"; patient_data = patient_info
                key = (room_no, bed_no)
                existing = admission_map.get(key)
                if existing is None or status == "Occupied" or existing.get("status") != "Occupied":
                    admission_map[key] = {"status": status, "patient": patient_data, "ip_number": ip_number, "is_roomActive": s_active, "is_roomCleaned": s_cleaned, "source": "roomShitingDetails"}
            for entry in details:
                room_no = str(entry.get("roomNo", "")).strip()
                bed_no  = str(entry.get("bedNo",  "")).strip()
                if not room_no or not bed_no:
                    continue
                e_active  = bool(entry.get("is_roomActive",  False))
                e_cleaned = bool(entry.get("is_roomCleaned", False))
                if e_active:
                    status = "Occupied"; patient_data = patient_info
                elif e_cleaned:
                    status = "Available"; patient_data = {}
                else:
                    status = "Available - Not Cleaned"; patient_data = patient_info
                key = (room_no, bed_no)
                existing = admission_map.get(key)
                if existing is None:
                    admission_map[key] = {"status": status, "patient": patient_data, "ip_number": ip_number, "is_roomActive": e_active, "is_roomCleaned": e_cleaned, "source": "room_details"}
                elif existing.get("status") != "Occupied" and status == "Occupied":
                    admission_map[key] = {"status": status, "patient": patient_data, "ip_number": ip_number, "is_roomActive": e_active, "is_roomCleaned": e_cleaned, "source": "room_details"}

        req_block           = str(request.GET.get("block", "") or "").strip()
        req_category        = str(request.GET.get("room_category", "") or request.GET.get("category", "") or "").strip()
        req_nursing_station = str(request.GET.get("nursing_station", "") or "").strip()
        req_floor           = str(request.GET.get("floor", "") or "").strip()
        req_room_no         = str(request.GET.get("room_number", "") or "").strip()

        for room in all_rooms:
            room_no         = str(room.get("room_number") or "").strip()
            room_is_blocked = str(room.get("room_status") or "").strip().lower() == "blocked"
            if not room_no:
                continue

            r_block           = str(room.get("block") or "").strip()
            r_category        = str(room.get("room_category") or room.get("room_type") or "").strip()
            r_nursing_station = str(room.get("nursing_station") or "").strip()
            r_floor           = str(room.get("floor") or "").strip()

            if req_block and req_block.lower() != "all" and req_block.lower() != r_block.lower():
                continue
            if req_category and req_category.lower() != "all" and req_category.lower() != r_category.lower():
                continue
            if req_nursing_station and req_nursing_station.lower() != "all" and req_nursing_station.lower() != r_nursing_station.lower():
                continue
            if req_floor and req_floor.lower() != "all" and req_floor != r_floor:
                continue
            if req_room_no and req_room_no.lower() not in room_no.lower():
                continue

            beds_data = []
            for bed in _safe_list(room.get("beds", [])):
                if not isinstance(bed, dict): continue
                bed_number = str(bed.get("bed_number", "")).strip()
                if not bed_number: continue
                key = (room_no, bed_number)
                bed_is_blocked = str(bed.get("bed_status", "")).strip().lower() == "blocked"
                if room_is_blocked or bed_is_blocked:
                    beds_data.append({"bed_number": bed_number, "status": "Maintenance", "patient": {}, "ip_number": "", "booking": None, "is_roomActive": False, "is_roomCleaned": True})
                    continue
                info = admission_map.get(key)
                if info:
                    beds_data.append({"bed_number": bed_number, "status": info.get("status", "Available"), "patient": info.get("patient", {}), "ip_number": info.get("ip_number", ""), "booking": None, "is_roomActive": info.get("is_roomActive", False), "is_roomCleaned": info.get("is_roomCleaned", False)})
                    continue
                booking_info = booking_map.get(key)
                if booking_info:
                    beds_data.append({"bed_number": bed_number, "status": "Reserved", "patient": {}, "ip_number": booking_info.get("ip_number", ""), "booking": booking_info, "is_roomActive": False, "is_roomCleaned": True})
                    continue
                beds_data.append({"bed_number": bed_number, "status": "Available", "patient": {}, "ip_number": "", "booking": None, "is_roomActive": False, "is_roomCleaned": True})
            result.append({
                "room_number": room_no,
                "room_type": r_category,
                "room_category": r_category,
                "block": r_block,
                "nursing_station": r_nursing_station,
                "floor": room.get("floor", ""),
                "capacity": room.get("capacity", 1),
                "beds": beds_data
            })

        return Response(result, status=200)
    except Exception as exc:
        traceback.print_exc()
        return Response({"success": False, "error": f"Room availability failed: {str(exc)}"}, status=500)


# ─────────────────────────────────────────────────────────────────────────────
# GET  /op-patient/<uhid>/  — patient detail by UHID (with age-from-dob)
# ─────────────────────────────────────────────────────────────────────────────
@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def op_patient_detail_by_uhid(request, uhid):
    try:
        branch_code   = request.data.get('auth-branch-code')
        hospital_code = request.data.get('auth-hospital-code')
        query = {"uhid": str(uhid)}
        if hospital_code and hospital_code != "system":
            query["hospital_code"] = hospital_code
        if branch_code and branch_code != "system":
            query["branch_code"] = branch_code

        client, hms_db = _get_hms_db()
        try:
            patient = hms_db["hospital_patient"].find_one(query)
            if not patient:
                # Try without branch/hospital filter as fallback
                patient = hms_db["hospital_patient"].find_one({"uhid": str(uhid)})
            if not patient:
                return Response({"error": "Patient not found"}, status=404)

            dob = patient.get("dob") or patient.get("dateOfBirth")
            calc_age, calc_age_type = _calc_age_and_type_from_dob(dob)

            company_code = (patient.get('company_code') or "").strip()
            company_name = None
            if company_code:
                insurance = hms_db["hospital_insuranceprovider"].find_one({"company_code": company_code})
                if insurance:
                    company_name = insurance.get("company_name")

            cust_type = str(patient.get('customer_type') or patient.get('customerType') or "General")

            data = {
                "id": str(patient.get("_id") or patient.get("pk") or patient.get("id") or ""),
                "uhid": patient.get("uhid"),
                "salutation": patient.get("salutation") or "",
                "firstName": patient.get("firstName") or "",
                "middleName": patient.get("middleName") or "",
                "lastName": patient.get("lastName") or "",
                "gender": patient.get("gender") or "",
                "dob": str(dob or ""),
                "age": calc_age if calc_age is not None else patient.get("age"),
                "age_type": _normalize_age_type(calc_age_type or patient.get("age_type") or "Y"),
                "mobilePhone": patient.get("mobilePhone") or "",
                "home_phone": patient.get("home_phone") or "",
                "email": patient.get("email") or "",
                "permanent_address": patient.get("permanent_address") or "",
                "area": patient.get("area") or "",
                "zipcode": patient.get("zipcode") or "",
                "city": patient.get("city") or "",
                "state": patient.get("state") or "",
                "blood_group": patient.get("blood_group") or "",
                "customer_type": cust_type,
                "customerType": cust_type,
                "company_code": company_code,
                "company_name": company_name,
                "insuranceCompanyName": company_name,
                "doctorName": patient.get("doctorName") or "",
                "referredBy": patient.get("referredBy") or "",
                "emergency_contact": patient.get("emergency_contact") or "",
                "mlc_type": patient.get("mlc_type") or "",
                "mlc_doc": patient.get("mlc_doc") or "",
                "mlc_remarks": patient.get("mlc_remarks") or "",
            }
            return Response(data)
        finally:
            if client:
                client.close()
    except Exception as e:
        return Response({"error": str(e)}, status=500)


# ─────────────────────────────────────────────────────────────────────────────
# GET / POST  /admissions/
# ─────────────────────────────────────────────────────────────────────────────
@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def admission_view(request):
    employee_id   = (request.data.get('auth-user-id')       or request.headers.get('auth-user-id')       or "system")
    hospital_code = (request.data.get("auth-hospital-code") or request.headers.get("auth-hospital-code") or "system")
    branch_code   = (request.data.get("auth-branch-code")   or request.headers.get("Branch-Code")        or "system")
    outlet_code   = (request.data.get("auth-outlet-code")   or request.headers.get("Outlet-Code")        or "system")

    # ── GET ───────────────────────────────────────────────────────────────────
    if request.method == 'GET':
        try:
            from_date_str = request.GET.get('from_date',        '').strip()
            to_date_str   = request.GET.get('to_date',          '').strip()
            status_filter = request.GET.get('status',           '').strip()
            doctor_filter = request.GET.get('admitting_doctor', '').strip()
            ip_filter     = request.GET.get('ip_number',        '').strip()
            uhid_filter   = request.GET.get('uhid',             '').strip()

            query = {}
            if hospital_code and hospital_code != "system":
                query["hospital_code"] = hospital_code
            if branch_code and branch_code != "system":
                query["branch_code"] = branch_code
            if outlet_code and outlet_code != "system":
                query["outlet_code"] = outlet_code

            if ip_filter:
                if "/" in ip_filter:
                    query["ipNumber"] = {"$regex": f"^{re.escape(ip_filter)}$", "$options": "i"}
                else:
                    query["ipNumber"] = {"$regex": re.escape(ip_filter), "$options": "i"}

            if uhid_filter:
                query["uhid"] = {"$regex": f"^{re.escape(uhid_filter)}$", "$options": "i"}

            if status_filter == 'Admitted':
                query["is_admitted"] = True
                query["is_discharged"] = False
                query["is_cancelled"] = {"$ne": True}
            elif status_filter == 'Discharged':
                query["is_discharged"] = True
            elif status_filter == 'Cancelled':
                query["is_cancelled"] = True

            if doctor_filter and doctor_filter.lower() != "all":
                query["admittingDoctor"] = {"$regex": re.escape(doctor_filter), "$options": "i"}

            # Date Range Filter
            from_date = to_date = None
            if from_date_str:
                try:
                    from_date = datetime.strptime(from_date_str, '%Y-%m-%d').date()
                except Exception:
                    pass
            if to_date_str:
                try:
                    to_date = datetime.strptime(to_date_str, '%Y-%m-%d').date()
                except Exception:
                    pass

            if from_date or to_date:
                dt_gte = datetime.combine(from_date, datetime.min.time()) if from_date else datetime.min
                dt_lte = datetime.combine(to_date, datetime.max.time()) if to_date else datetime.max
                query["admissionDateTime"] = {"$gte": dt_gte, "$lte": dt_lte}

            client, hms_db = _get_hms_db()
            try:
                cursor = hms_db["hospital_admission"].find(query).sort("admissionDateTime", -1)
                adm_docs = list(cursor)
            finally:
                if client:
                    client.close()

            result = []
            for adm in adm_docs:
                adm_dt = adm.get("admissionDateTime")
                adm_dt_iso = adm_dt.isoformat() if hasattr(adm_dt, "isoformat") else str(adm_dt) if adm_dt else None
                
                hr_dt = adm.get("high_risk_date")
                hr_dt_iso = hr_dt.isoformat() if hasattr(hr_dt, "isoformat") else str(hr_dt) if hr_dt else None

                c_dt = adm.get("created_date")
                c_dt_iso = c_dt.isoformat() if hasattr(c_dt, "isoformat") else str(c_dt) if c_dt else None

                m_dt = adm.get("lastmodified_date")
                m_dt_iso = m_dt.isoformat() if hasattr(m_dt, "isoformat") else str(m_dt) if m_dt else None

                d = {
                    "id": str(adm.get("_id") or adm.get("pk") or adm.get("id") or ""),
                    "ipNumber":          adm.get("ipNumber"),
                    "uhid":              adm.get("uhid"),
                    "admissionDateTime": adm_dt_iso,
                    "admittingDoctor":   adm.get("admittingDoctor") or "",
                    "consultingDoctor":  adm.get("consultingDoctor") or "",
                    "packageNo":         adm.get("packageName") or "",
                    "reasonForAdmission":adm.get("reasonForAdmission") or "",
                    "customer_type":     adm.get("customer_type") or "General",
                    "customerType":      adm.get("customer_type") or "General",
                    "company_code":      adm.get("company_code") or "",
                    "insurance_company": adm.get("insurance_company") or "",
                    "insuranceCompanyName": adm.get("insurance_company") or "",
                    "age":               adm.get("age"),
                    "age_type":          adm.get("age_type") or "",
                    "mlc_type":          adm.get("mlc_type") or "",
                    "mlc_doc":           adm.get("mlc_doc") or "",
                    "mlc_remarks":       adm.get("mlc_remarks") or "",
                    "attender_name":         adm.get("attender_name") or "",
                    "attender_relationship": adm.get("attender_relationship") or "",
                    "attender_phone":        adm.get("attender_phone") or "",
                    "is_high_risk":          bool(adm.get("is_high_risk", False)),
                    "high_risk_reason":      adm.get("high_risk_reason") or "",
                    "high_risk_date":        hr_dt_iso,
                    "room_details":      _safe_list(adm.get("room_details")),
                    "roomShitingDetails":_safe_list(adm.get("roomShitingDetails")),
                    "advance_payments":  _safe_list(adm.get("advance_payments")),
                    # ── Cancellation status & Edit history ───────────────────
                    "is_cancelled":      bool(adm.get("is_cancelled", False)),
                    "cancelled_by":      adm.get("cancelled_by"),
                    "cancelled_Reason":  adm.get("cancelled_Reason"),
                    "edit_history":      _safe_list(adm.get("edit_history")),
                    "ward_status":       adm.get("ward_status"),
                    # ──────────────────────────────────────────────────────────
                    "is_admitted":       bool(adm.get("is_admitted")),
                    "is_discharged":     bool(adm.get("is_discharged")),
                    "ipserial_number":   adm.get("ipserial_number"),
                    "hospital_code":     adm.get("hospital_code"),
                    "branch_code":       adm.get("branch_code"),
                    "outlet_code":       adm.get("outlet_code"),
                    "created_by":        adm.get("created_by"),
                    "created_date":      c_dt_iso,
                    "lastmodified_by":   adm.get("lastmodified_by"),
                    "lastmodified_date": m_dt_iso,
                }
                result.append(d)

            _enrich_admissions_batch(result, hospital_code)
            return JsonResponse({"success": True, "data": result, "count": len(result)})
        except Exception as e:
            traceback.print_exc()
            return JsonResponse({"error": str(e)}, status=500)

    # ── POST ──────────────────────────────────────────────────────────────────
    elif request.method == 'POST':
        try:
            data = {k: request.data.get(k) for k in request.data}
            uhid = str(data.get('uhid', '')).strip()
            if not uhid:
                return JsonResponse({"error": "UHID is required"}, status=400)

            client, hms_db = _get_hms_db()
            try:
                # ── Fast check for existing active admission with index ──
                existing_adm = hms_db["hospital_admission"].find_one({
                    "hospital_code": hospital_code,
                    "branch_code": branch_code,
                    "outlet_code": outlet_code,
                    "uhid": uhid,
                    "is_admitted": True,
                    "is_discharged": False,
                    "is_cancelled": {"$ne": True}
                })
                if existing_adm:
                    adm_dt = existing_adm.get("admissionDateTime")
                    adm_dt_iso = adm_dt.isoformat() if hasattr(adm_dt, "isoformat") else str(adm_dt) if adm_dt else None
                    cur_room = _get_current_room(existing_adm)
                    return JsonResponse({
                        "error": "Patient already admitted",
                        "already_admitted": True,
                        "ipNumber": existing_adm.get("ipNumber"),
                        "admissionDateTime": adm_dt_iso,
                        "roomNo": cur_room.get("roomNo", ""),
                        "bedNo":  cur_room.get("bedNo",  ""),
                    }, status=400)

                # ── Fast Next IP calculation with index ──
                now_dt  = datetime.now()
                fy      = (now_dt.year - 2001) if now_dt.month < 4 else (now_dt.year - 2000)
                prefix  = f"S{fy:03d}"
                max_num = 500000
                top_ips = list(hms_db["hospital_admission"].find(
                    {
                        "hospital_code": hospital_code,
                        "branch_code": branch_code,
                        "outlet_code": outlet_code,
                        "ipNumber": {"$regex": f"^{prefix}/"}
                    },
                    {"ipNumber": 1}
                ).sort("ipNumber", -1).limit(20))
                for a in top_ips:
                    ip = a.get("ipNumber") or ""
                    if "/" in ip:
                        try:
                            p, n = ip.split("/")
                            if p == prefix:
                                max_num = max(max_num, int(n))
                        except Exception:
                            pass
                ip_number = f"{prefix}/{max_num + 1:06d}"

                # ── Patient info lookup ──
                patient_obj = hms_db["hospital_patient"].find_one({
                    "hospital_code": hospital_code,
                    "uhid": uhid
                })
                if not patient_obj:
                    patient_obj = hms_db["hospital_patient"].find_one({"uhid": uhid})
            finally:
                if client:
                    client.close()

            admission_dt = parse_datetime(str(data.get('admissionDateTime') or '')) or timezone.now()
            now_iso   = datetime.now().isoformat()
            room_details = [{
                "room_entry_id": 1,
                "roomNo": str(data.get("roomNo") or ""),
                "bedNo":  str(data.get("bedNo")  or ""),
                "is_roomActive":  True,
                "is_roomCleaned": False,
                "startDateTime":  now_iso,
                "endDateTime":    None,
            }]

            # Extract customer type and insurance
            customer_type = str(data.get("customer_type") or data.get("customerType") or "General").strip() or "General"
            company_code = str(data.get("company_code") or data.get("insuranceProviderCode") or "").strip()
            insurance_company = str(data.get("insurance_company") or data.get("insuranceCompanyName") or "").strip()
            if customer_type == "Insurance" and company_code and not insurance_company:
                try:
                    prov = InsuranceProvider.objects.get(company_code=company_code)
                    insurance_company = prov.company_name
                except Exception:
                    insurance_company = company_code

            # Extract age & age_type (from request or calculated from Patient DOB)
            age_val = data.get("age")
            age_type_val = str(data.get("age_type") or data.get("ageType") or "").strip()
            if age_val is not None and str(age_val).isdigit():
                final_age = int(age_val)
                final_age_type = _normalize_age_type(age_type_val)
            elif patient_obj:
                p_dob = patient_obj.get("dob") or patient_obj.get("dateOfBirth")
                calc_n, calc_u = _calc_age_and_type_from_dob(p_dob)
                final_age = calc_n if calc_n is not None else patient_obj.get("age")
                final_age_type = _normalize_age_type(calc_u or patient_obj.get("age_type") or "Y")
            else:
                final_age = None
                final_age_type = _normalize_age_type(age_type_val)

            # High Risk Alert handling
            is_high_risk_raw = data.get("is_high_risk")
            is_high_risk = is_high_risk_raw in [True, "true", "True", "1", 1]
            high_risk_reason = str(data.get("high_risk_reason") or "").strip() or None if is_high_risk else None
            high_risk_date_val = data.get("high_risk_date")
            high_risk_date = None
            if is_high_risk and high_risk_date_val:
                try:
                    if isinstance(high_risk_date_val, (datetime, date)):
                        high_risk_date = high_risk_date_val.date() if isinstance(high_risk_date_val, datetime) else high_risk_date_val
                    else:
                        high_risk_date = datetime.strptime(str(high_risk_date_val).strip()[:10], '%Y-%m-%d').date()
                except Exception:
                    high_risk_date = timezone.now().date()
            elif is_high_risk:
                high_risk_date = timezone.now().date()

            # MLC handling (GridFS file upload + remarks)
            mlc_type = str(data.get("mlc_type") or "").strip() or None
            mlc_remarks = str(data.get("mlc_remarks") or "").strip() or None
            mlc_doc_name = None
            if request.FILES.get("mlc_doc"):
                mlc_file = request.FILES["mlc_doc"]
                try:
                    mlc_doc_name = _upload_to_gridfs(mlc_file)
                except Exception as ex:
                    print(f"GridFS upload failed: {ex}")
                    mlc_doc_name = mlc_file.name
            elif data.get("mlc_doc") and isinstance(data.get("mlc_doc"), str):
                mlc_doc_name = data.get("mlc_doc")

            # Attender details
            attender_name = str(data.get("attender_name") or data.get("attenderName") or "").strip() or None
            attender_relationship = str(data.get("attender_relationship") or data.get("attenderRelationship") or data.get("relationship") or "").strip() or None
            attender_phone = str(data.get("attender_phone") or data.get("attenderPhone") or "").strip() or None

            adm = Admission.objects.create(
                uhid=uhid, ipNumber=ip_number, admissionDateTime=admission_dt,
                hospital_code=hospital_code, branch_code=branch_code, outlet_code=outlet_code,
                admittingDoctor=str(data.get('admittingDoctor') or ""),
                consultingDoctor=data.get('consultingDoctor'),
                packageName=str(data.get('packageNo') or "") if data.get('packageNo') else "",
                customer_type=customer_type, company_code=company_code, insurance_company=insurance_company,
                age=final_age, age_type=final_age_type,
                mlc_type=mlc_type, mlc_doc=mlc_doc_name, mlc_remarks=mlc_remarks,
                attender_name=attender_name, attender_relationship=attender_relationship, attender_phone=attender_phone,
                is_high_risk=is_high_risk, high_risk_reason=high_risk_reason, high_risk_date=high_risk_date,
                room_details=room_details, roomShitingDetails=[], advance_payments=[],
                reasonForAdmission=data.get('reasonForAdmission'),
                is_cancelled=False, cancelled_by=None, cancelled_Reason=None,
                edit_history=[],
                ward_status=None,
                is_discharged=False, is_admitted=True,
                created_by=employee_id, created_date=timezone.now(),
                lastmodified_by=employee_id, lastmodified_date=timezone.now(),
            )
            _sync_to_mongo(ip_number, room_details, [], [], {
                "customer_type": customer_type,
                "company_code": company_code,
                "insurance_company": insurance_company,
                "age": final_age,
                "age_type": final_age_type,
                "mlc_type": mlc_type,
                "mlc_doc": mlc_doc_name,
                "mlc_remarks": mlc_remarks,
                "attender_name": attender_name,
                "attender_relationship": attender_relationship,
                "attender_phone": attender_phone,
                "is_high_risk": is_high_risk,
                "high_risk_reason": high_risk_reason,
                "high_risk_date": high_risk_date.isoformat() if high_risk_date else None,
                "edit_history": [],
                "is_cancelled": False,
                "cancelled_by": None,
                "cancelled_Reason": None,
                "is_discharged": False,
                "is_admitted": True,
            })
            d = {
                "id": str(adm.pk), "ipNumber": adm.ipNumber, "uhid": adm.uhid,
                "admissionDateTime": adm.admissionDateTime.isoformat() if adm.admissionDateTime else None,
                "admittingDoctor": adm.admittingDoctor or "", "consultingDoctor": adm.consultingDoctor or "",
                "packageNo": adm.packageName or "", "reasonForAdmission": adm.reasonForAdmission or "",
                "customer_type": customer_type, "customerType": customer_type,
                "company_code": company_code,
                "insurance_company": insurance_company, "insuranceCompanyName": insurance_company,
                "age": final_age, "age_type": final_age_type,
                "mlc_type": mlc_type or "", "mlc_doc": mlc_doc_name or "", "mlc_remarks": mlc_remarks or "",
                "attender_name": attender_name or "", "attender_relationship": attender_relationship or "", "attender_phone": attender_phone or "",
                "is_high_risk": is_high_risk, "high_risk_reason": high_risk_reason or "", "high_risk_date": high_risk_date.isoformat() if high_risk_date else None,
                "room_details": room_details, "roomShitingDetails": [], "advance_payments": [],
                "is_cancelled": False, "cancelled_by": None, "cancelled_Reason": None,
                "edit_history": [],
                "ward_status": None,
                "is_admitted": True, "is_discharged": False,
                "ipserial_number": adm.ipserial_number,
            }
            _enrich_with_patient(d, hospital_code)
            return JsonResponse({"success": True, "message": "Admission created successfully", "data": d}, status=201)
        except Exception as e:
            traceback.print_exc()
            return JsonResponse({"success": False, "error": str(e)}, status=500)


# ─────────────────────────────────────────────────────────────────────────────
# GET / PUT / DELETE  /admissions/<ipNumber>/
# ─────────────────────────────────────────────────────────────────────────────
@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def admission_detail(request, ipNumber):
    try:
        employee_id   = (request.data.get('auth-user-id')       or request.headers.get('auth-user-id')       or "system")
        hospital_code = (request.data.get("auth-hospital-code") or request.headers.get("auth-hospital-code") or "system")
        branch_code   = (request.data.get("auth-branch-code")   or request.headers.get("Branch-Code")        or "system")
        outlet_code   = (request.data.get("auth-outlet-code")   or request.headers.get("Outlet-Code")        or "system")

        from django.db.models import Q
        adm = Admission.objects.filter(
            Q(ipNumber=str(ipNumber)) | Q(uhid=str(ipNumber)),
            hospital_code=hospital_code, branch_code=branch_code, outlet_code=outlet_code,
        ).first()
        if not adm:
            # Fallback without hospital/branch/outlet
            adm = Admission.objects.filter(Q(ipNumber=str(ipNumber)) | Q(uhid=str(ipNumber))).first()

        if not adm:
            return JsonResponse({'success': False, 'error': 'Admission not found'}, status=404)
        if not adm.is_admitted:
            return JsonResponse({'success': False, 'error': 'Admission inactive'}, status=404)

        def _patient_block(uhid):
            try:
                uhid = str(uhid).strip()
                if not uhid: return {}
                client, hms_db = _get_hms_db()
                pt = None
                ins_name = getattr(adm, 'insurance_company', None) or ""
                try:
                    pt = hms_db["hospital_patient"].find_one({"uhid": uhid})
                    company_code = getattr(adm, 'company_code', None) or (pt.get('company_code') if pt else "") or ""
                    if not ins_name and company_code:
                        ins = hms_db["hospital_insuranceprovider"].find_one({"company_code": company_code})
                        if ins:
                            ins_name = ins.get("company_name", company_code)
                finally:
                    if client:
                        client.close()

                if not pt: return {}
                dob = pt.get("dob") or pt.get("dateOfBirth")
                calc_num, calc_unit = _calc_age_and_type_from_dob(dob)
                return {
                    'salutation':    pt.get('salutation') or "",
                    'firstName':     pt.get('firstName') or "",
                    'middleName':    pt.get("middleName") or "",
                    'lastName':      pt.get('lastName') or "",
                    'dob':           str(dob or ""),
                    'age':           calc_num if calc_num is not None else (getattr(adm, "age", None) or pt.get('age')),
                    'age_type':      _normalize_age_type(calc_unit if calc_num is not None else (getattr(adm, "age_type", "") or pt.get("age_type") or "Y")),
                    'gender':        pt.get('gender') or "",
                    'mobilePhone':   pt.get('mobilePhone') or "",
                    'permanent_address': pt.get("permanent_address") or "",
                    'area':    pt.get("area") or "",
                    'zipcode': pt.get("zipcode") or "",
                    'city':    pt.get("city") or "",
                    'state':   pt.get("state") or "",
                    'customerType': getattr(adm, "customer_type", None) or str(pt.get("customer_type") or pt.get("customerType") or "General"),
                    'customer_type': getattr(adm, "customer_type", None) or str(pt.get("customer_type") or pt.get("customerType") or "General"),
                    'insuranceCompanyName': ins_name,
                    'insurance_company': ins_name,
                    'company_code': getattr(adm, "company_code", "") or pt.get("company_code") or "",
                }
            except Exception:
                return {}

        def _build_result(adm, rd, sd, ap):
            current_room = {}
            for r in reversed(rd):
                if isinstance(r, dict) and r.get("is_roomActive"):
                    current_room = r; break
            if not current_room and rd:
                current_room = rd[0] if isinstance(rd[0], dict) else {}
            return {
                'id':                str(adm.pk),
                'ipNumber':          adm.ipNumber,
                'uhid':              adm.uhid,
                'admissionDateTime': adm.admissionDateTime.isoformat() if adm.admissionDateTime else None,
                'admittingDoctor':   adm.admittingDoctor  or "",
                'consultingDoctor':  adm.consultingDoctor or "",
                'packageNo':         adm.packageName      or "",
                'roomNo':  current_room.get('roomNo', ''),
                'bedNo':   current_room.get('bedNo',  ''),
                'reasonForAdmission': adm.reasonForAdmission or "",
                'customer_type':     getattr(adm, "customer_type", "General") or "General",
                'customerType':      getattr(adm, "customer_type", "General") or "General",
                'company_code':      getattr(adm, "company_code", "") or "",
                'insurance_company': getattr(adm, "insurance_company", "") or "",
                'insuranceCompanyName': getattr(adm, "insurance_company", "") or "",
                'age':               getattr(adm, "age", None),
                'age_type':          getattr(adm, "age_type", "") or "",
                'mlc_type':          adm.mlc_type    or "",
                'mlc_doc':           adm.mlc_doc     or "",
                'mlc_remarks':       adm.mlc_remarks or "",
                'attender_name':         getattr(adm, 'attender_name', '') or "",
                'attender_relationship': getattr(adm, 'attender_relationship', '') or "",
                'attender_phone':        getattr(adm, 'attender_phone', '') or "",
                'is_high_risk':          bool(getattr(adm, 'is_high_risk', False)),
                'high_risk_reason':      getattr(adm, 'high_risk_reason', '') or "",
                'high_risk_date':        adm.high_risk_date.isoformat() if hasattr(getattr(adm, "high_risk_date", None), "isoformat") else (str(getattr(adm, "high_risk_date", "")) if getattr(adm, "high_risk_date", None) else None),
                'advance_payments':  ap,
                # ── Cancellation status & Edit history ───────────────────────
                'is_cancelled':     bool(getattr(adm, "is_cancelled",    False)),
                'cancelled_by':     getattr(adm, "cancelled_by",         None),
                'cancelled_Reason': getattr(adm, "cancelled_Reason",     None),
                'edit_history':     _safe_list(getattr(adm, "edit_history", [])),
                'ward_status':      getattr(adm, "ward_status",          ""),
                # ────────────────────────────────────────────────────────────
                'is_admitted':       bool(adm.is_admitted),
                'is_discharged':     bool(adm.is_discharged),
                'ipserial_number':   adm.ipserial_number,
                'room_details':      rd,
                'roomShitingDetails':sd,
                **_patient_block(str(adm.uhid or "")),
            }

        # ── GET ───────────────────────────────────────────────────────────────
        if request.method == 'GET':
            rd = _safe_list(adm.room_details)
            sd = _safe_list(adm.roomShitingDetails)
            ap = _safe_list(adm.advance_payments)
            return JsonResponse({"success": True, "data": _build_result(adm, rd, sd, ap)})

        # ── PUT ───────────────────────────────────────────────────────────────
        elif request.method == 'PUT':
            data = request.data
            def get_val(v): return v[0] if isinstance(v, list) else v

            action = str(get_val(data.get('action', '')) or '').strip()

            rd = _safe_list(adm.room_details)
            sd = _safe_list(adm.roomShitingDetails)
            ap = _safe_list(adm.advance_payments)

            # ── action=cancel ─────────────────────────────────────────────────
            if action == 'cancel':
                cancel_reason = str(get_val(data.get('cancelled_Reason', '')) or '').strip()
                if not cancel_reason:
                    return JsonResponse({'success': False, 'error': 'cancelled_Reason is required to cancel an admission.'}, status=400)
                now_iso = timezone.now().isoformat()
                for room in rd:
                    if isinstance(room, dict) and room.get("is_roomActive"):
                        room["is_roomActive"] = False
                        if not room.get("endDateTime"): room["endDateTime"] = now_iso
                for room in sd:
                    if isinstance(room, dict) and room.get("is_roomActive"):
                        room["is_roomActive"] = False
                        if not room.get("endDateTime"): room["endDateTime"] = now_iso
                adm.is_cancelled       = True
                adm.cancelled_by       = employee_id
                adm.cancelled_Reason   = cancel_reason
                adm.is_admitted        = False
                adm.lastmodified_by    = employee_id
                adm.lastmodified_date  = timezone.now()
                _save_admission(adm, rd, sd, ap)
                return JsonResponse({"success": True, "message": "Admission cancelled successfully"})

            # ── action=edit  (regular PUT with edit tracking) ─────────────────
            else:
                edit_reason = str(get_val(data.get('edited_Reason', '')) or '').strip()
                if not edit_reason:
                    return JsonResponse({'success': False, 'error': 'edited_Reason is required to edit an admission.'}, status=400)

                for f in ['admittingDoctor', 'consultingDoctor', 'reasonForAdmission', 'mlc_type', 'mlc_remarks', 'attender_name', 'attender_relationship', 'attender_phone']:
                    if f in data:
                        val = get_val(data.get(f))
                        setattr(adm, f, str(val) if val else "")
                if 'attenderName' in data and not getattr(adm, 'attender_name', None):
                    adm.attender_name = str(get_val(data.get('attenderName')) or '')
                if 'attenderRelationship' in data and not getattr(adm, 'attender_relationship', None):
                    adm.attender_relationship = str(get_val(data.get('attenderRelationship')) or '')
                if 'attenderPhone' in data and not getattr(adm, 'attender_phone', None):
                    adm.attender_phone = str(get_val(data.get('attenderPhone')) or '')

                # Handle High Risk Alert edit
                if 'is_high_risk' in data:
                    ihr_val = get_val(data.get('is_high_risk'))
                    adm.is_high_risk = ihr_val in [True, "true", "True", "1", 1]
                    if adm.is_high_risk:
                        adm.high_risk_reason = str(get_val(data.get('high_risk_reason')) or '').strip() or None
                        hr_dt_val = get_val(data.get('high_risk_date'))
                        if hr_dt_val:
                            try:
                                if isinstance(hr_dt_val, (datetime, date)):
                                    adm.high_risk_date = hr_dt_val.date() if isinstance(hr_dt_val, datetime) else hr_dt_val
                                else:
                                    adm.high_risk_date = datetime.strptime(str(hr_dt_val).strip()[:10], '%Y-%m-%d').date()
                            except Exception:
                                adm.high_risk_date = timezone.now().date()
                        else:
                            adm.high_risk_date = timezone.now().date()
                    else:
                        adm.high_risk_reason = None
                        adm.high_risk_date = None
                elif 'high_risk_reason' in data and adm.is_high_risk:
                    adm.high_risk_reason = str(get_val(data.get('high_risk_reason')) or '').strip() or None

                if 'packageNo' in data:
                    val = get_val(data.get('packageNo'))
                    adm.packageName = str(val) if val else ""

                if 'customer_type' in data or 'customerType' in data:
                    c_type = str(get_val(data.get('customer_type')) or get_val(data.get('customerType')) or 'General')
                    adm.customer_type = c_type
                if 'company_code' in data or 'insuranceProviderCode' in data:
                    c_code = str(get_val(data.get('company_code')) or get_val(data.get('insuranceProviderCode')) or '')
                    adm.company_code = c_code
                if 'insurance_company' in data or 'insuranceCompanyName' in data:
                    i_comp = str(get_val(data.get('insurance_company')) or get_val(data.get('insuranceCompanyName')) or '')
                    adm.insurance_company = i_comp
                elif adm.customer_type == "Insurance" and adm.company_code:
                    try:
                        prov = InsuranceProvider.objects.get(company_code=adm.company_code)
                        adm.insurance_company = prov.company_name
                    except Exception:
                        pass

                if 'age' in data:
                    age_v = get_val(data.get('age'))
                    if age_v is not None and str(age_v).isdigit():
                        adm.age = int(age_v)
                if 'age_type' in data or 'ageType' in data:
                    at_v = str(get_val(data.get('age_type')) or get_val(data.get('ageType')) or '')
                    if at_v:
                        adm.age_type = _normalize_age_type(at_v)

                # Handle MLC Document GridFS upload on edit if provided
                if request.FILES.get("mlc_doc"):
                    mlc_file = request.FILES["mlc_doc"]
                    try:
                        adm.mlc_doc = _upload_to_gridfs(mlc_file)
                    except Exception as ex:
                        print(f"GridFS upload on edit failed: {ex}")
                        adm.mlc_doc = mlc_file.name

                new_room_no = str(get_val(data.get("roomNo")) or "").strip()
                new_bed_no  = str(get_val(data.get("bedNo"))  or "").strip()

                if new_room_no or new_bed_no:
                    now_iso     = timezone.now().isoformat()
                    active_room = next((r for r in rd if isinstance(r, dict) and r.get("is_roomActive")), None)
                    prev_room_no = prev_bed_no = ""
                    if active_room:
                        active_room["is_roomActive"]    = False
                        active_room["endDateTime"]       = now_iso
                        active_room["lastmodified_by"]   = employee_id
                        active_room["lastmodified_date"] = now_iso
                        prev_room_no = active_room.get("roomNo", "")
                        prev_bed_no  = active_room.get("bedNo",  "")
                    rd.append({
                        "room_entry_id": len(rd) + 1,
                        "roomNo": new_room_no or prev_room_no,
                        "bedNo":  new_bed_no  or prev_bed_no,
                        "is_roomActive":  True, "is_roomCleaned": False,
                        "startDateTime":  timezone.now().isoformat(), "endDateTime": None,
                        "created_by": employee_id, "created_date": timezone.now().isoformat(),
                        "lastmodified_by": employee_id, "lastmodified_date": timezone.now().isoformat(),
                    })

                # Append to edit_history array (single source of truth)
                edit_history = _safe_list(getattr(adm, "edit_history", []))
                edit_entry = {
                    "edited_by": str(employee_id),
                    "edited_date": timezone.now().isoformat(),
                    "edited_reason": edit_reason,
                }
                edit_history.append(edit_entry)
                adm.edit_history       = edit_history
                adm.lastmodified_by    = employee_id
                adm.lastmodified_date  = timezone.now()
                _save_admission(adm, rd, sd, ap)
                return JsonResponse({"success": True, "message": "Updated successfully", "data": _build_result(adm, rd, sd, ap)})

        # ── DELETE  (legacy — kept for backward compat, uses cancel logic) ────
        elif request.method == 'DELETE':
            now_iso = timezone.now().isoformat()
            rd = _safe_list(adm.room_details)
            sd = _safe_list(adm.roomShitingDetails)
            ap = _safe_list(adm.advance_payments)
            for room in rd:
                if isinstance(room, dict) and room.get("is_roomActive"):
                    room["is_roomActive"] = False
                    if not room.get("endDateTime"): room["endDateTime"] = now_iso
            for room in sd:
                if isinstance(room, dict) and room.get("is_roomActive"):
                    room["is_roomActive"] = False
                    if not room.get("endDateTime"): room["endDateTime"] = now_iso
            adm.is_cancelled      = True
            adm.cancelled_by      = employee_id
            adm.cancelled_Reason  = "Cancelled via DELETE"
            adm.is_admitted       = False
            adm.lastmodified_by   = employee_id
            adm.lastmodified_date = timezone.now()
            _save_admission(adm, rd, sd, ap)
            return JsonResponse({"success": True, "message": "Admission cancelled successfully"})

    except Exception as e:
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ── Advance Helpers ───────────────────────────────────────────────────────────

def _financial_year_prefix(dt=None):
    dt = dt or timezone.now()
    year, month = dt.year, dt.month
    fy = (
        f"{year % 100:02d}{(year + 1) % 100:02d}"
        if month >= 4
        else f"{(year - 1) % 100:02d}{year % 100:02d}"
    )
    return f"{fy}/"


def _max_sequence_for_prefix(bill_numbers, prefix):
    max_seq = 0
    for bn in bill_numbers:
        if isinstance(bn, str) and bn.startswith(prefix):
            try:
                max_seq = max(max_seq, int(bn.split('/')[-1]))
            except (ValueError, IndexError):
                continue
    return max_seq


def _generate_advance_bill_no(hospital_code, branch_code, outlet_code):
    """
    Continuous, FY-scoped bill number across admissions for this outlet.
    Optimized to fetch latest matching bill numbers without full table scan.
    """
    prefix = _financial_year_prefix()
    bill_numbers = []
    client, hms_db = _get_hms_db()
    try:
        q = {
            "advance_payments.bill_no": {"$regex": f"^{prefix}"}
        }
        if hospital_code and hospital_code != "system": q["hospital_code"] = hospital_code
        if branch_code and branch_code != "system": q["branch_code"] = branch_code
        if outlet_code and outlet_code != "system": q["outlet_code"] = outlet_code
        
        top_adms = list(hms_db["hospital_admission"].find(q, {"advance_payments": 1}).sort("created_date", -1).limit(50))
        for adm in top_adms:
            for p in _safe_list(adm.get("advance_payments")):
                if isinstance(p, dict) and p.get('bill_no'):
                    bill_numbers.append(p['bill_no'])
    except Exception as e:
        print(f"[_generate_advance_bill_no] Error: {e}")
    finally:
        if client:
            client.close()

    next_seq = _max_sequence_for_prefix(bill_numbers, prefix) + 1
    return f"{prefix}{next_seq:06d}"


def _generate_refund_bill_no(hospital_code, branch_code, outlet_code):
    """Separate, independent FY-scoped sequence for refund bill numbers."""
    prefix = _financial_year_prefix()
    bill_numbers = list(
        IpAdvance_Refund.objects.filter(
            hospital_code=hospital_code, branch_code=branch_code, outlet_code=outlet_code,
            refund_bill_no__startswith=prefix,
        ).values_list('refund_bill_no', flat=True)
    )
    next_seq = _max_sequence_for_prefix(bill_numbers, prefix) + 1
    return f"{prefix}{next_seq:06d}"


def _update_advance_payments(ip_number, hospital_code, branch_code, outlet_code,
                              advance_payments, employee_id):
    clean_ap = advance_payments if isinstance(advance_payments, list) else _safe_list(advance_payments)
    updated = Admission.objects.filter(
        ipNumber=str(ip_number), hospital_code=hospital_code,
        branch_code=branch_code, outlet_code=outlet_code,
    ).update(
        advance_payments=clean_ap,
        lastmodified_by=employee_id,
        lastmodified_date=timezone.now(),
    )
    _sync_advance_to_mongo(ip_number, clean_ap, employee_id)
    return updated


def _bill_type_fields(payload):
    bill_type = payload.get('bill_type')
    bill_type_no = payload.get('billTypeNo') or payload.get('bill_type_no')
    return bill_type, bill_type_no


# ── Advance View ─────────────────────────────────────────────────────────────

@api_view(['GET', 'POST', 'PUT'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def admission_advance(request, ipNumber=None):
    try:
        employee_id   = request.data.get('auth-user-id')       or request.headers.get('auth-user-id')       or "system"
        hospital_code = request.data.get("auth-hospital-code") or request.headers.get("auth-hospital-code") or "system"
        branch_code   = request.data.get("auth-branch-code")   or request.headers.get("Branch-Code")        or "system"
        outlet_code   = request.data.get("auth-outlet-code")   or request.headers.get("Outlet-Code")        or "system"
        now_iso = timezone.now().isoformat()

        # ── GET ───────────────────────────────────────────────────────────────
        if request.method == 'GET':
            ip_number = request.GET.get("ip_number", "").strip()
            uhid      = request.GET.get("uhid",      "").strip()
            from_date = request.GET.get("from_date", "").strip()
            to_date   = request.GET.get("to_date",   "").strip()

            if not ip_number and not uhid and not (from_date and to_date):
                return JsonResponse({'success': False, 'error': 'Provide ip_number/uhid or date range'}, status=400)

            q = {
                "is_admitted": True,
                "is_cancelled": {"$ne": True},
            }
            if hospital_code and hospital_code != "system": q["hospital_code"] = hospital_code
            if branch_code and branch_code != "system": q["branch_code"] = branch_code
            if outlet_code and outlet_code != "system": q["outlet_code"] = outlet_code

            if ip_number:
                q["ipNumber"] = ip_number
            if uhid:
                q["uhid"] = uhid

            client, hms_db = _get_hms_db()
            try:
                admissions = list(hms_db["hospital_admission"].find(q))
                if not admissions:
                    return JsonResponse({'success': False, 'error': 'No matching admissions found'}, status=404)

                uhids = list({str(a.get("uhid")).strip() for a in admissions if a.get("uhid")})
                patient_map = {}
                if uhids:
                    pt_cursor = hms_db["hospital_patient"].find({"uhid": {"$in": uhids}})
                    for p in pt_cursor:
                        key = str(p.get("uhid") or "").strip().upper()
                        patient_map[key] = " ".join(filter(None, [p.get("salutation"), p.get("firstName"), p.get("lastName")])).strip()
            finally:
                if client:
                    client.close()

            advance_payments = []
            for adm in admissions:
                payments = _safe_list(adm.get("advance_payments"))
                patient_key = str(adm.get("uhid") or "").strip().upper()
                for p in payments:
                    if not isinstance(p, dict):
                        continue
                    if p.get('status') == 'Edited':
                        continue
                    payment_mode = ""
                    if isinstance(p.get("payment_details"), dict):
                        payment_mode = p["payment_details"].get("method", "")
                    paid_date = p.get("paid_datetime") or ""
                    if isinstance(paid_date, datetime):
                        paid_date = paid_date.isoformat()
                    p["ip_number"]    = adm.get("ipNumber")
                    p["uhid"]         = adm.get("uhid")
                    p["patient_name"] = patient_map.get(patient_key, "")
                    p["payment_mode"] = payment_mode
                    p["paid_date"]    = paid_date
                    if not isinstance(p.get("refund_details"), list):
                        p["refund_details"] = []
                    advance_payments.append(p)

            if from_date and to_date:
                try:
                    from_dt = datetime.strptime(from_date, "%Y-%m-%d").date()
                    to_dt   = datetime.strptime(to_date,   "%Y-%m-%d").date()
                    filtered = []
                    for p in advance_payments:
                        date_value = p.get('created_date') or p.get('bill_date') or p.get('date')
                        if not date_value:
                            continue
                        try:
                            if isinstance(date_value, datetime):
                                p_date = date_value.date()
                            elif isinstance(date_value, str):
                                if 'T' in date_value:
                                    p_date = datetime.fromisoformat(date_value.replace('Z', '+00:00')).date()
                                else:
                                    p_date = datetime.strptime(date_value[:10], "%Y-%m-%d").date()
                            else:
                                continue
                            if from_dt <= p_date <= to_dt:
                                filtered.append(p)
                        except Exception:
                            continue
                    advance_payments = filtered
                except Exception as e:
                    return JsonResponse({'success': False, 'error': f'Invalid date format: {str(e)}'}, status=400)

            return JsonResponse({'success': True, 'data': advance_payments})

        # ── Find admission for POST / PUT ─────────────────────────────────────
        adm = Admission.objects.filter(
            ipNumber=str(ipNumber), hospital_code=hospital_code,
            branch_code=branch_code, outlet_code=outlet_code,
        ).first()
        if not adm:
            adm = Admission.objects.filter(ipNumber=str(ipNumber)).first()
        if not adm:
            return JsonResponse({'success': False, 'error': 'Admission not found'}, status=404)

        ap = _safe_list(adm.advance_payments)

        # ── POST — create new advance ─────────────────────────────────────────
        if request.method == 'POST':
            amount = request.data.get('advance_amount')
            if amount is None or str(amount).strip() == '':
                return JsonResponse({'success': False, 'error': 'advance_amount is required'}, status=400)

            ip_adv_raw = request.data.get('ip_advance')
            bill_adv_raw = request.data.get('billing_advance')
            if ip_adv_raw is None or str(ip_adv_raw).strip() == '' or bill_adv_raw is None or str(bill_adv_raw).strip() == '':
                return JsonResponse({'success': False, 'error': 'Both ip_advance and billing_advance must be entered'}, status=400)

            try:
                adv_amt = float(amount)
                ip_adv = float(ip_adv_raw)
                bill_adv = float(bill_adv_raw)
            except (ValueError, TypeError):
                return JsonResponse({'success': False, 'error': 'Invalid numeric values for advance amounts'}, status=400)

            if adv_amt <= 0:
                return JsonResponse({'success': False, 'error': 'advance_amount must be greater than 0'}, status=400)

            if abs((ip_adv + bill_adv) - adv_amt) > 0.01:
                return JsonResponse({'success': False, 'error': f'Sum of IP Advance (₹{ip_adv:.2f}) and Billing Advance (₹{bill_adv:.2f}) must equal Advance Amount (₹{adv_amt:.2f})'}, status=400)

            bill_type, bill_type_no = _bill_type_fields(request.data)
            if bill_type is None or not bill_type_no:
                return JsonResponse({'success': False, 'error': 'bill_type and billTypeNo are required'}, status=400)

            new_entry = {
                "advance_id":       f"ADV{len(ap) + 1}",
                "bill_no":          _generate_advance_bill_no(hospital_code, branch_code, outlet_code),
                "bill_type":        bill_type,
                "billTypeNo":       bill_type_no,
                "date":             request.data.get('date', now_iso[:10]),
                "bill_date":        now_iso,
                "advance_amount":   adv_amt,
                "ip_advance":       ip_adv,
                "billing_advance":  bill_adv,
                "is_advanceActive": True,
                "status":           "Pending",
                "created_by":       employee_id,
                "created_date":     now_iso,
                "is_refund":        False,
                "refund_details":   [],
            }
            ap.append(new_entry)
            _update_advance_payments(ipNumber, hospital_code, branch_code, outlet_code, ap, employee_id)
            return JsonResponse({'success': True, 'data': new_entry}, status=201)

        # ── PUT ───────────────────────────────────────────────────────────────
        elif request.method == 'PUT':
            action     = str(request.data.get('action', '') or '').strip()
            advance_id = str(request.data.get('advance_id', '') or '').strip()

            if not advance_id:
                return JsonResponse({'success': False, 'error': 'advance_id is required'}, status=400)

            entry = next((a for a in ap if a.get('advance_id') == advance_id), None)
            if not entry:
                return JsonResponse({'success': False, 'error': f'Advance entry "{advance_id}" not found'}, status=404)

            # ── cancel ──────────────────────────────────────────────────────
            if action == 'cancel':
                if not entry.get('is_advanceActive'):
                    return JsonResponse({'success': False, 'error': 'Advance is already inactive'}, status=400)
                if entry.get('status') == 'Cancelled':
                    return JsonResponse({'success': False, 'error': 'Advance is already cancelled'}, status=400)
                entry['is_advanceActive'] = False
                entry['status']           = 'Cancelled'
                entry['cancelled_by']     = employee_id
                entry['cancelled_date']   = now_iso
                _update_advance_payments(ipNumber, hospital_code, branch_code, outlet_code, ap, employee_id)
                return JsonResponse({'success': True, 'data': entry})

            # ── refund — full amount only, single refund record, status -> Refunded ──
            elif action == 'refund':
                current_status = entry.get('status')
                if current_status != 'Paid':
                    return JsonResponse(
                        {'success': False, 'error': f"Refund is only allowed for Paid advances. Current status: '{current_status}'"},
                        status=400,
                    )
                if entry.get('is_refund'):
                    return JsonResponse({'success': False, 'error': 'This advance has already been refunded'}, status=400)

                advance_total = float(entry.get('advance_amount', 0))
                raw_refund = request.data.get('refund_amount', advance_total)
                try:
                    refund_amount = float(raw_refund)
                except (TypeError, ValueError):
                    return JsonResponse({'success': False, 'error': 'refund_amount must be a valid number'}, status=400)

                if abs(refund_amount - advance_total) > 0.001:
                    return JsonResponse(
                        {'success': False, 'error': f"Partial refunds are not allowed. Refund amount must equal the full advance amount of ₹{advance_total:.2f}"},
                        status=400,
                    )

                refund_bill_type, refund_bill_type_no = _bill_type_fields(request.data)
                if refund_bill_type is None or not refund_bill_type_no:
                    refund_bill_type, refund_bill_type_no = entry.get('bill_type'), entry.get('billTypeNo')

                refund_bill_no = _generate_refund_bill_no(hospital_code, branch_code, outlet_code)

                # 1) Persist refund record in its table
                refund_row = IpAdvance_Refund.objects.create(
                    refund_bill_no=refund_bill_no,
                    refund_date=timezone.now(),
                    refund_amount=refund_amount,
                    bill_no=entry.get('bill_no'),
                    ip_number=str(ipNumber),
                    uhid=str(adm.uhid),
                    advance_amount=advance_total,
                    remarks=request.data.get('remarks', ''),
                    bill_type=str(refund_bill_type),
                    billTypeNo=refund_bill_type_no,
                    status="Refunded",
                    hospital_code=hospital_code,
                    branch_code=branch_code,
                    outlet_code=outlet_code,
                    created_by=employee_id,
                    created_date=timezone.now(),
                    lastmodified_by=employee_id,
                    lastmodified_date=timezone.now(),
                )

                # 2) Lightweight copy on advance entry
                refund_record = {
                    "refund_id":        str(refund_row.pk),
                    "refund_bill_no":   refund_bill_no,
                    "refunded_amount":  f"{refund_amount:.2f}",
                    "refunded_date":    now_iso,
                    "refunded_by":      employee_id,
                    "payment_mode":     request.data.get('payment_mode', 'Cash'),
                    "remarks":          request.data.get('remarks', ''),
                    "bill_type":        refund_bill_type,
                    "billTypeNo":       refund_bill_type_no,
                }
                entry['refund_details']     = [refund_record]
                entry['is_refund']          = True
                entry['status']             = 'Refunded'
                entry['is_advanceActive']   = False
                entry['fully_refunded_date'] = now_iso

                _update_advance_payments(ipNumber, hospital_code, branch_code, outlet_code, ap, employee_id)

                return JsonResponse({
                    'success': True,
                    'data': {
                        'advance_entry':  entry,
                        'refund_record':  refund_record,
                        'refund_bill_no': refund_bill_no,
                    },
                })

            # ── edit (only while Pending) ──────────────────────────────────
            else:
                amount = request.data.get('advance_amount')
                if not amount:
                    return JsonResponse({'success': False, 'error': 'advance_amount is required'}, status=400)
                if entry.get('status') != 'Pending':
                    return JsonResponse({'success': False, 'error': f"Cannot edit — status is '{entry.get('status')}'"}, status=400)

                bill_type, bill_type_no = _bill_type_fields(request.data)
                if bill_type is None or not bill_type_no:
                    bill_type, bill_type_no = entry.get('bill_type'), entry.get('billTypeNo')

                original_bill_no = entry.get('bill_no')
                entry['is_advanceActive'] = False
                entry['status']           = 'Edited'
                entry['edited_by']        = employee_id
                entry['edited_date']      = now_iso

                new_entry = {
                    "advance_id":       f"ADV{len(ap) + 1}",
                    "bill_no":          original_bill_no,
                    "bill_type":        bill_type,
                    "billTypeNo":       bill_type_no,
                    "date":             request.data.get('date', now_iso[:10]),
                    "bill_date":        now_iso,
                    "advance_amount":   float(amount),
                    "ip_advance":       float(request.data.get('ip_advance',      0)),
                    "billing_advance":  float(request.data.get('billing_advance', 0)),
                    "is_advanceActive": True,
                    "status":           "Pending",
                    "created_by":       employee_id,
                    "created_date":     now_iso,
                    "edited_from":      advance_id,
                    "is_refund":        False,
                    "refund_details":   [],
                }
                ap.append(new_entry)
                _update_advance_payments(ipNumber, hospital_code, branch_code, outlet_code, ap, employee_id)
                return JsonResponse({'success': True, 'data': {'original': entry, 'new_entry': new_entry}})

    except Exception as e:
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)}, status=500)