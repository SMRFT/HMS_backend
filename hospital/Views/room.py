from rest_framework.response import Response
from django.http import JsonResponse
from rest_framework import status
from pymongo import MongoClient
import os
from rest_framework.decorators import api_view, permission_classes
from pyauth.auth import HasRoleAndDataPermission
from django.views.decorators.csrf import csrf_exempt
import json
from uuid import uuid4
from django.utils import timezone as tz
from datetime import datetime
import traceback

from ..models import Block, RoomCategory, Room, Admission, Patient, RoomBooking, RoomKitItems, RoomServiceDescription, NursingStation
from ..serializers import (
    BlockSerializer,
    RoomCategorySerializer,
    RoomSerializer,
    RoomKitItemsSerializer,
    RoomServiceDescriptionSerializer,
    NursingStationSerializer
)

# --------------------------------------------------
# BLOCK
# --------------------------------------------------
@api_view(["GET", "POST", "PUT", "DELETE"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def block_view(request, pk=None):

    employee_id = (
        request.data.get('auth-user-id') or
        request.headers.get('auth-user-id') or
        "system"
    )

    hospital_code = (
        request.data.get("auth-hospital-code") or
        request.headers.get("auth-hospital-code") or
        "system"
    )

    branch_code = (
        request.data.get("auth-branch-code") or
        request.headers.get("Branch-Code") or
        "system"
    )

    # ── GET ─────────────────────────────────────────────
    if request.method == "GET":

        if pk:
            try:
                block = Block.objects.get(
                    block_id=pk,
                    hospital_code=hospital_code,
                    branch_code=branch_code
                )

                if not block.is_active:
                    return Response({"error": "Block not found"}, status=404)

            except Block.DoesNotExist:
                return Response({"error": "Block not found"}, status=404)

            serializer = BlockSerializer(block)
            return Response(serializer.data)

        # list
        all_blocks = Block.objects.filter(
            hospital_code=hospital_code,
            branch_code=branch_code
        ).order_by("block_id")

        blocks = [b for b in all_blocks if b.is_active]

        serializer = BlockSerializer(blocks, many=True)
        return Response(serializer.data)


    # ── POST ─────────────────────────────────────────────
    if request.method == "POST":

        data = request.data.copy()
        data["hospital_code"] = hospital_code
        data["branch_code"] = branch_code

        serializer = BlockSerializer(data=data)
        if serializer.is_valid():
            serializer.save(
                created_by=employee_id,
                created_date=timezone.now(),
                is_active=True
            )
            return Response(serializer.data, status=201)

        return Response(serializer.errors, status=400)


    # ── PUT ─────────────────────────────────────────────
    if request.method == "PUT":

        if not pk:
            return Response({"error": "Block ID required"}, status=400)

        try:
            block = Block.objects.get(
                block_id=pk,
                hospital_code=hospital_code,
                branch_code=branch_code
            )

            if not block.is_active:
                return Response({"error": "Block not found"}, status=404)

        except Block.DoesNotExist:
            return Response({"error": "Block not found"}, status=404)

        serializer = BlockSerializer(block, data=request.data, partial=True)

        if serializer.is_valid():
            serializer.save(
                lastmodified_by=employee_id,
                lastmodified_date=timezone.now()
            )
            return Response(serializer.data)

        return Response(serializer.errors, status=400)


    # ── DELETE (SOFT DELETE) ─────────────────────────────
    if request.method == "DELETE":

        if not pk:
            return Response({"error": "Block ID required"}, status=400)

        try:
            block = Block.objects.get(
                block_id=pk,
                hospital_code=hospital_code,
                branch_code=branch_code
            )

            if not block.is_active:
                return Response({"error": "Block not found"}, status=404)

        except Block.DoesNotExist:
            return Response({"error": "Block not found"}, status=404)

        block.is_active = False
        block.lastmodified_by = employee_id
        block.lastmodified_date = timezone.now()
        block.save()

        return Response({"message": "Deleted successfully"}, status=200)
        

# --------------------------------------------------
# ROOM CATEGORY
# --------------------------------------------------
@api_view(["GET", "POST", "PUT", "DELETE"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def room_category_view(request, pk=None):

    employee_id = (
        request.data.get('auth-user-id') or
        request.headers.get('auth-user-id') or
        "system"
    )

    hospital_code = (
        request.data.get("auth-hospital-code") or
        request.headers.get("auth-hospital-code") or
        "system"
    )

    branch_code = (
        request.data.get("auth-branch-code") or
        request.headers.get("Branch-Code") or
        "system"
    )

    # ── GET ─────────────────────────────────────────
    if request.method == "GET":

        if pk:
            try:
                category = RoomCategory.objects.get(
                    room_category_id=pk,
                    hospital_code=hospital_code,
                    branch_code=branch_code
                )

                if not category.is_active:
                    return Response({"error": "Room category not found"}, status=404)

            except RoomCategory.DoesNotExist:
                return Response({"error": "Room category not found"}, status=404)

            serializer = RoomCategorySerializer(category)
            return Response(serializer.data)

        # list
        all_categories = RoomCategory.objects.filter(
            hospital_code=hospital_code,
            branch_code=branch_code
        ).order_by("room_category_id")

        categories = [c for c in all_categories if c.is_active]

        serializer = RoomCategorySerializer(categories, many=True)
        return Response(serializer.data)


    # ── POST ────────────────────────────────────────
    if request.method == "POST":

        data = request.data.copy()
        data["hospital_code"] = hospital_code
        data["branch_code"] = branch_code

        serializer = RoomCategorySerializer(data=data)

        if serializer.is_valid():
            serializer.save(
                created_by=employee_id,
                created_date=timezone.now(),
                lastmodified_by=employee_id,
                lastmodified_date=timezone.now(),
                is_active=True
            )
            return Response(serializer.data, status=201)

        return Response(serializer.errors, status=400)


    # ── PUT ─────────────────────────────────────────
    if request.method == "PUT":

        if not pk:
            return Response({"error": "Room Category ID required"}, status=400)

        try:
            category = RoomCategory.objects.get(
                room_category_id=pk,
                hospital_code=hospital_code,
                branch_code=branch_code
            )

            if not category.is_active:
                return Response({"error": "Room category not found"}, status=404)

        except RoomCategory.DoesNotExist:
            return Response({"error": "Room category not found"}, status=404)

        serializer = RoomCategorySerializer(
            category,
            data=request.data,
            partial=True
        )

        if serializer.is_valid():
            serializer.save(
                lastmodified_by=employee_id,
                lastmodified_date=timezone.now()
            )
            return Response(serializer.data)

        return Response(serializer.errors, status=400)


    # ── DELETE (SOFT DELETE) ─────────────────────────
    if request.method == "DELETE":

        if not pk:
            return Response({"error": "Room Category ID required"}, status=400)

        try:
            category = RoomCategory.objects.get(
                room_category_id=pk,
                hospital_code=hospital_code,
                branch_code=branch_code
            )

            if not category.is_active:
                return Response({"error": "Room category not found"}, status=404)

        except RoomCategory.DoesNotExist:
            return Response({"error": "Room category not found"}, status=404)

        category.is_active = False
        category.lastmodified_by = employee_id
        category.lastmodified_date = timezone.now()
        category.save()

        return Response({"message": "Deleted successfully"}, status=200)


# --------------------------------------------------
# NURSING STATION
# --------------------------------------------------
@api_view(["GET", "POST", "PUT", "DELETE"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def nursingstation_view(request, pk=None):

    employee_id = (
        request.data.get('auth-user-id') or
        request.headers.get('auth-user-id') or
        "system"
    )

    hospital_code = (
        request.data.get("auth-hospital-code") or
        request.headers.get("auth-hospital-code") or
        "system"
    )

    branch_code = (
        request.data.get("auth-branch-code") or
        request.headers.get("Branch-Code") or
        "system"
    )

    # ── GET ─────────────────────────────────────────────
    if request.method == "GET":

        if pk:
            try:
                nursingstation = NursingStation.objects.get(
                    ward_id=pk,
                    hospital_code=hospital_code,
                    branch_code=branch_code
                )

                if not nursingstation.is_active:
                    return Response({"error": "NursingStation not found"}, status=404)

            except NursingStation.DoesNotExist:
                return Response({"error": "NursingStation not found"}, status=404)

            serializer = NursingStationSerializer(nursingstation)
            return Response(serializer.data)

        # List
        all_wards = NursingStation.objects.filter(
            hospital_code=hospital_code,
            branch_code=branch_code
        ).order_by("ward_id")

        wards = [w for w in all_wards if w.is_active]

        serializer = NursingStationSerializer(wards, many=True)
        return Response(serializer.data)


    # ── POST ─────────────────────────────────────────────
    if request.method == "POST":

        data = request.data.copy()
        data["hospital_code"] = hospital_code
        data["branch_code"] = branch_code

        serializer = NursingStationSerializer(data=data)
        if serializer.is_valid():
            serializer.save(
                created_by=employee_id,
                created_date=timezone.now(),
                is_active=True
            )
            return Response(serializer.data, status=201)

        return Response(serializer.errors, status=400)


    # ── PUT ─────────────────────────────────────────────
    if request.method == "PUT":

        if not pk:
            return Response({"error": "NursingStation ID required"}, status=400)

        try:
            nursingstation = NursingStation.objects.get(
                ward_id=pk,
                hospital_code=hospital_code,
                branch_code=branch_code
            )

            if not nursingstation.is_active:
                return Response({"error": "NursingStation not found"}, status=404)

        except NursingStation.DoesNotExist:
            return Response({"error": "NursingStation not found"}, status=404)

        serializer = NursingStationSerializer(
            nursingstation,
            data=request.data,
            partial=True
        )

        if serializer.is_valid():
            serializer.save(
                lastmodified_by=employee_id,
                lastmodified_date=timezone.now()
            )
            return Response(serializer.data)

        return Response(serializer.errors, status=400)


    # ── DELETE ─────────────────────────────────────────────
    if request.method == "DELETE":

        if not pk:
            return Response({"error": "NursingStation ID required"}, status=400)

        try:
            nursingstation = NursingStation.objects.get(
                ward_id=pk,
                hospital_code=hospital_code,
                branch_code=branch_code
            )

            if not nursingstation.is_active:
                return Response({"error": "NursingStation not found"}, status=404)

        except NursingStation.DoesNotExist:
            return Response({"error": "NursingStation not found"}, status=404)

        nursingstation.is_active = False
        nursingstation.lastmodified_by = employee_id
        nursingstation.lastmodified_date = timezone.now()
        nursingstation.save()

        return Response({"message": "Deleted successfully"}, status=200)
    

# --------------------------------------------------
# ROOM SERVICE DESCRIPTION
# --------------------------------------------------
@api_view(["GET", "POST", "PUT", "DELETE"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def room_service_description_view(request, pk=None):

    employee_id = (
        request.data.get('auth-user-id') or
        request.headers.get('auth-user-id') or
        "system"
    )

    hospital_code = (
        request.data.get("auth-hospital-code") or
        request.headers.get("auth-hospital-code") or
        "system"
    )

    branch_code = (
        request.data.get("auth-branch-code") or
        request.headers.get("Branch-Code") or
        "system"
    )


    # ── GET ─────────────────────────────────────────
    if request.method == "GET":

        if pk:
            try:
                roomservicedescription = RoomServiceDescription.objects.get(
                    description_id=pk,
                    hospital_code=hospital_code,
                    branch_code=branch_code
                )

                if not roomservicedescription.is_active:
                    return Response({"error": "RoomServiceDescription not found"}, status=404)

            except RoomServiceDescription.DoesNotExist:
                return Response({"error": "RoomServiceDescription not found"}, status=404)

            serializer = RoomServiceDescriptionSerializer(roomservicedescription)
            return Response(serializer.data)


        # list
        all_description = RoomServiceDescription.objects.filter(
            hospital_code=hospital_code,
            branch_code=branch_code
        ).order_by("description_id")

        descriptions = [b for b in all_description if b.is_active]

        serializer = RoomServiceDescriptionSerializer(descriptions, many=True)
        return Response(serializer.data)


    # ── POST ─────────────────────────────────────────
    if request.method == "POST":

        data = request.data.copy()
        data["hospital_code"] = hospital_code
        data["branch_code"] = branch_code

        serializer = RoomServiceDescriptionSerializer(data=data)

        if serializer.is_valid():
            serializer.save(
                created_by=employee_id,
                created_date=timezone.now(),
                lastmodified_by=employee_id,
                lastmodified_date=timezone.now(),
                is_active=True
            )
            return Response(serializer.data, status=201)

        return Response(serializer.errors, status=400)


    # ── PUT ─────────────────────────────────────────
    if request.method == "PUT":

        if not pk:
            return Response({"error": "RoomServiceDescription ID required"}, status=400)

        try:
            roomservicedescription = RoomServiceDescription.objects.get(
                description_id=pk,
                hospital_code=hospital_code,
                branch_code=branch_code
            )

            if not roomservicedescription.is_active:
                return Response({"error": "RoomServiceDescription not found"}, status=404)

        except RoomServiceDescription.DoesNotExist:
            return Response({"error": "RoomServiceDescription not found"}, status=404)


        serializer = RoomServiceDescriptionSerializer(
            roomservicedescription,
            data=request.data,
            partial=True
        )

        if serializer.is_valid():
            serializer.save(
                lastmodified_by=employee_id,
                lastmodified_date=timezone.now()
            )
            return Response(serializer.data)

        return Response(serializer.errors, status=400)


    # ── DELETE (SOFT DELETE) ─────────────────────────
    if request.method == "DELETE":

        if not pk:
            return Response({"error": "RoomServiceDescription ID required"}, status=400)

        try:
            roomservicedescription = RoomServiceDescription.objects.get(
                description_id=pk,
                hospital_code=hospital_code,
                branch_code=branch_code
            )

            if not roomservicedescription.is_active:
                return Response({"error": "RoomServiceDescription not found"}, status=404)

        except RoomServiceDescription.DoesNotExist:
            return Response({"error": "RoomServiceDescription not found"}, status=404)


        roomservicedescription.is_active = False
        roomservicedescription.lastmodified_by = employee_id
        roomservicedescription.lastmodified_date = timezone.now()
        roomservicedescription.save()

        return Response({"message": "Deleted successfully"}, status=200)
    

# --------------------------------------------------
# ROOM KIT ITEMS
# --------------------------------------------------
@api_view(["GET", "POST", "PUT", "DELETE"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def room_kititems_view(request, pk=None):

    employee_id = (
        request.data.get('auth-user-id') or
        request.headers.get('auth-user-id') or
        "system"
    )

    hospital_code = (
        request.data.get("auth-hospital-code") or
        request.headers.get("auth-hospital-code") or
        "system"
    )

    branch_code = (
        request.data.get("auth-branch-code") or
        request.headers.get("Branch-Code") or
        "system"
    )


    # ── GET ─────────────────────────────────────────
    if request.method == "GET":

        if pk:
            try:
                roomkititems = RoomKitItems.objects.get(
                    kit_id=pk,
                    hospital_code=hospital_code,
                    branch_code=branch_code
                )

                if not roomkititems.is_active:
                    return Response({"error": "RoomKitItems not found"}, status=404)

            except RoomKitItems.DoesNotExist:
                return Response({"error": "RoomKitItems not found"}, status=404)

            serializer = RoomKitItemsSerializer(roomkititems)
            return Response(serializer.data)


        # list
        all_roomkititems = RoomKitItems.objects.filter(
            hospital_code=hospital_code,
            branch_code=branch_code
        ).order_by("kit_id")

        roomkititems = [b for b in all_roomkititems if b.is_active]

        serializer = RoomKitItemsSerializer(roomkititems, many=True)
        return Response(serializer.data)


    # ── POST ─────────────────────────────────────────
    if request.method == "POST":

        data = request.data.copy()
        data["hospital_code"] = hospital_code
        data["branch_code"] = branch_code

        serializer = RoomKitItemsSerializer(data=data)

        if serializer.is_valid():
            serializer.save(
                created_by=employee_id,
                created_date=timezone.now(),
                lastmodified_by=employee_id,
                lastmodified_date=timezone.now(),
                is_active=True
            )
            return Response(serializer.data, status=201)

        return Response(serializer.errors, status=400)


    # ── PUT ─────────────────────────────────────────
    if request.method == "PUT":

        if not pk:
            return Response({"error": "RoomKitItems ID required"}, status=400)

        try:
            roomkititems = RoomKitItems.objects.get(
                kit_id=pk,
                hospital_code=hospital_code,
                branch_code=branch_code
            )

            if not roomkititems.is_active:
                return Response({"error": "RoomKitItems not found"}, status=404)

        except RoomKitItems.DoesNotExist:
            return Response({"error": "RoomKitItems not found"}, status=404)


        serializer = RoomKitItemsSerializer(
            roomkititems,
            data=request.data,
            partial=True
        )

        if serializer.is_valid():
            serializer.save(
                lastmodified_by=employee_id,
                lastmodified_date=timezone.now()
            )
            return Response(serializer.data)

        return Response(serializer.errors, status=400)


    # ── DELETE (SOFT DELETE) ─────────────────────────
    if request.method == "DELETE":

        if not pk:
            return Response({"error": "RoomKitItems ID required"}, status=400)

        try:
            roomkititems = RoomKitItems.objects.get(
                kit_id=pk,
                hospital_code=hospital_code,
                branch_code=branch_code
            )

            if not roomkititems.is_active:
                return Response({"error": "RoomKitItems not found"}, status=404)

        except RoomKitItems.DoesNotExist:
            return Response({"error": "RoomKitItems not found"}, status=404)


        roomkititems.is_active = False
        roomkititems.lastmodified_by = employee_id
        roomkititems.lastmodified_date = timezone.now()
        roomkititems.save()

        return Response({"message": "Deleted successfully"}, status=200)


# --------------------------------------------------
# ROOM (with Nested Beds, Services, Kits)
# --------------------------------------------------
def _get_auth(request):
    """Extract auth headers from either request.data or request.headers."""
    def pick(key):
        return (
            request.data.get(key)
            or request.headers.get(key)
            or "system"
        )
    return pick("auth-user-id"), pick("auth-hospital-code"), pick("auth-branch-code")
 
 
# ─────────────────────────────────────────────────────────────────────────────
@api_view(["GET", "POST", "PUT", "DELETE"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def room_view(request, pk=None):
 
    employee_id, hospital_code, branch_code = _get_auth(request)
 
    # ── GET ──────────────────────────────────────────────────────────────────
    if request.method == "GET":
 
        if pk:
            try:
                room = Room.objects.get(
                    pk=pk,
                    hospital_code=hospital_code,
                    branch_code=branch_code,
                )
                if not room.is_active:
                    return Response({"error": "Room not found"}, status=404)
                return Response(RoomSerializer(room).data)
            except Room.DoesNotExist:
                return Response({"error": "Room not found"}, status=404)
 
        all_rooms = Room.objects.filter(
            hospital_code=hospital_code,
            branch_code=branch_code,
        )
        active = [r for r in all_rooms if r.is_active]
        return Response(RoomSerializer(active, many=True).data)
 
    # ── POST ─────────────────────────────────────────────────────────────────
    elif request.method == "POST":
 
        data = request.data.copy()
        data["hospital_code"] = hospital_code
        data["branch_code"]   = branch_code
 
        # Pop nested lists before main serializer validation
        services  = data.pop("services",  [])
        beds      = data.pop("beds",      [])
        room_kits = data.pop("room_kits", [])
 
        room_number = data.get("room_number")
 
        # Duplicate check
        existing = Room.objects.filter(
            room_number=room_number,
            hospital_code=hospital_code,
            branch_code=branch_code,
        )
        if any(r.is_active for r in existing):
            return Response(
                {"error": "Room with this room number already exists"},
                status=400,
            )
 
        serializer = RoomSerializer(data=data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
 
        room = serializer.save(
            created_by=employee_id,
            created_date=timezone.now(),
            lastmodified_by=employee_id,
            lastmodified_date=timezone.now(),
            is_active=True,
        )
 
        # Persist nested JSON (already validated by serializer validators
        # if passed through data; here we store directly after popping above)
        room.services  = services
        room.beds      = _derive_bed_statuses(beds)
        room.room_kits = room_kits
        room.save()
 
        return Response(RoomSerializer(room).data, status=201)
 
    # ── PUT ──────────────────────────────────────────────────────────────────
    elif request.method == "PUT":
 
        try:
            room = Room.objects.get(
                pk=pk,
                hospital_code=hospital_code,
                branch_code=branch_code,
            )
            if not room.is_active:
                return Response({"error": "Room not found"}, status=404)
        except Room.DoesNotExist:
            return Response({"error": "Room not found"}, status=404)
 
        data = request.data.copy()
 
        services  = data.pop("services",  None)
        beds      = data.pop("beds",      None)
        room_kits = data.pop("room_kits", None)
 
        new_room_number = data.get("room_number")
 
        # Duplicate check when room number is being changed
        if new_room_number and new_room_number != room.room_number:
            existing = Room.objects.filter(
                room_number=new_room_number,
                hospital_code=hospital_code,
                branch_code=branch_code,
            )
            if any(r.is_active and str(r.pk) != str(pk) for r in existing):
                return Response(
                    {"error": "Room with this room number already exists"},
                    status=400,
                )
 
        serializer = RoomSerializer(room, data=data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
 
        room = serializer.save(
            lastmodified_by=employee_id,
            lastmodified_date=timezone.now(),
        )
 
        # Only update nested lists if explicitly sent in the request
        if services is not None:
            room.services = services
        if beds is not None:
            room.beds = _derive_bed_statuses(beds)
        if room_kits is not None:
            room.room_kits = room_kits
 
        room.save()
        return Response(RoomSerializer(room).data)
 
    # ── DELETE ───────────────────────────────────────────────────────────────
    elif request.method == "DELETE":
 
        try:
            room = Room.objects.get(
                pk=pk,
                hospital_code=hospital_code,
                branch_code=branch_code,
            )
            if not room.is_active:
                return Response({"error": "Room not found"}, status=404)
 
            room.is_active         = False
            room.lastmodified_by   = employee_id
            room.lastmodified_date = timezone.now()
            room.save()
            return Response({"message": "Deleted successfully"})
 
        except Room.DoesNotExist:
            return Response({"error": "Room not found"}, status=404)
 
 
# ─── Utility ─────────────────────────────────────────────────────────────────
 
def _derive_bed_statuses(beds):
    """
    Ensures every bed dict has bed_status derived from its `blocked` flag.
    Called before persisting to the JSONField.
    """
    if not isinstance(beds, list):
        return []
    for bed in beds:
        blocked = bool(bed.get("blocked", False))
        bed["blocked"]    = blocked
        bed["bed_status"] = "Blocked" if blocked else "Available"
    return beds
        

import json
from django.db.models.fields.json import JSONField

# --------------------------------------------------
# PATCH JSONFIELD FROM_DB_VALUE FOR DJONGO
# --------------------------------------------------
def safe_json_from_db_value(self, value, expression, connection):
    if value is None:
        return None

    # If Mongo already returned list/dict, return directly
    if isinstance(value, (list, dict)):
        return value

    try:
        return json.loads(value)
    except Exception:
        return value


JSONField.from_db_value = safe_json_from_db_value
# --------------------------------------------------
# SAFE JSON PARSER
# Handles list / dict / string / bytes
# --------------------------------------------------
def parse_json_field(value):

    if isinstance(value, list):
        return value

    if isinstance(value, dict):
        return [value]

    if value is None:
        return []

    if isinstance(value, (bytes, bytearray)):
        try:
            value = value.decode("utf-8")
        except Exception:
            return []

    if isinstance(value, str):
        value = value.strip()

        if not value or value in ("null", "None", "[]", "{}"):
            return []

        try:
            parsed = json.loads(value)

            if isinstance(parsed, list):
                return parsed

            if isinstance(parsed, dict):
                return [parsed]

        except Exception:
            return []

    try:
        parsed = json.loads(str(value))
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]
    except Exception:
        pass

    return []


def parse_json_field(value):
    """Safely parse a JSON field that may already be a list/dict or a JSON string."""
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict):
                return [parsed]
        except Exception:
            pass
    return []
 
 
def generate_shifting_id(existing_shiftings):
    """
    Generate a simple incremental integer shifting_id.
    Scans existing shifting records and returns max + 1.
    Falls back to a random int if parsing fails.
    """
    max_id = 0
    for shift in existing_shiftings:
        if not isinstance(shift, dict):
            continue
        try:
            sid = int(shift.get("shifting_id", 0))
            if sid > max_id:
                max_id = sid
        except (ValueError, TypeError):
            pass
    return str(max_id + 1)
 
 
# ─────────────────────────────────────────────────────────────────────────────
# ROOM ENQUIRY  (fixed status logic)
#
# Status rules:
#   is_roomActive=True,  is_roomCleaned=False  →  Occupied
#   is_roomActive=False, is_roomCleaned=False  →  Not Cleaned   ← was broken
#   is_roomActive=False, is_roomCleaned=True   →  Available
#   bed.blocked=True                           →  Maintenance
#   RoomBooking.is_booked=True (no admission)  →  Reserved
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def room_enquiry_view(request):

    try:
        result   = []
        floor_map = {}

        hospital_code = (
            request.data.get("auth-hospital-code") or
            request.headers.get("auth-hospital-code") or
            "system"
        )

        branch_code = (
            request.data.get("auth-branch-code") or
            request.headers.get("Branch-Code") or
            "system"
        )

        # ═══════════════════════════════════════════════
        # STEP 1 — PATIENT MAP
        # ═══════════════════════════════════════════════
        patient_map = {}

        for patient in Patient.objects.filter(
            hospital_code=hospital_code,
            branch_code=branch_code
        ):
            patient_map[str(patient.uhid)] = {
                "uhid":        str(patient.uhid or ""),
                "patientname": f"{patient.firstName or ''} {patient.lastName or ''}".strip(),
                "age":         str(patient.age or ""),
                "gender":      str(patient.gender or ""),
                "mobilePhone": str(patient.mobilePhone or ""),
            }

        # ═══════════════════════════════════════════════
        # STEP 2 — ADMISSION MAP
        #
        # FIX: Do NOT skip discharged admissions entirely.
        #      A discharged bed that is NOT cleaned must still
        #      appear as "Not Cleaned" until housekeeping marks
        #      it clean.  Only skip beds that are already clean.
        # ═══════════════════════════════════════════════
        admission_map = {}

        for admission in Admission.objects.filter(
            hospital_code=hospital_code,
            branch_code=branch_code
        ):
            uhid        = str(admission.uhid or "")
            ip_number   = str(admission.ipNumber or "")
            patient_info = patient_map.get(uhid, {})

            details  = parse_json_field(admission.room_details)
            shifts   = parse_json_field(admission.roomShitingDetails)
            shifts   = [s for s in shifts if isinstance(s, dict)]

            # ── Process roomShiftingDetails entries ───────────────────────
            for shift in shifts:
                room_no = str(shift.get("newRoomNo", "")).strip()
                bed_no  = str(shift.get("newBedNo",  "")).strip()

                if not room_no or not bed_no:
                    continue

                is_room_active = bool(shift.get("is_roomActive", False))
                is_cleaned     = bool(shift.get("is_roomCleaned", False))

                # Apply the 3-state rule directly from the entry flags
                if is_room_active and not is_cleaned:
                    status       = "Occupied"
                    patient_data = patient_info
                elif not is_room_active and not is_cleaned:
                    # Bed vacated but not yet cleaned — must show Not Cleaned
                    status       = "Not Cleaned"
                    patient_data = patient_info   # previous patient shown in hover
                else:
                    # is_roomCleaned=True → ready for next patient
                    status       = "Available"
                    patient_data = {}

                # Later entries (more recent shifts) win for the same bed
                admission_map[(room_no, bed_no)] = {
                    "status":        status,
                    "patient":       patient_data,
                    "ip_number":     ip_number,
                    "is_roomCleaned": is_cleaned,
                }

            # ── Process room_details entries ───────────────────────────────
            for entry in details:
                room_no = str(entry.get("roomNo", "")).strip()
                bed_no  = str(entry.get("bedNo",  "")).strip()

                if not room_no or not bed_no:
                    continue

                is_room_active = bool(entry.get("is_roomActive", False))
                is_cleaned     = bool(entry.get("is_roomCleaned", False))

                # Same 3-state rule
                if is_room_active and not is_cleaned:
                    status       = "Occupied"
                    patient_data = patient_info
                elif not is_room_active and not is_cleaned:
                    status       = "Not Cleaned"
                    patient_data = patient_info
                else:
                    status       = "Available"
                    patient_data = {}

                # Shifting details take priority — only write if not already set
                # by a shift entry (shifts are processed first above)
                if (room_no, bed_no) not in admission_map:
                    admission_map[(room_no, bed_no)] = {
                        "status":        status,
                        "patient":       patient_data,
                        "ip_number":     ip_number,
                        "is_roomCleaned": is_cleaned,
                    }

        # ═══════════════════════════════════════════════
        # STEP 3 — BOOKING MAP
        # ═══════════════════════════════════════════════
        booking_map = {}

        for booking in RoomBooking.objects.filter(
            hospital_code=hospital_code,
            branch_code=branch_code
        ):
            if not bool(getattr(booking, "is_booked", False)):
                continue

            if bool(getattr(booking, "room_shifted", False)):
                continue

            room_number = str(booking.room_number or "")
            bed_number  = str(booking.bed_number  or "")

            booking_map[(room_number, bed_number)] = {
                "ip_number": str(getattr(booking, "ip_number", "")),
                "uhid":      str(getattr(booking, "uhid", "")),
            }

        # ═══════════════════════════════════════════════
        # STEP 4 — ROOM LOOP
        # ═══════════════════════════════════════════════
        for room in Room.objects.filter(
            hospital_code=hospital_code,
            branch_code=branch_code
        ):
            if not getattr(room, "is_active", False):
                continue

            floor = getattr(room, "floor", 0) or 0

            if floor not in floor_map:
                floor_map[floor] = []

            beds      = parse_json_field(room.beds)
            beds_data = []

            for bed in beds:
                bed_number = str(bed.get("bed_number", "")).strip()
                key        = (str(room.room_number), bed_number)

                # 1. Maintenance / blocked
                if bool(bed.get("blocked", False)) or str(bed.get("bed_status", "")).lower() == "blocked":
                    beds_data.append({
                        "bed_number": bed_number,
                        "status":     "Maintenance",
                        "patient":    {},
                        "booking":    None,
                        "ip_number":  "",
                    })
                    continue

                # 2. Admission-driven status (Occupied / Not Cleaned / Available from admission)
                if key in admission_map:
                    info = admission_map[key]
                    beds_data.append({
                        "bed_number":  bed_number,
                        "status":      info["status"],
                        "patient":     info["patient"],
                        "booking":     None,
                        "ip_number":   info["ip_number"],
                        "is_roomCleaned": info["is_roomCleaned"],
                    })
                    continue

                # 3. Reserved via RoomBooking
                if key in booking_map:
                    beds_data.append({
                        "bed_number": bed_number,
                        "status":     "Reserved",
                        "patient":    {},
                        "booking":    booking_map[key],
                        "ip_number":  "",
                    })
                    continue

                # 4. Truly available
                beds_data.append({
                    "bed_number": bed_number,
                    "status":     "Available",
                    "patient":    {},
                    "booking":    None,
                    "ip_number":  "",
                })

            floor_map[floor].append({
                "room_number": room.room_number,
                "room_type":   room.room_category,
                "block":       room.block,
                "beds":        beds_data,
            })

        # ═══════════════════════════════════════════════
        # STEP 5 — SORT FLOORS
        # ═══════════════════════════════════════════════
        for floor in sorted(floor_map.keys()):
            result.append({
                "floor": floor,
                "rooms": floor_map[floor],
            })

        return Response(result, status=200)

    except Exception as exc:
        traceback.print_exc()
        return Response(
            {"error": f"Room enquiry failed: {str(exc)}"},
            status=500,
        )


@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def book_room_view(request):

    try:
        employee_id = (
            request.data.get('auth-user-id') or
            request.headers.get('auth-user-id') or
            "system"
        )

        hospital_code = (
            request.data.get("auth-hospital-code") or
            request.headers.get("auth-hospital-code") or
            "system"
        )

        branch_code = (
            request.data.get("auth-branch-code") or
            request.headers.get("Branch-Code") or
            "system"
        )

        ip_number   = str(request.data.get("ip_number",   "")).strip()
        room_number = str(request.data.get("room_number", "")).strip()
        bed_number  = str(request.data.get("bed_number",  "")).strip()

        if not ip_number:
            return Response(
                {"success": False, "error": "ip_number is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not room_number or not bed_number:
            return Response(
                {"success": False, "error": "room_number and bed_number are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Find Admission ────────────────────────────────────────────────
        admission = None

        for adm in Admission.objects.filter(
            hospital_code=hospital_code,
            branch_code=branch_code,
        ):
            if str(adm.ipNumber).strip() == ip_number:
                admission = adm
                break

        if not admission:
            return Response(
                {
                    "success": False,
                    "error":   f"No admission found for IP Number: {ip_number}",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # ── Duplicate check ───────────────────────────────────────────────
        existing_booking = None

        for booking in RoomBooking.objects.filter(
            hospital_code=hospital_code,
            branch_code=branch_code,
        ):
            if (
                str(booking.room_number).strip() == room_number and
                str(booking.bed_number).strip()  == bed_number  and
                bool(booking.is_booked)          is True        and
                bool(getattr(booking, "room_shifted", False)) is False
            ):
                existing_booking = booking
                break

        if existing_booking:
            return Response(
                {
                    "success": False,
                    "error":   (
                        f"Room {room_number} / Bed {bed_number} "
                        f"is already reserved (IP: {existing_booking.ip_number})"
                    ),
                },
                status=status.HTTP_409_CONFLICT,
            )

        # ── Create Booking ────────────────────────────────────────────────
        booking = RoomBooking(
            ip_number=ip_number,
            room_number=room_number,
            bed_number=bed_number,

            hospital_code=hospital_code,
            branch_code=branch_code,

            is_booked=True,
            room_shifted=False,

            created_by=employee_id,
            created_date=timezone.now(),
            lastmodified_by=employee_id,
            lastmodified_date=timezone.now(),
            booked_date=timezone.now(),
        )

        booking.save()

        return Response(
            {
                "success": True,
                "message": f"Room {room_number} / Bed {bed_number} reserved successfully",
                "data": {
                    "ip_number":    booking.ip_number,
                    "room_number":  booking.room_number,
                    "bed_number":   booking.bed_number,
                    "is_booked":    booking.is_booked,
                    "room_shifted": booking.room_shifted,
                    "booked_date":  booking.booked_date,
                },
            },
            status=status.HTTP_201_CREATED,
        )

    except Exception as exc:
        traceback.print_exc()
        return Response(
            {"success": False, "error": f"Booking failed: {str(exc)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


# ─────────────────────────────────────────────────────────────────────────────
# UPDATE is_roomCleaned  (PATCH)
# Body: { "room_no": "101", "bed_no": "2", "is_roomCleaned": true,
#         "ip_number": "S026/500001", "shifting_id": "" }
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["PATCH"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def update_room_cleaned_view(request):
    try:
        room_no     = str(request.data.get("room_no",        "")).strip()
        bed_no      = str(request.data.get("bed_no",         "")).strip()
        is_cleaned  = bool(request.data.get("is_roomCleaned", False))
        ip_number   = str(request.data.get("ip_number",      "")).strip()
        shifting_id = str(request.data.get("shifting_id",    "")).strip()

        if not room_no or not bed_no:
            return Response(
                {"success": False, "error": "room_no and bed_no are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        admission = None

        # Prefer exact match by ip_number
        if ip_number:
            for adm in Admission.objects.all():
                if str(adm.ipNumber) == ip_number:
                    admission = adm
                    break

        # Fallback: find by room/bed match in any entry
        if not admission:
            for adm in Admission.objects.all():
                details   = parse_json_field(adm.room_details)
                shiftings = parse_json_field(adm.roomShitingDetails)
                for entry in details + shiftings:
                    if not isinstance(entry, dict):
                        continue
                    rn = str(entry.get("roomNo") or entry.get("newRoomNo", "")).strip()
                    bn = str(entry.get("bedNo")  or entry.get("newBedNo",  "")).strip()
                    if rn == room_no and bn == bed_no:
                        admission = adm
                        break
                if admission:
                    break

        if not admission:
            return Response(
                {"success": False, "error": "Admission not found for this room/bed"},
                status=status.HTTP_404_NOT_FOUND,
            )

        updated = False

        # ── Try shifting entry first ──────────────────────────────────────
        shiftings     = parse_json_field(admission.roomShitingDetails)
        new_shiftings = []
        for shift in shiftings:
            if not isinstance(shift, dict):
                continue
            obj = dict(shift)
            rn  = str(obj.get("newRoomNo", "")).strip()
            bn  = str(obj.get("newBedNo",  "")).strip()
            sid = str(obj.get("shifting_id", ""))
            if rn == room_no and bn == bed_no:
                if shifting_id and sid != shifting_id:
                    new_shiftings.append(obj)
                    continue
                obj["is_roomCleaned"] = is_cleaned
                updated = True
            new_shiftings.append(obj)

        if updated:
            admission.roomShitingDetails = new_shiftings
        else:
            # ── Fall back to room_details ─────────────────────────────────
            details     = parse_json_field(admission.room_details)
            new_details = []
            for entry in details:
                if not isinstance(entry, dict):
                    continue
                obj = dict(entry)
                rn  = str(obj.get("roomNo", "")).strip()
                bn  = str(obj.get("bedNo",  "")).strip()
                if rn == room_no and bn == bed_no:
                    obj["is_roomCleaned"] = is_cleaned
                    updated = True
                new_details.append(obj)
            admission.room_details = new_details

        if not updated:
            return Response(
                {"success": False, "error": "Room/bed entry not found in admission"},
                status=status.HTTP_404_NOT_FOUND,
            )

        admission.lastmodified_date = timezone.now()
        admission.save()

        # --- Ensure JSON fields are saved as native arrays in MongoDB ---
        try:
            import os
            from pymongo import MongoClient
            MONGO_URI = os.getenv("GLOBAL_DB_HOST")
            if MONGO_URI:
                client = MongoClient(MONGO_URI)
                mongo_db = client["HMS"]
                
                mongo_db["hospital_admission"].update_one(
                    {"ipNumber": str(admission.ipNumber)},
                    {"$set": {
                        "roomShitingDetails": parse_json_field(admission.roomShitingDetails) if not isinstance(admission.roomShitingDetails, list) else admission.roomShitingDetails,
                        "room_details": parse_json_field(admission.room_details) if not isinstance(admission.room_details, list) else admission.room_details
                    }}
                )
        except Exception as ex:
            print("Failed to save admission fields natively:", str(ex))


        return Response({"success": True, "message": "Room cleaned status updated"})

    except Exception as exc:
        traceback.print_exc()
        return Response(
            {"error": f"Update failed: {str(exc)}"},
            status=500,
        )
 
# ─────────────────────────────────────────────────────────────────────────────
# GET ACTIVE ADMISSION
# ─────────────────────────────────────────────────────────────────────────────
 
import traceback
from datetime import datetime
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.utils import timezone as tz

# ─── Helpers ─────────────────────────────────────────────────────────────────

def parse_json_field(value):
    """Safely parse a JSON-like field that might be a list, dict, or string."""
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    if isinstance(value, str):
        import json
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict):
                return [parsed]
        except Exception:
            pass
    return []


def generate_shifting_id(existing_shiftings):
    """Generate a sequential shifting ID like SH001, SH002, …"""
    max_num = 0
    for s in existing_shiftings:
        if isinstance(s, dict):
            sid = str(s.get("shifting_id", ""))
            if sid.startswith("SH") and sid[2:].isdigit():
                max_num = max(max_num, int(sid[2:]))
    return f"SH{str(max_num + 1).zfill(3)}"


# ─────────────────────────────────────────────────────────────────────────────
# GET ACTIVE ADMISSION  (updated: includes RoomBooking check)
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET"])
@csrf_exempt
def get_active_admission(request):
    """
    Returns the active admission for a given UHID or IP Number.
    Also checks the RoomBooking collection for a pre-reserved room
    (is_booked=True, room_shifted=False) and includes it in the response
    so the frontend can auto-fill the new-room fields.
    """
    try:
        uhid      = request.GET.get("uhid",      "").strip()
        ip_number = request.GET.get("ip_number", "").strip()

        if not uhid and not ip_number:
            return Response(
                {"success": False, "message": "Provide UHID or IP Number"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Find matching admissions ──────────────────────────────────────
        all_admissions = []
        for adm in Admission.objects.all():
            if uhid      and str(adm.uhid)     != uhid:
                continue
            if ip_number and str(adm.ipNumber) != ip_number:
                continue
            all_admissions.append(adm)

        active_records = [
            adm for adm in all_admissions
            if getattr(adm, "is_admitted",        False) is True
            and getattr(adm, "is_admissionActive", False) is True
            and getattr(adm, "is_discharged",      True)  is False
        ]

        if not active_records:
            return Response(
                {"success": False, "message": "No active admission found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        def safe_sort_key(adm):
            dt = adm.admissionDateTime
            if dt is None:
                return datetime.min
            if hasattr(dt, "tzinfo") and dt.tzinfo is not None:
                return tz.make_naive(dt)
            return dt

        active_records.sort(key=safe_sort_key, reverse=True)
        admission = active_records[0]

        # ── Patient ───────────────────────────────────────────────────────
        patient_data = {}
        try:
            patient = Patient.objects.filter(uhid=admission.uhid).first()
            if patient:
                patient_data = {
                    "uhid":        str(patient.uhid or ""),
                    "patientname": f"{patient.firstName or ''} {patient.lastName or ''}".strip(),
                    "firstName":   str(patient.firstName  or ""),
                    "lastName":    str(patient.lastName   or ""),
                    "age":         str(patient.age        or ""),
                    "gender":      str(patient.gender     or ""),
                    "mobilePhone": str(patient.mobilePhone or ""),
                    "email":       str(patient.email      or ""),
                    "city":        str(patient.city       or ""),
                    "state":       str(patient.state      or ""),
                    "area":        str(getattr(patient, "area",    "") or ""),
                    "zipcode":     str(getattr(patient, "zipcode", "") or ""),
                }
        except Exception:
            traceback.print_exc()

        # ── Active room from room_details ─────────────────────────────────
        room_details = parse_json_field(admission.room_details)
        active_room  = {}
        for r in reversed(room_details):
            if isinstance(r, dict) and r.get("is_roomActive"):
                active_room = r
                break
        if not active_room and room_details:
            last = room_details[-1]
            active_room = last if isinstance(last, dict) else {}

        # ── Has already been shifted? ─────────────────────────────────────
        shiftings   = parse_json_field(admission.roomShitingDetails)
        has_shifted = any(isinstance(s, dict) for s in shiftings)

        # ── Check RoomBooking for a pre-reserved room ─────────────────────
        #    Looks for a booking where:
        #      ip_number matches AND is_booked=True AND room_shifted=False
        reserved_room = None
        reserved_bed  = None
        has_reservation = False
        try:
            booking = None

            for rb in RoomBooking.objects.all():
                if str(getattr(rb, "ip_number", "")).strip() != str(admission.ipNumber).strip():
                    continue

                is_booked = getattr(rb, "is_booked", False)
                room_shifted = getattr(rb, "room_shifted", False)

                # handle both boolean and string values
                if str(is_booked).lower() != "true":
                    continue

                if str(room_shifted).lower() != "false":
                    continue

                booking = rb
                break

            if booking:
                has_reservation = True
                reserved_room   = str(booking.room_number or "")
                reserved_bed    = str(booking.bed_number  or "")
        except Exception:
            traceback.print_exc()

        # ── Admission date/time formatting ────────────────────────────────
        admission_date = admission_time = ""
        dt = admission.admissionDateTime
        if dt:
            try:
                admission_date = dt.strftime("%Y-%m-%d")
                admission_time = dt.strftime("%H:%M:%S")
            except Exception:
                admission_date = str(dt)[:10]
                admission_time = str(dt)[11:19]

        from pymongo import MongoClient

        # Mongo connection (adjust if already configured)
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        global_db = client['Global']
        profile_collection = global_db['backend_diagnostics_profile']

        # ── Admission date + time formatting ─────────────────────────────
        admission_date = admission_time = ""
        formatted_datetime = ""

        dt = admission.admissionDateTime
        if dt:
            try:
                admission_date = dt.strftime("%Y-%m-%d")
                admission_time = dt.strftime("%H:%M:%S")
                formatted_datetime = dt.strftime("%d-%m-%Y %I:%M %p")  # 👈 FINAL FORMAT
            except Exception:
                admission_date = str(dt)[:10]
                admission_time = str(dt)[11:19]
                formatted_datetime = f"{admission_date} {admission_time}"

        # ── Doctor Name Mapping ──────────────────────────────────────────
        doctor_id = str(admission.admittingDoctor or "").strip()
        doctor_name = ""

        if doctor_id:
            doc = profile_collection.find_one({"employeeId": doctor_id})
            if doc:
                doctor_name = doc.get("employeeName", "")

        return Response({
            "success": True,
            "data": {
                "uhid":             str(admission.uhid            or ""),
                "ipNumber":         str(admission.ipNumber        or ""),
                "ipserial_number":  str(admission.ipserial_number or ""),
                "admittingDoctor":      doctor_id,
                "admittingDoctorName":  doctor_name,
                "admissionDate":        admission_date,
                "admissionTime":        admission_time,
                "admissionDateTime":    formatted_datetime,
                "consultingDoctor": str(admission.consultingDoctor or ""),
                "packageName":      str(admission.packageName      or ""),
                "roomNo":           active_room.get("roomNo", ""),
                "bedNo":            active_room.get("bedNo",  ""),
                "room_details":     room_details,
                "has_shifted":      has_shifted,
                # ── Reservation fields ─────────────────────────────────────
                "has_reservation":  has_reservation,   # True if a pre-booked room exists
                "reservedRoomNo":   reserved_room or "",
                "reservedBedNo":    reserved_bed  or "",
                # ── Status flags ───────────────────────────────────────────
                "is_admitted":        getattr(admission, "is_admitted",        None),
                "is_admissionActive": getattr(admission, "is_admissionActive", None),
                "is_discharged":      getattr(admission, "is_discharged",      None),
                "patient": patient_data,
            },
        }, status=status.HTTP_200_OK)

    except Exception as e:
        traceback.print_exc()
        return Response(
            {"success": False, "error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


# ─────────────────────────────────────────────────────────────────────────────
# ROOM SHIFTING — GET / POST
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def room_shifting_view(request):

    user_id = request.headers.get("auth-user-id", "system")

    # ════════════════════════════════════════════════════════════════════════
    # GET — list shifting history
    # ════════════════════════════════════════════════════════════════════════
    if request.method == "GET":
        from_date = str(request.GET.get("from_date", "")).strip()
        to_date   = str(request.GET.get("to_date",   "")).strip()
        uhid      = str(request.GET.get("uhid",      "")).strip()
        ip_number = str(request.GET.get("ip_number", "")).strip()

        results = []

        for admission in Admission.objects.all():
            if not getattr(admission, "is_admitted", False):
                continue

            if uhid      and uhid.lower()      not in str(admission.uhid     or "").lower():
                continue
            if ip_number and ip_number.lower() not in str(admission.ipNumber or "").lower():
                continue

            patient_name = ""
            try:
                patient = Patient.objects.filter(uhid=admission.uhid).first()
                if patient:
                    patient_name = f"{patient.firstName or ''} {patient.lastName or ''}".strip()
            except Exception:
                pass

            # Current active room (for old room display)
            room_details = parse_json_field(admission.room_details)
            old_room_no = old_bed_no = ""
            for r in reversed(room_details):
                if isinstance(r, dict) and r.get("is_roomActive"):
                    old_room_no = str(r.get("roomNo", ""))
                    old_bed_no  = str(r.get("bedNo",  ""))
                    break
            if not old_room_no and room_details:
                last = room_details[-1]
                if isinstance(last, dict):
                    old_room_no = str(last.get("roomNo", ""))
                    old_bed_no  = str(last.get("bedNo",  ""))

            shiftings = parse_json_field(admission.roomShitingDetails)

            for shift in shiftings:
                if not isinstance(shift, dict):
                    continue

                shift_date = str(shift.get("shiftingDateTime", ""))[:10]
                if from_date and shift_date and shift_date < from_date:
                    continue
                if to_date   and shift_date and shift_date > to_date:
                    continue

                results.append({
                    "uhid":             str(admission.uhid            or ""),
                    "ipNumber":         str(admission.ipNumber        or ""),
                    "ipserial_number":  str(admission.ipserial_number or ""),
                    "patient_name":     patient_name,
                    "shifting_id":      str(shift.get("shifting_id",      "")),
                    "oldRoomNo":        str(shift.get("oldRoomNo",        old_room_no)),
                    "oldBedNo":         str(shift.get("oldBedNo",         old_bed_no)),
                    "newRoomNo":        str(shift.get("newRoomNo",        "")),
                    "newBedNo":         str(shift.get("newBedNo",         "")),
                    "shiftingDateTime": str(shift.get("shiftingDateTime", "")),
                    "startDateTime":    str(shift.get("startDateTime",    "")),
                    "endDateTime":      str(shift.get("endDateTime",      "") or ""),
                    "shifted_by":       str(shift.get("shifted_by",       "")),
                    "is_roomActive":    bool(shift.get("is_roomActive",   False)),
                    "is_roomCleaned":   bool(shift.get("is_roomCleaned",  False)),
                    "edited_from":      str(shift.get("edited_from",      "") or ""),
                })

        # Sort by shiftingDateTime descending
        results.sort(key=lambda x: x.get("shiftingDateTime", ""), reverse=True)
        return Response(results, status=status.HTTP_200_OK)

    # ════════════════════════════════════════════════════════════════════════
    # POST — create a new shift
    # ════════════════════════════════════════════════════════════════════════
    elif request.method == "POST":
        ip_number = str(request.data.get("ip_number", "")).strip()
        new_room  = str(request.data.get("newRoomNo", "")).strip()
        new_bed   = str(request.data.get("newBedNo",  "")).strip()

        if not ip_number:
            return Response(
                {"success": False, "error": "ip_number is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not new_room or not new_bed:
            return Response(
                {"success": False, "error": "newRoomNo and newBedNo are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        admission = None
        for adm in Admission.objects.all():
            if (
                str(adm.ipNumber) == ip_number
                and bool(adm.is_admitted)
                and bool(adm.is_admissionActive)
            ):
                admission = adm
                break

        if not admission:
            return Response(
                {"success": False, "error": "Admission not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # ── Guard: only one active shift allowed ──────────────────────────
        existing_shiftings = parse_json_field(admission.roomShitingDetails)
        active_shiftings   = [s for s in existing_shiftings if isinstance(s, dict)]

        if active_shiftings:
            return Response(
                {
                    "success": False,
                    "error": "Room already shifted. Use Edit for the existing shifting record.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Old room ──────────────────────────────────────────────────────
        room_details = parse_json_field(admission.room_details)
        old_room_no  = old_bed_no = ""
        for r in reversed(room_details):
            if isinstance(r, dict) and r.get("is_roomActive"):
                old_room_no = str(r.get("roomNo", ""))
                old_bed_no  = str(r.get("bedNo",  ""))
                break
        if not old_room_no and room_details:
            last = room_details[-1]
            if isinstance(last, dict):
                old_room_no = str(last.get("roomNo", ""))
                old_bed_no  = str(last.get("bedNo",  ""))

        # ── Deactivate current room in room_details & set endDateTime ─────
        now_iso = timezone.now().isoformat()
        updated_room_details = []
        for room in room_details:
            if not isinstance(room, dict):
                continue
            obj = dict(room)
            if obj.get("is_roomActive"):
                obj["is_roomActive"] = False
                obj["endDateTime"]   = now_iso   # ← track how long patient was in room
            updated_room_details.append(obj)

        admission.room_details = updated_room_details

        # ── Build new shifting entry ──────────────────────────────────────
        new_shifting_id = generate_shifting_id(existing_shiftings)

        cleaned_shiftings = []
        for shift in existing_shiftings:
            if isinstance(shift, dict):
                cleaned_shiftings.append(dict(shift))

        # New shift entry — startDateTime set now, endDateTime null
        cleaned_shiftings.append({
            "shifting_id":      new_shifting_id,
            "oldRoomNo":        old_room_no,
            "oldBedNo":         old_bed_no,
            "newRoomNo":        new_room,
            "newBedNo":         new_bed,
            "shiftingDateTime": now_iso,
            "startDateTime":    now_iso,   # ← patient enters new room now
            "endDateTime":      None,      # ← still in this room
            "shifted_by":       str(user_id),
            "is_roomActive":    True,
            "is_roomCleaned":   False,
        })

        admission.roomShitingDetails = cleaned_shiftings
        admission.lastmodified_by    = str(user_id)
        admission.lastmodified_date  = timezone.now()

        if not isinstance(admission.advance_payments, list):
            admission.advance_payments = []

        admission.save()

        # --- Ensure JSON fields are saved as native arrays in MongoDB ---
        try:
            import os
            from pymongo import MongoClient
            MONGO_URI = os.getenv("GLOBAL_DB_HOST")
            if MONGO_URI:
                client = MongoClient(MONGO_URI)
                mongo_db = client["HMS"]
                
                mongo_db["hospital_admission"].update_one(
                    {"ipNumber": str(admission.ipNumber)},
                    {"$set": {
                        "roomShitingDetails": parse_json_field(admission.roomShitingDetails) if not isinstance(admission.roomShitingDetails, list) else admission.roomShitingDetails,
                        "room_details": parse_json_field(admission.room_details) if not isinstance(admission.room_details, list) else admission.room_details
                    }}
                )
        except Exception as ex:
            print("Failed to save admission fields natively:", str(ex))


        # ── Mark RoomBooking as shifted (if one existed) ──────────────────
        try:
            for rb in RoomBooking.objects.all():
                if str(getattr(rb, "ip_number", "")).strip() != str(ip_number).strip():
                    continue
                if str(getattr(rb, "is_booked", "")).lower() != "true":
                    continue
                if str(getattr(rb, "room_shifted", "")).lower() != "false":
                    continue
                rb.room_shifted = True
                rb.is_booked    = False
                rb.save()
                break
        except Exception:
            traceback.print_exc()

        return Response(
            {
                "success": True,
                "message": "Room shifted successfully",
                "data": {
                    "uhid":               admission.uhid,
                    "ipNumber":           admission.ipNumber,
                    "room_details":       admission.room_details,
                    "roomShitingDetails": admission.roomShitingDetails,
                },
            },
            status=status.HTTP_200_OK,
        )


# ─────────────────────────────────────────────────────────────────────────────
# PATCH /room-shifting/<ip_number>/update/
# Editing creates a NEW shifting object; previous one is set is_roomActive=False
# and endDateTime is stamped on it.
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["PATCH"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def room_shifting_detail_view(request, ip_number):

    user_id     = request.headers.get("auth-user-id", "system")
    shifting_id = str(request.data.get("shifting_id", "")).strip()
    new_room    = str(request.data.get("newRoomNo",   "")).strip()
    new_bed     = str(request.data.get("newBedNo",    "")).strip()

    if not shifting_id:
        return Response(
            {"success": False, "error": "shifting_id is required"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not new_room or not new_bed:
        return Response(
            {"success": False, "error": "newRoomNo and newBedNo are required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    admission = None
    for adm in Admission.objects.all():
        if str(adm.ipNumber) == str(ip_number):
            admission = adm
            break

    if not admission:
        return Response(
            {"success": False, "error": "Admission not found"},
            status=status.HTTP_404_NOT_FOUND,
        )

    shifting_details = parse_json_field(admission.roomShitingDetails)
    room_details     = parse_json_field(admission.room_details)

    # Check the target shift exists
    shift_found = any(
        isinstance(s, dict) and str(s.get("shifting_id", "")) == shifting_id
        for s in shifting_details
    )
    if not shift_found:
        return Response(
            {"success": False, "error": "Shifting record not found"},
            status=status.HTTP_404_NOT_FOUND,
        )

    now_iso = timezone.now().isoformat()

    # ── Mark the old shift as inactive and stamp endDateTime ─────────────
    updated_shiftings = []
    old_room_no = old_bed_no = ""
    for shift in shifting_details:
        if not isinstance(shift, dict):
            continue
        obj = dict(shift)
        if str(obj.get("shifting_id", "")) == shifting_id:
            obj["is_roomActive"]      = False
            obj["endDateTime"]        = now_iso   # ← how long patient was in that shifted room
            obj["lastmodified_by"]    = str(user_id)
            obj["lastmodified_date"]  = now_iso
            # Capture old room for the new entry
            old_room_no = str(obj.get("newRoomNo", ""))
            old_bed_no  = str(obj.get("newBedNo",  ""))
        updated_shiftings.append(obj)

    # ── New shifting entry ────────────────────────────────────────────────
    new_shifting_id = generate_shifting_id(updated_shiftings)
    updated_shiftings.append({
        "shifting_id":      new_shifting_id,
        "oldRoomNo":        old_room_no,
        "oldBedNo":         old_bed_no,
        "newRoomNo":        new_room,
        "newBedNo":         new_bed,
        "shiftingDateTime": now_iso,
        "startDateTime":    now_iso,
        "endDateTime":      None,
        "shifted_by":       str(user_id),
        "is_roomActive":    True,
        "is_roomCleaned":   False,
        "edited_from":      shifting_id,
    })

    # ── Deactivate current active room in room_details & stamp endDateTime ─
    updated_rooms = []
    for room in room_details:
        if not isinstance(room, dict):
            continue
        obj = dict(room)
        if obj.get("is_roomActive"):
            obj["is_roomActive"] = False
            obj["endDateTime"]   = now_iso
        updated_rooms.append(obj)

    admission.roomShitingDetails = updated_shiftings
    admission.room_details       = updated_rooms
    admission.lastmodified_by    = str(user_id)
    admission.lastmodified_date  = timezone.now()
    admission.save()

    # --- Ensure JSON fields are saved as native arrays in MongoDB ---
    try:
        import os
        from pymongo import MongoClient
        MONGO_URI = os.getenv("GLOBAL_DB_HOST")
        if MONGO_URI:
            client = MongoClient(MONGO_URI)
            mongo_db = client["HMS"]
            
            mongo_db["hospital_admission"].update_one(
                {"ipNumber": str(admission.ipNumber)},
                {"$set": {
                    "roomShitingDetails": parse_json_field(admission.roomShitingDetails) if not isinstance(admission.roomShitingDetails, list) else admission.roomShitingDetails,
                    "room_details": parse_json_field(admission.room_details) if not isinstance(admission.room_details, list) else admission.room_details
                }}
            )
    except Exception as ex:
        print("Failed to save admission fields natively:", str(ex))


    return Response(
        {
            "success": True,
            "message": "Room shifting updated — new record created",
            "data": {
                "ipNumber":           admission.ipNumber,
                "room_details":       admission.room_details,
                "roomShitingDetails": admission.roomShitingDetails,
            },
        },
        status=status.HTTP_200_OK,
    )
