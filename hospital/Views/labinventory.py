from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from ..models import LabInventory,RaiseIndent
from ..serializers import LabInventorySerializer,RaiseIndentSerializer


# auth:
from pyauth.auth import HasRoleAndDataPermission
from rest_framework.decorators import api_view, permission_classes


import json

@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
def dealer_items(request):

    if request.method == 'POST':
        data_in = request.data

        hospital_code = data_in.get("auth-hospital-code")
        branch_code   = data_in.get("auth-branch-code")
        
        employee_id   = data_in.get("auth-user-id")

        dealer_name = (data_in.get('dealer_name') or "").strip()
        items = data_in.get('items')

        if not isinstance(items, list):
            return Response(
                {"error": "items must be an array (list)"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ✅ Look for an existing dealer with the same name (scoped to hospital/branch/outlet)
        existing = LabInventory.objects.filter(
            dealer_name__iexact=dealer_name,
            hospital_code=hospital_code,
            branch_code=branch_code,
           
        ).first()

        if existing:
            existing_items = existing.items
            # normalize legacy rows where items was stored as a JSON string
            if isinstance(existing_items, str):
                try:
                    existing_items = json.loads(existing_items)
                except (TypeError, ValueError):
                    existing_items = []
            if not isinstance(existing_items, list):
                existing_items = []

            merged_items = existing_items + [i for i in items if i not in existing_items]

            serializer = LabInventorySerializer(
                existing, data={"items": merged_items}, partial=True
            )
            if serializer.is_valid():
                serializer.save(lastmodified_by=employee_id)
                return Response(serializer.data, status=200)
            return Response(serializer.errors, status=400)

        # ✅ No existing dealer — create new
        data = {
            "dealer_name": dealer_name,
            "items": items,
            "hospital_code": hospital_code,
            "branch_code": branch_code,
            
        }
        serializer = LabInventorySerializer(data=data)
        if serializer.is_valid():
            serializer.save(created_by=employee_id)
            return Response(serializer.data, status=201)

        return Response(serializer.errors, status=400)

    elif request.method == 'GET':
        hospital_code = request.query_params.get("auth-hospital-code")
        branch_code   = request.query_params.get("auth-branch-code")

        queryset = LabInventory.objects.all()
        if hospital_code:
            queryset = queryset.filter(hospital_code=hospital_code)
        if branch_code:
            queryset = queryset.filter(branch_code=branch_code)

        data = queryset.order_by('-dealer_id')
        serializer = LabInventorySerializer(data, many=True)
        return Response(serializer.data)




@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
def raise_indent(request):
    if request.method == 'POST':
        data_in = request.data

        hospital_code = data_in.get("auth-hospital-code")
        branch_code   = data_in.get("auth-branch-code")
       
        employee_id   = data_in.get("auth-user-id")

        dealer_items_val = data_in.get("dealer_items")
        if not isinstance(dealer_items_val, list):
            return Response(
                {"error": "dealer_items must be an array (list)"},
                status=status.HTTP_400_BAD_REQUEST
            )

        data = {
            "dealer_items": dealer_items_val,
            "requirements": data_in.get("requirements"),
            "stock": data_in.get("stock"),
            "status": data_in.get("status", "Raised"),
            "hospital_code": hospital_code,
            "branch_code": branch_code,
           
        }

        serializer = RaiseIndentSerializer(data=data)
        if serializer.is_valid():
            serializer.save(created_by=employee_id)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # GET
    hospital_code = request.query_params.get("auth-hospital-code")
    branch_code   = request.query_params.get("auth-branch-code")

    queryset = RaiseIndent.objects.all()
    if hospital_code:
        queryset = queryset.filter(hospital_code=hospital_code)
    if branch_code:
        queryset = queryset.filter(branch_code=branch_code)

    indents = queryset.order_by('-id')
    serializer = RaiseIndentSerializer(indents, many=True)
    return Response(serializer.data)