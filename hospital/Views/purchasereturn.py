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

def _next_purchase_return_bill_no():
    prefix = "2627/"
    max_seq = 0
    for row in PurchaseReturn.objects.filter(purchase_return_bill_no__startswith=prefix):
        ref = str(getattr(row, "purchase_return_bill_no", "")).strip()
        if ref.startswith(prefix):
            try:
                seq = int(ref.split("/")[-1])
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

    available_qty formula:
        total_stock - sold_quantity - transferred_out_quantity
        - blocked_quantity - grn_return_quantity + sales_return_quantity
    """
    grn_number = request.query_params.get("grn_number", "").strip()
    vendor_id  = request.query_params.get("vendor_id", "").strip()

    if not grn_number:
        return Response({"success": False, "error": "grn_number is required"}, status=400)

    request_data = request.data if hasattr(request, "data") else request.POST
    hospital_code, branch_code, outlet_code, user_id = _get_auth(request, request_data)

    try:
        if vendor_id:
            try:
                v_id = int(vendor_id)
            except ValueError:
                v_id = None
                
            if v_id is not None:
                # Need to use hospital.models.GRN directly instead of inventory.GRN to avoid ImportError if circular
                from .inventory import GRN
                # Fetch the GRN object to avoid strict type filtering issues with vendor_id
                grn_obj = GRN.objects.filter(hospital_code=hospital_code, branch_code=branch_code, grn_number=grn_number).first()
                if not grn_obj:
                    return Response({"success": False, "error": f"GRN {grn_number} not found in records."})
                
                # Check vendor_id manually (cast to string to safely compare)
                db_vendor_id = str(getattr(grn_obj, "vendor_id", "")).strip()
                if db_vendor_id != str(v_id):
                    # Resolve both vendor names for a clearer error                                                                           
                    from ..models import Vendor as VendorModel
                    def _vname(vid_str):
                        try:
                            vobj = VendorModel.objects.filter(
                                hospital_code=hospital_code, branch_code=branch_code, vendor_id=vid_str
                            ).first()
                            if vobj:
                                return getattr(vobj, "name", None) or getattr(vobj, "vendor_name", None) or vid_str
                        except Exception:
                            pass
                        return vid_str
                    db_vname = _vname(db_vendor_id)
                    sel_vname = _vname(str(v_id))
                    return Response({"success": False, "error": f"GRN {grn_number} belongs to vendor '{db_vname}', not the selected vendor ('{sel_vname}')!"})

        stock_qs = PharmacyStock.objects.filter(
            hospital_code=hospital_code,
            branch_code=branch_code,
            grn_number=grn_number,
        )

        item_ids = sorted(
            {str(getattr(s, "item_id", "")) for s in stock_qs}
        )
        item_map = {
            str(itm.item_id): getattr(itm, "item_name", "") or ""
            for itm in PharmacyItem.objects.filter(
                hospital_code=hospital_code,
                branch_code=branch_code,
                item_id__in=[int(i) for i in item_ids if str(i).isdigit()],
            )
        }

        results = []
        for s in stock_qs:
            available = _calc_available(s)
            iid       = str(getattr(s, "item_id", ""))

            # Try both field names that might hold the HSN code
            hsn = (
                str(getattr(s, "hsn_code", "") or "")
                or str(getattr(s, "hsn",      "") or "")
            )

            exp = getattr(s, "expiry_date", None)
            try:
                exp_str = exp.isoformat() if hasattr(exp, "isoformat") else str(exp) if exp else None
            except Exception:
                exp_str = None

            results.append({
                "stock_id":      getattr(s, "stock_id",      None),
                "item_id":       iid,
                "item_name":     item_map.get(iid, f"Item #{iid}"),
                "hsn_code":      hsn,
                "batch_number":  str(getattr(s, "batch_number",  "") or ""),
                "expiry_date":   exp_str,
                "mrp":           str(_dec(getattr(s, "mrp",          0))),
                "Selling_Price": str(_dec(getattr(s, "Selling_Price", 0))),
                # total_stock: raw value from collection (displayed as "Batch Stock")
                "total_stock":   _int(getattr(s, "total_stock", 0)),
                # available_qty: computed using the formula
                "available_qty": available,
                "outlet_code":   str(getattr(s, "outlet_code", "") or ""),
                "grn_number":    grn_number,
            })

        if not results:
            # Check if it exists in GRN
            from .inventory import GRN
            if GRN.objects.filter(hospital_code=hospital_code, branch_code=branch_code, grn_number=grn_number).exists():
                return Response({"success": False, "error": f"GRN {grn_number} exists, but no items found in PharmacyStock. Stock may not have been updated."})

        return Response({"success": True, "data": results})

    except Exception as e:
        logger.error(f"[get_grn_items] Error: {e}", exc_info=True)
        return Response({"success": False, "error": str(e)}, status=500)


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

        from_date = request.query_params.get("from_date", "")
        to_date   = request.query_params.get("to_date",   "")
        ref_no    = request.query_params.get("purchase_return_bill_no", "")

        if pk:
            doc = PurchaseReturn.objects.filter(
                purchase_return_bill_no=pk,
                hospital_code=hospital_code,
                branch_code=branch_code,
            ).first()
            if not doc:
                return Response({"success": False, "error": "Record not found"}, status=404)
            return Response({"success": True, "data": PurchaseReturnSerializer(doc).data})

        query = {
            "hospital_code": hospital_code,
            "branch_code":   branch_code,
        }
        if outlet_code:
            query["outlet_code"] = outlet_code
        if ref_no:
            query["purchase_return_bill_no"] = ref_no
        
        status_filter = request.query_params.get("status", "")
        if status_filter:
            query["status"] = status_filter

        qs = PurchaseReturn.objects.filter(**query).order_by("-created_date")

        from datetime import datetime
        if from_date:
            try:
                fd = datetime.strptime(from_date, "%Y-%m-%d").replace(hour=0, minute=0, second=0, microsecond=0)
                qs = qs.filter(purchase_return_bill_date__gte=fd)
            except ValueError:
                pass
        if to_date:
            try:
                td = datetime.strptime(to_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, microsecond=999999)
                qs = qs.filter(purchase_return_bill_date__lte=td)
            except ValueError:
                pass

        serializer = PurchaseReturnSerializer(qs, many=True)
        data_out = serializer.data

        # Patch missing item_names dynamically
        item_ids_to_fetch = set()
        for row in data_out:
            items_list = row.get("items")
            if isinstance(items_list, str):
                import json
                try:
                    items_list = json.loads(items_list)
                    row["items"] = items_list
                except:
                    continue
            if isinstance(items_list, list):
                for item in items_list:
                    if not item.get("item_name") or str(item.get("item_name")).startswith("Item #"):
                        iid = str(item.get("item_id", ""))
                        if iid.isdigit():
                            item_ids_to_fetch.add(int(iid))

        if item_ids_to_fetch:
            name_map = {
                str(itm.item_id): getattr(itm, "item_name", "") or ""
                for itm in PharmacyItem.objects.filter(
                    hospital_code=hospital_code,
                    branch_code=branch_code,
                    item_id__in=list(item_ids_to_fetch)
                )
            }
            for row in data_out:
                items_list = row.get("items")
                if isinstance(items_list, list):
                    for item in items_list:
                        if not item.get("item_name") or str(item.get("item_name")).startswith("Item #"):
                            iid = str(item.get("item_id", ""))
                            if iid in name_map:
                                item["item_name"] = name_map[iid]

        # Fetch vendor_names for each GRN
        grn_numbers_to_fetch = set()
        for row in data_out:
            if row.get("grn_number"):
                for g in str(row.get("grn_number", "")).split(","):
                    g = g.strip()
                    if g:
                        grn_numbers_to_fetch.add(g)
        
        if grn_numbers_to_fetch:
            grns = GRN.objects.filter(
                hospital_code=hospital_code,
                branch_code=branch_code,
                grn_number__in=list(grn_numbers_to_fetch)
            )
            vendor_ids = set()
            grn_to_vendor_id = {}
            grn_to_purchase_category = {}
            for grn in grns:
                v_id = str(getattr(grn, "vendor_id", ""))
                if v_id:
                    vendor_ids.add(v_id)
                    grn_to_vendor_id[grn.grn_number] = v_id
                cat = str(getattr(grn, "purchase_category", ""))
                if cat:
                    grn_to_purchase_category[grn.grn_number] = cat
            
            vendor_name_map = {}
            if vendor_ids:
                vendors = Vendor.objects.filter(
                    hospital_code=hospital_code,
                    branch_code=branch_code,
                    vendor_id__in=list(vendor_ids)
                )
                for v in vendors:
                    vendor_name_map[str(v.vendor_id)] = getattr(v, "name", "") or getattr(v, "vendor_name", "") or str(v.vendor_id)
            
            for row in data_out:
                grn_list = [g.strip() for g in str(row.get("grn_number", "")).split(",") if g.strip()]
                v_names = []
                p_categories = []
                for g in grn_list:
                    vid = grn_to_vendor_id.get(g)
                    if vid and vid in vendor_name_map:
                        if vendor_name_map[vid] not in v_names:
                            v_names.append(vendor_name_map[vid])
                    cat = grn_to_purchase_category.get(g)
                    if cat and cat not in p_categories:
                        p_categories.append(cat)
                
                if v_names:
                    row["vendor_name"] = ", ".join(v_names)
                if p_categories:
                    row["purchase_category"] = ", ".join(p_categories)

        return Response({
            "success": True,
            "count":   qs.count(),
            "data":    data_out,
        })

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