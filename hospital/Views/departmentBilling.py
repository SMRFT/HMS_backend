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



@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def op_patient_detail_by_uhid(request, uhid):
    try:
        patient = Patient.objects.get(uhid=uhid)
        serializer = PatientSerializer(patient)
        data = dict(serializer.data)  # ← convert to mutable dict

        if data.get('company_code'):
            try:
                insurance = InsuranceProvider.objects.get(company_code=data['company_code'].strip())
                data['company_name'] = insurance.company_name
            except InsuranceProvider.DoesNotExist:
                data['company_name'] = None
        else:
            data['company_name'] = None

        return Response(data)
    except Patient.DoesNotExist:
        return Response({"error": "Patient not found"}, status=404)


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def ip_patient_detail_by_ipNumber(request, ipNumber):
    try:
        admission = Admission.objects.get(ipNumber=ipNumber)

        try:
            patient = Patient.objects.get(uhid=admission.uhid)

            # Fetch company name if company_code exists
            company_name = None
            if patient.company_code:
                try:
                    insurance = InsuranceProvider.objects.get(company_code=patient.company_code)
                    company_name = insurance.company_name
                except InsuranceProvider.DoesNotExist:
                    pass

            response_data = {
                'ipNumber': admission.ipNumber,
                'uhid': admission.uhid,
                'roomNo': admission.roomNo,
                'admissionDate': admission.admissionDateTime.strftime("%Y-%m-%d") if admission.admissionDateTime else None,
                'admissionTime': admission.admissionDateTime.strftime("%H:%M") if admission.admissionDateTime else None,
                'admittingDoctor': admission.admittingDoctor,
                'salutation': patient.salutation if hasattr(patient, 'salutation') else '',
                'firstName': patient.firstName,
                'lastName': patient.lastName,
                'age': patient.age,
                'gender': patient.gender,
                'area': patient.area,
                'city': patient.city,
                'state': patient.state,
                # Company fields
                'customer_type': patient.customer_type,
                'company_code': patient.company_code,
                'company_name': company_name,
            }

            return Response(response_data, status=status.HTTP_200_OK)

        except Patient.DoesNotExist:
            return Response({"error": "Patient not found for the given UHID"}, status=status.HTTP_404_NOT_FOUND)

    except Admission.DoesNotExist:
        return Response({"error": "Admission record not found for the given IP Number"}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": f"An error occurred: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
 
@csrf_exempt
@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def estimate_billing_create(request):
    if request.method == 'POST':
        current_user = request.data.get('auth-user-id', 'system')
        branch_code = request.data.get('auth-branch-code', 'system')
        department_code = request.data.get('auth-department-code', 'system')
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
            request_data['department_code'] = department_code      # ← from auth header

            serializer = EstimateBillingSerializer(data=request_data)
            if serializer.is_valid():
                serializer.save()
                return Response({'message': 'Form data saved successfully!', 'EstBillNo': formatted_bill_no}, status=201)

            return Response(serializer.errors, status=400)


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def estimate_billing_list(request):
    """
    Returns active estimate bills with all filters applied server-side.

    Query params:
      fromDate    : YYYY-MM-DD
      toDate      : YYYY-MM-DD
      billType    : numeric bill_type id  (e.g. 10)
      doctor      : exact doctor name
      uhid        : partial/prefix match
      patientType : "IP" | "OP"  (blank = ALL)
    """

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
        if isinstance(doc, dict):
            return {k: serialize_doc(v) for k, v in doc.items()}
        if isinstance(doc, list):
            return [serialize_doc(i) for i in doc]
        return serialize_val(doc)

    try:
        # ── Read query params ──────────────────────────────────────────────────
        from_date_str  = request.GET.get('fromDate', '').strip()
        to_date_str    = request.GET.get('toDate', '').strip()
        bill_type_param = request.GET.get('billType', '').strip()
        doctor_param   = request.GET.get('doctor', '').strip()
        uhid_param     = request.GET.get('uhid', '').strip()
        patient_type   = request.GET.get('patientType', '').strip()

        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client['HMS']
        estimate_collection = db['hospital_estimatebilling']
        patient_collection  = db['hospital_patient']
        billtype_collection = db['hospital_billtype']

        # ── Build MongoDB query directly (skip ORM entirely) ──────────────────
        query = {"is_active": {"$nin": [False, 0, "false", "False"]}}

        # Date filter on EstBillDate
        if from_date_str and to_date_str:
            try:
                start = datetime.strptime(from_date_str, "%Y-%m-%d")
                end   = datetime.strptime(to_date_str,   "%Y-%m-%d").replace(
                    hour=23, minute=59, second=59, microsecond=999999
                )
                query["EstBillDate"] = {"$gte": start, "$lte": end}
            except ValueError:
                client.close()
                return Response(
                    {"error": "Invalid date format. Use YYYY-MM-DD."},
                    status=400,
                )

        # Bill type filter — match both int and string variants because
        # Django serializers may store bill_type as "10" (str) or 10 (int)
        # depending on the model field type. Use $in to cover both.
        if bill_type_param:
            try:
                int_val = int(bill_type_param)
                query["bill_type"] = {"$in": [int_val, str(int_val)]}
            except (ValueError, TypeError):
                query["bill_type"] = {"$in": [bill_type_param]}

        # Doctor filter — exact match
        if doctor_param:
            query["doctor"] = doctor_param

        # UHID filter — partial / case-insensitive
        if uhid_param:
            query["uhid"] = {"$regex": uhid_param, "$options": "i"}

        # Patient type filter — IP has non-empty ipNumber, OP does not
        if patient_type == "IP":
            query["ipNumber"] = {"$exists": True, "$ne": "", "$nin": [None]}
        elif patient_type == "OP":
            query["$or"] = [
                {"ipNumber": {"$exists": False}},
                {"ipNumber": ""},
                {"ipNumber": None},
            ]

        data = list(estimate_collection.find(query).sort("_id", -1))

        # ── Batch-cache patient details (avoid N+1) ────────────────────────────
        uhids = {doc.get("uhid") for doc in data if doc.get("uhid")}
        patient_cache = {}
        if uhids:
            patients = patient_collection.find(
                {"uhid": {"$in": list(uhids)}},
                {"_id": 0, "uhid": 1, "salutation": 1,
                 "firstName": 1, "lastName": 1, "age": 1, "gender": 1},
            )
            for p in patients:
                patient_cache[p["uhid"]] = p

        # ── Batch-cache bill type names ────────────────────────────────────────
        # bill_type may be stored as int OR string in hospital_estimatebilling
        # depending on Django serializer. Normalise everything to int for lookup.
        bill_type_ids = set()
        for doc in data:
            bt = doc.get("bill_type")
            if bt is not None and bt != "":
                try:
                    bill_type_ids.add(int(bt))
                except (ValueError, TypeError):
                    pass

        bill_type_cache = {}  # keyed by int
        if bill_type_ids:
            bt_docs = billtype_collection.find(
                {"bill_type": {"$in": list(bill_type_ids)}},
                {"_id": 0, "bill_type": 1, "bill_name": 1, "billTypeNo": 1},
            )
            for bt in bt_docs:
                bill_type_cache[int(bt["bill_type"])] = {
                    "bill_name":  bt.get("bill_name", ""),
                    "billTypeNo": bt.get("billTypeNo", ""),
                }

        # ── Enrich each document ───────────────────────────────────────────────
        result = []
        for doc in data:
            # Patient info
            uhid    = doc.get("uhid", "")
            patient = patient_cache.get(uhid, {})
            doc["salutation"] = patient.get("salutation", "")
            doc["firstName"]  = patient.get("firstName", "")
            doc["lastName"]   = patient.get("lastName", "")
            doc["age"]        = patient.get("age", "")
            doc["gender"]     = patient.get("gender", "")

            # Bill type name
            try:
                bt_key = int(doc.get("bill_type", 0))
            except (ValueError, TypeError):
                bt_key = 0
            bt_info = bill_type_cache.get(bt_key, {})
            doc["bill_name"]  = bt_info.get("bill_name", "")
            doc["billTypeNo"] = bt_info.get("billTypeNo", "")

            # Parse item JSON string if needed
            if isinstance(doc.get("item"), str):
                try:
                    doc["item"] = json.loads(doc["item"])
                except json.JSONDecodeError:
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
    """Fetch bill types from hospital_billtype collection"""
    try:
        # Connect to MongoDB
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client['HMS']
        collection = db['hospital_billtype']

        # Fetch all active bill types
        bill_types = list(collection.find(
            {"is_active": True},
            {
                "_id": 0,
                "bill_type": 1,
                "bill_name": 1,
                "billTypeNo": 1,
                "department_code": 1,
                "is_allowDiscount": 1,
            }
        ))
        
        # Close the MongoDB connection
        client.close()

        return JsonResponse({"billTypes": bill_types}, safe=True)
    
    except Exception as e:
        return JsonResponse({
            "error": "An error occurred while fetching bill types",
            "details": str(e)
        }, status=500)
    
@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_packages(request):
    """Fetch all active packages from hospital_package collection"""
    try:
        # Connect to MongoDB
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client['HMS']
        collection = db['hospital_package']

        # Fetch all active packages
        packages = list(collection.find(
            {"is_active": True},
            {
                "_id": 0,
                "packageNo": 1,
                "packageName": 1,
                "department": 1
            }
        ))
        
        # Close the MongoDB connection
        client.close()

        return JsonResponse({"packages": packages}, safe=True)
    
    except Exception as e:
        return JsonResponse({
            "error": "An error occurred while fetching packages",
            "details": str(e)
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
                # Get the price for the specific bill_type
                price = item.get(str(bill_type), "0")
                
                # Only include items that have a price for this bill_type
                if price and price != "0":
                    formatted_items.append({
                        "itemName": item_name,
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
        department_code = request.data.get('auth-department-code', 'system')
        hospital_code = request.data.get('auth-hospital-code', 'system')

        data = {k: v for k, v in request.data.items()
                if not k.startswith('auth-')}

        # ── Normalize item field ───────────────────────────────
        def normalize_item(item):
            if isinstance(item, list):
                return json.dumps(item)
            elif isinstance(item, str):
                try:
                    parsed = json.loads(item)
                    if isinstance(parsed, str):
                        parsed = json.loads(parsed)
                    return json.dumps(parsed)
                except (json.JSONDecodeError, TypeError):
                    return json.dumps([])
            return json.dumps([])

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

            data["lastmodified_by"] = current_user
            data["lastmodified_date"] = timezone.now()
            data["editRemarks"] = edit_remarks   # store flat on the document
            data.pop("investBillNo", None)

            invest_collection.update_one(
                {"_id": existing_record["_id"]},
                {"$set": data}
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
        data["department_code"] = department_code
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
        """Recursively convert MongoDB types to JSON-serializable types."""
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
        else:
            return doc

    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client['HMS']

        collection = db['hospital_investbilling']
        bill_type_collection = db['hospital_billtype']
        patient_collection = db['hospital_patient']

        query = {"is_active": True}

        # ── Date filter ────────────────────────────────────────────────────────
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')

        if start_date and end_date:
            try:
                start = datetime.strptime(start_date, "%Y-%m-%d")
                end = datetime.strptime(end_date, "%Y-%m-%d").replace(
                    hour=23, minute=59, second=59, microsecond=999999
                )
                query["investBillDate"] = {"$gte": start, "$lte": end}
            except ValueError:
                return JsonResponse({"error": "Invalid date format. Use YYYY-MM-DD."}, status=400)

        # ── Bill type filter ───────────────────────────────────────────────────
        bill_type_param = request.GET.get('billType')
        if bill_type_param:
            try:
                query["bill_type"] = int(bill_type_param)
            except (ValueError, TypeError):
                query["bill_type"] = bill_type_param

        # ── Doctor filter ──────────────────────────────────────────────────────
        doctor_param = request.GET.get('doctor')
        if doctor_param:
            query["doctor"] = doctor_param

        # ── UHID filter (partial / prefix match) ──────────────────────────────
        uhid_param = request.GET.get('uhid')
        if uhid_param:
            query["uhid"] = {"$regex": uhid_param, "$options": "i"}

        # ── Patient type filter (IP / OP) ──────────────────────────────────────
        patient_type_param = request.GET.get('patientType')
        if patient_type_param == 'IP':
            # IP patients have a non-empty ipNumber
            query["ipNumber"] = {"$exists": True, "$ne": "", "$nin": [None]}
        elif patient_type_param == 'OP':
            # OP patients have no ipNumber or it is blank/null
            query["$or"] = [
                {"ipNumber": {"$exists": False}},
                {"ipNumber": ""},
                {"ipNumber": None},
            ]

        data = list(collection.find(query))

        # ── Cache bill types to avoid repeated DB calls ────────────────────────
        bill_type_cache = {}

        result = []
        for doc in data:

            # Resolve bill_name using bill_type as integer
            bill_type = doc.get("bill_type")
            if bill_type:
                if bill_type not in bill_type_cache:
                    try:
                        bill_type_doc = bill_type_collection.find_one(
                            {"bill_type": int(bill_type)},
                            {"_id": 0, "bill_name": 1, "billTypeNo": 1}
                        )
                        if bill_type_doc:
                            bill_type_cache[bill_type] = {
                                "bill_name": bill_type_doc.get("bill_name", ""),
                                "billTypeNo": bill_type_doc.get("billTypeNo", ""),
                            }
                        else:
                            bill_type_cache[bill_type] = {"bill_name": "", "billTypeNo": ""}
                    except (ValueError, TypeError):
                        bill_type_cache[bill_type] = {"bill_name": "", "billTypeNo": ""}

                doc["bill_name"] = bill_type_cache[bill_type]["bill_name"]
                doc["billTypeNo"] = bill_type_cache[bill_type]["billTypeNo"]
            else:
                doc["bill_name"] = ""
                doc["billTypeNo"] = ""

            # Parse item if it's a JSON string
            if isinstance(doc.get("item"), str):
                try:
                    doc["item"] = json.loads(doc["item"])
                except json.JSONDecodeError:
                    doc["item"] = []

            # Fetch patient details
            uhid = doc.get("uhid")
            if uhid:
                patient = patient_collection.find_one({"uhid": uhid})
                if patient:
                    doc["salutation"] = patient.get("salutation", "")
                    doc["firstName"] = patient.get("firstName", "")
                    doc["lastName"] = patient.get("lastName", "")
                    doc["age"] = patient.get("age", "")
                    doc["gender"] = patient.get("gender", "")
                else:
                    doc["salutation"] = doc["firstName"] = doc["lastName"] = doc["age"] = doc["gender"] = ""

            result.append(serialize_doc(doc))

        client.close()

        result.sort(key=lambda x: x.get("investBillDate", ""), reverse=True)

        return JsonResponse(result, safe=False)

    except Exception as e:
        return JsonResponse({"error": "Failed to generate billing report", "details": str(e)}, status=500)
    

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
    """
    Returns Deleted or Edited bills for the Department Bill Update/Delete Report.

    Query params:
      report_type : "deleted" | "edited"   (required)
      start_date  : YYYY-MM-DD
      end_date    : YYYY-MM-DD
    """

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

        # HMS db — billing data
        hms_db               = client['HMS']
        collection           = hms_db['hospital_investbilling']
        bill_type_collection = hms_db['hospital_billtype']

        # Global db — employee profiles for name resolution
        global_db            = client['Global']
        profile_collection   = global_db['backend_diagnostics_profile']

        # ── Build query ────────────────────────────────────────────────────────
        if report_type == 'deleted':
            query = {
                "is_active": False,
                "deletedAt": {"$exists": True},
            }
            date_field      = "deletedAt"
            actor_id_field  = "deletedBy"       # employeeId stored here
            actor_name_out  = "deletedByName"   # resolved name written here
        else:
            query = {
                "is_active": True,
                "lastmodified_by": {"$ne": None, "$exists": True},
                "editRemarks": {"$exists": True},
            }
            date_field      = "lastmodified_date"
            actor_id_field  = "lastmodified_by"
            actor_name_out  = "lastmodified_by_name"

        # ── Date filter ────────────────────────────────────────────────────────
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

        # ── Collect unique employee IDs to resolve in one batch ────────────────
        # Avoids N separate DB calls — fetch all needed profiles at once.
        actor_ids = {
            str(doc.get(actor_id_field, "")).strip()
            for doc in data
            if doc.get(actor_id_field)
        }

        employee_cache = {}  # { "60002": "Najma", ... }
        if actor_ids:
            profiles = profile_collection.find(
                {"employeeId": {"$in": list(actor_ids)}},
                {"_id": 0, "employeeId": 1, "employeeName": 1},
            )
            for p in profiles:
                employee_cache[str(p.get("employeeId", "")).strip()] = p.get("employeeName", "")

        # ── Cache bill type names ──────────────────────────────────────────────
        bill_type_cache = {}

        result = []
        for doc in data:
            # Resolve bill type name
            bill_type = doc.get("bill_type")
            if bill_type:
                if bill_type not in bill_type_cache:
                    try:
                        bt_doc = bill_type_collection.find_one(
                            {"bill_type": int(bill_type)},
                            {"_id": 0, "bill_name": 1, "billTypeNo": 1},
                        )
                        bill_type_cache[bill_type] = {
                            "bill_name":  bt_doc.get("bill_name", "")  if bt_doc else "",
                            "billTypeNo": bt_doc.get("billTypeNo", "") if bt_doc else "",
                        }
                    except (ValueError, TypeError):
                        bill_type_cache[bill_type] = {"bill_name": "", "billTypeNo": ""}

                doc["bill_name"]  = bill_type_cache[bill_type]["bill_name"]
                doc["billTypeNo"] = bill_type_cache[bill_type]["billTypeNo"]
            else:
                doc["bill_name"]  = ""
                doc["billTypeNo"] = ""

            # Resolve actor name from employee cache
            actor_id = str(doc.get(actor_id_field, "")).strip()
            doc[actor_name_out] = employee_cache.get(actor_id, actor_id or "")
            # ^ falls back to the raw ID if no profile found, never returns blank

            result.append(serialize_doc(doc))

        client.close()

        result.sort(key=lambda x: x.get(date_field, ""), reverse=True)

        return JsonResponse(result, safe=False)

    except Exception as e:
        return JsonResponse(
            {"error": "Failed to fetch report", "details": str(e)},
            status=500,
        )
    