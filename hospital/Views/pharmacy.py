from django.http import JsonResponse
from pymongo import MongoClient
import os
import json
import pytz
from datetime import datetime, date
from decimal import Decimal, InvalidOperation

from bson import ObjectId
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework import status
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.db import DatabaseError
from django.utils import timezone
from django.db.models import Max

# Auth/permissions
from pyauth.auth import HasRoleAndDataPermission, HasRolePermission

# Models & Serializers
from ..models import Patient, PharmacyStock, PharmacyBilling, PharmacyItem
from ..serializers import PharmacyBillingSerializer

# MongoDB Configuration
MONGO_URI = os.getenv("GLOBAL_DB_HOST")
DB_NAME = "HMS"
COLLECTION_NAME = "hospital_oppharmacystock"

client = MongoClient(MONGO_URI)
mongo_db = client[DB_NAME]
stock_collection = mongo_db["hospital_oppharmacystock"]
bill_collection = mongo_db["hospital_pharmacybilling"]

from bson.decimal128 import Decimal128

def convert_decimals(obj):
    if isinstance(obj, list):
        return [convert_decimals(i) for i in obj]
    elif isinstance(obj, dict):
        return {k: convert_decimals(v) for k, v in obj.items()}
    elif isinstance(obj, Decimal128):
        return float(obj.to_decimal())
    return obj



@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def get_oppharmacy_stock(request):
    try:
        # ✅ Get values
        print("test", request.data.get("outlet_code"))
        hospital_code = request.data.get("auth-hospital-code")
        branch_code = request.data.get("auth-branch-code")
        outlet_code = request.data.get("auth-outlet-code")

        print("hospital_code:", hospital_code)
        print("branch_code:", branch_code)
        print("outlet_code:", outlet_code)

        if not hospital_code or not branch_code or not outlet_code:
            return JsonResponse({
                "success": False,
                "message": "Missing hospital_code / branch_code / outlet_code"
            }, status=400)

        # ✅ Mongo connection
        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        mongo_db = client["HMS"]

        # ✅ MATCH STOCK STRICTLY
        match_stage = {
            "hospital_code": hospital_code,
            "branch_code": branch_code,
            "outlet_code": outlet_code   # ✅ IMPORTANT FIX
        }

        pipeline = [

            # ✅ FILTER STOCK
            {
                "$match": match_stage
            },

            # ✅ JOIN ITEM MASTER (STRICT MATCH)
            {
                "$lookup": {
                    "from": "hospital_pharmacyitem",
                    "let": {
                        "item_id": "$item_id",
                        "branch_code": "$branch_code",
                        "hospital_code": "$hospital_code"
                    },
                    "pipeline": [
                        {
                            "$match": {
                                "$expr": {
                                    "$and": [
                                        {"$eq": ["$item_id", "$$item_id"]},
                                        {"$eq": ["$branch_code", "$$branch_code"]},
                                        {"$eq": ["$hospital_code", "$$hospital_code"]}  # ✅ FIX
                                    ]
                                }
                            }
                        }
                    ],
                    "as": "item_details"
                }
            },

            # ✅ REMOVE NON-MATCHED ITEMS
            {
                "$unwind": {
                    "path": "$item_details",
                    "preserveNullAndEmptyArrays": False
                }
            },

            # ✅ ACTIVE ITEMS ONLY
            {
                "$match": {
                    "item_details.is_blocked": False,
                    "item_details.is_active": True
                }
            },

            # ✅ STOCK CALCULATION
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
                    "reorder_level": {
                        "$ifNull": ["$item_details.reorder_level", 0]
                    }
                }
            },

            # ✅ LOW STOCK
            {
                "$addFields": {
                    "is_low_stock": {
                        "$lte": ["$available_stock", "$reorder_level"]
                    }
                }
            },

            # ✅ FINAL RESPONSE
            {
                "$project": {
                    "_id": 0,
                    "hospital_code": 1,
                    "branch_code": 1,
                    "outlet_code": 1,

                    "item_id": 1,
                    "batch_number": 1,
                    "expiry_date": 1,
                    "total_stock": 1,
                    "mrp": 1,

                    "available_stock": 1,
                    "reorder_level": 1,
                    "is_low_stock": 1,

                    "item_name": "$item_details.item_name",
                    "category": "$item_details.category",
                    "hsn_code": "$item_details.hsn",

                    "CGST_Percentage": 1,
                    "SGST_Percentage": 1
                }
            }
        ]

        result = list(mongo_db["hospital_pharmacystock"].aggregate(pipeline))
        result = convert_decimals(result)

        return JsonResponse({
            "success": True,
            "data": result
        })

    except Exception as e:
        print("Error:", str(e))
        return JsonResponse({
            "success": False,
            "message": str(e)
        }, status=500)






from datetime import datetime
from pymongo import MongoClient
import os

# ----------------------------------------------------------
# SANITIZE MEDICINES
# ----------------------------------------------------------
def sanitize_medicines(medicines):
    cleaned = []

    for m in medicines:
        cleaned.append({
            "item_id": int(m.get("item_id", 0)),
            "batch_number": str(m.get("batch_number", "")).strip(),
            "qty": float(m.get("qty", 0)),
            "price": float(m.get("price", 0)),
            "edit_history": m.get("edit_history", [])
        })

    return cleaned


# ----------------------------------------------------------
# CHECK QTY CHANGE (NEW)
# ----------------------------------------------------------
def has_qty_changed(old_meds, new_meds):
    def safe_key(m):
        return (
            int(m.get("item_id", 0)),
            str(m.get("batch_number", "")).strip()
        )

    old_map = {safe_key(m): float(m.get("qty", 0)) for m in old_meds}
    new_map = {safe_key(m): float(m.get("qty", 0)) for m in new_meds}

    keys = set(old_map.keys()).union(new_map.keys())

    for key in keys:
        if old_map.get(key, 0) != new_map.get(key, 0):
            return True

    return False


