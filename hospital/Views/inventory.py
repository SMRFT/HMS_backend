from django.shortcuts import render
from rest_framework.response import Response
from django.http import JsonResponse
from rest_framework import status
from pymongo import MongoClient
from django.utils.timezone import now
from rest_framework.parsers import MultiPartParser, FormParser
from bson import Decimal128, ObjectId
from datetime import datetime
from decimal import Decimal, InvalidOperation
from django.utils import timezone
import re
import logging
import json
import os
import ast
from collections import OrderedDict
from typing import Any
from rest_framework.decorators import api_view, permission_classes,parser_classes
from django.views.decorators.csrf import csrf_exempt

# Auth/permissions
from pyauth.auth import HasRoleAndDataPermission

# Logger setup
logger = logging.getLogger(__name__)


#VENDOR VIEWS
from ..models import Vendor
from ..serializers import VendorSerializer

@api_view(["GET", "POST", "PUT", "DELETE"])
@permission_classes([HasRoleAndDataPermission])
def vendor_view(request, pk=None):

    employee_id = (
        request.data.get('auth-user-id') or
        request.headers.get('auth-user-id') or
        "system"
    )

    hospital_code = (
        request.data.get("auth-hospital-code") or
        request.headers.get("auth-hospital-code") or
        "system"
    )

    branch_code = (
        request.data.get("auth-branch-code") or
        request.headers.get("Branch-Code") or
        "system"
    )

    # ── GET ─────────────────────────────────────────────
    if request.method == "GET":

        if pk:
            try:
                vendor = Vendor.objects.get(
                    vendor_id=pk,
                    hospital_code=hospital_code,
                    branch_code=branch_code
                )

                if not vendor.is_active:
                    return Response({"error": "Vendor not found"}, status=404)

            except Vendor.DoesNotExist:
                return Response({"error": "Vendor not found"}, status=404)

            serializer = VendorSerializer(vendor)
            return Response(serializer.data)

        # list
        all_vendors = Vendor.objects.filter(
            hospital_code=hospital_code,
            branch_code=branch_code
        ).order_by("vendor_id")

        vendors = [v for v in all_vendors if v.is_active]

        serializer = VendorSerializer(vendors, many=True)
        return Response(serializer.data)

    # ── POST ─────────────────────────────────────────────
    if request.method == "POST":

        data = request.data.copy()
        data["hospital_code"] = hospital_code
        data["branch_code"] = branch_code

        serializer = VendorSerializer(data=data)
        if serializer.is_valid():
            serializer.save(
                created_by=employee_id,
                created_date=timezone.now(),
                is_active=True
            )
            return Response(serializer.data, status=201)

        return Response(serializer.errors, status=400)

    # ── PUT ─────────────────────────────────────────────
    if request.method == "PUT":

        if not pk:
            return Response({"error": "Vendor ID required"}, status=400)

        try:
            vendor = Vendor.objects.get(
                vendor_id=pk,
                hospital_code=hospital_code,
                branch_code=branch_code
            )

            if not vendor.is_active:
                return Response({"error": "Vendor not found"}, status=404)

        except Vendor.DoesNotExist:
            return Response({"error": "Vendor not found"}, status=404)

        serializer = VendorSerializer(vendor, data=request.data, partial=True)

        if serializer.is_valid():
            serializer.save(
                lastmodified_by=employee_id,
                lastmodified_date=timezone.now()
            )
            return Response(serializer.data)

        return Response(serializer.errors, status=400)

    # ── DELETE (SOFT DELETE) ─────────────────────────────
    if request.method == "DELETE":

        if not pk:
            return Response({"error": "Vendor ID required"}, status=400)

        try:
            vendor = Vendor.objects.get(
                vendor_id=pk,
                hospital_code=hospital_code,
                branch_code=branch_code
            )

            if not vendor.is_active:
                return Response({"error": "Vendor not found"}, status=404)

        except Vendor.DoesNotExist:
            return Response({"error": "Vendor not found"}, status=404)

        vendor.is_active = False
        vendor.lastmodified_by = employee_id
        vendor.lastmodified_date = timezone.now()
        vendor.save()

        return Response({"message": "Deleted successfully"}, status=200)

    
