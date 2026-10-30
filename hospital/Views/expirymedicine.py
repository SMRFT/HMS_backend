from django.shortcuts import render
from rest_framework.response import Response
from django.http import JsonResponse
from rest_framework import status
from pymongo import MongoClient
from django.utils.timezone import now
from bson import Decimal128, ObjectId
from datetime import datetime
from decimal import Decimal, InvalidOperation
from django.utils import timezone
import re
import logging
import json
import os
from collections import OrderedDict
from typing import Any
from rest_framework.decorators import api_view, permission_classes
from django.views.decorators.csrf import csrf_exempt

# Auth/permissions
from pyauth.auth import HasRoleAndDataPermission

# Logger setup
logger = logging.getLogger(__name__)

from ..models import PharmacyStock, ExpiryMedicine, PharmacyItem
from ..serializers import ExpiryMedicineSerializer, PharmacyStockSerializer
from .mongo_utils import get_hms_db, paginate_mongo_query, clean_docs, clean_doc, apply_date_filter
from pymongo import ASCENDING, DESCENDING
from django.db.models import Q


# ─────────────────────────────────────────────────────────────────────────────
# SAFE CONVERSION HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _dec(value, default="0.00"):
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
    try:
        return int(_dec(value, str(default)))
    except Exception:
        return default


# ─── Financial year + ref-number ─────────────────────────────────────────────

def _current_fin_year():
    today = datetime.today()
    from_yr = today.year if today.month >= 4 else today.year - 1
    return f"{str(from_yr)[-2:]}{str(from_yr + 1)[-2:]}"


def _next_expiry_ref_number():
    """
    Generates the next sequential expiry_ref_number for the current
    financial year. Format: EXP-YYZZ/000001
    """
    prefix = f"EXP-{_current_fin_year()}/"
    client, hms_db = get_hms_db()
    top_doc = list(hms_db["hospital_expirymedicine"].find(
        {"expiry_ref_number": {"$regex": f"^{prefix}"}},
        {"expiry_ref_number": 1}
    ).sort("expiry_ref_number", DESCENDING).limit(1))
    max_seq = 0
    if top_doc:
        try:
            seq = int(str(top_doc[0].get("expiry_ref_number", "")).split("/")[-1])
            if seq > max_seq:
                max_seq = seq
        except (ValueError, IndexError):
            pass
    return f"{prefix}{str(max_seq + 1).zfill(6)}"


# ─────────────────────────────────────────────────────────────────────────────
# ITEM PARSING / ENRICHMENT HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def parse_expiry_items(raw_items):
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
        for s in hms_db["hospital_pharmacystock"].find(
            {"stock_id": {"$in": stock_ids}},
            {"stock_id": 1, "expiry_date": 1, "Selling_Price": 1, "selling_price": 1, "mrp": 1, "batch_number": 1, "hsn_code": 1}
        ):
            sid = _int(s.get("stock_id"))
            stock_map[sid] = {
                "expiry_date": s.get("expiry_date"),
                "selling_price": float(_dec(s.get("Selling_Price") or s.get("selling_price") or s.get("mrp") or 0)),
                "mrp": float(_dec(s.get("mrp") or 0)),
                "batch_number": str(s.get("batch_number", "") or ""),
                "hsn_code": str(s.get("hsn_code", "") or ""),
            }

    enriched = []
    for item in items:
        if isinstance(item, OrderedDict):
            item = dict(item)

        item_id = _int(item.get("item_id", 0))
        stock_id = _int(item.get("stock_id", 0))
        qty = _int(item.get("quantity", item.get("expiry_quantity", 0)))
        stock_info = stock_map.get(stock_id, {})

        selling_price = float(_dec(item.get("Selling_Price", stock_info.get("selling_price", 0))))
        mrp = float(_dec(item.get("mrp", stock_info.get("mrp", 0))))
        total_item_amount = float(_dec(item.get("total_amount", qty * selling_price)))

        raw_expiry = item.get("expiry_date") or stock_info.get("expiry_date")
        if hasattr(raw_expiry, "strftime"):
            expiry_str = raw_expiry.strftime("%Y-%m-%d")
        elif hasattr(raw_expiry, "isoformat"):
            expiry_str = raw_expiry.isoformat()
        else:
            expiry_str = str(raw_expiry) if raw_expiry else ""

        enriched.append({
            "stock_id": stock_id,
            "item_id": item_id,
            "item_name": item.get("item_name") or item_map.get(item_id, f"Item #{item_id}"),
            "batch_number": item.get("batch_number", stock_info.get("batch_number", "")),
            "expiry_date": expiry_str,
            "Selling_Price": selling_price,
            "mrp": mrp,
            "quantity": qty,
            "total_amount": round(total_item_amount, 2),
        })

    return enriched