# ----------------------------------------------------------
# STOCK UPDATE
# ----------------------------------------------------------
def adjust_blocked_stock(old_meds, new_meds, hospital_code, branch_code, outlet_code):

    client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
    db = client["HMS"]
    stock_collection = db["hospital_pharmacystock"]

    def safe_key(m):
        return (
            int(m.get("item_id", 0)),
            str(m.get("batch_number", "")).strip()
        )

    old_map = {safe_key(m): m for m in old_meds if m.get("item_id")}
    new_map = {safe_key(m): m for m in new_meds if m.get("item_id")}

    keys = set(old_map.keys()).union(new_map.keys())

    for key in keys:

        old_qty = float(old_map.get(key, {}).get("qty", 0))
        new_qty = float(new_map.get(key, {}).get("qty", 0))

        diff = new_qty - old_qty

        if diff == 0:
            continue

        item_id, batch_number = key

        if not batch_number:
            continue

        stock_collection.update_one(
            {
                "hospital_code": hospital_code,
                "branch_code": branch_code,
                "outlet_code": outlet_code,
                "item_id": item_id,
                "batch_number": batch_number
            },
            [
                {
                    "$set": {
                        "blocked_quantity": {
                            "$max": [
                                {"$add": ["$blocked_quantity", diff]},
                                0
                            ]
                        }
                    }
                }
            ]
        )


# ----------------------------------------------------------
# EDIT HISTORY
# ----------------------------------------------------------
def build_edit_history(old_meds, new_meds, employee_id):

    updated = []

    def safe_key(m):
        return (
            int(m.get("item_id", 0)),
            str(m.get("batch_number", "")).strip()
        )

    old_map = {safe_key(m): m for m in old_meds if m.get("item_id")}
    new_map = {safe_key(m): m for m in new_meds if m.get("item_id")}

    keys = set(old_map.keys()).union(new_map.keys())

    for key in keys:

        old = old_map.get(key)
        new = new_map.get(key)

        now = datetime.utcnow().isoformat()

        if not old and new:
            new.setdefault("edit_history", [])
            new["edit_history"].append({
                "action": "medicine_added",
                "qty": new.get("qty", 0),
                "blocked_change": new.get("qty", 0),
                "timestamp": now,
                "edited_by": employee_id
            })
            updated.append(new)

        elif old and not new:
            old.setdefault("edit_history", [])
            old["edit_history"].append({
                "action": "medicine_deleted",
                "qty_deleted": old.get("qty", 0),
                "blocked_change": -old.get("qty", 0),
                "timestamp": now,
                "edited_by": employee_id
            })
            updated.append(old)

        elif old and new:
            old_qty = float(old.get("qty", 0))
            new_qty = float(new.get("qty", 0))

            history = old.get("edit_history", [])

            if old_qty != new_qty:
                diff = new_qty - old_qty

                history.append({
                    "action": "qty_added" if diff > 0 else "qty_deleted",
                    "old_qty": old_qty,
                    "new_qty": new_qty,
                    "blocked_change": diff,
                    "timestamp": now,
                    "edited_by": employee_id
                })

            new["edit_history"] = history
            updated.append(new)

    return updated


