from rest_framework.response import Response
from rest_framework import status
from pymongo import MongoClient
import os
from rest_framework.decorators import api_view, permission_classes
from pyauth.auth import HasRoleAndDataPermission
from django.views.decorators.csrf import csrf_exempt
import json
import traceback

from ..models import Block, RoomCategory, Room, Admission
from ..serializers import (
    BlockSerializer,
    RoomCategorySerializer,
    RoomSerializer,
)

# --------------------------------------------------
# BLOCK
# --------------------------------------------------
@api_view(["GET", "POST", "PUT", "DELETE"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def block_view(request, pk=None):

    user_id = request.headers.get("auth-user-id", "system")

    # ── GET ──────────────────────────────────────────────────────────────────
    if request.method == "GET":
        if pk:
            try:
                block = Block.objects.get(block_id=pk)
                if not block.is_active:
                    return Response({"error": "Block not found"}, status=404)
            except Block.DoesNotExist:
                return Response({"error": "Block not found"}, status=404)
            except (ValueError, TypeError):
                return Response({"error": "Invalid Block ID"}, status=400)

            serializer = BlockSerializer(block)
            return Response(serializer.data)

        # List – filter in Python to avoid Djongo boolean filter bug
        all_blocks = Block.objects.all().order_by("block_id")
        blocks = [b for b in all_blocks if b.is_active]
        serializer = BlockSerializer(blocks, many=True)
        return Response(serializer.data)

    # ── POST ─────────────────────────────────────────────────────────────────
    if request.method == "POST":
        serializer = BlockSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(created_by=user_id, lastmodified_by=user_id)
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)

    # ── PUT ──────────────────────────────────────────────────────────────────
    if request.method == "PUT":
        if not pk:
            return Response({"error": "Block ID required"}, status=400)
        try:
            block = Block.objects.get(block_id=pk)
            if not block.is_active:
                return Response({"error": "Block not found"}, status=404)
        except Block.DoesNotExist:
            return Response({"error": "Block not found"}, status=404)
        except (ValueError, TypeError):
            return Response({"error": "Invalid Block ID"}, status=400)

        serializer = BlockSerializer(block, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save(lastmodified_by=user_id)
            return Response(serializer.data)
        return Response(serializer.errors, status=400)

    # ── DELETE ───────────────────────────────────────────────────────────────
    if request.method == "DELETE":
        if not pk:
            return Response({"error": "Block ID required"}, status=400)
        try:
            block = Block.objects.get(block_id=pk)
            if not block.is_active:
                return Response({"error": "Block not found"}, status=404)
        except Block.DoesNotExist:
            return Response({"error": "Block not found"}, status=404)
        except (ValueError, TypeError):
            return Response({"error": "Invalid Block ID"}, status=400)

        block.is_active = False
        block.lastmodified_by = user_id
        block.save()
        return Response({"message": "Deleted successfully"}, status=200)
        

# --------------------------------------------------
# ROOM CATEGORY
# --------------------------------------------------
@api_view(["GET", "POST", "PUT", "DELETE"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def room_category_view(request, pk=None):

    user_id = request.headers.get("auth-user-id", "system")

    # ── GET ─────────────────────────────────────────
    if request.method == "GET":
        if pk:
            try:
                category = RoomCategory.objects.get(room_category_id=pk)
                if not category.is_active:
                    return Response({"error": "Room category not found"}, status=404)
            except RoomCategory.DoesNotExist:
                return Response({"error": "Room category not found"}, status=404)
            except (ValueError, TypeError):
                return Response({"error": "Invalid Room Category ID"}, status=400)

            serializer = RoomCategorySerializer(category)
            return Response(serializer.data)

        # List – filter in Python (Djongo boolean workaround)
        all_categories = RoomCategory.objects.all().order_by("room_category_id")
        categories = [c for c in all_categories if c.is_active]
        serializer = RoomCategorySerializer(categories, many=True)
        return Response(serializer.data)

    # ── POST ────────────────────────────────────────
    if request.method == "POST":
        serializer = RoomCategorySerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(created_by=user_id, lastmodified_by=user_id)
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)

    # ── PUT ─────────────────────────────────────────
    if request.method == "PUT":
        if not pk:
            return Response({"error": "Room Category ID required"}, status=400)
        try:
            category = RoomCategory.objects.get(room_category_id=pk)
            if not category.is_active:
                return Response({"error": "Room category not found"}, status=404)
        except RoomCategory.DoesNotExist:
            return Response({"error": "Room category not found"}, status=404)
        except (ValueError, TypeError):
            return Response({"error": "Invalid Room Category ID"}, status=400)

        serializer = RoomCategorySerializer(category, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save(lastmodified_by=user_id)
            return Response(serializer.data)
        return Response(serializer.errors, status=400)

    # ── DELETE ──────────────────────────────────────
    if request.method == "DELETE":
        if not pk:
            return Response({"error": "Room Category ID required"}, status=400)
        try:
            category = RoomCategory.objects.get(room_category_id=pk)
            if not category.is_active:
                return Response({"error": "Room category not found"}, status=404)
        except RoomCategory.DoesNotExist:
            return Response({"error": "Room category not found"}, status=404)
        except (ValueError, TypeError):
            return Response({"error": "Invalid Room Category ID"}, status=400)

        category.is_active = False
        category.lastmodified_by = user_id
        category.save()
        return Response({"message": "Deleted successfully"}, status=200)


@api_view(["GET"])
def room_service_description_view(request):

    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    db = client.HMS
    collection = db.hospital_roomservice_description

    data = list(collection.find({"is_active": True}))

    result = []

    for item in data:
        result.append({
            "description": item.get("description", "")
        })

    return Response(result)


# --------------------------------------------------
# ROOM (with Nested Beds, Services, Kits)
# --------------------------------------------------
@api_view(['GET', 'POST', 'PUT', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def room_view(request, pk=None):

    user_id = request.headers.get("auth-user-id", "system")

    if request.method == "GET":

        # -------- Single Room --------
        if pk:
            try:
                room = Room.objects.get(pk=pk)

                if not room.is_active:
                    return Response({"error": "Room not found"}, status=404)

                return Response(RoomSerializer(room).data)

            except Room.DoesNotExist:
                return Response({"error": "Room not found"}, status=404)

        # -------- All Active Rooms --------
        all_rooms = Room.objects.all()
        active_rooms = [room for room in all_rooms if room.is_active]

        return Response(RoomSerializer(active_rooms, many=True).data)

    elif request.method == "POST":

        data = request.data.copy()

        services = data.pop("services", [])
        beds = data.pop("beds", [])
        room_kits = data.pop("room_kits", [])

        room_number = data.get("room_number")

        # Duplicate check (Djongo-safe)
        existing_rooms = Room.objects.filter(room_number=room_number)

        if any(room.is_active for room in existing_rooms):
            return Response(
                {"error": "Room with this room number already exists"},
                status=400
            )

        serializer = RoomSerializer(data=data)

        if serializer.is_valid():

            room = serializer.save(
                created_by=user_id,
                lastmodified_by=user_id
            )

            # Assign nested JSON fields
            room.services = services
            room.beds = beds
            room.room_kits = room_kits

            room.save()

            return Response(RoomSerializer(room).data, status=201)

        return Response(serializer.errors, status=400)

    elif request.method == "PUT":

        try:
            room = Room.objects.get(pk=pk)

            if not room.is_active:
                return Response({"error": "Room not found"}, status=404)

        except Room.DoesNotExist:
            return Response({"error": "Room not found"}, status=404)

        data = request.data.copy()

        services = data.pop("services", None)
        beds = data.pop("beds", None)
        room_kits = data.pop("room_kits", None)

        new_room_number = data.get("room_number")

        # Duplicate check (exclude current room)
        if new_room_number and new_room_number != room.room_number:

            existing_rooms = Room.objects.filter(room_number=new_room_number)

            if any(r.is_active and str(r.pk) != str(pk) for r in existing_rooms):
                return Response(
                    {"error": "Room with this room number already exists"},
                    status=400
                )

        serializer = RoomSerializer(room, data=data, partial=True)

        if serializer.is_valid():

            room = serializer.save(lastmodified_by=user_id)

            if services is not None:
                room.services = services

            if beds is not None:
                room.beds = beds

            if room_kits is not None:
                room.room_kits = room_kits

            room.save()

            return Response(RoomSerializer(room).data)

        return Response(serializer.errors, status=400)

    elif request.method == "DELETE":

        try:
            room = Room.objects.get(pk=pk)

            if not room.is_active:
                return Response({"error": "Room not found"}, status=404)

            room.is_active = False
            room.lastmodified_by = user_id
            room.save()

            return Response({"message": "Deleted successfully"})

        except Room.DoesNotExist:
            return Response({"error": "Room not found"}, status=404)
    

# --------------------------------------------------
# ROOM SHIFTING
# --------------------------------------------------
@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def room_shifting_view(request):
    user_id = request.headers.get("auth-user-id", "system")

    # ==================== GET (Search Admission) ====================
    if request.method == "GET":
        query = request.GET.get("search") # UHID or IP

        if not query:
            return Response({"error": "Search query (UHID or IP) required"}, status=400)

        # Try to find active admission by UHID or IP
        admissions = Admission.objects.filter(is_active=True).filter(
            models.Q(uhid__icontains=query) | models.Q(ipNumber__icontains=query)
        )
        
        if not admissions.exists():
             return Response({"error": "Active admission not found"}, status=404)
        
        # Return the first match or list? Let's return list if needed, but simplistic approach first match
        admission = admissions.first()

        return Response({
            "uhid": admission.uhid,
            "ip_no": admission.ipNumber,
            "patient_name": f"{admission.firstName} {admission.lastName}",
            "current_room_no": admission.roomNo,
            "current_bed_no": admission.bedNo,
        })

    # ==================== POST (Shift Room) ====================
    elif request.method == "POST":
        uhid = request.data.get("uhid")
        ip_no = request.data.get("ip_no")
        new_room_no = request.data.get("newRoomNo")
        new_bed_no = request.data.get("newBedNo")

        if not (uhid or ip_no) or not (new_room_no and new_bed_no):
            return Response({"error": "Missing required fields"}, status=400)

        try:
            if uhid:
                admission = Admission.objects.get(uhid=uhid, is_active=True)
            else:
                admission = Admission.objects.get(ipNumber=ip_no, is_active=True)
        except Admission.DoesNotExist:
            return Response({"error": "Active admission not found"}, status=404)
        
        old_room_no = admission.roomNo
        old_bed_no = admission.bedNo

        # 1. Update Admission
        admission.roomNo = new_room_no
        admission.bedNo = new_bed_no
        admission.lastmodified_by = user_id
        admission.save()

        # 3. Update New Bed (Make Occupied)
        try:
            new_room = Room.objects.get(room_number=new_room_no, is_active=True)
        except Room.DoesNotExist:
             return Response({"error": f"New Room {new_room_no} not found"}, status=404)

        return Response({"message": "Room shifted successfully"})



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


# --------------------------------------------------
# ROOM ENQUIRY
# --------------------------------------------------
@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def room_enquiry_view(request):

    try:

        result = []
        floor_map = {}

        # ==================================================
        # STEP 1 — BUILD ADMISSION MAP (OCCUPIED BEDS)
        # ==================================================
        admission_map = {}

        admissions = Admission.objects.values(
            "room_details",
            "roomShitingDetails",
            "is_admissionActive",
            "is_discharged",
        )

        for admission in admissions:

            if not admission.get("is_admissionActive"):
                continue

            if admission.get("is_discharged"):
                continue

            details = parse_json_field(admission.get("room_details"))
            shifts  = parse_json_field(admission.get("roomShitingDetails"))

            for entry in details + shifts:

                if not isinstance(entry, dict):
                    continue

                room_no = str(entry.get("roomNo", "")).strip()
                bed_no  = str(entry.get("bedNo", "")).strip()

                if not room_no or not bed_no:
                    continue

                admission_map[(room_no, bed_no)] = {
                    "is_roomActive": bool(entry.get("is_roomActive", False)),
                    "is_roomCleaned": bool(entry.get("is_roomCleaned", False)),
                }

        # ==================================================
        # STEP 2 — PROCESS ROOMS
        # ==================================================
        rooms = Room.objects.values(
            "room_number",
            "floor",
            "room_type",
            "block",
            "room_status",
            "room_blocked",
            "is_active",
            "beds",
        )

        for room in rooms:

            if not room.get("is_active"):
                continue

            floor = room.get("floor") or 0

            if floor not in floor_map:
                floor_map[floor] = []

            beds_raw = room.get("beds")
            beds = parse_json_field(beds_raw)

            beds_data = []

            for bed in beds:

                if not isinstance(bed, dict):
                    continue

                bed_number = str(bed.get("bed_number", "")).strip()

                if not bed_number:
                    continue

                # --------------------------------------------------
                # Determine bed status
                # --------------------------------------------------
                if room.get("room_status") == "Blocked" or room.get("room_blocked"):

                    status = "Maintenance"

                else:

                    key = (str(room.get("room_number")), bed_number)

                    admission_info = admission_map.get(key)

                    if admission_info:

                        active = admission_info["is_roomActive"]
                        cleaned = admission_info["is_roomCleaned"]

                        if active and not cleaned:
                            status = "Occupied"

                        elif not active and cleaned:
                            status = "Available"

                        elif not active and not cleaned:
                            status = "Available (Not Cleaned)"

                        else:
                            status = "Occupied"

                    else:
                        status = "Available"

                beds_data.append({
                    "bed_number": bed_number,
                    "status": status
                })

            floor_map[floor].append({
                "room_number": room.get("room_number"),
                "room_type": room.get("room_type"),
                "block": room.get("block"),
                "beds": beds_data,
            })

        # ==================================================
        # STEP 3 — SORT FLOORS
        # ==================================================
        for floor in sorted(floor_map.keys()):

            result.append({
                "floor": floor,
                "rooms": floor_map[floor]
            })

        return Response(result)

    except Exception as exc:

        print("ROOM ENQUIRY ERROR:", str(exc))
        traceback.print_exc()

        return Response(
            {"error": f"Room enquiry failed: {str(exc)}"},
            status=500
        )