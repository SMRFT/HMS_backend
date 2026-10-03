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
from rest_framework.decorators import api_view, permission_classes, parser_classes
from django.views.decorators.csrf import csrf_exempt

# Auth/permissions
from pyauth.auth import HasRoleAndDataPermission

# Logger setup
logger = logging.getLogger(__name__)

from ..models import PharmacyStock, StockTransfer, PharmacyItem
from ..serializers import StockTransferSerializer, PharmacyStockSerializer


# ─────────────────────────────────────────────────────────────────────────────
# SAFE HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _dec(value, default="0.00"):
    """
    Safely convert any value coming out of a Djongo/MongoDB query to Decimal.
    Handles bson.Decimal128, {"$numberDecimal": "x"}, plain strings, int/float, None.
    """
    try:
        if value in (None, "", "None"):
            return Decimal(default)
        if hasattr(value, "to_decimal"):
            return value.to_decimal()
        if isinstance(value, dict) and "$numberDecimal" in value:
            return Decimal(str(value["$numberDecimal"]))
        cleaned = (
            str(value).strip()
            .replace("\u201c", "").replace("\u201d", "")
            .replace('"', "").replace("'", "").replace(",", "")
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

from .mongo_utils import get_hms_db, paginate_queryset, paginate_mongo_query, clean_doc, clean_docs, apply_date_filter
from pymongo import ASCENDING, DESCENDING
from django.db.models import Q


# ─── Financial year + ref-number ─────────────────────────────────────────────

def _current_fin_year():
    today = datetime.today()
    from_yr = today.year if today.month >= 4 else today.year - 1
    return f"{str(from_yr)[-2:]}{str(from_yr + 1)[-2:]}"


def _next_transfer_ref_number():
    """
    Generates the next sequential transfer_ref_number for the current
    financial year.  Format: YYZZ/000001
    """
    prefix = f"{_current_fin_year()}/"
    client, hms_db = get_hms_db()
    top_doc = list(hms_db["hospital_stocktransfer"].find(
        {"transfer_ref_number": {"$regex": f"^{prefix}"}},
        {"transfer_ref_number": 1}
    ).sort("transfer_ref_number", DESCENDING).limit(1))
    max_seq = 0
    if top_doc:
        try:
            seq = int(str(top_doc[0].get("transfer_ref_number", "")).split("/")[-1])
            if seq > max_seq:
                max_seq = seq
        except (ValueError, IndexError):
            pass
    return f"{prefix}{str(max_seq + 1).zfill(6)}"


# ─────────────────────────────────────────────────────────────────────────────
# ACTIVE OUTLETS  (only real outlets — Drug Purchase is frontend-only concept)
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_active_stock_outlets(request):
    """
    Returns all outlets where is_stock_outlet=True and is_active=True.
    Drug Purchase is NOT in the DB — it is represented by outlet_code="" on frontend.
    """
    try:
        client, hms_db = get_hms_db()
        outlets = list(hms_db["hospital_outlets"].find(
            {"is_stock_outlet": True, "is_active": True},
            {"_id": 0}
        ))
        return Response({"success": True, "data": clean_docs(outlets)})
    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=500)


# ─────────────────────────────────────────────────────────────────────────────
# ITEM PARSING / ENRICHMENT HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def parse_transfer_items(raw_items):
    if not raw_items:
        return []

    if isinstance(raw_items, list):
        return raw_items

    if isinstance(raw_items, dict):
        return [raw_items]

    if isinstance(raw_items, str):
        raw_items = raw_items.strip()
        try:
            parsed = json.loads(raw_items)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict):
                return [parsed]
        except Exception:
            pass

        try:
            from collections import OrderedDict
            parsed = eval(raw_items, {"OrderedDict": OrderedDict})
            final_items = []
            if isinstance(parsed, list):
                for row in parsed:
                    if isinstance(row, OrderedDict):
                        final_items.append(dict(row))
                    elif isinstance(row, dict):
                        final_items.append(row)
                    elif isinstance(row, list):
                        final_items.append(dict(row))
                return final_items
            elif isinstance(parsed, OrderedDict):
                return [dict(parsed)]
        except Exception:
            pass

    return []


