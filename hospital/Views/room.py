from rest_framework.response import Response
from django.http import JsonResponse
from rest_framework import status
from pymongo import MongoClient
import os
import re
from rest_framework.decorators import api_view, permission_classes
from pyauth.auth import HasRoleAndDataPermission
from django.views.decorators.csrf import csrf_exempt
import json
from uuid import uuid4
from django.utils import timezone as tz, timezone
from datetime import datetime, timedelta
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

# ─────────────────────────────────────────────────────────────────────────────
# _safe_list + _save_admission
#
# _save_admission is the ONE function that should be called instead of
# adm.save() anywhere the Admission model is touched in this file.
# It always:
#   1. Assigns all 3 array fields as Python lists before save.
#   2. Calls adm.save().
#   3. Forces native BSON arrays in MongoDB via a direct update_one.
#
# This prevents Djongo from stringifying JSONFields on PATCH/PUT requests
# where only some fields were modified.
# ─────────────────────────────────────────────────────────────────────────────

def _safe_list(value):
    """Always return a Python list from a JSONField value (list, string, or None)."""
    if isinstance(value, list):
        return value
    if value is None:
        return []
    if isinstance(value, str):
        value = value.strip()
        if not value or value in ("null", "None", "[]", "{}"):
            return []
        try:
            import json as _j
            parsed = _j.loads(value)
            return parsed if isinstance(parsed, list) else [parsed] if isinstance(parsed, dict) else []
        except Exception:
            return []
    return []


def _save_admission(adm, room_details, shifting_details, advance_payments):
    """
    Assign all 3 JSON array fields, call adm.save(), then force native
    BSON arrays in MongoDB. Always pass the in-memory lists you built —
    never re-read from ORM after save.
    """
    import json
    def make_serializable(data):
        return json.loads(json.dumps(data, default=str))

    rd = make_serializable(room_details     if isinstance(room_details,     list) else _safe_list(room_details))
    sd = make_serializable(shifting_details if isinstance(shifting_details, list) else _safe_list(shifting_details))
    ap = make_serializable(advance_payments if isinstance(advance_payments, list) else _safe_list(advance_payments))

    adm.room_details       = rd
    adm.roomShitingDetails = sd
    adm.advance_payments   = ap
    adm.save()

    try:
        MONGO_URI = os.getenv("GLOBAL_DB_HOST")
        if MONGO_URI:
            client = MongoClient(MONGO_URI)
            client["HMS"]["hospital_admission"].update_one(
                {"ipNumber": str(adm.ipNumber)},
                {"$set": {
                    "room_details":       rd,
                    "roomShitingDetails": sd,
                    "advance_payments":   ap,
                }}
            )
    except Exception as ex:
        print(f"[_save_admission] Mongo sync failed for {adm.ipNumber}: {ex}")


def _save_room(room, services=None, beds=None, room_kits=None):
    """
    Save Room model instance and force native BSON arrays in MongoDB for
    services, beds, and room_kits.
    """
    import json
    def make_serializable(data):
        return json.loads(json.dumps(data, default=str))

    svc = make_serializable(services if isinstance(services, list) else _safe_list(getattr(room, "services", [])))
    bd  = make_serializable(beds     if isinstance(beds,     list) else _safe_list(getattr(room, "beds", [])))
    rk  = make_serializable(room_kits if isinstance(room_kits, list) else _safe_list(getattr(room, "room_kits", [])))

    room.services  = svc
    room.beds      = bd
    room.room_kits = rk
    room.save()

    try:
        MONGO_URI = os.getenv("GLOBAL_DB_HOST")
        if MONGO_URI:
            client = MongoClient(MONGO_URI)
            db_name = os.getenv("HMS_DB_NAME", "HMS")
            client[db_name]["hospital_room"].update_one(
                {"room_number": str(room.room_number)},
                {"$set": {
                    "services":  svc,
                    "beds":      bd,
                    "room_kits": rk,
                }}
            )
    except Exception as ex:
        print(f"[_save_room] Mongo sync failed for {room.room_number}: {ex}")


_mongo_client = None

def _get_hms_db():
    global _mongo_client
    if _mongo_client is None:
        _mongo_client = MongoClient(os.getenv('GLOBAL_DB_HOST'), maxPoolSize=50, connectTimeoutMS=5000)
    hms_db = _mongo_client[os.getenv("HMS_DB_NAME", "HMS")]
    return _mongo_client, hms_db


_room_indexes_created = False


