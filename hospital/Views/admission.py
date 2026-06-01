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
# FIXED: search_rooms — GET /admission-room-search/
#
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  BUG SUMMARY                                                            ║
# ╠══════════════════════════════════════════════════════════════════════════╣
# ║                                                                          ║
# ║  [BUG 1 — ROOT CAUSE] ★ CRITICAL ★                                      ║
# ║  `if is_discharged: continue` ran BEFORE the has_unclean_room check.    ║
# ║  Result: discharged patients with unclean rooms were skipped entirely,   ║
# ║  so those beds appeared as "Available" instead of "Not Cleaned".         ║
# ║                                                                          ║
# ║  Fix: compute has_unclean_room FIRST, then skip only if:                ║
# ║    (is_discharged OR not is_admissionActive) AND has_unclean_room=False  ║
# ║                                                                          ║
# ║  [BUG 2]                                                                 ║
# ║  room_details loop: is_roomActive=True was ignored when shifts exist.    ║
# ║  Fix: is_roomActive=True always → Occupied, regardless of shifts.        ║
# ║                                                                          ║
# ║  [BUG 3]                                                                 ║
# ║  Per-bed bed_status="Blocked" was never checked for Maintenance.         ║
# ║  Fix: check bed.get("bed_status") == "Blocked" per bed entry.            ║
# ║                                                                          ║
# ║  [BUG 4]                                                                 ║
# ║  admission_map key: shifting entry (Occupied) could be overwritten by    ║
# ║  a room_details entry (Not Cleaned). Tightened overwrite guard.          ║
# ╚══════════════════════════════════════════════════════════════════════════╝
#
# STATUS RULES (applied per bed entry):
#   is_roomActive=True  + is_roomCleaned=False  →  Occupied
#   is_roomActive=False + is_roomCleaned=False  →  Available - Not Cleaned
#   is_roomActive=False + is_roomCleaned=True   →  Available
#   bed_status="Blocked" in beds[]              →  Maintenance
#   room_blocked=True / room_status="blocked"   →  Maintenance (all beds)
#   RoomBooking.is_booked=True                  →  Reserved
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

        result        = []
        patient_map   = _build_patient_map(hospital_code)
        admission_map = {}

        # =====================================================================
        # STEP 1 — BUILD admission_map  {(room_no, bed_no): {...}}
        # =====================================================================
        for admission in Admission.objects.all():

            details = parse_json_field(getattr(admission, "room_details",       []))
            shifts  = parse_json_field(getattr(admission, "roomShitingDetails", []))

            is_discharged = bool(getattr(admission, "is_discharged",     False))
            is_active_adm = bool(getattr(admission, "is_admissionActive", False))

            # Does this admission still own at least one unclean bed?
            has_unclean_room = any(
                not bool(x.get("is_roomCleaned", False))
                for x in (details + shifts)
            )

            # BUG 1 FIX:
            # OLD: if is_discharged: continue   ← skipped BEFORE unclean check
            # NEW: skip only when nothing useful to show
            #      i.e. all beds cleaned AND (discharged OR inactive)
            if not has_unclean_room and (is_discharged or not is_active_adm):
                continue

            uhid         = str(getattr(admission, "uhid",     "") or "").strip()
            ip_number    = str(getattr(admission, "ipNumber", "") or "")
            patient_info = patient_map.get(uhid, {"uhid": uhid})

            # Active shift: highest shifting_id that has is_roomActive=True
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

            # ── roomShiftingDetails ───────────────────────────────────────────
            for shift in shifts:
                room_no = str(shift.get("newRoomNo", "")).strip()
                bed_no  = str(shift.get("newBedNo",  "")).strip()
                if not room_no or not bed_no:
                    continue

                s_active  = bool(shift.get("is_roomActive",  False))
                s_cleaned = bool(shift.get("is_roomCleaned", False))

                if active_shift and shift == active_shift:
                    status = "Occupied"
                    patient_data = patient_info
                elif s_cleaned:
                    status = "Available"
                    patient_data = {}
                else:
                    status = "Available - Not Cleaned"
                    patient_data = patient_info

                key      = (room_no, bed_no)
                existing = admission_map.get(key)
                if (existing is None
                        or status == "Occupied"
                        or existing.get("status") != "Occupied"):
                    admission_map[key] = {
                        "status":         status,
                        "patient":        patient_data,
                        "ip_number":      ip_number,
                        "is_roomActive":  s_active,
                        "is_roomCleaned": s_cleaned,
                        "source":         "roomShitingDetails",
                    }

            # ── room_details ──────────────────────────────────────────────────
            for entry in details:
                room_no = str(entry.get("roomNo", "")).strip()
                bed_no  = str(entry.get("bedNo",  "")).strip()
                if not room_no or not bed_no:
                    continue

                e_active  = bool(entry.get("is_roomActive",  False))
                e_cleaned = bool(entry.get("is_roomCleaned", False))

                # BUG 2 FIX: is_roomActive=True always → Occupied
                if e_active:
                    status = "Occupied"
                    patient_data = patient_info
                elif e_cleaned:
                    status = "Available"
                    patient_data = {}
                else:
                    status = "Available - Not Cleaned"
                    patient_data = patient_info

                key      = (room_no, bed_no)
                existing = admission_map.get(key)

                # BUG 4 FIX: never downgrade Occupied to Not Cleaned
                if existing is None:
                    admission_map[key] = {
                        "status":         status,
                        "patient":        patient_data,
                        "ip_number":      ip_number,
                        "is_roomActive":  e_active,
                        "is_roomCleaned": e_cleaned,
                        "source":         "room_details",
                    }
                elif existing.get("status") != "Occupied" and status == "Occupied":
                    admission_map[key] = {
                        "status":         status,
                        "patient":        patient_data,
                        "ip_number":      ip_number,
                        "is_roomActive":  e_active,
                        "is_roomCleaned": e_cleaned,
                        "source":         "room_details",
                    }
                # else: keep existing — do not overwrite Occupied with anything lower

        # =====================================================================
        # STEP 2 — BOOKING MAP  {(room_no, bed_no): {...}}
        # =====================================================================
        booking_map = {}
        for booking in RoomBooking.objects.all():
            if not bool(getattr(booking, "is_booked",     False)):
                continue
            if bool(getattr(booking, "room_shifted", False)):
                continue
            room_no = str(getattr(booking, "room_number", "") or "").strip()
            bed_no  = str(getattr(booking, "bed_number",  "") or "").strip()
            if not room_no or not bed_no:
                continue
            booking_map[(room_no, bed_no)] = {
                "ip_number": str(getattr(booking, "ip_number", "") or "").strip(),
                "uhid":      str(getattr(booking, "uhid",      "") or "").strip(),
            }

        # =====================================================================
        # STEP 3 — FILTERS
        # =====================================================================
        room_number_filter = str(request.GET.get("room_number",   "")).strip()
        category_filter    = str(request.GET.get("room_category", "")).strip()
        block_filter       = str(request.GET.get("block",         "")).strip()
        floor_filter       = str(request.GET.get("floor",         "")).strip()

        # =====================================================================
        # STEP 4 — ROOM LOOP → build result
        # =====================================================================
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

            # Room-level block → all beds are Maintenance
            room_is_blocked = (
                bool(getattr(room, "room_blocked", False))
                or str(getattr(room, "room_status", "")).strip().lower() == "blocked"
            )

            beds_data = []
            beds = parse_json_field(getattr(room, "beds", []))

            for bed in beds:
                if not isinstance(bed, dict):
                    continue
                bed_number = str(bed.get("bed_number", "")).strip()
                if not bed_number:
                    continue

                key = (room_no, bed_number)

                # BUG 3 FIX: check per-bed bed_status="Blocked"
                bed_is_blocked = (
                    str(bed.get("bed_status", "")).strip().lower() == "blocked"
                )

                if room_is_blocked or bed_is_blocked:
                    beds_data.append({
                        "bed_number":     bed_number,
                        "status":         "Maintenance",
                        "patient":        {},
                        "ip_number":      "",
                        "booking":        None,
                        "is_roomActive":  False,
                        "is_roomCleaned": True,
                    })
                    continue

                # Admission match
                info = admission_map.get(key)
                if info:
                    beds_data.append({
                        "bed_number":     bed_number,
                        "status":         info.get("status",         "Available"),
                        "patient":        info.get("patient",         {}),
                        "ip_number":      info.get("ip_number",       ""),
                        "booking":        None,
                        "is_roomActive":  info.get("is_roomActive",   False),
                        "is_roomCleaned": info.get("is_roomCleaned",  False),
                    })
                    continue

                # Booking match → Reserved
                booking_info = booking_map.get(key)
                if booking_info:
                    beds_data.append({
                        "bed_number":     bed_number,
                        "status":         "Reserved",
                        "patient":        {},
                        "ip_number":      booking_info.get("ip_number", ""),
                        "booking":        booking_info,
                        "is_roomActive":  False,
                        "is_roomCleaned": True,
                    })
                    continue

                # No match → Available
                beds_data.append({
                    "bed_number":     bed_number,
                    "status":         "Available",
                    "patient":        {},
                    "ip_number":      "",
                    "booking":        None,
                    "is_roomActive":  False,
                    "is_roomCleaned": True,
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
        return Response(
            {"success": False, "error": f"Room availability failed: {str(exc)}"},
            status=500,
        )

        
@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def admission_view(request):

    employee_id   = (request.data.get('auth-user-id')       or request.headers.get('auth-user-id')       or "system")
    hospital_code = (request.data.get("auth-hospital-code") or request.headers.get("auth-hospital-code") or "system")
    branch_code   = (request.data.get("auth-branch-code")   or request.headers.get("Branch-Code")        or "system")
    outlet_code   = (request.data.get("auth-outlet-code")   or request.headers.get("Outlet-Code")        or "system")
    print("*****************", employee_id, hospital_code, branch_code, outlet_code)

    # ── GET ───────────────────────────────────────────────────────────────────
    if request.method == 'GET':
        try:
            from_date_str = request.GET.get('from_date',        '').strip()
            to_date_str   = request.GET.get('to_date',          '').strip()
            status_filter = request.GET.get('status',           '').strip()
            doctor_filter = request.GET.get('admitting_doctor', '').strip()
            ip_filter     = request.GET.get('ip_number',        '').strip()  # ← NEW

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
                # ── IP Number filter ─────────────────────────────────────────
                # Full IP typed  (contains "/") → exact match:  "S026/500008" == ipNumber
                # Suffix typed   (no "/")       → suffix match: "500008" in "S026/500008"
                if ip_filter:
                    ip = (adm.ipNumber or "").strip()
                    if "/" in ip_filter:
                        # Full IP: must match exactly (case-insensitive)
                        if ip.lower() != ip_filter.lower():
                            continue
                    else:
                        # Suffix match: "500008" matches "S026/500008", "S027/500008" …
                        slash_idx = ip.rfind("/")
                        suffix = ip[slash_idx + 1:] if slash_idx != -1 else ip
                        if ip_filter.lower() not in suffix.lower():
                            continue

                # ── Status filter ────────────────────────────────────────────
                if status_filter == 'Admitted':
                    if not (adm.is_admitted and not adm.is_discharged): continue
                elif status_filter == 'Discharged':
                    if not adm.is_discharged: continue

                # ── Date filter ──────────────────────────────────────────────
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

                # ── Doctor filter ────────────────────────────────────────────
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
                    "packageNo":          adm.packageName or "",
                    "reasonForAdmission": adm.reasonForAdmission or "",
                    "room_details":       parse_json_field(adm.room_details),
                    "roomShitingDetails": parse_json_field(adm.roomShitingDetails),
                    "advance_payments":   parse_json_field(adm.advance_payments),
                    "is_admissionActive": bool(adm.is_admissionActive),
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
                packageName=str(package_no_value) if package_no_value else "",
                room_details=room_details,
                roomShitingDetails=[],
                advance_payments=[],
                reasonForAdmission=data.get('reasonForAdmission'),
                is_admissionActive=True,
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
                "packageNo":         adm.packageName or "",
                "reasonForAdmission": adm.reasonForAdmission or "",
                "room_details":      parse_json_field(adm.room_details),
                "roomShitingDetails": [],
                "advance_payments":  [],
                "is_admissionActive": bool(adm.is_admissionActive),
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
        

        
        

# ──────────────────────────────────────────────────────────────────────────────
#   admission_detail  (GET / PUT / DELETE)  — unchanged from original
# ──────────────────────────────────────────────────────────────────────────────
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
        # ✅ SUPPORT BOTH IP AND UHID
        adm = Admission.objects.filter(
            Q(ipNumber=str(ipNumber)) | Q(uhid=str(ipNumber)),
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

                now_iso = timezone.now().isoformat()

                # STEP 1: Find active room
                active_room = next(
                    (
                        room for room in room_details
                        if isinstance(room, dict) and room.get("is_roomActive")
                    ),
                    None
                )

                # STEP 2: Close existing active room
                if active_room:
                    active_room["is_roomActive"] = False
                    active_room["endDateTime"] = now_iso
                    active_room["lastmodified_by"] = employee_id
                    active_room["lastmodified_date"] = now_iso

                    prev_room_no = active_room.get("roomNo", "")
                    prev_bed_no = active_room.get("bedNo", "")
                else:
                    prev_room_no = ""
                    prev_bed_no = ""

                # STEP 3: Create new room entry
                new_entry = {
                    "room_entry_id": len(room_details) + 1,
                    "roomNo": new_room_no or prev_room_no,
                    "bedNo": new_bed_no or prev_bed_no,
                    "is_roomActive": True,
                    "is_roomCleaned": False,
                    "startDateTime": now_iso,
                    "endDateTime": None,
                    "created_by": employee_id,
                    "created_date": now_iso,
                    "lastmodified_by": employee_id,
                    "lastmodified_date": now_iso
                }

                room_details.append(new_entry)

                # STEP 4: Assign back
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
    

# ──────────────────────────────────────────────────────────────────────────────
#   admission_advance  (GET / POST / PATCH / PUT)
# ──────────────────────────────────────────────────────────────────────────────
@api_view(['GET', 'POST', 'PATCH', 'PUT'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def admission_advance(request, ipNumber=None):
    try:
        employee_id   = request.data.get('auth-user-id')       or request.headers.get('auth-user-id')       or "system"
        hospital_code = request.data.get("auth-hospital-code") or request.headers.get("auth-hospital-code") or "system"
        branch_code   = request.data.get("auth-branch-code")   or request.headers.get("Branch-Code")        or "system"
        outlet_code   = request.data.get("auth-outlet-code")   or request.headers.get("Outlet-Code")        or "system"

        now_iso = timezone.now().isoformat()

        # =====================================================================
        # GET — list advances (unchanged)
        # =====================================================================
        if request.method == 'GET':
            ip_number = request.GET.get("ip_number", "").strip()
            uhid      = request.GET.get("uhid", "").strip()
            from_date = request.GET.get("from_date", "").strip()
            to_date   = request.GET.get("to_date", "").strip()

            if not ip_number and not uhid and not (from_date and to_date):
                return JsonResponse(
                    {'success': False, 'error': 'Provide ip_number/uhid or date range'},
                    status=400
                )

            # ── Fetch admissions ──────────────────────────────────────────────
            if ip_number or uhid:
                admissions = [
                    a for a in Admission.objects.all()
                    if (not ip_number or str(a.ipNumber) == ip_number)
                    and (not uhid or str(a.uhid) == uhid)
                    and getattr(a, 'is_admitted', False)
                    and getattr(a, 'is_admissionActive', False)
                ]
            else:
                admissions = [
                    a for a in Admission.objects.all()
                    if getattr(a, 'is_admitted', False)
                    and getattr(a, 'is_admissionActive', False)
                ]

            if not admissions:
                return JsonResponse({'success': False, 'error': 'No matching admissions found'}, status=404)

            # ── Patient name map ──────────────────────────────────────────────
            uhids = list(set(str(a.uhid) for a in admissions))
            patient_map = {}
            for p in Patient.objects.filter(uhid__in=uhids):
                full_name = " ".join(filter(None, [p.salutation, p.firstName, p.lastName])).strip()
                patient_map[str(p.uhid)] = full_name

            # ── Collect payments ──────────────────────────────────────────────
            advance_payments = []
            for adm in admissions:
                payments = parse_json_field(adm.advance_payments)
                if not isinstance(payments, list):
                    continue

                for p in payments:
                    if not isinstance(p, dict):
                        continue

                    # Skip history-only entries
                    if p.get('status') == 'Edited':
                        continue

                    # ── Extract convenience fields ────────────────────────────
                    payment_mode = ""
                    if isinstance(p.get("payment_details"), dict):
                        payment_mode = p["payment_details"].get("method", "")

                    paid_date = p.get("paid_datetime") or ""
                    if isinstance(paid_date, datetime):
                        paid_date = paid_date.isoformat()

                    p["ip_number"]    = adm.ipNumber
                    p["uhid"]         = adm.uhid
                    p["patient_name"] = patient_map.get(str(adm.uhid), "")
                    p["payment_mode"] = payment_mode
                    p["paid_date"]    = paid_date

                    # ── Ensure refund_details is always a list ────────────────
                    if not isinstance(p.get("refund_details"), list):
                        p["refund_details"] = []

                    advance_payments.append(p)

            # ── Date filter ───────────────────────────────────────────────────
            if from_date and to_date:
                try:
                    from_dt = datetime.strptime(from_date, "%Y-%m-%d").date()
                    to_dt   = datetime.strptime(to_date,   "%Y-%m-%d").date()
                    filtered = []
                    for p in advance_payments:
                        date_value = (
                            p.get('created_date') or
                            p.get('bill_date')    or
                            p.get('date')
                        )
                        if not date_value:
                            continue
                        try:
                            if isinstance(date_value, datetime):
                                p_date = date_value.date()
                            elif isinstance(date_value, str):
                                if 'T' in date_value:
                                    p_date = datetime.fromisoformat(
                                        date_value.replace('Z', '+00:00')
                                    ).date()
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
                    return JsonResponse(
                        {'success': False, 'error': f'Invalid date format: {str(e)}'},
                        status=400
                    )

            return JsonResponse({'success': True, 'data': advance_payments})

        # =====================================================================
        # POST / PATCH / PUT — require ipNumber in URL
        # =====================================================================
        adm = Admission.objects.filter(
            ipNumber=str(ipNumber),
            hospital_code=hospital_code,
            branch_code=branch_code,
            outlet_code=outlet_code,
        ).first()

        if not adm:
            return JsonResponse({'success': False, 'error': 'Admission not found'}, status=404)

        advance_payments = parse_json_field(adm.advance_payments)
        if not isinstance(advance_payments, list):
            advance_payments = []

        # ── Bill number generator ─────────────────────────────────────────────
        def generate_bill_number(payments_list):
            today_dt = timezone.now()
            year, month = today_dt.year, today_dt.month
            if month >= 4:
                fy = f"{year % 100:02d}{(year + 1) % 100:02d}"
            else:
                fy = f"{(year - 1) % 100:02d}{year % 100:02d}"
            existing_sequences = []
            for p in payments_list:
                if isinstance(p, dict) and p.get('bill_no'):
                    try:
                        seq = int(p['bill_no'].split('/')[-1])
                        existing_sequences.append(seq)
                    except Exception:
                        pass
            next_seq = max(existing_sequences, default=0) + 1
            return f"{fy}/{next_seq:06d}"

        # ─────────────────────────────────────────────────────────────────────
        # POST — create new advance (unchanged)
        # ─────────────────────────────────────────────────────────────────────
        if request.method == 'POST':
            amount = request.data.get('advance_amount')
            if not amount:
                return JsonResponse(
                    {'success': False, 'error': 'advance_amount is required'},
                    status=400
                )

            new_entry = {
                "advance_id":       f"ADV{len(advance_payments) + 1}",
                "bill_no":          generate_bill_number(advance_payments),
                "date":             request.data.get('date', now_iso[:10]),
                "bill_date":        now_iso,
                "advance_amount":   float(amount),
                "ip_advance":       float(request.data.get('ip_advance', 0)),
                "billing_advance":  float(request.data.get('billing_advance', 0)),
                "is_advanceActive": True,
                "status":           "Pending",
                "created_by":       employee_id,
                "created_date":     now_iso,
                "is_refund":        False,
                "refund_details":   [],
            }
            advance_payments.append(new_entry)
            adm.advance_payments = advance_payments
            adm.save()
            return JsonResponse({'success': True, 'data': new_entry})

        # ─────────────────────────────────────────────────────────────────────
        # PATCH — cancel  OR  refund  (based on action field)
        # ─────────────────────────────────────────────────────────────────────
        elif request.method == 'PATCH':
            advance_id = request.data.get('advance_id', '').strip()
            action     = request.data.get('action', 'cancel').strip().lower()

            # ── Find target entry ─────────────────────────────────────────────
            entry = next(
                (a for a in advance_payments if a.get('advance_id') == advance_id),
                None
            )
            if not entry:
                return JsonResponse(
                    {'success': False, 'error': f'Advance entry "{advance_id}" not found'},
                    status=404
                )

            # =================================================================
            # ACTION: cancel
            # =================================================================
            if action == 'cancel':
                if not entry.get('is_advanceActive'):
                    return JsonResponse(
                        {'success': False, 'error': 'Advance is already inactive'},
                        status=400
                    )
                if entry.get('status') == 'Cancelled':
                    return JsonResponse(
                        {'success': False, 'error': 'Advance is already cancelled'},
                        status=400
                    )

                entry['is_advanceActive'] = False
                entry['status']           = 'Cancelled'
                entry['cancelled_by']     = employee_id
                entry['cancelled_date']   = now_iso

                adm.advance_payments = advance_payments
                adm.save()
                return JsonResponse({'success': True, 'data': entry})

            # =================================================================
            # ACTION: refund
            # =================================================================
            elif action == 'refund':
                # ── Guards ────────────────────────────────────────────────────
                current_status = entry.get('status')
                if current_status not in ('Paid',):
                    return JsonResponse(
                        {
                            'success': False,
                            'error': f"Refund is only allowed for Paid advances. "
                                     f"Current status: '{current_status}'"
                        },
                        status=400
                    )

                # ── Parse refund amount ───────────────────────────────────────
                raw_refund = request.data.get('refund_amount')
                if raw_refund is None:
                    return JsonResponse(
                        {'success': False, 'error': 'refund_amount is required'},
                        status=400
                    )
                try:
                    refund_amount = float(raw_refund)
                except (TypeError, ValueError):
                    return JsonResponse(
                        {'success': False, 'error': 'refund_amount must be a valid number'},
                        status=400
                    )
                if refund_amount <= 0:
                    return JsonResponse(
                        {'success': False, 'error': 'refund_amount must be greater than 0'},
                        status=400
                    )

                # ── Compute how much has already been refunded ─────────────
                refund_history = entry.get('refund_details', [])
                if not isinstance(refund_history, list):
                    refund_history = []

                total_already_refunded = sum(
                    float(r.get('refunded_amount', 0)) for r in refund_history
                )
                advance_total   = float(entry.get('advance_amount', 0))
                remaining       = advance_total - total_already_refunded

                if refund_amount > remaining + 0.001:   # tiny float tolerance
                    return JsonResponse(
                        {
                            'success': False,
                            'error': (
                                f"Refund amount ₹{refund_amount:.2f} exceeds "
                                f"refundable balance ₹{remaining:.2f}"
                            )
                        },
                        status=400
                    )

                # ── Build refund record ───────────────────────────────────────
                new_total_refunded  = total_already_refunded + refund_amount
                new_remaining       = advance_total - new_total_refunded
                is_fully_refunded   = new_remaining <= 0.001   # float tolerance

                refund_record = {
                    "refund_id":               f"REF{len(refund_history) + 1}",
                    "refunded_amount":         f"{refund_amount:.2f}",
                    "refunded_date":           now_iso,
                    "refunded_by":             employee_id,
                    "payment_mode":            request.data.get('payment_mode', 'Cash'),
                    "remarks":                 request.data.get('remarks', ''),
                    "total_refunded_so_far":   f"{new_total_refunded:.2f}",
                    "remaining_balance":       f"{max(0, new_remaining):.2f}",
                }

                # ── Append and update entry ───────────────────────────────────
                refund_history.append(refund_record)
                entry['refund_details']   = refund_history
                entry['is_refund']        = True

                # If fully refunded, mark status = "Refunded"
                if is_fully_refunded:
                    entry['status']           = 'Refunded'
                    entry['is_advanceActive'] = False
                    entry['fully_refunded_date'] = now_iso
                # Partial refund — keep status as Paid / Pending
                # (status stays what it was; only is_refund flag is set)

                adm.advance_payments = advance_payments
                adm.save()

                return JsonResponse({
                    'success': True,
                    'data': {
                        'advance_entry':        entry,
                        'refund_record':        refund_record,
                        'total_refunded':       f"{new_total_refunded:.2f}",
                        'remaining_balance':    f"{max(0, new_remaining):.2f}",
                        'is_fully_refunded':    is_fully_refunded,
                    }
                })

            else:
                return JsonResponse(
                    {'success': False, 'error': f'Unknown action "{action}". Use "cancel" or "refund".'},
                    status=400
                )

        # ─────────────────────────────────────────────────────────────────────
        # PUT — edit an advance (unchanged)
        # ─────────────────────────────────────────────────────────────────────
        elif request.method == 'PUT':
            advance_id = request.data.get('advance_id', '').strip()
            amount     = request.data.get('advance_amount')

            if not advance_id:
                return JsonResponse(
                    {'success': False, 'error': 'advance_id is required'},
                    status=400
                )
            if not amount:
                return JsonResponse(
                    {'success': False, 'error': 'advance_amount is required'},
                    status=400
                )

            original = next(
                (a for a in advance_payments if a.get('advance_id') == advance_id),
                None
            )
            if not original:
                return JsonResponse(
                    {'success': False, 'error': 'Advance entry not found'},
                    status=404
                )
            if original.get('status') != 'Pending':
                return JsonResponse(
                    {
                        'success': False,
                        'error': f"Cannot edit — status is '{original.get('status')}'"
                    },
                    status=400
                )

            original_bill_no = original.get('bill_no')

            # Mark original as Edited
            original['is_advanceActive'] = False
            original['status']           = 'Edited'
            original['edited_by']        = employee_id
            original['edited_date']      = now_iso

            # Create new entry — reuse same bill_no
            new_entry = {
                "advance_id":       f"ADV{len(advance_payments) + 1}",
                "bill_no":          original_bill_no,
                "date":             request.data.get('date', now_iso[:10]),
                "bill_date":        now_iso,
                "advance_amount":   float(amount),
                "ip_advance":       float(request.data.get('ip_advance', 0)),
                "billing_advance":  float(request.data.get('billing_advance', 0)),
                "is_advanceActive": True,
                "status":           "Pending",
                "created_by":       employee_id,
                "created_date":     now_iso,
                "edited_from":      advance_id,
                "is_refund":        False,
                "refund_details":   [],
            }

            advance_payments.append(new_entry)
            adm.advance_payments = advance_payments
            adm.save()

            return JsonResponse({
                'success': True,
                'data': {
                    'original':  original,
                    'new_entry': new_entry,
                }
            })

    except Exception as e:
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)}, status=500)