def _enrich_expiry_batch(expiry_list: list, hospital_code: str, branch_code: str) -> list:
    if not expiry_list:
        return expiry_list
    for row in expiry_list:
        raw_items = row.get("items", [])
        parsed_items = parse_expiry_items(raw_items)
        row["items"] = enrich_items_with_medicine_name(parsed_items, hospital_code, branch_code)
        row["outlet_code"] = row.get("outlet_code", "")
    return expiry_list


# ─────────────────────────────────────────────────────────────────────────────
# EXPIRY MEDICINE VIEW (GET / POST)
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def expiry_medicine_view(request, pk=None):
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
    user_outlet = "" if raw_outlet in ("", "null", "None", "system") else raw_outlet

    user_id = (
        request_data.get("auth-user-id")
        or request.headers.get("auth-user-id")
        or "system"
    )

    # ─────────────────────────────────────────────────────────────────────────
    # GET
    # ─────────────────────────────────────────────────────────────────────────
    if request.method == "GET":
        ref_lookup = pk or request.GET.get("expiry_ref_number", "").strip()

        # ── SINGLE RECORD ─────────────────────────────────────────────────────
        if ref_lookup:
            try:
                obj = ExpiryMedicine.objects.get(
                    expiry_ref_number=ref_lookup,
                    hospital_code=hospital_code,
                    branch_code=branch_code
                )
                data = ExpiryMedicineSerializer(obj).data
                raw_items = data.get("items", [])
                parsed_items = parse_expiry_items(raw_items)
                data["items"] = enrich_items_with_medicine_name(parsed_items, hospital_code, branch_code)
                return Response({"success": True, "data": data})
            except ExpiryMedicine.DoesNotExist:
                # Fallback to direct MongoDB query
                client, hms_db = get_hms_db()
                doc = hms_db["hospital_expirymedicine"].find_one({
                    "expiry_ref_number": ref_lookup,
                    "hospital_code": hospital_code,
                    "branch_code": branch_code
                })
                if doc:
                    doc = clean_doc(doc)
                    raw_items = doc.get("items", [])
                    parsed_items = parse_expiry_items(raw_items)
                    doc["items"] = enrich_items_with_medicine_name(parsed_items, hospital_code, branch_code)
                    return Response({"success": True, "data": doc})
                return Response({"success": False, "error": "Expiry record not found"}, status=404)

        # ── LIST RECORDS ──────────────────────────────────────────────────────
        filter_q = {}
        if hospital_code and hospital_code != "system":
            filter_q["hospital_code"] = hospital_code
        if branch_code and branch_code != "system":
            filter_q["branch_code"] = branch_code

        # Outlet filter (if param provided, use param; otherwise if user is logged into an outlet, filter by that)
        outlet_param = request.GET.get("outlet_code", None)
        if outlet_param is not None:
            if outlet_param in ("", "null", "None", "system", "__DRUG_PURCHASE__"):
                filter_q["$or"] = [{"outlet_code": ""}, {"outlet_code": None}]
            else:
                filter_q["outlet_code"] = outlet_param
        elif user_outlet:
            filter_q["outlet_code"] = user_outlet

        # Status filter (Draft, Approved, Rejected)
        status_param = request.GET.get("status", "").strip()
        if status_param and status_param.lower() != "all":
            filter_q["is_verified"] = {"$regex": f"^{re.escape(status_param)}$", "$options": "i"}

        search = request.GET.get("search", "").strip()
        if search:
            reg = {"$regex": re.escape(search), "$options": "i"}
            or_clauses = [
                {"expiry_ref_number": reg},
                {"is_verified": reg},
                {"remarks": reg},
                {"outlet_code": reg},
                {"items.item_name": reg},
                {"items.batch_number": reg},
            ]
            if "$or" in filter_q:
                filter_q["$and"] = [{"$or": filter_q.pop("$or")}, {"$or": or_clauses}]
            else:
                filter_q["$or"] = or_clauses

        filter_q = apply_date_filter(filter_q, request, "created_date")

        def _enrich_page(data_list):
            return _enrich_expiry_batch(data_list, hospital_code, branch_code)

        return Response(paginate_mongo_query(
            "hospital_expirymedicine",
            filter_q,
            sort=[("created_date", DESCENDING)],
            request=request,
            enrich_fn=_enrich_page
        ))

    # ─────────────────────────────────────────────────────────────────────────
    # POST — Create Draft Expiry Record
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
                {"success": False, "error": "Remarks are required for expiry medicine entries"},
                status=400,
            )

        outlet_code = str(data.get("outlet_code") if data.get("outlet_code") is not None else user_outlet).strip()
        if outlet_code in ("null", "None", "system", "__DRUG_PURCHASE__"):
            outlet_code = ""

        client, hms_db = get_hms_db()

        # Batch-fetch relevant stock items by stock_id
        stock_ids = [_int(item.get("stock_id")) for item in raw_items if item.get("stock_id")]
        stocks_map = {}
        if stock_ids:
            for s in hms_db["hospital_pharmacystock"].find({"stock_id": {"$in": stock_ids}}):
                stocks_map[_int(s.get("stock_id"))] = clean_doc(s)

        errors = []
        processed_items = []
        total_quantity = 0
        total_amount = Decimal("0.00")

        for idx, item in enumerate(raw_items):
            stock_id     = str(item.get("stock_id", "")).strip()
            item_id      = str(item.get("item_id", "")).strip()
            batch_number = str(item.get("batch_number", "")).strip()
            qty          = _int(item.get("quantity", item.get("expiry_quantity", 0)))

            if qty <= 0:
                errors.append(f"Item {idx + 1}: quantity must be greater than 0")
                continue

            # Match source stock record
            source = None
            if stock_id and _int(stock_id) in stocks_map:
                source = stocks_map[_int(stock_id)]
            else:
                mongo_filter = {
                    "item_id": _int(item_id),
                    "batch_number": batch_number,
                }
                if hospital_code and hospital_code != "system":
                    mongo_filter["hospital_code"] = hospital_code
                if branch_code and branch_code != "system":
                    mongo_filter["branch_code"] = branch_code
                if outlet_code:
                    mongo_filter["outlet_code"] = outlet_code
                else:
                    mongo_filter["$or"] = [{"outlet_code": ""}, {"outlet_code": None}]

                doc = hms_db["hospital_pharmacystock"].find_one(mongo_filter)
                if doc:
                    source = clean_doc(doc)

            if source is None:
                errors.append(
                    f"Item {idx + 1}: stock record not found (item_id={item_id}, batch={batch_number}, outlet='{outlet_code}')"
                )
                continue

            available = (
                _int(source.get("total_stock", 0))
                - _int(source.get("sold_quantity", 0))
                - _int(source.get("transferred_out_quantity", 0))
                - _int(source.get("grn_return_quantity", 0))
                - _int(source.get("blocked_quantity", 0))
                + _int(source.get("sales_return_quantity", 0))
            )

            if qty > available:
                errors.append(
                    f"Item {idx + 1} ({source.get('batch_number', batch_number)}): requested {qty}, only {available} available in stock"
                )
                continue

            # Fetch medicine name if available
            med_item_id = _int(source.get("item_id", item_id))
            med_name_doc = hms_db["hospital_pharmacyitem"].find_one({"item_id": med_item_id}, {"item_name": 1})
            item_name = med_name_doc.get("item_name") if med_name_doc else item.get("item_name", f"Item #{med_item_id}")

            selling_price = _dec(
                source.get("Selling_Price") or
                source.get("selling_price") or
                source.get("mrp") or 0
            )
            mrp = _dec(source.get("mrp", 0))
            item_total = _dec(qty) * selling_price

            raw_exp = source.get("expiry_date", None)
            if hasattr(raw_exp, "strftime"):
                exp_date_str = raw_exp.strftime("%Y-%m-%d")
            elif hasattr(raw_exp, "isoformat"):
                exp_date_str = raw_exp.isoformat()
            else:
                exp_date_str = str(raw_exp) if raw_exp else ""

            processed_items.append({
                "stock_id":      _int(source.get("stock_id", 0)),
                "item_id":       med_item_id,
                "item_name":     item_name,
                "batch_number":  str(source.get("batch_number", batch_number) or ""),
                "expiry_date":   exp_date_str,
                "quantity":      qty,
                "mrp":           float(mrp),
                "Selling_Price": float(selling_price),
                "total_amount":  float(item_total),
            })

            total_quantity += qty
            total_amount += item_total

        if errors:
            return Response({"success": False, "error": errors}, status=400)

        expiry_payload = {
            "outlet_code":       outlet_code,
            "expiry_ref_number": _next_expiry_ref_number(),
            "items":             processed_items,
            "total_quantity":    total_quantity,
            "total_amount":      float(total_amount),
            "is_verified":       "Draft",
            "remarks":           remarks,
            "hospital_code":     hospital_code,
            "branch_code":       branch_code,
        }

        serializer = ExpiryMedicineSerializer(data=expiry_payload)
        if serializer.is_valid():
            saved = serializer.save(
                created_by        = user_id,
                created_date      = timezone.now(),
                lastmodified_by   = user_id,
                lastmodified_date = timezone.now(),
            )

            response_data = ExpiryMedicineSerializer(saved).data
            raw_saved = getattr(saved, "items", [])
            parsed_saved = parse_expiry_items(raw_saved)
            response_data["items"] = enrich_items_with_medicine_name(
                parsed_saved, hospital_code, branch_code
            )

            return Response(
                {
                    "success": True,
                    "message": f"Expiry entry created as Draft ({expiry_payload['expiry_ref_number']})",
                    "data":    response_data,
                },
                status=201,
            )

        return Response({"success": False, "error": serializer.errors}, status=400)


