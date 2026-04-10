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
from datetime import datetime


# ──────────────────────────────────────────────────────────────────────────────
# Safe JSON field parser
# Handles: real list, JSON string, Python repr string (OrderedDict), None
# ──────────────────────────────────────────────────────────────────────────────
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


# ──────────────────────────────────────────────────────────────────────────────
# Normalize a single admission object — convert string fields to real lists
# ──────────────────────────────────────────────────────────────────────────────
def _normalize_admission(adm_data):
    adm_data['room_details']       = parse_json_field(adm_data.get('room_details'))
    adm_data['roomShitingDetails'] = parse_json_field(adm_data.get('roomShitingDetails'))
    adm_data['advance_payments']   = parse_json_field(adm_data.get('advance_payments'))
    return adm_data


# ──────────────────────────────────────────────────────────────────────────────
# Build patient lookup map — hospital_code only (patients have null branch)
# ──────────────────────────────────────────────────────────────────────────────
def _build_patient_map(hospital_code):
    patient_map = {}
    for patient in Patient.objects.filter(hospital_code=hospital_code):
        key = str(patient.uhid or "").strip()
        if not key:
            continue
        patient_map[key] = {
            "uhid":               key,
            "salutation":         str(patient.salutation  or ""),
            "firstName":          str(patient.firstName   or ""),
            "middleName":         str(getattr(patient, "middleName", "") or ""),
            "lastName":           str(patient.lastName    or ""),
            "age":                patient.age,
            "gender":             str(patient.gender      or ""),
            "mobilePhone":        str(patient.mobilePhone or ""),
            "permanent_address":  str(getattr(patient, "permanent_address", "") or ""),
            "area":               str(getattr(patient, "area",    "") or ""),
            "zipcode":            str(getattr(patient, "zipcode", "") or ""),
            "city":               str(getattr(patient, "city",    "") or ""),
            "state":              str(getattr(patient, "state",   "") or ""),
            "customerType":       str(getattr(patient, "customer_type", "") or
                                      getattr(patient, "customerType", "") or ""),
            "insuranceCompanyName": "",
            "company_code":       str(getattr(patient, "company_code", "") or ""),
        }
    return patient_map


# ──────────────────────────────────────────────────────────────────────────────
# Enrich a single admission dict with patient data
# ──────────────────────────────────────────────────────────────────────────────
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

        adm_data["salutation"]           = pt.salutation or ""
        adm_data["firstName"]            = pt.firstName  or ""
        adm_data["middleName"]           = getattr(pt, "middleName", "") or ""
        adm_data["lastName"]             = pt.lastName   or ""
        adm_data["age"]                  = pt.age
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


# ──────────────────────────────────────────────────────────────────────────────
# Helper: get the currently active room entry from a model instance
# ──────────────────────────────────────────────────────────────────────────────
def _get_current_room(adm):
    """Return the currently active room_details entry dict, or {} if none."""
    details = parse_json_field(adm.room_details)
    for r in reversed(details):
        if isinstance(r, dict) and r.get("is_roomActive"):
            return r
    return details[0] if details else {}


# ──────────────────────────────────────────────────────────────────────────────
# RENAMED: ip-number-preview  →  GET /admission-ip-preview/
# Permission key: HMS-P-ADMIT-IP-PREVIEW
# URL: path('admission-ip-preview/', admission.get_next_ip_number, name='admission_ip_preview')
# Perm mapping: r'^/_b_a_c_k_e_n_d/HMS/admission-ip-preview/?(\?.*)?$': 'HMS-P-ADMIT-IP-PREVIEW'
# ──────────────────────────────────────────────────────────────────────────────
@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def get_next_ip_number(request):
    try:
        hospital_code = (
            request.data.get("auth-hospital-code") or
            request.headers.get("auth-hospital-code") or "system"
        )
        branch_code = (
            request.data.get("auth-branch-code") or
            request.headers.get("Branch-Code") or "system"
        )
        outlet_code = (
            request.data.get("auth-outlet-code") or
            request.headers.get("Outlet-Code") or "system"
        )

        now    = datetime.now()
        fy     = (now.year - 2001) if now.month < 4 else (now.year - 2000)
        prefix = f"S{fy:03d}"
        max_num = 500000

        for adm in Admission.objects.filter(
            hospital_code=hospital_code,
            branch_code=branch_code,
            outlet_code=outlet_code
        ):
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