def enrich_items_with_medicine_name(items, hospital_code, branch_code):
    if not items:
        return []

    client, hms_db = get_hms_db()

    item_ids = list({_int(it.get("item_id")) for it in items if it.get("item_id") is not None})
    stock_ids = list({_int(it.get("stock_id")) for it in items if it.get("stock_id") is not None})

    item_map = {}
    if item_ids:
        for p in hms_db["hospital_pharmacyitem"].find({"item_id": {"$in": item_ids}}, {"item_id": 1, "item_name": 1}):
            item_map[int(p.get("item_id"))] = p.get("item_name", "")

    stock_map = {}
    if stock_ids:
        for s in hms_db["hospital_pharmacystock"].find({"stock_id": {"$in": stock_ids}}, {"stock_id": 1, "expiry_date": 1, "Selling_Price": 1, "selling_price": 1, "mrp": 1, "batch_number": 1}):
            sid = _int(s.get("stock_id"))
            stock_map[sid] = {
                "expiry_date": s.get("expiry_date"),
                "selling_price": float(_dec(s.get("Selling_Price") or s.get("selling_price") or s.get("mrp") or 0)),
                "batch_number": str(s.get("batch_number", "") or ""),
            }

    enriched = []
    for item in items:
        if isinstance(item, OrderedDict):
            item = dict(item)
        item_id = _int(item.get("item_id", 0))
        stock_id = _int(item.get("stock_id", 0))
        qty = _int(item.get("transferred_out_quantity", item.get("transfer_quantity", 0)))
        stock_info = stock_map.get(stock_id, {})

        enriched.append({
            "stock_id": stock_id,
            "item_id": item_id,
            "item_name": item_map.get(item_id, f"Item #{item_id}"),
            "batch_number": item.get("batch_number", stock_info.get("batch_number", "")),
            "expiry_date": stock_info.get("expiry_date"),
            "Selling_Price": stock_info.get("selling_price", 0),
            "transferred_out_quantity": qty,
        })

    return enriched


def _enrich_transfers_batch(transfer_list: list, hospital_code: str, branch_code: str) -> list:
    if not transfer_list:
        return transfer_list
    for row in transfer_list:
        raw_items = row.get("items", [])
        parsed_items = parse_transfer_items(raw_items)
        row["items"] = enrich_items_with_medicine_name(parsed_items, hospital_code, branch_code)
        row["from_outlet"] = row.get("outlet_code", "")
    return transfer_list


