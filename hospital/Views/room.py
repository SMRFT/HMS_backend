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

from ..models import Block, RoomCategory, Room, Admission,Patient
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
        # STEP 1 — BUILD ADMISSION MAP FROM BOTH room_details & roomShitingDetails
        #
        # Key: (room_no, bed_no) → {
        #   is_roomActive, is_roomCleaned,
        #   patient_name, uhid, ip_number, ipserial_number
        # }
        #
        # Priority: the LAST entry with matching room/bed wins.
        # We iterate room_details first, then roomShitingDetails so that
        # shifting entries (more recent) override base room_details.
        # ══════════════════════════════════════════════════════════════════════
 
        admission_map = {}   # (room_no, bed_no) → admission info
        patient_map   = {}   # uhid → patient dict
 
        # Pre-load all patients keyed by uhid to avoid N+1 queries
        for patient in Patient.objects.all():
            patient_map[str(patient.uhid)] = {
                "uhid":        str(patient.uhid or ""),
                "patientname": f"{patient.firstName or ''} {patient.lastName or ''}".strip(),
                "age":         str(patient.age or ""),
                "gender":      str(patient.gender or ""),
                "mobilePhone": str(patient.mobilePhone or ""),
            }
 
        for admission in Admission.objects.all():
            if not getattr(admission, "is_admissionActive", False):
                continue
            if getattr(admission, "is_discharged", True):
                continue
 
            uhid        = str(admission.uhid or "")
            ip_number   = str(admission.ipNumber or "")
            ipserial    = str(admission.ipserial_number or "")
            patient_info = patient_map.get(uhid, {})
 
            details  = parse_json_field(admission.room_details)
            shiftings = parse_json_field(admission.roomShitingDetails)
 
            # Process room_details first
            for entry in details:
                if not isinstance(entry, dict):
                    continue
                room_no = str(entry.get("roomNo", "")).strip()
                bed_no  = str(entry.get("bedNo", "")).strip()
                if not room_no or not bed_no:
                    continue
 
                admission_map[(room_no, bed_no)] = {
                    "is_roomActive":  bool(entry.get("is_roomActive", False)),
                    "is_roomCleaned": bool(entry.get("is_roomCleaned", False)),
                    "uhid":           uhid,
                    "ip_number":      ip_number,
                    "ipserial":       ipserial,
                    "patient":        patient_info,
                    "source":         "room_details",
                }
 
            # Process roomShitingDetails — these override room_details entries
            for entry in shiftings:
                if not isinstance(entry, dict):
                    continue

                room_no = str(entry.get("newRoomNo", "")).strip()
                bed_no  = str(entry.get("newBedNo", "")).strip()
                if not room_no or not bed_no:
                    continue

                admission_map[(room_no, bed_no)] = {
                    "is_roomActive":  bool(entry.get("is_roomActive", False)),
                    "is_roomCleaned": bool(entry.get("is_roomCleaned", False)),
                    "uhid":           uhid,
                    "ip_number":      ip_number,
                    "ipserial":       ipserial,
                    "patient":        patient_info,
                    "source":         "shifting",
                    "shifting_id":    str(entry.get("shifting_id", "")),
                }
 
        # ══════════════════════════════════════════════════════════════════════
        # STEP 2 — PROCESS ROOMS
        # ══════════════════════════════════════════════════════════════════════
 
        for room in Room.objects.all():
            if not getattr(room, "is_active", False):
                continue
 
            floor = getattr(room, "floor", 0) or 0
 
            if floor not in floor_map:
                floor_map[floor] = []
 
            beds      = parse_json_field(room.beds)
            beds_data = []
 
            for bed in beds:
                if not isinstance(bed, dict):
                    continue
 
                bed_number = str(bed.get("bed_number", "")).strip()
                if not bed_number:
                    continue
 
                # Determine status
                if getattr(room, "room_status", "") == "Blocked" or getattr(room, "room_blocked", False):
                    status_str   = "Maintenance"
                    patient_data = {}
                else:
                    key           = (str(room.room_number), bed_number)
                    admission_info = admission_map.get(key)
 
                    if admission_info:
                        active   = admission_info["is_roomActive"]
                        cleaned  = admission_info["is_roomCleaned"]
                        patient_data = admission_info.get("patient", {})
 
                        if active and not cleaned:
                            # Bed is currently occupied by a patient
                            status_str = "Occupied"
                        elif not active and cleaned:
                            # Patient left AND bed is cleaned → truly available
                            status_str   = "Available"
                            patient_data = {}
                        elif not active and not cleaned:
                            # Patient left but bed not yet cleaned
                            status_str = "Available (Not Cleaned)"
                        else:
                            # active=True, cleaned=True — treat as occupied (edge case)
                            status_str = "Occupied"
                    else:
                        status_str   = "Available"
                        patient_data = {}
 
                # Determine if this bed entry came from a shifting record
                # (so the frontend can send the right update key)
                source_info = admission_map.get((str(room.room_number), bed_number), {})
 
                beds_data.append({
                    "bed_number":  bed_number,
                    "status":      status_str,
                    "patient":     patient_data,
                    "source":      source_info.get("source", ""),
                    "shifting_id": source_info.get("shifting_id", ""),
                    "ip_number":   source_info.get("ip_number", ""),
                })
 
            floor_map[floor].append({
                "room_number": room.room_number,
                "room_type":   room.room_type,
                "block":       room.block,
                "beds":        beds_data,
            })
 
        # ══════════════════════════════════════════════════════════════════════
        # STEP 3 — SORT AND RETURN
        # ══════════════════════════════════════════════════════════════════════
        for floor in sorted(floor_map.keys()):
            result.append({
                "floor": floor,
                "rooms": floor_map[floor],
            })
 
        return Response(result)
 
    except Exception as exc:
        traceback.print_exc()
        return Response(
            {"error": f"Room enquiry failed: {str(exc)}"},
            status=500,
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
 
@api_view(["GET"])
@csrf_exempt
def get_active_admission(request):
    try:
        uhid      = request.GET.get("uhid",      "").strip()
        ip_number = request.GET.get("ip_number", "").strip()
 
        if not uhid and not ip_number:
            return Response(
                {"success": False, "message": "Provide UHID or IP Number"},
                status=status.HTTP_400_BAD_REQUEST,
            )
 
        # Filter using model (no SQL)
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
 
        # Patient
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
                }
        except Exception:
            traceback.print_exc()
 
        # room_details
        room_details = parse_json_field(admission.room_details)
 
        # active room
        active_room = {}
        for r in reversed(room_details):
            if isinstance(r, dict) and r.get("is_roomActive"):
                active_room = r
                break
        if not active_room and room_details:
            last = room_details[-1]
            active_room = last if isinstance(last, dict) else {}
 
        # Check if this admission has already been shifted
        # (has any non-cancelled entry in roomShitingDetails)
        shiftings   = parse_json_field(admission.roomShitingDetails)
        has_shifted = any(isinstance(s, dict) for s in shiftings)
        
        # datetime formatting
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
                "has_shifted":      has_shifted,   # ← tells frontend to disable form
                "is_admitted":        getattr(admission, "is_admitted",        None),
                "is_admissionActive": getattr(admission, "is_admissionActive", None),
                "is_discharged":      getattr(admission, "is_discharged",      None),
                "patient": patient_data,
            },
        }, status=status.HTTP_200_OK)
 
    except Exception as e:
        traceback.print_exc()
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
 
 
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
 
            # Patient info for display
            patient_name = ""
            try:
                patient = Patient.objects.filter(uhid=admission.uhid).first()
                if patient:
                    patient_name = f"{patient.firstName or ''} {patient.lastName or ''}".strip()
            except Exception:
                pass
 
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
                    "newRoomNo":        str(shift.get("newRoomNo",        "")),
                    "newBedNo":         str(shift.get("newBedNo",         "")),
                    "shiftingDateTime": str(shift.get("shiftingDateTime", "")),
                    "shifted_by":       str(shift.get("shifted_by",       "")),
                    "is_roomActive":    bool(shift.get("is_roomActive",   False)),
                    "is_roomCleaned":   bool(shift.get("is_roomCleaned",  False)),
                })
 
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
 
        # ── GUARD: only one active shift allowed per admission ────────────
        existing_shiftings = parse_json_field(admission.roomShitingDetails)
        active_shiftings = [
            s for s in existing_shiftings
            if isinstance(s, dict)
        ]

        if active_shiftings:
            return Response(
                {
                    "success": False,
                    "error": "Room already shifted. Use Edit for existing shifting record.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
 
        # ── Find current active room for oldRoomNo / oldBedNo ─────────────
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
 
        # ── Deactivate current room in room_details ────────────────────────
        updated_room_details = []
        for room in room_details:
            if not isinstance(room, dict):
                continue
            obj = {
                "roomNo":         str(room.get("roomNo",         "")),
                "bedNo":          str(room.get("bedNo",          "")),
                "is_roomActive":  bool(room.get("is_roomActive",  False)),
                "is_roomCleaned": bool(room.get("is_roomCleaned", False)),
            }
            if obj["is_roomActive"]:
                obj["is_roomActive"] = False
            updated_room_details.append(obj)
 
        admission.room_details = updated_room_details
 
        # ── Build shifting entry ───────────────────────────────────────────
        new_shifting_id = generate_shifting_id(existing_shiftings)
 
        cleaned_shiftings = []
        for shift in existing_shiftings:
            if not isinstance(shift, dict):
                continue
            cleaned_shiftings.append({
                "shifting_id":      str(shift.get("shifting_id",      "")),
                "newRoomNo":        str(shift.get("newRoomNo",        "")),
                "newBedNo":         str(shift.get("newBedNo",         "")),
                "shiftingDateTime": str(shift.get("shiftingDateTime", "")),
                "shifted_by":       str(shift.get("shifted_by",       "")),
                "is_roomActive":    bool(shift.get("is_roomActive",   False)),
                "is_roomCleaned":   bool(shift.get("is_roomCleaned",  False)),
            })
 
        # New shift — is_roomActive: True, is_roomCleaned: False (requirement #5)
        cleaned_shiftings.append({
            "shifting_id":      new_shifting_id,
            "newRoomNo":        new_room,
            "newBedNo":         new_bed,
            "shiftingDateTime": timezone.now().isoformat(),
            "shifted_by":       str(user_id),
            "is_roomActive":    True,   # ← requirement #5
            "is_roomCleaned":   False,  # ← requirement #5
        })
 
        admission.roomShitingDetails = cleaned_shiftings
        admission.lastmodified_by    = str(user_id)
        admission.lastmodified_date  = timezone.now()
 
        if not isinstance(admission.advance_payments, list):
            admission.advance_payments = []
 
        admission.save()
 
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
# PATCH /room-shifting/<ip_number>/
# Editing creates a NEW shifting object; previous one is set is_roomActive: False
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
 
    shift_found  = False
    target_shift = None

    for shift in shifting_details:
        if isinstance(shift, dict) and str(shift.get("shifting_id", "")) == shifting_id:
            target_shift = shift
            shift_found = True
            break

    if not shift_found:
        return Response(
            {"success": False, "error": "Shifting record not found"},
            status=status.HTTP_404_NOT_FOUND,
        )

    updated_shiftings = []
    for shift in shifting_details:
        if not isinstance(shift, dict):
            continue

        obj = dict(shift)

        if str(obj.get("shifting_id", "")) == shifting_id:
            obj["is_roomActive"] = False
            obj["lastmodified_by"] = str(user_id)
            obj["lastmodified_date"] = timezone.now().isoformat()

        updated_shiftings.append(obj)

    new_shifting_id = generate_shifting_id(updated_shiftings)

    updated_shiftings.append({
        "shifting_id": new_shifting_id,
        "newRoomNo": new_room,
        "newBedNo": new_bed,
        "shiftingDateTime": timezone.now().isoformat(),
        "shifted_by": str(user_id),
        "is_roomActive": True,
        "is_roomCleaned": False,
        "edited_from": shifting_id,
    })
 
    # ── Deactivate current active room in room_details ────────────────────
    updated_rooms = []
    for room in room_details:
        if not isinstance(room, dict):
            continue
        obj = dict(room)
        if obj.get("is_roomActive"):
            obj["is_roomActive"] = False
        updated_rooms.append(obj)
 
    admission.roomShitingDetails = updated_shiftings
    admission.room_details       = updated_rooms
    admission.lastmodified_by    = str(user_id)
    admission.save()
 
    return Response(
        {
            "success": True,
            "message": "Room shifting updated (new record created)",
            "data": {
                "ipNumber":           admission.ipNumber,
                "room_details":       admission.room_details,
                "roomShitingDetails": admission.roomShitingDetails,
            },
        },
        status=status.HTTP_200_OK,
    )
 