def _ensure_room_indexes(hms_db):
    global _room_indexes_created
    if _room_indexes_created:
        return
    def _safe_idx(coll, keys, **kwargs):
        try:
            hms_db[coll].create_index(keys, background=True, **kwargs)
        except Exception:
            pass

    # Hospital Admission indexes
    _safe_idx("hospital_admission", [("hospital_code", 1), ("branch_code", 1), ("is_admitted", 1), ("is_discharged", 1)])
    _safe_idx("hospital_admission", [("uhid", 1)])
    _safe_idx("hospital_admission", [("ipNumber", 1)])
    _safe_idx("hospital_admission", [("hospital_code", 1), ("branch_code", 1), ("ipNumber", 1)])
    _safe_idx("hospital_admission", [("hospital_code", 1), ("branch_code", 1), ("uhid", 1)])
    _safe_idx("hospital_admission", [("room_details.roomNo", 1), ("room_details.bedNo", 1)])
    _safe_idx("hospital_admission", [("roomShitingDetails.newRoomNo", 1), ("roomShitingDetails.newBedNo", 1)])
    _safe_idx("hospital_admission", [("roomShitingDetails.shiftingDateTime", -1)])
    _safe_idx("hospital_admission", [("lastmodified_date", -1)])
    _safe_idx("hospital_admission", [("admissionDateTime", -1)])

    # Patient indexes
    _safe_idx("hospital_patient", [("hospital_code", 1), ("uhid", 1)])
    _safe_idx("hospital_patient", [("uhid", 1)])

    # Room indexes
    _safe_idx("hospital_room", [("hospital_code", 1), ("branch_code", 1), ("is_active", 1)])
    _safe_idx("hospital_room", [("hospital_code", 1), ("branch_code", 1), ("room_number", 1)])
    _safe_idx("hospital_room", [("room_number", 1)])
    _safe_idx("hospital_room", [("floor", 1), ("room_number", 1)])

    # RoomBooking indexes
    _safe_idx("hospital_roombooking", [("hospital_code", 1), ("branch_code", 1), ("is_booked", 1), ("room_shifted", 1)])
    _safe_idx("hospital_roombooking", [("ip_number", 1)])
    _safe_idx("hospital_roombooking", [("hospital_code", 1), ("branch_code", 1), ("ip_number", 1)])
    _safe_idx("hospital_roombooking", [("room_number", 1), ("bed_number", 1)])

    # Master tables indexes
    _safe_idx("hospital_block", [("hospital_code", 1), ("branch_code", 1), ("is_active", 1)])
    _safe_idx("hospital_roomcategory", [("hospital_code", 1), ("branch_code", 1), ("is_active", 1)])
    _safe_idx("hospital_nursingstation", [("hospital_code", 1), ("branch_code", 1), ("is_active", 1)])
    _safe_idx("hospital_roomservicedescription", [("hospital_code", 1), ("branch_code", 1), ("is_active", 1)])
    _safe_idx("hospital_roomkititems", [("hospital_code", 1), ("branch_code", 1), ("is_active", 1)])

    _room_indexes_created = True


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
                    branch_code=branch_code
                )
                if not room.is_active:
                    return Response({"error": "Room not found"}, status=404)
                return Response(RoomSerializer(room).data)
            except Room.DoesNotExist:
                return Response({"error": "Room not found"}, status=404)
 
        all_rooms = Room.objects.filter(
            hospital_code=hospital_code,
            branch_code=branch_code
        ).order_by("room_number")
        rooms = [r for r in all_rooms if r.is_active]
        return Response(RoomSerializer(rooms, many=True).data)
 
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
            branch_code=branch_code
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
        _save_room(room, services=services, beds=_derive_bed_statuses(beds), room_kits=room_kits)
 
        return Response(RoomSerializer(room).data, status=201)
 
    # ── PUT ──────────────────────────────────────────────────────────────────
    elif request.method == "PUT":
 
        try:
            room = Room.objects.get(
                pk=pk,
                hospital_code=hospital_code,
                branch_code=branch_code
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
                branch_code=branch_code
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
        final_beds = _derive_bed_statuses(beds) if beds is not None else None
        _save_room(room, services=services, beds=final_beds, room_kits=room_kits)
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
def parse_json_field(value):
    """Safely parse a JSON-like field that might be a list, dict, or string."""
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
    return []
 
 
def generate_shifting_id(existing_shiftings):
    """
    Generate sequential shifting_id formatted as SH1, SH2, SH3...
    matching the migrated database standard across 55,000+ records.
    Scans existing shifting records for this admission and returns max + 1.
    """
    max_id = 0
    for shift in existing_shiftings:
        if not isinstance(shift, dict):
            continue
        sid_raw = str(shift.get("shifting_id", "")).strip()
        nums = re.findall(r'\d+', sid_raw)
        if nums:
            try:
                sid = int(nums[-1])
                if sid > max_id:
                    max_id = sid
            except (ValueError, TypeError):
                pass
    return f"SH{max_id + 1}"
 
 
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
        result    = []
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

        client, hms_db = _get_hms_db()
        _ensure_room_indexes(hms_db)

        # ═══════════════════════════════════════════════
        # STEP 1 — DOCTOR MAP
        # ═══════════════════════════════════════════════
        doctor_map = {}
        try:
            global_db = client['Global']
            diag_prof = global_db['backend_diagnostics_profile']
            for d in diag_prof.find({}, {"employeeId": 1, "employeeName": 1, "_id": 0}):
                emp_id = str(d.get("employeeId") or "").strip()
                emp_name = str(d.get("employeeName") or "").strip()
                if emp_id and emp_name:
                    doctor_map[emp_id] = emp_name
        except Exception as e:
            print("doctor_map error:", e)

        # ═══════════════════════════════════════════════
        # STEP 2 — ACTIVE & UNCLEANED ADMISSIONS (INDEXED QUERY)
        # ═══════════════════════════════════════════════
        recent_dt = datetime.now() - timedelta(days=7)
        adm_query = {
            "$or": [
                {"is_admitted": True, "is_discharged": False, "is_cancelled": {"$ne": True}},
                {"is_discharged": True, "lastmodified_date": {"$gte": recent_dt}, "room_details.is_roomCleaned": False},
                {"is_discharged": True, "lastmodified_date": {"$gte": recent_dt}, "roomShitingDetails.is_roomCleaned": False}
            ]
        }
        if hospital_code and hospital_code != "system":
            adm_query["hospital_code"] = hospital_code
        if branch_code and branch_code != "system":
            adm_query["branch_code"] = branch_code

        active_admissions = list(hms_db["hospital_admission"].find(
            adm_query,
            {
                "uhid": 1, "ipNumber": 1, "admittingDoctor": 1, "admissionDateTime": 1,
                "is_high_risk": 1, "high_risk_reason": 1, "high_risk_date": 1,
                "room_details": 1, "roomShitingDetails": 1, "is_admitted": 1, "is_discharged": 1
            }
        ))

        # ═══════════════════════════════════════════════
        # STEP 3 — PATIENTS MAP (ONLY FOR ACTIVE ADMISSIONS)
        # ═══════════════════════════════════════════════
        uhids = list(filter(None, {str(a.get("uhid") or "").strip() for a in active_admissions}))
        patient_map = {}
        if uhids:
            pat_query = {"uhid": {"$in": uhids}}
            if hospital_code and hospital_code != "system":
                pat_query["hospital_code"] = hospital_code

            pat_cursor = hms_db["hospital_patient"].find(
                pat_query,
                {
                    "uhid": 1, "firstName": 1, "lastName": 1, "age": 1,
                    "gender": 1, "mobilePhone": 1
                }
            )
            for patient in pat_cursor:
                k = str(patient.get("uhid") or "").strip()
                if not k:
                    continue
                pname = f"{patient.get('firstName') or ''} {patient.get('lastName') or ''}".strip()
                patient_map[k] = {
                    "uhid":        k,
                    "patientname": pname,
                    "name":        pname,
                    "firstName":   str(patient.get("firstName") or ""),
                    "lastName":    str(patient.get("lastName") or ""),
                    "age":         str(patient.get("age") or ""),
                    "gender":      str(patient.get("gender") or ""),
                    "mobilePhone": str(patient.get("mobilePhone") or ""),
                }

        # ═══════════════════════════════════════════════
        # STEP 4 — BUILD ADMISSION MAP FOR ROOMS/BEDS
        # ═══════════════════════════════════════════════
        admission_map = {}
        for admission in active_admissions:
            uhid = str(admission.get("uhid") or "").strip()
            ip_number = str(admission.get("ipNumber") or "").strip()
            p_dict = patient_map.get(uhid)
            patient_info = dict(p_dict) if isinstance(p_dict, dict) else {
                "uhid":        uhid,
                "patientname": "",
                "name":        "",
                "firstName":   "",
                "lastName":    "",
                "age":         "",
                "gender":      "",
                "mobilePhone": "",
            }

            # Resolve Doctor Name
            doc_id = str(admission.get("admittingDoctor") or "").strip()
            doc_name = doctor_map.get(doc_id) or doc_id
            if doc_name and not doc_name.startswith("Dr.") and doc_id in doctor_map:
                doc_name = f"Dr. {doc_name}"
            elif doc_name and not doc_name.startswith("Dr.") and not doc_name.isdigit():
                doc_name = f"Dr. {doc_name}"

            patient_info["admittingDoctor"]   = doc_name
            patient_info["admittingDoctorId"] = doc_id
            patient_info["admissionDateTime"] = str(admission.get("admissionDateTime") or "")
            patient_info["is_high_risk"]      = bool(admission.get("is_high_risk", False))
            patient_info["high_risk_reason"]  = str(admission.get("high_risk_reason") or "")
            patient_info["high_risk_date"]    = str(admission.get("high_risk_date") or "")

            details = _safe_list(admission.get("room_details"))
            shifts  = _safe_list(admission.get("roomShitingDetails"))
            shifts  = [s for s in shifts if isinstance(s, dict)]
            details = [d for d in details if isinstance(d, dict)]

            # ── Process roomShiftingDetails entries ───────────────────
            for shift in shifts:
                room_no = str(shift.get("newRoomNo", "") or shift.get("roomNo", "")).strip()
                bed_no  = str(shift.get("newBedNo", "") or shift.get("bedNo", "")).strip()
                if not room_no or not bed_no:
                    continue

                is_room_active = bool(shift.get("is_roomActive", False))
                is_cleaned     = bool(shift.get("is_roomCleaned", False))

                if is_room_active and not is_cleaned:
                    status       = "Occupied"
                    patient_data = patient_info
                elif not is_room_active and not is_cleaned:
                    status       = "Not Cleaned"
                    patient_data = patient_info
                else:
                    status       = "Available"
                    patient_data = {}

                admission_map[(room_no, bed_no)] = {
                    "status":        status,
                    "patient":       patient_data,
                    "ip_number":     ip_number,
                    "is_roomCleaned": is_cleaned,
                }

            # ── Process room_details entries ─────────────────────────
            for entry in details:
                room_no = str(entry.get("roomNo", "")).strip()
                bed_no  = str(entry.get("bedNo", "")).strip()
                if not room_no or not bed_no:
                    continue

                is_room_active = bool(entry.get("is_roomActive", False))
                is_cleaned     = bool(entry.get("is_roomCleaned", False))

                if is_room_active and not is_cleaned:
                    status       = "Occupied"
                    patient_data = patient_info
                elif not is_room_active and not is_cleaned:
                    status       = "Not Cleaned"
                    patient_data = patient_info
                else:
                    status       = "Available"
                    patient_data = {}

                if (room_no, bed_no) not in admission_map:
                    admission_map[(room_no, bed_no)] = {
                        "status":        status,
                        "patient":       patient_data,
                        "ip_number":     ip_number,
                        "is_roomCleaned": is_cleaned,
                    }

        # ═══════════════════════════════════════════════
        # STEP 5 — BOOKING MAP (INDEXED QUERY)
        # ═══════════════════════════════════════════════
        booking_map = {}
        booking_query = {"is_booked": True, "room_shifted": {"$ne": True}}
        if hospital_code and hospital_code != "system":
            booking_query["hospital_code"] = hospital_code
        if branch_code and branch_code != "system":
            booking_query["branch_code"] = branch_code

        for booking in hms_db["hospital_roombooking"].find(booking_query):
            room_number = str(booking.get("room_number") or "")
            bed_number  = str(booking.get("bed_number") or "")
            if room_number and bed_number:
                booking_map[(room_number, bed_number)] = {
                    "ip_number": str(booking.get("ip_number") or ""),
                    "uhid":      str(booking.get("uhid") or ""),
                }

        # ═══════════════════════════════════════════════
        # STEP 6 — ROOMS & BEDS (INDEXED QUERY)
        # ═══════════════════════════════════════════════
        room_query = {"is_active": True}
        if hospital_code and hospital_code != "system":
            room_query["hospital_code"] = hospital_code
        if branch_code and branch_code != "system":
            room_query["branch_code"] = branch_code

        rooms_list = list(hms_db["hospital_room"].find(room_query).sort([("floor", 1), ("room_number", 1)]))
        if not rooms_list and branch_code and branch_code != "system":
            fallback_query = {"is_active": True}
            if hospital_code and hospital_code != "system":
                fallback_query["hospital_code"] = hospital_code
            rooms_list = list(hms_db["hospital_room"].find(fallback_query).sort([("floor", 1), ("room_number", 1)]))

        for room_doc in rooms_list:
            floor = room_doc.get("floor", 0) or 0
            if floor not in floor_map:
                floor_map[floor] = []

            beds      = _safe_list(room_doc.get("beds"))
            beds_data = []

            for bed in beds:
                if not isinstance(bed, dict):
                    continue
                bed_number = str(bed.get("bed_number", "")).strip()
                key        = (str(room_doc.get("room_number", "")), bed_number)

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

                # 2. Admission-driven status (Occupied / Not Cleaned / Available)
                if key in admission_map:
                    info = admission_map[key]
                    beds_data.append({
                        "bed_number":     bed_number,
                        "status":         info["status"],
                        "patient":        info["patient"],
                        "booking":        None,
                        "ip_number":      info["ip_number"],
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
                "room_number":     room_doc.get("room_number", ""),
                "room_type":       room_doc.get("room_category") or room_doc.get("room_type") or "",
                "room_category":   room_doc.get("room_category") or room_doc.get("room_type") or "",
                "block":           room_doc.get("block", "") or "",
                "nursing_station": room_doc.get("nursing_station", "") or "",
                "floor":           floor,
                "beds":            beds_data,
            })

        # ═══════════════════════════════════════════════
        # STEP 7 — SORT FLOORS
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

        # ── Find Admission (indexed direct lookup) ─────────────────────────
        admission = Admission.objects.filter(
            hospital_code=hospital_code,
            branch_code=branch_code,
            ipNumber=ip_number
        ).first()

        if not admission:
            admission = Admission.objects.filter(ipNumber=ip_number).first()

        if not admission:
            return Response(
                {
                    "success": False,
                    "error":   f"No admission found for IP Number: {ip_number}",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # ── Duplicate check (indexed direct lookup) ────────────────────────
        existing_booking = RoomBooking.objects.filter(
            hospital_code=hospital_code,
            branch_code=branch_code,
            room_number=room_number,
            bed_number=bed_number,
            is_booked=True,
            room_shifted=False
        ).first()

        if not existing_booking:
            existing_booking = RoomBooking.objects.filter(
                room_number=room_number,
                bed_number=bed_number,
                is_booked=True,
                room_shifted=False
            ).first()

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
# UPDATE is_roomCleaned  (PUT)
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["PUT"])
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

        # Direct indexed lookup by ip_number
        if ip_number:
            admission = Admission.objects.filter(ipNumber=ip_number).first()

        # Fallback: fast indexed Mongo lookup by room/bed
        if not admission:
            client, hms_db = _get_hms_db()
            doc = hms_db["hospital_admission"].find_one({
                "$or": [
                    {"room_details.roomNo": room_no, "room_details.bedNo": bed_no},
                    {"roomShitingDetails.roomNo": room_no, "roomShitingDetails.bedNo": bed_no},
                    {"roomShitingDetails.newRoomNo": room_no, "roomShitingDetails.newBedNo": bed_no}
                ],
                "is_discharged": False
            }, {"ipNumber": 1})
            if not doc:
                # If already discharged recently, still allow cleaning room
                doc = hms_db["hospital_admission"].find_one({
                    "$or": [
                        {"room_details.roomNo": room_no, "room_details.bedNo": bed_no},
                        {"roomShitingDetails.roomNo": room_no, "roomShitingDetails.bedNo": bed_no},
                        {"roomShitingDetails.newRoomNo": room_no, "roomShitingDetails.newBedNo": bed_no}
                    ]
                }, {"ipNumber": 1}, sort=[("lastmodified_date", -1)])

            if doc and doc.get("ipNumber"):
                admission = Admission.objects.filter(ipNumber=str(doc["ipNumber"])).first()

        if not admission:
            return Response(
                {"success": False, "error": "Admission not found for this room/bed"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Read ALL 3 arrays into memory before modifying anything
        rd = _safe_list(admission.room_details)
        sd = _safe_list(admission.roomShitingDetails)
        ap = _safe_list(admission.advance_payments)

        updated = False

        # ── Update shifting entries (support all key variants and case-insensitivity) ──
        new_sd = []
        for shift in sd:
            if not isinstance(shift, dict):
                continue
            obj = dict(shift)
            rn  = str(obj.get("newRoomNo") or obj.get("roomNo") or obj.get("room_no") or obj.get("room") or obj.get("roomNumber") or "").strip()
            bn  = str(obj.get("newBedNo") or obj.get("bedNo") or obj.get("bed_no") or obj.get("bed") or obj.get("bedNumber") or "").strip()
            sid = str(obj.get("shifting_id") or obj.get("room_entry_id") or "").strip()
            if rn.lower() == room_no.lower() and bn.lower() == bed_no.lower():
                if shifting_id and sid and sid.lower() != shifting_id.lower():
                    new_sd.append(obj)
                    continue
                obj["is_roomCleaned"] = is_cleaned
                updated = True
            new_sd.append(obj)
        sd = new_sd

        # ── Update room_details entries (support all key variants and case-insensitivity) ──
        new_rd = []
        for entry in rd:
            if not isinstance(entry, dict):
                continue
            obj = dict(entry)
            rn  = str(obj.get("roomNo") or obj.get("newRoomNo") or obj.get("room_no") or obj.get("room") or obj.get("roomNumber") or "").strip()
            bn  = str(obj.get("bedNo") or obj.get("newBedNo") or obj.get("bed_no") or obj.get("bed") or obj.get("bedNumber") or "").strip()
            sid = str(obj.get("shifting_id") or obj.get("room_entry_id") or "").strip()
            if rn.lower() == room_no.lower() and bn.lower() == bed_no.lower():
                if shifting_id and sid and sid.lower() != shifting_id.lower():
                    new_rd.append(obj)
                    continue
                obj["is_roomCleaned"] = is_cleaned
                updated = True
            new_rd.append(obj)
        rd = new_rd

        if not updated:
            return Response(
                {"success": False, "error": "Room/bed entry not found in admission"},
                status=status.HTTP_404_NOT_FOUND,
            )

        admission.lastmodified_date = timezone.now()
        # _save_admission assigns all 3 arrays, calls save(), then syncs Mongo
        _save_admission(admission, rd, sd, ap)

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

        client, hms_db = _get_hms_db()

        # ── Find active admission directly in MongoDB ────────────────
        query = {
            "is_discharged": {"$ne": True},
            "is_cancelled": {"$ne": True},
        }
        if uhid:
            query["uhid"] = uhid
        if ip_number:
            query["ipNumber"] = ip_number

        admission = hms_db["hospital_admission"].find_one(
            query,
            sort=[("admissionDateTime", -1)]
        )

        if not admission:
            fallback_query = {"is_discharged": {"$ne": True}}
            if ip_number:
                fallback_query["ipNumber"] = ip_number
            elif uhid:
                fallback_query["uhid"] = uhid
            admission = hms_db["hospital_admission"].find_one(
                fallback_query,
                sort=[("admissionDateTime", -1)]
            )

        if not admission:
            return Response(
                {"success": False, "error": "No active admission found", "message": "No active admission found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # ── Patient (indexed lookup) ──────────────────────────────────────
        patient_data = {}
        adm_uhid = str(admission.get("uhid") or "").strip()
        if adm_uhid:
            patient = hms_db["hospital_patient"].find_one({"uhid": adm_uhid})
            if patient:
                patient_data = {
                    "uhid":        str(patient.get("uhid") or ""),
                    "patientname": f"{patient.get('firstName') or ''} {patient.get('lastName') or ''}".strip(),
                    "firstName":   str(patient.get("firstName") or ""),
                    "lastName":    str(patient.get("lastName") or ""),
                    "age":         str(patient.get("age") or ""),
                    "gender":      str(patient.get("gender") or ""),
                    "mobilePhone": str(patient.get("mobilePhone") or ""),
                    "email":       str(patient.get("email") or ""),
                    "city":        str(patient.get("city") or ""),
                    "state":       str(patient.get("state") or ""),
                    "area":        str(patient.get("area") or ""),
                    "zipcode":     str(patient.get("zipcode") or ""),
                }

        # ── Active room from room_details ─────────────────────────────────
        room_details = _safe_list(admission.get("room_details"))
        active_room  = {}
        for r in reversed(room_details):
            if isinstance(r, dict) and r.get("is_roomActive"):
                active_room = r
                break
        if not active_room and room_details:
            last = room_details[-1]
            active_room = last if isinstance(last, dict) else {}

        # ── Has already been shifted? ─────────────────────────────────────
        shiftings   = _safe_list(admission.get("roomShitingDetails"))
        has_shifted = any(isinstance(s, dict) for s in shiftings)

        # ── Check RoomBooking for a pre-reserved room ─────────────────────
        reserved_room = None
        reserved_bed  = None
        has_reservation = False
        adm_ip = str(admission.get("ipNumber") or "").strip()
        if adm_ip:
            booking = hms_db["hospital_roombooking"].find_one({
                "ip_number": adm_ip,
                "is_booked": True,
                "room_shifted": False
            })
            if booking:
                has_reservation = True
                reserved_room   = str(booking.get("room_number") or "")
                reserved_bed    = str(booking.get("bed_number") or "")

        # ── Admission date + time formatting ─────────────────────────────
        admission_date = admission_time = ""
        formatted_datetime = ""

        dt = admission.get("admissionDateTime")
        if dt:
            if isinstance(dt, datetime):
                admission_date = dt.strftime("%Y-%m-%d")
                admission_time = dt.strftime("%H:%M:%S")
                formatted_datetime = dt.strftime("%d-%m-%Y %I:%M %p")
            else:
                dt_str = str(dt)
                admission_date = dt_str[:10]
                admission_time = dt_str[11:19]
                formatted_datetime = f"{admission_date} {admission_time}".strip()

        # ── Doctor Name Mapping ──────────────────────────────────────────
        doctor_id = str(admission.get("admittingDoctor") or "").strip()
        doctor_name = ""

        if doctor_id:
            try:
                global_db = client['Global']
                doc = global_db['backend_diagnostics_profile'].find_one(
                    {"employeeId": doctor_id},
                    {"employeeName": 1, "_id": 0}
                )
                if doc:
                    doctor_name = doc.get("employeeName", "")
            except Exception:
                pass

        return Response({
            "success": True,
            "data": {
                "uhid":             str(admission.get("uhid") or ""),
                "ipNumber":         str(admission.get("ipNumber") or ""),
                "ipserial_number":  str(admission.get("ipserial_number") or ""),
                "admittingDoctor":      doctor_id,
                "admittingDoctorName":  doctor_name,
                "admissionDate":        admission_date,
                "admissionTime":        admission_time,
                "admissionDateTime":    formatted_datetime,
                "consultingDoctor": str(admission.get("consultingDoctor") or ""),
                "packageName":      str(admission.get("packageName") or ""),
                "roomNo":           active_room.get("roomNo", ""),
                "bedNo":            active_room.get("bedNo", ""),
                "room_details":     room_details,
                "has_shifted":      has_shifted,
                # ── Reservation fields ─────────────────────────────────────
                "has_reservation":  has_reservation,
                "reservedRoomNo":   reserved_room or "",
                "reservedBedNo":    reserved_bed  or "",
                # ── Status flags ───────────────────────────────────────────
                "is_admitted":        admission.get("is_admitted"),
                "is_discharged":      admission.get("is_discharged"),
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

    user_id = (request.data.get('auth-user-id') or request.headers.get('auth-user-id') or "system")

    # ════════════════════════════════════════════════════════════════════════
    # GET — list shifting history (Fast Indexed Direct Query + Batching)
    # ════════════════════════════════════════════════════════════════════════
    if request.method == "GET":
        try:
            from_date = str(request.GET.get("from_date", "")).strip()[:10]
            to_date   = str(request.GET.get("to_date",   "")).strip()[:10]
            uhid      = str(request.GET.get("uhid",      "")).strip()
            ip_number = str(request.GET.get("ip_number", "")).strip()

            client, hms_db = _get_hms_db()
            _ensure_room_indexes(hms_db)

            adm_query = {"roomShitingDetails.0": {"$exists": True}}
            if uhid:
                adm_query["uhid"] = {"$regex": f"^{re.escape(uhid)}", "$options": "i"} if len(uhid) < 6 else uhid
            if ip_number:
                adm_query["ipNumber"] = {"$regex": f"^{re.escape(ip_number)}", "$options": "i"} if len(ip_number) < 6 else ip_number

            # Fetch matching admissions with projection of only required fields
            admissions_cursor = hms_db["hospital_admission"].find(
                adm_query,
                {
                    "uhid": 1,
                    "ipNumber": 1,
                    "ipserial_number": 1,
                    "room_details": 1,
                    "roomShitingDetails": 1,
                    "lastmodified_date": 1,
                }
            ).sort([("lastmodified_date", -1)]).limit(5000)

            admissions_list = list(admissions_cursor)

            # ── Batch fetch all Patient names in a single indexed query ──────
            uhids = list(filter(None, {str(a.get("uhid") or "").strip() for a in admissions_list}))
            patient_name_map = {}
            if uhids:
                pat_cursor = hms_db["hospital_patient"].find(
                    {"uhid": {"$in": uhids}},
                    {"uhid": 1, "firstName": 1, "lastName": 1, "_id": 0}
                )
                for p in pat_cursor:
                    uk = str(p.get("uhid") or "").strip()
                    if uk:
                        patient_name_map[uk] = f"{p.get('firstName') or ''} {p.get('lastName') or ''}".strip()

            results = []
            for admission in admissions_list:
                adm_uhid = str(admission.get("uhid") or "").strip()
                adm_ip   = str(admission.get("ipNumber") or "").strip()
                patient_name = patient_name_map.get(adm_uhid, "")

                # Current active room (for old room display)
                room_details = _safe_list(admission.get("room_details"))
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

                shiftings = _safe_list(admission.get("roomShitingDetails"))

                for shift in shiftings:
                    if not isinstance(shift, dict):
                        continue

                    raw_dt = shift.get("shiftingDateTime") or shift.get("startDateTime") or ""
                    if isinstance(raw_dt, dict) and "$date" in raw_dt:
                        raw_dt = raw_dt["$date"]
                    if hasattr(raw_dt, "strftime"):
                        shift_date = raw_dt.strftime("%Y-%m-%d")
                    else:
                        shift_date = str(raw_dt).replace("T", " ")[:10]

                    if from_date and shift_date and shift_date < from_date:
                        continue
                    if to_date and shift_date and shift_date > to_date:
                        continue

                    results.append({
                        "uhid":             adm_uhid,
                        "ipNumber":         adm_ip,
                        "ipserial_number":  str(admission.get("ipserial_number") or ""),
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

        except Exception as exc:
            traceback.print_exc()
            return Response(
                {"error": f"Failed to fetch shifting history: {str(exc)}"},
                status=500,
            )

    # ════════════════════════════════════════════════════════════════════════
    # POST — create a new shift (Indexed Direct Filter)
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

        # Direct indexed lookup for active admission
        admission = Admission.objects.filter(
            ipNumber=ip_number,
            is_admitted=True,
            is_discharged=False,
            is_cancelled=False
        ).first()

        if not admission:
            admission = Admission.objects.filter(
                ipNumber=ip_number,
                is_discharged=False
            ).first()

        if not admission:
            return Response(
                {"success": False, "error": "No active admission found for this IP Number"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # ── Guard: only one active shift allowed ──────────────────────────
        existing_shiftings = _safe_list(admission.roomShitingDetails)
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
        room_details = _safe_list(admission.room_details)
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
                obj["endDateTime"]   = now_iso
            updated_room_details.append(obj)

        admission.room_details = updated_room_details

        # ── Build new shifting entry ──────────────────────────────────────
        new_shifting_id = generate_shifting_id(existing_shiftings)

        cleaned_shiftings = []
        for shift in existing_shiftings:
            if isinstance(shift, dict):
                cleaned_shiftings.append(dict(shift))

        cleaned_shiftings.append({
            "shifting_id":      new_shifting_id,
            "bill_number":      new_shifting_id,
            "bill_no":          new_shifting_id,
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
        })

        admission.roomShitingDetails = cleaned_shiftings
        admission.lastmodified_by    = str(user_id)
        admission.lastmodified_date  = timezone.now()

        ap = _safe_list(admission.advance_payments)
        _save_admission(admission, updated_room_details, cleaned_shiftings, ap)

        # ── Mark RoomBooking as shifted (indexed direct update) ───────────
        try:
            RoomBooking.objects.filter(
                ip_number=str(ip_number).strip(),
                is_booked=True,
                room_shifted=False
            ).update(
                room_shifted=True,
                is_booked=False
            )
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
# PUT /room-shifting/<ip_number>/update/
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["PUT"])
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

    # Direct indexed lookup
    admission = Admission.objects.filter(ipNumber=str(ip_number).strip()).first()

    if not admission:
        return Response(
            {"success": False, "error": "Admission not found"},
            status=status.HTTP_404_NOT_FOUND,
        )

    shifting_details = _safe_list(admission.roomShitingDetails)
    room_details     = _safe_list(admission.room_details)
    advance_payments = _safe_list(admission.advance_payments)

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
            obj["endDateTime"]        = now_iso
            obj["lastmodified_by"]    = str(user_id)
            obj["lastmodified_date"]  = now_iso
            old_room_no = str(obj.get("newRoomNo", ""))
            old_bed_no  = str(obj.get("newBedNo",  ""))
        updated_shiftings.append(obj)

    # ── New shifting entry ────────────────────────────────────────────────
    new_shifting_id = generate_shifting_id(updated_shiftings)
    updated_shiftings.append({
        "shifting_id":      new_shifting_id,
        "bill_number":      new_shifting_id,
        "bill_no":          new_shifting_id,
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
    _save_admission(admission, updated_rooms, updated_shiftings, advance_payments)

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