# ─────────────────────────────────────────────────────────────────────────────
# PHARMACY STOCK VIEW
# GET params: item_id, outlet_code, search (item_name prefix)
# Drug Purchase: outlet_code="" (stocks with no outlet_code)
# ─────────────────────────────────────────────────────────────────────────────
@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def pharmacy_stock_view(request, pk=None):

    if request.method == "GET":
        if pk:
            try:
                stock = PharmacyStock.objects.get(stock_id=_int(pk))
                return Response(PharmacyStockSerializer(stock).data)
            except PharmacyStock.DoesNotExist:
                return Response({"error": "Stock record not found"}, status=404)

        try:
            hospital_code = (
                request.data.get("auth-hospital-code") or
                request.headers.get("auth-hospital-code") or "system"
            )
            branch_code = (
                request.data.get("auth-branch-code") or
                request.headers.get("Branch-Code") or "system"
            )

            grn_number        = request.query_params.get("grn_number")
            item_id           = request.query_params.get("item_id")
            outlet_code_param = request.query_params.get("outlet_code", None)
            search            = request.query_params.get("search", "").strip()

            filter_q = {}
            if hospital_code and hospital_code != "system":
                filter_q["hospital_code"] = hospital_code
            if branch_code and branch_code != "system":
                filter_q["branch_code"] = branch_code

            if grn_number:
                filter_q["grn_number"] = grn_number
            if item_id:
                filter_q["item_id"] = _int(item_id)

            if outlet_code_param is not None:
                if outlet_code_param in ("", "None", "null", "system"):
                    filter_q["$or"] = [{"outlet_code": ""}, {"outlet_code": None}]
                else:
                    filter_q["outlet_code"] = outlet_code_param

            client, hms_db = get_hms_db()
            if search:
                matching_ids = [
                    d["item_id"] for d in hms_db["hospital_pharmacyitem"].find(
                        {"item_name": {"$regex": re.escape(search), "$options": "i"}},
                        {"item_id": 1}
                    )
                ]
                if not matching_ids:
                    return Response({
                        "success": True, "count": 0, "total_records": 0, "total_pages": 1,
                        "current_page": 1, "page_size": 10, "has_next": False, "has_previous": False,
                        "data": [], "results": []
                    })
                filter_q["item_id"] = {"$in": matching_ids}

            # Enrich helper
            def _enrich_stocks(stock_docs):
                if not stock_docs:
                    return stock_docs
                iids = list({s.get("item_id") for s in stock_docs if s.get("item_id") is not None})
                imap = {}
                if iids:
                    for itm in hms_db["hospital_pharmacyitem"].find({"item_id": {"$in": iids}}, {"item_id": 1, "item_name": 1}):
                        imap[itm.get("item_id")] = itm.get("item_name", "")

                enriched = []
                for row in stock_docs:
                    iid = row.get("item_id")
                    row["item_name"]                = imap.get(iid, f"Item #{iid}")
                    row["mrp"]                      = str(_dec(row.get("mrp", 0)))
                    row["Selling_Price"]            = str(_dec(
                        row.get("Selling_Price") or row.get("selling_price") or row.get("mrp") or 0
                    ))
                    row["CGST_Percentage"]          = str(_dec(row.get("CGST_Percentage", 0)))
                    row["SGST_Percentage"]          = str(_dec(row.get("SGST_Percentage", 0)))
                    row["CGST_Amt"]                 = str(_dec(row.get("CGST_Amt", 0)))
                    row["SGST_Amt"]                 = str(_dec(row.get("SGST_Amt", 0)))
                    row["total_stock"]              = _int(row.get("total_stock", 0))
                    row["sold_quantity"]            = _int(row.get("sold_quantity", 0))
                    row["transferred_out_quantity"] = _int(row.get("transferred_out_quantity", 0))
                    row["grn_return_quantity"]      = _int(row.get("grn_return_quantity", 0))
                    row["blocked_quantity"]         = _int(row.get("blocked_quantity", 0))
                    row["sales_return_quantity"]    = _int(row.get("sales_return_quantity", 0))
                    row["available_qty"] = (
                        row["total_stock"]
                        - row["sold_quantity"]
                        - row["transferred_out_quantity"]
                        - row["grn_return_quantity"]
                        - row["blocked_quantity"]
                        + row["sales_return_quantity"]
                    )
                    enriched.append(row)
                return enriched

            return Response(paginate_mongo_query(
                "hospital_pharmacystock",
                filter_q,
                sort=[("stock_id", DESCENDING)],
                request=request,
                enrich_fn=_enrich_stocks
            ))

        except Exception as e:
            logger.error(f"[pharmacy_stock_view] Unhandled error: {e}", exc_info=True)
            return Response({"error": str(e)}, status=500)


