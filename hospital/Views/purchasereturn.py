"""
purchasereturn.py - Purchase Return views (Django REST Framework + PyMongo).
"""

from django.shortcuts import render
from rest_framework.response import Response
from rest_framework import status
from pymongo import MongoClient
from django.utils import timezone
from decimal import Decimal, InvalidOperation
from bson import Decimal128, ObjectId
from datetime import datetime
import logging
import os
import re
import json

from rest_framework.decorators import api_view, permission_classes
from django.views.decorators.csrf import csrf_exempt

from pyauth.auth import HasRoleAndDataPermission
from ..models import PharmacyStock, PharmacyItem, PurchaseReturn, GRN, Vendor
from ..serializers import PurchaseReturnSerializer

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

CAUSE_OF_RETURN_CHOICES = [
    "Broken",
    "Damage",
    "Nearing Expiry",
    "Non Moving",
    "Price Difference",
    "Returns",
    "Shortage",
]

PURCHASE_RETURN_STATUS_CHOICES = [
    "Pending",
    "Returned",
]


# ─────────────────────────────────────────────────────────────────────────────
# SAFE HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _dec(value, default="0.00"):
    """Safely convert any value to Decimal."""
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


def _calc_available(stock_obj):
    """
    Batch Stock formula:
    total_stock - sold_quantity - transferred_out_quantity
    - blocked_quantity - grn_return_quantity + sales_return_quantity
    """
    total     = _int(getattr(stock_obj, "total_stock",               0))
    sold      = _int(getattr(stock_obj, "sold_quantity",             0))
    trans_out = _int(getattr(stock_obj, "transferred_out_quantity",  0))
    grn_ret   = _int(getattr(stock_obj, "grn_return_quantity",       0))
    blocked   = _int(getattr(stock_obj, "blocked_quantity",          0))
    sales_ret = _int(getattr(stock_obj, "sales_return_quantity",     0))
    return total - sold - trans_out - grn_ret - blocked + sales_ret


# ─────────────────────────────────────────────────────────────────────────────
# AUTH CONTEXT HELPER
# ─────────────────────────────────────────────────────────────────────────────

def _get_auth(request, request_data):
    hospital_code = (
        request_data.get("auth-hospital-code")
        or request.headers.get("auth-hospital-code")
        or request.POST.get("auth-hospital-code")
        or None
    )
    branch_code = (
        request_data.get("auth-branch-code")
        or request.headers.get("auth-branch-code")
        or request.headers.get("Branch-Code")
        or request.POST.get("auth-branch-code")
        or None
    )
    raw_outlet = (
        request_data.get("auth-outlet-code")
        or request.headers.get("auth-outlet-code")
        or request.headers.get("Outlet-Code")
        or request.POST.get("auth-outlet-code")
        or ""
    )
    outlet_code = "" if raw_outlet in ("", "null", "None", "system", "undefined") else raw_outlet
    user_id = (
        request_data.get("auth-user-id")
        or request.headers.get("auth-user-id")
        or request.POST.get("auth-user-id")
        or "system"
    )
    return hospital_code, branch_code, outlet_code, user_id


# ─────────────────────────────────────────────────────────────────────────────
# MONGO COLLECTION
# ─────────────────────────────────────────────────────────────────────────────

def _get_collection():
    client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
    db     = client.HMS
    return db.hospital_purchase_returns


def _serialize_doc(doc):
    """Make a MongoDB document JSON-serializable."""
    if doc is None:
        return None
    result = {}
    for k, v in doc.items():
        if k == "_id":
            result[k] = str(v)
        elif isinstance(v, datetime):
            result[k] = v.isoformat()
        elif isinstance(v, Decimal):
            result[k] = str(v)
        elif isinstance(v, Decimal128):
            result[k] = str(v.to_decimal())
        elif isinstance(v, list):
            result[k] = [
                _serialize_doc(i) if isinstance(i, dict) else i for i in v
            ]
        elif isinstance(v, dict):
            result[k] = _serialize_doc(v)
        else:
            result[k] = v
    return result


# ─────────────────────────────────────────────────────────────────────────────
# BILL-NO GENERATOR  (format: 2627/000001)
# ─────────────────────────────────────────────────────────────────────────────

from .mongo_utils import get_hms_db, paginate_queryset, paginate_mongo_query, clean_doc, clean_docs, apply_date_filter
from pymongo import ASCENDING, DESCENDING
from django.db.models import Q


