from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from .models import StoresAssetsManagement, StoresAssetsmaintenance , recycle_asset
from .serializer import StoresAssetsManagementSerializer, StoresAssetsmaintenanceSerializer, recycle_assetSerializer
from rest_framework.permissions import AllowAny
from datetime import datetime
from pyauth.auth import HasRoleAndDataPermission

def generate_asset_id():
    now = datetime.now()
    if now.month <= 3:
        fy_str = f"{(now.year - 1) % 100:02d}{now.year % 100:02d}"
    else:
        fy_str = f"{now.year % 100:02d}{(now.year + 1) % 100:02d}"
    prefix = f"SH/{fy_str}/"
    
    last_record = StoresAssetsManagement.objects.filter(asset_id__startswith=prefix).order_by('-created_date').first()
    
    if last_record:
        last_id = last_record.asset_id
        try:
            # Extract sequence number from "SH/2526/00001"
            last_sequence_str = last_id.split('/')[-1]
            last_sequence = int(last_sequence_str)
            new_sequence = last_sequence + 1
        except (ValueError, IndexError):
            new_sequence = 1
    else:
        new_sequence = 1
        
    return f"{prefix}{new_sequence:05d}"

@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
def stores_assets_management_list_create(request):
    employee_id  = request.data.get('auth-user-id', 'system')
    branch_code = request.data.get('auth-branch-code', 'system')
    outlet_code = request.data.get('auth-outlet-code', 'system')
    hospital_code = request.data.get('auth-hospital-code', 'system')
    
    if request.method == 'GET':
        from_date = request.query_params.get('from_date')
        to_date = request.query_params.get('to_date')

        queryset = StoresAssetsManagement.objects.all().order_by('-created_date')

        if from_date:
            queryset = queryset.filter(date__gte=from_date)
        if to_date:
            queryset = queryset.filter(date__lte=to_date)

        serializer = StoresAssetsManagementSerializer(queryset, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        data = request.data.copy()
        if not data.get('asset_id'):
            data['asset_id'] = generate_asset_id()
            if not data.get('barcode'):
                data['barcode'] = data['asset_id']
        
        data['created_by'] = employee_id
        data['branch_code'] = branch_code
        data['outlet_code'] = outlet_code

        serializer = StoresAssetsManagementSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
def stores_assets_management_detail(request, pk):
    employee_id  = request.data.get('auth-user-id', 'system')
    branch_code = request.data.get('auth-branch-code', 'system')
    outlet_code = request.data.get('auth-outlet-code', 'system')
    hospital_code = request.data.get('auth-hospital-code', 'system')

    try:
        item = StoresAssetsManagement.objects.filter(pk=pk).first()
        if not item:
            return Response({"error": "Asset not found or already deleted"}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    if request.method == 'GET':
        serializer = StoresAssetsManagementSerializer(item)
        return Response(serializer.data)

    elif request.method == 'PATCH':
        from django.utils import timezone
        data = request.data.copy()
        if data.get('is_active') == False:
            data['deactivated_date'] = timezone.now()
        elif data.get('is_active') == True:
            data['deactivated_date'] = None

        data['lastmodified_by'] = employee_id
        data['branch_code'] = branch_code
        data['outlet_code'] = outlet_code

        serializer = StoresAssetsManagementSerializer(item, data=data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        from django.utils import timezone
        item.is_active = False
        item.deactivated_date = timezone.now()
        item.save()
        return Response({"message": "Asset soft deleted successfully"}, status=status.HTTP_204_NO_CONTENT)

from .models import StoresAssetsmaintenance
from .serializer import StoresAssetsmaintenanceSerializer

from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from datetime import datetime

def generate_maintenance_id():
    now = datetime.now()
    if now.month <= 3:
        fy_str = f"{(now.year - 1) % 100:02d}{now.year % 100:02d}"
    else:
        fy_str = f"{now.year % 100:02d}{(now.year + 1) % 100:02d}"
    prefix = f"SH/MNT/{fy_str}/"
    
    last_record = StoresAssetsmaintenance.objects.filter(asset_id__startswith=prefix).order_by('-created_date').first()
    
    if last_record:
        last_id = last_record.asset_id
        try:
            # Extract sequence number from "SH/2526/00001"
            last_sequence_str = last_id.split('/')[-1]
            last_sequence = int(last_sequence_str)
            new_sequence = last_sequence + 1
        except (ValueError, IndexError):
            new_sequence = 1
    else:
        new_sequence = 1
        
    return f"{prefix}{new_sequence:05d}"

@api_view(['GET', 'POST', 'PATCH'])
@permission_classes([HasRoleAndDataPermission])
def stores_assets_maintenance_details(request, pk=None):
    employee_id  = request.data.get('auth-user-id', 'system')
    branch_code = request.data.get('auth-branch-code', 'system')
    outlet_code = request.data.get('auth-outlet-code', 'system')
    hospital_code = request.data.get('auth-hospital-code', 'system')

    # =========================
    # ✅ GET (with date filter)
    # =========================
    if request.method == 'GET':
        from_date = request.GET.get('from_date')
        to_date = request.GET.get('to_date')

        queryset = StoresAssetsmaintenance.objects.all().order_by('-created_date')

        if from_date:
            queryset = queryset.filter(date__gte=from_date)

        if to_date:
            queryset = queryset.filter(date__lte=to_date)

        # single or list
        if pk:
            obj = get_object_or_404(queryset, pk=pk)
            serializer = StoresAssetsmaintenanceSerializer(obj)
        else:
            serializer = StoresAssetsmaintenanceSerializer(queryset, many=True)

        return Response(serializer.data)

    # =========================
    # ✅ POST (create)
    # =========================
    elif request.method == 'POST':
        data = request.data.copy()
        if not data.get('asset_id'):
            data['asset_id'] = generate_maintenance_id()
        if not data.get('barcode'):
            data['barcode'] = data['asset_id']
        data['created_by'] = employee_id
        data['branch_code'] = branch_code
        data['outlet_code'] = outlet_code

        serializer = StoresAssetsmaintenanceSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response({
                "message": "Created successfully",
                "data": serializer.data
            })

        return Response(serializer.errors, status=400)

    # =========================
    # ✅ PATCH (update all fields)
    # =========================
    elif request.method == 'PATCH':
        obj = get_object_or_404(StoresAssetsmaintenance, pk=pk)
        data = request.data.copy()
        data['lastmodified_by'] = employee_id
        data['branch_code'] = branch_code
        data['outlet_code'] = outlet_code

        if "maintenance_details" in data:
            new_data = data.get("maintenance_details", [])

            if isinstance(new_data, list):
                # Simply replace the logs array directly, as the frontend sends the *complete* modified array
                data["maintenance_details"] = new_data
            elif isinstance(new_data, str):
                import json
                try:
                    data["maintenance_details"] = json.loads(new_data)
                except Exception:
                    data["maintenance_details"] = []
            else:
                return Response(
                    {"error": "maintenance_details must be list"},
                    status=400
                )

        serializer = StoresAssetsmaintenanceSerializer(
            obj,
            data=data,
            partial=True  # allow updating all or partial fields

        )

        if serializer.is_valid():
            serializer.save()
            return Response({
                "message": "Updated successfully",
                "data": serializer.data
            })

        return Response(serializer.errors, status=400)

def generate_recycle_id():
    now = datetime.now()
    if now.month <= 3:
        fy_str = f"{(now.year - 1) % 100:02d}{now.year % 100:02d}"
    else:
        fy_str = f"{now.year % 100:02d}{(now.year + 1) % 100:02d}"
    prefix = f"SH/RCY/{fy_str}/"
    
    last_record = recycle_asset.objects.filter(asset_id__startswith=prefix).order_by('-created_date').first()
    
    if last_record:
        last_id = last_record.asset_id
        try:
            # Extract sequence number from "SH/RCY/2526/00001"
            last_sequence_str = last_id.split('/')[-1]
            last_sequence = int(last_sequence_str)
            new_sequence = last_sequence + 1
        except (ValueError, IndexError):
            new_sequence = 1
    else:
        new_sequence = 1
        
    return f"{prefix}{new_sequence:05d}"

@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
def create_recycle_asset(request):
    employee_id  = request.data.get('auth-user-id', 'system')
    branch_code = request.data.get('auth-branch-code', 'system')
    outlet_code = request.data.get('auth-outlet-code', 'system')
    hospital_code = request.data.get('auth-hospital-code', 'system')

    if request.method == 'GET':
        from_date = request.GET.get('from_date')
        to_date = request.GET.get('to_date')
        queryset = recycle_asset.objects.filter(is_active__in=[True]).order_by('-created_date')
        if from_date:
            queryset = queryset.filter(date__gte=from_date)
        if to_date:
            queryset = queryset.filter(date__lte=to_date)
        serializer = recycle_assetSerializer(queryset, many=True)
        return Response(serializer.data)
    elif request.method == 'POST':
        data = request.data.copy()
        if not data.get('asset_id'):
            data['asset_id'] = generate_recycle_id()
        data['created_by'] = employee_id
        data['branch_code'] = branch_code
        data['outlet_code'] = outlet_code

        serializer = recycle_assetSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response({
                "message": "Created successfully",
                "data": serializer.data
            })
        return Response(serializer.errors, status=400)
    return Response({"error": "Invalid request method"}, status=400)

@api_view(['GET', 'PATCH'])
@permission_classes([HasRoleAndDataPermission])
def update_recycle_asset(request, pk):
    employee_id  = request.data.get('auth-user-id', 'system')
    branch_code = request.data.get('auth-branch-code', 'system')
    outlet_code = request.data.get('auth-outlet-code', 'system')
    hospital_code = request.data.get('auth-hospital-code', 'system')

    if request.method == 'GET':
        queryset = recycle_asset.objects.filter(is_active__in=[True]).order_by('-created_date')
        serializer = recycle_assetSerializer(queryset, many=True)
        return Response(serializer.data)
    elif request.method == 'PATCH':
        data = request.data.copy()
        data['lastmodified_by'] = employee_id
        data['branch_code'] = branch_code
        data['outlet_code'] = outlet_code
        
        obj = get_object_or_404(recycle_asset, pk=pk)
        serializer = recycle_assetSerializer(obj, data=data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({
                "message": "Updated successfully",
                "data": serializer.data
            })
        return Response(serializer.errors, status=400)
    return Response({"error": "Invalid request method"}, status=400)
