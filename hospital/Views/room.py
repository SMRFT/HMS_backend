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
from django.utils import timezone
from django.utils import timezone as tz
from datetime import datetime
import traceback

from ..models import Block, RoomCategory, Room, Admission,Patient, RoomBooking
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
# ROOM ENQUIRY
# Returns floor → room → bed data with availability from BOTH
# room_details AND roomShiftingDetails.
# Also returns patient info per occupied bed for hover display.
# ─────────────────────────────────────────────────────────────────────────────
 
@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def room_enquiry_view(request):
    try:
        result = []
        floor_map = {}

        # ══════════════════════════════════════════════════════════════════════
        # STEP 1 — LOAD PATIENT DETAILS
        # ══════════════════════════════════════════════════════════════════════
        patient_map = {}
        for patient in Patient.objects.all():
            patient_map[str(patient.uhid)] = {
                "uhid":        str(patient.uhid or ""),
                "patientname": f"{patient.firstName or ''} {patient.lastName or ''}".strip(),
                "age":         str(patient.age or ""),
                "gender":      str(patient.gender or ""),
                "mobilePhone": str(patient.mobilePhone or ""),
            }

        # ══════════════════════════════════════════════════════════════════════
        # STEP 2 — BUILD ADMISSION MAP
        #
        # Key  : (room_no, bed_no)
        # Value: { status, patient, ip_number, is_roomCleaned, source, shifting_id }
        #
        # LOGIC:
        #   For each active admission (is_admissionActive=True, is_discharged=False):
        #
        #   A) Find the LATEST active shifting entry (is_roomActive=True).
        #      That room/bed → Occupied.
        #      All OTHER shifting entries with is_roomActive=False:
        #        - is_roomCleaned=True  → Available
        #        - is_roomCleaned=False → Available (Not Cleaned)
        #
        #   B) room_details entry:
        #      If ANY shifting exists, the original room is vacated.
        #      Apply same cleaned logic for original room.
        #      If NO shifting exists, use room_details is_roomActive to determine status.
        # ══════════════════════════════════════════════════════════════════════
        admission_map = {}

        for admission in Admission.objects.all():

            if not getattr(admission, "is_admissionActive", False):
                continue
            if getattr(admission, "is_discharged", False):
                continue

            uhid      = str(admission.uhid or "")
            ip_number = str(admission.ipNumber or "")
            ipserial  = str(admission.ipserial_number or "")
            patient_info = patient_map.get(uhid, {})

            details  = parse_json_field(admission.room_details)
            shifts   = parse_json_field(admission.roomShitingDetails)

            # ── Validate shifts are dicts ──────────────────────────────────
            shifts = [s for s in shifts if isinstance(s, dict)]

            has_shifts = len(shifts) > 0

            # ── Find the one currently-active shift (is_roomActive=True) ──
            # If multiple are active (data issue), take the one with highest shifting_id
            active_shifts = [s for s in shifts if bool(s.get("is_roomActive", False))]
            active_shift  = None
            if active_shifts:
                try:
                    active_shift = max(
                        active_shifts,
                        key=lambda s: int(s.get("shifting_id", 0))
                    )
                except Exception:
                    active_shift = active_shifts[-1]

            # ── Process each shift entry ───────────────────────────────────
            for shift in shifts:
                room_no = str(shift.get("newRoomNo", "")).strip()
                bed_no  = str(shift.get("newBedNo",  "")).strip()
                if not room_no or not bed_no:
                    continue

                is_active  = bool(shift.get("is_roomActive",  False))
                is_cleaned = bool(shift.get("is_roomCleaned", False))

                # This is the currently active room → Occupied
                if active_shift and shift.get("shifting_id") == active_shift.get("shifting_id"):
                    status       = "Occupied"
                    patient_data = patient_info
                else:
                    # Vacated shift entry
                    if is_cleaned:
                        status       = "Available"
                        patient_data = {}
                    else:
                        status       = "Available (Not Cleaned)"
                        patient_data = patient_info  # still shows who was there

                key = (room_no, bed_no)
                # Only write if not already written with a higher-priority (Occupied) status
                existing = admission_map.get(key)
                if existing is None or status == "Occupied":
                    admission_map[key] = {
                        "status":         status,
                        "patient":        patient_data,
                        "uhid":           uhid,
                        "ip_number":      ip_number,
                        "ipserial":       ipserial,
                        "is_roomCleaned": is_cleaned,
                        "is_roomActive":  is_active,   # ← ADD THIS
                        "source":         "shifting",
                        "shifting_id":    str(shift.get("shifting_id", "")),
                    }

            # ── Process room_details (original room) ───────────────────────
            for entry in details:
                if not isinstance(entry, dict):
                    continue

                room_no = str(entry.get("roomNo", "")).strip()
                bed_no  = str(entry.get("bedNo",  "")).strip()
                if not room_no or not bed_no:
                    continue

                is_active  = bool(entry.get("is_roomActive",  False))
                is_cleaned = bool(entry.get("is_roomCleaned", False))

                if has_shifts:
                    # Patient has shifted away from original room.
                    # Original room is now vacated — apply cleaned logic.
                    if is_cleaned:
                        status       = "Available"
                        patient_data = {}
                    else:
                        status       = "Available (Not Cleaned)"
                        patient_data = patient_info
                else:
                    # No shifts: use is_roomActive directly
                    if is_active and not is_cleaned:
                        status       = "Occupied"
                        patient_data = patient_info
                    elif not is_active and is_cleaned:
                        status       = "Available"
                        patient_data = {}
                    elif not is_active and not is_cleaned:
                        status       = "Available (Not Cleaned)"
                        patient_data = patient_info
                    else:
                        # is_active=True, is_cleaned=True (edge case) → treat as Occupied
                        status       = "Occupied"
                        patient_data = patient_info

                key = (room_no, bed_no)
                existing = admission_map.get(key)

                # Don't overwrite if a shift already wrote Occupied for this key
                if existing is None or (existing.get("status") != "Occupied" and status == "Occupied"):
                    admission_map[key] = {
                        "status":         status,
                        "patient":        patient_data,
                        "uhid":           uhid,
                        "ip_number":      ip_number,
                        "ipserial":       ipserial,
                        "is_roomCleaned": is_cleaned,
                        "is_roomActive":  is_active,   # ← ADD THIS
                        "source":         "room_details",
                        "shifting_id":    "",
                    }

        # STEP 3 — LOAD RoomBooking RESERVATIONS (Mongo-safe)
        # Key: (room_number, bed_number)
        # Only active bookings: is_booked=True, room_shifted=False
        # ══════════════════════════════════════════════════════════════════════
        booking_map = {}

        for booking in RoomBooking.objects.all():

            is_booked = bool(getattr(booking, "is_booked", False))
            room_shifted = bool(getattr(booking, "room_shifted", False))

            if not is_booked:
                continue

            if room_shifted:
                continue

            room_number = str(getattr(booking, "room_number", "")).strip()
            bed_number  = str(getattr(booking, "bed_number", "")).strip()

            if not room_number or not bed_number:
                continue

            key = (room_number, bed_number)

            booking_map[key] = {
                "ip_number": str(getattr(booking, "ip_number", "") or "").strip(),
                "uhid":      str(getattr(booking, "uhid", "") or "").strip(),
                "booked_at": str(
                    getattr(booking, "booked_date", None)
                    or getattr(booking, "booked_at", None)
                    or ""
                ),
            }
        # ══════════════════════════════════════════════════════════════════════
        # STEP 4 — PROCESS ROOM LIST
        # ══════════════════════════════════════════════════════════════════════
        for room in Room.objects.all():

            if not getattr(room, "is_active", False):
                continue

            floor = getattr(room, "floor", 0) or 0
            if floor not in floor_map:
                floor_map[floor] = []

            beds     = parse_json_field(room.beds)
            beds_data = []

            for bed in beds:
                if not isinstance(bed, dict):
                    continue

                bed_number = str(bed.get("bed_number", "")).strip()
                if not bed_number:
                    continue

                room_no_str = str(room.room_number).strip()
                key = (room_no_str, bed_number)

                # Room blocked / maintenance overrides everything
                if getattr(room, "room_blocked", False) or \
                   str(getattr(room, "room_status", "")).lower() == "blocked":
                    beds_data.append({
                        "bed_number":    bed_number,
                        "status":        "Maintenance",
                        "patient":       {},
                        "is_roomCleaned": False,
                        "source":        "",
                        "shifting_id":   "",
                        "ip_number":     "",
                        "booking":       None,
                    })
                    continue

                # Check admission map first
                info = admission_map.get(key)

                # In STEP 4, replace the "Check admission map first" branch:

                if info:
                    beds_data.append({
                        "bed_number":     bed_number,
                        "status":         info.get("status", "Available"),
                        "patient":        info.get("patient", {}),
                        "is_roomCleaned": info.get("is_roomCleaned", False),
                        "is_roomActive":  info.get("is_roomActive", False),   # ← ADD THIS
                        "source":         info.get("source", ""),
                        "shifting_id":    info.get("shifting_id", ""),
                        "ip_number":      info.get("ip_number", ""),
                        "booking":        None,
                    })
                    continue

                # Check booking map (only if not in admission map)
                booking_info = booking_map.get(key)
                if booking_info:
                    beds_data.append({
                        "bed_number":     bed_number,
                        "status":         "Reserved",
                        "patient":        {},
                        "is_roomCleaned": False,
                        "source":         "booking",
                        "shifting_id":    "",
                        "ip_number":      booking_info.get("ip_number", ""),
                        "booking":        booking_info,
                    })
                    continue

                # Truly available
                beds_data.append({
                    "bed_number":     bed_number,
                    "status":         "Available",
                    "patient":        {},
                    "is_roomCleaned": True,
                    "source":         "",
                    "shifting_id":    "",
                    "ip_number":      "",
                    "booking":        None,
                })

            floor_map[floor].append({
                "room_number": room.room_number,
                "room_type":   room.room_type,
                "block":       room.block,
                "beds":        beds_data,
            })

        # ══════════════════════════════════════════════════════════════════════
        # STEP 5 — SORT FLOOR WISE RESPONSE
        # ══════════════════════════════════════════════════════════════════════
        for floor in sorted(floor_map.keys()):
            result.append({
                "floor": floor,
                "rooms": floor_map[floor],
            })

        return Response(result, status=200)

    except Exception as exc:
        traceback.print_exc()
        return Response({"error": f"Room enquiry failed: {str(exc)}"}, status=500)
    

