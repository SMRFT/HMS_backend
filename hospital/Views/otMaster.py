from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from ..models import OTMaster
from pyauth.auth import HasRoleAndDataPermission
from django.utils import timezone
import re, traceback

def generate_ot_id():
    try:
        ots = OTMaster.objects.all().values("ot_id")

        max_num = 0

        for ot in ots:
            ot_id = ot.get("ot_id", "")

            if ot_id.startswith("OT"):
                try:
                    num = int(ot_id.replace("OT", ""))
                    if num > max_num:
                        max_num = num
                except:
                    pass

        new_id = max_num + 1
        return f"OT{str(new_id).zfill(2)}"

    except Exception as e:
        return "OT01"

# ─── CREATE ───────────────────────────────────────────────────────────────────
@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def create_ot(request):
    try:
        data = request.data
        user_id      = data.get('auth-user-id', 'system')
        branch_code  = data.get('auth-branch-code', 'system')
        hospital_code = data.get('auth-hospital-code', 'system')

        ot_name      = data.get('ot_name', '').strip()
        availability = data.get('availability', 'Available').strip()
        capacity     = data.get('capacity', '').strip()

        # Validation
        if not ot_name:
            return Response({"success": False, "message": "OT Name is required"}, status=400)

        if not capacity:
            return Response({"success": False, "message": "Capacity is required"}, status=400)

        # ✅ FIXED duplicate check
        existing_ots = OTMaster.objects.filter(
            ot_name__iexact=ot_name,
            branch_code=branch_code
        ).values()

        if any(o.get("is_active") == True for o in existing_ots):
            return Response(
                {"success": False, "message": "OT with same name already exists in this branch"},
                status=400
            )

        # Create
        ot = OTMaster.objects.create(
            ot_id=generate_ot_id(),
            ot_name=ot_name,
            availability=availability,
            capacity=capacity,
            branch_code=branch_code,
            hospital_code=hospital_code,
            created_by=user_id,
        )

        return Response({
            "success": True,
            "message": "OT created successfully",
            "data": _serialize(ot)
        }, status=201)

    except Exception as e:
        import traceback
        return Response({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }, status=500)



@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def list_ots(request):
    try:
        ots = OTMaster.objects.all().values()   # ✅ no filter

        # manually filter in Python (safe)
        filtered = [o for o in ots if o.get("is_active") == True]

        return Response({
            "success": True,
            "data": filtered
        })

    except Exception as e:
        import traceback
        return Response({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        })
    
# ─── UPDATE ───────────────────────────────────────────────────────────────────
@api_view(['PUT'])
@permission_classes([HasRoleAndDataPermission])
def update_ot(request, ot_id):
    try:
        data = request.data
        user_id = data.get('auth-user-id', 'system')

        # ✅ FIXED QUERY (no boolean filter)
        ot = OTMaster.objects.filter(ot_id=ot_id).first()

        # ✅ manual check
        if not ot or not ot.is_active:
            return Response(
                {"success": False, "message": "OT not found"},
                status=404
            )

        ot.ot_name = data.get('ot_name', ot.ot_name).strip()
        ot.availability = data.get('availability', ot.availability).strip()
        ot.capacity = data.get('capacity', ot.capacity).strip()
        ot.lastmodified_by = user_id
        ot.lastmodified_date = timezone.now()
        ot.save()

        return Response({
            "success": True,
            "message": "OT updated successfully",
            "data": _serialize(ot)
        })

    except Exception as e:
        import traceback
        return Response({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }, status=500)

# ─── SOFT DELETE ──────────────────────────────────────────────────────────────
@api_view(['DELETE'])
@permission_classes([HasRoleAndDataPermission])
def delete_ot(request, ot_id):
    try:
        user_id = request.data.get('auth-user-id', 'system')

        # ✅ FIXED QUERY
        ot = OTMaster.objects.filter(ot_id=ot_id).first()

        # ✅ manual check
        if not ot or not ot.is_active:
            return Response(
                {"success": False, "message": "OT not found"},
                status=404
            )

        # Soft delete
        ot.is_active = False
        ot.lastmodified_by = user_id
        ot.lastmodified_date = timezone.now()
        ot.save()

        return Response({
            "success": True,
            "message": "OT deleted successfully"
        })

    except Exception as e:
        import traceback
        return Response({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }, status=500)

def _serialize(ot):
    return {
        "ot_id": ot.ot_id,   # ✅ use this instead
        "ot_name": ot.ot_name,
        "availability": ot.availability,
        "capacity": ot.capacity,
        "branch_code": ot.branch_code,
        "hospital_code": ot.hospital_code,
        "created_by": ot.created_by,
        "created_date": ot.created_date,
        "lastmodified_by": ot.lastmodified_by,
        "lastmodified_date": ot.lastmodified_date,
        "is_active": ot.is_active,
    }