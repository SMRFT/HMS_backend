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
def get_ippharmacy_stock(request):
    try:
        # ✅ Dynamic department (code1)
        outlet_code = request.GET.get("outlet_code", "OLET001")

        # ✅ Mongo connection (code2)
        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        mongo_db = client["HMS"]

        pipeline = [

            # ✅ Filter department
            {
                "$match": {
                    "outlet_code": outlet_code
                }
            },

            # ✅ Join item master
            {
                "$lookup": {
                    "from": "hospital_pharmacyitem",
                    "localField": "item_id",
                    "foreignField": "item_id",
                    "as": "item_details"
                }
            },

            {
                "$unwind": {
                    "path": "$item_details",
                    "preserveNullAndEmptyArrays": False
                }
            },

            # ✅ Only active items
            {
                "$match": {
                    "item_details.is_blocked": False,
                    "item_details.is_active": True
                }
            },

            # ✅ Calculate stock + reorder level
            {
                "$addFields": {
                    "available_stock": {
                        "$add": [
                            {
                                "$subtract": [
                                    {
                                        "$subtract": [
                                            {
                                                "$subtract": [
                                                    {
                                                        "$subtract": [
                                                            "$total_stock",
                                                            {"$ifNull": ["$sold_quantity", 0]}
                                                        ]
                                                    },
                                                    {"$ifNull": ["$transferred_out_quantity", 0]}
                                                ]
                                            },
                                            {"$ifNull": ["$grn_return_quantity", 0]}
                                        ]
                                    },
                                    {"$ifNull": ["$blocked_quantity", 0]}
                                ]
                            },
                            {"$ifNull": ["$sales_return_quantity", 0]}
                        ]
                    },

                    # ✅ Ensure reorder_level exists
                    "reorder_level": {
                        "$ifNull": ["$item_details.reorder_level", 0]
                    }
                }
            },

            # ✅ Low stock flag
            {
                "$addFields": {
                    "is_low_stock": {
                        "$cond": {
                            "if": {
                                "$lte": ["$available_stock", "$reorder_level"]
                            },
                            "then": True,
                            "else": False
                        }
                    }
                }
            },

            # ✅ Final projection
            {
                "$project": {
                    "_id": 0,

                    "org_id": 1,
                    "branch_code": 1,
                    "department_code": 1,
                    "item_id": 1,
                    "batch_number": 1,
                    "expiry_date": 1,
                    "total_stock": 1,
                    "mrp": 1,
                    "grn_number": 1,

                    "sold_quantity": 1,
                    "transferred_out_quantity": 1,
                    "sales_return_quantity": 1,

                    "available_stock": 1,
                    "reorder_level": 1,
                    "is_low_stock": 1,

                    # ✅ Item details
                    "item_name": "$item_details.item_name",
                    "item_last_name": "$item_details.item_last_name",
                    "category": "$item_details.category",
                    "hsn_code": "$item_details.hsn",

                    "high_risk": "$item_details.high_risk",
                    "look_alike": "$item_details.look_alike",
                    "sound_alike": "$item_details.sound_alike",

                    # ✅ Tax
                    "CGST_Percentage": 1,
                    "SGST_Percentage": 1,
                    "CGST_Amt": 1,
                    "SGST_Amt": 1
                }
            }
        ]

        data = list(mongo_db["hospital_pharmacystock"].aggregate(pipeline))

        # ✅ Convert Decimal128 → float
        data = convert_decimals(data)

        return JsonResponse({
            "success": True,
            "data": data
        }, safe=False)

    except Exception as e:
        print("Error in get_oppharmacy_stock:", str(e))
        return JsonResponse({
            "success": False,
            "message": str(e)
        }, status=500)




@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def save_ot_medicine_ward_request(request):
    """
    Save OT medicine ward request using PharmacyBilling model.
    Bill_id is auto-generated in PharmacyBilling.save()
    """

    try:
        data = request.data

        current_user = data.get("auth-user-id", "system")
        branch_code = data.get("auth-branch-code", "system")
        hospital_code = data.get("auth-hospital-code", "system")
        # outlet_code = data.get("auth-outlet-code", "OLET001")

        medicine_particulars = data.get("medicine_particulars", [])
        total_amount = round(float(data.get("total_amount", 0)), 2)

        # Remove fields that should not be stored in medicine_particulars
        STRIP_FIELDS = {
            "edit_history",
            "billType",
            "billTypeNo",
            "billTypeName",
            "total_stock",
            "price",
            "expiry_date",
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
            cleaned.setdefault("quantity", cleaned.get("qty", 0))

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
            edit_history=[],

            cashier_id="",
        )

        return Response(
            {
                "success": True,
                "message": "OT medicine ward request saved successfully",
                "bill_id": bill.Bill_id,
                "billing_status": bill.billing_status,
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
                {
                    "success": False,
                    "error": "UHID is required"
                },
                status=400
            )

        query_params = {
            "uhid": uhid,
            "is_ward_request": True
        }

        if ip_number:
            query_params["inpatient_number"] = ip_number

        ward_req_collection = hms_db["hospital_pharmacybilling"]

        requests_data = list(
            ward_req_collection.find(query_params).sort("ward_request_date", -1)
        )

        # Fetch bill type names
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

        formatted_data = []
        ist = pytz.timezone("Asia/Kolkata")

        for doc in requests_data:
            items = doc.get("medicine_particulars", [])

            # If medicine_particulars is stored as string, convert to list
            if isinstance(items, str):
                try:
                    items = json.loads(items)
                except Exception:
                    items = []

            medicines = []

            for itm in items:
                # Handle if medicine item itself is a stringified JSON
                if isinstance(itm, str):
                    try:
                        itm = json.loads(itm)
                    except Exception:
                        continue

                if not isinstance(itm, dict):
                    continue

                medicines.append({
                    "item_id": itm.get("item_id", ""),
                    "name": itm.get("itemName", itm.get("item_name", "")),
                    "quantity": itm.get("quantity", itm.get("qty", 1)),
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

            # Convert Mongo UTC datetime to IST
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
                "doctor": doc.get("doctor", ""),
                "doctorName": doc.get("doctor_id", ""),
                "wardName": doc.get("room_no", ""),
                "billingStatus": doc.get("billing_status", ""),
                "billingMode": doc.get("billing_mode", ""),
                "medicines": medicines,
                "total_amount": doc.get("total_amount", 0),
                "net_amount": doc.get("net_amount", 0)
            }

            formatted_data.append(formatted_doc)

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