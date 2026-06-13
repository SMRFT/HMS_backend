import logging
from datetime import datetime

from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.views.decorators.csrf import csrf_exempt

from pyauth.auth import HasRoleAndDataPermission
from ..models import PurchaseRequisition, PurchaseRequisitionItem
from ..serializers import PurchaseRequisitionSerializer

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _auth(request):
    data = request.data
    return {
        "employee_id":   data.get("auth-user-id")       or request.headers.get("auth-user-id")       or "system",
        "hospital_code": data.get("auth-hospital-code") or request.headers.get("auth-hospital-code") or "system",
        "branch_code":   data.get("auth-branch-code")   or request.headers.get("Branch-Code")        or "system",
    }


def _current_fin_year():
    today   = datetime.today()
    from_yr = today.year if today.month >= 4 else today.year - 1
    return f"{str(from_yr)[-2:]}{str(from_yr + 1)[-2:]}"


def _next_pr_number():
    """PR/<FINYEAR>/<SEQ6>  e.g. PR/2627/000001"""
    fin_year = _current_fin_year()
    prefix   = f"PR/{fin_year}/"
    max_seq  = 0
    for row in PurchaseRequisition.objects.all():
        ref = str(getattr(row, "pr_number", "") or "")
        if ref.startswith(prefix):
            try:
                seq = int(ref.split("/")[-1])
                if seq > max_seq:
                    max_seq = seq
            except (ValueError, IndexError):
                pass
    return f"{prefix}{str(max_seq + 1).zfill(6)}"


def _scope_ok(obj, hospital_code, branch_code):
    return (
        getattr(obj, "hospital_code", None) == hospital_code
        and getattr(obj, "branch_code",   None) == branch_code
    )


def _today_str():
    return datetime.today().strftime("%Y-%m-%d")


def _validate_items(items_data):
    """Validate the items list payload. Returns (cleaned_list, error_str | None)."""
    if not isinstance(items_data, list) or len(items_data) == 0:
        return None, "At least one medicine item is required"
    cleaned = []
    for i, it in enumerate(items_data):
        name = str(it.get("medicine_name", "")).strip()
        if not name:
            return None, f"medicine_name is required for item {i + 1}"
        try:
            qty = int(it.get("quantity", 0))
            if qty < 1:
                raise ValueError
        except (ValueError, TypeError):
            return None, f"quantity must be a positive integer for item {i + 1}"
        cleaned.append({
            "medicine_name": name,
            "item_id":       str(it.get("item_id",   "") or "").strip(),
            "item_code":     str(it.get("item_code", "") or "").strip(),
            "quantity":      qty,
            "unit":          str(it.get("unit", "Tablet")).strip() or "Tablet",
            "remarks":       str(it.get("remarks", "") or "").strip(),
        })
    return cleaned, None


