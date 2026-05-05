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
    "OPENING STOCK": "DP",
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
                except:
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

            # Djongo-safe fetch
            all_grns = GRN.objects.all()

            grns = [
                g for g in all_grns
                if getattr(g, "hospital_code", None) == hospital_code and
                getattr(g, "branch_code", None) == branch_code
            ]

            grns = sorted(
                grns,
                key=lambda x: getattr(x, "created_date", timezone.now()),
                reverse=True
            )

            return Response(GRNSerializer(grns, many=True).data)

        except Exception as e:
            return Response({"error": str(e)}, status=500)

    # ───────────────── POST ─────────────────
    if request.method == "POST":

        payload = data.copy()

        if isinstance(payload.get("items"), (list, dict)):
            payload["items"] = json.dumps(payload["items"])

        if isinstance(payload.get("payment_status"), (list, dict)):
            payload["payment_status"] = json.dumps(payload["payment_status"])

        payload["hospital_code"] = hospital_code
        payload["branch_code"] = branch_code
        payload["status"] = "Draft"
        payload["grn_number"] = ""
        payload["draft_number"] = _next_draft_number()

        serializer = GRNSerializer(data=payload)

        if serializer.is_valid():
            saved = serializer.save(
                created_by=employee_id,
                created_date=timezone.now(),
                is_active=True
            )

            return Response(GRNSerializer(saved).data, status=201)

        logger.error("GRN POST errors: %s", serializer.errors)
        return Response(serializer.errors, status=400)

    # ───────────────── PUT ─────────────────
    if request.method == "PUT":

        incoming = data.copy()

        if isinstance(incoming.get("items"), (list, dict)):
            incoming["items"] = json.dumps(incoming["items"])

        if isinstance(incoming.get("payment_status"), (list, dict)):
            incoming["payment_status"] = json.dumps(incoming["payment_status"])

        draft_no_in_body = incoming.get("draft_number", "")
        grn = None

        # Resolve GRN
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
            return Response({"error": "GRN not found"}, status=404)

        # Hospital/Branch security
        if (
            getattr(grn, "hospital_code", None) != hospital_code or
            getattr(grn, "branch_code", None) != branch_code
        ):
            return Response({"error": "GRN not found"}, status=404)

        # Verified guard
        if grn.status == "Verified":
            return Response(
                {"error": "Verified GRN cannot be edited."},
                status=status.HTTP_403_FORBIDDEN,
            )

        incoming_status = incoming.get("status", grn.status)
        going_verified = (grn.status == "Draft" and incoming_status == "Verified")

        if going_verified:
            category = incoming.get("purchase_category") or grn.purchase_category or ""
            incoming["grn_number"] = _grn_number_from_draft(
                grn.draft_number,
                category
            )
            incoming["draft_number"] = grn.draft_number
            incoming["status"] = "Verified"
        else:
            incoming["grn_number"] = ""
            incoming["draft_number"] = grn.draft_number
            incoming["status"] = "Draft"

        # Immutable fields
        for field in (
            "created_by",
            "created_date",
            "hospital_code",
            "branch_code",
        ):
            incoming.pop(field, None)

        incoming["lastmodified_by"] = employee_id
        incoming["lastmodified_date"] = timezone.now()

        serializer = GRNSerializer(grn, data=incoming, partial=True)

        if not serializer.is_valid():
            logger.error("GRN PUT errors: %s", serializer.errors)
            return Response(serializer.errors, status=400)

        saved = serializer.save()

        # ───────── Auto-create PharmacyStock on Verification ─────────
        if going_verified:

            DEPT_CODE_MAP = {
                "OP PHARMACY": "OLET002",
                "IP PHARMACY": "OLET001",
                "OPENING STOCK": "",
            }

            outlet_code = DEPT_CODE_MAP.get(
                saved.purchase_category,
                "OP PHARMACY"
            )

            assigned_grn_no = saved.grn_number

            try:
                items = json.loads(saved.items or "[]")
            except:
                items = []

            for it in items:
                expiry_date = None
                expiry_raw = it.get("expiry", "")

                if expiry_raw:
                    parts = expiry_raw.split("/")
                    if len(parts) == 2:
                        try:
                            expiry_date = datetime.strptime(
                                f"01/{parts[0]}/{parts[1]}",
                                "%d/%m/%Y"
                            ).date()
                        except:
                            expiry_date = None

                cgst_pct = float(it.get("selling_cgst_percent", 0) or 0)
                sgst_pct = float(it.get("selling_sgst_percent", 0) or 0)

                PharmacyStock.objects.create(
                    hospital_code=hospital_code,
                    branch_code=branch_code,
                    outlet_code=outlet_code,
                    item_id=int(it.get("item_id") or 0),
                    batch_number=str(it.get("batch") or ""),
                    expiry_date=expiry_date,
                    mrp=float(it.get("mrp") or 0),
                    grn_number=assigned_grn_no,
                    total_stock=int(it.get("quantity") or 0),
                    sold_quantity=0,
                    transferred_out_quantity=0,
                    stock_type="grn",
                    stock_ref_id=0,
                    grn_return_quantity=0,
                    blocked_quantity=0,
                    sales_return_quantity=0,
                    CGST_Percentage=cgst_pct,
                    SGST_Percentage=sgst_pct,
                    CGST_Amt=float(it.get("selling_cgst_amt", 0) or 0),
                    SGST_Amt=float(it.get("selling_sgst_amt", 0) or 0),
                    Selling_Price=float(it.get("selling_price", 0) or 0),
                    created_by=employee_id,
                    created_date=timezone.now(),
                )

        return Response(GRNSerializer(saved).data)
    

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