@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def book_room_view(request):
    try:
        ip_number   = str(request.data.get("ip_number", "")).strip()
        room_number = str(request.data.get("room_number", "")).strip()
        bed_number  = str(request.data.get("bed_number", "")).strip()

        if not ip_number:
            return Response(
                {"success": False, "error": "ip_number is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not room_number or not bed_number:
            return Response(
                {"success": False, "error": "room_number and bed_number are required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ─────────────────────────────────────────────
        # Find Admission by ip_number
        # ─────────────────────────────────────────────
        admission = None

        for adm in Admission.objects.all():
            if str(adm.ipNumber).strip() == ip_number:
                admission = adm
                break

        if not admission:
            return Response(
                {
                    "success": False,
                    "error": f"No admission found for IP Number: {ip_number}"
                },
                status=status.HTTP_404_NOT_FOUND
            )

        # ─────────────────────────────────────────────
        # Mongo-safe duplicate check
        # ─────────────────────────────────────────────
        existing_booking = None

        for booking in RoomBooking.objects.all():
            if (
                str(booking.room_number).strip() == room_number and
                str(booking.bed_number).strip() == bed_number and
                bool(booking.is_booked) is True and
                bool(getattr(booking, "room_shifted", False)) is False
            ):
                existing_booking = booking
                break

        if existing_booking:
            return Response(
                {
                    "success": False,
                    "error": (
                        f"Room {room_number} / Bed {bed_number} "
                        f"is already reserved (IP: {existing_booking.ip_number})"
                    )
                },
                status=status.HTTP_409_CONFLICT
            )

        # ─────────────────────────────────────────────
        # Create booking document
        # ─────────────────────────────────────────────
        booking = RoomBooking(
            ip_number=ip_number,
            room_number=room_number,
            bed_number=bed_number,
            is_booked=True,
            room_shifted=False,
            booked_date=timezone.now(),
        )

        booking.save()

        return Response(
            {
                "success": True,
                "message": f"Room {room_number} / Bed {bed_number} reserved successfully",
                "data": {
                    "ip_number": booking.ip_number,
                    "room_number": booking.room_number,
                    "bed_number": booking.bed_number,
                    "is_booked": booking.is_booked,
                    "room_shifted": booking.room_shifted,
                    "booked_date": booking.booked_date,
                }
            },
            status=status.HTTP_201_CREATED
        )

    except Exception as exc:
        traceback.print_exc()
        return Response(
            {
                "success": False,
                "error": f"Booking failed: {str(exc)}"
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
 
 
# ─────────────────────────────────────────────────────────────────────────────
# UPDATE is_roomCleaned (PATCH)
# Body: { "room_no": "101", "bed_no": "A", "is_roomCleaned": true }
# Updates the matching entry in room_details OR roomShitingDetails.
# ─────────────────────────────────────────────────────────────────────────────
 
@api_view(["PATCH"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def update_room_cleaned_view(request):
    try:
        room_no     = str(request.data.get("room_no", "")).strip()
        bed_no      = str(request.data.get("bed_no", "")).strip()
        is_cleaned  = bool(request.data.get("is_roomCleaned", False))
        ip_number   = str(request.data.get("ip_number", "")).strip()
        shifting_id = str(request.data.get("shifting_id", "")).strip()
 
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
 
        # Fallback: find admission that owns this room/bed
        if not admission:
            for adm in Admission.objects.all():
                if not getattr(adm, "is_admissionActive", False):
                    continue
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
 
        # ── Try to update matching shifting entry first ────────────────────
        shiftings = parse_json_field(admission.roomShitingDetails)
        new_shiftings = []
        for shift in shiftings:
            if not isinstance(shift, dict):
                continue
            obj = dict(shift)
            rn = str(obj.get("newRoomNo", "")).strip()
            bn = str(obj.get("newBedNo",  "")).strip()
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
            # ── Update room_details entry ──────────────────────────────────
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

        return Response({
            "success": True,
            "data": {
                "uhid":             str(admission.uhid            or ""),
                "ipNumber":         str(admission.ipNumber        or ""),
                "ipserial_number":  str(admission.ipserial_number or ""),
                "admissionDate":    admission_date,
                "admissionTime":    admission_time,
                "admittingDoctor":  str(admission.admittingDoctor  or ""),
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
