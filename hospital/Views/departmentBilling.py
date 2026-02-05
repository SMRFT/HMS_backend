from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from pyauth.auth import HasRoleAndDataPermission
from ..models import Patient,EstimateBilling,Admission
from ..serializers import PatientSerializer,EstimateBillingSerializer,AdmissionSerializer
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



@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def op_patient_detail_by_uhid(request, uhid):
    try:
        patient = Patient.objects.get(uhid=uhid)
        serializer = PatientSerializer(patient)
        return Response(serializer.data)
    except Patient.DoesNotExist:
        return Response({"error": "Patient not found"}, status=404)

  
from django.db.models import Q
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status

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
                'admissionDate': admission.admissionDate,
                'admissionTime': admission.time if hasattr(admission, 'time') else None,
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
        with transaction.atomic():  # Ensures atomic operation
            last_bill = EstimateBilling.objects.select_for_update().order_by('-id').first()

            if last_bill and last_bill.EstBillNo:
                last_number = int(last_bill.EstBillNo)
                next_number = last_number + 1
            else:
                next_number = 1  # Start from 000001 if no previous bill exists

            # Format EstBillNo as a 6-digit number (e.g., 000001, 000002, etc.)
            formatted_bill_no = f"{next_number:06d}"

            # Ensure uniqueness
            while EstimateBilling.objects.filter(EstBillNo=formatted_bill_no).exists():
                next_number += 1
                formatted_bill_no = f"{next_number:06d}"

            # Create a mutable copy of request data
            request_data = request.data.copy()
            request_data['EstBillNo'] = formatted_bill_no

            serializer = EstimateBillingSerializer(data=request_data)
            if serializer.is_valid():
                serializer.save()
                return Response({'message': 'Form data saved successfully!', 'EstBillNo': formatted_bill_no}, status=201)

            return Response(serializer.errors, status=400)

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def estimate_billing_list(request):
    estimates = EstimateBilling.objects.all().order_by('-id')

    # Python-side filtering (Djongo-safe)
    active_estimates = [
        e for e in estimates
        if e.is_active not in [False, 0, "false", "False", None]
    ]

    serializer = EstimateBillingSerializer(active_estimates, many=True)
    return Response(serializer.data)