# ─────────────────────────────────────────────────────────────────────────────
# PURCHASE REQUISITION — CRUD
# GET    /purchase-requisition/             → list  (default: today's date)
# GET    /purchase-requisition/<pr_number>/ → detail
# POST   /purchase-requisition/             → create Draft
# PUT    /purchase-requisition/<pr_number>/ → edit (Draft / Verified only)
# DELETE /purchase-requisition/<pr_number>/ → hard-delete Draft only
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET", "POST", "PUT", "DELETE"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def purchase_requisition_view(request, pk=None):

    ctx           = _auth(request)
    data          = request.data
    hospital_code = ctx["hospital_code"]
    branch_code   = ctx["branch_code"]
    employee_id   = ctx["employee_id"]

    # ── GET ──────────────────────────────────────────────────────────────────
    if request.method == "GET":
        try:
            # ── Detail ────────────────────────────────────────────────────
            if pk:
                try:
                    obj = PurchaseRequisition.objects.get(pr_number=pk)
                except PurchaseRequisition.DoesNotExist:
                    return Response({"success": False, "error": "Record not found"}, status=404)
                if not _scope_ok(obj, hospital_code, branch_code):
                    return Response({"success": False, "error": "Record not found"}, status=404)
                return Response({"success": True, "data": PurchaseRequisitionSerializer(obj).data})

            # ── List ──────────────────────────────────────────────────────
            results = [
                r for r in PurchaseRequisition.objects.all()
                if _scope_ok(r, hospital_code, branch_code)
            ]
            results.sort(key=lambda x: getattr(x, "created_date", timezone.now()), reverse=True)

            # Status filter
            status_filter = request.GET.get("status", "").strip()
            if status_filter:
                results = [r for r in results if r.status == status_filter]

            # Date filter (defaults to today)
            from_date = request.GET.get("from_date", "").strip()
            to_date   = request.GET.get("to_date",   "").strip()
            if not from_date and not to_date:
                from_date = _today_str()
                to_date   = _today_str()

            if from_date or to_date:
                date_filtered = []
                for r in results:
                    d = getattr(r, "created_date", None)
                    if d:
                        d_str = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)[:10]
                        if from_date and d_str < from_date:
                            continue
                        if to_date and d_str > to_date:
                            continue
                    date_filtered.append(r)
                results = date_filtered

            return Response({
                "success": True,
                "count":   len(results),
                "data":    PurchaseRequisitionSerializer(results, many=True).data,
            })

        except Exception as e:
            logger.error("[purchase_requisition GET] %s", e, exc_info=True)
            return Response({"success": False, "error": str(e)}, status=500)

    # ── POST — Create Draft ───────────────────────────────────────────────────
    if request.method == "POST":

        department   = str(data.get("department",   "")).strip()
        requested_by = str(data.get("requested_by", "")).strip()
        request_date = data.get("request_date", "")

        if not department:
            return Response({"success": False, "error": "department is required"}, status=400)
        if not requested_by:
            return Response({"success": False, "error": "requested_by is required"}, status=400)
        if not request_date:
            return Response({"success": False, "error": "request_date is required"}, status=400)

        items_data = data.get("items", [])
        cleaned_items, item_error = _validate_items(items_data)
        if item_error:
            return Response({"success": False, "error": item_error}, status=400)

        pr_number = _next_pr_number()
        now       = timezone.now()

        try:
            obj = PurchaseRequisition.objects.create(
                pr_number       = pr_number,
                department      = department,
                requested_by    = requested_by,
                request_date    = request_date,
                purpose         = str(data.get("purpose", "")).strip(),
                status          = "Draft",
                hospital_code   = hospital_code,
                branch_code     = branch_code,
                # Audit blanks on create
                approved_by     = "", approved_date   = None,
                rejected_by     = "", rejected_reason = "", rejected_date = None,
                edited_by       = "", edited_reason   = "", edited_date   = None,
                created_by      = employee_id, created_date      = now,
                lastmodified_by = employee_id, lastmodified_date = now,
            )

            # Create related items
            for it in cleaned_items:
                PurchaseRequisitionItem.objects.create(
                    purchase_requisition = obj,
                    medicine_name = it["medicine_name"],
                    item_id       = it["item_id"],
                    item_code     = it["item_code"],
                    quantity      = it["quantity"],
                    unit          = it["unit"],
                    remarks       = it["remarks"],
                )

            return Response({
                "success": True,
                "message": "Purchase Requisition created successfully",
                "data":    PurchaseRequisitionSerializer(obj).data,
            }, status=201)

        except Exception as e:
            logger.error("[purchase_requisition POST] %s", e, exc_info=True)
            return Response({"success": False, "error": str(e)}, status=500)

    # ── PUT — Edit (Draft / Verified only) ────────────────────────────────────
    if request.method == "PUT":
        if not pk:
            return Response({"success": False, "error": "pr_number required in URL"}, status=400)

        try:
            obj = PurchaseRequisition.objects.get(pr_number=pk)
        except PurchaseRequisition.DoesNotExist:
            return Response({"success": False, "error": "Record not found"}, status=404)

        if not _scope_ok(obj, hospital_code, branch_code):
            return Response({"success": False, "error": "Record not found"}, status=404)

        if obj.status in ("Approved", "Rejected"):
            return Response({"success": False, "error": f"Cannot edit a {obj.status} requisition"}, status=403)

        edited_reason = str(data.get("edited_reason", "")).strip()
        if not edited_reason:
            return Response({"success": False, "error": "edited_reason is required when updating"}, status=400)

        # Validate items if provided
        items_data = data.get("items", None)
        cleaned_items = None
        if items_data is not None:
            cleaned_items, item_error = _validate_items(items_data)
            if item_error:
                return Response({"success": False, "error": item_error}, status=400)

        now = timezone.now()

        # Update header fields
        if "department"   in data: obj.department   = str(data["department"]).strip()
        if "requested_by" in data: obj.requested_by = str(data["requested_by"]).strip()
        if "request_date" in data: obj.request_date = data["request_date"]
        if "purpose"      in data: obj.purpose      = str(data["purpose"]).strip()

        obj.edited_by         = employee_id
        obj.edited_reason     = edited_reason
        obj.edited_date       = now
        obj.lastmodified_by   = employee_id
        obj.lastmodified_date = now
        obj.save()

        # Replace items if provided
        if cleaned_items is not None:
            obj.items.all().delete()
            for it in cleaned_items:
                PurchaseRequisitionItem.objects.create(
                    purchase_requisition = obj,
                    medicine_name = it["medicine_name"],
                    item_id       = it["item_id"],
                    item_code     = it["item_code"],
                    quantity      = it["quantity"],
                    unit          = it["unit"],
                    remarks       = it["remarks"],
                )

        return Response({
            "success": True,
            "message": "Purchase Requisition updated",
            "data":    PurchaseRequisitionSerializer(obj).data,
        })

    # ── DELETE — Hard-delete Draft only ──────────────────────────────────────
    if request.method == "DELETE":
        if not pk:
            return Response({"success": False, "error": "pr_number required in URL"}, status=400)

        try:
            obj = PurchaseRequisition.objects.get(pr_number=pk)
        except PurchaseRequisition.DoesNotExist:
            return Response({"success": False, "error": "Record not found"}, status=404)

        if not _scope_ok(obj, hospital_code, branch_code):
            return Response({"success": False, "error": "Record not found"}, status=404)

        if obj.status != "Draft":
            return Response({
                "success": False,
                "error": f"Only Draft requisitions can be deleted. Current: {obj.status}",
            }, status=403)

        obj.delete()
        return Response({"success": True, "message": "Purchase Requisition deleted"})


