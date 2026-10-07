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


from .mongo_utils import get_hms_db, paginate_queryset, paginate_mongo_query, clean_doc, clean_docs, ensure_inventory_indexes, apply_date_filter
from pymongo import ASCENDING, DESCENDING
from django.db.models import Q

#VENDOR VIEWS
from ..models import Vendor, GRN, PharmacyStock, StockTransfer, PharmacyBilling, SalesReturn, PurchaseReturn, PharmacyItem
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

        # list with high-performance MongoDB index pagination
        filter_q = {"is_active": True}
        if hospital_code and hospital_code != "system":
            filter_q["hospital_code"] = hospital_code
        if branch_code and branch_code != "system":
            filter_q["branch_code"] = branch_code

        search = str(request.GET.get("search", "") or request.GET.get("q", "")).strip()
        if search:
            regex_q = {"$regex": re.escape(search), "$options": "i"}
            filter_q["$or"] = [
                {"name": regex_q},
                {"vendor_type": regex_q},
                {"city": regex_q},
                {"state": regex_q},
                {"gstin": regex_q},
                {"phone": regex_q},
                {"contact_person": regex_q},
                {"vendor_id": regex_q},
            ]

        vendor_type = str(request.GET.get("vendor_type", "")).strip()
        if vendor_type:
            filter_q["vendor_type"] = vendor_type

        filter_q = apply_date_filter(filter_q, request, "created_date")

        return Response(paginate_mongo_query(
            "hospital_vendor",
            filter_q,
            sort=[("vendor_id", DESCENDING)],
            request=request
        ))

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
        None
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
                if not comp.is_active:
                    return Response({"error": "Composition not found"}, status=404)
                return Response(ChemicalCompositionSerializer(comp).data)

            filter_q = {"is_active": True}
            if hospital_code and hospital_code != "system":
                filter_q["hospital_code"] = hospital_code
            if branch_code and branch_code != "system":
                filter_q["branch_code"] = branch_code

            search = str(request.GET.get("search", "") or request.GET.get("q", "")).strip()
            if search:
                filter_q["composition_name"] = {"$regex": re.escape(search), "$options": "i"}

            filter_q = apply_date_filter(filter_q, request, "created_date")

            return Response(paginate_mongo_query(
                "hospital_chemicalcomposition",
                filter_q,
                sort=[("composition_id", ASCENDING)],
                request=request
            ))

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

            serializer = ChemicalCompositionSerializer(comp, data=request.data, partial=True)
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
        None
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
                if not category.is_active:
                    return Response({"error": "Category not found"}, status=404)
                return Response(PharmacyCategorySerializer(category).data)

            filter_q = {"is_active": True}
            if hospital_code and hospital_code != "system":
                filter_q["hospital_code"] = hospital_code
            if branch_code and branch_code != "system":
                filter_q["branch_code"] = branch_code

            search = str(request.GET.get("search", "") or request.GET.get("q", "")).strip()
            if search:
                filter_q["category_name"] = {"$regex": re.escape(search), "$options": "i"}

            filter_q = apply_date_filter(filter_q, request, "created_date")

            return Response(paginate_mongo_query(
                "hospital_pharmacycategory",
                filter_q,
                sort=[("category_id", ASCENDING)],
                request=request
            ))

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

            serializer = PharmacyCategorySerializer(category, data=request.data, partial=True)
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
        None
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
                if not item.is_active:
                    return Response({"error": "Item not found"}, status=404)
                return Response(PharmacyItemSerializer(item).data)

            filter_q = {"is_active": True}
            if hospital_code and hospital_code != "system":
                filter_q["hospital_code"] = hospital_code
            if branch_code and branch_code != "system":
                filter_q["branch_code"] = branch_code

            search = str(request.GET.get("search", "") or request.GET.get("q", "")).strip()
            if search:
                reg = {"$regex": re.escape(search), "$options": "i"}
                _, db = get_hms_db()

                # Look up matching categories in hospital_pharmacycategory by name
                matched_cats = list(db["hospital_pharmacycategory"].find(
                    {"category_name": reg},
                    {"category_id": 1, "category_name": 1}
                ))
                cat_ids_for_search = []
                for mc in matched_cats:
                    cid = mc.get("category_id")
                    if cid is not None:
                        cat_ids_for_search.append(str(cid).strip())
                        if str(cid).strip().isdigit():
                            cat_ids_for_search.append(int(str(cid).strip()))
                    if mc.get("category_name"):
                        cat_ids_for_search.append(mc.get("category_name"))

                # Look up matching compositions in hospital_chemicalcomposition by name
                matched_comps = list(db["hospital_chemicalcomposition"].find(
                    {"composition_name": reg},
                    {"composition_id": 1, "composition_name": 1}
                ))
                comp_ids_for_search = []
                for mcp in matched_comps:
                    cpid = mcp.get("composition_id")
                    if cpid is not None:
                        comp_ids_for_search.append(str(cpid).strip())
                        if str(cpid).strip().isdigit():
                            comp_ids_for_search.append(int(str(cpid).strip()))
                    if mcp.get("composition_name"):
                        comp_ids_for_search.append(mcp.get("composition_name"))

                or_clauses = [
                    {"item_name": reg},
                    {"item_last_name": reg},
                    {"brand_name": reg},
                    {"chemical_composition": reg},
                    {"category": reg},
                    {"hsn": reg}
                ]
                if cat_ids_for_search:
                    or_clauses.append({"category": {"$in": list(set(cat_ids_for_search))}})
                if comp_ids_for_search:
                    or_clauses.append({"chemical_composition": {"$in": list(set(comp_ids_for_search))}})

                filter_q["$or"] = or_clauses

            category_param = str(request.GET.get("category", "")).strip()
            if category_param:
                cat_match_values = [category_param]
                if category_param.isdigit():
                    cat_match_values.append(int(category_param))
                _, db = get_hms_db()
                matched_cats = list(db["hospital_pharmacycategory"].find({
                    "$or": [
                        {"category_id": int(category_param) if category_param.isdigit() else category_param},
                        {"category_id": category_param},
                        {"category_name": {"$regex": f"^{re.escape(category_param)}$", "$options": "i"}}
                    ]
                }))
                for mc in matched_cats:
                    cid = mc.get("category_id")
                    cname = mc.get("category_name")
                    if cid is not None:
                        cat_match_values.append(str(cid).strip())
                        if str(cid).strip().isdigit():
                            cat_match_values.append(int(str(cid).strip()))
                    if cname:
                        cat_match_values.append(cname)
                filter_q["category"] = {"$in": list(set(cat_match_values))}

            def _enrich_pharmacy_items(docs):
                if not docs:
                    return docs
                client, db = get_hms_db()

                cat_ids = set()
                for it in docs:
                    c = it.get("category")
                    if c is not None and str(c).strip():
                        s = str(c).strip()
                        if s.isdigit():
                            cat_ids.add(int(s))
                        cat_ids.add(s)

                comp_ids = set()
                for it in docs:
                    comp = it.get("chemical_composition")
                    if comp is not None and str(comp).strip():
                        s = str(comp).strip()
                        if s.isdigit():
                            comp_ids.add(int(s))
                        comp_ids.add(s)

                cat_map = {}
                if cat_ids:
                    cat_docs = list(db["hospital_pharmacycategory"].find({
                        "$or": [
                            {"category_id": {"$in": list(cat_ids)}},
                            {"category_id": {"$in": [str(x) for x in cat_ids]}}
                        ]
                    }))
                    for c in cat_docs:
                        cid = str(c.get("category_id", "")).strip()
                        cname = c.get("category_name", "")
                        if cid:
                            cat_map[cid] = cname
                        if cname:
                            cat_map[cname.lower()] = cname

                comp_map = {}
                if comp_ids:
                    comp_docs = list(db["hospital_chemicalcomposition"].find({
                        "$or": [
                            {"composition_id": {"$in": list(comp_ids)}},
                            {"composition_id": {"$in": [str(x) for x in comp_ids]}}
                        ]
                    }))
                    for c in comp_docs:
                        cid = str(c.get("composition_id", "")).strip()
                        cname = c.get("composition_name", "")
                        if cid:
                            comp_map[cid] = cname
                        if cname:
                            comp_map[cname.lower()] = cname

                for it in docs:
                    c_val = str(it.get("category") or "").strip()
                    it["category_name"] = cat_map.get(c_val) or cat_map.get(c_val.lower()) or c_val

                    comp_val = str(it.get("chemical_composition") or "").strip()
                    it["chemical_composition_name"] = comp_map.get(comp_val) or comp_map.get(comp_val.lower()) or comp_val

                return docs

            return Response(paginate_mongo_query(
                "hospital_pharmacyitem",
                filter_q,
                sort=[("item_id", ASCENDING)],
                enrich_fn=_enrich_pharmacy_items,
                request=request
            ))

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
    """DRAFT/<FINYEAR>/<SEQ5> using high-speed indexed Mongo query"""
    fin_year = _current_fin_year()
    prefix = f"DRAFT/{fin_year}/"

    client, hms_db = get_hms_db()
    top_doc = list(hms_db["hospital_grn"].find(
        {"draft_number": {"$regex": f"^{prefix}"}},
        {"draft_number": 1}
    ).sort("draft_number", DESCENDING).limit(1))

    max_seq = 0
    if top_doc:
        d_val = top_doc[0].get("draft_number", "")
        try:
            max_seq = int(d_val.split("/")[-1])
        except (ValueError, IndexError):
            pass

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
# GRN VIEW — HIGH PERFORMANCE + PAGINATION + HOSPITAL/BRANCH FILTER
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

                return Response(GRNSerializer(grn).data)

            filter_q = {}
            if hospital_code and hospital_code != "system":
                filter_q["hospital_code"] = hospital_code
            if branch_code and branch_code != "system":
                filter_q["branch_code"] = branch_code

            search = str(request.GET.get("search", "") or request.GET.get("q", "")).strip()
            if search:
                reg = {"$regex": re.escape(search), "$options": "i"}
                filter_q["$or"] = [
                    {"draft_number": reg},
                    {"grn_number": reg},
                    {"invoice_no": reg},
                    {"vendor_name": reg},
                    {"purchase_category": reg},
                    {"status": reg}
                ]

            status_f = str(request.GET.get("status", "")).strip()
            if status_f:
                filter_q["status"] = status_f

            filter_q = apply_date_filter(filter_q, request, "created_date")

            def _enrich_grn_items(data_list):
                for r in data_list:
                    if isinstance(r.get("items"), str):
                        try:
                            r["items"] = json.loads(r["items"])
                        except Exception:
                            pass
                return data_list

            return Response(paginate_mongo_query(
                "hospital_grn",
                filter_q,
                sort=[("created_date", DESCENDING)],
                request=request,
                enrich_fn=_enrich_grn_items
            ))

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

        # ───────── Indexed PyMongo fetch ─────────
        client, hms_db = get_hms_db()
        filter_q = {"item_id": int(item_id) if item_id.isdigit() else item_id}
        if hospital_code and hospital_code != "system":
            filter_q["hospital_code"] = hospital_code
        if branch_code and branch_code != "system":
            filter_q["branch_code"] = branch_code

        cursor = hms_db["hospital_pharmacystock"].find(filter_q).sort("created_date", DESCENDING).limit(100)
        stocks = list(cursor)

        # ───────── Build Response ─────────
        result = []
        for stock in stocks:
            result.append({
                "stock_id": stock.get("stock_id", ""),
                "item_id": stock.get("item_id", ""),
                "item_name": stock.get("item_name", ""),
                "batch": stock.get("batch_number", ""),
                "expiry": str(stock.get("expiry_date", "") or ""),
                "packing_price": str(stock.get("packing_price", 0)),
                "purchase_cost": str(stock.get("purchase_cost", 0)),
                "mrp": str(stock.get("mrp", 0)),
                "CGST_Amt": str(stock.get("CGST_Amt", 0)),
                "SGST_Amt": str(stock.get("SGST_Amt", 0)),
                "quantity": str(stock.get("total_stock", 0)),
                "vendor_id": stock.get("vendor_id", ""),
                "invoice_no": stock.get("invoice_no", ""),
                "grn_number": stock.get("grn_number", ""),
                "hospital_code": stock.get("hospital_code", ""),
                "branch_code": stock.get("branch_code", ""),
                "created_date": stock.get("created_date", None),
            })

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
# @permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def medicine_tracking(request):
    try:
        item_id   = str(request.GET.get("item_id", "")).strip()
        item_name = str(request.GET.get("item_name", "")).strip().lower()
        requested_outlet = str(request.GET.get("outlet_code", "")).strip()

        hospital_code = (
            request.GET.get("auth-hospital-code")
            or request.headers.get("auth-hospital-code")
            or None
        )
        branch_code = (
            request.GET.get("auth-branch-code")
            or request.headers.get("Branch-Code")
            or None
        )

        if not item_id and not item_name:
            return Response({
                "success": False,
                "error": "item_id or item_name is required"
            }, status=400)

        _, db = get_hms_db()

        # Outlet map lookup
        outlet_map = {
            "OLET001": "IP Pharmacy",
            "OLET002": "OP Pharmacy",
            "OLET003": "Main Store / Procurement",
        }
        try:
            for o in db.hospital_outlet.find({}, {"outlet_code": 1, "outlet_name": 1, "_id": 0}):
                if o.get("outlet_code") and o.get("outlet_name"):
                    outlet_map[o["outlet_code"]] = o["outlet_name"]
        except Exception:
            pass

        item_doc = None
        if item_id:
            try:
                item_doc = db.hospital_pharmacyitem.find_one({"item_id": int(item_id)}, {"item_id": 1, "item_name": 1})
            except Exception:
                pass
            if not item_doc:
                item_doc = db.hospital_pharmacyitem.find_one({"item_id": item_id}, {"item_id": 1, "item_name": 1})

        if not item_doc and item_name:
            item_doc = db.hospital_pharmacyitem.find_one(
                {"item_name": {"$regex": f"^{re.escape(item_name)}$", "$options": "i"}},
                {"item_id": 1, "item_name": 1}
            )
            if not item_doc:
                item_doc = db.hospital_pharmacyitem.find_one(
                    {"item_name": {"$regex": re.escape(item_name), "$options": "i"}},
                    {"item_id": 1, "item_name": 1}
                )

        if item_doc:
            item_id = str(item_doc.get("item_id", ""))
            item_name = str(item_doc.get("item_name", "")).lower()
            item_name_display = item_doc.get("item_name", "")
        else:
            item_name_display = item_name

        if not item_id and not item_name:
            return Response({
                "success": False,
                "error": "Medicine not found"
            }, status=404)

        def _dt(v):
            if isinstance(v, datetime):
                return v.isoformat()
            return str(v) if v else None

        def _dec(v):
            try:
                return str(Decimal(str(v)))
            except Exception:
                return "0"

        def _item_matches(it):
            if not isinstance(it, dict):
                return False
            iid = str(it.get("item_id", "")).strip()
            iname = str(it.get("medicine_name") or it.get("item_name") or it.get("particulars") or it.get("product_name") or "").strip().lower()
            if item_id and iid == str(item_id):
                return True
            if item_name and (item_name in iname or iname in item_name):
                return True
            return False

        timeline = []

        # ── 1. Pharmacy Stock (Current Batches & Availability) ──────────────
        stock_or = []
        if item_id:
            if str(item_id).isdigit():
                stock_or.append({"item_id": int(item_id)})
            stock_or.append({"item_id": str(item_id)})
        
        stock_filter = {"$or": stock_or} if stock_or else {}
        if hospital_code and hospital_code != "system":
            stock_filter["hospital_code"] = hospital_code
        if branch_code and branch_code != "system":
            stock_filter["branch_code"] = branch_code

        stock_docs = list(db.hospital_pharmacystock.find(stock_filter, {
            "stock_id": 1, "item_id": 1, "batch_number": 1, "expiry_date": 1,
            "total_stock": 1, "sold_quantity": 1, "transferred_out_quantity": 1,
            "grn_return_quantity": 1, "blocked_quantity": 1, "sales_return_quantity": 1,
            "outlet_code": 1, "_id": 0
        }))

        stock_op = Decimal("0")
        stock_ip = Decimal("0")
        stock_main = Decimal("0")
        stock_total = Decimal("0")
        stock_batches = []

        for s in stock_docs:
            tot = Decimal(str(s.get("total_stock") or 0))
            sold = Decimal(str(s.get("sold_quantity") or 0))
            trans = Decimal(str(s.get("transferred_out_quantity") or 0))
            grn_ret = Decimal(str(s.get("grn_return_quantity") or 0))
            blk = Decimal(str(s.get("blocked_quantity") or 0))
            s_ret = Decimal(str(s.get("sales_return_quantity") or 0))
            avail = tot - sold - trans - grn_ret - blk + s_ret

            s_outlet = str(s.get("outlet_code") or "").strip()
            if s_outlet == "OLET002":
                stock_op += avail
            elif s_outlet == "OLET001":
                stock_ip += avail
            else:
                stock_main += avail
            stock_total += avail

            exp = s.get("expiry_date")
            exp_str = exp.strftime("%d-%m-%Y") if hasattr(exp, "strftime") else str(exp)[:10] if exp else "-"
            stock_batches.append({
                "batch_number": s.get("batch_number") or "-",
                "expiry_date": exp_str,
                "outlet_code": s_outlet,
                "outlet_name": outlet_map.get(s_outlet, s_outlet or "Main Store"),
                "available": str(avail),
                "total_stock": str(tot)
            })

        # ── 2. GRN movements (Procurement) ─────────────────────────────────
        grn_q = {}
        if hospital_code and hospital_code != "system":
            grn_q["hospital_code"] = hospital_code
        if branch_code and branch_code != "system":
            grn_q["branch_code"] = branch_code

        # If user explicitly wants single outlet alone (e.g. OLET001 / OLET002), filter if specified
        if requested_outlet in ("OLET001", "OLET002"):
            grn_q["outlet_code"] = requested_outlet

        grn_search_or = []
        if item_id:
            if str(item_id).isdigit():
                grn_search_or.append({"items.item_id": int(item_id)})
            grn_search_or.append({"items.item_id": str(item_id)})
            grn_search_or.append({"items": {"$regex": f'"item_id":\\s*"?{re.escape(str(item_id))}"?'}})
            grn_search_or.append({"items": {"$regex": f"'item_id':\\s*'?{re.escape(str(item_id))}'?"}})
        if item_name:
            grn_search_or.append({"items.medicine_name": {"$regex": re.escape(item_name), "$options": "i"}})
            grn_search_or.append({"items.item_name": {"$regex": re.escape(item_name), "$options": "i"}})
            grn_search_or.append({"items": {"$regex": re.escape(item_name), "$options": "i"}})
        if grn_search_or:
            grn_q["$or"] = grn_search_or

        grn_docs = list(db.hospital_grn.find(grn_q, {
            "date": 1, "created_date": 1, "grn_number": 1, "draft_number": 1,
            "invoice_no": 1, "invoice_date": 1, "vendor_id": 1, "vendor_name": 1,
            "outlet_code": 1, "purchase_category": 1, "status": 1, "items": 1
        }).sort("created_date", -1).limit(1000))

        for g in grn_docs:
            raw_items = g.get("items", [])
            if isinstance(raw_items, str):
                try:
                    raw_items = json.loads(raw_items)
                except Exception:
                    try:
                        raw_items = ast.literal_eval(raw_items)
                    except Exception:
                        raw_items = []
            if not isinstance(raw_items, list):
                continue

            for it in raw_items:
                if _item_matches(it):
                    batch_no = it.get("batch_number", "") or ""
                    qty = _dec(it.get("quantity", 0) or 0)
                    g_outlet = g.get("outlet_code", "") or "OLET003"
                    timeline.append({
                        "type": "PURCHASE",
                        "date": _dt(g.get("date") or g.get("created_date")),
                        "ref_no": g.get("grn_number", "") or g.get("draft_number", ""),
                        "bill_ref": g.get("invoice_no", ""),
                        "bill_date": _dt(g.get("invoice_date")),
                        "vendor_id": g.get("vendor_id", ""),
                        "vendor_name": it.get("vendor_name", "") or g.get("vendor_name", "") or "",
                        "outlet_code": g_outlet,
                        "outlet_name": outlet_map.get(g_outlet, "Main Store"),
                        "batch_no": batch_no,
                        "quantity": qty,
                        "status": g.get("status", ""),
                        "details": f"Procured via GRN — {g.get('purchase_category', '') or 'Purchase'}"
                    })

        # ── 3. Stock Transfer movements ────────────────────────────────────
        tf_q = {}
        if hospital_code and hospital_code != "system":
            tf_q["hospital_code"] = hospital_code
        if branch_code and branch_code != "system":
            tf_q["branch_code"] = branch_code

        if requested_outlet in ("OLET001", "OLET002"):
            tf_q["$or"] = [{"to_outlet": requested_outlet}, {"from_outlet": requested_outlet}, {"outlet_code": requested_outlet}]

        tf_search_or = []
        if item_id:
            if str(item_id).isdigit():
                tf_search_or.append({"items.item_id": int(item_id)})
            tf_search_or.append({"items.item_id": str(item_id)})
            tf_search_or.append({"items": {"$regex": f'"item_id":\\s*"?{re.escape(str(item_id))}"?'}})
            tf_search_or.append({"items": {"$regex": f"'item_id':\\s*'?{re.escape(str(item_id))}'?"}})
        if item_name:
            tf_search_or.append({"items.medicine_name": {"$regex": re.escape(item_name), "$options": "i"}})
            tf_search_or.append({"items.item_name": {"$regex": re.escape(item_name), "$options": "i"}})
            tf_search_or.append({"items": {"$regex": re.escape(item_name), "$options": "i"}})
        if tf_search_or:
            if "$or" in tf_q:
                tf_q["$and"] = [{"$or": tf_q.pop("$or")}, {"$or": tf_search_or}]
            else:
                tf_q["$or"] = tf_search_or

        tf_docs = list(db.hospital_stocktransfer.find(tf_q, {
            "created_date": 1, "transfer_ref_number": 1, "outlet_code": 1,
            "from_outlet": 1, "to_outlet": 1, "is_verified": 1, "approved_by": 1,
            "approved_date": 1, "items": 1
        }).sort("created_date", -1).limit(1000))

        transferred_in = Decimal("0")
        transferred_out = Decimal("0")

        for t in tf_docs:
            to_out = t.get("to_outlet", "") or ""
            from_out = t.get("from_outlet", "") or t.get("outlet_code", "") or "Main Store"
            raw_items = t.get("items", [])
            if isinstance(raw_items, str):
                try:
                    raw_items = json.loads(raw_items)
                except Exception:
                    try:
                        raw_items = ast.literal_eval(raw_items)
                    except Exception:
                        raw_items = []
            if not isinstance(raw_items, list):
                continue

            for it in raw_items:
                if _item_matches(it):
                    batch_no = it.get("batch_number", "") or ""
                    qty = _dec(it.get("quantity", 0) or it.get("transfer_quantity", 0) or it.get("transferred_out_quantity", 0) or 0)
                    qty_dec = Decimal(str(qty))
                    
                    # Determine movement direction relative to requested outlet or general
                    if requested_outlet == "OLET001":
                        direction = "IN" if to_out == "OLET001" else "OUT"
                    elif requested_outlet == "OLET002":
                        direction = "IN" if to_out == "OLET002" else "OUT"
                    else:
                        direction = "TRANSFER"

                    if direction == "IN":
                        transferred_in += qty_dec
                    elif direction == "OUT":
                        transferred_out += qty_dec
                    else:
                        transferred_in += qty_dec

                    from_name = outlet_map.get(from_out, from_out or "Main Store")
                    to_name = outlet_map.get(to_out, to_out or "Pharmacy")
                    movement_desc = f"Stock Transfer — From: {from_name} → To: {to_name}"

                    timeline.append({
                        "type": f"STOCK_TRANSFER_{direction}",
                        "date": _dt(t.get("created_date")),
                        "ref_no": t.get("transfer_ref_number", ""),
                        "from_outlet": from_out,
                        "from_outlet_name": from_name,
                        "to_outlet": to_out,
                        "to_outlet_name": to_name,
                        "outlet_code": to_out or from_out,
                        "outlet_name": to_name,
                        "batch_no": batch_no,
                        "quantity": qty,
                        "status": t.get("is_verified", ""),
                        "details": movement_desc,
                        "approved_by": t.get("approved_by", ""),
                        "approved_date": _dt(t.get("approved_date")),
                    })

        # ── 4. Pharmacy Billing (Sales in OP / IP) ─────────────────────────
        bill_q = {}
        if hospital_code and hospital_code != "system":
            bill_q["hospital_code"] = hospital_code
        if branch_code and branch_code != "system":
            bill_q["branch_code"] = branch_code
        if requested_outlet in ("OLET001", "OLET002"):
            bill_q["outlet_code"] = requested_outlet

        bill_search_or = []
        if item_id:
            if str(item_id).isdigit():
                bill_search_or.append({"medicine_particulars.item_id": int(item_id)})
            bill_search_or.append({"medicine_particulars.item_id": str(item_id)})
            bill_search_or.append({"medicine_particulars": {"$regex": f'"item_id":\\s*"?{re.escape(str(item_id))}"?'}})
            bill_search_or.append({"medicine_particulars": {"$regex": f"'item_id':\\s*'?{re.escape(str(item_id))}'?"}})
        if item_name:
            bill_search_or.append({"medicine_particulars.item_name": {"$regex": re.escape(item_name), "$options": "i"}})
            bill_search_or.append({"medicine_particulars.particulars": {"$regex": re.escape(item_name), "$options": "i"}})
            bill_search_or.append({"medicine_particulars.medicine_name": {"$regex": re.escape(item_name), "$options": "i"}})
            bill_search_or.append({"medicine_particulars": {"$regex": re.escape(item_name), "$options": "i"}})
        if bill_search_or:
            bill_q["$or"] = bill_search_or

        bill_docs = list(db.hospital_pharmacybilling.find(bill_q, {
            "bill_date": 1, "created_date": 1, "bill_no": 1, "Bill_id": 1,
            "uhid": 1, "outlet_code": 1, "billing_status": 1, "medicine_particulars": 1
        }).sort("created_date", -1).limit(1000))

        sold_op = Decimal("0")
        sold_ip = Decimal("0")
        sold_total = Decimal("0")

        for b in bill_docs:
            meds = b.get("medicine_particulars", []) or []
            if isinstance(meds, str):
                try:
                    meds = json.loads(meds)
                except Exception:
                    try:
                        meds = ast.literal_eval(meds)
                    except Exception:
                        meds = []
            if not isinstance(meds, list):
                continue

            b_outlet = str(b.get("outlet_code") or "").strip()
            for m in meds:
                if _item_matches(m):
                    batch_no = m.get("batch_number", "") or ""
                    qty = _dec(m.get("quantity", 0) or 0)
                    qty_dec = Decimal(str(qty))

                    if b_outlet == "OLET002":
                        sold_op += qty_dec
                    elif b_outlet == "OLET001":
                        sold_ip += qty_dec
                    sold_total += qty_dec

                    out_label = outlet_map.get(b_outlet, "OP Pharmacy" if b_outlet == "OLET002" else ("IP Pharmacy" if b_outlet == "OLET001" else b_outlet or "Pharmacy"))

                    timeline.append({
                        "type": "SALE",
                        "date": _dt(b.get("bill_date") or b.get("created_date")),
                        "ref_no": b.get("bill_no", "") or str(b.get("Bill_id", "")),
                        "uhid": b.get("uhid", ""),
                        "patient_name": m.get("patient_name", "") or "",
                        "outlet_code": b_outlet,
                        "outlet_name": out_label,
                        "batch_no": batch_no,
                        "quantity": qty,
                        "status": b.get("billing_status", ""),
                        "details": f"Sold via Pharmacy Bill ({out_label}) — {b.get('billing_status', '')}"
                    })

        # ── 5. Sales Return movements ───────────────────────────────────────
        sr_q = {}
        if hospital_code and hospital_code != "system":
            sr_q["hospital_code"] = hospital_code
        if branch_code and branch_code != "system":
            sr_q["branch_code"] = branch_code
        if requested_outlet in ("OLET001", "OLET002"):
            sr_q["outlet_code"] = requested_outlet

        sr_search_or = []
        if item_id:
            if str(item_id).isdigit():
                sr_search_or.append({"medicine_particulars.item_id": int(item_id)})
            sr_search_or.append({"medicine_particulars.item_id": str(item_id)})
            sr_search_or.append({"medicine_particulars": {"$regex": f'"item_id":\\s*"?{re.escape(str(item_id))}"?'}})
            sr_search_or.append({"medicine_particulars": {"$regex": f"'item_id':\\s*'?{re.escape(str(item_id))}'?"}})
        if item_name:
            sr_search_or.append({"medicine_particulars.item_name": {"$regex": re.escape(item_name), "$options": "i"}})
            sr_search_or.append({"medicine_particulars.particulars": {"$regex": re.escape(item_name), "$options": "i"}})
            sr_search_or.append({"medicine_particulars.medicine_name": {"$regex": re.escape(item_name), "$options": "i"}})
            sr_search_or.append({"medicine_particulars": {"$regex": re.escape(item_name), "$options": "i"}})
        if sr_search_or:
            sr_q["$or"] = sr_search_or

        sr_docs = list(db.hospital_salesreturn.find(sr_q, {
            "return_bill_date": 1, "created_date": 1, "return_bill_no": 1,
            "bill_no": 1, "uhid": 1, "outlet_code": 1, "medicine_particulars": 1
        }).sort("created_date", -1).limit(1000))

        returned_from_sale = Decimal("0")
        for sr in sr_docs:
            meds = sr.get("medicine_particulars", []) or []
            if isinstance(meds, str):
                try:
                    meds = json.loads(meds)
                except Exception:
                    try:
                        meds = ast.literal_eval(meds)
                    except Exception:
                        meds = []
            if not isinstance(meds, list):
                continue

            sr_out = str(sr.get("outlet_code") or "").strip()
            for m in meds:
                if _item_matches(m):
                    batch_no = m.get("batch_number", "") or ""
                    qty = _dec(m.get("quantity", 0) or 0)
                    returned_from_sale += Decimal(str(qty))
                    sr_out_name = outlet_map.get(sr_out, "OP Pharmacy" if sr_out == "OLET002" else ("IP Pharmacy" if sr_out == "OLET001" else sr_out or "Pharmacy"))
                    timeline.append({
                        "type": "SALES_RETURN",
                        "date": _dt(sr.get("return_bill_date") or sr.get("created_date")),
                        "ref_no": sr.get("return_bill_no", ""),
                        "bill_no": sr.get("bill_no", ""),
                        "uhid": sr.get("uhid", ""),
                        "outlet_code": sr_out,
                        "outlet_name": sr_out_name,
                        "batch_no": batch_no,
                        "quantity": qty,
                        "details": f"Sales Return — returned by patient/customer ({sr_out_name})"
                    })

        # ── 6. Purchase Return movements ───────────────────────────────────
        pr_q = {}
        if hospital_code and hospital_code != "system":
            pr_q["hospital_code"] = hospital_code
        if branch_code and branch_code != "system":
            pr_q["branch_code"] = branch_code
        if requested_outlet in ("OLET001", "OLET002"):
            pr_q["outlet_code"] = requested_outlet

        pr_search_or = []
        if item_id:
            if str(item_id).isdigit():
                pr_search_or.append({"items.item_id": int(item_id)})
            pr_search_or.append({"items.item_id": str(item_id)})
            pr_search_or.append({"items": {"$regex": f'"item_id":\\s*"?{re.escape(str(item_id))}"?'}})
            pr_search_or.append({"items": {"$regex": f"'item_id':\\s*'?{re.escape(str(item_id))}'?"}})
        if item_name:
            pr_search_or.append({"items.medicine_name": {"$regex": re.escape(item_name), "$options": "i"}})
            pr_search_or.append({"items.item_name": {"$regex": re.escape(item_name), "$options": "i"}})
            pr_search_or.append({"items": {"$regex": re.escape(item_name), "$options": "i"}})
        if pr_search_or:
            pr_q["$or"] = pr_search_or

        pr_docs = list(db.hospital_purchasereturn.find(pr_q, {
            "purchase_return_bill_date": 1, "created_date": 1, "purchase_return_bill_no": 1,
            "grn_number": 1, "vendor_code": 1, "vendor_name": 1, "outlet_code": 1,
            "status": 1, "return_remark": 1, "items": 1
        }).sort("created_date", -1).limit(1000))

        returned_to_vendor = Decimal("0")
        for pr in pr_docs:
            raw_items = pr.get("items", [])
            if isinstance(raw_items, str):
                try:
                    raw_items = json.loads(raw_items)
                except Exception:
                    try:
                        raw_items = ast.literal_eval(raw_items)
                    except Exception:
                        raw_items = []
            if not isinstance(raw_items, list):
                continue

            for it in raw_items:
                if _item_matches(it):
                    batch_no = it.get("batch_number", "") or ""
                    qty = _dec(it.get("return_qty", 0) or 0)
                    returned_to_vendor += Decimal(str(qty))
                    pr_out = pr.get("outlet_code", "")
                    timeline.append({
                        "type": "PURCHASE_RETURN",
                        "date": _dt(pr.get("purchase_return_bill_date") or pr.get("created_date")),
                        "ref_no": pr.get("purchase_return_bill_no", ""),
                        "grn_number": pr.get("grn_number", ""),
                        "vendor_code": pr.get("vendor_code", ""),
                        "vendor_name": pr.get("vendor_name", ""),
                        "outlet_code": pr_out,
                        "outlet_name": outlet_map.get(pr_out, "Main Store"),
                        "batch_no": batch_no,
                        "quantity": qty,
                        "status": pr.get("status", ""),
                        "details": f"Purchase Return — {pr.get('return_remark', '') or 'Returned to vendor'}"
                    })

        # Sort timeline by date descending
        def _sort_key(x):
            d = x.get("date") or ""
            return str(d)

        timeline.sort(key=_sort_key, reverse=True)

        purchased = sum(Decimal(t["quantity"]) for t in timeline if t["type"] == "PURCHASE")
        transferred_total = sum(Decimal(t["quantity"]) for t in timeline if "STOCK_TRANSFER" in t["type"])

        # Outlet-aware current stock & sold values
        if requested_outlet == "OLET001":
            effective_current_stock = stock_ip
            effective_sold = sold_ip
        elif requested_outlet == "OLET002":
            effective_current_stock = stock_op
            effective_sold = sold_op
        else:
            effective_current_stock = stock_total
            effective_sold = sold_total

        return Response({
            "success": True,
            "item_id": item_id,
            "item_name": item_name_display,
            "outlet_code": requested_outlet or "ALL",
            "outlet_name": outlet_map.get(requested_outlet, "All Outlets (Combined)"),
            "summary": {
                "purchased": str(purchased),
                "sold": str(effective_sold),
                "sold_op": str(sold_op),
                "sold_ip": str(sold_ip),
                "sold_total": str(sold_total),
                "sales_return": str(returned_from_sale),
                "purchase_return": str(returned_to_vendor),
                "stock_transfer_in": str(transferred_in),
                "stock_transfer_out": str(transferred_out),
                "stock_transfer": str(transferred_total),
                "current_stock": str(effective_current_stock),
                "current_stock_op": str(stock_op),
                "current_stock_ip": str(stock_ip),
                "current_stock_main": str(stock_main),
                "current_stock_total": str(stock_total),
            },
            "batches": stock_batches,
            "count": len(timeline),
            "data": timeline
        })

    except Exception as e:
        logger.error("[medicine_tracking] %s", e, exc_info=True)
        return Response({
            "success": False,
            "error": str(e)
        }, status=500)



