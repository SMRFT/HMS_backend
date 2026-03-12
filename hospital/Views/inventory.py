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

        all_vendors = Vendor.objects.all().order_by("vendor_id")
        vendors = [v for v in all_vendors if v.is_active]
        serializer = VendorSerializer(vendors, many=True)
        return Response(serializer.data)

    if request.method == "POST":
        serializer = VendorSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(created_by=user_id, lastmodified_by=user_id)
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)

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

        all_Category = PharmacyCategory.objects.all().order_by("category_id")
        Categories = [b for b in all_Category if b.is_active]
        serializer = PharmacyCategorySerializer(Categories, many=True)
        return Response(serializer.data)

    if request.method == "POST":
        serializer = PharmacyCategorySerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(created_by=user_id, lastmodified_by=user_id)
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)

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


#PHARMACY ITEM VIEWS
from ..models import PharmacyItem
from ..serializers import PharmacyItemSerializer

@api_view(["GET", "POST", "PUT", "DELETE"])
@csrf_exempt
def pharmacy_item_view(request, pk=None):

    user_id = request.headers.get("auth-user-id", "system")

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

        all_items = PharmacyItem.objects.all().order_by("item_id")
        items = [i for i in all_items if i.is_active]
        serializer = PharmacyItemSerializer(items, many=True)
        return Response(serializer.data)

    if request.method == "POST":
        serializer = PharmacyItemSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(created_by=user_id, lastmodified_by=user_id)
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)

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


# ─────────────────────────────────────────────────────────────────────────────
# GRN — number generation helpers ONLY
# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
# GRN — number generation helpers ONLY
# ─────────────────────────────────────────────────────────────────────────────
from ..models import GRN
from ..serializers import GRNSerializer

GRN_CATEGORY_PREFIX = {
    "MEDICINE_PURCHASE":    "GRN/OP",
    "MEDICINE_PURCHASE_IP": "GRN/IP",
    "OPENING_STOCK_DRUG":   "GRN/OS",
}

def _current_fin_year():
    today   = datetime.today()
    from_yr = today.year if today.month >= 4 else today.year - 1
    return f"{str(from_yr)[-2:]}{str(from_yr + 1)[-2:]}"

def _next_draft_number():
    """DRAFT/<FINYEAR>/<SEQ5>  e.g.  DRAFT/2526/00001"""
    fin_year = _current_fin_year()
    prefix   = f"DRAFT/{fin_year}/"
    last = (
        GRN.objects
        .filter(draft_number__startswith=prefix)
        .order_by("-draft_number")
        .values_list("draft_number", flat=True)
        .first()
    )
    max_seq = 0
    if last:
        try:
            max_seq = int(last.split("/")[-1])
        except (ValueError, IndexError):
            pass
    return f"{prefix}{str(max_seq + 1).zfill(5)}"

def _grn_number_from_draft(draft_number, purchase_category):
    """
    DRAFT/2526/00001 + MEDICINE_PURCHASE  →  GRN/OP/2526/00001
    """
    try:
        parts    = draft_number.split("/")
        fin_year = parts[1]
        seq      = parts[2]
    except (IndexError, AttributeError):
        fin_year = _current_fin_year()
        seq      = "00001"
    cat_prefix = GRN_CATEGORY_PREFIX.get(purchase_category, "GRN")
    return f"{cat_prefix}/{fin_year}/{seq}"