# ----------------------------------------------------------
# MAIN API
# ----------------------------------------------------------
@api_view(["POST", "PATCH"])
@permission_classes([HasRoleAndDataPermission])
def save_oppharmacy_bill(request):

    data = request.data

    employee_id = data.get("auth-user-id")
    hospital_code = data.get("auth-hospital-code")
    branch_code = request.data.get("auth-branch-code")
    outlet_code = request.data.get("auth-outlet-code")

    status_raw = str(data.get("status", "")).strip().lower()

    if status_raw in ["estimate", "estimated"]:
        status = "Estimate"
    elif status_raw == "billed":
        status = "Billed"
    else:
        return Response({"success": False, "message": "Invalid status"})

    Bill_id = data.get("Bill_id")
    medicines = sanitize_medicines(data.get("medicine_particulars") or [])

    fields = {
        "uhid": data.get("uhid"),
        "inpatient_number": data.get("inpatient_number"),
        "bill_type": data.get("bill_type"),
        "doctor_id": data.get("doctor_id"),
        "room_no": data.get("room_no"),
        "total_amount": float(data.get("total_amount", 0)),
        "overall_discount_type": data.get("overall_discount_type"),
        "overall_discount_value": float(data.get("overall_discount_value", 0)),
        "overall_discount_amount": float(data.get("overall_discount_amount", 0)),
        "net_amount": float(data.get("net_amount", 0)),
    }

    # ======================================================
    # PATCH
    # ======================================================
    if request.method == "PATCH":

        if not Bill_id:
            return Response({"success": False, "message": "Bill_id required"})

        try:
            record = PharmacyBilling.objects.get(Bill_id=int(Bill_id))
        except PharmacyBilling.DoesNotExist:
            return Response({"success": False, "message": "Record not found"})

        old_meds = record.medicine_particulars or []
        is_edit = data.get("is_edit", False)

        updated_meds = (
            build_edit_history(old_meds, medicines, employee_id)
            if is_edit else medicines
        )

        # ✅ CHECK QTY CHANGE
        qty_changed = has_qty_changed(old_meds, updated_meds)

        # ✅ SKIP CONDITION
        # Only skip blocked_quantity update when converting a plain Estimate → Billed
        # with no qty change. Do NOT skip for ward requests (is_ward_request=True),
        # because ward request → bill must always update blocked_quantity.
        is_ward_request_record = getattr(record, "is_ward_request", False)

        skip_block_update = (
            not is_ward_request_record and          # FIX #3: never skip for ward requests
            record.billing_status == "Estimate" and
            status == "Billed" and
            not qty_changed
        )

        if is_ward_request_record and not skip_block_update:
            adjust_blocked_stock(
                old_meds,
                updated_meds,
                hospital_code,
                branch_code,
                outlet_code
            )

        update_data = {
            **fields,
            "medicine_particulars": updated_meds,
            "hospital_code": hospital_code,
            "branch_code": branch_code,
            "lastmodified_by": employee_id,
            "lastmodified_date": datetime.utcnow(),
            "pharmacist_id": employee_id
        }

        if status == "Estimate":
            update_data.update({
                "billing_status": "Estimate",
                # FIX #1: Do NOT set billing_mode here — preserve existing value.
                # billing_mode is set only at creation time and must not be overwritten.
                "billing_mode": "ESTIMATE",
                "Esimated_id": employee_id
            })

        elif status == "Billed":

            if not record.bill_no:
                update_data["bill_no"] = get_last_oppharmacy_billno(get_financial_year())

            update_data.update({
                "billing_status": "Billed",
                # FIX #1 & #2: Do NOT hardcode billing_mode to "DIRECT" here.
                # The frontend sends the correct billing_mode ("ESTIMATE" for
                # estimate-converted bills, "WARD_REQUEST" for medicine-chart
                # conversions, "DIRECT" for new direct bills).
                # Preserve the incoming billing_mode from the request payload.
                "billing_mode": data.get("billing_mode", record.billing_mode or "DIRECT"),
                "is_ward_request": False,
                "Edit_reason": data.get("edit_reason"),
                "Edited_by": employee_id
            })

        bill_collection.update_one(
            {"Bill_id": int(Bill_id)},
            {"$set": update_data}
        )

        record.refresh_from_db()

        return Response({
            "success": True,
            "message": "Bill updated successfully",
            "Bill_id": record.Bill_id,
            "bill_no": record.bill_no,
            "estimate_no": record.estimate_no
        })

    # ======================================================
    # POST
    # ======================================================
    if request.method == "POST":

        last = PharmacyBilling.objects.order_by('-Bill_id').first()
        next_Bill_id = (last.Bill_id + 1) if last else 1

        record_doc = {
            "Bill_id": next_Bill_id,
            "medicine_particulars": medicines,
            "billing_status": status,
            "created_by": employee_id,
            "outlet_code": outlet_code,
            "pharmacist_id": employee_id,
            "hospital_code": hospital_code,
            "branch_code": branch_code,
            "created_date": datetime.utcnow(),
            "bill_date": datetime.utcnow(),
            "is_deleted": False,
            **fields
        }

        if status == "Billed":

            bill_no = get_last_oppharmacy_billno(get_financial_year())

            record_doc.update({
                "bill_no": bill_no,
                "billing_mode": "DIRECT",
                "is_ward_request": False
            })

            bill_collection.insert_one(record_doc)

            adjust_blocked_stock([], medicines, hospital_code, branch_code, outlet_code)

            return Response({
                "success": True,
                "message": f"Bill created successfully. Bill No: {bill_no}",
                "Bill_id": next_Bill_id
            })

        if status == "Estimate":

            estimate_no = generate_estimate_no()

            record_doc.update({
                "estimate_no": estimate_no,
                "billing_mode": "ESTIMATE",
                "is_ward_request": False
            })

            bill_collection.insert_one(record_doc)

            adjust_blocked_stock([], medicines, hospital_code, branch_code, outlet_code)

            return Response({
                "success": True,
                "message": f"Estimate created successfully. Estimate No: {estimate_no}",
                "Bill_id": next_Bill_id
            })

    return Response({"success": False, "message": "Invalid request"})

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_pharmacy_BillType(request):
    db = client["HMS"]
    stock_collection = db["hospital_billtype"]

    # ✅ Get values from headers
    hospital_code = request.data.get("auth-hospital-code")
    branch_code = request.data.get("auth-branch-code")
    outlet_code = request.data.get("auth-outlet-code")
    print(request.data.get)
    print("hospital_code:", hospital_code)
    print("branch_code:", branch_code)
    print("outlet_code:", outlet_code)

    # ✅ Build dynamic filter (avoid None values)
    filter_query = {
        "is_active": True
    }

    if hospital_code:
        filter_query["hospital_code"] = hospital_code
    if branch_code:
        filter_query["branch_code"] = branch_code
    if outlet_code:
        filter_query["outlet_code"] = outlet_code

    # ✅ Fetch data
    cursor = stock_collection.find(filter_query)
    billtypes = list(cursor)

    # ✅ Convert ObjectId to string
    for bill in billtypes:
        bill["_id"] = str(bill["_id"])

    return Response({
        "status": True,
        "data": billtypes
    })

def get_financial_year():
    today = date.today()
    year = today.year

    if today.month >= 4:  # April onwards
        start = year % 100
        end = (year + 1) % 100
    else:
        start = (year - 1) % 100
        end = year % 100

    return f"{start:02d}{end:02d}"

# HELPER: GET LAST BILL NO

def get_last_oppharmacy_billno(fy):
    last_bill = (
        PharmacyBilling.objects
        .filter(bill_no__startswith=f"{fy}/")
        .order_by("-bill_no")
        .first()
    )

    if not last_bill:
        return f"{fy}/000001"

    last_no = int(last_bill.bill_no.split("/")[-1])
    next_no = last_no + 1

    return f"{fy}/{next_no:06d}"



@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_last_billed_uhid(request):

    # 1️⃣ Get latest bill
    last_bill = (
        PharmacyBilling.objects
        .order_by("-bill_date")
        .first()
    )

    if not last_bill:
        return Response({
            "success": False,
            "message": "No records found"
        })

    # 2️⃣ Get patient using UHID
    patient = Patient.objects.filter(uhid=last_bill.uhid).first()

    if not patient:
        return Response({
            "success": False,
            "message": "Patient not found"
        })

    # 3️⃣ Prepare full response
    full_name = f"{patient.salutation or ''} {patient.firstName or ''} {patient.lastName or ''}".strip()

    return Response({
        "success": True,
        "data": {
            # 🔹 Patient Details
            "uhid": patient.uhid,
            "patient_name": full_name,
            "inpatient_number": patient.ip_number,
            "age": patient.age,
            "gender": patient.gender,
            "mobile": patient.mobilePhone,
            "city": patient.city,
            "blood_group": patient.blood_group,

            # 🔹 Bill Details
            "doctor_id": last_bill.doctor_id,
            "room_no": last_bill.room_no,
            "bill_type": last_bill.bill_type,
            "bill_no": last_bill.bill_no,
            "bill_date": last_bill.bill_date,
        }
    })


