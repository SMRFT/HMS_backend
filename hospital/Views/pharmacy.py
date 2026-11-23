from django.http import JsonResponse
from pymongo import MongoClient
import os
import json
import re
import pytz
from datetime import datetime, date, timedelta
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
from rest_framework.permissions import AllowAny

# Models & Serializers
from ..models import Patient, PharmacyStock, PharmacyBilling, PharmacyItem, Admission, InsuranceProvider,Admission
from ..serializers import PharmacyBillingSerializer
from .cashcounter import validate_active_shift
from .dbcollection import (
    profile_collection, get_pharmacy_items_with_stock, resolve_medicine_stock_details,
    get_employee_name_by_id, resolve_doctor_id, get_doctor_name_by_id,
    admission_collection, pharmacy_billing_collection,
    hospital_insuranceprovider, get_insurance_provider_by_patient, get_insurance_company_name,
    get_room_details, hospital_room
)
from ..counter_service import get_next_pharmacy_bill_no, get_next_sequence_value

# MongoDB Configuration
from dotenv import load_dotenv
load_dotenv(override=True)
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


def to_utc_iso(dt_val):
    if not dt_val:
        return ""
    if isinstance(dt_val, datetime):
        if dt_val.tzinfo is None:
            return dt_val.isoformat() + "Z"
        return dt_val.astimezone(timezone.utc).isoformat()
    s = str(dt_val).strip()
    if s and "T" in s and not s.endswith("Z") and "+" not in s:
        return s + "Z"
    return s





def resolve_request_outlet(request, data=None):
    if data is None:
        data = getattr(request, "data", {}) if isinstance(getattr(request, "data", None), dict) else {}

    # 1. Primary: Active outlet from headers, GET query param, or body
    active_outlet = (
        (request.headers.get("Outlet-Code") if hasattr(request, "headers") else None)
        or (request.headers.get("outlet-code") if hasattr(request, "headers") else None)
        or (request.META.get("HTTP_OUTLET_CODE") if hasattr(request, "META") else None)
        or (request.META.get("HTTP_AUTH_OUTLET_CODE") if hasattr(request, "META") else None)
        or (request.GET.get("outlet_code") if hasattr(request, "GET") else None)
        or (data.get("outlet_code") if isinstance(data, dict) else None)
    )

    if active_outlet and str(active_outlet).strip().lower() not in ("null", "undefined", "none", "", "all"):
        return str(active_outlet).strip()

    # 2. Fallback: auth-outlet-code from token
    auth_outlet = (
        data.get("auth-outlet-code") if isinstance(data, dict) else None
    ) or (
        request.data.get("auth-outlet-code") if hasattr(request, "data") and isinstance(request.data, dict) else None
    )

    if isinstance(auth_outlet, (list, tuple)):
        if "OLET002" in auth_outlet:
            return "OLET002"
        elif "OLET001" in auth_outlet:
            return "OLET001"
        return auth_outlet[0] if auth_outlet else None
    return auth_outlet


@api_view(["POST","GET"])
@permission_classes([HasRoleAndDataPermission])
def get_pharmacy_stock(request):
    try:
        data = request.data if isinstance(getattr(request, "data", None), dict) else {}
        hospital_code = (
            data.get("auth-hospital-code")
            or (request.headers.get("Hospital-Code") if hasattr(request, "headers") else None)
            or (request.headers.get("hospital-code") if hasattr(request, "headers") else None)
            or (request.GET.get("hospital_code") if hasattr(request, "GET") else None)
            or "SH001"
        )
        branch_code = (
            data.get("auth-branch-code")
            or (request.headers.get("Branch-Code") if hasattr(request, "headers") else None)
            or (request.headers.get("branch-code") if hasattr(request, "headers") else None)
            or (request.GET.get("branch_code") if hasattr(request, "GET") else None)
            or "SHB001"
        )
        outlet_code = resolve_request_outlet(request, data) or (request.headers.get("Outlet-Code") if hasattr(request, "headers") else None) or "OLET001"
        if isinstance(outlet_code, (list, tuple)):
            if len(outlet_code) == 1:
                outlet_code = outlet_code[0]
            elif outlet_code:
                outlet_code = {"$in": list(outlet_code)}
            else:
                outlet_code = None

        search_query = (
            request.GET.get("search")
            or request.GET.get("q")
            or data.get("search")
            or ""
        ).strip()

        if not hospital_code or not branch_code or not outlet_code:
            return JsonResponse({
                "success": False,
                "message": "Missing hospital_code / branch_code / outlet_code"
            }, status=400)

        # ✅ Mongo connection
        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        mongo_db = client["HMS"]

        # ✅ MATCH STOCK DYNAMICALLY
        match_stage = {}
        if hospital_code:
            match_stage["hospital_code"] = hospital_code
        if branch_code:
            match_stage["branch_code"] = branch_code
        if outlet_code:
            match_stage["outlet_code"] = outlet_code

        # Filter to active batches with total_stock > 0 only when no search query is provided and zero stock is not requested
        include_zero_stock = request.GET.get("include_zero_stock") or data.get("include_zero_stock")
        is_include_zero = include_zero_stock and str(include_zero_stock).lower() in ("true", "1")
        if not is_include_zero and not search_query:
            match_stage["total_stock"] = {"$gt": 0}

        # Fast search filter: if search query is provided, find matching item_ids first
        # Prioritizing items whose names start with the search query ("starting letter filter")
        if search_query:
            import re
            escaped_q = re.escape(search_query)
            search_items = list(mongo_db.hospital_pharmacyitem.find(
                {
                    "hospital_code": hospital_code,
                    "branch_code": branch_code,
                    "item_name": re.compile(f"^{escaped_q}", re.IGNORECASE),
                    "is_active": True,
                    "is_blocked": False
                },
                {"item_id": 1, "item_name": 1, "_id": 0}
            ).sort("item_name", 1).limit(100))

            # Fallback if no starting-letter matches: match word boundary
            if not search_items:
                search_items = list(mongo_db.hospital_pharmacyitem.find(
                    {
                        "hospital_code": hospital_code,
                        "branch_code": branch_code,
                        "item_name": re.compile(f"(?:^|\\s){escaped_q}", re.IGNORECASE),
                        "is_active": True,
                        "is_blocked": False
                    },
                    {"item_id": 1, "item_name": 1, "_id": 0}
                ).sort("item_name", 1).limit(60))

            # Fallback: substring match anywhere
            if not search_items:
                search_items = list(mongo_db.hospital_pharmacyitem.find(
                    {
                        "hospital_code": hospital_code,
                        "branch_code": branch_code,
                        "item_name": re.compile(escaped_q, re.IGNORECASE),
                        "is_active": True,
                        "is_blocked": False
                    },
                    {"item_id": 1, "item_name": 1, "_id": 0}
                ).sort("item_name", 1).limit(60))

            matching_ids = [it["item_id"] for it in search_items if "item_id" in it]
            if not matching_ids:
                return JsonResponse({
                    "success": True,
                    "count": 0,
                    "data": []
                })
            match_stage["item_id"] = {"$in": matching_ids}

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
                            {"$gt": [{"$ifNull": ["$mrp", 0]}, 0]},
                            "$mrp",
                            {"$ifNull": ["$Selling_Price", 0]}
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

        if search_query:
            sq = search_query.upper()
            result.sort(key=lambda x: (
                0 if str(x.get("item_name") or "").upper().startswith(sq) else 1,
                str(x.get("item_name") or "").upper()
            ))

        # Enrich each stock item with expiry calculation (within 10 days of expiry)
        now_dt = datetime.now()
        import calendar
        for item in result:
            exp_str = item.get("expiry_date")
            is_exp = False
            is_soon = False
            days_left = None
            if exp_str:
                try:
                    exp_dt = None
                    if isinstance(exp_str, datetime):
                        exp_dt = exp_str.replace(tzinfo=None)
                    elif isinstance(exp_str, str):
                        clean_exp = exp_str.strip().split("T")[0]
                        for sep in ["/", "-"]:
                            if sep in clean_exp:
                                parts = clean_exp.split(sep)
                                if len(parts) >= 3:
                                    if len(parts[0]) == 4:
                                        exp_dt = datetime(int(parts[0]), int(parts[1]), int(parts[2]))
                                    else:
                                        exp_dt = datetime(int(parts[2]), int(parts[1]), int(parts[0]))
                                    break
                                elif len(parts) == 2:
                                    if len(parts[0]) == 4:
                                        yr, mo = int(parts[0]), int(parts[1])
                                    else:
                                        mo, yr = int(parts[0]), int(parts[1])
                                    last_day = calendar.monthrange(yr, mo)[1]
                                    exp_dt = datetime(yr, mo, last_day)
                                    break
                        if not exp_dt:
                            try:
                                exp_dt = datetime.fromisoformat(exp_str.replace("Z", "+00:00")).replace(tzinfo=None)
                            except Exception:
                                pass
                    if exp_dt:
                        diff = (exp_dt.date() - now_dt.date()).days
                        days_left = diff
                        if diff < 0:
                            is_exp = True
                        elif diff <= 10:
                            is_soon = True
                except Exception:
                    pass
            item["days_to_expiry"] = days_left
            item["is_expired"] = is_exp
            item["is_expiring_soon"] = is_soon

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
    if not medicines:
        return clean

    for med in medicines:
        if not med:
            continue

        try:
            item_id_val = int(med.get("item_id"))
        except (ValueError, TypeError):
            continue

        bn_val = str(med.get("batch_number") or med.get("batch_no") or "").strip()
        if not bn_val or bn_val.lower() in ["none", "null", "n/a", ""]:
            # On-demand lookup for ONLY this specific item_id
            st = stock_collection.find_one(
                {"item_id": item_id_val, "batch_number": {"$exists": True, "$ne": ""}},
                {"batch_number": 1}
            )
            if st and st.get("batch_number"):
                bn_val = str(st["batch_number"]).strip()
            else:
                v_st = mongo_db["hospital_velavan_stock"].find_one(
                    {"item_id": item_id_val, "batch_no": {"$exists": True, "$ne": ""}},
                    {"batch_no": 1}
                )
                if v_st and v_st.get("batch_no"):
                    bn_val = str(v_st["batch_no"]).strip()
                else:
                    bn_val = ""

        med_is_consumable = med.get("is_consumable_items")
        if med_is_consumable is None and item_id_val:
            try:
                p_it = mongo_db["hospital_pharmacyitem"].find_one(
                    {"item_id": item_id_val},
                    {"is_consumable_items": 1}
                )
                if not p_it and str(item_id_val).isdigit():
                    p_it = mongo_db["hospital_pharmacyitem"].find_one(
                        {"item_id": int(item_id_val)},
                        {"is_consumable_items": 1}
                    )
                if p_it:
                    med_is_consumable = bool(p_it.get("is_consumable_items", False))
            except Exception:
                pass
        if med_is_consumable is None:
            med_is_consumable = False
        else:
            med_is_consumable = bool(med_is_consumable)

        # Resolve item_name, expiry_date, hsn_code
        item_name_val = str(med.get("item_name") or med.get("name") or med.get("medicine_name") or "").strip()
        expiry_val = str(med.get("expiry_date") or med.get("expiry") or "").strip()
        hsn_val = str(med.get("hsn_code") or med.get("hsn") or "").strip()

        # CGST / SGST rates
        cgst_pct = 0.0
        for k in ("CGST_Percentage", "cgst_percentage", "cgst_rate", "cgst_pct", "cgst"):
            if med.get(k) is not None and str(med.get(k)).strip() != "":
                try:
                    cgst_pct = float(med.get(k))
                    break
                except Exception:
                    pass

        sgst_pct = 0.0
        for k in ("SGST_Percentage", "sgst_percentage", "sgst_rate", "sgst_pct", "sgst"):
            if med.get(k) is not None and str(med.get(k)).strip() != "":
                try:
                    sgst_pct = float(med.get(k))
                    break
                except Exception:
                    pass

        # If any of item_name, expiry, hsn, or GST rates are missing, lookup from stock / item collection
        if not item_name_val or not expiry_val or (cgst_pct == 0.0 and sgst_pct == 0.0) or not hsn_val:
            try:
                stk_q = {"item_id": item_id_val}
                if bn_val:
                    stk_q["batch_number"] = bn_val
                stk_doc = stock_collection.find_one(stk_q)
                if not stk_doc and str(item_id_val).isdigit():
                    stk_q["item_id"] = int(item_id_val)
                    stk_doc = stock_collection.find_one(stk_q)

                if stk_doc:
                    if not item_name_val:
                        item_name_val = str(stk_doc.get("item_name") or "").strip()
                    if not expiry_val and stk_doc.get("expiry_date"):
                        exp_d = stk_doc.get("expiry_date")
                        if isinstance(exp_d, (datetime, date)):
                            expiry_val = exp_d.strftime("%Y-%m-%d")
                        else:
                            expiry_val = str(exp_d)
                    if not hsn_val:
                        hsn_val = str(stk_doc.get("hsn_code") or stk_doc.get("hsn") or "").strip()
                    if cgst_pct == 0.0 and stk_doc.get("CGST_Percentage") is not None:
                        try:
                            cgst_pct = float(stk_doc.get("CGST_Percentage"))
                        except Exception:
                            pass
                    if sgst_pct == 0.0 and stk_doc.get("SGST_Percentage") is not None:
                        try:
                            sgst_pct = float(stk_doc.get("SGST_Percentage"))
                        except Exception:
                            pass

                # If still missing item_name or hsn or GST, check pharmacy item master
                if not item_name_val or not hsn_val or (cgst_pct == 0.0 and sgst_pct == 0.0):
                    itm_master = mongo_db["hospital_pharmacyitem"].find_one({"item_id": item_id_val})
                    if not itm_master and str(item_id_val).isdigit():
                        itm_master = mongo_db["hospital_pharmacyitem"].find_one({"item_id": int(item_id_val)})
                    if itm_master:
                        if not item_name_val:
                            item_name_val = str(itm_master.get("item_name") or "").strip()
                        if not hsn_val:
                            hsn_val = str(itm_master.get("hsn_code") or itm_master.get("hsn") or "").strip()
                        if cgst_pct == 0.0 and itm_master.get("CGST_Percentage") is not None:
                            try:
                                cgst_pct = float(itm_master.get("CGST_Percentage"))
                            except Exception:
                                pass
                        if sgst_pct == 0.0 and itm_master.get("SGST_Percentage") is not None:
                            try:
                                sgst_pct = float(itm_master.get("SGST_Percentage"))
                            except Exception:
                                pass
            except Exception:
                pass

        raw_dv = med.get("discount_value")
        if raw_dv is not None and str(raw_dv).strip() not in ("", "%"):
            try:
                disc_val = float(raw_dv)
            except Exception:
                disc_val = 0.0
        elif med.get("discount") is not None and str(med.get("discount")).strip() not in ("", "%"):
            try:
                disc_val = float(med.get("discount"))
            except Exception:
                disc_val = 0.0
        elif med.get("discount_percent") is not None and str(med.get("discount_percent")).strip() not in ("", "%"):
            try:
                disc_val = float(med.get("discount_percent"))
            except Exception:
                disc_val = 0.0
        else:
            disc_val = 0.0

        disc_type = str(med.get("discount_type") or "percent").strip()
        disc_amt = float(med.get("discount_amount", 0) or 0)
        qty_val = int(med.get("qty", 0) or med.get("quantity", 0))
        price_val = float(med.get("price", 0) or med.get("mrp", 0))
        calc_price = float(med.get("calculated_price", 0) or (qty_val * price_val))
        mrp_val = float(med.get("mrp", 0) or (calc_price / qty_val if qty_val > 0 else price_val))

        total_gst_pct = cgst_pct + sgst_pct
        product_val = round(calc_price / (1.0 + total_gst_pct / 100.0), 4) if total_gst_pct > 0 else calc_price

        if disc_amt == 0 and disc_val > 0:
            disc_amt = disc_val if disc_type == "amount" else (product_val * disc_val / 100.0)

        taxable_val = max(0.0, product_val - disc_amt)

        cgst_amt = 0.0
        for k in ("CGST_Amt", "cgst_amount", "cgst_amt"):
            if med.get(k) is not None and str(med.get(k)).strip() != "":
                try:
                    cgst_amt = float(med.get(k))
                    break
                except Exception:
                    pass

        sgst_amt = 0.0
        for k in ("SGST_Amt", "sgst_amount", "sgst_amt"):
            if med.get(k) is not None and str(med.get(k)).strip() != "":
                try:
                    sgst_amt = float(med.get(k))
                    break
                except Exception:
                    pass

        if cgst_amt == 0.0 and cgst_pct > 0 and taxable_val > 0:
            cgst_amt = round((taxable_val * cgst_pct) / 100.0, 2)
        if sgst_amt == 0.0 and sgst_pct > 0 and taxable_val > 0:
            sgst_amt = round((taxable_val * sgst_pct) / 100.0, 2)

        is_del = bool(med.get("is_deleted") or med.get("deleted_is"))
        # Skip items with qty 0 unless they are an audit-tracked deleted item
        if qty_val <= 0 and not is_del:
            continue

        clean_item = {
            "item_id": item_id_val,
            "batch_number": bn_val,
            "expiry_date": expiry_val,
            "hsn_code": hsn_val,
            "qty": qty_val,
            "price": price_val,
            "mrp": mrp_val,
            "calculated_price": calc_price,
            "product_value": round(product_val, 4),
            "taxable_value": round(taxable_val, 4),
            "CGST_Percentage": cgst_pct,
            "SGST_Percentage": sgst_pct,
            "CGST_Amt": round(cgst_amt, 2),
            "SGST_Amt": round(sgst_amt, 2),
            "discount_type": disc_type,
            "discount_value": disc_val,
            "discount_percent": "%" if disc_type == "percent" else str(med.get("discount_percent") or "%"),
            "discount_amount": round(disc_amt, 2),
            "discount": disc_val,
        }
        if is_del:
            clean_item["is_deleted"] = True
        if med.get("dosage"):
            clean_item["dosage"] = med.get("dosage")
        if med.get("noOfDays") or med.get("no_of_days"):
            clean_item["noOfDays"] = med.get("noOfDays") or med.get("no_of_days")
        if med.get("total") is not None:
            clean_item["total"] = float(med.get("total"))
        if med_is_consumable:
            clean_item["is_consumable_items"] = True
        if med.get("dispatched_qty") is not None:
            try:
                clean_item["dispatched_qty"] = float(med.get("dispatched_qty"))
            except Exception:
                clean_item["dispatched_qty"] = med.get("dispatched_qty")
        clean_item["edit_history"] = med.get("edit_history") or []

        clean.append(clean_item)

    return clean


# ----------------------------------------------------------
# STOCK UPDATE (NO department_code)
# ----------------------------------------------------------
def adjust_blocked_stock(old_meds, new_meds, hospital_code, branch_code, outlet_code):

    if not hospital_code or not branch_code or not outlet_code:
        return

    def _clean_bn(b):
        s = str(b or "").strip()
        return "" if s.lower() in ["none", "null", "n/a", "undefined", "—", "-"] else s

    def _clean_iid(iid):
        try:
            return int(iid)
        except (ValueError, TypeError):
            return iid

    def _get_qty(m):
        if not isinstance(m, dict):
            return 0.0
        try:
            return float(m.get("qty") if m.get("qty") is not None else m.get("quantity", 0) or 0)
        except (ValueError, TypeError):
            return 0.0

    old_map = {}
    for m in (old_meds or []):
        if isinstance(m, dict):
            iid = _clean_iid(m.get("item_id"))
            bn = _clean_bn(m.get("batch_number") or m.get("batch_no") or m.get("batch"))
            if iid is not None and bn:
                old_map[(iid, bn)] = _get_qty(m)

    new_map = {}
    for m in (new_meds or []):
        if isinstance(m, dict):
            iid = _clean_iid(m.get("item_id"))
            bn = _clean_bn(m.get("batch_number") or m.get("batch_no") or m.get("batch"))
            if iid is not None and bn:
                new_map[(iid, bn)] = _get_qty(m)

    keys = set(old_map.keys()).union(new_map.keys())

    for item_id_val, batch_number in keys:
        old_qty = old_map.get((item_id_val, batch_number), 0.0)
        new_qty = new_map.get((item_id_val, batch_number), 0.0)

        diff = new_qty - old_qty

        if diff == 0:
            continue

        stock_collection.update_one(
            {
                "hospital_code": hospital_code,
                "branch_code": branch_code,
                "outlet_code": outlet_code,
                "item_id": item_id_val,
                "batch_number": str(batch_number)
            },
            {
                "$inc": {"blocked_quantity": diff}
            }
        )