# ─────────────────────────────────────────────────────────────────────────────
# EXPIRY MEDICINE ACTION (approve / reject)
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def expiry_medicine_action_view(request):
    """
    Body:
        expiry_ref_number : e.g. "EXP-2627/000001"
        action            : "approve" | "reject"
        rejected_reason   : "..." (required if action == "reject")
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
    user_id = (
        request_data.get("auth-user-id")
        or request.headers.get("auth-user-id")
        or "system"
    )

    ref_number = str(request_data.get("expiry_ref_number", "")).strip()
    action = str(request_data.get("action", "")).strip().lower()

    if not ref_number:
        return Response({"success": False, "error": "expiry_ref_number is required"}, status=400)

    # ── Fetch record ──────────────────────────────────────────────────────────
    try:
        obj = ExpiryMedicine.objects.get(expiry_ref_number=ref_number)
    except ExpiryMedicine.DoesNotExist:
        # Check MongoDB
        client, hms_db = get_hms_db()
        doc = hms_db["hospital_expirymedicine"].find_one({"expiry_ref_number": ref_number})
        if not doc:
            return Response({"success": False, "error": "Expiry record not found"}, status=404)
        obj = type('ExpObj', (object,), doc)()

    if hospital_code and str(getattr(obj, "hospital_code", "")) != str(hospital_code):
        return Response({"success": False, "error": "Expiry record not found in this hospital"}, status=404)
    if branch_code and str(getattr(obj, "branch_code", "")) != str(branch_code):
        return Response({"success": False, "error": "Expiry record not found in this branch"}, status=404)

    current_status = str(getattr(obj, "is_verified", ""))

    client, hms_db = get_hms_db()

    # ── APPROVE ───────────────────────────────────────────────────────────────
    if action == "approve":
        if current_status == "Approved":
            return Response({"success": False, "error": "Expiry record is already Approved"}, status=400)
        if current_status == "Rejected":
            return Response({"success": False, "error": "Rejected expiry records cannot be approved"}, status=403)

        raw_items = getattr(obj, "items", []) or []
        parsed_items = parse_expiry_items(raw_items)
        errors = []

        stock_ids = [_int(item.get("stock_id")) for item in parsed_items if item.get("stock_id")]
        stocks_map = {}
        if stock_ids:
            for s in hms_db["hospital_pharmacystock"].find({"stock_id": {"$in": stock_ids}}):
                stocks_map[_int(s.get("stock_id"))] = clean_doc(s)

        target_updates = []

        for idx, item in enumerate(parsed_items):
            if isinstance(item, OrderedDict):
                item = dict(item)

            stock_id     = str(item.get("stock_id", "")).strip()
            item_id      = str(item.get("item_id", "")).strip()
            batch_number = str(item.get("batch_number", "")).strip()
            qty          = _int(item.get("quantity", item.get("expiry_quantity", 0)))
            outlet_code  = str(getattr(obj, "outlet_code", "") or "")

            if qty <= 0:
                errors.append(f"Item {idx + 1}: invalid quantity ({qty})")
                continue

            source = None
            if stock_id and _int(stock_id) in stocks_map:
                source = stocks_map[_int(stock_id)]
            else:
                s_filter = {
                    "item_id": _int(item_id),
                    "batch_number": batch_number,
                }
                if hospital_code and hospital_code != "system":
                    s_filter["hospital_code"] = hospital_code
                if branch_code and branch_code != "system":
                    s_filter["branch_code"] = branch_code
                if outlet_code:
                    s_filter["outlet_code"] = outlet_code
                else:
                    s_filter["$or"] = [{"outlet_code": ""}, {"outlet_code": None}]

                s_doc = hms_db["hospital_pharmacystock"].find_one(s_filter)
                if s_doc:
                    source = clean_doc(s_doc)

            if source is None:
                errors.append(
                    f"Item {idx + 1}: stock not found (item_id={item_id}, batch={batch_number}, outlet='{outlet_code}')"
                )
                continue

            available = (
                _int(source.get("total_stock", 0))
                - _int(source.get("sold_quantity", 0))
                - _int(source.get("transferred_out_quantity", 0))
                - _int(source.get("grn_return_quantity", 0))
                - _int(source.get("blocked_quantity", 0))
                + _int(source.get("sales_return_quantity", 0))
            )

            if qty > available:
                errors.append(
                    f"Item {idx + 1} (batch={batch_number}): requested {qty}, only {available} available at approval time"
                )
                continue

            target_updates.append((source, qty))

        if errors:
            return Response({"success": False, "error": errors}, status=400)

        # ── Apply stock deduction / block ─────────────────────────────────────
        # For expiry write-off, increment blocked_quantity so available stock drops permanently
        for source, qty in target_updates:
            cur_blocked = _int(source.get("blocked_quantity", 0))
            new_blocked = cur_blocked + qty
            s_id = _int(source.get("stock_id", 0))

            # Update Django model
            try:
                PharmacyStock.objects.filter(stock_id=s_id).update(
                    blocked_quantity  = new_blocked,
                    lastmodified_by   = user_id,
                    lastmodified_date = timezone.now(),
                )
            except Exception as e:
                logger.warning(f"Django update failed for stock_id {s_id}: {e}")

            # Update MongoDB collection
            try:
                hms_db["hospital_pharmacystock"].update_one(
                    {"stock_id": s_id},
                    {
                        "$set": {
                            "blocked_quantity":  new_blocked,
                            "lastmodified_by":   user_id,
                            "lastmodified_date": timezone.now(),
                        }
                    }
                )
            except Exception as e:
                logger.error(f"MongoDB update failed for stock_id {s_id}: {e}")

        # ── Update ExpiryMedicine status ──────────────────────────────────────
        now_ts = timezone.now()
        try:
            ExpiryMedicine.objects.filter(expiry_ref_number=ref_number).update(
                is_verified       = "Approved",
                approved_by       = user_id,
                approved_date     = now_ts,
                lastmodified_by   = user_id,
                lastmodified_date = now_ts,
            )
        except Exception:
            pass

        hms_db["hospital_expirymedicine"].update_one(
            {"expiry_ref_number": ref_number},
            {
                "$set": {
                    "is_verified":       "Approved",
                    "approved_by":       user_id,
                    "approved_date":     now_ts,
                    "lastmodified_by":   user_id,
                    "lastmodified_date": now_ts,
                }
            }
        )

        try:
            updated = ExpiryMedicine.objects.get(expiry_ref_number=ref_number)
            response_data = ExpiryMedicineSerializer(updated).data
        except Exception:
            updated_doc = hms_db["hospital_expirymedicine"].find_one({"expiry_ref_number": ref_number})
            response_data = clean_doc(updated_doc)

        response_data["items"] = enrich_items_with_medicine_name(
            parse_expiry_items(response_data.get("items", [])),
            hospital_code,
            branch_code
        )

        return Response({
            "success": True,
            "message": "Expiry record approved successfully. Quantities have been deducted from active inventory.",
            "data":    response_data,
        })

    # ── REJECT ────────────────────────────────────────────────────────────────
    if action == "reject":
        if current_status == "Approved":
            return Response({"success": False, "error": "Approved expiry records cannot be cancelled"}, status=403)
        if current_status == "Rejected":
            return Response({"success": False, "error": "Expiry record is already Cancelled"}, status=400)

        rejected_reason = str(request_data.get("rejected_reason", "")).strip()
        if not rejected_reason:
            return Response(
                {"success": False, "error": "Rejection reason is required"},
                status=400,
            )

        now_ts = timezone.now()
        try:
            ExpiryMedicine.objects.filter(expiry_ref_number=ref_number).update(
                is_verified       = "Rejected",
                rejected_by       = user_id,
                rejected_date     = now_ts,
                rejected_reason   = rejected_reason,
                lastmodified_by   = user_id,
                lastmodified_date = now_ts,
            )
        except Exception:
            pass

        hms_db["hospital_expirymedicine"].update_one(
            {"expiry_ref_number": ref_number},
            {
                "$set": {
                    "is_verified":       "Rejected",
                    "rejected_by":       user_id,
                    "rejected_date":     now_ts,
                    "rejected_reason":   rejected_reason,
                    "lastmodified_by":   user_id,
                    "lastmodified_date": now_ts,
                }
            }
        )

        try:
            updated = ExpiryMedicine.objects.get(expiry_ref_number=ref_number)
            response_data = ExpiryMedicineSerializer(updated).data
        except Exception:
            updated_doc = hms_db["hospital_expirymedicine"].find_one({"expiry_ref_number": ref_number})
            response_data = clean_doc(updated_doc)

        response_data["items"] = enrich_items_with_medicine_name(
            parse_expiry_items(response_data.get("items", [])),
            hospital_code,
            branch_code
        )

        return Response({
            "success": True,
            "message": "Expiry record cancelled/rejected",
            "data":    response_data,
        })

    return Response(
        {"success": False, "error": f"Unknown action '{action}'. Expected 'approve' or 'reject'."},
        status=400,
    )
