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
from ..models import Patient, PharmacyStock, PharmacyItem

# MongoDB Configuration
MONGO_URI = os.getenv("GLOBAL_DB_HOST")
DB_NAME = "HMS"
COLLECTION_NAME = "hospital_oppharmacystock"

client = MongoClient(MONGO_URI)
mongo_db = client[DB_NAME]
stock_collection = mongo_db["hospital_oppharmacystock"]
bill_collection = mongo_db["hospital_oppharmacybill"]

from bson.decimal128 import Decimal128

def convert_decimals(obj):
    if isinstance(obj, list):
        return [convert_decimals(i) for i in obj]
    elif isinstance(obj, dict):
        return {k: convert_decimals(v) for k, v in obj.items()}
    elif isinstance(obj, Decimal128):
        return float(obj.to_decimal())
    return obj



@api_view(["GET"])
# @permission_classes([HasRoleAndDataPermission])
def get_oppharmacy_stock(request):
    try:
        # ✅ Dynamic department (code1)
        dept_code = request.GET.get("department_code", "")

        # ✅ Mongo connection (code2)
        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        mongo_db = client["HMS"]

        pipeline = [

            # ✅ Filter department
            {
                "$match": {
                    "outlet_code": dept_code
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



# ----------------------------------------------------------
# SANITIZE MEDICINES





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
# STOCK UPDATE
# ----------------------------------------------------------
def adjust_blocked_stock(old_meds, new_meds, department_code="OP001"):

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
                "department_code": department_code,
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


@api_view(["POST", "PATCH"])
@permission_classes([HasRoleAndDataPermission])
def save_oppharmacy_bill(request):
    data = request.data
    employee_id = data.get("auth-user-id")  # Use consistently

    # ✅ STATUS NORMALIZATION (unchanged)
    status_raw = str(data.get("status", "")).strip().lower()
    if status_raw in ["estimate", "estimated"]:
        status = "Estimate"
    elif status_raw == "billed":
        status = "Billed"
    else:
        return Response({"success": False, "error": "Invalid status"})

    Bill_id = data.get("Bill_id")  # Frontend sends Bill_id (note lowercase 'id')

    medicines = sanitize_medicines(data.get("medicine_particulars", []))
    department_code = "OP001"

    # COMMON FIELDS (Removed patient_name and bill_name)
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
    # 🔁 PATCH (UPDATE / CONVERT) - Fixed: Ensure int(Bill_id), handle missing
    # ======================================================
    # ======================================================
    # 🔁 PATCH (UPDATE / CONVERT)
    # ======================================================
    if request.method == "PATCH":
        if not Bill_id:
            return Response({"success": False, "error": "Bill_id required for updates/conversions"})

        try:
            record = OPPharmacyBill.objects.get(Bill_id=int(Bill_id))
        except OPPharmacyBill.DoesNotExist:
            return Response({"success": False, "error": "Record not found"})

        old_meds = record.medicine_particulars or []
        updated_meds = build_edit_history(old_meds, medicines, employee_id)
        adjust_blocked_stock(old_meds, updated_meds, department_code)

        # Update metadata
        update_data = {**fields}
        update_data["medicine_particulars"] = updated_meds
        update_data["lastmodified_by"] = employee_id
        update_data["lastmodified_date"] = datetime.utcnow()

        # 🔥 CASE 3: UPDATE ESTIMATE
        if status == "Estimate":
            update_data["billing_status"] = "Estimate"
            update_data["billing_mode"] = "ESTIMATE"

        # 🔥 CASE 4: CONVERT TO BILL
        elif status == "Billed":
            if not record.bill_no:
                update_data["bill_no"] = get_last_oppharmacy_billno(get_financial_year())
            update_data["billing_status"] = "Billed"
            update_data["billing_mode"] = "ESTIMATE"

        # ✅ NATIVE MONGO UPDATE
        bill_collection.update_one(
            {"Bill_id": int(Bill_id)},
            {"$set": update_data}
        )

        # Refresh for response
        record.refresh_from_db()

        return Response({
            "success": True,
            "Bill_id": record.Bill_id,
            "bill_no": record.bill_no,
            "estimate_no": record.estimate_no
        })

    # ======================================================
    # 🆕 POST (CREATE)
    # ======================================================
    if request.method == "POST":
        # Calculate next Bill_id
        last = OPPharmacyBill.objects.order_by('-Bill_id').first()
        next_Bill_id = (last.Bill_id + 1) if last else 1

        record_doc = {
            "Bill_id": next_Bill_id,
            "medicine_particulars": medicines,
            "billing_status": status,
            "cashier_id": employee_id,
            "created_by": employee_id,
            "created_date": datetime.utcnow(),
            "bill_date": datetime.utcnow(),
            **fields
        }

        # CASE 1: DIRECT BILL
        if status == "Billed":
            bill_no = get_last_oppharmacy_billno(get_financial_year())
            record_doc.update({
                "bill_no": bill_no,
                "estimate_no": None,
                "billing_mode": "DIRECT",
            })
            bill_collection.insert_one(record_doc)
            adjust_blocked_stock([], medicines, department_code)
            return Response({
                "success": True,
                "bill_no": bill_no,
                "Bill_id": next_Bill_id
            })

        # CASE 2: ESTIMATE
        if status == "Estimate":
            estimate_no = generate_estimate_no()
            record_doc.update({
                "bill_no": None,
                "estimate_no": estimate_no,
                "billing_mode": "ESTIMATE",
            })
            bill_collection.insert_one(record_doc)
            adjust_blocked_stock([], medicines, department_code)
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

    cursor = stock_collection.find(
        {
            "billing_outlet": "PHARMACY",
            "is_active": True
        }
    )

    billtypes = list(cursor)

    # Convert ObjectId to string (important)
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
        OPPharmacyBill.objects
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
        OPPharmacyBill.objects
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
    last = OPPharmacyBill.objects.aggregate(
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
    last = OPPharmacyBill.objects.order_by('-Bill_id').first()
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
        "bill_date": now_ist
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
  
    estimates = OPPharmacyBill.objects.filter(billing_status="Estimate")
    serializer = OPPharmacyBillSerializer(estimates, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)



@api_view(["GET"])
def get_estimate_bills(request):
    try:

        bills = OPPharmacyBill.objects.filter(billing_status="Estimate")
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
                
                # Fetch name since it is no longer stored in medicine_particulars array
                item = PharmacyItem.objects.filter(item_id=item_id).first()
                item_name = item.item_name if item else ""

                particulars.append({
                    "item_id": item_id,
                    "item_name": item_name,
                    "batch_number": med.get("batch_number"),
                    "qty": med.get("qty"),
                    "Price": med.get("price"),
                })

            # Re-fetch patient name from Patient model
            patient = Patient.objects.filter(uhid=bill.uhid).first()
            patient_name = patient.patient_name if patient else ""

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

    estimate = OPPharmacyBill.objects.get(
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




@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def OPPharmacy_pending_bills(request):

    bills = list(
        OPPharmacyBill.objects.filter(
            billing_status__in=["Billed", "Paid"]
        )
    )

    # ✅ Collect all UHIDs
    uhids = [bill.uhid for bill in bills if bill.uhid]

    # ✅ Fetch all patients in ONE query
    patients = Patient.objects.filter(uhid__in=uhids)

    # ✅ Map UHID → Full Name
    patient_map = {
        p.uhid: f"{p.salutation or ''} {p.firstName or ''} {p.lastName or ''}".strip()
        for p in patients
    }

    # ✅ Attach patient_name
    data = []
    for bill in bills:
        serialized = OPPharmacyBillSerializer(bill).data
        serialized["patient_name"] = patient_map.get(bill.uhid, "")
        data.append(serialized)

    return Response(data, status=status.HTTP_200_OK)


from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status

from decimal import Decimal, InvalidOperation
from datetime import datetime
from pymongo import MongoClient
import os, json




@api_view(["POST"])
def collect_oppharmacy_payment(request):
    try:
        data = request.data

        Bill_id = data.get("Bill_id")
        uhid = data.get("uhid")
        bill_no = data.get("bill_no")
        payment_details = data.get("payment_details")

        if not Bill_id or not uhid or not payment_details:
            return Response({
                "success": False,
                "error": "Missing required fields"
            })

        # ✅ TYPE FIX
        Bill_id = int(Bill_id)
        uhid = str(uhid).strip()

        print("DEBUG:", Bill_id, uhid)

        # ================================
        # ✅ CORRECT COLLECTION
        # ================================
        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        db = client["HMS"]

        bill_collection = db["hospital_oppharmacybill"]   # 🔥 FIXED
        stock_collection = db["hospital_pharmacystock"]

        # ================================
        # ✅ DEBUG CHECK
        # ================================
        print("ALL BILLS:", list(bill_collection.find({}, {"Bill_id": 1, "uhid": 1})))

        # ================================
        # ✅ FETCH BILL
        # ================================
        bill = bill_collection.find_one({
            "Bill_id": Bill_id,
            "uhid": uhid
        })

        if not bill:
            return Response({
                "success": False,
                "error": "Bill not found"
            })

        # ================================
        # ✅ STOCK UPDATE
        # ================================
        for med in bill.get("medicine_particulars", []):
            stock_collection.update_one(
                {
                    "item_id": med["item_id"],
                    "batch_number": med["batch_number"]
                },
                {
                    "$inc": {"sold_quantity": med["qty"]}
                }
            )

        # ================================
        # ✅ BILL UPDATE
        # ================================
        bill_collection.update_one(
            {
                "Bill_id": Bill_id,
                "uhid": uhid
            },
            {
                "$set": {
                    "billing_status": "Paid",
                    "payment_details": payment_details,
                    "paid_date": datetime.utcnow()
                }
            }
        )

        return Response({
            "success": True,
            "message": "Payment collected successfully"
        })

    except Exception as e:
        return Response({
            "success": False,
            "error": str(e)
        })