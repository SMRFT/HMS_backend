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
@permission_classes([HasRoleAndDataPermission])
def save_lab_ward_request(request):
    try:
        import json
        data = request.data
        current_user = data.get('auth-user-id', "system")
        branch_code = data.get('auth-branch-code', 'system')
        department_code = data.get('auth-department-code', 'system')
        hospital_code = data.get('auth-hospital-code', 'system')
        
        # Prepare the document for saving
        # We remove auth fields
        request_doc = {k: v for k, v in data.items() if not k.startswith('auth-')}
        
        # ── Map selectedTests to 'item' for compatibility ──
        selected_tests = request_doc.get("selectedTests", [])
        request_doc["item"] = json.dumps(selected_tests)
        
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
        request_doc.update({
            "investBillNo": invest_bill_no,
            "created_by": current_user,
            "branch_code": branch_code,
            "department_code": department_code,
            "hospital_code": hospital_code,
            "created_date": datetime.now(),
            "status": "Result Pending",
            "is_active": True,
            "is_ward_request": True,
            "ward_request_type": "LAB",
            "investBillDate": datetime.now()
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
@permission_classes([HasRoleAndDataPermission])
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
                "selectedTests": new_items, # Keep both for now
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
        
        if not uhid:
            return Response({"success": False, "error": "UHID is required"}, status=400)
            
        # Fetch from OPPharmacyBill (Django model) where billing_status="Estimated"
        query_params = {
            "uhid": uhid,
            "billing_status": "Estimated",
            "billing_mode": "ESTIMATE"
        }
        if ip_number:
            query_params["inpatient_number"] = ip_number
            
        requests_data = OPPharmacyBill.objects.filter(**query_params).order_by("-bill_date")
        
        formatted_data = []
        for doc in requests_data:
            # medicine_particulars is already a list (JSONField)
            items = doc.medicine_particulars or []

            medicines = []
            for itm in items:
                medicines.append({
                    "item_id": itm.get("item_id", ""),
                    "name": itm.get("itemName", itm.get("item_name", "")),
                    "quantity": itm.get("quantity", itm.get("qty", 1)),
                    "price": itm.get("price", itm.get("Price", 0)),
                    "billType": itm.get("billType", ""),
                    "doctor": itm.get("doctor", ""),
                    "dosage": itm.get("dosage", ""),
                    "noOfDays": itm.get("noOfDays", ""),
                    "dose": itm.get("dose", ""),
                    "doseUnit": itm.get("doseUnit", ""),
                    "route": itm.get("route", ""),
                    "instruction": itm.get("instruction", "")
                })

            formatted_doc = {
                "id": doc.bill_no, # PK
                "uhid": doc.uhid,
                "ipNumber": doc.inpatient_number,
                "patientName": doc.patient_name,
                "reqDate": doc.bill_date.strftime("%d-%m-%Y") if doc.bill_date else "",
                "reqTime": doc.bill_date.strftime("%I:%M %p") if doc.bill_date else "",
                "userName": doc.created_by,
                "requestNo": doc.estimate_no,
                "doctorName": doc.doctor_id,
                "medicines": medicines,
                "total_amount": doc.total_amount
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
@permission_classes([HasRoleAndDataPermission])
def save_medicine_ward_request(request):
    try:
        # import json # Not needed with new logic
        data = request.data
        current_user = data.get('auth-user-id', "system")
        branch_code = data.get('auth-branch-code', 'system')
        # department_code = data.get('auth-department-code', 'system') # Not needed with new logic
        # hospital_code = data.get('auth-hospital-code', 'system') # Not needed with new logic
        
        request_doc = {k: v for k, v in data.items() if not k.startswith('auth-')}
        
        selected_medicines = request_doc.get("selectedMedicines", [])
        total_amount = float(request_doc.get("total_amount", 0))
        
        # ── Estimate Number Generation ──────────────────────────────
        estimate_no = OPPharmacyBill.generate_estimate_no()
        
        # ── Map Fields for OPPharmacyBill ──────────────────────────
        # Patient name should be combined if split
        first_name = request_doc.get("firstName", "")
        last_name = request_doc.get("lastName", "")
        patient_name = f"{first_name} {last_name}".strip()
        
        # Create Estimate in OPPharmacyBill
        bill_obj = OPPharmacyBill.objects.create(
            bill_no="", # Following pharmacy.py pattern for estimates
            estimate_no=estimate_no,
            patient_name=patient_name,
            uhid=request_doc.get("uhid"),
            inpatient_number=request_doc.get("ipNumber"),
            doctor_id=request_doc.get("doctor"),
            room_no=request_doc.get("room_no"),
            medicine_particulars=selected_medicines,
            total_amount=total_amount,
            net_amount=total_amount,
            billing_status="Estimated",
            billing_mode="ESTIMATE",
            created_by=current_user,
            branch_code=branch_code
        )
        
        return Response({
            "success": True,
            "message": "Medicine ward request saved as Pharmacy Estimate successfully",
            "estimateNo": estimate_no,
            "id": bill_obj.bill_no # bill_no is pk
        })
        
    except Exception as e:
        print(traceback.format_exc())
        return Response({"success": False, "error": str(e)}, status=500)

@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def cancel_medicine_ward_request(request):
    try:
        data = request.data
        request_id = data.get("id") # bill_no
        
        if not request_id:
            return Response({"success": False, "error": "Request ID is required"}, status=400)
            
        # For OPPharmacyBill, we might set billing_status to "Cancelled" or similar
        # But looking at pharmacy.py, they seem to use billing_status for workflow.
        # Let's use billing_status="Cancelled"
        
        result = OPPharmacyBill.objects.filter(bill_no=request_id).update(billing_status="Cancelled")
        
        if result > 0:
            return Response({"success": True, "message": "Medicine ward request cancelled successfully"})
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
        request_id = data.get("id") # bill_no
        item_id = data.get("item_id")
        item_name = data.get("item_name")
        
        if not request_id:
            return Response({"success": False, "error": "Request ID is required"}, status=400)
            
        # Step 1: Get the document
        doc = OPPharmacyBill.objects.filter(bill_no=request_id).first()
        if not doc:
            return Response({"success": False, "error": "Request not found"}, status=404)
            
        items = doc.medicine_particulars or []
            
        # Step 2: Remove the medicine
        new_items = []
        found = False
        for itm in items:
            if item_id and str(itm.get("item_id")) == str(item_id):
                found = True
                continue
            if not item_id and itm.get("itemName") == item_name:
                found = True
                continue
            new_items.append(itm)
            
        if found:
            # Step 3: Recalculate total amount
            new_total = sum(float(t.get("price", t.get("Price", 0))) for t in new_items)
            
            doc.medicine_particulars = new_items
            doc.total_amount = new_total
            doc.net_amount = new_total
            doc.save()
            
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
@permission_classes([HasRoleAndDataPermission])
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
@permission_classes([HasRoleAndDataPermission])
def save_radiology_ward_request(request):
    try:
        import json
        data = request.data
        current_user = data.get('auth-user-id', "system")
        branch_code = data.get('auth-branch-code', 'system')
        department_code = data.get('auth-department-code', 'system')
        hospital_code = data.get('auth-hospital-code', 'system')
        
        request_doc = {k: v for k, v in data.items() if not k.startswith('auth-')}
        
        # ── Map selectedTests to 'item' for compatibility ──
        selected_tests = request_doc.get("selectedTests", [])
        request_doc["item"] = json.dumps(selected_tests)
        
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
        
        request_doc.update({
            "investBillNo": invest_bill_no,
            "created_by": current_user,
            "created_date": datetime.now(),
            "created_at": datetime.now(),
            "branch_code": branch_code,
            "department_code": department_code,
            "hospital_code": hospital_code,
            "status": "Result Pending",
            "is_active": True,
            "is_ward_request": True,
            "ward_request_type": "RADIOLOGY",
            "investBillDate": datetime.now()
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
@permission_classes([HasRoleAndDataPermission])
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
@permission_classes([HasRoleAndDataPermission])
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
