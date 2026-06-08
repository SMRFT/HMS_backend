from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from ..models import PharmacyItem, PharmacyStock, PhysicalStockEntry
from ..serializers import PhysicalStockEntrySerializer
from pyauth.auth import HasRoleAndDataPermission


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
    GET /pharmacy-stock-batches/?item_name=<search>

    Search PharmacyItem by name (case-insensitive contains).
    For each matching item, return all active PharmacyStock batches with
    the computed available stock.
    """
    _, hospital_code, branch_code = _get_auth(request)
    item_name_query = request.query_params.get("item_name", "").strip()

    if not item_name_query:
        return Response({"error": "item_name query parameter is required"}, status=400)

    try:
        # ── Search PharmacyItem ───────────────────────────────────────────
        all_items = PharmacyItem.objects.all()
        matched_items = [
            i for i in all_items
            if i.is_active
            and getattr(i, "hospital_code", None) == hospital_code
            and getattr(i, "branch_code", None) == branch_code
            and item_name_query.lower() in (i.item_name or "").lower()
        ]

        if not matched_items:
            return Response([], status=200)

        result = []

        for item in matched_items:
            # ── Fetch batches for this item ───────────────────────────────
            all_stocks = PharmacyStock.objects.all()
            batches = [
                s for s in all_stocks
                if getattr(s, "item_id", None) == item.item_id
                and getattr(s, "hospital_code", None) == hospital_code
                and getattr(s, "branch_code", None) == branch_code
            ]

            for stock in batches:
                available = _compute_available_stock(stock)
                result.append({
                    "item_id":        item.item_id,
                    "item_name":      item.item_name,
                    "stock_id":       getattr(stock, "stock_id", None),
                    "batch_number":   stock.batch_number,
                    "computer_stock": available,
                    "expiry_date":    str(stock.expiry_date) if stock.expiry_date else None,
                    "mrp":            str(stock.mrp) if stock.mrp else None,
                })

        return Response(result, status=200)

    except Exception as e:
        return Response({"error": str(e)}, status=500)


# ─── 2. Physical Stock Entry CRUD ─────────────────────────────────────────────

@api_view(["GET", "POST", "PUT", "DELETE"])
@permission_classes([HasRoleAndDataPermission])
def physical_stock_entry_view(request, pk=None):
    """
    CRUD for PhysicalStockEntry.

    POST accepts either a single object or a list (bulk save).
    """
    employee_id, hospital_code, branch_code = _get_auth(request)

    # ── GET ──────────────────────────────────────────────────────────────
    if request.method == "GET":
        try:
            if pk:
                entry = PhysicalStockEntry.objects.get(entry_id=pk)
                if (
                    not entry.is_active or
                    entry.hospital_code != hospital_code or
                    entry.branch_code != branch_code
                ):
                    return Response({"error": "Entry not found"}, status=404)
                return Response(PhysicalStockEntrySerializer(entry).data)

            all_entries = PhysicalStockEntry.objects.all()
            entries = [
                e for e in all_entries
                if e.is_active
                and e.hospital_code == hospital_code
                and e.branch_code == branch_code
            ]
            return Response(PhysicalStockEntrySerializer(entries, many=True).data)

        except Exception as e:
            return Response({"error": str(e)}, status=500)

    # ── POST (single or bulk) ────────────────────────────────────────────
    if request.method == "POST":
        try:
            data = request.data

            # Support bulk: list of entries
            is_bulk = isinstance(data, list)
            payload_list = data if is_bulk else [data]

            saved = []
            errors = []

            for payload in payload_list:
                item_payload = payload.copy() if hasattr(payload, "copy") else dict(payload)
                item_payload["hospital_code"] = hospital_code
                item_payload["branch_code"]   = branch_code

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

            if errors:
                return Response({"saved": saved, "errors": errors}, status=207)

            return Response(saved if is_bulk else saved[0], status=201)

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
                serializer.save(
                    lastmodified_by=employee_id,
                    lastmodified_date=timezone.now(),
                )
                return Response(serializer.data)
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

    Body for PUT:
        { "action": "approve" | "reject", "approval_notes": "..." }
    """
    employee_id, hospital_code, branch_code = _get_auth(request)

    # ── GET ──────────────────────────────────────────────────────────────
    if request.method == "GET":
        try:
            all_entries = PhysicalStockEntry.objects.all()
            entries = [
                e for e in all_entries
                if e.is_active
                and e.hospital_code == hospital_code
                and e.branch_code == branch_code
            ]
            return Response(PhysicalStockEntrySerializer(entries, many=True).data)
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
                return Response(
                    {"message": "Entry approved", "entry_id": pk},
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