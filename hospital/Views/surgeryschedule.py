from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from ..models import SurgerySchedule, OTMaster, AnesMaster
from ..serializers import SurgeryScheduleSerializer, SurgeryScheduleWriteSerializer
from pyauth.auth import HasRoleAndDataPermission
from django.utils import timezone
from django.db import connections
import traceback, json
from datetime import datetime, date as date_type
import os
from pymongo import MongoClient
from pymongo import MongoClient
import pytz
from datetime import datetime
from ..models import PharmacyBilling


client   = MongoClient(os.getenv("GLOBAL_DB_HOST"))
hms_db   = client[os.getenv("HMS_DB_NAME", "HMS")]


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

        # Step 1: ip_number → (uhid, age, age_type)
        admissions = list(
            Admission.objects.filter(ipNumber__in=ip_numbers)
            .values("ipNumber", "uhid", "age", "age_type")
        )
        if not admissions:
            return {}

        ip_to_admission = {a["ipNumber"]: a for a in admissions}
        uhids = {a["uhid"] for a in admissions}

        # Step 2: uhid → Patient
        patients = list(
            Patient.objects.filter(uhid__in=uhids)
            .values("uhid", "salutation", "firstName", "lastName",
                    "gender", "customer_type", "company_code")
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
        for ip_num, adm in ip_to_admission.items():
            uhid       = adm["uhid"]
            pt         = uhid_to_patient.get(uhid, {})
            salutation = (pt.get("salutation") or "").strip()
            first      = (pt.get("firstName")  or "").strip()
            last       = (pt.get("lastName")   or "").strip()
            full_name  = " ".join(filter(None, [salutation, first, last])) or None
            cc         = pt.get("company_code")

            result[ip_num] = {
                "uhid":          uhid,
                "patient_name":  full_name,
                "age":           adm.get("age"),
                "age_type":      adm.get("age_type"),
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
            "age_type":      pt.get("age_type"),
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
        # ✅ Get auth codes
        branch_code   = request.data.get("auth-branch-code",   "system")
        hospital_code = request.data.get("auth-hospital-code", "system")

        from_date_str = request.GET.get("from_date", "")
        to_date_str   = request.GET.get("to_date", "")

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

        # ✅ Apply DB-level filter FIRST (IMPORTANT for performance)
        queryset = SurgerySchedule.objects.all()

        if hospital_code:
            queryset = queryset.filter(hospital_code=hospital_code)

        if branch_code:
            queryset = queryset.filter(branch_code=branch_code)

        all_records = list(queryset.values())

        # ── Date filter (your existing logic) ─────────────────
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

        # ✅ Bulk enrich (unchanged)
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



@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def list_diagnosis(request):
    """
    Fetch all active diagnosis records from hospital_diagnosis collection (HMS DB).
    Returns: { success: true, data: [{ diagnostics_id, diagnostics_name }] }
    """
    try:
        
        cursor = hms_db["hospital_diagnosis"].find(
            {"is_active": True},
            {"diagnostics_id": 1, "diagnostics_name": 1, "_id": 0},
        ).sort("diagnostics_name", 1)   # alphabetical order
 
        data = [
            {
                "diagnostics_id":   doc.get("diagnostics_id"),
                "diagnostics_name": doc.get("diagnostics_name", ""),
            }
            for doc in cursor
        ]
 
        client.close()
 
        return Response({"success": True, "data": data})
 
    except Exception as e:
        return Response(
            {"success": False, "error": str(e), "traceback": traceback.format_exc()},
        )
   
    
from bson.decimal128 import Decimal128
from django.http import JsonResponse

def convert_decimals(obj):
    if isinstance(obj, list):
        return [convert_decimals(i) for i in obj]
    elif isinstance(obj, dict):
        return {k: convert_decimals(v) for k, v in obj.items()}
    elif isinstance(obj, Decimal128):
        return float(obj.to_decimal())
    return obj

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_pharmacy_items(request):
    """
    Search hospital_pharmacyitem by item_name prefix.
    Returns only is_active=True, is_blocked=False items.
    No stock/batch/MRP lookup needed here.
    """
    try:
        search        = request.GET.get("search", "").strip()
        branch_code   = request.data.get("auth-branch-code",   "system")
        hospital_code = request.data.get("auth-hospital-code", "system")

        if len(search) < 2:
            return JsonResponse({"success": True, "data": []})

        client   = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        mongo_db = client["HMS"]

        pipeline = [
            {
                "$match": {
                    "branch_code":   branch_code,
                    "hospital_code": hospital_code,
                    "is_active":     True,
                    "is_blocked":    False,
                    "item_name": {
                        "$regex":   f"^{search}",   # prefix-anchored = uses index
                        "$options": "i"
                    }
                }
            },
            {
                "$project": {
                    "_id":       0,
                    "item_id":   1,
                    "item_name": 1,
                }
            },
            { "$limit": 30 }
        ]

        data = list(mongo_db["hospital_pharmacyitem"].aggregate(pipeline))

        return JsonResponse({"success": True, "data": data})

    except Exception as e:
        print("Error in get_pharmacy_items:", str(e))
        return JsonResponse({"success": False, "message": str(e)}, status=500)


# ─── NEW: Medicine Packages ────────────────────────────────────────────────────
@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_medicine_packages(request):
    """
    Fetch active medicine packages from hospital_medicine_package collection (HMS DB),
    scoped to outlet/branch/hospital, for use in the OT Medicine Request "Select
    from Package" flow.

    Query params:
        outlet_code   (optional, defaults to OLET001)
        search        (optional, filters by medPackage_name, case-insensitive)

    Returns:
        { success: true, data: [ { medPackage_id, medPackage_name, items: [...], is_active }, ... ] }
    """
    try:
        outlet_code = request.GET.get("outlet_code", "OLET001")
        search = request.GET.get("search", "").strip()
        branch_code = request.data.get("auth-branch-code", "system")
        hospital_code = request.data.get("auth-hospital-code", "system")

        mongo_client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        mongo_db = mongo_client[os.getenv("HMS_DB_NAME", "HMS")]

        query = {
            "outlet_code": outlet_code,
            "branch_code": branch_code,
            "hospital_code": hospital_code,
            "is_active": True,
        }

        if search:
            query["medPackage_name"] = {"$regex": search, "$options": "i"}

        cursor = (
            mongo_db["hospital_medicine_package"]
            .find(
                query,
                {
                    "_id": 0,
                    "medPackage_id": 1,
                    "medPackage_name": 1,
                    "items": 1,
                    "is_active": 1,
                    "outlet_code": 1,
                },
            )
            .sort("medPackage_name", 1)
        )

        data = list(cursor)
        data = convert_decimals(data)

        mongo_client.close()

        return Response({"success": True, "data": data}, status=200)

    except Exception as e:
        return Response(
            {
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc(),
            },
            status=500,
        )


@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def save_ot_medicine_ward_request(request):
    """
    Save OT medicine ward request using PharmacyBilling model.
    Bill_id is auto-generated in PharmacyBilling.save()

    Supports Package_id: when the request was created by selecting a medicine
    package on the frontend, medPackage_id is sent as "Package_id" and stored
    on the bill. Defaults to "" when no package was used.
    """

    try:
        data = request.data

        current_user = data.get("auth-user-id", "system")
        branch_code = data.get("auth-branch-code", "system")
        hospital_code = data.get("auth-hospital-code", "system")
        # outlet_code = data.get("auth-outlet-code", "OLET001")

        medicine_particulars = data.get("medicine_particulars", [])
        total_amount = round(float(data.get("total_amount", 0)), 2)

        # Package_id — sent by frontend when a package was selected,
        # empty string otherwise.
        package_id = data.get("Package_id", "") or ""

        # Remove fields that should not be stored in medicine_particulars.
        # itemName is intentionally stripped: item_id is the source of truth,
        # and the display name is resolved on read via hospital_pharmacyitem
        # (see get_ot_medicine_ward_requests). Storing it here would just be
        # a stale, duplicated copy.
        STRIP_FIELDS = {
            "edit_history",
            "billType",
            "billTypeNo",
            "billTypeName",
            "total_stock",
            "price",
            "expiry_date",
            "itemName",
            "item_name",
            "name",
        }

        cleaned_medicines = []

        for med in medicine_particulars:
            cleaned = {
                key: value
                for key, value in med.items()
                if key not in STRIP_FIELDS
            }

            # Ensure required/default fields exist
            cleaned.setdefault("remark", "")
            cleaned.setdefault("dose", "")
            cleaned.setdefault("doseUnit", "")
            cleaned.setdefault("route", "")
            cleaned.setdefault("dosage", "")
            cleaned.setdefault("noOfDays", "")
            cleaned.setdefault("qty", cleaned.get("quantity", 0))

            cleaned_medicines.append(cleaned)

        # Save through model instead of direct mongo insert
        bill = PharmacyBilling.objects.create(
            branch_code=branch_code,
            hospital_code=hospital_code,
            outlet_code="OLET001",

            created_by=current_user,
            created_date=timezone.now(),

            ward_request_date=timezone.now(),
            is_ward_request=True,
            bill_date=None,
            bill_no="",
            estimate_no="",

            uhid=data.get("uhid", ""),
            inpatient_number=data.get("ipNumber", ""),

            bill_type=18,
            doctor_id=data.get("doctor_id", ""),
            room_no=data.get("wardName", ""),

            medicine_particulars=cleaned_medicines,

            total_amount=total_amount,

            overall_discount_type="percent",
            overall_discount_value=0.0,
            overall_discount_amount=0.0,

            net_amount=total_amount,

            billing_mode="WARD REQUEST",
            billing_status="Pending",
            payment_mode="Credit",

            payment_details={},

            is_deleted=False,
            delete_reason="",
            deleted_by="",

            round_off=0,

            cashier_id="",

            Package_id=package_id,
        )

        return Response(
            {
                "success": True,
                "message": "OT medicine ward request saved successfully",
                "bill_id": bill.Bill_id,
                "billing_status": bill.billing_status,
                "package_id": bill.Package_id,
            },
            status=200,
        )

    except Exception as e:
        return Response(
            {
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc(),
            },
            status=500,
        )
    


@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_ot_medicine_ward_requests(request):
    try:
        uhid = request.query_params.get("uhid")
        ip_number = request.query_params.get("ipNumber")

        if not uhid:
            return Response(
                {"success": False, "error": "UHID is required"},
                status=400
            )

        query_params = {
            "uhid": uhid,
            "is_ward_request": True
        }

        if ip_number:
            query_params["inpatient_number"] = ip_number

        # ✅ Two DB connections
        hms_client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        hms_db = hms_client[os.getenv("HMS_DB_NAME", "HMS")]

        global_client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        global_db = global_client[os.getenv("GLOBAL_DB_NAME", "Global")]

        ward_req_collection = hms_db["hospital_pharmacybilling"]

        requests_data = list(
            ward_req_collection.find(query_params).sort("ward_request_date", -1)
        )

        # ✅ -------------------------------
        # STEP 1: Collect all item_ids
        # ✅ -------------------------------
        all_item_ids = set()

        for doc in requests_data:
            items = doc.get("medicine_particulars", [])

            if isinstance(items, str):
                try:
                    items = json.loads(items)
                except:
                    items = []

            for itm in items:
                if isinstance(itm, str):
                    try:
                        itm = json.loads(itm)
                    except:
                        continue

                if isinstance(itm, dict):
                    item_id = itm.get("item_id")
                    if item_id:
                        all_item_ids.add(item_id)

        # ✅ -------------------------------
        # STEP 2: Fetch item names in one query
        # ✅ -------------------------------
        item_map = {}

        if all_item_ids:
            item_collection = hms_db["hospital_pharmacyitem"]

            item_docs = item_collection.find(
                {"item_id": {"$in": list(all_item_ids)}},
                {"item_id": 1, "item_name": 1, "_id": 0}
            )

            item_map = {
                item["item_id"]: item.get("item_name", "")
                for item in item_docs
            }

        # ✅ -------------------------------
        # STEP 3: Fetch bill type names
        # ✅ -------------------------------
        bill_types = {
            doc.get("bill_type")
            for doc in requests_data
            if doc.get("bill_type") is not None
        }

        billtype_map = {}

        if bill_types:
            billtype_collection = hms_db["hospital_billtype"]

            billtype_map = {
                bt.get("bill_type"): bt.get("bill_name", "")
                for bt in billtype_collection.find(
                    {"bill_type": {"$in": list(bill_types)}},
                    {"bill_type": 1, "bill_name": 1, "_id": 0}
                )
            }

        # ✅ -------------------------------
        # STEP 4: Fetch doctor names from Global DB
        # ✅ -------------------------------
        all_doctor_ids = {
            str(doc.get("doctor_id"))
            for doc in requests_data
            if doc.get("doctor_id")
        }

        doctor_map = {}

        if all_doctor_ids:
            diagnostics_collection = global_db["backend_diagnostics_profile"]

            doctor_docs = diagnostics_collection.find(
                {"employeeId": {"$in": list(all_doctor_ids)}},
                {"employeeId": 1, "employeeName": 1, "_id": 0}
            )

            doctor_map = {
                doc["employeeId"]: doc.get("employeeName", "")
                for doc in doctor_docs
            }

        # ✅ -------------------------------
        # STEP 4b: Fetch package names for any Package_id referenced
        # ✅ -------------------------------
        all_package_ids = {
            doc.get("Package_id")
            for doc in requests_data
            if doc.get("Package_id")
        }

        package_map = {}

        if all_package_ids:
            package_collection = hms_db["hospital_medicine_package"]

            # Package_id stored on PharmacyBilling is a CharField, while
            # medPackage_id in the package collection is numeric — try both
            # so the lookup matches whichever form was stored.
            normalized_ids = list(all_package_ids)
            numeric_ids = []
            for pid in normalized_ids:
                try:
                    numeric_ids.append(int(pid))
                except (TypeError, ValueError):
                    pass

            package_docs = package_collection.find(
                {"medPackage_id": {"$in": numeric_ids or normalized_ids}},
                {"medPackage_id": 1, "medPackage_name": 1, "_id": 0}
            )

            for pkg in package_docs:
                package_map[str(pkg.get("medPackage_id"))] = pkg.get("medPackage_name", "")
                package_map[pkg.get("medPackage_id")] = pkg.get("medPackage_name", "")

        # ✅ -------------------------------
        # STEP 5: Format response
        # ✅ -------------------------------
        formatted_data = []
        ist = pytz.timezone("Asia/Kolkata")

        for doc in requests_data:
            items = doc.get("medicine_particulars", [])

            if isinstance(items, str):
                try:
                    items = json.loads(items)
                except:
                    items = []

            medicines = []

            for itm in items:
                if isinstance(itm, str):
                    try:
                        itm = json.loads(itm)
                    except:
                        continue

                if not isinstance(itm, dict):
                    continue

                item_id = itm.get("item_id")

                medicines.append({
                    "item_id": item_id,
                    "name": item_map.get(
                        item_id,
                        itm.get("itemName", itm.get("item_name", ""))
                    ),
                    "qty": itm.get("qty", 1),
                    "doctor": itm.get("doctor", ""),
                    "dosage": itm.get("dosage", ""),
                    "noOfDays": itm.get("noOfDays", ""),
                    "dose": itm.get("dose", ""),
                    "doseUnit": itm.get("doseUnit", ""),
                    "route": itm.get("route", ""),
                    "instruction": itm.get("instruction", ""),
                    "remark": itm.get("remark", "")
                })

            bill_type = doc.get("bill_type")
            bill_name = billtype_map.get(bill_type, "")

            # ✅ Doctor name lookup
            doctor_id = str(doc.get("doctor_id", ""))
            doctor_name = doctor_map.get(doctor_id, doc.get("doctor", ""))

            # ✅ Date conversion
            ward_request_date = doc.get("ward_request_date")
            req_date = ""
            req_time = ""

            if ward_request_date:
                if ward_request_date.tzinfo is None:
                    ward_request_date = pytz.utc.localize(ward_request_date)

                ward_request_date = ward_request_date.astimezone(ist)

                req_date = ward_request_date.strftime("%d-%m-%Y")
                req_time = ward_request_date.strftime("%I:%M %p")

            formatted_doc = {
                "id": str(doc.get("_id")),
                "bill_id": doc.get("Bill_id", ""),
                "uhid": doc.get("uhid", ""),
                "ipNumber": doc.get("inpatient_number", ""),
                "patientName": doc.get("patient_name", ""),
                "billType": bill_type,
                "billName": bill_name,
                "reqDate": req_date,
                "reqTime": req_time,
                "userName": doc.get("created_by", ""),
                "requestNo": doc.get("estimate_no", ""),
                "doctorName": doctor_name,          # ✅ Resolved from Global DB
                "doctor_id": doctor_id,
                "wardName": doc.get("room_no", ""),
                "billingStatus": doc.get("billing_status", ""),
                "is_dispatched": doc.get("is_dispatched", False),   # ← ADD
                "is_received":   doc.get("is_received",   False),   # ← ADD
                "billingMode": doc.get("billing_mode", ""),
                "medicines": medicines,
                "total_amount": doc.get("total_amount", 0),
                "net_amount": doc.get("net_amount", 0),
                "Package_id": doc.get("Package_id", ""),
                "packageName": package_map.get(doc.get("Package_id", "")) or "",
            }

            formatted_data.append(formatted_doc)

        hms_client.close()
        global_client.close()

        return Response(
            {
                "success": True,
                "count": len(formatted_data),
                "data": formatted_data
            },
            status=200
        )

    except Exception as e:
        return Response(
            {
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc()
            },
            status=500
        )


@api_view(["PUT"])
@permission_classes([HasRoleAndDataPermission])
def update_ot_medicine_ward_request(request):
    """
    Update OT medicine ward request using Bill_id (NOT ObjectId)
    Only allowed when billing_status == "Pending"

    Supports updating Package_id whenever the key is present in the payload —
    this covers both setting a package (newly selected) and clearing one
    (frontend sends "" when the user removes an item from a package-derived
    list or clicks "Clear Package").
    """
    try:
        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        hms_db = client[os.getenv("HMS_DB_NAME", "HMS")]

        data = request.data
        current_user = data.get("auth-user-id", "system")

        # ✅ GET bill_id instead of record_id
        bill_id = data.get("bill_id")

        if bill_id is None:
            return Response(
                {"success": False, "message": "Bill_id is required"},
                status=400
            )

        try:
            bill_id = int(bill_id)
        except:
            return Response(
                {"success": False, "message": "Bill_id must be a number"},
                status=400
            )

        collection = hms_db["hospital_pharmacybilling"]

        # ✅ Fetch using Bill_id
        existing = collection.find_one({"Bill_id": bill_id})

        if not existing:
            return Response(
                {"success": False, "message": "Record not found"},
                status=404
            )

        # ✅ Check status
        if existing.get("billing_status", "Pending") != "Pending":
            return Response(
                {
                    "success": False,
                    "message": f"Cannot edit a record with status '{existing.get('billing_status')}'"
                },
                status=400
            )

        medicine_particulars = data.get("medicine_particulars", [])
        total_amount = round(float(data.get("total_amount", 0)), 2)

        # ✅ Clean medicines — itemName/item_name/name stripped, same reasoning
        # as in save_ot_medicine_ward_request: item_id is the source of truth,
        # display name is resolved on read.
        STRIP_FIELDS = {
            "edit_history", "billType", "billTypeNo", "billTypeName",
            "total_stock", "price", "expiry_date",
            "itemName", "item_name", "name",
        }

        cleaned_medicines = []
        for med in medicine_particulars:
            cleaned = {k: v for k, v in med.items() if k not in STRIP_FIELDS}
            cleaned.setdefault("remark", "")
            cleaned_medicines.append(cleaned)


        update_fields = {
            "medicine_particulars": cleaned_medicines,
            "total_amount": total_amount,
            "net_amount": total_amount,
            "lastmodified_by": current_user,
            "lastmodified_date": timezone.now(),
        }

        # ✅ Update doctor if present
        if data.get("doctor_id"):
            update_fields["doctor_id"] = data["doctor_id"]

        # ✅ Update Package_id whenever the key is present in the payload
        # (covers both setting and clearing it — frontend always sends the key,
        # using "" to mean "no package").
        if "Package_id" in data:
            update_fields["Package_id"] = data.get("Package_id") or ""

        # ✅ Update using Bill_id
        collection.update_one(
            {"Bill_id": bill_id},
            {"$set": update_fields}
        )

        client.close()

        return Response({
            "success": True,
            "message": "OT medicine ward request updated successfully",
        })

    except Exception as e:
        return Response(
            {
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc()
            },
            status=500
        )

@api_view(["PUT"])
@permission_classes([HasRoleAndDataPermission])
def delete_ot_medicine_ward_request(request):
    """
    Soft-delete: sets is_ward_request = False
    Only allowed when billing_status == "Pending"
    """
    try:
        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        hms_db = client[os.getenv("HMS_DB_NAME", "HMS")]

        data = request.data
        current_user = data.get("auth-user-id", "system")

        bill_id = data.get("bill_id")
        if bill_id is None:
            return Response({"success": False, "message": "bill_id is required"}, status=400)

        try:
            bill_id = int(bill_id)
        except:
            return Response({"success": False, "message": "bill_id must be a number"}, status=400)

        collection = hms_db["hospital_pharmacybilling"]
        existing = collection.find_one({"Bill_id": bill_id})

        if not existing:
            return Response({"success": False, "message": "Record not found"}, status=404)

        if existing.get("billing_status", "Pending") != "Pending":
            return Response(
                {"success": False, "message": f"Cannot delete a record with status '{existing.get('billing_status')}'"},
                status=400
            )

        collection.update_one(
            {"Bill_id": bill_id},
            {"$set": {
                "is_ward_request": False,
                "lastmodified_by": current_user,
                "lastmodified_date": timezone.now(),
            }}
        )

        client.close()
        return Response({"success": True, "message": "Ward request deleted successfully"})

    except Exception as e:
        return Response({"success": False, "error": str(e), "traceback": traceback.format_exc()}, status=500)
    
@api_view(["PUT"])
@permission_classes([HasRoleAndDataPermission])
def mark_ot_medicine_received(request):
    """
    Sets is_received = True on a dispatched ward request.
    Only allowed when is_dispatched == True.
    """
    try:
        client  = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        hms_db  = client[os.getenv("HMS_DB_NAME", "HMS")]
        data    = request.data
        current_user = data.get("auth-user-id", "system")

        bill_id = data.get("bill_id")
        if bill_id is None:
            return Response({"success": False, "message": "bill_id is required"}, status=400)
        try:
            bill_id = int(bill_id)
        except Exception:
            return Response({"success": False, "message": "bill_id must be a number"}, status=400)

        collection = hms_db["hospital_pharmacybilling"]
        existing   = collection.find_one({"Bill_id": bill_id})

        if not existing:
            return Response({"success": False, "message": "Record not found"}, status=404)

        if not existing.get("is_dispatched", False):
            return Response(
                {"success": False, "message": "Cannot mark as received: not yet dispatched"},
                status=400,
            )

        collection.update_one(
            {"Bill_id": bill_id},
            {"$set": {
                "is_received":       True,
                "lastmodified_by":   current_user,
                "lastmodified_date": timezone.now(),
            }}
        )

        client.close()
        return Response({"success": True, "message": "Marked as received successfully"})

    except Exception as e:
        return Response(
            {"success": False, "error": str(e), "traceback": traceback.format_exc()},
            status=500,
        )
    
@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_implant_items(request):
    """
    Search VelavanItems where category='IMPLANT', is_active=True,
    itemName contains the search term (case-insensitive prefix match).
 
    Query params:
        search  — required, min 2 chars
 
    Returns:
        { success: true, data: [{ item_id, itemName, hsn, category }] }
    """
    try:
        from ..models import VelavanItems  # adjust import path to your app
 
        search        = request.GET.get("search", "").strip()
        branch_code   = request.data.get("auth-branch-code",   "system")
        hospital_code = request.data.get("auth-hospital-code", "system")
 
        if len(search) < 2:
            return Response({"success": True, "data": []})
 
        qs = VelavanItems.objects.filter(
            category__iexact="IMPLANT",
            is_active=True,
            branch_code=branch_code,
            hospital_code=hospital_code,
            itemName__icontains=search,
        ).values("id", "itemName", "hsn", "category")[:40]
 
        data = [
            {
                "item_id":  str(item["id"]),
                "itemName": item["itemName"],
                "hsn":      item["hsn"] or "",
                "category": item["category"],
            }
            for item in qs
        ]
 
        return Response({"success": True, "data": data})
 
    except Exception as e:
        return Response(
            {"success": False, "error": str(e), "traceback": traceback.format_exc()},
            status=500,
        )
 
# ─── 2. Save new implant request ──────────────────────────────────────────────
@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def save_implant_request(request):
    """
    Create a new ImplantRequest.

    Body:
        uhid          : patient UHID
        ipNumber      : IP number
        patient_name  : patient full name (stored for audit convenience)
        surgeryRef    : surgery schedule reference_no
        items         : [{ item_id, itemName, hsn, quantity }]

    Returns:
        { success: true, request_id: <ImplantRequest_id> }

    NOTE: ImplantRequest_id is generated inside ImplantRequest.save() itself
    (see models.py), so .create() below always returns an instance with
    ImplantRequest_id already set — no dependency on djongo's broken
    AutoField round-trip.

    NOTE: djongo's JSONField has been confirmed to store Python
    lists/dicts as a JSON-encoded STRING in Mongo (visible as
    "items": "[{...}]" with escaped quotes) instead of a native BSON
    array — i.e. it's effectively behaving like a TextField for this
    field type on this djongo version. To guarantee `items` is stored
    as a true array, we create the record via the ORM first (everything
    else is fine through djongo), then immediately overwrite just the
    `items` field with a raw pymongo update_one(), which writes native
    BSON and bypasses djongo's JSONField serialization entirely.
    """
    try:
        from ..models import ImplantRequest  # adjust import path to your app

        data          = request.data
        current_user  = data.get("auth-user-id",       "system")
        branch_code   = data.get("auth-branch-code",   "system")
        hospital_code = data.get("auth-hospital-code", "system")

        items = data.get("items", [])
        if not items:
            return Response(
                {"success": False, "message": "At least one item is required"},
                status=400,
            )

        # Strip any stray fields; keep only what we need
        ALLOWED_ITEM_FIELDS = {"item_id", "itemName", "hsn", "quantity"}
        cleaned_items = [
            {k: v for k, v in item.items() if k in ALLOWED_ITEM_FIELDS}
            for item in items
        ]
        for ci in cleaned_items:
            # Defensively normalize item_id — a missing/None value must
            # become "" here, never the literal string "None".
            item_id = ci.get("item_id")
            ci["item_id"] = str(item_id) if item_id else ""
            ci.setdefault("hsn", "")
            try:
                ci["quantity"] = int(ci.get("quantity", 1))
            except (ValueError, TypeError):
                ci["quantity"] = 1

        implant_req = ImplantRequest.objects.create(
            branch_code      = branch_code,
            hospital_code    = hospital_code,
            outlet_code      = data.get("outlet_code", ""),
            created_by       = current_user,
            created_date     = timezone.now(),
            uhid             = data.get("uhid", ""),
            inpatient_number = data.get("ipNumber", ""),
            surgery_ref      = data.get("surgeryRef", ""),
            items            = [],  # set below via raw pymongo write
            status           = "Pending",
            is_active        = True,
        )

        # Overwrite `items` with a raw pymongo write so it's stored as a
        # native array, bypassing djongo's JSONField stringification.
        hms_db["hospital_implant_request"].update_one(
            {"ImplantRequest_id": implant_req.ImplantRequest_id},
            {"$set": {"items": cleaned_items}},
        )

        return Response(
            {
                "success":    True,
                "message":    "Implant request saved successfully",
                "request_id": implant_req.ImplantRequest_id,
            },
            status=201,
        )

    except Exception as e:
        return Response(
            {"success": False, "error": str(e), "traceback": traceback.format_exc()},
            status=500,
        )


# ─── 3. List implant requests for a patient ───────────────────────────────────
@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_implant_requests(request):
    """
    Fetch all active implant requests for a given UHID / IP number.

    Query params:
        uhid      — required
        ipNumber  — optional additional filter

    Returns:
        { success: true, count: N, data: [...] }

    NOTE: djongo (1.3.6) cannot translate a bare-column BooleanField filter
    (e.g. .filter(is_active=True), which Django compiles to the SQL form
    `WHERE "table"."is_active"` rather than `WHERE "table"."is_active" = true`)
    into a Mongo query — its sql2mongo WHERE-clause parser crashes with
    `AttributeError: 'NoneType' object has no attribute 'lhs'` because it
    expects every WHERE token to be part of a binary lhs/op/rhs comparison,
    and a bare boolean column reference has no operator.
    This happens even with a SINGLE boolean filter and no other conditions,
    so any .filter(...) call that includes a BooleanField kwarg is unsafe on
    this djongo version. We avoid the issue entirely by not filtering in the
    ORM at all — fetch everything with .all() and do all filtering (uhid,
    ipNumber, is_active) and sorting in Python.
    """
    try:
        from ..models import ImplantRequest  # adjust import path to your app

        uhid      = request.query_params.get("uhid", "").strip()
        ip_number = request.query_params.get("ipNumber", "").strip()

        if not uhid:
            return Response(
                {"success": False, "error": "UHID is required"},
                status=400,
            )

        def _normalize_items(raw):
            """
            `items` should be a native list (post-fix records use a raw
            pymongo write to guarantee this). Older records saved before
            this fix may still have `items` stored as a JSON-encoded
            string by djongo's JSONField — handle both so old and new
            documents read back correctly.
            """
            if isinstance(raw, list):
                return raw
            if isinstance(raw, str):
                try:
                    parsed = json.loads(raw)
                    return parsed if isinstance(parsed, list) else []
                except (ValueError, TypeError):
                    return []
            return []

        # No .filter(...) at all — djongo 1.3.6 cannot safely translate even
        # a single BooleanField filter. Fetch everything and filter in Python.
        qs = ImplantRequest.objects.all()

        records = [
            rec for rec in qs
            if rec.is_active
            and rec.uhid == uhid
            and (not ip_number or rec.inpatient_number == ip_number)
        ]
        records.sort(
            key=lambda r: r.created_date or timezone.now(),
            reverse=True,
        )

        ist = pytz.timezone("Asia/Kolkata")

        formatted = []
        for rec in records:
            created = rec.created_date
            if created and created.tzinfo is None:
                created = pytz.utc.localize(created)
            if created:
                created = created.astimezone(ist)

            formatted.append(
                {
                    "request_id":  rec.ImplantRequest_id,
                    "uhid":        rec.uhid,
                    "ipNumber":    rec.inpatient_number,
                    "surgeryRef":  rec.surgery_ref or "",
                    "items":       _normalize_items(rec.items),
                    "status":      rec.status,
                    "reqDate":     created.strftime("%d-%m-%Y") if created else "",
                    "reqTime":     created.strftime("%I:%M %p") if created else "",
                    "created_by":  rec.created_by or "",
                    "branch_code": rec.branch_code or "",
                }
            )

        return Response({"success": True, "count": len(formatted), "data": formatted})

    except Exception as e:
        return Response(
            {"success": False, "error": str(e), "traceback": traceback.format_exc()},
            status=500,
        )


# ─── 4. Update implant request (Pending only) ─────────────────────────────────
@api_view(["PUT"])
@permission_classes([HasRoleAndDataPermission])
def update_implant_request(request):
    """
    Update items on an existing ImplantRequest.
    Only allowed when status == 'Pending'.

    Body:
        request_id  : ImplantRequest_id
        items       : [{ item_id, itemName, hsn, quantity }]

    Returns:
        { success: true }
    """
    try:
        from ..models import ImplantRequest  # adjust import path to your app

        data         = request.data
        current_user = data.get("auth-user-id", "system")
        request_id   = data.get("request_id")

        if not request_id:
            return Response(
                {"success": False, "message": "request_id is required"},
                status=400,
            )

        try:
            request_id = int(request_id)
        except (ValueError, TypeError):
            return Response(
                {"success": False, "message": "request_id must be a number"},
                status=400,
            )

        # Single-field filter to stay djongo-safe; check is_active in Python.
        implant_req = ImplantRequest.objects.filter(
            ImplantRequest_id=request_id
        ).first()

        if not implant_req or not implant_req.is_active:
            return Response(
                {"success": False, "message": "Record not found"},
                status=404,
            )

        if implant_req.status != "Pending":
            return Response(
                {
                    "success": False,
                    "message": f"Cannot edit a request with status '{implant_req.status}'",
                },
                status=400,
            )

        items = data.get("items", [])
        if not items:
            return Response(
                {"success": False, "message": "At least one item is required"},
                status=400,
            )

        ALLOWED_ITEM_FIELDS = {"item_id", "itemName", "hsn", "quantity"}
        cleaned_items = [
            {k: v for k, v in item.items() if k in ALLOWED_ITEM_FIELDS}
            for item in items
        ]
        for ci in cleaned_items:
            # Defensively normalize item_id — a missing/None value must
            # become "" here, never the literal string "None".
            item_id = ci.get("item_id")
            ci["item_id"] = str(item_id) if item_id else ""
            ci.setdefault("hsn", "")
            try:
                ci["quantity"] = int(ci.get("quantity", 1))
            except (ValueError, TypeError):
                ci["quantity"] = 1

        implant_req.lastmodified_by   = current_user
        implant_req.lastmodified_date = timezone.now()
        implant_req.save()

        # Write `items` via raw pymongo so it's stored as a native array,
        # bypassing djongo's JSONField stringification (same reasoning as
        # save_implant_request above).
        hms_db["hospital_implant_request"].update_one(
            {"ImplantRequest_id": request_id},
            {"$set": {"items": cleaned_items}},
        )

        return Response(
            {"success": True, "message": "Implant request updated successfully"}
        )

    except Exception as e:
        return Response(
            {"success": False, "error": str(e), "traceback": traceback.format_exc()},
            status=500,
        )


# ─── 5. Soft-delete implant request (Pending only) ────────────────────────────
@api_view(["PUT"])
@permission_classes([HasRoleAndDataPermission])
def delete_implant_request(request):
    """
    Soft-delete: sets is_active = False.
    Only allowed when status == 'Pending'.

    Body:
        request_id : ImplantRequest_id

    Returns:
        { success: true }
    """
    try:
        from ..models import ImplantRequest  # adjust import path to your app

        data         = request.data
        current_user = data.get("auth-user-id", "system")
        request_id   = data.get("request_id")

        if not request_id:
            return Response(
                {"success": False, "message": "request_id is required"},
                status=400,
            )

        try:
            request_id = int(request_id)
        except (ValueError, TypeError):
            return Response(
                {"success": False, "message": "request_id must be a number"},
                status=400,
            )

        # Single-field filter to stay djongo-safe; check is_active in Python.
        implant_req = ImplantRequest.objects.filter(
            ImplantRequest_id=request_id
        ).first()

        if not implant_req or not implant_req.is_active:
            return Response(
                {"success": False, "message": "Record not found"},
                status=404,
            )

        if implant_req.status != "Pending":
            return Response(
                {
                    "success": False,
                    "message": f"Cannot delete a request with status '{implant_req.status}'",
                },
                status=400,
            )

        implant_req.is_active         = False
        implant_req.lastmodified_by   = current_user
        implant_req.lastmodified_date = timezone.now()
        implant_req.save()

        return Response(
            {"success": True, "message": "Implant request deleted successfully"}
        )

    except Exception as e:
        return Response(
            {"success": False, "error": str(e), "traceback": traceback.format_exc()},
            status=500,
        )