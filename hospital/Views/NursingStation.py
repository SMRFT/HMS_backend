from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
import os
from datetime import datetime, timedelta
from ..models import Admission, PharmacyBilling, PharmacyItem
from ..serializers import AdmissionSerializer
from django.conf import settings
from django.db import DatabaseError
from django.http import JsonResponse
from pymongo import MongoClient
from datetime import datetime
from django.utils import timezone

# Auth/permissions
from pyauth.auth import HasRoleAndDataPermission, HasRolePermission
from rest_framework.decorators import api_view, permission_classes



import traceback

import pytz

from rest_framework.decorators import api_view
from rest_framework.response import Response
from datetime import datetime, timedelta
import pytz
import traceback

from pymongo import MongoClient, ReturnDocument
import os

MONGO_URI = os.getenv("GLOBAL_DB_HOST")
client = MongoClient(MONGO_URI)
mongo_db = client["HMS"]
global_db = client["Global"]
profile_collection = global_db["backend_diagnostics_profile"]
room_collection = mongo_db["hospital_room"]

@api_view(["GET"])
# @permission_classes([HasRoleAndDataPermission])
def get_admission_list(request):
    try:
        from_date = request.GET.get("from_date")
        to_date = request.GET.get("to_date")

        print("FROM DATE:", from_date)
        print("TO DATE:", to_date)

        query = {"is_admissionActive": True}

        if from_date and to_date:
            ist = pytz.timezone("Asia/Kolkata")
            start_ist = ist.localize(datetime.strptime(from_date, "%Y-%m-%d"))
            end_ist = ist.localize(datetime.strptime(to_date, "%Y-%m-%d") + timedelta(days=1))
            start_utc = start_ist.astimezone(pytz.UTC)
            end_utc = end_ist.astimezone(pytz.UTC)
            
            print("START UTC:", start_utc)
            print("END UTC:", end_utc)
            query["admissionDateTime"] = {"$gte": start_utc, "$lt": end_utc}
            
        raw_admissions = list(mongo_db["hospital_admission"].find(query).sort("admissionDateTime", -1))
        
        # Serialize BSON properly
        data = serialize_doc(raw_admissions)
        
        # Convert _id string to id
        for item in data:
            if "_id" in item:
                item["id"] = item["_id"]

        print("TOTAL FILTERED RECORDS:", len(data))

        # -----------------------------------------
        # ADDITIONAL DATA ENRICHMENT
        # -----------------------------------------
        for item in data:

            print("Processing item:", item.get("ipNumber"))

            # -----------------------------
            # PATIENT NAME MAPPING
            # -----------------------------
            patient_details = item.get("patient_details", {})
            if not patient_details and item.get("uhid"):
                patient_doc = mongo_db.hospital_patient.find_one({"uhid": item.get("uhid")})
                if patient_doc:
                    item["patient_details"] = serialize_doc(patient_doc)
                    patient_details = item["patient_details"]

            if patient_details:
                fname = patient_details.get("firstName", "")
                lname = patient_details.get("lastName", "")
                item["patient_name"] = f"{fname} {lname}".strip()
            else:
                item["patient_name"] = ""

            # -----------------------------
            # DOCTOR NAME MAPPING
            # -----------------------------
            for doctor_field in ["admittingDoctor", "consultingDoctor"]:

                doctor_id = item.get(doctor_field)

                print("Doctor field:", doctor_field)
                print("Doctor ID from API:", doctor_id)

                if doctor_id:
                    doctor_id = str(doctor_id)

                    print("Searching Mongo for employeeId:", doctor_id)

                    doc = profile_collection.find_one(
                        {"employeeId": {"$in": [doctor_id, int(doctor_id)]}},
                        {"employeeName": 1, "_id": 0}
                    )

                    print("Mongo result:", doc)

                    if doc:
                        item[doctor_field] = doc.get("employeeName")
                        print("Doctor name replaced:", doc.get("employeeName"))
                    else:
                        print("Doctor not found in Mongo")

            # -----------------------------
            # ROOM DETAILS MAPPING
            # -----------------------------
            room_no = item.get("roomNo")

            # --- Room/Bed Fallback Logic (Manual Mongo Fetch) ---
            if not room_no or not item.get("bedNo"):
                # Fetching raw document for native arrays
                raw_admission = mongo_db.hospital_admission.find_one({"ipNumber": item.get("ipNumber")})
                if raw_admission:
                    for field in ["roomShiftingDetails", "roomShitingDetails", "room_details"]:
                        shifting = raw_admission.get(field, [])
                        if shifting and isinstance(shifting, list):
                            active_shift = next((s for s in shifting if s.get("is_roomActive")), None)
                            if active_shift:
                                item["roomNo"] = active_shift.get("roomNo", "")
                                item["bedNo"] = active_shift.get("bedNo", "")
                                room_no = item["roomNo"]
                                break
            
            print("Final Room number for lookup:", room_no)

            if room_no:
                room = room_collection.find_one(
                    {"room_number": room_no},
                    {
                        "_id": 0,
                        "room_number": 1,
                        "room_category": 1,
                        "block": 1,
                        "nursing_station": 1
                    }
                )

                print("Room Mongo result:", room)

                if room:
                    room_cat_name = room.get("room_category")
                    block_name = room.get("block")
                    station_name = room.get("nursing_station")

                    item["room_category"] = room_cat_name
                    item["block"] = block_name
                    item["nursing_station"] = station_name

                    # --- Add IDs for Frontend Filtering ---
                    if block_name:
                        block_obj = mongo_db.hospital_block.find_one({"block_name": block_name}, {"block_id": 1})
                        if block_obj:
                            item["block_id"] = str(block_obj.get("block_id"))

                    if room_cat_name:
                        cat_obj = mongo_db.hospital_roomcategory.find_one({"category_name": room_cat_name}, {"room_category_id": 1})
                        if cat_obj:
                            item["room_category_id"] = str(cat_obj.get("room_category_id"))

                    if station_name:
                        station_obj = mongo_db.hospital_Wards.find_one({"ward_name": station_name}, {"_id": 1})
                        if station_obj:
                            item["nursing_station_id"] = str(station_obj.get("_id"))

                    print("Room data and IDs added")
                else:
                    print("Room not found")
                    item["room_category"] = None
                    item["block"] = None
                    item["nursing_station"] = None

        return Response({
            "success": True,
            "count": len(data),
            "data": data
        })

    except Exception as e:
        print("ERROR OCCURRED")
        print(traceback.format_exc())

        return Response({
            "success": False,
            "error": str(e)
        }, status=500)
    


    

