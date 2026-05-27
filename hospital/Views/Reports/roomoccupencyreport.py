from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from pyauth.auth import HasRoleAndDataPermission
from pymongo import MongoClient
import os
import json
import ast
from datetime import datetime, date, timedelta
from ...models import Admission, Patient, Room


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
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


def get_doctor_mapping(client):
    try:
        global_db = client['Global']
        diagnostics_collection = global_db['backend_diagnostics_profile']
        doctors = list(diagnostics_collection.find(
            {"designation": "DESIG094"},
            {"employeeId": 1, "employeeName": 1, "_id": 0}
        ))
        return {d['employeeId']: d['employeeName'] for d in doctors if d.get('employeeId')}
    except:
        return {}


def serialize_doc(doc):
    if isinstance(doc, dict):
        return {k: serialize_doc(v) for k, v in doc.items()}
    elif isinstance(doc, list):
        return [serialize_doc(i) for i in doc]
    elif isinstance(doc, datetime):
        return doc.isoformat()
    return doc


def parse_dt(val):
    """Coerce various datetime representations to a naive datetime."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.replace(tzinfo=None)
    if isinstance(val, date):
        return datetime.combine(val, datetime.min.time())
    if isinstance(val, str):
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(val[:19], fmt)
            except ValueError:
                continue
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Current Room Occupancy Report
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def room_occupancy_report_view(request):
    """
    Get report of currently occupied rooms based on active admissions.
    Allows filtering by room_category, block, floor, and admitting_doctor.
    """
    try:
        hospital_code = (
            request.data.get('auth-hospital-code')
            or request.headers.get('auth-hospital-code')
            or request.META.get('HTTP_AUTH_HOSPITAL_CODE')
            or 'system'
        )
        branch_code = (
            request.data.get('auth-branch-code')
            or request.headers.get('auth-branch-code')
            or request.headers.get('Branch-Code')
            or request.headers.get('Branch_Code')
            or request.META.get('HTTP_BRANCH_CODE')
        )

        if hospital_code == 'system' and branch_code:
            first_adm = Admission.objects.filter(branch_code=branch_code).first()
            if first_adm:
                hospital_code = getattr(first_adm, 'hospital_code', 'system')
            else:
                first_room = Room.objects.filter(branch_code=branch_code).first()
                if first_room:
                    hospital_code = getattr(first_room, 'hospital_code', 'system')

        category_filter = request.GET.get('room_category', '').strip()
        block_filter    = request.GET.get('block', '').strip()
        floor_filter    = request.GET.get('floor', '').strip()
        doctor_filter   = request.GET.get('admitting_doctor', '').strip()

        admission_query = {"hospital_code": hospital_code}
        if branch_code:
            admission_query["branch_code"] = branch_code

        admissions = Admission.objects.filter(**admission_query)
        admissions = [
            adm for adm in admissions
            if getattr(adm, "is_admissionActive", False) is True
            and getattr(adm, "is_discharged", True) is False
            and getattr(adm, "is_admitted", False) is True
        ]

        uhids = list(set(adm.uhid for adm in admissions if adm.uhid))
        patient_map = {p.uhid: p for p in Patient.objects.filter(uhid__in=uhids, hospital_code=hospital_code)}

        room_query = {"hospital_code": hospital_code}
        if branch_code:
            room_query["branch_code"] = branch_code
        rooms = [r for r in Room.objects.filter(**room_query) if getattr(r, "is_active", False) is True]
        room_map = {r.room_number: r for r in rooms}

        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        doctor_map = get_doctor_mapping(client)
        client.close()

        def resolve_doctor_name(doc_id):
            return doctor_map.get(doc_id, doc_id) if doc_id else 'N/A'

        results = []
        for adm in admissions:
            room_no = bed_no = None

            shifts = parse_json_field(adm.roomShitingDetails)
            active_shift_rooms = [r for r in shifts if r.get("is_roomActive") in (True, "True", "true", 1, "1")]
            if active_shift_rooms:
                latest = active_shift_rooms[-1]
                room_no = latest.get("newRoomNo")
                bed_no  = latest.get("newBedNo")

            if room_no is None:
                details = parse_json_field(adm.room_details)
                active_rooms = [r for r in details if r.get("is_roomActive") in (True, "True", "true", 1, "1")]
                if active_rooms:
                    room_no = active_rooms[-1].get("roomNo")
                    bed_no  = active_rooms[-1].get("bedNo")
                elif details:
                    room_no = details[-1].get("roomNo")
                    bed_no  = details[-1].get("bedNo")

            if not room_no or not bed_no:
                continue

            room_obj      = room_map.get(str(room_no))
            room_category = getattr(room_obj, 'room_category', 'N/A') if room_obj else 'N/A'
            block         = getattr(room_obj, 'block', 'N/A') if room_obj else 'N/A'
            floor         = getattr(room_obj, 'floor', 'N/A') if room_obj else 'N/A'
            room_type     = getattr(room_obj, 'room_type', 'N/A') if room_obj else 'N/A'

            if category_filter and category_filter.lower() not in str(room_category).lower():
                continue
            if block_filter and block_filter.lower() not in str(block).lower():
                continue
            if floor_filter and str(floor_filter) != str(floor):
                continue

            doc_name = resolve_doctor_name(adm.admittingDoctor)
            if doctor_filter and doctor_filter.lower() not in doc_name.lower() and doctor_filter.lower() not in str(adm.admittingDoctor).lower():
                continue

            patient      = patient_map.get(adm.uhid)
            patient_name = f"{patient.firstName} {patient.lastName}".strip() if patient else "Unknown"
            age          = getattr(patient, 'age', 'N/A') if patient else 'N/A'
            gender       = getattr(patient, 'gender', 'N/A') if patient else 'N/A'
            mobile       = getattr(patient, 'mobilePhone', 'N/A') if patient else 'N/A'

            results.append({
                "roomNo":            room_no,
                "bedNo":             bed_no,
                "roomCategory":      room_category,
                "roomType":          room_type,
                "block":             block,
                "floor":             floor,
                "ipNumber":          adm.ipNumber,
                "uhid":              adm.uhid,
                "patientName":       patient_name,
                "age":               age,
                "gender":            gender,
                "mobile":            mobile,
                "admissionDateTime": adm.admissionDateTime,
                "admittingDoctor":   doc_name,
                "admittingDoctorId": adm.admittingDoctor,
                "packageName":       adm.packageName or "N/A"
            })

        try:
            results.sort(key=lambda x: (str(x["roomNo"]), str(x["bedNo"])))
        except:
            pass

        return Response(serialize_doc(results), status=200)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"error": str(e)}, status=500)


# ─────────────────────────────────────────────────────────────────────────────
# Previous Day / Date-Specific Room Occupancy Report
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def previous_day_room_occupancy_view(request):
    """
    Returns room occupancy as it stood at END-OF-DAY for a given target_date.

    Logic — a patient counts as 'occupied' on target_date if:
      1. Their admissionDateTime <= EOD of target_date
      2. AND they were NOT fully discharged before SOD of target_date
         (i.e. dischargeDateTime >= SOD, or is_admissionActive=True)

    Query param: target_date=YYYY-MM-DD  (defaults to yesterday)
    """
    try:
        hospital_code = (
            request.data.get('auth-hospital-code')
            or request.headers.get('auth-hospital-code')
            or request.META.get('HTTP_AUTH_HOSPITAL_CODE')
            or 'system'
        )
        branch_code = (
            request.data.get('auth-branch-code')
            or request.headers.get('auth-branch-code')
            or request.headers.get('Branch-Code')
            or request.META.get('HTTP_BRANCH_CODE')
        )

        if hospital_code == 'system' and branch_code:
            first_adm = Admission.objects.filter(branch_code=branch_code).first()
            if first_adm:
                hospital_code = getattr(first_adm, 'hospital_code', 'system')

        # Target date — defaults to yesterday
        target_date_str = request.GET.get('target_date', '')
        if target_date_str:
            try:
                target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
            except ValueError:
                return Response({"error": "Invalid target_date format. Use YYYY-MM-DD."}, status=400)
        else:
            target_date = date.today() - timedelta(days=1)

        sod = datetime.combine(target_date, datetime.min.time())   # 00:00:00
        eod = datetime.combine(target_date, datetime.max.time())   # 23:59:59.999999

        category_filter = request.GET.get('room_category', '').strip()
        doctor_filter   = request.GET.get('admitting_doctor', '').strip()

        # ── 1. Fetch ALL admissions for this hospital ──
        admission_query = {"hospital_code": hospital_code}
        if branch_code:
            admission_query["branch_code"] = branch_code
        all_admissions = list(Admission.objects.filter(**admission_query))

        # ── 2. Keep only admissions that overlapped with the target date ──
        candidates = []
        for adm in all_admissions:
            adm_dt = parse_dt(adm.admissionDateTime)
            if adm_dt is None or adm_dt > eod:
                continue                                   # admitted after target date

            # Still active (not yet discharged)
            if getattr(adm, "is_admissionActive", False) is True:
                candidates.append(adm)
                continue

            # Discharged — include only if discharge was on or after SOD
            discharge_dt = parse_dt(getattr(adm, "dischargeDateTime", None))
            if discharge_dt is not None and discharge_dt >= sod:
                candidates.append(adm)
                continue

            # Edge case: is_discharged flag is False even without discharge date
            if getattr(adm, "is_discharged", True) is False:
                candidates.append(adm)

        # ── 3. Build supporting maps ──
        uhids = list(set(adm.uhid for adm in candidates if adm.uhid))
        patient_map = {p.uhid: p for p in Patient.objects.filter(uhid__in=uhids, hospital_code=hospital_code)}

        room_query = {"hospital_code": hospital_code}
        if branch_code:
            room_query["branch_code"] = branch_code
        rooms = [r for r in Room.objects.filter(**room_query) if getattr(r, "is_active", False) is True]
        room_map = {r.room_number: r for r in rooms}

        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        doctor_map = get_doctor_mapping(client)
        client.close()

        def resolve_doctor_name(doc_id):
            return doctor_map.get(doc_id, doc_id) if doc_id else 'N/A'

        # ── 4. Build result rows ──
        results = []
        for adm in candidates:
            room_no = bed_no = None

            # Room shifting history — find last shift active on or before EOD
            shifts = parse_json_field(adm.roomShitingDetails)
            for shift in reversed(shifts):
                shift_dt = parse_dt(shift.get("startDateTime") or shift.get("shiftDateTime"))
                if shift_dt and shift_dt <= eod:
                    room_no = shift.get("newRoomNo")
                    bed_no  = shift.get("newBedNo")
                    break

            if room_no is None:
                details = parse_json_field(adm.room_details)
                for det in reversed(details):
                    det_dt = parse_dt(det.get("startDateTime"))
                    if det_dt and det_dt <= eod:
                        room_no = det.get("roomNo")
                        bed_no  = det.get("bedNo")
                        break
                if room_no is None and details:
                    room_no = details[-1].get("roomNo")
                    bed_no  = details[-1].get("bedNo")

            if not room_no or not bed_no:
                continue

            room_obj      = room_map.get(str(room_no))
            room_category = getattr(room_obj, 'room_category', 'N/A') if room_obj else 'N/A'
            block         = getattr(room_obj, 'block', 'N/A') if room_obj else 'N/A'
            floor         = getattr(room_obj, 'floor', 'N/A') if room_obj else 'N/A'
            room_type     = getattr(room_obj, 'room_type', 'N/A') if room_obj else 'N/A'

            if category_filter and category_filter.lower() not in str(room_category).lower():
                continue

            doc_name = resolve_doctor_name(adm.admittingDoctor)
            if doctor_filter and doctor_filter.lower() not in doc_name.lower() and doctor_filter.lower() not in str(adm.admittingDoctor).lower():
                continue

            patient      = patient_map.get(adm.uhid)
            patient_name = f"{patient.firstName} {patient.lastName}".strip() if patient else "Unknown"
            age          = getattr(patient, 'age', 'N/A') if patient else 'N/A'
            gender       = getattr(patient, 'gender', 'N/A') if patient else 'N/A'
            mobile       = getattr(patient, 'mobilePhone', 'N/A') if patient else 'N/A'

            # Compute status label for this record
            is_active    = getattr(adm, "is_admissionActive", False) is True
            discharge_dt = parse_dt(getattr(adm, "dischargeDateTime", None))
            if is_active:
                status = "Still Active"
            elif discharge_dt and discharge_dt.date() == target_date:
                status = "Discharged on this Date"
            elif discharge_dt and discharge_dt.date() > target_date:
                status = "Active on Date"
            else:
                status = "Discharged"

            results.append({
                "roomNo":            room_no,
                "bedNo":             bed_no,
                "roomCategory":      room_category,
                "roomType":          room_type,
                "block":             block,
                "floor":             floor,
                "ipNumber":          adm.ipNumber,
                "uhid":              adm.uhid,
                "patientName":       patient_name,
                "age":               age,
                "gender":            gender,
                "mobile":            mobile,
                "admissionDateTime": adm.admissionDateTime,
                "dischargeDateTime": getattr(adm, "dischargeDateTime", None),
                "admittingDoctor":   doc_name,
                "packageName":       adm.packageName or "N/A",
                "status":            status,
            })

        try:
            results.sort(key=lambda x: (str(x["roomNo"]), str(x["bedNo"])))
        except:
            pass

        return Response(serialize_doc(results), status=200)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"error": str(e)}, status=500)