# ----------------------------------------------------------
# EDIT HISTORY (Safely handles ward requests / missing batch numbers)
# ----------------------------------------------------------
def build_edit_history(old_meds, new_meds, employee_id):

    updated = []

    # Ensure list types
    if isinstance(old_meds, str):
        try:
            old_meds = json.loads(old_meds)
        except Exception:
            old_meds = []
    if not isinstance(old_meds, list):
        old_meds = []

    if isinstance(new_meds, str):
        try:
            new_meds = json.loads(new_meds)
        except Exception:
            new_meds = []
    if not isinstance(new_meds, list):
        new_meds = []

    def _clean_key(m):
        if not isinstance(m, dict):
            return (None, "")
        iid = m.get("item_id")
        try:
            iid = int(iid)
        except (ValueError, TypeError):
            pass
        b = str(m.get("batch_number") or m.get("batch_no") or m.get("batch") or "").strip()
        if b.lower() in ["none", "null", "n/a", "undefined", "—", "-"]:
            b = ""
        return (iid, b)

    def _get_qty(m):
        if not isinstance(m, dict):
            return 0
        try:
            return float(m.get("qty") if m.get("qty") is not None else m.get("quantity", 0) or 0)
        except (ValueError, TypeError):
            return 0

    unmatched_old = [m for m in old_meds if isinstance(m, dict) and not m.get("is_deleted")]
    unmatched_new = [m for m in new_meds if isinstance(m, dict)]

    pairs = []  # (old_item, new_item)

    # Pass 1: Exact (item_id, batch_number) match
    remaining_new = []
    for new_it in unmatched_new:
        new_k = _clean_key(new_it)
        matched_idx = None
        for idx, old_it in enumerate(unmatched_old):
            old_k = _clean_key(old_it)
            if new_k[0] is not None and old_k[0] is not None and new_k[0] == old_k[0] and new_k[1] == old_k[1] and new_k[1] != "":
                matched_idx = idx
                break
        if matched_idx is not None:
            pairs.append((unmatched_old.pop(matched_idx), new_it))
        else:
            remaining_new.append(new_it)
    unmatched_new = remaining_new

    # Pass 2: Match by item_id when old item had no batch assigned yet (e.g. from Medicine Chart / Ward Requests)
    remaining_new = []
    for new_it in unmatched_new:
        new_k = _clean_key(new_it)
        matched_idx = None
        for idx, old_it in enumerate(unmatched_old):
            old_k = _clean_key(old_it)
            if new_k[0] is not None and old_k[0] is not None and new_k[0] == old_k[0] and old_k[1] == "":
                matched_idx = idx
                break
        if matched_idx is not None:
            pairs.append((unmatched_old.pop(matched_idx), new_it))
        else:
            remaining_new.append(new_it)
    unmatched_new = remaining_new

    now = datetime.utcnow().isoformat()

    # Process paired items
    for old, new in pairs:
        old_qty = _get_qty(old)
        new_qty = _get_qty(new)
        history = list(old.get("edit_history") or [])

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

        new_item = {k: v for k, v in new.items() if k != "item_name" and k != "quantity"}
        new_item["qty"] = new_qty
        new_item["edit_history"] = history
        updated.append(new_item)

    # Process additions (in new but not in old)
    for new in unmatched_new:
        new_qty = _get_qty(new)
        new_item = {k: v for k, v in new.items() if k != "item_name" and k != "quantity"}
        new_item["qty"] = new_qty
        new_item.setdefault("edit_history", [])
        new_item["edit_history"].append({
            "action": "medicine_added",
            "qty": new_qty,
            "blocked_change": new_qty,
            "timestamp": now,
            "edited_by": employee_id
        })
        updated.append(new_item)

    # Process deletions (in old but not in new)
    for old in unmatched_old:
        old_qty = _get_qty(old)
        old_item = {k: v for k, v in old.items() if k != "item_name" and k != "quantity"}
        old_item["qty"] = old_qty
        old_item.setdefault("edit_history", [])
        old_item["is_deleted"] = True
        old_item["edit_history"].append({
            "action": "medicine_deleted",
            "qty_deleted": old_qty,
            "blocked_change": -old_qty,
            "timestamp": now,
            "edited_by": employee_id
        })
        updated.append(old_item)

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
    outlet_code   = resolve_request_outlet(request, data)

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
    resolved_doctor_id = resolve_doctor_id(data.get("doctor_id"))
    doc_name = (data.get("doctor_name") or data.get("doctorName") or "").strip()
    if not doc_name and resolved_doctor_id:
        doc_name = get_doctor_name_by_id(resolved_doctor_id)
    if not resolved_doctor_id and doc_name:
        resolved_doctor_id = resolve_doctor_id(doc_name) or ""

    round_off_val = float(data.get("round_off", 0) or 0.0)

    raw_pm = data.get("payment_mode") or data.get("paymentMode")
    norm_pm = "Credit" if str(raw_pm).strip().lower() == "credit" else ("Cash" if str(raw_pm).strip().lower() == "cash" else None)
    if status == "Billed" and not norm_pm:
        norm_pm = "Cash"

    fields = {
        # FIX 1: uhid is optional — stored as-is (None if not provided)
        "uhid":                     uhid,
        "inpatient_number":         data.get("inpatient_number"),
        "bill_type":                data.get("bill_type"),
        "doctor_id":                resolved_doctor_id,
        "doctor_name":              doc_name,
        # FIX 3: age stored as integer; also returned in every response
        "age":                      int(data.get("age", 0) or 0),
        "room_no":                  data.get("room_no"),
        "total_amount":             float(data.get("total_amount", 0)),
        "total_item_discount":      float(data.get("total_item_discount", 0) or 0),
        "discount_amount":          float(data.get("discount_amount", 0) or data.get("total_item_discount", 0) or data.get("overall_discount_amount", 0) or 0),
        "overall_discount_type":    data.get("overall_discount_type"),
        "overall_discount_value":   float(data.get("overall_discount_value", 0)),
        "overall_discount_amount":  float(data.get("overall_discount_amount", 0)),
        "net_amount":               float(data.get("net_amount", 0)),
        "round_off":                round_off_val,
        "shiftno":                  data.get("shiftno"),
        "payment_mode":             norm_pm,
    }

    # ✅ Save patient_name ONLY when billing WITHOUT UHID
    raw_pname = (
        data.get("patient_name")
        or data.get("patientname")
        or data.get("patientName")
        or data.get("customer_name")
        or ""
    )
    if isinstance(raw_pname, str):
        raw_pname = raw_pname.strip()

    # When without UHID do billing, user enters patient name, that time alone patient_name stored.
    # When UHID is present, do NOT store patient_name in bill document; compare & display from patient table.
    if not uhid and raw_pname:
        fields["patient_name"] = raw_pname

    # ======================================================
    # 🔁 PATCH (UPDATE / CONVERT)
    # ======================================================
    if request.method == "PATCH":

        if not Bill_id:
            return Response({"success": False, "error": "Bill_id required"})

        record = bill_collection.find_one({"Bill_id": int(Bill_id)})
        if not record:
            return Response({"success": False, "error": "Record not found"})

        old_meds = record.get("medicine_particulars") or []
        updated_meds = build_edit_history(old_meds, medicines, employee_id)

        existing_bm = str(record.get("billing_mode") or "").strip().upper()
        req_no = str(record.get("request_no") or "").strip().upper()
        is_ward_rec = bool(
            record.get("is_ward_request")
            or existing_bm in ["WARD REQUEST", "OT REQUEST", "DISCHARGE MEDICINE"]
            or req_no.startswith("MR")
            or req_no.startswith("OT")
        )
        if is_ward_rec:
            old_med_map = {}
            for om in old_meds:
                if isinstance(om, dict) and om.get("item_id") is not None:
                    old_med_map[str(om.get("item_id"))] = om
                    try:
                        old_med_map[int(om.get("item_id"))] = om
                    except Exception:
                        pass
            for um in updated_meds:
                if isinstance(um, dict):
                    om = old_med_map.get(um.get("item_id")) or old_med_map.get(str(um.get("item_id")))
                    if om:
                        prev_disp = float(om.get("dispatched_qty", 0) or 0)
                        req_q = float(om.get("requested_qty") or om.get("qty") or om.get("quantity") or 0)
                        curr_disp = float(um.get("dispatched_qty", 0) or 0)
                        if curr_disp > prev_disp:
                            um["dispatched_qty"] = curr_disp
                        elif prev_disp > 0:
                            um["dispatched_qty"] = prev_disp
                        if req_q > 0:
                            um["qty"] = req_q

        qty_changed = old_meds != medicines

        is_estimate_to_bill = (
            record.get("billing_status") == "Estimate" and status == "Billed"
        )

        current_outlet_code = outlet_code or record.get("outlet_code")

        # ✅ STOCK UPDATE CONTROL
        if not is_estimate_to_bill or qty_changed:
            adjust_blocked_stock(
                old_meds,
                medicines,
                hospital_code or record.get("hospital_code"),
                branch_code or record.get("branch_code"),
                current_outlet_code
            )

        update_data = {**fields}
        update_data["medicine_particulars"] = updated_meds
        update_data["lastmodified_by"]      = employee_id
        update_data["lastmodified_date"]    = datetime.utcnow()
        update_data["edit_reason"]          = data.get("edit_reason", "")
        update_data["edited_by"]            = employee_id
        update_data["is_dispatched"]        = data.get("is_dispatched", False)   
        update_data["pending_returns"]      = data.get("pending_returns", [])

        if current_outlet_code:
            update_data["outlet_code"]      = current_outlet_code
        if hospital_code or record.get("hospital_code"):
            update_data["hospital_code"]    = hospital_code or record.get("hospital_code")
        if branch_code or record.get("branch_code"):
            update_data["branch_code"]      = branch_code or record.get("branch_code")

        # 🔥 UPDATE ESTIMATE
        if status == "Estimate":
            if not record.get("estimate_no"):
                update_data["estimate_no"] = generate_estimate_no()
            update_data["billing_status"] = "Estimate"
            existing_bm = str(record.get("billing_mode") or "").strip().upper()
            req_no = str(record.get("request_no") or "").strip().upper()
            if existing_bm in ["OT REQUEST", "WARD REQUEST", "DISCHARGE MEDICINE"] or req_no.startswith("OT") or req_no.startswith("MR") or record.get("is_ward_request"):
                if existing_bm == "OT REQUEST" or req_no.startswith("OT"):
                    update_data["billing_mode"] = "OT REQUEST"
                elif "DISCHARGE" in existing_bm:
                    update_data["billing_mode"] = "DISCHARGE MEDICINE"
                else:
                    update_data["billing_mode"] = "WARD REQUEST"
            else:
                update_data["billing_mode"]   = "ESTIMATE"
            update_data["bill_date"]      = datetime.utcnow()

        # 🔥 CONVERT TO BILL
        elif status == "Billed":
            if not record.get("bill_no") or str(record.get("bill_no", "")).startswith("MR"):
                update_data["bill_no"] = get_next_pharmacy_bill_no(
                    outlet_code=current_outlet_code,
                    fy=get_financial_year(),
                    db_instance=mongo_db
                )
            # Converted to bill: bill_no is the official final invoice number
            update_data.pop("billed_bill_no", None)
            update_data.pop("converted_bill_no", None)

            update_data["billing_status"] = "Billed"
            existing_bm = str(record.get("billing_mode") or "").strip().upper()
            req_no = str(record.get("request_no") or "").strip().upper()
            if existing_bm in ["OT REQUEST", "WARD REQUEST", "DISCHARGE MEDICINE"] or req_no.startswith("OT") or record.get("is_ward_request"):
                if existing_bm == "OT REQUEST" or req_no.startswith("OT"):
                    update_data["billing_mode"] = "OT REQUEST"
                elif "DISCHARGE" in existing_bm:
                    update_data["billing_mode"] = "DISCHARGE MEDICINE"
                else:
                    update_data["billing_mode"] = "WARD REQUEST"
            else:
                update_data["billing_mode"]   = data.get("billing_mode") or ("IP CREDIT" if norm_pm == "Credit" else "ESTIMATE")
            update_data["payment_mode"]   = norm_pm or "Cash"
            update_data["bill_date"]      = datetime.utcnow()
            update_data["billed_id"]      = employee_id
            update_data["is_active"]      = True

        # 🔥 CANCEL BILL / ESTIMATE
        elif status == "Cancelled":
            update_data["billing_status"] = "Cancelled"
            update_data["status"]         = "Cancelled"
            update_data["is_cancelled"]   = True
            update_data["cancelled_by"]   = employee_id
            update_data["cancelled_date"] = datetime.utcnow()
            update_data["cancel_reason"]  = data.get("cancel_reason") or data.get("edit_reason", "Cancelled by user")
            # Release all blocked stock for this estimate
            adjust_blocked_stock(old_meds, [], hospital_code or record.get("hospital_code"), branch_code or record.get("branch_code"), current_outlet_code)

        patch_update_ops = {"$set": update_data}
        unset_map = {
            "billed_bill_no": "",
            "converted_bill_no": "",
            "dispatch_history": ""
        }
        if uhid or record.get("uhid"):
            update_data.pop("patient_name", None)
            update_data.pop("patientname", None)
            update_data.pop("age", None)
            unset_map["patient_name"] = ""
            unset_map["patientname"] = ""
            unset_map["age"] = ""
        patch_update_ops["$unset"] = unset_map

        bill_collection.update_one(
            {"Bill_id": int(Bill_id)},
            patch_update_ops
        )

        try:
            PharmacyBilling.objects.filter(Bill_id=int(Bill_id)).update(
                billing_status=update_data.get("billing_status", "Billed"),
                billed_id=update_data.get("billed_id", employee_id)
            )
        except Exception:
            pass

        doc_id = resolve_doctor_id(data.get("doctor_id") or record.get("doctor_id"))
        doc_name = (data.get("doctor_name") or data.get("doctorName") or record.get("doctor_name") or "").strip()
        if not doc_name and doc_id:
            doc_name = get_doctor_name_by_id(doc_id)
        if not doc_id and doc_name:
            doc_id = resolve_doctor_id(doc_name) or ""
        if doc_name:
            update_data["doctor_name"] = doc_name
        if doc_id:
            update_data["doctor_id"] = doc_id

        emp_id = employee_id or record.get("created_by")
        emp_name = get_employee_name_by_id(emp_id) if emp_id else ""
        if emp_name == "Unknown":
            emp_name = ""

        # Return bill_no + age immediately in PATCH response
        return Response({
            "success":         True,
            "Bill_id":         record.get("Bill_id"),
            "bill_no":         update_data.get("bill_no") or record.get("bill_no"),
            "bill_date":       to_utc_iso(update_data.get("bill_date") or record.get("bill_date")),
            "created_date":    to_utc_iso(record.get("created_date")),
            "estimate_no":     update_data.get("estimate_no") or record.get("estimate_no"),
            "age":             update_data.get("age", record.get("age") or 0),
            "edit_reason":     update_data.get("edit_reason"),
            "edited_by":       update_data.get("edited_by"),
            "doctor_id":       doc_id,
            "doctor_name":     doc_name,
            "created_by":      emp_id,
            "created_by_name": emp_name,
            "billed_id":       update_data.get("billed_id") or record.get("billed_id") or employee_id,
            "billed_name":     emp_name,
            "employee_name":   emp_name,
            "employee_name":   emp_name,
        })

    # ======================================================
    # 🆕 POST (CREATE)
    # ======================================================
    if request.method == "POST":

        next_Bill_id = get_next_sequence_value("pharmacy_billing_bill_id", db_instance=mongo_db)

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
            "is_active":            True,
            **fields
        }

        # Resolve doctor & cashier names
        doc_id = resolved_doctor_id
        if not doc_name and doc_id:
            doc_name = get_doctor_name_by_id(doc_id)
        if doc_name:
            record_doc["doctor_name"] = doc_name
        record_doc["doctor_id"] = doc_id

        emp_name = get_employee_name_by_id(employee_id) if employee_id else ""
        if emp_name == "Unknown":
            emp_name = ""

        # 🔥 DIRECT BILL
        if status == "Billed":
            bill_no = get_next_pharmacy_bill_no(
                outlet_code=outlet_code,
                fy=get_financial_year(),
                db_instance=mongo_db
            )

            existing_bm = str(data.get("billing_mode") or "").strip().upper()
            req_no = str(data.get("request_no") or "").strip().upper()
            is_ward = data.get("is_ward_request") or existing_bm == "WARD REQUEST" or req_no.startswith("MR")
            is_ot = existing_bm == "OT REQUEST" or req_no.startswith("OT")
            if is_ot:
                resolved_bm = "OT REQUEST"
            elif is_ward:
                resolved_bm = "WARD REQUEST"
            elif existing_bm:
                resolved_bm = existing_bm
            else:
                resolved_bm = "IP CREDIT" if norm_pm == "Credit" else "DIRECT"

            record_doc.update({
                "bill_no":      bill_no,
                "estimate_no":  None,
                "billing_mode": resolved_bm,
                "payment_mode": norm_pm or "Cash",
                "billed_id":    employee_id,
                "is_active":    True,
            })

            bill_collection.insert_one(record_doc)

            adjust_blocked_stock(
                [],
                medicines,
                hospital_code,
                branch_code,
                outlet_code
            )

            # Return bill_no + age immediately
            return Response({
                "success":         True,
                "bill_no":         bill_no,
                "Bill_id":         next_Bill_id,
                "bill_date":       to_utc_iso(record_doc.get("bill_date")),
                "created_date":    to_utc_iso(record_doc.get("created_date")),
                "age":             record_doc.get("age", 0),
                "doctor_id":       doc_id,
                "doctor_name":     doc_name,
                "created_by":      employee_id,
                "created_by_name": emp_name,
                "billed_id":       employee_id,
                "billed_name":     emp_name,
                "employee_name":   emp_name,
            })

        # 🔥 ESTIMATE
        if status == "Estimate":
            estimate_no = generate_estimate_no()

            record_doc.update({
                "bill_no":      None,
                "estimate_no":  estimate_no,
                "billing_mode": "ESTIMATE",
                "is_active":    True,
            })

            bill_collection.insert_one(record_doc)

            adjust_blocked_stock(
                [],
                medicines,
                hospital_code,
                branch_code,
                outlet_code
            )

            # Return estimate_no + age immediately
            return Response({
                "success":         True,
                "estimate_no":     estimate_no,
                "Bill_id":         next_Bill_id,
                "age":             record_doc.get("age", 0),
                "doctor_id":       doc_id,
                "doctor_name":     doc_name,
                "created_by":      employee_id,
                "created_by_name": emp_name,
                "billed_id":       employee_id,
                "billed_name":     emp_name,
                "employee_name":   emp_name,
            })

    return Response({"success": False, "error": "Invalid request"})


@api_view(["GET"])
@permission_classes([AllowAny])
def get_employee_name_api(request):
    """Resolve employee/doctor name by ID or name using get_employee_name_by_id / get_doctor_name_by_id."""
    emp_id = request.GET.get("employee_id") or request.GET.get("id") or request.GET.get("user_id")
    if not emp_id:
        return Response({"success": False, "error": "employee_id required", "name": ""})
    raw_name = get_employee_name_by_id(emp_id)
    if not raw_name or raw_name == "Unknown":
        raw_name = get_doctor_name_by_id(emp_id)
    name = "" if raw_name == "Unknown" else raw_name.strip()
    resolved_doc_id = resolve_doctor_id(emp_id)
    return Response({
        "success": True,
        "employee_id": str(emp_id),
        "doctor_id": resolved_doc_id,
        "name": name,
    })




@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_pharmacy_BillType(request):
    db = client["HMS"]
    stock_collection = db["hospital_billtype"]

    hospital_code = request.data.get("auth-hospital-code") 
    branch_code   = request.data.get("auth-branch-code") 
    outlet_code   = request.data.get("auth-outlet-code") 

    if isinstance(outlet_code, (list, tuple)):
        if len(outlet_code) == 1:
            outlet_code = outlet_code[0]
        elif outlet_code:
            outlet_code = {"$in": list(outlet_code)}
        else:
            outlet_code = None

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

# HELPER: GET LAST BILL NO (Now atomic & outlet-wise via counter_service)

def get_last_oppharmacy_billno(fy=None, outlet_code=None):
    if isinstance(fy, str) and not fy.isdigit() and outlet_code is None:
        outlet_code = fy
        fy = None
    return get_next_pharmacy_bill_no(
        outlet_code=outlet_code,
        fy=fy or get_financial_year(),
        db_instance=mongo_db
    )



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
    last_doc = bill_collection.find_one(
        {"estimate_no": {"$exists": True, "$ne": None, "$nin": ["", None]}},
        sort=[("estimate_no", -1)],
        projection={"estimate_no": 1}
    )

    if last_doc and last_doc.get("estimate_no"):
        try:
            next_no = int(last_doc["estimate_no"]) + 1
        except (ValueError, TypeError):
            next_no = 1
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

    # Calculate next Bill_id atomically
    next_Bill_id = get_next_sequence_value("pharmacy_billing_bill_id", db_instance=mongo_db)

    medicines = sanitize_medicines(data.get("medicine_particulars", []))

    record_doc = {
        "Bill_id": next_Bill_id,
        "uhid": data.get("uhid"),
        "inpatient_number": data.get("inpatient_number"),
        "bill_type": data.get("bill_type"),
        "doctor_id": resolve_doctor_id(data.get("doctor_id")),
        "room_no": data.get("room_no"),
        "total_amount": float(data.get("total_amount", 0)),
        "total_item_discount": float(data.get("total_item_discount", 0) or 0),
        "discount_amount": float(data.get("discount_amount", 0) or data.get("total_item_discount", 0) or data.get("overall_discount_amount", 0) or 0),
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
        "is_active": True,
    }

    raw_pname = (
        data.get("patient_name")
        or data.get("patientname")
        or data.get("patientName")
        or data.get("customer_name")
        or ""
    )
    if isinstance(raw_pname, str):
        raw_pname = raw_pname.strip()
    if not data.get("uhid") and raw_pname:
        record_doc["patient_name"] = raw_pname

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



def process_expired_estimate_bills(hospital_code=None, branch_code=None, outlet_code=None):
    """
    Deletes estimate bills older than 24 hours from their actual billing save time (bill_date / created_date),
    releases blocked stock in hospital_pharmacystock, and writes comprehensive audit records to hospital_pharmacy_deleted_logs.
    """
    try:
        now_utc = datetime.utcnow()
        expiry_cutoff = now_utc - timedelta(hours=24)

        query = {"billing_status": "Estimate"}
        if hospital_code:
            query["hospital_code"] = hospital_code
        if branch_code:
            query["branch_code"] = branch_code
        if outlet_code:
            query["outlet_code"] = outlet_code

        cursor = bill_collection.find(query)
        deleted_count = 0

        for bill in list(cursor):
            Bill_id = bill.get("Bill_id")
            raw_date = bill.get("bill_date") or bill.get("lastmodified_date") or bill.get("created_date")
            if not raw_date:
                continue

            if isinstance(raw_date, datetime):
                bill_time_utc = raw_date.astimezone(timezone.utc).replace(tzinfo=None) if raw_date.tzinfo else raw_date
            elif isinstance(raw_date, str):
                try:
                    dt = parse_datetime(raw_date) or datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                    bill_time_utc = dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt
                except Exception:
                    continue
            else:
                continue

            # Verify 24-hour expiry strictly based on bill save timestamp
            if bill_time_utc > expiry_cutoff:
                continue

            h_code = bill.get("hospital_code")
            b_code = bill.get("branch_code")
            o_code = bill.get("outlet_code")
            medicines = bill.get("medicine_particulars", [])
            if isinstance(medicines, str):
                try:
                    medicines = json.loads(medicines)
                except Exception:
                    medicines = []

            # 1. Release blocked stock
            for med in medicines:
                if not isinstance(med, dict):
                    continue
                item_id = med.get("item_id")
                batch_number = med.get("batch_number")
                qty = float(med.get("qty", 0) or med.get("quantity", 0) or 0)
                if not item_id or qty <= 0:
                    continue

                try:
                    item_id_val = int(item_id)
                except (ValueError, TypeError):
                    item_id_val = item_id

                stock_filter = {
                    "item_id": item_id_val,
                    "hospital_code": h_code,
                    "branch_code": b_code,
                    "outlet_code": o_code,
                }
                if batch_number and str(batch_number).strip().lower() not in ["", "none", "null", "n/a"]:
                    stock_filter["batch_number"] = str(batch_number).strip()

                stock = stock_collection.find_one(stock_filter)
                if stock:
                    current_blocked = float(stock.get("blocked_quantity", 0) or 0)
                    release_qty = min(qty, current_blocked)
                    if release_qty > 0:
                        stock_collection.update_one(
                            {"_id": stock["_id"]},
                            {"$inc": {"blocked_quantity": -release_qty}}
                        )

            # Resolve estimated_time (exact estimate creation/bill datetime)
            estimated_time = raw_date if isinstance(raw_date, datetime) else bill_time_utc

            # Resolve uhid with fallback to admission if inpatient_number exists
            uhid = bill.get("uhid") or bill.get("UHID") or bill.get("patient_uhid") or bill.get("patient_id")
            if not uhid and bill.get("inpatient_number"):
                try:
                    adm = mongo_db["hospital_admission"].find_one(
                        {"ipNumber": bill.get("inpatient_number")},
                        {"uhid": 1, "patientName": 1}
                    )
                    if adm:
                        uhid = adm.get("uhid")
                except Exception:
                    pass

            # Resolve patient_name
            patient_name = bill.get("patient_name") or bill.get("patientname") or ""
            if not patient_name and uhid:
                try:
                    pat = mongo_db["hospital_patient"].find_one({"uhid": uhid}, {"firstName": 1, "lastName": 1, "patient_name": 1, "name": 1})
                    if pat:
                        fn = pat.get("firstName") or ""
                        ln = pat.get("lastName") or ""
                        patient_name = f"{fn} {ln}".strip() or pat.get("patient_name") or pat.get("name") or ""
                except Exception:
                    pass

            doc_id = bill.get("doctor_id")
            doc_name = get_doctor_name_by_id(doc_id) if doc_id else ""

            # 2. Write to deletion logs
            mongo_db["hospital_pharmacy_deleted_logs"].insert_one({
                "Bill_id": Bill_id,
                "estimate_no": bill.get("estimate_no"),
                "uhid": uhid,
                "estimated_time": estimated_time,
                "estimate_time": estimated_time,
                "deleted_at": datetime.utcnow(),
                "reason": "Estimate expired after 24 hours from bill save time",
                "medicine_particulars": medicines,
                "hospital_code": h_code,
                "branch_code": b_code,
                "outlet_code": o_code,
                "doctor_id": doc_id,
                "doctor_name": doc_name,
                "total_amount": float(bill.get("total_amount", 0) or 0),
                "net_amount": float(bill.get("net_amount", 0) or 0),
                "created_date": bill.get("created_date"),
                "bill_date": bill.get("bill_date"),
                "patient_name": patient_name,
                "deleted_by": "AUTO_DELETE_24HR",
            })

            # 3. Delete from hospital_pharmacybilling
            bill_collection.delete_one({"Bill_id": Bill_id})
            try:
                PharmacyBilling.objects.filter(Bill_id=int(Bill_id)).delete()
            except Exception:
                pass

            deleted_count += 1

        return deleted_count

    except Exception as e:
        print("[ERROR] process_expired_estimate_bills:", e)
        return 0


