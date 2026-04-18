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
COLLECTION_NAME = "hospital_pharmacystock"

client = MongoClient(MONGO_URI)
mongo_db = client[DB_NAME]
stock_collection = mongo_db["hospital_pharmacystock"]
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
# ✅ SHELF SELECTION BASED ON OUTLET (HARDCODE LOGIC)
    {
        "$addFields": {
            "shelf_no": {
                "$cond": [
                    {"$eq": ["$outlet_code", "OLET001"]},
                    "$item_details.IP_shelf_no",
                    {
                        "$cond": [
                            {"$eq": ["$outlet_code", "OLET002"]},
                            "$item_details.OP_shelf_no",
                            ""
                        ]
                    }
                ]
            },
            "rack_no": {
                "$cond": [
                    {"$eq": ["$outlet_code", "OLET001"]},
                    "$item_details.IP_rack_no",
                    {
                        "$cond": [
                            {"$eq": ["$outlet_code", "OLET002"]},
                            "$item_details.OP_rack_no",
                            ""
                        ]
                    }
                ]
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

                    "chemical_composition": "$item_details.chemical_composition", 

                    "shelf_no": 1,   
                    "rack_no": 1,    

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






from datetime import datetime, date
from pymongo import MongoClient
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
import os

# ----------------------------------------------------------
# SANITIZE MEDICINES
# ----------------------------------------------------------
def sanitize_medicines(medicines):
    clean = []

    for med in medicines:
        if not med:
            continue

        price = med.get("price") or med.get("Price") or 0

        clean.append({
            "item_id": int(med.get("item_id")),
            "batch_number": str(med.get("batch_number")),
            "qty": int(med.get("qty", 0)),
            "price": float(price),
            "edit_history": med.get("edit_history", [])
        })

    return clean


# ----------------------------------------------------------
# STOCK UPDATE (NO department_code)
# ----------------------------------------------------------
def adjust_blocked_stock(old_meds, new_meds, hospital_code, branch_code, outlet_code):

    client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
    db = client["HMS"]
    stock_collection = db["hospital_pharmacystock"]

    old_map = {(m["item_id"], m["batch_number"]): m for m in old_meds}
    new_map = {(m["item_id"], m["batch_number"]): m for m in new_meds}

    keys = set(old_map.keys()).union(new_map.keys())

    for key in keys:
        old_qty = float(old_map.get(key, {}).get("qty", 0))
        new_qty = float(new_map.get(key, {}).get("qty", 0))

        diff = new_qty - old_qty

        if diff == 0:
            continue

        item_id, batch_number = key

        stock_collection.update_one(
            {
                "hospital_code": hospital_code,
                "branch_code": branch_code,
                "outlet_code": outlet_code,
                "item_id": int(item_id),
                "batch_number": str(batch_number)
            },
            {
                "$inc": {"blocked_quantity": diff}
            }
        )


# ----------------------------------------------------------
# EDIT HISTORY
# ----------------------------------------------------------
def build_edit_history(old_meds, new_meds, employee_id):

    updated = []

    old_map = {(m["item_id"], m["batch_number"]): m for m in old_meds}
    new_map = {(m["item_id"], m["batch_number"]): m for m in new_meds}

    keys = set(old_map.keys()).union(new_map.keys())

    for key in keys:
        old = old_map.get(key)
        new = new_map.get(key)

        now = datetime.utcnow().isoformat()

        if not old and new:
            new.setdefault("edit_history", [])
            new["edit_history"].append({
                "action": "medicine_added",
                "qty": new["qty"],
                "blocked_change": new["qty"],
                "timestamp": now,
                "edited_by": employee_id
            })
            updated.append(new)

        elif old and not new:
            old.setdefault("edit_history", [])
            old["edit_history"].append({
                "action": "medicine_deleted",
                "qty_deleted": old["qty"],
                "blocked_change": -old["qty"],
                "timestamp": now,
                "edited_by": employee_id
            })
            updated.append(old)

        elif old and new:
            old_qty = old.get("qty", 0)
            new_qty = new.get("qty", 0)

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

    # ✅ AUTH CODES
    hospital_code = data.get("auth-hospital-code")
    branch_code = data.get("auth-branch-code")
    outlet_code = data.get("auth-outlet-code")

    # --------------------------------------------------
    # STATUS NORMALIZATION
    # --------------------------------------------------
    status_raw = str(data.get("status", "")).strip().lower()

    if status_raw in ["estimate", "estimated"]:
        status = "Estimate"
    elif status_raw == "billed":
        status = "Billed"
    else:
        return Response({"success": False, "error": "Invalid status"})

    Bill_id = data.get("Bill_id")

    medicines = sanitize_medicines(data.get("medicine_particulars", []))

    # --------------------------------------------------
    # COMMON FIELDS
    # --------------------------------------------------
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

    client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
    db = client["HMS"]
    bill_collection = db["hospital_pharmacybilling"]

    # ======================================================
    # 🔁 PATCH (UPDATE / CONVERT)
    # ======================================================
    if request.method == "PATCH":

        if not Bill_id:
            return Response({"success": False, "error": "Bill_id required"})

        try:
            record = PharmacyBilling.objects.get(Bill_id=int(Bill_id))
        except PharmacyBilling.DoesNotExist:
            return Response({"success": False, "error": "Record not found"})

        old_meds = record.medicine_particulars or []
        updated_meds = build_edit_history(old_meds, medicines, employee_id)

        qty_changed = old_meds != medicines

        is_estimate_to_bill = (
            record.billing_status == "Estimate" and status == "Billed"
        )

        # ✅ STOCK UPDATE CONTROL
        if not is_estimate_to_bill or qty_changed:
            adjust_blocked_stock(
                old_meds,
                medicines,
                hospital_code,
                branch_code,
                outlet_code
            )

        update_data = {**fields}
        update_data["medicine_particulars"] = updated_meds
        update_data["lastmodified_by"] = employee_id
        update_data["lastmodified_date"] = datetime.utcnow()

        # 🔥 UPDATE ESTIMATE
        if status == "Estimate":
            update_data["billing_status"] = "Estimate"
            update_data["billing_mode"] = "ESTIMATE"

        # 🔥 CONVERT TO BILL
        elif status == "Billed":
            if not record.bill_no:
                update_data["bill_no"] = get_last_oppharmacy_billno(get_financial_year())

            update_data["billing_status"] = "Billed"
            update_data["billing_mode"] = "ESTIMATE"
            update_data["bill_date"] = datetime.utcnow()

        bill_collection.update_one(
            {"Bill_id": int(Bill_id)},
            {"$set": update_data}
        )

        return Response({
            "success": True,
            "Bill_id": record.Bill_id,
            "bill_no": update_data.get("bill_no"),
            "estimate_no": record.estimate_no
        })

    # ======================================================
    # 🆕 POST (CREATE)
    # ======================================================
    if request.method == "POST":

        last = PharmacyBilling.objects.order_by('-Bill_id').first()
        next_Bill_id = (last.Bill_id + 1) if last else 1

        record_doc = {
            "Bill_id": next_Bill_id,
            "medicine_particulars": medicines,
            "billing_status": status,
            "created_by": employee_id,
            "created_date": datetime.utcnow(),
            "bill_date": datetime.utcnow(),
            "hospital_code": hospital_code,
            "branch_code": branch_code,
            "outlet_code": outlet_code,
            **fields
        }

        # 🔥 DIRECT BILL
        if status == "Billed":
            bill_no = get_last_oppharmacy_billno(get_financial_year())

            record_doc.update({
                "bill_no": bill_no,
                "estimate_no": None,
                "billing_mode": "DIRECT",
            })

            bill_collection.insert_one(record_doc)

            adjust_blocked_stock(
                [],
                medicines,
                hospital_code,
                branch_code,
                outlet_code
            )

            return Response({
                "success": True,
                "bill_no": bill_no,
                "Bill_id": next_Bill_id
            })

        # 🔥 ESTIMATE
        if status == "Estimate":
            estimate_no = generate_estimate_no()

            record_doc.update({
                "bill_no": None,
                "estimate_no": estimate_no,
                "billing_mode": "ESTIMATE",
            })

            bill_collection.insert_one(record_doc)

            adjust_blocked_stock(
                [],
                medicines,
                hospital_code,
                branch_code,
                outlet_code
            )

            return Response({
                "success": True,
                "estimate_no": estimate_no,
                "Bill_id": next_Bill_id
            })

    return Response({"success": False, "error": "Invalid request"})


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
            billing_status__in=["Billed", "Paid", "Processing","deleted"],
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
@permission_classes([HasRoleAndDataPermission])
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





def sanitize_medicines(medicines):
    if isinstance(medicines, dict):
        medicines = [medicines]

    cleaned = []

    for m in medicines:
        cleaned.append({
            "item_id": int(m.get("item_id", 0)),
            "batch_number": str(m.get("batch_number", "")).strip(),
            "qty": float(m.get("qty", m.get("quantity", 0))),
            "price": float(m.get("price", 0)),
        })

    return cleaned


@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def substitute_medicine(request):
    try:
        
        data = request.data

        # ================================
        # ✅ AUTH CONTEXT (NEW)
        # ================================
        hospital_code = data.get("auth-hospital-code")
        branch_code = data.get("auth-branch-code")
        outlet_code = data.get("auth-outlet-code")

        print("hospital_code_substitute_medicine:", hospital_code)
        print("branch_code:", branch_code)
        print("outlet_code:", outlet_code)

        # ✅ VALIDATION (IMPORTANT)
        if not hospital_code or not branch_code or not outlet_code:
            return Response(
                {"error": "Missing hospital/branch/outlet code"},
                status=400
            )

        # ================================
        # INPUT DATA
        # ================================
        Bill_id = data.get("Bill_id")
        item_id = int(data.get("item_id"))
        batch_number = data.get("batch_number")

        substitute_item = data.get("substitute_item")

        # ✅ ensure dict
        if isinstance(substitute_item, str):
            substitute_item = json.loads(substitute_item)

        # ================================
        # FETCH BILL (UPDATED FILTER)
        # ================================
        bill = bill_collection.find_one({
            "Bill_id": Bill_id,
            "hospital_code": hospital_code,
            "branch_code": branch_code,
            "outlet_code": outlet_code
        })

        if not bill:
            return Response({"error": "Bill not found"}, status=404)

        medicines = bill.get("medicine_particulars", [])
        updated_medicines = []

        for med in medicines:
            if med["item_id"] == item_id and med["batch_number"] == batch_number:

                # ✅ handle null history
                med_edit_history = med.get("edit_history") or []

                # ✅ sanitize
                old_clean = sanitize_medicines([med])[0]
                new_clean = sanitize_medicines([substitute_item])[0]

                med_edit_history.append({
                    "type": "substitute",
                    "old_data": old_clean,
                    "new_data": new_clean,
                    "updated_at": datetime.utcnow(),
                    "hospital_code": hospital_code,
                    "branch_code": branch_code,
                    "outlet_code": outlet_code
                })

                # mark old deleted
                med["is_deleted"] = True

                # attach history to new
                substitute_item["edit_history"] = med_edit_history

                updated_medicines.append(substitute_item)
            else:
                updated_medicines.append(med)

        # ================================
        # UPDATE BILL
        # ================================
        bill_collection.update_one(
            {
                "Bill_id": Bill_id,
                "hospital_code": hospital_code,
                "branch_code": branch_code,
                "outlet_code": outlet_code
            },
            {
                "$set": {
                    "medicine_particulars": updated_medicines,
                    "lastmodified_date": datetime.utcnow(),
                    "lastmodified_context": {
                        "hospital_code": hospital_code,
                        "branch_code": branch_code,
                        "outlet_code": outlet_code
                    }
                }
            }
        )

        return Response({
            "status": "success",
            "message": "Medicine substituted"
        })

    except Exception as e:
        return Response({"error": str(e)}, status=500)
    



@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def convert_to_bill(request):
    try:
        Bill_id = request.data.get("Bill_id")

        result = bill_collection.update_one(
            {"Bill_id": Bill_id},
            {
                "$set": {
                    "billing_status": "Processing",
                    "lastmodified_date": datetime.utcnow()
                }
            }
        )

        if result.matched_count == 0:
            return Response({"error": "Bill not found"}, status=404)

        return Response({"status": "success", "message": "Converted to Processing"})

    except Exception as e:
        return Response({"error": str(e)}, status=500)
    



@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def finalize_bill(request):
    try:
        from datetime import datetime

        data = request.data

        # =========================================
        # ✅ AUTH CONTEXT (BODY + HEADER FALLBACK)
        # =========================================
        hospital_code = (
            data.get("auth-hospital-code")
            or request.headers.get("auth-hospital-code")
        )

        branch_code = (
            data.get("auth-branch-code")
            or request.headers.get("auth-branch-code")
        )

        outlet_code = (
            data.get("auth-outlet-code")
            or request.headers.get("auth-outlet-code")
        )

        print("hospital_code_finalize_bill:", hospital_code)
        print("branch_code-finalize_bill:", branch_code)
        print("outlet_code-finalize_bill:", outlet_code)

        # =========================================
        # ✅ VALIDATION
        # =========================================
        if not hospital_code or not branch_code or not outlet_code:
            return Response(
                {"error": "Missing hospital/branch/outlet code"},
                status=400
            )

        # =========================================
        # INPUT
        # =========================================
        Bill_id = data.get("Bill_id")

        # =========================================
        # FETCH BILL (WITH CONTEXT)
        # =========================================
        bill = bill_collection.find_one({
            "Bill_id": Bill_id,
            "hospital_code": hospital_code,
            "branch_code": branch_code,
            "outlet_code": outlet_code
        })

        if not bill:
            return Response({"error": "Bill not found"}, status=404)

        # =========================================
        # ✅ GENERATE BILL NO (ONLY IF NOT EXISTS)
        # =========================================
        if not bill.get("bill_no"):
            fy = get_financial_year()
            new_bill_no = get_last_oppharmacy_billno(fy)

            bill_date = datetime.utcnow()

            bill_collection.update_one(
                {
                    "Bill_id": Bill_id,
                    "hospital_code": hospital_code,
                    "branch_code": branch_code,
                    "outlet_code": outlet_code
                },
                {
                    "$set": {
                        "bill_no": new_bill_no,
                        "bill_date": bill_date
                    }
                }
            )
        else:
            new_bill_no = bill.get("bill_no")
            bill_date = bill.get("bill_date")

        medicines = bill.get("medicine_particulars", [])

        # =========================================
        # ✅ STOCK UPDATE (BLOCKED QTY)
        # =========================================
        for med in medicines:
            if med.get("is_deleted"):
                continue

            try:
                item_id = int(med.get("item_id"))
                batch = str(med.get("batch_number")).strip()
                qty = float(med.get("quantity", 0))
            except Exception as e:
                print("Skipping invalid med:", med, "Error:", e)
                continue

            result = stock_collection.update_one(
                {
                    "item_id": item_id,
                    "batch_number": batch,
                    "hospital_code": hospital_code,
                    "branch_code": branch_code,
                    "outlet_code": outlet_code
                },
                {
                    "$inc": {"blocked_quantity": qty}
                },
                upsert=False   # 🔴 change to True if you want auto-create
            )

            # =========================================
            # 🔍 DEBUG LOGS
            # =========================================
            print("STOCK FILTER:", {
                "item_id": item_id,
                "batch_number": batch,
                "hospital_code": hospital_code,
                "branch_code": branch_code,
                "outlet_code": outlet_code
            })
            print("MATCHED:", result.matched_count, "MODIFIED:", result.modified_count)

        # =========================================
        # ✅ UPDATE BILL STATUS
        # =========================================
        bill_collection.update_one(
            {
                "Bill_id": Bill_id,
                "hospital_code": hospital_code,
                "branch_code": branch_code,
                "outlet_code": outlet_code
            },
            {
                "$set": {
                    "billing_status": "Billed",
                    "lastmodified_date": datetime.utcnow()
                }
            }
        )

        # =========================================
        # RESPONSE
        # =========================================
        return Response({
            "status": "success",
            "message": "Bill finalized & stock updated",
            "bill_no": new_bill_no,
            "bill_date": bill_date
        })

    except Exception as e:
        return Response({"error": str(e)}, status=500)
    


from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from ..models import Admission
from pymongo import MongoClient
import os
import traceback

# ✅ Mongo connection
MONGO_URI = os.getenv("GLOBAL_DB_HOST")
client = MongoClient(MONGO_URI)
mongo_db = client["HMS"]
patient_collection = mongo_db["hospital_patient"]


@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def ipadvance_bills(request):
    try:

        # =========================================
        # ✅ GET VALUES FROM request.data
        # =========================================
        hospital_code = request.data.get("auth-hospital-code")
        branch_code = request.data.get("auth-branch-code")
        outlet_code = request.data.get("auth-outlet-code")

        if not hospital_code or not branch_code or not outlet_code:
            return Response(
                {"error": "Missing auth headers"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # =========================================
        # ✅ GET METHOD
        # =========================================
        if request.method == "GET":

            admissions = Admission.objects.filter(
                hospital_code=hospital_code,
                branch_code=branch_code,
                outlet_code=outlet_code,
                is_admissionActive=True
            )

            result = []

            for admission in admissions:

                # =========================================
                # ✅ FETCH PATIENT NAME USING UHID
                # =========================================
                patient = patient_collection.find_one({
                    "uhid": admission.uhid,
                    "hospital_code": hospital_code,
                    "branch_code": branch_code
                })

                if patient:
                    salutation = patient.get("salutation", "")
                    firstName = patient.get("firstName", "")
                    lastName = patient.get("lastName", "")
                    patient_name = f"{salutation} {firstName} {lastName}".strip()
                else:
                    patient_name = None

                # =========================================
                # ✅ RESPONSE (RAW DB STRUCTURE)
                # =========================================
                admission_data = {
                    "ipNumber": admission.ipNumber,
                    "ipserial_number" :admission.ipserial_number,
                    "uhid": admission.uhid,
                    "patient_name": patient_name,
                    "hospital_code": admission.hospital_code,
                    "branch_code": admission.branch_code,
                    "outlet_code": admission.outlet_code,
                    "admissionDateTime": admission.admissionDateTime,
                    "admittingDoctor": admission.admittingDoctor,
                    "consultingDoctor": admission.consultingDoctor,
                    "packageName": admission.packageName,
                    "room_details": admission.room_details,
                    "roomShitingDetails": admission.roomShitingDetails,
                    "reasonForAdmission": admission.reasonForAdmission,
                    "mlc_type": admission.mlc_type,
                    "mlc_doc": admission.mlc_doc,
                    "mlc_remarks": admission.mlc_remarks,
                    "is_admissionActive": admission.is_admissionActive,
                    "is_discharged": admission.is_discharged,
                    "is_admitted": admission.is_admitted,
                    "created_by": admission.created_by,
                    "created_date": admission.created_date,
                    "lastmodified_by": admission.lastmodified_by,
                    "lastmodified_date": admission.lastmodified_date,

                    # ✅ EXACT SAME AS DB (NO FILTERING)
                    "advance_payments": admission.advance_payments or []
                }

                result.append(admission_data)

            return Response({
                "status": "success",
                "count": len(result),
                "data": result
            }, status=status.HTTP_200_OK)

        # =========================================
        # ✅ POST METHOD (UPDATE STATUS)
        # =========================================
        if request.method == "POST":

            ipNumber = request.data.get("ipNumber")
            advance_id = request.data.get("advance_id")
            payment_details = request.data.get("payment_details", {})

            if not ipNumber:
                return Response(
                    {"error": "ipNumber required"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            admission = Admission.objects.filter(
                ipNumber=ipNumber,
                hospital_code=hospital_code,
                branch_code=branch_code,
                outlet_code=outlet_code
            ).first()

            if not admission:
                return Response(
                    {"error": "Admission not found"},
                    status=status.HTTP_404_NOT_FOUND
                )

            payments = admission.advance_payments or []

            if not isinstance(payments, list):
                payments = []

            updated = False

            for p in payments:
                if not isinstance(p, dict):
                    continue

                if advance_id:
                    if p.get("advance_id") == advance_id:
                        p["status"] = "Paid"
                        p["payment_details"] = payment_details
                        updated = True
                else:
                    if str(p.get("status", "")).lower() == "pending":
                        p["status"] = "Paid"
                        p["payment_details"] = payment_details
                        updated = True

            if not updated:
                return Response(
                    {"message": "No matching payments found"},
                    status=status.HTTP_200_OK
                )

            admission.advance_payments = payments
            admission.save()

            # =========================================
            # ✅ FETCH PATIENT NAME AGAIN
            # =========================================
            patient = patient_collection.find_one({
                "uhid": admission.uhid,
                "hospital_code": hospital_code,
                "branch_code": branch_code
            })

            if patient:
                salutation = patient.get("salutation", "")
                firstName = patient.get("firstName", "")
                lastName = patient.get("lastName", "")
                patient_name = f"{salutation} {firstName} {lastName}".strip()
            else:
                patient_name = None

            return Response({
                "status": "success",
                "message": "Payment(s) updated successfully",
                "data": {
                    "ipNumber": admission.ipNumber,
                    "uhid": admission.uhid,
                    "patient_name": patient_name,
                    "hospital_code": admission.hospital_code,
                    "branch_code": admission.branch_code,
                    "outlet_code": admission.outlet_code,

                    # ✅ RETURN FULL UPDATED STRUCTURE
                    "advance_payments": payments
                }
            }, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({
            "error": str(e),
            "type": type(e).__name__,
            "trace": traceback.format_exc()
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from pymongo import MongoClient
import os

# Mongo setup
MONGO_URI = os.getenv("GLOBAL_DB_HOST")
DB_NAME = "HMS"
COLLECTION_NAME = "hospital_outlets"

client = MongoClient(MONGO_URI)
mongo_db = client[DB_NAME]
outlet_collection = mongo_db[COLLECTION_NAME]


@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def cashcounter_outlet(request):
    try:
        # =========================================
        # ✅ GET VALUES (ONLY request.data)
        # =========================================
        hospital_code = request.data.get("auth-hospital-code")
        branch_code = request.data.get("auth-branch-code")
        outlet_code = request.data.get("auth-outlet-code")

        print("hospital_code:", hospital_code)
        print("branch_code:", branch_code)
        print("outlet_code:", outlet_code)

        # =========================================
        # ✅ BUILD FILTER
        # =========================================
        filter_query = {
            "is_active": True,
            "is_cash_outlet": True   # 🔥 Mandatory condition
        }

        if hospital_code:
            filter_query["hospital_code"] = hospital_code
        if branch_code:
            filter_query["branch_code"] = branch_code
        if outlet_code:
            filter_query["outlet_code"] = outlet_code

        print("Mongo Query:", filter_query)

        # =========================================
        # ✅ FETCH ONLY outlet_name
        # =========================================
        outlet = outlet_collection.find_one(
            filter_query,
            {"_id": 0, "outlet_name": 1}
        )

        if not outlet:
            return Response({
                "status": False,
                "message": "No cash outlet found"
            }, status=404)

        # =========================================
        # ✅ RESPONSE
        # =========================================
        return Response({
            "status": True,
            "outlet_name": outlet.get("outlet_name")
        }, status=200)

    except Exception as e:
        print("Error:", str(e))
        return Response({
            "status": False,
            "message": str(e)
        }, status=500)