from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from ..models import SurgerySchedule, OTMaster, AnesMaster
from ..serializers import SurgeryScheduleSerializer, SurgeryScheduleWriteSerializer
from pyauth.auth import HasRoleAndDataPermission
from django.utils import timezone
from django.db import connections
import traceback, json
from datetime import datetime, date as date_type


# ─── ID Generator ─────────────────────────────────────────────────────────────
def generate_reference_no():
    today = datetime.today()
    if today.month < 4:
        financial_year = f"{(today.year - 1) % 100:02d}{today.year % 100:02d}"
    else:
        financial_year = f"{today.year % 100:02d}{(today.year + 1) % 100:02d}"

    prefix = f"SUR{financial_year}/"

    try:
        records = SurgerySchedule.objects.all().values("reference_no")
        max_num = 0
        for r in records:
            ref = r.get("reference_no", "") or ""
            if ref.startswith(prefix):
                try:
                    seq = int(ref[len(prefix):])
                    if seq > max_num:
                        max_num = seq
                except (ValueError, TypeError):
                    pass
        return f"{prefix}{str(max_num + 1).zfill(5)}"
    except Exception:
        return f"{prefix}00001"


# ─── BULK LOOKUP HELPERS ──────────────────────────────────────────────────────

def _bulk_get_patient_info(ip_numbers: set) -> dict:
    if not ip_numbers:
        return {}
    try:
        from ..models import Admission, Patient, InsuranceProvider

        # Step 1: ip_number → uhid
        admissions = list(
            Admission.objects.filter(ipNumber__in=ip_numbers)
            .values("ipNumber", "uhid")
        )
        if not admissions:
            return {}

        ip_to_uhid = {a["ipNumber"]: a["uhid"] for a in admissions}
        uhids = set(ip_to_uhid.values())

        # Step 2: uhid → Patient
        patients = list(
            Patient.objects.filter(uhid__in=uhids)
            .values("uhid", "salutation", "firstName", "lastName",
                    "age", "gender", "customer_type", "company_code")
        )
        uhid_to_patient = {p["uhid"]: p for p in patients}

        # Step 3: company_code → company_name
        company_codes = {p["company_code"] for p in patients if p.get("company_code")}
        code_to_name = {}
        if company_codes:
            insurers = InsuranceProvider.objects.filter(
                company_code__in=company_codes
            ).values("company_code", "company_name")
            code_to_name = {i["company_code"]: i["company_name"] for i in insurers}

        # Step 4: assemble result keyed by ip_number
        result = {}
        for ip_num, uhid in ip_to_uhid.items():
            pt         = uhid_to_patient.get(uhid, {})
            salutation = (pt.get("salutation") or "").strip()
            first      = (pt.get("firstName")  or "").strip()
            last       = (pt.get("lastName")   or "").strip()
            full_name  = " ".join(filter(None, [salutation, first, last])) or None
            cc         = pt.get("company_code")

            result[ip_num] = {
                "uhid":          uhid,
                "patient_name":  full_name,
                "age":           pt.get("age"),
                "gender":        pt.get("gender"),
                "customer_type": pt.get("customer_type"),
                "company_name":  code_to_name.get(cc) if cc else None,
            }

        return result

    except Exception as e:
        print(f"[ERROR] _bulk_get_patient_info: {e}\n{traceback.format_exc()}")
        return {}


def _bulk_get_employee_names(emp_ids: set) -> dict:
    """
    Single pymongo query to global DB.
    Returns { emp_id_str: employeeName }

    NOTE: Uses pymongo directly because the global DB is MongoDB,
          NOT a SQL database — django connections["global"] won't work here.
    """
    if not emp_ids:
        return {}

    clean_ids = [str(e) for e in emp_ids if e]
    if not clean_ids:
        return {}

    try:
        import os
        from pymongo import MongoClient

        client     = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        global_db  = client[os.getenv("GLOBAL_DB_NAME", "Global")]
        collection = global_db["backend_diagnostics_profile"]

        cursor = collection.find(
            {"employeeId": {"$in": clean_ids}},
            {"employeeId": 1, "employeeName": 1, "_id": 0}
        )

        result = {doc["employeeId"]: doc["employeeName"] for doc in cursor}

        # Debug: warn about any IDs that returned nothing
        missing = set(clean_ids) - set(result.keys())
        if missing:
            print(f"[DEBUG] Employee IDs not found in global DB: {missing}")

        return result

    except Exception as e:
        print(f"[ERROR] _bulk_get_employee_names failed: {e}\n{traceback.format_exc()}")
        return {}


def _bulk_get_ot_names(ot_ids: set) -> dict:
    if not ot_ids:
        return {}
    try:
        ots = OTMaster.objects.filter(ot_id__in=ot_ids).values("ot_id", "ot_name")
        return {o["ot_id"]: o["ot_name"] for o in ots}
    except Exception as e:
        print(f"[ERROR] _bulk_get_ot_names failed: {e}")
        return {}


