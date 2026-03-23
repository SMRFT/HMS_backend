from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from ..models import SurgerySchedule, OTMaster, AnesMaster
from ..serializers import SurgeryScheduleSerializer, SurgeryScheduleWriteSerializer
from pyauth.auth import HasRoleAndDataPermission
from django.utils import timezone
from django.db import connections
import traceback, json


# ─── ID Generator ─────────────────────────────────────────────────────────────
def generate_reference_no():
    """
    Format: SUR2526/00001
      SUR        — fixed prefix
      2526       — financial year tag  (Apr 2025–Mar 2026 → "2526")
      /00001     — 5-digit sequence, resets every financial year
    """
    from datetime import datetime

    today = datetime.today()
    if today.month < 4:
        financial_year = f"{(today.year - 1) % 100:02d}{today.year % 100:02d}"
    else:
        financial_year = f"{today.year % 100:02d}{(today.year + 1) % 100:02d}"

    prefix = f"SUR{financial_year}/"   # e.g. "SUR2526/"

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


# ─── Enrichment Helper ────────────────────────────────────────────────────────
def _enrich(record: dict) -> dict:
    """
    Takes a raw SurgerySchedule values() dict and returns it enriched with:
      - patient_name, uhid, gender, age, customer_type, company_name  (via ip_number)
      - ot_name                                                        (via ot_id)
      - anesthesia_name                                                (via anesthesia_id)
      - surgeon_name, anaesthetist_name                                (via employee IDs)
      - additional_anaesthetists_names, additional_doctors_names       (via JSON maps)

    All lookups are best-effort — a missing record just leaves the field as None.
    """

    # ── 1. Patient info from Admission + Patient models ───────────────────────
    ip_number = record.get("ip_number", "")
    patient_info = {
        "uhid":         None,
        "patient_name": None,
        "age":          None,
        "gender":       None,
        "customer_type": None,
        "company_name": None,
    }

    if ip_number:
        try:
            from ..models import Admission, Patient, InsuranceProvider

            admission = Admission.objects.filter(ipNumber=ip_number).first()
            if admission:
                patient_info["uhid"] = admission.uhid
                try:
                    patient = Patient.objects.get(uhid=admission.uhid)
                    salutation  = getattr(patient, "salutation", "") or ""
                    first_name  = getattr(patient, "firstName",  "") or ""
                    last_name   = getattr(patient, "lastName",   "") or ""
                    patient_info["patient_name"] = f"{salutation} {first_name} {last_name}".strip()
                    patient_info["age"]          = getattr(patient, "age",           None)
                    patient_info["gender"]       = getattr(patient, "gender",        None)
                    patient_info["customer_type"]= getattr(patient, "customer_type", None)

                    company_code = getattr(patient, "company_code", None)
                    if company_code:
                        try:
                            insurance = InsuranceProvider.objects.get(company_code=company_code)
                            patient_info["company_name"] = insurance.company_name
                        except Exception:
                            pass
                except Exception:
                    pass
        except Exception:
            pass

    record.update(patient_info)

    # ── 2. OT name from OTMaster ──────────────────────────────────────────────
    ot_id = record.get("ot_id", "")
    record["ot_name"] = None
    if ot_id:
        try:
            ot = OTMaster.objects.filter(ot_id=ot_id).first()
            if ot:
                record["ot_name"] = ot.ot_name
        except Exception:
            pass

    # ── 3. Anesthesia name from AnesMaster ────────────────────────────────────
    anesthesia_id = record.get("anesthesia_id", "")
    record["anesthesia_name"] = None
    if anesthesia_id:
        try:
            anes = AnesMaster.objects.filter(anesthesia_id=anesthesia_id).first()
            if anes:
                record["anesthesia_name"] = anes.anesthesia_name
        except Exception:
            pass

    # ── 4. Employee name lookup from Global DB (backend_diagnostics_profile) ──
    def get_employee_name(emp_id: str) -> str | None:
        """Query backend_diagnostics_profile by employeeId → employeeName."""
        if not emp_id:
            return None
        try:
            global_db = connections["global"]
            with global_db.cursor() as cursor:
                cursor.execute(
                    'SELECT "employeeName" FROM "backend_diagnostics_profile" '
                    'WHERE "employeeId" = %s LIMIT 1',
                    [str(emp_id)],
                )
                row = cursor.fetchone()
                return row[0] if row else None
        except Exception:
            return None

    # Surgeon
    record["surgeon_name"] = get_employee_name(record.get("surgeon_id", ""))

    # Primary anaesthetist
    record["anaesthetist_name"] = get_employee_name(record.get("anaesthetist_id", ""))

    # Additional anaesthetists  →  {"1":"60380","2":"60254"}  →  ["Name A","Name B"]
    def resolve_staff_map(json_str: str) -> list:
        if not json_str or json_str == "{}":
            return []
        try:
            mapping = json.loads(json_str) if isinstance(json_str, str) else json_str
            return [
                get_employee_name(str(emp_id))
                for emp_id in mapping.values()
                if emp_id
            ]
        except Exception:
            return []

    record["additional_anaesthetists_names"] = resolve_staff_map(
        record.get("additional_anaesthetists", "{}")
    )
    record["additional_doctors_names"] = resolve_staff_map(
        record.get("additional_doctors", "{}")
    )

    return record


