import datetime
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.utils import timezone
from datetime import datetime, timedelta
from pyauth.auth import HasRoleAndDataPermission

from .models import Complaint
from .serializer import ComplaintSerializer

def populate_reporter_names(data):
    if not data:
        return data
        
    is_list = isinstance(data, list)
    items = data if is_list else [data]
    
    reporter_ids = list(set([item.get('reporter') for item in items if item.get('reporter')]))
    if not reporter_ids:
        for item in items:
            item['reporter_name'] = item.get('reporter')
        return data
        
    try:
        import os
        from pymongo import MongoClient
        mongo_host = os.getenv("GLOBAL_DB_HOST")
        client = MongoClient(mongo_host)
        global_db = client['Global']
        profile_coll = global_db['backend_diagnostics_profile']
        
        profiles = list(profile_coll.find({"employeeId": {"$in": reporter_ids}}, {"employeeId": 1, "employeeName": 1}))
        profile_map = {p.get('employeeId'): p.get('employeeName') for p in profiles}
        client.close()
    except Exception as e:
        print(f"Error populating reporter names: {e}")
        profile_map = {}
        
    for item in items:
        rep_id = item.get('reporter')
        item['reporter_name'] = profile_map.get(rep_id, rep_id)
        
    return data

@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
def complaint_list_create(request):
    employee_id = request.data.get('auth-user-id', 'system')
    branch_code = request.data.get('auth-branch-code', 'system')
    outlet_code = request.data.get('auth-outlet-code', 'system')
    hospital_code = request.data.get('auth-hospital-code', 'system')

    if request.method == 'GET':
        # If employee_id query param is provided, filter by reporter
        reporter_id = request.query_params.get('employee_id')
        if reporter_id:
            complaints = Complaint.objects.filter(reporter=reporter_id).order_by('-reported_date')
        else:
            complaints = Complaint.objects.all().order_by('-reported_date')
            
        serializer = ComplaintSerializer(complaints, many=True)
        return Response(populate_reporter_names(serializer.data))

    elif request.method == 'POST':
        data = request.data.copy()
        
        # Set audit and defaults
        data['created_by'] = employee_id
        data['branch_code'] = branch_code
        data['outlet_code'] = outlet_code
        data['hospital_code'] = hospital_code
        
        if not data.get('reporter'):
            data['reporter'] = employee_id
            
        if not data.get('status'):
            data['status'] = 'Pending'
            
        serializer = ComplaintSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
def complaint_detail(request, pk):
    employee_id = request.data.get('auth-user-id', 'system')
    branch_code = request.data.get('auth-branch-code', 'system')
    outlet_code = request.data.get('auth-outlet-code', 'system')
    hospital_code = request.data.get('auth-hospital-code', 'system')

    complaint = get_object_or_404(Complaint, pk=pk)

    if request.method == 'GET':
        serializer = ComplaintSerializer(complaint)
        return Response(populate_reporter_names(serializer.data))

    elif request.method == 'PATCH':
        data = request.data.copy()
        data['lastmodified_by'] = employee_id
        data['branch_code'] = branch_code
        data['outlet_code'] = outlet_code
        data['hospital_code'] = hospital_code
        
        # If status is changing to Completed, auto-populate final completion date
        if data.get('status') == 'Completed' and complaint.status != 'Completed' and not data.get('final_completion_date'):
            data['final_completion_date'] = timezone.now().date().strftime('%Y-%m-%d')

        serializer = ComplaintSerializer(complaint, data=data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        complaint.delete()
        return Response({"message": "Complaint deleted successfully"}, status=status.HTTP_204_NO_CONTENT)

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def complaints_admin_list(request):
    from_date = request.query_params.get('from_date')
    to_date = request.query_params.get('to_date')

    # Defaults to last 15 days
    if not from_date:
        from_date = (timezone.now() - timedelta(days=15)).strftime('%Y-%m-%d')
    if not to_date:
        to_date = timezone.now().strftime('%Y-%m-%d')

    try:
        from_dt = datetime.strptime(from_date, '%Y-%m-%d').date()
        to_dt = datetime.strptime(to_date, '%Y-%m-%d').date()
    except ValueError:
        return Response({"error": "Invalid date format. Use YYYY-MM-DD."}, status=status.HTTP_400_BAD_REQUEST)

    # Fetch all complaints to filter in Python memory, avoiding Djongo translation anomalies
    all_complaints = Complaint.objects.all().order_by('-reported_date')
    
    pending_list = []
    completed_list = []
    
    for c in all_complaints:
        c_status = (c.status or "Pending").strip().lower()
        if c_status == 'completed':
            rep_date = c.reported_date.date() if hasattr(c.reported_date, 'date') else c.reported_date
            # Check if within date range
            if from_dt <= rep_date <= to_dt:
                completed_list.append(c)
        else:
            pending_list.append(c)

    pending_serializer = ComplaintSerializer(pending_list, many=True)
    completed_serializer = ComplaintSerializer(completed_list, many=True)

    return Response({
        "pending": populate_reporter_names(pending_serializer.data),
        "completed": populate_reporter_names(completed_serializer.data),
        "from_date": from_date,
        "to_date": to_date
    })

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def complaints_departments(request):
    try:
        import os
        from pymongo import MongoClient
        mongo_host = os.getenv("GLOBAL_DB_HOST")
        client = MongoClient(mongo_host)
        global_db = client['Global']
        dept_collection = global_db['backend_diagnostics_Departments']
        
        depts = list(dept_collection.find({}, {"department_code": 1, "department_name": 1, "_id": 0}))
        client.close()
        return Response(depts, status=200)
    except Exception as e:
        return Response({"error": str(e)}, status=500)
