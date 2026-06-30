import json
import pytz
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.utils import timezone
from django.db.models import Q

from hospital.models import PatientDietOrder, DietMaster, DietExtraMaster
from pyauth.auth import HasRoleAndDataPermission

import os
from pymongo import MongoClient
from bson import ObjectId
from bson.decimal128 import Decimal128

IST = pytz.timezone("Asia/Kolkata")
MONGO_URI = os.getenv("GLOBAL_DB_HOST")

def to_float(value):
    if value is None:
        return 0.0
    if isinstance(value, Decimal128):
        return float(value.to_decimal())
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


# ─── Save / Place a new Diet Order ────────────────────────────────────────────
@csrf_exempt
@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def save_diet_order(request):
    try:
        data = request.data

        uhid             = data.get("uhid", "")
        ip_number        = data.get("inpatient_number") or data.get("ipNumber", "")
        patient_name     = data.get("patient_name", "")
        ward_name        = data.get("ward_name", "")
        room_no          = data.get("room_no", "")
        food_items       = data.get("food_items", "")
        diet_type        = data.get("diet_type", "")
        special_diet_note = data.get("special_diet_note", "")
        meal_time        = data.get("meal_time", "Lunch")
        extra_items      = data.get("extra_items", [])          # list of {item, qty}
        attender_count   = int(data.get("attender_count", 0))
        special_instructions = data.get("special_instructions", "")

        diet_price        = to_float(data.get("diet_price", 0))
        extra_items_price = to_float(data.get("extra_items_price", 0))
        total_price       = to_float(data.get("total_price", 0))

        ordered_by       = data.get("auth-user-id", "")
        branch_code      = data.get("auth-branch-code", "")
        hospital_code    = data.get("auth-hospital-code", "")

        if not uhid or not diet_type:
            return Response({"success": False, "error": "uhid and diet_type are required."}, status=400)

        diet_id = data.get("diet_id")
        
        # Use MongoClient for updates to handle MongoDB string IDs
        with MongoClient(MONGO_URI) as client:
            db = client["HMS"]
            col = db["hospital_patientdietorder"]
            
            if diet_id:
                try:
                    oid = ObjectId(diet_id)
                    existing = col.find_one({"_id": oid})
                    if not existing:
                        return Response({"success": False, "error": "Order not found"}, status=404)
                    
                    if existing.get("status") != "Ordered":
                        return Response({"success": False, "error": f"Cannot edit order with status {existing.get('status')}"}, status=400)
                    
                    # Update existing record
                    col.update_one(
                        {"_id": oid},
                        {"$set": {
                            "uhid": uhid,
                            "inpatient_number": ip_number,
                            "patient_name": patient_name,
                            "ward_name": ward_name,
                            "room_no": room_no,
                            "food_items": food_items,
                            "diet_type": diet_type,
                            "special_diet_note": special_diet_note,
                            "meal_time": meal_time,
                            "extra_items": extra_items,
                            "attender_count": attender_count,
                            "special_instructions": special_instructions,
                            "diet_price": Decimal128(str(diet_price)),
                            "extra_items_price": Decimal128(str(extra_items_price)),
                            "total_price": Decimal128(str(total_price)),
                            "ordered_by": ordered_by,
                            "branch_code": branch_code,
                            "hospital_code": hospital_code,
                            "lastmodified_by": ordered_by,
                            "lastmodified_date": timezone.now()
                        }}
                    )
                    return Response({"success": True, "message": "Order updated successfully"})
                except Exception as e:
                    return Response({"success": False, "error": f"Update Error: {str(e)}"}, status=500)
            else:
                # Create new record via ORM (safe for new records)
                order = PatientDietOrder()
                order.uhid                 = uhid
                order.inpatient_number     = ip_number
                order.patient_name         = patient_name
                order.ward_name            = ward_name
                order.room_no              = room_no
                order.food_items           = food_items
                order.diet_type            = diet_type
                order.special_diet_note    = special_diet_note
                order.meal_time            = meal_time
                order.extra_items          = extra_items
                order.attender_count       = attender_count
                order.special_instructions = special_instructions
                order.diet_price           = diet_price
                order.extra_items_price    = extra_items_price
                order.total_price          = total_price
                order.status               = "Ordered"
                order.order_date           = timezone.now()
                order.ordered_by           = ordered_by
                order.branch_code          = branch_code
                order.hospital_code        = hospital_code
                order.save()
                return Response({"success": True, "message": "Order placed successfully"})

    except Exception as e:
        import traceback
        return Response({"success": False, "error": str(e), "trace": traceback.format_exc()}, status=500)


