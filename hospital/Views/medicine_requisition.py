import json
import logging
from datetime import datetime

from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from django.views.decorators.csrf import csrf_exempt

from pyauth.auth import HasRoleAndDataPermission

from ..models import PurchaseRequisition, PharmacyItem, ChemicalComposition
from ..serializers import PurchaseRequisitionSerializer

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _get_request_data(request):
    return request.data if hasattr(request, "data") else request.POST


def _current_fin_year():
    today = datetime.today()
    from_yr = today.year if today.month >= 4 else today.year - 1
    return f"{str(from_yr)[-2:]}{str(from_yr + 1)[-2:]}"


def _next_pr_number():
    """PR/<FINYEAR>/<SEQ6>  e.g. PR/2627/000001"""
    fin_year = _current_fin_year()
    prefix   = f"PR/{fin_year}/"

    max_seq = 0
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


def _auth(request):
    """Extract common auth context from headers / request data."""
    data = _get_request_data(request)
    return {
        "employee_id": (
            data.get("auth-user-id") or
            request.headers.get("auth-user-id") or
            "system"
        ),
        "hospital_code": (
            data.get("auth-hospital-code") or
            request.headers.get("auth-hospital-code") or
            None
        ),
        "branch_code": (
            data.get("auth-branch-code") or
            request.headers.get("Branch-Code") or
            None
        ),
    }