# HELPER: GENERATE ESTIMATE NO
@permission_classes([HasRoleAndDataPermission])
def generate_estimate_no():
    last = PharmacyBilling.objects.aggregate(
        Max("estimate_no")
    )["estimate_no__max"]

    if last:
        next_no = int(last) + 1
    else:
        next_no = 1

    return f"{next_no:06d}" 


@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def save_oppharmacy_estimate(request):

    data = request.data.copy()

    # ✅ Get employee id from auth payload
    employee_id = data.get("auth-user-id")

    # ✅ Indian Timezone (IST)
    india_tz = pytz.timezone("Asia/Kolkata")
    now_ist = timezone.now().astimezone(india_tz)

    # ✅ Add audit fields
    data["created_by"] = employee_id
    data["created_date"] = now_ist   # timezone-aware datetime
    data["is_active"] = True
    data["billing_status"] = "Estimate"

    # Calculate next Bill_id if using PyMongo
    last = PharmacyBilling.objects.order_by('-Bill_id').first()
    next_Bill_id = (last.Bill_id + 1) if last else 1

    medicines = sanitize_medicines(data.get("medicine_particulars", []))

    record_doc = {
        "Bill_id": next_Bill_id,
        "uhid": data.get("uhid"),
        "inpatient_number": data.get("inpatient_number"),
        "bill_type": data.get("bill_type"),
        "doctor_id": data.get("doctor_id"),
        "room_no": data.get("room_no"),
        "total_amount": float(data.get("total_amount", 0)),
        "overall_discount_type": data.get("overall_discount_type"),
        "overall_discount_value": float(data.get("overall_discount_value", 0)),
        "overall_discount_amount": float(data.get("overall_discount_amount", 0)),
        "round_off": float(data.get("round_off", 0)),
        "net_amount": float(data.get("net_amount", 0)),
        "medicine_particulars": medicines,
        "billing_status": "Estimate",
        "billing_mode": "ESTIMATE",
        "estimate_no": generate_estimate_no(),
        "created_by": employee_id,
        "created_date": now_ist,
        "bill_date": now_ist,
        
    }

    result = bill_collection.insert_one(record_doc)

    if result.inserted_id:
        return Response(
            {
                "success": True,
                "estimate_no": record_doc["estimate_no"],
                "Bill_id": next_Bill_id
            },
            status=201
        )

    return Response({"error": "Failed to save estimate"}, status=400)



@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_active_estimates(request):
  
    estimates = PharmacyBilling.objects.filter(billing_status="Estimate")
    serializer = PharmacyBillingSerializer(estimates, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)



from ..models import PharmacyItem
import json

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_estimate_bills(request):
    try:

        hospital_code = request.data.get("auth-hospital-code")
        branch_code = request.data.get("auth-branch-code")
        outlet_code = request.data.get("auth-outlet-code")

        bills = PharmacyBilling.objects.filter(
            billing_status="Estimate",
            hospital_code=hospital_code,
            branch_code=branch_code,
            outlet_code=outlet_code
        )

        data = []

        for bill in bills:
            # ✅ Get patient using UHID
            patient = Patient.objects.filter(uhid=bill.uhid).first()

            patient_name = ""
            if patient:
                patient_name = f"{patient.firstName} {patient.lastName}"

            meds = bill.medicine_particulars

            # ✅ Handle both string and list
            if isinstance(meds, str):
                meds = json.loads(meds)

            particulars = []

            for med in meds:
                item_id = med.get("item_id")
                batch_no = med.get("batch_number")

                item = PharmacyItem.objects.filter(item_id=item_id).first()

                particulars.append({
                    "item_id": item_id,
                    "item_name": item.item_name if item else "",
                    "batch_number": batch_no,
                    "qty": med.get("qty"),
                    "Price": med.get("price"),
                })

            data.append({
                "created_date": bill.created_date,
                "lastmodified_date": bill.lastmodified_date,
                "created_by": bill.created_by,
                "lastmodified_by": bill.lastmodified_by,
                "bill_no": bill.bill_no,
                "Bill_id": bill.Bill_id,
                "estimate_no": bill.estimate_no,
                "bill_date": bill.bill_date,
                "uhid": bill.uhid,
                "inpatient_number": bill.inpatient_number,
                "bill_type": bill.bill_type,
                "patient_name": patient_name,
                "doctor_id": bill.doctor_id,
                "room_no": bill.room_no,
                "medicine_particulars": particulars,
                "total_amount": bill.total_amount,
                "overall_discount_type": bill.overall_discount_type,
                "overall_discount_value": bill.overall_discount_value,
                "overall_discount_amount": bill.overall_discount_amount,
                "net_amount": bill.net_amount,
                "round_off": bill.round_off,
                "billing_status": bill.billing_status,
                "billing_mode": bill.billing_mode,
                "payment_details": bill.payment_details,
                "cashier_id": bill.cashier_id,
            })

        return Response(data)

    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def convert_estimate_to_bill(request, estimate_no):

    estimate = PharmacyBilling.objects.get(
        estimate_no=estimate_no,
        billing_status="Estimate"
    )

    medicines = estimate.medicine_particulars
    if isinstance(medicines, str):
        medicines = json.loads(medicines)

    converted_items = []

    for m in medicines:
        converted_items.append({
            "item_id": m.get("item_id"),
            "batch_number": m.get("batch_number"),
            "qty": m.get("qty"),
            "price": m.get("price") or m.get("Price") or 0,
            "edit_history": m.get("edit_history", [])
        })

    # Re-fetch patient name for the response payload
    patient = Patient.objects.filter(uhid=estimate.uhid).first()
    patient_name = patient.patient_name if patient else ""

    data = {
        "patient_name": patient_name,
        "uhid": estimate.uhid,
        "inpatient_number": estimate.inpatient_number,
        "doctor_id": estimate.doctor_id,
        "room_no": estimate.room_no,
        "bill_type": estimate.bill_type,
        "bill_name": estimate.bill_name,
        "medicine_particulars": converted_items,
        "net_amount": estimate.net_amount
    }

    # deactivate estimate
    estimate.is_active = False
    estimate.save()

    return Response({
        "success": True,
        "data": data
    })