@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_pharmacy_item_tracking(request):
    try:
        item_id = request.GET.get("item_id")
        if not item_id:
            return Response({"success": False, "error": "item_id is required"}, status=400)

        _, db = get_hms_db()

        # Support both int and str item_id
        item_filter = []
        if str(item_id).isdigit():
            item_filter.append({"item_id": int(item_id)})
        item_filter.append({"item_id": str(item_id)})

        stock_docs = list(db["hospital_pharmacystock"].find(
            {"$or": item_filter},
            {
                "batch_number": 1,
                "expiry_date": 1,
                "grn_number": 1,
                "total_stock": 1,
                "sold_quantity": 1,
                "transferred_out_quantity": 1,
                "grn_return_quantity": 1,
                "blocked_quantity": 1,
                "sales_return_quantity": 1,
                "_id": 0,
            }
        ))

        # Batch lookup GRN dates in one single query
        grn_numbers = list({s.get("grn_number") for s in stock_docs if s.get("grn_number")})
        grn_map = {}
        if grn_numbers:
            for g in db["hospital_grn"].find({"grn_number": {"$in": grn_numbers}}, {"grn_number": 1, "date": 1, "_id": 0}):
                g_date = g.get("date")
                if g_date:
                    grn_map[g.get("grn_number")] = g_date.strftime("%d-%m-%Y") if hasattr(g_date, "strftime") else str(g_date)[:10]

        batches = []
        total_stock = 0

        for s in stock_docs:
            tot = float(s.get("total_stock") or 0)
            sold = float(s.get("sold_quantity") or 0)
            trans_out = float(s.get("transferred_out_quantity") or 0)
            grn_ret = float(s.get("grn_return_quantity") or 0)
            blocked = float(s.get("blocked_quantity") or 0)
            sales_ret = float(s.get("sales_return_quantity") or 0)

            available_qty = tot - sold - trans_out - grn_ret - blocked + sales_ret
            total_stock += available_qty

            exp = s.get("expiry_date")
            expiry = "-"
            if exp:
                expiry = exp.strftime("%d-%m-%Y") if hasattr(exp, "strftime") else str(exp)[:10]

            grn_num = s.get("grn_number")

            batches.append({
                "batch_number": s.get("batch_number") or "-",
                "expiry_date": expiry,
                "grn_number": grn_num or "-",
                "procured_date": grn_map.get(grn_num, "-"),
                "current_stock": available_qty,
                "total_stock": tot,
            })

        return Response({
            "success": True,
            "total_stock": total_stock,
            "times_procured": len(stock_docs),
            "batches": batches,
        })
    except Exception as e:
        logger.error("[get_pharmacy_item_tracking] %s", e, exc_info=True)
        return Response({"success": False, "error": str(e)}, status=500)


