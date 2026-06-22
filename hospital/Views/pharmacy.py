from django.http import JsonResponse
from pymongo import MongoClient
import os
import json
import pytz
from datetime import datetime, date
from django.utils.dateparse import parse_datetime
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
from ..models import Patient, PharmacyStock, PharmacyBilling, PharmacyItem, Admission, InsuranceProvider
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



@api_view(["POST","GET"])
@permission_classes([HasRoleAndDataPermission])
def get_pharmacy_stock(request):
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
            "outlet_code": outlet_code   
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
                                        {"$eq": ["$hospital_code", "$$hospital_code"]}  
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

    # ✅ JOIN CHEMICAL COMPOSITION
{
    "$lookup": {
        "from": "hospital_chemicalcomposition",
        "let": {
            "composition_id": {
                "$toInt": "$item_details.chemical_composition"
            },
            "hospital_code": "$hospital_code",
            "branch_code": "$branch_code"
        },
        "pipeline": [
            {
                "$match": {
                    "$expr": {
                        "$and": [
                            {
                                "$eq": [
                                    "$composition_id",
                                    "$$composition_id"
                                ]
                            },
                            {
                                "$eq": [
                                    "$hospital_code",
                                    "$$hospital_code"
                                ]
                            },
                            {
                                "$eq": [
                                    "$branch_code",
                                    "$$branch_code"
                                ]
                            },
                            {
                                "$eq": [
                                    "$is_active",
                                    True
                                ]
                            }
                        ]
                    }
                }
            }
        ],
        "as": "composition_details"
    }
},

