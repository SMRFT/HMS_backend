from decimal import Decimal, InvalidOperation
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from pyauth.auth import HasRoleAndDataPermission
from ..models import Admission, Room, Patient, InsuranceProvider, RoomBooking
from ..serializers import AdmissionSerializer
import traceback
import json
import ast
from datetime import datetime, date


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


# ─────────────────────────────────────────────────────────────────────────────
# Age from DOB helper
# Returns age as a formatted string e.g. "34Y" or "34Y 3M"
# ─────────────────────────────────────────────────────────────────────────────
def _calc_age_from_dob(dob_value):
    """
    Accepts a date, datetime, or ISO string.
    Returns a concise age string like "34Y" or "34Y 3M 10D".
    Returns None if dob_value is falsy or unparseable.
    """
    if not dob_value:
        return None
    try:
        if isinstance(dob_value, (date, datetime)):
            dob = dob_value if isinstance(dob_value, date) else dob_value.date()
        elif isinstance(dob_value, str):
            dob_value = dob_value.strip()
            if not dob_value:
                return None
            # Handle ISO datetime strings
            if "T" in dob_value:
                dob = datetime.fromisoformat(dob_value.replace("Z", "+00:00")).date()
            else:
                # Try common date formats
                for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
                    try:
                        dob = datetime.strptime(dob_value, fmt).date()
                        break
                    except ValueError:
                        continue
                else:
                    return None
        else:
            return None

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
            return f"{years}Y"
        elif months >= 1:
            return f"{months}M"
        else:
            return f"{days}D"
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# _sync_to_mongo
# ─────────────────────────────────────────────────────────────────────────────
def _sync_to_mongo(ip, room_details, shifting_details, advance_payments):
    try:
        import os
        from pymongo import MongoClient
        MONGO_URI = os.getenv("GLOBAL_DB_HOST")
        if not MONGO_URI:
            return
        client = MongoClient(MONGO_URI)
        client["HMS"]["hospital_admission"].update_one(
            {"ipNumber": str(ip)},
            {"$set": {
                "room_details":       room_details       if isinstance(room_details,       list) else _safe_list(room_details),
                "roomShitingDetails": shifting_details   if isinstance(shifting_details,   list) else _safe_list(shifting_details),
                "advance_payments":   advance_payments   if isinstance(advance_payments,   list) else _safe_list(advance_payments),
            }}
        )
    except Exception as ex:
        print(f"[_sync_to_mongo] Failed for {ip}: {ex}")


def _sync_advance_to_mongo(ip, adm_obj, payments_list):
    _sync_to_mongo(
        ip,
        _safe_list(adm_obj.room_details),
        _safe_list(adm_obj.roomShitingDetails),
        payments_list if isinstance(payments_list, list) else _safe_list(payments_list),
    )


def _save_admission(adm, room_details, shifting_details, advance_payments):
    rd  = room_details       if isinstance(room_details,       list) else _safe_list(room_details)
    sd  = shifting_details   if isinstance(shifting_details,   list) else _safe_list(shifting_details)
    ap  = advance_payments   if isinstance(advance_payments,   list) else _safe_list(advance_payments)

    adm.room_details       = rd
    adm.roomShitingDetails = sd
    adm.advance_payments   = ap

    adm.save()
    _sync_to_mongo(adm.ipNumber, rd, sd, ap)


# ─────────────────────────────────────────────────────────────────────────────
# Patient helpers
# ─────────────────────────────────────────────────────────────────────────────
def _build_patient_map(hospital_code):
    patient_map = {}
    for patient in Patient.objects.filter(hospital_code=hospital_code):
        key = str(patient.uhid or "").strip()
        if not key:
            continue
        dob = getattr(patient, "dob", None) or getattr(patient, "dateOfBirth", None)
        age_from_dob = _calc_age_from_dob(dob)
        patient_map[key] = {
            "uhid":                 key,
            "salutation":           str(patient.salutation  or ""),
            "firstName":            str(patient.firstName   or ""),
            "middleName":           str(getattr(patient, "middleName", "") or ""),
            "lastName":             str(patient.lastName    or ""),
            "dob":                  str(dob or ""),
            "age":                  age_from_dob or patient.age,
            "gender":               str(patient.gender      or ""),
            "mobilePhone":          str(patient.mobilePhone or ""),
            "permanent_address":    str(getattr(patient, "permanent_address", "") or ""),
            "area":                 str(getattr(patient, "area",    "") or ""),
            "zipcode":              str(getattr(patient, "zipcode", "") or ""),
            "city":                 str(getattr(patient, "city",    "") or ""),
            "state":                str(getattr(patient, "state",   "") or ""),
            "customerType":         str(getattr(patient, "customer_type", "") or
                                        getattr(patient, "customerType", "") or ""),
            "insuranceCompanyName": "",
            "company_code":         str(getattr(patient, "company_code", "") or ""),
        }
    return patient_map


