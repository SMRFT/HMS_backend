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


#VENDOR VIEWS
from ..models import Vendor
from ..serializers import VendorSerializer

@api_view(["GET", "POST", "PUT", "DELETE"])
@csrf_exempt
def vendor_view(request, pk=None):

    user_id = request.headers.get("auth-user-id", "system")

    # ── GET ──
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

    # ── POST ──
    if request.method == "POST":
        serializer = VendorSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(created_by=user_id, lastmodified_by=user_id)
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)

    # ── PUT ──
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

    # ── DELETE ──
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


#PHARMACY CATEGORY VIEWS
from ..models import PharmacyCategory
from ..serializers import PharmacyCategorySerializer

@api_view(["GET", "POST", "PUT", "DELETE"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def pharmacycategory_view(request, pk=None):

    user_id = request.headers.get("auth-user-id", "system")

    # ── GET ──────────────────────────────────────────────────────────────────
    if request.method == "GET":
        if pk:
            try:
                category = PharmacyCategory.objects.get(category_id=pk)
                if not category.is_active:
                    return Response({"error": "Category not found"}, status=404)
            except PharmacyCategory.DoesNotExist:
                return Response({"error": "Category not found"}, status=404)
            except (ValueError, TypeError):
                return Response({"error": "Invalid Category ID"}, status=400)

            serializer = PharmacyCategorySerializer(category)
            return Response(serializer.data)

        # List – filter in Python to avoid Djongo boolean filter bug
        all_Category = PharmacyCategory.objects.all().order_by("category_id")
        Categories = [b for b in all_Category if b.is_active]
        serializer = PharmacyCategorySerializer(Categories, many=True)
        return Response(serializer.data)

    # ── POST ─────────────────────────────────────────────────────────────────
    if request.method == "POST":
        serializer = PharmacyCategorySerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(created_by=user_id, lastmodified_by=user_id)
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)

    # ── PUT ──────────────────────────────────────────────────────────────────
    if request.method == "PUT":
        if not pk:
            return Response({"error": "Category ID required"}, status=400)
        try:
            category = PharmacyCategory.objects.get(category_id=pk)
            if not category.is_active:
                return Response({"error": "Category not found"}, status=404)
        except PharmacyCategory.DoesNotExist:
            return Response({"error": "Category not found"}, status=404)
        except (ValueError, TypeError):
            return Response({"error": "Invalid Category ID"}, status=400)

        serializer = PharmacyCategorySerializer(category, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save(lastmodified_by=user_id)
            return Response(serializer.data)
        return Response(serializer.errors, status=400)

    # ── DELETE ───────────────────────────────────────────────────────────────
    if request.method == "DELETE":
        if not pk:
            return Response({"error": "Category ID required"}, status=400)
        try:
            category = PharmacyCategory.objects.get(category_id=pk)
            if not category.is_active:
                return Response({"error": "Category not found"}, status=404)
        except PharmacyCategory.DoesNotExist:
            return Response({"error": "Category not found"}, status=404)
        except (ValueError, TypeError):
            return Response({"error": "Invalid Category ID"}, status=400)

        category.is_active = False
        category.lastmodified_by = user_id
        category.save()
        return Response({"message": "Deleted successfully"}, status=200)
    

#PHARMACY STOCK VIEWS
from ..models import PharmacyItem
from ..serializers import PharmacyItemSerializer

@api_view(["GET", "POST", "PUT", "DELETE"])
@csrf_exempt
def pharmacy_item_view(request, pk=None):

    user_id = request.headers.get("auth-user-id", "system")

    # ── GET ──
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

    # ── POST ──
    if request.method == "POST":
        serializer = PharmacyItemSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(created_by=user_id, lastmodified_by=user_id)
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)

    # ── PUT ──
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

    # ── DELETE ──
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

@api_view(["GET", "POST", "PUT"])
@csrf_exempt
def grn_view(request, pk=None):

    user_id = request.headers.get("auth-user-id", "system")

    # ───────── GET ─────────
    if request.method == "GET":
        if pk:
            try:
                grn = GRN.objects.get(id=ObjectId(pk))
            except Exception:
                return Response({"error": "GRN not found"}, status=404)
            serializer = GRNSerializer(grn)
            return Response(serializer.data)

        grns = GRN.objects.all().order_by("-created_date")
        serializer = GRNSerializer(grns, many=True)
        return Response(serializer.data)

    # ───────── POST ─────────
    if request.method == "POST":
        data = request.data.copy()

        if isinstance(data.get("items"), (list, dict)):
            data["items"] = json.dumps(data["items"])
        if isinstance(data.get("payment_status"), (list, dict)):
            data["payment_status"] = json.dumps(data["payment_status"])

        serializer = GRNSerializer(data=data)
        if serializer.is_valid():
            serializer.save(created_by=user_id, lastmodified_by=user_id)
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)

    # ───────── PUT ─────────
    if request.method == "PUT":
        if not pk:
            return Response({"error": "GRN ID required"}, status=400)
        try:
            grn = GRN.objects.get(grn_id=pk)
            if not grn.is_active:
                return Response({"error": "GRN not found"}, status=404)
        except GRN.DoesNotExist:
            return Response({"error": "GRN not found"}, status=404)
        except (ValueError, TypeError):
            return Response({"error": "Invalid GRN ID"}, status=400)

        data = request.data.copy()

        # Serialise JSON fields if they arrive as parsed objects
        if isinstance(data.get("items"), (list, dict)):
            data["items"] = json.dumps(data["items"])
        if isinstance(data.get("payment_status"), (list, dict)):
            data["payment_status"] = json.dumps(data["payment_status"])

        # ── Regenerate grn_number when purchase_category changes ──────────────
        new_category = data.get("purchase_category", grn.purchase_category)
        if new_category != grn.purchase_category:
            # Clear grn_number so model.save() auto-generates the correct one
            grn.purchase_category = new_category   # set before calling helper
            data["grn_number"] = grn._next_grn_number()
        else:
            # Category unchanged — preserve existing grn_number (never overwrite)
            data["grn_number"] = grn.grn_number

        serializer = GRNSerializer(grn, data=data, partial=True)
        if serializer.is_valid():
            serializer.save(lastmodified_by=user_id)
            return Response(serializer.data)
        return Response(serializer.errors, status=400)