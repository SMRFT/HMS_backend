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

# Auth/permissions
from pyauth.auth import HasRoleAndDataPermission

# Logger setup
logger = logging.getLogger(__name__)


# ==================== VENDOR VIEWS ====================
from ..models import Vendor
from ..serializers import VendorSerializer

@api_view(["GET", "POST", "PUT", "DELETE"])
@csrf_exempt
def vendor_view(request, pk=None):

    user_id = request.headers.get("auth-user-id", "system")

    # ── GET ──────────────────────────────────────────────────────────────────
    if request.method == "GET":
        if pk:
            try:
                vendor = Vendor.objects.get(vendor_id=pk)
                if not vendor.is_active:
                    return Response({"error": "Vendor not found"}, status=404)
            except Vendor.DoesNotExist:
                return Response({"error": "Vendor not found"}, status=404)
            except (ValueError, TypeError):
                return Response({"error": "Invalid Vendor ID"}, status=400)

            serializer = VendorSerializer(vendor)
            return Response(serializer.data)

        # List – filter in Python to avoid Djongo boolean filter bug
        all_vendors = Vendor.objects.all().order_by("vendor_id")
        vendors = [v for v in all_vendors if v.is_active]
        serializer = VendorSerializer(vendors, many=True)
        return Response(serializer.data)

    # ── POST ─────────────────────────────────────────────────────────────────
    if request.method == "POST":
        serializer = VendorSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(created_by=user_id, lastmodified_by=user_id)
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)

    # ── PUT ──────────────────────────────────────────────────────────────────
    if request.method == "PUT":
        if not pk:
            return Response({"error": "Vendor ID required"}, status=400)
        try:
            vendor = Vendor.objects.get(vendor_id=pk)
            if not vendor.is_active:
                return Response({"error": "Vendor not found"}, status=404)
        except Vendor.DoesNotExist:
            return Response({"error": "Vendor not found"}, status=404)
        except (ValueError, TypeError):
            return Response({"error": "Invalid Vendor ID"}, status=400)

        serializer = VendorSerializer(vendor, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save(lastmodified_by=user_id)
            return Response(serializer.data)
        return Response(serializer.errors, status=400)

    # ── DELETE ───────────────────────────────────────────────────────────────
    if request.method == "DELETE":
        if not pk:
            return Response({"error": "Vendor ID required"}, status=400)
        try:
            vendor = Vendor.objects.get(vendor_id=pk)
            if not vendor.is_active:
                return Response({"error": "Vendor not found"}, status=404)
        except Vendor.DoesNotExist:
            return Response({"error": "Vendor not found"}, status=404)
        except (ValueError, TypeError):
            return Response({"error": "Invalid Vendor ID"}, status=400)

        vendor.is_active = False
        vendor.lastmodified_by = user_id
        vendor.save()
        return Response({"message": "Deleted successfully"}, status=200)


from ..models import PharmacyItem
from ..serializers import PharmacyItemSerializer

@api_view(["GET", "POST", "PUT", "DELETE"])
@csrf_exempt
def pharmacy_item_view(request, pk=None):

    user_id = request.headers.get("auth-user-id", "system")

    # ── GET ──────────────────────────────────────────────────────────────────
    if request.method == "GET":
        if pk:
            try:
                item = PharmacyItem.objects.get(item_id=pk)
                if not item.is_active:
                    return Response({"error": "Item not found"}, status=404)
            except PharmacyItem.DoesNotExist:
                return Response({"error": "Item not found"}, status=404)
            except (ValueError, TypeError):
                return Response({"error": "Invalid Item ID"}, status=400)

            serializer = PharmacyItemSerializer(item)
            return Response(serializer.data)

        # List – filter in Python to avoid Djongo boolean filter bug
        all_items = PharmacyItem.objects.all().order_by("item_id")
        items = [i for i in all_items if i.is_active]
        serializer = PharmacyItemSerializer(items, many=True)
        return Response(serializer.data)

    # ── POST ─────────────────────────────────────────────────────────────────
    if request.method == "POST":
        serializer = PharmacyItemSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(created_by=user_id, lastmodified_by=user_id)
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)

    # ── PUT ──────────────────────────────────────────────────────────────────
    if request.method == "PUT":
        if not pk:
            return Response({"error": "Item ID required"}, status=400)
        try:
            item = PharmacyItem.objects.get(item_id=pk)
            if not item.is_active:
                return Response({"error": "Item not found"}, status=404)
        except PharmacyItem.DoesNotExist:
            return Response({"error": "Item not found"}, status=404)
        except (ValueError, TypeError):
            return Response({"error": "Invalid Item ID"}, status=400)

        serializer = PharmacyItemSerializer(item, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save(lastmodified_by=user_id)
            return Response(serializer.data)
        return Response(serializer.errors, status=400)

    # ── DELETE ───────────────────────────────────────────────────────────────
    if request.method == "DELETE":
        if not pk:
            return Response({"error": "Item ID required"}, status=400)
        try:
            item = PharmacyItem.objects.get(item_id=pk)
            if not item.is_active:
                return Response({"error": "Item not found"}, status=404)
        except PharmacyItem.DoesNotExist:
            return Response({"error": "Item not found"}, status=404)
        except (ValueError, TypeError):
            return Response({"error": "Invalid Item ID"}, status=400)

        item.is_active = False
        item.lastmodified_by = user_id
        item.save()
        return Response({"message": "Deleted successfully"}, status=200)
    

from ..models import GRN
from ..serializers import GRNSerializer

@api_view(['GET', 'POST', 'PATCH', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def grn_view(request, pk=None):
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client.HMS
        collection = db.hospital_grn

        if request.method == 'POST':
            data = request.data.copy()
            employee_id = request.data.get('auth-user-id', 'system')
            
            # Complex fields as strings if they are objects/arrays
            if isinstance(data.get('items'), (list, dict)):
                data['items'] = json.dumps(data['items'])
            if isinstance(data.get('payment_status'), (list, dict)):
                data['payment_status'] = json.dumps(data['payment_status'])
            
            data["created_by"] = employee_id
            data["lastmodified_by"] = employee_id
            data["is_active"] = True

            serializer = GRNSerializer(data=data)
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data, status=status.HTTP_201_CREATED)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        elif request.method == 'GET':
            if pk:
                try:
                    doc = collection.find_one({"_id": ObjectId(pk), "is_active": True})
                    if not doc:
                        doc = collection.find_one({"grn_number": pk, "is_active": True})
                    
                    if not doc:
                        return Response({"error": "GRN not found"}, status=status.HTTP_404_NOT_FOUND)
                    
                    doc['id'] = str(doc['_id'])
                    del doc['_id']
                    return Response(doc)
                except Exception as e:
                    return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            else:
                grns = list(collection.find({"is_active": True}).sort("created_date", -1))
                for grn in grns:
                    grn['id'] = str(grn['_id'])
                    del grn['_id']
                return Response(grns)

        elif request.method == 'PATCH':
            if not pk:
                return Response({"error": "ID required"}, status=status.HTTP_400_BAD_REQUEST)
            
            try:
                grn = GRN.objects.get(pk=pk)
                data = request.data.copy()
                
                if isinstance(data.get('items'), (list, dict)):
                    data['items'] = json.dumps(data['items'])
                if isinstance(data.get('payment_status'), (list, dict)):
                    data['payment_status'] = json.dumps(data['payment_status'])
                
                data["lastmodified_by"] = request.data.get('auth-user-id', 'system')
                
                serializer = GRNSerializer(grn, data=data, partial=True)
                if serializer.is_valid():
                    serializer.save()
                    return Response(serializer.data)
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            except GRN.DoesNotExist:
                return Response({"error": "GRN not found"}, status=status.HTTP_404_NOT_FOUND)

        elif request.method == 'DELETE':
            if not pk:
                return Response({"error": "ID required"}, status=status.HTTP_400_BAD_REQUEST)
            
            result = collection.update_one({"_id": ObjectId(pk)}, {"$set": {"is_active": False}})
            if result.matched_count == 0:
                result = collection.update_one({"grn_number": pk}, {"$set": {"is_active": False}})
                
            if result.matched_count == 0:
                return Response({"error": "GRN not found"}, status=status.HTTP_404_NOT_FOUND)
            return Response({"message": "GRN deleted successfully"}, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)