@api_view(["GET"])
def get_active_stock_outlets(request):
    try:
        client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
        db = client.HMS
        collection = db.hospital_outlets

        query = {
            "is_stock_outlet": True,
            "is_active": True
        }

        outlets = list(collection.find(query, {"_id": 0}))

        return Response({
            "success": True,
            "data": outlets
        })

    except Exception as e:
        return Response({
            "success": False,
            "error": str(e)
        }, status=500)


from ..models import PharmacyStock, StockTransfer, PharmacyItem
from ..serializers import StockTransferSerializer, PharmacyStockSerializer     
# ─────────────────────────────────────────────────────────────────────────────
# SAFE HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _dec(value, default="0.00"):
    """
    Safely convert any value coming out of a Djongo/MongoDB query to a Python
    Decimal.  Handles:
        • bson.Decimal128          (has .to_decimal())
        • {"$numberDecimal": "x"}  (raw Mongo dict)
        • '"450.00"'               (double-quoted string from JSON)
        • '450.00'                 (plain string)
        • int / float              (direct cast)
        • None / "" / "None"       (returns default)
    """
    try:
        if value in (None, "", "None"):
            return Decimal(default)

        # bson Decimal128
        if hasattr(value, "to_decimal"):
            return value.to_decimal()

        # Raw Mongo extended-JSON dict
        if isinstance(value, dict) and "$numberDecimal" in value:
            return Decimal(str(value["$numberDecimal"]))

        # Strip curly/straight quotes, commas, whitespace
        cleaned = (
            str(value)
            .strip()
            .replace("\u201c", "")   # "
            .replace("\u201d", "")   # "
            .replace('"', "")
            .replace("'", "")
            .replace(",", "")
        )

        if cleaned in ("", "None"):
            cleaned = default

        return Decimal(cleaned)

    except (InvalidOperation, Exception):
        return Decimal(default)


def _int(value, default=0):
    """Decimal128-safe integer conversion."""
    try:
        return int(_dec(value, str(default)))
    except Exception:
        return default

# ─── Financial year + ref-number ─────────────────────────────────────────────

def _current_fin_year():
    from datetime import datetime
    today = datetime.today()
    from_yr = today.year if today.month >= 4 else today.year - 1
    return f"{str(from_yr)[-2:]}{str(from_yr + 1)[-2:]}"


