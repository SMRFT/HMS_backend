from bson import Decimal128, ObjectId
from rest_framework.response import Response
from rest_framework import status
from pymongo import MongoClient
import os
from datetime import datetime
from rest_framework.decorators import api_view, permission_classes
from pyauth.auth import HasRoleAndDataPermission
from django.http import JsonResponse
from ..models import Admission, Room
from ..serializers import RoomSerializer
from django.views.decorators.csrf import csrf_exempt


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _get_db():
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    return client.HMS


def _serialize_doc(doc):
    """Convert a MongoDB document to a JSON-serializable dict."""
    doc = dict(doc)
    doc['id'] = str(doc['_id'])
    del doc['_id']
    for k, v in doc.items():
        if isinstance(v, datetime):
            doc[k] = v.isoformat()
        elif isinstance(v, Decimal128):
            doc[k] = float(str(v))
    return doc


# ─── IP Number (auto-generated) ───────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def get_next_ip_number(request):
    current_year = datetime.now().year
    current_month = datetime.now().month

    if current_month < 4:
        banking_year = current_year - 2001   # Jan-Mar → previous FY
    else:
        banking_year = current_year - 2000   # Apr-Dec → current FY

    new_prefix = f"S{banking_year:03d}"

    latest_admission = Admission.objects.order_by('-ipNumber').first()

    if latest_admission:
        last_ip_number = latest_admission.ipNumber
        try:
            last_prefix, last_number = last_ip_number.split("/")
            last_number = int(last_number)
            next_number = 500001 if last_prefix != new_prefix else last_number + 1
        except (ValueError, AttributeError):
            next_number = 500001
    else:
        next_number = 500001

    return Response({"next_ipNumber": f"{new_prefix}/{next_number:06d}"})


# ─── OP Patient (by UHID) ─────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def get_op_patient_by_uhid(request, uhid):
    """
    Returns: salutation, firstName, middleName, lastName, customerType,
             insuranceCompany, privilegedCustomerId, age, gender, phone,
             permanent_address, area, zipcode, city, state
    """
    try:
        db = _get_db()
        patient = db.hospital_patient.find_one({"uhid": uhid})
        if not patient:
            return Response({"error": "Patient not found"}, status=404)
        return Response(_serialize_doc(patient))
    except Exception as e:
        return Response({"error": str(e)}, status=500)


# ─── OP Patient Search (partial UHID, min 4 chars) ────────────────────────────

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def search_op_patients(request):
    """
    GET /op-patient-search/?uhid=1234
    Returns patients whose UHID contains the given string (min 4 chars).
    """
    try:
        uhid_query = request.GET.get('uhid', '').strip()
        if len(uhid_query) < 4:
            return Response(
                {"error": "Please enter at least 4 characters"},
                status=status.HTTP_400_BAD_REQUEST
            )
        db = _get_db()
        patients = list(
            db.hospital_patient.find(
                {"uhid": {"$regex": uhid_query, "$options": "i"}},
                limit=20
            )
        )
        return Response([_serialize_doc(p) for p in patients])
    except Exception as e:
        return Response({"error": str(e)}, status=500)