@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_bill_types(request):
    try:
        # Connect to MongoDB
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client['HMS']
        collection = db['hospital_investigationprice']

        # Fetch all documents
        all_bills = list(collection.find({}, {"_id": 0}))
        
        # Compile all items across all bill types
        all_items = []
        for bill in all_bills:
            bill_type = bill.get("BillType", "Unknown")
            items = bill.get("Items", [])
            
            # Add bill type to each item for context
            for item in items:
                item['billType'] = bill_type
            
            all_items.extend(items)

        # Close the MongoDB connection
        client.close()

        # Return JsonResponse with all items
        return JsonResponse({"items": all_items}, safe=True)
    
    except Exception as e:
        # Handle any errors that might occur
        return JsonResponse({
            "error": "An error occurred while fetching bill types",
            "details": str(e)
        }, status=500)

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_lab_tests(request):
    """Fetch lab tests from Diagnostics database"""
    try:
        bill_type = request.GET.get('billType', '')
        
        # Connect to MongoDB Diagnostics database
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client['Diagnostics']
        collection = db['core_testdetails']
        
        # Fetch active tests
        tests = list(collection.find(
            {"is_active": True},
            {
                "test_id": 1,
                "test_name": 1,
                "SH_Rate": 1,
                "Credit_Rate": 1,
                "_id": 0
            }
        ))
        
        client.close()
        
        return Response({"success": True, "data": tests}, status=drf_status.HTTP_200_OK)
        
    except Exception as e:
        return Response({
            "success": False,
            "error": str(e)
        }, status=drf_status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def invest_billing_create(request):
    try:
        # Get current user for audit fields from request.data
        current_user = request.data.get('auth-user-id', "system")
        
        # Create a clean data dictionary without auth fields
        data = {k: v for k, v in request.data.items() 
                if not k.startswith('auth-')}

        # Extract EstBillNo from request data for deletion
        est_bill_no = data.get("EstBillNo")
        if est_bill_no:
            mongo_client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
            mongo_db = mongo_client['HMS']
            estimate_collection = mongo_db['hospital_estimatebilling']  # ⚠ exact collection name

            estimate_collection.update_one(
                {"EstBillNo": est_bill_no, "is_active": True},
                {
                    "$set": {
                        "is_active": False,
                        "lastmodified_by": current_user,
                        "lastmodified_date": timezone.now()
                    }
                }
            )

            mongo_client.close()

        # Remove EstBillNo and EstBillDate from new data before storing
        data.pop("EstBillNo", None)
        data.pop("EstBillDate", None)

        # Extract the billType to determine the collection name
        bill_type = data.get("billType")
        if not bill_type:
            return Response({"error": "BillType is required"}, status=drf_status.HTTP_400_BAD_REQUEST)

        # Connect to MongoDB
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client['HMS']
        collection = db[bill_type]

        # Check if this is an UPDATE operation (has investBillNo in data)
        existing_invest_bill_no = data.get("investBillNo")
        
        if existing_invest_bill_no:
            # This is an UPDATE operation
            existing_record = collection.find_one({"investBillNo": existing_invest_bill_no})
            
            if existing_record:
                # Convert `item` to a JSON string if it exists
                if "item" in data:
                    data["item"] = json.dumps(data["item"])
                
                # Add audit fields for update
                data["lastmodified_by"] = current_user
                data["lastmodified_date"] = timezone.now()
                
                # Update the existing record
                collection.update_one(
                    {"_id": existing_record["_id"]},
                    {"$set": data}
                )
                
                client.close()
                return Response({"message": "Billing updated successfully!", "investBillNo": existing_invest_bill_no}, status=drf_status.HTTP_200_OK)
            else:
                client.close()
                return Response({"error": f"No record found with investBillNo: {existing_invest_bill_no}"}, status=drf_status.HTTP_404_NOT_FOUND)
        
        # If no investBillNo provided, create a NEW bill
        # Get the current date to determine the financial year
        today = datetime.today()
        current_year = today.year
        next_year = current_year + 1

        # Check if we are in the previous financial year
        if today.month < 4:  # If it's Jan, Feb, or March
            financial_year = f"{(current_year-1) % 100}{current_year % 100}"
        else:  # If it's April or later
            financial_year = f"{current_year % 100}{next_year % 100}"

        # Find the latest bill number for the current financial year
        last_bill = collection.find_one(
            {"investBillNo": {"$regex": f"^{financial_year}/"}},
            sort=[("investBillNo", -1)]
        )

        if last_bill:
            try:
                last_number = int(last_bill["investBillNo"].split("/")[-1])
            except ValueError:
                last_number = 0
            next_number = last_number + 1
        else:
            next_number = 1

        # Format the new bill number as "2526/000001"
        invest_bill_no = f"{financial_year}/{next_number:06d}"

        # Convert `item` to a JSON string
        if "item" in data:
            data["item"] = json.dumps(data["item"])

        # Add the new investBillNo to the data
        data["investBillNo"] = invest_bill_no

        # Add audit fields for new record
        data["created_by"] = current_user
        data["created_date"] = timezone.now()
        data["is_active"] = True 

        # Insert the data into the appropriate collection
        collection.insert_one(data)

        # Close the MongoDB connection
        client.close()

        return Response({"message": "Billing saved successfully!", "investBillNo": invest_bill_no}, status=drf_status.HTTP_201_CREATED)

    except Exception as e:
        traceback.print_exc()  # 🔥 THIS WILL SHOW REAL ERROR IN CONSOLE
        return Response(
            {"error": "Billing failed", "details": repr(e)},
            status=500
        )


from django.http import JsonResponse
from pymongo import MongoClient
from datetime import datetime
import json  # Import JSON library to parse the string
from rest_framework.decorators import api_view

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def billing_report_view(request):
    try:
        # Connect to MongoDB
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client['HMS']

        # Define bill types (collection names)
        bill_types = ['CT Scan', 'Lab Test (SH)', 'Lab Test (CREDIT)', 'Scanning', 'X-Ray']  # Add all your bill types here

        # Optional filtering (e.g., by date range)
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')

        result = []

        for bill_type in bill_types:
            collection = db[bill_type]
            query = {}

            # Apply date range filtering if provided
            if start_date and end_date:
                try:
                    start = datetime.strptime(start_date, "%Y-%m-%d")
                    end = datetime.strptime(end_date, "%Y-%m-%d")
                    query["billDate"] = {"$gte": start, "$lte": end}
                except ValueError:
                    return JsonResponse({"error": "Invalid date format. Use YYYY-MM-DD."}, status=400)

            # Fetch data from the collection
            data = list(collection.find(query))
            for doc in data:
                doc["_id"] = str(doc["_id"])  # Convert ObjectId to string
                doc["billType"] = bill_type   # Add billType field for clarity

                # Check if 'item' is a JSON string and convert it into an array
                if isinstance(doc.get("item"), str):
                    try:
                        doc["item"] = json.loads(doc["item"])  # Convert string to list (if it's a valid JSON string)
                    except json.JSONDecodeError:
                        doc["item"] = []  # If it's not a valid JSON string, default to empty list

            result.extend(data)

        client.close()

        # Sort the combined result by billDate (if available)
        result.sort(key=lambda x: x.get("billDate", ""), reverse=True)

        return JsonResponse(result, safe=False)

    except Exception as e:
        return JsonResponse({"error": "Failed to generate billing report", "details": str(e)}, status=500)



@api_view(['DELETE'])
@csrf_exempt
@permission_classes([HasRoleAndDataPermission])
def delete_bill_view(request):
    try:
        bill_id = request.data.get('billId')
        bill_type = request.data.get('billType')

        if not bill_id or not bill_type:
            return JsonResponse({'error': 'Missing billId or billType'}, status=400)

        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client['HMS']
        collection = db[bill_type]
        recycle_collection = db['RecycleBin']

        # Find the bill
        bill = collection.find_one({"_id": ObjectId(bill_id)})
        if not bill:
            return JsonResponse({'error': 'Bill not found'}, status=404)

        # Insert into RecycleBin
        bill['deletedAt'] = datetime.now()
        recycle_collection.insert_one(bill)

        # Delete from original collection
        collection.delete_one({"_id": ObjectId(bill_id)})

        client.close()
        return JsonResponse({'message': 'Bill deleted and moved to recycle bin'}, status=200)

    except Exception as e:
        return JsonResponse({'error': 'Failed to delete bill', 'details': str(e)}, status=500)
