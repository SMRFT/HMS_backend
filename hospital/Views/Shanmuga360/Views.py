from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from .models import registration360
from .serializer import registration360Serializer
from ..dbcollection import (
    shanmuga360_collection,
    doctor_list,
    Diagnostics_test_details,
    profile_collection,
    sample_collector as SAMPLE_COLLECTOR_ROLE,
)



# Auth/permissions
from pyauth.auth import HasRoleAndDataPermission, HasRolePermission
from rest_framework.decorators import api_view, permission_classes


@api_view(['POST', 'GET'])
@permission_classes([HasRoleAndDataPermission])
def shanmuga360_registration(request):
    """
    GET  - List all 360 registration records.
    POST - Create a new 360 registration record.
    """
    if request.method == 'GET':
        records = registration360.objects.all().order_by('-date')
        serializer = registration360Serializer(records, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    elif request.method == 'POST':
        data = request.data.copy() 
        employee_id = data.get("auth-user-id") 
        if employee_id:
            data['created_by'] = employee_id
        data['created_date'] = timezone.now()
        data['lastmodified_by'] = None
        data['lastmodified_date'] = None
        serializer = registration360Serializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(
                {'message': 'Registration saved successfully', 'data': serializer.data},
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_360_medicinelist(request):
    """
    GET - Returns all active medicines from shanmuga360_collection (is_active: True).
    Returns: title, category, product_price
    """
    try:
        medicines = shanmuga360_collection.find(
            {"is_active": True},
            {"_id": 0, "title": 1, "category": 1, "product_price": 1}
        )
        result = []
        for med in medicines:
            result.append({
                "title": med.get("title", ""),
                "category": med.get("category", ""),
                "product_price": float(med.get("product_price", 0)),
            })
        return Response(result, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])  
@permission_classes([HasRoleAndDataPermission])
def get_360_doctorlist(request):
    """
    GET - Returns all active doctors from doctor_list (is_active: True).
    Returns: doctor_name list
    """
    try:
        doctors = doctor_list.find(
            {"is_active": True},
            {"_id": 0, "doctor_name": 1}
        )
        result = [doc.get("doctor_name", "") for doc in doctors if doc.get("doctor_name")]
        return Response(result, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET']) 
@permission_classes([HasRoleAndDataPermission]) 
def get_360_testlist(request):
    """
    GET - Returns all active tests from Diagnostics_test_details (is_active: True).
    Returns: list of dicts with test_name and amount
    """
    try:
        tests = Diagnostics_test_details.find(
            {"is_active": True},
            {"_id": 0, "test_name": 1, "SH_Rate": 1, "MRP": 1, "Credit_Rate": 1, "price": 1, "amount": 1, "rate": 1}
        )
        seen = set()
        result = []
        for t in tests:
            name = t.get("test_name")
            if name and isinstance(name, str) and name.strip() and name.strip() not in seen:
                seen.add(name.strip())
                raw_amt = t.get("SH_Rate") or t.get("MRP") or t.get("Credit_Rate") or t.get("price") or t.get("amount") or t.get("rate") or 0
                try:
                    amt = float(str(raw_amt).replace(",", "").strip())
                except (ValueError, TypeError):
                    amt = 0.0
                result.append({
                    "test_name": name.strip(),
                    "amount": amt
                })
        result.sort(key=lambda x: x["test_name"])
        return Response(result, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


from django.db.models import Q
from django.utils.dateparse import parse_date


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def shanmuga360_report(request):
    """
    GET - Retrieve 360 registration reports filtered by date range (from_date, to_date).
    Supports: ?from_date=YYYY-MM-DD&to_date=YYYY-MM-DD&search=...
    """
    try:
        from_date = request.query_params.get('from_date') or request.GET.get('from_date')
        to_date = request.query_params.get('to_date') or request.GET.get('to_date')
        search = request.query_params.get('search') or request.GET.get('search')

        records = registration360.objects.all()

        if from_date and from_date.strip():
            d_from = parse_date(from_date.strip()) or from_date.strip()
            records = records.filter(date__gte=d_from)

        if to_date and to_date.strip():
            d_to = parse_date(to_date.strip()) or to_date.strip()
            records = records.filter(date__lte=d_to)

        if search and search.strip():
            s = search.strip()
            records = records.filter(
                Q(patient_name__icontains=s) |
                Q(mobile_number__icontains=s) |
                Q(bill_number__icontains=s) |
                Q(medicine_bill_number__icontains=s) |
                Q(lab_test_bill_number__icontains=s) |
                Q(labtestbillnumber__icontains=s) |
                Q(staff_name__icontains=s) |
                Q(home_care_type__icontains=s) |
                Q(reference_id__icontains=s) |
                Q(order_id__icontains=s)
            )

        records = records.order_by('-date', '-created_date')
        serializer = registration360Serializer(records, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_sample_collector(request):
    """
    GET - Returns names of employees having sample_collector role
    in primaryRole or additionalRoles from profile_collection.
    """
    try:
        query = {
            "$or": [
                {"primaryRole": SAMPLE_COLLECTOR_ROLE},
                {"additionalRoles": SAMPLE_COLLECTOR_ROLE}
            ]
        }
        profiles = profile_collection.find(
            query,
            {"_id": 0, "employeeName": 1, "employeeId": 1}
        )
        seen = set()
        result = []
        for p in profiles:
            name = p.get("employeeName")
            if name and isinstance(name, str) and name.strip() and name.strip() not in seen:
                seen.add(name.strip())
                result.append(name.strip())
        result.sort()
        return Response(result, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


sample_collector = get_sample_collector