def _next_transfer_ref_number():
    prefix  = f"{_current_fin_year()}/"
    max_seq = 0
    for row in StockTransfer.objects.all():
        ref = str(getattr(row, "transfer_ref_number", "")).strip()
        if ref.startswith(prefix):
            try:
                seq = int(ref.split("/")[-1])
                if seq > max_seq:
                    max_seq = seq
            except (ValueError, IndexError):
                pass
    return f"{prefix}{str(max_seq + 1).zfill(6)}"


# ─────────────────────────────────────────────────────────────────────────────
# STOCK TRANSFER VIEW
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET", "POST", "PUT"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def stock_transfer_view(request, pk=None):

    request_data = request.data if hasattr(request, "data") else request.POST

    user_id = (
        request_data.get("auth-user-id")
        or request.headers.get("auth-user-id")
        or "system"
    )
    hospital_code = (
        request_data.get("auth-hospital-code")
        or request.headers.get("auth-hospital-code")
        or None
    )
    branch_code = (
        request_data.get("auth-branch-code")
        or request.headers.get("auth-branch-code")
        or request.headers.get("Branch-Code")
        or None
    )

    # ─────────────────────────────────────────────────────────────────────────
    # GET
    # ─────────────────────────────────────────────────────────────────────────
    if request.method == "GET":

        # single record
        if pk:
            try:
                obj = StockTransfer.objects.get(transfer_id=pk)
            except StockTransfer.DoesNotExist:
                return Response({"success": False, "error": "Transfer not found"}, status=404)

            if (
                str(getattr(obj, "hospital_code", "")) != str(hospital_code)
                or str(getattr(obj, "branch_code", ""))  != str(branch_code)
            ):
                return Response({"success": False, "error": "Transfer not found"}, status=404)

            return Response({"success": True, "data": StockTransferSerializer(obj).data})

        # list — Djongo-safe Python filter
        from_outlet_f  = request.GET.get("from_outlet", "")
        to_outlet_f    = request.GET.get("to_outlet",   "")
        ref_prefix_f   = request.GET.get("ref_prefix",  "")
        # ── NEW: selected_outlet filter for outlet-wise display ──────────────
        selected_outlet_f = request.GET.get("selected_outlet", "")

        results = []
        for row in StockTransfer.objects.all():
            if str(getattr(row, "hospital_code", "")) != str(hospital_code):
                continue
            if str(getattr(row, "branch_code", ""))  != str(branch_code):
                continue
            # outlet_code stores the FROM outlet
            if from_outlet_f and from_outlet_f != "All":
                if str(getattr(row, "outlet_code", "")) != from_outlet_f:
                    continue
            if to_outlet_f and to_outlet_f != "All":
                if str(getattr(row, "to_outlet", "")) != to_outlet_f:
                    continue
            if ref_prefix_f:
                if not str(getattr(row, "transfer_ref_number", "")).startswith(ref_prefix_f):
                    continue
            # ── NEW: outlet-wise filter —
            # if selected_outlet is provided, show records where this outlet
            # appears as either the source (outlet_code) or destination (to_outlet)
            if selected_outlet_f:
                row_from = str(getattr(row, "outlet_code", ""))
                row_to   = str(getattr(row, "to_outlet",   ""))
                if selected_outlet_f not in (row_from, row_to):
                    continue
            results.append(row)

        results.sort(
            key=lambda x: getattr(x, "created_date", timezone.now()),
            reverse=True,
        )

        rows = StockTransferSerializer(results, many=True).data
        # add from_outlet alias so frontend table column works unchanged
        for row in rows:
            row["from_outlet"] = row.get("outlet_code", "")

        return Response({"success": True, "count": len(rows), "data": rows})

    # ─────────────────────────────────────────────────────────────────────────
    # POST  —  3-step logic (ONLY creates StockTransfer in Draft state)
    #   Step 1: Validate available stock quantities
    #   Step 2: Create StockTransfer master record (is_verified = "Draft")
    #   NOTE:   transferred_out_quantity update + PharmacyStock creation
    #           happen in PUT /approve — NOT here
    # ─────────────────────────────────────────────────────────────────────────
    if request.method == "POST":

        data = request_data.copy()

        raw_items = data.get("items", [])
        if isinstance(raw_items, str):
            try:
                raw_items = json.loads(raw_items)
            except (json.JSONDecodeError, ValueError):
                raw_items = []

        if not raw_items:
            return Response({"success": False, "error": "At least one item is required"}, status=400)

        from_outlet = str(data.get("from_outlet", "")).strip()   # outlet_code of source
        to_outlet   = str(data.get("to_outlet",   "")).strip()   # outlet_code of destination

        if not from_outlet or not to_outlet:
            return Response({"success": False, "error": "from_outlet and to_outlet are required"}, status=400)
        if from_outlet == to_outlet:
            return Response({"success": False, "error": "from_outlet and to_outlet must be different"}, status=400)

        # load all stocks once (Djongo-safe)
        all_stocks = list(PharmacyStock.objects.all())

        errors          = []
        processed_items = []   # saved into StockTransfer.items JSONField

        for idx, item in enumerate(raw_items):

            stock_id     = str(item.get("stock_id",     "")).strip()
            item_id      = str(item.get("item_id",      "")).strip()
            batch_number = str(item.get("batch_number", "")).strip()
            outlet_code  = str(item.get("outlet_code") or from_outlet).strip()
            transfer_qty = _int(item.get("transfer_quantity", 0))

            if transfer_qty <= 0:
                errors.append(f"Item {idx + 1}: transfer_quantity must be > 0")
                continue

            # ── locate source stock row ───────────────────────────────────────
            source = None
            for s in all_stocks:
                if (
                    str(getattr(s, "hospital_code", "")) != str(hospital_code)
                    or str(getattr(s, "branch_code",  "")) != str(branch_code)
                ):
                    continue

                # prefer exact stock_id match
                if stock_id and str(getattr(s, "stock_id", "")) == stock_id:
                    source = s
                    break

                # fallback: item_id + batch_number + outlet_code
                if (
                    str(getattr(s, "item_id",      "")) == item_id
                    and str(getattr(s, "batch_number", "")).strip() == batch_number
                    and str(getattr(s, "outlet_code",  "")).strip() == outlet_code
                ):
                    source = s
                    break

            if source is None:
                errors.append(f"Item {idx + 1}: stock record not found "
                              f"(item_id={item_id}, batch={batch_number}, outlet={outlet_code})")
                continue

            # ── validate available quantity ───────────────────────────────────
            available = (
                _int(getattr(source, "total_stock",               0))
                - _int(getattr(source, "sold_quantity",           0))
                - _int(getattr(source, "transferred_out_quantity", 0))
                - _int(getattr(source, "grn_return_quantity",      0))
                - _int(getattr(source, "blocked_quantity",         0))
                + _int(getattr(source, "sales_return_quantity",    0))
            )

            if transfer_qty > available:
                errors.append(
                    f"Item {idx + 1} (batch={batch_number}): "
                    f"requested {transfer_qty}, only {available} available"
                )
                continue

            processed_items.append({
                "stock_id":                 _int(getattr(source, "stock_id", 0)),
                "item_id":                  _int(item_id),
                "batch_number":             batch_number,
                "transferred_out_quantity": transfer_qty,
            })

        if errors:
            return Response({"success": False, "error": errors}, status=400)

        # ─────────────────────────────────────────────────────────────────────
        # STEP 2 — create the StockTransfer master record in DRAFT state only
        #
        # outlet_code = from_outlet (source)
        # to_outlet   = to_outlet   (destination)
        # items       = raw Python list
        # is_verified = "Draft"  (stock quantities NOT yet affected)
        # ─────────────────────────────────────────────────────────────────────
        transfer_payload = {
            "outlet_code":         from_outlet,
            "to_outlet":           to_outlet,
            "transfer_ref_number": _next_transfer_ref_number(),
            "items":               processed_items,
            "is_verified":         "Draft",
            "hospital_code":       hospital_code,
            "branch_code":         branch_code,
        }

        serializer = StockTransferSerializer(data=transfer_payload)
        if serializer.is_valid():
            saved = serializer.save(
                created_by        = user_id,
                created_date      = timezone.now(),
                lastmodified_by   = user_id,
                lastmodified_date = timezone.now(),
            )
            return Response(
                {
                    "success": True,
                    "message": "Stock transfer created as Draft",
                    "data":    StockTransferSerializer(saved).data,
                },
                status=201,
            )

        return Response({"success": False, "error": serializer.errors}, status=400)

    # ─────────────────────────────────────────────────────────────────────────
    # PUT  —  Approve / Reject / general update
    #
    # action = "approve"  →  run the 2-step stock update + set is_verified=Approved
    # action = "reject"   →  set is_verified=Rejected  (no stock changes)
    # (no action)         →  partial field update (ref number immutable)
    # ─────────────────────────────────────────────────────────────────────────
    if request.method == "PUT":

        if not pk:
            return Response({"success": False, "error": "transfer_id is required"}, status=400)

        try:
            obj = StockTransfer.objects.get(transfer_id=pk)
        except StockTransfer.DoesNotExist:
            return Response({"success": False, "error": "Transfer not found"}, status=404)

        if (
            str(getattr(obj, "hospital_code", "")) != str(hospital_code)
            or str(getattr(obj, "branch_code",  "")) != str(branch_code)
        ):
            return Response({"success": False, "error": "Transfer not found"}, status=404)

        current_status = str(getattr(obj, "is_verified", ""))
        action = str(request_data.get("action", "")).strip().lower()

        # ── APPROVE ──────────────────────────────────────────────────────────
        if action == "approve":

            if current_status == "Approved":
                return Response({"success": False, "error": "Transfer is already Approved"}, status=400)
            if current_status == "Rejected":
                return Response({"success": False, "error": "Rejected transfers cannot be approved"}, status=403)

            transfer_items = getattr(obj, "items", []) or []
            from_outlet    = str(getattr(obj, "outlet_code", ""))
            to_outlet      = str(getattr(obj, "to_outlet",   ""))
            all_stocks     = list(PharmacyStock.objects.all())
            errors         = []

            for idx, item in enumerate(transfer_items):
                stock_id     = str(item.get("stock_id",     "")).strip()
                item_id      = str(item.get("item_id",      "")).strip()
                batch_number = str(item.get("batch_number", "")).strip()
                transfer_qty = _int(item.get("transferred_out_quantity", 0))

                if transfer_qty <= 0:
                    errors.append(f"Item {idx + 1}: invalid transfer quantity")
                    continue

                # ── locate source stock ───────────────────────────────────────
                source = None
                for s in all_stocks:
                    if (
                        str(getattr(s, "hospital_code", "")) != str(hospital_code)
                        or str(getattr(s, "branch_code",  "")) != str(branch_code)
                    ):
                        continue
                    if stock_id and str(getattr(s, "stock_id", "")) == stock_id:
                        source = s
                        break
                    if (
                        str(getattr(s, "item_id",      "")) == item_id
                        and str(getattr(s, "batch_number", "")).strip() == batch_number
                        and str(getattr(s, "outlet_code",  "")).strip() == from_outlet
                    ):
                        source = s
                        break

                if source is None:
                    errors.append(f"Item {idx + 1}: source stock not found "
                                  f"(item_id={item_id}, batch={batch_number})")
                    continue

                # ── re-validate available qty at approval time ────────────────
                available = (
                    _int(getattr(source, "total_stock",               0))
                    - _int(getattr(source, "sold_quantity",           0))
                    - _int(getattr(source, "transferred_out_quantity", 0))
                    - _int(getattr(source, "grn_return_quantity",      0))
                    - _int(getattr(source, "blocked_quantity",         0))
                    + _int(getattr(source, "sales_return_quantity",    0))
                )

                if transfer_qty > available:
                    errors.append(
                        f"Item {idx + 1} (batch={batch_number}): "
                        f"requested {transfer_qty}, only {available} available at approval time"
                    )
                    continue

                # ── STEP 1: update transferred_out_quantity on source ─────────
                new_transferred_out = (
                    _int(getattr(source, "transferred_out_quantity", 0)) + transfer_qty
                )
                PharmacyStock.objects.filter(
                    item_id=getattr(source, "item_id", None),
                    batch_number=getattr(source, "batch_number", ""),
                    hospital_code=hospital_code,
                    branch_code=branch_code,
                    outlet_code=from_outlet,
                ).update(
                    transferred_out_quantity=new_transferred_out,
                    lastmodified_by=user_id,
                    lastmodified_date=timezone.now(),
                )

                # ── STEP 2: create new PharmacyStock row for destination ───────
                source_stock_id = _int(getattr(source, "stock_id", 0))
                try:
                    PharmacyStock.objects.create(
                        hospital_code   = hospital_code,
                        branch_code     = branch_code,
                        outlet_code     = to_outlet,
                        item_id         = _int(getattr(source, "item_id", 0)),
                        batch_number    = str(getattr(source, "batch_number", "") or ""),
                        expiry_date     = getattr(source, "expiry_date", None),
                        grn_number      = str(getattr(source, "grn_number", "") or ""),
                        total_stock               = transfer_qty,
                        sold_quantity             = 0,
                        transferred_out_quantity  = 0,
                        grn_return_quantity       = 0,
                        grn_return_ref_id         = None,
                        blocked_quantity          = 0,
                        sales_return_quantity     = 0,
                        sales_return_ref_id       = None,
                        stock_type   = "transfer",
                        stock_ref_id = source_stock_id,
                        mrp               = _dec(getattr(source, "mrp",               0)),
                        Selling_Price     = _dec(getattr(source, "Selling_Price",     0)),
                        CGST_Percentage   = _dec(getattr(source, "CGST_Percentage",   0)),
                        SGST_Percentage   = _dec(getattr(source, "SGST_Percentage",   0)),
                        CGST_Amt          = _dec(getattr(source, "CGST_Amt",          0)),
                        SGST_Amt          = _dec(getattr(source, "SGST_Amt",          0)),
                        created_by        = user_id,
                        created_date      = timezone.now(),
                        lastmodified_by   = user_id,
                        lastmodified_date = timezone.now(),
                    )
                except Exception as e:
                    errors.append(f"Item {idx + 1}: failed to create destination stock — {e}")
                    continue

            if errors:
                return Response({"success": False, "error": errors}, status=400)

            # ── mark transfer as Approved ─────────────────────────────────────
            StockTransfer.objects.filter(
                transfer_id=pk
            ).update(
                is_verified       = "Approved",
                lastmodified_by   = user_id,
                lastmodified_date = timezone.now(),
            )

            try:
                updated = StockTransfer.objects.get(transfer_id=pk)
            except StockTransfer.DoesNotExist:
                updated = obj

            return Response({
                "success": True,
                "message": "Stock transfer approved successfully",
                "data":    StockTransferSerializer(updated).data,
            })

        # ── REJECT ───────────────────────────────────────────────────────────
        if action == "reject":

            if current_status == "Approved":
                return Response({"success": False, "error": "Approved transfers cannot be rejected"}, status=403)
            if current_status == "Rejected":
                return Response({"success": False, "error": "Transfer is already Rejected"}, status=400)

            StockTransfer.objects.filter(
                transfer_id=pk
            ).update(
                is_verified       = "Rejected",
                lastmodified_by   = user_id,
                lastmodified_date = timezone.now(),
            )

            try:
                updated = StockTransfer.objects.get(transfer_id=pk)
            except StockTransfer.DoesNotExist:
                updated = obj

            return Response({
                "success": True,
                "message": "Stock transfer rejected",
                "data":    StockTransferSerializer(updated).data,
            })

        # ── General partial update (no action) ───────────────────────────────
        if current_status == "Approved":
            return Response({"success": False, "error": "Approved transfers cannot be edited"}, status=403)

        incoming = request_data.copy()
        # ref number is immutable
        incoming["transfer_ref_number"] = obj.transfer_ref_number
        incoming.pop("created_by",   None)
        incoming.pop("created_date", None)

        serializer = StockTransferSerializer(obj, data=incoming, partial=True)
        if serializer.is_valid():
            saved = serializer.save(lastmodified_by=user_id, lastmodified_date=timezone.now())
            return Response({"success": True, "data": StockTransferSerializer(saved).data})

        return Response({"success": False, "error": serializer.errors}, status=400)