# CHEMICAL COMPOSITION VIEWS
from ..models import ChemicalComposition
from ..serializers import ChemicalCompositionSerializer

@api_view(["GET", "POST", "PUT", "DELETE"])
@permission_classes([HasRoleAndDataPermission])
def chemical_composition_view(request, pk=None):

    employee_id = (
        request.data.get('auth-user-id') or
        request.headers.get('auth-user-id') or
        "system"
    )

    hospital_code = (
        request.data.get("auth-hospital-code") or
        request.headers.get("auth-hospital-code") or
        None   # ⚠️ IMPORTANT
    )

    branch_code = (
        request.data.get("auth-branch-code") or
        request.headers.get("Branch-Code") or
        None
    )

    # ─────────────── GET ───────────────
    if request.method == "GET":

        try:
            if pk:
                comp = ChemicalComposition.objects.get(composition_id=pk)

                if (
                    not comp.is_active or
                    getattr(comp, "hospital_code", None) != hospital_code or
                    getattr(comp, "branch_code", None) != branch_code
                ):
                    return Response({"error": "Composition not found"}, status=404)

                serializer = ChemicalCompositionSerializer(comp)
                return Response(serializer.data)

            # SAFE FETCH (Djongo safe)
            all_comps = ChemicalComposition.objects.all()

            comps = [
                c for c in all_comps
                if c.is_active and
                getattr(c, "hospital_code", None) == hospital_code and
                getattr(c, "branch_code", None) == branch_code
            ]

            serializer = ChemicalCompositionSerializer(comps, many=True)
            return Response(serializer.data)

        except Exception as e:
            return Response({"error": str(e)}, status=500)

    # ─────────────── POST ───────────────
    if request.method == "POST":

        data = request.data.copy()
        data["hospital_code"] = hospital_code
        data["branch_code"] = branch_code

        serializer = ChemicalCompositionSerializer(data=data)

        if serializer.is_valid():
            serializer.save(
                created_by=employee_id,
                created_date=timezone.now(),
                is_active=True
            )
            return Response(serializer.data, status=201)

        return Response(serializer.errors, status=400)

    # ─────────────── PUT ───────────────
    if request.method == "PUT":

        if not pk:
            return Response({"error": "Composition ID required"}, status=400)

        try:
            comp = ChemicalComposition.objects.get(composition_id=pk)

            if (
                not comp.is_active or
                getattr(comp, "hospital_code", None) != hospital_code or
                getattr(comp, "branch_code", None) != branch_code
            ):
                return Response({"error": "Composition not found"}, status=404)

            serializer = ChemicalCompositionSerializer(
                comp,
                data=request.data,
                partial=True
            )

            if serializer.is_valid():
                serializer.save(
                    lastmodified_by=employee_id,
                    lastmodified_date=timezone.now()
                )
                return Response(serializer.data)

            return Response(serializer.errors, status=400)

        except ChemicalComposition.DoesNotExist:
            return Response({"error": "Composition not found"}, status=404)

    # ─────────────── DELETE ───────────────
    if request.method == "DELETE":

        if not pk:
            return Response({"error": "Composition ID required"}, status=400)

        try:
            comp = ChemicalComposition.objects.get(composition_id=pk)

            if (
                not comp.is_active or
                getattr(comp, "hospital_code", None) != hospital_code or
                getattr(comp, "branch_code", None) != branch_code
            ):
                return Response({"error": "Composition not found"}, status=404)

            comp.is_active = False
            comp.lastmodified_by = employee_id
            comp.lastmodified_date = timezone.now()
            comp.save()

            return Response({"message": "Deleted successfully"}, status=200)

        except ChemicalComposition.DoesNotExist:
            return Response({"error": "Composition not found"}, status=404)


#PHARMACY CATEGORY VIEWS
from ..models import PharmacyCategory
from ..serializers import PharmacyCategorySerializer