# ─── Get Diet Orders for a patient ────────────────────────────────────────────
@csrf_exempt
@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_diet_orders(request):
    try:
        uhid       = request.GET.get("uhid", "")
        ip_number  = request.GET.get("ipNumber", "")

        if not uhid:
            return Response({"success": False, "error": "uhid is required."}, status=400)

        query = {"uhid": uhid}
        if ip_number:
            query["inpatient_number"] = ip_number

        with MongoClient(MONGO_URI) as client:
            db = client["HMS"]
            col = db["hospital_patientdietorder"]
            cursor = col.find(query).sort("order_date", -1)
            
            orders = []
            for o in cursor:
                # Date Formatting
                order_date = o.get("order_date")
                if order_date:
                    if order_date.tzinfo is None:
                        # Naive datetime from MongoDB, assume UTC
                        order_date = pytz.utc.localize(order_date)
                    
                    order_date_ist = order_date.astimezone(IST)
                    date_str = order_date_ist.strftime("%d-%m-%Y")
                    time_str = order_date_ist.strftime("%I:%M %p")
                else:
                    date_str = time_str = ""

                orders.append({
                    "diet_id":             str(o.get("_id")),
                    "uhid":                o.get("uhid"),
                    "inpatient_number":    o.get("inpatient_number"),
                    "patient_name":        o.get("patient_name"),
                    "ward_name":           o.get("ward_name"),
                    "room_no":             o.get("room_no"),
                    "diet_type":           o.get("diet_type"),
                    "food_items":          o.get("food_items"),
                    "special_diet_note":   o.get("special_diet_note"),
                    "meal_time":           o.get("meal_time"),
                    "extra_items":         json.loads(o.get("extra_items") or "[]") if isinstance(o.get("extra_items"), str) else o.get("extra_items", []),
                    "attender_count":      o.get("attender_count", 0),
                    "diet_price":          to_float(o.get("diet_price", 0)),
                    "extra_items_price":   to_float(o.get("extra_items_price", 0)),
                    "total_price":         to_float(o.get("total_price", 0)),
                    "special_instructions": o.get("special_instructions"),
                    "status":              o.get("status"),
                    "ordered_by":          o.get("ordered_by"),
                    "order_date":          date_str,
                    "order_time":          time_str,
                })

        return Response({"success": True, "data": orders})

    except Exception as e:
        import traceback
        return Response({"success": False, "error": str(e), "trace": traceback.format_exc()}, status=500)


# ─── Update Diet Order Status ──────────────────────────────────────────────────
@csrf_exempt
@api_view(["POST", "PATCH"])
@permission_classes([HasRoleAndDataPermission])
def update_diet_status(request):
    try:
        data     = request.data
        diet_id  = data.get("diet_id")
        status   = data.get("status", "")
        modified_by = data.get("auth-user-id", "")

        if not diet_id:
            return Response({"success": False, "error": "diet_id is required."}, status=400)

        valid_statuses = ["Ordered", "Received", "Delivered", "Cancelled"]
        if status not in valid_statuses:
            return Response({"success": False, "error": f"Invalid status. Choose from {valid_statuses}"}, status=400)

        with MongoClient(MONGO_URI) as client:
            db = client["HMS"]
            col = db["hospital_patientdietorder"]
            
            # Try to update by _id (which is diet_id)
            try:
                oid = ObjectId(diet_id)
            except:
                return Response({"success": False, "error": "Invalid ID format."}, status=400)

            res = col.update_one(
                {"_id": oid},
                {"$set": {
                    "status": status,
                    "lastmodified_by": modified_by,
                    "lastmodified_date": timezone.now()
                }}
            )

            if res.matched_count == 0:
                return Response({"success": False, "error": "Diet order not found."}, status=404)

        return Response({"success": True, "diet_id": diet_id, "status": status})

    except Exception as e:
        import traceback
        return Response({"success": False, "error": str(e), "trace": traceback.format_exc()}, status=500)


