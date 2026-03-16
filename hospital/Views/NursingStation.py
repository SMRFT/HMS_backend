from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
import os
from datetime import datetime, timedelta
from ..models import Admission
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
@permission_classes([HasRoleAndDataPermission])
def get_admission_list(request):
    try:
        from_date = request.GET.get("from_date")
        to_date = request.GET.get("to_date")

        print("FROM DATE:", from_date)
        print("TO DATE:", to_date)

        admissions = Admission.objects.all().order_by("-admissionDateTime")

        filtered = []

        start_utc = None
        end_utc = None

        if from_date and to_date:
            ist = pytz.timezone("Asia/Kolkata")

            start_ist = ist.localize(datetime.strptime(from_date, "%Y-%m-%d"))
            end_ist = ist.localize(
                datetime.strptime(to_date, "%Y-%m-%d") + timedelta(days=1)
            )

            start_utc = start_ist.astimezone(pytz.UTC)
            end_utc = end_ist.astimezone(pytz.UTC)

            print("START UTC:", start_utc)
            print("END UTC:", end_utc)

        for admission in admissions:

            print("CHECKING ADMISSION:", admission.ipNumber)

            if not getattr(admission, "is_admissionActive", True):
                print("Skipping inactive admission")
                continue

            if start_utc and end_utc:
                if not (start_utc <= admission.admissionDateTime < end_utc):
                    print("Skipping due to date filter")
                    continue

            filtered.append(admission)

        serializer = AdmissionSerializer(filtered, many=True)
        data = serializer.data

        print("TOTAL FILTERED RECORDS:", len(data))

        # -----------------------------------------
        # ADDITIONAL DATA ENRICHMENT
        # -----------------------------------------
        for item in data:

            print("Processing item:", item.get("ipNumber"))

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

            print("Room number:", room_no)

            if room_no:
                room = room_collection.find_one(
                    {"room_number": room_no},
                    {
                        "_id": 0,
                        "room_category": 1,
                        "block": 1,
                        "nursing_station": 1
                    }
                )

                print("Room Mongo result:", room)

                if room:
                    item["room_category"] = room.get("room_category")
                    item["block"] = room.get("block")
                    item["nursing_station"] = room.get("nursing_station")

                    print("Room data added")
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
@permission_classes([HasRoleAndDataPermission])
def get_wards_list(request):
    try:
        # ✅ Fetch only active wards
        wards_cursor = collection.find(
            {"is_active": True},      # filter
            {"_id": 0, "ward_name": 1}  # projection (only ward_name)
        )

        wards = list(wards_cursor)

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
@permission_classes([HasRoleAndDataPermission])
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

    admissions = Admission.objects.filter(uhid=uhid)

    if not admissions.exists():
        return Response({
            "success": True,
            "admitted": False,
            "data": []
        })

    admission = admissions.first()

    admitted = False

    if admission.is_admissionActive and not admission.is_discharged:
        admitted = True

    serializer = AdmissionSerializer(admission)

    return Response({
        "success": True,
        "admitted": admitted,
        "data": serializer.data
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

        query = {"is_active": True}
        if uhid:
            query["uhid"] = uhid
        if ip_number:
            query["ipNumber"] = ip_number

        # Fetch from the new lab ward request collection
        ward_req_collection = mongo_db["hospital_labwardrequest"]
        requests_data = list(ward_req_collection.find(query).sort("created_date", -1))

        # Enrich and format for the frontend component
        formatted_data = []
        for doc in requests_data:
            # In the new collection, 'selectedTests' is likely already a list
            items = doc.get("selectedTests", [])
            
            # Map tests for the frontend structure
            tests = []
            for itm in items:
                tests.append({
                    "test_id": itm.get("test_id", ""),
                    "name": itm.get("itemName", ""),
                    "collectionTime": "" 
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
@permission_classes([HasRoleAndDataPermission])
def save_lab_ward_request(request):
    try:
        data = request.data
        current_user = data.get('auth-user-id', "system")
        
        # Prepare the document for saving
        # We remove auth fields
        request_doc = {k: v for k, v in data.items() if not k.startswith('auth-')}
        
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
        
        # Add metadata and generated fields
        request_doc["investBillNo"] = invest_bill_no
        request_doc["created_by"] = current_user
        request_doc["created_date"] = datetime.now()
        request_doc["status"] = "Result Pending"
        request_doc["is_active"] = True
        
        # Save to the new collection
        collection = mongo_db["hospital_labwardrequest"]
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
        collection = mongo_db["hospital_labwardrequest"]
        
        result = collection.update_one(
            {"_id": ObjectId(request_id)},
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
@permission_classes([HasRoleAndDataPermission])
def remove_individual_test_from_lab_ward_request(request):
    try:
        data = request.data
        request_id = data.get("id")
        test_id = data.get("test_id")
        test_name = data.get("test_name") # Fallback if test_id is empty
        
        if not request_id:
            return Response({"success": False, "error": "Request ID is required"}, status=400)
            
        from bson import ObjectId
        collection = mongo_db["hospital_labwardrequest"]
        
        # Build the match criteria for pulling the test
        pull_query = {}
        if test_id:
            pull_query = {"test_id": test_id}
        else:
            pull_query = {"itemName": test_name}

        # Step 1: Remove the test
        result = collection.update_one(
            {"_id": ObjectId(request_id)},
            {"$pull": {"selectedTests": pull_query}}
        )
        
        if result.modified_count > 0:
            # Step 2: Recalculate total amount
            doc = collection.find_one({"_id": ObjectId(request_id)})
            tests = doc.get("selectedTests", [])
            
            # Recalculate new total
            new_total = sum(float(t.get("price", 0)) for t in tests)
            
            update_fields = {"total_amount": new_total}
            if not tests:
                update_fields["status"] = "Cancelled"
                update_fields["is_active"] = False
                
            collection.update_one(
                {"_id": ObjectId(request_id)},
                {"$set": update_fields}
            )
            
            return Response({
                "success": True, 
                "message": "Test removed successfully",
                "remaining_tests": len(tests)
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
        
        if not uhid:
            return Response({"success": False, "error": "UHID is required"}, status=400)
            
        collection = mongo_db["hospital_medicinewardrequest"]
        query = {"uhid": uhid, "is_active": True}
        if ip_number:
            query["ipNumber"] = ip_number
            
        requests_data = list(collection.find(query).sort("created_date", -1))
        
        formatted_data = []
        for doc in requests_data:
            items = doc.get("selectedMedicines", [])
            medicines = []
            for itm in items:
                medicines.append({
                    "item_id": itm.get("item_id", ""),
                    "name": itm.get("itemName", ""),
                    "quantity": itm.get("quantity", 1),
                    "price": itm.get("price", 0),
                    "billType": itm.get("billType", ""),
                    "doctor": itm.get("doctor", ""),
                    "dosage": itm.get("dosage", ""),
                    "noOfDays": itm.get("noOfDays", ""),
                    "dose": itm.get("dose", ""),
                    "doseUnit": itm.get("doseUnit", ""),
                    "route": itm.get("route", ""),
                    "remark": itm.get("remark", ""),
                    "isRegular": itm.get("isRegular", False),
                    "isDischarge": itm.get("isDischarge", False)
                })
            
            formatted_doc = {
                "id": str(doc.get("_id")),
                "status": doc.get("status", "Pending"),
                "reqDate": doc.get("created_date").strftime("%d/%m/%Y") if doc.get("created_date") else "",
                "reqTime": doc.get("created_date").strftime("%I:%M %p") if doc.get("created_date") else "",
                "userName": doc.get("created_by", ""),
                "requestNo": doc.get("medicineRequestNo", ""),
                "wardName": doc.get("wardName", ""),
                "doctorName": doc.get("doctor", ""),
                "medicines": medicines,
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
@permission_classes([HasRoleAndDataPermission])
def save_medicine_ward_request(request):
    try:
        data = request.data
        current_user = data.get('auth-user-id', "system")
        
        request_doc = {k: v for k, v in data.items() if not k.startswith('auth-')}
        
        # ── Request Number Generation ──────────────────────────────
        collection = mongo_db["hospital_medicinewardrequest"]
        counters = mongo_db["hospital_counters"]
        
        from datetime import datetime
        now = datetime.now()
        year_prefix = now.strftime("%y%y") # e.g. 2424 or similar logic
        # Simplified logic for now
        
        counter = counters.find_one_and_update(
            {"_id": "medicine_ward_request"},
            {"$inc": {"sequence_value": 1}},
            upsert=True,
            return_document=True
        )
        seq = str(counter["sequence_value"]).zfill(6)
        medicine_request_no = f"{year_prefix}/MED/{seq}"
        # ──────────────────────────────────────────────────────────
        
        request_doc.update({
            "medicineRequestNo": medicine_request_no,
            "created_at": datetime.now(),
            "created_date": datetime.now(),
            "created_by": current_user,
            "is_active": True,
            "status": "Pending"
        })
        
        result = collection.insert_one(request_doc)
        
        return Response({
            "success": True,
            "message": "Medicine request saved successfully",
            "medicineRequestNo": medicine_request_no
        })
        
    except Exception as e:
        print(traceback.format_exc())
        return Response({"success": False, "error": str(e)}, status=500)

@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def cancel_medicine_ward_request(request):
    try:
        data = request.data
        request_id = data.get("id")
        
        if not request_id:
            return Response({"success": False, "error": "Request ID is required"}, status=400)
            
        from bson import ObjectId
        collection = mongo_db["hospital_medicinewardrequest"]
        
        result = collection.update_one(
            {"_id": ObjectId(request_id)},
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
@permission_classes([HasRoleAndDataPermission])
def remove_individual_medicine_from_ward_request(request):
    try:
        data = request.data
        request_id = data.get("id")
        item_id = data.get("item_id")
        item_name = data.get("item_name")
        
        if not request_id:
            return Response({"success": False, "error": "Request ID is required"}, status=400)
            
        from bson import ObjectId
        collection = mongo_db["hospital_medicinewardrequest"]
        
        pull_query = {}
        if item_id:
            pull_query = {"item_id": item_id}
        else:
            pull_query = {"itemName": item_name}

        result = collection.update_one(
            {"_id": ObjectId(request_id)},
            {"$pull": {"selectedMedicines": pull_query}}
        )
        
        if result.modified_count > 0:
            doc = collection.find_one({"_id": ObjectId(request_id)})
            medicines = doc.get("selectedMedicines", [])
            
            new_total = sum(float(m.get("price", 0)) * int(m.get("quantity", 1)) for m in medicines)
            
            update_fields = {"total_amount": new_total}
            if not medicines:
                update_fields["status"] = "Cancelled"
                update_fields["is_active"] = False
                
            collection.update_one(
                {"_id": ObjectId(request_id)},
                {"$set": update_fields}
            )
            
            return Response({
                "success": True, 
                "message": "Medicine removed successfully",
                "remaining_items": len(medicines)
            })
        else:
            return Response({"success": False, "error": "Medicine not found in request"}, status=404)
            
    except Exception as e:
        print(traceback.format_exc())
        return Response({"success": False, "error": str(e)}, status=500)


@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_radiology_ward_requests(request):
    try:
        uhid = request.GET.get("uhid")
        ip_number = request.GET.get("ipNumber")

        query = {"is_active": True}
        if uhid:
            query["uhid"] = uhid
        if ip_number:
            query["ipNumber"] = ip_number

        collection = mongo_db["hospital_radiologywardrequest"]
        requests_data = list(collection.find(query).sort("created_date", -1))

        formatted_data = []
        for doc in requests_data:
            items = doc.get("selectedTests", [])
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
                "tests": tests
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
@permission_classes([HasRoleAndDataPermission])
def save_radiology_ward_request(request):
    try:
        data = request.data
        current_user = data.get('auth-user-id', "system")
        
        request_doc = {k: v for k, v in data.items() if not k.startswith('auth-')}
        
        # ── Bill Number Generation (Prefix RAD) ──
        bill_type_code = data.get("billTypeNo", "RAD")
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
        
        request_doc.update({
            "investBillNo": invest_bill_no,
            "created_by": current_user,
            "created_date": datetime.now(),
            "status": "Result Pending",
            "is_active": True
        })
        
        collection = mongo_db["hospital_radiologywardrequest"]
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
@permission_classes([HasRoleAndDataPermission])
def cancel_radiology_ward_request(request):
    try:
        data = request.data
        request_id = data.get("id")
        
        if not request_id:
            return Response({"success": False, "error": "Request ID is required"}, status=400)
            
        from bson import ObjectId
        collection = mongo_db["hospital_radiologywardrequest"]
        
        result = collection.update_one(
            {"_id": ObjectId(request_id)},
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
@permission_classes([HasRoleAndDataPermission])
def remove_individual_test_from_radiology_ward_request(request):
    try:
        data = request.data
        request_id = data.get("id")
        test_id = data.get("test_id")
        test_name = data.get("test_name")
        
        if not request_id:
            return Response({"success": False, "error": "Request ID is required"}, status=400)
            
        from bson import ObjectId
        collection = mongo_db["hospital_radiologywardrequest"]
        
        pull_query = {"test_id": test_id} if test_id else {"itemName": test_name}

        result = collection.update_one(
            {"_id": ObjectId(request_id)},
            {"$pull": {"selectedTests": pull_query}}
        )
        
        if result.modified_count > 0:
            doc = collection.find_one({"_id": ObjectId(request_id)})
            tests = doc.get("selectedTests", [])
            new_total = sum(float(t.get("price", 0)) for t in tests)
            
            update_fields = {"total_amount": new_total}
            if not tests:
                update_fields["status"] = "Cancelled"
                update_fields["is_active"] = False
                
            collection.update_one({"_id": ObjectId(request_id)}, {"$set": update_fields})
            
            return Response({"success": True, "message": "Test removed successfully"})
        else:
            return Response({"success": False, "error": "Test not found"}, status=404)
            
    except Exception as e:
        print(traceback.format_exc())
        return Response({"success": False, "error": str(e)}, status=500)