@api_view(["GET", "POST", "PUT", "DELETE"])
@permission_classes([HasRoleAndDataPermission])
def pharmacycategory_view(request, pk=None):

    employee_id = (
        request.data.get('auth-user-id') or
        request.headers.get('auth-user-id') or
        "system"
    )

    hospital_code = (
        request.data.get("auth-hospital-code") or
        request.headers.get("auth-hospital-code") or
        None   # ⚠️ use None instead of "system"
    )

    branch_code = (
        request.data.get("auth-branch-code") or
        request.headers.get("Branch-Code") or
        None
    )

    # ───────────────── GET ─────────────────
    if request.method == "GET":

        try:
            if pk:
                category = PharmacyCategory.objects.get(category_id=pk)

                # Djongo-safe filtering
                if (
                    not category.is_active or
                    getattr(category, "hospital_code", None) != hospital_code or
                    getattr(category, "branch_code", None) != branch_code
                ):
                    return Response({"error": "Category not found"}, status=404)

                serializer = PharmacyCategorySerializer(category)
                return Response(serializer.data)

            # SAFE FETCH (avoid Djongo crash)
            all_categories = PharmacyCategory.objects.all()

            categories = [
                c for c in all_categories
                if c.is_active and
                getattr(c, "hospital_code", None) == hospital_code and
                getattr(c, "branch_code", None) == branch_code
            ]

            serializer = PharmacyCategorySerializer(categories, many=True)
            return Response(serializer.data)

        except Exception as e:
            return Response({"error": str(e)}, status=500)

    # ───────────────── POST ─────────────────
    if request.method == "POST":

        data = request.data.copy()
        data["hospital_code"] = hospital_code
        data["branch_code"] = branch_code

        serializer = PharmacyCategorySerializer(data=data)

        if serializer.is_valid():
            serializer.save(
                created_by=employee_id,
                created_date=timezone.now(),
                is_active=True
            )
            return Response(serializer.data, status=201)

        return Response(serializer.errors, status=400)

    # ───────────────── PUT ─────────────────
    if request.method == "PUT":

        if not pk:
            return Response({"error": "Category ID required"}, status=400)

        try:
            category = PharmacyCategory.objects.get(category_id=pk)

            if (
                not category.is_active or
                getattr(category, "hospital_code", None) != hospital_code or
                getattr(category, "branch_code", None) != branch_code
            ):
                return Response({"error": "Category not found"}, status=404)

            serializer = PharmacyCategorySerializer(
                category,
                data=request.data,
                partial=True
            )

            if serializer.is_valid():
                serializer.save(
                    lastmodified_by=employee_id,
                    lastmodified_date=timezone.now()
                )
                return Response(serializer.data)

            return Response(serializer.errors, status=400)

        except PharmacyCategory.DoesNotExist:
            return Response({"error": "Category not found"}, status=404)

    # ───────────────── DELETE ─────────────────
    if request.method == "DELETE":

        if not pk:
            return Response({"error": "Category ID required"}, status=400)

        try:
            category = PharmacyCategory.objects.get(category_id=pk)

            if (
                not category.is_active or
                getattr(category, "hospital_code", None) != hospital_code or
                getattr(category, "branch_code", None) != branch_code
            ):
                return Response({"error": "Category not found"}, status=404)

            category.is_active = False
            category.lastmodified_by = employee_id
            category.lastmodified_date = timezone.now()
            category.save()

            return Response({"message": "Deleted successfully"}, status=200)

        except PharmacyCategory.DoesNotExist:
            return Response({"error": "Category not found"}, status=404)


#PHARMACY ITEM VIEWS
from ..models import PharmacyItem
from ..serializers import PharmacyItemSerializer