# ─── Diet Master Views ────────────────────────────────────────────────────────
@csrf_exempt
@api_view(["GET"])
# @permission_classes([IsAuthenticated])
def get_diet_master(request):
    try:
        active_only = request.GET.get("active_only", "true").lower() == "true"
        
        query = {}
        if active_only:
            query["is_active"] = True

        with MongoClient(MONGO_URI) as client:
            db = client["HMS"]
            col = db["hospital_dietmaster"]
            cursor = col.find(query).sort("diet_name", 1)
            
            data = []
            for doc in cursor:
                data.append({
                    "diet_id":         str(doc.get('_id')),
                    "item_id":         doc.get('item_id', ""),
                    "diet_name":       doc.get('diet_name', ""),
                    "morning_items":   doc.get('morning_items', ""),
                    "afternoon_items": doc.get('afternoon_items', ""),
                    "evening_items":   doc.get('evening_items', ""),
                    "dinner_items":    doc.get('dinner_items', ""),
                    "price":           to_float(doc.get('price', 0)),
                    "is_active":       doc.get('is_active', True),
                })

        return Response({"success": True, "data": data})

    except Exception as e:
        import traceback
        return Response({"success": False, "error": str(e), "trace": traceback.format_exc()}, status=500)


# ─── Add Extra Food to Existing Order ─────────────────────────────────────────
@csrf_exempt
@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def add_extra_to_order(request):
    try:
        data = request.data
        diet_id = data.get("diet_id")
        extra_item = data.get("extra_item") # {item_name, qty, price}
        
        if not diet_id or not extra_item:
            return Response({"success": False, "error": "diet_id and extra_item are required."}, status=400)
            
        with MongoClient(MONGO_URI) as client:
            db = client["HMS"]
            col = db["hospital_patientdietorder"]
            
            try:
                oid = ObjectId(diet_id)
            except:
                return Response({"success": False, "error": "Invalid ID format."}, status=400)

            order = col.find_one({"_id": oid})
            if not order:
                return Response({"success": False, "error": "Order not found."}, status=404)
            
            current_extras = json.loads(order.get("extra_items") or "[]") if isinstance(order.get("extra_items"), str) else order.get("extra_items", [])
            current_extras.append(extra_item)
            
            extra_price = to_float(extra_item.get("price", 0)) * int(extra_item.get("qty", 1))
            new_extra_total = to_float(order.get("extra_items_price", 0)) + extra_price
            new_grand_total = to_float(order.get("total_price", 0)) + extra_price
            
            col.update_one(
                {"_id": oid},
                {"$set": {
                    "extra_items": current_extras,
                    "extra_items_price": new_extra_total,
                    "total_price": new_grand_total
                }}
            )
            
        return Response({"success": True})
    except Exception as e:
        import traceback
        return Response({"success": False, "error": str(e), "trace": traceback.format_exc()}, status=500)

@csrf_exempt
@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def update_diet_order_extras(request):
    try:
        data = request.data
        diet_id = data.get("diet_id")
        extra_items = data.get("extra_items") # List of {item_name, qty, price}
        
        if not diet_id or extra_items is None:
            return Response({"success": False, "error": "diet_id and extra_items are required."}, status=400)
            
        with MongoClient(MONGO_URI) as client:
            db = client["HMS"]
            col = db["hospital_patientdietorder"]
            
            try:
                oid = ObjectId(diet_id)
            except:
                return Response({"success": False, "error": "Invalid ID format."}, status=400)

            order = col.find_one({"_id": oid})
            if not order:
                return Response({"success": False, "error": "Order not found."}, status=404)
            
            # Recalculate totals
            extra_items_price = sum(to_float(item.get("price", 0)) * int(item.get("qty", 1)) for item in extra_items)
            diet_price = to_float(order.get("diet_price", 0))
            total_price = diet_price + extra_items_price
            
            col.update_one(
                {"_id": oid},
                {"$set": {
                    "extra_items": extra_items,
                    "extra_items_price": extra_items_price,
                    "total_price": total_price
                }}
            )
            
        return Response({"success": True})
    except Exception as e:
        import traceback
        return Response({"success": False, "error": str(e), "trace": traceback.format_exc()}, status=500)