def _bulk_get_anes_names(anes_ids: set) -> dict:
    if not anes_ids:
        return {}
    try:
        anes = AnesMaster.objects.filter(
            anesthesia_id__in=anes_ids
        ).values("anesthesia_id", "anesthesia_name")
        return {a["anesthesia_id"]: a["anesthesia_name"] for a in anes}
    except Exception as e:
        print(f"[ERROR] _bulk_get_anes_names failed: {e}")
        return {}


# ─── BULK ENRICH ─────────────────────────────────────────────────────────────
def _enrich_bulk(records: list) -> list:
    if not records:
        return records

    # ── Collect all IDs ───────────────────────────────────────────────────────
    ip_numbers = {r["ip_number"]     for r in records if r.get("ip_number")}
    ot_ids     = {r["ot_id"]         for r in records if r.get("ot_id")}
    anes_ids   = {r["anesthesia_id"] for r in records if r.get("anesthesia_id")}

    emp_ids: set = set()
    for r in records:
        for field in ("surgeon_id", "anaesthetist_id"):
            if r.get(field):
                emp_ids.add(str(r[field]))
        for json_field in ("additional_anaesthetists", "additional_doctors"):
            raw = r.get(json_field) or "{}"
            try:
                mapping = json.loads(raw) if isinstance(raw, str) else raw
                emp_ids.update(str(v) for v in mapping.values() if v)
            except Exception:
                pass

    # ── Batch fetch ───────────────────────────────────────────────────────────
    patient_map = _bulk_get_patient_info(ip_numbers)
    ot_map      = _bulk_get_ot_names(ot_ids)
    anes_map    = _bulk_get_anes_names(anes_ids)
    emp_map     = _bulk_get_employee_names(emp_ids)

    # ── Stitch back ───────────────────────────────────────────────────────────
    def resolve_staff_map(json_str) -> list:
        if not json_str or json_str == "{}":
            return []
        try:
            mapping = json.loads(json_str) if isinstance(json_str, str) else json_str
            return [emp_map.get(str(v)) for v in mapping.values() if v]
        except Exception:
            return []

    enriched = []
    for r in records:
        pt = patient_map.get(r.get("ip_number"), {})
        r.update({
            "uhid":          pt.get("uhid"),
            "patient_name":  pt.get("patient_name"),
            "age":           pt.get("age"),
            "gender":        pt.get("gender"),
            "customer_type": pt.get("customer_type"),
            "company_name":  pt.get("company_name"),

            "ot_name":         ot_map.get(r.get("ot_id")),
            "anesthesia_name": anes_map.get(r.get("anesthesia_id")),

            "surgeon_name":      emp_map.get(str(r.get("surgeon_id", ""))),
            "anaesthetist_name": emp_map.get(str(r.get("anaesthetist_id", ""))),

            "additional_anaesthetists_names": resolve_staff_map(
                r.get("additional_anaesthetists", "{}")
            ),
            "additional_doctors_names": resolve_staff_map(
                r.get("additional_doctors", "{}")
            ),
        })
        enriched.append(r)

    return enriched


def _enrich(record: dict) -> dict:
    return _enrich_bulk([record])[0]


@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def create_surgery_schedule(request):
    try:
        user_id       = request.data.get("auth-user-id",       "system")
        branch_code   = request.data.get("auth-branch-code",   "system")
        hospital_code = request.data.get("auth-hospital-code", "system")

        serializer = SurgeryScheduleWriteSerializer(data=request.data)
        if not serializer.is_valid():
            first_error = next(iter(serializer.errors.values()))[0]
            return Response(
                {"success": False, "message": str(first_error), "errors": serializer.errors},
                status=400,
            )

        schedule = serializer.save(
            reference_no  = generate_reference_no(),
            status        = "Scheduled",
            is_active     = True,
            is_postponed  = False,
            branch_code   = branch_code,
            hospital_code = hospital_code,
            created_by    = user_id,
        )

        raw      = SurgeryScheduleSerializer(schedule).data
        enriched = _enrich(dict(raw))

        return Response(
            {"success": True, "message": "Surgery schedule created successfully", "data": enriched},
            status=201,
        )

    except Exception as e:
        return Response(
            {"success": False, "error": str(e), "traceback": traceback.format_exc()},
            status=500,
        )