# ─────────────────────────────────────────────────────────────────────────────
# PHARMACY STOCK VIEW
# Filters: grn_number, item_id, outlet_code, search (item_name)
# Response: enriched with item_name + available_qty (all Decimal128-safe)
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET"])
@csrf_exempt
def pharmacy_stock_view(request, pk=None):

    if request.method == "GET":

        # single record
        if pk:
            try:
                stock = PharmacyStock.objects.get(stock_id=pk)
            except PharmacyStock.DoesNotExist:
                return Response({"error": "Stock record not found"}, status=404)
            return Response(PharmacyStockSerializer(stock).data)

        # list
        all_stocks  = list(PharmacyStock.objects.all().order_by("-stock_id"))
        grn_number  = request.query_params.get("grn_number")
        item_id     = request.query_params.get("item_id")
        outlet_code = request.query_params.get("outlet_code")
        search      = request.query_params.get("search", "").strip().lower()

        # resolve item_ids that match the search string
        matching_item_ids = None
        if search:
            all_items = list(PharmacyItem.objects.all())
            matching_item_ids = {
                str(i.item_id)
                for i in all_items
                if search in str(getattr(i, "item_name", "")).lower()
            }
            if not matching_item_ids:
                return Response([])

        results = []
        for s in all_stocks:
            if grn_number and getattr(s, "grn_number", "") != grn_number:
                continue
            if item_id and str(getattr(s, "item_id", "")) != str(item_id):
                continue
            if outlet_code and getattr(s, "outlet_code", "") != outlet_code:
                continue
            if matching_item_ids is not None and str(getattr(s, "item_id", "")) not in matching_item_ids:
                continue
            results.append(s)

        # build item_name lookup in one pass
        all_items_map = {}
        if results:
            for itm in PharmacyItem.objects.all():
                all_items_map[str(itm.item_id)] = getattr(itm, "item_name", "")

        serialized = PharmacyStockSerializer(results, many=True).data

        for row in serialized:
            iid = str(row.get("item_id", ""))

            # inject item_name
            row["item_name"] = all_items_map.get(iid, f"Item #{iid}")

            # normalise all numeric fields (Decimal128-safe)
            row["mrp"]                      = str(_dec(row.get("mrp",              0)))
            row["Selling_Price"]            = str(_dec(row.get("Selling_Price",    0)))
            row["CGST_Percentage"]          = str(_dec(row.get("CGST_Percentage",  0)))
            row["SGST_Percentage"]          = str(_dec(row.get("SGST_Percentage",  0)))
            row["CGST_Amt"]                 = str(_dec(row.get("CGST_Amt",         0)))
            row["SGST_Amt"]                 = str(_dec(row.get("SGST_Amt",         0)))
            row["total_stock"]              = _int(row.get("total_stock",               0))
            row["sold_quantity"]            = _int(row.get("sold_quantity",              0))
            row["transferred_out_quantity"] = _int(row.get("transferred_out_quantity",  0))
            row["grn_return_quantity"]      = _int(row.get("grn_return_quantity",        0))
            row["blocked_quantity"]         = _int(row.get("blocked_quantity",           0))
            row["sales_return_quantity"]    = _int(row.get("sales_return_quantity",      0))

            # computed available_qty — frontend can use this directly
            row["available_qty"] = (
                row["total_stock"]
                - row["sold_quantity"]
                - row["transferred_out_quantity"]
                - row["grn_return_quantity"]
                - row["blocked_quantity"]
                + row["sales_return_quantity"]
            )

        return Response(serialized)