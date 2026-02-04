from rest_framework.response import Response
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from pyauth.auth import HasRoleAndDataPermission
from django.views.decorators.csrf import csrf_exempt
from pymongo import MongoClient
from bson import ObjectId
import os

from ..models import Block, RoomCategory, Room, Bed, Service, Admission
from ..serializers import (
    BlockSerializer,
    RoomCategorySerializer,
    RoomSerializer,
    BedSerializer,
    ServiceSerializer
)

# MongoDB connection
def get_mongo_db():
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    return client.HMS

# --------------------------------------------------
# BLOCK
# --------------------------------------------------
@api_view(['GET', 'POST', 'PUT', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def block_view(request, pk=None):
    try:
        db = get_mongo_db()
        collection = db.hospital_block

        if request.method == 'GET':
            if pk:
                # Try to find by ObjectId first, then by block_id
                try:
                    doc = collection.find_one({"_id": ObjectId(pk), "is_active": True})
                except:
                    doc = collection.find_one({"block_id": pk, "is_active": True})
                
                if not doc:
                    return Response({"error": "Block not found"}, status=404)
                
                # Convert MongoDB document to serializable format
                doc['id'] = str(doc['_id'])
                del doc['_id']
                return Response(doc)

            # Get all active blocks
            blocks = list(collection.find({"is_active": True}))
            for block in blocks:
                block['id'] = str(block['_id'])
                del block['_id']
            
            return Response(blocks)

        elif request.method == 'POST':
            data = request.data.copy()
            employee_id = request.headers.get('auth-user-id', 'system')
            
            # Generate block_id if not provided
            if not data.get('block_id'):
                last_block = collection.find_one(sort=[("block_id", -1)])
                if last_block and last_block.get('block_id'):
                    try:
                        last_number = int(last_block['block_id'].replace("B", ""))
                        data['block_id'] = f"B{last_number + 1}"
                    except:
                        data['block_id'] = "B1"
                else:
                    data['block_id'] = "B1"
            
            data['created_by'] = employee_id
            data['lastmodified_by'] = employee_id
            data['is_active'] = True
            
            result = collection.insert_one(data)
            data['id'] = str(result.inserted_id)
            if '_id' in data:
                del data['_id']
            
            return Response(data, status=201)

        elif request.method == 'PUT':
            if not pk:
                return Response({"error": "ID required"}, status=400)
            
            employee_id = request.headers.get('auth-user-id', 'system')
            update_data = request.data.copy()
            update_data['lastmodified_by'] = employee_id
            
            # Try to update by ObjectId first, then by block_id
            try:
                result = collection.update_one(
                    {"_id": ObjectId(pk), "is_active": True},
                    {"$set": update_data}
                )
            except:
                result = collection.update_one(
                    {"block_id": pk, "is_active": True},
                    {"$set": update_data}
                )
            
            if result.matched_count == 0:
                return Response({"error": "Block not found"}, status=404)
            
            # Fetch and return updated document
            try:
                doc = collection.find_one({"_id": ObjectId(pk)})
            except:
                doc = collection.find_one({"block_id": pk})
            
            if doc:
                doc['id'] = str(doc['_id'])
                del doc['_id']
            
            return Response(doc)

        elif request.method == 'DELETE':
            if not pk:
                return Response({"error": "ID required"}, status=400)
            
            # Try to delete by ObjectId first, then by block_id
            try:
                result = collection.update_one(
                    {"_id": ObjectId(pk)},
                    {"$set": {"is_active": False}}
                )
            except:
                result = collection.update_one(
                    {"block_id": pk},
                    {"$set": {"is_active": False}}
                )
            
            if result.matched_count == 0:
                return Response({"error": "Block not found"}, status=404)
            
            return Response({"message": "Deleted successfully"})

    except Exception as e:
        import traceback
        return Response({
            "error": "Database error occurred",
            "message": str(e),
            "traceback": traceback.format_exc()
        }, status=500)
    

# --------------------------------------------------
# ROOM CATEGORY
# --------------------------------------------------
@api_view(['GET', 'POST', 'PUT', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def room_category_view(request, pk=None):
    try:
        db = get_mongo_db()
        collection = db.hospital_roomcategory

        if request.method == 'GET':
            if pk:
                try:
                    doc = collection.find_one({"_id": ObjectId(pk), "is_active": True})
                except:
                    doc = collection.find_one({"ward_name": pk, "is_active": True})
                
                if not doc:
                    return Response({"error": "Room category not found"}, status=404)
                
                doc['id'] = str(doc['_id'])
                del doc['_id']
                return Response(doc)

            categories = list(collection.find({"is_active": True}))
            for cat in categories:
                cat['id'] = str(cat['_id'])
                del cat['_id']
            
            return Response(categories)

        elif request.method == 'POST':
            data = request.data.copy()
            employee_id = request.headers.get('auth-user-id', 'system')
            
            data['created_by'] = employee_id
            data['lastmodified_by'] = employee_id
            data['is_active'] = True
            
            result = collection.insert_one(data)
            data['id'] = str(result.inserted_id)
            if '_id' in data:
                del data['_id']
            
            return Response(data, status=201)

        elif request.method == 'PUT':
            if not pk:
                return Response({"error": "ID required"}, status=400)
            
            employee_id = request.headers.get('auth-user-id', 'system')
            update_data = request.data.copy()
            update_data['lastmodified_by'] = employee_id
            
            try:
                result = collection.update_one(
                    {"_id": ObjectId(pk), "is_active": True},
                    {"$set": update_data}
                )
            except:
                result = collection.update_one(
                    {"ward_name": pk, "is_active": True},
                    {"$set": update_data}
                )
            
            if result.matched_count == 0:
                return Response({"error": "Room category not found"}, status=404)
            
            try:
                doc = collection.find_one({"_id": ObjectId(pk)})
            except:
                doc = collection.find_one({"ward_name": pk})
            
            if doc:
                doc['id'] = str(doc['_id'])
                del doc['_id']
            
            return Response(doc)

        elif request.method == 'DELETE':
            if not pk:
                return Response({"error": "ID required"}, status=400)
            
            try:
                result = collection.update_one(
                    {"_id": ObjectId(pk)},
                    {"$set": {"is_active": False}}
                )
            except:
                result = collection.update_one(
                    {"ward_name": pk},
                    {"$set": {"is_active": False}}
                )
            
            if result.matched_count == 0:
                return Response({"error": "Room category not found"}, status=404)
            
            return Response({"message": "Deleted successfully"})

    except Exception as e:
        import traceback
        return Response({
            "error": "Database error occurred",
            "message": str(e),
            "traceback": traceback.format_exc()
        }, status=500)


# --------------------------------------------------
# ROOM
# --------------------------------------------------
@api_view(['GET', 'POST', 'PUT', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def room_view(request, pk=None):
    try:
        db = get_mongo_db()
        collection = db.hospital_room

        if request.method == 'GET':
            if pk:
                try:
                    doc = collection.find_one({"_id": ObjectId(pk), "is_active": True})
                except:
                    doc = collection.find_one({"room_number": pk, "is_active": True})
                
                if not doc:
                    return Response({"error": "Room not found"}, status=404)
                
                doc['id'] = str(doc['_id'])
                del doc['_id']
                return Response(doc)

            rooms = list(collection.find({"is_active": True}))
            for room in rooms:
                room['id'] = str(room['_id'])
                del room['_id']
            
            return Response(rooms)

        elif request.method == 'POST':
            data = request.data.copy()
            employee_id = request.headers.get('auth-user-id', 'system')
            
            data['created_by'] = employee_id
            data['lastmodified_by'] = employee_id
            data['is_active'] = True
            
            result = collection.insert_one(data)
            data['id'] = str(result.inserted_id)
            if '_id' in data:
                del data['_id']
            
            return Response(data, status=201)

        elif request.method == 'PUT':
            if not pk:
                return Response({"error": "ID required"}, status=400)
            
            employee_id = request.headers.get('auth-user-id', 'system')
            update_data = request.data.copy()
            update_data['lastmodified_by'] = employee_id
            
            try:
                result = collection.update_one(
                    {"_id": ObjectId(pk), "is_active": True},
                    {"$set": update_data}
                )
            except:
                result = collection.update_one(
                    {"room_number": pk, "is_active": True},
                    {"$set": update_data}
                )
            
            if result.matched_count == 0:
                return Response({"error": "Room not found"}, status=404)
            
            try:
                doc = collection.find_one({"_id": ObjectId(pk)})
            except:
                doc = collection.find_one({"room_number": pk})
            
            if doc:
                doc['id'] = str(doc['_id'])
                del doc['_id']
            
            return Response(doc)

        elif request.method == 'DELETE':
            if not pk:
                return Response({"error": "ID required"}, status=400)
            
            try:
                result = collection.update_one(
                    {"_id": ObjectId(pk)},
                    {"$set": {"is_active": False}}
                )
            except:
                result = collection.update_one(
                    {"room_number": pk},
                    {"$set": {"is_active": False}}
                )
            
            if result.matched_count == 0:
                return Response({"error": "Room not found"}, status=404)
            
            return Response({"message": "Deleted successfully"})

    except Exception as e:
        import traceback
        return Response({
            "error": "Database error occurred",
            "message": str(e),
            "traceback": traceback.format_exc()
        }, status=500)


# --------------------------------------------------
# BED
# --------------------------------------------------
@api_view(['GET', 'POST', 'PUT', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def bed_view(request, pk=None):
    try:
        db = get_mongo_db()
        collection = db.hospital_bed

        if request.method == 'GET':
            if pk:
                try:
                    doc = collection.find_one({"_id": ObjectId(pk), "is_active": True})
                except:
                    doc = collection.find_one({"bed_number": pk, "is_active": True})
                
                if not doc:
                    return Response({"error": "Bed not found"}, status=404)
                
                doc['id'] = str(doc['_id'])
                del doc['_id']
                # Handle room ForeignKey reference
                if doc.get('room_id'):
                    doc['room'] = str(doc['room_id'])
                
                return Response(doc)

            beds = list(collection.find({"is_active": True}))
            for bed in beds:
                bed['id'] = str(bed['_id'])
                del bed['_id']
                if bed.get('room_id'):
                   bed['room'] = str(bed['room_id'])
            
            return Response(beds)

        elif request.method == 'POST':
            data = request.data.copy()
            employee_id = request.headers.get('auth-user-id', 'system')
            
            data['created_by'] = employee_id
            data['lastmodified_by'] = employee_id
            data['is_active'] = True
            
            result = collection.insert_one(data)
            data['id'] = str(result.inserted_id)
            if '_id' in data:
                del data['_id']
            
            return Response(data, status=201)

        elif request.method == 'PUT':
            if not pk:
                return Response({"error": "ID required"}, status=400)
            
            employee_id = request.headers.get('auth-user-id', 'system')
            update_data = request.data.copy()
            update_data['lastmodified_by'] = employee_id
            
            try:
                result = collection.update_one(
                    {"_id": ObjectId(pk), "is_active": True},
                    {"$set": update_data}
                )
            except:
                result = collection.update_one(
                    {"bed_number": pk, "is_active": True},
                    {"$set": update_data}
                )
            
            if result.matched_count == 0:
                return Response({"error": "Bed not found"}, status=404)
            
            try:
                doc = collection.find_one({"_id": ObjectId(pk)})
            except:
                doc = collection.find_one({"bed_number": pk})
            
            if doc:
                doc['id'] = str(doc['_id'])
                del doc['_id']
            
            return Response(doc)

        elif request.method == 'DELETE':
            if not pk:
                return Response({"error": "ID required"}, status=400)
            
            try:
                result = collection.update_one(
                    {"_id": ObjectId(pk)},
                    {"$set": {"is_active": False}}
                )
            except:
                result = collection.update_one(
                    {"bed_number": pk},
                    {"$set": {"is_active": False}}
                )
            
            if result.matched_count == 0:
                return Response({"error": "Bed not found"}, status=404)
            
            return Response({"message": "Deleted successfully"})

    except Exception as e:
        import traceback
        return Response({
            "error": "Database error occurred",
            "message": str(e),
            "traceback": traceback.format_exc()
        }, status=500)


# --------------------------------------------------
# SERVICE
# --------------------------------------------------
@api_view(['GET', 'POST', 'PUT', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def service_view(request, pk=None):
    try:
        db = get_mongo_db()
        collection = db.hospital_service

        if request.method == 'GET':
            if pk:
                try:
                    doc = collection.find_one({"_id": ObjectId(pk), "is_active": True})
                except:
                    doc = collection.find_one({"service_code": pk, "is_active": True})
                
                if not doc:
                    return Response({"error": "Service not found"}, status=404)
                
                doc['id'] = str(doc['_id'])
                del doc['_id']
                return Response(doc)

            services = list(collection.find({"is_active": True}))
            for service in services:
                service['id'] = str(service['_id'])
                del service['_id']
            
            return Response(services)

        elif request.method == 'POST':
            data = request.data.copy()
            employee_id = request.headers.get('auth-user-id', 'system')
            
            data['created_by'] = employee_id
            data['lastmodified_by'] = employee_id
            data['is_active'] = True
            
            result = collection.insert_one(data)
            data['id'] = str(result.inserted_id)
            if '_id' in data:
                del data['_id']
            
            return Response(data, status=201)

        elif request.method == 'PUT':
            if not pk:
                return Response({"error": "ID required"}, status=400)
            
            employee_id = request.headers.get('auth-user-id', 'system')
            update_data = request.data.copy()
            update_data['lastmodified_by'] = employee_id
            
            try:
                result = collection.update_one(
                    {"_id": ObjectId(pk), "is_active": True},
                    {"$set": update_data}
                )
            except:
                result = collection.update_one(
                    {"service_code": pk, "is_active": True},
                    {"$set": update_data}
                )
            
            if result.matched_count == 0:
                return Response({"error": "Service not found"}, status=404)
            
            try:
                doc = collection.find_one({"_id": ObjectId(pk)})
            except:
                doc = collection.find_one({"service_code": pk})
            
            if doc:
                doc['id'] = str(doc['_id'])
                del doc['_id']
            
            return Response(doc)

        elif request.method == 'DELETE':
            if not pk:
                return Response({"error": "ID required"}, status=400)
            
            try:
                result = collection.update_one(
                    {"_id": ObjectId(pk)},
                    {"$set": {"is_active": False}}
                )
            except:
                result = collection.update_one(
                    {"service_code": pk},
                    {"$set": {"is_active": False}}
                )
            
            if result.matched_count == 0:
                return Response({"error": "Service not found"}, status=404)
            
            return Response({"message": "Deleted successfully"})

    except Exception as e:
        import traceback
        return Response({
            "error": "Database error occurred",
            "message": str(e),
            "traceback": traceback.format_exc()
        }, status=500)


# --------------------------------------------------
# ROOM ENQUIRY (Block → Floor → Room → Bed)
# --------------------------------------------------
@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def room_enquiry_view(request):
    try:
        db = get_mongo_db()
        blocks_collection = db.hospital_block
        rooms_collection = db.hospital_room
        beds_collection = db.hospital_bed

        blocks = list(blocks_collection.find({"is_active": True}))
        result = []

        for block in blocks:
            block['id'] = str(block['_id'])
            del block['_id']
            rooms = list(rooms_collection.find({
                "block": block.get('block_name'),
                "is_active": True
            }))
            floor_map = {}

            for room in rooms:
                room['id'] = str(room['_id'])
                del room['_id']
                floor = room.get('floor', 0)
                floor_map.setdefault(floor, [])

                # Find beds for this room by room ObjectId
                beds = list(beds_collection.find({
                    "room_id": room['_id'],
                    "is_active": True
                }))
                
                for bed in beds:
                    bed['id'] = str(bed['_id'])
                    del bed['_id']
                    if bed.get('room_id'):
                        bed['room'] = str(bed['room_id'])
                
                room['beds'] = beds
                floor_map[floor].append(room)

            result.append({
                "block": block,
                "floors": floor_map
            })

        return Response(result)
    except Exception as e:
        import traceback
        return Response({
            "error": "Database error occurred",
            "message": str(e),
            "traceback": traceback.format_exc()
        }, status=500)


# --------------------------------------------------
# ROOM SHIFTING
# --------------------------------------------------
@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def room_shifting_view(request):
    try:
        db = get_mongo_db()
        collection = db.hospital_admission

        # ==================== GET ====================
        # Fetch current room & bed details for an active admission
        if request.method == 'GET':
            uhid = request.GET.get("uhid")

            if not uhid:
                return Response(
                    {"error": "UHID is required"},
                    status=400
                )

            admission = collection.find_one({
                "uhid": uhid,
                "is_active": True
            })

            if not admission:
                return Response(
                    {"error": "Active admission not found"},
                    status=404
                )

            return Response({
                "uhid": admission.get('uhid'),
                "ip_no": admission.get('ipNumber'),
                "room_no": admission.get('roomNo'),
                "bed_no": admission.get('bedNo'),
            }, status=200)

        # ==================== POST ====================
        # Shift room & bed
        uhid = request.data.get("uhid")
        new_room_no = request.data.get("newRoomNo")
        new_bed_no = request.data.get("newBedNo")

        if not all([uhid, new_room_no, new_bed_no]):
            return Response(
                {"error": "Missing required fields"},
                status=400
            )

        result = collection.update_one(
            {"uhid": uhid, "is_active": True},
            {
                "$set": {
                    "roomNo": new_room_no,
                    "bedNo": new_bed_no
                }
            }
        )

        if result.matched_count == 0:
            return Response(
                {"error": "Active admission not found"},
                status=404
            )

        return Response(
            {"message": "Room shifted successfully"},
            status=200
        )
        
    except Exception as e:
        import traceback
        return Response({
            "error": "Database error occurred",
            "message": str(e),
            "traceback": traceback.format_exc()
        }, status=500)