# ─────────────────────────────────────────────────────────────────────────────
# PURCHASE REQUISITION ACTION — Approve / Reject
# POST /purchase-requisition-action/
# Body: { pr_number, action: "approve"|"reject", rejected_reason (if reject) }
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def purchase_requisition_action_view(request):

    ctx           = _auth(request)
    data          = request.data
    hospital_code = ctx["hospital_code"]
    branch_code   = ctx["branch_code"]
    employee_id   = ctx["employee_id"]

    pr_number = str(data.get("pr_number", "")).strip()
    action    = str(data.get("action",    "")).strip().lower()

    if not pr_number:
        return Response({"success": False, "error": "pr_number is required"}, status=400)
    if action not in ("approve", "reject"):
        return Response({"success": False, "error": f"Unknown action '{action}'. Expected 'approve' or 'reject'."}, status=400)

    try:
        obj = PurchaseRequisition.objects.get(pr_number=pr_number)
    except PurchaseRequisition.DoesNotExist:
        return Response({"success": False, "error": "Record not found"}, status=404)

    if not _scope_ok(obj, hospital_code, branch_code):
        return Response({"success": False, "error": "Record not found"}, status=404)

    current = obj.status

    # ── APPROVE ───────────────────────────────────────────────────────────────
    if action == "approve":
        if current == "Approved":
            return Response({"success": False, "error": "Already Approved"}, status=400)
        if current == "Rejected":
            return Response({"success": False, "error": "Rejected requisitions cannot be approved"}, status=403)

        obj.status            = "Approved"
        obj.approved_by       = employee_id
        obj.approved_date     = timezone.now()
        obj.lastmodified_by   = employee_id
        obj.lastmodified_date = timezone.now()
        obj.save()

        return Response({
            "success": True,
            "message": f"Purchase Requisition {pr_number} approved successfully",
            "data":    PurchaseRequisitionSerializer(obj).data,
        })

    # ── REJECT ────────────────────────────────────────────────────────────────
    if action == "reject":
        if current == "Approved":
            return Response({"success": False, "error": "Approved requisitions cannot be rejected"}, status=403)
        if current == "Rejected":
            return Response({"success": False, "error": "Already Rejected"}, status=400)

        rejected_reason = str(data.get("rejected_reason", "")).strip()
        if not rejected_reason:
            return Response({"success": False, "error": "rejected_reason is required"}, status=400)

        obj.status            = "Rejected"
        obj.rejected_by       = employee_id
        obj.rejected_reason   = rejected_reason
        obj.rejected_date     = timezone.now()
        obj.lastmodified_by   = employee_id
        obj.lastmodified_date = timezone.now()
        obj.save()

        return Response({
            "success": True,
            "message": f"Purchase Requisition {pr_number} rejected",
            "data":    PurchaseRequisitionSerializer(obj).data,
        })