from pymongo import MongoClient
import os
import ast

from bson.decimal128 import Decimal128

def convert_decimal(value):
    if isinstance(value, Decimal128):
        return float(value.to_decimal())
    try:
        return float(value)
    except:
        return 0.0


from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from pymongo import MongoClient
import os

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def OPPharmacy_pending_bills(request):

    # =========================================================
    # ✅ Get values from HEADERS (FIXED)
    # =========================================================
    hospital_code = request.data.get("auth-hospital-code")
    branch_code = request.data.get("auth-branch-code")
    outlet_code = request.data.get("auth-outlet-code")

    print("hospital_code_pendingbills:", hospital_code)
    print("branch_code:", branch_code)
    print("outlet_code:", outlet_code)

    # ✅ Guard (important)
    if not hospital_code or not branch_code or not outlet_code:
        return Response({
            "success": False,
            "message": "Missing hospital_code / branch_code / outlet_code"
        }, status=400)

    # =========================================================
    # ✅ Django Bills (FILTERED)
    # =========================================================
    bills = list(
        PharmacyBilling.objects.filter(
            billing_status__in=["Billed", "Paid", "deleted"],
            hospital_code=hospital_code,
            branch_code=branch_code,
            outlet_code=outlet_code
        )
    )

    if not bills:
        return Response([], status=status.HTTP_200_OK)

    # =========================================================
    # ✅ Patient Mapping
    # =========================================================
    uhids = [bill.uhid for bill in bills if bill.uhid]

    patients = Patient.objects.filter(uhid__in=uhids)

    patient_map = {
        p.uhid: f"{p.salutation or ''} {p.firstName or ''} {p.lastName or ''}".strip()
        for p in patients
    }

    # =========================================================
    # ✅ MongoDB Connections
    # =========================================================
    client = MongoClient(os.getenv("GLOBAL_DB_HOST"))

    global_db = client["Global"]
    profile_collection = global_db["backend_diagnostics_profile"]

    hms_db = client["HMS"]
    billtype_collection = hms_db["hospital_billtype"]

    pharmacy_item_collection = hms_db["hospital_pharmacyitem"]
    pharmacy_stock_collection = hms_db["hospital_pharmacystock"]
    oppharmacy_collection = hms_db["hospital_pharmacybilling"]

    # =========================================================
    # ✅ Doctor & Bill Type
    # =========================================================
    doctor_ids = list(set([bill.doctor_id for bill in bills if bill.doctor_id]))
    bill_types = list(set([int(bill.bill_type) for bill in bills if bill.bill_type]))

    doctor_map = {}
    if doctor_ids:
        doctor_cursor = profile_collection.find(
            {"employeeId": {"$in": doctor_ids}},
            {"employeeId": 1, "employeeName": 1}
        )
        doctor_map = {
            str(doc["employeeId"]): doc.get("employeeName", "")
            for doc in doctor_cursor
        }

    billtype_map = {}
    if bill_types:
        billtype_cursor = billtype_collection.find(
            {"bill_type": {"$in": bill_types}},
            {"bill_type": 1, "bill_name": 1}
        )
        billtype_map = {
            bt["bill_type"]: bt.get("bill_name", "")
            for bt in billtype_cursor
        }

    # =========================================================
    # ✅ Collect item_id + batch_number FROM MONGO
    # =========================================================
    item_batch_set = set()

    for bill in bills:
        mongo_bill = oppharmacy_collection.find_one(
            {
                "Bill_id": bill.Bill_id,
                "hospital_code": hospital_code,
                "branch_code": branch_code,
                "outlet_code":outlet_code

            },
            {"medicine_particulars": 1}
        )

        if mongo_bill:
            for item in mongo_bill.get("medicine_particulars", []):
                item_id = item.get("item_id")
                batch_number = item.get("batch_number")

                if item_id and batch_number:
                    item_batch_set.add((int(item_id), str(batch_number).strip()))

    item_ids = list(set([i[0] for i in item_batch_set]))
    batch_numbers = list(set([i[1] for i in item_batch_set]))

    # =========================================================
    # ✅ Fetch Item Names
    # =========================================================
    item_map = {}

    if item_ids:
        item_cursor = pharmacy_item_collection.find(
            {
                "item_id": {"$in": item_ids},
                "hospital_code": hospital_code,
                "branch_code": branch_code
            },
            {"item_id": 1, "item_name": 1}
        )

        item_map = {
            i["item_id"]: i.get("item_name", "")
            for i in item_cursor
        }

    # =========================================================
    # ✅ Fetch Stock Data
    # =========================================================
    stock_map = {}

    if item_ids and batch_numbers:
        stock_cursor = pharmacy_stock_collection.find(
            {
                "item_id": {"$in": item_ids},
                "batch_number": {"$in": batch_numbers},
                "hospital_code": hospital_code,
                "branch_code": branch_code,
                "outlet_code": outlet_code
            },
            {
                "item_id": 1,
                "batch_number": 1,
                "CGST_Percentage": 1,
                "SGST_Percentage": 1,
                "CGST_Amt": 1,
                "SGST_Amt": 1
            }
        )

        stock_map = {
            (s["item_id"], str(s["batch_number"]).strip()): s
            for s in stock_cursor
        }

    # =========================================================
    # ✅ Final Response
    # =========================================================
    data = []

    for bill in bills:
        serialized = PharmacyBillingSerializer(bill).data

        serialized["patient_name"] = patient_map.get(bill.uhid, "")
        serialized["doctor_name"] = doctor_map.get(str(bill.doctor_id), "")
        serialized["bill_type_name"] = billtype_map.get(int(bill.bill_type), "")

        # =====================================================
        # ✅ Fetch medicine_particulars
        # =====================================================
        mongo_bill = oppharmacy_collection.find_one(
            {
                "Bill_id": bill.Bill_id,
                "hospital_code": hospital_code,
                "branch_code": branch_code,
                "outlet_code": outlet_code
            },
            {"medicine_particulars": 1}
        )

        medicine_list = mongo_bill.get("medicine_particulars", []) if mongo_bill else []

        # =====================================================
        # ✅ Process items
        # =====================================================
        updated_items = []

        for item in medicine_list:
            item_id = item.get("item_id")
            batch_number = item.get("batch_number")

            item_id = int(item_id) if item_id else None
            batch_number = str(batch_number).strip() if batch_number else ""

            item["item_name"] = item_map.get(item_id, "")

            stock = stock_map.get((item_id, batch_number), {})

            item["CGST_Percentage"] = convert_decimal(stock.get("CGST_Percentage", 0))
            item["SGST_Percentage"] = convert_decimal(stock.get("SGST_Percentage", 0))
            item["CGST_Amt"] = convert_decimal(stock.get("CGST_Amt", 0))
            item["SGST_Amt"] = convert_decimal(stock.get("SGST_Amt", 0))

            updated_items.append(item)

        serialized["medicine_particulars"] = updated_items

        data.append(serialized)

    return Response(data, status=status.HTTP_200_OK)