@csrf_exempt
@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def save_diet_master(request):
    try:
        data       = request.data
        diet_id    = data.get("diet_id")
        diet_name  = data.get("diet_name")
        morning_items   = data.get("morning_items")
        afternoon_items = data.get("afternoon_items")
        evening_items   = data.get("evening_items")
        dinner_items    = data.get("dinner_items")
        price           = to_float(data.get("price", 0))
        is_active       = data.get("is_active", True)
        user_id         = data.get("auth-user-id")
        custom_item_id  = data.get("item_id", "")

        if not diet_name:
            return Response({"success": False, "error": "diet_name is required."}, status=400)

        from django.conf import settings
        import pymongo
        from bson import ObjectId
        import uuid
        
        client = pymongo.MongoClient(settings.DATABASES['default']['CLIENT']['host'])
        db = client[settings.DATABASES['default']['NAME']]
        col = db['hospital_dietmaster']

        update_data = {
            "diet_name": diet_name,
            "morning_items": morning_items,
            "afternoon_items": afternoon_items,
            "evening_items": evening_items,
            "dinner_items": dinner_items,
            "price": price,
            "is_active": is_active,
            "hospital_code": "SH001"
        }
        
        if custom_item_id:
            update_data["item_id"] = custom_item_id
        
        if diet_id:
            update_data["lastmodified_by"] = user_id
            col.update_one({"_id": ObjectId(diet_id)}, {"$set": update_data})
            save_id = diet_id
        else:
            update_data["created_by"] = user_id
            if custom_item_id:
                update_data["item_id"] = custom_item_id
            else:
                last_item = col.find_one({"item_id": {"$regex": "^D-"}}, sort=[("_id", pymongo.DESCENDING)])
                new_id = "D-01"
                if last_item and last_item.get("item_id"):
                    try:
                        last_num = int(last_item["item_id"].replace("D-", ""))
                        new_id = f"D-{last_num + 1:02d}"
                    except:
                        pass
                update_data["item_id"] = new_id
                
            res = col.insert_one(update_data)
            save_id = str(res.inserted_id)
        
        client.close()

        return Response({"success": True, "diet_id": save_id})
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return Response({"success": False, "error": f"Save Error: {str(e)}"}, status=500)


