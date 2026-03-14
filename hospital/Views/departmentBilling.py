from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from pyauth.auth import HasRoleAndDataPermission
from ..models import Patient,EstimateBilling,Admission
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
        return Response(serializer.data)
    except Patient.DoesNotExist:
        return Response({"error": "Patient not found"}, status=404)

  
@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def ip_patient_detail_by_ipNumber(request, ipNumber):
    try:
        # Get admission details
        admission = Admission.objects.get(ipNumber=ipNumber)
        
        # Get patient details using UHID from admission
        try:
            patient = Patient.objects.get(uhid=admission.uhid)
            
            # Combine data from both models
            response_data = {
                # From Admission model
                'ipNumber': admission.ipNumber,
                'uhid': admission.uhid,
                'roomNo': admission.roomNo,
                'admissionDate': admission.admissionDate.strftime("%Y-%m-%d") if admission.admissionDate else None,
                'admissionTime': admission.admissionDate.strftime("%H:%M") if admission.admissionDate else None,
                'admittingDoctor': admission.admittingDoctor,
                
                # From Patient model
                'salutation': patient.salutation if hasattr(patient, 'salutation') else '',
                'firstName': patient.firstName,
                'lastName': patient.lastName,
                'age': patient.age,
                'gender': patient.gender,
                'area': patient.area,
                'city': patient.city,
                'state': patient.state,
            }
            
            return Response(response_data, status=status.HTTP_200_OK)
            
        except Patient.DoesNotExist:
            return Response({
                "error": "Patient not found for the given UHID"
            }, status=status.HTTP_404_NOT_FOUND)
            
    except Admission.DoesNotExist:
        return Response({
            "error": "Admission record not found for the given IP Number"
        }, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({
            "error": f"An error occurred: {str(e)}"
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)  
    
 
@csrf_exempt
@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def estimate_billing_create(request):
    if request.method == 'POST':
        current_user = request.data.get('auth-user-id', 'system')

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

            serializer = EstimateBillingSerializer(data=request_data)
            if serializer.is_valid():
                serializer.save()
                return Response({'message': 'Form data saved successfully!', 'EstBillNo': formatted_bill_no}, status=201)

            return Response(serializer.errors, status=400)


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def estimate_billing_list(request):
    try:
        estimates = EstimateBilling.objects.all().order_by('-id')

        active_estimates = [
            e for e in estimates
            if e.is_active not in [False, 0, "false", "False", None]
        ]

        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client['HMS']
        patient_collection = db['hospital_patient']
        billtype_collection = db['hospital_billtype']  # ✅ Add this

        serializer = EstimateBillingSerializer(active_estimates, many=True)
        estimate_data = serializer.data

        for estimate in estimate_data:
            # Enrich patient details
            uhid = estimate.get("uhid")
            if uhid:
                patient = patient_collection.find_one({"uhid": uhid})
                if patient:
                    estimate["salutation"] = patient.get("salutation", "")
                    estimate["firstName"] = patient.get("firstName", "")
                    estimate["lastName"] = patient.get("lastName", "")
                    estimate["age"] = patient.get("age", "")
                    estimate["gender"] = patient.get("gender", "")
                else:
                    estimate["salutation"] = ""
                    estimate["firstName"] = ""
                    estimate["lastName"] = ""
                    estimate["age"] = ""
                    estimate["gender"] = ""

            # ✅ Enrich bill_name from hospital_billtype
            bill_type = estimate.get("bill_type")
            if bill_type:
                bill_type_doc = billtype_collection.find_one(
                    {"bill_type": int(bill_type)},
                    {"_id": 0, "bill_name": 1, "billTypeNo": 1}
                )
                if bill_type_doc:
                    estimate["bill_name"] = bill_type_doc.get("bill_name", "")
                    estimate["billTypeNo"] = bill_type_doc.get("billTypeNo", "")
                else:
                    estimate["bill_name"] = ""
                    estimate["billTypeNo"] = ""

        client.close()

        return Response(estimate_data)

    except Exception as e:
        return Response({"error": "Failed to fetch estimate billing list", "details": str(e)}, status=500)


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

            data["lastmodified_by"] = current_user
            data["lastmodified_date"] = timezone.now()
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

        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')

        if start_date and end_date:
            try:
                start = datetime.strptime(start_date, "%Y-%m-%d")
                end = datetime.strptime(end_date, "%Y-%m-%d")
                query["EstBillDate"] = {"$gte": start, "$lte": end}
            except ValueError:
                return JsonResponse({"error": "Invalid date format. Use YYYY-MM-DD."}, status=400)

        data = list(collection.find(query))

        # ✅ Cache bill types to avoid repeated DB calls
        bill_type_cache = {}

        result = []
        for doc in data:

            # ✅ Resolve bill_name using bill_type as integer (same as estimate_billing_list)
            bill_type = doc.get("bill_type")
            if bill_type:
                if bill_type not in bill_type_cache:
                    try:
                        bill_type_doc = bill_type_collection.find_one(
                            {"bill_type": int(bill_type)},       # ✅ query by numeric bill_type field
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

            # Serialize all MongoDB types recursively
            result.append(serialize_doc(doc))

        client.close()

        result.sort(key=lambda x: x.get("EstBillDate", ""), reverse=True)

        return JsonResponse(result, safe=False)

    except Exception as e:
        return JsonResponse({"error": "Failed to generate billing report", "details": str(e)}, status=500)
    

@api_view(['PATCH'])
@csrf_exempt
@permission_classes([HasRoleAndDataPermission])
def delete_bill_view(request):
    try:
        bill_id = request.data.get('billId')
        bill_type = request.data.get('billType')
        employeeId = request.data.get('auth-user-id', "system")

        if not bill_id or not bill_type:
            return JsonResponse({'error': 'Missing billId or billType'}, status=400)

        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client['HMS']
        collection = db[bill_type]

        # Soft delete: set is_active to False
        result = collection.update_one(
            {"_id": ObjectId(bill_id)},
            {
                "$set": {
                    "is_active": False,
                    "deletedBy": employeeId,
                    "deletedAt": datetime.now()
                }
            }
        )

        client.close()

        if result.matched_count == 0:
            return JsonResponse({'error': 'Bill not found'}, status=404)

        return JsonResponse({'message': 'Bill marked as inactive successfully'}, status=200)

    except Exception as e:
        return JsonResponse({'error': 'Failed to update bill', 'details': str(e)}, status=500)
