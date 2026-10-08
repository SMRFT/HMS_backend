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
from django.db.models import Max, Q

# Auth/permissions
from pyauth.auth import HasRoleAndDataPermission, HasRolePermission, HasDataPermission

# Models & Serializers
from ..models import Patient, PharmacyStock, PharmacyBilling, PharmacyItem, Admission, InsuranceProvider,Admission
from ..serializers import PharmacyBillingSerializer
from .cashcounter import validate_active_shift
from .dbcollection import profile_collection, get_pharmacy_items_with_stock, resolve_medicine_stock_details

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
        data = request.data
        hospital_code = data.get("auth-hospital-code") 
        branch_code   = data.get("auth-branch-code")
        outlet_code   = data.get("auth-outlet-code")
        
        # Respect passed outlet_code (query param or body) before falling back to auth-outlet-code
        passed_outlet = data.get("outlet_code") or request.GET.get("outlet_code")
        if passed_outlet:
            outlet_code = passed_outlet

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

        # Filter to active batches with total_stock > 0 to avoid scanning tens of thousands of historical 0-stock batches
        include_zero_stock = request.GET.get("include_zero_stock") or data.get("include_zero_stock")
        if not include_zero_stock or str(include_zero_stock).lower() == "false":
            match_stage["total_stock"] = {"$gt": 0}

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
                "$convert": {
                    "input": "$item_details.chemical_composition",
                    "to": "int",
                    "onError": None,
                    "onNull": None
                }
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
                    "mrp": {
                        "$cond": [
                            {"$gt": [{"$ifNull": ["$Selling_Price", 0]}, 0]},
                            "$Selling_Price",
                            {"$ifNull": ["$mrp", 0]}
                        ]
                    },
                    "Selling_Price": {
                        "$cond": [
                            {"$gt": [{"$ifNull": ["$Selling_Price", 0]}, 0]},
                            "$Selling_Price",
                            {"$ifNull": ["$mrp", 0]}
                        ]
                    },
                    "price": {
                        "$cond": [
                            {"$gt": [{"$ifNull": ["$Selling_Price", 0]}, 0]},
                            "$Selling_Price",
                            {"$ifNull": ["$mrp", 0]}
                        ]
                    },

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

    # Fallback map for batch numbers if missing
    fallback_batch_map = {}
    try:
        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        db = client["HMS"]
        for s in db["hospital_pharmacystock"].find():
            iid = s.get("item_id")
            bn = s.get("batch_number")
            if iid is not None and bn and iid not in fallback_batch_map:
                fallback_batch_map[iid] = str(bn).strip()
                try:
                    fallback_batch_map[int(iid)] = str(bn).strip()
                except Exception:
                    pass
        for v in db["hospital_velavan_stock"].find():
            iid = v.get("item_id")
            bn = v.get("batch_no")
            if iid is not None and bn and iid not in fallback_batch_map:
                fallback_batch_map[iid] = str(bn).strip()
                try:
                    fallback_batch_map[int(iid)] = str(bn).strip()
                except Exception:
                    pass
    except Exception:
        pass

    for med in medicines:
        if not med:
            continue

        item_id_val = int(med.get("item_id"))
        bn_val = str(med.get("batch_number") or med.get("batch_no") or "").strip()
        if not bn_val or bn_val.lower() == "none" or bn_val.lower() == "null" or bn_val == "N/A":
            bn_val = fallback_batch_map.get(item_id_val, "") or fallback_batch_map.get(str(item_id_val), "")

        med_is_consumable = med.get("is_consumable_items")
        if med_is_consumable is None:
            try:
                p_it = db["hospital_pharmacyitem"].find_one({"item_id": item_id_val}, {"is_consumable_items": 1})
                med_is_consumable = bool(p_it.get("is_consumable_items", False)) if p_it else False
            except Exception:
                med_is_consumable = False
        else:
            med_is_consumable = bool(med_is_consumable)

        clean.append({
            "item_id": item_id_val,
            "item_name": med.get("item_name") or med.get("name") or "",
            "batch_number": bn_val,
            "qty": int(med.get("qty", 0)),
            "price": float(med.get("price", 0)),
            "calculated_price": float(med.get("calculated_price", 0)),
            "is_consumable_items": med_is_consumable,
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
    try:
        hospital_code = request.data.get("auth-hospital-code")
        branch_code   = request.data.get("auth-branch-code")
        outlet_code   = request.GET.get("outlet_code") or request.data.get("auth-outlet-code")

        filters = {"uhid__isnull": False}
        if hospital_code:
            filters["hospital_code"] = hospital_code
        if branch_code:
            filters["branch_code"] = branch_code
        if outlet_code:
            filters["outlet_code"] = outlet_code

        # 1️⃣ Get latest bill with a valid UHID
        last_bill = (
            PharmacyBilling.objects
            .filter(**filters)
            .exclude(uhid="")
            .order_by("-bill_date")
            .first()
        )

        # Fallback without outlet filter if not found
        if not last_bill:
            last_bill = (
                PharmacyBilling.objects
                .exclude(uhid__isnull=True)
                .exclude(uhid="")
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

        full_name = ""
        if patient:
            sal = (patient.salutation or "").strip()
            fn  = (patient.firstName or "").strip()
            ln  = (patient.lastName or "").strip()
            if ln.lower() == fn.lower():
                ln = ""
            full_name = " ".join(f"{sal} {fn} {ln}".split()).strip()
        else:
            full_name = getattr(last_bill, "patientname", "") or ""

        inpatient_num = (
            getattr(last_bill, "inpatient_number", "")
            or getattr(patient, "inpatient_number", "")
            or ""
        )

        return Response({
            "success": True,
            "data": {
                # 🔹 Patient Details
                "uhid": last_bill.uhid,
                "patient_name": full_name,
                "inpatient_number": inpatient_num,
                "age": getattr(patient, "age", None) or getattr(last_bill, "age", None),
                "gender": getattr(patient, "gender", "") or "",
                "mobile": getattr(patient, "mobilePhone", "") or "",
                "city": getattr(patient, "city", "") or "",
                "blood_group": getattr(patient, "blood_group", "") or "",

                # 🔹 Bill Details
                "doctor_id": getattr(last_bill, "doctor_id", ""),
                "room_no": getattr(last_bill, "room_no", ""),
                "bill_type": getattr(last_bill, "bill_type", ""),
                "bill_no": getattr(last_bill, "bill_no", ""),
                "bill_date": last_bill.bill_date.isoformat() if last_bill.bill_date else None,
            }
        })
    except Exception as e:
        return Response({
            "success": False,
            "message": str(e)
        }, status=500)



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
        cashier_id = data.get("auth-user-id")
        counter_id = data.get("counter_id")
        if not counter_id and cashier_id:
            client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
            global_db = client["Global"]
            profile_col = global_db["backend_diagnostics_profile"]
            try:
                query_id = str(cashier_id)
                search_query = {"employeeId": {"$in": [query_id, int(query_id) if query_id.isdigit() else query_id]}}
            except:
                search_query = {"employeeId": str(cashier_id)}
            profile_data = profile_col.find_one(search_query)
            emp_cashcounter = profile_data.get("cashcounter") if profile_data else None
            if emp_cashcounter:
                counter_id = emp_cashcounter

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

        # Active shift validation
        is_valid, msg, active_shift = validate_active_shift(
            shiftno=shiftno,
            counter_id=counter_id,
            outlet_code=outlet_code,
            hospital_code=hospital_code,
            branch_code=branch_code
        )
        if not is_valid:
            return Response({
                "success": False,
                "error": msg
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

            # Recalculate shift totals
            try:
                from .cashcounter import recalculate_and_update_shift_details
                recalculate_and_update_shift_details(shiftno)
            except Exception as e:
                print("Error updating shift details in OP Pharmacy payment:", e)

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
        data = request.data

        hospital_code = data.get("auth-hospital-code")
        branch_code   = data.get("auth-branch-code")
        outlet_code   = data.get("auth-outlet-code")

        print("hospital_code:", hospital_code)
        print("branch_code:", branch_code)
        print("outlet_code:", outlet_code)

        if not hospital_code or not branch_code or not outlet_code:
            return Response(
                {"error": "hospital_code, branch_code, outlet_code required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # =========================================
        # 1. GET BILL DATA (Using PharmacyBilling model & serializer)
        # =========================================
        queryset = PharmacyBilling.objects.filter(
            hospital_code=hospital_code,
            branch_code=branch_code,
            outlet_code=outlet_code,
            billing_status__in=["Pending", "Processing"],
            is_ward_request=True
        ).order_by('-created_date')

        serialized_data = PharmacyBillingSerializer(queryset, many=True).data

        if not serialized_data:
            return Response(
                {"status": "success", "count": 0, "data": []},
                status=status.HTTP_200_OK
            )

        # =========================================
        # 2. BULK PREFETCHING: Eliminate N+1 loop queries
        # =========================================
        all_uhids = set()
        all_doc_ids = set()
        all_item_ids = set()
        bill_items_map = {}

        for bill in serialized_data:
            b_id = bill.get("Bill_id")
            uhid = bill.get("uhid")
            if uhid:
                all_uhids.add(str(uhid).strip())

            doc_id = bill.get("doctor_id")
            if doc_id:
                all_doc_ids.add(str(doc_id).strip())

            raw_particulars = bill.get("medicine_particulars", [])
            items = parse_medicine_particulars(raw_particulars)
            bill_items_map[b_id] = items

            for item in items:
                if isinstance(item, dict) and not item.get("is_deleted"):
                    iid = item.get("item_id")
                    if iid is not None:
                        try:
                            all_item_ids.add(int(iid))
                        except (ValueError, TypeError):
                            all_item_ids.add(str(iid).strip())

        # 3. Bulk fetch Patients
        patient_map = {}
        if all_uhids:
            try:
                for p in Patient.objects.filter(uhid__in=list(all_uhids)):
                    p_name = f"{p.firstName or ''} {p.lastName or ''}".strip()
                    patient_map[str(p.uhid).strip()] = {
                        "patient_name": p_name,
                        "address": p.permanent_address or "",
                        "mobile": p.mobilePhone or ""
                    }
            except Exception as e:
                print("Patient bulk prefetch error:", e)

        # 3b. Bulk fetch Admissions using Admission Django model
        admission_map = {}
        if all_uhids:
            try:
                admissions = Admission.objects.filter(
                    hospital_code=hospital_code,
                    branch_code=branch_code,
                    uhid__in=list(all_uhids),
                    is_admitted=True
                ).order_by('-admissionDateTime')

                for adm in admissions:
                    u = str(adm.uhid or "").strip()
                    if u in admission_map:
                        continue  # Already captured latest active admission

                    cust_type = str(adm.customer_type or "General").strip()
                    adv_list = adm.advance_payments or []
                    total_adv = 0.0

                    if isinstance(adv_list, list):
                        for ap in adv_list:
                            if isinstance(ap, dict) and (
                                ap.get("is_advanceActive") is not False
                                and str(ap.get("status", "")).strip().lower() not in ["cancelled", "refunded"]
                                and not ap.get("is_refund")
                            ):
                                try:
                                    total_adv += float(ap.get("ip_advance") or 0)
                                except (ValueError, TypeError):
                                    pass
                    elif isinstance(adv_list, dict):
                        if (
                            adv_list.get("is_advanceActive") is not False
                            and str(adv_list.get("status", "")).strip().lower() not in ["cancelled", "refunded"]
                            and not adv_list.get("is_refund")
                        ):
                            try:
                                total_adv += float(adv_list.get("ip_advance") or 0)
                            except (ValueError, TypeError):
                                pass

                    admission_map[u] = {
                        "customer_type": cust_type,
                        "is_insurance": cust_type.lower() == "insurance",
                        "insurance_company": adm.insurance_company or "",
                        "total_ip_advance": round(total_adv, 2),
                        "ipNumber": adm.ipNumber or ""
                    }
            except Exception as e:
                print("Admission model bulk prefetch error:", e)

        # 4. Bulk fetch Doctors from profile_collection (dbcollection.py)
        doctor_map = {}
        if all_doc_ids:
            try:
                for emp in profile_collection.find(
                    {"employeeId": {"$in": list(all_doc_ids)}},
                    {"employeeId": 1, "employeeName": 1, "_id": 0}
                ):
                    doctor_map[str(emp.get("employeeId")).strip()] = emp.get("employeeName")
            except Exception as e:
                print("profile_collection error:", e)

        # 5. Bulk fetch Pharmacy items & stock via common optimized function in dbcollection.py
        items_stock_data = get_pharmacy_items_with_stock(
            hospital_code=hospital_code,
            branch_code=branch_code,
            outlet_code=outlet_code,
            item_ids=all_item_ids
        )

        # =========================================
        # 6. IN-MEMORY ASSEMBLY (Instant)
        # =========================================
        final_data = []
        for bill in serialized_data:
            b_id = bill.get("Bill_id")
            uhid_str = str(bill.get("uhid") or "").strip()
            doc_id_str = str(bill.get("doctor_id") or "").strip()

            bill["patient_details"] = patient_map.get(uhid_str, {})
            bill["doctor_name"] = doctor_map.get(doc_id_str)

            adm_info = admission_map.get(uhid_str, {})
            bill["customer_type"] = adm_info.get("customer_type", bill.get("customer_type", "General"))
            bill["is_insurance"] = adm_info.get("is_insurance", False)
            bill["insurance_company"] = adm_info.get("insurance_company", "")
            bill["total_ip_advance"] = adm_info.get("total_ip_advance", 0.0)
            if not bill.get("inpatient_number") and adm_info.get("ipNumber"):
                bill["inpatient_number"] = adm_info.get("ipNumber")

            items = bill_items_map.get(b_id, [])
            mapped_items = []

            for item in items:
                if not isinstance(item, dict) or item.get("is_deleted"):
                    continue

                stock_info = resolve_medicine_stock_details(item, items_stock_data)
                mapped_items.append({
                    **item,
                    **stock_info
                })

            bill["medicine_items"] = mapped_items
            final_data.append(bill)

        return Response(
            {
                "status": "success",
                "count": len(final_data),
                "data": final_data
            },
            status=status.HTTP_200_OK
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response(
            {
                "error": "Something went wrong",
                "details": str(e)
            },
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
        hospital_code = data.get("auth-hospital-code")
        branch_code   = data.get("auth-branch-code")
        outlet_code   = data.get("auth-outlet-code")
        employee_id   = data.get("auth-user-id")

        print("hospital_code_finalize_bill:", hospital_code)
        print("branch_code_finalize_bill:",   branch_code)
        print("outlet_code_finalize_bill:",   outlet_code)

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

        # ── Optional: updated medicines + amounts from frontend ─────────────
        # Frontend sends these when the user edited quantities on the Pharmacy
        # page before clicking Bill.  If not provided, fall back to DB values.
        frontend_medicines              = data.get("medicine_particulars")    # list | None
        frontend_total                  = data.get("total_amount")            # float | None
        frontend_net_amount             = data.get("net_amount")              # float | None
        frontend_overall_discount_type  = data.get("overall_discount_type")
        frontend_overall_discount_value = data.get("overall_discount_value")
        frontend_overall_discount_amount= data.get("overall_discount_amount")

        # =====================================================
        # ✅ FETCH BILL
        # =====================================================
        bill = bill_collection.find_one({
            "Bill_id":       Bill_id,
            "hospital_code": hospital_code,
            "branch_code":   branch_code,
            "outlet_code":   outlet_code,
        })

        if not bill:
            return Response(
                {"error": "Bill not found"},
                status=404
            )

        # =====================================================
        # ✅ RESOLVE MEDICINES & TOTAL
        # =====================================================
        # Prefer frontend-supplied data (user may have edited qty).
        medicines_to_use = (
            frontend_medicines
            if frontend_medicines is not None
            else bill.get("medicine_particulars", [])
        )

        total_amount_to_use = (
            float(frontend_total)
            if frontend_total is not None
            else float(bill.get("total_amount", 0) or 0)
        )

        # =====================================================
        # ✅ IP ADVANCE CHECK
        # =====================================================
        inpatient_number = bill.get("inpatient_number")

        if inpatient_number:
            ip_advance = 0.0
            advance_check_blocked = False  # True = block billing (no active advance found)
            customer_type = "General"

            try:
                admission = Admission.objects.filter(
                    ipNumber=inpatient_number
                ).first()

                admission_doc = None
                if not admission:
                    admission_doc = mongo_db["hospital_admission"].find_one({
                        "ipNumber": inpatient_number,
                        "hospital_code": hospital_code
                    })

                if admission or admission_doc:
                    if admission:
                        customer_type = getattr(admission, "customer_type", "") or "General"
                        advance_payments = getattr(admission, "advance_payments", []) or []
                    else:
                        customer_type = admission_doc.get("customer_type", "General") or "General"
                        advance_payments = admission_doc.get("advance_payments", []) or []

                    if isinstance(advance_payments, list):
                        # Active advance entries not cancelled or refunded
                        valid_entries = [
                            ap for ap in advance_payments
                            if ap.get("is_advanceActive") is not False
                            and str(ap.get("status", "")).strip().lower() not in ["cancelled", "refunded"]
                            and not ap.get("is_refund")
                        ]

                        if not valid_entries:
                            advance_check_blocked = True
                        else:
                            ip_advance = sum(
                                float(ap.get("ip_advance", 0) or 0)
                                for ap in valid_entries
                            )

                    elif isinstance(advance_payments, dict):
                        if (
                            advance_payments.get("is_advanceActive") is not False
                            and str(advance_payments.get("status", "")).strip().lower() not in ["cancelled", "refunded"]
                            and not advance_payments.get("is_refund")
                        ):
                            ip_advance = float(advance_payments.get("ip_advance", 0) or 0)
                        else:
                            advance_check_blocked = True

                else:
                    advance_check_blocked = True

            except Exception as adm_err:
                print("Warning: could not fetch admission advance —", adm_err)
                ip_advance = None

            is_insurance_patient = str(customer_type).strip().lower() == "insurance"

            # ── Determine amount to check against IP Advance ─────────────────
            # Rule: For Insurance patients, ONLY consumable items are payable by patient from IP Advance.
            if is_insurance_patient:
                consumable_amount = 0.0
                for med in medicines_to_use:
                    if not isinstance(med, dict) or med.get("is_deleted"):
                        continue
                    m_is_consumable = med.get("is_consumable_items")
                    if m_is_consumable is None:
                        try:
                            m_id = int(med.get("item_id", 0))
                        except (ValueError, TypeError):
                            m_id = 0
                        p_item = mongo_db["hospital_pharmacyitem"].find_one(
                            {"item_id": m_id, "hospital_code": hospital_code},
                            {"is_consumable_items": 1}
                        )
                        m_is_consumable = bool(p_item.get("is_consumable_items", False)) if p_item else False

                    if m_is_consumable:
                        q = float(med.get("qty") or med.get("quantity") or 0)
                        p = float(med.get("price") or med.get("mrp") or med.get("rate") or 0)
                        consumable_amount += float(med.get("calculated_price") or (q * p))

                consumable_amount = round(consumable_amount, 2)
                amount_to_check = consumable_amount
            else:
                amount_to_check = total_amount_to_use

            # If Insurance patient has 0 consumable items, no IP advance deduction is needed
            if is_insurance_patient and amount_to_check == 0:
                pass
            else:
                if advance_check_blocked:
                    return Response(
                        {
                            "error": "No Active IP Advance found for this patient. Billing not allowed.",
                        },
                        status=400
                    )

                if ip_advance is not None and ip_advance > 0:
                    existing_billed_cursor = bill_collection.find({
                        "inpatient_number": inpatient_number,
                        "billing_status":   "Billed",
                        "is_deleted":       {"$ne": True},
                        "Bill_id":          {"$ne": Bill_id},
                    })
                    existing_total = 0.0
                    for b in existing_billed_cursor:
                        if is_insurance_patient:
                            past_meds = b.get("medicine_particulars", [])
                            for pm in past_meds:
                                if isinstance(pm, dict) and pm.get("is_consumable_items"):
                                    q = float(pm.get("qty") or pm.get("quantity") or 0)
                                    p = float(pm.get("price") or pm.get("mrp") or 0)
                                    existing_total += float(pm.get("calculated_price") or (q * p))
                        else:
                            existing_total += float(b.get("total_amount", 0) or 0)

                    cumulative_total = round(existing_total + amount_to_check, 2)

                    print(
                        f"IP Advance check | customer_type={customer_type} | is_insurance={is_insurance_patient} "
                        f"| ip_advance={ip_advance} | existing_billed={existing_total} "
                        f"| current_payable={amount_to_check} | cumulative={cumulative_total}"
                    )

                    if cumulative_total > ip_advance:
                        err_msg = "Payable Consumables Exceed IP Advance" if is_insurance_patient else "Billing Exceeds From IP Advance"
                        return Response(
                            {
                                "error":             err_msg,
                                "customer_type":      customer_type,
                                "is_insurance":       is_insurance_patient,
                                "ip_advance":         ip_advance,
                                "existing_billed":    existing_total,
                                "current_payable":    amount_to_check,
                                "cumulative_total":   cumulative_total,
                            },
                            status=400
                        )

                elif ip_advance == 0:
                    return Response(
                        {
                            "error": "IP Advance amount is 0. Billing not allowed.",
                        },
                        status=400
                    )

        # =====================================================
        # ✅ GENERATE BILL NO
        # =====================================================
        if not bill.get("bill_no"):

            fy          = get_financial_year()
            new_bill_no = get_last_oppharmacy_billno(fy)
            bill_date   = datetime.utcnow()

            bill_collection.update_one(
                {
                    "Bill_id":       Bill_id,
                    "hospital_code": hospital_code,
                    "branch_code":   branch_code,
                    "outlet_code":   outlet_code,
                },
                {
                    "$set": {
                        "bill_no":   new_bill_no,
                        "bill_date": bill_date,
                    }
                }
            )

        else:
            new_bill_no = bill.get("bill_no")
            bill_date   = bill.get("bill_date")

        # =====================================================
        # ✅ PREPARE MEDICINE HISTORY
        # =====================================================
        # Build a map of DB medicines so we can detect qty changes
        db_medicines_map = {
            (str(m.get("item_id")), str(m.get("batch_number", ""))): m
            for m in bill.get("medicine_particulars", [])
        }

        medicine_history = []
        now_ts = datetime.utcnow()

        for med in medicines_to_use:

            if med.get("is_deleted"):
                continue

            try:
                item_id = int(med.get("item_id", 0))
            except Exception:
                item_id = 0

            try:
                qty = float(
                    med.get("qty")
                    or med.get("quantity")
                    or 0
                )
            except Exception:
                qty = 0

            try:
                price = float(
                    med.get("price")
                    or med.get("mrp")
                    or med.get("rate")
                    or 0
                )
            except Exception:
                price = 0

            calculated_price = round(qty * price, 2)

            # ── Carry forward existing edit_history for this item ─────────
            edit_history = list(med.get("edit_history") or [])

            # ── FIX 3: Only record qty change if something actually changed ─
            # Do NOT add any entry just because billing happened.
            # edit_history inside medicine_particulars = changes only.
            db_key = (str(item_id), str(med.get("batch_number", "")))
            db_med = db_medicines_map.get(db_key)
            if db_med is not None:
                db_qty = float(
                    db_med.get("qty")
                    or db_med.get("quantity")
                    or 0
                )
                if db_qty != qty:
                    # Only then record — qty was actually changed by the user
                    diff = qty - db_qty
                    edit_history.append({
                        "action":        "qty_changed_at_billing",
                        "old_qty":        db_qty,
                        "new_qty":        qty,
                        "blocked_change": diff,
                        "timestamp":      now_ts.isoformat(),
                        "edited_by":      employee_id,
                    })

            bn_val = str(med.get("batch_number") or med.get("batch_no") or "").strip()
            if not bn_val or bn_val.lower() == "none" or bn_val.lower() == "null" or bn_val == "N/A":
                try:
                    stk = bill_collection.database["hospital_pharmacystock"].find_one({"item_id": item_id})
                    if stk and stk.get("batch_number"):
                        bn_val = str(stk["batch_number"]).strip()
                except Exception:
                    pass

            med_is_consumable = med.get("is_consumable_items")
            if med_is_consumable is None:
                p_item = mongo_db["hospital_pharmacyitem"].find_one(
                    {"item_id": item_id, "hospital_code": hospital_code},
                    {"is_consumable_items": 1}
                )
                med_is_consumable = bool(p_item.get("is_consumable_items", False)) if p_item else False
            else:
                med_is_consumable = bool(med_is_consumable)

            med_entry = {
                "item_id":          item_id,
                "item_name":        med.get("item_name") or med.get("name"),
                "batch_number":     bn_val,
                "quantity":         qty,
                "price":            price,
                "calculated_price": calculated_price,
                "discount":         med.get("discount", 0),
                "tax":              med.get("tax", 0),
                "mrp":              med.get("mrp"),
                "expiry_date":      med.get("expiry_date"),
                "is_consumable_items": med_is_consumable,
                "action":           "finalized",
                "edited_by":        employee_id,
                "edited_at":        now_ts,
            }

            # ✅ FIX 3: Only store edit_history inside medicine_particulars
            # if there were actual changes (qty edited before billing).
            # If nothing changed — no edit_history key stored at all.
            if edit_history:
                med_entry["edit_history"] = edit_history

            medicine_history.append(med_entry)

        # =====================================================
        # ✅ STOCK UPDATE
        # =====================================================
        for med in medicines_to_use:

            if med.get("is_deleted"):
                continue

            try:
                item_id = int(med.get("item_id"))
                batch   = str(med.get("batch_number")).strip()
                qty     = float(
                    med.get("qty")
                    or med.get("quantity")
                    or 0
                )

            except Exception as e:
                print("Skipping invalid med:", med, "Error:", e)
                continue

            result = stock_collection.update_one(
                {
                    "item_id":       item_id,
                    "batch_number":  batch,
                    "hospital_code": hospital_code,
                    "branch_code":   branch_code,
                    "outlet_code":   outlet_code,
                },
                {
                    "$inc": {
                        "blocked_quantity": qty
                    }
                },
                upsert=False,
            )

            print("STOCK FILTER:", {
                "item_id":       item_id,
                "batch_number":  batch,
                "hospital_code": hospital_code,
                "branch_code":   branch_code,
                "outlet_code":   outlet_code,
            })

            print(
                "MATCHED:",   result.matched_count,
                "MODIFIED:",  result.modified_count,
            )

        # =====================================================
        # ✅ UPDATE BILL
        # =====================================================
        set_payload = {

            "billing_status":       "Billed",

            # ✅ NEW: mark as dispatched when billing is finalised
            "is_dispatched":        True,

            "lastmodified_date":    now_ts,

            # ✅ Store updated medicine list (with edit_history per item)
            "medicine_particulars": medicine_history,
        }

        # Persist updated total / net amounts if frontend sent them
        if frontend_total is not None:
            set_payload["total_amount"] = total_amount_to_use
        if frontend_net_amount is not None:
            set_payload["net_amount"] = float(frontend_net_amount)
        if frontend_overall_discount_type is not None:
            set_payload["overall_discount_type"] = frontend_overall_discount_type
        if frontend_overall_discount_value is not None:
            set_payload["overall_discount_value"] = float(frontend_overall_discount_value)
        if frontend_overall_discount_amount is not None:
            set_payload["overall_discount_amount"] = float(frontend_overall_discount_amount)

        bill_collection.update_one(
            {
                "Bill_id":       Bill_id,
                "hospital_code": hospital_code,
                "branch_code":   branch_code,
                "outlet_code":   outlet_code,
            },
            {
                "$set": set_payload,
            }
        )

        # =====================================================
        # ✅ RESPONSE
        # =====================================================
        return Response({

            "status":   "success",

            "message":  "Bill finalized, dispatched & stock updated",

            "bill_no":  new_bill_no,

            "bill_date": bill_date,

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
            if first_name and last_name:
                if (
                    first_name.lower() == last_name.lower()
                    or first_name.lower().endswith(last_name.lower())
                    or first_name.lower().replace(" ", "") == last_name.lower().replace(" ", "")
                ):
                    last_name = ""
                elif last_name.lower().startswith(first_name.lower()):
                    first_name = ""
            full_name = " ".join(filter(None, [salutation, first_name, last_name])).strip()
            words = full_name.split()
            if len(words) >= 2 and len(words) % 2 == 0:
                half = len(words) // 2
                if [w.lower() for w in words[:half]] == [w.lower() for w in words[half:]]:
                    words = words[:half]
            clean_words = []
            for idx, w in enumerate(words):
                if idx > 0 and len(w) > 1 and w.lower() == words[idx - 1].lower():
                    continue
                clean_words.append(w)
            patient_map[pd["uhid"]] = " ".join(clean_words).strip()

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
    # ✅ Query Parameters: Date, Search, Bill Type, Limit
    # =========================================================
    from_date_str = request.GET.get("from_date") or request.query_params.get("from_date")
    to_date_str   = request.GET.get("to_date")   or request.query_params.get("to_date")
    search_by     = (request.GET.get("search_by") or request.query_params.get("search_by") or "").strip()
    search_value  = (request.GET.get("search_value") or request.query_params.get("search_value") or "").strip()
    bill_type_param = request.GET.get("bill_type") or request.query_params.get("bill_type")
    limit_param   = request.GET.get("limit") or request.query_params.get("limit")

    try:
        limit = min(int(limit_param), 2000) if limit_param else 1000
    except (ValueError, TypeError):
        limit = 1000

    from_dt = None
    to_dt   = None
    if from_date_str:
        try:
            from django.utils.timezone import make_aware
            from_dt = make_aware(datetime.strptime(from_date_str.strip(), "%Y-%m-%d"))
        except Exception:
            try:
                from_dt = datetime.strptime(from_date_str.strip(), "%Y-%m-%d")
            except Exception:
                pass

    if to_date_str:
        try:
            from django.utils.timezone import make_aware
            to_dt = make_aware(datetime.strptime(to_date_str.strip(), "%Y-%m-%d").replace(hour=23, minute=59, second=59))
        except Exception:
            try:
                to_dt = datetime.strptime(to_date_str.strip(), "%Y-%m-%d").replace(hour=23, minute=59, second=59)
            except Exception:
                pass

    # =========================================================
    # ✅ Django Bills Query
    # =========================================================
    bill_filters = {
        "billing_status__in": ["Billed", "Paid", "Processing", "deleted"],
        "hospital_code": hospital_code,
        "branch_code": branch_code,
        "outlet_code": matched_outlet,
    }

    if bill_type_param and bill_type_param != "ALL":
        try:
            bill_filters["bill_type"] = int(bill_type_param)
        except (ValueError, TypeError):
            bill_filters["bill_type__in"] = allowed_bill_types
    else:
        bill_filters["bill_type__in"] = allowed_bill_types

    if from_dt and to_dt:
        bill_filters["bill_date__range"] = (from_dt, to_dt)
    elif from_dt:
        bill_filters["bill_date__gte"] = from_dt
    elif to_dt:
        bill_filters["bill_date__lte"] = to_dt

    extra_filter = None
    if search_value:
        if search_by == "bill_no":
            bill_filters["bill_no__icontains"] = search_value
        elif search_by == "uhid":
            bill_filters["uhid__icontains"] = search_value
        elif search_by == "patient_name":
            matching_uhids = list(
                Patient.objects.filter(
                    Q(firstName__icontains=search_value) | Q(lastName__icontains=search_value)
                ).values_list("uhid", flat=True)[:300]
            )
            if matching_uhids:
                extra_filter = Q(patientname__icontains=search_value) | Q(uhid__in=matching_uhids)
            else:
                bill_filters["patientname__icontains"] = search_value
        else:
            bill_filters["bill_no__icontains"] = search_value

    bills_qs = PharmacyBilling.objects.filter(**bill_filters)
    if extra_filter:
        bills_qs = bills_qs.filter(extra_filter)
    bills_qs = bills_qs.order_by("-bill_date")

    bills = list(bills_qs[:limit])

    # =========================================================
    # ✅ Patient Mapping (fast values() lookup)
    # =========================================================
    uhids = list(set([bill.uhid for bill in bills if bill.uhid]))
    patient_map = {}
    if uhids:
        patients = Patient.objects.filter(uhid__in=uhids).values("uhid", "salutation", "firstName", "lastName")
        for p in patients:
            sal = (p.get("salutation") or "").strip()
            fn  = (p.get("firstName") or "").strip()
            ln  = (p.get("lastName") or "").strip()
            if ln.lower() == fn.lower():
                ln = ""
            full_name = f"{sal} {fn} {ln}".strip()
            patient_map[p["uhid"]] = " ".join(full_name.split())

    # =========================================================
    # ✅ Doctor Mapping
    # =========================================================
    doctor_ids = list(set([str(bill.doctor_id).strip() for bill in bills if bill.doctor_id]))
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
    # ✅ Employee / Creator Mapping
    # =========================================================
    creator_ids = list(set([
        str(bill.created_by).strip() for bill in bills if bill.created_by
    ] + [
        str(bill.cashier_id).strip() for bill in bills if bill.cashier_id
    ]))

    employee_map = {}
    if creator_ids:
        search_ids = []
        for cid in creator_ids:
            search_ids.append(cid)
            if cid.isdigit():
                search_ids.append(int(cid))

        creator_cursor = profile_collection.find(
            {"employeeId": {"$in": search_ids}},
            {"employeeId": 1, "employeeName": 1}
        )
        for doc in creator_cursor:
            emp_n = doc.get("employeeName", "")
            if emp_n:
                employee_map[str(doc["employeeId"])] = emp_n

    # =========================================================
    # ✅ Fallback for bills missing medicine_particulars in Django
    # =========================================================
    missing_med_bill_ids = [b.Bill_id for b in bills if not b.medicine_particulars]
    mongo_map = {}
    if missing_med_bill_ids:
        mongo_bills = oppharmacy_collection.find(
            {
                "Bill_id": {"$in": missing_med_bill_ids},
                "hospital_code": hospital_code,
                "branch_code": branch_code,
                "outlet_code": matched_outlet
            },
            {
                "Bill_id": 1,
                "medicine_particulars": 1,
            }
        )
        mongo_map = {m["Bill_id"]: m.get("medicine_particulars", []) for m in mongo_bills}

    # =========================================================
    # ✅ Fast Float Conversion Helper
    # =========================================================
    def to_num(val):
        if val is None:
            return 0.0
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, (Decimal, Decimal128)):
            return float(val)
        try:
            return float(str(val).strip())
        except (ValueError, TypeError):
            return 0.0

    # =========================================================
    # ✅ Build Bills Data (Fast direct serialization)
    # =========================================================
    data = []

    for bill in bills:
        # Direct field dictionary (100x faster than DRF ModelSerializer in a loop)
        serialized = {}
        for f in bill._meta.fields:
            val = getattr(bill, f.name)
            if isinstance(val, (datetime, date)):
                serialized[f.name] = val.isoformat()
            elif isinstance(val, (Decimal, Decimal128)):
                serialized[f.name] = float(val)
            else:
                serialized[f.name] = val

        p_name = patient_map.get(bill.uhid, "") or getattr(bill, "patientname", "") or ""
        serialized["patient_name"]   = p_name
        serialized["doctor_name"]    = doctor_map.get(str(bill.doctor_id), "")
        serialized["bill_type_name"] = billtype_map.get(int(bill.bill_type) if bill.bill_type is not None else 0, "")

        created_val  = str(bill.created_by or bill.cashier_id or "").strip()
        matched_user = employee_map.get(created_val) or created_val
        serialized["employee_name"]   = matched_user
        serialized["created_by_name"] = matched_user

        medicine_list = bill.medicine_particulars or mongo_map.get(bill.Bill_id, []) or []
        updated_items = []

        for item in medicine_list:
            it = dict(item)
            it["CGST_Percentage"] = to_num(it.get("CGST_Percentage", 0))
            it["SGST_Percentage"] = to_num(it.get("SGST_Percentage", 0))
            it["CGST_Amt"]        = to_num(it.get("CGST_Amt", 0))
            it["SGST_Amt"]        = to_num(it.get("SGST_Amt", 0))
            it["price"]           = to_num(it.get("price", 0))
            it["calculated_price"] = to_num(it.get("calculated_price", 0))
            it["edit_history"]    = it.get("edit_history", [])
            updated_items.append(it)

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


@api_view(["GET"])
# @permission_classes([HasRoleAndDataPermission])
def get_doctor_prescriptions(request):
    """
    Retrieve doctor consultation records with prescription_details for pharmacy billing.
    Returns patient demographics, doctor name, prescribed medicines list, and pharmacy billing status.
    """
    try:
        uhid_filter = request.query_params.get("uhid")
        search_filter = (request.query_params.get("search") or "").strip().lower()
        from_date_str = request.query_params.get("from_date")
        to_date_str = request.query_params.get("to_date")

        from hospital.Views.OPEMR.models import OPDoctorConsultation
        from hospital.models import Patient
        from hospital.Views.dbcollection import get_employee_name_by_id
        from pymongo import MongoClient
        from django.utils import timezone

        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        hms_mongo = client["HMS"]
        pb_col = hms_mongo["hospital_pharmacybilling"]

        qs = OPDoctorConsultation.objects.all()
        if uhid_filter:
            qs = qs.filter(uhid=uhid_filter)

        consultations = list(qs.order_by("-created_date", "-date"))

        # Full stock detail map for prescription enrichment: item_id -> {batch, price, mrp, expiry}
        stock_detail_map = {}
        try:
            for s in hms_mongo["hospital_pharmacystock"].find():
                iid = s.get("item_id")
                if iid is None:
                    continue
                detail = {
                    "batch_number": str(s.get("batch_number") or "").strip(),
                    "price":        float(s.get("price") or s.get("mrp") or 0),
                    "mrp":          float(s.get("mrp") or s.get("price") or 0),
                    "expiry_date":  str(s.get("expiry_date") or "").strip(),
                    "hsn_code":     str(s.get("hsn_code") or "").strip(),
                    "cgst_rate":    float(s.get("CGST_Percentage") or s.get("cgst_rate") or 0),
                    "sgst_rate":    float(s.get("SGST_Percentage") or s.get("sgst_rate") or 0),
                    "cgst_amount":  float(s.get("CGST_Amt") or s.get("cgst_amount") or 0),
                    "sgst_amount":  float(s.get("SGST_Amt") or s.get("sgst_amount") or 0),
                }
                if iid not in stock_detail_map:
                    stock_detail_map[iid] = detail
                try:
                    if int(iid) not in stock_detail_map:
                        stock_detail_map[int(iid)] = detail
                except Exception:
                    pass
            for v in hms_mongo["hospital_velavan_stock"].find():
                iid = v.get("item_id")
                if iid is None:
                    continue
                detail = {
                    "batch_number": str(v.get("batch_no") or v.get("batch_number") or "").strip(),
                    "price":        float(v.get("price") or v.get("mrp") or 0),
                    "mrp":          float(v.get("mrp") or v.get("price") or 0),
                    "expiry_date":  str(v.get("expiry_date") or "").strip(),
                    "hsn_code":     str(v.get("hsn_code") or "").strip(),
                    "cgst_rate":    float(v.get("CGST_Percentage") or v.get("cgst_rate") or 0),
                    "sgst_rate":    float(v.get("SGST_Percentage") or v.get("sgst_rate") or 0),
                    "cgst_amount":  float(v.get("CGST_Amt") or v.get("cgst_amount") or 0),
                    "sgst_amount":  float(v.get("SGST_Amt") or v.get("sgst_amount") or 0),
                }
                if iid not in stock_detail_map:
                    stock_detail_map[iid] = detail
                try:
                    if int(iid) not in stock_detail_map:
                        stock_detail_map[int(iid)] = detail
                except Exception:
                    pass
        except Exception:
            pass

        results = []
        for c in consultations:
            raw_presc_items = getattr(c, "prescription_details", []) or []
            if not isinstance(raw_presc_items, list) or len(raw_presc_items) == 0:
                continue

            presc_items = []
            for it in raw_presc_items:
                if not isinstance(it, dict):
                    continue
                it_copy = dict(it)
                it_id = it_copy.get("item_id")

                # Look up full stock details for this item
                stock_info = (
                    stock_detail_map.get(it_id)
                    or stock_detail_map.get(str(it_id) if it_id is not None else "")
                    or {}
                )

                # ── Batch number ──
                it_bn = str(it_copy.get("batch_number") or it_copy.get("batch_no") or "").strip()
                if not it_bn or it_bn.lower() in ("none", "null", "n/a", ""):
                    it_bn = stock_info.get("batch_number", "")
                it_copy["batch_number"] = it_bn
                it_copy["batch_no"] = it_bn

                # ── Price / MRP ── (fill from stock if prescription item has no price)
                if not it_copy.get("price") and not it_copy.get("mrp"):
                    it_copy["price"]    = stock_info.get("price", 0)
                    it_copy["mrp"]      = stock_info.get("mrp", 0)
                else:
                    it_copy.setdefault("price", stock_info.get("price", 0))
                    it_copy.setdefault("mrp",   stock_info.get("mrp", 0))

                # ── Expiry date ──
                if not it_copy.get("expiry_date"):
                    it_copy["expiry_date"] = stock_info.get("expiry_date", "")

                # ── HSN / Tax rates ──
                it_copy.setdefault("hsn_code",    stock_info.get("hsn_code", ""))
                it_copy.setdefault("cgst_rate",   stock_info.get("cgst_rate", 0))
                it_copy.setdefault("sgst_rate",   stock_info.get("sgst_rate", 0))
                it_copy.setdefault("cgst_amount", stock_info.get("cgst_amount", 0))
                it_copy.setdefault("sgst_amount", stock_info.get("sgst_amount", 0))

                presc_items.append(it_copy)

            c_uhid = getattr(c, "uhid", "") or ""
            c_created = getattr(c, "created_date", None) or getattr(c, "date", None)

            # Date filtering if provided
            if c_created:
                c_date_val = c_created.date() if hasattr(c_created, "date") else None
                if from_date_str and c_date_val:
                    try:
                        from_d = datetime.strptime(from_date_str, "%Y-%m-%d").date()
                        if c_date_val < from_d:
                            continue
                    except Exception:
                        pass
                if to_date_str and c_date_val:
                    try:
                        to_d = datetime.strptime(to_date_str, "%Y-%m-%d").date()
                        if c_date_val > to_d:
                            continue
                    except Exception:
                        pass

            # Patient details
            p_obj = Patient.objects.filter(uhid=c_uhid).first() if c_uhid else None
            if p_obj:
                p_name = f"{p_obj.salutation or ''} {p_obj.firstName or ''} {p_obj.lastName or ''}".strip()
                p_age = p_obj.age or ""
                p_gender = p_obj.gender or ""
                p_mobile = p_obj.mobilePhone or ""
                p_address = p_obj.permanent_address or p_obj.city or ""
            else:
                p_name = f"Patient ({c_uhid})"
                p_age = ""
                p_gender = ""
                p_mobile = ""
                p_address = ""

            # Search filter matching
            if search_filter:
                match_uhid = search_filter in c_uhid.lower()
                match_name = search_filter in p_name.lower()
                if not (match_uhid or match_name):
                    continue

            # Doctor name
            doc_id = getattr(c, "doctor_id", "") or getattr(c, "created_by", "") or ""
            doc_name = get_employee_name_by_id(doc_id)
            if not doc_name or doc_name == "Unknown":
                doc_name = f"Dr. ({doc_id})" if doc_id else "Doctor"
            elif not doc_name.lower().startswith("dr"):
                doc_name = f"Dr. {doc_name}"

            # Check if matching bill exists in pharmacy billing
            billing_status = "Pending"
            bill_no = None
            bill_id = None
            if c_uhid:
                matching_bill = pb_col.find_one({"uhid": c_uhid}, sort=[("created_date", -1)])
                if matching_bill:
                    billing_status = matching_bill.get("billing_status") or "Billed"
                    bill_no = matching_bill.get("bill_no")
                    bill_id = matching_bill.get("Bill_id")

            # Localize timestamp to Asia/Kolkata
            created_str = ""
            if c_created:
                try:
                    if timezone.is_naive(c_created):
                        c_created = timezone.make_aware(c_created, timezone.utc)
                    created_str = timezone.localtime(c_created).isoformat()
                except Exception:
                    created_str = c_created.isoformat() if hasattr(c_created, "isoformat") else str(c_created)

            results.append({
                "id": str(getattr(c, "_id", "") or getattr(c, "pk", "") or ""),
                "_id": str(getattr(c, "_id", "") or getattr(c, "pk", "") or ""),
                "uhid": c_uhid,
                "patient_name": p_name,
                "age": p_age,
                "gender": p_gender,
                "mobile": p_mobile,
                "address": p_address,
                "doctor_id": doc_id,
                "doctor_name": doc_name,
                "created_date": created_str,
                "status": getattr(c, "status", "Completed") or "Completed",
                "finding": getattr(c, "finding", "") or "",
                "prescription_details": presc_items,
                "items_count": len(presc_items),
                "billing_status": billing_status,
                "bill_no": bill_no,
                "Bill_id": bill_id
            })

        return Response({"success": True, "data": results}, status=status.HTTP_200_OK)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

