from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from ..models import Summary
from ..serializers import SummarySerializer
from django.shortcuts import render
from rest_framework.response import Response
from django.http import JsonResponse
from rest_framework import status
from pymongo import MongoClient
from django.utils.timezone import now
from rest_framework.parsers import MultiPartParser, FormParser
from bson import Decimal128
from rest_framework.decorators import api_view, permission_classes
from django.views.decorators.csrf import csrf_exempt
from pymongo import MongoClient
import os, json
from ..serializers import  Patient,PatientSerializer
from ..models import CTReport, MRIReport, USGReport, XRayReport
from django.views.decorators.http import require_http_methods
import logging
logger = logging.getLogger(__name__)
from pymongo import MongoClient
from datetime import datetime
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from pyauth.auth import HasRoleAndDataPermission
import json
from urllib.parse import unquote
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from pymongo import MongoClient
import os
from datetime import datetime
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status



@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_summaries(request):
    # Get all summaries first (without filter to avoid the bug)
    all_summaries = Summary.objects.all()
    
    # Filter in Python
    active_summaries = [s for s in all_summaries if s.is_active == True]
    
    serializer = SummarySerializer(active_summaries, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def create_summary(request):
    serializer = SummarySerializer(data=request.data)
    if serializer.is_valid():
        ip_no = serializer.validated_data.get('ipNo')
        
        # Check if summary already exists for this ipNo
        if Summary.objects.filter(ipNo=ip_no).exists():
            return Response(
                {"error": f"Summary already exists for ipNo: {ip_no}"},
                status=status.HTTP_409_CONFLICT
            )
        
        # Get user ID from request
        created_by = request.data.get('auth-user-id', "system")
        
        # Pass created_by and created_date to save()
        serializer.save(
            created_by=created_by,
            created_date=datetime.utcnow()
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@require_http_methods(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_patient_investigations(request, ip_no):
    """
    Fetch all investigation reports (CT, MRI, USG, XRay) for a specific patient IP number
    """
    if not ip_no:
        return JsonResponse({'error': 'Patient IP number is required'}, status=400)
    
    try:
        # IMPORTANT CHANGE: Removed the approve=True filter to show all reports
        ct_reports = CTReport.objects.filter(ipNumber=ip_no).values(
            'investigation', 'impression', 'is_approved'
        )
        
        mri_reports = MRIReport.objects.filter(ipNumber=ip_no).values(
            'investigation', 'impression', 'is_approved'
        )
        
        usg_reports = USGReport.objects.filter(ipNumber=ip_no).values(
            'investigation', 'impression', 'is_approved'
        )
        
        xray_reports = XRayReport.objects.filter(ipNumber=ip_no).values(
            'investigation', 'impression', 'is_approved'
        )
        
        # Combine all reports with type information
        all_reports = []
        
        for report in ct_reports:
            all_reports.append({
                'reportType': 'CT Scan',
                'investigation': report.get('investigation', ''),
                'impression': report.get('impression', ''),
                'is_approved': report.get('is_approved', True)  # Include approval status
            })
            
        for report in mri_reports:
            all_reports.append({
                'reportType': 'MRI',
                'investigation': report.get('investigation', ''),
                'impression': report.get('impression', ''),
                'is_approved': report.get('is_approved', True)
            })
            
        for report in usg_reports:
            all_reports.append({
                'reportType': 'USG',
                'investigation': report.get('investigation', ''),
                'impression': report.get('impression', ''),
                'is_approved': report.get('is_approved', True)
            })
            
        for report in xray_reports:
            all_reports.append({
                'reportType': 'X-Ray',
                'investigation': report.get('investigation', ''),
                'impression': report.get('impression', ''),
                'is_approved': report.get('is_approved', True)
            })
        
        # If no reports found, return empty list with 200 status
        if not all_reports:
            logger.info(f"No investigation reports found for patient IP: {ip_no}")
            return JsonResponse([], safe=False)
        
        logger.info(f"Found {len(all_reports)} reports for patient IP: {ip_no}")
        return JsonResponse(all_reports, safe=False)
        
    except Exception as e:
        logger.error(f"Error fetching patient investigations for IP {ip_no}: {str(e)}")
        return JsonResponse({'error': 'Failed to fetch investigations'}, status=500)
    

@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def approve_summary(request, ip_no):
    # MongoDB connection setup
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    db = client['HMS']
    collection = db['hospital_summary']  # Changed collection name to 'hospital_summary'
    try:
        # Get the user who is performing the soft delete (if available)
        created_by = request.data.get('auth-user-id', "system")

        
        # Find the summary by IP number and update
        result = collection.update_one(
            {"ipNo": ip_no},  # Query to find the document by IP No
            {"$set": {
                "approve": True,
                "approved_by": created_by,
                "approve_time": datetime.now().isoformat()  # Set the current time
            }}
        )
        
        # Check if the document was updated
        if result.matched_count > 0:
            return Response({"message": "Summary approved successfully"}, status=status.HTTP_200_OK)
        else:
            return Response({"error": "Summary not found"}, status=status.HTTP_404_NOT_FOUND)
    
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['PATCH'])  # Changed from DELETE to PATCH
@permission_classes([HasRoleAndDataPermission])
def delete_summary(request, ip_no):
    # MongoDB connection setup
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    db = client['HMS']
    collection = db['hospital_summary']
    
    try:
        # Get the user who is performing the soft delete (if available)
        created_by = request.data.get('auth-user-id', "system")

        
        # Update the document to set is_active to False
        result = collection.update_one(
            {"ipNo": ip_no, "is_active": True},  # Only update if currently active
            {
                "$set": {
                    "is_active": False,
                    "deleted_by": created_by,
                    "deleted_date": datetime.now()
                }
            }
        )
        
        # Check if the document was updated
        if result.matched_count > 0:
            return Response(
                {"message": "Summary deleted successfully"}, 
                status=status.HTTP_200_OK
            )
        else:
            return Response(
                {"error": "Summary not found or already deleted"}, 
                status=status.HTTP_404_NOT_FOUND
            )
    
    except Exception as e:
        return Response(
            {"error": str(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    finally:
        client.close()  # Always close the MongoDB connection
    

from urllib.parse import unquote

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_editsummary(request, ip_no):
    # MongoDB connection setup
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    db = client['HMS']
    collection = db['hospital_summary']  # Changed collection name to 'hospital_summary'
    decoded_ip_no = unquote(ip_no)  # Decode the IP No
    summary = collection.find_one({"ipNo": decoded_ip_no})
    # Rest of the logic...

    try:
        # Find the document by IP number
        summary = collection.find_one({"ipNo": ip_no})
        
        if summary:
            summary['_id'] = str(summary['_id'])  # Convert ObjectId to string
            return Response(summary, status=status.HTTP_200_OK)
        else:
            return Response({"error": "Summary not found"}, status=status.HTTP_404_NOT_FOUND)
    
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def update_summary_fields(request, ip_no):
    # MongoDB connection setup
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    db = client['HMS']
    collection = db['hospital_summary']
    
    try:
        decoded_ip_no = unquote(ip_no)  # Decode the IP No
        data = request.data.copy()  # Create a copy to avoid modifying original request data
        created_by = request.data.get('auth-user-id', "system")

        # Only include the fields you want to store
        data = {k: v for k, v in request.data.items() 
                if not k.startswith('auth-')}


        # Check if 'fieldsData' exists and is non-empty
        if 'fieldsData' not in data or not data['fieldsData']:
            return Response(
                {"error": "No fieldsData provided"}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        # Convert fieldsData to JSON string if it's a dict/object
        if isinstance(data['fieldsData'], dict):
            data['fieldsData'] = json.dumps(data['fieldsData'])
        
        # Add lastmodified_date timestamp
        from datetime import datetime
        data['lastmodified_date'] = datetime.utcnow()  # Store as datetime object, not string
        data['lastmodified_by'] = created_by

        # Process the data and update the document in the database
        updated_summary = collection.update_one(
            {"ipNo": decoded_ip_no},
            {"$set": data}
        )

        if updated_summary.matched_count > 0:
            return Response(
                {"message": "Summary updated successfully!"}, 
                status=status.HTTP_200_OK
            )
        else:
            return Response(
                {"error": "Summary not found"}, 
                status=status.HTTP_404_NOT_FOUND
            )

    except json.JSONDecodeError as e:
        return Response(
            {"error": f"Invalid JSON format in fieldsData: {str(e)}"}, 
            status=status.HTTP_400_BAD_REQUEST
        )
    except Exception as e:
        return Response(
            {"error": str(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    finally:
        client.close()  # Always close the MongoDB connection

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_printsummary(request, ip_no):
    decoded_ip_no = unquote(ip_no)  # Decode the IP No
    
    try:
        # MongoDB connection
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        
        # HMS database
        hms_db = client['HMS']
        
        # Get hospital summary from hospital_summary collection
        hospital_summary_collection = hms_db['hospital_summary']
        summary = hospital_summary_collection.find_one({"ipNo": decoded_ip_no})
        
        if not summary:
            client.close()
            return JsonResponse({'error': 'Hospital summary not found for the given IP number'}, status=404)
        
        # Convert ObjectId to string
        summary['_id'] = str(summary['_id'])
        
        # Initialize test details
        summary['testdetails'] = []
        summary['barcode'] = None
        summary['investBillNo'] = None
        
        # === STEP 1: Get Lab Test Record from HMS database ===
        # Access 'Lab Test' collection in HMS database
        lab_test_collection = hms_db['Lab Test']
        
        # The field is 'ipNumber' not 'ipNo'
        lab_test_record = lab_test_collection.find_one({"ipNumber": decoded_ip_no})
        
        if not lab_test_record:
            # Return summary without test details if no lab test found
            client.close()
            return JsonResponse(summary, safe=False)
        
        # Get investBillNo from lab test record
        invest_bill_no = lab_test_record.get('investBillNo')
        if not invest_bill_no:
            # Return summary without test details
            client.close()
            return JsonResponse(summary, safe=False)
        
        summary['investBillNo'] = invest_bill_no
        
        # === STEP 2: Get Barcode from Diagnostics database ===
        diagnostics_db = client['Diagnostics']
        barcode_collection = diagnostics_db['core_HMSbarcode']
        
        # The field in core_HMSbarcode is 'billnumber' not 'investBillNo'
        barcode_record = barcode_collection.find_one({"billnumber": invest_bill_no})
        
        if not barcode_record:
            # Return summary without test details
            client.close()
            return JsonResponse(summary, safe=False)
        
        barcode = barcode_record.get('barcode')
        if not barcode:
            # Return summary without test details
            client.close()
            return JsonResponse(summary, safe=False)
        
        summary['barcode'] = barcode
        
        # === STEP 3: Get Test Values from Diagnostics database ===
        testvalue_collection = diagnostics_db['core_testvalue']
        test_value_records = list(testvalue_collection.find({"barcode": barcode}))
        
        if not test_value_records:
            # Return summary without test details
            client.close()
            return JsonResponse(summary, safe=False)
        
        # === STEP 4: Process Test Details ===
        test_details = []
        for test_value in test_value_records:
            try:
                # Parse testdetails JSON
                testdetails_raw = test_value.get('testdetails', '[]')
                testvalue_details = json.loads(testdetails_raw) if isinstance(testdetails_raw, str) else testdetails_raw
                
                if not isinstance(testvalue_details, list):
                    continue
                
                # Process each test
                for test_detail in testvalue_details:
                    testname = test_detail.get("testname")
                    if not testname:
                        continue
                    
                    # Build test detail object
                    test_response = {
                        "department": test_detail.get("department", ""),
                        "NABL": test_detail.get("NABL", ""),
                        "testname": testname,
                        "verified_by": test_detail.get("verified_by", ""),
                        "approve_by": test_detail.get("approve_by", ""),
                        "approve_time": test_detail.get("approve_time", ""),
                        "remarks": test_detail.get("remarks", "")
                    }
                    
                    # Check if test has parameters
                    if test_detail.get("parameters"):
                        # Test with parameters - add parameters array
                        processed_parameters = []
                        for param in test_detail.get("parameters", []):
                            processed_param = {
                                "name": param.get("name", ""),
                                "value": param.get("value", ""),
                                "unit": param.get("unit", ""),
                                "specimen_type": param.get("specimen_type", ""),
                                "reference_range": param.get("reference_range", ""),
                                "method": param.get("method", ""),
                                "sub_title": param.get("sub_title", "")
                            }
                            processed_parameters.append(processed_param)
                        
                        test_response["parameters"] = processed_parameters
                    else:
                        # Test without parameters - add direct values
                        test_response.update({
                            "method": test_detail.get("method", ""),
                            "specimen_type": test_detail.get("specimen_type", ""),
                            "value": test_detail.get("value", ""),
                            "unit": test_detail.get("unit", ""),
                            "reference_range": test_detail.get("reference_range", "")
                        })
                    
                    test_details.append(test_response)
                    
            except (json.JSONDecodeError, AttributeError) as e:
                continue
        
        # Add test details to summary response
        summary['testdetails'] = test_details
        
        # Close MongoDB connection
        client.close()
        
        return JsonResponse(summary, safe=False)
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)