from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status

from decimal import Decimal, InvalidOperation
from datetime import datetime
from pymongo import MongoClient
import os, json

from ..models import PharmacyBilling


from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from pymongo import MongoClient
from datetime import datetime
import os


@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def collect_oppharmacy_payment(request):
    try:
        data = request.data

        # ================================
        # ✅ INPUT FIELDS
        # ================================
        Bill_id = data.get("Bill_id")
        uhid = data.get("uhid")
        payment_details = data.get("payment_details")

        # ✅ AUTH FIELDS
        hospital_code = data.get("auth-hospital-code")
        branch_code = data.get("auth-branch-code")
        outlet_code = data.get("auth-outlet-code")

        # ✅ CASHIER (NEW)
        cashier_id = data.get("auth-user-id")

        # ================================
        # ✅ VALIDATION
        # ================================
        if not Bill_id or not uhid or not payment_details:
            return Response({
                "success": False,
                "error": "Missing required fields"
            })

        if not hospital_code or not branch_code or not outlet_code:
            return Response({
                "success": False,
                "error": "Missing hospital/branch/outlet"
            })

        if not cashier_id:
            return Response({
                "success": False,
                "error": "Missing cashier (auth-user-id)"
            })

        # Validate payment_details
        if not isinstance(payment_details, dict):
            return Response({
                "success": False,
                "error": "Invalid payment_details format"
            })

        # ================================
        # ✅ NORMALIZATION
        # ================================
        Bill_id = int(Bill_id)

        uhid = str(uhid).strip()
        hospital_code = str(hospital_code).strip()
        branch_code = str(branch_code).strip()
        outlet_code = str(outlet_code).strip()
        cashier_id = str(cashier_id).strip()

        print("🔍 DEBUG INPUT:", {
            "Bill_id": Bill_id,
            "uhid": repr(uhid),
            "hospital_code": hospital_code,
            "branch_code": branch_code,
            "outlet_code": outlet_code,
            "cashier_id": cashier_id
        })

        # ================================
        # ✅ DB CONNECTION
        # ================================
        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        db = client["HMS"]

        bill_collection = db["hospital_pharmacybilling"]
        stock_collection = db["hospital_pharmacystock"]

        # ================================
        # ✅ FETCH BILL
        # ================================
        query = {
            "Bill_id": Bill_id,
            "uhid": uhid,
            "hospital_code": hospital_code,
            "branch_code": branch_code,
            "outlet_code": outlet_code,
            "is_deleted": False
        }

        bill = bill_collection.find_one(query)

        if not bill:
            return Response({
                "success": False,
                "error": "Bill not found",
                "query": query
            })

        # ================================
        # ✅ PREVENT DOUBLE PAYMENT
        # ================================
        if bill.get("billing_status") == "Paid":
            return Response({
                "success": False,
                "error": "Bill already paid"
            })

        # ================================
        # ✅ STOCK UPDATE
        # ================================
        for med in bill.get("medicine_particulars", []):
            stock_collection.update_one(
                {
                    "item_id": med.get("item_id"),
                    "batch_number": med.get("batch_number")
                },
                {
                    "$inc": {
                        "sold_quantity": float(med.get("qty", 0))
                    }
                }
            )

        # ================================
        # ✅ BILL UPDATE (WITH CASHIER)
        # ================================
        update_result = bill_collection.update_one(
            query,
            {
                "$set": {
                    "billing_status": "Paid",
                    "payment_details": payment_details,
                    "paid_date": datetime.utcnow(),
                    "cashier_id": cashier_id   # 🔥 ADDED
                }
            }
        )

        # ================================
        # ✅ VERIFY UPDATE
        # ================================
        if update_result.modified_count == 0:
            return Response({
                "success": False,
                "error": "Payment update failed"
            })

        return Response({
            "success": True,
            "message": "Payment collected successfully",
            "cashier_id": cashier_id
        })

    except Exception as e:
        return Response({
            "success": False,
            "error": str(e)
        })

from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.utils import timezone
from django.db import transaction

from ..models import PharmacyBilling, PharmacyStock