@api_view(["GET", "POST", "PUT", "DELETE"])
@permission_classes([HasRoleAndDataPermission])
def pharmacy_item_view(request, pk=None):

    employee_id = (
        request.data.get('auth-user-id') or
        request.headers.get('auth-user-id') or
        "system"
    )

    hospital_code = (
        request.data.get("auth-hospital-code") or
        request.headers.get("auth-hospital-code") or
        None   # ⚠️ use None instead of "system"
    )

    branch_code = (
        request.data.get("auth-branch-code") or
        request.headers.get("Branch-Code") or
        None
    )

    # ─────────────── GET ───────────────
    if request.method == "GET":

        try:
            if pk:
                item = PharmacyItem.objects.get(item_id=pk)

                if (
                    not item.is_active or
                    getattr(item, "hospital_code", None) != hospital_code or
                    getattr(item, "branch_code", None) != branch_code
                ):
                    return Response({"error": "Item not found"}, status=404)

                serializer = PharmacyItemSerializer(item)
                return Response(serializer.data)

            # Djongo-safe fetch
            all_items = PharmacyItem.objects.all()

            items = [
                i for i in all_items
                if i.is_active and
                getattr(i, "hospital_code", None) == hospital_code and
                getattr(i, "branch_code", None) == branch_code
            ]

            serializer = PharmacyItemSerializer(items, many=True)
            return Response(serializer.data)

        except Exception as e:
            return Response({"error": str(e)}, status=500)

    # ─────────────── POST ───────────────
    if request.method == "POST":

        payload = request.data.copy()
        payload["hospital_code"] = hospital_code
        payload["branch_code"] = branch_code

        serializer = PharmacyItemSerializer(data=payload)

        if serializer.is_valid():
            serializer.save(
                created_by=employee_id,
                created_date=timezone.now(),
                is_active=True
            )
            return Response(serializer.data, status=201)

        return Response(serializer.errors, status=400)

    # ─────────────── PUT ───────────────
    if request.method == "PUT":

        if not pk:
            return Response({"error": "Item ID required"}, status=400)

        try:
            item = PharmacyItem.objects.get(item_id=pk)

            if (
                not item.is_active or
                getattr(item, "hospital_code", None) != hospital_code or
                getattr(item, "branch_code", None) != branch_code
            ):
                return Response({"error": "Item not found"}, status=404)

            serializer = PharmacyItemSerializer(item, data=request.data, partial=True)

            if serializer.is_valid():
                serializer.save(
                    lastmodified_by=employee_id,
                    lastmodified_date=timezone.now()
                )
                return Response(serializer.data)

            return Response(serializer.errors, status=400)

        except PharmacyItem.DoesNotExist:
            return Response({"error": "Item not found"}, status=404)

    # ─────────────── DELETE ───────────────
    if request.method == "DELETE":

        if not pk:
            return Response({"error": "Item ID required"}, status=400)

        try:
            item = PharmacyItem.objects.get(item_id=pk)

            if (
                not item.is_active or
                getattr(item, "hospital_code", None) != hospital_code or
                getattr(item, "branch_code", None) != branch_code
            ):
                return Response({"error": "Item not found"}, status=404)

            item.is_active = False
            item.lastmodified_by = employee_id
            item.lastmodified_date = timezone.now()
            item.save()

            return Response({"message": "Deleted successfully"}, status=200)

        except PharmacyItem.DoesNotExist:
            return Response({"error": "Item not found"}, status=404)


# ─────────────────────────────────────────────────────────────────────────────
# GRN — number generation helpers ONLY
# ─────────────────────────────────────────────────────────────────────────────
from ..models import GRN
from ..serializers import GRNSerializer

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

GRN_CATEGORY_PREFIX = {
    "OP PHARMACY":   "OP",
    "IP PHARMACY":   "IP",
    "DRUG PURCHASE": "DP"
}


def _get_request_data(request):
    return request.data if hasattr(request, "data") else request.POST


def _current_fin_year():
    today = datetime.today()
    from_yr = today.year if today.month >= 4 else today.year - 1
    return f"{str(from_yr)[-2:]}{str(from_yr + 1)[-2:]}"