# ─────────────────────────────────────────────────────────────────────────────
# STOCK TRANSFER VIEW
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET", "POST", "PUT"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def stock_transfer_view(request, pk=None):

    request_data = request.data if hasattr(request, "data") else request.POST

    # ── Read auth context ─────────────────────────────────────────────────────
    hospital_code = (
        request_data.get("auth-hospital-code")
        or request.headers.get("auth-hospital-code")
        or "system"
    )
    branch_code = (
        request_data.get("auth-branch-code")
        or request.headers.get("auth-branch-code")
        or request.headers.get("Branch-Code")
        or "system"
    )
    raw_outlet = (
        request_data.get("auth-outlet-code")
        or request.headers.get("auth-outlet-code")
        or request.headers.get("Outlet-Code")
        or ""
    )
    # Normalize: treat "null", "None", "system" as Drug Purchase (empty string)
    outlet_code = "" if raw_outlet in ("", "null", "None", "system") else raw_outlet

    user_id = (
        request_data.get("auth-user-id")
        or request.headers.get("auth-user-id")
        or "system"
    )

    is_drug_purchase = (outlet_code == "")

    # ─────────────────────────────────────────────────────────────────────────
    # GET
    # ─────────────────────────────────────────────────────────────────────────
    if request.method == "GET":
        # ── SINGLE RECORD ─────────────────────────────────────────────────────
        if pk:
            try:
                st = StockTransfer.objects.get(
                    transfer_ref_number=pk,
                    hospital_code=hospital_code,
                    branch_code=branch_code
                )
                data = StockTransferSerializer(st).data
                raw_items = data.get("items", [])
                parsed_items = parse_transfer_items(raw_items)
                data["items"] = enrich_items_with_medicine_name(parsed_items, hospital_code, branch_code)
                data["from_outlet"] = data.get("outlet_code", "")
                return Response({"success": True, "data": data})
            except StockTransfer.DoesNotExist:
                return Response({"success": False, "error": "Transfer not found"}, status=404)

        # ── LIST RECORDS ──────────────────────────────────────────────────────
        filter_q = {}
        if hospital_code and hospital_code != "system":
            filter_q["hospital_code"] = hospital_code
        if branch_code and branch_code != "system":
            filter_q["branch_code"] = branch_code

        ref_number = request.GET.get("transfer_ref_number", "").strip()
        if ref_number:
            filter_q["transfer_ref_number"] = ref_number

        if is_drug_purchase:
            filter_q["$or"] = [{"to_outlet": ""}, {"to_outlet": None}]
        else:
            if outlet_code:
                filter_q["to_outlet"] = outlet_code

        search = request.GET.get("search", "").strip()
        if search:
            reg = {"$regex": re.escape(search), "$options": "i"}
            filter_q["$or"] = [
                {"transfer_ref_number": reg},
                {"is_verified": reg},
                {"remarks": reg},
                {"outlet_code": reg}
            ]

        filter_q = apply_date_filter(filter_q, request, "created_date")

        def _enrich_page(data_list):
            return _enrich_transfers_batch(data_list, hospital_code, branch_code)

        return Response(paginate_mongo_query(
            "hospital_stocktransfer",
            filter_q,
            sort=[("created_date", DESCENDING)],
            request=request,
            enrich_fn=_enrich_page
        ))

    # ─────────────────────────────────────────────────────────────────────────
    # POST — Create Draft Transfer
    # ─────────────────────────────────────────────────────────────────────────
    if request.method == "POST":

        data = request_data

        raw_items = data.get("items", [])
        if isinstance(raw_items, str):
            try:
                raw_items = json.loads(raw_items)
            except Exception:
                raw_items = []

        if not raw_items:
            return Response(
                {"success": False, "error": "At least one item is required"},
                status=400,
            )
        
        remarks = str(data.get("remarks", "")).strip()
        if not remarks:
            return Response(
                {"success": False, "error": "Remarks are required"},
                status=400,
            )

        from_outlet = str(data.get("from_outlet") or "").strip()
        to_outlet   = str(data.get("to_outlet")   or "").strip()

        # Both must be explicitly provided (even if empty string for Drug Purchase)
        # But they must differ
        if from_outlet == to_outlet:
            return Response(
                {"success": False, "error": "From Outlet and To Outlet must be different"},
                status=400,
            )

        all_stocks = list(PharmacyStock.objects.all())
        errors = []
        processed_items = []

        for idx, item in enumerate(raw_items):
            stock_id         = str(item.get("stock_id",         "")).strip()
            item_id          = str(item.get("item_id",          "")).strip()
            batch_number     = str(item.get("batch_number",     "")).strip()
            outlet_code_item = str(item.get("outlet_code") or from_outlet).strip()
            transfer_qty     = _int(item.get("transfer_quantity", 0))

            if transfer_qty <= 0:
                errors.append(f"Item {idx + 1}: transfer_quantity must be > 0")
                continue

            # Find source stock record
            source = None
            for s in all_stocks:
                if (
                    str(getattr(s, "hospital_code", "")) != str(hospital_code)
                    or str(getattr(s, "branch_code",  "")) != str(branch_code)
                ):
                    continue

                # Match by stock_id (primary) or item_id+batch+outlet (fallback)
                if stock_id and str(getattr(s, "stock_id", "")) == stock_id:
                    source = s
                    break

                row_outlet = str(getattr(s, "outlet_code", "") or "")
                if (
                    str(getattr(s, "item_id",      "")) == item_id
                    and str(getattr(s, "batch_number", "")).strip() == batch_number
                    and row_outlet == outlet_code_item
                ):
                    source = s
                    break

            if source is None:
                errors.append(
                    f"Item {idx + 1}: stock record not found "
                    f"(item_id={item_id}, batch={batch_number}, outlet='{outlet_code_item}')"
                )
                continue

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
                    f"Item {idx + 1}: requested {transfer_qty}, only {available} available"
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

        transfer_payload = {
            "outlet_code":         from_outlet,
            "to_outlet":           to_outlet,
            "transfer_ref_number": _next_transfer_ref_number(),
            "items":               processed_items,
            "is_verified":         "Draft",
            "remarks":             remarks,          # ← NEW
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

            response_data = StockTransferSerializer(saved).data
            response_data["from_outlet"] = response_data.get("outlet_code", "")

            raw_items_saved = getattr(saved, "items", [])
            parsed_saved    = parse_transfer_items(raw_items_saved)
            response_data["items"] = enrich_items_with_medicine_name(
                parsed_saved, hospital_code, branch_code
            )

            return Response(
                {
                    "success": True,
                    "message": "Stock transfer created as Draft",
                    "data":    response_data,
                },
                status=201,
            )

        return Response({"success": False, "error": serializer.errors}, status=400)


# ─────────────────────────────────────────────────────────────────────────────
# STOCK TRANSFER ACTION  (approve / reject)
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def stock_transfer_action_view(request):
    """
    Body:
        transfer_ref_number : e.g. "2627/000001"
        action              : "approve" | "reject"
    """
    request_data = request.data if hasattr(request, "data") else request.POST

    # ── Auth context ──────────────────────────────────────────────────────────
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
    raw_outlet = (
        request_data.get("auth-outlet-code")
        or request.headers.get("auth-outlet-code")
        or request.headers.get("Outlet-Code")
        or ""
    )
    outlet_code = "" if raw_outlet in ("", "null", "None", "system") else raw_outlet
    is_drug_purchase = (outlet_code == "")

    user_id = (
        request_data.get("auth-user-id")
        or request.headers.get("auth-user-id")
        or "system"
    )

    pk     = str(request_data.get("transfer_ref_number", "")).strip()
    action = str(request_data.get("action", "")).strip().lower()

    if not pk:
        return Response({"success": False, "error": "transfer_ref_number is required"}, status=400)

    # ── Fetch transfer ────────────────────────────────────────────────────────
    try:
        obj = StockTransfer.objects.get(transfer_ref_number=pk)
    except StockTransfer.DoesNotExist:
        return Response({"success": False, "error": "Transfer not found"}, status=404)

    if (
        str(getattr(obj, "hospital_code", "")) != str(hospital_code)
        or str(getattr(obj, "branch_code",  "")) != str(branch_code)
    ):
        return Response({"success": False, "error": "Transfer not found"}, status=404)

    current_status = str(getattr(obj, "is_verified", ""))

    # ── APPROVE ───────────────────────────────────────────────────────────────
    if action == "approve":

        if current_status == "Approved":
            return Response({"success": False, "error": "Transfer is already Approved"}, status=400)
        if current_status == "Rejected":
            return Response({"success": False, "error": "Rejected transfers cannot be approved"}, status=403)

        transfer_to_outlet = str(getattr(obj, "to_outlet", "") or "")

        # Permission: Drug Purchase can approve any; real outlet can only approve if they are the recipient
        if not is_drug_purchase and outlet_code != transfer_to_outlet:
            return Response(
                {"success": False, "error": "Only the receiving outlet can approve this transfer"},
                status=403,
            )

        from_outlet    = str(getattr(obj, "outlet_code", "") or "")
        transfer_items = getattr(obj, "items", []) or []
        parsed_items   = parse_transfer_items(transfer_items)
        all_stocks     = list(PharmacyStock.objects.all())
        errors         = []

        for idx, item in enumerate(parsed_items):
            if isinstance(item, OrderedDict):
                item = dict(item)

            stock_id     = str(item.get("stock_id",     "")).strip()
            item_id      = str(item.get("item_id",      "")).strip()
            batch_number = str(item.get("batch_number", "")).strip()
            transfer_qty = _int(item.get("transferred_out_quantity", item.get("transfer_quantity", 0)))

            if transfer_qty <= 0:
                errors.append(f"Item {idx + 1}: invalid transfer quantity")
                continue

            # Find source stock
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
                row_outlet = str(getattr(s, "outlet_code", "") or "")
                if (
                    str(getattr(s, "item_id",      "")) == item_id
                    and str(getattr(s, "batch_number", "")).strip() == batch_number
                    and row_outlet == from_outlet
                ):
                    source = s
                    break

            if source is None:
                errors.append(
                    f"Item {idx + 1}: source stock not found "
                    f"(item_id={item_id}, batch={batch_number}, outlet='{from_outlet}')"
                )
                continue

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

            # ── Deduct from source ────────────────────────────────────────────
            new_transferred_out = _int(getattr(source, "transferred_out_quantity", 0)) + transfer_qty
            PharmacyStock.objects.filter(
                stock_id      = getattr(source, "stock_id", None),
                hospital_code = hospital_code,
                branch_code   = branch_code,
            ).update(
                transferred_out_quantity = new_transferred_out,
                lastmodified_by          = user_id,
                lastmodified_date        = timezone.now(),
            )

            # ── Create destination stock record ───────────────────────────────
            source_stock_id = _int(getattr(source, "stock_id", 0))
            try:
                PharmacyStock.objects.create(
                    hospital_code            = hospital_code,
                    branch_code              = branch_code,
                    outlet_code              = transfer_to_outlet,  # "" = Drug Purchase
                    item_id                  = _int(getattr(source, "item_id", 0)),
                    batch_number             = str(getattr(source, "batch_number", "") or ""),
                    expiry_date              = getattr(source, "expiry_date", None),
                    grn_number               = str(getattr(source, "grn_number", "") or ""),
                    total_stock              = transfer_qty,
                    sold_quantity            = 0,
                    transferred_out_quantity = 0,
                    grn_return_quantity      = 0,
                    grn_return_ref_id        = None,
                    blocked_quantity         = 0,
                    sales_return_quantity    = 0,
                    sales_return_ref_id      = None,
                    stock_type               = "transfer",
                    stock_ref_id             = source_stock_id,
                    mrp                      = _dec(getattr(source, "mrp",             0)),
                    Selling_Price            = _dec(
                        getattr(source, "Selling_Price", None) or
                        getattr(source, "selling_price", None) or
                        getattr(source, "mrp", 0)
                    ),
                    CGST_Percentage          = _dec(getattr(source, "CGST_Percentage", 0)),
                    SGST_Percentage          = _dec(getattr(source, "SGST_Percentage", 0)),
                    CGST_Amt                 = _dec(getattr(source, "CGST_Amt",        0)),
                    SGST_Amt                 = _dec(getattr(source, "SGST_Amt",        0)),
                    created_by               = user_id,
                    created_date             = timezone.now(),
                    lastmodified_by          = user_id,
                    lastmodified_date        = timezone.now(),
                )
            except Exception as e:
                errors.append(f"Item {idx + 1}: failed to create destination stock — {e}")
                continue

        if errors:
            return Response({"success": False, "error": errors}, status=400)

        StockTransfer.objects.filter(transfer_ref_number=pk).update(
            is_verified       = "Approved",
            approved_by       = user_id,            # ← NEW
            approved_date     = timezone.now(),     # ← NEW
            lastmodified_by   = user_id,
            lastmodified_date = timezone.now(),
        )

        try:
            updated = StockTransfer.objects.get(transfer_ref_number=pk)
        except StockTransfer.DoesNotExist:
            updated = obj

        response_data = StockTransferSerializer(updated).data
        response_data["from_outlet"] = response_data.get("outlet_code", "")

        return Response({
            "success": True,
            "message": "Stock transfer approved successfully",
            "data":    response_data,
        })

    # ── REJECT ────────────────────────────────────────────────────────────────
    if action == "reject":

        if current_status == "Approved":
            return Response({"success": False, "error": "Approved transfers cannot be cancelled"}, status=403)
        if current_status == "Rejected":
            return Response({"success": False, "error": "Transfer is already Cancelled"}, status=400)

        rejected_reason = str(request_data.get("rejected_reason", "")).strip()
        if not rejected_reason:
            return Response(
                {"success": False, "error": "Rejection reason is required"},
                status=400,
            )

        StockTransfer.objects.filter(transfer_ref_number=pk).update(
            is_verified       = "Rejected",
            rejected_by       = user_id,            # ← NEW
            rejected_date     = timezone.now(),     # ← NEW
            rejected_reason   = rejected_reason,    # ← NEW
            lastmodified_by   = user_id,
            lastmodified_date = timezone.now(),
        )

        try:
            updated = StockTransfer.objects.get(transfer_ref_number=pk)
        except StockTransfer.DoesNotExist:
            updated = obj

        response_data = StockTransferSerializer(updated).data
        response_data["from_outlet"] = response_data.get("outlet_code", "")

        return Response({
            "success": True,
            "message": "Stock transfer cancelled",
            "data":    response_data,
        })

    # ── Unknown action ────────────────────────────────────────────────────────
    return Response(
        {"success": False, "error": f"Unknown action '{action}'. Expected 'approve' or 'reject'."},
        status=400,
    )