def _current_fin_year():
    today = datetime.today()
    from_yr = today.year if today.month >= 4 else today.year - 1
    return f"{str(from_yr)[-2:]}{str(from_yr + 1)[-2:]}"


def _next_purchase_return_bill_no():
    prefix = f"{_current_fin_year()}/"
    client, hms_db = get_hms_db()
    top_doc = list(hms_db["hospital_purchase_returns"].find(
        {"purchase_return_bill_no": {"$regex": f"^{prefix}"}},
        {"purchase_return_bill_no": 1}
    ).sort("purchase_return_bill_no", DESCENDING).limit(1))
    max_seq = 0
    if top_doc:
        try:
            seq = int(str(top_doc[0].get("purchase_return_bill_no", "")).split("/")[-1])
            if seq > max_seq:
                max_seq = seq
        except (ValueError, IndexError):
            pass
    return f"{prefix}{str(max_seq + 1).zfill(6)}"


# ─────────────────────────────────────────────────────────────────────────────
# GRN ITEMS  — fetch PharmacyStock rows for a given GRN number
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_grn_items(request):
    """
    Returns all PharmacyStock rows for the given GRN, enriched with
    item_name (from PharmacyItem), total_stock (raw), and computed available_qty.
    """
    grn_number = request.query_params.get("grn_number", "").strip()
    vendor_id  = request.query_params.get("vendor_id", "").strip()

    if not grn_number:
        return Response({"success": False, "error": "grn_number is required"}, status=400)

    request_data = request.data if hasattr(request, "data") else request.POST
    hospital_code, branch_code, outlet_code, user_id = _get_auth(request, request_data)

    try:
        client, hms_db = get_hms_db()

        if vendor_id:
            try:
                v_id = int(vendor_id)
            except ValueError:
                v_id = None
                
            if v_id is not None:
                grn_doc = hms_db["hospital_grn"].find_one({
                    "hospital_code": hospital_code,
                    "branch_code": branch_code,
                    "grn_number": grn_number
                })
                if not grn_doc:
                    return Response({"success": False, "error": f"GRN {grn_number} not found in records."})
                
                db_vendor_id = str(grn_doc.get("vendor_id", "")).strip()
                if db_vendor_id != str(v_id):
                    def _vname(vid_str):
                        vdoc = hms_db["hospital_vendor"].find_one({
                            "hospital_code": hospital_code, "branch_code": branch_code, "vendor_id": str(vid_str)
                        })
                        if vdoc:
                            return vdoc.get("name") or vdoc.get("vendor_name") or vid_str
                        return vid_str
                    db_vname = _vname(db_vendor_id)
                    sel_vname = _vname(str(v_id))
                    return Response({"success": False, "error": f"GRN {grn_number} belongs to vendor '{db_vname}', not the selected vendor ('{sel_vname}')!"})

        stock_docs = list(hms_db["hospital_pharmacystock"].find({
            "hospital_code": hospital_code,
            "branch_code": branch_code,
            "grn_number": grn_number,
        }))

        item_ids = list({_int(s.get("item_id")) for s in stock_docs if s.get("item_id") is not None})
        item_map = {}
        if item_ids:
            for itm in hms_db["hospital_pharmacyitem"].find({"item_id": {"$in": item_ids}}, {"item_id": 1, "item_name": 1}):
                item_map[str(itm.get("item_id"))] = itm.get("item_name", "")

        results = []
        for s in stock_docs:
            total     = _int(s.get("total_stock", 0))
            sold      = _int(s.get("sold_quantity", 0))
            trans_out = _int(s.get("transferred_out_quantity", 0))
            grn_ret   = _int(s.get("grn_return_quantity", 0))
            blocked   = _int(s.get("blocked_quantity", 0))
            sales_ret = _int(s.get("sales_return_quantity", 0))
            available = total - sold - trans_out - grn_ret - blocked + sales_ret

            iid = str(s.get("item_id", ""))
            hsn = str(s.get("hsn_code", "") or s.get("hsn", "") or "")

            exp = s.get("expiry_date")
            try:
                exp_str = exp.isoformat() if hasattr(exp, "isoformat") else str(exp) if exp else None
            except Exception:
                exp_str = None

            results.append({
                "stock_id":      s.get("stock_id"),
                "item_id":       iid,
                "item_name":     item_map.get(iid, f"Item #{iid}"),
                "hsn_code":      hsn,
                "batch_number":  str(s.get("batch_number", "") or ""),
                "expiry_date":   exp_str,
                "mrp":           str(_dec(s.get("mrp", 0))),
                "Selling_Price": str(_dec(s.get("Selling_Price") or s.get("selling_price") or 0)),
                "total_stock":   total,
                "available_qty": available,
                "outlet_code":   str(s.get("outlet_code", "") or ""),
                "grn_number":    grn_number,
            })

        if not results:
            if hms_db["hospital_grn"].find_one({"hospital_code": hospital_code, "branch_code": branch_code, "grn_number": grn_number}):
                return Response({"success": False, "error": f"GRN {grn_number} exists, but no items found in PharmacyStock. Stock may not have been updated."})

        return Response({"success": True, "data": results})

    except Exception as e:
        logger.error(f"[get_grn_items] Error: {e}", exc_info=True)
        return Response({"success": False, "error": str(e)}, status=500)


