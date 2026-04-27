from django.shortcuts import render
from rest_framework.response import Response
from django.http import JsonResponse
from rest_framework import status
from pymongo import MongoClient
from django.utils.timezone import now
from rest_framework.parsers import MultiPartParser, FormParser
from bson import Decimal128, ObjectId
from datetime import datetime
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
                lastmodified_by=employee_id,
                lastmodified_date=timezone.now(),
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

GRN_CATEGORY_PREFIX = {
    "MEDICINE_PURCHASE":    "OP",
    "MEDICINE_PURCHASE_IP": "IP",
    "OPENING_STOCK_DRUG":   "DP",
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
                "MEDICINE_PURCHASE":    "OLET002",
                "MEDICINE_PURCHASE_IP": "OLET001",
                "OPENING_STOCK_DRUG":   "",
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
    

def _next_transfer_ref_number():
    """
    Generates the next transfer_ref_number in the pattern YYFINYY/000001.
    e.g.  2627/000001, 2627/000002, …  (resets each financial year)
    """
    from ..models import StockTransfer
 
    fin_year = _current_fin_year()
    prefix   = f"{fin_year}/"
 
    last = (
        StockTransfer.objects
        .filter(transfer_ref_number__startswith=prefix)
        .order_by("-transfer_ref_number")
        .values_list("transfer_ref_number", flat=True)
        .first()
    )
 
    max_seq = 0
    if last:
        try:
            max_seq = int(last.split("/")[-1])
        except (ValueError, IndexError):
            pass
 
    return f"{prefix}{str(max_seq + 1).zfill(6)}"
 
 
# ─────────────────────────────────────────────────────────────────────────────
# STOCK TRANSFER VIEW
# ─────────────────────────────────────────────────────────────────────────────
 
from ..models import StockTransfer
from ..serializers import StockTransferSerializer

@api_view(["GET", "POST", "PUT"])
@csrf_exempt
def stock_transfer_view(request, pk=None):
    """
    GET    /stock-transfer/          → list all transfers (with optional filters)
    GET    /stock-transfer/<pk>/     → retrieve one transfer
    POST   /stock-transfer/          → create new transfer (status = Draft)
    PUT    /stock-transfer/<pk>/     → update a transfer
    """
 
    user_id = request.headers.get("auth-user-id", "system")
 
    # ── GET ───────────────────────────────────────────────────────────────────
    if request.method == "GET":
 
        # ── Single record ─────────────────────────────────────────────────────
        if pk:
            try:
                transfer = StockTransfer.objects.get(transfer_id=pk)
            except StockTransfer.DoesNotExist:
                try:
                    transfer = StockTransfer.objects.get(transfer_ref_number=pk)
                except StockTransfer.DoesNotExist:
                    return Response({"error": "Transfer not found"}, status=404)
            return Response(StockTransferSerializer(transfer).data)
 
        # ── List with optional filters ────────────────────────────────────────
        qs = StockTransfer.objects.all().order_by("-created_date")
 
        from_outlet = request.query_params.get("from_outlet")
        to_outlet   = request.query_params.get("to_outlet")
        from_date   = request.query_params.get("from_date")
        to_date     = request.query_params.get("to_date")
        ref_prefix  = request.query_params.get("ref_prefix")   # used by frontend for seq gen
 
        if from_outlet:
            qs = qs.filter(from_outlet__iexact=from_outlet)
        if to_outlet:
            qs = qs.filter(to_outlet__iexact=to_outlet)
        if from_date:
            qs = qs.filter(created_date__date__gte=from_date)
        if to_date:
            qs = qs.filter(created_date__date__lte=to_date)
        if ref_prefix:
            qs = qs.filter(transfer_ref_number__startswith=f"{ref_prefix}/")
 
        return Response(StockTransferSerializer(qs, many=True).data)
 
    # ── POST — create new Draft ───────────────────────────────────────────────
    if request.method == "POST":
        data = request.data.copy()
 
        # Normalise items to a JSON string
        if isinstance(data.get("items"), (list, dict)):
            data["items"] = json.dumps(data["items"])
 
        # Auto-generate ref number; ignore anything sent by the client
        data["transfer_ref_number"] = _next_transfer_ref_number()
 
        # Always start as Draft
        data["is_verified"] = "Draft"
 
        serializer = StockTransferSerializer(data=data)
        if serializer.is_valid():
            saved = serializer.save(created_by=user_id, lastmodified_by=user_id)
            return Response(StockTransferSerializer(saved).data, status=201)
 
        logger.error("StockTransfer POST errors: %s", serializer.errors)
        return Response(serializer.errors, status=400)
 
    # ── PUT — update existing transfer ────────────────────────────────────────
    if request.method == "PUT":
        if not pk:
            return Response({"error": "Transfer ID required"}, status=400)
 
        # Resolve record by PK or ref number
        transfer = None
        try:
            transfer = StockTransfer.objects.get(transfer_id=pk)
        except (StockTransfer.DoesNotExist, ValueError):
            try:
                transfer = StockTransfer.objects.get(transfer_ref_number=pk)
            except StockTransfer.DoesNotExist:
                pass
 
        if transfer is None:
            return Response({"error": "Transfer not found"}, status=404)
 
        # Guard: Approved transfers are immutable
        if transfer.is_verified == "Approved":
            return Response(
                {"error": "Approved transfers cannot be edited."},
                status=status.HTTP_403_FORBIDDEN,
            )
 
        incoming = request.data.copy()
 
        # Normalise items
        if isinstance(incoming.get("items"), (list, dict)):
            incoming["items"] = json.dumps(incoming["items"])
 
        # Ref number is immutable
        incoming["transfer_ref_number"] = transfer.transfer_ref_number
 
        # Strip immutable audit fields from payload
        for field in ("created_by", "created_date"):
            incoming.pop(field, None)
 
        incoming["lastmodified_by"]   = user_id
        incoming["lastmodified_date"] = datetime.utcnow()
 
        serializer = StockTransferSerializer(transfer, data=incoming, partial=True)
        if not serializer.is_valid():
            logger.error("StockTransfer PUT errors: %s", serializer.errors)
            return Response(serializer.errors, status=400)
 
        saved = serializer.save(lastmodified_by=user_id)
        return Response(StockTransferSerializer(saved).data)
    

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