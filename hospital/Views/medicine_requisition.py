import logging
import re
from datetime import datetime

from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.views.decorators.csrf import csrf_exempt

from pyauth.auth import HasRoleAndDataPermission
from ..models import MedicineRequisition
from ..serializers import MedicineRequisitionSerializer

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


from .mongo_utils import get_hms_db, paginate_queryset, paginate_mongo_query, clean_doc, clean_docs, apply_date_filter
from pymongo import ASCENDING, DESCENDING
from django.db.models import Q


def _next_mr_number():
    """MR/<FINYEAR>/<SEQ6>  e.g. MR/2627/000001"""
    fin_year = _current_fin_year()
    prefix   = f"MR/{fin_year}/"
    client, hms_db = get_hms_db()
    top_doc = list(hms_db["hospital_medicinerequisition"].find(
        {"mr_number": {"$regex": f"^{prefix}"}},
        {"mr_number": 1}
    ).sort("mr_number", DESCENDING).limit(1))
    max_seq  = 0
    if top_doc:
        try:
            seq = int(str(top_doc[0].get("mr_number", "")).split("/")[-1])
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
    """Return today's date as YYYY-MM-DD string."""
    return datetime.today().strftime("%Y-%m-%d")


# ─────────────────────────────────────────────────────────────────────────────
# MEDICINE REQUISITION — CRUD
# GET    /medicine-requisition/             → list  (default: today's date)
# GET    /medicine-requisition/<mr_number>/ → detail
# POST   /medicine-requisition/             → create Draft
# PUT    /medicine-requisition/<mr_number>/ → edit (Draft only)
# DELETE /medicine-requisition/<mr_number>/ → hard-delete Draft only
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET", "POST", "PUT", "DELETE"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def medicine_requisition_view(request, pk=None):

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
                    mr = MedicineRequisition.objects.get(
                        mr_number=pk,
                        hospital_code=hospital_code,
                        branch_code=branch_code
                    )
                    return Response({"success": True, "data": MedicineRequisitionSerializer(mr).data})
                except MedicineRequisition.DoesNotExist:
                    return Response({"success": False, "error": "Record not found"}, status=404)

            # ── List ──────────────────────────────────────────────────────
            filter_q = {}
            if hospital_code and hospital_code != "system":
                filter_q["hospital_code"] = hospital_code
            if branch_code and branch_code != "system":
                filter_q["branch_code"] = branch_code

            # Status filter
            status_filter = request.GET.get("status", "").strip()
            if status_filter:
                filter_q["status"] = status_filter

            search = request.GET.get("search", "").strip()
            if search:
                reg = {"$regex": re.escape(search), "$options": "i"}
                filter_q["$or"] = [
                    {"mr_number": reg},
                    {"medicine_name": reg},
                    {"consultant_name": reg},
                    {"department_name": reg},
                    {"patient_name": reg},
                    {"patient_id": reg},
                    {"nurse_name": reg}
                ]

            filter_q = apply_date_filter(filter_q, request, "created_date")

            return Response(paginate_mongo_query(
                "hospital_medicinerequisition",
                filter_q,
                sort=[("created_date", DESCENDING)],
                request=request
            ))

        except Exception as e:
            logger.error("[medicine_requisition GET] %s", e, exc_info=True)
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
            "mr_number":            _next_mr_number(),
            "medicine_name":        medicine_name,
            "chemical_composition": str(data.get("chemical_composition", "")).strip(),
            "consultant_name":      consultant_name,
            "request_date":         request_date,
            "remarks":              str(data.get("remarks", "")).strip(),
            "status":               "Draft",
            "hospital_code":        hospital_code,
            "branch_code":          branch_code,
            # Audit blanks on create
            "approved_by":    "",   "approved_date":   None,
            "rejected_by":    "",   "rejected_reason": "",   "rejected_date": None,
            "edited_by":      "",   "edited_reason":   "",   "edited_date":   None,
        }

        serializer = MedicineRequisitionSerializer(data=payload)
        if serializer.is_valid():
            saved = serializer.save(
                created_by=employee_id,
                created_date=timezone.now(),
                lastmodified_by=employee_id,
                lastmodified_date=timezone.now(),
            )
            return Response({
                "success": True,
                "message": "Medicine Requisition created successfully",
                "data":    MedicineRequisitionSerializer(saved).data,
            }, status=201)

        logger.error("[medicine_requisition POST] %s", serializer.errors)
        return Response({"success": False, "error": serializer.errors}, status=400)

    # ── PUT — Edit (Draft only) ───────────────────────────────────────────────
    if request.method == "PUT":
        if not pk:
            return Response({"success": False, "error": "mr_number required in URL"}, status=400)

        try:
            obj = MedicineRequisition.objects.get(mr_number=pk)
        except MedicineRequisition.DoesNotExist:
            return Response({"success": False, "error": "Record not found"}, status=404)

        if not _scope_ok(obj, hospital_code, branch_code):
            return Response({"success": False, "error": "Record not found"}, status=404)

        if obj.status in ("Approved", "Rejected"):
            return Response({"success": False, "error": f"Cannot edit a {obj.status} requisition"}, status=403)

        edited_reason = str(data.get("edited_reason", "")).strip()
        if not edited_reason:
            return Response({"success": False, "error": "edited_reason is required when updating"}, status=400)

        allowed  = {"medicine_name", "chemical_composition", "consultant_name", "request_date", "remarks"}
        incoming = {k: v for k, v in data.items() if k in allowed}
        incoming["edited_by"]     = employee_id
        incoming["edited_reason"] = edited_reason
        incoming["edited_date"]   = timezone.now()

        # Immutable — never overwrite
        for f in ("mr_number", "status", "approved_by", "approved_date",
                  "rejected_by", "rejected_reason", "rejected_date",
                  "hospital_code", "branch_code", "created_by", "created_date"):
            incoming.pop(f, None)

        serializer = MedicineRequisitionSerializer(obj, data=incoming, partial=True)
        if serializer.is_valid():
            saved = serializer.save(lastmodified_by=employee_id, lastmodified_date=timezone.now())
            return Response({"success": True, "message": "Medicine Requisition updated",
                             "data": MedicineRequisitionSerializer(saved).data})

        logger.error("[medicine_requisition PUT] %s", serializer.errors)
        return Response({"success": False, "error": serializer.errors}, status=400)

    # ── DELETE — Hard-delete Draft only ──────────────────────────────────────
    if request.method == "DELETE":
        if not pk:
            return Response({"success": False, "error": "mr_number required in URL"}, status=400)

        try:
            obj = MedicineRequisition.objects.get(mr_number=pk)
        except MedicineRequisition.DoesNotExist:
            return Response({"success": False, "error": "Record not found"}, status=404)

        if not _scope_ok(obj, hospital_code, branch_code):
            return Response({"success": False, "error": "Record not found"}, status=404)

        if obj.status != "Draft":
            return Response({"success": False,
                             "error": f"Only Draft requisitions can be deleted. Current: {obj.status}"}, status=403)

        obj.delete()
        return Response({"success": True, "message": "Medicine Requisition deleted"})


# ─────────────────────────────────────────────────────────────────────────────
# MEDICINE REQUISITION ACTION — Approve / Reject
# POST /medicine-requisition-action/
# Body: { mr_number, action: "approve"|"reject", rejected_reason (if reject) }
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def medicine_requisition_action_view(request):

    ctx           = _auth(request)
    data          = request.data
    hospital_code = ctx["hospital_code"]
    branch_code   = ctx["branch_code"]
    employee_id   = ctx["employee_id"]

    mr_number = str(data.get("mr_number", "")).strip()
    action    = str(data.get("action",    "")).strip().lower()

    if not mr_number:
        return Response({"success": False, "error": "mr_number is required"}, status=400)
    if action not in ("approve", "reject"):
        return Response({"success": False, "error": f"Unknown action '{action}'. Expected 'approve' or 'reject'."}, status=400)

    try:
        obj = MedicineRequisition.objects.get(mr_number=mr_number)
    except MedicineRequisition.DoesNotExist:
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
            "message": f"Medicine Requisition {mr_number} approved successfully",
            "data":    MedicineRequisitionSerializer(obj).data,
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
            "message": f"Medicine Requisition {mr_number} rejected",
            "data":    MedicineRequisitionSerializer(obj).data,
        })