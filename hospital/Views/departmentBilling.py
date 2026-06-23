from pydoc import doc

from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from pyauth.auth import HasRoleAndDataPermission
from ..models import Patient,EstimateBilling,Admission, InsuranceProvider
from ..serializers import PatientSerializer,EstimateBillingSerializer
from rest_framework import status
from pymongo import MongoClient  
from django.db import transaction
from django.views.decorators.csrf import csrf_exempt
from datetime import datetime
from django.http import JsonResponse
from bson import ObjectId
from rest_framework import status as drf_status
import os, json
import traceback
from django.utils import timezone
from django.db.models import Q
from django.db import connection
from bson import Decimal128, ObjectId
from bson.json_util import dumps
import json
from pymongo import MongoClient, ReturnDocument
import re



@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def op_patient_detail_by_uhid(request, uhid):
    try:

        branch_code = request.data.get('auth-branch-code')
        hospital_code = request.data.get('auth-hospital-code')

        # Build filter
        query = {}

        if hospital_code:
            query["hospital_code"] = hospital_code
        if branch_code:
            query["branch_code"] = branch_code

        # Add UHID filter
        query["uhid"] = str(uhid)

        print("PATIENT QUERY:", query)

        # Direct query (NO LOOP ❌)
        patient = Patient.objects.filter(**query).first()

        if not patient:
            return Response({"error": "Patient not found"}, status=404)

        serializer = PatientSerializer(patient)
        data = dict(serializer.data)

        # Insurance name
        company_code = (data.get('company_code') or "").strip()

        if company_code:
            insurance = InsuranceProvider.objects.filter(
                company_code=company_code
            ).first()

            data['company_name'] = (
                insurance.company_name if insurance else None
            )
        else:
            data['company_name'] = None

        return Response(data)

    except Exception as e:
        return Response({"error": str(e)}, status=500)

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def ip_patient_detail_by_ipNumber(request, ipNumber):
    try:
        # ✅ Get auth codes (reuse helper)
        branch_code = request.data.get('auth-branch-code')
        hospital_code = request.data.get('auth-hospital-code')

        # ✅ Build admission query
        admission_query = {"ipNumber": ipNumber}

        if hospital_code:
            admission_query["hospital_code"] = hospital_code
        if branch_code:
            admission_query["branch_code"] = branch_code
        print("ADMISSION QUERY:", admission_query)

        # ✅ Fetch admission (NO .get ❌)
        admission = Admission.objects.filter(**admission_query).first()

        if not admission:
            return Response(
                {"error": "Admission record not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        # ✅ Build patient query
        patient_query = {"uhid": admission.uhid}

        if hospital_code:
            patient_query["hospital_code"] = hospital_code
        if branch_code:
            patient_query["branch_code"] = branch_code

        print("PATIENT QUERY:", patient_query)

        patient = Patient.objects.filter(**patient_query).first()

        if not patient:
            return Response(
                {"error": "Patient not found for the given UHID"},
                status=status.HTTP_404_NOT_FOUND
            )

        # ── Company Name ─────────────────────────────
        company_name = None
        if patient.company_code:
            insurance = InsuranceProvider.objects.filter(
                company_code=patient.company_code
            ).first()

            if insurance:
                company_name = insurance.company_name

        # ── Latest Room / Bed Details ───────────────
        room_no = None
        bed_no = None

        if admission.roomShitingDetails:
            active_shift_rooms = [
                r for r in admission.roomShitingDetails
                if r.get("is_roomActive") is True
            ]

            if active_shift_rooms:
                latest_shift = active_shift_rooms[-1]
                room_no = latest_shift.get("newRoomNo")
                bed_no = latest_shift.get("newBedNo")

        if room_no is None and admission.room_details:
            active_rooms = [
                r for r in admission.room_details
                if r.get("is_roomActive") is True
            ]

            latest_room = active_rooms[-1] if active_rooms else admission.room_details[-1]

            room_no = latest_room.get("roomNo")
            bed_no = latest_room.get("bedNo")

        # ── Response ───────────────────────────────
        response_data = {
            'ipNumber': admission.ipNumber,
            'ipserial_number': admission.ipserial_number,
            'uhid': admission.uhid,

            'roomNo': room_no,
            'bedNo': bed_no,
            'room_details': admission.room_details,
            'roomShitingDetails': getattr(admission, 'roomShitingDetails', []),

            'admissionDate': (
                admission.admissionDateTime.strftime("%Y-%m-%d")
                if admission.admissionDateTime else None
            ),
            'admissionTime': (
                admission.admissionDateTime.strftime("%H:%M")
                if admission.admissionDateTime else None
            ),
            'admittingDoctor': admission.admittingDoctor,
            'consultingDoctor': admission.consultingDoctor,
            'packageName': admission.packageName,
            'reasonForAdmission': admission.reasonForAdmission,

            'is_discharged': admission.is_discharged,
            'is_admissionActive': admission.is_admissionActive,
            'is_admitted': getattr(admission, 'is_admitted', False),

            'salutation': getattr(patient, 'salutation', ''),
            'firstName': patient.firstName,
            'lastName': patient.lastName,
            'age': patient.age,
            'gender': patient.gender,
            'dob': patient.dob,
            'mobilePhone': patient.mobilePhone,
            'area': patient.area,
            'city': patient.city,
            'state': patient.state,
            'zipcode': patient.zipcode,

            'customer_type': patient.customer_type,
            'company_code': patient.company_code,
            'company_name': company_name,
        }

        return Response(response_data, status=status.HTTP_200_OK)

    except Exception as e:
        return Response(
            {"error": f"An error occurred: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )       
 
@csrf_exempt
@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def estimate_billing_create(request):
    if request.method == 'POST':
        current_user = request.data.get('auth-user-id', 'system')
        branch_code = request.data.get('auth-branch-code', 'system')
        outlet_code = request.data.get('auth-outlet-code', 'system')
        hospital_code = request.data.get('auth-hospital-code', 'system')

        with transaction.atomic():
            last_bill = EstimateBilling.objects.select_for_update().order_by('-id').first()

            if last_bill and last_bill.EstBillNo:
                last_number = int(last_bill.EstBillNo)
                next_number = last_number + 1
            else:
                next_number = 1

            formatted_bill_no = f"{next_number:06d}"

            while EstimateBilling.objects.filter(EstBillNo=formatted_bill_no).exists():
                next_number += 1
                formatted_bill_no = f"{next_number:06d}"

            request_data = {k: v for k, v in request.data.items()
                            if not k.startswith('auth-')}

            request_data['EstBillNo'] = formatted_bill_no
            request_data['EstBillDate'] = timezone.now()   # ← server time
            request_data['created_by'] = current_user      # ← from auth header
            request_data['branch_code'] = branch_code      # ← from auth header
            request_data['hospital_code'] = hospital_code      # ← from auth header
            request_data['outlet_code'] = outlet_code      # ← from auth header

            serializer = EstimateBillingSerializer(data=request_data)
            if serializer.is_valid():
                serializer.save()
                return Response({'message': 'Form data saved successfully!', 'EstBillNo': formatted_bill_no}, status=201)

            return Response(serializer.errors, status=400)

def serialize_val(val):
    """Make a single value JSON-safe."""
    if isinstance(val, Decimal128):
        return float(val.to_decimal())
    if isinstance(val, ObjectId):
        return str(val)
    if isinstance(val, datetime):
        return val.isoformat()
    return val


def serialize_doc(doc):
    """Recursively convert Mongo document to JSON-safe dict."""
    if isinstance(doc, dict):
        return {k: serialize_doc(v) for k, v in doc.items()}
    if isinstance(doc, list):
        return [serialize_doc(i) for i in doc]
    return serialize_val(doc)

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def estimate_billing_list(request):
    try:
        branch_code   = request.data.get('auth-branch-code')
        outlet_code   = request.data.get('auth-outlet-code')
        hospital_code = request.data.get('auth-hospital-code')

        from_date_str   = request.GET.get('fromDate',     '').strip()
        to_date_str     = request.GET.get('toDate',       '').strip()
        bill_type_param = request.GET.get('billType',     '').strip()
        doctor_param    = request.GET.get('doctor',       '').strip()
        uhid_param      = request.GET.get('uhid',         '').strip()
        patient_type    = request.GET.get('patientType',  '').strip()

        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client['HMS']
        global_db = client['Global']

        estimate_collection      = db['hospital_estimatebilling']
        patient_collection       = db['hospital_patient']
        billtype_collection      = db['hospital_billtype']
        diagnostics_profile_coll = global_db['backend_diagnostics_profile']   # ← new

        # ── Base Query ───────────────────────────────────────────────────────
        query = {"is_active": {"$nin": [False, 0, "false", "False"]}}

        if hospital_code:
            query["hospital_code"] = hospital_code
        if branch_code:
            query["branch_code"] = branch_code
        if outlet_code:
            query["outlet_code"] = outlet_code

        print("ESTIMATE QUERY:", query)

        # ── Date filter ──────────────────────────────────────────────────────
        if from_date_str and to_date_str:
            try:
                start = datetime.strptime(from_date_str, "%Y-%m-%d")
                end   = datetime.strptime(to_date_str, "%Y-%m-%d").replace(
                    hour=23, minute=59, second=59, microsecond=999999
                )
                query["EstBillDate"] = {"$gte": start, "$lte": end}
            except ValueError:
                client.close()
                return Response(
                    {"error": "Invalid date format. Use YYYY-MM-DD."},
                    status=400,
                )

        # ── Bill type filter ─────────────────────────────────────────────────
        if bill_type_param:
            try:
                int_val = int(bill_type_param)
                query["bill_type"] = {"$in": [int_val, str(int_val)]}
            except (ValueError, TypeError):
                query["bill_type"] = {"$in": [bill_type_param]}

        # ── Doctor filter ────────────────────────────────────────────────────
        if doctor_param:
            query["doctor"] = doctor_param

        # ── UHID filter ──────────────────────────────────────────────────────
        if uhid_param:
            query["uhid"] = {"$regex": uhid_param, "$options": "i"}

        # ── Patient type filter ──────────────────────────────────────────────
        if patient_type == "IP":
            query["ipNumber"] = {"$exists": True, "$ne": "", "$nin": [None]}
        elif patient_type == "OP":
            query["$or"] = [
                {"ipNumber": {"$exists": False}},
                {"ipNumber": ""},
                {"ipNumber": None},
            ]

        # ── Fetch data ───────────────────────────────────────────────────────
        data = list(estimate_collection.find(query).sort("_id", -1))

        # ── Patient Cache ────────────────────────────────────────────────────
        uhids = {doc.get("uhid") for doc in data if doc.get("uhid")}
        patient_cache = {}

        if uhids:
            patient_query = {"uhid": {"$in": list(uhids)}}
            if hospital_code:
                patient_query["hospital_code"] = hospital_code
            if branch_code:
                patient_query["branch_code"] = branch_code

            patients = patient_collection.find(
                patient_query,
                {
                    "_id": 0, "uhid": 1, "salutation": 1,
                    "firstName": 1, "lastName": 1, "age": 1, "gender": 1
                }
            )
            for p in patients:
                patient_cache[p["uhid"]] = p

        # ── Bill Type Cache ──────────────────────────────────────────────────
        bill_type_ids = set()
        for doc in data:
            bt = doc.get("bill_type")
            if bt:
                try:
                    bill_type_ids.add(int(bt))
                except:
                    pass

        bill_type_cache = {}
        if bill_type_ids:
            bt_query = {"bill_type": {"$in": list(bill_type_ids)}}
            if hospital_code:
                bt_query["hospital_code"] = hospital_code
            if branch_code:
                bt_query["branch_code"] = branch_code
            if outlet_code:
                bt_query["outlet_code"] = outlet_code

            bt_docs = billtype_collection.find(
                bt_query,
                {"_id": 0, "bill_type": 1, "bill_name": 1, "billTypeNo": 1}
            )
            for bt in bt_docs:
                bill_type_cache[int(bt["bill_type"])] = {
                    "bill_name":  bt.get("bill_name",  ""),
                    "billTypeNo": bt.get("billTypeNo", "")
                }

        # ── Doctor / ReferredBy Cache ────────────────────────────────────────
        doctor_ids      = set()
        referred_by_ids = set()

        for doc in data:
            doc_val = doc.get("doctor", "")
            ref_val = doc.get("referredBy", "")

            if doc_val and str(doc_val).upper() != "SELF":
                doctor_ids.add(str(doc_val))
            if ref_val and str(ref_val).upper() != "SELF":
                referred_by_ids.add(str(ref_val))

        diagnostics_profile_cache = {}   # employeeId → employeeName

        all_profile_ids = doctor_ids | referred_by_ids
        if all_profile_ids:
            profile_docs = diagnostics_profile_coll.find(
                {"employeeId": {"$in": list(all_profile_ids)}},
                {"_id": 0, "employeeId": 1, "employeeName": 1}
            )
            for p in profile_docs:
                emp_id = str(p.get("employeeId", ""))
                if emp_id:
                    diagnostics_profile_cache[emp_id] = p.get("employeeName", "")

        # ── Enrich Data ──────────────────────────────────────────────────────
        result = []

        for doc in data:
            uhid = doc.get("uhid", "").strip()
            
            if uhid:
                patient = patient_cache.get(uhid, {})
                doc["salutation"] = patient.get("salutation", "")
                doc["firstName"]  = patient.get("firstName",  "")
                doc["lastName"]   = patient.get("lastName",   "")
                doc["gender"]     = patient.get("gender",     "")
            else:
                # Manual entry — fields already stored directly on the estimate doc
                doc["salutation"] = doc.get("salutation", "")
                doc["firstName"]  = doc.get("firstName",  "")
                doc["lastName"]   = doc.get("lastName",   "")
                doc["gender"]     = doc.get("gender",     "")

            # Age / room — always from the estimate doc
            doc["age"]      = doc.get("age",      "")
            doc["age_type"] = doc.get("age_type", "")
            doc["roomNo"]   = doc.get("roomNo",   "")

            try:
                bt_key = int(doc.get("bill_type", 0))
            except:
                bt_key = 0

            bt_info = bill_type_cache.get(bt_key, {})
            doc["bill_name"]  = bt_info.get("bill_name",  "")
            doc["billTypeNo"] = bt_info.get("billTypeNo", "")

            # ── Doctor name ──────────────────────────────────────────────────
            doc_val = doc.get("doctor", "")
            if doc_val and str(doc_val).upper() == "SELF":
                doc["doctorName"] = "SELF"
            else:
                doc["doctorName"] = diagnostics_profile_cache.get(str(doc_val), "")

            # ── ReferredBy name ──────────────────────────────────────────────
            ref_val = doc.get("referredBy", "")
            if ref_val and str(ref_val).upper() == "SELF":
                doc["referredByName"] = "SELF"
            else:
                doc["referredByName"] = diagnostics_profile_cache.get(str(ref_val), "")

            if isinstance(doc.get("item"), str):
                try:
                    doc["item"] = json.loads(doc["item"])
                except:
                    doc["item"] = []

            result.append(serialize_doc(doc))

        client.close()
        return Response(result)

    except Exception as e:
        return Response(
            {"error": "Failed to fetch estimate billing list", "details": str(e)},
            status=500,
        )



@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_bill_types(request):
    try:
        branch_code = request.data.get('auth-branch-code')
        outlet_code = request.data.get('auth-outlet-code')
        hospital_code = request.data.get('auth-hospital-code')

        ignore_outlet = request.GET.get('ignore_outlet') == 'true'

        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client['HMS']
        collection = db['hospital_billtype']

        query = {"is_active": True}

        if hospital_code:
            query["hospital_code"] = hospital_code

        if branch_code:
            query["branch_code"] = branch_code

        # ✅ FIX: include empty outlet also
        if outlet_code and not ignore_outlet:
            query["$or"] = [
                {"outlet_code": outlet_code},
                {"outlet_code": ""},
                {"outlet_code": {"$exists": False}}
            ]

        print("QUERY:", query)

        bill_types = list(collection.find(
            query,
            {
                "_id": 0,
                "bill_type": 1,
                "bill_name": 1,
                "billTypeNo": 1,
                "outlet_code": 1,
                "is_allowDiscount": 1,
            }
        ))

        client.close()

        return JsonResponse({"billTypes": bill_types}, safe=False)

    except Exception as e:
        return JsonResponse({
            "error": str(e)
        }, status=500)
    
@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_packages(request):
    try:
        branch_code = request.data.get('auth-branch-code')
        outlet_code = request.data.get('auth-outlet-code')
        hospital_code = request.data.get('auth-hospital-code')

        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client['HMS']
        collection = db['hospital_package']

        # ✅ Base query
        query = {"is_active": True}

        # ✅ Apply auth filters dynamically
        if hospital_code:
            query["hospital_code"] = hospital_code
        if branch_code:
            query["branch_code"] = branch_code
        if outlet_code:
            query["outlet_code"] = outlet_code

        print("PACKAGE QUERY:", query)

        packages = list(collection.find(
            query,
            {
                "_id": 0,
                "packageNo": 1,
                "packageName": 1
            }
        ))

        client.close()

        return JsonResponse({
            "success": True,
            "packages": packages
        }, safe=False)

    except Exception as e:
        return JsonResponse({
            "success": False,
            "error": str(e)
        }, status=500)

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_package_items(request):
    """Fetch package items based on packageNo"""
    try:
        package_no = request.GET.get('packageNo')
        
        if not package_no:
            return JsonResponse({
                "error": "packageNo parameter is required"
            }, status=400)
        
        # Convert to int
        try:
            package_no = int(package_no)
        except (ValueError, TypeError):
            return JsonResponse({
                "error": "packageNo must be a valid integer",
                "packageNo": package_no
            }, status=400)
        
        # Connect to MongoDB
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client['HMS']
        collection = db['hospital_package']

        # Fetch package by packageNo
        package_data = collection.find_one(
            {"packageNo": package_no, "is_active": True},
            {"_id": 0, "items": 1, "packageName": 1, "totalPrice": 1}
        )
        
        client.close()

        if package_data and "items" in package_data:
            return JsonResponse({
                "items": package_data["items"],
                "packageName": package_data.get("packageName", ""),
                "totalPrice": package_data.get("totalPrice", "0.00")
            }, safe=True)
        else:
            return JsonResponse({"items": [], "packageName": ""}, safe=True)
    
    except Exception as e:
        return JsonResponse({
            "error": "An error occurred while fetching package items",
            "details": str(e)
        }, status=500)


@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_investigation_items(request):
    """Fetch investigation items based on billTypeNo and bill_type from hospital_investigationprice collection
    Special case: When billTypeNo="LAB01", fetch lab tests from Diagnostics database"""
    try:
        bill_type_no = request.GET.get('billTypeNo')
        bill_type = request.GET.get('billType')
        item_name = request.GET.get('itemName')
        
        # Validate billTypeNo
        if bill_type_no is None or bill_type_no == 'undefined' or bill_type_no == 'null':
            return JsonResponse({
                "error": "billTypeNo parameter is required and cannot be undefined",
                "received": bill_type_no
            }, status=400)
        
        # Validate billType
        if bill_type is None or bill_type == 'undefined' or bill_type == 'null':
            return JsonResponse({
                "error": "billType parameter is required and cannot be undefined",
                "received": bill_type
            }, status=400)
        
        # Convert bill_type to int (it should always be numeric)
        try:
            bill_type = int(bill_type)
        except (ValueError, TypeError):
            return JsonResponse({
                "error": "billType must be a valid integer",
                "billType": bill_type
            }, status=400)
        
        # Special case: billTypeNo = "LAB01" means fetch lab tests
        if bill_type_no == "LAB01":
            # Connect to MongoDB Diagnostics database
            client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
            db = client['Diagnostics']
            collection = db['core_testdetails']
            
            # Build query
            query = {"is_active": True}
            if item_name:
                query["test_name"] = {"$regex": item_name, "$options": "i"}

            # Fetch active tests
            tests = list(collection.find(
                query,
                {
                    "test_id": 1,
                    "test_name": 1,
                    "SH_Rate": 1,
                    "Credit_Rate": 1,
                    "_id": 0
                }
            ))
            
            client.close()
            
            # Determine which rate to use based on bill_type
            # You can customize this logic based on your bill_type values
            # For example, if bill_type ends with "SH" use SH_Rate, otherwise Credit_Rate
            formatted_items = []
            for test in tests:
                # Default to SH_Rate, but you can add logic to determine which rate
                # based on bill_type or other criteria
                price = test.get('SH_Rate', '0')
                
                # Convert None, "None", empty string, or None type to "0" for consistency
                if price is None or str(price).strip().lower() == 'none' or str(price).strip() == '':
                    price = "0"
                
                # Ensure price is a string
                price_str = str(price)
                
                formatted_items.append({
                    "itemName": test.get('test_name', ''),
                    "price": price_str,
                    "test_id": test.get('test_id', '')
                })
            
            return JsonResponse({"items": formatted_items}, safe=True)
        
        # Regular case: Fetch from hospital_investigationprice
        # billTypeNo is kept as string (e.g., "X-RAY01", "CT01")
        # Connect to MongoDB
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client['HMS']
        collection = db['hospital_investigationprice']

        # Fetch items for the specific billTypeNo (using string comparison)
        investigation_data = collection.find_one(
            {"billTypeNo": bill_type_no},
            {"_id": 0, "Items": 1, "BillType": 1}
        )
        
        client.close()

        if investigation_data and "Items" in investigation_data:
            items = investigation_data["Items"]
            # Transform items to a more usable format
            # Each item has structure like: {"8": "800", "41": "500", "itemName": "Chest X-Ray"}
            # where "8" and "41" are bill_types and "800", "500" are their respective prices
            formatted_items = []
            for item in items:
                item_name = item.get("itemName", "")
                item_id = item.get("item_id", "")
                # Get the price for the specific bill_type
                price = item.get(str(bill_type), "0")
                
                # Only include items that have a price for this bill_type
                if price and price != "0":
                    formatted_items.append({
                        "itemName": item_name,
                        "item_id": item_id,
                        "price": price
                    })
            
            return JsonResponse({"items": formatted_items}, safe=True)
        else:
            return JsonResponse({"items": []}, safe=True)
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({
            "error": "An error occurred while fetching investigation items",
            "details": str(e)
        }, status=500)


@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def invest_billing_create(request):
    mongo_client = None

    try:
        current_user = request.data.get('auth-user-id', "system")
        branch_code = request.data.get('auth-branch-code', 'system')
        outlet_code = request.data.get('auth-outlet-code', 'system')
        hospital_code = request.data.get('auth-hospital-code', 'system')

        data = {k: v for k, v in request.data.items()
                if not k.startswith('auth-')}

        # ── Normalize item field ───────────────────────────────
        def normalize_item(item):
            if isinstance(item, list):
                return item   # ✅ keep as list

            elif isinstance(item, str):
                try:
                    parsed = json.loads(item)

                    # Handle double-string case
                    if isinstance(parsed, str):
                        parsed = json.loads(parsed)

                    return parsed if isinstance(parsed, list) else []

                except (json.JSONDecodeError, TypeError):
                    return []

            return []

        if "item" in data:
            data["item"] = normalize_item(data["item"])

        # ── Connect MongoDB ─────────────────────────────────────
        mongo_client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        mongo_db = mongo_client['HMS']
        invest_collection = mongo_db['hospital_investbilling']
        counters_collection = mongo_db['counters']

        # ── Deactivate related estimate ─────────────────────────
        est_bill_no = data.get("EstBillNo")
        if est_bill_no:
            mongo_db['hospital_estimatebilling'].update_one(
                {"EstBillNo": est_bill_no, "is_active": True},
                {"$set": {
                    "is_active": False,
                    "lastmodified_by": current_user,
                    "lastmodified_date": timezone.now()
                }}
            )

        data.pop("EstBillNo", None)
        data.pop("EstBillDate", None)

        bill_type = data.get("bill_type")
        if not bill_type:
            return Response(
                {"error": "bill_type is required"},
                status=drf_status.HTTP_400_BAD_REQUEST
            )

        data["investBillDate"] = timezone.now()

       # ───────────────── UPDATE ──────────────────────────────
        existing_invest_bill_no = data.get("investBillNo")
        if existing_invest_bill_no:

            existing_record = invest_collection.find_one(
                {"investBillNo": existing_invest_bill_no, "is_active": True}
            )

            if not existing_record:
                return Response(
                    {"error": f"No record found with investBillNo: {existing_invest_bill_no}"},
                    status=drf_status.HTTP_404_NOT_FOUND
                )

            # ── editRemarks is required for every edit ────────────────────────
            edit_remarks = data.get("editRemarks", "").strip()
            if not edit_remarks:
                return Response(
                    {"error": "editRemarks is required when editing a bill."},
                    status=drf_status.HTTP_400_BAD_REQUEST
                )
            # ── Build history snapshot with only old values of changed fields ─────
            fields_to_ignore = {"_id", "history", "investBillNo", "lastmodified_by",
                                "lastmodified_date", "editRemarks", "created_by",
                                "created_date", "branch_code", "outlet_code", "hospital_code"}

            changed_fields = {}
            for key, new_value in data.items():
                if key in fields_to_ignore:
                    continue
                old_value = existing_record.get(key)
                if old_value != new_value:
                    changed_fields[key] = old_value   # ← only old value

            history_edit = {
                "modified_date": timezone.now(),
                "modified_by": current_user,
                "editRemarks": edit_remarks,
                "changes": changed_fields
            }

            data["lastmodified_by"] = current_user
            data["lastmodified_date"] = timezone.now()
            data.pop("editRemarks", None)   # ← remove from top-level
            data.pop("investBillNo", None)

            invest_collection.update_one(
                {"_id": existing_record["_id"]},
                {
                    "$set": data,
                    "$push": {"history": history_edit}
                }
            )

            return Response(
                {"message": "Billing updated successfully!",
                "investBillNo": existing_invest_bill_no},
                status=drf_status.HTTP_200_OK
            )
        # ───────────────── CREATE ──────────────────────────────

        # Financial Year Logic
        today = datetime.today()
        if today.month < 4:
            financial_year = f"{(today.year - 1) % 100:02d}{today.year % 100:02d}"
        else:
            financial_year = f"{today.year % 100:02d}{(today.year + 1) % 100:02d}"

        prefix_key = f"{financial_year}/{bill_type}"
        prefix = f"{prefix_key}/"

        # 🔥 ATOMIC COUNTER (Concurrency Safe)
        counter = counters_collection.find_one_and_update(
            {"_id": prefix_key},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER
        )

        next_number = counter["seq"]
        invest_bill_no = f"{prefix}{next_number:06d}"

        # Stamp fields
        data["investBillNo"] = invest_bill_no
        data["created_by"] = current_user
        data["branch_code"] = branch_code
        data["outlet_code"] = outlet_code
        data["hospital_code"] = hospital_code
        data["created_date"] = timezone.now()
        data["lastmodified_by"] = None
        data["lastmodified_date"] = timezone.now()
        data["is_active"] = True

        # Insert
        invest_collection.insert_one(data)

        return Response(
            {"message": "Billing saved successfully!",
             "investBillNo": invest_bill_no},
            status=drf_status.HTTP_201_CREATED
        )

    except Exception as e:
        traceback.print_exc()
        return Response(
            {"error": "Billing failed", "details": repr(e)},
            status=500
        )

    finally:
        if mongo_client:
            mongo_client.close()



@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def billing_report_view(request):

    def serialize_doc(doc):
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

    try:
        branch_code   = request.data.get('auth-branch-code',   'system')
        outlet_code   = request.data.get('auth-outlet-code',   'system')
        hospital_code = request.data.get('auth-hospital-code', 'system')

        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client['HMS']
        global_db = client['Global']

        collection               = db['hospital_investbilling']
        bill_type_collection     = db['hospital_billtype']
        patient_collection       = db['hospital_patient']
        refund_collection        = db['hospital_investrefund']
        diagnostics_profile_coll = global_db['backend_diagnostics_profile']  # ← new

        # ── Base Query ─────────────────────────────────────────
        query = {"is_active": True}

        if hospital_code:
            query["hospital_code"] = hospital_code
        if branch_code:
            query["branch_code"] = branch_code
        if outlet_code:
            query["outlet_code"] = outlet_code

        print("BILLING QUERY:", query)

        # ── Date filter ────────────────────────────────────────
        start_date = request.GET.get('start_date')
        end_date   = request.GET.get('end_date')

        if start_date and end_date:
            try:
                start = datetime.strptime(start_date, "%Y-%m-%d")
                end   = datetime.strptime(end_date,   "%Y-%m-%d").replace(
                    hour=23, minute=59, second=59, microsecond=999999
                )
                query["investBillDate"] = {"$gte": start, "$lte": end}
            except ValueError:
                return JsonResponse({"error": "Invalid date format"}, status=400)

        # ── Bill type filter ───────────────────────────────────
        bill_type_param = request.GET.get('billType')
        if bill_type_param:
            try:
                query["bill_type"] = int(bill_type_param)
            except:
                query["bill_type"] = bill_type_param

        # ── Doctor filter ──────────────────────────────────────
        doctor_param = request.GET.get('doctor')
        if doctor_param:
            query["doctor"] = doctor_param

        # ── UHID filter ────────────────────────────────────────
        uhid_param = request.GET.get('uhid')
        if uhid_param:
            query["uhid"] = {"$regex": uhid_param, "$options": "i"}

        # ── Patient type filter ────────────────────────────────
        patient_type_param = request.GET.get('patientType')
        if patient_type_param == 'IP':
            query["ipNumber"] = {"$exists": True, "$ne": "", "$nin": [None]}
        elif patient_type_param == 'OP':
            query["$or"] = [
                {"ipNumber": {"$exists": False}},
                {"ipNumber": ""},
                {"ipNumber": None},
            ]

        # ── Fetch billing data ─────────────────────────────────
        data = list(collection.find(query))

        # ── Batch Refund Cache ─────────────────────────────────
        invest_bill_nos = [
            doc.get("investBillNo") for doc in data if doc.get("investBillNo")
        ]

        refunded_test_ids = {}

        if invest_bill_nos:
            refund_docs = refund_collection.find(
                {
                    "investBillNo": {"$in": invest_bill_nos},
                    "is_active": True
                },
                {"_id": 0, "investBillNo": 1, "item": 1}
            )

            for rdoc in refund_docs:
                bill_no = rdoc.get("investBillNo")
                items   = rdoc.get("item", [])

                if isinstance(items, str):
                    try:
                        items = json.loads(items)
                    except:
                        items = []

                if bill_no not in refunded_test_ids:
                    refunded_test_ids[bill_no] = set()

                for it in items:
                    tid = it.get("item_id") or it.get("test_id")
                    if tid is not None:
                        try:
                            refunded_test_ids[bill_no].add(int(tid))
                        except (ValueError, TypeError):
                            refunded_test_ids[bill_no].add(tid)

        # ── Batch Patient Cache ────────────────────────────────
        uhids = {doc.get("uhid") for doc in data if doc.get("uhid")}
        patient_cache = {}

        if uhids:
            patient_query = {"uhid": {"$in": list(uhids)}}
            if hospital_code:
                patient_query["hospital_code"] = hospital_code
            if branch_code:
                patient_query["branch_code"] = branch_code

            patients = patient_collection.find(
                patient_query,
                {
                    "_id": 0, "uhid": 1, "salutation": 1,
                    "firstName": 1, "lastName": 1, "age": 1, "gender": 1
                }
            )
            for p in patients:
                patient_cache[p["uhid"]] = p

        # ── Batch Bill Type Cache ──────────────────────────────
        bill_type_ids = set()
        for doc in data:
            bt = doc.get("bill_type")
            if bt:
                try:
                    bill_type_ids.add(int(bt))
                except:
                    pass

        bill_type_cache = {}
        if bill_type_ids:
            bt_docs = bill_type_collection.find(
                {"bill_type": {"$in": list(bill_type_ids)}},
                {"_id": 0, "bill_type": 1, "bill_name": 1, "billTypeNo": 1}
            )
            for bt in bt_docs:
                bill_type_cache[int(bt["bill_type"])] = {
                    "bill_name":  bt.get("bill_name",  ""),
                    "billTypeNo": bt.get("billTypeNo", "")
                }

        # ── Batch Doctor / ReferredBy Cache ────────────────────
        # Collect all employee IDs that are NOT "SELF"
        doctor_ids     = set()
        referred_by_ids = set()

        for doc in data:
            doc_val = doc.get("doctor", "")
            ref_val = doc.get("referredBy", "")

            if doc_val and doc_val.upper() != "SELF":
                doctor_ids.add(str(doc_val))

            if ref_val and ref_val.upper() != "SELF":
                referred_by_ids.add(str(ref_val))

        # One query covers both sets — union of all IDs needed
        all_profile_ids = doctor_ids | referred_by_ids
        diagnostics_profile_cache = {}   # employeeId → full name string

        if all_profile_ids:
            profile_docs = diagnostics_profile_coll.find(
                {"employeeId": {"$in": list(all_profile_ids)}},
                {"_id": 0, "employeeId": 1, "employeeName": 1}
            )
            for p in profile_docs:
                emp_id   = str(p.get("employeeId", ""))
                emp_name = p.get("employeeName", "")
                if emp_id:
                    diagnostics_profile_cache[emp_id] = emp_name

        # ── Enrich & Filter Data ───────────────────────────────
        result = []

        for doc in data:

            # Patient — use patient_cache if uhid exists, else fall back to doc fields
            uhid = doc.get("uhid", "").strip()
            if uhid:
                patient = patient_cache.get(uhid, {})
                doc["salutation"] = patient.get("salutation", "")
                doc["firstName"]  = patient.get("firstName",  "")
                doc["lastName"]   = patient.get("lastName",   "")
                doc["gender"]     = patient.get("gender",     "")
            else:
                # Manual entry — fields already stored directly on the billing doc
                doc["salutation"] = doc.get("salutation", "")
                doc["firstName"]  = doc.get("firstName",  "")
                doc["lastName"]   = doc.get("lastName",   "")
                doc["gender"]     = doc.get("gender",     "")

            # Age / room — always from the billing doc (not patient_cache)
            doc["age"]      = doc.get("age",    "")
            doc["age_type"] = doc.get("age_type", "")
            doc["roomNo"]   = doc.get("roomNo",   "")

            # Bill type
            try:
                bt_key = int(doc.get("bill_type", 0))
            except:
                bt_key = 0

            bt_info = bill_type_cache.get(bt_key, {})
            doc["bill_name"]  = bt_info.get("bill_name",  "")
            doc["billTypeNo"] = bt_info.get("billTypeNo", "")

            # ── Doctor name ────────────────────────────────────
            doc_val = doc.get("doctor", "")
            if doc_val and doc_val.upper() == "SELF":
                doc["doctorName"] = "SELF"
            else:
                doc["doctorName"] = diagnostics_profile_cache.get(str(doc_val), "")

            # ── ReferredBy name ────────────────────────────────
            ref_val = doc.get("referredBy", "")
            if ref_val and ref_val.upper() == "SELF":
                doc["referredByName"] = "SELF"
            else:
                doc["referredByName"] = diagnostics_profile_cache.get(str(ref_val), "")

            # Parse items
            items = doc.get("item", [])
            if isinstance(items, str):
                try:
                    items = json.loads(items)
                except:
                    items = []

            # ── Exclude already-refunded items ─────────────────
            bill_no          = doc.get("investBillNo", "")
            already_refunded = refunded_test_ids.get(bill_no, set())

            if already_refunded:
                filtered_items = []
                for it in items:
                    tid = it.get("item_id") or it.get("test_id")
                    try:
                        tid_norm = int(tid) if tid is not None else None
                    except (ValueError, TypeError):
                        tid_norm = tid

                    if tid_norm not in already_refunded:
                        filtered_items.append(it)
                doc["item"] = filtered_items
            else:
                doc["item"] = items

            # Skip the bill entirely if all items have been refunded
            if not doc["item"]:
                continue

            result.append(serialize_doc(doc))

        client.close()

        result.sort(key=lambda x: x.get("investBillDate", ""), reverse=True)

        return JsonResponse(result, safe=False)

    except Exception as e:
        return JsonResponse(
            {"error": "Failed to generate billing report", "details": str(e)},
            status=500
        )



@api_view(['PATCH'])
@csrf_exempt
@permission_classes([HasRoleAndDataPermission])
def delete_bill_view(request):
    try:
        investBillNo  = request.data.get('investBillNo')
        delete_remarks = request.data.get('deleteRemarks', '').strip()
        employeeId    = request.data.get('auth-user-id', 'system')

        if not investBillNo:
            return JsonResponse({'error': 'Missing investBillNo'}, status=400)

        if not delete_remarks:
            return JsonResponse({'error': 'deleteRemarks is required'}, status=400)

        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client['HMS']
        collection = db['hospital_investbilling']

        result = collection.update_one(
            {"investBillNo": investBillNo, "is_active": True},
            {
                "$set": {
                    "is_active":     False,
                    "deletedBy":     employeeId,
                    "deletedAt":     datetime.now(),
                    "deleteRemarks": delete_remarks,   # ← stored on the document
                }
            }
        )

        client.close()

        if result.matched_count == 0:
            return JsonResponse({'error': 'Bill not found or already deleted'}, status=404)

        return JsonResponse({'message': 'Bill deleted successfully'}, status=200)

    except Exception as e:
        return JsonResponse({'error': 'Failed to delete bill', 'details': str(e)}, status=500)
    
    
    
@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def dept_budr_view(request):

    def serialize_doc(doc):
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

    try:
        report_type = request.GET.get('report_type', '').strip().lower()
        if report_type not in ('deleted', 'edited'):
            return JsonResponse(
                {"error": "report_type must be 'deleted' or 'edited'"},
                status=400,
            )

        start_date = request.GET.get('start_date')
        end_date   = request.GET.get('end_date')

        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))

        # DBs
        hms_db     = client['HMS']
        global_db  = client['Global']

        collection           = hms_db['hospital_investbilling']
        bill_type_collection = hms_db['hospital_billtype']
        outlet_collection    = hms_db['hospital_outlets']   # ✅ NEW

        profile_collection   = global_db['backend_diagnostics_profile']

        # ── Query setup ─────────────────────────────
        if report_type == 'deleted':
            query = {
                "is_active": False,
                "deletedAt": {"$exists": True},
            }
            date_field      = "deletedAt"
            actor_id_field  = "deletedBy"
            actor_name_out  = "deletedByName"
        else:
            query = {
                "is_active": True,
                "lastmodified_by": {"$ne": None, "$exists": True},
                "history": {"$exists": True},
            }
            date_field      = "lastmodified_date"
            actor_id_field  = "lastmodified_by"
            actor_name_out  = "lastmodified_by_name"

        # ── Date filter ─────────────────────────────
        if start_date and end_date:
            try:
                start = datetime.strptime(start_date, "%Y-%m-%d")
                end   = datetime.strptime(end_date, "%Y-%m-%d").replace(
                    hour=23, minute=59, second=59, microsecond=999999
                )
                query[date_field] = {"$gte": start, "$lte": end}
            except ValueError:
                client.close()
                return JsonResponse(
                    {"error": "Invalid date format. Use YYYY-MM-DD."},
                    status=400,
                )

        data = list(collection.find(query))

        # ── Employee mapping ───────────────────────
        actor_ids = {
            str(doc.get(actor_id_field, "")).strip()
            for doc in data
            if doc.get(actor_id_field)
        }

        employee_cache = {}
        if actor_ids:
            profiles = profile_collection.find(
                {"employeeId": {"$in": list(actor_ids)}},
                {"_id": 0, "employeeId": 1, "employeeName": 1},
            )
            for p in profiles:
                employee_cache[str(p.get("employeeId", "")).strip()] = p.get("employeeName", "")

        # ── Bill type cache ────────────────────────
        bill_type_cache = {}

        # ── Outlet mapping (NEW) ───────────────────
        outlet_codes = {
            str(doc.get("outlet_code", "")).strip()
            for doc in data
            if doc.get("outlet_code")
        }

        outlet_cache = {}
        if outlet_codes:
            outlets = outlet_collection.find(
                {"outlet_code": {"$in": list(outlet_codes)}},
                {"_id": 0, "outlet_code": 1, "outlet_name": 1}
            )
            for o in outlets:
                outlet_cache[str(o.get("outlet_code", "")).strip()] = o.get("outlet_name", "")

        # ── Process data ───────────────────────────
        result = []

        for doc in data:

            # Bill type
            bill_type = doc.get("bill_type")
            if bill_type:
                if bill_type not in bill_type_cache:
                    try:
                        bt_doc = bill_type_collection.find_one(
                            {"bill_type": int(bill_type)},
                            {"_id": 0, "bill_name": 1, "billTypeNo": 1},
                        )
                        bill_type_cache[bill_type] = {
                            "bill_name":  bt_doc.get("bill_name", "") if bt_doc else "",
                            "billTypeNo": bt_doc.get("billTypeNo", "") if bt_doc else "",
                        }
                    except:
                        bill_type_cache[bill_type] = {"bill_name": "", "billTypeNo": ""}

                doc["bill_name"]  = bill_type_cache[bill_type]["bill_name"]
                doc["billTypeNo"] = bill_type_cache[bill_type]["billTypeNo"]
            else:
                doc["bill_name"]  = ""
                doc["billTypeNo"] = ""

            # Employee name
            actor_id = str(doc.get(actor_id_field, "")).strip()
            doc[actor_name_out] = employee_cache.get(actor_id, actor_id or "")

            # ✅ Outlet name (NEW)
            outlet_code = str(doc.get("outlet_code", "")).strip()
            doc["outlet_name"] = outlet_cache.get(outlet_code, "")

            result.append(serialize_doc(doc))

        client.close()

        result.sort(key=lambda x: x.get(date_field, ""), reverse=True)

        return JsonResponse(result, safe=False)

    except Exception as e:
        return JsonResponse(
            {"error": "Failed to fetch report", "details": str(e)},
            status=500,
        )
@api_view(['POST'])
@csrf_exempt
@permission_classes([HasRoleAndDataPermission])
def invest_refund_create(request):
    """
    Creates a refund bill for selected items from an existing invest bill.
    refundBillNo is generated by incrementing the last existing refundBillNo
    that matches the same financial-year/bill_type prefix  (no atomic counter).
    """
    mongo_client = None
    try:
        current_user  = request.data.get('auth-user-id',       'system')
        branch_code   = request.data.get('auth-branch-code',   'system')
        outlet_code   = request.data.get('auth-outlet-code',   'system')
        hospital_code = request.data.get('auth-hospital-code', 'system')

        data = {k: v for k, v in request.data.items()
                if not k.startswith('auth-')}

        # ── Validate required fields ────────────────────────────────────────
        required = ['investBillNo', 'uhid', 'bill_type', 'item', 'refund_finalPrice']
        for field in required:
            if not data.get(field):
                return Response(
                    {'error': f'{field} is required'},
                    status=drf_status.HTTP_400_BAD_REQUEST
                )

        # ── Normalize item list ─────────────────────────────────────────────
        item_data = data.get('item', [])
        if isinstance(item_data, str):
            try:
                item_data = json.loads(item_data)
                if isinstance(item_data, str):
                    item_data = json.loads(item_data)
            except (json.JSONDecodeError, TypeError):
                item_data = []
        if not isinstance(item_data, list) or len(item_data) == 0:
            return Response(
                {'error': 'At least one item must be selected for refund'},
                status=drf_status.HTTP_400_BAD_REQUEST
            )

        # ── Connect MongoDB ─────────────────────────────────────────────────
        mongo_client   = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        mongo_db       = mongo_client['HMS']
        refund_col     = mongo_db['hospital_investrefund']
        invest_col     = mongo_db['hospital_investbilling']

        # ── Verify the source invest bill exists and is active ───────────────
        invest_bill_no = data['investBillNo']
        source_bill = invest_col.find_one(
            {'investBillNo': invest_bill_no, 'is_active': True}
        )
        if not source_bill:
            return Response(
                {'error': f'Active invest bill not found: {invest_bill_no}'},
                status=drf_status.HTTP_404_NOT_FOUND
            )

        # ── Financial year prefix ────────────────────────────────────────────
        today = datetime.today()
        if today.month < 4:
            financial_year = f"{(today.year - 1) % 100:02d}{today.year % 100:02d}"
        else:
            financial_year = f"{today.year % 100:02d}{(today.year + 1) % 100:02d}"

        # fixed — financial year only
        bill_type  = data['bill_type']   
        prefix_key = f"{financial_year}"   # e.g. "2627"
        prefix     = f"{prefix_key}/"      # e.g. "2627/"

        # ── Last-incremental refundBillNo (no atomic counter) ────────────────
        # Find the highest existing refundBillNo for this prefix and add 1.
        last_doc = refund_col.find_one(
            {'refundBillNo': {'$regex': f'^{re.escape(prefix)}'}},
            sort=[('refundBillNo', -1)]
        )

        if last_doc and last_doc.get('refundBillNo'):
            try:
                last_seq = int(last_doc['refundBillNo'].rsplit('/', 1)[-1])
            except (ValueError, IndexError):
                last_seq = 0
        else:
            last_seq = 0

        next_seq       = last_seq + 1
        refund_bill_no = f"{prefix}{next_seq:06d}"   # e.g. "2627/16/000009"

        # ── Build document ───────────────────────────────────────────────────
        now = timezone.now()
        # Parse investBillDate string → proper datetime object
        raw_invest_date = data.get('investBillDate')
        if raw_invest_date:
            try:
                # Handle both "2026-05-13T11:57:04.604Z" and "2026-05-13T11:57:04.604+00:00"
                invest_bill_date = datetime.fromisoformat(
                    raw_invest_date.replace('Z', '+00:00')
                )
            except (ValueError, AttributeError):
                invest_bill_date = now
        else:
            invest_bill_date = now

        refund_doc = {
            'refundBillNo':     refund_bill_no,
            'refundBillDate':   now,
            'investBillNo':     invest_bill_no,
            'uhid':             data.get('uhid', ''),
            'ipNumber':         data.get('ipNumber', ''),
            'bill_type':        bill_type,
            'billTypeNo':       data.get('billTypeNo', ''),
            'refund_finalPrice':str(data.get('refund_finalPrice', '0.00')),
            'paymentStatus':    'Pending',
            'item':             item_data,
            'investBillDate':   invest_bill_date,   # use the parsed datetime object
            'created_by':       current_user,
            'branch_code':      branch_code,
            'outlet_code':      outlet_code,
            'hospital_code':    hospital_code,
            'created_date':     now,
            'lastmodified_by':  None,
            'lastmodified_date':now,
            'is_active':        True,
        }

        refund_col.insert_one(refund_doc)

        return Response(
            {
                'message':       'Refund bill created successfully!',
                'refundBillNo':  refund_bill_no,
            },
            status=drf_status.HTTP_201_CREATED
        )

    except Exception as e:
        traceback.print_exc()
        return Response(
            {'error': 'Refund creation failed', 'details': repr(e)},
            status=500
        )
    finally:
        if mongo_client:
            mongo_client.close()  
