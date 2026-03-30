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


@api_view(["GET"])
@csrf_exempt
def get_active_admission(request):
    try:
        uhid       = request.GET.get("uhid", "").strip()
        ip_number  = request.GET.get("ip_number", "").strip()

        if not uhid and not ip_number:
            return Response({
                "success": False,
                "message": "Provide UHID or IP Number"
            }, status=status.HTTP_400_BAD_REQUEST)

        # ✅ Step 1: Basic queryset (Djongo safe)
        if uhid:
            qs = Admission.objects.filter(uhid=uhid)
        else:
            qs = Admission.objects.filter(ipNumber=ip_number)

        # ✅ Step 2: Convert to list (avoid Djongo issues)
        try:
            all_records = list(qs.values(
                'uhid', 'ipNumber', 'ipserial_number',
                'admissionDateTime', 'admittingDoctor', 'consultingDoctor',
                'packageName', 'room_details', 'roomShitingDetails',
                'reasonForAdmission', 'advance_payments',
                'mlc_type', 'mlc_doc', 'mlc_remarks',
                'is_advanceActive', 'is_admissionActive',
                'is_discharged', 'is_admitted',
            ))
        except Exception as db_err:
            traceback.print_exc()
            return Response({
                "success": False,
                "message": "Database query failed",
                "error": str(db_err)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # ✅ Step 3: Filter active admissions
        active_records = [
            r for r in all_records
            if r.get('is_admitted') is True
            and r.get('is_admissionActive') is True
            and r.get('is_discharged') is False
        ]

        if not active_records:
            return Response({
                "success": False,
                "message": "No active admission found"
            }, status=status.HTTP_404_NOT_FOUND)

        # ✅ Step 4: Sort latest admission
        def safe_sort_key(r):
            dt = r.get('admissionDateTime')
            if dt is None:
                return datetime.min
            if hasattr(dt, 'tzinfo') and dt.tzinfo is not None:
                return tz.make_naive(dt)
            return dt

        active_records.sort(key=safe_sort_key, reverse=True)
        admission = active_records[0]

        # ✅ Step 5: Fetch Patient using UHID
        patient_data = {}
        try:
            patient = Patient.objects.filter(
                uhid=admission.get('uhid')
            ).values(
                'uhid', 'firstName', 'lastName', 'age', 'gender',
                'mobilePhone', 'email', 'city', 'state'
            ).first()

            if patient:
                patient_data = {
                    "uhid": patient.get("uhid") or "",
                    "patientname": f"{patient.get('firstName','')} {patient.get('lastName','')}".strip(),
                    "firstName": patient.get("firstName") or "",
                    "lastName": patient.get("lastName") or "",
                    "age": patient.get("age") or "",
                    "gender": patient.get("gender") or "",
                    "mobilePhone": patient.get("mobilePhone") or "",
                    "email": patient.get("email") or "",
                    "city": patient.get("city") or "",
                    "state": patient.get("state") or "",
                }
        except Exception as e:
            traceback.print_exc()
            patient_data = {}

        # ✅ Step 6: Parse room_details
        room_details = admission.get('room_details') or []
        if not isinstance(room_details, list):
            try:
                room_details = json.loads(room_details) if isinstance(room_details, str) else []
            except Exception:
                room_details = []

        # ✅ Step 7: Find active room
        active_room = {}
        for r in reversed(room_details):
            if isinstance(r, dict) and r.get("is_roomActive"):
                active_room = r
                break

        if not active_room and room_details:
            last = room_details[-1]
            active_room = last if isinstance(last, dict) else {}

        # ✅ Step 8: Format datetime
        admission_date = ""
        admission_time = ""
        dt = admission.get('admissionDateTime')

        if dt:
            try:
                admission_date = dt.strftime("%Y-%m-%d")
                admission_time = dt.strftime("%H:%M:%S")
            except Exception:
                admission_date = str(dt)[:10]
                admission_time = str(dt)[11:19]

        # ✅ FINAL RESPONSE
        return Response({
            "success": True,
            "data": {
                "uhid":             admission.get('uhid') or "",
                "ipNumber":         admission.get('ipNumber') or "",
                "ipserial_number":  admission.get('ipserial_number') or "",

                "admissionDate":    admission_date,
                "admissionTime":    admission_time,

                "admittingDoctor":  admission.get('admittingDoctor') or "",
                "consultingDoctor": admission.get('consultingDoctor') or "",
                "packageName":      admission.get('packageName') or "",

                "roomNo":           active_room.get("roomNo", ""),
                "bedNo":            active_room.get("bedNo", ""),
                "room_details":     room_details,

                "is_admitted":        admission.get('is_admitted'),
                "is_admissionActive": admission.get('is_admissionActive'),
                "is_discharged":      admission.get('is_discharged'),

                # ✅ Patient Data
                "patient": patient_data
            }
        }, status=status.HTTP_200_OK)

    except Exception as e:
        traceback.print_exc()
        return Response({
            "success": False,
            "error": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def room_shifting_view(request):

    user_id = request.headers.get("auth-user-id", "system")

    # ══════════════════════════════════════════════════════════════════════════
    # GET
    # ══════════════════════════════════════════════════════════════════════════
    if request.method == "GET":

        from_date = str(request.GET.get("from_date", "")).strip()
        to_date   = str(request.GET.get("to_date", "")).strip()
        uhid      = str(request.GET.get("uhid", "")).strip()
        ip_number = str(request.GET.get("ip_number", "")).strip()

        results = []

        admissions = Admission.objects.filter(is_admitted=True)

        for admission in admissions:

            # avoid icontains / SQL-like filters
            if uhid and uhid.lower() not in str(admission.uhid).lower():
                continue

            if ip_number and ip_number.lower() not in str(admission.ipNumber).lower():
                continue

            shiftings = admission.roomShitingDetails
            if not isinstance(shiftings, list):
                shiftings = []

            for shift in shiftings:

                if not isinstance(shift, dict):
                    continue

                shift_date = str(shift.get("shiftingDateTime", ""))[:10]

                if from_date and shift_date and shift_date < from_date:
                    continue

                if to_date and shift_date and shift_date > to_date:
                    continue

                results.append({
                    "uhid": admission.uhid,
                    "ipNumber": admission.ipNumber,
                    "ipserial_number": admission.ipserial_number,
                    "shifting_id": str(shift.get("shifting_id", "")),
                    "oldRoomNo": str(shift.get("oldRoomNo", "")),
                    "oldBedNo": str(shift.get("oldBedNo", "")),
                    "newRoomNo": str(shift.get("newRoomNo", "")),
                    "newBedNo": str(shift.get("newBedNo", "")),
                    "shiftingDateTime": str(shift.get("shiftingDateTime", "")),
                    "shifted_by": str(shift.get("shifted_by", "")),
                    "is_cancelled": bool(shift.get("is_cancelled", False)),
                    "cancelled_by": str(shift.get("cancelled_by", "")),
                    "cancelled_at": str(shift.get("cancelled_at", "")),
                })

        return Response(results, status=status.HTTP_200_OK)

    # ══════════════════════════════════════════════════════════════════════════
    # POST
    # ══════════════════════════════════════════════════════════════════════════
    elif request.method == "POST":

        ip_number = str(request.data.get("ip_number", "")).strip()
        new_room  = str(request.data.get("newRoomNo", "")).strip()
        new_bed   = str(request.data.get("newBedNo", "")).strip()

        if not ip_number:
            return Response(
                {"success": False, "error": "ip_number is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not new_room or not new_bed:
            return Response(
                {"success": False, "error": "newRoomNo and newBedNo are required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        admission = None

        for adm in Admission.objects.all():
            if (
                str(adm.ipNumber) == ip_number and
                adm.is_admitted and
                adm.is_admissionActive
            ):
                admission = adm
                break

        if not admission:
            return Response(
                {"success": False, "error": "Admission not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        room_details = admission.room_details
        if not isinstance(room_details, list):
            room_details = []

        old_room = ""
        old_bed = ""

        updated_room_details = []

        # deactivate current active room
        for room in room_details:

            if not isinstance(room, dict):
                continue

            room_obj = {
                "roomNo": str(room.get("roomNo", "")),
                "bedNo": str(room.get("bedNo", "")),
                "is_roomActive": bool(room.get("is_roomActive", False)),
                "is_roomCleaned": bool(room.get("is_roomCleaned", False)),
            }

            if room_obj["is_roomActive"]:
                old_room = room_obj["roomNo"]
                old_bed = room_obj["bedNo"]
                room_obj["is_roomActive"] = False

            updated_room_details.append(room_obj)

        # update existing current room object if only one room exists
        updated_existing = False

        if len(updated_room_details) == 1:
            updated_room_details[0]["roomNo"] = new_room
            updated_room_details[0]["bedNo"] = new_bed
            updated_room_details[0]["is_roomActive"] = True
            updated_room_details[0]["is_roomCleaned"] = False
            updated_existing = True

        # if multiple rooms / history exists, append new room entry
        if not updated_existing:
            updated_room_details.append({
                "roomNo": new_room,
                "bedNo": new_bed,
                "is_roomActive": True,
                "is_roomCleaned": False,
            })

        admission.room_details = updated_room_details

        shifting_details = admission.roomShitingDetails
        if not isinstance(shifting_details, list):
            shifting_details = []

        cleaned_shiftings = []

        for shift in shifting_details:
            if isinstance(shift, dict):
                cleaned_shiftings.append({
                    "shifting_id": str(shift.get("shifting_id", "")),
                    "oldRoomNo": str(shift.get("oldRoomNo", "")),
                    "oldBedNo": str(shift.get("oldBedNo", "")),
                    "newRoomNo": str(shift.get("newRoomNo", "")),
                    "newBedNo": str(shift.get("newBedNo", "")),
                    "shiftingDateTime": str(shift.get("shiftingDateTime", "")),
                    "shifted_by": str(shift.get("shifted_by", "")),
                    "is_cancelled": bool(shift.get("is_cancelled", False)),
                    "cancelled_by": str(shift.get("cancelled_by", "")),
                    "cancelled_at": str(shift.get("cancelled_at", "")),
                })

        cleaned_shiftings.append({
            "shifting_id": str(uuid4()),
            "oldRoomNo": old_room,
            "oldBedNo": old_bed,
            "newRoomNo": new_room,
            "newBedNo": new_bed,
            "shiftingDateTime": timezone.now().isoformat(),
            "shifted_by": str(user_id),
            "is_cancelled": False,
            "cancelled_by": "",
            "cancelled_at": "",
        })

        admission.roomShitingDetails = cleaned_shiftings

        admission.lastmodified_by = str(user_id)

        if not isinstance(admission.advance_payments, list):
            admission.advance_payments = []

        admission.save()

        return Response(
            {
                "success": True,
                "message": "Room shifted successfully",
                "data": {
                    "uhid": admission.uhid,
                    "ipNumber": admission.ipNumber,
                    "room_details": admission.room_details,
                    "roomShitingDetails": admission.roomShitingDetails
                }
            },
            status=status.HTTP_200_OK
        )


# ─────────────────────────────────────────────────────────────────────────────
# PATCH /room-shifting/<ip_number>/
# Update only roomShitingDetails
# In room_details only make current active room inactive
# ─────────────────────────────────────────────────────────────────────────────
@api_view(["PATCH"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def room_shifting_detail_view(request, ip_number):

    user_id = request.headers.get("auth-user-id", "system")

    shifting_id = str(request.data.get("shifting_id", "")).strip()
    new_room    = str(request.data.get("newRoomNo", "")).strip()
    new_bed     = str(request.data.get("newBedNo", "")).strip()

    if not shifting_id:
        return Response(
            {"success": False, "error": "shifting_id is required"},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not new_room or not new_bed:
        return Response(
            {"success": False, "error": "newRoomNo and newBedNo are required"},
            status=status.HTTP_400_BAD_REQUEST
        )

    admission = None

    for adm in Admission.objects.all():
        if str(adm.ipNumber) == str(ip_number):
            admission = adm
            break

    if not admission:
        return Response(
            {"success": False, "error": "Admission not found"},
            status=status.HTTP_404_NOT_FOUND
        )

    shifting_details = admission.roomShitingDetails
    if not isinstance(shifting_details, list):
        shifting_details = []

    room_details = admission.room_details
    if not isinstance(room_details, list):
        room_details = []

    updated_shiftings = []
    shift_found = False

    for shift in shifting_details:

        if not isinstance(shift, dict):
            continue

        shift_obj = {
            "shifting_id": str(shift.get("shifting_id", "")),
            "oldRoomNo": str(shift.get("oldRoomNo", "")),
            "oldBedNo": str(shift.get("oldBedNo", "")),
            "newRoomNo": str(shift.get("newRoomNo", "")),
            "newBedNo": str(shift.get("newBedNo", "")),
            "shiftingDateTime": str(shift.get("shiftingDateTime", "")),
            "shifted_by": str(shift.get("shifted_by", "")),
            "is_cancelled": bool(shift.get("is_cancelled", False)),
            "cancelled_by": str(shift.get("cancelled_by", "")),
            "cancelled_at": str(shift.get("cancelled_at", "")),
        }

        if shift_obj["shifting_id"] == shifting_id:

            if shift_obj["is_cancelled"]:
                return Response(
                    {
                        "success": False,
                        "error": "Cancelled shifting record cannot be edited"
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            # only update roomShitingDetails values
            shift_obj["newRoomNo"] = new_room
            shift_obj["newBedNo"] = new_bed
            shift_obj["lastmodified_by"] = str(user_id)
            shift_obj["lastmodified_date"] = timezone.now().isoformat()

            shift_found = True

        updated_shiftings.append(shift_obj)

    if not shift_found:
        return Response(
            {"success": False, "error": "Shifting record not found"},
            status=status.HTTP_404_NOT_FOUND
        )

    # only deactivate currently active room in room_details
    updated_rooms = []

    for room in room_details:

        if not isinstance(room, dict):
            continue

        room_obj = {
            "roomNo": str(room.get("roomNo", "")),
            "bedNo": str(room.get("bedNo", "")),
            "is_roomActive": bool(room.get("is_roomActive", False)),
            "is_roomCleaned": bool(room.get("is_roomCleaned", False)),
        }

        if room_obj["is_roomActive"]:
            room_obj["is_roomActive"] = False

        updated_rooms.append(room_obj)

    admission.roomShitingDetails = updated_shiftings
    admission.room_details = updated_rooms
    admission.lastmodified_by = str(user_id)

    admission.save()

    return Response(
        {
            "success": True,
            "message": "Room shifting updated successfully",
            "data": {
                "ipNumber": admission.ipNumber,
                "room_details": admission.room_details,
                "roomShitingDetails": admission.roomShitingDetails
            }
        },
        status=status.HTTP_200_OK
    )

# ─────────────────────────────────────────────────────────────────────────────
# POST /room-shifting/<shifting_id>/cancel/
# ─────────────────────────────────────────────────────────────────────────────
@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def room_shifting_cancel_view(request, shifting_id):

    user_id = request.headers.get("auth-user-id", "system")

    admission = None

    for adm in Admission.objects.all():

        shiftings = adm.roomShitingDetails
        if not isinstance(shiftings, list):
            continue

        found = False

        for shift in shiftings:
            if isinstance(shift, dict) and str(shift.get("shifting_id", "")) == str(shifting_id):
                admission = adm
                found = True
                break

        if found:
            break

    if not admission:
        return Response(
            {"success": False, "error": "Shifting record not found"},
            status=status.HTTP_404_NOT_FOUND
        )

    shiftings = admission.roomShitingDetails
    room_details = admission.room_details

    if not isinstance(shiftings, list):
        shiftings = []

    if not isinstance(room_details, list):
        room_details = []

    cancelled_shift = None

    for shift in shiftings:

        if not isinstance(shift, dict):
            continue

        if str(shift.get("shifting_id", "")) == str(shifting_id):

            if shift.get("is_cancelled"):
                return Response(
                    {"success": False, "error": "Already cancelled"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            shift["is_cancelled"] = True
            shift["cancelled_by"] = str(user_id)
            shift["cancelled_at"] = timezone.now().isoformat()

            cancelled_shift = shift
            break

    if not cancelled_shift:
        return Response(
            {"success": False, "error": "Shifting record not found"},
            status=status.HTTP_404_NOT_FOUND
        )

    updated_rooms = []

    for room in room_details:

        if not isinstance(room, dict):
            continue

        room_obj = {
            "roomNo": str(room.get("roomNo", "")),
            "bedNo": str(room.get("bedNo", "")),
            "is_roomActive": bool(room.get("is_roomActive", False)),
            "is_roomCleaned": bool(room.get("is_roomCleaned", False)),
        }

        if (
            room_obj["roomNo"] == str(cancelled_shift.get("newRoomNo", "")) and
            room_obj["bedNo"] == str(cancelled_shift.get("newBedNo", ""))
        ):
            room_obj["is_roomActive"] = False
            room_obj["is_roomCleaned"] = True

        if (
            room_obj["roomNo"] == str(cancelled_shift.get("oldRoomNo", "")) and
            room_obj["bedNo"] == str(cancelled_shift.get("oldBedNo", ""))
        ):
            room_obj["is_roomActive"] = True
            room_obj["is_roomCleaned"] = False

        updated_rooms.append(room_obj)

    admission.room_details = updated_rooms
    admission.roomShitingDetails = shiftings
    admission.lastmodified_by = str(user_id)

    admission.save()

    return Response(
        {
            "success": True,
            "message": "Shifting record cancelled successfully"
        },
        status=status.HTTP_200_OK
    )