from rest_framework.decorators import api_view, permission_classes
from pyauth.auth import HasRoleAndDataPermission
from django.shortcuts import render
from django.http import JsonResponse
from rest_framework import status
from pymongo import MongoClient
from django.utils.timezone import now
from django.views.decorators.csrf import csrf_exempt
import os, json
import logging
logger = logging.getLogger(__name__)
from ..models import CTReport, MRIReport, USGReport, XRayReport,Patient 
from ..serializers import MRIReportSerializer,XRayReportSerializer,USGReportSerializer 
from datetime import datetime, timedelta

# View to list all CT investigations
@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_ct_investigations(request):
    # MongoDB connection setup
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    db = client['HMS']
    ct_collection = db['CT Scan']
    ct_report_collection = db['hospital_ctreport']
    
    # Get all active MRI records
    ct_scans = list(ct_collection.find({'is_active': True}, {'_id': 0}))
    
    # Get only NON-DELETED reports
    existing_reports = list(ct_report_collection.find(
        {'is_deleted': {'$ne': True}},  # Only get reports where is_deleted is not True
        {'investBillNo': 1, 'investigation': 1, '_id': 0}
    ))
    
    # Create a set of (investBillNo, investigation) tuples for quick lookup
    existing_combinations = set()
    for report in existing_reports:
        invest_bill = report.get('investBillNo')
        investigation = report.get('investigation')
        if invest_bill and investigation:
            existing_combinations.add((invest_bill, investigation))
    
    # Filter investigations
    filtered_investigations = []
    
    for scan in ct_scans:
        invest_bill_no = scan.get('investBillNo')
        items = json.loads(scan.get('item', '[]'))
        
        # Skip if no investBillNo
        if not invest_bill_no:
            continue
        
        # Filter items that don't already exist in reports
        pending_items = []
        for item in items:
            item_name = item.get('itemName')
            if not item_name:
                continue
            
            # Check if this combination does NOT exist in any NON-DELETED report
            if (invest_bill_no, item_name) not in existing_combinations:
                pending_items.append(item)
        
        # Only include scan if it has pending items
        if pending_items:
            scan_copy = scan.copy()
            scan_copy['item'] = json.dumps(pending_items)
            filtered_investigations.append(scan_copy)
    
    return JsonResponse(filtered_investigations, safe=False)


    