@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def oppharmacy_deletebill(request):
    try:
        data = request.data
        employee_id = data.get("auth-user-id")  # ✅ ADDED

        bill_id = data.get("bill_id")
        delete_reason = data.get("delete_reason")

        # ✅ VALIDATION
        if not bill_id:
            return Response({
                "status": "error",
                "message": "Bill ID is required to delete the bill.",
                "code": "BILL_ID_MISSING"
            }, status=400)

        if not delete_reason:
            return Response({
                "status": "error",
                "message": "Please provide a reason for deleting the bill.",
                "code": "DELETE_REASON_MISSING"
            }, status=400)

        bill = PharmacyBilling.objects.filter(Bill_id=bill_id).first()

        # ✅ BILL NOT FOUND
        if not bill:
            return Response({
                "status": "error",
                "message": f"No bill found for Bill ID: {bill_id}.",
                "code": "BILL_NOT_FOUND"
            }, status=404)

        bill_no = bill.bill_no or bill_id

        # ✅ ALREADY DELETED CHECK
        if bill.billing_status and bill.billing_status.lower() == "deleted":
            return Response({
                "status": "error",
                "message": f"Bill Number {bill_no} is already deleted.",
                "code": "BILL_ALREADY_DELETED"
            }, status=400)

        medicines = bill.medicine_particulars or []
        updated_medicines = []

        with transaction.atomic():

            for med in medicines:
                item_id = med.get("item_id")
                batch = med.get("batch_number")
                qty = int(med.get("qty", 0))

                if not item_id or not batch or qty <= 0:
                    updated_medicines.append(med)
                    continue

                # ✅ STOCK REVERSAL
                stock = PharmacyStock.objects.filter(
                    item_id=item_id,
                    batch_number=batch
                ).first()

                if stock:
                    new_blocked = max(0, stock.blocked_quantity - qty)

                    PharmacyStock.objects.filter(
                        item_id=item_id,
                        batch_number=batch
                    ).update(
                        blocked_quantity=new_blocked,
                        lastmodified_date=timezone.now()
                    )

                # ✅ HISTORY TRACK
                history = med.get("edit_history", [])
                history.append({
                    "action": "qty_deleted",
                    "deleted_qty": qty,
                    "blockedqty_change": qty,
                    "reason": delete_reason,
                    "timestamp": str(timezone.now()),
                    "edited_by": employee_id,  # ✅ UPDATED
                    "is_deleted": True
                })

                med["edit_history"] = history
                updated_medicines.append(med)

            # ✅ BILL UPDATE
            PharmacyBilling.objects.filter(Bill_id=bill_id).update(
                billing_status="deleted",
                is_deleted=True,
                deleted_by=employee_id,  # ✅ ADDED
                delete_reason=delete_reason,
                medicine_particulars=updated_medicines,
                lastmodified_date=timezone.now()
            )

        return Response({
            "status": "success",
            "message": f"Bill Number {bill_no} deleted successfully.",
            "code": "BILL_DELETED_SUCCESS",
            "data": {
                "bill_id": bill_id,
                "bill_no": bill_no,
                "billing_status": "deleted"
            }
        }, status=200)

    except Exception as e:
        print("DELETE ERROR:", str(e))
        return Response({
            "status": "error",
            "message": "Something went wrong while deleting the bill. Please try again.",
            "code": "INTERNAL_SERVER_ERROR",
            "debug": str(e)
        }, status=500)



from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from ..models import PharmacyBilling
from ..serializers import PharmacyBillingSerializer


from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from django.db.models import Sum
import ast
import re

from bson.decimal128 import Decimal128

def convert_decimal(value):
    if isinstance(value, Decimal128):
        return float(value.to_decimal())
    return float(value) if value is not None else 0


# -----------------------------------------
# 🔹 Parse OrderedDict string safely
# -----------------------------------------
def parse_medicine_particulars(data):
    if isinstance(data, list):
        return data

    if isinstance(data, str):
        try:
            # Convert OrderedDict → dict
            clean_str = re.sub(r'OrderedDict\(', 'dict(', data)
            parsed = eval(clean_str)
            return parsed if isinstance(parsed, list) else []
        except Exception as e:
            print("❌ Parsing failed:", e)
            return []

    return []