# ─── CREATE ───────────────────────────────────────────────────────────────────
@api_view(["POST"])
# @permission_classes([HasRoleAndDataPermission])
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
            billTypeNo    = "SUR01",          # always stored as SUR01
            status        = "Scheduled",
            is_active     = True,
            is_postponed  = False,
            branch_code   = branch_code,
            hospital_code = hospital_code,
            created_by    = user_id,
        )

        # Return enriched record so the frontend gets names immediately
        raw = SurgeryScheduleSerializer(schedule).data
        enriched = _enrich(dict(raw))

        return Response(
            {
                "success": True,
                "message": "Surgery schedule created successfully",
                "data":    enriched,
            },
            status=201,
        )

    except Exception as e:
        return Response(
            {"success": False, "error": str(e), "traceback": traceback.format_exc()},
            status=500,
        )


# ─── LIST (with date range + cancelled toggle) ────────────────────────────────
@api_view(["GET"])
# @permission_classes([HasRoleAndDataPermission])
def list_surgery_schedules(request):
    try:
        from_date_str = request.GET.get("from_date", "")
        to_date_str   = request.GET.get("to_date",   "")

        # Djongo cannot handle chained exclude() + date range + boolean in one query.
        # Fetch all and filter in Python (same pattern as OTMaster, AnesMaster).
        all_records = list(SurgerySchedule.objects.all().values())

        from datetime import date as date_type, datetime

        def parse_date(s):
            if not s:
                return None
            try:
                return datetime.strptime(s, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                return None

        def coerce_date(val):
            """Djongo returns scheduled_date as datetime; normalise to date."""
            if val is None:
                return None
            if isinstance(val, date_type):
                return val
            if hasattr(val, "date"):
                return val.date()
            return parse_date(str(val))

        from_date = parse_date(from_date_str)
        to_date   = parse_date(to_date_str)

        filtered = []
        for r in all_records:
            scheduled_date   = coerce_date(r.get("scheduled_date"))
            postponed_date   = coerce_date(r.get("postponed_date"))
            has_postponed    = postponed_date is not None

            # A record matches the date range if EITHER of these is true:
            #   1. Its scheduled_date falls within [from_date, to_date]
            #   2. It has a postponed_date that falls within [from_date, to_date]
            # If no date range is given, all records pass.

            def in_range(d):
                """Return True if date d falls within the requested range."""
                if d is None:
                    return False
                if from_date and d < from_date:
                    return False
                if to_date and d > to_date:
                    return False
                return True

            if from_date or to_date:
                # At least one range boundary is set — must match on one of the dates
                matches_scheduled = in_range(scheduled_date)
                matches_postponed = has_postponed and in_range(postponed_date)
                if not matches_scheduled and not matches_postponed:
                    continue

            filtered.append(r)

        # Enrich every record with patient / OT / anesthesia / staff names
        enriched = [_enrich(dict(r)) for r in filtered]

        return Response({"success": True, "data": enriched})

    except Exception as e:
        return Response(
            {"success": False, "error": str(e), "traceback": traceback.format_exc()},
        )


# ─── GET SINGLE ───────────────────────────────────────────────────────────────
# reference_no is passed as a GET query param to avoid slash-in-URL issues:
#   GET /get_surgery_schedule/?reference_no=SUR2526/00001
@api_view(["GET"])
# @permission_classes([HasRoleAndDataPermission])
def get_surgery_schedule(request):
    try:
        reference_no = request.GET.get("reference_no", "").strip()
        if not reference_no:
            return Response({"success": False, "message": "reference_no is required"}, status=400)

        # Djongo can't handle chained filters — fetch by PK then check is_active in Python
        schedule = SurgerySchedule.objects.filter(reference_no=reference_no).first()

        if not schedule or not schedule.is_active:
            return Response(
                {"success": False, "message": "Record not found"}, status=404
            )

        raw      = SurgeryScheduleSerializer(schedule).data
        enriched = _enrich(dict(raw))

        return Response({"success": True, "data": enriched})

    except Exception as e:
        return Response(
            {"success": False, "error": str(e), "traceback": traceback.format_exc()},
            status=500,
        )


# ─── UPDATE ───────────────────────────────────────────────────────────────────
# reference_no is read from the request body to avoid slash-in-URL issues.
# Frontend sends: PUT /update_surgery_schedule/  with { reference_no: "SUR2526/00001", ... }
@api_view(["PUT"])
# @permission_classes([HasRoleAndDataPermission])
def update_surgery_schedule(request):
    try:
        reference_no = request.data.get("reference_no", "").strip()
        if not reference_no:
            return Response({"success": False, "message": "reference_no is required"}, status=400)

        user_id = request.data.get("auth-user-id", "system")

        # Djongo can't handle chained filters — fetch by PK then check is_active in Python
        schedule = SurgerySchedule.objects.filter(reference_no=reference_no).first()

        if not schedule or not schedule.is_active:
            return Response(
                {"success": False, "message": "Record not found"}, status=404
            )

        serializer = SurgeryScheduleWriteSerializer(
            schedule, data=request.data, partial=True
        )

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
            {
                "success": True,
                "message": "Surgery schedule updated successfully",
                "data":    enriched,
            }
        )

    except Exception as e:
        return Response(
            {"success": False, "error": str(e), "traceback": traceback.format_exc()},
            status=500,
        )


