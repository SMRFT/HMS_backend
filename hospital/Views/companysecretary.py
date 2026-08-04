from rest_framework.decorators import api_view
from rest_framework.response import Response
from decimal import Decimal, InvalidOperation
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from django.http import JsonResponse
from django.utils import timezone
from rest_framework import status
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from pyauth.auth import HasRoleAndDataPermission
import traceback
import json
import ast
from datetime import datetime, date
from ..models import licencemasterdetails,licence_master
from ..serializers import licencemasterdetailsSerializer,licence_masterSerializer
from .dbcollection import profile_collection,user_collection
from django.conf import settings
from django.core.mail import EmailMessage
from datetime import timedelta




from django.utils import timezone
from rest_framework.response import Response
from rest_framework import status

@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
def get_licence_master(request):
    """
    GET: Returns all licence master records
    POST: Creates a new licence master record
    """

    if request.method == 'GET':
        queryset = licence_master.objects.all().order_by('s_no')
        serializer = licence_masterSerializer(queryset, many=True)
        return Response(serializer.data)

    # ✅ POST
    data = request.data.copy()

    # Get employee id from header/body
    employee_id = request.headers.get('auth-user-id') or data.get('auth-user-id')

    # Add audit fields
    data['created_by'] = employee_id
    data['created_date'] = timezone.now()

    serializer = licence_masterSerializer(data=data)
    
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)




@api_view(['GET', 'POST', 'PUT'])
@permission_classes([HasRoleAndDataPermission])
def licence_master_details(request, s_no=None):
    if request.method == 'GET':
        queryset = licencemasterdetails.objects.all().order_by('s_no')
        serializer = licencemasterdetailsSerializer(queryset, many=True)
        return Response(serializer.data)
 
    if request.method == 'POST':
        data = request.data.copy()
        employee_id = data.get('auth-user-id')
        data['created_by'] = employee_id
        data['created_date'] = timezone.now()
 
        serializer = licencemasterdetailsSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
 
    # PUT - update existing record by s_no
    try:
        instance = licencemasterdetails.objects.get(s_no=s_no)
    except licencemasterdetails.DoesNotExist:
        return Response({'error': 'Record not found'}, status=status.HTTP_404_NOT_FOUND)
 
    data = request.data.copy()
    data['lastmodified_by'] = data.get('auth-user-id')
    # lastmodified_date has auto_now=True, so it stamps itself on instance.save() below —
    # no need to set it manually here.
 
    serializer = licencemasterdetailsSerializer(instance, data=data, partial=True)
    if serializer.is_valid():
        for attr, value in serializer.validated_data.items():
            setattr(instance, attr, value)
        instance.save()  # explicit update on the already-fetched instance
        return Response(
            licencemasterdetailsSerializer(instance).data,
            status=status.HTTP_200_OK
        )
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
 
 
@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_incharge_list(request):
    """
    Incharge dropdown source: employeeId, employeeName, email from the
    global profile collection, filtered to only employees whose account
    is_active=True in the global user collection.
    """
    active_employee_ids = {
        doc.get('employeeId')
        for doc in user_collection.find({'is_active': True}, {'employeeId': 1})
    }
 
    employees = profile_collection.find(
        {'employeeId': {'$in': list(active_employee_ids)}},
        {'employeeId': 1, 'employeeName': 1, 'email': 1, '_id': 0}
    )
 
    result = [
        {
            'employeeId': emp.get('employeeId'),
            'employeeName': emp.get('employeeName'),
            'email': emp.get('email'),
        }
        for emp in employees
    ]
    return Response(result)
 
 
@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def licence_renewal(request, s_no):
    """
    POST /licence_master_details/<s_no>/renew/
    Body: { "renewal_date": "2026-03-25", "expiry_date": "2026-04-30" }
 
    Kept separate from the generic PUT branch above on purpose: this is the
    ONLY code path that sets renewal_date and appends a history entry
    (via instance.save(is_renewal=True)). Plain field edits through the
    PUT branch never touch history or renewal_date.
    """
    try:
        instance = licencemasterdetails.objects.get(s_no=s_no)
    except licencemasterdetails.DoesNotExist:
        return Response({'error': 'Record not found'}, status=status.HTTP_404_NOT_FOUND)
 
    renewal_date = request.data.get('renewal_date')
    new_expiry_date = request.data.get('expiry_date')
 
    if not renewal_date or not new_expiry_date:
        return Response(
            {'error': 'renewal_date and expiry_date are required'},
            status=status.HTTP_400_BAD_REQUEST,
        )
 
    instance.renewal_date = renewal_date
    instance.expiry_date = new_expiry_date
    instance.renewwed_by = request.data.get('auth-user-id')
    instance.lastmodified_by = request.data.get('auth-user-id')
    instance.save(is_renewal=True)
 
    return Response(
        licencemasterdetailsSerializer(instance).data,
        status=status.HTTP_200_OK,
    )
 