def _enrich_purchase_returns_batch(returns_list: list, hospital_code: str, branch_code: str) -> list:
    if not returns_list:
        return returns_list

    client, hms_db = get_hms_db()

    # Collect item IDs and GRN numbers
    item_ids = set()
    grn_numbers = set()

    for row in returns_list:
        items = row.get("items", [])
        if isinstance(items, str):
            try:
                items = json.loads(items)
                row["items"] = items
            except Exception:
                row["items"] = []
                items = []

        if isinstance(items, list):
            for item in items:
                iid = str(item.get("item_id", ""))
                if iid.isdigit():
                    item_ids.add(int(iid))

        if row.get("grn_number"):
            for g in str(row.get("grn_number", "")).split(","):
                g = g.strip()
                if g:
                    grn_numbers.add(g)

    # Batch item name resolution
    name_map = {}
    if item_ids:
        for itm in hms_db["hospital_pharmacyitem"].find({"item_id": {"$in": list(item_ids)}}, {"item_id": 1, "item_name": 1}):
            name_map[str(itm.get("item_id"))] = itm.get("item_name", "")

    # Batch GRN / Vendor resolution
    grn_to_vendor_id = {}
    grn_to_category = {}
    vendor_ids = set()

    if grn_numbers:
        for grn in hms_db["hospital_grn"].find({"grn_number": {"$in": list(grn_numbers)}}, {"grn_number": 1, "vendor_id": 1, "purchase_category": 1}):
            vid = str(grn.get("vendor_id", "") or "").strip()
            if vid:
                vendor_ids.add(vid)
                grn_to_vendor_id[grn.get("grn_number")] = vid
            cat = str(grn.get("purchase_category", "") or "").strip()
            if cat:
                grn_to_category[grn.get("grn_number")] = cat

    vendor_name_map = {}
    if vendor_ids:
        for v in hms_db["hospital_vendor"].find({"vendor_id": {"$in": list(vendor_ids)}}, {"vendor_id": 1, "name": 1, "vendor_name": 1}):
            vendor_name_map[str(v.get("vendor_id"))] = v.get("name") or v.get("vendor_name") or str(v.get("vendor_id"))

    # Enrich rows
    for row in returns_list:
        items = row.get("items", [])
        if isinstance(items, list):
            for itm in items:
                if not itm.get("item_name") or str(itm.get("item_name")).startswith("Item #"):
                    iid = str(itm.get("item_id", ""))
                    if iid in name_map:
                        itm["item_name"] = name_map[iid]

        grn_list = [g.strip() for g in str(row.get("grn_number", "")).split(",") if g.strip()]
        v_names = []
        p_categories = []
        for g in grn_list:
            vid = grn_to_vendor_id.get(g)
            if vid and vid in vendor_name_map:
                vname = vendor_name_map[vid]
                if vname not in v_names:
                    v_names.append(vname)
            cat = grn_to_category.get(g)
            if cat and cat not in p_categories:
                p_categories.append(cat)

        if v_names:
            row["vendor_name"] = ", ".join(v_names)
        if p_categories:
            row["purchase_category"] = ", ".join(p_categories)

    return returns_list


