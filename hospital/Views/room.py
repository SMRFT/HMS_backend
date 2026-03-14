from rest_framework.response import Response
from rest_framework import status
from pymongo import MongoClient
import os
from rest_framework.decorators import api_view, permission_classes
from pyauth.auth import HasRoleAndDataPermission
from django.views.decorators.csrf import csrf_exempt

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
# ROOM ENQUIRY (Block → Floor → Room → Bed)
# --------------------------------------------------
@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def room_enquiry_view(request):
    try:
        result = []
        blocks = Block.objects.filter(is_active=True)

        for block in blocks:
            rooms = Room.objects.filter(
                block=block,
                is_active=True
            ).order_by("floor")

            floor_map = {}

            for room in rooms:
                floor = room.floor or 0
                floor_map.setdefault(floor, [])

                room_data = RoomSerializer(room).data
                floor_map[floor].append(room_data)

            result.append({
                "block": BlockSerializer(block).data,
                "floors": {str(k): v for k, v in floor_map.items()}
            })

        return Response(result)

    except Exception as e:
        return Response({"error": str(e)}, status=500)


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