# ─── CANCEL (soft delete) ─────────────────────────────────────────────────────
# reference_no is read from the request body to avoid slash-in-URL issues.
# Frontend sends: DELETE /cancel_surgery_schedule/  with { reference_no: "SUR2526/00001" }
@api_view(["DELETE"])
# @permission_classes([HasRoleAndDataPermission])
def cancel_surgery_schedule(request):
    try:
        reference_no = request.data.get("reference_no", "").strip()
        if not reference_no:
            return Response({"success": False, "message": "reference_no is required"}, status=400)

        user_id = request.data.get("auth-user-id", "system")

        # Djongo can't handle chained filters — fetch by PK then check is_active in Python
        schedule = SurgerySchedule.objects.filter(reference_no=reference_no).first()

        if not schedule or not schedule.is_active:
            return Response(
                {"success": False, "message": "Record not found"}, status=404
            )

        schedule.status            = "Cancelled"
        schedule.is_active         = False
        schedule.lastmodified_by   = user_id
        schedule.lastmodified_date = timezone.now()
        schedule.save()

        return Response(
            {"success": True, "message": "Surgery schedule cancelled successfully"}
        )

    except Exception as e:
        return Response(
            {"success": False, "error": str(e), "traceback": traceback.format_exc()},
            status=500,
        )


# ─── STATUS UPDATE ────────────────────────────────────────────────────────────
# reference_no is read from the request body to avoid slash-in-URL issues.
# Body: { "reference_no": "SUR2526/00001", "status": "Postponed", ... }
@api_view(["PATCH"])
# @permission_classes([HasRoleAndDataPermission])
def update_schedule_status(request):
    try:
        reference_no = request.data.get("reference_no", "").strip()
        if not reference_no:
            return Response({"success": False, "message": "reference_no is required"}, status=400)

        user_id = request.data.get("auth-user-id", "system")

        # Djongo can't handle chained filters — fetch by PK then check is_active in Python
        schedule = SurgerySchedule.objects.filter(reference_no=reference_no).first()

        if not schedule or not schedule.is_active:
            return Response(
                {"success": False, "message": "Record not found"}, status=404
            )

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

        # Allow explicit is_active override (e.g. Confirm reactivates a cancelled schedule)
        if "is_active" in request.data:
            schedule.is_active = bool(request.data["is_active"])

        schedule.lastmodified_by   = user_id
        schedule.lastmodified_date = timezone.now()
        schedule.save()

        raw      = SurgeryScheduleSerializer(schedule).data
        enriched = _enrich(dict(raw))

        return Response(
            {
                "success": True,
                "message": f"Status updated to '{new_status}'",
                "data":    enriched,
            }
        )

    except Exception as e:
        return Response(
            {"success": False, "error": str(e), "traceback": traceback.format_exc()},
            status=500,
        )