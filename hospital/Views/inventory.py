from django.shortcuts import render
from rest_framework.response import Response
from django.http import JsonResponse
from rest_framework import status
from pymongo import MongoClient
from django.utils.timezone import now
from rest_framework.parsers import MultiPartParser, FormParser
from bson import Decimal128, ObjectId
from datetime import datetime
import traceback
import logging
import json
import os
from rest_framework.decorators import api_view, permission_classes
from django.views.decorators.csrf import csrf_exempt

from ..models import Vendor
from ..serializers import VendorSerializer

# Auth/permissions
from pyauth.auth import HasRoleAndDataPermission

# Logger setup
logger = logging.getLogger(__name__)

# Removed Item views


def get_next_vendor_id(collection):
    last_vendor = collection.aggregate([
        {
            "$match": {
                "vendor_id": {"$exists": True, "$ne": None}
            }
        },
        {
            "$addFields": {
                "vendor_id_int": {"$toInt": "$vendor_id"}
            }
        },
        {
            "$sort": {"vendor_id_int": -1}
        },
        {
            "$limit": 1
        }
    ])

    last_vendor = list(last_vendor)

    if not last_vendor:
        return "1"

    return str(last_vendor[0]["vendor_id_int"] + 1)



# ==================== VENDOR VIEWS ====================
@api_view(['GET', 'POST', 'PATCH', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def vendor_view(request, vendor_id=None):
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client.HMS
        collection = db.hospital_vendor
        collection.update_many({"is_active": {"$exists": False}}, {"$set": {"is_active": True}})

        if request.method == 'POST':
            employee_id = request.data.get('auth-user-id', 'system')

            next_vendor_id = get_next_vendor_id(collection)

            data = request.data.copy()
            data["vendor_id"] = next_vendor_id
            data["created_by"] = employee_id
            data["created_date"] = datetime.now()
            data["lastmodified_by"] = employee_id
            data["lastmodified_date"] = datetime.now()
            data["is_active"] = True

            serializer = VendorSerializer(data=data)
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data, status=status.HTTP_201_CREATED)

            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


        elif request.method == 'GET':
            if vendor_id:
                try:
                    doc = collection.find_one({"_id": ObjectId(vendor_id), "is_active": True})
                    if not doc:
                        doc = collection.find_one({"vendor_id": vendor_id, "is_active": True})
                    
                    if not doc:
                        return Response({"error": "Vendor not found"}, status=status.HTTP_404_NOT_FOUND)
                    
                    doc['id'] = str(doc['_id'])
                    del doc['_id']
                    return Response(doc)
                except Exception as e:
                    return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            else:
                vendors = list(collection.find({"is_active": True}))
                for vendor in vendors:
                    vendor['id'] = str(vendor['_id'])
                    del vendor['_id']
                return Response(vendors)

        elif request.method == 'PATCH':
            if not vendor_id:
                return Response({"error": "vendor_id required"}, status=status.HTTP_400_BAD_REQUEST)
            employee_id = request.data.get('auth-user-id')
            update_data = request.data.copy()
            update_data["lastmodified_by"] = employee_id
            update_data["lastmodified_date"] = datetime.now()
            result = collection.update_one({"_id": ObjectId(vendor_id)}, {"$set": update_data})
            if result.matched_count == 0:
                return Response({"error": "Vendor not found"}, status=status.HTTP_404_NOT_FOUND)
            updated = collection.find_one({"_id": ObjectId(vendor_id)})
            updated["id"] = str(updated["_id"])
            del updated["_id"]
            return Response(updated)

        elif request.method == 'DELETE':
            if not vendor_id:
                return Response({"error": "vendor_id required"}, status=status.HTTP_400_BAD_REQUEST)
            result = collection.update_one({"_id": ObjectId(vendor_id)}, {"$set": {"is_active": False}})
            if result.matched_count == 0:
                return Response({"error": "Vendor not found"}, status=status.HTTP_404_NOT_FOUND)
            return Response({"message": "Vendor deleted successfully"}, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error in vendor_view: {e}")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)