@api_view(["GET", "POST", "PUT", "DELETE"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def purchase_requisition_view(request, pk=None):

    ctx  = _auth(request)
    data = _get_request_data(request)

    hospital_code = ctx["hospital_code"]
    branch_code   = ctx["branch_code"]
    employee_id   = ctx["employee_id"]

    # ── GET ──────────────────────────────────────────────────────────────────
    if request.method == "GET":
        try:
            if pk:
                try:
                    obj = PurchaseRequisition.objects.get(pr_number=pk)
                except PurchaseRequisition.DoesNotExist:
                    return Response({"success": False, "error": "Record not found"}, status=404)

                if (
                    not obj.is_active or
                    getattr(obj, "hospital_code", None) != hospital_code or
                    getattr(obj, "branch_code",   None) != branch_code
                ):
                    return Response({"success": False, "error": "Record not found"}, status=404)

                return Response({"success": True, "data": PurchaseRequisitionSerializer(obj).data})

            # List — scoped to hospital+branch, active only, newest first
            all_prs = PurchaseRequisition.objects.all()
            results = [
                r for r in all_prs
                if r.is_active
                and getattr(r, "hospital_code", None) == hospital_code
                and getattr(r, "branch_code",   None) == branch_code
            ]
            results.sort(
                key=lambda x: getattr(x, "created_date", timezone.now()),
                reverse=True,
            )

            # Optional query-param filters
            status_filter = request.GET.get("status", "").strip()
            if status_filter:
                results = [r for r in results if r.status == status_filter]

            from_date = request.GET.get("from_date", "").strip()
            to_date   = request.GET.get("to_date",   "").strip()
            if from_date or to_date:
                filtered = []
                for r in results:
                    d = getattr(r, "request_date", None)
                    if d:
                        d_str = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)[:10]
                        if from_date and d_str < from_date:
                            continue
                        if to_date and d_str > to_date:
                            continue
                    filtered.append(r)
                results = filtered

            return Response({
                "success": True,
                "count":   len(results),
                "data":    PurchaseRequisitionSerializer(results, many=True).data,
            })

        except Exception as e:
            logger.error("[purchase_requisition_view GET] %s", e, exc_info=True)
            return Response({"success": False, "error": str(e)}, status=500)

    # ── POST — Create Draft ───────────────────────────────────────────────────
    if request.method == "POST":

        medicine_name = str(data.get("medicine_name", "")).strip()
        if not medicine_name:
            return Response({"success": False, "error": "medicine_name is required"}, status=400)

        consultant_name = str(data.get("consultant_name", "")).strip()
        if not consultant_name:
            return Response({"success": False, "error": "consultant_name is required"}, status=400)

        request_date = data.get("request_date", "")
        if not request_date:
            return Response({"success": False, "error": "request_date is required"}, status=400)

        payload = {
            "pr_number":            _next_pr_number(),
            "medicine_name":        medicine_name,
            "item_id":              data.get("item_id") or None,
            "chemical_composition": str(data.get("chemical_composition", "")).strip(),
            "consultant_name":      consultant_name,
            "request_date":         request_date,
            "remarks":              str(data.get("remarks", "")).strip(),
            "status":               "Draft",
            # Audit fields — blank on create
            "approved_by":          "",
            "approved_date":        None,
            "rejected_by":          "",
            "rejected_reason":      "",
            "rejected_date":        None,
            "edited_by":            "",
            "edited_reason":        "",
            "edited_date":          None,
            "hospital_code":        hospital_code,
            "branch_code":          branch_code,
            "is_active":            True,
        }

        serializer = PurchaseRequisitionSerializer(data=payload)
        if serializer.is_valid():
            saved = serializer.save(
                created_by=employee_id,
                created_date=timezone.now(),
                lastmodified_by=employee_id,
                lastmodified_date=timezone.now(),
            )
            return Response(
                {"success": True, "message": "Purchase Requisition created as Draft",
                 "data": PurchaseRequisitionSerializer(saved).data},
                status=201,
            )

        logger.error("[PR POST] %s", serializer.errors)
        return Response({"success": False, "error": serializer.errors}, status=400)

    # ── PUT — Edit Draft (requires edited_reason) ────────────────────────────
    if request.method == "PUT":

        if not pk:
            return Response({"success": False, "error": "pr_number is required in URL"}, status=400)

        try:
            obj = PurchaseRequisition.objects.get(pr_number=pk)
        except PurchaseRequisition.DoesNotExist:
            return Response({"success": False, "error": "Record not found"}, status=404)

        if (
            not obj.is_active or
            getattr(obj, "hospital_code", None) != hospital_code or
            getattr(obj, "branch_code",   None) != branch_code
        ):
            return Response({"success": False, "error": "Record not found"}, status=404)

        # Block edits on Approved / Rejected records
        if obj.status in ("Approved", "Rejected"):
            return Response(
                {"success": False,
                 "error": f"Cannot edit a {obj.status} requisition"},
                status=403,
            )

        # edited_reason mandatory for any PUT
        edited_reason = str(data.get("edited_reason", "")).strip()
        if not edited_reason:
            return Response(
                {"success": False, "error": "edited_reason is required when updating a requisition"},
                status=400,
            )

        allowed_fields = {
            "medicine_name", "item_id", "chemical_composition",
            "consultant_name", "request_date", "remarks",
        }
        incoming = {k: v for k, v in data.items() if k in allowed_fields}
        incoming["edited_by"]     = employee_id
        incoming["edited_reason"] = edited_reason
        incoming["edited_date"]   = timezone.now()

        # Immutable fields — never overwrite
        for field in (
            "pr_number", "status", "approved_by", "approved_date",
            "rejected_by", "rejected_reason", "rejected_date",
            "hospital_code", "branch_code", "created_by", "created_date",
        ):
            incoming.pop(field, None)

        serializer = PurchaseRequisitionSerializer(obj, data=incoming, partial=True)
        if serializer.is_valid():
            saved = serializer.save(
                lastmodified_by=employee_id,
                lastmodified_date=timezone.now(),
            )
            return Response({
                "success": True,
                "message": "Purchase Requisition updated",
                "data":    PurchaseRequisitionSerializer(saved).data,
            })

        logger.error("[PR PUT] %s", serializer.errors)
        return Response({"success": False, "error": serializer.errors}, status=400)

    # ── DELETE — Soft-delete Draft only ──────────────────────────────────────
    if request.method == "DELETE":

        if not pk:
            return Response({"success": False, "error": "pr_number is required in URL"}, status=400)

        try:
            obj = PurchaseRequisition.objects.get(pr_number=pk)
        except PurchaseRequisition.DoesNotExist:
            return Response({"success": False, "error": "Record not found"}, status=404)

        if (
            not obj.is_active or
            getattr(obj, "hospital_code", None) != hospital_code or
            getattr(obj, "branch_code",   None) != branch_code
        ):
            return Response({"success": False, "error": "Record not found"}, status=404)

        if obj.status != "Draft":
            return Response(
                {"success": False,
                 "error": f"Only Draft requisitions can be deleted. Current status: {obj.status}"},
                status=403,
            )

        obj.is_active          = False
        obj.lastmodified_by    = employee_id
        obj.lastmodified_date  = timezone.now()
        obj.save()

        return Response({"success": True, "message": "Purchase Requisition deleted"})


# ─────────────────────────────────────────────────────────────────────────────
# PURCHASE REQUISITION ACTION  (approve / reject)
# POST /purchase-requisition-action/
# Body: { pr_number, action: "approve"|"reject", rejected_reason (if reject) }
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def purchase_requisition_action_view(request):

    ctx  = _auth(request)
    data = _get_request_data(request)

    hospital_code = ctx["hospital_code"]
    branch_code   = ctx["branch_code"]
    employee_id   = ctx["employee_id"]

    pr_number = str(data.get("pr_number", "")).strip()
    action    = str(data.get("action",    "")).strip().lower()

    if not pr_number:
        return Response({"success": False, "error": "pr_number is required"}, status=400)
    if action not in ("approve", "reject"):
        return Response(
            {"success": False,
             "error": f"Unknown action '{action}'. Expected 'approve' or 'reject'."},
            status=400,
        )

    try:
        obj = PurchaseRequisition.objects.get(pr_number=pr_number)
    except PurchaseRequisition.DoesNotExist:
        return Response({"success": False, "error": "Record not found"}, status=404)

    if (
        not obj.is_active or
        getattr(obj, "hospital_code", None) != hospital_code or
        getattr(obj, "branch_code",   None) != branch_code
    ):
        return Response({"success": False, "error": "Record not found"}, status=404)

    current_status = obj.status

    # ── APPROVE ───────────────────────────────────────────────────────────────
    if action == "approve":

        if current_status == "Approved":
            return Response({"success": False, "error": "Already Approved"}, status=400)
        if current_status == "Rejected":
            return Response(
                {"success": False, "error": "Rejected requisitions cannot be approved"},
                status=403,
            )

        obj.status        = "Approved"
        obj.approved_by   = employee_id
        obj.approved_date = timezone.now()

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

        if current_status == "Approved":
            return Response(
                {"success": False, "error": "Approved requisitions cannot be rejected"},
                status=403,
            )
        if current_status == "Rejected":
            return Response({"success": False, "error": "Already Rejected"}, status=400)

        rejected_reason = str(data.get("rejected_reason", "")).strip()
        if not rejected_reason:
            return Response(
                {"success": False, "error": "rejected_reason is required"},
                status=400,
            )

        obj.status          = "Rejected"
        obj.rejected_by     = employee_id
        obj.rejected_reason = rejected_reason
        obj.rejected_date   = timezone.now()

        obj.lastmodified_by   = employee_id
        obj.lastmodified_date = timezone.now()
        obj.save()

        return Response({
            "success": True,
            "message": f"Purchase Requisition {pr_number} rejected",
            "data":    PurchaseRequisitionSerializer(obj).data,
        })


# ─────────────────────────────────────────────────────────────────────────────
# MEDICINE SEARCH HELPER  (used by the frontend autocomplete)
# GET /purchase-requisition-medicine-search/?q=<term>
# Returns matching PharmacyItem records with their chemical compositions
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def pr_medicine_search_view(request):

    ctx = _auth(request)
    hospital_code = ctx["hospital_code"]
    branch_code   = ctx["branch_code"]

    query = str(request.GET.get("q", "")).strip().lower()
    if not query or len(query) < 2:
        return Response({"success": True, "data": []})

    try:
        all_items = PharmacyItem.objects.all()
        matched = [
            i for i in all_items
            if i.is_active
            and getattr(i, "hospital_code", None) == hospital_code
            and getattr(i, "branch_code",   None) == branch_code
            and query in (str(getattr(i, "item_name", "") or "")).lower()
        ]

        # Fetch compositions for matched items
        all_comps = ChemicalComposition.objects.all()
        comp_map  = {}
        for c in all_comps:
            if not c.is_active:
                continue
            iid = str(getattr(c, "item_id", "") or "")
            if iid:
                comp_map.setdefault(iid, []).append(
                    str(getattr(c, "composition_name", "") or getattr(c, "name", "") or "")
                )

        result = []
        for item in matched[:30]:           # cap at 30 suggestions
            iid  = str(item.item_id)
            name = f"{item.item_name} {getattr(item, 'item_last_name', '') or ''}".strip()
            result.append({
                "item_id":             item.item_id,
                "item_name":           name,
                "hsn":                 getattr(item, "hsn", "") or "",
                "chemical_composition": ", ".join(comp_map.get(iid, [])),
            })

        return Response({"success": True, "data": result})

    except Exception as e:
        logger.error("[pr_medicine_search_view] %s", e, exc_info=True)
        return Response({"success": False, "error": str(e)}, status=500)