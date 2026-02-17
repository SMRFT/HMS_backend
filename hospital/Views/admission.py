
from bson import Decimal128
from rest_framework.response import Response
from rest_framework import status
from pymongo import MongoClient
import os
from datetime import datetime
from rest_framework.decorators import api_view, permission_classes
from pyauth.auth import HasRoleAndDataPermission
from django.http import JsonResponse
from rest_framework.parsers import MultiPartParser, FormParser
from ..models import Admission, Patient, Room
from ..serializers import AdmissionSerializer, PatientSerializer, RoomSerializer


from django.views.decorators.csrf import csrf_exempt


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def get_next_ip_number(request):
    current_year = datetime.now().year
    current_month = datetime.now().month

    # Determine banking year prefix
    if current_month < 4:
        banking_year = current_year - 2001  # Example: Jan-March 2025 -> S024
    else:
        banking_year = current_year - 2000  # Example: April 2025 -> S025

    new_prefix = f"S{banking_year:03d}"

    # Fetch the latest ipNumber from the database
    latest_admission =  Admission.objects.order_by('-ipNumber').first()

    if latest_admission:
        last_ip_number = latest_admission.ipNumber  # e.g., "S024/500100"
        last_prefix, last_number = last_ip_number.split("/")
        last_number = int(last_number)

        # If the prefix has changed, reset numbering to 500001
        if last_prefix != new_prefix:
            next_number = 500001
        else:
            next_number = last_number + 1
    else:
        # If no records exist, start fresh
        next_number = 500001

    next_ip_number = f"{new_prefix}/{next_number:06d}"

    return Response({"next_ipNumber": next_ip_number})


@api_view(['GET'])  
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def get_op_patient_by_uhid(request, uhid):
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client.HMS
        collection = db.hospital_patient
        
        patient = collection.find_one({"uhid": uhid})
        if not patient:
            return Response({"error": "Patient not found"}, status=404)
        
        patient['id'] = str(patient['_id'])
        del patient['_id']
        return Response(patient)
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def search_rooms(request):

    try:
        room_number = request.GET.get('room_number')
        room_category = request.GET.get('room_category')
        block = request.GET.get('block')
        floor = request.GET.get('floor')

        # Start with all rooms
        rooms = Room.objects.all()

        # Filter only active rooms (Djongo-safe)
        rooms = [room for room in rooms if room.is_active]

        # Apply filters safely
        if room_number:
            rooms = [
                room for room in rooms
                if room_number.lower() in room.room_number.lower()
            ]

        if room_category:
            rooms = [
                room for room in rooms
                if room.room_category == room_category
            ]

        if block:
            rooms = [
                room for room in rooms
                if room.block == block
            ]

        if floor not in (None, ""):
            try:
                floor = int(floor)
                rooms = [
                    room for room in rooms
                    if room.floor == floor
                ]
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

        return Response(
            {"error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def admission_view(request):
    """
    Handle GET (list active admissions) and POST (create admission)
    """
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client.HMS
        collection = db.hospital_admission
        
        if request.method == 'GET':
            # List only active admissions by default
            admissions = list(collection.find({"is_active": True}))
            
            # Convert ObjectId to string
            for admission in admissions:
                admission['id'] = str(admission['_id'])
                del admission['_id']
            
            return JsonResponse(admissions, safe=False)
        
        elif request.method == 'POST':
            # Create new admission
            data = request.data.copy()
            employee_id = request.headers.get('auth-user-id', 'system')
            
            data['created_by'] = employee_id
            data['lastmodified_by'] = employee_id
            data['is_active'] = True
            data['created_date'] = datetime.now()
            data['lastmodified_date'] = datetime.now()
            
            result = collection.insert_one(data)
            data['id'] = str(result.inserted_id)
            if '_id' in data:
                del data['_id']
            
            return JsonResponse({'message': 'Admission created successfully!', 'data': data}, status=201)
            
    except Exception as e:
        import traceback
        print("Error in admission_view:", e)
        print(traceback.format_exc())
        return JsonResponse({'error': str(e)}, status=500)


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def admission_detail(request, uhid):
    """
    Handle GET, PUT (update) and DELETE (cancel - soft delete) for specific admission
    Using UHID for lookup assuming one active admission per patient or passing ID
    """
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client.HMS
        collection = db.hospital_admission
        
        # Try to match by ID if 'uhid' param is actually an ID, or find by uhid
        try:
            admission = collection.find_one({"_id": ObjectId(uhid)})
        except:
            admission = None
        
        # Or if passed uhid, get the active one?
        if not admission:
            admission = collection.find_one({"uhid": uhid, "is_active": True})
        
        if not admission:
            return JsonResponse({'error': 'Admission not found'}, status=404)
        
        admission['id'] = str(admission['_id'])
        del admission['_id']

        if request.method == 'GET':
            return JsonResponse(admission)

        elif request.method == 'PUT':
            update_data = request.data.copy()
            employee_id = request.headers.get('auth-user-id', 'system')
            update_data['lastmodified_by'] = employee_id
            update_data['lastmodified_date'] = datetime.now()
            
            result = collection.update_one(
                {"_id": admission['_id']},
                {"$set": update_data}
            )
            
            if result.matched_count == 0:
                return JsonResponse({'error': 'Failed to update admission'}, status=400)
            
            return JsonResponse({'message': 'Admission updated successfully!'}, status=200)

        elif request.method == 'DELETE':
            # Soft delete (Cancel admission)
            result = collection.update_one(
                {"_id": admission['_id']},
                {"$set": {"is_active": False}}
            )
            
            if result.matched_count == 0:
                return JsonResponse({'error': 'Failed to cancel admission'}, status=400)
            
            return JsonResponse({'message': 'Admission cancelled successfully'}, status=200)
            
    except Exception as e:
        import traceback
        print("Error in admission_detail:", e)
        print(traceback.format_exc())
        return JsonResponse({'error': str(e)}, status=500)