from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from pymongo import MongoClient
import os

# MongoDB Configuration
MONGO_URI = os.getenv("GLOBAL_DB_HOST")
DB_NAME = "HMS"
COLLECTION_NAME = "hospital_nursingstation"

client = MongoClient(MONGO_URI)
mongo_db = client[DB_NAME]
collection = mongo_db[COLLECTION_NAME]


@api_view(["GET"])
# @permission_classes([HasRoleAndDataPermission])
def get_wards_list(request):
    try:
        # ✅ Fetch only active wards
        wards_cursor = collection.find(
            {"is_active": True},      # filter
            {"_id": 1, "ward_name": 1}  # projection (include _id)
        )

        wards = []
        for d in wards_cursor:
            wards.append({
                "id": str(d["_id"]),
                "ward_name": d.get("ward_name", "")
            })

        return Response({
            "success": True,
            "data": wards
        }, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({
            "success": False,
            "error": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(["GET"])
def get_location_mapping(request):
    """
    Returns a complete mapping of all rooms to their blocks, categories, and nursing stations.
    Used for perfect bidirectional filtering on the frontend.
    """
    try:
        rooms = list(mongo_db["hospital_room"].find(
            {"is_active": True},
            {"room_number": 1, "room_category": 1, "block": 1, "nursing_station": 1}
        ))
        
        # Pre-fetch ID mappings to avoid repeated lookups
        blocks_map = {b["block_name"]: str(b["block_id"]) for b in mongo_db["hospital_block"].find({}, {"block_name": 1, "block_id": 1})}
        cats_map = {c["category_name"]: str(c["room_category_id"]) for c in mongo_db["hospital_roomcategory"].find({}, {"category_name": 1, "room_category_id": 1})}
        wards_map = {w["ward_name"]: str(w["_id"]) for w in mongo_db["hospital_Wards"].find({}, {"ward_name": 1})}

        enriched = []
        for r in rooms:
            b_name = r.get("block")
            c_name = r.get("room_category")
            s_name = r.get("nursing_station")
            
            enriched.append({
                "room_no": r.get("room_number"),
                "block": b_name,
                "block_id": blocks_map.get(b_name),
                "category": c_name,
                "room_category_id": cats_map.get(c_name),
                "nursing_station": s_name,
                "nursing_station_id": wards_map.get(s_name)
            })
            
        return Response({"success": True, "data": enriched})
    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=500)


MONGO_URI = os.getenv("GLOBAL_DB_HOST")
client = MongoClient(MONGO_URI)
mongo_db = client["HMS"]

@api_view(["GET"])
# @permission_classes([HasRoleAndDataPermission])
def get_LabBillType_list(request):
    try:
        collection = mongo_db["hospital_billtype"]

        # Fetch all active bill types intended for ward requests
        billtypes_cursor = collection.find(
            {
                "ward_request": True,
                "is_active": True
            },
            {
                "_id": 0
            }
        )
        
        billtypes = list(billtypes_cursor)

        if not billtypes:
            return Response({
                "success": False,
                "message": "No Lab Bill Types found for ward requests"
            })

        return Response({
            "success": True,
            "data": billtypes
        })

    except Exception as e:
        return Response({
            "success": False,
            "error": str(e)
        })



from rest_framework.response import Response
from rest_framework.decorators import api_view
from ..models import Admission
from ..serializers import AdmissionSerializer

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def uhidadmissionstatus(request):

    uhid = request.GET.get("uhid")

    admission = mongo_db["hospital_admission"].find_one({"uhid": uhid})

    if not admission:
        return Response({
            "success": True,
            "admitted": False,
            "data": []
        })

    admitted = False

    # ✅ Updated condition including is_admitted
    if (
        admission.get("is_admitted") is True and
        admission.get("is_admissionActive") is True and
        admission.get("is_discharged") is False
    ):
        admitted = True

    formatted_data = serialize_doc(admission)

    if "_id" in formatted_data:
        formatted_data["id"] = formatted_data["_id"]

    return Response({
        "success": True,
        "admitted": admitted,
        "data": formatted_data
    })

def serialize_doc(doc):
    """Recursively convert MongoDB types to JSON-serializable types."""
    from bson import Decimal128, ObjectId
    import json
    if isinstance(doc, dict):
        return {k: serialize_doc(v) for k, v in doc.items()}
    elif isinstance(doc, list):
        return [serialize_doc(i) for i in doc]
    elif isinstance(doc, Decimal128):
        return float(doc.to_decimal())
    elif isinstance(doc, ObjectId):
        return str(doc)
    elif isinstance(doc, datetime):
        return doc.isoformat()
    return doc

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_lab_ward_requests(request):
    try:
        uhid = request.GET.get("uhid")
        ip_number = request.GET.get("ipNumber")

        query = {
            "is_active": True,
            "is_ward_request": True,
            "ward_request_type": "LAB"
        }
        if uhid:
            query["uhid"] = uhid
        if ip_number:
            query["ipNumber"] = ip_number

        # Fetch from the centralized investbilling collection
        ward_req_collection = mongo_db["hospital_investbilling"]
        requests_data = list(ward_req_collection.find(query).sort("created_date", -1))

        # Enrich and format for the frontend component
        formatted_data = []
        for doc in requests_data:
            import json
            # Parse 'item' field back to list
            item_data = doc.get("item", "[]")
            if isinstance(item_data, str):
                try:
                    items = json.loads(item_data)
                except json.JSONDecodeError:
                    items = []
            else:
                items = item_data
            
            # Map tests for the frontend structure
            tests = []
            for itm in items:
                tests.append({
                    "test_id": itm.get("test_id", ""),
                    "name": itm.get("itemName", ""),
                    "collectionTime": itm.get("collectionTime", "") 
                })
            
            formatted_doc = {
                "id": str(doc.get("_id")),
                "status": doc.get("status", "Result Pending"),
                "reqDate": doc.get("created_date").strftime("%d/%m/%Y") if doc.get("created_date") else "",
                "reqTime": doc.get("created_date").strftime("%I:%M %p") if doc.get("created_date") else "",
                "userName": doc.get("created_by", ""),
                "billNo": doc.get("investBillNo", ""),
                "wardName": doc.get("wardName", ""),
                "doctorName": doc.get("doctor", ""),
                "tests": tests
            }
            formatted_data.append(formatted_doc)

        return Response({
            "success": True,
            "data": serialize_doc(formatted_data)
        })

    except Exception as e:
        print(traceback.format_exc())
        return Response({
            "success": False,
            "error": str(e)
        }, status=500)

@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def save_lab_ward_request(request):
    try:
        import json
        data = request.data
        current_user = data.get('auth-user-id', "system")
        branch_code = data.get('auth-branch-code', 'system')
        outlet_code = (
            request.data.get("auth-outlet-code") or
            request.headers.get("Outlet-Code") or "system"
        )

        hospital_code = data.get('auth-hospital-code', 'system')
        
        # Prepare the document for saving
        request_doc = {k: v for k, v in data.items() if not k.startswith('auth-')}
        
        # --- Doctor & Patient Resolution ---
        doctor_name = data.get("doctor", "")
        if doctor_name:
            doc_profile = mongo_db["backend_diagnostics_profile"].find_one({"employeeName": doctor_name})
            if doc_profile and "employeeId" in doc_profile:
                request_doc["doctor_id"] = doc_profile["employeeId"]
            else:
                request_doc["doctor_id"] = doctor_name
                
        patient_name = data.get("patient_name", "").strip()
        if not patient_name:
            # Fallback to Admission via PyMongo
            admission = mongo_db["hospital_admission"].find_one({"uhid": data.get("uhid"), "is_admissionActive": True})
            if admission and "patient_details" in admission:
                fname = admission["patient_details"].get("firstName", "")
                lname = admission["patient_details"].get("lastName", "")
                request_doc["patient_name"] = f"{fname} {lname}".strip()
        
        # --- Robust Item Fetching (Handle multiple field names) ---
        # LabWardRequest.js uses 'item', but some components use 'selectedTests' or 'items'
        selected_tests = request_doc.pop("selectedTests", request_doc.pop("items", request_doc.pop("item", [])))
        
        # Ensure it is a native list inside mongo to avoid parsing issues
        request_doc["item"] = selected_tests
        
        # ── Bill Number Generation ──────────────────────────────
        bill_type_code = data.get("bill_type", "LAB")
        today = datetime.now()
        if today.month < 4:
            financial_year = f"{(today.year - 1) % 100:02d}{today.year % 100:02d}"
        else:
            financial_year = f"{today.year % 100:02d}{(today.year + 1) % 100:02d}"

        prefix_key = f"{financial_year}/{bill_type_code}"
        prefix = f"{prefix_key}/"

        counters_collection = mongo_db["counters"]
        counter = counters_collection.find_one_and_update(
            {"_id": prefix_key},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER
        )
        next_number = counter["seq"]
        invest_bill_no = f"{prefix}{next_number:06d}"
        
        # Use Indian Standard Time (IST) for saves
        ist = pytz.timezone("Asia/Kolkata")
        now_ist = datetime.now(ist)
        
        # Add metadata and generated fields
        request_doc.update({
            "investBillNo": invest_bill_no,
            "total_amount": round(float(request_doc.get("total_amount", 0)), 2),
            "created_by": current_user,
            "branch_code": branch_code,
            "outlet_code": outlet_code,
            "hospital_code": hospital_code,
            "created_date": now_ist,
            "investBillDate": now_ist,
            "is_active": True,
            "is_ward_request": True,
            "status": "Result Pending",
            "paymentStatus":"Pending",
            "ward_request_type": "LAB"
        })
        
        # Save to the centralized investbilling collection
        collection = mongo_db["hospital_investbilling"]
        result = collection.insert_one(request_doc)
        
        return Response({
            "success": True,
            "message": "Lab Ward Request saved successfully",
            "id": str(result.inserted_id),
            "investBillNo": invest_bill_no
        })
        
    except Exception as e:
        print(traceback.format_exc())
        return Response({
            "success": False,
            "error": str(e)
        }, status=500)

@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def cancel_lab_ward_request(request):
    try:
        data = request.data
        request_id = data.get("id")
        
        if not request_id:
            return Response({"success": False, "error": "Request ID is required"}, status=400)
            
        from bson import ObjectId
        collection = mongo_db["hospital_investbilling"]
        
        result = collection.update_one(
            {"_id": ObjectId(request_id), "is_ward_request": True},
            {"$set": {"is_active": False, "status": "Cancelled"}}
        )
        
        if result.modified_count > 0:
            return Response({"success": True, "message": "Request cancelled successfully"})
        else:
            return Response({"success": False, "error": "Request not found or already cancelled"}, status=404)
            
    except Exception as e:
        print(traceback.format_exc())
        return Response({"success": False, "error": str(e)}, status=500)

@api_view(["POST"])
# @permission_classes([HasRoleAndDataPermission])
def remove_individual_test_from_lab_ward_request(request):
    try:
        import json
        data = request.data
        request_id = data.get("id")
        test_id = data.get("test_id")
        test_name = data.get("test_name") # Fallback if test_id is empty
        
        if not request_id:
            return Response({"success": False, "error": "Request ID is required"}, status=400)
            
        from bson import ObjectId
        collection = mongo_db["hospital_investbilling"]
        
        # Step 1: Get the document
        doc = collection.find_one({"_id": ObjectId(request_id), "is_ward_request": True})
        if not doc:
            return Response({"success": False, "error": "Request not found"}, status=404)
            
        # Parse items
        item_data = doc.get("item", "[]")
        if isinstance(item_data, str):
            items = json.loads(item_data)
        else:
            items = item_data
            
        # Step 2: Remove the test
        new_items = []
        found = False
        for itm in items:
            if test_id and str(itm.get("test_id")) == str(test_id):
                found = True
                continue
            if not test_id and itm.get("itemName") == test_name:
                found = True
                continue
            new_items.append(itm)
            
        if found:
            # Step 3: Recalculate total amount
            new_total = sum(float(t.get("price", 0)) for t in new_items)
            
            update_fields = {
                "item": json.dumps(new_items),
                "total_amount": new_total
            }
            
            if not new_items:
                update_fields["status"] = "Cancelled"
                update_fields["is_active"] = False
                
            collection.update_one(
                {"_id": ObjectId(request_id)},
                {"$set": update_fields}
            )
            
            return Response({
                "success": True, 
                "message": "Test removed successfully",
                "remaining_tests": len(new_items)
            })
        else:
            return Response({"success": False, "error": "Test not found in request"}, status=404)
            
    except Exception as e:
        print(traceback.format_exc())
        return Response({"success": False, "error": str(e)}, status=500)

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_medicine_ward_requests(request):
    try:
        uhid = request.query_params.get("uhid")
        ip_number = request.query_params.get("ipNumber")
        outlet_code = request.query_params.get("outlet_code")

        if not uhid:
            return Response({"success": False, "error": "UHID is required"}, status=400)

        # Build query
        query_params = {"uhid": uhid, "is_ward_request": True}
        if ip_number:
            query_params["inpatient_number"] = ip_number
        if outlet_code:
            query_params["outlet_code"] = outlet_code

        # Fetch billing records
        requests_data = list(
            PharmacyBilling.objects.filter(**query_params).values().order_by("-bill_date")
        )

        # --- Batch-load item names ---
        all_item_ids = set()
        for doc in requests_data:
            for itm in (doc.get("medicine_particulars") or []):
                if isinstance(itm, dict) and itm.get("item_id"):
                    try:
                        all_item_ids.add(int(itm["item_id"]))
                    except (ValueError, TypeError):
                        pass
        item_name_map = {
            i.item_id: i.item_name
            for i in PharmacyItem.objects.filter(item_id__in=all_item_ids)
        }

        formatted_data = []
        for doc in requests_data:
            import json
            items = doc.get("medicine_particulars", [])
            if isinstance(items, str):
                try:
                    items = json.loads(items)
                except Exception:
                    items = []

            medicines = []
            for itm in (items or []):
                if isinstance(itm, str):
                    try:
                        itm = json.loads(itm)
                    except Exception:
                        continue
                if not isinstance(itm, dict):
                    continue

                try:
                    item_id_int = int(itm.get("item_id", 0))
                except (ValueError, TypeError):
                    item_id_int = 0

                medicines.append({
                    "item_id": itm.get("item_id", ""),
                    "item_name": item_name_map.get(item_id_int, ""),
                    "batch_number": itm.get("batch_number", ""),
                    "quantity": itm.get("quantity", itm.get("qty", 0)),
                    "dosage": itm.get("dosage", ""),
                    "noOfDays": itm.get("noOfDays", ""),
                    "dose": itm.get("dose", ""),
                    "doseunit": itm.get("doseunit", ""),
                    "instruction": itm.get("instruction", ""),
                    "is_deleted": itm.get("is_deleted", False),
                    "edit_history": itm.get("edit_history", []),
                })

            formatted_data.append({
                "Bill_id": doc.get("Bill_id"),
                "reqId": str(doc.get("Bill_id")),
                "uhid": doc.get("uhid", ""),
                "ipNumber": doc.get("inpatient_number", ""),
                "billType": doc.get("bill_type", ""),
                "billTypeNo": doc.get("bill_type_no", ""),
                "billName": doc.get("bill_type_no", ""),
                "reqDate": (\
                    (lambda dt: dt.astimezone(pytz.timezone("Asia/Kolkata")).strftime("%d-%m-%Y"))(
                        doc.get("ward_request_date") or doc.get("bill_date") or doc.get("created_date")
                    )
                ) if (
                    doc.get("ward_request_date") or doc.get("bill_date") or doc.get("created_date")
                ) else "",
                "reqTime": (
                    (lambda dt: dt.astimezone(pytz.timezone("Asia/Kolkata")).strftime("%I:%M %p"))(
                        doc.get("ward_request_date") or doc.get("bill_date") or doc.get("created_date")
                    )
                ) if (
                    doc.get("ward_request_date") or doc.get("bill_date") or doc.get("created_date")
                ) else "",
                "status": doc.get("billing_status", "Pending"),
                "doctor": doc.get("doctor_id", ""),
                "outlet_code": doc.get("outlet_code", ""),
                "medicines": medicines,
                "total_amount": doc.get("total_amount", 0),
            })

        return Response({"success": True, "data": formatted_data})

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return Response({"success": False, "error": str(e)}, status=500)


@api_view(["PATCH"])
@permission_classes([HasRoleAndDataPermission])
def update_medicine_ward_request(request):
    """
    Patch individual medicines inside an existing ward request.
    Supports:
      - Soft-deleting a medicine (is_deleted: true)
      - Changing qty / dosage with an audit trail in edit_history
    """
    import traceback
    try:
        data = request.data
        bill_id = data.get("Bill_id")
        updated_medicines = data.get("medicine_particulars", [])
        changed_by = data.get("auth-user-id", "system")

        if not bill_id:
            return Response({"success": False, "error": "Bill_id is required"}, status=400)

        try:
            bill = PharmacyBilling.objects.get(Bill_id=bill_id)
        except PharmacyBilling.DoesNotExist:
            return Response({"success": False, "error": "Ward request not found"}, status=404)

        if bill.billing_status in ["Billed", "Cancelled"]:
            return Response(
                {"success": False, "error": f"Cannot edit a {bill.billing_status} request"},
                status=400,
            )

        existing = list(bill.medicine_particulars or [])

        # Build a lookup map keyed by (item_id, batch_number)
        existing_map = {}
        for idx, itm in enumerate(existing):
            if not isinstance(itm, dict):
                continue
            key = (str(itm.get("item_id", "")), str(itm.get("batch_number", "")))
            existing_map[key] = (idx, itm)

        changed_at = timezone.now().isoformat()

        for incoming in updated_medicines:
            if not isinstance(incoming, dict):
                continue
            key = (str(incoming.get("item_id", "")), str(incoming.get("batch_number", "")))
            if key not in existing_map:
                continue

            idx, current = existing_map[key]
            audit_entry = {}

            # --- Handle soft delete ---
            if incoming.get("is_deleted") and not current.get("is_deleted"):
                current["is_deleted"] = True
                audit_entry = {
                    "changed_by": changed_by,
                    "changed_at": changed_at,
                    "action": "deleted",
                }

            else:
                # --- Handle qty change ---
                old_qty = current.get("quantity", current.get("qty", 0))
                new_qty = incoming.get("quantity", old_qty)
                # --- Handle dosage change ---
                old_dosage = current.get("dosage", "")
                new_dosage = incoming.get("dosage", old_dosage)

                qty_changed = str(old_qty) != str(new_qty)
                dosage_changed = old_dosage != new_dosage

                if qty_changed or dosage_changed:
                    audit_entry = {
                        "changed_by": changed_by,
                        "changed_at": changed_at,
                        "action": "edited",
                    }
                    if qty_changed:
                        audit_entry["old_qty"] = old_qty
                        audit_entry["new_qty"] = new_qty
                        current["quantity"] = new_qty
                    if dosage_changed:
                        audit_entry["old_dosage"] = old_dosage
                        audit_entry["new_dosage"] = new_dosage
                        current["dosage"] = new_dosage

            if audit_entry:
                eh = current.get("edit_history", [])
                if not isinstance(eh, list):
                    eh = []
                eh.append(audit_entry)
                current["edit_history"] = eh

            existing[idx] = current

        bill.medicine_particulars = existing

        # Recalculate totals from non-deleted items
        new_total = sum(
            float(itm.get("quantity", itm.get("qty", 0))) * float(itm.get("price", 0))
            for itm in existing
            if isinstance(itm, dict) and not itm.get("is_deleted")
        )
        bill.total_amount = round(new_total, 2)
        bill.net_amount = round(new_total, 2)
        bill.lastmodified_by = changed_by
        bill.save()

        return Response({"success": True, "message": "Ward request updated successfully"})

    except Exception as e:
        print(traceback.format_exc())
        return Response({"success": False, "error": str(e)}, status=500)


@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def save_medicine_ward_request(request):
    try:
        data = request.data
        print(data)
        current_user = data.get('auth-user-id', "system")
        branch_code = data.get('auth-branch-code', 'system')
        hospital_code = data.get('auth-hospital-code', 'system')
        outlet_code = data.get('outlet_code', 'system')
        
        medicine_particulars = data.get("medicine_particulars", [])
        total_amount = round(float(data.get("total_amount") or 0), 2)
        
        # --- Doctor & Patient Settings ---
        doctor_id = data.get("doctor_id", data.get("doctor", ""))
        patient_name = data.get("patient_name", "").strip()
        if not patient_name:
            # Fallback to Admission via PyMongo
            admission = mongo_db["hospital_admission"].find_one({"uhid": data.get("uhid"), "is_admissionActive": True})
            if admission and "patient_details" in admission:
                fname = admission["patient_details"].get("firstName", "")
                lname = admission["patient_details"].get("lastName", "")
                patient_name = f"{fname} {lname}".strip()

        # Strip item names from particulars before saving as per user request
        cleaned_particulars = []
        for item in (medicine_particulars or []):
            cleaned_item = {
                "item_id": item.get("item_id"),
                "qty": item.get("quantity", item.get("qty", 0)),
                "dosage": item.get("dosage", ""),
                "noOfDays": item.get("noOfDays", ""),
                "dose": item.get("dose", ""),
                "doseunit": item.get("doseunit", ""),
                "batch_number": item.get("batch_number", ""),
                "instruction": item.get("instruction", "")
            }
            cleaned_particulars.append(cleaned_item)

        # Create Bill via Django Model (Handles auto-increment and defaults)
        bill = PharmacyBilling(
            uhid=data.get("uhid"),
            inpatient_number=data.get("ipNumber"),
            bill_type=data.get("bill_type"),
            # bill_type_no=data.get("billTypeNo"),
            doctor_id=data.get("doctor_id"),
            medicine_particulars=cleaned_particulars,
            total_amount=total_amount,
            net_amount=total_amount,
            billing_status="Pending",
            billing_mode="WARD REQUEST",
            payment_details={},
            outlet_code=outlet_code,
            hospital_code=hospital_code,
            branch_code=branch_code,
            created_by=current_user,
            is_ward_request=True
        )
        bill.save()
        
        return Response({
            "success": True,
            "message": "Medicine ward request saved successfully",
            "id": bill.Bill_id
        })
        
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return Response({"success": False, "error": str(e)}, status=500)

@api_view(["GET", "POST"])
# @permission_classes([HasRoleAndDataPermission])
def dosage_master_view(request):
    dosage_col = mongo_db["hospital_dosage"]
    try:
        if request.method == "GET":
            dosages = list(dosage_col.find({}, {"_id": 0}))
            return Response({"success": True, "data": dosages})
            
        elif request.method == "POST":
            data = request.data
            dosage_name = data.get("dosage_name")
            if not dosage_name:
                return Response({"success": False, "message": "Dosage name is required"}, status=400)
            
            # Simple check/upsert
            dosage_col.update_one(
                {"dosage_name": dosage_name},
                {"$set": {"dosage_name": dosage_name, "created_at": datetime.now()}},
                upsert=True
            )
            return Response({"success": True, "message": "Dosage saved successfully"})
    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=500)

@api_view(["POST"])
# @permission_classes([HasRoleAndDataPermission])
def cancel_medicine_ward_request(request):
    try:
        data = request.data
        request_id = data.get("id") # bill_no
        
        if not request_id:
            return Response({"success": False, "error": "Request ID is required"}, status=400)
            
        # For OPPharmacyBill, we might set billing_status to "Cancelled" or similar
        # But looking at pharmacy.py, they seem to use billing_status for workflow.
        # Use PyMongo to avoid Django ORM crashes with native arrays
        collection = mongo_db["hospital_oppharmacybill"]
        from bson import ObjectId
        result = collection.update_one({"_id": ObjectId(request_id)}, {"$set": {"billing_status": "Cancelled"}})
        
        if result.modified_count > 0:
            return Response({"success": True, "message": "Medicine ward request cancelled successfully"})
        else:
            return Response({"success": False, "error": "Request not found"}, status=404)
            
    except Exception as e:
        print(traceback.format_exc())
        return Response({"success": False, "error": str(e)}, status=500)

@api_view(["POST"])
# @permission_classes([HasRoleAndDataPermission])
def remove_individual_medicine_from_ward_request(request):
    try:
        data = request.data
        request_id = data.get("id") # bill_no
        item_id = data.get("item_id")
        item_name = data.get("item_name")
        
        if not request_id:
            return Response({"success": False, "error": "Request ID is required"}, status=400)
            
        # Step 1: Get the document via PyMongo
        from bson import ObjectId
        collection = mongo_db["hospital_oppharmacybill"]
        doc = collection.find_one({"_id": ObjectId(request_id)})
        if not doc:
            return Response({"success": False, "error": "Request not found"}, status=404)
            
        items = doc.get("medicine_particulars", [])
            
        # Step 2: Remove the medicine
        new_items = []
        found = False
        for itm in items:
            if item_id and str(itm.get("item_id", "")) == str(item_id):
                found = True
                continue
            if not item_id and itm.get("itemName", "") == item_name:
                found = True
                continue
            new_items.append(itm)
            
        if found:
            # Step 3: Recalculate total amount
            new_total = sum(float(t.get("price", t.get("Price", 0))) for t in new_items)
            
            collection.update_one(
                {"_id": ObjectId(request_id)},
                {"$set": {
                    "medicine_particulars": new_items,
                    "total_amount": new_total,
                    "net_amount": new_total
                }}
            )
            
            return Response({
                "success": True, 
                "message": "Medicine removed successfully",
                "remaining_medicines": len(new_items)
            })
        else:
            return Response({"success": False, "error": "Medicine not found in request"}, status=404)
            
    except Exception as e:
        print(traceback.format_exc())
        return Response({"success": False, "error": str(e)}, status=500)


@api_view(["GET"])
# @permission_classes([HasRoleAndDataPermission])
def get_radiology_ward_requests(request):
    try:
        uhid = request.query_params.get("uhid")
        ip_number = request.query_params.get("ipNumber")

        if not uhid:
            return Response({"success": False, "error": "UHID is required"}, status=400)

        collection = mongo_db["hospital_investbilling"]
        query = {
            "uhid": uhid,
            "is_active": True,
            "is_ward_request": True,
            "ward_request_type": "RADIOLOGY"
        }
        if ip_number:
            query["ipNumber"] = ip_number

        requests_data = list(collection.find(query).sort("created_date", -1))

        formatted_data = []
        for doc in requests_data:
            import json
            # Parse 'item' field back to list
            item_data = doc.get("item", "[]")
            if isinstance(item_data, str):
                try:
                    items = json.loads(item_data)
                except json.JSONDecodeError:
                    items = []
            else:
                items = item_data

            tests = []
            for itm in items:
                tests.append({
                    "test_id": itm.get("test_id", ""),
                    "name": itm.get("itemName", ""),
                    "price": itm.get("price", 0)
                })
            
            formatted_doc = {
                "id": str(doc.get("_id")),
                "status": doc.get("status", "Result Pending"),
                "reqDate": doc.get("created_date").strftime("%d/%m/%Y") if doc.get("created_date") else "",
                "reqTime": doc.get("created_date").strftime("%I:%M %p") if doc.get("created_date") else "",
                "userName": doc.get("created_by", ""),
                "billNo": doc.get("investBillNo", ""),
                "billType": doc.get("billTypeName", ""),
                "wardName": doc.get("wardName", ""),
                "doctorName": doc.get("doctor", ""),
                "tests": tests,
                "total_amount": doc.get("total_amount", 0)
            }
            formatted_data.append(formatted_doc)

        return Response({
            "success": True,
            "data": serialize_doc(formatted_data)
        })

    except Exception as e:
        print(traceback.format_exc())
        return Response({"success": False, "error": str(e)}, status=500)

@api_view(["POST"])
# @permission_classes([HasRoleAndDataPermission])
def save_radiology_ward_request(request):
    try:
        import json
        data = request.data
        current_user = data.get('auth-user-id', "system")
        branch_code = data.get('auth-branch-code', 'system')
        department_code = data.get('auth-department-code', 'system')
        hospital_code = data.get('auth-hospital-code', 'system')
        
        request_doc = {k: v for k, v in data.items() if not k.startswith('auth-')}
        
        # --- Doctor & Patient Resolution ---
        doctor_name = data.get("doctor", "")
        if doctor_name:
            doc_profile = mongo_db["backend_diagnostics_profile"].find_one({"employeeName": doctor_name})
            if doc_profile and "employeeId" in doc_profile:
                request_doc["doctor_id"] = doc_profile["employeeId"]
            else:
                request_doc["doctor_id"] = doctor_name
                
        patient_name = data.get("patient_name", "").strip()
        if not patient_name:
            # Fallback to Admission via PyMongo
            admission = mongo_db["hospital_admission"].find_one({"uhid": data.get("uhid"), "is_admissionActive": True})
            if admission and "patient_details" in admission:
                fname = admission["patient_details"].get("firstName", "")
                lname = admission["patient_details"].get("lastName", "")
                request_doc["patient_name"] = f"{fname} {lname}".strip()
        
        # --- Robust Item Fetching (Handle multiple field names) ---
        # RadiologyWardRequest.js might use 'selectedTests' or 'item'
        selected_tests = request_doc.pop("selectedTests", request_doc.pop("items", request_doc.pop("item", [])))
        
        # Ensure it is a native list inside mongo to avoid parsing issues
        request_doc["item"] = selected_tests
        
        # ── Bill Number Generation (Prefix RAD) ──
        bill_type_code = data.get("billTypeNo", "RAD")
        from datetime import datetime
        today = datetime.now()
        if today.month < 4:
            financial_year = f"{(today.year - 1) % 100:02d}{today.year % 100:02d}"
        else:
            financial_year = f"{today.year % 100:02d}{(today.year + 1) % 100:02d}"

        prefix_key = f"{financial_year}/{bill_type_code}"
        prefix = f"{prefix_key}/"

        counters_collection = mongo_db["hospital_counters"]
        counter = counters_collection.find_one_and_update(
            {"_id": prefix_key},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER
        )
        next_number = counter["seq"]
        invest_bill_no = f"{prefix}{next_number:06d}"
        
        ist = pytz.timezone("Asia/Kolkata")
        now_ist = datetime.now(ist)

        request_doc.update({
            "investBillNo": invest_bill_no,
            "total_amount": round(float(request_doc.get("total_amount", 0)), 2),
            "created_by": current_user,
            "branch_code": branch_code,
            "department_code": department_code,
            "hospital_code": hospital_code,
            "created_date": now_ist,
            "investBillDate": now_ist,
            "bill_date": now_ist,
            "is_active": True,
            "is_ward_request": True,
            "status": "Result Pending",
            "ward_request_type": "RADIOLOGY"
        })
        
        collection = mongo_db["hospital_investbilling"]
        result = collection.insert_one(request_doc)
        
        return Response({
            "success": True,
            "message": "Radiology Ward Request saved successfully",
            "id": str(result.inserted_id),
            "investBillNo": invest_bill_no
        })

    except Exception as e:
        print(traceback.format_exc())
        return Response({"success": False, "error": str(e)}, status=500)

@api_view(["POST"])
# @permission_classes([HasRoleAndDataPermission])
def cancel_radiology_ward_request(request):
    try:
        data = request.data
        request_id = data.get("id")
        
        if not request_id:
            return Response({"success": False, "error": "Request ID is required"}, status=400)
            
        from bson import ObjectId
        collection = mongo_db["hospital_investbilling"]
        
        result = collection.update_one(
            {"_id": ObjectId(request_id), "is_ward_request": True, "ward_request_type": "RADIOLOGY"},
            {"$set": {"is_active": False, "status": "Cancelled"}}
        )
        
        if result.modified_count > 0:
            return Response({"success": True, "message": "Request cancelled successfully"})
        else:
            return Response({"success": False, "error": "Request not found"}, status=404)
            
    except Exception as e:
        print(traceback.format_exc())
        return Response({"success": False, "error": str(e)}, status=500)

@api_view(["POST"])
# @permission_classes([HasRoleAndDataPermission])
def remove_individual_test_from_radiology_ward_request(request):
    try:
        import json
        data = request.data
        request_id = data.get("id")
        test_id = data.get("test_id")
        test_name = data.get("test_name")
        
        if not request_id:
            return Response({"success": False, "error": "Request ID is required"}, status=400)
            
        from bson import ObjectId
        collection = mongo_db["hospital_investbilling"]
        
        # Step 1: Get document
        doc = collection.find_one({"_id": ObjectId(request_id), "is_ward_request": True, "ward_request_type": "RADIOLOGY"})
        if not doc:
            return Response({"success": False, "error": "Request not found"}, status=404)
            
        # Parse items
        item_data = doc.get("item", "[]")
        if isinstance(item_data, str):
            try:
                items = json.loads(item_data)
            except json.JSONDecodeError:
                items = []
        else:
            items = item_data
            
        # Step 2: Remove test
        new_items = []
        found = False
        for itm in items:
            if test_id and str(itm.get("test_id")) == str(test_id):
                found = True
                continue
            if not test_id and itm.get("itemName") == test_name:
                found = True
                continue
            new_items.append(itm)
            
        if found:
            # Step 3: Recalculate total amount
            new_total = sum(float(t.get("price", 0)) for t in new_items)
            
            update_fields = {
                "item": json.dumps(new_items),
                "selectedTests": new_items, # Keep both for now
                "total_amount": new_total
            }
            if not new_items:
                update_fields["status"] = "Cancelled"
                update_fields["is_active"] = False
                
            collection.update_one({"_id": ObjectId(request_id)}, {"$set": update_fields})
            
            return Response({"success": True, "message": "Test removed successfully", "remaining_tests": len(new_items)})
        else:
            return Response({"success": False, "error": "Test not found in request"}, status=404)
            
    except Exception as e:
        print(traceback.format_exc())
        return Response({"success": False, "error": str(e)}, status=500)