def _enrich_with_patient(adm_data, hospital_code):
    uhid = str(adm_data.get("uhid") or "").strip()
    if not uhid:
        return adm_data
    try:
        pt = Patient.objects.filter(hospital_code=hospital_code, uhid=uhid).first()
        if not pt:
            return adm_data
        ins_name = ""
        company_code = str(getattr(pt, "company_code", "") or "")
        if company_code:
            try:
                prov = InsuranceProvider.objects.get(company_code=company_code)
                ins_name = prov.company_name
            except Exception:
                ins_name = company_code

        # Calculate age from DOB; fall back to stored age
        dob = getattr(pt, "dob", None) or getattr(pt, "dateOfBirth", None)
        age_from_dob = _calc_age_from_dob(dob)

        adm_data["salutation"]           = pt.salutation or ""
        adm_data["firstName"]            = pt.firstName  or ""
        adm_data["middleName"]           = getattr(pt, "middleName", "") or ""
        adm_data["lastName"]             = pt.lastName   or ""
        adm_data["dob"]                  = str(dob or "")
        adm_data["age"]                  = age_from_dob or pt.age
        adm_data["gender"]               = pt.gender     or ""
        adm_data["mobilePhone"]          = pt.mobilePhone or ""
        adm_data["permanent_address"]    = getattr(pt, "permanent_address", "") or ""
        adm_data["area"]                 = getattr(pt, "area",    "") or ""
        adm_data["zipcode"]              = getattr(pt, "zipcode", "") or ""
        adm_data["city"]                 = getattr(pt, "city",    "") or ""
        adm_data["state"]                = getattr(pt, "state",   "") or ""
        adm_data["customerType"]         = str(getattr(pt, "customer_type", "") or
                                               getattr(pt, "customerType", "") or "")
        adm_data["insuranceCompanyName"] = ins_name
        adm_data["company_code"]         = company_code
    except Exception:
        pass
    return adm_data


def _get_current_room(adm):
    details = _safe_list(adm.room_details)
    for r in reversed(details):
        if isinstance(r, dict) and r.get("is_roomActive"):
            return r
    return details[0] if details else {}


