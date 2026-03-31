from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
import os
from datetime import datetime, timedelta
from ..models import Admission, OPPharmacyBill
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
COLLECTION_NAME = "hospital_Wards"

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

    if admission.get("is_admissionActive") and not admission.get("is_discharged"):
        admitted = True

    # Serialize using our custom function to handle objectids and datetimes
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
# @permission_classes([HasRoleAndDataPermission])
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
                "billType": doc.get("billTypeName", "LAB BILL (CREDIT)"),
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
# @permission_classes([HasRoleAndDataPermission])
def save_lab_ward_request(request):
    try:
        import json
        data = request.data
        current_user = data.get('auth-user-id', "system")
        branch_code = data.get('auth-branch-code', 'system')
        department_code = data.get('auth-department-code', 'system')
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
        bill_type_code = data.get("billTypeNo", "LAB")
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
        
        # Use Indian Standard Time (IST) for saves
        ist = pytz.timezone("Asia/Kolkata")
        now_ist = datetime.now(ist)
        
        # Add metadata and generated fields
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
# @permission_classes([HasRoleAndDataPermission])
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
# @permission_classes([HasRoleAndDataPermission])
def get_medicine_ward_requests(request):
    try:
        uhid = request.query_params.get("uhid")
        ip_number = request.query_params.get("ipNumber")
        
        if not uhid:
            return Response({"success": False, "error": "UHID is required"}, status=400)
            
        # Fetch from OPPharmacyBill where is_ward_request=True using PyMongo
        query_params = {
            "uhid": uhid,
            "is_ward_request": True
        }
        if ip_number:
            query_params["inpatient_number"] = ip_number
            
        ward_req_collection = mongo_db["hospital_oppharmacybill"]
        requests_data = list(ward_req_collection.find(query_params).sort("bill_date", -1))
        
        formatted_data = []
        for doc in requests_data:
            # medicine_particulars is already a native list because we save it directly via PyMongo
            # However, older data might still possess string encoding
            items = doc.get("medicine_particulars", [])
            if isinstance(items, str):
                import json
                try:
                    items = json.loads(items)
                except json.JSONDecodeError:
                    items = []

            medicines = []
            for itm in items:
                if isinstance(itm, str):
                    import json
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
                    "instruction": itm.get("instruction", "")
                })

            formatted_doc = {
                "id": str(doc["_id"]),
                "uhid": doc.get("uhid", ""),
                "ipNumber": doc.get("inpatient_number", ""),
                "patientName": doc.get("patient_name", ""),
                "billType": doc.get("bill_type", ""),
                "billName": doc.get("bill_name", ""),
                "reqDate": doc.get("bill_date").strftime("%d-%m-%Y") if doc.get("bill_date") else "",
                "reqTime": doc.get("bill_date").strftime("%I:%M %p") if doc.get("bill_date") else "",
                "userName": doc.get("created_by", ""),
                "requestNo": doc.get("estimate_no", ""),
                "doctor": doc.get("doctor", ""),
                "doctorName": doc.get("doctor_id", ""),
                "medicines": medicines,
                "total_amount": doc.get("total_amount", 0)
            }
            formatted_data.append(formatted_doc)

        return Response({
            "success": True,
            "data": formatted_data
        })

    except Exception as e:
        print(traceback.format_exc())
        return Response({"success": False, "error": str(e)}, status=500)


@api_view(["POST"])
# @permission_classes([HasRoleAndDataPermission])
def save_medicine_ward_request(request):
    try:
        data = request.data
        current_user = data.get('auth-user-id', "system")
        branch_code = data.get('auth-branch-code', 'system')
        
        request_doc = {k: v for k, v in data.items() if not k.startswith('auth-')}
        
        # Extract medicines and totals (round to 2 digits)
        medicine_particulars = data.get("medicine_particulars", [])
        total_amount = round(float(data.get("total_amount", 0)), 2)
        
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

        bill_type = data.get("bill_type", "")
        bill_type_no = data.get("billTypeNo", "")
        bill_name = data.get("billTypeName", "")
        
        # Clean up unnecessary fields from medicine_particulars for ward request
        for med in medicine_particulars:
            med.pop("edit_history", None)
            med.pop("billType", None)
            med.pop("billTypeNo", None)
            med.pop("billTypeName", None)
            med.pop("total_stock", None)
            med.pop("price", None)
            med.pop("expiry_date", None)
            
        from datetime import datetime
        import pytz
        ist = pytz.timezone("Asia/Kolkata")
        now_ist = datetime.now(ist)
        
        # Create Ward Request document for PyMongo insert (To allow native BSON arrays)
        bill_doc = {
            "bill_no": "", 
            "estimate_no": "",
            "patient_name": patient_name,
            "uhid": data.get("uhid"),
            "inpatient_number": data.get("ipNumber"),
            "bill_type": bill_type,
            "bill_type_no": bill_type_no,
            "bill_name": bill_name,
            "doctor_id": data.get("doctor_id"),
            "doctor": data.get("doctor"),
            "room_no": data.get("wardName", ""),
            "medicine_particulars": medicine_particulars, # Native List
            "total_amount": total_amount,
            "net_amount": total_amount,
            "overall_discount_amount": 0.0,
            "overall_discount_type": "percent",
            "overall_discount_value": 0.0,
            "billing_status": "Ward Request",
            "billing_mode": "WARD REQUEST",
            "is_ward_request": True,
            "is_active": True,
            "created_by": current_user,
            "branch_code": branch_code,
            "bill_date": now_ist
            # Note: edit_history is deliberately removed for ward requests
        }
        
        # Insert into hospital_oppharmacybill natively to avoid Djongo JSONField stringification
        collection = mongo_db["hospital_oppharmacybill"]
        result = collection.insert_one(bill_doc)
        
        return Response({
            "success": True,
            "message": "Medicine ward request saved successfully",
            "id": str(result.inserted_id)
        })
        
    except Exception as e:
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