# ─────────────────────────────────────────────────────────────────────────────
# GRN VIEW — pure Django ORM
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET", "POST", "PUT"])
@csrf_exempt
def grn_view(request, pk=None):
    user_id = request.headers.get("auth-user-id", "system")

    # ── GET ──────────────────────────────────────────────────────────────────
    if request.method == "GET":
        if pk:
            try:
                grn = GRN.objects.get(pk=pk)
            except GRN.DoesNotExist:
                try:
                    grn = GRN.objects.get(draft_number=pk)
                except GRN.DoesNotExist:
                    return Response({"error": "GRN not found"}, status=404)
            return Response(GRNSerializer(grn).data)

        grns = GRN.objects.all().order_by("-created_date")
        return Response(GRNSerializer(grns, many=True).data)

    # ── POST — create new Draft ───────────────────────────────────────────────
    if request.method == "POST":
        data = request.data.copy()

        if isinstance(data.get("items"), (list, dict)):
            data["items"] = json.dumps(data["items"])
        if isinstance(data.get("payment_status"), (list, dict)):
            data["payment_status"] = json.dumps(data["payment_status"])

        data["status"]       = "Draft"
        data["grn_number"]   = ""
        data["draft_number"] = _next_draft_number()

        serializer = GRNSerializer(data=data)
        if serializer.is_valid():
            saved = serializer.save(created_by=user_id, lastmodified_by=user_id)
            return Response(GRNSerializer(saved).data, status=201)
        logger.error("GRN POST errors: %s", serializer.errors)
        return Response(serializer.errors, status=400)

    # ── PUT — update existing GRN via Django ORM ─────────────────────────────
    if request.method == "PUT":
        incoming = request.data.copy()

        if isinstance(incoming.get("items"), (list, dict)):
            incoming["items"] = json.dumps(incoming["items"])
        if isinstance(incoming.get("payment_status"), (list, dict)):
            incoming["payment_status"] = json.dumps(incoming["payment_status"])

        # ── Resolve record ────────────────────────────────────────────────────
        draft_no_in_body = incoming.get("draft_number", "")
        grn = None
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

        # ── Guard ─────────────────────────────────────────────────────────────
        if grn.status == "Verified":
            return Response(
                {"error": "Verified GRN cannot be edited."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # ── Decide status & numbers ───────────────────────────────────────────
        incoming_status = incoming.get("status", grn.status)
        going_verified  = (grn.status == "Draft" and incoming_status == "Verified")

        if going_verified:
            category = incoming.get("purchase_category") or grn.purchase_category or ""
            incoming["grn_number"]   = _grn_number_from_draft(grn.draft_number, category)
            incoming["draft_number"] = grn.draft_number
            incoming["status"]       = "Verified"
        else:
            incoming["grn_number"]   = ""
            incoming["draft_number"] = grn.draft_number
            incoming["status"]       = "Draft"

        # ── Immutable fields ──────────────────────────────────────────────────
        for field in ("created_by", "created_date", "hospital_code"):
            incoming.pop(field, None)

        incoming["lastmodified_by"]   = user_id
        incoming["lastmodified_date"] = datetime.utcnow()

        serializer = GRNSerializer(grn, data=incoming, partial=True)
        if not serializer.is_valid():
            logger.error("GRN PUT errors: %s", serializer.errors)
            return Response(serializer.errors, status=400)

        saved = serializer.save()

        # ── Auto-create PharmacyStock on Draft → Verified ─────────────────────
        if going_verified:
            from ..models import PharmacyStock

            DEPT_CODE_MAP = {
                "MEDICINE_PURCHASE":    "PHARMACY_OP",
                "MEDICINE_PURCHASE_IP": "PHARMACY_IP",
                "OPENING_STOCK_DRUG":   "PHARMACY_OS",
            }
            department_code = DEPT_CODE_MAP.get(saved.purchase_category, "PHARMACY")
            assigned_grn_no = saved.grn_number

            try:
                items = json.loads(saved.items or "[]")
            except (json.JSONDecodeError, TypeError):
                items = []

            stock_errors = []
            for it in items:
                # ── Parse expiry "MM/YYYY" → date field ──────────────────────
                expiry_date = None
                expiry_raw  = it.get("expiry", "")
                if expiry_raw:
                    parts = expiry_raw.split("/")
                    if len(parts) == 2:
                        try:
                            expiry_date = datetime.strptime(
                                f"01/{parts[0]}/{parts[1]}", "%d/%m/%Y"
                            ).date()
                        except ValueError:
                            expiry_date = None

                # ── Tax amounts ───────────────────────────────────────────────
                cgst_pct = float(it.get("cgst_percent", 0) or 0)
                sgst_pct = float(it.get("sgst_percent", 0) or 0)
                item_val = float(it.get("item_value",   0) or 0)
                cgst_amt = round(item_val * (cgst_pct / 100), 2)
                sgst_amt = round(item_val * (sgst_pct / 100), 2)

                try:
                    PharmacyStock.objects.create(
                        department_code          = department_code,
                        item_id                  = int(it.get("item_id") or 0),
                        batch_number             = str(it.get("batch") or ""),
                        expiry_date              = expiry_date,
                        mrp                      = float(it.get("mrp") or 0),
                        grn_number               = assigned_grn_no,
                        total_stock              = int(it.get("quantity") or 0),
                        sold_quantity            = 0,
                        transferred_out_quantity = 0,
                        stock_type               = "grn",
                        stock_id                 = int(it.get("stock_id") or 0),
                        stock_ref_id             = 0,
                        grn_return_quantity      = 0,
                        grn_return_ref_id        = None,
                        blocked_quantity         = 0,
                        sales_return_quantity    = 0,
                        sales_return_ref_id      = None,
                        CGST_Percentage          = cgst_pct,
                        SGST_Percentage          = sgst_pct,
                        CGST_Amt                 = cgst_amt,
                        SGST_Amt                 = sgst_amt,
                    )
                except Exception as e:
                    logger.error("PharmacyStock create failed for item %s: %s", it.get("item_id"), e)
                    stock_errors.append(str(it.get("item_id")))

            if stock_errors:
                logger.warning("Stock creation failed for item_ids: %s", stock_errors)

        return Response(GRNSerializer(saved).data)
    

# ─────────────────────────────────────────────────────────────────────────────
# PHARMACY STOCK VIEWS
# ─────────────────────────────────────────────────────────────────────────────
from ..models import PharmacyStock
from ..serializers import PharmacyStockSerializer

@api_view(["GET", "POST", "PUT", "DELETE"])
@csrf_exempt
def pharmacy_stock_view(request, pk=None):
    """
    PharmacyStock — one record is created per GRN item when status → Verified.

    POST fields (per item):
        department_code, item_id, batch_number, expiry_date (YYYY-MM-DD),
        mrp, grn_number, total_stock,
        CGST_Percentage, SGST_Percentage, CGST_Amt, SGST_Amt
    stock_type defaults to "grn"; all other nullable fields default to 0/null.
    """

    user_id = request.headers.get("auth-user-id", "system")

    if request.method == "GET":
        if pk:
            try:
                stock = PharmacyStock.objects.get(stock_id=pk)
            except PharmacyStock.DoesNotExist:
                return Response({"error": "Stock record not found"}, status=404)
            return Response(PharmacyStockSerializer(stock).data)

        qs = PharmacyStock.objects.all().order_by("-stock_id")
        if grn_number := request.query_params.get("grn_number"):
            qs = qs.filter(grn_number=grn_number)
        if dept := request.query_params.get("department_code"):
            qs = qs.filter(department_code=dept)
        return Response(PharmacyStockSerializer(qs, many=True).data)

    if request.method == "POST":
        data = request.data.copy()
        # ── Apply model-compatible defaults ──────────────────────────────────
        # The PharmacyStock model uses IntegerField(default=0) for counters,
        # NOT null=True.  Frontend sends null for "not yet used" fields;
        # we coerce those to 0 / None where the model allows it.
        def _int(v, fallback=0):
            try: return int(v) if v is not None else fallback
            except (TypeError, ValueError): return fallback

        data["sold_quantity"]              = _int(data.get("sold_quantity"),            0)
        data["transferred_out_quantity"]   = _int(data.get("transferred_out_quantity"), 0)
        data["grn_return_quantity"]        = _int(data.get("grn_return_quantity"),      0)
        data["blocked_quantity"]           = _int(data.get("blocked_quantity"),         0)
        data["sales_return_quantity"]      = _int(data.get("sales_return_quantity"),    0)
        data["stock_ref_id"]               = _int(data.get("stock_ref_id"),             0)
        # Nullable FK-style fields (null=True, blank=True in model)
        data["grn_return_ref_id"]          = data.get("grn_return_ref_id")   or None
        data["sales_return_ref_id"]        = data.get("sales_return_ref_id") or None
        data.setdefault("stock_type",  "grn")
        data.setdefault("CGST_Percentage", 0)
        data.setdefault("SGST_Percentage", 0)
        data.setdefault("CGST_Amt",        0)
        data.setdefault("SGST_Amt",        0)

        serializer = PharmacyStockSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=201)
        logger.error("PharmacyStock POST errors: %s", serializer.errors)
        return Response(serializer.errors, status=400)

    if request.method == "PUT":
        if not pk:
            return Response({"error": "Stock ID required"}, status=400)
        try:
            stock = PharmacyStock.objects.get(stock_id=pk)
        except PharmacyStock.DoesNotExist:
            return Response({"error": "Stock record not found"}, status=404)
        serializer = PharmacyStockSerializer(stock, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)

    if request.method == "DELETE":
        if not pk:
            return Response({"error": "Stock ID required"}, status=400)
        try:
            stock = PharmacyStock.objects.get(stock_id=pk)
        except PharmacyStock.DoesNotExist:
            return Response({"error": "Stock record not found"}, status=404)
        stock.delete()
        return Response({"message": "Deleted successfully"}, status=200)