import json
import pytz
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.utils import timezone
from django.db.models import Q

from hospital.models import PatientDietOrder, DietMaster
from pyauth.auth import HasRoleAndDataPermission

import os
from pymongo import MongoClient
from bson import ObjectId

IST = pytz.timezone("Asia/Kolkata")
MONGO_URI = os.getenv("GLOBAL_DB_HOST")


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
        ordered_by       = data.get("auth-user-id", "")
        branch_code      = data.get("auth-branch-code", "")
        hospital_code    = data.get("auth-hospital-code", "")

        if not uhid or not diet_type:
            return Response({"success": False, "error": "uhid and diet_type are required."}, status=400)

        order = PatientDietOrder(
            uhid                 = uhid,
            inpatient_number     = ip_number,
            patient_name         = patient_name,
            ward_name            = ward_name,
            room_no              = room_no,
            food_items           = food_items,
            diet_type            = diet_type,
            special_diet_note    = special_diet_note,
            meal_time            = meal_time,
            extra_items          = json.dumps(extra_items),
            attender_count       = attender_count,
            special_instructions = special_instructions,
            status               = "Ordered",
            ordered_by           = ordered_by,
            order_date           = timezone.now(),
            branch_code          = branch_code,
            hospital_code        = hospital_code,
        )
        order.save()

        return Response({"success": True, "diet_id": str(order.diet_id)})

    except Exception as e:
        import traceback
        return Response({"success": False, "error": str(e), "trace": traceback.format_exc()}, status=500)


# ─── Get Diet Orders for a patient ────────────────────────────────────────────
@csrf_exempt
@api_view(["GET"])
# @permission_classes([IsAuthenticated])
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
                    if hasattr(order_date, "astimezone"):
                        order_date_ist = order_date.astimezone(IST)
                    else:
                        order_date_ist = IST.localize(order_date)
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
# @permission_classes([IsAuthenticated])
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
                    "diet_name":       doc.get('diet_name', ""),
                    "morning_items":   doc.get('morning_items', ""),
                    "afternoon_items": doc.get('afternoon_items', ""),
                    "evening_items":   doc.get('evening_items', ""),
                    "dinner_items":    doc.get('dinner_items', ""),
                    "is_active":       doc.get('is_active', True),
                })

        return Response({"success": True, "data": data})

    except Exception as e:
        import traceback
        return Response({"success": False, "error": str(e), "trace": traceback.format_exc()}, status=500)

@csrf_exempt
@api_view(["POST"])
# @permission_classes([HasRoleAndDataPermission])
def save_diet_master(request):
    try:
        data       = request.data
        diet_id    = data.get("diet_id")
        diet_name  = data.get("diet_name")
        morning_items   = data.get("morning_items")
        afternoon_items = data.get("afternoon_items")
        evening_items   = data.get("evening_items")
        dinner_items    = data.get("dinner_items")
        is_active       = data.get("is_active", True)
        user_id         = data.get("auth-user-id")

        if not diet_name:
            return Response({"success": False, "error": "diet_name is required."}, status=400)

        try:
            if diet_id:
                master = DietMaster.objects.get(id=diet_id)
            else:
                master = DietMaster()

            master.diet_name        = diet_name
            master.morning_items    = morning_items
            master.afternoon_items  = afternoon_items
            master.evening_items    = evening_items
            master.dinner_items     = dinner_items
            master.is_active        = is_active
            if diet_id:
                master.lastmodified_by = user_id
            else:
                master.created_by = user_id
                
            master.save()
            save_id = str(master.pk)
        except Exception as orm_save_error:
            # FALLBACK: Use direct Pymongo for saving if ORM fails
            print(f"ORM Save Error, falling back to Pymongo: {str(orm_save_error)}")
            from django.conf import settings
            import pymongo
            client = pymongo.MongoClient(settings.DATABASES['default']['CLIENT']['host'])
            db = client[settings.DATABASES['default']['NAME']]
            col = db['hospital_dietmaster']
            
            from bson import ObjectId
            update_data = {
                "diet_name":        diet_name,
                "morning_items":    morning_items,
                "afternoon_items":  afternoon_items,
                "evening_items":    evening_items,
                "dinner_items":     dinner_items,
                "is_active":        is_active,
                "hospital_code":    "SH001" 
            }
            if diet_id:
                col.update_one({"_id": ObjectId(diet_id)}, {"$set": update_data})
                save_id = diet_id
            else:
                res = col.insert_one(update_data)
                save_id = str(res.inserted_id)

        return Response({"success": True, "diet_id": save_id})
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return Response({"success": False, "error": f"Save Error: {str(e)}"}, status=500)


# ─── Comprehensive Diet Order Report ──────────────────────────────────────────
@csrf_exempt
@api_view(["GET"])
# @permission_classes([IsAuthenticated])
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

        with MongoClient(MONGO_URI) as client:
            db = client["HMS"]
            col = db["hospital_patientdietorder"]
            cursor = col.find(query).sort("order_date", -1)

            orders = []
            for o in cursor:
                # Date Formatting
                order_date = o.get("order_date")
                if order_date:
                    if hasattr(order_date, "astimezone"):
                        order_date_ist = order_date.astimezone(IST)
                    else:
                        # If order_date is naive from mongo? improbable but safe.
                        from datetime import datetime
                        if not isinstance(order_date, datetime):
                            order_date = datetime.fromisoformat(str(order_date))
                        order_date_ist = IST.localize(order_date) if order_date.tzinfo is None else order_date.astimezone(IST)
                    
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