@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_active_estimates(request):
    process_expired_estimate_bills()
    estimates = list(bill_collection.find({"billing_status": "Estimate", "is_cancelled": {"$ne": True}}, {"_id": 0}).sort("Bill_id", -1))
    
    # Dynamic enrichment: resolve patient_name from hospital_patient and item_name from hospital_pharmacyitem
    uhids = {str(e.get("uhid")).strip() for e in estimates if e.get("uhid")}
    item_ids = set()
    for e in estimates:
        for m in (e.get("medicine_particulars") or []):
            if isinstance(m, dict) and m.get("item_id"):
                item_ids.add(m.get("item_id"))

    pat_map = {}
    if uhids:
        try:
            for p in mongo_db["hospital_patient"].find({"uhid": {"$in": list(uhids)}}, {"uhid": 1, "salutation": 1, "firstName": 1, "lastName": 1, "_id": 0}):
                sal = (p.get("salutation") or "").strip()
                fn  = (p.get("firstName") or "").strip()
                ln  = (p.get("lastName") or "").strip()
                if ln.lower() == fn.lower():
                    ln = ""
                full_n = " ".join(f"{sal} {fn} {ln}".split())
                pat_map[p["uhid"]] = full_n
        except Exception:
            pass

    item_name_map = {}
    if item_ids:
        try:
            search_iids = []
            for iid in item_ids:
                search_iids.append(iid)
                if str(iid).isdigit():
                    search_iids.append(int(iid))
                    search_iids.append(str(iid))
            for itm in mongo_db["hospital_pharmacyitem"].find({"item_id": {"$in": search_iids}}, {"item_id": 1, "item_name": 1, "_id": 0}):
                raw_id = itm.get("item_id")
                nm = itm.get("item_name", "")
                item_name_map[raw_id] = nm
                item_name_map[str(raw_id)] = nm
        except Exception:
            pass

    for e in estimates:
        u = str(e.get("uhid") or "").strip()
        if u and u in pat_map:
            e["patient_name"] = pat_map[u]
            e["patientname"]  = pat_map[u]
        for m in (e.get("medicine_particulars") or []):
            if isinstance(m, dict):
                iid = m.get("item_id")
                if not m.get("item_name") and (iid in item_name_map or str(iid) in item_name_map):
                    resolved_name = item_name_map.get(iid) or item_name_map.get(str(iid)) or ""
                    m["item_name"] = resolved_name
                    m["name"] = resolved_name

    return Response(estimates, status=status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_estimate_bills(request):
    try:
        hospital_code = request.data.get("auth-hospital-code")
        branch_code   = request.data.get("auth-branch-code")
        active_outlet = resolve_request_outlet(request, request.data if hasattr(request, "data") else None)

        # ── 1. Automatically purge and log any expired estimates (>24 hours from bill save time) ──
        process_expired_estimate_bills(hospital_code=None, branch_code=None, outlet_code=None)

        # =========================================================
        # ✅ Fetch Active Estimate Bills directly from MongoDB
        # =========================================================
        filter_query = {
            "billing_status": "Estimate",
            "is_cancelled": {"$ne": True}
        }
        if hospital_code:
            filter_query["hospital_code"] = hospital_code
        if branch_code:
            filter_query["branch_code"] = branch_code
        if active_outlet:
            filter_query["outlet_code"] = active_outlet

        cursor = bill_collection.find(filter_query).sort("Bill_id", -1)
        data = []

        for bill in cursor:
            Bill_id = bill.get("Bill_id")
            uhid = bill.get("uhid") or ""

            # =========================================================
            # ✅ Get Patient Name (compare from patient table if UHID present)
            # =========================================================
            patient_name = ""
            if uhid:
                try:
                    pat = mongo_db["hospital_patient"].find_one({"uhid": uhid}, {"firstName": 1, "lastName": 1, "salutation": 1, "patient_name": 1, "name": 1})
                    if pat:
                        sal = (pat.get("salutation") or "").strip()
                        fn = (pat.get("firstName") or "").strip()
                        ln = (pat.get("lastName") or "").strip()
                        if ln.lower() == fn.lower():
                            ln = ""
                        patient_name = " ".join(f"{sal} {fn} {ln}".split()) or pat.get("patient_name") or pat.get("name") or ""
                except Exception:
                    pass

            if not patient_name:
                patient_name = bill.get("patient_name") or bill.get("patientname") or ""

            if not patient_name and bill.get("inpatient_number"):
                try:
                    adm = mongo_db["hospital_admission"].find_one({"ipNumber": bill.get("inpatient_number")}, {"patientName": 1})
                    if adm:
                        patient_name = adm.get("patientName", "")
                except Exception:
                    pass

            # =========================================================
            # ✅ Resolve Doctor ID & Doctor Name
            # =========================================================
            doc_id = bill.get("doctor_id") or ""
            doc_name = get_doctor_name_by_id(doc_id) if doc_id else ""

            # =========================================================
            # ✅ Resolve Bill Type Name
            # =========================================================
            bill_type_val = bill.get("bill_type")
            bill_type_name = ""
            if bill_type_val is not None:
                try:
                    bt_doc = mongo_db["hospital_billtype"].find_one({"bill_type": int(bill_type_val)})
                    if bt_doc:
                        bill_type_name = bt_doc.get("bill_name", "")
                except Exception:
                    pass

            # =========================================================
            # ✅ Medicine Particulars Handling
            # =========================================================
            meds = bill.get("medicine_particulars", [])
            if isinstance(meds, str):
                try:
                    meds = json.loads(meds)
                except Exception:
                    meds = []

            particulars = []
            for med in (meds or []):
                if not isinstance(med, dict):
                    continue
                item_id = med.get("item_id")
                item_name = med.get("item_name") or med.get("medicine_name") or med.get("name") or ""
                if not item_name and item_id:
                    try:
                        p_item = mongo_db["hospital_pharmacyitem"].find_one({"item_id": int(item_id)}, {"item_name": 1})
                        if p_item:
                            item_name = p_item.get("item_name", "")
                    except Exception:
                        pass

                qty = float(med.get("qty", 0) or med.get("quantity", 0) or 0)
                calc_price = float(med.get("calculated_price", 0) or 0)
                med_total = float(med.get("total", 0) or 0)

                # Robust unit MRP derivation:
                unit_mrp = 0.0
                if med.get("mrp") is not None and float(med.get("mrp")) > 0:
                    unit_mrp = float(med.get("mrp"))
                elif calc_price > 0 and qty > 0:
                    unit_mrp = round(calc_price / qty, 2)
                elif med_total > 0 and qty > 0:
                    unit_mrp = round(med_total / qty, 2)
                elif med.get("Selling_Price") is not None and float(med.get("Selling_Price")) > 0:
                    unit_mrp = float(med.get("Selling_Price"))
                elif med.get("selling_price") is not None and float(med.get("selling_price")) > 0:
                    unit_mrp = float(med.get("selling_price"))
                elif med.get("price") is not None and float(med.get("price")) > 0:
                    unit_mrp = float(med.get("price"))

                rate = float(med.get("price") or unit_mrp)
                mrp = float(unit_mrp or rate)

                particulars.append({
                    **med,
                    "item_id": item_id,
                    "item_name": item_name,
                    "name": item_name,
                    "batch_number": med.get("batch_number", ""),
                    "qty": qty,
                    "quantity": qty,
                    "price": rate,
                    "mrp": mrp,
                    "Selling_Price": mrp,
                    "selling_price": mrp,
                    "calculated_price": float(calc_price or (qty * mrp)),
                    "total": float(med_total or (qty * mrp)),
                    "CGST_Percentage": float(med.get("CGST_Percentage", 0) or 0),
                    "SGST_Percentage": float(med.get("SGST_Percentage", 0) or 0),
                    "CGST_Amt": float(med.get("CGST_Amt", 0) or 0),
                    "SGST_Amt": float(med.get("SGST_Amt", 0) or 0),
                    "dosage": med.get("dosage", ""),
                    "noOfDays": med.get("noOfDays", ""),
                })

            bill_date = bill.get("bill_date") or bill.get("created_date")
            created_date = bill.get("created_date") or bill.get("bill_date")
            lastmodified_date = bill.get("lastmodified_date")

            def _to_utc_iso(dt_val):
                if not dt_val:
                    return ""
                if isinstance(dt_val, datetime):
                    if dt_val.tzinfo is None:
                        return dt_val.isoformat() + "Z"
                    return dt_val.astimezone(timezone.utc).isoformat()
                s = str(dt_val).strip()
                if s and "T" in s and not s.endswith("Z") and "+" not in s:
                    return s + "Z"
                return s

            data.append({
                "Bill_id": Bill_id,
                "bill_no": bill.get("bill_no"),
                "estimate_no": bill.get("estimate_no"),
                "created_date": _to_utc_iso(created_date),
                "bill_date": _to_utc_iso(bill_date),
                "lastmodified_date": _to_utc_iso(lastmodified_date),
                "created_by": bill.get("created_by"),
                "lastmodified_by": bill.get("lastmodified_by"),
                "uhid": uhid,
                "inpatient_number": bill.get("inpatient_number", ""),
                "bill_type": bill_type_val,
                "bill_type_name": bill_type_name,
                "bill_name": bill_type_name,
                "patient_name": patient_name,
                "doctor_id": doc_id,
                "doctor_name": doc_name,
                "room_no": bill.get("room_no", ""),
                "medicine_particulars": particulars,
                "total_amount": float(bill.get("total_amount", 0) or 0),
                "overall_discount_type": bill.get("overall_discount_type"),
                "overall_discount_value": float(bill.get("overall_discount_value", 0) or 0),
                "overall_discount_amount": float(bill.get("overall_discount_amount", 0) or 0),
                "net_amount": float(bill.get("net_amount", 0) or 0),
                "round_off": float(bill.get("round_off", 0) or 0),
                "billing_status": "Estimate",
                "billing_mode": bill.get("billing_mode", "ESTIMATE"),
                "hospital_code": bill.get("hospital_code"),
                "branch_code": bill.get("branch_code"),
                "outlet_code": bill.get("outlet_code"),
                "payment_details": bill.get("payment_details"),
                "cashier_id": bill.get("cashier_id"),
            })

        return Response(data, status=status.HTTP_200_OK)

    except Exception as e:
        print("[ERROR] get_estimate_bills:", e)
        return Response({
            "status": "error",
            "message": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def convert_estimate_to_bill(request, estimate_no):
    try:
        estimate = bill_collection.find_one({
            "estimate_no": str(estimate_no),
            "billing_status": "Estimate"
        })
        if not estimate:
            return Response({"success": False, "error": f"Estimate {estimate_no} not found or already converted."}, status=404)

        medicines = estimate.get("medicine_particulars", [])
        if isinstance(medicines, str):
            try:
                medicines = json.loads(medicines)
            except Exception:
                medicines = []

        converted_items = []
        for m in medicines:
            if not isinstance(m, dict):
                continue
            item_id = m.get("item_id")
            qty = float(m.get("qty", 0) or m.get("quantity", 0) or 0)
            calc_price = float(m.get("calculated_price", 0) or 0)
            m_total = float(m.get("total", 0) or 0)

            unit_mrp = 0.0
            if m.get("mrp") is not None and float(m.get("mrp")) > 0:
                unit_mrp = float(m.get("mrp"))
            elif calc_price > 0 and qty > 0:
                unit_mrp = round(calc_price / qty, 2)
            elif m_total > 0 and qty > 0:
                unit_mrp = round(m_total / qty, 2)
            elif m.get("Selling_Price") is not None and float(m.get("Selling_Price")) > 0:
                unit_mrp = float(m.get("Selling_Price"))
            elif m.get("selling_price") is not None and float(m.get("selling_price")) > 0:
                unit_mrp = float(m.get("selling_price"))
            elif m.get("price") is not None and float(m.get("price")) > 0:
                unit_mrp = float(m.get("price"))

            item_name = m.get("item_name") or m.get("medicine_name") or m.get("name") or ""
            if not item_name and item_id:
                try:
                    p_it = mongo_db["hospital_pharmacyitem"].find_one({"item_id": int(item_id)}, {"item_name": 1})
                    if p_it:
                        item_name = p_it.get("item_name", "")
                except Exception:
                    pass

            rate = float(m.get("price") or unit_mrp)
            mrp = float(unit_mrp or rate)
            converted_items.append({
                "item_id": item_id,
                "item_name": item_name,
                "name": item_name,
                "batch_number": m.get("batch_number", ""),
                "qty": qty,
                "quantity": qty,
                "price": rate,
                "mrp": mrp,
                "Selling_Price": mrp,
                "selling_price": mrp,
                "calculated_price": float(calc_price or (qty * mrp)),
                "total": float(m_total or (qty * mrp)),
                "edit_history": m.get("edit_history", [])
            })

        uhid = estimate.get("uhid")
        patient_name = ""
        if uhid:
            try:
                pat = mongo_db["hospital_patient"].find_one({"uhid": uhid}, {"firstName": 1, "lastName": 1, "salutation": 1, "patient_name": 1, "name": 1})
                if pat:
                    sal = (pat.get("salutation") or "").strip()
                    fn = (pat.get("firstName") or "").strip()
                    ln = (pat.get("lastName") or "").strip()
                    if ln.lower() == fn.lower():
                        ln = ""
                    patient_name = " ".join(f"{sal} {fn} {ln}".split()) or pat.get("patient_name") or pat.get("name") or ""
            except Exception:
                pass
        if not patient_name:
            patient_name = estimate.get("patient_name") or estimate.get("patientname") or ""

        doc_id = estimate.get("doctor_id") or ""
        doc_name = get_doctor_name_by_id(doc_id) if doc_id else ""

        bill_type_val = estimate.get("bill_type")
        bill_type_name = ""
        if bill_type_val is not None:
            try:
                bt_doc = mongo_db["hospital_billtype"].find_one({"bill_type": int(bill_type_val)})
                if bt_doc:
                    bill_type_name = bt_doc.get("bill_name", "")
            except Exception:
                pass

        data = {
            "Bill_id": estimate.get("Bill_id"),
            "estimate_no": estimate.get("estimate_no"),
            "patient_name": patient_name,
            "uhid": uhid,
            "inpatient_number": estimate.get("inpatient_number"),
            "doctor_id": doc_id,
            "doctor_name": doc_name,
            "room_no": estimate.get("room_no"),
            "bill_type": bill_type_val,
            "bill_type_name": bill_type_name,
            "bill_name": bill_type_name,
            "medicine_particulars": converted_items,
            "net_amount": float(estimate.get("net_amount", 0) or 0),
            "total_amount": float(estimate.get("total_amount", 0) or 0),
        }

        return Response({
            "success": True,
            "data": data
        })

    except Exception as e:
        print("[ERROR] convert_estimate_to_bill:", e)
        return Response({"success": False, "error": str(e)}, status=500)


@api_view(["POST"])
# @permission_classes([HasRoleAndDataPermission])
def cancel_estimate_bill(request):
    """
    Cancels an estimate bill in hospital_pharmacybilling, releases any blocked stock in hospital_pharmacystock,
    updates billing_status to 'Cancelled', and writes an audit log to hospital_pharmacy_deleted_logs.
    """
    try:
        data = request.data
        employee_id   = data.get("auth-user-id")
        hospital_code = data.get("auth-hospital-code")
        branch_code   = data.get("auth-branch-code")
        outlet_code   = resolve_request_outlet(request, data) if "resolve_request_outlet" in globals() else (data.get("auth-outlet-code") or data.get("outlet_code"))

        bill_id = data.get("Bill_id") or data.get("bill_id")
        estimate_no = data.get("estimate_no")
        cancel_reason = data.get("cancel_reason") or data.get("reason") or "Cancelled by user"

        query = {}
        if bill_id is not None and str(bill_id).strip() != "":
            try:
                query["Bill_id"] = int(bill_id)
            except (ValueError, TypeError):
                query["Bill_id"] = bill_id
        elif estimate_no:
            query["estimate_no"] = str(estimate_no).strip()
        else:
            return Response({
                "status": "error",
                "message": "Bill_id or estimate_no is required to cancel estimate."
            }, status=status.HTTP_400_BAD_REQUEST)

        record = bill_collection.find_one(query)
        if not record:
            return Response({
                "status": "error",
                "message": f"Estimate bill not found for query {query}."
            }, status=status.HTTP_404_NOT_FOUND)

        current_status = str(record.get("billing_status") or record.get("status") or "").strip().lower()
        if current_status in ["billed", "paid"]:
            return Response({
                "status": "error",
                "message": "Cannot cancel this estimate because it has already been converted into a final bill."
            }, status=status.HTTP_400_BAD_REQUEST)

        if current_status == "cancelled" or record.get("is_cancelled") is True:
            return Response({
                "status": "success",
                "message": "Estimate is already cancelled.",
                "Bill_id": record.get("Bill_id"),
                "estimate_no": record.get("estimate_no")
            }, status=status.HTTP_200_OK)

        # 1. Release blocked stock in hospital_pharmacystock
        old_meds = record.get("medicine_particulars", [])
        if isinstance(old_meds, str):
            try:
                old_meds = json.loads(old_meds)
            except Exception:
                old_meds = []

        h_code = record.get("hospital_code") or hospital_code
        b_code = record.get("branch_code") or branch_code
        o_code = record.get("outlet_code") or outlet_code

        adjust_blocked_stock(old_meds, [], h_code, b_code, o_code)

        # 2. Update status in MongoDB
        now_time = datetime.utcnow()
        update_data = {
            "billing_status": "Cancelled",
            "status": "Cancelled",
            "is_cancelled": True,
            "cancelled_by": employee_id,
            "cancelled_date": now_time,
            "lastmodified_by": employee_id,
            "lastmodified_date": now_time,
            "cancel_reason": cancel_reason,
        }
        bill_collection.update_one({"_id": record["_id"]}, {"$set": update_data})

        # 3. Update SQL PharmacyBilling model if it exists
        try:
            PharmacyBilling.objects.filter(Bill_id=int(record.get("Bill_id"))).update(
                billing_status="Cancelled",
                lastmodified_by=employee_id,
                lastmodified_date=now_time
            )
        except Exception:
            pass

        # 4. Write audit entry to hospital_pharmacy_deleted_logs
        try:
            mongo_db["hospital_pharmacy_deleted_logs"].insert_one({
                "Bill_id": record.get("Bill_id"),
                "estimate_no": record.get("estimate_no"),
                "uhid": record.get("uhid"),
                "patient_name": record.get("patient_name") or record.get("patientname") or "",
                "estimated_time": record.get("bill_date") or record.get("created_date"),
                "cancelled_at": now_time,
                "cancelled_by": employee_id,
                "reason": cancel_reason,
                "medicine_particulars": old_meds,
                "hospital_code": h_code,
                "branch_code": b_code,
                "outlet_code": o_code,
                "doctor_id": record.get("doctor_id"),
                "doctor_name": get_doctor_name_by_id(record.get("doctor_id")) if record.get("doctor_id") else "",
                "total_amount": float(record.get("total_amount", 0) or 0),
                "net_amount": float(record.get("net_amount", 0) or 0),
                "action": "ESTIMATE_CANCELLED",
            })
        except Exception as e_log:
            print("[WARN] Failed to write deleted log for cancelled estimate:", e_log)

        return Response({
            "status": "success",
            "message": "Estimate bill cancelled successfully.",
            "Bill_id": record.get("Bill_id"),
            "estimate_no": record.get("estimate_no")
        }, status=status.HTTP_200_OK)

    except Exception as e:
        print("[ERROR] cancel_estimate_bill:", e)
        return Response({
            "status": "error",
            "message": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)






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

        bill_mongo_id = data.get("_id") or data.get("id") or data.get("bill_mongo_id")
        bill_no = data.get("bill_no") or data.get("bill_number")
        Bill_id = data.get("Bill_id")
        uhid = data.get("uhid")
        payment_details = data.get("payment_details")

        from .dbcollection import (
            hms_db,
            global_db,
            profile_collection,
            pharmacy_billing_collection,
            pharmacy_stock_collection,
            cashcounter_shift_collection
        )

        shiftno = data.get("shiftno")
        cashier_id = (
            data.get("auth-user-id")
            or request.headers.get("User-Id")
            or request.META.get("HTTP_AUTH_USER_ID")
        )
        if not cashier_id and shiftno:
            s_doc = cashcounter_shift_collection.find_one({"shiftno": str(shiftno).strip()})
            if s_doc and s_doc.get("CashierID"):
                cashier_id = s_doc.get("CashierID")

        counter_id = data.get("counter_id")
        if not counter_id and cashier_id:
            try:
                query_id = str(cashier_id)
                search_query = {"employeeId": {"$in": [query_id, int(query_id) if query_id.isdigit() else query_id]}}
            except:
                search_query = {"employeeId": str(cashier_id)}
            profile_data = profile_collection.find_one(search_query)
            emp_cashcounter = profile_data.get("cashcounter") if profile_data else None
            if emp_cashcounter:
                counter_id = emp_cashcounter

        remarks = data.get("remarks", "")

        hospital_code = (
            data.get("auth-hospital-code")
            or request.headers.get("Hospital-Code")
            or request.META.get("HTTP_HOSPITAL_CODE")
            or "SH001"
        )

        branch_code = (
            data.get("auth-branch-code")
            or request.headers.get("Branch-Code")
            or request.META.get("HTTP_BRANCH_CODE")
            or "SHB001"
        )

        raw_outlet = (
            data.get("outlet_code")
            or data.get("auth-outlet-code")
            or request.headers.get("Outlet-Code")
            or request.META.get("HTTP_OUTLET_CODE")
        )

        parsed_outlets = []
        if isinstance(raw_outlet, (list, tuple)):
            parsed_outlets = [str(x).strip() for x in raw_outlet if str(x).strip()]
        elif isinstance(raw_outlet, str):
            s = raw_outlet.strip()
            if s.startswith("[") and s.endswith("]"):
                import ast
                try:
                    p = ast.literal_eval(s)
                    if isinstance(p, (list, tuple)):
                        parsed_outlets = [str(x).strip() for x in p if str(x).strip()]
                except Exception:
                    pass
            if not parsed_outlets and s and s.lower() != "all":
                parsed_outlets = [s]

        outlet_code = parsed_outlets[0] if parsed_outlets else "OLET002"

        # =====================================================
        # VALIDATIONS
        # =====================================================

        if not Bill_id and not bill_mongo_id and not bill_no:
            return Response({
                "success": False,
                "error": "Bill_id, _id, or bill_no is required"
            })

        if not payment_details:
            return Response({
                "success": False,
                "error": "payment_details is required"
            })

        if not hospital_code or not branch_code:
            return Response({
                "success": False,
                "error": "hospital/branch missing"
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

        if Bill_id:
            try:
                Bill_id = int(Bill_id)
            except Exception:
                pass

        uhid_clean = str(uhid).strip() if uhid and str(uhid).strip() not in ["-", "None", "null", ""] else None

        hospital_code = str(hospital_code).strip()
        branch_code = str(branch_code).strip()
        cashier_id = str(cashier_id).strip()

        # =====================================================
        # DB CONNECTION
        # =====================================================

        bill_collection = pharmacy_billing_collection
        stock_collection = pharmacy_stock_collection

        # =====================================================
        # FIND BILL
        # =====================================================

        bill = None

        # 1. Highest priority: Search by MongoDB ObjectId if provided (100% unique guarantee)
        if bill_mongo_id:
            try:
                from bson import ObjectId
                bill = bill_collection.find_one({"_id": ObjectId(str(bill_mongo_id))})
            except Exception:
                pass

        # 2. Second priority: Search by bill_no if provided
        if not bill and bill_no:
            b_query = {
                "bill_no": str(bill_no).strip(),
                "hospital_code": hospital_code,
                "branch_code": branch_code,
                "$or": [
                    {"is_deleted": False},
                    {"is_deleted": {"$exists": False}}
                ]
            }
            bill = bill_collection.find_one(b_query)

        # 3. Third priority: Search by Bill_id (strictly prioritizing UNPAID bills to avoid collisions)
        query = {
            "Bill_id": Bill_id,
            "hospital_code": hospital_code,
            "branch_code": branch_code,
            "$or": [
                {"is_deleted": False},
                {"is_deleted": {"$exists": False}}
            ]
        }

        if len(parsed_outlets) == 1:
            query["outlet_code"] = parsed_outlets[0]
        elif len(parsed_outlets) > 1:
            query["outlet_code"] = {"$in": parsed_outlets}

        if not bill and Bill_id:
            # 3a. Search UNPAID bill matching Bill_id (and uhid if passed)
            unpaid_query = {
                "Bill_id": Bill_id,
                "billing_status": {"$in": ["Billed", "Pending", "Processing", "Unpaid"]},
                "hospital_code": hospital_code,
                "branch_code": branch_code,
                "$or": [
                    {"is_deleted": False},
                    {"is_deleted": {"$exists": False}}
                ]
            }
            if uhid_clean:
                unpaid_query["uhid"] = uhid_clean
            if len(parsed_outlets) == 1:
                unpaid_query["outlet_code"] = parsed_outlets[0]
            elif len(parsed_outlets) > 1:
                unpaid_query["outlet_code"] = {"$in": parsed_outlets}

            bill = bill_collection.find_one(unpaid_query)

            # 3b. Fallback: Search UNPAID bill without outlet constraint
            if not bill:
                unpaid_fb = {
                    "Bill_id": Bill_id,
                    "billing_status": {"$in": ["Billed", "Pending", "Processing", "Unpaid"]},
                    "$or": [
                        {"is_deleted": False},
                        {"is_deleted": {"$exists": False}}
                    ]
                }
                if uhid_clean:
                    unpaid_fb["uhid"] = uhid_clean
                bill = bill_collection.find_one(unpaid_fb)

            # 3c. Fallback to standard Bill_id query
            if not bill:
                bill = bill_collection.find_one(query)

            if not bill:
                fallback_query = {
                    "Bill_id": Bill_id,
                    "$or": [
                        {"is_deleted": False},
                        {"is_deleted": {"$exists": False}}
                    ]
                }
                if hospital_code:
                    fallback_query["hospital_code"] = hospital_code
                if branch_code:
                    fallback_query["branch_code"] = branch_code
                bill = bill_collection.find_one(fallback_query)

            if not bill:
                bill = bill_collection.find_one({
                    "Bill_id": Bill_id,
                    "$or": [
                        {"is_deleted": False},
                        {"is_deleted": {"$exists": False}}
                    ]
                })

        # 4. Critical Safety: If found bill is Paid, but cashier provided uhid and UHID does not match
        if bill and bill.get("billing_status") == "Paid" and uhid_clean and str(bill.get("uhid")).strip() != uhid_clean:
            patient_pending_bill = bill_collection.find_one({
                "uhid": uhid_clean,
                "billing_status": {"$in": ["Billed", "Pending", "Processing", "Unpaid"]},
                "hospital_code": hospital_code,
                "branch_code": branch_code,
                "$or": [
                    {"is_deleted": False},
                    {"is_deleted": {"$exists": False}}
                ]
            })
            if patient_pending_bill:
                bill = patient_pending_bill

        if not bill:
            return Response({
                "success": False,
                "error": "Bill not found",
                "query": query
            })

        resolved_outlet = (
            bill.get("outlet_code")
            or (parsed_outlets[0] if parsed_outlets else "OLET002")
        )

        # =====================================================
        # CHECK ALREADY PAID
        # =====================================================

        if bill.get("billing_status") == "Paid":
            return Response({
                "success": False,
                "error": "Bill already paid"
            })

        # =====================================================
        # VALIDATE EXACT AMOUNT (NO LOW / EXCESS AMOUNT ALLOWED)
        # =====================================================
        bill_net = float(bill.get("net_amount", 0) or 0)
        paid_amt = float(payment_details.get("Paid_amount", 0) or 0)
        if abs(paid_amt - bill_net) > 0.01:
            if paid_amt < bill_net:
                return Response({
                    "success": False,
                    "error": f"Paid amount (₹{paid_amt:,.2f}) is lower than Net Amount (₹{bill_net:,.2f}). Low amount / partial payment is not allowed."
                })
            else:
                return Response({
                    "success": False,
                    "error": f"Paid amount (₹{paid_amt:,.2f}) is greater than Net Amount (₹{bill_net:,.2f}). Excess payment is not allowed."
                })

        method_str = str(payment_details.get("method", "")).strip().lower()
        # Any payment collected at cash counter (Cash, Card, Multiple, Cheque, UPI) is a settled counter collection
        if method_str == "credit":
            bill_payment_mode = "Credit"
        else:
            bill_payment_mode = "Cash"

        # =====================================================
        # UPDATE STOCK
        # =====================================================

        is_from_estimate = bool(bill.get("estimate_no"))
        for med in bill.get("medicine_particulars", []):
            qty = float(med.get("qty", 0) or 0)
            item_id = med.get("item_id")
            try:
                item_id = int(item_id)
            except (ValueError, TypeError):
                pass

            inc_payload = {"sold_quantity": qty}
            if is_from_estimate:
                inc_payload["blocked_quantity"] = -qty

            stock_collection.update_one(
                {
                    "hospital_code": hospital_code,
                    "branch_code": branch_code,
                    "outlet_code": resolved_outlet,
                    "item_id": item_id,
                    "batch_number": str(med.get("batch_number", "")).strip()
                },
                {"$inc": inc_payload}
            )

        # =====================================================
        # UPDATE BILL
        # =====================================================

        update_result = bill_collection.update_one(
            {"_id": bill["_id"]},
            {
                "$set": {
                    "billing_status": "Paid",
                    "payment_details": payment_details,
                    "payment_mode": bill_payment_mode,
                    "paid_date": datetime.utcnow(),
                    "cashier_id": cashier_id,
                    "shiftno": shiftno,
                    "counter_id": counter_id,
                    "lastmodified_by": cashier_id,
                    "lastmodified_date": datetime.utcnow()
                }
            }
        )

        try:
            PharmacyBilling.objects.filter(Bill_id=Bill_id).update(
                billing_status="Paid",
                payment_details=payment_details,
                payment_mode=bill_payment_mode,
                cashier_id=cashier_id,
                shiftno=shiftno
            )
        except Exception as e:
            print("Sync error with PharmacyBilling SQL model:", e)

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
            "outlet_code": resolved_outlet,

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

        # Check if cash counter record already exists for this bill to prevent double entry
        try:
            b_no_clean = str(bill.get("bill_no", "")).strip()
            existing_cc = hms_db["hospital_cashcountercollection"].find_one({
                "$or": [
                    {"bill_no": b_no_clean},
                    {"bill_number": b_no_clean}
                ],
                "billing_category": "OPPharmacyBills",
                "transaction_type": "collected"
            })

            if not existing_cc:
                mongo_cc_data = {
                    "hospital_code": hospital_code,
                    "branch_code": branch_code,
                    "outlet_code": resolved_outlet,
                    "created_by": str(cashier_id),
                    "created_date": datetime.utcnow(),
                    "lastmodified_by": str(cashier_id),
                    "lastmodified_date": datetime.utcnow(),
                    "Bill_id": bill.get("Bill_id"),
                    "bill_no": bill.get("bill_no"),
                    "bill_type": bill.get("bill_type"),
                    "bill_number": bill.get("bill_no"),
                    "counter_code": str(counter_id),
                    "shift_no": str(shiftno),
                    "billing_category": "OPPharmacyBills",
                    "transaction_type": "collected",
                    "collected_amount": Decimal128(str(payment_details.get("Paid_amount", 0))),
                    "Returned_amount": Decimal128("0.00"),
                    "RemittedToBank": Decimal128("0.00"),
                    "HandOverAmount": Decimal128("0.00"),
                    "remarks": remarks
                }
                hms_db["hospital_cashcountercollection"].insert_one(mongo_cc_data)
                print(f"✅ CashCounterCollection saved directly to MongoDB for bill {bill.get('bill_no')}")
            else:
                print(f"⚠️ CashCounterCollection already exists for bill {bill.get('bill_no')}, skipping duplicate insert")
        except Exception as e_cc:
            print("Direct PyMongo cashcountercollection save error:", e_cc)

        # Recalculate shift totals in background daemon thread so response returns instantly
        try:
            from .cashcounter import recalculate_and_update_shift_details
            import threading
            threading.Thread(
                target=recalculate_and_update_shift_details,
                args=(shiftno,),
                daemon=True,
                name=f"ShiftRecalc-{shiftno}"
            ).start()
        except Exception as e:
            print("Error scheduling shift recalculation in OP Pharmacy payment:", e)

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
        data = request.data if isinstance(getattr(request, "data", None), dict) else {}

        hospital_code = data.get("auth-hospital-code")
        branch_code   = data.get("auth-branch-code")
        outlet_code   = data.get("auth-outlet-code")

        # Determine client's explicitly requested / active outlet (from payload, query param, or header)
        requested_outlet = (
            data.get("outlet_code")
            or request.GET.get("outlet_code")
            or (request.headers.get("Outlet-Code") if hasattr(request, "headers") else None)
            or (request.headers.get("outlet-code") if hasattr(request, "headers") else None)
            or request.META.get("HTTP_OUTLET_CODE")
            or request.META.get("HTTP_AUTH_OUTLET_CODE")
        )

        target_outlet = None
        if requested_outlet and str(requested_outlet).strip().upper() not in ["ALL", "", "NONE", "UNDEFINED"]:
            target_outlet = str(requested_outlet).strip()
        elif outlet_code:
            if isinstance(outlet_code, (list, tuple)):
                target_outlet = {"$in": list(outlet_code)}
            else:
                target_outlet = outlet_code

        # If user specified a specific target outlet, ensure they have access if outlet_code list is restricted
        if target_outlet and isinstance(target_outlet, str):
            if isinstance(outlet_code, (list, tuple)) and outlet_code and target_outlet not in outlet_code:
                return Response(
                    {
                        "status": "success",
                        "hospital_code": hospital_code,
                        "branch_code": branch_code,
                        "outlet_code": target_outlet,
                        "count": 0,
                        "data": []
                    },
                    status=status.HTTP_200_OK
                )

        # =========================================
        # 1. GET BILL DATA (Using PyMongo for speed & reliability)
        # =========================================
        from_date_str = data.get("from_date") or request.GET.get("from_date")
        to_date_str   = data.get("to_date")   or request.GET.get("to_date")

        base_mongo_filter = {
            "hospital_code": hospital_code,
            "branch_code": branch_code,
            "billing_status": {"$in": ["Pending", "Processing", "Billed", "Completed", "Paid"]},
            "is_cancelled": {"$ne": True},
            "is_deleted": {"$ne": True},
            "is_ward_request": True
        }
        if target_outlet:
            base_mongo_filter["outlet_code"] = target_outlet

        date_q = {}
        str_date_q = {}
        if from_date_str:
            try:
                # 6 hours buffer to safely cover Asia/Kolkata timezone (UTC+5:30)
                f_dt = datetime.strptime(str(from_date_str).strip()[:10], "%Y-%m-%d") - timedelta(hours=6)
                date_q["$gte"] = f_dt
                str_date_q["$gte"] = (datetime.strptime(str(from_date_str).strip()[:10], "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
            except Exception:
                pass
        if to_date_str:
            try:
                t_dt = datetime.strptime(str(to_date_str).strip()[:10], "%Y-%m-%d") + timedelta(days=1, hours=6)
                date_q["$lt"] = t_dt
                str_date_q["$lt"] = (datetime.strptime(str(to_date_str).strip()[:10], "%Y-%m-%d") + timedelta(days=2)).strftime("%Y-%m-%d")
            except Exception:
                pass

        if date_q:
            base_mongo_filter["$or"] = [
                {"created_date": date_q},
                {"created_date": str_date_q},
                {"created_date": {"$exists": False}, "ward_request_date": date_q}
            ]

        cursor = pharmacy_billing_collection.find(base_mongo_filter).sort("created_date", -1)
        if not date_q:
            cursor = cursor.limit(300)

        raw_bills = list(cursor)

        serialized_data = []
        for bill in raw_bills:
            b = dict(bill)
            if "_id" in b:
                b["_id"] = str(b["_id"])
            for date_key in ["created_date", "lastmodified_date", "bill_date", "ward_request_date"]:
                val = b.get(date_key)
                if val:
                    b[date_key] = to_utc_iso(val)

            # Only retain request_no if explicitly present in document
            raw_req = b.get("request_no")
            if raw_req and str(raw_req).strip() and str(raw_req).strip().lower() not in ["none", "null", "undefined"]:
                b["request_no"] = str(raw_req).strip()
            else:
                b["request_no"] = ""

            serialized_data.append(b)

        if not serialized_data:
            return Response(
                {
                    "status": "success",
                    "hospital_code": hospital_code,
                    "branch_code": branch_code,
                    "outlet_code": target_outlet or outlet_code,
                    "count": 0,
                    "data": []
                },
                status=status.HTTP_200_OK
            )

        # =========================================
        # 2. BULK PREFETCHING: Eliminate N+1 loop queries
        # =========================================
        all_uhids = set()
        all_doc_ids = set()
        all_created_by_ids = set()
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

            cb_id = bill.get("created_by")
            if cb_id:
                all_created_by_ids.add(str(cb_id).strip())

            raw_particulars = bill.get("medicine_particulars", [])
            items = parse_medicine_particulars(raw_particulars)
            bill_mongo_id = str(bill.get("_id"))
            bill_items_map[bill_mongo_id] = items
            if b_id:
                bill_items_map[b_id] = items

            for item in items:
                if isinstance(item, dict) and not item.get("is_deleted") and not item.get("deleted_is"):
                    iid = item.get("item_id")
                    if iid is not None:
                        try:
                            all_item_ids.add(int(iid))
                        except (ValueError, TypeError):
                            all_item_ids.add(str(iid).strip())

        # 3. Bulk fetch Patients using PyMongo (ultra-fast, zero SQL queries)
        patient_map = {}
        if all_uhids:
            try:
                p_docs = list(mongo_db["hospital_patient"].find(
                    {"uhid": {"$in": list(all_uhids)}},
                    {
                        "uhid": 1, "salutation": 1, "firstName": 1, "lastName": 1,
                        "permanent_address": 1, "area": 1, "mobilePhone": 1,
                        "customer_type": 1, "company_code": 1, "dob": 1, "age": 1
                    }
                ))
                for p in p_docs:
                    f = (p.get("firstName") or "").strip()
                    l = (p.get("lastName") or "").strip()
                    n = f if (f and l and (f.lower() == l.lower() or f.lower().endswith(l.lower()))) else f"{f} {l}".strip()
                    full_p_name = f"{p.get('salutation') or ''} {n}".strip()

                    age_str = ""
                    dob = p.get("dob")
                    if dob:
                        try:
                            today = date.today()
                            d = dob.date() if hasattr(dob, "date") else dob
                            years = today.year - d.year
                            months = today.month - d.month
                            days = today.day - d.day
                            if days < 0:
                                months -= 1
                                days += 30
                            if months < 0:
                                years -= 1
                                months += 12
                            age_str = f"{years}Y {months}M {days}D"
                        except Exception:
                            age_str = str(p.get("age") or "")
                    elif p.get("age"):
                        age_str = str(p.get("age"))

                    patient_map[str(p.get("uhid")).strip()] = {
                        "patient_name": full_p_name,
                        "address": p.get("permanent_address") or "",
                        "place": p.get("area") or "",
                        "mobile": p.get("mobilePhone") or "",
                        "customer_type": p.get("customer_type") or "General",
                        "company_code": p.get("company_code") or "",
                        "age": age_str,
                    }
            except Exception as e:
                print("Patient bulk prefetch error:", e)

        # 3b. Bulk fetch Admissions using PyMongo (ultra-fast)
        admission_map = {}
        if all_uhids:
            try:
                admissions = list(admission_collection.find(
                    {
                        "hospital_code": hospital_code,
                        "branch_code": branch_code,
                        "uhid": {"$in": list(all_uhids)},
                        "is_admitted": True
                    }
                ).sort("admissionDateTime", -1))

                for adm in admissions:
                    u = str(adm.get("uhid") or "").strip()
                    if u in admission_map:
                        continue  # Already captured latest active admission

                    cust_type = str(adm.get("customer_type") or "General").strip()
                    adv_list = adm.get("advance_payments") or []
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

                    room_details = adm.get("room_details") or []
                    shifting_details = adm.get("roomShitingDetails") or []
                    active_room = next((r for r in room_details if isinstance(r, dict) and r.get("is_roomActive") is True), None)
                    active_shift = next((r for r in shifting_details if isinstance(r, dict) and r.get("is_roomActive") is True), None)
                    room_label = ""
                    if active_room:
                        room_label = f"{active_room.get('roomNo', '')} / Bed {active_room.get('bedNo', '')}"
                    elif active_shift:
                        room_label = f"{active_shift.get('newRoomNo', '')} / Bed {active_shift.get('newBedNo', '')}"

                    adm_dt = adm.get("admissionDateTime")
                    adm_dt_str = adm_dt.isoformat() if hasattr(adm_dt, "isoformat") else str(adm_dt or "")

                    admission_map[u] = {
                        "admitted": True,
                        "customer_type": cust_type,
                        "is_insurance": cust_type.lower() == "insurance",
                        "insurance_company": adm.get("insurance_company") or "",
                        "total_ip_advance": round(total_adv, 2),
                        "advance_payments": adv_list if isinstance(adv_list, list) else [],
                        "ipNumber": adm.get("ipNumber") or "",
                        "admissionDateTime": adm_dt_str,
                        "admittingDoctor": adm.get("admittingDoctor") or "",
                        "consultingDoctor": adm.get("consultingDoctor") or "",
                        "roomLabel": room_label,
                    }
            except Exception as e:
                print("Admission bulk prefetch error:", e)

        # 4. Bulk fetch Doctors from profile_collection (dbcollection.py)
        doctor_map = {}
        if all_doc_ids:
            try:
                emp_query_ids = list(all_doc_ids)
                for x in all_doc_ids:
                    if str(x).isdigit():
                        emp_query_ids.append(int(x))
                for emp in profile_collection.find(
                    {"employeeId": {"$in": emp_query_ids}},
                    {"employeeId": 1, "employeeName": 1, "_id": 0}
                ):
                    eid_str = str(emp.get("employeeId")).strip()
                    ename = emp.get("employeeName") or ""
                    if ename and not ename.lower().startswith("dr"):
                        ename = f"Dr. {ename}"
                    doctor_map[eid_str] = ename
            except Exception as e:
                print("profile_collection error:", e)

        # 4b. Bulk fetch Employee Names (Prepared by) from profile_collection (dbcollection.py)
        employee_map = {}
        if all_created_by_ids:
            try:
                emp_query_ids = list(all_created_by_ids)
                for x in all_created_by_ids:
                    if str(x).isdigit():
                        emp_query_ids.append(int(x))
                for emp in profile_collection.find(
                    {"employeeId": {"$in": emp_query_ids}},
                    {"employeeId": 1, "employeeName": 1, "_id": 0}
                ):
                    eid_str = str(emp.get("employeeId")).strip()
                    employee_map[eid_str] = emp.get("employeeName") or ""
            except Exception as e:
                print("profile_collection created_by bulk error:", e)

        # 5. Bulk fetch Pharmacy items & stock via common optimized function in dbcollection.py
        stock_outlet = target_outlet or outlet_code
        if isinstance(stock_outlet, dict) and "$in" in stock_outlet:
            stock_outlet = stock_outlet["$in"][0] if stock_outlet["$in"] else None
        elif isinstance(stock_outlet, (list, tuple)):
            stock_outlet = stock_outlet[0] if stock_outlet else None

        items_stock_data = get_pharmacy_items_with_stock(
            hospital_code=hospital_code,
            branch_code=branch_code,
            outlet_code=stock_outlet,
            item_ids=all_item_ids
        )

        # =========================================
        # 6. IN-MEMORY ASSEMBLY (Instant)
        # =========================================
        final_data = []
        room_cache = {}
        ins_cache = {}

        for bill in serialized_data:
            b_id = bill.get("Bill_id")
            uhid_str = str(bill.get("uhid") or "").strip()
            doc_id_str = str(bill.get("doctor_id") or "").strip()

            p_info = patient_map.get(uhid_str, {})
            p_name = p_info.get("patient_name") or bill.get("patientname") or ""
            p_addr = p_info.get("address") or ""
            p_mob  = p_info.get("mobile") or ""

            doc_name = doctor_map.get(doc_id_str) or get_doctor_name_by_id(doc_id_str)

            # Resolve Prepared by Employee Name using dbcollection.py get_employee_name_by_id
            cb_val = str(bill.get("created_by") or "").strip()
            prep_by = employee_map.get(cb_val)
            if not prep_by and cb_val:
                resolved = get_employee_name_by_id(cb_val)
                prep_by = resolved if resolved != "Unknown" else cb_val

            final_prepared_by = prep_by or cb_val

            bill["patient_details"] = {
                "patient_name": p_name,
                "address": p_addr,
                "mobile": p_mob,
                "doctor_name": doc_name,
                "prepared_by": final_prepared_by,
                "created_by_name": final_prepared_by,
            }
            bill["patient_name"] = p_name
            bill["address"] = p_addr
            bill["place"] = p_info.get("place", "")
            bill["mobile"] = p_mob
            bill["age"] = p_info.get("age") or str(bill.get("age") or "")
            bill["doctor_name"] = doc_name
            bill["created_by_id"] = bill.get("created_by")
            bill["created_by_name"] = final_prepared_by
            bill["prepared_by"] = final_prepared_by
            bill["created_by"] = final_prepared_by

            adm_info = admission_map.get(uhid_str, {})
            bill["admission_status"] = "ADMITTED" if adm_info.get("admitted") else "NOT ADMITTED"
            if not bill.get("inpatient_number") and adm_info.get("ipNumber"):
                bill["inpatient_number"] = adm_info.get("ipNumber")
            bill["admission_datetime"] = adm_info.get("admissionDateTime", "")
            b_mode = str(bill.get("billing_mode") or "").strip().upper()
            req_no = str(bill.get("request_no") or "").strip().upper()
            raw_room = str(bill.get("room_no") or bill.get("ward_name") or "").strip()
            is_ot = "OT" in b_mode or req_no.startswith("OT") or "OT" in raw_room.upper()
            if is_ot:
                if (not raw_room or raw_room in ["-", "—", "None", ""]) and (bill.get("inpatient_number") or uhid_str):
                    try:
                        q_sc = {"inpatient_number": bill.get("inpatient_number")} if bill.get("inpatient_number") else {"uhid": uhid_str}
                        sc_doc = hms_db["hospital_surgeryschedule"].find_one(q_sc, sort=[("created_date", -1)])
                        if sc_doc:
                            raw_room = sc_doc.get("ot_name") or sc_doc.get("theater") or sc_doc.get("ot_id") or ""
                    except Exception:
                        pass
                if raw_room and raw_room not in ["-", "—", "None", ""]:
                    room_lbl = raw_room if "OT" in raw_room.upper() else f"OT Request ({raw_room})"
                else:
                    room_lbl = "OT Request"
                bill["billing_mode"] = "OT REQUEST"
            else:
                room_lbl = raw_room if raw_room and raw_room not in ["-", "—", "None", ""] else (adm_info.get("roomLabel") or "")
                bill["billing_mode"] = "WARD REQUEST"
            bill["room_no"] = room_lbl
            bill["ward_name"] = bill.get("ward_name") or room_lbl

            # Resolve room_category, block, nursing_station from hospital_room in dbcollection.py (cached)
            if room_lbl not in room_cache:
                room_cache[room_lbl] = get_room_details(room_lbl, hospital_code=hospital_code, branch_code=branch_code)
            room_info = room_cache[room_lbl]

            bill["room_details"] = room_info
            bill["room_category"] = room_info.get("room_category") or ""
            bill["block"] = room_info.get("block") or ""
            bill["nursing_station"] = room_info.get("nursing_station") or ""
            if not bill.get("ward_name") or bill.get("ward_name") in ["-", "—", "None"]:
                bill["ward_name"] = room_info.get("room_category") or room_info.get("block") or room_info.get("nursing_station") or room_lbl
            bill["patient_details"]["room_category"] = bill["room_category"]
            bill["patient_details"]["block"] = bill["block"]
            bill["patient_details"]["nursing_station"] = bill["nursing_station"]
            bill["patient_details"]["room_details"] = room_info

            adm_cust_type = adm_info.get("customer_type") or ""
            pat_cust_type = p_info.get("customer_type") or ""
            bill_cust_type = bill.get("customer_type") or ""
            final_cust_type = adm_cust_type or pat_cust_type or bill_cust_type or "General"

            comp_code = p_info.get("company_code") or bill.get("company_code") or adm_info.get("company_code") or ""
            ins_key = (uhid_str, comp_code)
            if ins_key not in ins_cache:
                ins_cache[ins_key] = get_insurance_provider_by_patient(
                    uhid=uhid_str,
                    company_code=comp_code,
                    patient_obj=p_info
                )
            ins_details = ins_cache[ins_key]

            ins_company = ins_details.get("company_name") or adm_info.get("insurance_company") or bill.get("insurance_company") or ""
            is_ins = bool(
                ins_details.get("is_insurance")
                or final_cust_type.lower() == "insurance"
                or adm_info.get("is_insurance")
                or ins_company
            )

            if is_ins:
                final_cust_type = "Insurance"

            bill["customer_type"] = final_cust_type
            bill["is_insurance"] = is_ins
            bill["insurance_company"] = ins_company
            bill["company_code"] = ins_details.get("company_code") or comp_code
            bill["patient_details"]["customer_type"] = final_cust_type
            bill["patient_details"]["insurance_company"] = ins_company
            bill["patient_details"]["company_code"] = bill["company_code"]
            bill["patient_details"]["is_insurance"] = is_ins
            bill["advance_payments"] = adm_info.get("advance_payments", [])
            bill["total_ip_advance"] = adm_info.get("total_ip_advance", 0.0)

            items = bill_items_map.get(str(bill.get("_id"))) or bill_items_map.get(b_id, [])
            mapped_items = []
            is_completed_bill = str(bill.get("billing_status", "")).strip().lower() in ["billed", "paid", "completed"]

            for item in items:
                if not isinstance(item, dict) or item.get("is_deleted") or item.get("deleted_is"):
                    continue

                # 1. Total requested quantity & already dispatched quantity
                orig_qty = float(item.get("qty") or item.get("quantity") or 0)
                disp_qty = float(item.get("dispatched_qty", 0) or 0)
                pending_qty = max(0.0, orig_qty - disp_qty)

                # 2. For active pending/processing bills, fully dispatched items should NOT be displayed again
                if not is_completed_bill:
                    if orig_qty > 0 and pending_qty <= 0:
                        continue

                stock_info = resolve_medicine_stock_details(item, items_stock_data)

                clean_orig = int(orig_qty) if orig_qty.is_integer() else orig_qty
                clean_disp = int(disp_qty) if disp_qty.is_integer() else disp_qty
                clean_pending = int(pending_qty) if pending_qty.is_integer() else pending_qty

                mapped_items.append({
                    **item,
                    **stock_info,
                    "qty": clean_pending if not is_completed_bill else (clean_disp or clean_orig),
                    "requested_qty": clean_orig,
                    "dispatched_qty": clean_disp,
                    "pending_qty": clean_pending,
                })

            # If all items in this bill are fully dispatched, do not display the bill in pending chart
            if not mapped_items and not is_completed_bill:
                continue

            bill["medicine_items"] = mapped_items
            bill["medicine_particulars"] = mapped_items
            final_data.append(bill)

        return Response(
            {
                "status": "success",
                "hospital_code": hospital_code,
                "branch_code": branch_code,
                "outlet_code": target_outlet or outlet_code,
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

    # Prefer actively admitted record first
    admission = mongo_db["hospital_admission"].find_one({"uhid": uhid, "is_admitted": True})
    if not admission:
        admission = mongo_db["hospital_admission"].find_one({"uhid": uhid}, sort=[("_id", -1)])

    if not admission:
        return Response({
            "success": True,
            "admitted": False,
            "data": []
        })

    admitted = bool(admission.get("is_admitted", False))

    # ✅ Convert _id
    admission["_id"] = str(admission["_id"])

    # If insurance_company is empty but company_code exists, resolve name
    if not admission.get("insurance_company") and admission.get("company_code"):
        ins_name = get_insurance_company_name(admission.get("company_code"))
        if ins_name:
            admission["insurance_company"] = ins_name

    return Response({
        "success": True,
        "admitted": admitted,
        # ✅ Always return latest admission document so customer_type, insurance_company, ipNumber etc. are accessible
        "data": admission
    })




from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from django.views.decorators.csrf import csrf_exempt
from pymongo import MongoClient
import os
import time
from collections import defaultdict
from django.db.models import Q
from ..models import Patient, Billing
from ..serializers import PatientSerializer, BillingSerializer

_DOCTOR_CACHE_TIME = 0
_DOCTOR_ID_TO_NAME = {}
_DOCTOR_NAME_TO_ID = {}

def _get_doctor_lookup_maps():
    global _DOCTOR_CACHE_TIME, _DOCTOR_ID_TO_NAME, _DOCTOR_NAME_TO_ID
    now = time.time()
    if _DOCTOR_ID_TO_NAME and (now - _DOCTOR_CACHE_TIME) < 300:
        return _DOCTOR_ID_TO_NAME, _DOCTOR_NAME_TO_ID

    try:
        c = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        profiles = list(c["Global"]["backend_diagnostics_profile"].find(
            {}, {"employeeId": 1, "employeeName": 1, "designation": 1, "_id": 0}
        ))
        id_to_name = {}
        name_to_id = {}
        for p in profiles:
            eid = str(p.get("employeeId") or "").strip()
            ename = str(p.get("employeeName") or "").strip()
            if eid:
                id_to_name[eid] = ename
                try:
                    id_to_name[str(int(eid))] = ename
                except Exception:
                    pass
            if ename:
                name_to_id[ename.lower()] = eid

        _DOCTOR_ID_TO_NAME = id_to_name
        _DOCTOR_NAME_TO_ID = name_to_id
        _DOCTOR_CACHE_TIME = now
    except Exception as e:
        logger.error(f"Error loading doctor lookup maps: {e}")

    return _DOCTOR_ID_TO_NAME, _DOCTOR_NAME_TO_ID

def fast_resolve_doctor_pharmacy(doc_input):
    if not doc_input:
        return "", ""
    s = str(doc_input).strip()
    if not s:
        return "", ""

    id_to_name, name_to_id = _get_doctor_lookup_maps()

    # 1. Direct ID match
    if s in id_to_name:
        return s, id_to_name[s]
    try:
        num_s = str(int(s))
        if num_s in id_to_name:
            return s, id_to_name[num_s]
    except Exception:
        pass

    # 2. Exact name match
    s_lower = s.lower()
    if s_lower in name_to_id:
        eid = name_to_id[s_lower]
        return eid, id_to_name.get(eid, s)

    # 3. Substring match in loaded doctor profiles
    for ename_lower, eid in name_to_id.items():
        if s_lower in ename_lower or ename_lower in s_lower:
            return eid, id_to_name.get(eid, s)

    return s, s


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def patient_details(request):

    uhid      = request.GET.get('uhid')
    ip_number = request.GET.get('ip_number')
    mobile    = request.GET.get('mobile')

    name      = request.GET.get('name')

    query = Q()
    has_filter = False

    if uhid:
        clean_uhid = str(uhid).strip()
        if clean_uhid:
            uhid_cond = (
                Q(uhid__iexact=clean_uhid) |
                Q(uhid__iendswith=clean_uhid) |
                Q(uhid__iendswith=f'/{clean_uhid}')
            )

            if '/' in clean_uhid:
                parts = clean_uhid.split('/', 1)
                prefix, num_part = parts[0].strip(), parts[1].strip()
                if num_part.isdigit():
                    padded_num = num_part.zfill(6)
                    if prefix:
                        uhid_cond |= Q(uhid__iexact=f'{prefix}/{padded_num}')
                    else:
                        uhid_cond |= Q(uhid__iendswith=f'/{padded_num}')
            elif clean_uhid.isdigit():
                padded_num = clean_uhid.zfill(6)
                uhid_cond |= Q(uhid__iendswith=f'/{padded_num}')
                if len(clean_uhid) == 10:
                    uhid_cond |= (Q(mobilePhone__icontains=clean_uhid) | Q(mobilePhone__iendswith=clean_uhid))

            query &= uhid_cond
            has_filter = True

    if ip_number:
        clean_ip = str(ip_number).strip()
        if clean_ip:
            query &= Q(ip_number=clean_ip)
            has_filter = True

    name_str = (name or "").strip()
    mobile_str = (mobile or "").strip()

    if name_str and mobile_str and name_str == mobile_str:
        # Unified Name/Phone field search
        clean_digits = re.sub(r'\D', '', name_str)
        phone_q = Q(mobilePhone__icontains=name_str)
        if len(clean_digits) >= 10:
            phone_q |= Q(mobilePhone__icontains=clean_digits[-10:])

        query &= (
            Q(firstName__icontains=name_str) |
            Q(lastName__icontains=name_str) |
            phone_q
        )
        has_filter = True
    else:
        if name_str:
            query &= (Q(firstName__icontains=name_str) | Q(lastName__icontains=name_str))
            has_filter = True
        if mobile_str:
            clean_digits = re.sub(r'\D', '', mobile_str)
            if len(clean_digits) >= 10:
                query &= (Q(mobilePhone__icontains=mobile_str) | Q(mobilePhone__icontains=clean_digits[-10:]))
            else:
                query &= Q(mobilePhone__icontains=mobile_str)
            has_filter = True

    if not has_filter:
        return Response({
            "success": False,
            "message": "Please provide a search parameter (uhid, ip_number, mobile, or name)."
        }, status=status.HTTP_400_BAD_REQUEST)

    patients = Patient.objects.filter(query).order_by('-id')[:50]

    serializer   = PatientSerializer(patients, many=True)
    patient_data = serializer.data

    if not patient_data:
        return Response({
            "success": True,
            "data"   : []
        }, status=status.HTTP_200_OK)

    # ── High Performance Batch Queries ────────────────────────────────
    # 1. Batch Billing query (single SQL query for all patients)
    patient_ids = [int(p["id"]) for p in patient_data if p.get("id")]
    all_billings = list(Billing.objects.filter(patient_id__in=patient_ids).order_by('-billed_date'))
    billing_by_patient = defaultdict(list)
    for b in all_billings:
        billing_by_patient[b.patient_id].append(b)

    # 2. Batch Admissions query (single MongoDB query for all UHIDs)
    client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
    hms_db = client["HMS"]
    admission_collection = hms_db["hospital_admission"]

    uhids = [p["uhid"] for p in patient_data if p.get("uhid")]
    all_adms = list(admission_collection.find({"uhid": {"$in": uhids}}).sort([("_id", -1)]))
    adm_by_uhid = {}
    for adm in all_adms:
        u = adm.get("uhid")
        if u not in adm_by_uhid or (adm.get("is_admitted") and not adm_by_uhid[u].get("is_admitted")):
            adm_by_uhid[u] = adm

    # ── Step 3: Attach billing + doctor_name + admission_status (in-memory 0ms resolution) ──
    for patient in patient_data:
        patient_id = int(patient["id"])
        bills = billing_by_patient.get(patient_id, [])
        billing_list = []

        # Keep top 5 latest bills for lightweight and instant payload
        for bill in bills[:5]:
            raw_doc_id = bill.doctor_id
            resolved_id, doc_name = fast_resolve_doctor_pharmacy(raw_doc_id)
            billing_list.append({
                "bill_number"    : bill.bill_number,
                "doctor_id"      : resolved_id or raw_doc_id,
                "doctor_name"    : doc_name or raw_doc_id,
                "raw_doctor_id"  : raw_doc_id,
                "total_fees"     : str(bill.total_fees),
                "payment_status" : bill.payment_status,
                "billed_date"    : bill.billed_date,
            })

        patient["billing"] = billing_list

        # Resolve patient's default doctor
        pat_doc_input = patient.get("doctorName") or patient.get("doctor_id")
        if pat_doc_input:
            resolved_pat_doc_id, pat_doc_name = fast_resolve_doctor_pharmacy(pat_doc_input)
            patient["doctor_id"] = resolved_pat_doc_id or patient.get("doctor_id") or ""
            if not patient.get("doctor_name"):
                patient["doctor_name"] = pat_doc_name or pat_doc_input

        # Live admission status check
        pat_uhid = patient.get("uhid")
        adm = adm_by_uhid.get(pat_uhid)
        is_adm = bool(adm.get("is_admitted", False)) if adm else False
        patient["is_admitted"] = is_adm
        patient["admission_status"] = "Admitted" if is_adm else "Not Admitted"
        if adm:
            patient["ip_number"] = adm.get("ipNumber") or adm.get("ip_number") or patient.get("ip_number") or ""
            consulting_doc = adm.get("consultingDoctor") or adm.get("admittingDoctor") or ""
            patient["consulting_doctor"] = consulting_doc
            res_c_id, res_c_name = fast_resolve_doctor_pharmacy(consulting_doc)
            patient["consulting_doctor_id"] = res_c_id or ""
            patient["consulting_doctor_name"] = res_c_name or consulting_doc

            # Customer type from admission (e.g. INSURANCE, General)
            adm_cust_type = (adm.get("customer_type") or "").strip()
            if adm_cust_type:
                patient["customer_type"] = adm_cust_type

            # Insurance company from admission or company_code
            ins_comp = adm.get("insurance_company")
            if not ins_comp and adm.get("company_code"):
                ins_comp = get_insurance_company_name(adm.get("company_code"))
            if not ins_comp and patient.get("company_code"):
                ins_comp = get_insurance_company_name(patient.get("company_code"))
            if ins_comp:
                patient["insurance_company"] = ins_comp
            if adm.get("company_code"):
                patient["company_code"] = adm.get("company_code")
        else:
            if patient.get("company_code") and not patient.get("insurance_company"):
                patient["insurance_company"] = get_insurance_company_name(patient.get("company_code")) or ""

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
        try:
            b_id_int = int(Bill_id)
        except (ValueError, TypeError):
            b_id_int = None
        id_clause = {"$in": [b_id_int, str(Bill_id)]} if b_id_int is not None else str(Bill_id)

        bill_query = {
            "Bill_id":       id_clause,
            "hospital_code": hospital_code,
            "branch_code":   branch_code,
        }
        if outlet_code:
            if isinstance(outlet_code, (list, tuple)):
                bill_query["outlet_code"] = {"$in": list(outlet_code)}
            else:
                bill_query["outlet_code"] = outlet_code

        bill = bill_collection.find_one(bill_query)
        if not bill:
            bill = bill_collection.find_one({
                "Bill_id":       id_clause,
                "hospital_code": hospital_code,
                "branch_code":   branch_code,
            })

        if not bill:
            return Response({"error": "Bill not found"}, status=404)

        medicines        = bill.get("medicine_particulars", [])
        updated_medicines = []
        substituted      = False

        for med in medicines:
            if not isinstance(med, dict):
                continue
            m_iid = med.get("item_id")
            m_bn  = str(med.get("batch_number") or med.get("batch_no") or med.get("batch") or "").strip()
            target_bn = str(batch_number or "").strip()
            is_match = False
            if m_iid is not None and item_id is not None and str(m_iid) == str(item_id):
                if not target_bn or not m_bn or target_bn.lower() in ["none", "null", "n/a", ""]:
                    is_match = True
                elif m_bn.lower() == target_bn.lower():
                    is_match = True

            if is_match and not substituted:
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
                substitute_item_clean = {k: v for k, v in substitute_item.items() if k != "item_name"}
                substitute_item_clean["edit_history"] = med_edit_history
                # Carry forward prescription details (dosage, noOfDays, dose, doseunit, instruction, etc.)
                for field in ["dosage", "noOfDays", "no_of_days", "dose", "doseunit", "doseUnit", "instruction", "route", "remark", "dispatched_qty"]:
                    if med.get(field) is not None and substitute_item_clean.get(field) is None:
                        substitute_item_clean[field] = med.get(field)
                updated_medicines.append(substitute_item_clean)   # ← substitute replaces original
            else:
                med_clean = {k: v for k, v in med.items() if k != "item_name"}
                updated_medicines.append(med_clean)               # ← all others unchanged

        if not substituted:
            return Response({"error": "Matching medicine not found in bill"}, status=404)

        # ── Persist ───────────────────────────────────────────────────
        sub_outlet = bill.get("outlet_code") or (outlet_code[0] if isinstance(outlet_code, (list, tuple)) and outlet_code else (outlet_code or "OLET001"))
        bill_collection.update_one(
            {"_id": bill["_id"]},
            {
                "$set": {
                    "medicine_particulars": updated_medicines,
                    "lastmodified_date":    datetime.utcnow(),
                    "lastmodified_context": {
                        "hospital_code": hospital_code,
                        "branch_code":   branch_code,
                        "outlet_code":   sub_outlet,
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
        try:
            b_id_int = int(Bill_id)
        except (ValueError, TypeError):
            b_id_int = None
        id_clause = {"$in": [b_id_int, str(Bill_id)]} if b_id_int is not None else str(Bill_id)

        existing_bill = bill_collection.find_one({"Bill_id": id_clause})
        if not existing_bill:
            return Response({"error": "Bill not found"}, status=404)
        if existing_bill.get("billing_status") == "Cancelled" or existing_bill.get("is_cancelled") is True or existing_bill.get("is_deleted") is True:
            return Response({"error": "Cannot convert a cancelled ward request / bill to Processing"}, status=400)

        result = bill_collection.update_one(
            {"Bill_id": id_clause},
            {
                "$set": {
                    "billing_status": "Processing",
                    "is_active": True,
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
        bill = None

        # 1. Exact lookup by MongoDB _id (avoids collision if duplicate Bill_id exists)
        mongo_id = data.get("_id") or data.get("record_id") or data.get("mongo_id")
        if mongo_id:
            try:
                from bson import ObjectId
                m_str = str(mongo_id).strip()
                if ObjectId.is_valid(m_str):
                    bill = bill_collection.find_one({"_id": ObjectId(m_str)})
            except Exception:
                pass

        if not bill:
            try:
                b_id_int = int(Bill_id)
            except (ValueError, TypeError):
                b_id_int = None
            id_clause = {"$in": [b_id_int, str(Bill_id)]} if b_id_int is not None else str(Bill_id)

            bill_query = {
                "Bill_id":       id_clause,
                "hospital_code": hospital_code,
                "branch_code":   branch_code,
            }
            if outlet_code:
                if isinstance(outlet_code, (list, tuple)):
                    bill_query["outlet_code"] = {"$in": list(outlet_code)}
                else:
                    bill_query["outlet_code"] = outlet_code

            # 2. Prioritize currently active ("Pending" or "Processing") bill
            active_q = dict(bill_query)
            active_q["billing_status"] = {"$in": ["Pending", "Processing"]}
            if data.get("is_ward_request"):
                active_q["is_ward_request"] = True
            if data.get("uhid"):
                active_q["uhid"] = str(data.get("uhid")).strip()

            bill = bill_collection.find_one(active_q, sort=[("created_date", -1)])

            # 3. If no active pending bill found with outlet match, check across outlets with status active
            if not bill:
                fallback_active_q = {
                    "Bill_id":       id_clause,
                    "hospital_code": hospital_code,
                    "branch_code":   branch_code,
                    "billing_status": {"$in": ["Pending", "Processing"]}
                }
                if data.get("uhid"):
                    fallback_active_q["uhid"] = str(data.get("uhid")).strip()
                bill = bill_collection.find_one(fallback_active_q, sort=[("created_date", -1)])

            # 4. Standard fallback
            if not bill:
                bill = bill_collection.find_one(bill_query, sort=[("created_date", -1)])

            if not bill:
                bill = bill_collection.find_one({
                    "Bill_id":       id_clause,
                    "hospital_code": hospital_code,
                    "branch_code":   branch_code,
                }, sort=[("created_date", -1)])

        if not bill:
            return Response(
                {"error": "Bill not found"},
                status=404
            )

        if bill.get("billing_status") == "Cancelled" or bill.get("is_cancelled") is True or bill.get("is_deleted") is True:
            return Response(
                {"error": "Cannot finalize or update status of a cancelled ward request / bill"},
                status=400
            )

        bill_outlet = bill.get("outlet_code") or (
            outlet_code[0] if isinstance(outlet_code, (list, tuple)) and outlet_code else (outlet_code or "OLET001")
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
            customer_type = ""

            try:
                admission_doc = mongo_db["hospital_admission"].find_one({
                    "ipNumber": inpatient_number,
                    "hospital_code": hospital_code
                })
                if not admission_doc:
                    admission_doc = mongo_db["hospital_admission"].find_one({
                        "ipNumber": inpatient_number
                    })

                if admission_doc:
                    customer_type = str(admission_doc.get("customer_type") or admission_doc.get("customerType") or "").strip()

                if not customer_type:
                    patient_details_map = bill.get("patient_details") or {}
                    customer_type = str(
                        bill.get("customer_type") or
                        data.get("customer_type") or
                        patient_details_map.get("customer_type") or
                        patient_details_map.get("customerType") or
                        ""
                    ).strip()

                # ── RULE: Only applicable for customer_type: "GENERAL IP" ───────
                # Other customer types (General, Insurance, etc.) are NOT applicable for this concept.
                is_general_ip = customer_type.upper() == "GENERAL IP"

                if is_general_ip:
                    if admission_doc:
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

                    if advance_check_blocked or ip_advance is None or ip_advance <= 0:
                        return Response(
                            {
                                "error": "No Active IP Advance found for this patient. Billing not allowed.",
                                "customer_type": customer_type,
                            },
                            status=400
                        )

                    existing_billed_cursor = bill_collection.find({
                        "inpatient_number": inpatient_number,
                        "billing_status":   "Billed",
                        "is_deleted":       {"$ne": True},
                        "Bill_id":          {"$ne": Bill_id},
                    })
                    existing_total = sum(
                        float(b.get("total_amount", 0) or 0)
                        for b in existing_billed_cursor
                    )

                    cumulative_total = round(existing_total + total_amount_to_use, 2)

                    print(
                        f"IP Advance check | customer_type={customer_type} "
                        f"| ip_advance={ip_advance} | existing_billed={existing_total} "
                        f"| current_payable={total_amount_to_use} | cumulative={cumulative_total}"
                    )

                    if cumulative_total > ip_advance:
                        return Response(
                            {
                                "error":             "Billing Exceeds From IP Advance",
                                "customer_type":      customer_type,
                                "is_insurance":       False,
                                "ip_advance":         ip_advance,
                                "existing_billed":    existing_total,
                                "current_payable":    total_amount_to_use,
                                "cumulative_total":   cumulative_total,
                            },
                            status=400
                        )

            except Exception as adm_err:
                print("Warning: could not fetch admission advance —", adm_err)

        # =====================================================
        # ✅ DISPATCH TRACKING & RETRY GUARD (For Ward Requests)
        # =====================================================
        now_ts = datetime.utcnow()
        existing_bm = str(bill.get("billing_mode") or data.get("billing_mode") or "").strip().upper()
        req_no = str(bill.get("request_no") or data.get("request_no") or "").strip().upper()
        is_ward = bool(
            bill.get("is_ward_request")
            or data.get("is_ward_request")
            or existing_bm in ["WARD REQUEST", "OT REQUEST", "DISCHARGE MEDICINE"]
            or req_no.startswith("MR")
            or req_no.startswith("OT")
        )
        orig_particulars = bill.get("medicine_particulars", [])

        # Build lookup of actual items billed in this transaction
        billed_items_map = {}
        for med in medicines_to_use:
            if not isinstance(med, dict) or med.get("is_deleted"):
                continue
            m_iid = med.get("item_id")
            m_qty = float(med.get("qty") or med.get("quantity") or 0)
            if m_iid is not None and m_qty > 0:
                billed_items_map[str(m_iid)] = m_qty
                try:
                    billed_items_map[int(m_iid)] = m_qty
                except Exception:
                    pass

        # Idempotency Guard: ONLY trigger if bill was ALREADY fully finalized/billed and has zero pending items.
        # NEVER block active "Processing" or partial dispatches!
        is_already_billed = str(bill.get("billing_status", "")).strip().lower() in ["billed", "paid", "completed"] and bill.get("is_dispatched") is True
        if is_ward and is_already_billed and bill.get("bill_no") and bill.get("lastmodified_date"):
            try:
                last_time = bill.get("lastmodified_date")
                if isinstance(last_time, str):
                    last_time = datetime.fromisoformat(last_time)
                sec_diff = (now_ts - last_time).total_seconds()
                if 0 <= sec_diff <= 3:
                    doc_id = bill.get("doctor_id") or data.get("doctor_id")
                    doc_name = get_employee_name_by_id(doc_id) if doc_id else ""
                    if doc_name and doc_name != "Unknown" and not doc_name.lower().startswith("dr"):
                        doc_name = f"Dr. {doc_name}"
                    elif doc_name == "Unknown":
                        doc_name = ""
                    return Response({
                        "status": "success",
                        "message": f"Bill #{bill.get('bill_no')} already finalized",
                        "bill_no": bill.get("bill_no"),
                        "Bill_id": bill.get("Bill_id"),
                        "bill_date": to_utc_iso(now_ts),
                        "doctor_id": doc_id,
                        "doctor_name": doc_name,
                    }, status=status.HTTP_200_OK)
            except Exception:
                pass

        # Calculate pending quantity and cumulative dispatched quantity
        all_items_fully_dispatched = True
        updated_orig_meds = []
        has_prior_dispatches = any(float(m.get("dispatched_qty", 0) or 0) > 0 for m in orig_particulars)

        if is_ward:
            for orig_m in orig_particulars:
                if not isinstance(orig_m, dict):
                    continue
                m_iid = orig_m.get("item_id")
                # Check if item is deleted either in orig or in frontend payload
                is_del = (
                    orig_m.get("deleted_is") is True or
                    orig_m.get("is_deleted") is True or
                    any((str(dm.get("item_id")) == str(m_iid) and (dm.get("deleted_is") or dm.get("is_deleted"))) for dm in medicines_to_use)
                )
                if is_del:
                    continue  # Deleted items do NOT count towards pending dispatch!

                orig_req_qty = float(orig_m.get("requested_qty") or orig_m.get("qty") or orig_m.get("quantity") or 0)
                prev_disp = float(orig_m.get("dispatched_qty", 0) or 0)

                # Actual quantity entered and billed right now
                billed_qty = float(
                    billed_items_map.get(m_iid)
                    or billed_items_map.get(str(m_iid))
                    or (billed_items_map.get(int(m_iid)) if str(m_iid).isdigit() else 0)
                    or 0
                )

                # Ensure dispatched quantities never exceed requested quantity
                new_disp = min(orig_req_qty, prev_disp + billed_qty) if orig_req_qty > 0 else (prev_disp + billed_qty)
                pending_qty = max(0.0, orig_req_qty - new_disp)

                if pending_qty > 0:
                    all_items_fully_dispatched = False

                u_item = dict(orig_m)
                u_item["qty"] = orig_req_qty            # Keep field qty as qty
                if "quantity" in u_item:
                    del u_item["quantity"]
                u_item["dispatched_qty"] = new_disp     # Actual cumulative dispatched quantity
                u_item.pop("pending_qty", None)
                u_item.pop("requested_qty", None)
                u_item.pop("last_billed_qty", None)
                updated_orig_meds.append(u_item)

        # =====================================================
        # ✅ GENERATE BILL NO
        # =====================================================
        is_save_later_only = bool(data.get("save_later_only")) or (is_ward and not billed_items_map)

        fy = get_financial_year()
        new_bill_no = bill.get("bill_no")
        bill_date   = bill.get("bill_date")
        if not is_save_later_only:
            if not new_bill_no or str(new_bill_no).startswith("MR"):
                new_bill_no = get_next_pharmacy_bill_no(
                    outlet_code=bill_outlet,
                    fy=fy,
                    db_instance=mongo_db
                )
                bill_date = datetime.utcnow()
            elif not bill_date:
                bill_date = datetime.utcnow()

        # =====================================================
        # ✅ PREPARE MEDICINE HISTORY
        # =====================================================
        # Build a map of DB medicines so we can detect qty changes
        db_medicines_map = {
            (str(m.get("item_id")), str(m.get("batch_number", ""))): m
            for m in bill.get("medicine_particulars", [])
        }

        medicine_history = []

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

            dosage_val = med.get("dosage") or (db_med.get("dosage") if db_med else "") or ""
            no_days_val = med.get("noOfDays") or med.get("no_of_days") or (db_med.get("noOfDays") if db_med else "") or ""
            dose_val = med.get("dose") or (db_med.get("dose") if db_med else "") or ""
            doseunit_val = med.get("doseunit") or med.get("doseUnit") or (db_med.get("doseunit") if db_med else "") or ""
            instruction_val = med.get("instruction") or (db_med.get("instruction") if db_med else "") or ""
            route_val = med.get("route") or (db_med.get("route") if db_med else "") or ""

            med_entry = {
                "item_id":          item_id,
                "batch_number":     bn_val,
                "qty":              qty,
                "price":            price,
                "calculated_price": calculated_price,
                "discount":         med.get("discount", 0),
                "tax":              med.get("tax", 0),
                "mrp":              med.get("mrp"),
                "expiry_date":      med.get("expiry_date"),
                "dosage":           dosage_val,
                "noOfDays":         no_days_val,
                "dose":             dose_val,
                "doseunit":         doseunit_val,
                "instruction":      instruction_val,
                "route":            route_val,
                "action":           "finalized",
                "edited_by":        employee_id,
                "edited_at":        now_ts,
            }
            if med_is_consumable:
                med_entry["is_consumable_items"] = True

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

            if qty <= 0:
                continue

            result = stock_collection.update_one(
                {
                    "item_id":       item_id,
                    "batch_number":  batch,
                    "hospital_code": hospital_code,
                    "branch_code":   branch_code,
                    "outlet_code":   bill_outlet,
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
                "outlet_code":   bill_outlet,
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

            "billed_id":            employee_id,

            # ✅ NEW: mark as dispatched when billing is finalised
            "is_dispatched":        True,

            "lastmodified_date":    now_ts,
            "lastmodified_by":      employee_id,

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
        # Determine if patient is an insurance patient
        cust_type_val = str(
            data.get("customer_type")
            or bill.get("customer_type")
            or (bill.get("patient_details") or {}).get("customer_type")
            or ""
        ).strip()
        ins_comp_val = str(
            data.get("insurance_company")
            or bill.get("insurance_company")
            or (bill.get("patient_details") or {}).get("insurance_company")
            or ""
        ).strip()
        is_insurance_patient = bool(
            data.get("is_insurance")
            or bill.get("is_insurance")
            or (bill.get("patient_details") or {}).get("is_insurance")
            or cust_type_val.lower() == "insurance"
            or ins_comp_val
        )

        # 🛑 Rule: billing_mode should NEVER change from WARD REQUEST or OT REQUEST or DISCHARGE MEDICINE!
        existing_bm = str(bill.get("billing_mode") or data.get("billing_mode") or "").strip().upper()
        req_no = str(bill.get("request_no") or data.get("request_no") or "").strip().upper()
        is_ward = is_ward or bill.get("is_ward_request") or data.get("is_ward_request") or existing_bm == "WARD REQUEST" or req_no.startswith("MR")
        is_ot = existing_bm == "OT REQUEST" or req_no.startswith("OT")
        is_discharge = "DISCHARGE" in existing_bm

        if is_ot:
            set_payload["billing_mode"] = "OT REQUEST"
        elif is_discharge:
            set_payload["billing_mode"] = "DISCHARGE MEDICINE"
        elif is_ward:
            set_payload["billing_mode"] = "WARD REQUEST"
        elif existing_bm and existing_bm not in ["ESTIMATE", "DIRECT"]:
            set_payload["billing_mode"] = existing_bm
        elif is_insurance_patient:
            set_payload["billing_mode"] = "IP CREDIT"
        elif data.get("billing_mode"):
            set_payload["billing_mode"] = data.get("billing_mode")

        raw_final_pm = data.get("payment_mode") or data.get("paymentMode")
        if is_insurance_patient:
            set_payload["payment_mode"] = "Credit"
            set_payload["is_insurance"] = True
            set_payload["customer_type"] = "Insurance"
        elif raw_final_pm:
            set_payload["payment_mode"] = "Credit" if str(raw_final_pm).strip().lower() == "credit" else "Cash"

        # Resolve patient name and age
        resolved_p_name = (
            bill.get("patientname")
            or bill.get("patient_name")
            or data.get("patient_name")
            or data.get("patientname")
        )
        if not resolved_p_name and bill.get("uhid"):
            try:
                p_doc = mongo_db["hospital_patient"].find_one({"uhid": bill.get("uhid")})
                if p_doc:
                    sal = (p_doc.get("salutation") or "").strip()
                    fn  = (p_doc.get("firstName") or "").strip()
                    ln  = (p_doc.get("lastName") or "").strip()
                    resolved_p_name = " ".join(f"{sal} {fn} {ln}".split()).strip()
            except Exception:
                pass

        resolved_age = bill.get("age") or data.get("age")

        # Sanitize medicines so ALL normal billing fields are stored (taxable_value, product_value, CGST, SGST, discount, total, etc.)
        sanitized_meds = sanitize_medicines(medicines_to_use)

        if is_ward:
            # Build lookup of billed items from sanitized_meds
            billed_map = {}
            for sm in sanitized_meds:
                m_iid = sm.get("item_id")
                if m_iid is not None:
                    billed_map[str(m_iid)] = sm
                    try:
                        billed_map[int(m_iid)] = sm
                    except Exception:
                        pass

            final_particulars = []
            handled_iids = set()

            for orig_m in orig_particulars:
                if not isinstance(orig_m, dict):
                    continue
                m_iid = orig_m.get("item_id")
                handled_iids.add(str(m_iid))
                try:
                    handled_iids.add(int(m_iid))
                except Exception:
                    pass

                # Check if item was deleted in frontend or marked deleted
                is_del = (
                    orig_m.get("deleted_is") is True or
                    orig_m.get("is_deleted") is True or
                    any((str(dm.get("item_id")) == str(m_iid) and (dm.get("deleted_is") or dm.get("is_deleted"))) for dm in sanitized_meds)
                )

                if is_del:
                    item_entry = dict(orig_m)
                    item_entry["deleted_is"] = True
                    item_entry["is_deleted"] = True
                    item_entry.pop("requested_qty", None)
                    item_entry.pop("pending_qty", None)
                    item_entry.pop("last_billed_qty", None)
                    eh = item_entry.pop("edit_history", None) or []
                    item_entry["edit_history"] = eh
                    final_particulars.append(item_entry)
                    continue

                orig_req_qty = float(orig_m.get("requested_qty") or orig_m.get("qty") or orig_m.get("quantity") or 0)
                prev_disp = float(orig_m.get("dispatched_qty", 0) or 0)

                billed_sm = (
                    billed_map.get(m_iid)
                    or billed_map.get(str(m_iid))
                    or (billed_map.get(int(m_iid)) if str(m_iid).isdigit() else None)
                )
                billed_qty = float(billed_sm.get("qty", 0)) if billed_sm else 0.0

                new_disp = min(orig_req_qty, prev_disp + billed_qty) if orig_req_qty > 0 else (prev_disp + billed_qty)
                pending_qty = max(0.0, orig_req_qty - new_disp)

                if billed_sm and billed_qty > 0:
                    # Item was billed: copy full billing fields (pricing, batch, tax) and set quantities
                    item_entry = dict(billed_sm)
                    item_entry["qty"] = orig_req_qty if orig_req_qty > 0 else (prev_disp + billed_qty)
                    item_entry["dispatched_qty"] = new_disp
                    unit_mrp = float(item_entry.get("mrp") or item_entry.get("price") or 0)
                    if unit_mrp > 0 and new_disp > 0:
                        calc_p = round(unit_mrp * new_disp, 2)
                        item_entry["calculated_price"] = calc_p
                        cgst_p = float(item_entry.get("CGST_Percentage") or 0)
                        sgst_p = float(item_entry.get("SGST_Percentage") or 0)
                        tot_gst = cgst_p + sgst_p
                        p_val = round(calc_p / (1.0 + tot_gst / 100.0), 4) if tot_gst > 0 else calc_p
                        item_entry["product_value"] = p_val
                        disc_a = float(item_entry.get("discount_amount") or 0)
                        taxable_val = max(0.0, p_val - disc_a)
                        item_entry["taxable_value"] = taxable_val
                        if cgst_p > 0:
                            item_entry["CGST_Amt"] = round((taxable_val * cgst_p) / 100.0, 2)
                        if sgst_p > 0:
                            item_entry["SGST_Amt"] = round((taxable_val * sgst_p) / 100.0, 2)
                        item_entry["total"] = calc_p
                else:
                    # Item was NOT billed in this transaction (e.g. out of stock): preserve original request item with updated dispatch
                    item_entry = dict(orig_m)
                    item_entry["qty"] = orig_req_qty
                    item_entry["dispatched_qty"] = prev_disp

                # Ensure unwanted intermediate fields are not stored
                item_entry.pop("requested_qty", None)
                item_entry.pop("pending_qty", None)
                item_entry.pop("last_billed_qty", None)

                # Store edit_history after dispatched_qty
                eh = item_entry.pop("edit_history", None) or []
                item_entry["edit_history"] = eh

                final_particulars.append(item_entry)

            # Also include any newly added items (e.g. substitutes or additional items) not in orig_particulars
            for sm in sanitized_meds:
                sm_iid = sm.get("item_id")
                if sm_iid not in handled_iids and str(sm_iid) not in handled_iids:
                    item_entry = dict(sm)
                    if sm.get("deleted_is") or sm.get("is_deleted"):
                        item_entry["deleted_is"] = True
                        item_entry["is_deleted"] = True
                    else:
                        b_qty = float(sm.get("qty", 0))
                        item_entry["qty"] = b_qty
                        item_entry["dispatched_qty"] = b_qty
                    item_entry.pop("requested_qty", None)
                    item_entry.pop("pending_qty", None)
                    item_entry.pop("last_billed_qty", None)
                    eh = item_entry.pop("edit_history", None) or []
                    item_entry["edit_history"] = eh
                    final_particulars.append(item_entry)

            set_payload["medicine_particulars"] = final_particulars
            if is_save_later_only or not all_items_fully_dispatched:
                set_payload["billing_status"] = "Processing"
                set_payload["is_dispatched"] = False
            else:
                set_payload["billing_status"] = "Billed"
                set_payload["is_dispatched"] = True
        else:
            for sm in sanitized_meds:
                b_qty = float(sm.get("qty", 0))
                sm["dispatched_qty"] = b_qty
                sm.pop("requested_qty", None)
                sm.pop("pending_qty", None)
                sm.pop("last_billed_qty", None)
                eh = sm.pop("edit_history", None) or []
                sm["edit_history"] = eh
            set_payload["medicine_particulars"] = sanitized_meds
            set_payload["billing_status"]       = "Billed"
            set_payload["is_dispatched"]        = True

        if new_bill_no and not is_save_later_only:
            set_payload["bill_no"]              = new_bill_no
        if bill_date and not is_save_later_only:
            set_payload["bill_date"]            = bill_date
        set_payload["billed_id"]            = employee_id
        set_payload["lastmodified_date"]    = now_ts
        set_payload["lastmodified_by"]      = employee_id
        cumulative_bill_total = sum(
            float(it.get("total") or it.get("calculated_price") or 0)
            for it in (final_particulars if is_ward else sanitized_meds)
            if not it.get("is_deleted") and not it.get("deleted_is")
        )
        if is_ward and cumulative_bill_total > 0:
            rounded_net = float(round(cumulative_bill_total))
            set_payload["total_amount"]         = round(cumulative_bill_total, 2)
            set_payload["net_amount"]           = rounded_net
            set_payload["round_off"]            = round(rounded_net - cumulative_bill_total, 2)
        else:
            set_payload["total_amount"]         = total_amount_to_use
            set_payload["net_amount"]           = float(frontend_net_amount if frontend_net_amount is not None else total_amount_to_use)

        # Do NOT save patient details when UHID is present (dynamically compared & displayed from patient collection by UHID).
        # Do NOT save billed_bill_no, converted_bill_no, or dispatch_history.
        unset_payload = {
            "billed_bill_no": "",
            "converted_bill_no": "",
            "dispatch_history": ""
        }
        uhid_val = str(bill.get("uhid") or data.get("uhid") or "").strip()
        has_uhid = bool(uhid_val)
        if has_uhid:
            unset_payload["patientname"] = ""
            unset_payload["patient_name"] = ""
            unset_payload["age"] = ""
        else:
            if resolved_p_name:
                set_payload["patient_name"] = resolved_p_name
            if resolved_age:
                set_payload["age"] = resolved_age

        bill_collection.update_one(
            {"_id": bill["_id"]},
            {
                "$set": set_payload,
                "$unset": unset_payload
            }
        )

        try:
            PharmacyBilling.objects.filter(Bill_id=int(bill.get("Bill_id"))).update(
                billing_status=set_payload.get("billing_status", "Billed"),
                billed_id=employee_id,
                bill_no=new_bill_no,
                bill_date=bill_date,
                payment_mode=set_payload.get("payment_mode", "Cash"),
                total_amount=set_payload.get("total_amount", float(bill.get("total_amount", 0))),
                net_amount=set_payload.get("net_amount", float(bill.get("net_amount", 0)))
            )
        except Exception:
            pass

        final_returned_bill_id = bill.get("Bill_id")

        # Resolve doctor name and employee name
        doc_id = bill.get("doctor_id") or data.get("doctor_id")
        doc_name = get_employee_name_by_id(doc_id) if doc_id else ""
        if doc_name and doc_name != "Unknown" and not doc_name.lower().startswith("dr"):
            doc_name = f"Dr. {doc_name}"
        elif doc_name == "Unknown":
            doc_name = ""

        emp_id = employee_id or bill.get("created_by")
        emp_name = get_employee_name_by_id(emp_id) if emp_id else ""
        if emp_name == "Unknown":
            emp_name = ""

        res_msg = "Prescriptions saved for later in Medicine Chart" if is_save_later_only else "Bill finalized, dispatched & stock updated"

        # =====================================================
        # ✅ RESPONSE
        # =====================================================
        return Response({

            "status":          "success",

            "message":         res_msg,

            "bill_no":         new_bill_no,

            "Bill_id":         final_returned_bill_id,

            "bill_date":       to_utc_iso(bill_date),

            "doctor_id":       doc_id,

            "doctor_name":     doc_name,

            "created_by":      emp_id,

            "created_by_name": emp_name,

            "billed_id":       employee_id,

            "billed_name":     emp_name,

            "employee_name":   emp_name,

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
        adm_data["dob"]                  = pt.dob.isoformat() if getattr(pt, "dob", None) else ""
        adm_data["insuranceCompanyName"] = ins_name
        adm_data["company_code"]         = company_code
    except Exception:
        pass
    return adm_data



@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def searchby_ip(request):

    data = getattr(request, "data", {}) if isinstance(getattr(request, "data", None), dict) else {}

    employee_id   = (
        request.headers.get("User-Id")
        or request.META.get("HTTP_USER_ID")
        or request.GET.get("employee_id")
        or data.get("auth-user-id")
    )
    hospital_code = (
        request.headers.get("Hospital-Code")
        or request.META.get("HTTP_HOSPITAL_CODE")
        or request.GET.get("hospital_code")
        or data.get("auth-hospital-code")
    )
    branch_code   = (
        request.headers.get("Branch-Code")
        or request.META.get("HTTP_BRANCH_CODE")
        or request.GET.get("branch_code")
        or data.get("auth-branch-code")
    )

    # ── GET ───────────────────────────────────────────────────────────────────
    if request.method == 'GET':
        try:
            from_date_str = request.GET.get('from_date',        '').strip()
            to_date_str   = request.GET.get('to_date',          '').strip()
            status_filter = request.GET.get('status',           '').strip()
            doctor_filter = request.GET.get('admitting_doctor', '').strip()
            ip_filter     = request.GET.get('ip_number',        '').strip()

            from_date = to_date = None
            if from_date_str:
                try: from_date = datetime.strptime(from_date_str, '%Y-%m-%d').date()
                except: pass
            if to_date_str:
                try: to_date = datetime.strptime(to_date_str, '%Y-%m-%d').date()
                except: pass

            q = Q()
            if hospital_code:
                q &= Q(hospital_code=hospital_code)
            if branch_code:
                q &= Q(branch_code=branch_code)

            if ip_filter:
                if "/" in ip_filter:
                    q &= Q(ipNumber__iexact=ip_filter)
                else:
                    q &= (Q(ipNumber__iendswith=f"/{ip_filter}") | Q(ipNumber__icontains=ip_filter))

            if status_filter == 'Admitted':
                q &= Q(is_admitted=True, is_discharged=False)
            elif status_filter == 'Discharged':
                q &= Q(is_discharged=True)

            if from_date:
                q &= Q(admissionDateTime__date__gte=from_date)
            if to_date:
                q &= Q(admissionDateTime__date__lte=to_date)

            if doctor_filter:
                q &= (Q(admittingDoctor__icontains=doctor_filter) | Q(consultingDoctor__icontains=doctor_filter))

            # Database-direct query sorted by active status and latest admission date
            admissions = list(
                Admission.objects.filter(q).order_by('-is_admitted', '-admissionDateTime')[:50]
            )

            # Fallback if no admissions found with hospital/branch filter
            if not admissions and ip_filter:
                fallback_q = Q(ipNumber__iexact=ip_filter) if "/" in ip_filter else (Q(ipNumber__iendswith=f"/{ip_filter}") | Q(ipNumber__icontains=ip_filter))
                admissions = list(
                    Admission.objects.filter(fallback_q).order_by('-is_admitted', '-admissionDateTime')[:50]
                )

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
                _enrich_with_patient(d, hospital_code or adm.hospital_code)
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
    request_outlet = resolve_request_outlet(request, request.data)

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
    billtype_collection      = hms_db["hospital_billtype"]
    pharmacy_item_collection = hms_db["hospital_pharmacyitem"]
    oppharmacy_collection    = hms_db["hospital_pharmacybilling"]
    patient_collection       = hms_db["hospital_patient"]
    admission_collection     = hms_db["hospital_admission"]
    insurance_collection     = hms_db["hospital_insuranceprovider"]

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
    except Exception:
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
    if isinstance(request_outlet, (list, tuple)):
        valid_outlets = [o for o in request_outlet if o in emp_outlets]
        if not valid_outlets:
            return Response({
                "success": False,
                "message": f"Outlet {request_outlet} not mapped to employee"
            }, status=403)
        matched_outlet = valid_outlets[0]
    else:
        if request_outlet not in emp_outlets:
            return Response({
                "success": False,
                "message": f"Outlet {request_outlet} not mapped to employee"
            }, status=403)
        matched_outlet = request_outlet

    # =========================================================
    # ✅ Get All Bill Types (Bulk 1 query)
    # =========================================================
    billtype_cursor = billtype_collection.find(
        {
            "hospital_code": hospital_code,
            "branch_code":   branch_code
        },
        {
            "bill_type": 1,
            "bill_name": 1,
            "_id": 0
        }
    )

    billtype_map       = {}
    allowed_bill_types = []

    for bt in billtype_cursor:
        bt_val = bt.get("bill_type")
        if bt_val is not None:
            try:
                bt_int = int(bt_val)
                allowed_bill_types.append(bt_int)
                billtype_map[bt_int] = bt.get("bill_name", "")
            except (ValueError, TypeError):
                pass

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
            from_dt = datetime.strptime(from_date_str.strip(), "%Y-%m-%d")
        except Exception:
            pass

    if to_date_str:
        try:
            to_dt = datetime.strptime(to_date_str.strip(), "%Y-%m-%d").replace(hour=23, minute=59, second=59, microsecond=999999)
        except Exception:
            pass

    # =========================================================
    # ✅ Direct High-Speed MongoDB Bill Query
    # =========================================================
    and_conditions = [
        {"hospital_code": hospital_code},
        {"branch_code":   branch_code},
        {
            "$or": [
                {"billing_status": {"$in": ["Billed", "billed", "Paid", "paid", "Completed", "completed", "deleted", "partially billed", "Partially Billed"]}},
                {
                    "billing_status": {"$in": ["Processing", "processing"]},
                    "bill_no": {"$exists": True, "$nin": [None, "", "—", "None", "null"]},
                    "medicine_particulars": {"$elemMatch": {"dispatched_qty": {"$gt": 0}}}
                }
            ]
        },
        {"bill_no": {"$nin": [None, "", "—"]}}
    ]

    if isinstance(matched_outlet, (list, tuple)):
        and_conditions.append({"outlet_code": {"$in": list(matched_outlet)}})
    elif matched_outlet:
        and_conditions.append({"outlet_code": matched_outlet})

    if bill_type_param and bill_type_param != "ALL":
        try:
            bt_int = int(bill_type_param)
            if bt_int == 18:
                and_conditions.append({"$or": [{"bill_type": 18}, {"is_ward_request": True}]})
            else:
                and_conditions.append({"bill_type": bt_int})
        except (ValueError, TypeError):
            pass

    if from_dt and to_dt:
        and_conditions.append({
            "$or": [
                {"bill_date": {"$gte": from_dt, "$lte": to_dt}},
                {"bill_date": {"$gte": from_date_str.strip(), "$lte": to_date_str.strip() + "T23:59:59.999999"}},
                {"created_date": {"$gte": from_dt, "$lte": to_dt}},
                {"created_date": {"$gte": from_date_str.strip(), "$lte": to_date_str.strip() + "T23:59:59.999999"}},
            ]
        })
    elif from_dt:
        and_conditions.append({
            "$or": [
                {"bill_date": {"$gte": from_dt}},
                {"bill_date": {"$gte": from_date_str.strip()}},
                {"created_date": {"$gte": from_dt}},
                {"created_date": {"$gte": from_date_str.strip()}},
            ]
        })
    elif to_dt:
        and_conditions.append({
            "$or": [
                {"bill_date": {"$lte": to_dt}},
                {"bill_date": {"$lte": to_date_str.strip() + "T23:59:59.999999"}},
                {"created_date": {"$lte": to_dt}},
                {"created_date": {"$lte": to_date_str.strip() + "T23:59:59.999999"}},
            ]
        })

    if search_value:
        sv = re.escape(search_value)
        if search_by == "bill_no":
            and_conditions.append({"bill_no": {"$regex": sv, "$options": "i"}})
        elif search_by == "uhid":
            and_conditions.append({"uhid": {"$regex": sv, "$options": "i"}})
        elif search_by == "patient_name":
            p_uhids = [
                p["uhid"] for p in patient_collection.find(
                    {"$or": [
                        {"firstName": {"$regex": sv, "$options": "i"}},
                        {"lastName": {"$regex": sv, "$options": "i"}}
                    ]},
                    {"uhid": 1, "_id": 0}
                ).limit(300)
            ]
            or_conds = [
                {"patient_name": {"$regex": sv, "$options": "i"}},
                {"patientname": {"$regex": sv, "$options": "i"}},
            ]
            if p_uhids:
                or_conds.append({"uhid": {"$in": p_uhids}})
            and_conditions.append({"$or": or_conds})
        else:
            and_conditions.append({"bill_no": {"$regex": sv, "$options": "i"}})

    bill_q = {"$and": and_conditions} if len(and_conditions) > 1 else (and_conditions[0] if and_conditions else {})

    # Fetch bills directly via PyMongo
    bills = list(oppharmacy_collection.find(bill_q).sort([("bill_date", -1), ("created_date", -1)]).limit(limit))

    # =========================================================
    # ✅ Collect IDs for Instant In-Memory Bulk Joins
    # =========================================================
    uhids      = set()
    doctor_ids = set()
    emp_ids    = set()
    item_ids   = set()

    for b in bills:
        u = b.get("uhid")
        if u:
            uhids.add(str(u).strip())
        doc_id = b.get("doctor_id")
        if doc_id:
            doctor_ids.add(str(doc_id).strip())
        for fld in ["billed_id", "created_by", "cashier_id"]:
            val = b.get(fld)
            if val:
                emp_ids.add(str(val).strip())
        for it in (b.get("medicine_particulars") or []):
            if isinstance(it, dict) and it.get("item_id"):
                item_ids.add(it["item_id"])

    # =========================================================
    # ✅ Bulk Join 1: Patients & Insurance Codes (1 query)
    # =========================================================
    patient_map     = {}
    patient_ins_map = {}
    all_comp_codes  = set()

    if uhids:
        for p in patient_collection.find(
            {"uhid": {"$in": list(uhids)}},
            {"uhid": 1, "salutation": 1, "firstName": 1, "lastName": 1, "company_code": 1, "customer_type": 1, "_id": 0}
        ):
            sal = (p.get("salutation") or "").strip()
            fn  = (p.get("firstName") or "").strip()
            ln  = (p.get("lastName") or "").strip()
            if ln.lower() == fn.lower():
                ln = ""
            full_n = " ".join(f"{sal} {fn} {ln}".split())
            patient_map[p["uhid"]] = full_n
            cc = (p.get("company_code") or "").strip()
            if cc:
                patient_ins_map[p["uhid"]] = cc
                all_comp_codes.add(cc)
            elif str(p.get("customer_type") or "").upper() == "INSURANCE":
                patient_ins_map[p["uhid"]] = "INSURANCE"

    # =========================================================
    # ✅ Bulk Join 2: Admissions (1 query)
    # =========================================================
    admission_map = {}
    if uhids:
        for adm in admission_collection.find(
            {"uhid": {"$in": list(uhids)}},
            {"uhid": 1, "is_admitted": 1, "customer_type": 1, "company_code": 1, "insurance_company": 1, "room_details": 1, "ipNumber": 1, "inpatient_number": 1, "created_date": 1, "_id": 0}
        ).sort("created_date", -1):
            u = adm.get("uhid")
            if u not in admission_map or adm.get("is_admitted"):
                admission_map[u] = adm
            cc = (adm.get("company_code") or "").strip()
            if cc:
                all_comp_codes.add(cc)

    # =========================================================
    # ✅ Bulk Join 3: Insurance Providers (1 query)
    # =========================================================
    insurance_name_map = {}
    if all_comp_codes:
        for ins in insurance_collection.find(
            {"company_code": {"$in": list(all_comp_codes)}},
            {"company_code": 1, "company_name": 1, "_id": 0}
        ):
            cc = str(ins.get("company_code") or "").strip()
            nm = (ins.get("company_name") or "").strip()
            if cc and nm:
                insurance_name_map[cc] = nm
                insurance_name_map[cc.upper()] = nm
                insurance_name_map[cc.lower()] = nm

    # =========================================================
    # ✅ Bulk Join 4: Profiles (Doctors & Employees in 1 query)
    # =========================================================
    all_pids    = list(doctor_ids | emp_ids)
    profile_map = {}
    if all_pids:
        search_pids = []
        for pid in all_pids:
            search_pids.append(pid)
            if pid.isdigit():
                search_pids.append(int(pid))
        for prof in profile_collection.find(
            {"employeeId": {"$in": search_pids}},
            {"employeeId": 1, "employeeName": 1, "_id": 0}
        ):
            eid_str = str(prof.get("employeeId"))
            ename   = prof.get("employeeName", "")
            if ename:
                profile_map[eid_str] = ename
                try:
                    profile_map[str(int(eid_str))] = ename
                except (ValueError, TypeError):
                    pass

    # =========================================================
    # ✅ Bulk Join 5: Pharmacy Items (1 query)
    # =========================================================
    item_map = {}
    if item_ids:
        search_iids = []
        for iid in item_ids:
            search_iids.append(iid)
            if str(iid).isdigit():
                search_iids.append(int(iid))
                search_iids.append(str(iid))
        for itm in pharmacy_item_collection.find(
            {"item_id": {"$in": search_iids}},
            {"item_id": 1, "item_name": 1, "is_consumable_items": 1, "hsn": 1, "hsn_code": 1, "CGST_Percentage": 1, "SGST_Percentage": 1, "mrp": 1, "Selling_Price": 1, "_id": 0}
        ):
            raw_id = itm.get("item_id")
            item_map[raw_id] = itm
            item_map[str(raw_id)] = itm
            try:
                item_map[int(raw_id)] = itm
            except (ValueError, TypeError):
                pass

    # =========================================================
    # ✅ Bulk Join 6: Pharmacy Stocks (for batch-specific GST & Expiry)
    # =========================================================
    stock_map = {}
    if item_ids:
        search_iids = []
        for iid in item_ids:
            search_iids.append(iid)
            if str(iid).isdigit():
                search_iids.append(int(iid))
                search_iids.append(str(iid))
        for st in stock_collection.find(
            {"item_id": {"$in": search_iids}},
            {"item_id": 1, "batch_number": 1, "expiry_date": 1, "CGST_Percentage": 1, "SGST_Percentage": 1, "CGST_Amt": 1, "SGST_Amt": 1, "hsn_code": 1, "item_name": 1, "mrp": 1, "_id": 0}
        ):
            s_iid = st.get("item_id")
            s_bn = str(st.get("batch_number") or "").strip()
            stock_map[(s_iid, s_bn)] = st
            stock_map[(str(s_iid), s_bn)] = st
            try:
                stock_map[(int(s_iid), s_bn)] = st
            except (ValueError, TypeError):
                pass

    # =========================================================
    # ✅ Bulk Join 7: Fallback Doctor Names from hospital_billing
    # =========================================================
    uhid_doctor_map = {}
    if uhids:
        try:
            for hb in mongo_db["hospital_billing"].find(
                {"uhid": {"$in": list(uhids)}, "doctorName": {"$exists": True, "$ne": ""}},
                {"uhid": 1, "doctorName": 1, "doctor_id": 1, "_id": 0}
            ).sort("billed_date", -1):
                u_val = hb.get("uhid")
                if u_val and u_val not in uhid_doctor_map:
                    uhid_doctor_map[u_val] = (hb.get("doctorName") or "").strip()
        except Exception:
            pass

    # =========================================================
    # ✅ Helpers for serialization
    # =========================================================
    def to_num(val):
        if val is None:
            return 0.0
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, Decimal128):
            return float(val.to_decimal())
        if isinstance(val, Decimal):
            return float(val)
        try:
            return float(str(val).strip())
        except (ValueError, TypeError):
            return 0.0

    def serialize_val(val):
        if isinstance(val, (datetime, date)):
            return val.isoformat()
        if isinstance(val, Decimal128):
            return float(val.to_decimal())
        if isinstance(val, Decimal):
            return float(val)
        if hasattr(val, '__str__') and type(val).__name__ == 'ObjectId':
            return str(val)
        if isinstance(val, dict):
            return {k: serialize_val(v) for k, v in val.items()}
        if isinstance(val, list):
            return [serialize_val(x) for x in val]
        return val

    # =========================================================
    # ✅ Build Bills Data (Fast direct in-memory serialization)
    # =========================================================
    data = []

    for b in bills:
        serialized = {}
        for k, v in b.items():
            if k == "_id":
                serialized["_id"] = str(v)
            else:
                serialized[k] = serialize_val(v)

        u = str(b.get("uhid") or "").strip()
        adm_doc = admission_map.get(u) or {}
        p_name = (
            patient_map.get(u)
            or b.get("patient_name")
            or b.get("patientname")
            or b.get("patientName")
            or adm_doc.get("patient_name")
            or adm_doc.get("patientName")
            or b.get("customer_name")
            or ""
        )
        serialized["patient_name"] = p_name
        serialized["patientname"]  = p_name

        # Doctor
        doc_id_val = str(b.get("doctor_id") or "").strip()
        doc_display = profile_map.get(doc_id_val, "")
        if not doc_display:
            doc_display = b.get("doctor_name") or (doc_id_val if not doc_id_val.isdigit() else "")
        if not doc_display and u:
            doc_display = adm_doc.get("doctor_name") or adm_doc.get("primary_doctor") or uhid_doctor_map.get(u, "")
        serialized["doctor_name"] = doc_display

        # Bill type name
        bt_val = b.get("bill_type")
        try:
            bt_name = billtype_map.get(int(bt_val)) if bt_val is not None else ""
        except Exception:
            bt_name = ""
        if not bt_name and (b.get("is_ward_request") or b.get("billing_mode") == "WARD REQUEST" or b.get("outlet_code") == "OLET001"):
            bt_name = billtype_map.get(18, "PHARMACY IP BILL")
        serialized["bill_type_name"] = bt_name or ""

        # Billed / Employee name
        billed_id_val = str(b.get("billed_id") or "").strip()
        created_val   = str(b.get("created_by") or "").strip()
        cashier_val   = str(b.get("cashier_id") or "").strip()

        billed_display = (
            profile_map.get(billed_id_val) or
            profile_map.get(cashier_val) or
            profile_map.get(created_val) or
            billed_id_val or
            created_val
        )
        serialized["billed_id"]       = billed_id_val or None
        serialized["billed_name"]     = billed_display
        serialized["employee_name"]   = billed_display
        serialized["prepared_by"]     = billed_display
        serialized["created_by_name"] = profile_map.get(created_val, created_val)

        # Admission & Insurance
        adm_doc = admission_map.get(u) or {}
        adm_ins = adm_doc.get("insurance_company")
        if not adm_ins and adm_doc.get("company_code"):
            adm_ins = insurance_name_map.get(str(adm_doc.get("company_code")).strip(), "")
        if not adm_ins and str(adm_doc.get("customer_type") or "").upper() == "INSURANCE":
            adm_ins = "INSURANCE"

        pat_ins = ""
        pat_cc = patient_ins_map.get(u)
        if pat_cc:
            pat_ins = insurance_name_map.get(pat_cc, pat_cc if pat_cc == "INSURANCE" else "")

        final_ins = adm_ins or pat_ins or ""
        serialized["insurance_name"]    = final_ins
        serialized["insurance_company"] = final_ins

        if not serialized.get("inpatient_number") and (adm_doc.get("ipNumber") or adm_doc.get("inpatient_number")):
            serialized["inpatient_number"] = adm_doc.get("ipNumber") or adm_doc.get("inpatient_number")

        if not serialized.get("room_no") and adm_doc.get("room_details"):
            rooms = adm_doc.get("room_details") or []
            active_r = next((r for r in rooms if r.get("is_roomActive")), rooms[0] if rooms else None)
            if active_r:
                serialized["room_no"] = " | ".join(filter(None, [active_r.get("ward"), active_r.get("room_no") or active_r.get("room")]))

        # Line items
        updated_items = []
        for item in (b.get("medicine_particulars") or []):
            if not isinstance(item, dict):
                continue
            it = dict(item)
            item_id_val = it.get("item_id")
            bn_val = str(it.get("batch_number") or it.get("batch_no") or it.get("batch") or "").strip()
            master_item = item_map.get(item_id_val, {})
            if not master_item and str(item_id_val).isdigit():
                master_item = item_map.get(int(item_id_val)) or item_map.get(str(item_id_val)) or {}
            stock_item = stock_map.get((item_id_val, bn_val), {})
            if not stock_item and str(item_id_val).isdigit():
                stock_item = stock_map.get((int(item_id_val), bn_val), {})

            raw_name = (it.get("item_name") or it.get("medicine_name") or it.get("name") or "").strip()
            if not raw_name:
                raw_name = (master_item.get("item_name") or stock_item.get("item_name") or "").strip()
            if not raw_name and item_id_val:
                try:
                    p_itm = pharmacy_item_collection.find_one({"item_id": int(item_id_val)}, {"item_name": 1})
                    if p_itm:
                        raw_name = (p_itm.get("item_name") or "").strip()
                except Exception:
                    pass
            it["item_name"]     = raw_name
            it["medicine_name"] = raw_name

            if not it.get("hsn_code"):
                it["hsn_code"] = stock_item.get("hsn_code") or master_item.get("hsn_code") or master_item.get("hsn") or ""

            if not it.get("expiry_date"):
                exp_val = stock_item.get("expiry_date")
                if exp_val:
                    if isinstance(exp_val, (datetime, date)):
                        it["expiry_date"] = exp_val.strftime("%Y-%m-%d")
                    else:
                        it["expiry_date"] = str(exp_val)

            cgst_pct = to_num(it.get("CGST_Percentage", 0))
            sgst_pct = to_num(it.get("SGST_Percentage", 0))
            if cgst_pct == 0.0:
                cgst_pct = to_num(stock_item.get("CGST_Percentage")) or to_num(master_item.get("CGST_Percentage"))
            if sgst_pct == 0.0:
                sgst_pct = to_num(stock_item.get("SGST_Percentage")) or to_num(master_item.get("SGST_Percentage"))
            it["CGST_Percentage"] = cgst_pct
            it["SGST_Percentage"] = sgst_pct

            price_val = to_num(it.get("price", 0))
            if price_val == 0.0:
                price_val = to_num(it.get("mrp", 0)) or to_num(stock_item.get("mrp", 0)) or to_num(master_item.get("Selling_Price", 0)) or to_num(master_item.get("mrp", 0))

            qty_val  = to_num(it.get("qty", 0) or it.get("quantity", 0))
            calc_val = to_num(it.get("calculated_price", 0))
            if calc_val == 0.0 and price_val > 0 and qty_val > 0:
                calc_val = round(price_val * qty_val, 2)

            cgst_amt_val = to_num(it.get("CGST_Amt", 0))
            sgst_amt_val = to_num(it.get("SGST_Amt", 0))

            total_gst_pct = cgst_pct + sgst_pct
            product_val = round(calc_val / (1.0 + total_gst_pct / 100.0), 4) if total_gst_pct > 0 else calc_val
            raw_dv = it.get("discount_value")
            if raw_dv is not None and str(raw_dv).strip() not in ("", "%"):
                disc_val = to_num(raw_dv)
            elif it.get("discount") is not None and str(it.get("discount")).strip() not in ("", "%"):
                disc_val = to_num(it.get("discount"))
            elif it.get("discount_percent") is not None and str(it.get("discount_percent")).strip() not in ("", "%"):
                disc_val = to_num(it.get("discount_percent"))
            else:
                disc_val = 0.0
            disc_amt = to_num(it.get("discount_amount", 0))
            if disc_amt == 0.0 and disc_val > 0:
                disc_amt = round(product_val * (disc_val / 100.0), 4)
            taxable_val = max(0.0, product_val - disc_amt)

            if cgst_amt_val == 0.0 and cgst_pct > 0 and taxable_val > 0:
                cgst_amt_val = round((taxable_val * cgst_pct) / 100.0, 2)
            if sgst_amt_val == 0.0 and sgst_pct > 0 and taxable_val > 0:
                sgst_amt_val = round((taxable_val * sgst_pct) / 100.0, 2)

            it["product_value"]    = product_val
            it["taxable_value"]    = taxable_val
            it["discount_amount"]  = disc_amt
            it["CGST_Amt"]         = cgst_amt_val
            it["SGST_Amt"]         = sgst_amt_val
            it["price"]            = price_val
            it["mrp"]              = to_num(it.get("mrp", 0)) or to_num(stock_item.get("mrp", 0)) or to_num(master_item.get("mrp", 0)) or price_val
            it["calculated_price"] = calc_val
            it["edit_history"]     = it.get("edit_history", [])
            updated_items.append(it)

        # Recalculate bill total if 0
        items_total = sum(to_num(it.get("calculated_price", 0)) for it in updated_items)
        if to_num(serialized.get("total_amount", 0)) == 0.0 and items_total > 0:
            serialized["total_amount"] = round(items_total, 2)
        if to_num(serialized.get("net_amount", 0)) == 0.0 and items_total > 0:
            serialized["net_amount"] = round(items_total, 2)

        # Preserve actual billing_status from DB (Billed / Paid / etc.)
        raw_bs = str(b.get("billing_status") or serialized.get("billing_status") or "").strip()
        if not raw_bs:
            has_payment = bool(b.get("payment_details") and (b.get("paid_date") or b.get("cashier_id")))
            raw_bs = "Paid" if has_payment else "Billed"
        serialized["billing_status"] = raw_bs

        serialized["medicine_particulars"] = updated_items
        data.append(serialized)

    # =========================================================
    # ✅ Final Response
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
        if outlet_code and str(outlet_code).strip() not in ["", "ALL", "all", "All"]:
            clean_outlet = str(outlet_code).strip()
            if clean_outlet == "OLET006":
                match_stage["$or"] = [
                    {"outlet_code": "OLET006"},
                    {"outlet_code": None},
                    {"outlet_code": ""}
                ]
            else:
                match_stage["outlet_code"] = clean_outlet
            
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

            # Doctor name & ID
            raw_doc = getattr(c, "doctor_id", "") or getattr(c, "created_by", "") or ""
            doc_id = resolve_doctor_id(raw_doc) if raw_doc else ""
            doc_name = get_doctor_name_by_id(doc_id or raw_doc)
            if not doc_name:
                doc_name = "Doctor"

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


from hospital.Views.dbcollection import clean_patient_name

# Indian Standard Timezone (Asia/Kolkata)
_KOLKATA_TZ = pytz.timezone("Asia/Kolkata")

def _format_ist_datetime(val):
    """
    Convert UTC or naive datetime stored in MongoDB to IST (Asia/Kolkata)
    and format as DD/MM/YYYY hh:mm:ss AM/PM (e.g. 13/11/2026 08:40:16 AM).
    """
    if not val:
        return "—"
    d_obj = None
    if isinstance(val, datetime):
        d_obj = val
    elif isinstance(val, date):
        return val.strftime("%d/%m/%Y")
    elif isinstance(val, str):
        val_str = val.strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}$", val_str):
            try:
                return datetime.strptime(val_str, "%Y-%m-%d").strftime("%d/%m/%Y")
            except Exception:
                return val_str
        try:
            d_obj = parse_datetime(val_str)
        except Exception:
            pass
        if not d_obj:
            try:
                d_obj = datetime.fromisoformat(val_str.replace("Z", "+00:00"))
            except Exception:
                pass
        if not d_obj:
            return val_str[:19]

    if d_obj:
        try:
            if d_obj.tzinfo is None:
                d_obj = pytz.utc.localize(d_obj)
            d_obj_ist = d_obj.astimezone(_KOLKATA_TZ)
            return d_obj_ist.strftime("%d/%m/%Y %I:%M:%S %p")
        except Exception:
            return str(d_obj)[:19]

    return str(val)[:19]

def _get_ist_date_str(val):
    """Extract YYYY-MM-DD in Asia/Kolkata timezone from datetime or string."""
    if not val:
        return ""
    d_obj = None
    if isinstance(val, datetime):
        d_obj = val
    elif isinstance(val, date):
        return val.strftime("%Y-%m-%d")
    elif isinstance(val, str):
        val_str = val.strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}$", val_str):
            return val_str[:10]
        try:
            d_obj = parse_datetime(val_str)
        except Exception:
            pass
        if not d_obj:
            try:
                d_obj = datetime.fromisoformat(val_str.replace("Z", "+00:00"))
            except Exception:
                pass
    if d_obj:
        try:
            if d_obj.tzinfo is None:
                d_obj = pytz.utc.localize(d_obj)
            return d_obj.astimezone(_KOLKATA_TZ).strftime("%Y-%m-%d")
        except Exception:
            return str(d_obj)[:10]
    return str(val)[:10]

def _extract_best_bill_dt(doc):
    """
    Pick the most specific timestamp available in the bill doc.
    Prefers a datetime with non-zero time component over date-only strings.
    """
    cd = doc.get("created_date")
    bd = doc.get("bill_date")
    if isinstance(bd, datetime) and (bd.hour != 0 or bd.minute != 0 or bd.second != 0):
        return bd
    if isinstance(cd, datetime):
        return cd
    if isinstance(bd, datetime):
        return bd
    if isinstance(bd, str) and ("T" in bd or ":" in bd):
        return bd
    if isinstance(cd, str) and ("T" in cd or ":" in cd):
        return cd
    return bd or cd

@api_view(["POST", "GET"])
@permission_classes([HasRoleAndDataPermission])
def PharmacyBillanalysis(request):
    """
    Pharmacy Bill Analysis:
    1. Displays bill analysis data stored in pharmacy billing filtered by outlet_code, hospital_code, branch_code.
    2. Date range filtering (from_date, to_date) defaulting to today.
    3. Complete A-to-Z bill travel analysis:
       - Patient details link via UHID (Name, Age, Gender, Phone, Address).
       - Inpatient admission details via IP number / UHID (IP Advance, Room, Doctors, Insurance, Discharged status).
       - Sales return travel (hospital_salesreturn and edit_history).
       - IP / Ward return travel (hospital_wardreturndetails and pending_returns).
       - Cash counter collection status.
       - Status, Date & Time, Bill Type, Bill Number, UHID, Patient Name, Gross, Discount, Advance, IP Return, Net Amount, Action.
    """
    try:
        data = request.data
        hospital_code = data.get("auth-hospital-code") 
        branch_code   = data.get("auth-branch-code")
        outlet_code   = data.get("auth-outlet-code")
        raw_outlet    = outlet_code

        if isinstance(raw_outlet, (list, tuple)):
            if len(raw_outlet) == 1:
                outlet_code = raw_outlet[0]
            elif raw_outlet:
                outlet_code = {"$in": list(raw_outlet)}
            else:
                outlet_code = None
        elif isinstance(raw_outlet, str) and raw_outlet.strip().startswith("[") and raw_outlet.strip().endswith("]"):
            try:
                parsed_list = ast.literal_eval(raw_outlet.strip())
                if isinstance(parsed_list, (list, tuple)):
                    if len(parsed_list) == 1:
                        outlet_code = parsed_list[0]
                    elif parsed_list:
                        outlet_code = {"$in": list(parsed_list)}
                    else:
                        outlet_code = None
                else:
                    outlet_code = raw_outlet
            except Exception:
                outlet_code = raw_outlet
        else:
            outlet_code = raw_outlet

        from_date_str = str(data.get("from_date") or "").strip()
        to_date_str   = str(data.get("to_date") or "").strip()
        search_value  = str(data.get("search") or "").strip()
        status_filter = str(data.get("status") or "all").strip().lower()

        # Connect to MongoDB
        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        hms_db = client["HMS"]

        pb_col    = hms_db["hospital_pharmacybilling"]
        pat_col   = hms_db["hospital_patient"]
        adm_col   = hms_db["hospital_admission"]
        sr_col    = hms_db["hospital_salesreturn"]
        wr_col    = hms_db["hospital_wardreturndetails"]
        cc_col    = hms_db["hospital_cashcountercollection"]
        disch_col = hms_db["hospital_dischargebilling"]
        bt_col    = hms_db["hospital_billtype"]
        pi_col    = hms_db["hospital_pharmacyitem"]

        # Date handling (Default to today in IST if not provided)
        today_str = datetime.now(_KOLKATA_TZ).strftime("%Y-%m-%d")

        if not from_date_str:
            from_date_str = today_str
        if not to_date_str:
            to_date_str = today_str

        from_dt = None
        to_dt = None

        if from_date_str.lower() != "all":
            try:
                from_dt_local = datetime.strptime(from_date_str, "%Y-%m-%d").replace(hour=0, minute=0, second=0)
                from_dt_utc = _KOLKATA_TZ.localize(from_dt_local).astimezone(pytz.utc).replace(tzinfo=None)
                from_dt = min(from_dt_utc, from_dt_local)
            except Exception:
                pass

        if to_date_str.lower() != "all":
            try:
                to_dt_local = datetime.strptime(to_date_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59, microsecond=999999)
                to_dt_utc = _KOLKATA_TZ.localize(to_dt_local).astimezone(pytz.utc).replace(tzinfo=None)
                to_dt = max(to_dt_utc, to_dt_local)
            except Exception:
                pass

        # Build Base Query (Strictly only Billed/Paid/Cancelled bills with a valid bill_no; Estimates excluded)
        query = {
            "hospital_code": hospital_code,
            "branch_code": branch_code,
            "billing_status": {"$in": ["Billed", "Paid", "Cancelled", "billed", "paid", "cancelled"]},
            "billing_mode": {"$nin": ["ESTIMATE", "estimate"]},
            "bill_no": {"$exists": True, "$ne": None, "$nin": ["", "—", "None", "null"]},
        }
        if outlet_code:
            query["outlet_code"] = outlet_code

        if from_dt and to_dt:
            query["$or"] = [
                {"bill_date": {"$gte": from_dt, "$lte": to_dt}},
                {"created_date": {"$gte": from_dt, "$lte": to_dt}},
            ]
        elif from_dt:
            query["$or"] = [
                {"bill_date": {"$gte": from_dt}},
                {"created_date": {"$gte": from_dt}},
            ]

        # Fetch Bills (sorted by created_date desc)
        raw_bills = list(pb_col.find(query).sort("created_date", -1).limit(2500))

        # Fallback: if 0 bills found with date filter, but search_value is present, search across all dates
        if len(raw_bills) == 0 and search_value:
            search_query = {
                "hospital_code": hospital_code,
                "branch_code": branch_code,
                "billing_status": {"$in": ["Billed", "Paid", "Cancelled", "billed", "paid", "cancelled"]},
                "billing_mode": {"$nin": ["ESTIMATE", "estimate"]},
                "bill_no": {"$exists": True, "$ne": None, "$nin": ["", "—", "None", "null"]},
            }
            if outlet_code:
                search_query["outlet_code"] = outlet_code
            search_query["$or"] = [
                {"bill_no": {"$regex": re.escape(search_value), "$options": "i"}},
                {"uhid": {"$regex": re.escape(search_value), "$options": "i"}},
                {"inpatient_number": {"$regex": re.escape(search_value), "$options": "i"}},
            ]
            raw_bills = list(pb_col.find(search_query).sort("created_date", -1).limit(1000))

        # Collect distinct identifiers for batch lookup
        uhids = list({b.get("uhid") for b in raw_bills if b.get("uhid")})
        ip_numbers = list({b.get("inpatient_number") for b in raw_bills if b.get("inpatient_number")})
        bill_nos = list({b.get("bill_no") for b in raw_bills if b.get("bill_no")})

        # 1. Batch fetch Patient Details
        patients_map = {}
        if uhids:
            for p in pat_col.find({"uhid": {"$in": uhids}}):
                u = p.get("uhid")
                if u:
                    f_name = p.get("firstName") or ""
                    l_name = p.get("lastName") or ""
                    full_name = clean_patient_name(f"{f_name} {l_name}".strip()) or f_name
                    patients_map[u] = {
                        "uhid": u,
                        "name": full_name,
                        "age": p.get("age", ""),
                        "gender": p.get("gender", ""),
                        "phone": p.get("mobilePhone", ""),
                        "address": p.get("permanent_address") or p.get("city") or "",
                    }

        # 2. Batch fetch Admission Details
        admissions_map = {}
        adm_query = []
        if uhids:
            adm_query.append({"uhid": {"$in": uhids}})
        if ip_numbers:
            adm_query.append({"ipNumber": {"$in": ip_numbers}})
        if adm_query:
            for a in adm_col.find({"$or": adm_query}):
                u = a.get("uhid")
                ip = a.get("ipNumber")

                adv_list = a.get("advance_payments") or []
                total_adv = 0.0
                adv_records = []
                if isinstance(adv_list, list):
                    for ap in adv_list:
                        if isinstance(ap, dict):
                            is_active = ap.get("is_advanceActive") is not False
                            status_val = str(ap.get("status", "")).strip().lower()
                            if is_active and status_val not in ["cancelled", "refunded"] and not ap.get("is_refund"):
                                try:
                                    amt = float(ap.get("ip_advance") or ap.get("advance_amount") or ap.get("amount") or 0)
                                    total_adv += amt
                                    adv_records.append({
                                        "bill_no": ap.get("bill_no") or ap.get("bill_number") or "",
                                        "amount": amt,
                                        "date": ap.get("date") or ap.get("created_date") or "",
                                        "mode": ap.get("payment_mode") or ap.get("mode") or "Cash",
                                    })
                                except Exception:
                                    pass

                room_label = ""
                room_details = a.get("room_details") or []
                shifting_details = a.get("roomShitingDetails") or []
                active_room = next((r for r in room_details if isinstance(r, dict) and r.get("is_roomActive") is True), None)
                active_shift = next((r for r in shifting_details if isinstance(r, dict) and r.get("is_roomActive") is True), None)
                if active_room:
                    room_label = f"{active_room.get('roomNo', '')} / Bed {active_room.get('bedNo', '')}"
                elif active_shift:
                    room_label = f"{active_shift.get('newRoomNo', '')} / Bed {active_shift.get('newBedNo', '')}"

                adm_info = {
                    "uhid": u,
                    "ipNumber": ip,
                    "total_ip_advance": round(total_adv, 2),
                    "advance_records": adv_records,
                    "room_label": room_label,
                    "admissionDateTime": a.get("admissionDateTime"),
                    "admittingDoctor": a.get("admittingDoctor") or "",
                    "consultingDoctor": a.get("consultingDoctor") or "",
                    "customer_type": a.get("customer_type") or "Cash",
                    "insurance_company": a.get("insurance_company") or "",
                    "is_discharged": a.get("is_discharged") is True,
                    "is_admitted": a.get("is_admitted") is not False,
                }
                if u:
                    admissions_map[u] = adm_info
                if ip:
                    admissions_map[ip] = adm_info

        # 3. Batch fetch Sales Returns
        sales_returns_map = {}
        if bill_nos:
            for sr in sr_col.find({"bill_no": {"$in": bill_nos}}):
                b_no = sr.get("bill_no")
                if b_no:
                    if b_no not in sales_returns_map:
                        sales_returns_map[b_no] = []
                    ret_amt = 0.0
                    try:
                        ret_amt = float(sr.get("return_amount") or 0)
                    except Exception:
                        pass
                    sales_returns_map[b_no].append({
                        "return_bill_no": sr.get("return_bill_no", "—"),
                        "return_date": _format_ist_datetime(sr.get("return_bill_date") or sr.get("created_date")),
                        "return_amount": ret_amt,
                        "payment_type": sr.get("PaymentType") or "Cash",
                        "status": sr.get("status") or "Approved",
                        "items": sr.get("medicine_particulars") or [],
                    })

        # 4. Batch fetch Ward / IP Returns
        ward_returns_map = {}
        if bill_nos:
            for wr in wr_col.find({"bill_no": {"$in": bill_nos}}):
                b_no = wr.get("bill_no")
                if b_no:
                    if b_no not in ward_returns_map:
                        ward_returns_map[b_no] = []
                    ret_amt = 0.0
                    try:
                        ret_amt = float(wr.get("return_amount") or 0)
                    except Exception:
                        pass
                    ward_returns_map[b_no].append({
                        "ward_return_bill_no": wr.get("ward_return_bill_no", "—"),
                        "ward_return_date": _format_ist_datetime(wr.get("ward_return_bill_date") or wr.get("created_date")),
                        "return_amount": ret_amt,
                        "inpatient_number": wr.get("inpatient_number", ""),
                        "status": wr.get("status") or "Approved",
                        "items": wr.get("medicine_particulars") or [],
                    })

        # 5. Batch fetch Cash Counter Collections (Pharmacy collections only)
        cash_map = {}
        if bill_nos:
            for cc in cc_col.find({
                "bill_no": {"$in": bill_nos},
                "billing_category": {"$in": ["OPPharmacyBills", "Pharmacy"]}
            }):
                b_no = cc.get("bill_no")
                if b_no:
                    if b_no not in cash_map:
                        cash_map[b_no] = []
                    c_amt = 0.0
                    try:
                        c_amt = float(cc.get("collected_amount", 0) or 0)
                    except Exception:
                        pass
                    cash_map[b_no].append({
                        "bill_number": cc.get("bill_number"),
                        "collected_amount": c_amt,
                        "counter_code": cc.get("counter_code"),
                        "shift_no": cc.get("shift_no"),
                        "created_date": _format_ist_datetime(cc.get("created_date")),
                    })

        # 6. Batch fetch Bill Types map
        billtype_map = {}
        for bt in bt_col.find({}, {"bill_type": 1, "bill_name": 1}):
            bt_id = bt.get("bill_type")
            if bt_id is not None:
                try:
                    billtype_map[int(bt_id)] = bt.get("bill_name", "")
                except Exception:
                    pass

        # 7. Batch fetch Pharmacy Item Names from hospital_pharmacyitem
        item_ids_to_fetch = set()
        for b in raw_bills:
            for m in b.get("medicine_particulars") or []:
                if isinstance(m, dict):
                    iid = m.get("item_id")
                    if iid is not None:
                        try:
                            item_ids_to_fetch.add(int(iid))
                        except Exception:
                            item_ids_to_fetch.add(iid)

        item_names_map = {}
        if item_ids_to_fetch:
            for pi in pi_col.find({"item_id": {"$in": list(item_ids_to_fetch)}}, {"item_id": 1, "item_name": 1}):
                iid = pi.get("item_id")
                iname = pi.get("item_name")
                if iid is not None and iname:
                    try:
                        item_names_map[int(iid)] = iname
                    except Exception:
                        pass
                    item_names_map[str(iid)] = iname

        # Helper for float conversion
        def to_num(val):
            if val is None:
                return 0.0
            from bson.decimal128 import Decimal128
            if isinstance(val, Decimal128):
                return float(val.to_decimal())
            try:
                return float(val)
            except Exception:
                return 0.0

        # Build Final Enriched Response
        results = []
        tot_gross = 0.0
        tot_discount = 0.0
        tot_net = 0.0
        tot_advance = 0.0
        tot_ip_return = 0.0
        tot_sales_return = 0.0

        for b in raw_bills:
            b_status_raw = str(b.get("billing_status") or "").strip().lower()
            b_mode_raw = str(b.get("billing_mode") or "").strip().lower()
            b_no_raw = b.get("bill_no")
            b_no_str = str(b_no_raw or "").strip()

            # Strictly exclude Estimates: only billed, paid, or cancelled bills with a real bill number must display
            if (
                b_status_raw in ["estimate", "estimated"]
                or b_mode_raw == "estimate"
                or not b_no_raw
                or b_no_str in ["", "—", "none", "null"]
                or (b.get("estimate_no") and (not b_no_raw or b_no_str in ["", "—", "none", "null"]))
            ):
                continue

            b_no = b_no_str
            u = b.get("uhid", "")
            raw_ip = str(b.get("inpatient_number") or b.get("ipNumber") or "").strip()
            ip_num = "" if (not raw_ip or raw_ip == "—" or raw_ip.lower() == "none" or raw_ip.upper().startswith("OP")) else raw_ip

            # Bill Type Lookup
            bt_num = b.get("bill_type")
            bt_name = "PHARMACY BILL"
            if bt_num is not None:
                try:
                    bt_name = billtype_map.get(int(bt_num), f"Bill Type {bt_num}")
                except Exception:
                    pass

            # Patient details
            pat = patients_map.get(u, {})
            p_name = pat.get("name") or b.get("patient_name") or b.get("patientname") or "—"
            p_age = pat.get("age") or b.get("age") or ""
            p_gender = pat.get("gender") or ""
            p_phone = pat.get("phone") or ""
            p_address = pat.get("address") or b.get("room_no") or ""

            # Admission details
            adm = admissions_map.get(ip_num) or admissions_map.get(u) or {}
            if not adm.get("room_label") and b.get("room_no"):
                adm = dict(adm)
                adm["room_label"] = b.get("room_no")
            adv_amt = float(adm.get("total_ip_advance", 0.0))
            is_ip_cleared = adm.get("is_discharged", False)

            # Sales return details
            sr_list = sales_returns_map.get(b_no, [])
            sales_ret_amt = sum(s["return_amount"] for s in sr_list)
            # Check medicine_particulars edit_history for sales_return if not in hospital_salesreturn
            med_list = b.get("medicine_particulars") or []
            if sales_ret_amt == 0:
                for m in med_list:
                    if isinstance(m, dict):
                        for eh in m.get("edit_history") or []:
                            if isinstance(eh, dict) and eh.get("action") == "sales_return":
                                try:
                                    r_qty = float(eh.get("return_qty") or 0)
                                    u_price = float(m.get("price") or 0)
                                    sales_ret_amt += (r_qty * u_price)
                                except Exception:
                                    pass

            has_sales_return = len(sr_list) > 0 or sales_ret_amt > 0

            # IP / Ward return details
            wr_list = ward_returns_map.get(b_no, [])
            ip_ret_amt = sum(w["return_amount"] for w in wr_list)
            # Check pending_returns inside bill
            pending_ret = b.get("pending_returns") or []
            if ip_ret_amt == 0:
                for pr in pending_ret:
                    if isinstance(pr, dict) and pr.get("status") == "Approved":
                        for it in pr.get("items") or []:
                            if isinstance(it, dict):
                                try:
                                    ip_ret_amt += float(it.get("return_qty") or 0) * 50.0
                                except Exception:
                                    pass

            has_ip_return = len(wr_list) > 0 or ip_ret_amt > 0 or len(pending_ret) > 0

            # Cash collection details
            cash_list = cash_map.get(b_no, [])

            # Monetary amounts
            gross = to_num(b.get("total_amount", 0))
            discount = to_num(b.get("overall_discount_amount", 0))
            net = to_num(b.get("net_amount", 0))

            # Status determination based strictly on payment_mode:
            # - payment_mode: "Cash" -> "Cash Bills"
            # - payment_mode: "Credit" -> "Credit Bills"
            # Even for cancelled bills, display the payment mode
            b_status = b.get("billing_status") or "Billed"
            is_cancelled = b_status.lower() in ["cancelled", "deleted"] or b.get("is_deleted") is True
            p_mode = str(b.get("payment_mode") or "").strip().lower()
            b_mode = str(b.get("billing_mode") or "").strip().upper()

            if p_mode == "credit" or b_mode in ["WARD REQUEST", "IP CREDIT", "CREDIT"]:
                derived_status = "Credit Bills"
            elif p_mode in ["cash", "card", "upi", "online", "multiple payment"] or b_mode == "DIRECT" or b.get("payment_details"):
                derived_status = "Cash Bills"
            else:
                if p_mode:
                    derived_status = f"{p_mode.title()} Bills"
                elif b.get("inpatient_number") or "IP" in bt_name.upper():
                    derived_status = "Credit Bills"
                else:
                    derived_status = "Cash Bills"

            # A bill is a Cash Bill if payment_mode is Cash (or direct payment) and not cancelled
            is_cash_bill = not is_cancelled and (
                derived_status == "Cash Bills" or (p_mode != "credit" and b_mode not in ["WARD REQUEST", "IP CREDIT", "CREDIT"])
            )

            # Status filter
            if status_filter != "all":
                sf = status_filter.lower()
                if sf in ["credit bills", "ip credit bills", "credit bill", "credit"] and derived_status != "Credit Bills":
                    continue
                elif sf in ["cash bills", "cash bill", "cash"] and derived_status != "Cash Bills":
                    continue
                elif sf == "cancelled" and not is_cancelled:
                    continue
                elif sf == "sales return" and not has_sales_return:
                    continue
                elif sf == "ip return" and not has_ip_return:
                    continue

            # Extract best timestamp and filter strictly by IST date
            b_date = _extract_best_bill_dt(b)
            if from_date_str.lower() != "all" or to_date_str.lower() != "all":
                b_ist_date = _get_ist_date_str(b_date)
                if b_ist_date:
                    if from_date_str.lower() != "all" and b_ist_date < from_date_str:
                        continue
                    if to_date_str.lower() != "all" and b_ist_date > to_date_str:
                        continue

            # Format Date & Time in IST (Asia/Kolkata): "DD/MM/YYYY hh:mm:ss AM/PM"
            date_time_str = _format_ist_datetime(b_date)

            # Accumulate totals
            tot_gross += gross
            tot_discount += discount
            tot_net += net
            tot_advance += adv_amt
            tot_ip_return += ip_ret_amt
            tot_sales_return += sales_ret_amt

            # Serialized medicine items
            serialized_meds = []
            for m in med_list:
                if isinstance(m, dict):
                    m_id = m.get("item_id")
                    m_name = m.get("item_name")
                    if not m_name and m_id is not None:
                        try:
                            m_name = item_names_map.get(int(m_id)) or item_names_map.get(str(m_id))
                        except Exception:
                            m_name = item_names_map.get(str(m_id))
                    serialized_meds.append({
                        "item_id": m_id,
                        "item_name": m_name or "—",
                        "batch_number": m.get("batch_number", "—"),
                        "qty": to_num(m.get("qty") or m.get("quantity") or 0),
                        "price": to_num(m.get("price", 0)),
                        "calculated_price": to_num(m.get("calculated_price", 0)),
                        "edit_history": m.get("edit_history") or [],
                    })

            # Bill record item
            results.append({
                "id": str(b.get("_id", "")),
                "bill_number": b_no,
                "bill_no": b_no,
                "date_time": date_time_str,
                "bill_type": bt_name,
                "bill_type_id": bt_num,
                "uhid": u or "—",
                "patient_name": p_name,
                "patient_age": p_age,
                "patient_gender": p_gender,
                "patient_phone": p_phone,
                "patient_address": p_address,
                "inpatient_number": ip_num or "—",
                "gross_amount": round(gross, 2),
                "discount": round(discount, 2),
                "advance": round(adv_amt, 2),
                "ip_return": round(ip_ret_amt, 2),
                "sales_return_amount": round(sales_ret_amt, 2),
                "net_amount": round(net, 2),
                "status": derived_status,
                "billing_mode": b.get("billing_mode", "DIRECT"),
                "outlet_code": b.get("outlet_code") or outlet_code,
                "room_no": b.get("room_no") or "",
                "doctor_id": b.get("doctor_id") or "—",
                "shift_no": b.get("shiftno") or "—",
                "medicine_particulars": serialized_meds,
                # Indicators matching Screenshot 2
                "bill_cancelled": "Yes" if is_cancelled else "No",
                "is_cash_bill": "Yes" if is_cash_bill else "No",
                "sales_return_entered": "Yes" if has_sales_return else "No",
                "ip_cleared": "Yes" if is_ip_cleared else "No",
                # Complete Travel / Journey breakdown for Action modal
                "travel": {
                    "bill_info": {
                        "bill_no": b_no,
                        "bill_date": date_time_str,
                        "bill_type": bt_name,
                        "billing_mode": b.get("billing_mode", "DIRECT"),
                        "billing_status": b_status,
                        "shift_no": b.get("shiftno") or "—",
                        "doctor_id": b.get("doctor_id") or "—",
                        "created_by": b.get("created_by") or "—",
                        "billed_id": b.get("billed_id") or "—",
                        "outlet_code": b.get("outlet_code") or outlet_code,
                    },
                    "patient": {
                        "uhid": u,
                        "name": p_name,
                        "age": p_age,
                        "gender": p_gender,
                        "phone": p_phone,
                        "address": p_address,
                    },
                    "admission": adm,
                    "medicines": serialized_meds,
                    "sales_returns": sales_returns_map.get(b_no, []),
                    "ward_returns": ward_returns_map.get(b_no, []),
                    "pending_returns": pending_ret,
                    "cash_collections": cash_list,
                }
            })

        summary = {
            "total_bills": len(results),
            "total_gross": round(tot_gross, 2),
            "total_discount": round(tot_discount, 2),
            "total_advance": round(tot_advance, 2),
            "total_ip_return": round(tot_ip_return, 2),
            "total_sales_return": round(tot_sales_return, 2),
            "total_net": round(tot_net, 2),
        }

        return Response({
            "success": True,
            "data": results,
            "summary": summary,
            "filters": {
                "from_date": from_date_str,
                "to_date": to_date_str,
                "outlet_code": outlet_code,
                "hospital_code": hospital_code,
                "branch_code": branch_code,
            }
        }, status=status.HTTP_200_OK)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(["POST", "GET"])
@permission_classes([HasRoleAndDataPermission])
def search_pharmacy_items(request):
    """
    Search pharmacy item catalog (hospital_pharmacyitem and hospital_pharmacystock)
    by item name or ID for auto-suggestions.
    """
    try:
        data = request.data if isinstance(getattr(request, "data", None), dict) else {}
        query = str(
            request.GET.get("q")
            or request.GET.get("search")
            or data.get("search")
            or data.get("query")
            or ""
        ).strip()

        if not query:
            return Response({"success": True, "data": []}, status=status.HTTP_200_OK)

        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        hms_db = client["HMS"]
        pharmacy_item_col = hms_db["hospital_pharmacyitem"]
        pharmacy_stock_col = hms_db["hospital_pharmacystock"]

        tokens = [t for t in re.split(r'\s+', query) if t]
        token_regex = ".*".join([re.escape(t) for t in tokens])

        mongo_query = {
            "$or": [
                {"item_name": {"$regex": re.escape(query), "$options": "i"}},
                {"item_name": {"$regex": token_regex, "$options": "i"}},
            ]
        }
        if query.isdigit():
            mongo_query["$or"].append({"item_id": int(query)})

        items = list(pharmacy_item_col.find(
            mongo_query,
            {"item_id": 1, "item_name": 1, "category": 1, "_id": 0}
        ).limit(30))

        # If few found, fallback to pharmacystock
        if len(items) < 10:
            existing_ids = {it.get("item_id") for it in items}
            stock_items = list(pharmacy_stock_col.find(
                {"item_name": {"$regex": re.escape(query), "$options": "i"}},
                {"item_id": 1, "item_name": 1, "_id": 0}
            ).limit(20))
            for s in stock_items:
                iid = s.get("item_id")
                if iid and iid not in existing_ids:
                    items.append({
                        "item_id": iid,
                        "item_name": s.get("item_name") or f"Item #{iid}",
                    })
                    existing_ids.add(iid)

        return Response({"success": True, "data": items}, status=status.HTTP_200_OK)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["POST", "GET"])
# @permission_classes([HasRoleAndDataPermission])
def PharmacyItemPatientAnalysis(request):
    """
    Pharmacy Bill Analysis -> Item-wise Patient Purchase Analysis:
    Identifies how many unique patients (UHIDs and IP Numbers) purchased a particular medicine
    or item within a selected date range, along with complete patient purchase details.
    """
    try:
        data = request.data if isinstance(getattr(request, "data", None), dict) else {}
        hospital_code = data.get("auth-hospital-code") 
        branch_code   = data.get("auth-branch-code")
        outlet_code   = data.get("auth-outlet-code") 
        raw_outlet    = outlet_code

        if isinstance(raw_outlet, (list, tuple)):
            if len(raw_outlet) == 1:
                outlet_code = raw_outlet[0]
            elif raw_outlet:
                outlet_code = {"$in": list(raw_outlet)}
            else:
                outlet_code = None
        elif isinstance(raw_outlet, str) and raw_outlet.strip().startswith("[") and raw_outlet.strip().endswith("]"):
            try:
                parsed_list = ast.literal_eval(raw_outlet.strip())
                if isinstance(parsed_list, (list, tuple)):
                    if len(parsed_list) == 1:
                        outlet_code = parsed_list[0]
                    elif parsed_list:
                        outlet_code = {"$in": list(parsed_list)}
                    else:
                        outlet_code = None
                else:
                    outlet_code = raw_outlet
            except Exception:
                outlet_code = raw_outlet
        else:
            outlet_code = raw_outlet

        from_date_str = str(data.get("from_date") or request.GET.get("from_date") or "").strip()
        to_date_str   = str(data.get("to_date") or request.GET.get("to_date") or "").strip()
        search_item   = str(data.get("search_item") or data.get("search") or request.GET.get("search_item") or request.GET.get("search") or "").strip()
        selected_item_id = data.get("item_id") or request.GET.get("item_id")

        # Connect to MongoDB
        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        hms_db = client["HMS"]

        pb_col  = hms_db["hospital_pharmacybilling"]
        pat_col = hms_db["hospital_patient"]
        pi_col  = hms_db["hospital_pharmacyitem"]
        ps_col  = hms_db["hospital_pharmacystock"]

        # Date handling (Default to today in Asia/Kolkata if not provided)
        today_str = datetime.now(_KOLKATA_TZ).strftime("%Y-%m-%d")

        if not from_date_str:
            from_date_str = today_str
        if not to_date_str:
            to_date_str = today_str

        from_dt = None
        to_dt = None

        if from_date_str.lower() != "all":
            try:
                from_dt_local = datetime.strptime(from_date_str, "%Y-%m-%d").replace(hour=0, minute=0, second=0)
                from_dt_utc = _KOLKATA_TZ.localize(from_dt_local).astimezone(pytz.utc).replace(tzinfo=None)
                from_dt = min(from_dt_utc, from_dt_local)
            except Exception:
                pass

        if to_date_str.lower() != "all":
            try:
                to_dt_local = datetime.strptime(to_date_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59, microsecond=999999)
                to_dt_utc = _KOLKATA_TZ.localize(to_dt_local).astimezone(pytz.utc).replace(tzinfo=None)
                to_dt = max(to_dt_utc, to_dt_local)
            except Exception:
                pass

        # Build Base Query for Pharmacy Bills (exclude deleted/cancelled/estimates)
        query = {
            "is_deleted": {"$ne": True},
            "billing_status": {"$nin": ["Cancelled", "cancelled", "Deleted", "deleted", "Estimate", "estimate", "ESTIMATE"]},
            "billing_mode": {"$nin": ["ESTIMATE", "estimate"]},
            "bill_no": {"$exists": True, "$ne": None, "$nin": ["", "—", "None", "null"]},
        }
        if hospital_code:
            query["hospital_code"] = hospital_code
        if branch_code:
            query["branch_code"] = branch_code
        if outlet_code:
            query["outlet_code"] = outlet_code

        if from_dt and to_dt:
            query["$or"] = [
                {"bill_date": {"$gte": from_dt, "$lte": to_dt}},
                {"created_date": {"$gte": from_dt, "$lte": to_dt}},
            ]
        elif from_dt:
            query["$or"] = [
                {"bill_date": {"$gte": from_dt}},
                {"created_date": {"$gte": from_dt}},
            ]

        # 1. Resolve Target Item(s) if search_item or selected_item_id is specified
        target_item_ids = set()
        searched_items_meta = {}  # item_id -> item_name
        is_specific_search = bool(search_item or (selected_item_id is not None and str(selected_item_id).strip() != ""))

        if selected_item_id is not None and str(selected_item_id).strip() != "":
            try:
                target_item_ids.add(int(selected_item_id))
            except Exception:
                pass
            target_item_ids.add(str(selected_item_id).strip())

            # Fetch its meta
            for it in pi_col.find({"item_id": {"$in": list(target_item_ids)}}):
                iid = it.get("item_id")
                searched_items_meta[iid] = it.get("item_name", "")
                searched_items_meta[str(iid)] = it.get("item_name", "")

        elif search_item:
            tokens = [t for t in re.split(r'\s+', search_item) if t]
            token_regex = ".*".join([re.escape(t) for t in tokens])
            cat_query = {
                "$or": [
                    {"item_name": {"$regex": re.escape(search_item), "$options": "i"}},
                    {"item_name": {"$regex": token_regex, "$options": "i"}},
                ]
            }
            if search_item.isdigit():
                cat_query["$or"].append({"item_id": int(search_item)})

            for it in pi_col.find(cat_query, {"item_id": 1, "item_name": 1}).limit(100):
                iid = it.get("item_id")
                target_item_ids.add(iid)
                target_item_ids.add(str(iid))
                searched_items_meta[iid] = it.get("item_name", "")
                searched_items_meta[str(iid)] = it.get("item_name", "")

            # Also check pharmacystock if few found
            if len(target_item_ids) < 5:
                for stk in ps_col.find({"item_name": {"$regex": re.escape(search_item), "$options": "i"}}, {"item_id": 1, "item_name": 1}).limit(50):
                    iid = stk.get("item_id")
                    if iid:
                        target_item_ids.add(iid)
                        target_item_ids.add(str(iid))
                        if iid not in searched_items_meta:
                            searched_items_meta[iid] = stk.get("item_name", "")
                            searched_items_meta[str(iid)] = stk.get("item_name", "")

        # If specific items were found from catalog search, add condition to billing query
        if target_item_ids:
            query["medicine_particulars.item_id"] = {"$in": list(target_item_ids)}
        elif is_specific_search and search_item:
            query["medicine_particulars.item_name"] = {"$regex": re.escape(search_item), "$options": "i"}

        # Fetch Bills (sorted by created_date desc)
        raw_bills = list(pb_col.find(query).sort("created_date", -1).limit(3500))

        # Fallback: if 0 bills found with date filter and outlet_code, but specific search was given,
        # check if bills exist without outlet_code filter
        if len(raw_bills) == 0 and is_specific_search and outlet_code:
            fallback_query = {
                "is_deleted": {"$ne": True},
                "billing_status": {"$nin": ["Cancelled", "cancelled", "Deleted", "deleted", "Estimate", "estimate", "ESTIMATE"]},
                "billing_mode": {"$nin": ["ESTIMATE", "estimate"]},
                "bill_no": {"$exists": True, "$ne": None, "$nin": ["", "—", "None", "null"]},
            }
            if hospital_code:
                fallback_query["hospital_code"] = hospital_code
            if branch_code:
                fallback_query["branch_code"] = branch_code
            if from_dt and to_dt:
                fallback_query["$or"] = [
                    {"bill_date": {"$gte": from_dt, "$lte": to_dt}},
                    {"created_date": {"$gte": from_dt, "$lte": to_dt}},
                ]
            if target_item_ids:
                fallback_query["medicine_particulars.item_id"] = {"$in": list(target_item_ids)}
            elif search_item:
                fallback_query["medicine_particulars.item_name"] = {"$regex": re.escape(search_item), "$options": "i"}

            raw_bills = list(pb_col.find(fallback_query).sort("created_date", -1).limit(3500))

        # Helper for float conversion
        def to_num(val):
            if val is None:
                return 0.0
            from bson.decimal128 import Decimal128
            if isinstance(val, Decimal128):
                return float(val.to_decimal())
            try:
                return float(val)
            except Exception:
                return 0.0

        # Group purchases by item_id
        items_acc = {}
        all_uhids = set()
        all_item_ids = set()

        for b in raw_bills:
            b_status_raw = str(b.get("billing_status") or "").strip().lower()
            b_mode_raw = str(b.get("billing_mode") or "").strip().lower()
            b_no_raw = b.get("bill_no")
            b_no_str = str(b_no_raw or "").strip()

            # Strictly exclude Estimates: only billed items should display
            if (
                b_status_raw in ["estimate", "estimated", "cancelled", "deleted"]
                or b_mode_raw == "estimate"
                or not b_no_raw
                or b_no_str in ["", "—", "none", "null"]
                or (b.get("estimate_no") and (not b_no_raw or b_no_str in ["", "—", "none", "null"]))
            ):
                continue

            b_no = b_no_str
            u = str(b.get("uhid") or "").strip()
            raw_ip = str(b.get("inpatient_number") or b.get("ipNumber") or "").strip()
            ip_num = "" if (not raw_ip or raw_ip == "—" or raw_ip.lower() == "none" or raw_ip.upper().startswith("OP")) else raw_ip

            # Extract best timestamp and filter strictly by IST date
            b_date = _extract_best_bill_dt(b)
            if from_date_str.lower() != "all" or to_date_str.lower() != "all":
                b_ist_date = _get_ist_date_str(b_date)
                if b_ist_date:
                    if from_date_str.lower() != "all" and b_ist_date < from_date_str:
                        continue
                    if to_date_str.lower() != "all" and b_ist_date > to_date_str:
                        continue

            # Format Date & Time in IST (Asia/Kolkata): "DD/MM/YYYY hh:mm:ss AM/PM"
            date_time_str = _format_ist_datetime(b_date)

            med_list = b.get("medicine_particulars") or []
            for m in med_list:
                if not isinstance(m, dict):
                    continue
                raw_iid = m.get("item_id")
                m_name = m.get("item_name") or m.get("medicine_name") or ""

                # Check if matches target items if specific search was conducted
                if is_specific_search:
                    matched = False
                    if target_item_ids and (raw_iid in target_item_ids or str(raw_iid) in target_item_ids):
                        matched = True
                    elif search_item and m_name and re.search(re.escape(search_item), m_name, re.IGNORECASE):
                        matched = True
                    if not matched:
                        continue

                item_key = raw_iid if raw_iid is not None else m_name
                if not item_key:
                    continue

                all_item_ids.add(item_key)
                if u and u != "—":
                    all_uhids.add(u)

                qty = to_num(m.get("qty") or m.get("quantity") or 0)

                if item_key not in items_acc:
                    items_acc[item_key] = {
                        "item_id": raw_iid,
                        "item_name": searched_items_meta.get(raw_iid) or searched_items_meta.get(str(raw_iid)) or m_name or "",
                        "total_quantity": 0.0,
                        "uhids": set(),
                        "ip_numbers": set(),
                        "bills": set(),
                        "purchases": [],
                    }

                items_acc[item_key]["total_quantity"] += qty
                if u and u != "—":
                    items_acc[item_key]["uhids"].add(u)
                if ip_num:
                    items_acc[item_key]["ip_numbers"].add(ip_num)
                if b_no and b_no != "—":
                    items_acc[item_key]["bills"].add(b_no)

                items_acc[item_key]["purchases"].append({
                    "uhid": u or "—",
                    "inpatient_number": ip_num,
                    "bill_number": b_no,
                    "bill_date": date_time_str,
                    "purchased_quantity": qty,
                    "batch_number": m.get("batch_number", "—"),
                    "price": to_num(m.get("price", 0)),
                    "calculated_price": to_num(m.get("calculated_price", 0)),
                    "patient_name": b.get("patientname") or b.get("patient_name") or "—",
                    "mobile_number": b.get("phone") or b.get("mobilePhone") or "—",
                })

        # Batch fetch Patient Details for collected UHIDs
        patients_map = {}
        if all_uhids:
            for p in pat_col.find({"uhid": {"$in": list(all_uhids)}}):
                u = p.get("uhid")
                if u:
                    f_name = p.get("firstName") or ""
                    l_name = p.get("lastName") or ""
                    full_name = clean_patient_name(f"{f_name} {l_name}".strip()) or f_name
                    phone = p.get("mobilePhone") or p.get("phone") or ""
                    patients_map[u] = {
                        "name": full_name,
                        "phone": phone,
                        "gender": p.get("gender", ""),
                        "age": p.get("age", ""),
                    }

        # Batch fetch Item Names for all billed item IDs
        item_names_map = dict(searched_items_meta)
        missing_item_ids = [k for k in all_item_ids if k not in item_names_map and str(k) not in item_names_map]
        if missing_item_ids:
            query_ids = []
            for k in missing_item_ids:
                query_ids.append(k)
                if str(k).isdigit():
                    query_ids.append(int(k))
                query_ids.append(str(k))
            for it in pi_col.find({"item_id": {"$in": query_ids}}, {"item_id": 1, "item_name": 1}):
                iid = it.get("item_id")
                name = it.get("item_name", "")
                item_names_map[iid] = name
                item_names_map[str(iid)] = name

            still_missing = [k for k in missing_item_ids if k not in item_names_map and str(k) not in item_names_map]
            if still_missing:
                for stk in ps_col.find({"item_id": {"$in": still_missing}}, {"item_id": 1, "item_name": 1}):
                    iid = stk.get("item_id")
                    name = stk.get("item_name", "")
                    item_names_map[iid] = name
                    item_names_map[str(iid)] = name

        # Enrich purchases with patient details and resolve item names
        final_items = []
        overall_unique_uhids = set()
        overall_unique_ips = set()
        overall_unique_bills = set()
        overall_total_qty = 0.0

        for item_key, info in items_acc.items():
            resolved_name = (
                info["item_name"]
                or item_names_map.get(info["item_id"])
                or item_names_map.get(str(info["item_id"]))
                or item_names_map.get(item_key)
                or str(item_key)
            )

            # Enrich purchases
            enriched_purchases = []
            for p in info["purchases"]:
                u = p["uhid"]
                pat = patients_map.get(u, {})
                pat_name = pat.get("name") or p.get("patient_name") or "—"
                mobile = pat.get("phone") or p.get("mobile_number") or "—"
                enriched_purchases.append({
                    **p,
                    "patient_name": pat_name,
                    "mobile_number": mobile,
                })

            unique_uhid_count = len(info["uhids"])
            unique_ip_count = len(info["ip_numbers"])
            total_bills_count = len(info["bills"])
            total_qty = round(info["total_quantity"], 2)

            overall_unique_uhids.update(info["uhids"])
            overall_unique_ips.update(info["ip_numbers"])
            overall_unique_bills.update(info["bills"])
            overall_total_qty += total_qty

            final_items.append({
                "item_id": info["item_id"],
                "item_name": resolved_name,
                "total_quantity": total_qty,
                "unique_uhid_count": unique_uhid_count,
                "unique_ip_count": unique_ip_count,
                "total_bills_count": total_bills_count,
                "unique_uhids": list(info["uhids"]),
                "unique_ip_numbers": list(info["ip_numbers"]),
                "patients": enriched_purchases,
            })

        # If a specific search was made (e.g. "SEAGATE SATA HDD 1 TB") and 0 bills were found:
        # Provide zero-count record for each searched item or the searched query
        if is_specific_search and len(final_items) == 0:
            if searched_items_meta:
                seen_names = set()
                for iid, iname in searched_items_meta.items():
                    if iname and iname not in seen_names:
                        seen_names.add(iname)
                        final_items.append({
                            "item_id": iid,
                            "item_name": iname,
                            "total_quantity": 0,
                            "unique_uhid_count": 0,
                            "unique_ip_count": 0,
                            "total_bills_count": 0,
                            "unique_uhids": [],
                            "unique_ip_numbers": [],
                            "patients": [],
                        })
            else:
                final_items.append({
                    "item_id": selected_item_id or None,
                    "item_name": search_item,
                    "total_quantity": 0,
                    "unique_uhid_count": 0,
                    "unique_ip_count": 0,
                    "total_bills_count": 0,
                    "unique_uhids": [],
                    "unique_ip_numbers": [],
                    "patients": [],
                })

        # Sort items: by total_quantity descending
        final_items.sort(key=lambda x: x["total_quantity"], reverse=True)

        summary = {
            "total_items": len(final_items),
            "total_quantity": round(overall_total_qty, 2),
            "total_unique_uhids": len(overall_unique_uhids),
            "total_unique_ips": len(overall_unique_ips),
            "total_bills": len(overall_unique_bills),
        }

        return Response({
            "success": True,
            "data": final_items,
            "summary": summary,
            "filters": {
                "from_date": from_date_str,
                "to_date": to_date_str,
                "search_item": search_item,
                "item_id": selected_item_id,
                "outlet_code": outlet_code,
                "hospital_code": hospital_code,
                "branch_code": branch_code,
            }
        }, status=status.HTTP_200_OK)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
