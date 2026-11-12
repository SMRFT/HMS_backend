import re
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from ..models import PharmacyItem, PharmacyStock, PhysicalStockEntry
from ..serializers import PhysicalStockEntrySerializer
from pyauth.auth import HasRoleAndDataPermission
from .mongo_utils import get_hms_db, paginate_queryset, paginate_mongo_query, clean_doc, clean_docs, apply_date_filter, enrich_employee_names
from pymongo import ASCENDING, DESCENDING
from django.db.models import Q


# ─── helpers ──────────────────────────────────────────────────────────────────

def _get_auth(request):
    """Extract tenant headers from request (data or headers)."""
    employee_id = (
        request.data.get("auth-user-id") or
        request.headers.get("auth-user-id") or
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
    return employee_id, hospital_code, branch_code


def _compute_available_stock(stock):
    """
    Available Stock = total_stock
                    - sold_quantity
                    - transferred_out_quantity
                    - grn_return_quantity
                    - blocked_quantity
                    + sales_return_quantity
    """
    return (
        (getattr(stock, "total_stock", 0) or 0)
        - (getattr(stock, "sold_quantity", 0) or 0)
        - (getattr(stock, "transferred_out_quantity", 0) or 0)
        - (getattr(stock, "grn_return_quantity", 0) or 0)
        - (getattr(stock, "blocked_quantity", 0) or 0)
        + (getattr(stock, "sales_return_quantity", 0) or 0)
    )


# ─── 1. Batch search view ─────────────────────────────────────────────────────

@api_view(["GET"])
# @permission_classes([HasRoleAndDataPermission])
def pharmacy_stock_batches_view(request):
    """
    GET /pharmacy-stock-batches/?item_id=<id>&item_name=<search>
    Returns active GRN batches sorted by most recently added date / stock_id descending.
    """
    _, hospital_code, branch_code = _get_auth(request)
    item_id_param = request.query_params.get("item_id", "").strip()
    item_name_query = request.query_params.get("item_name", "").strip()

    if not item_id_param and not item_name_query:
        return Response({"error": "item_id or item_name query parameter is required"}, status=400)

    try:
        client, hms_db = get_hms_db()

        item_filter = {"is_active": True}
        if hospital_code and hospital_code != "system":
            item_filter["hospital_code"] = hospital_code
        if branch_code and branch_code != "system":
            item_filter["branch_code"] = branch_code

        if item_id_param:
            item_filter["item_id"] = int(item_id_param) if item_id_param.isdigit() else item_id_param
        else:
            clean_name = re.escape(item_name_query.strip())
            item_filter["item_name"] = {"$regex": f"^{clean_name}", "$options": "i"}

        matched_items = list(
            hms_db["hospital_pharmacyitem"]
            .find(item_filter, {"item_id": 1, "item_name": 1, "item_last_name": 1})
            .sort("item_name", 1)
            .limit(100)
        )

        if not matched_items:
            return Response([], status=200)

        item_map = {
            m.get("item_id"): " ".join(filter(None, [m.get("item_name"), m.get("item_last_name")])).strip()
            for m in matched_items
        }
        matched_ids = list(item_map.keys())

        stock_filter = {
            "item_id": {"$in": matched_ids},
            "stock_type": "grn",
            "is_active": {"$ne": False},
        }
        if hospital_code and hospital_code != "system":
            stock_filter["hospital_code"] = hospital_code
        if branch_code and branch_code != "system":
            stock_filter["branch_code"] = branch_code

        batches = list(hms_db["hospital_pharmacystock"].find(stock_filter))

        # Enrich GRN dates for recently-added sorting when stock.created_date is null
        grn_numbers = list({str(b.get("grn_number")).strip() for b in batches if b.get("grn_number")})
        grn_date_map = {}
        if grn_numbers:
            grn_q = {"grn_number": {"$in": grn_numbers}}
            if hospital_code and hospital_code != "system":
                grn_q["hospital_code"] = hospital_code
            if branch_code and branch_code != "system":
                grn_q["branch_code"] = branch_code
            for g in hms_db["hospital_grn"].find(grn_q, {"grn_number": 1, "date": 1, "created_date": 1}):
                gn = str(g.get("grn_number") or "").strip()
                gd = g.get("created_date") or g.get("date")
                if gn and gd:
                    grn_date_map[gn] = gd

        def _sort_ts(val):
            if val is None:
                return ""
            return str(val)

        result = []
        for stock in batches:
            total     = stock.get("total_stock", 0) or 0
            sold      = stock.get("sold_quantity", 0) or 0
            trans_out = stock.get("transferred_out_quantity", 0) or 0
            grn_ret   = stock.get("grn_return_quantity", 0) or 0
            blocked   = stock.get("blocked_quantity", 0) or 0
            sales_ret = stock.get("sales_return_quantity", 0) or 0
            available = total - sold - trans_out - grn_ret - blocked + sales_ret

            iid = stock.get("item_id")
            gn = str(stock.get("grn_number") or "").strip()
            batch_date = stock.get("created_date") or grn_date_map.get(gn)

            result.append({
                "item_id":        iid,
                "item_name":      str(item_map.get(iid, f"Item #{iid}")).upper(),
                "stock_id":       stock.get("stock_id"),
                "batch_number":   stock.get("batch_number", ""),
                "grn_number":     gn,
                "outlet_code":    stock.get("outlet_code", ""),
                "total_stock":    total,
                "computer_stock": available,
                "expiry_date":    str(stock.get("expiry_date")) if stock.get("expiry_date") else None,
                "mrp":            str(stock.get("mrp")) if stock.get("mrp") is not None else None,
                "grn_date":       str(batch_date)[:10] if batch_date else None,
                "_sort_date":     _sort_ts(batch_date),
            })

        result.sort(
            key=lambda x: (
                x.get("_sort_date") or "",
                int(x.get("stock_id") or 0),
            ),
            reverse=True,
        )
        for row in result:
            row.pop("_sort_date", None)

        return Response(result, status=200)

    except Exception as e:
        return Response({"error": str(e)}, status=500)


def _update_pharmacy_stock_total(hms_db, stock_id, item_id, batch_number, hospital_code, branch_code, physical_stock, employee_id):
    """
    Update total_stock in hospital_pharmacystock when physical stock is saved.
    Returns (updated_count, new_computer_stock).
    """
    base_q = {}
    if hospital_code and hospital_code != "system":
        base_q["hospital_code"] = hospital_code
    if branch_code and branch_code != "system":
        base_q["branch_code"] = branch_code

    target_q = None
    if stock_id not in (None, ""):
        target_q = {**base_q, "stock_id": int(stock_id) if str(stock_id).isdigit() else stock_id}
    elif item_id not in (None, "") and batch_number:
        target_q = {
            **base_q,
            "item_id": int(item_id) if str(item_id).isdigit() else item_id,
            "batch_number": str(batch_number),
        }

    if not target_q:
        return 0, int(physical_stock)

    doc = hms_db["hospital_pharmacystock"].find_one(target_q)
    if not doc and base_q:
        # Fallback without tenant filter if stock_id is globally unique
        fallback_q = {"stock_id": target_q["stock_id"]} if "stock_id" in target_q else {
            "item_id": target_q["item_id"], "batch_number": target_q["batch_number"]
        }
        doc = hms_db["hospital_pharmacystock"].find_one(fallback_q)
        if doc:
            target_q = {"_id": doc["_id"]}

    new_total = int(physical_stock)
    res = hms_db["hospital_pharmacystock"].update_one(
        target_q,
        {
            "$set": {
                "total_stock": new_total,
                "lastmodified_by": employee_id,
                "lastmodified_date": timezone.now(),
            }
        },
    )

    if doc:
        sold      = doc.get("sold_quantity", 0) or 0
        trans_out = doc.get("transferred_out_quantity", 0) or 0
        grn_ret   = doc.get("grn_return_quantity", 0) or 0
        blocked   = doc.get("blocked_quantity", 0) or 0
        sales_ret = doc.get("sales_return_quantity", 0) or 0
        available = new_total - sold - trans_out - grn_ret - blocked + sales_ret
    else:
        available = new_total

    return res.modified_count or res.matched_count, available


# ─── 2. Physical Stock Entry CRUD ─────────────────────────────────────────────

@api_view(["GET", "POST", "PUT", "DELETE"])
@permission_classes([HasRoleAndDataPermission])
def physical_stock_entry_view(request, pk=None):
    """
    CRUD for PhysicalStockEntry.
    """
    employee_id, hospital_code, branch_code = _get_auth(request)

    # ── GET ──────────────────────────────────────────────────────────────
    if request.method == "GET":
        try:
            if pk:
                try:
                    entry = PhysicalStockEntry.objects.get(
                        entry_id=int(pk) if str(pk).isdigit() else pk,
                        hospital_code=hospital_code,
                        branch_code=branch_code,
                        is_active=True,
                    )
                    return Response(enrich_employee_names(PhysicalStockEntrySerializer(entry).data))
                except PhysicalStockEntry.DoesNotExist:
                    return Response({"error": "Entry not found"}, status=404)

            filter_q = {"is_active": True}
            if hospital_code and hospital_code != "system":
                filter_q["hospital_code"] = hospital_code
            if branch_code and branch_code != "system":
                filter_q["branch_code"] = branch_code

            search = request.GET.get("search", "").strip()
            if search:
                reg = {"$regex": re.escape(search), "$options": "i"}
                filter_q["$or"] = [
                    {"item_name": reg},
                    {"batch_number": reg},
                    {"remarks": reg}
                ]

            filter_q = apply_date_filter(filter_q, request, "stock_date")

            return Response(paginate_mongo_query(
                "hospital_physicalstockentry",
                filter_q,
                sort=[("stock_date", DESCENDING), ("entry_id", DESCENDING)],
                request=request
            ))

        except Exception as e:
            return Response({"error": str(e)}, status=500)

    # ── POST (single or bulk) ────────────────────────────────────────────
    if request.method == "POST":
        try:
            data = request.data
            is_bulk = isinstance(data, list)
            payload_list = data if is_bulk else [data]

            saved = []
            errors = []
            for payload in payload_list:
                item_payload = payload.copy() if hasattr(payload, "copy") else dict(payload)
                item_payload["hospital_code"] = hospital_code
                item_payload["branch_code"]   = branch_code

                try:
                    comp_val = int(item_payload.get("computer_stock") or 0)
                    phys_val = int(item_payload.get("physical_stock") or 0)
                    item_payload["variance"] = phys_val - comp_val
                except (TypeError, ValueError):
                    pass

                serializer = PhysicalStockEntrySerializer(data=item_payload)
                if serializer.is_valid():
                    instance = serializer.save(
                        created_by=employee_id,
                        is_active=True,
                        is_approved=False,
                    )
                    saved.append(PhysicalStockEntrySerializer(instance).data)
                else:
                    errors.append(serializer.errors)

            if errors and not saved:
                return Response({"errors": errors}, status=400)

            return Response(saved if is_bulk else (saved[0] if saved else {}), status=201 if saved else 400)

        except Exception as e:
            return Response({"error": str(e)}, status=500)

    # ── PUT ──────────────────────────────────────────────────────────────
    if request.method == "PUT":
        if not pk:
            return Response({"error": "Entry ID required"}, status=400)
        try:
            entry = PhysicalStockEntry.objects.get(entry_id=pk)
            if (
                not entry.is_active or
                entry.hospital_code != hospital_code or
                entry.branch_code != branch_code
            ):
                return Response({"error": "Entry not found"}, status=404)

            serializer = PhysicalStockEntrySerializer(
                entry, data=request.data, partial=True
            )
            if serializer.is_valid():
                instance = serializer.save(
                    lastmodified_by=employee_id,
                    lastmodified_date=timezone.now(),
                )
                instance.variance = int(instance.physical_stock or 0) - int(instance.computer_stock or 0)
                instance.save()
                return Response(PhysicalStockEntrySerializer(instance).data)
            return Response(serializer.errors, status=400)

        except PhysicalStockEntry.DoesNotExist:
            return Response({"error": "Entry not found"}, status=404)

    # ── DELETE ───────────────────────────────────────────────────────────
    if request.method == "DELETE":
        if not pk:
            return Response({"error": "Entry ID required"}, status=400)
        try:
            entry = PhysicalStockEntry.objects.get(entry_id=pk)
            if (
                not entry.is_active or
                entry.hospital_code != hospital_code or
                entry.branch_code != branch_code
            ):
                return Response({"error": "Entry not found"}, status=404)

            entry.is_active = False
            entry.lastmodified_by = employee_id
            entry.lastmodified_date = timezone.now()
            entry.save()
            return Response({"message": "Deleted successfully"}, status=200)

        except PhysicalStockEntry.DoesNotExist:
            return Response({"error": "Entry not found"}, status=404)


# ─── 3. Approval view ────────────────────────────────────────────────────────

@api_view(["GET", "PUT"])
@permission_classes([HasRoleAndDataPermission])
def physical_stock_approval_view(request, pk=None):
    """
    GET  /physical-stock-approval/      → list all active entries (pending + approved)
    PUT  /physical-stock-approval/<pk>/ → approve or reject an entry
    """
    employee_id, hospital_code, branch_code = _get_auth(request)

    # ── GET ──────────────────────────────────────────────────────────────
    if request.method == "GET":
        try:
            filter_q = {"is_active": True}
            if hospital_code and hospital_code != "system":
                filter_q["hospital_code"] = hospital_code
            if branch_code and branch_code != "system":
                filter_q["branch_code"] = branch_code

            status_param = request.GET.get("status", "").strip()
            if status_param == "approved":
                filter_q["is_approved"] = True
            elif status_param == "pending":
                filter_q["is_approved"] = False

            search = request.GET.get("search", "").strip()
            if search:
                reg = {"$regex": re.escape(search), "$options": "i"}
                filter_q["$or"] = [
                    {"item_name": reg},
                    {"batch_number": reg},
                    {"approval_notes": reg}
                ]

            filter_q = apply_date_filter(filter_q, request, "stock_date")

            return Response(paginate_mongo_query(
                "hospital_physicalstockentry",
                filter_q,
                sort=[("stock_date", DESCENDING), ("entry_id", DESCENDING)],
                request=request
            ))
        except Exception as e:
            return Response({"error": str(e)}, status=500)

    # ── PUT ──────────────────────────────────────────────────────────────
    if request.method == "PUT":
        if not pk:
            return Response({"error": "Entry ID required"}, status=400)
        try:
            entry = PhysicalStockEntry.objects.get(entry_id=pk)
            if (
                not entry.is_active or
                entry.hospital_code != hospital_code or
                entry.branch_code != branch_code
            ):
                return Response({"error": "Entry not found"}, status=404)

            action = request.data.get("action", "").lower()
            notes  = request.data.get("approval_notes", "")

            if action == "approve":
                entry.is_approved     = True
                entry.approved_by     = employee_id
                entry.approved_date   = timezone.now()
                entry.approval_notes  = notes
                entry.lastmodified_by = employee_id
                entry.lastmodified_date = timezone.now()
                entry.save()

                _, hms_db = get_hms_db()
                _, new_available = _update_pharmacy_stock_total(
                    hms_db,
                    entry.stock_id,
                    entry.item_id,
                    entry.batch_number,
                    hospital_code,
                    branch_code,
                    entry.physical_stock,
                    employee_id,
                )

                return Response(
                    {
                        "message": "Entry approved",
                        "entry_id": pk,
                        "total_stock": int(entry.physical_stock or 0),
                        "computer_stock": new_available,
                    },
                    status=200,
                )

            elif action == "reject":
                entry.is_approved     = False
                entry.approved_by     = None
                entry.approved_date   = None
                entry.approval_notes  = notes
                entry.lastmodified_by = employee_id
                entry.lastmodified_date = timezone.now()
                entry.save()
                return Response(
                    {"message": "Entry rejected", "entry_id": pk},
                    status=200,
                )

            else:
                return Response(
                    {"error": "action must be 'approve' or 'reject'"},
                    status=400,
                )

        except PhysicalStockEntry.DoesNotExist:
            return Response({"error": "Entry not found"}, status=404)