# ──────────────────────────────────────────────────────────────────────────────
# RENAMED: room-availability  →  GET /admission-room-search/
# Permission key: HMS-P-ADMIT-ROOM-SEARCH
# URL: path('admission-room-search/', admission.search_rooms, name='admission_room_search')
# Perm mapping: r'^/_b_a_c_k_e_n_d/HMS/admission-room-search/?(\?.*)?$': 'HMS-P-ADMIT-ROOM-SEARCH'
# ──────────────────────────────────────────────────────────────────────────────
@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def search_rooms(request):
    try:
        hospital_code = (
            request.data.get("auth-hospital-code") or
            request.headers.get("auth-hospital-code") or "system"
        )
        result = []
        patient_map   = _build_patient_map(hospital_code)
        admission_map = {}

        for admission in Admission.objects.all():
            if bool(getattr(admission, "is_discharged", False)):
                continue

            details = parse_json_field(getattr(admission, "room_details",       []))
            shifts  = parse_json_field(getattr(admission, "roomShitingDetails", []))

            has_unclean_room = any(
                not bool(x.get("is_roomCleaned", False))
                for x in (details + shifts)
            )
            if (not bool(getattr(admission, "is_admissionActive", False))
                    and not has_unclean_room):
                continue

            uhid         = str(getattr(admission, "uhid",     "") or "").strip()
            ip_number    = str(getattr(admission, "ipNumber", "") or "")
            patient_info = patient_map.get(uhid, {"uhid": uhid})

            active_shift  = None
            active_shifts = [s for s in shifts if bool(s.get("is_roomActive", False))]
            if active_shifts:
                try:
                    active_shift = max(
                        active_shifts,
                        key=lambda s: int(str(s.get("shifting_id", "0")).replace("SH", ""))
                    )
                except Exception:
                    active_shift = active_shifts[-1]

            for shift in shifts:
                room_no    = str(shift.get("newRoomNo", "")).strip()
                bed_no     = str(shift.get("newBedNo",  "")).strip()
                if not room_no or not bed_no:
                    continue
                is_active  = bool(shift.get("is_roomActive",  False))
                is_cleaned = bool(shift.get("is_roomCleaned", False))

                if active_shift and shift == active_shift:
                    status = "Occupied"; patient_data = patient_info
                elif is_cleaned:
                    status = "Available"; patient_data = {}
                else:
                    status = "Available - Not Cleaned"; patient_data = patient_info

                key      = (room_no, bed_no)
                existing = admission_map.get(key)
                if (existing is None or status == "Occupied"
                        or existing.get("status") != "Occupied"):
                    admission_map[key] = {
                        "status": status, "patient": patient_data,
                        "ip_number": ip_number,
                        "is_roomActive": is_active, "is_roomCleaned": is_cleaned,
                        "source": "roomShitingDetails",
                    }

            has_shifts = len(shifts) > 0
            for entry in details:
                room_no    = str(entry.get("roomNo", "")).strip()
                bed_no     = str(entry.get("bedNo",  "")).strip()
                if not room_no or not bed_no:
                    continue
                is_active  = bool(entry.get("is_roomActive",  False))
                is_cleaned = bool(entry.get("is_roomCleaned", False))

                if has_shifts:
                    if is_cleaned:
                        status = "Available"; patient_data = {}
                    else:
                        status = "Available - Not Cleaned"; patient_data = patient_info
                else:
                    if is_active:
                        status = "Occupied"; patient_data = patient_info
                    elif is_cleaned:
                        status = "Available"; patient_data = {}
                    else:
                        status = "Available - Not Cleaned"; patient_data = patient_info

                key      = (room_no, bed_no)
                existing = admission_map.get(key)
                if existing is None:
                    admission_map[key] = {
                        "status": status, "patient": patient_data,
                        "ip_number": ip_number,
                        "is_roomActive": is_active, "is_roomCleaned": is_cleaned,
                        "source": "room_details",
                    }
                elif existing.get("status") != "Occupied" and status == "Occupied":
                    admission_map[key] = {
                        "status": status, "patient": patient_data,
                        "ip_number": ip_number,
                        "is_roomActive": is_active, "is_roomCleaned": is_cleaned,
                        "source": "room_details",
                    }

        booking_map = {}
        for booking in RoomBooking.objects.all():
            if not bool(getattr(booking, "is_booked", False)) or bool(getattr(booking, "room_shifted", False)):
                continue
            room_no = str(getattr(booking, "room_number", "") or "").strip()
            bed_no  = str(getattr(booking, "bed_number",  "") or "").strip()
            if not room_no or not bed_no:
                continue
            booking_map[(room_no, bed_no)] = {
                "ip_number": str(getattr(booking, "ip_number", "") or "").strip(),
                "uhid":      str(getattr(booking, "uhid",      "") or "").strip(),
            }

        room_number_filter = str(request.GET.get("room_number",   "")).strip()
        category_filter    = str(request.GET.get("room_category", "")).strip()
        block_filter       = str(request.GET.get("block",         "")).strip()
        floor_filter       = str(request.GET.get("floor",         "")).strip()

        for room in Room.objects.all():
            if not bool(getattr(room, "is_active", False)):
                continue
            room_no = str(getattr(room, "room_number", "")).strip()
            if room_number_filter and room_number_filter.lower() not in room_no.lower():
                continue
            if category_filter and str(getattr(room, "room_category", "")).strip() != category_filter:
                continue
            if block_filter and str(getattr(room, "block", "")).strip() != block_filter:
                continue
            if floor_filter:
                try:
                    if int(getattr(room, "floor", 0)) != int(floor_filter):
                        continue
                except Exception:
                    continue

            beds_data = []
            beds = parse_json_field(getattr(room, "beds", []))
            for bed in beds:
                if not isinstance(bed, dict):
                    continue
                bed_number = str(bed.get("bed_number", "")).strip()
                if not bed_number:
                    continue
                key = (room_no, bed_number)
                if (bool(getattr(room, "room_blocked", False))
                        or str(getattr(room, "room_status", "")).strip().lower() == "blocked"):
                    beds_data.append({
                        "bed_number": bed_number, "status": "Maintenance",
                        "patient": {}, "ip_number": "", "booking": None,
                        "is_roomActive": False, "is_roomCleaned": True,
                    })
                    continue
                info = admission_map.get(key)
                if info:
                    beds_data.append({
                        "bed_number":     bed_number,
                        "status":         info.get("status",       "Available"),
                        "patient":        info.get("patient",      {}),
                        "ip_number":      info.get("ip_number",    ""),
                        "booking":        None,
                        "is_roomActive":  info.get("is_roomActive",  False),
                        "is_roomCleaned": info.get("is_roomCleaned", False),
                    })
                    continue
                booking_info = booking_map.get(key)
                if booking_info:
                    beds_data.append({
                        "bed_number": bed_number, "status": "Reserved",
                        "patient": {}, "ip_number": booking_info.get("ip_number", ""),
                        "booking": booking_info,
                        "is_roomActive": False, "is_roomCleaned": True,
                    })
                    continue
                beds_data.append({
                    "bed_number": bed_number, "status": "Available",
                    "patient": {}, "ip_number": "", "booking": None,
                    "is_roomActive": False, "is_roomCleaned": True,
                })

            result.append({
                "room_number":   room_no,
                "room_type":     str(getattr(room, "room_type",     "") or ""),
                "room_category": str(getattr(room, "room_category", "") or ""),
                "block":         str(getattr(room, "block",         "") or ""),
                "floor":         getattr(room, "floor", ""),
                "beds":          beds_data,
            })

        return Response(result, status=200)

    except Exception as exc:
        traceback.print_exc()
        return Response({"success": False, "error": f"Room availability failed: {str(exc)}"}, status=500)



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
            from_date_str = request.GET.get('from_date', '').strip()
            to_date_str   = request.GET.get('to_date',   '').strip()
            status_filter = request.GET.get('status',    '').strip()
            doctor_filter = request.GET.get('admitting_doctor', '').strip()

            from_date = to_date = None
            if from_date_str:
                try: from_date = datetime.strptime(from_date_str, '%Y-%m-%d').date()
                except: pass
            if to_date_str:
                try: to_date = datetime.strptime(to_date_str, '%Y-%m-%d').date()
                except: pass

            admissions = []
            for adm in Admission.objects.filter(
                hospital_code=hospital_code,
                branch_code=branch_code,
                outlet_code=outlet_code
            ):
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
                    else:
                        continue

                if doctor_filter and doctor_filter.lower() not in (adm.admittingDoctor or '').lower():
                    continue

                admissions.append(adm)

            result = []
            for adm in admissions:
                d = {
                    "id":                 str(adm.pk),
                    "ipNumber":           adm.ipNumber,
                    "uhid":               adm.uhid,
                    "admissionDateTime":  adm.admissionDateTime.isoformat() if adm.admissionDateTime else None,
                    "admittingDoctor":    adm.admittingDoctor  or "",
                    "consultingDoctor":   adm.consultingDoctor or "",
                    # packageName field stores packageNo — return as "packageNo" for frontend resolution
                    "packageNo":          adm.packageName or "",
                    "reasonForAdmission": adm.reasonForAdmission or "",
                    "room_details":       parse_json_field(adm.room_details),
                    "roomShitingDetails": parse_json_field(adm.roomShitingDetails),
                    "advance_payments":   parse_json_field(adm.advance_payments),
                    "is_admissionActive": bool(adm.is_admissionActive),
                    "is_advanceActive":   bool(adm.is_advanceActive),
                    "is_admitted":        bool(adm.is_admitted),
                    "is_discharged":      bool(adm.is_discharged),
                    "ipserial_number":    adm.ipserial_number,
                    "mlc_type":           adm.mlc_type    or "",
                    "mlc_remarks":        adm.mlc_remarks or "",
                    "hospital_code":      adm.hospital_code,
                    "branch_code":        adm.branch_code,
                    "outlet_code":        adm.outlet_code,
                    "created_by":         adm.created_by,
                    "created_date":       adm.created_date.isoformat() if adm.created_date else None,
                    "lastmodified_by":    adm.lastmodified_by,
                    "lastmodified_date":  adm.lastmodified_date.isoformat() if adm.lastmodified_date else None,
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

            for adm in Admission.objects.filter(
                hospital_code=hospital_code,
                branch_code=branch_code,
                outlet_code=outlet_code
            ):
                if adm.uhid == uhid and adm.is_admitted and not adm.is_discharged:
                    return JsonResponse({
                        "error": "Patient already admitted",
                        "already_admitted": True,
                        "ipNumber": adm.ipNumber,
                    }, status=400)

            admission_dt = parse_datetime(str(data.get('admissionDateTime') or '')) or timezone.now()

            now_dt  = datetime.now()
            fy      = (now_dt.year - 2001) if now_dt.month < 4 else (now_dt.year - 2000)
            prefix  = f"S{fy:03d}"
            max_num = 500000
            for adm in Admission.objects.filter(
                hospital_code=hospital_code,
                branch_code=branch_code,
                outlet_code=outlet_code
            ):
                ip = adm.ipNumber or ""
                if "/" in ip:
                    try:
                        p, n = ip.split("/")
                        if p == prefix: max_num = max(max_num, int(n))
                    except: pass

            ip_number = f"{prefix}/{max_num + 1:06d}"
            now_iso   = datetime.now().isoformat()

            room_details = [{
                "room_entry_id":  1,
                "roomNo":         str(data.get("roomNo") or ""),
                "bedNo":          str(data.get("bedNo")  or ""),
                "is_roomActive":  True,
                "is_roomCleaned": False,
                "startDateTime":  now_iso,
                "endDateTime":    None,
            }]

            # Store packageNo value in the packageName field (model has no packageNo column)
            package_no_value = data.get('packageNo') or ""

            adm = Admission.objects.create(
                uhid=uhid,
                ipNumber=ip_number,
                admissionDateTime=admission_dt,
                hospital_code=hospital_code,
                branch_code=branch_code,
                outlet_code=outlet_code,
                admittingDoctor=str(data.get('admittingDoctor') or ""),
                consultingDoctor=data.get('consultingDoctor'),
                # packageName field stores packageNo value
                packageName=str(package_no_value) if package_no_value else "",
                room_details=room_details,
                roomShitingDetails=[],
                advance_payments=[],
                reasonForAdmission=data.get('reasonForAdmission'),
                is_admissionActive=True,
                is_advanceActive=False,
                is_discharged=False,
                is_admitted=True,
                created_by=employee_id,
                created_date=timezone.now(),
                lastmodified_by=employee_id,
                lastmodified_date=timezone.now(),
            )

            d = {
                "id":                str(adm.pk),
                "ipNumber":          adm.ipNumber,
                "uhid":              adm.uhid,
                "admissionDateTime": adm.admissionDateTime.isoformat() if adm.admissionDateTime else None,
                "admittingDoctor":   adm.admittingDoctor  or "",
                "consultingDoctor":  adm.consultingDoctor or "",
                # Return stored packageNo so frontend resolves display name from packages API
                "packageNo":         adm.packageName or "",
                "reasonForAdmission": adm.reasonForAdmission or "",
                "room_details":      parse_json_field(adm.room_details),
                "roomShitingDetails": [],
                "advance_payments":  [],
                "is_admissionActive": bool(adm.is_admissionActive),
                "is_advanceActive":   bool(adm.is_advanceActive),
                "is_admitted":        bool(adm.is_admitted),
                "is_discharged":      bool(adm.is_discharged),
                "ipserial_number":    adm.ipserial_number,
                "mlc_type":           adm.mlc_type    or "",
                "mlc_remarks":        adm.mlc_remarks or "",
            }
            _enrich_with_patient(d, hospital_code)

            return JsonResponse({"success": True, "message": "Admission created successfully", "data": d}, status=201)

        except Exception as e:
            traceback.print_exc()
            return JsonResponse({"success": False, "error": str(e)}, status=500)


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def admission_detail(request, ipNumber):
    try:
        employee_id   = (request.data.get('auth-user-id')       or request.headers.get('auth-user-id')       or "system")
        hospital_code = (request.data.get("auth-hospital-code") or request.headers.get("auth-hospital-code") or "system")
        branch_code   = (request.data.get("auth-branch-code")   or request.headers.get("Branch-Code")        or "system")
        outlet_code   = (request.data.get("auth-outlet-code")   or request.headers.get("Outlet-Code")        or "system")

        # ✅ STRICT FILTER
        adm = Admission.objects.filter(
            ipNumber=str(ipNumber),
            hospital_code=hospital_code,
            branch_code=branch_code,
            outlet_code=outlet_code,
        ).first()

        if not adm:
            return JsonResponse({'success': False, 'error': 'Admission not found'}, status=404)

        if not adm.is_admitted:
            return JsonResponse({'success': False, 'error': 'Admission inactive'}, status=404)

        def _patient_block(uhid):
            try:
                uhid = str(uhid).strip()
                if not uhid:
                    return {}

                pt = Patient.objects.filter(
                    hospital_code=hospital_code,
                    uhid=uhid
                ).first()

                if not pt:
                    return {}

                ins_name = ""
                if getattr(pt, 'company_code', None):
                    try:
                        prov = InsuranceProvider.objects.get(
                            company_code=pt.company_code
                        )
                        ins_name = prov.company_name
                    except:
                        ins_name = pt.company_code or ""

                return {
                    'salutation': pt.salutation or "",
                    'firstName': pt.firstName or "",
                    'middleName': getattr(pt, "middleName", "") or "",
                    'lastName': pt.lastName or "",
                    'age': pt.age,
                    'gender': pt.gender or "",
                    'mobilePhone': pt.mobilePhone or "",
                    'permanent_address': getattr(pt, "permanent_address", "") or "",
                    'area': getattr(pt, "area", "") or "",
                    'zipcode': getattr(pt, "zipcode", "") or "",
                    'city': getattr(pt, "city", "") or "",
                    'state': getattr(pt, "state", "") or "",
                    'customerType': str(
                        getattr(pt, "customer_type", "") or
                        getattr(pt, "customerType", "") or ""
                    ),
                    'insuranceCompanyName': ins_name,
                    'company_code': getattr(pt, "company_code", "") or "",
                }

            except Exception:
                return {}

        def _build_result(adm):
            room_details = parse_json_field(adm.room_details)
            room_shifting_details = parse_json_field(adm.roomShitingDetails)
            advance_payments = parse_json_field(adm.advance_payments)
            current_room = _get_current_room(adm)

            return {
                'id': str(adm.pk),
                'ipNumber': adm.ipNumber,
                'uhid': adm.uhid,

                'admissionDateTime':
                    adm.admissionDateTime.isoformat()
                    if adm.admissionDateTime else None,

                'admittingDoctor': adm.admittingDoctor or "",
                'consultingDoctor': adm.consultingDoctor or "",

                'packageNo': adm.packageName or "",

                'roomNo': current_room.get('roomNo', ''),
                'bedNo': current_room.get('bedNo', ''),

                'reasonForAdmission': adm.reasonForAdmission or "",
                'mlc_type': adm.mlc_type or "",
                'mlc_remarks': adm.mlc_remarks or "",

                'advance_payments': advance_payments,

                'is_admissionActive': bool(adm.is_admissionActive),
                'is_advanceActive': bool(adm.is_advanceActive),
                'is_admitted': bool(adm.is_admitted),
                'is_discharged': bool(adm.is_discharged),

                'ipserial_number': adm.ipserial_number,

                'room_details': room_details,
                'roomShitingDetails': room_shifting_details,

                **_patient_block(str(adm.uhid or "")),
            }

        # ---------------- GET ----------------

        if request.method == 'GET':
            return JsonResponse({
                "success": True,
                "data": _build_result(adm)
            })

        # ---------------- PUT ----------------

        elif request.method == 'PUT':

            data = request.data

            def get_val(v):
                return v[0] if isinstance(v, list) else v

            # Normal field updates
            for f in [
                'admittingDoctor',
                'consultingDoctor',
                'reasonForAdmission',
                'mlc_type',
                'mlc_remarks'
            ]:
                if f in data:
                    val = get_val(data.get(f))
                    setattr(adm, f, str(val) if val else "")

            if 'packageNo' in data:
                val = get_val(data.get('packageNo'))
                adm.packageName = str(val) if val else ""

            # Update active room_details entry directly
            new_room_no = str(get_val(data.get("roomNo")) or "").strip()
            new_bed_no = str(get_val(data.get("bedNo")) or "").strip()

            if new_room_no or new_bed_no:
                room_details = parse_json_field(adm.room_details)

                if not isinstance(room_details, list):
                    room_details = []

                active_room = next(
                    (
                        room for room in room_details
                        if isinstance(room, dict) and room.get("is_roomActive")
                    ),
                    None
                )

                if active_room:
                    if new_room_no:
                        active_room["roomNo"] = new_room_no

                    if new_bed_no:
                        active_room["bedNo"] = new_bed_no

                    active_room["lastmodified_by"] = employee_id
                    active_room["lastmodified_date"] = timezone.now().isoformat()

                # Always assign back a list, never None
                adm.room_details = room_details

            adm.lastmodified_by = employee_id
            adm.lastmodified_date = timezone.now()
            adm.save()

            return JsonResponse({
                "success": True,
                "message": "Updated successfully",
                "data": _build_result(adm)
            })

        # ---------------- DELETE ----------------

        elif request.method == 'DELETE':

            now_iso = timezone.now().isoformat()

            room_details = parse_json_field(adm.room_details)
            room_shifting_details = parse_json_field(adm.roomShitingDetails)

            # Deactivate active room entries in room_details
            for room in room_details:
                if isinstance(room, dict) and room.get("is_roomActive"):
                    room["is_roomActive"] = False
                    if not room.get("endDateTime"):
                        room["endDateTime"] = now_iso

            # Deactivate active room entries in roomShitingDetails
            for room in room_shifting_details:
                if isinstance(room, dict) and room.get("is_roomActive"):
                    room["is_roomActive"] = False
                    if not room.get("endDateTime"):
                        room["endDateTime"] = now_iso

            adm.room_details = room_details
            adm.roomShitingDetails = room_shifting_details

            adm.is_admissionActive = False
            adm.is_admitted = False
            adm.lastmodified_by = employee_id
            adm.lastmodified_date = timezone.now()

            adm.save()

            return JsonResponse({
                "success": True,
                "message": "Admission cancelled successfully"
            })
    except Exception as e:
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)