from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from .models import StoresAssetsManagement, StoresAssetsmaintenance , recycle_asset, AssetMaintenanceRequest
from .serializer import StoresAssetsManagementSerializer, StoresAssetsmaintenanceSerializer, recycle_assetSerializer, AssetMaintenanceRequestSerializer
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
        department = request.GET.get('department')
        is_active_param = request.GET.get('is_active')

        queryset = StoresAssetsmaintenance.objects.all().order_by('-created_date')

        if from_date:
            queryset = queryset.filter(date__gte=from_date)

        if to_date:
            queryset = queryset.filter(date__lte=to_date)

        if department:
            from django.db.models import Q
            queryset = queryset.filter(Q(department=department) | Q(department__icontains=department))

        if is_active_param is not None and is_active_param != '':
            if is_active_param.lower() == 'true':
                queryset = queryset.filter(is_active=True)
            elif is_active_param.lower() == 'false':
                queryset = queryset.filter(is_active=False)

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

def generate_request_id():
    now = datetime.now()
    if now.month <= 3:
        fy_str = f"{(now.year - 1) % 100:02d}{now.year % 100:02d}"
    else:
        fy_str = f"{now.year % 100:02d}{(now.year + 1) % 100:02d}"
    prefix = f"SH/REQ/{fy_str}/"
    
    last_record = AssetMaintenanceRequest.objects.filter(request_id__startswith=prefix).order_by('-created_date').first()
    
    if last_record:
        last_id = last_record.request_id
        try:
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
def asset_maintenance_request_list_detail(request, pk=None):
    employee_id  = request.data.get('auth-user-id', 'system')
    branch_code = request.data.get('auth-branch-code', 'system')
    outlet_code = request.data.get('auth-outlet-code', 'system')

    if request.method == 'GET':
        from_date = request.GET.get('from_date')
        to_date = request.GET.get('to_date')
        status_filter = request.GET.get('status')
        asset_id = request.GET.get('asset_id')
        incharge_id = request.GET.get('incharge_id')
        requested_by_id = request.GET.get('requested_by_id')
        requested_by = request.GET.get('requested_by')

        queryset = AssetMaintenanceRequest.objects.filter(is_active__in=[True]).order_by('-created_date')

        if from_date:
            queryset = queryset.filter(date__gte=from_date)
        if to_date:
            queryset = queryset.filter(date__lte=to_date)
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        if asset_id:
            queryset = queryset.filter(asset_id=asset_id)
        if incharge_id:
            queryset = queryset.filter(incharge_id=incharge_id)
        if requested_by_id:
            from django.db.models import Q
            queryset = queryset.filter(Q(requested_by_id=requested_by_id) | Q(requested_by__icontains=requested_by_id) | Q(created_by=requested_by_id))
        elif requested_by:
            from django.db.models import Q
            queryset = queryset.filter(Q(requested_by__icontains=requested_by) | Q(requested_by_id=requested_by))

        if pk:
            obj = AssetMaintenanceRequest.objects.filter(pk=pk).first()
            if not obj:
                return Response({"error": "Maintenance request not found"}, status=404)
            serializer = AssetMaintenanceRequestSerializer(obj)
            data = serializer.data
            
            # Look up profile_collection for requested_by
            from ..dbcollection import profile_collection
            req_by_val = str(data.get('requested_by') or data.get('requested_by_id') or '').strip()
            if req_by_val:
                prof = profile_collection.find_one({"employeeId": req_by_val}, {"employeeName": 1, "name": 1, "_id": 0})
                if prof:
                    emp_name = prof.get("employeeName") or prof.get("name") or ""
                    if emp_name:
                        data['requested_by'] = f"{emp_name} ({req_by_val})"
            return Response(data)
        else:
            serializer = AssetMaintenanceRequestSerializer(queryset, many=True)
            data = serializer.data
            
            # Map requested_by employeeId -> Name (ID) from profile_collection
            req_emp_ids = set()
            for r in data:
                val = str(r.get('requested_by') or r.get('requested_by_id') or '').strip()
                if val:
                    req_emp_ids.add(val)
            
            if req_emp_ids:
                from ..dbcollection import profile_collection
                profiles = list(profile_collection.find(
                    {"employeeId": {"$in": list(req_emp_ids)}},
                    {"employeeId": 1, "employeeName": 1, "name": 1, "_id": 0}
                ))
                profile_map = {}
                for p in profiles:
                    e_id = str(p.get("employeeId") or "").strip()
                    e_name = p.get("employeeName") or p.get("name") or ""
                    if e_id and e_name:
                        profile_map[e_id] = e_name

                for r in data:
                    raw_val = str(r.get('requested_by') or r.get('requested_by_id') or '').strip()
                    if raw_val in profile_map:
                        r['requested_by'] = f"{profile_map[raw_val]} ({raw_val})"
                    elif r.get('requested_by_id') and str(r.get('requested_by_id')).strip() in profile_map:
                        r_id = str(r.get('requested_by_id')).strip()
                        r['requested_by'] = f"{profile_map[r_id]} ({r_id})"

            return Response(data)

    elif request.method == 'POST':
        data = request.data.copy()
        if not data.get('request_id'):
            data['request_id'] = generate_request_id()
        if not data.get('date'):
            data['date'] = datetime.now().strftime('%Y-%m-%d')
        data['created_by'] = employee_id
        data['branch_code'] = branch_code
        data['outlet_code'] = outlet_code

        # Format requested_by as Name (ID) using profile_collection lookup
        from ..dbcollection import profile_collection
        req_by_val = str(data.get('requested_by_id') or data.get('requested_by') or '').strip()
        if req_by_val:
            prof = profile_collection.find_one({"employeeId": req_by_val}, {"employeeName": 1, "name": 1, "_id": 0})
            if prof:
                emp_name = prof.get("employeeName") or prof.get("name") or ""
                if emp_name:
                    data['requested_by'] = f"{emp_name} ({req_by_val})"
                    data['requested_by_id'] = req_by_val

        # Fetch targeted asset to determine incharge assignment logic
        target_asset_id = data.get('asset_id')
        priority = data.get('priority', 'Low')

        if target_asset_id:
            asset_obj = StoresAssetsmaintenance.objects.filter(asset_id=target_asset_id).first()
            if asset_obj:
                data['asset_name'] = asset_obj.asset_name
                if asset_obj.incharge_id:
                    data['incharge_id'] = asset_obj.incharge_id
                    data['incharge_name'] = asset_obj.incharge_name

        # If Priority is High OR no Incharge assigned -> Auto-Approve immediately
        is_high_priority = (priority == 'High')
        is_no_incharge = not data.get('incharge_id')
        if is_high_priority or is_no_incharge:
            if not data.get('status') or data.get('status') == 'Pending':
                data['status'] = 'Approved'
                data['approved_by'] = 'Auto-Approved (High Priority)' if is_high_priority else 'System Auto-Approval (No Incharge)'
                data['approval_date'] = datetime.now()
        else:
            if not data.get('status'):
                data['status'] = 'Pending'

        serializer = AssetMaintenanceRequestSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response({
                "message": "Request created successfully",
                "data": serializer.data
            }, status=201)

        return Response(serializer.errors, status=400)

    elif request.method == 'PATCH':
        obj = AssetMaintenanceRequest.objects.filter(pk=pk).first()
        if not obj:
            return Response({"error": "Maintenance request not found"}, status=404)

        if hasattr(obj, 'service_cost') and obj.service_cost is not None:
            try:
                obj.service_cost = float(str(obj.service_cost))
            except Exception:
                obj.service_cost = 0.0

        data = request.data.copy()
        data['lastmodified_by'] = employee_id

        new_status = data.get('status')
        if new_status == 'Approved' and obj.status != 'Approved':
            data['approval_date'] = datetime.now()
            data['approved_by'] = data.get('approved_by', employee_id)
        elif new_status == 'Completed' and obj.status != 'Completed':
            completion_dt = datetime.now()
            data['completion_date'] = completion_dt
            data['completed_by'] = data.get('completed_by', employee_id)

            # Update asset maintenance details & last_service_date
            asset_obj = StoresAssetsmaintenance.objects.filter(asset_id=obj.asset_id).first()
            if asset_obj:
                service_date_str = completion_dt.strftime('%Y-%m-%d')
                logs = list(asset_obj.maintenance_details or [])
                new_log_desc = data.get('service_remarks', obj.service_remarks or obj.description or 'Completed Maintenance Request')
                new_log_cost = float(data.get('service_cost', obj.service_cost) or 0)
                
                # Deduplication check: do not append if identical log already exists
                already_exists = any(
                    (str(log.get('service_date')) == service_date_str and
                     str(log.get('service_description')) == str(new_log_desc))
                    for log in logs
                )
                if not already_exists:
                    logs.append({
                        "service_date": service_date_str,
                        "service_cost": new_log_cost,
                        "service_description": new_log_desc,
                        "service_by": data.get('completed_by', employee_id)
                    })
                    asset_obj.maintenance_details = logs
                    asset_obj.last_service_date = service_date_str
                    asset_obj.save()
                asset_obj.save()

        serializer = AssetMaintenanceRequestSerializer(obj, data=data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({
                "message": "Request updated successfully",
                "data": serializer.data
            })

        return Response(serializer.errors, status=400)