# -----------------------------------------
# 🔹 MAIN API
# -----------------------------------------
@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def pharmacy_medicinechart(request):
    try:
        print("\n===== API START: pharmacy_medicinechart =====")

        # =========================================
        # 🔐 HEADERS + DATA
        # =========================================
        data = request.data

        hospital_code = data.get("auth-hospital-code")
        branch_code = request.data.get("auth-branch-code")
        outlet_code = request.data.get("auth-outlet-code")

        print("hospital_code:", hospital_code)
        print("branch_code:", branch_code)
        print("outlet_code:", outlet_code)

        if not hospital_code or not branch_code or not outlet_code:
            return Response(
                {"error": "hospital_code, branch_code, outlet_code required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # =========================================
        # 🌐 GLOBAL DB (DOCTOR LOOKUP)
        # =========================================
        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        global_db = client["Global"]
        employee_collection = global_db["backend_diagnostics_profile"]

        # =========================================
        # 🔎 FETCH BILLS
        # =========================================
        queryset = PharmacyBilling.objects.filter(
            hospital_code=hospital_code,
            branch_code=branch_code,
            outlet_code=outlet_code,
            billing_status="Pending",
            is_ward_request=True
        ).order_by('-created_date')

        serializer = PharmacyBillingSerializer(queryset, many=True)
        serialized_data = serializer.data

        final_data = []

        # =========================================
        # 🔄 LOOP BILLS
        # =========================================
        for bill in serialized_data:

            if not bill.get("is_ward_request"):
                continue

            # -------------------------------------
            # 👤 PATIENT DETAILS
            # -------------------------------------
            uhid = bill.get("uhid")
            patient_data = {}

            if uhid:
                patient = Patient.objects.filter(uhid=uhid).first()
                if patient:
                    patient_data = {
                        "patient_name": f"{patient.firstName} {patient.lastName}",
                        "address": patient.permanent_address,
                        "mobile": patient.mobilePhone
                    }

            bill["patient_details"] = patient_data

            # -------------------------------------
            # 👨‍⚕️ DOCTOR DETAILS (GLOBAL DB)
            # -------------------------------------
            doctor_id = bill.get("doctor_id")
            doctor_name = None

            if doctor_id:
                doctor = employee_collection.find_one(
                    {"employeeId": str(doctor_id)},
                    {"employeeName": 1, "_id": 0}
                )
                if doctor:
                    doctor_name = doctor.get("employeeName")

            bill["doctor_name"] = doctor_name

            # -------------------------------------
            # 💊 PARSE MEDICINE ITEMS
            # -------------------------------------
            items = parse_medicine_particulars(
                bill.get("medicine_particulars", [])
            )

            mapped_items = []

            # -------------------------------------
            # 🔄 LOOP ITEMS
            # -------------------------------------
            for item in items:

                if not isinstance(item, dict):
                    continue

                item_id = item.get("item_id")
                req_batch = item.get("batch_number")

                print(f"\nItem → {item_id}, Batch → {req_batch}")

                # ---------------------------------
                # 🔹 ITEM NAME
                # ---------------------------------
                item_obj = PharmacyItem.objects.filter(
                    item_id=item_id,
                    hospital_code=hospital_code,
                    branch_code=branch_code
                ).first()

                item_name = item_obj.item_name if item_obj else None

                # ---------------------------------
                # 🔹 STRICT STOCK FILTER
                # ---------------------------------
                stock_qs = PharmacyStock.objects.filter(
                    hospital_code=hospital_code,
                    branch_code=branch_code,
                    outlet_code=outlet_code,
                    item_id=item_id,
                    batch_number=req_batch
                ).order_by('-stock_id')

                # ---------------------------------
                # 🔥 FALLBACK (IF BATCH NOT FOUND)
                # ---------------------------------
                if not stock_qs.exists():
                    print("⚠️ Batch not found → using available batch")

                    stock_qs = PharmacyStock.objects.filter(
                        hospital_code=hospital_code,
                        branch_code=branch_code,
                        outlet_code=outlet_code,
                        item_id=item_id
                    ).order_by('-stock_id')

                    fallback_stock = stock_qs.first()

                    if fallback_stock:
                        req_batch = fallback_stock.batch_number

                # ---------------------------------
                # 📊 STOCK CALCULATION
                # ---------------------------------
                stock_agg = stock_qs.aggregate(
                    total_stock=Sum('total_stock'),
                    sold=Sum('sold_quantity'),
                    transferred=Sum('transferred_out_quantity'),
                    grn_return=Sum('grn_return_quantity')
                )

                total_stock = stock_agg.get("total_stock") or 0
                sold = stock_agg.get("sold") or 0
                transferred = stock_agg.get("transferred") or 0
                grn_return = stock_agg.get("grn_return") or 0

                available_stock = total_stock - sold - transferred - grn_return

                # ---------------------------------
                # 💰 TAX
                # ---------------------------------
                latest_stock = stock_qs.first()

                cgst_per = convert_decimal(
                    getattr(latest_stock, "CGST_Percentage", 0)
                ) if latest_stock else 0

                sgst_per = convert_decimal(
                    getattr(latest_stock, "SGST_Percentage", 0)
                ) if latest_stock else 0

                cgst_amt = convert_decimal(
                    getattr(latest_stock, "CGST_Amt", 0)
                ) if latest_stock else 0

                sgst_amt = convert_decimal(
                    getattr(latest_stock, "SGST_Amt", 0)
                ) if latest_stock else 0

                # ---------------------------------
                # ✅ FINAL MAP
                # ---------------------------------
                mapped_items.append({
                    **item,
                    "item_name": item_name,
                    "batch_number": req_batch,
                    "available_stock": available_stock,
                    "CGST_Percentage": cgst_per,
                    "SGST_Percentage": sgst_per,
                    "CGST_Amt": cgst_amt,
                    "SGST_Amt": sgst_amt
                })

            bill["medicine_items"] = mapped_items
            final_data.append(bill)

        print("\n===== API SUCCESS =====")

        return Response({
            "status": "success",
            "count": len(final_data),
            "data": final_data
        }, status=status.HTTP_200_OK)

    except Exception as e:
        print("❌ ERROR:", str(e))
        return Response(
            {"error": "Something went wrong", "details": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from bson import ObjectId

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def admissionstatus(request):

    uhid = request.GET.get("uhid")

    admission = mongo_db["hospital_admission"].find_one({"uhid": uhid})

    if not admission:
        return Response({
            "success": True,
            "admitted": False,
            "data": []
        })

    admitted = admission.get("is_admitted", False)

    # ✅ Convert _id
    admission["_id"] = str(admission["_id"])

    return Response({
        "success": True,
        "admitted": admitted,
        # ✅ Only return data if admitted = True
        "data": admission if admitted else []
    })




from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from django.views.decorators.csrf import csrf_exempt
from pymongo import MongoClient
import os
from django.db.models import Q
from ..models import Patient, Billing
from ..serializers import PatientSerializer, BillingSerializer



@api_view(['GET'])
def patient_details(request):

    uhid      = request.GET.get('uhid')
    ip_number = request.GET.get('ip_number')
    mobile    = request.GET.get('mobile')

    # ── Step 1: Filter Patients ───────────────────────────────────────
    if uhid:
        patients = Patient.objects.filter(
            Q(uhid__iexact=uhid) |           # full match  e.g. S026/0000001
            Q(uhid__iendswith=f'/{uhid}')    # suffix match e.g. /0000001
        )
    elif ip_number:
        patients = Patient.objects.filter(ip_number=ip_number)
    elif mobile:
        patients = Patient.objects.filter(mobilePhone=mobile)
    else:
        # ✅ FIX: Never return ALL patients — return empty instead
        return Response({
            "success": False,
            "message": "Please provide a search parameter (uhid, ip_number, or mobile)."
        }, status=status.HTTP_400_BAD_REQUEST)

    # ── Step 2: MongoDB connection ────────────────────────────────────
    client      = MongoClient(os.getenv("GLOBAL_DB_HOST"))
    global_db   = client["Global"]
    employee_collection = global_db["backend_diagnostics_profile"]

    serializer   = PatientSerializer(patients, many=True)
    patient_data = serializer.data

    # ── Step 3: Attach billing + doctor_name to each patient ──────────
    for patient in patient_data:
        patient_id = int(patient["id"])
        billings   = Billing.objects.filter(patient_id=patient_id)
        billing_list = []

        for bill in billings:
            doctor_id   = bill.doctor_id
            employee    = employee_collection.find_one({"employeeId": doctor_id})
            doctor_name = employee["employeeName"] if employee else None
            billing_list.append({
                "bill_number"    : bill.bill_number,
                "doctor_id"      : doctor_id,
                "doctor_name"    : doctor_name,
                "total_fees"     : str(bill.total_fees),
                "payment_status" : bill.payment_status,
                "billed_date"    : bill.billed_date,
            })

        patient["billing"] = billing_list

    return Response({
        "success": True,
        "data"   : patient_data
    }, status=status.HTTP_200_OK)