# ─────────────────────────────────────────────────────────────────────────────
# GET /admission-ip-preview/
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
        for adm in Admission.objects.filter(hospital_code=hospital_code, branch_code=branch_code, outlet_code=outlet_code):
            ip = adm.ipNumber or ""
            if "/" in ip:
                try:
                    p, n = ip.split("/")
                    if p == prefix:
                        max_num = max(max_num, int(n))
                except Exception:
                    continue
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
        patient_map   = _build_patient_map(hospital_code)
        admission_map = {}

        for admission in Admission.objects.all():
            details = _safe_list(getattr(admission, "room_details",       []))
            shifts  = _safe_list(getattr(admission, "roomShitingDetails", []))
            is_discharged  = bool(getattr(admission, "is_discharged", False))
            # ── NEW: use is_admitted + is_cancelled instead of is_admissionActive ──
            is_cancelled   = bool(getattr(admission, "is_cancelled",  False))
            is_admitted    = bool(getattr(admission, "is_admitted",   False))
            is_active_adm  = is_admitted and not is_cancelled and not is_discharged

            has_unclean_room = any(not bool(x.get("is_roomCleaned", False)) for x in (details + shifts))
            if not has_unclean_room and (is_discharged or not is_active_adm):
                continue

            uhid         = str(getattr(admission, "uhid",     "") or "").strip()
            ip_number    = str(getattr(admission, "ipNumber", "") or "")
            patient_info = patient_map.get(uhid, {"uhid": uhid})
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

        booking_map = {}
        try:
            for booking in RoomBooking.objects.filter(is_active=True):
                rno = str(booking.room_number or "").strip()
                bno = str(booking.bed_number  or "").strip()
                if rno and bno:
                    booking_map[(rno, bno)] = {
                        "ip_number": str(booking.ipNumber or ""),
                        "booking_date": str(booking.booking_date or ""),
                    }
        except Exception:
            pass

        for room in Room.objects.filter(hospital_code=hospital_code):
            room_no       = str(getattr(room, "room_number", "") or "").strip()
            room_is_blocked = str(getattr(room, "room_status", "")).strip().lower() == "blocked"
            if not room_no:
                continue
            beds_data = []
            for bed in _safe_list(getattr(room, "beds", [])):
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
            result.append({"room_number": room_no, "room_type": str(getattr(room, "room_type", "") or ""), "room_category": str(getattr(room, "room_category", "") or ""), "block": str(getattr(room, "block", "") or ""), "floor": getattr(room, "floor", ""), "beds": beds_data})

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
        query = {}
        if hospital_code:
            query["hospital_code"] = hospital_code
        if branch_code:
            query["branch_code"] = branch_code
        query["uhid"] = str(uhid)
        patient = Patient.objects.filter(**query).first()
        if not patient:
            return Response({"error": "Patient not found"}, status=404)

        from ..serializers import PatientSerializer
        serializer = PatientSerializer(patient)
        data = dict(serializer.data)

        # Calculate age from DOB and overwrite the age field
        dob = data.get("dob") or data.get("dateOfBirth") or getattr(patient, "dob", None) or getattr(patient, "dateOfBirth", None)
        age_from_dob = _calc_age_from_dob(dob)
        if age_from_dob:
            data["age"]     = age_from_dob
        data["dob"]         = str(dob or "")

        # Insurance name
        company_code = (data.get('company_code') or "").strip()
        if company_code:
            insurance = InsuranceProvider.objects.filter(company_code=company_code).first()
            data['company_name'] = insurance.company_name if insurance else None
        else:
            data['company_name'] = None

        return Response(data)
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
            from_date = to_date = None
            if from_date_str:
                try: from_date = datetime.strptime(from_date_str, '%Y-%m-%d').date()
                except: pass
            if to_date_str:
                try: to_date = datetime.strptime(to_date_str, '%Y-%m-%d').date()
                except: pass
            admissions = []
            for adm in Admission.objects.filter(hospital_code=hospital_code, branch_code=branch_code, outlet_code=outlet_code):
                if ip_filter:
                    ip = (adm.ipNumber or "").strip()
                    if "/" in ip_filter:
                        if ip.lower() != ip_filter.lower(): continue
                    else:
                        slash_idx = ip.rfind("/")
                        suffix = ip[slash_idx + 1:] if slash_idx != -1 else ip
                        if ip_filter.lower() not in suffix.lower(): continue
                if uhid_filter:
                    if str(adm.uhid or "").strip().lower() != uhid_filter.lower(): continue
                if status_filter == 'Admitted':
                    if not (adm.is_admitted and not adm.is_discharged): continue
                elif status_filter == 'Discharged':
                    if not adm.is_discharged: continue
                if from_date or to_date:
                    adm_date = None
                    if adm.admissionDateTime:
                        try: adm_date = adm.admissionDateTime.date()
                        except: pass
                    if adm_date:
                        if from_date and adm_date < from_date: continue
                        if to_date   and adm_date > to_date:   continue
                    else: continue
                if doctor_filter and doctor_filter.lower() not in (adm.admittingDoctor or '').lower(): continue
                admissions.append(adm)
            result = []
            for adm in admissions:
                d = {
                    "id": str(adm.pk),
                    "ipNumber":          adm.ipNumber,
                    "uhid":              adm.uhid,
                    "admissionDateTime": adm.admissionDateTime.isoformat() if adm.admissionDateTime else None,
                    "admittingDoctor":   adm.admittingDoctor   or "",
                    "consultingDoctor":  adm.consultingDoctor  or "",
                    "packageNo":         adm.packageName       or "",
                    "reasonForAdmission":adm.reasonForAdmission or "",
                    "room_details":      _safe_list(adm.room_details),
                    "roomShitingDetails":_safe_list(adm.roomShitingDetails),
                    "advance_payments":  _safe_list(adm.advance_payments),
                    # ── NEW status fields ──────────────────────────────────────
                    "is_cancelled":      bool(getattr(adm, "is_cancelled",    False)),
                    "cancelled_by":      getattr(adm, "cancelled_by",         None),
                    "cancelled_Reason":  getattr(adm, "cancelled_Reason",     None),
                    "is_edited":         bool(getattr(adm, "is_edited",       False)),
                    "edited_by":         getattr(adm, "edited_by",            None),
                    "edited_Reason":     getattr(adm, "edited_Reason",        None),
                    "ward_status":       getattr(adm, "ward_status",          ""),
                    # ──────────────────────────────────────────────────────────
                    "is_admitted":       bool(adm.is_admitted),
                    "is_discharged":     bool(adm.is_discharged),
                    "ipserial_number":   adm.ipserial_number,
                    "mlc_type":          adm.mlc_type     or "",
                    "mlc_remarks":       adm.mlc_remarks  or "",
                    "hospital_code":     adm.hospital_code,
                    "branch_code":       adm.branch_code,
                    "outlet_code":       adm.outlet_code,
                    "created_by":        adm.created_by,
                    "created_date":      adm.created_date.isoformat()       if hasattr(adm.created_date, 'isoformat') else adm.created_date if adm.created_date else None,
                    "lastmodified_by":   adm.lastmodified_by,
                    "lastmodified_date": adm.lastmodified_date.isoformat()  if hasattr(adm.lastmodified_date, 'isoformat') else adm.lastmodified_date if adm.lastmodified_date else None,
                }
                _enrich_with_patient(d, hospital_code)
                result.append(d)
            return JsonResponse({"success": True, "data": result})
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

            # ── Check for existing active admission (is_admitted and NOT cancelled/discharged) ──
            for adm in Admission.objects.filter(hospital_code=hospital_code, branch_code=branch_code, outlet_code=outlet_code):
                if (adm.uhid == uhid
                        and adm.is_admitted
                        and not adm.is_discharged
                        and not getattr(adm, "is_cancelled", False)):
                    return JsonResponse({
                        "error": "Patient already admitted",
                        "already_admitted": True,
                        "ipNumber": adm.ipNumber,
                        "admissionDateTime": adm.admissionDateTime.isoformat() if adm.admissionDateTime else None,
                        "roomNo": _get_current_room(adm).get("roomNo", ""),
                        "bedNo":  _get_current_room(adm).get("bedNo",  ""),
                    }, status=400)

            admission_dt = parse_datetime(str(data.get('admissionDateTime') or '')) or timezone.now()
            now_dt  = datetime.now()
            fy      = (now_dt.year - 2001) if now_dt.month < 4 else (now_dt.year - 2000)
            prefix  = f"S{fy:03d}"; max_num = 500000
            for adm in Admission.objects.filter(hospital_code=hospital_code, branch_code=branch_code, outlet_code=outlet_code):
                ip = adm.ipNumber or ""
                if "/" in ip:
                    try:
                        p, n = ip.split("/")
                        if p == prefix: max_num = max(max_num, int(n))
                    except: pass
            ip_number = f"{prefix}/{max_num + 1:06d}"
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
            adm = Admission.objects.create(
                uhid=uhid, ipNumber=ip_number, admissionDateTime=admission_dt,
                hospital_code=hospital_code, branch_code=branch_code, outlet_code=outlet_code,
                admittingDoctor=str(data.get('admittingDoctor') or ""),
                consultingDoctor=data.get('consultingDoctor'),
                packageName=str(data.get('packageNo') or "") if data.get('packageNo') else "",
                room_details=room_details, roomShitingDetails=[], advance_payments=[],
                reasonForAdmission=data.get('reasonForAdmission'),
                # ── NEW fields ──────────────────────────────────────────────
                is_cancelled=False, cancelled_by=None, cancelled_Reason=None,
                is_edited=False,    edited_by=None,    edited_Reason=None,
                ward_status=None,
                # ────────────────────────────────────────────────────────────
                is_discharged=False, is_admitted=True,
                created_by=employee_id, created_date=timezone.now(),
                lastmodified_by=employee_id, lastmodified_date=timezone.now(),
            )
            _sync_to_mongo(ip_number, room_details, [], [])
            d = {
                "id": str(adm.pk), "ipNumber": adm.ipNumber, "uhid": adm.uhid,
                "admissionDateTime": adm.admissionDateTime.isoformat() if adm.admissionDateTime else None,
                "admittingDoctor": adm.admittingDoctor or "", "consultingDoctor": adm.consultingDoctor or "",
                "packageNo": adm.packageName or "", "reasonForAdmission": adm.reasonForAdmission or "",
                "room_details": room_details, "roomShitingDetails": [], "advance_payments": [],
                "is_cancelled": False, "cancelled_by": None, "cancelled_Reason": None,
                "is_edited": False,    "edited_by": None,    "edited_Reason": None,
                "ward_status": None,
                "is_admitted": True, "is_discharged": False,
                "ipserial_number": adm.ipserial_number, "mlc_type": adm.mlc_type or "", "mlc_remarks": adm.mlc_remarks or "",
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
            return JsonResponse({'success': False, 'error': 'Admission not found'}, status=404)
        if not adm.is_admitted:
            return JsonResponse({'success': False, 'error': 'Admission inactive'}, status=404)

        def _patient_block(uhid):
            try:
                uhid = str(uhid).strip()
                if not uhid: return {}
                pt = Patient.objects.filter(hospital_code=hospital_code, uhid=uhid).first()
                if not pt: return {}
                ins_name = ""
                if getattr(pt, 'company_code', None):
                    try:
                        prov = InsuranceProvider.objects.get(company_code=pt.company_code)
                        ins_name = prov.company_name
                    except Exception:
                        ins_name = pt.company_code or ""
                dob = getattr(pt, "dob", None) or getattr(pt, "dateOfBirth", None)
                age_from_dob = _calc_age_from_dob(dob)
                return {
                    'salutation':    pt.salutation or "",
                    'firstName':     pt.firstName  or "",
                    'middleName':    getattr(pt, "middleName", "") or "",
                    'lastName':      pt.lastName   or "",
                    'dob':           str(dob or ""),
                    'age':           age_from_dob or pt.age,
                    'gender':        pt.gender     or "",
                    'mobilePhone':   pt.mobilePhone or "",
                    'permanent_address': getattr(pt, "permanent_address", "") or "",
                    'area':    getattr(pt, "area",    "") or "",
                    'zipcode': getattr(pt, "zipcode", "") or "",
                    'city':    getattr(pt, "city",    "") or "",
                    'state':   getattr(pt, "state",   "") or "",
                    'customerType': str(getattr(pt, "customer_type", "") or getattr(pt, "customerType", "") or ""),
                    'insuranceCompanyName': ins_name,
                    'company_code': getattr(pt, "company_code", "") or "",
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
                'mlc_type':   adm.mlc_type    or "",
                'mlc_remarks':adm.mlc_remarks  or "",
                'advance_payments': ap,
                # ── NEW status fields ────────────────────────────────────────
                'is_cancelled':     bool(getattr(adm, "is_cancelled",    False)),
                'cancelled_by':     getattr(adm, "cancelled_by",         None),
                'cancelled_Reason': getattr(adm, "cancelled_Reason",     None),
                'is_edited':        bool(getattr(adm, "is_edited",       False)),
                'edited_by':        getattr(adm, "edited_by",            None),
                'edited_Reason':    getattr(adm, "edited_Reason",        None),
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

                for f in ['admittingDoctor', 'consultingDoctor', 'reasonForAdmission', 'mlc_type', 'mlc_remarks']:
                    if f in data:
                        val = get_val(data.get(f))
                        setattr(adm, f, str(val) if val else "")
                if 'packageNo' in data:
                    val = get_val(data.get('packageNo'))
                    adm.packageName = str(val) if val else ""

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

                adm.is_edited          = True
                adm.edited_by          = employee_id
                adm.edited_Reason      = edit_reason
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


from ..models import Admission, Patient, IpAdvance_Refund

# ── helpers ──────────────────────────────────────────────────────────────────

def _safe_list(value):
    """Always return a real Python list of dicts, never a JSON string."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        import json
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


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
    Continuous, FY-scoped bill number across ALL admissions for this outlet —
    not just the current admission's advance_payments list. This is the fix
    for bill numbers always restarting at .../000001.
    """
    prefix = _financial_year_prefix()
    bill_numbers = []
    qs = Admission.objects.filter(
        hospital_code=hospital_code, branch_code=branch_code, outlet_code=outlet_code,
    )
    for adm in qs.iterator():
        for p in _safe_list(adm.advance_payments):
            if isinstance(p, dict) and p.get('bill_no'):
                bill_numbers.append(p['bill_no'])
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
    """
    Partial update: touches ONLY advance_payments + audit fields.
    Replaces the old pattern of loading room_details / roomShitingDetails and
    re-saving the entire Admission document just to change one JSON field.
    """
    updated = Admission.objects.filter(
        ipNumber=str(ip_number), hospital_code=hospital_code,
        branch_code=branch_code, outlet_code=outlet_code,
    ).update(
        advance_payments=advance_payments,
        lastmodified_by=employee_id,
        lastmodified_date=timezone.now(),
    )
    return updated


def _bill_type_fields(payload):
    """
    Pull ONLY bill_type + billTypeNo off the incoming payload — never persist
    the full bill-type document. The frontend gets the full list from the
    existing `bill-types/` endpoint and just sends these two back.
    """
    bill_type = payload.get('bill_type')
    bill_type_no = payload.get('billTypeNo') or payload.get('bill_type_no')
    return bill_type, bill_type_no


# ── view ─────────────────────────────────────────────────────────────────────

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

            if ip_number or uhid:
                admissions = [
                    a for a in Admission.objects.all()
                    if (not ip_number or str(a.ipNumber) == ip_number)
                    and (not uhid or str(a.uhid) == uhid)
                    and getattr(a, 'is_admitted', False)
                    and not getattr(a, 'is_cancelled', False)
                ]
            else:
                admissions = [
                    a for a in Admission.objects.all()
                    if getattr(a, 'is_admitted', False)
                    and not getattr(a, 'is_cancelled', False)
                ]

            if not admissions:
                return JsonResponse({'success': False, 'error': 'No matching admissions found'}, status=404)

            # ── Patient name lookup — works the same for ip_number OR uhid search.
            # Keys are normalised (stripped + upper-cased) on both sides so a
            # stray space / case mismatch between Admission.uhid and Patient.uhid
            # never silently drops the patient name.
            uhids = list({str(a.uhid).strip() for a in admissions if a.uhid})
            patient_map = {}
            for p in Patient.objects.filter(uhid__in=uhids):
                key = str(p.uhid).strip().upper()
                patient_map[key] = " ".join(filter(None, [p.salutation, p.firstName, p.lastName])).strip()

            advance_payments = []
            for adm in admissions:
                payments = _safe_list(adm.advance_payments)
                patient_key = str(adm.uhid).strip().upper()
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
                    p["ip_number"]    = adm.ipNumber
                    p["uhid"]         = adm.uhid
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
                                    p_date = datetime.strptime(date_value, "%Y-%m-%d").date()
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
            return JsonResponse({'success': False, 'error': 'Admission not found'}, status=404)

        ap = _safe_list(adm.advance_payments)

        # ── POST — create new advance ─────────────────────────────────────────
        if request.method == 'POST':
            amount = request.data.get('advance_amount')
            if not amount:
                return JsonResponse({'success': False, 'error': 'advance_amount is required'}, status=400)

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
                "advance_amount":   float(amount),
                "ip_advance":       float(request.data.get('ip_advance',      0)),
                "billing_advance":  float(request.data.get('billing_advance', 0)),
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

                # No partial / split refunds — must match the full advance amount.
                if abs(refund_amount - advance_total) > 0.001:
                    return JsonResponse(
                        {'success': False, 'error': f"Partial refunds are not allowed. Refund amount must equal the full advance amount of ₹{advance_total:.2f}"},
                        status=400,
                    )

                refund_bill_type, refund_bill_type_no = _bill_type_fields(request.data)
                if refund_bill_type is None or not refund_bill_type_no:
                    # fall back to the advance entry's own bill type if the caller didn't pick one
                    refund_bill_type, refund_bill_type_no = entry.get('bill_type'), entry.get('billTypeNo')

                refund_bill_no = _generate_refund_bill_no(hospital_code, branch_code, outlet_code)

                # 1) Persist the authoritative refund record in its own table.
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

                # 2) Keep a lightweight copy on the advance entry for fast display
                #    (still a real array, never a json.dumps string).
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
                entry['refund_details']     = [refund_record]   # single record only — no splits
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
                    "bill_no":          original_bill_no,   # bill number is preserved across an edit
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