@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def list_surgery_schedules(request):
    try:
        from_date_str = request.GET.get("from_date", "")
        to_date_str   = request.GET.get("to_date",   "")

        def parse_date(s):
            if not s:
                return None
            try:
                return datetime.strptime(s, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                return None

        def coerce_date(val):
            if val is None:
                return None
            if isinstance(val, date_type):
                return val
            if hasattr(val, "date"):
                return val.date()
            return parse_date(str(val))

        from_date = parse_date(from_date_str)
        to_date   = parse_date(to_date_str)

        all_records = list(SurgerySchedule.objects.all().values())

        if from_date or to_date:
            def in_range(d):
                if d is None:
                    return False
                if from_date and d < from_date:
                    return False
                if to_date and d > to_date:
                    return False
                return True

            filtered = []
            for r in all_records:
                scheduled_date = coerce_date(r.get("scheduled_date"))
                postponed_date = coerce_date(r.get("postponed_date"))
                if in_range(scheduled_date) or in_range(postponed_date):
                    filtered.append(r)
        else:
            filtered = all_records

        # ONE bulk enrich call — not N individual calls
        enriched = _enrich_bulk(filtered)

        return Response({"success": True, "data": enriched})

    except Exception as e:
        return Response(
            {"success": False, "error": str(e), "traceback": traceback.format_exc()},
        )


@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_surgery_schedule(request):
    try:
        reference_no = request.GET.get("reference_no", "").strip()
        if not reference_no:
            return Response({"success": False, "message": "reference_no is required"}, status=400)

        schedule = SurgerySchedule.objects.filter(reference_no=reference_no).first()
        if not schedule or not schedule.is_active:
            return Response({"success": False, "message": "Record not found"}, status=404)

        raw      = SurgeryScheduleSerializer(schedule).data
        enriched = _enrich(dict(raw))

        return Response({"success": True, "data": enriched})

    except Exception as e:
        return Response(
            {"success": False, "error": str(e), "traceback": traceback.format_exc()},
            status=500,
        )

@api_view(["PUT"])
@permission_classes([HasRoleAndDataPermission])
def update_surgery_schedule(request):
    try:
        reference_no = request.data.get("reference_no", "").strip()
        if not reference_no:
            return Response({"success": False, "message": "reference_no is required"}, status=400)

        user_id  = request.data.get("auth-user-id", "system")
        schedule = SurgerySchedule.objects.filter(reference_no=reference_no).first()

        if not schedule or not schedule.is_active:
            return Response({"success": False, "message": "Record not found"}, status=404)

        serializer = SurgeryScheduleWriteSerializer(schedule, data=request.data, partial=True)
        if not serializer.is_valid():
            first_error = next(iter(serializer.errors.values()))[0]
            return Response(
                {"success": False, "message": str(first_error), "errors": serializer.errors},
                status=400,
            )

        schedule = serializer.save(
            lastmodified_by   = user_id,
            lastmodified_date = timezone.now(),
        )

        raw      = SurgeryScheduleSerializer(schedule).data
        enriched = _enrich(dict(raw))

        return Response(
            {"success": True, "message": "Surgery schedule updated successfully", "data": enriched}
        )

    except Exception as e:
        return Response(
            {"success": False, "error": str(e), "traceback": traceback.format_exc()},
            status=500,
        )


@api_view(["DELETE"])
@permission_classes([HasRoleAndDataPermission])
def cancel_surgery_schedule(request):
    try:
        reference_no = request.data.get("reference_no", "").strip()
        if not reference_no:
            return Response({"success": False, "message": "reference_no is required"}, status=400)

        user_id  = request.data.get("auth-user-id", "system")
        schedule = SurgerySchedule.objects.filter(reference_no=reference_no).first()

        if not schedule or not schedule.is_active:
            return Response({"success": False, "message": "Record not found"}, status=404)

        schedule.status            = "Cancelled"
        schedule.is_active         = False
        schedule.lastmodified_by   = user_id
        schedule.lastmodified_date = timezone.now()
        schedule.save()

        return Response({"success": True, "message": "Surgery schedule cancelled successfully"})

    except Exception as e:
        return Response(
            {"success": False, "error": str(e), "traceback": traceback.format_exc()},
            status=500,
        )


@api_view(["PATCH"])
@permission_classes([HasRoleAndDataPermission])
def update_schedule_status(request):
    try:
        reference_no = request.data.get("reference_no", "").strip()
        if not reference_no:
            return Response({"success": False, "message": "reference_no is required"}, status=400)

        user_id  = request.data.get("auth-user-id", "system")
        schedule = SurgerySchedule.objects.filter(reference_no=reference_no).first()

        if not schedule or not schedule.is_active:
            return Response({"success": False, "message": "Record not found"}, status=404)

        new_status = request.data.get("status", "").strip()
        allowed    = ["Scheduled", "Confirmed", "Completed", "Postponed", "Cancelled"]

        if new_status not in allowed:
            return Response(
                {"success": False, "message": f"Status must be one of: {', '.join(allowed)}"},
                status=400,
            )

        schedule.status = new_status

        if new_status == "Postponed":
            schedule.is_postponed = True
            if request.data.get("postponed_date"):
                schedule.postponed_date = request.data["postponed_date"]
            if request.data.get("post_startTime"):
                schedule.post_startTime = request.data["post_startTime"]
            if request.data.get("post_endTime"):
                schedule.post_endTime = request.data["post_endTime"]

        if new_status == "Cancelled":
            schedule.is_active = False

        if "is_active" in request.data:
            schedule.is_active = bool(request.data["is_active"])

        schedule.lastmodified_by   = user_id
        schedule.lastmodified_date = timezone.now()
        schedule.save()

        raw      = SurgeryScheduleSerializer(schedule).data
        enriched = _enrich(dict(raw))

        return Response(
            {"success": True, "message": f"Status updated to '{new_status}'", "data": enriched}
        )

    except Exception as e:
        return Response(
            {"success": False, "error": str(e), "traceback": traceback.format_exc()},
            status=500,
        )