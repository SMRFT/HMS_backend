from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from ..models import AnesMaster
from pyauth.auth import HasRoleAndDataPermission
from django.utils import timezone
import traceback


def generate_anes_id():
    try:
        records = AnesMaster.objects.all().values("anesthesia_id")

        max_num = 0

        for r in records:
            anes_id = r.get("anesthesia_id", "")

            if anes_id.startswith("ANES"):
                try:
                    num = int(anes_id.replace("ANES", ""))
                    if num > max_num:
                        max_num = num
                except:
                    pass

        new_id = max_num + 1
        return f"ANES{str(new_id).zfill(2)}"

    except Exception:
        return "ANES01"


# ─── CREATE ───────────────────────────────────────────────────────────────────
@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def create_anes(request):
    try:
        data = request.data
        user_id       = data.get('auth-user-id', 'system')
        branch_code   = data.get('auth-branch-code', 'system')
        hospital_code = data.get('auth-hospital-code', 'system')

        anesthesia_name   = data.get('anesthesia_name', '').strip()
        type_of_anesthesia = data.get('type_of_anesthesia', '').strip()
        admin_guide       = data.get('admin_guide', '').strip()
        description       = data.get('description', '').strip()

        # Validation
        if not anesthesia_name:
            return Response(
                {"success": False, "message": "Anesthesia Name is required"},
                status=400
            )

        if not type_of_anesthesia:
            return Response(
                {"success": False, "message": "Type of Anesthesia is required"},
                status=400
            )

        # Duplicate check (same name + branch, active records only)
        existing = AnesMaster.objects.filter(
            anesthesia_name__iexact=anesthesia_name,
            branch_code=branch_code
        ).values()

        if any(o.get("is_active") == True for o in existing):
            return Response(
                {"success": False, "message": "Anesthesia with the same name already exists in this branch"},
                status=400
            )

        anes = AnesMaster.objects.create(
            anesthesia_id=generate_anes_id(),
            anesthesia_name=anesthesia_name,
            type_of_anesthesia=type_of_anesthesia,
            admin_guide=admin_guide,
            description=description,
            branch_code=branch_code,
            hospital_code=hospital_code,
            created_by=user_id,
        )

        return Response({
            "success": True,
            "message": "Anesthesia created successfully",
            "data": _serialize(anes)
        }, status=201)

    except Exception as e:
        return Response({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }, status=500)


# ─── LIST ─────────────────────────────────────────────────────────────────────
@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def list_anes(request):
    try:
        records = AnesMaster.objects.all().values()

        # Filter active records in Python (safe for custom boolean fields)
        filtered = [r for r in records if r.get("is_active") == True]

        return Response({
            "success": True,
            "data": filtered
        })

    except Exception as e:
        return Response({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        })


# ─── UPDATE ───────────────────────────────────────────────────────────────────
@api_view(['PUT'])
@permission_classes([HasRoleAndDataPermission])
def update_anes(request, anesthesia_id):
    try:
        data = request.data
        user_id = data.get('auth-user-id', 'system')

        anes = AnesMaster.objects.filter(anesthesia_id=anesthesia_id).first()

        if not anes or not anes.is_active:
            return Response(
                {"success": False, "message": "Anesthesia record not found"},
                status=404
            )

        anes.anesthesia_name    = data.get('anesthesia_name', anes.anesthesia_name).strip()
        anes.type_of_anesthesia = data.get('type_of_anesthesia', anes.type_of_anesthesia).strip()
        anes.admin_guide        = data.get('admin_guide', anes.admin_guide).strip()
        anes.description        = data.get('description', anes.description).strip()
        anes.lastmodified_by    = user_id
        anes.lastmodified_date  = timezone.now()
        anes.save()

        return Response({
            "success": True,
            "message": "Anesthesia updated successfully",
            "data": _serialize(anes)
        })

    except Exception as e:
        return Response({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }, status=500)


# ─── SOFT DELETE ──────────────────────────────────────────────────────────────
@api_view(['DELETE'])
@permission_classes([HasRoleAndDataPermission])
def delete_anes(request, anesthesia_id):
    try:
        user_id = request.data.get('auth-user-id', 'system')

        anes = AnesMaster.objects.filter(anesthesia_id=anesthesia_id).first()

        if not anes or not anes.is_active:
            return Response(
                {"success": False, "message": "Anesthesia record not found"},
                status=404
            )

        anes.is_active         = False
        anes.lastmodified_by   = user_id
        anes.lastmodified_date = timezone.now()
        anes.save()

        return Response({
            "success": True,
            "message": "Anesthesia deleted successfully"
        })

    except Exception as e:
        return Response({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }, status=500)


# ─── SERIALIZER ───────────────────────────────────────────────────────────────
def _serialize(anes):
    return {
        "anesthesia_id":     anes.anesthesia_id,
        "anesthesia_name":   anes.anesthesia_name,
        "type_of_anesthesia": anes.type_of_anesthesia,
        "admin_guide":       anes.admin_guide,
        "description":       anes.description,
        "branch_code":       anes.branch_code,
        "hospital_code":     anes.hospital_code,
        "created_by":        anes.created_by,
        "created_date":      anes.created_date,
        "lastmodified_by":   anes.lastmodified_by,
        "lastmodified_date": anes.lastmodified_date,
        "is_active":         anes.is_active,
    }