# ✅ UNWIND COMPOSITION
{
    "$unwind": {
        "path": "$composition_details",
        "preserveNullAndEmptyArrays": True
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
                     "composition_name": "$composition_details.composition_name",

                    "high_risk": "$item_details.high_risk",
                    "look_alike": "$item_details.look_alike",
                    "sound_alike": "$item_details.sound_alike", 

                    "shelf_no": 1,   
                    "rack_no": 1,    

                    "CGST_Percentage": 1,
                    "SGST_Percentage": 1,

                    "CGST_Amt": 1,
                    "SGST_Amt": 1
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

        clean.append({
            "item_id": int(med.get("item_id")),
            "batch_number": str(med.get("batch_number")),
            "qty": int(med.get("qty", 0)),
            "price": float(med.get("price", 0)),
            "calculated_price": float(med.get("calculated_price", 0)),
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
def save_pharmacy_bill(request):

    data = request.data
    employee_id = data.get("auth-user-id")

    # ✅ AUTH CODES
    hospital_code = data.get("auth-hospital-code")
    branch_code   = data.get("auth-branch-code")
    outlet_code   = data.get("auth-outlet-code")

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
    # FIX 1 — uhid is NOT mandatory; store None if missing
    # --------------------------------------------------
    uhid = data.get("uhid") or None   # blank string → None (allowed)

    # --------------------------------------------------
    # COMMON FIELDS
    # --------------------------------------------------
    fields = {
        # FIX 1: uhid is optional — stored as-is (None if not provided)
        "uhid":                     uhid,
        "inpatient_number":         data.get("inpatient_number"),
        "bill_type":                data.get("bill_type"),
        "doctor_id":                data.get("doctor_id"),
        # FIX 3: age stored as integer; also returned in every response
        "age":                      int(data.get("age", 0) or 0),
        "room_no":                  data.get("room_no"),
        "total_amount":             float(data.get("total_amount", 0)),
        "overall_discount_type":    data.get("overall_discount_type"),
        "overall_discount_value":   float(data.get("overall_discount_value", 0)),
        "overall_discount_amount":  float(data.get("overall_discount_amount", 0)),
        "net_amount":               float(data.get("net_amount", 0)),
        "shiftno":                  data.get("shiftno"),
    }

    # ✅ Save patient_name ONLY when uhid is not provided
    if not uhid:
        fields["patient_name"] = data.get("patient_name")

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
        update_data["lastmodified_by"]      = employee_id
        update_data["lastmodified_date"]    = datetime.utcnow()
        update_data["edit_reason"]          = data.get("edit_reason", "")
        update_data["edited_by"]            = employee_id
        update_data["is_dispatched"]        = data.get("is_dispatched", False)   
        update_data["pending_returns"]      = data.get("pending_returns", [])

        # 🔥 UPDATE ESTIMATE
        if status == "Estimate":
            update_data["billing_status"] = "Estimate"
            update_data["billing_mode"]   = "ESTIMATE"

        # 🔥 CONVERT TO BILL
        elif status == "Billed":
            if not record.bill_no:
                update_data["bill_no"] = get_last_oppharmacy_billno(get_financial_year())

            update_data["billing_status"] = "Billed"
            update_data["billing_mode"]   = "ESTIMATE"
            update_data["bill_date"]      = datetime.utcnow()

        bill_collection.update_one(
            {"Bill_id": int(Bill_id)},
            {"$set": update_data}
        )

        # FIX 3: return bill_no + age immediately in PATCH response
        return Response({
            "success":     True,
            "Bill_id":     record.Bill_id,
            "bill_no":     update_data.get("bill_no") or record.bill_no,
            "estimate_no": record.estimate_no,
            "age":         update_data.get("age", record.age or 0),   # ✅ FIX 3
            "edit_reason": update_data.get("edit_reason"),
            "edited_by":   update_data.get("edited_by"),
        })

    # ======================================================
    # 🆕 POST (CREATE)
    # ======================================================
    if request.method == "POST":

        last = PharmacyBilling.objects.order_by('-Bill_id').first()
        next_Bill_id = (last.Bill_id + 1) if last else 1

        record_doc = {
            "Bill_id":              next_Bill_id,
            "medicine_particulars": medicines,
            "billing_status":       status,
            "created_by":           employee_id,
            "created_date":         datetime.utcnow(),
            "bill_date":            datetime.utcnow(),
            "hospital_code":        hospital_code,
            "branch_code":          branch_code,
            "outlet_code":          outlet_code,
            "is_dispatched":        False,        
            "pending_returns":      [],     
            **fields
        }

        # 🔥 DIRECT BILL
        if status == "Billed":
            bill_no = get_last_oppharmacy_billno(get_financial_year())

            record_doc.update({
                "bill_no":      bill_no,
                "estimate_no":  None,
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

            # FIX 3: return bill_no + age immediately
            return Response({
                "success": True,
                "bill_no": bill_no,
                "Bill_id": next_Bill_id,
                "age":     record_doc.get("age", 0),   # ✅ FIX 3
            })

        # 🔥 ESTIMATE
        if status == "Estimate":
            estimate_no = generate_estimate_no()

            record_doc.update({
                "bill_no":      None,
                "estimate_no":  estimate_no,
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

            # FIX 3: return estimate_no + age immediately
            return Response({
                "success":     True,
                "estimate_no": estimate_no,
                "Bill_id":     next_Bill_id,
                "age":         record_doc.get("age", 0),   # ✅ FIX 3
            })

    return Response({"success": False, "error": "Invalid request"})




@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_pharmacy_BillType(request):
    db = client["HMS"]
    stock_collection = db["hospital_billtype"]

 
    hospital_code = request.data.get("auth-hospital-code") 
    branch_code   = request.data.get("auth-branch-code") 
    outlet_code   = request.data.get("auth-outlet-code") 
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



@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_estimate_bills(request):
    try:

      
        hospital_code = request.data.get("auth-hospital-code") or request.META.get("HTTP_AUTH_HOSPITAL_CODE")
        branch_code = request.data.get("auth-branch-code") or (request.META.get("HTTP_AUTH_BRANCH_CODE") or request.META.get("HTTP_BRANCH_CODE"))
        outlet_code = request.data.get("auth-outlet-code") or (request.META.get("HTTP_AUTH_OUTLET_CODE") or request.META.get("HTTP_OUTLET_CODE"))

        # =========================================================
        # ✅ Fetch Estimate Bills
        # =========================================================
        bills = PharmacyBilling.objects.filter(
            billing_status="Estimate",
            hospital_code=hospital_code,
            branch_code=branch_code,
            outlet_code=outlet_code
        )

        data = []

        for bill in bills:

            # =========================================================
            # ✅ Get Patient (ONLY ONCE)
            # =========================================================
            patient = Patient.objects.filter(uhid=bill.uhid).first()

            patient_name = ""
            if patient:
                patient_name = f"{patient.firstName} {patient.lastName}"

            # =========================================================
            # ✅ Medicine Particulars Handling
            # =========================================================
            meds = bill.medicine_particulars

            # Handle string JSON
            if isinstance(meds, str):
                meds = json.loads(meds)

            particulars = []

            for med in meds:
                item_id = med.get("item_id")

                # =====================================================
                # ✅ Fetch Item Name
                # =====================================================
                item = PharmacyItem.objects.filter(item_id=item_id).first()
                item_name = item.item_name if item else ""

                particulars.append({
                    "item_id": item_id,
                    "item_name": item_name,
                    "batch_number": med.get("batch_number"),
                    "qty": med.get("qty"),
                    "price": med.get("price"),
                })

            # =========================================================
            # ✅ Final Response Object
            # =========================================================
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

        return Response(data, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({
            "status": "error",
            "message": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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










from decimal import Decimal
from datetime import datetime
from pymongo import MongoClient
import os
import traceback

from ..models import PharmacyBilling
from ..serializers import CashCounterCollectionSerializer

from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response


@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def collect_oppharmacy_payment(request):

    try:

        data = request.data

        Bill_id = data.get("Bill_id")
        uhid = data.get("uhid")
        payment_details = data.get("payment_details")

        shiftno = data.get("shiftno")
        counter_id = data.get("counter_id")

        remarks = data.get("remarks", "")

        hospital_code = (
            data.get("auth-hospital-code")
            or request.META.get("HTTP_AUTH_HOSPITAL_CODE")
        )

        branch_code = (
            data.get("auth-branch-code")
           
            
        )

        outlet_code = (
            data.get("auth-outlet-code")
            
           
        )

        cashier_id = data.get("auth-user-id")

        # =====================================================
        # VALIDATIONS
        # =====================================================

        if not Bill_id:
            return Response({
                "success": False,
                "error": "Bill_id is required"
            })

        if not uhid:
            return Response({
                "success": False,
                "error": "uhid is required"
            })

        if not payment_details:
            return Response({
                "success": False,
                "error": "payment_details is required"
            })

        if not hospital_code or not branch_code or not outlet_code:
            return Response({
                "success": False,
                "error": "hospital/branch/outlet missing"
            })

        if not cashier_id:
            return Response({
                "success": False,
                "error": "cashier_id missing"
            })

        if not isinstance(payment_details, dict):
            return Response({
                "success": False,
                "error": "payment_details must be object"
            })

        # =====================================================
        # TYPE CONVERSIONS
        # =====================================================

        Bill_id = int(Bill_id)

        uhid = str(uhid).strip()

        hospital_code = str(hospital_code).strip()
        branch_code = str(branch_code).strip()
        outlet_code = str(outlet_code).strip()

        cashier_id = str(cashier_id).strip()

        # =====================================================
        # DB CONNECTION
        # =====================================================

        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))

        db = client["HMS"]

        bill_collection = db["hospital_pharmacybilling"]

        stock_collection = db["hospital_pharmacystock"]

        # =====================================================
        # FIND BILL
        # =====================================================

        query = {
            "Bill_id": Bill_id,
            "uhid": uhid,
            "hospital_code": hospital_code,
            "branch_code": branch_code,
            "outlet_code": outlet_code,
            "$or": [
                {"is_deleted": False},
                {"is_deleted": {"$exists": False}}
            ]
        }

        bill = bill_collection.find_one(query)

        if not bill:
            return Response({
                "success": False,
                "error": "Bill not found",
                "query": query
            })

        # =====================================================
        # CHECK ALREADY PAID
        # =====================================================

        if bill.get("billing_status") == "Paid":
            return Response({
                "success": False,
                "error": "Bill already paid"
            })

        # =====================================================
        # UPDATE STOCK
        # =====================================================

        for med in bill.get("medicine_particulars", []):

            stock_collection.update_one(
                {
                    "item_id": med.get("item_id"),
                    "batch_number": med.get("batch_number")
                },
                {
                    "$inc": {
                        "sold_quantity": float(
                            med.get("qty", 0)
                        )
                    }
                }
            )

        # =====================================================
        # UPDATE BILL
        # =====================================================

        update_result = bill_collection.update_one(
            query,
            {
                "$set": {
                    "billing_status": "Paid",
                    "payment_details": payment_details,
                    "paid_date": datetime.utcnow(),

                    "cashier_id": cashier_id,
                    "shiftno": shiftno,
                    "counter_id": counter_id
                }
            }
        )

        if update_result.modified_count == 0:
            return Response({
                "success": False,
                "error": "Payment update failed"
            })

        # =====================================================
        # CASH COUNTER COLLECTION SAVE
        # =====================================================

        print("=" * 60)
        print("💾 CashCounterCollection SAVE START")
        print("=" * 60)

        collected_amount = payment_details.get(
            "Paid_amount",
            0
        )

        cash_counter_data = {

            # ===================================
            # AUDIT FIELDS
            # ===================================

            "hospital_code": hospital_code,
            "branch_code": branch_code,
            "outlet_code": outlet_code,

            "created_by": cashier_id,
            "lastmodified_by": cashier_id,

            # ===================================
            # BILL DATA FROM PharmacyBilling
            # ===================================

            "Bill_id": bill.get("Bill_id"),

            "bill_no": bill.get("bill_no"),

            "bill_type": bill.get("bill_type"),

            # bill_number stores bill_no
            "bill_number": bill.get("bill_no"),

            # ===================================
            # CASH COUNTER DATA
            # ===================================

            "counter_code": counter_id,

           "shift_no": shiftno,

            "billing_category": "OPPharmacyBills",

            "transaction_type": "collected",

            "collected_amount": str(
                payment_details.get("Paid_amount", 0)
            ),

            "Returned_amount": "0.00",

            "remarks": remarks
        }

        print("📦 cash_counter_data:")
        print(cash_counter_data)

        cc_serializer = CashCounterCollectionSerializer(
            data=cash_counter_data
        )

        if cc_serializer.is_valid():

            instance = cc_serializer.save()

            print(
                f"✅ CashCounterCollection saved successfully "
                f"ID = {instance.collection_id}"
            )

        else:

            print("❌ SERIALIZER ERRORS")
            print(cc_serializer.errors)

            return Response({
                "success": False,
                "error": cc_serializer.errors
            })

        print("=" * 60)

        # =====================================================
        # SUCCESS RESPONSE
        # =====================================================

        return Response({
            "success": True,
            "message": "Payment collected successfully",

            "Bill_id": Bill_id,
            "cashier_id": cashier_id,

            "collection_saved": True
        })

    except Exception as e:

        print(f"❌ EXCEPTION: {e}")

        traceback.print_exc()

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
def pharmacy_deletebill(request):
    try:
        data = request.data
        employee_id = data.get("auth-user-id") 

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

                    current_sold = int(stock.sold_quantity or 0)

                    # ✅ REDUCE SOLD QTY
                    new_sold = max(0, current_sold - qty)

                    PharmacyStock.objects.filter(
                        item_id=item_id,
                        batch_number=batch
                    ).update(
                        sold_quantity=new_sold,
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



from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from django.db.models import Sum
from pymongo import MongoClient
import os
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

    if not isinstance(data, str) or not data.strip():
        return []

    try:
        # Step 1: Convert OrderedDict([...]) → dict([...])
        clean = re.sub(r'OrderedDict\(', 'dict(', data)

        # Step 2: eval with datetime in scope so datetime.datetime(...) resolves
        import datetime as dt
        parsed = eval(clean, {"__builtins__": {}, "dict": dict, "datetime": dt, "True": True, "False": False, "None": None})

        return parsed if isinstance(parsed, list) else []

    except Exception as e:
        print("❌ parse_medicine_particulars failed:", e)
        print("   Raw data snippet:", str(data)[:300])
        return []


# -----------------------------------------
# 🔹 MAIN API
# -----------------------------------------
@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def pharmacy_medicinechart(request):
    try:
        print("\n===== API START: pharmacy_medicinechart =====")

        data = request.data

        hospital_code = data.get("auth-hospital-code")
        branch_code   = data.get("auth-branch-code")
        outlet_code   = data.get("auth-outlet-code")

        print("hospital_code:", hospital_code)
        print("branch_code:",   branch_code)
        print("outlet_code:",   outlet_code)

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
        # 🌐 PHARMACY MONGO COLLECTION
        #    FIX: connect to bill_collection so we can read the latest
        #    medicine_particulars (which includes substituted items saved
        #    by substitute_medicine — those are written to MongoDB, not
        #    back to the Django ORM, so the ORM serializer would return
        #    stale pre-substitute data on refresh).
        # =========================================
        pharmacy_client = MongoClient(os.getenv("PHARMACY_DB_HOST", os.getenv("GLOBAL_DB_HOST")))
        pharmacy_db     = pharmacy_client[os.getenv("PHARMACY_DB_NAME", "pharmacy")]
        bill_collection = pharmacy_db["pharmacy_billing"]   # adjust collection name as needed

        # =========================================
        # 🔎 FETCH BILLS via Django ORM
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

            bill_id = bill.get("Bill_id")

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
                        "address":       patient.permanent_address,
                        "mobile":        patient.mobilePhone
                    }

            bill["patient_details"] = patient_data

            # -------------------------------------
            # 👨‍⚕️ DOCTOR DETAILS (GLOBAL DB)
            # -------------------------------------
            doctor_id   = bill.get("doctor_id")
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
            # 💊 FIX: READ medicine_particulars FROM MONGODB
            #
            # substitute_medicine writes directly to bill_collection
            # (MongoDB). The ORM serializer only reflects the original
            # Django model — it never sees MongoDB updates. Reading from
            # bill_collection here ensures substituted items are always
            # returned fresh on every call.
            # -------------------------------------
            mongo_doc = bill_collection.find_one(
                {
                    "Bill_id":      bill_id,
                    "hospital_code": hospital_code,
                    "branch_code":   branch_code,
                    "outlet_code":   outlet_code,
                },
                {"medicine_particulars": 1, "_id": 0}
            )

            if mongo_doc:
                # Use the up-to-date MongoDB version (includes substitutes)
                raw_particulars = mongo_doc.get("medicine_particulars", [])
                print(f"✅ Bill {bill_id}: read {len(raw_particulars)} items from MongoDB")
            else:
                # Fallback: parse from ORM serializer (first-time / sync lag)
                raw_particulars = bill.get("medicine_particulars", [])
                print(f"⚠️ Bill {bill_id}: MongoDB doc not found, falling back to ORM data")

            items = parse_medicine_particulars(raw_particulars)

            mapped_items = []

            # -------------------------------------
            # 🔄 LOOP ITEMS
            # -------------------------------------
            for item in items:

                if not isinstance(item, dict):
                    continue

                # Skip soft-deleted items (replaced by substitute)
                if item.get("is_deleted"):
                    continue

                item_id   = item.get("item_id")
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

                item_name = item_obj.item_name if item_obj else item.get("item_name")

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
                sold        = stock_agg.get("sold")        or 0
                transferred = stock_agg.get("transferred") or 0
                grn_return  = stock_agg.get("grn_return")  or 0

                available_stock = total_stock - sold - transferred - grn_return

                # ---------------------------------
                # 💰 TAX
                # ---------------------------------
                latest_stock = stock_qs.first()

                cgst_per = convert_decimal(getattr(latest_stock, "CGST_Percentage", 0)) if latest_stock else 0
                sgst_per = convert_decimal(getattr(latest_stock, "SGST_Percentage", 0)) if latest_stock else 0
                cgst_amt = convert_decimal(getattr(latest_stock, "CGST_Amt",        0)) if latest_stock else 0
                sgst_amt = convert_decimal(getattr(latest_stock, "SGST_Amt",        0)) if latest_stock else 0

                # ---------------------------------
                # ✅ FINAL MAP — preserve substitute flags from MongoDB
                # ---------------------------------
                mapped_items.append({
                    **item,                        # keeps is_substitute, substituted, edit_history, etc.
                    "item_name":       item_name,
                    "batch_number":    req_batch,
                    "available_stock": available_stock,
                    "CGST_Percentage": cgst_per,
                    "SGST_Percentage": sgst_per,
                    "CGST_Amt":        cgst_amt,
                    "SGST_Amt":        sgst_amt,
                })

            bill["medicine_items"] = mapped_items
            final_data.append(bill)

        print("\n===== API SUCCESS =====")

        return Response({
            "status":  "success",
            "count":   len(final_data),
            "data":    final_data
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







@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def substitute_medicine(request):
    try:
        data = request.data

        # ── Auth context ──────────────────────────────────────────────
        hospital_code = data.get("auth-hospital-code")
        branch_code   = data.get("auth-branch-code")
        outlet_code   = data.get("auth-outlet-code")
        employee_id = data.get("auth-user-id")

        if not hospital_code or not branch_code or not outlet_code:
            return Response({"error": "Missing hospital/branch/outlet code"}, status=400)

        # ── Input ─────────────────────────────────────────────────────
        Bill_id      = data.get("Bill_id")
        item_id      = int(data.get("item_id"))
        batch_number = data.get("batch_number")
        

        substitute_item = data.get("substitute_item")
        if isinstance(substitute_item, str):
            substitute_item = json.loads(substitute_item)

        # ── Fetch bill ────────────────────────────────────────────────
        bill = bill_collection.find_one({
            "Bill_id":      Bill_id,
            "hospital_code": hospital_code,
            "branch_code":   branch_code,
            "outlet_code":   outlet_code,
        })
        if not bill:
            return Response({"error": "Bill not found"}, status=404)

        medicines        = bill.get("medicine_particulars", [])
        updated_medicines = []
        substituted      = False

        for med in medicines:
            if med["item_id"] == item_id and med["batch_number"] == batch_number:
                substituted = True

                # Carry forward existing history (guard against null)
                med_edit_history = med.get("edit_history") or []

                # Append a concise substitution record (matches qty_added style)
                med_edit_history.append({
                    "action":      "substituted",
                    "old_item_id": med["item_id"],
                    "new_item_id": substitute_item.get("item_id"),
                    "timestamp":   datetime.utcnow().isoformat(),
                    "edited_by":   employee_id,
                    "hospital_code": hospital_code,
                    "branch_code":   branch_code,
                    "outlet_code":   outlet_code,
                })

                # Replace in-place: substitute carries the history, old entry dropped
                substitute_item["edit_history"] = med_edit_history
                updated_medicines.append(substitute_item)   # ← substitute replaces original
            else:
                updated_medicines.append(med)               # ← all others unchanged

        if not substituted:
            return Response({"error": "Matching medicine not found in bill"}, status=404)

        # ── Persist ───────────────────────────────────────────────────
        bill_collection.update_one(
            {
                "Bill_id":      Bill_id,
                "hospital_code": hospital_code,
                "branch_code":   branch_code,
                "outlet_code":   outlet_code,
            },
            {
                "$set": {
                    "medicine_particulars": updated_medicines,
                    "lastmodified_date":    datetime.utcnow(),
                    "lastmodified_context": {
                        "hospital_code": hospital_code,
                        "branch_code":   branch_code,
                        "outlet_code":   outlet_code,
                    },
                }
            }
        )

        return Response({"status": "success", "message": "Medicine substituted"})

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

        # =====================================================
        # ✅ AUTH CONTEXT
        # =====================================================
        hospital_code = (
            data.get("auth-hospital-code")
            
        )

        branch_code = (
            data.get("auth-branch-code")
            
        )

        outlet_code = (
            data.get("auth-outlet-code")
           
        )

        employee_id = (
            data.get("auth-user-id")
            
        )

        print("hospital_code_finalize_bill:", hospital_code)
        print("branch_code_finalize_bill:", branch_code)
        print("outlet_code_finalize_bill:", outlet_code)

        # =====================================================
        # ✅ VALIDATION
        # =====================================================
        if not hospital_code or not branch_code or not outlet_code:
            return Response(
                {"error": "Missing hospital/branch/outlet code"},
                status=400
            )

        # =====================================================
        # ✅ INPUT
        # =====================================================
        Bill_id = data.get("Bill_id")

        if not Bill_id:
            return Response(
                {"error": "Bill_id is required"},
                status=400
            )

        # =====================================================
        # ✅ FETCH BILL
        # =====================================================
        bill = bill_collection.find_one({
            "Bill_id": Bill_id,
            "hospital_code": hospital_code,
            "branch_code": branch_code,
            "outlet_code": outlet_code
        })

        if not bill:
            return Response(
                {"error": "Bill not found"},
                status=404
            )

        # =====================================================
        # ✅ GENERATE BILL NO
        # =====================================================
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

        # =====================================================
        # ✅ PREPARE MEDICINE HISTORY
        # =====================================================
        medicine_history = []

        for med in medicines:

            if med.get("is_deleted"):
                continue

            try:
                item_id = int(med.get("item_id", 0))
            except:
                item_id = 0

            try:
                qty = float(med.get("quantity", 0))
            except:
                qty = 0

            try:
                price = float(
                    med.get("price")
                    or med.get("mrp")
                    or med.get("rate")
                    or 0
                )
            except:
                price = 0

            calculated_price = round(qty * price, 2)

            medicine_history.append({

                "item_id": item_id,
                "item_name": med.get("item_name"),
                "batch_number": med.get("batch_number"),

                "quantity": qty,

                # ✅ PRICE
                "price": price,

                # ✅ CALCULATED PRICE
                "calculated_price": calculated_price,

                # ✅ EXTRA FIELDS
                "discount": med.get("discount", 0),
                "tax": med.get("tax", 0),
                "mrp": med.get("mrp"),
                "expiry_date": med.get("expiry_date"),

                # ✅ ACTION
                "action": "finalized",

                # ✅ AUDIT
                "edited_by": employee_id,
                "edited_at": datetime.utcnow()
            })

        # =====================================================
        # ✅ STOCK UPDATE
        # =====================================================
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
                    "$inc": {
                        "blocked_quantity": qty
                    }
                },
                upsert=False
            )

            print("STOCK FILTER:", {
                "item_id": item_id,
                "batch_number": batch,
                "hospital_code": hospital_code,
                "branch_code": branch_code,
                "outlet_code": outlet_code
            })

            print(
                "MATCHED:",
                result.matched_count,
                "MODIFIED:",
                result.modified_count
            )

        # =====================================================
        # ✅ UPDATE BILL
        # =====================================================
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

                    "lastmodified_date": datetime.utcnow(),

                    # ✅ STORE PRICE VALUES INSIDE MAIN MEDICINES
                    "medicine_particulars": medicine_history
                },

                # ✅ STORE EDIT HISTORY
                "$push": {
                    "edit_history": {

                        "action": "finalized",

                        "edited_by": employee_id,

                        "edited_at": datetime.utcnow(),

                        "bill_no": new_bill_no,

                        "bill_date": bill_date,

                        "medicines": medicine_history
                    }
                }
            }
        )

        # =====================================================
        # ✅ RESPONSE
        # =====================================================
        return Response({

            "status": "success",

            "message": "Bill finalized & stock updated",

            "bill_no": new_bill_no,

            "bill_date": bill_date

        })

    except Exception as e:

        import traceback

        traceback.print_exc()

        return Response(
            {"error": str(e)},
            status=500
        )






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
        hospital_code = request.data.get("auth-hospital-code") or request.META.get("HTTP_AUTH_HOSPITAL_CODE")
        branch_code = request.data.get("auth-branch-code") or (request.META.get("HTTP_AUTH_BRANCH_CODE") or request.META.get("HTTP_BRANCH_CODE"))
        outlet_code = request.data.get("auth-outlet-code") or (request.META.get("HTTP_AUTH_OUTLET_CODE") or request.META.get("HTTP_OUTLET_CODE"))

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
    








from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from pymongo import MongoClient
import os

from ..models import SalesReturn, Patient
from ..serializers import SalesReturnSerializer, PatientSerializer


@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_salesreturn_details(request):
    """
    GET /get_salesreturn_details/?from_date=YYYY-MM-DD&to_date=YYYY-MM-DD
    Returns sales return records enriched with patient name and pharmacist name.
    Defaults to today's date if no params are passed.
    """
    try:
        today = timezone.now().date()

        from_date_str = request.query_params.get("from_date", str(today))
        to_date_str   = request.query_params.get("to_date",   str(today))

        try:
            from datetime import datetime
            from_dt = datetime.strptime(from_date_str, "%Y-%m-%d")
            to_dt   = datetime.strptime(to_date_str,   "%Y-%m-%d").replace(
                hour=23, minute=59, second=59
            )
        except ValueError:
            return Response(
                {"status": "error", "message": "Invalid date format. Use YYYY-MM-DD."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── 1. Fetch SalesReturn records in date range ────────────────────────
        returns = SalesReturn.objects.filter(
            return_bill_date__gte=from_dt,
            return_bill_date__lte=to_dt,
        ).order_by("-return_bill_date")

        serialized = SalesReturnSerializer(returns, many=True).data

        if not serialized:
            return Response({"status": "success", "data": []}, status=status.HTTP_200_OK)

        # ── 2. Collect unique UHIDs & pharmacist IDs for batch lookup ─────────
        uhid_set         = {r["uhid"] for r in serialized if r.get("uhid")}
        pharmacist_id_set = {r["pharmacist_id"] for r in serialized if r.get("pharmacist_id")}

        # ── 3. Patient name lookup (Django ORM) ───────────────────────────────
        patients = Patient.objects.filter(uhid__in=uhid_set)
        patient_map = {}
        for p in patients:
            pd = PatientSerializer(p).data
            salutation  = (pd.get("salutation") or "").strip()
            first_name  = (pd.get("firstName")  or "").strip()
            last_name   = (pd.get("lastName")   or "").strip()
            full_name   = " ".join(filter(None, [salutation, first_name, last_name]))
            patient_map[pd["uhid"]] = full_name

        # ── 4. Pharmacist name lookup (MongoDB cross-db) ──────────────────────
        pharmacist_map = {}
        if pharmacist_id_set:
            try:
                client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
                global_db          = client["Global"]
                profile_collection = global_db["backend_diagnostics_profile"]

                profiles = profile_collection.find(
                    {"employeeId": {"$in": list(pharmacist_id_set)}},
                    {"employeeId": 1, "employeeName": 1, "_id": 0},
                )
                for profile in profiles:
                    pharmacist_map[str(profile["employeeId"])] = profile.get("employeeName", "")

                client.close()
            except Exception as mongo_err:
                # Non-fatal — names just won't resolve
                print(f"Pharmacist lookup failed: {mongo_err}")

        # ── 5. Build enriched response ────────────────────────────────────────
        result = []
        for r in serialized:
            uhid          = r.get("uhid", "")
            pharmacist_id = r.get("pharmacist_id", "")

            result.append({
                # Raw serializer fields
                **r,
                # Enriched display fields
                "patient_name":    patient_map.get(uhid, ""),
                "pharmacist_name": pharmacist_map.get(str(pharmacist_id), ""),
            })

        return Response(
            {"status": "success", "data": result},
            status=status.HTTP_200_OK,
        )

    except Exception as e:
        return Response(
            {
                "status": "error",
                "message": f"Internal server error: {str(e)}",
                "error_type": type(e).__name__,
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


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



@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def searchby_ip(request):

    employee_id   = request.data.get('auth-user-id')       
    hospital_code = request.data.get("auth-hospital-code") 
    branch_code   = request.data.get("auth-branch-code")   
    
    print("*****************", employee_id, hospital_code, branch_code)

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
        







from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from datetime import datetime
from rest_framework import status
from pymongo import MongoClient
import os



@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def pharmacy_view_bills(request):

    # =========================================================
    # ✅ Get values from REQUEST
    # =========================================================
    employee_id    = request.data.get("auth-user-id")
    hospital_code  = request.data.get("auth-hospital-code")
    branch_code    = request.data.get("auth-branch-code")
    request_outlet = request.data.get("auth-outlet-code")

    # =========================================================
    # ✅ Guard
    # =========================================================
    if not hospital_code or not branch_code or not request_outlet or not employee_id:
        return Response({
            "success": False,
            "message": "Missing required headers (hospital, branch, outlet, or employee)"
        }, status=400)

    # =========================================================
    # ✅ MongoDB Connections
    # =========================================================
    client = MongoClient(os.getenv("GLOBAL_DB_HOST"))

    global_db = client["Global"]
    profile_collection = global_db["backend_diagnostics_profile"]

    hms_db = client["HMS"]
    billtype_collection          = hms_db["hospital_billtype"]
    pharmacy_item_collection     = hms_db["hospital_pharmacyitem"]
    pharmacy_stock_collection    = hms_db["hospital_pharmacystock"]
    oppharmacy_collection        = hms_db["hospital_pharmacybilling"]
    # ✅ Sales returns are read from oppharmacy_collection (edit_history) — NOT hospital_salesreturn

    # =========================================================
    # ✅ Employee Profile
    # =========================================================
    try:
        query_id = str(employee_id)
        search_query = {
            "employeeId": {
                "$in": [
                    query_id,
                    int(query_id) if query_id.isdigit() else query_id
                ]
            }
        }
    except:
        search_query = {"employeeId": str(employee_id)}

    employee_profile = profile_collection.find_one(
        search_query,
        {
            "employeeId":   1,
            "employeeName": 1,
            "hms_outlets":  1
        }
    )

    if not employee_profile:
        return Response({
            "success": False,
            "message": "Employee not found"
        }, status=404)

    emp_outlets = employee_profile.get("hms_outlets", [])
    emp_name    = employee_profile.get("employeeName", employee_id)

    # =========================================================
    # ✅ Outlet Validation
    # =========================================================
    if request_outlet not in emp_outlets:
        return Response({
            "success": False,
            "message": f"Outlet {request_outlet} not mapped to employee"
        }, status=403)

    matched_outlet = request_outlet

    # =========================================================
    # ✅ Get All Bill Types
    # =========================================================
    billtype_cursor = billtype_collection.find(
        {
            "hospital_code": hospital_code,
            "branch_code":   branch_code
        },
        {
            "bill_type": 1,
            "bill_name": 1
        }
    )

    billtype_map       = {}
    allowed_bill_types = []

    for bt in billtype_cursor:
        bill_type = bt.get("bill_type")
        if bill_type is not None:
            allowed_bill_types.append(int(bill_type))
            billtype_map[int(bill_type)] = bt.get("bill_name", "")

    # =========================================================
    # ✅ Django Bills
    # =========================================================
    bills = list(
        PharmacyBilling.objects.filter(
            billing_status__in=["Billed", "Paid", "Processing", "deleted"],
            hospital_code=hospital_code,
            branch_code=branch_code,
            outlet_code=matched_outlet,
            bill_type__in=allowed_bill_types
        ).order_by("-created_date")
    )

    # =========================================================
    # ✅ Patient Mapping
    # =========================================================
    uhids = [bill.uhid for bill in bills if bill.uhid]

    patients    = Patient.objects.filter(uhid__in=uhids)
    patient_map = {
        p.uhid: f"{p.salutation or ''} {p.firstName or ''} {p.lastName or ''}".strip()
        for p in patients
    }

    # =========================================================
    # ✅ Doctor Mapping
    # =========================================================
    doctor_ids = list(set([bill.doctor_id for bill in bills if bill.doctor_id]))
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

    # =========================================================
    # ✅ Collect Bill Items from MongoDB (oppharmacy_collection)
    #    This collection also holds edit_history with sales_return entries
    # =========================================================
    bill_ids    = [bill.Bill_id for bill in bills]
    mongo_bills = []

    if bill_ids:
        mongo_bills = list(
            oppharmacy_collection.find(
                {
                    "Bill_id":       {"$in": bill_ids},
                    "hospital_code": hospital_code,
                    "branch_code":   branch_code,
                    "outlet_code":   matched_outlet
                },
                {
                    "Bill_id":              1,
                    "medicine_particulars": 1,
                    "billing_status":       1,
                }
            )
        )

    mongo_map = {m["Bill_id"]: m for m in mongo_bills}

    # =========================================================
    # ✅ Collect item_ids + batch_numbers for mapping
    # =========================================================
    item_batch_set = set()

    for m in mongo_bills:
        for item in m.get("medicine_particulars", []):
            if item.get("item_id") and item.get("batch_number"):
                item_batch_set.add((
                    int(item["item_id"]),
                    str(item["batch_number"]).strip()
                ))

    item_ids      = list(set([i[0] for i in item_batch_set]))
    batch_numbers = list(set([i[1] for i in item_batch_set]))

    # =========================================================
    # ✅ Item Mapping
    # =========================================================
    item_map = {}

    if item_ids:
        item_cursor = pharmacy_item_collection.find(
            {
                "item_id":       {"$in": item_ids},
                "hospital_code": hospital_code,
                "branch_code":   branch_code
            },
            {
                "item_id":   1,
                "item_name": 1
            }
        )
        item_map = {
            i["item_id"]: i.get("item_name", "")
            for i in item_cursor
        }

    # =========================================================
    # ✅ Stock Mapping (GST)
    # =========================================================
    stock_map = {}

    if item_ids and batch_numbers:
        stock_cursor = pharmacy_stock_collection.find(
            {
                "item_id":       {"$in": item_ids},
                "batch_number":  {"$in": batch_numbers},
                "hospital_code": hospital_code,
                "branch_code":   branch_code,
                "outlet_code":   matched_outlet
            },
            {
                "item_id":         1,
                "batch_number":    1,
                "CGST_Percentage": 1,
                "SGST_Percentage": 1,
                "CGST_Amt":        1,
                "SGST_Amt":        1
            }
        )
        stock_map = {
            (
                s["item_id"],
                str(s["batch_number"]).strip()
            ): s
            for s in stock_cursor
        }

    # =========================================================
    # ✅ Build Bills Data
    #    medicine_particulars includes edit_history so the frontend
    #    can derive sales_return rows inline without a separate collection
    # =========================================================
    data = []

    for bill in bills:

        serialized = PharmacyBillingSerializer(bill).data

        serialized["patient_name"]   = patient_map.get(bill.uhid, "")
        serialized["doctor_name"]    = doctor_map.get(str(bill.doctor_id), "")
        serialized["bill_type_name"] = billtype_map.get(int(bill.bill_type), "")

        mongo_bill    = mongo_map.get(bill.Bill_id, {})
        medicine_list = mongo_bill.get("medicine_particulars", [])

        updated_items = []

        for item in medicine_list:

            item_id      = int(item.get("item_id")) if item.get("item_id") else None
            batch_number = str(item.get("batch_number")).strip() if item.get("batch_number") else ""

            item["item_name"] = item_map.get(item_id, "")

            stock = stock_map.get((item_id, batch_number), {})

            item["CGST_Percentage"] = convert_decimal(stock.get("CGST_Percentage", 0))
            item["SGST_Percentage"] = convert_decimal(stock.get("SGST_Percentage", 0))
            item["CGST_Amt"]        = convert_decimal(stock.get("CGST_Amt", 0))
            item["SGST_Amt"]        = convert_decimal(stock.get("SGST_Amt", 0))

            # ✅ edit_history is passed through as-is so the frontend can
            #    extract sales_return entries and render them inline in the table
            item["edit_history"] = item.get("edit_history", [])

            updated_items.append(item)

        serialized["medicine_particulars"] = updated_items
        data.append(serialized)

    # =========================================================
    # ✅ Final Response  (no sales_returns key — embedded in edit_history)
    # =========================================================
    return Response({
        "employee_id":   employee_id,
        "employee_name": emp_name,
        "data":          data,
    }, status=status.HTTP_200_OK)




@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def pharmacy_expiry_report(request):
    try:
        hospital_code = request.data.get("auth-hospital-code") or request.META.get("HTTP_AUTH_HOSPITAL_CODE")
        branch_code = request.data.get("auth-branch-code") or (request.META.get("HTTP_AUTH_BRANCH_CODE") or request.META.get("HTTP_BRANCH_CODE"))
        
        # Optional filters
        outlet_code = request.data.get("outlet_code")
        start_date_str = request.data.get("start_date")
        end_date_str = request.data.get("end_date")
        search_query = request.data.get("search_query")
        all_time = request.data.get("all_time", False)
        report_type = request.data.get("report_type", "expiry") # "fast_moving", "not_sold", "stock_transfer", "expiry", "reorder_level"
        
        if not hospital_code or not branch_code:
            return Response({
                "success": False,
                "message": "Missing hospital_code / branch_code"
            }, status=status.HTTP_400_BAD_REQUEST)
            
        # Match stage for stock query
        match_stage = {
            "hospital_code": hospital_code,
            "branch_code": branch_code
        }
        if outlet_code:
            match_stage["outlet_code"] = outlet_code
            
        # Apply report_type specific match filters
        if report_type == "fast_moving":
            match_stage["sold_quantity"] = {"$gt": 0}
        elif report_type == "not_sold":
            match_stage["$or"] = [
                {"sold_quantity": {"$exists": False}},
                {"sold_quantity": {"$eq": 0}},
                {"sold_quantity": None}
            ]
            match_stage["total_stock"] = {"$gt": 0}
        elif report_type == "stock_transfer":
            match_stage["transferred_out_quantity"] = {"$gt": 0}
        # reorder_level filter will be applied after $addFields (post-pipeline stage)

        # Parse start & end dates
        date_filter = {}
        if start_date_str:
            try:
                start_dt = datetime.strptime(start_date_str, "%Y-%m-%d")
                date_filter["$gte"] = start_dt
            except ValueError:
                pass
        if end_date_str:
            try:
                end_dt = datetime.strptime(end_date_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
                date_filter["$lte"] = end_dt
            except ValueError:
                pass
                
        if date_filter:
            match_stage["expiry_date"] = date_filter
        elif not all_time and report_type not in ["fast_moving", "not_sold", "stock_transfer"]:
            match_stage["expiry_date"] = {"$ne": None} # by default exclude nulls
            
        pipeline = [
            # 1. Match stock
            {"$match": match_stage},
            
            # 2. Join with Item details
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
                                        {"$eq": ["$hospital_code", "$$hospital_code"]}
                                    ]
                                }
                            }
                        }
                    ],
                    "as": "item_details"
                }
            },
            
            # 3. Unwind item details
            {
                "$unwind": {
                    "path": "$item_details",
                    "preserveNullAndEmptyArrays": False
                }
            },
            
            # 4. Filter active/non-blocked items
            {
                "$match": {
                    "item_details.is_blocked": False,
                    "item_details.is_active": True
                }
            },
            
            # 5. Stock calculation + reorder_level computation
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
            # 5b. Compute is_below_reorder flag
            {
                "$addFields": {
                    "is_below_reorder": {
                        "$lte": ["$available_stock", "$reorder_level"]
                    }
                }
            }
        ]
        
        # 6. Apply Search Query if present
        if search_query:
            pipeline.append({
                "$match": {
                    "$or": [
                        {"item_details.item_name": {"$regex": search_query, "$options": "i"}},
                        {"batch_number": {"$regex": search_query, "$options": "i"}}
                    ]
                }
            })
            
        # 7. Filter reorder_level items AFTER available_stock is computed
        if report_type == "reorder_level":
            pipeline.append({
                "$match": {
                    "is_below_reorder": True
                }
            })

        # 8. Final projection
        pipeline.append({
            "$project": {
                "_id": 0,
                "stock_id": 1,
                "item_id": 1,
                "batch_number": 1,
                "expiry_date": 1,
                "mrp": 1,
                "Selling_Price": 1,
                "total_stock": 1,
                "available_stock": 1,
                "sold_quantity": {"$ifNull": ["$sold_quantity", 0]},
                "transferred_out_quantity": {"$ifNull": ["$transferred_out_quantity", 0]},
                "reorder_level": 1,
                "is_below_reorder": 1,
                "item_name": "$item_details.item_name",
                "brand_name": "$item_details.brand_name",
                "category": "$item_details.category",
                "hsn": "$item_details.hsn",
                "outlet_code": 1
            }
        })
        
        # 9. Sort by relevant field based on report type
        if report_type == "fast_moving":
            pipeline.append({
                "$sort": {"sold_quantity": -1}
            })
        elif report_type == "stock_transfer":
            pipeline.append({
                "$sort": {"transferred_out_quantity": -1}
            })
        elif report_type == "not_sold":
            pipeline.append({
                "$sort": {"total_stock": -1}
            })
        elif report_type == "reorder_level":
            # Sort by available_stock ascending — most critical (lowest stock) first
            pipeline.append({
                "$sort": {"available_stock": 1}
            })
        else:
            pipeline.append({
                "$sort": {"expiry_date": 1}
            })
        
        results = list(mongo_db["hospital_pharmacystock"].aggregate(pipeline))
        
        # Convert decimal fields and ObjectId
        results = convert_decimals(results)
        
        # Serialize datetime / date fields properly
        def serialize_datetime(obj):
            if isinstance(obj, list):
                return [serialize_datetime(i) for i in obj]
            elif isinstance(obj, dict):
                return {k: serialize_datetime(v) for k, v in obj.items()}
            elif isinstance(obj, (datetime, date)):
                return obj.strftime("%Y-%m-%d")
            return obj
            
        results = serialize_datetime(results)
        
        return Response({
            "success": True,
            "data": results
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({
            "success": False,
            "message": f"Internal server error: {str(e)}"
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
