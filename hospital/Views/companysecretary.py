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









# EXPIRY_WARNING_DAYS = 90


# def get_employee_email(employee_id):
#     if not employee_id:
#         return None
#     profile = profile_collection.find_one({"employeeId": employee_id})
#     return profile.get("email") if profile else None


# def run_licence_expiry_check():
#     today = timezone.now().date()
#     target_date = today + timedelta(days=EXPIRY_WARNING_DAYS)

#     sent = []
#     skipped = []

#     for record in licencemasterdetails.objects.all():
#         expiry_date = record.expiry_date
#         if not expiry_date:
#             continue

#         expiry_date_only = (
#             expiry_date.date() if hasattr(expiry_date, "date") else expiry_date
#         )
#         if expiry_date_only != target_date:
#             continue

#         incharge_email = get_employee_email(record.incharge)
#         respective_person_email = get_employee_email(record.respective_person)

#         if not incharge_email:
#             skipped.append({
#                 "licence_name": record.licence_name,
#                 "reason": f"No email found for incharge id {record.incharge}",
#             })
#             continue

#         subject = f"Licence Expiry Reminder: {record.licence_name}"
#         message = (
#             f"Dear Team,\n\n"
#             f"This is a reminder that the following licence is due to expire "
#             f"in {EXPIRY_WARNING_DAYS} days.\n\n"
#             f"Licence Name: {record.licence_name}\n"
#             f"Licence/Case/Ref Number: {record.license_number}\n"
#             f"Valid From: {record.valid_from}\n"
#             f"Expiry Date: {record.expiry_date}\n\n"
#             f"Please take the necessary action before the expiry date.\n\n"
#             f"Regards,\n"
#             f"Shanmuga Hospital Limited"
#         )

#         cc_list = [respective_person_email] if respective_person_email else []

#         try:
#             email = EmailMessage(
#                 subject=subject,
#                 body=message,
#                 from_email=settings.DEFAULT_FROM_EMAIL,
#                 to=[incharge_email],
#                 cc=cc_list,
#             )
#             email.send(fail_silently=False)
#             sent.append({
#                 "licence_name": record.licence_name,
#                 "to": incharge_email,
#                 "cc": cc_list,
#             })
#         except Exception as e:
#             skipped.append({
#                 "licence_name": record.licence_name,
#                 "reason": str(e),
#             })

#     return {
#         "success": True,
#         "target_date": str(target_date),
#         "sent_count": len(sent),
#         "sent": sent,
#         "skipped": skipped,
#     }


# # companysecretary/views.py

# from rest_framework.decorators import api_view
# from rest_framework.response import Response

# from .utils import run_licence_expiry_check


# @api_view(['GET'])
# def autoscheduler_email(request):
#     result = run_licence_expiry_check()
#     return Response(result)