# ─────────────────────────────────────────────────────────────────────────────
# PURCHASE RETURN  (GET list / GET single / POST create / PUT update status)
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET", "POST", "PUT"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def purchase_return_view(request, pk=None):

    request_data = request.data if hasattr(request, "data") else request.POST
    hospital_code, branch_code, outlet_code, user_id = _get_auth(request, request_data)

    # ─────────────────────────────────────────────────────────────────────────
    # GET
    # ─────────────────────────────────────────────────────────────────────────
    if request.method == "GET":
        try:
            if pk:
                try:
                    pr = PurchaseReturn.objects.get(
                        purchase_return_bill_no=pk,
                        hospital_code=hospital_code,
                        branch_code=branch_code,
                    )
                    enriched = _enrich_purchase_returns_batch([PurchaseReturnSerializer(pr).data], hospital_code, branch_code)[0]
                    return Response({"success": True, "data": enriched})
                except PurchaseReturn.DoesNotExist:
                    return Response({"success": False, "error": "Record not found"}, status=404)

            filter_q = {}
            if hospital_code and hospital_code != "system":
                filter_q["hospital_code"] = hospital_code
            if branch_code and branch_code != "system":
                filter_q["branch_code"] = branch_code
            if outlet_code:
                filter_q["outlet_code"] = outlet_code

            ref_no = request.query_params.get("purchase_return_bill_no", "").strip()
            if ref_no:
                filter_q["purchase_return_bill_no"] = ref_no

            status_filter = request.query_params.get("status", "").strip()
            if status_filter:
                filter_q["status"] = status_filter

            search = request.query_params.get("search", "").strip()
            if search:
                reg = {"$regex": re.escape(search), "$options": "i"}
                filter_q["$or"] = [
                    {"purchase_return_bill_no": reg},
                    {"grn_number": reg},
                    {"status": reg},
                    {"return_remark": reg}
                ]

            filter_q = apply_date_filter(filter_q, request, "created_date")

            def _enrich_page(data_list):
                return _enrich_purchase_returns_batch(data_list, hospital_code, branch_code)

            return Response(paginate_mongo_query(
                "hospital_purchase_returns",
                filter_q,
                sort=[("created_date", DESCENDING)],
                request=request,
                enrich_fn=_enrich_page
            ))

        except Exception as e:
            logger.error("[purchase_return GET] %s", e, exc_info=True)
            return Response({"success": False, "error": str(e)}, status=500)

    # ─────────────────────────────────────────────────────────────────────────
    # POST — Create Purchase Return
    # ─────────────────────────────────────────────────────────────────────────
    if request.method == "POST":
        data = request_data

        outlet_code_body = str(data.get("outlet_code") or outlet_code or "").strip()
        outlet_code_body = str(data.get("outlet_code") or outlet_code or "").strip()

        raw_items = data.get("items", [])
        if isinstance(raw_items, str):
            try:
                raw_items = json.loads(raw_items)
            except Exception:
                raw_items = []

        if not raw_items:
            return Response({"success": False, "error": "At least one item is required"}, status=400)

        grn_numbers = set(str(item.get("grn_number", "")).strip() for item in raw_items)
        if "" in grn_numbers: grn_numbers.remove("")

        all_stocks = list(PharmacyStock.objects.filter(
            hospital_code=hospital_code,
            branch_code=branch_code,
            grn_number__in=grn_numbers,
        ))

        # Build item_name map for storing names in the document
        item_ids_in_request = {str(item.get("item_id", "")) for item in raw_items}
        item_name_map = {
            str(itm.item_id): getattr(itm, "item_name", "") or ""
            for itm in PharmacyItem.objects.filter(
                hospital_code=hospital_code,
                branch_code=branch_code,
                item_id__in=[int(i) for i in item_ids_in_request if str(i).isdigit()],
            )
        }

        errors = []
        processed_items = []
        total_return_amount = Decimal("0.00")

        for idx, item in enumerate(raw_items):
            item_id         = str(item.get("item_id",         "")).strip()
            stock_id        = str(item.get("stock_id",        "")).strip()
            batch_number    = str(item.get("batch_number",    "")).strip()
            return_qty      = _int(item.get("return_qty",     0))
            price           = _dec(item.get("price",          0))
            cause_of_return = str(item.get("cause_of_return", "")).strip()

            if cause_of_return not in CAUSE_OF_RETURN_CHOICES:
                errors.append(
                    f"Item {idx + 1}: cause_of_return must be one of {CAUSE_OF_RETURN_CHOICES}"
                )
                continue

            if return_qty <= 0:
                errors.append(f"Item {idx + 1}: return_qty must be > 0")
                continue

            if price < 0:
                errors.append(f"Item {idx + 1}: price must be >= 0")
                continue

            source = None
            for s in all_stocks:
                if stock_id and str(getattr(s, "stock_id", "")) == stock_id:
                    source = s
                    break
                if (
                    str(getattr(s, "item_id",      "")) == item_id
                    and str(getattr(s, "batch_number", "")).strip() == batch_number
                ):
                    source = s
                    break

            if source is None:
                errors.append(
                    f"Item {idx + 1}: stock record not found "
                    f"(item_id={item_id}, batch={batch_number})"
                )
                continue

            available = _calc_available(source)
            if return_qty > available:
                errors.append(
                    f"Item {idx + 1}: requested {return_qty}, only {available} available"
                )
                continue

            line_total = price * Decimal(str(return_qty))
            total_return_amount += line_total

            processed_items.append({
                "item_id":         _int(item_id),
                "item_name":       item_name_map.get(item_id, f"Item #{item_id}"),
                "stock_id":        _int(getattr(source, "stock_id", 0)),
                "batch_number":    batch_number,
                "return_qty":      return_qty,
                "price":           float(price),
                "cause_of_return": cause_of_return,
                "grn_number":      str(item.get("grn_number", "")).strip(),
            })

        if errors:
            return Response({"success": False, "error": errors}, status=400)

        bill_no = _next_purchase_return_bill_no()
        now     = timezone.now()

        pr = PurchaseReturn.objects.create(
            created_by=user_id,
            created_date=now,
            lastmodified_by=user_id,
            lastmodified_date=now,
            hospital_code=hospital_code,
            branch_code=branch_code,
            outlet_code=outlet_code_body,
            grn_number=",".join(grn_numbers),
            items=processed_items,
            purchase_return_amount=str(total_return_amount.quantize(Decimal("0.01"))),
            purchase_return_bill_date=now,
            purchase_return_bill_no=bill_no,
            status="Pending",
            return_remark=str(data.get("return_remark", "")).strip()
        )

        return Response({
            "success": True,
            "message": "Purchase return created successfully",
            "data":    PurchaseReturnSerializer(pr).data,
        }, status=201)

    # ─────────────────────────────────────────────────────────────────────────
    # PUT — Update Status
    # ─────────────────────────────────────────────────────────────────────────
    if request.method == "PUT":
        data       = request_data
        bill_no    = str(data.get("purchase_return_bill_no", pk or "")).strip()
        new_status = str(data.get("status", "")).strip()

        if not bill_no:
            return Response({"success": False, "error": "purchase_return_bill_no is required"}, status=400)

        if new_status not in PURCHASE_RETURN_STATUS_CHOICES:
            return Response(
                {"success": False, "error": f"status must be one of {PURCHASE_RETURN_STATUS_CHOICES}"},
                status=400,
            )

        try:
            pr = PurchaseReturn.objects.get(
                purchase_return_bill_no=bill_no,
                hospital_code=hospital_code,
                branch_code=branch_code
            )
            if new_status == "Returned" and pr.status != "Returned":
                # Parse items if it's a string, else use directly
                items_data = pr.items
                if isinstance(items_data, str):
                    import json
                    try:
                        items_data = json.loads(items_data)
                    except json.JSONDecodeError:
                        items_data = []
                
                # Update PharmacyStock for each item
                for item in items_data:
                    stock_id = item.get("stock_id")
                    ret_qty = int(item.get("return_qty", 0))
                    
                    if stock_id and ret_qty > 0:
                        try:
                            stock_id = int(stock_id)
                        except ValueError:
                            pass
                        try:
                            client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
                            db = client.HMS
                            db.hospital_pharmacystock.update_one(
                                {"stock_id": stock_id},
                                {"$inc": {"grn_return_quantity": ret_qty}}
                            )
                        except Exception as e:
                            logger.error(f"Error updating stock: {e}")

            try:
                client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
                db = client.HMS
                db.hospital_purchasereturn.update_one(
                    {"purchase_return_bill_no": bill_no},
                    {"$set": {
                        "status": new_status,
                        "lastmodified_by": user_id,
                        "lastmodified_date": timezone.now()
                    }}
                )
            except Exception as e:
                logger.error(f"Error updating purchase return: {e}")
                
            pr.status = new_status
            return Response({
                "success": True,
                "message": f"Status updated to '{new_status}'",
                "data":    PurchaseReturnSerializer(pr).data,
            })
        except PurchaseReturn.DoesNotExist:
            return Response({"success": False, "error": "Record not found"}, status=404)