# ─── Rooms ────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def search_rooms(request):
    """
    GET /search-rooms/?room_number=&room_category=&block=&floor=
    Only returns rooms where is_active=True.
    """
    try:
        room_number = request.GET.get('room_number')
        room_category = request.GET.get('room_category')
        block = request.GET.get('block')
        floor = request.GET.get('floor')

        rooms = [room for room in Room.objects.all() if room.is_active]

        if room_number:
            rooms = [r for r in rooms if room_number.lower() in r.room_number.lower()]
        if room_category:
            rooms = [r for r in rooms if r.room_category == room_category]
        if block:
            rooms = [r for r in rooms if r.block == block]
        if floor not in (None, ""):
            try:
                floor = int(floor)
                rooms = [r for r in rooms if r.floor == floor]
            except ValueError:
                return Response(
                    {"error": "Floor must be a number"},
                    status=status.HTTP_400_BAD_REQUEST
                )

        serializer = RoomSerializer(rooms, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    except Exception as e:
        import traceback
        print("Error in search_rooms:", e)
        print(traceback.format_exc())
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ─── Room Beds (by room_number) ───────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def get_room_beds(request, room_number):
    """
    GET /room-beds/<room_number>/
    Returns the list of beds for the given active room.
    """
    try:
        room = Room.objects.filter(room_number=room_number, is_active=True).first()
        if not room:
            return Response({"error": "Room not found or inactive"}, status=404)
        serializer = RoomSerializer(room)
        return Response(serializer.data)
    except Exception as e:
        return Response({"error": str(e)}, status=500)


# ─── Admissions List / Create ─────────────────────────────────────────────────

@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def admission_view(request):
    """
    GET  /admission/         – list active admissions (optionally filter by ip_number)
    POST /admission/         – create new admission (ipNumber auto-generated)
    """
    try:
        db = _get_db()
        collection = db.hospital_admission

        if request.method == 'GET':
            query = {"is_active": True}

            ip_filter = request.GET.get('ip_number', '').strip()
            if ip_filter:
                # Support both partial search (min 4 chars) and exact match (e.g. S025/500001)
                if '/' in ip_filter:
                    # Exact or near-exact IP Number lookup from Admission model
                    query["ipNumber"] = {"$regex": f"^{ip_filter}", "$options": "i"}
                elif len(ip_filter) < 4:
                    return JsonResponse(
                        {"error": "ip_number filter must be at least 4 characters"},
                        status=400
                    )
                else:
                    query["ipNumber"] = {"$regex": ip_filter, "$options": "i"}

            admissions = [_serialize_doc(a) for a in collection.find(query)]
            return JsonResponse(admissions, safe=False)

        elif request.method == 'POST':
            data = dict(request.data)
            data = {k: v[0] if isinstance(v, list) and len(v) == 1 else v for k, v in data.items()}

            # ── Auto-generate IP Number ──────────────────────────────────────
            current_year = datetime.now().year
            current_month = datetime.now().month
            banking_year = (current_year - 2001) if current_month < 4 else (current_year - 2000)
            new_prefix = f"S{banking_year:03d}"

            latest_admission = Admission.objects.order_by('-ipNumber').first()
            if latest_admission:
                try:
                    last_prefix, last_number = latest_admission.ipNumber.split("/")
                    last_number = int(last_number)
                    next_number = 500001 if last_prefix != new_prefix else last_number + 1
                except (ValueError, AttributeError):
                    next_number = 500001
            else:
                next_number = 500001

            data['ipNumber'] = f"{new_prefix}/{next_number:06d}"

            # ── Strip fields not in model ────────────────────────────────────
            allowed_fields = {
                'uhid', 'ipNumber', 'admissionDate', 'time',
                'salutation', 'firstName', 'middleName', 'lastName',
                'customerType', 'insuranceCompany', 'privilegedCustomerId',
                'admittingDoctor', 'consultingDoctor',
                'roomNo', 'bedNo',
                'reasonForAdmission', 'packageName',
                'mlc_type', 'mlc_doc', 'mlc_remarks',
                'roomShitingDetails', 'advance', 'ip_advance', 'creditLimit',
                'is_advanceActive', 'is_admissionActive', 'is_roomCleaned', 'is_roomActive',
            }
            data = {k: v for k, v in data.items() if k in allowed_fields}

            # ── Boolean defaults ─────────────────────────────────────────────
            for bool_field in ('is_advanceActive', 'is_admissionActive', 'is_roomCleaned', 'is_roomActive'):
                data.setdefault(bool_field, False)

            # ── Null defaults ────────────────────────────────────────────────
            for null_field in ('roomShitingDetails', 'advance', 'ip_advance', 'creditLimit'):
                data.setdefault(null_field, None)

            employee_id = request.headers.get('auth-user-id', 'system')
            data.update({
                'created_by': employee_id,
                'lastmodified_by': employee_id,
                'is_active': True,
                'created_date': datetime.now(),
                'lastmodified_date': datetime.now(),
            })

            result = collection.insert_one(data)
            data['id'] = str(result.inserted_id)
            data.pop('_id', None)
            for k, v in data.items():
                if isinstance(v, datetime):
                    data[k] = v.isoformat()

            return JsonResponse(
                {'message': 'Admission created successfully!', 'data': data},
                status=201
            )

    except Exception as e:
        import traceback
        print("Error in admission_view:", e)
        print(traceback.format_exc())
        return JsonResponse({'error': str(e)}, status=500)


# ─── Admission Detail: Get / Update / Cancel ──────────────────────────────────

@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def admission_detail(request, admission_id):
    """
    GET    /admission/<id>/   – fetch one admission
    PUT    /admission/<id>/   – update admission
    DELETE /admission/<id>/   – soft-delete / cancel (sets is_active=False)
    """
    try:
        db = _get_db()
        collection = db.hospital_admission

        admission = None
        try:
            admission = collection.find_one({"_id": ObjectId(admission_id)})
        except Exception:
            pass

        if not admission:
            admission = collection.find_one({"uhid": admission_id, "is_active": True})

        if not admission:
            return JsonResponse({'error': 'Admission not found'}, status=404)

        object_id = admission['_id']
        admission = _serialize_doc(admission)

        if request.method == 'GET':
            return JsonResponse(admission)

        elif request.method == 'PUT':
            update_data = dict(request.data)
            update_data = {
                k: v[0] if isinstance(v, list) and len(v) == 1 else v
                for k, v in update_data.items()
            }

            # Strip fields not in model
            allowed_fields = {
                'admissionDate', 'time',
                'salutation', 'firstName', 'middleName', 'lastName',
                'customerType', 'insuranceCompany', 'privilegedCustomerId',
                'admittingDoctor', 'consultingDoctor',
                'roomNo', 'bedNo',
                'reasonForAdmission', 'packageName',
                'mlc_type', 'mlc_doc', 'mlc_remarks',
            }
            update_data = {k: v for k, v in update_data.items() if k in allowed_fields}

            employee_id = request.headers.get('auth-user-id', 'system')
            update_data['lastmodified_by'] = employee_id
            update_data['lastmodified_date'] = datetime.now()

            result = collection.update_one(
                {"_id": object_id},
                {"$set": update_data}
            )

            if result.matched_count == 0:
                return JsonResponse({'error': 'Failed to update admission'}, status=400)

            return JsonResponse({'message': 'Admission updated successfully!'}, status=200)

        elif request.method == 'DELETE':
            employee_id = request.headers.get('auth-user-id', 'system')

            cancel_data = {}
            try:
                cancel_data = dict(request.data)
                cancel_data = {
                    k: v[0] if isinstance(v, list) and len(v) == 1 else v
                    for k, v in cancel_data.items()
                }
            except Exception:
                pass

            result = collection.update_one(
                {"_id": object_id},
                {"$set": {
                    "is_active": False,
                    "cancelled_by": employee_id,
                    "cancelled_date": datetime.now(),
                    "cancellation_reason": cancel_data.get('cancellationReason', ''),
                }}
            )

            if result.matched_count == 0:
                return JsonResponse({'error': 'Failed to cancel admission'}, status=400)

            return JsonResponse({'message': 'Admission cancelled successfully'}, status=200)

    except Exception as e:
        import traceback
        print("Error in admission_detail:", e)
        print(traceback.format_exc())
        return JsonResponse({'error': str(e)}, status=500)