@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def create_ct_report(request):
    try:
        data = request.data
        
        # Get user ID from request headers
        user_id = request.data.get('auth-user-id', 'system')
        
        # Create CTReport instance using your model
        ct_report = CTReport.objects.create(
            date=data.get('date'),
            time=data.get('time', ''),
            patientId=data.get('patientId'),
            investBillNo=data.get('investBillNo'),
            ipNumber=data.get('ipNumber'),
            investigation=data.get('investigation'),
            impression=data.get('impression'),
            is_approved=data.get('is_approved', False),
            created_by=user_id
        )
        
        return JsonResponse({
            "_id": str(ct_report.id),
            "message": "CT Report created successfully"
        }, status=201)
        
    except Exception as e:
        return JsonResponse({
            "error": str(e)
        }, status=400)

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_ct_reports(request, patientId=None):
    # Get query parameters for date filtering
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    
    # MongoDB connection setup
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    db = client['HMS']
    ct_report_collection = db['hospital_ctreport']
    
    # Build query filters
    query_filter = {'is_deleted': False}  # Always exclude deleted reports
    
    if patientId:
        query_filter['patientId'] = patientId
    
    # Add date range filter if provided
    if from_date or to_date:
        date_filter = {}
        
        if from_date:
            try:
                from_date_obj = datetime.strptime(from_date, '%Y-%m-%d')
                date_filter['$gte'] = from_date_obj
            except ValueError:
                return JsonResponse(
                    {'error': 'Invalid from_date format. Use YYYY-MM-DD'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        if to_date:
            try:
                to_date_obj = datetime.strptime(to_date, '%Y-%m-%d')
                # Add one day and subtract 1 second to include the entire end date
                to_date_obj = to_date_obj + timedelta(days=1) - timedelta(seconds=1)
                date_filter['$lte'] = to_date_obj
            except ValueError:
                return JsonResponse(
                    {'error': 'Invalid to_date format. Use YYYY-MM-DD'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        query_filter['date'] = date_filter
    
    try:
        # Fetch reports from MongoDB with filters
        reports = list(ct_report_collection.find(
            query_filter,
            {'_id': 0}  # Exclude MongoDB _id field
        ).sort('date', -1))  # Sort by date descending (newest first)
        
        # Enrich each report with patient information from Django ORM
        enriched_reports = []
        for report_data in reports:
            patient_id = report_data.get('patientId')
            
            try:
                patient = Patient.objects.get(uhid=patient_id)
                report_data['salutation'] = patient.salutation
                report_data['firstName'] = patient.firstName
                report_data['lastName'] = patient.lastName
                report_data['age'] = patient.age
                report_data['gender'] = patient.gender
            except Patient.DoesNotExist:
                report_data['salutation'] = ''
                report_data['firstName'] = ''
                report_data['lastName'] = ''
                report_data['age'] = None
                report_data['gender'] = ''
            
            # Convert MongoDB date to ISO format string for JSON serialization
            if 'date' in report_data and report_data['date']:
                if isinstance(report_data['date'], datetime):
                    report_data['date'] = report_data['date'].isoformat()
            
            # Convert other datetime fields if present
            datetime_fields = ['created_date', 'lastmodified_date', 'approved_date', 'deleted_date']
            for field in datetime_fields:
                if field in report_data and report_data[field]:
                    if isinstance(report_data[field], datetime):
                        report_data[field] = report_data[field].isoformat()
            
            enriched_reports.append(report_data)
        
        if patientId and not enriched_reports:
            return JsonResponse(
                {'error': 'Report not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        return JsonResponse(
            enriched_reports if not patientId else enriched_reports[0] if enriched_reports else {}, 
            safe=False, 
            status=status.HTTP_200_OK
        )
        
    except Exception as e:
        return JsonResponse(
            {'error': str(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    


@csrf_exempt
@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def soft_delete_ct_report(request, investBillNo):
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        collection = client['HMS']['hospital_ctreport']

        try:
            data = request.data
            investigation = data.get("investigation")
            user_id = request.data.get('auth-user-id', 'system')
            date_str = data.get("date")

            # --- Build Query ---
            query = {"investBillNo": investBillNo, "is_deleted": False}
            if investigation:
                query["investigation"] = investigation

            # Parse date (if provided)
            if date_str:
                try:
                    date_obj = (
                        datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                        if "T" in date_str
                        else datetime.strptime(date_str, "%Y-%m-%d")
                    )

                    start = date_obj.replace(hour=0, minute=0, second=0, microsecond=0)
                    end = date_obj.replace(hour=23, minute=59, second=59, microsecond=999999)

                    query["date"] = {"$gte": start, "$lte": end}
                except ValueError:
                    return JsonResponse({"error": "Invalid date format"}, status=400)

            # --- Fetch Report ---
            report = collection.find_one(query)
            if not report:
                return JsonResponse({"error": "Report not found"}, status=404)

            # --- Update Report ---
            update_result = collection.update_one(
                {"_id": report["_id"]},
                {
                    "$set": {
                        "is_deleted": True,
                        "deleted_by": user_id,
                        "deleted_date": now().isoformat(),
                    }
                }
            )

            if update_result.modified_count == 0:
                return JsonResponse({"error": "Failed to update report"}, status=400)

            # --- Fetch Updated Report ---
            updated_report = collection.find_one({"_id": report["_id"]})

            # Convert fields to JSON serializable types
            updated_report["_id"] = str(updated_report["_id"])

            for field in ["date", "created_date", "lastmodified_date"]:
                if field in updated_report and isinstance(updated_report[field], datetime):
                    updated_report[field] = updated_report[field].isoformat()

            return JsonResponse(updated_report, safe=False, status=200)

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)



@csrf_exempt
@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def approve_ct_report(request, investBillNo):
    
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    collection = client['HMS']['hospital_ctreport']

    try:
        data = request.data
        investigation = data.get("investigation")
        user_id = request.data.get('auth-user-id', 'system')
        date_str = data.get("date")

        # --- Build Query ---
        query = {"investBillNo": investBillNo, "is_deleted": False}
        if investigation:
            query["investigation"] = investigation

        # Parse date (if provided)
        if date_str:
            try:
                date_obj = (
                    datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    if "T" in date_str
                    else datetime.strptime(date_str, "%Y-%m-%d")
                )

                start = date_obj.replace(hour=0, minute=0, second=0, microsecond=0)
                end = date_obj.replace(hour=23, minute=59, second=59, microsecond=999999)

                query["date"] = {"$gte": start, "$lte": end}
            except ValueError:
                return JsonResponse({"error": "Invalid date format"}, status=400)

        # --- Fetch Report ---
        report = collection.find_one(query)
        if not report:
            return JsonResponse({"error": "Report not found"}, status=404)

        # --- Update Report ---
        update_result = collection.update_one(
            {"_id": report["_id"]},
            {
                "$set": {
                    "is_approved": True,
                    "approved_by": user_id,
                    "approved_date": now().isoformat(),
                    
                }
            }
        )

        if update_result.modified_count == 0:
            return JsonResponse({"error": "Failed to update report"}, status=400)

        # --- Fetch Updated Report ---
        updated_report = collection.find_one({"_id": report["_id"]})

        # Convert fields to JSON serializable types
        updated_report["_id"] = str(updated_report["_id"])

        for field in ["date", "created_date", "lastmodified_date", "approved_date"]:
            if field in updated_report and isinstance(updated_report[field], datetime):
                updated_report[field] = updated_report[field].isoformat()

        return JsonResponse(updated_report, safe=False, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
    finally:
        client.close()

    
@csrf_exempt
@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def edit_ct_report_impression(request, investBillNo):
    """
    Edit only the impression field of a CT report
    """
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    collection = client['HMS']['hospital_ctreport']

    try:
        data = request.data
        investigation = data.get("investigation")
        new_impression = data.get("impression")
        date_str = data.get("date")
        user_id = request.data.get('auth-user-id', 'system')

        # Validate required fields
        if not new_impression:
            return JsonResponse({"error": "Impression field is required"}, status=400)

        # --- Build Query ---
        query = {"investBillNo": investBillNo, "is_deleted": False}
        if investigation:
            query["investigation"] = investigation

        # Parse date (if provided)
        if date_str:
            try:
                date_obj = (
                    datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    if "T" in date_str
                    else datetime.strptime(date_str, "%Y-%m-%d")
                )

                start = date_obj.replace(hour=0, minute=0, second=0, microsecond=0)
                end = date_obj.replace(hour=23, minute=59, second=59, microsecond=999999)

                query["date"] = {"$gte": start, "$lte": end}
            except ValueError:
                return JsonResponse({"error": "Invalid date format"}, status=400)

        # --- Fetch Report ---
        report = collection.find_one(query)
        if not report:
            return JsonResponse({"error": "Report not found"}, status=404)

        # Check if report is approved (optional - you can remove this if you want to allow editing approved reports)
        # if not report.get("is_approved", False):
        #     return JsonResponse({"error": "Only approved reports can be edited"}, status=400)

        # --- Update Report ---
        update_result = collection.update_one(
            {"_id": report["_id"]},
            {
                "$set": {
                    "impression": new_impression,
                    "lastmodified_by": user_id,
                    "lastmodified_date": now().isoformat(),
                }
            }
        )

        if update_result.modified_count == 0:
            return JsonResponse({"error": "Failed to update report"}, status=400)

        # --- Fetch Updated Report ---
        updated_report = collection.find_one({"_id": report["_id"]})

        # Convert fields to JSON serializable types
        updated_report["_id"] = str(updated_report["_id"])

        for field in ["date", "created_date", "lastmodified_date", "approved_date"]:
            if field in updated_report and isinstance(updated_report[field], datetime):
                updated_report[field] = updated_report[field].isoformat()

        return JsonResponse(updated_report, safe=False, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
    finally:
        client.close()


# View to list all MRI investigations
@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_mri_investigations(request):
    # MongoDB connection setup
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    db = client['HMS']
    mri_collection = db['MRI Scan']
    mri_report_collection = db['hospital_mrireport']
    
    # Get all active MRI records
    mri_scans = list(mri_collection.find({'is_active': True}, {'_id': 0}))
    
    # Get only NON-DELETED reports
    existing_reports = list(mri_report_collection.find(
        {'is_deleted': {'$ne': True}},  # Only get reports where is_deleted is not True
        {'investBillNo': 1, 'investigation': 1, '_id': 0}
    ))
    
    # Create a set of (investBillNo, investigation) tuples for quick lookup
    existing_combinations = set()
    for report in existing_reports:
        invest_bill = report.get('investBillNo')
        investigation = report.get('investigation')
        if invest_bill and investigation:
            existing_combinations.add((invest_bill, investigation))
    
    # Filter investigations
    filtered_investigations = []
    
    for scan in mri_scans:
        invest_bill_no = scan.get('investBillNo')
        items = json.loads(scan.get('item', '[]'))
        
        # Skip if no investBillNo
        if not invest_bill_no:
            continue
        
        # Filter items that don't already exist in reports
        pending_items = []
        for item in items:
            item_name = item.get('itemName')
            if not item_name:
                continue
            
            # Check if this combination does NOT exist in any NON-DELETED report
            if (invest_bill_no, item_name) not in existing_combinations:
                pending_items.append(item)
        
        # Only include scan if it has pending items
        if pending_items:
            scan_copy = scan.copy()
            scan_copy['item'] = json.dumps(pending_items)
            filtered_investigations.append(scan_copy)
    
    return JsonResponse(filtered_investigations, safe=False)


    
@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def create_mri_report(request):
    try:
        data = request.data
        
        # Get user ID from request headers
        user_id = request.data.get('auth-user-id', 'system')
        
        # Create CTReport instance using your model
        mri_report = MRIReport.objects.create(
            date=data.get('date'),
            time=data.get('time', ''),
            patientId=data.get('patientId'),
            investBillNo=data.get('investBillNo'),
            ipNumber=data.get('ipNumber'),
            investigation=data.get('investigation'),
            impression=data.get('impression'),
            is_approved=data.get('is_approved', False),
            created_by=user_id
        )
        
        return JsonResponse({
            "_id": str(mri_report.id),
            "message": "X-Ray Report created successfully"
        }, status=201)
        
    except Exception as e:
        return JsonResponse({
            "error": str(e)
        }, status=400)

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_mri_reports(request, patientId=None):
    # Get query parameters for date filtering
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    
    # MongoDB connection setup
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    db = client['HMS']
    mri_report_collection = db['hospital_mrireport']
    
    # Build query filters
    query_filter = {'is_deleted': False}  # Always exclude deleted reports
    
    if patientId:
        query_filter['patientId'] = patientId
    
    # Add date range filter if provided
    if from_date or to_date:
        date_filter = {}
        
        if from_date:
            try:
                from_date_obj = datetime.strptime(from_date, '%Y-%m-%d')
                date_filter['$gte'] = from_date_obj
            except ValueError:
                return JsonResponse(
                    {'error': 'Invalid from_date format. Use YYYY-MM-DD'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        if to_date:
            try:
                to_date_obj = datetime.strptime(to_date, '%Y-%m-%d')
                # Add one day and subtract 1 second to include the entire end date
                to_date_obj = to_date_obj + timedelta(days=1) - timedelta(seconds=1)
                date_filter['$lte'] = to_date_obj
            except ValueError:
                return JsonResponse(
                    {'error': 'Invalid to_date format. Use YYYY-MM-DD'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        query_filter['date'] = date_filter
    
    try:
        # Fetch reports from MongoDB with filters
        reports = list(mri_report_collection.find(
            query_filter,
            {'_id': 0}  # Exclude MongoDB _id field
        ).sort('date', -1))  # Sort by date descending (newest first)
        
        # Enrich each report with patient information from Django ORM
        enriched_reports = []
        for report_data in reports:
            patient_id = report_data.get('patientId')
            
            try:
                patient = Patient.objects.get(uhid=patient_id)
                report_data['salutation'] = patient.salutation
                report_data['firstName'] = patient.firstName
                report_data['lastName'] = patient.lastName
                report_data['age'] = patient.age
                report_data['gender'] = patient.gender
            except Patient.DoesNotExist:
                report_data['salutation'] = ''
                report_data['firstName'] = ''
                report_data['lastName'] = ''
                report_data['age'] = None
                report_data['gender'] = ''
            
            # Convert MongoDB date to ISO format string for JSON serialization
            if 'date' in report_data and report_data['date']:
                if isinstance(report_data['date'], datetime):
                    report_data['date'] = report_data['date'].isoformat()
            
            # Convert other datetime fields if present
            datetime_fields = ['created_date', 'lastmodified_date', 'approved_date', 'deleted_date']
            for field in datetime_fields:
                if field in report_data and report_data[field]:
                    if isinstance(report_data[field], datetime):
                        report_data[field] = report_data[field].isoformat()
            
            enriched_reports.append(report_data)
        
        if patientId and not enriched_reports:
            return JsonResponse(
                {'error': 'Report not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        return JsonResponse(
            enriched_reports if not patientId else enriched_reports[0] if enriched_reports else {}, 
            safe=False, 
            status=status.HTTP_200_OK
        )
        
    except Exception as e:
        return JsonResponse(
            {'error': str(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    


@csrf_exempt
@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def soft_delete_mri_report(request, investBillNo):
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        collection = client['HMS']['hospital_mrireport']

        try:
            data = request.data
            investigation = data.get("investigation")
            user_id = request.data.get('auth-user-id', 'system')
            date_str = data.get("date")

            # --- Build Query ---
            query = {"investBillNo": investBillNo, "is_deleted": False}
            if investigation:
                query["investigation"] = investigation

            # Parse date (if provided)
            if date_str:
                try:
                    date_obj = (
                        datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                        if "T" in date_str
                        else datetime.strptime(date_str, "%Y-%m-%d")
                    )

                    start = date_obj.replace(hour=0, minute=0, second=0, microsecond=0)
                    end = date_obj.replace(hour=23, minute=59, second=59, microsecond=999999)

                    query["date"] = {"$gte": start, "$lte": end}
                except ValueError:
                    return JsonResponse({"error": "Invalid date format"}, status=400)

            # --- Fetch Report ---
            report = collection.find_one(query)
            if not report:
                return JsonResponse({"error": "Report not found"}, status=404)

            # --- Update Report ---
            update_result = collection.update_one(
                {"_id": report["_id"]},
                {
                    "$set": {
                        "is_deleted": True,
                        "deleted_by": user_id,
                        "deleted_date": now().isoformat(),
                    }
                }
            )

            if update_result.modified_count == 0:
                return JsonResponse({"error": "Failed to update report"}, status=400)

            # --- Fetch Updated Report ---
            updated_report = collection.find_one({"_id": report["_id"]})

            # Convert fields to JSON serializable types
            updated_report["_id"] = str(updated_report["_id"])

            for field in ["date", "created_date", "lastmodified_date"]:
                if field in updated_report and isinstance(updated_report[field], datetime):
                    updated_report[field] = updated_report[field].isoformat()

            return JsonResponse(updated_report, safe=False, status=200)

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)



@csrf_exempt
@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def approve_mri_report(request, investBillNo):
    
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    collection = client['HMS']['hospital_mrireport']

    try:
        data = request.data
        investigation = data.get("investigation")
        user_id = request.data.get('auth-user-id', 'system')
        date_str = data.get("date")

        # --- Build Query ---
        query = {"investBillNo": investBillNo, "is_deleted": False}
        if investigation:
            query["investigation"] = investigation

        # Parse date (if provided)
        if date_str:
            try:
                date_obj = (
                    datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    if "T" in date_str
                    else datetime.strptime(date_str, "%Y-%m-%d")
                )

                start = date_obj.replace(hour=0, minute=0, second=0, microsecond=0)
                end = date_obj.replace(hour=23, minute=59, second=59, microsecond=999999)

                query["date"] = {"$gte": start, "$lte": end}
            except ValueError:
                return JsonResponse({"error": "Invalid date format"}, status=400)

        # --- Fetch Report ---
        report = collection.find_one(query)
        if not report:
            return JsonResponse({"error": "Report not found"}, status=404)

        # --- Update Report ---
        update_result = collection.update_one(
            {"_id": report["_id"]},
            {
                "$set": {
                    "is_approved": True,
                    "approved_by": user_id,
                    "approved_date": now().isoformat(),
                   
                }
            }
        )

        if update_result.modified_count == 0:
            return JsonResponse({"error": "Failed to update report"}, status=400)

        # --- Fetch Updated Report ---
        updated_report = collection.find_one({"_id": report["_id"]})

        # Convert fields to JSON serializable types
        updated_report["_id"] = str(updated_report["_id"])

        for field in ["date", "created_date", "lastmodified_date", "approved_date"]:
            if field in updated_report and isinstance(updated_report[field], datetime):
                updated_report[field] = updated_report[field].isoformat()

        return JsonResponse(updated_report, safe=False, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
    finally:
        client.close()

    
@csrf_exempt
@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def edit_mri_report_impression(request, investBillNo):
    """
    Edit only the impression field of a MRI report
    """
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    collection = client['HMS']['hospital_mrireport']

    try:
        data = request.data
        investigation = data.get("investigation")
        new_impression = data.get("impression")
        date_str = data.get("date")
        user_id = request.data.get('auth-user-id', 'system')

        # Validate required fields
        if not new_impression:
            return JsonResponse({"error": "Impression field is required"}, status=400)

        # --- Build Query ---
        query = {"investBillNo": investBillNo, "is_deleted": False}
        if investigation:
            query["investigation"] = investigation

        # Parse date (if provided)
        if date_str:
            try:
                date_obj = (
                    datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    if "T" in date_str
                    else datetime.strptime(date_str, "%Y-%m-%d")
                )

                start = date_obj.replace(hour=0, minute=0, second=0, microsecond=0)
                end = date_obj.replace(hour=23, minute=59, second=59, microsecond=999999)

                query["date"] = {"$gte": start, "$lte": end}
            except ValueError:
                return JsonResponse({"error": "Invalid date format"}, status=400)

        # --- Fetch Report ---
        report = collection.find_one(query)
        if not report:
            return JsonResponse({"error": "Report not found"}, status=404)

        # Check if report is approved (optional - you can remove this if you want to allow editing approved reports)
        # if not report.get("is_approved", False):
        #     return JsonResponse({"error": "Only approved reports can be edited"}, status=400)

        # --- Update Report ---
        update_result = collection.update_one(
            {"_id": report["_id"]},
            {
                "$set": {
                    "impression": new_impression,
                    "lastmodified_by": user_id,
                    "lastmodified_date": now().isoformat(),
                }
            }
        )

        if update_result.modified_count == 0:
            return JsonResponse({"error": "Failed to update report"}, status=400)

        # --- Fetch Updated Report ---
        updated_report = collection.find_one({"_id": report["_id"]})

        # Convert fields to JSON serializable types
        updated_report["_id"] = str(updated_report["_id"])

        for field in ["date", "created_date", "lastmodified_date", "approved_date"]:
            if field in updated_report and isinstance(updated_report[field], datetime):
                updated_report[field] = updated_report[field].isoformat()

        return JsonResponse(updated_report, safe=False, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
    finally:
        client.close()



@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_usg_investigations(request):
    # MongoDB connection setup
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    db = client['HMS']
    xray_collection = db['X-Ray']
    usg_report_collection = db['hospital_usgreport']
    
    # Get all active X-Ray records
    usg_scans = list(xray_collection.find({'is_active': True}, {'_id': 0}))
    
    # Get only NON-DELETED reports
    existing_reports = list(usg_report_collection.find(
        {'is_deleted': {'$ne': True}},  # Only get reports where is_deleted is not True
        {'investBillNo': 1, 'investigation': 1, '_id': 0}
    ))
    
    # Create a set of (investBillNo, investigation) tuples for quick lookup
    existing_combinations = set()
    for report in existing_reports:
        invest_bill = report.get('investBillNo')
        investigation = report.get('investigation')
        if invest_bill and investigation:
            existing_combinations.add((invest_bill, investigation))
    
    # Filter investigations
    filtered_investigations = []
    
    for scan in usg_scans:
        invest_bill_no = scan.get('investBillNo')
        items = json.loads(scan.get('item', '[]'))
        
        # Skip if no investBillNo
        if not invest_bill_no:
            continue
        
        # Filter items that don't already exist in reports
        pending_items = []
        for item in items:
            item_name = item.get('itemName')
            if not item_name:
                continue
            
            # Check if this combination does NOT exist in any NON-DELETED report
            if (invest_bill_no, item_name) not in existing_combinations:
                pending_items.append(item)
        
        # Only include scan if it has pending items
        if pending_items:
            scan_copy = scan.copy()
            scan_copy['item'] = json.dumps(pending_items)
            filtered_investigations.append(scan_copy)
    
    return JsonResponse(filtered_investigations, safe=False)


    
@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def create_usg_report(request):
    try:
        data = request.data
        
        # Get user ID from request headers
        user_id = request.data.get('auth-user-id', 'system')
        
        # Create CTReport instance using your model
        usg_report = USGReport.objects.create(
            date=data.get('date'),
            time=data.get('time', ''),
            patientId=data.get('patientId'),
            investBillNo=data.get('investBillNo'),
            ipNumber=data.get('ipNumber'),
            investigation=data.get('investigation'),
            impression=data.get('impression'),
            is_approved=data.get('is_approved', False),
            created_by=user_id
        )
        
        return JsonResponse({
            "_id": str(usg_report.id),
            "message": "X-Ray Report created successfully"
        }, status=201)
        
    except Exception as e:
        return JsonResponse({
            "error": str(e)
        }, status=400)

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_usg_reports(request, patientId=None):
    # Get query parameters for date filtering
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    
    # MongoDB connection setup
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    db = client['HMS']
    usg_report_collection = db['hospital_usgreport']
    
    # Build query filters
    query_filter = {'is_deleted': False}  # Always exclude deleted reports
    
    if patientId:
        query_filter['patientId'] = patientId
    
    # Add date range filter if provided
    if from_date or to_date:
        date_filter = {}
        
        if from_date:
            try:
                from_date_obj = datetime.strptime(from_date, '%Y-%m-%d')
                date_filter['$gte'] = from_date_obj
            except ValueError:
                return JsonResponse(
                    {'error': 'Invalid from_date format. Use YYYY-MM-DD'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        if to_date:
            try:
                to_date_obj = datetime.strptime(to_date, '%Y-%m-%d')
                # Add one day and subtract 1 second to include the entire end date
                to_date_obj = to_date_obj + timedelta(days=1) - timedelta(seconds=1)
                date_filter['$lte'] = to_date_obj
            except ValueError:
                return JsonResponse(
                    {'error': 'Invalid to_date format. Use YYYY-MM-DD'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        query_filter['date'] = date_filter
    
    try:
        # Fetch reports from MongoDB with filters
        reports = list(usg_report_collection.find(
            query_filter,
            {'_id': 0}  # Exclude MongoDB _id field
        ).sort('date', -1))  # Sort by date descending (newest first)
        
        # Enrich each report with patient information from Django ORM
        enriched_reports = []
        for report_data in reports:
            patient_id = report_data.get('patientId')
            
            try:
                patient = Patient.objects.get(uhid=patient_id)
                report_data['salutation'] = patient.salutation
                report_data['firstName'] = patient.firstName
                report_data['lastName'] = patient.lastName
                report_data['age'] = patient.age
                report_data['gender'] = patient.gender
            except Patient.DoesNotExist:
                report_data['salutation'] = ''
                report_data['firstName'] = ''
                report_data['lastName'] = ''
                report_data['age'] = None
                report_data['gender'] = ''
            
            # Convert MongoDB date to ISO format string for JSON serialization
            if 'date' in report_data and report_data['date']:
                if isinstance(report_data['date'], datetime):
                    report_data['date'] = report_data['date'].isoformat()
            
            # Convert other datetime fields if present
            datetime_fields = ['created_date', 'lastmodified_date', 'approved_date', 'deleted_date']
            for field in datetime_fields:
                if field in report_data and report_data[field]:
                    if isinstance(report_data[field], datetime):
                        report_data[field] = report_data[field].isoformat()
            
            enriched_reports.append(report_data)
        
        if patientId and not enriched_reports:
            return JsonResponse(
                {'error': 'Report not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        return JsonResponse(
            enriched_reports if not patientId else enriched_reports[0] if enriched_reports else {}, 
            safe=False, 
            status=status.HTTP_200_OK
        )
        
    except Exception as e:
        return JsonResponse(
            {'error': str(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    


@csrf_exempt
@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def soft_delete_usg_report(request, investBillNo):
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        collection = client['HMS']['hospital_usgreport']

        try:
            data = request.data
            investigation = data.get("investigation")
            user_id = request.data.get('auth-user-id', 'system')
            date_str = data.get("date")

            # --- Build Query ---
            query = {"investBillNo": investBillNo, "is_deleted": False}
            if investigation:
                query["investigation"] = investigation

            # Parse date (if provided)
            if date_str:
                try:
                    date_obj = (
                        datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                        if "T" in date_str
                        else datetime.strptime(date_str, "%Y-%m-%d")
                    )

                    start = date_obj.replace(hour=0, minute=0, second=0, microsecond=0)
                    end = date_obj.replace(hour=23, minute=59, second=59, microsecond=999999)

                    query["date"] = {"$gte": start, "$lte": end}
                except ValueError:
                    return JsonResponse({"error": "Invalid date format"}, status=400)

            # --- Fetch Report ---
            report = collection.find_one(query)
            if not report:
                return JsonResponse({"error": "Report not found"}, status=404)

            # --- Update Report ---
            update_result = collection.update_one(
                {"_id": report["_id"]},
                {
                    "$set": {
                        "is_deleted": True,
                        "deleted_by": user_id,
                        "deleted_date": now().isoformat(),
                    }
                }
            )

            if update_result.modified_count == 0:
                return JsonResponse({"error": "Failed to update report"}, status=400)

            # --- Fetch Updated Report ---
            updated_report = collection.find_one({"_id": report["_id"]})

            # Convert fields to JSON serializable types
            updated_report["_id"] = str(updated_report["_id"])

            for field in ["date", "created_date", "lastmodified_date"]:
                if field in updated_report and isinstance(updated_report[field], datetime):
                    updated_report[field] = updated_report[field].isoformat()

            return JsonResponse(updated_report, safe=False, status=200)

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)



@csrf_exempt
@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def approve_usg_report(request, investBillNo):
    
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    collection = client['HMS']['hospital_usgreport']

    try:
        data = request.data
        investigation = data.get("investigation")
        user_id = request.data.get('auth-user-id', 'system')
        date_str = data.get("date")

        # --- Build Query ---
        query = {"investBillNo": investBillNo, "is_deleted": False}
        if investigation:
            query["investigation"] = investigation

        # Parse date (if provided)
        if date_str:
            try:
                date_obj = (
                    datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    if "T" in date_str
                    else datetime.strptime(date_str, "%Y-%m-%d")
                )

                start = date_obj.replace(hour=0, minute=0, second=0, microsecond=0)
                end = date_obj.replace(hour=23, minute=59, second=59, microsecond=999999)

                query["date"] = {"$gte": start, "$lte": end}
            except ValueError:
                return JsonResponse({"error": "Invalid date format"}, status=400)

        # --- Fetch Report ---
        report = collection.find_one(query)
        if not report:
            return JsonResponse({"error": "Report not found"}, status=404)

        # --- Update Report ---
        update_result = collection.update_one(
            {"_id": report["_id"]},
            {
                "$set": {
                    "is_approved": True,
                    "approved_by": user_id,
                    "approved_date": now().isoformat(),
                    
                }
            }
        )

        if update_result.modified_count == 0:
            return JsonResponse({"error": "Failed to update report"}, status=400)

        # --- Fetch Updated Report ---
        updated_report = collection.find_one({"_id": report["_id"]})

        # Convert fields to JSON serializable types
        updated_report["_id"] = str(updated_report["_id"])

        for field in ["date", "created_date", "lastmodified_date", "approved_date"]:
            if field in updated_report and isinstance(updated_report[field], datetime):
                updated_report[field] = updated_report[field].isoformat()

        return JsonResponse(updated_report, safe=False, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
    finally:
        client.close()

    
@csrf_exempt
@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def edit_usg_report_impression(request, investBillNo):
    """
    Edit only the impression field of a USG report
    """
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    collection = client['HMS']['hospital_usgreport']

    try:
        data = request.data
        investigation = data.get("investigation")
        new_impression = data.get("impression")
        date_str = data.get("date")
        user_id = request.data.get('auth-user-id', 'system')

        # Validate required fields
        if not new_impression:
            return JsonResponse({"error": "Impression field is required"}, status=400)

        # --- Build Query ---
        query = {"investBillNo": investBillNo, "is_deleted": False}
        if investigation:
            query["investigation"] = investigation

        # Parse date (if provided)
        if date_str:
            try:
                date_obj = (
                    datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    if "T" in date_str
                    else datetime.strptime(date_str, "%Y-%m-%d")
                )

                start = date_obj.replace(hour=0, minute=0, second=0, microsecond=0)
                end = date_obj.replace(hour=23, minute=59, second=59, microsecond=999999)

                query["date"] = {"$gte": start, "$lte": end}
            except ValueError:
                return JsonResponse({"error": "Invalid date format"}, status=400)

        # --- Fetch Report ---
        report = collection.find_one(query)
        if not report:
            return JsonResponse({"error": "Report not found"}, status=404)

        # Check if report is approved (optional - you can remove this if you want to allow editing approved reports)
        # if not report.get("is_approved", False):
        #     return JsonResponse({"error": "Only approved reports can be edited"}, status=400)

        # --- Update Report ---
        update_result = collection.update_one(
            {"_id": report["_id"]},
            {
                "$set": {
                    "impression": new_impression,
                    "lastmodified_by": user_id,
                    "lastmodified_date": now().isoformat(),
                }
            }
        )

        if update_result.modified_count == 0:
            return JsonResponse({"error": "Failed to update report"}, status=400)

        # --- Fetch Updated Report ---
        updated_report = collection.find_one({"_id": report["_id"]})

        # Convert fields to JSON serializable types
        updated_report["_id"] = str(updated_report["_id"])

        for field in ["date", "created_date", "lastmodified_date", "approved_date"]:
            if field in updated_report and isinstance(updated_report[field], datetime):
                updated_report[field] = updated_report[field].isoformat()

        return JsonResponse(updated_report, safe=False, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
    finally:
        client.close()

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_x_ray_investigations(request):
    # MongoDB connection setup
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    db = client['HMS']
    xray_collection = db['X-Ray']
    xray_report_collection = db['hospital_xrayreport']
    
    # Get all active X-Ray records
    xray_scans = list(xray_collection.find({'is_active': True}, {'_id': 0}))
    
    # Get only NON-DELETED reports
    existing_reports = list(xray_report_collection.find(
        {'is_deleted': {'$ne': True}},  # Only get reports where is_deleted is not True
        {'investBillNo': 1, 'investigation': 1, '_id': 0}
    ))
    
    # Create a set of (investBillNo, investigation) tuples for quick lookup
    existing_combinations = set()
    for report in existing_reports:
        invest_bill = report.get('investBillNo')
        investigation = report.get('investigation')
        if invest_bill and investigation:
            existing_combinations.add((invest_bill, investigation))
    
    # Filter investigations
    filtered_investigations = []
    
    for scan in xray_scans:
        invest_bill_no = scan.get('investBillNo')
        items = json.loads(scan.get('item', '[]'))
        
        # Skip if no investBillNo
        if not invest_bill_no:
            continue
        
        # Filter items that don't already exist in reports
        pending_items = []
        for item in items:
            item_name = item.get('itemName')
            if not item_name:
                continue
            
            # Check if this combination does NOT exist in any NON-DELETED report
            if (invest_bill_no, item_name) not in existing_combinations:
                pending_items.append(item)
        
        # Only include scan if it has pending items
        if pending_items:
            scan_copy = scan.copy()
            scan_copy['item'] = json.dumps(pending_items)
            filtered_investigations.append(scan_copy)
    
    return JsonResponse(filtered_investigations, safe=False)


    
@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def create_x_ray_report(request):
    try:
        data = request.data
        
        # Get user ID from request headers
        user_id = request.data.get('auth-user-id', 'system')
        
        # Create CTReport instance using your model
        x_ray_report = XRayReport.objects.create(
            date=data.get('date'),
            time=data.get('time', ''),
            patientId=data.get('patientId'),
            investBillNo=data.get('investBillNo'),
            ipNumber=data.get('ipNumber'),
            investigation=data.get('investigation'),
            impression=data.get('impression'),
            is_approved=data.get('is_approved', False),
            created_by=user_id
        )
        
        return JsonResponse({
            "_id": str(x_ray_report.id),
            "message": "X-Ray Report created successfully"
        }, status=201)
        
    except Exception as e:
        return JsonResponse({
            "error": str(e)
        }, status=400)

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_x_ray_reports(request, patientId=None):
    # Get query parameters for date filtering
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    
    # MongoDB connection setup
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    db = client['HMS']
    x_ray_report_collection = db['hospital_xrayreport']
    
    # Build query filters
    query_filter = {'is_deleted': False}  # Always exclude deleted reports
    
    if patientId:
        query_filter['patientId'] = patientId
    
    # Add date range filter if provided
    if from_date or to_date:
        date_filter = {}
        
        if from_date:
            try:
                from_date_obj = datetime.strptime(from_date, '%Y-%m-%d')
                date_filter['$gte'] = from_date_obj
            except ValueError:
                return JsonResponse(
                    {'error': 'Invalid from_date format. Use YYYY-MM-DD'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        if to_date:
            try:
                to_date_obj = datetime.strptime(to_date, '%Y-%m-%d')
                # Add one day and subtract 1 second to include the entire end date
                to_date_obj = to_date_obj + timedelta(days=1) - timedelta(seconds=1)
                date_filter['$lte'] = to_date_obj
            except ValueError:
                return JsonResponse(
                    {'error': 'Invalid to_date format. Use YYYY-MM-DD'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        query_filter['date'] = date_filter
    
    try:
        # Fetch reports from MongoDB with filters
        reports = list(x_ray_report_collection.find(
            query_filter,
            {'_id': 0}  # Exclude MongoDB _id field
        ).sort('date', -1))  # Sort by date descending (newest first)
        
        # Enrich each report with patient information from Django ORM
        enriched_reports = []
        for report_data in reports:
            patient_id = report_data.get('patientId')
            
            try:
                patient = Patient.objects.get(uhid=patient_id)
                report_data['salutation'] = patient.salutation
                report_data['firstName'] = patient.firstName
                report_data['lastName'] = patient.lastName
                report_data['age'] = patient.age
                report_data['gender'] = patient.gender
            except Patient.DoesNotExist:
                report_data['salutation'] = ''
                report_data['firstName'] = ''
                report_data['lastName'] = ''
                report_data['age'] = None
                report_data['gender'] = ''
            
            # Convert MongoDB date to ISO format string for JSON serialization
            if 'date' in report_data and report_data['date']:
                if isinstance(report_data['date'], datetime):
                    report_data['date'] = report_data['date'].isoformat()
            
            # Convert other datetime fields if present
            datetime_fields = ['created_date', 'lastmodified_date', 'approved_date', 'deleted_date']
            for field in datetime_fields:
                if field in report_data and report_data[field]:
                    if isinstance(report_data[field], datetime):
                        report_data[field] = report_data[field].isoformat()
            
            enriched_reports.append(report_data)
        
        if patientId and not enriched_reports:
            return JsonResponse(
                {'error': 'Report not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        return JsonResponse(
            enriched_reports if not patientId else enriched_reports[0] if enriched_reports else {}, 
            safe=False, 
            status=status.HTTP_200_OK
        )
        
    except Exception as e:
        return JsonResponse(
            {'error': str(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    


@csrf_exempt
@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def soft_delete_x_ray_report(request, investBillNo):
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        collection = client['HMS']['hospital_xrayreport']

        try:
            data = request.data
            investigation = data.get("investigation")
            user_id = request.data.get('auth-user-id', 'system')
            date_str = data.get("date")

            # --- Build Query ---
            query = {"investBillNo": investBillNo, "is_deleted": False}
            if investigation:
                query["investigation"] = investigation

            # Parse date (if provided)
            if date_str:
                try:
                    date_obj = (
                        datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                        if "T" in date_str
                        else datetime.strptime(date_str, "%Y-%m-%d")
                    )

                    start = date_obj.replace(hour=0, minute=0, second=0, microsecond=0)
                    end = date_obj.replace(hour=23, minute=59, second=59, microsecond=999999)

                    query["date"] = {"$gte": start, "$lte": end}
                except ValueError:
                    return JsonResponse({"error": "Invalid date format"}, status=400)

            # --- Fetch Report ---
            report = collection.find_one(query)
            if not report:
                return JsonResponse({"error": "Report not found"}, status=404)

            # --- Update Report ---
            update_result = collection.update_one(
                {"_id": report["_id"]},
                {
                    "$set": {
                        "is_deleted": True,
                        "deleted_by": user_id,
                        "deleted_date": now().isoformat(),
                    }
                }
            )

            if update_result.modified_count == 0:
                return JsonResponse({"error": "Failed to update report"}, status=400)

            # --- Fetch Updated Report ---
            updated_report = collection.find_one({"_id": report["_id"]})

            # Convert fields to JSON serializable types
            updated_report["_id"] = str(updated_report["_id"])

            for field in ["date", "created_date", "lastmodified_date"]:
                if field in updated_report and isinstance(updated_report[field], datetime):
                    updated_report[field] = updated_report[field].isoformat()

            return JsonResponse(updated_report, safe=False, status=200)

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)



@csrf_exempt
@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def approve_x_ray_report(request, investBillNo):
    
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    collection = client['HMS']['hospital_xrayreport']

    try:
        data = request.data
        investigation = data.get("investigation")
        user_id = request.data.get('auth-user-id', 'system')
        date_str = data.get("date")

        # --- Build Query ---
        query = {"investBillNo": investBillNo, "is_deleted": False}
        if investigation:
            query["investigation"] = investigation

        # Parse date (if provided)
        if date_str:
            try:
                date_obj = (
                    datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    if "T" in date_str
                    else datetime.strptime(date_str, "%Y-%m-%d")
                )

                start = date_obj.replace(hour=0, minute=0, second=0, microsecond=0)
                end = date_obj.replace(hour=23, minute=59, second=59, microsecond=999999)

                query["date"] = {"$gte": start, "$lte": end}
            except ValueError:
                return JsonResponse({"error": "Invalid date format"}, status=400)

        # --- Fetch Report ---
        report = collection.find_one(query)
        if not report:
            return JsonResponse({"error": "Report not found"}, status=404)

        # --- Update Report ---
        update_result = collection.update_one(
            {"_id": report["_id"]},
            {
                "$set": {
                    "is_approved": True,
                    "approved_by": user_id,
                    "approved_date": now().isoformat(),
                   
                }
            }
        )

        if update_result.modified_count == 0:
            return JsonResponse({"error": "Failed to update report"}, status=400)

        # --- Fetch Updated Report ---
        updated_report = collection.find_one({"_id": report["_id"]})

        # Convert fields to JSON serializable types
        updated_report["_id"] = str(updated_report["_id"])

        for field in ["date", "created_date", "lastmodified_date", "approved_date"]:
            if field in updated_report and isinstance(updated_report[field], datetime):
                updated_report[field] = updated_report[field].isoformat()

        return JsonResponse(updated_report, safe=False, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
    finally:
        client.close()

    
@csrf_exempt
@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def edit_x_ray_report_impression(request, investBillNo):
    """
    Edit only the impression field of a X-Ray report
    """
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    collection = client['HMS']['hospital_xrayreport']

    try:
        data = request.data
        investigation = data.get("investigation")
        new_impression = data.get("impression")
        date_str = data.get("date")
        user_id = request.data.get('auth-user-id', 'system')

        # Validate required fields
        if not new_impression:
            return JsonResponse({"error": "Impression field is required"}, status=400)

        # --- Build Query ---
        query = {"investBillNo": investBillNo, "is_deleted": False}
        if investigation:
            query["investigation"] = investigation

        # Parse date (if provided)
        if date_str:
            try:
                date_obj = (
                    datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    if "T" in date_str
                    else datetime.strptime(date_str, "%Y-%m-%d")
                )

                start = date_obj.replace(hour=0, minute=0, second=0, microsecond=0)
                end = date_obj.replace(hour=23, minute=59, second=59, microsecond=999999)

                query["date"] = {"$gte": start, "$lte": end}
            except ValueError:
                return JsonResponse({"error": "Invalid date format"}, status=400)

        # --- Fetch Report ---
        report = collection.find_one(query)
        if not report:
            return JsonResponse({"error": "Report not found"}, status=404)

        # Check if report is approved (optional - you can remove this if you want to allow editing approved reports)
        # if not report.get("is_approved", False):
        #     return JsonResponse({"error": "Only approved reports can be edited"}, status=400)

        # --- Update Report ---
        update_result = collection.update_one(
            {"_id": report["_id"]},
            {
                "$set": {
                    "impression": new_impression,
                    "lastmodified_by": user_id,
                    "lastmodified_date": now().isoformat(),
                }
            }
        )

        if update_result.modified_count == 0:
            return JsonResponse({"error": "Failed to update report"}, status=400)

        # --- Fetch Updated Report ---
        updated_report = collection.find_one({"_id": report["_id"]})

        # Convert fields to JSON serializable types
        updated_report["_id"] = str(updated_report["_id"])

        for field in ["date", "created_date", "lastmodified_date", "approved_date"]:
            if field in updated_report and isinstance(updated_report[field], datetime):
                updated_report[field] = updated_report[field].isoformat()

        return JsonResponse(updated_report, safe=False, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
    finally:
        client.close()