def _next_draft_number():
    """DRAFT/<FINYEAR>/<SEQ5>"""
    fin_year = _current_fin_year()
    prefix = f"DRAFT/{fin_year}/"

    all_grns = GRN.objects.all()

    draft_numbers = [
        getattr(g, "draft_number", "")
        for g in all_grns
        if getattr(g, "draft_number", "").startswith(prefix)
    ]

    max_seq = 0
    for draft in draft_numbers:
        try:
            seq = int(draft.split("/")[-1])
            if seq > max_seq:
                max_seq = seq
        except (ValueError, IndexError):
            continue

    return f"{prefix}{str(max_seq + 1).zfill(5)}"


def _grn_number_from_draft(draft_number, purchase_category):
    try:
        parts = draft_number.split("/")
        fin_year = parts[1]
        seq = parts[2]
    except (IndexError, AttributeError):
        fin_year = _current_fin_year()
        seq = "00001"

    cat_prefix = GRN_CATEGORY_PREFIX.get(purchase_category, "GRN")
    return f"{cat_prefix}/{fin_year}/{seq}"


# ─────────────────────────────────────────────────────────────────────────────
# GRN VIEW — DJONGO SAFE + HOSPITAL/BRANCH FILTER
# ─────────────────────────────────────────────────────────────────────────────
from ..models import GRN, PharmacyStock
@api_view(["GET", "POST", "PUT"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def grn_view(request, pk=None):
 
    data = _get_request_data(request)
 
    employee_id = (
        data.get("auth-user-id") or
        request.headers.get("auth-user-id") or
        "system"
    )
 
    hospital_code = (
        data.get("auth-hospital-code") or
        request.headers.get("auth-hospital-code") or
        None
    )
 
    branch_code = (
        data.get("auth-branch-code") or
        request.headers.get("Branch-Code") or
        None
    )
 
    # ───────────────── GET ─────────────────
    if request.method == "GET":
 
        try:
            if pk:
                grn = None
 
                try:
                    grn = GRN.objects.get(pk=pk)
                except Exception:
                    try:
                        grn = GRN.objects.get(draft_number=pk)
                    except GRN.DoesNotExist:
                        pass
 
                if not grn:
                    return Response({"error": "GRN not found"}, status=404)
 
                if (
                    getattr(grn, "hospital_code", None) != hospital_code or
                    getattr(grn, "branch_code", None) != branch_code
                ):
                    return Response({"error": "GRN not found"}, status=404)
 
                return Response(GRNSerializer(grn).data)
 
            # Djongo-safe fetch — list all for this hospital+branch
            all_grns = GRN.objects.all()
 
            grns = [
                g for g in all_grns
                if getattr(g, "hospital_code", None) == hospital_code
                and getattr(g, "branch_code", None) == branch_code
            ]
 
            grns = sorted(
                grns,
                key=lambda x: getattr(x, "created_date", timezone.now()),
                reverse=True,
            )
 
            return Response({"success": True, "data": GRNSerializer(grns, many=True).data})
 
        except Exception as e:
            logger.error("[grn_view GET] %s", e, exc_info=True)
            return Response({"error": str(e)}, status=500)
 
    # ───────────────── POST ─────────────────
    if request.method == "POST":
 
        payload = data.copy()
 
        if isinstance(payload.get("items"), (list, dict)):
            payload["items"] = json.dumps(payload["items"])
 
        if isinstance(payload.get("payment_status"), (list, dict)):
            payload["payment_status"] = json.dumps(payload["payment_status"])
 
        payload["hospital_code"] = hospital_code
        payload["branch_code"]   = branch_code
        payload["status"]        = "Draft"
        payload["grn_number"]    = ""
        payload["draft_number"]  = _next_draft_number()
 
        # Clear edit-audit fields on fresh creation
        payload["edited_by"]     = ""
        payload["edited_date"]   = None
        payload["edited_reason"] = ""
 
        serializer = GRNSerializer(data=payload)
 
        if serializer.is_valid():
            saved = serializer.save(
                created_by=employee_id,
                created_date=timezone.now(),
                is_active=True,
            )
            return Response({"success": True, "data": GRNSerializer(saved).data}, status=201)
 
        logger.error("GRN POST errors: %s", serializer.errors)
        return Response({"success": False, "error": serializer.errors}, status=400)
 
    # ───────────────── PUT ─────────────────
    if request.method == "PUT":
 
        incoming = data.copy()
 
        if isinstance(incoming.get("items"), (list, dict)):
            incoming["items"] = json.dumps(incoming["items"])
 
        if isinstance(incoming.get("payment_status"), (list, dict)):
            incoming["payment_status"] = json.dumps(incoming["payment_status"])
 
        draft_no_in_body = incoming.get("draft_number", "")
        grn = None
 
        # Resolve GRN object — try body draft_number first, then URL pk
        if draft_no_in_body:
            try:
                grn = GRN.objects.get(draft_number=draft_no_in_body)
            except GRN.DoesNotExist:
                pass
 
        if grn is None and pk:
            try:
                grn = GRN.objects.get(pk=pk)
            except GRN.DoesNotExist:
                pass
 
        if grn is None:
            return Response({"success": False, "error": "GRN not found"}, status=404)
 
        # Hospital / Branch security
        if (
            getattr(grn, "hospital_code", None) != hospital_code or
            getattr(grn, "branch_code", None) != branch_code
        ):
            return Response({"success": False, "error": "GRN not found"}, status=404)
 
        # Verified guard — no edits once verified
        if grn.status == "Verified":
            return Response(
                {"success": False, "error": "Verified GRN cannot be edited."},
                status=status.HTTP_403_FORBIDDEN,
            )
 
        incoming_status = incoming.get("status", grn.status)
        going_verified  = (grn.status == "Draft" and incoming_status == "Verified")
 
        if going_verified:
            # ── Draft → Verified: assign GRN number, clear edit-audit fields ──
            category = incoming.get("purchase_category") or grn.purchase_category or ""
            incoming["grn_number"]   = _grn_number_from_draft(grn.draft_number, category)
            incoming["draft_number"] = grn.draft_number
            incoming["status"]       = "Verified"
 
            # Edit-audit fields should not be touched during verification
            incoming.pop("edited_by",     None)
            incoming.pop("edited_date",   None)
            incoming.pop("edited_reason", None)
 
        else:
            # ── Draft → Draft (edit): require edited_reason ──────────────────
            edited_reason = str(incoming.get("edited_reason", "")).strip()
            if not edited_reason:
                return Response(
                    {
                        "success": False,
                        "error": "edited_reason is required when updating a Draft GRN",
                    },
                    status=400,
                )
 
            incoming["edited_reason"] = edited_reason
            incoming["edited_by"]     = employee_id
            incoming["edited_date"]   = timezone.now()
 
            incoming["grn_number"]   = ""
            incoming["draft_number"] = grn.draft_number
            incoming["status"]       = "Draft"
 
        # Immutable fields — never allow overwrite
        for field in ("created_by", "created_date", "hospital_code", "branch_code"):
            incoming.pop(field, None)
 
        incoming["lastmodified_by"]   = employee_id
        incoming["lastmodified_date"] = timezone.now()
 
        serializer = GRNSerializer(grn, data=incoming, partial=True)
 
        if not serializer.is_valid():
            logger.error("GRN PUT errors: %s", serializer.errors)
            return Response({"success": False, "error": serializer.errors}, status=400)
 
        saved = serializer.save()
 
        # ── Auto-create PharmacyStock on Verification ─────────────────────────
        if going_verified:
 
            DEPT_CODE_MAP = {
                "OP PHARMACY":   "OLET002",
                "IP PHARMACY":   "OLET001",
                "DRUG PURCHASE": "",
            }
 
            outlet_code     = DEPT_CODE_MAP.get(saved.purchase_category, "OLET002")
            assigned_grn_no = saved.grn_number
 
            try:
                items = json.loads(saved.items or "[]")
            except Exception:
                items = []
 
            for it in items:
                expiry_date = None
                expiry_raw  = it.get("expiry", "")
 
                if expiry_raw:
                    parts = expiry_raw.split("/")
                    if len(parts) == 2:
                        try:
                            expiry_date = datetime.strptime(
                                f"01/{parts[0]}/{parts[1]}", "%d/%m/%Y"
                            ).date()
                        except Exception:
                            expiry_date = None
 
                cgst_pct = float(it.get("selling_cgst_percent", 0) or 0)
                sgst_pct = float(it.get("selling_sgst_percent", 0) or 0)
 
                PharmacyStock.objects.create(
                    hospital_code            = hospital_code,
                    branch_code              = branch_code,
                    outlet_code              = outlet_code,
                    item_id                  = int(it.get("item_id") or 0),
                    batch_number             = str(it.get("batch") or ""),
                    expiry_date              = expiry_date,
                    mrp                      = float(it.get("mrp") or 0),
                    grn_number               = assigned_grn_no,
                    total_stock              = int(it.get("quantity") or 0),
                    sold_quantity            = 0,
                    transferred_out_quantity = 0,
                    stock_type               = "grn",
                    stock_ref_id             = 0,
                    grn_return_quantity      = 0,
                    blocked_quantity         = 0,
                    sales_return_quantity    = 0,
                    CGST_Percentage          = cgst_pct,
                    SGST_Percentage          = sgst_pct,
                    CGST_Amt                 = float(it.get("selling_cgst_amt", 0) or 0),
                    SGST_Amt                 = float(it.get("selling_sgst_amt", 0) or 0),
                    Selling_Price            = float(it.get("selling_price", 0) or 0),
                    created_by               = employee_id,
                    created_date             = timezone.now(),
                )
 
        return Response({"success": True, "data": GRNSerializer(saved).data})
    

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def pharmacy_stock_history(request):
    try:
        # ───────── Request Values ─────────
        item_id = str(request.GET.get("item_id", "")).strip()

        hospital_code = (
            request.GET.get("auth-hospital-code") or
            request.headers.get("auth-hospital-code") or
            None
        )

        branch_code = (
            request.GET.get("auth-branch-code") or
            request.headers.get("Branch-Code") or
            None
        )

        # ───────── Validation ─────────
        if not item_id:
            return Response({
                "success": False,
                "error": "item_id is required"
            }, status=400)

        # ───────── Djongo-safe fetch ─────────
        all_stocks = PharmacyStock.objects.all()

        stocks = [
            stock for stock in all_stocks
            if str(getattr(stock, "item_id", "")) == item_id
            and getattr(stock, "hospital_code", None) == hospital_code
            and getattr(stock, "branch_code", None) == branch_code
        ]

        # Latest first
        stocks = sorted(
            stocks,
            key=lambda x: (
                getattr(x, "created_date", None) or "",
                getattr(x, "stock_id", 0)
            ),
            reverse=True
        )

        # ───────── Build Response ─────────
        result = []

        for stock in stocks:
            result.append({
                "stock_id": getattr(stock, "stock_id", ""),
                "item_id": getattr(stock, "item_id", ""),
                "item_name": getattr(stock, "item_name", ""),
                "batch": getattr(stock, "batch_number", ""),
                "expiry": getattr(stock, "expiry_date", ""),
                "packing_price": str(getattr(stock, "packing_price", 0)),
                "purchase_cost": str(getattr(stock, "purchase_cost", 0)),
                "mrp": str(getattr(stock, "mrp", 0)),
                "CGST_Amt": str(getattr(stock, "CGST_Amt", 0)),
                "SGST_Amt": str(getattr(stock, "SGST_Amt", 0)),
                "quantity": str(
                    getattr(stock, "total_stock", 0)
                ),
                "vendor_id": getattr(stock, "vendor_id", ""),
                "invoice_no": getattr(stock, "invoice_no", ""),
                "grn_number": getattr(stock, "grn_number", ""),
                "hospital_code": getattr(stock, "hospital_code", ""),
                "branch_code": getattr(stock, "branch_code", ""),
                "created_date": getattr(stock, "created_date", None),
            })

        # ───────── Final Response ─────────
        return Response({
            "success": True,
            "count": len(result),
            "data": result
        })

    except Exception as e:
        return Response({
            "success": False,
            "error": str(e)
        }, status=500)