# ─── Comprehensive Diet Order Report ──────────────────────────────────────────
@csrf_exempt
@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_all_diet_orders(request):
    try:
        from_date = request.GET.get("from_date")
        to_date   = request.GET.get("to_date")
        status    = request.GET.get("status")

        query = {}
        if from_date and to_date:
            from datetime import datetime, timedelta
            start_ist = IST.localize(datetime.strptime(from_date, "%Y-%m-%d"))
            end_ist   = IST.localize(datetime.strptime(to_date, "%Y-%m-%d") + timedelta(days=1))
            start_utc = start_ist.astimezone(pytz.UTC)
            end_utc   = end_ist.astimezone(pytz.UTC)
            query["order_date"] = {"$gte": start_utc, "$lt": end_utc}

        if status:
            query["status"] = status
        
        meal_time = request.GET.get("meal_time")
        if meal_time:
            query["meal_time"] = meal_time

        diet_type = request.GET.get("diet_type")
        if diet_type:
            query["diet_type"] = diet_type

        with MongoClient(MONGO_URI) as client:
            db = client["HMS"]
            col = db["hospital_patientdietorder"]
            cursor = col.find(query).sort("order_date", -1)

            orders = []
            for o in cursor:
                # Date Formatting
                order_date = o.get("order_date")
                if order_date:
                    if order_date.tzinfo is None:
                        # Naive datetime from MongoDB, assume UTC
                        order_date = pytz.utc.localize(order_date)
                    
                    order_date_ist = order_date.astimezone(IST)
                    date_str = order_date_ist.strftime("%d-%m-%Y")
                    time_str = order_date_ist.strftime("%I:%M %p")
                else:
                    date_str = time_str = ""

                orders.append({
                    "diet_id":             str(o.get("_id")),
                    "uhid":                o.get("uhid"),
                    "inpatient_number":    o.get("inpatient_number"),
                    "patient_name":        o.get("patient_name"),
                    "ward_name":           o.get("ward_name"),
                    "room_no":             o.get("room_no"),
                    "diet_type":           o.get("diet_type"),
                    "food_items":          o.get("food_items"),
                    "special_diet_note":   o.get("special_diet_note"),
                    "meal_time":           o.get("meal_time"),
                    "extra_items":         json.loads(o.get("extra_items") or "[]") if isinstance(o.get("extra_items"), str) else o.get("extra_items", []),
                    "attender_count":      o.get("attender_count", 0),
                    "diet_price":          to_float(o.get("diet_price", 0)),
                    "extra_items_price":   to_float(o.get("extra_items_price", 0)),
                    "total_price":         to_float(o.get("total_price", 0)),
                    "special_instructions": o.get("special_instructions"),
                    "status":              o.get("status"),
                    "ordered_by":          o.get("ordered_by"),
                    "order_date":          date_str,
                    "order_time":          time_str,
                })

        return Response({"success": True, "data": orders})

    except Exception as e:
        import traceback
        return Response({"success": False, "error": str(e), "trace": traceback.format_exc()}, status=500)

# ─── Diet Extra Master Views ──────────────────────────────────────────────────
@csrf_exempt
@api_view(["GET"])
def get_diet_extra_master(request):
    try:
        active_only = request.GET.get("active_only", "true").lower() == "true"
        query = {}
        if active_only:
            query["is_active"] = True

        with MongoClient(MONGO_URI) as client:
            db = client["HMS"]
            col = db["hospital_dietextramaster"]
            cursor = col.find(query).sort("item_name", 1)
            
            data = []
            for doc in cursor:
                data.append({
                    "extra_id":    str(doc.get('_id')),
                    "item_id":     doc.get('item_id', ""),
                    "item_name":   doc.get('item_name', ""),
                    "price":       to_float(doc.get('price', 0)),
                    "is_active":   doc.get('is_active', True),
                })

        return Response({"success": True, "data": data})
    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=500)

@csrf_exempt
@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def save_diet_extra_master(request):
    try:
        data       = request.data
        extra_id   = data.get("extra_id")
        item_name  = data.get("item_name")
        price      = to_float(data.get("price", 0))
        is_active  = data.get("is_active", True)
        user_id    = data.get("auth-user-id")
        custom_item_id  = data.get("item_id", "")

        if not item_name:
            return Response({"success": False, "error": "item_name is required."}, status=400)

        from django.conf import settings
        import pymongo
        from bson import ObjectId
        import uuid

        client = pymongo.MongoClient(settings.DATABASES['default']['CLIENT']['host'])
        db = client[settings.DATABASES['default']['NAME']]
        col = db['hospital_dietextramaster']
        
        update_data = {
            "item_name": item_name,
            "price": price,
            "is_active": is_active,
        }
        if custom_item_id:
            update_data["item_id"] = custom_item_id

        if extra_id:
            col.update_one({"_id": ObjectId(extra_id)}, {"$set": update_data})
            save_id = extra_id
        else:
            update_data["created_by"] = user_id
            if custom_item_id:
                update_data["item_id"] = custom_item_id
            else:
                last_item = col.find_one({"item_id": {"$regex": "^E-"}}, sort=[("_id", pymongo.DESCENDING)])
                new_id = "E-01"
                if last_item and last_item.get("item_id"):
                    try:
                        last_num = int(last_item["item_id"].replace("E-", ""))
                        new_id = f"E-{last_num + 1:02d}"
                    except:
                        pass
                update_data["item_id"] = new_id
                
            res = col.insert_one(update_data)
            save_id = str(res.inserted_id)

        client.close()
        return Response({"success": True, "extra_id": save_id})
    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=500)
