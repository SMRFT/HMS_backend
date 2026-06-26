import logging
import os
from datetime import datetime

from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from pymongo import MongoClient

from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from pyauth.auth import HasRoleAndDataPermission

from ..models import PurchaseRequisition
from ..serializers import PurchaseRequisitionSerializer


logger = logging.getLogger(__name__)

# ═════════════════════════════════════════════════════════════════════════════
# MONGODB PROFILE LOOKUP  (resolve employee_id → employee name)
# ═════════════════════════════════════════════════════════════════════════════

def _get_profile_collection():
    client    = MongoClient(os.getenv("GLOBAL_DB_HOST"))
    global_db = client["Global"]
    return global_db["backend_diagnostics_profile"]


def _get_employee_name(employee_id: str) -> str:
    if not employee_id or str(employee_id).strip() in ("", "system"):
        return employee_id or ""
    try:
        col = _get_profile_collection()
        doc = col.find_one({"employeeId": str(employee_id).strip()})
        if doc:
            return doc.get("employeeName", employee_id)
    except Exception as exc:
        logger.warning("Profile lookup failed for %s: %s", employee_id, exc)
    return employee_id


# ═════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def _get_data(request):
    return request.data if hasattr(request, "data") else request.POST


def _auth(request):
    data = _get_data(request)
    return {
        "employee_id": (
            data.get("auth-user-id")
            or request.headers.get("auth-user-id")
            or request.headers.get("Auth-User-Id")
            or "system"
        ),
        "hospital_code": (
            data.get("auth-hospital-code")
            or request.headers.get("auth-hospital-code")
            or request.headers.get("Hospital-Code")
            or "system"
        ),
        "branch_code": (
            data.get("auth-branch-code")
            or request.headers.get("auth-branch-code")
            or request.headers.get("Branch-Code")
            or "system"
        ),
    }


def _current_fin_year():
    today     = datetime.today()
    from_year = today.year if today.month >= 4 else today.year - 1
    return f"{str(from_year)[-2:]}{str(from_year + 1)[-2:]}"


def _next_pr_number():
    """PR/<FINYEAR>/<SEQ6>  e.g. PR/2627/000001"""
    fin_year = _current_fin_year()
    prefix   = f"PR/{fin_year}/"
    max_seq  = 0
    for row in PurchaseRequisition.objects.filter(pr_number__startswith=prefix):
        try:
            seq = int(str(row.pr_number).split("/")[-1])
            if seq > max_seq:
                max_seq = seq
        except Exception:
            pass
    return f"{prefix}{str(max_seq + 1).zfill(6)}"


def _safe_items(raw) -> list:
    """
    Guarantee items is always a plain Python list.

    Items are stored as a native BSON array in MongoDB (same as PurchaseOrder).
    ⚠️  Never call json.dumps / json.loads on items — it is NOT a JSON string.
    """
    if isinstance(raw, list):
        return raw
    return []


def _read_items_from_instance(pr) -> list:
    """
    Read items directly from the model instance attribute, bypassing the
    serializer which may not correctly round-trip the BSON array field.
    """
    raw = getattr(pr, "items", None)
    if isinstance(raw, list):
        return raw
    raw = pr.__dict__.get("items", None)
    if isinstance(raw, list):
        return raw
    return []


def _items_to_store(items: list) -> list:
    """
    Clean and normalise a list of medicine items before writing to MongoDB.
    A Purchase Requisition line only carries the medicine reference — no
    quantity — per the simplified PR workflow.
    Returns a plain Python list (stored as a BSON array).
    """
    cleaned = []
    for item in items:
        name = str(item.get("medicine_name", "")).strip()
        if not name:
            continue
        cleaned.append({
            "item_id":       item.get("item_id") or None,
            "medicine_name": name,
        })
    return cleaned


def _validate_items(items: list) -> list:
    """Return a list of validation error strings (empty = valid)."""
    errors = []
    if not items:
        errors.append("At least one medicine is required.")
        return errors
    for idx, item in enumerate(items):
        if not str(item.get("medicine_name", "")).strip():
            errors.append(f"Item {idx + 1}: medicine_name is required.")
    return errors


# Fields whose `<field>_by` employee id should be resolved to a display name
_EMPLOYEE_FIELDS = (
    "created_by",
    "approved_by",
    "rejected_by",
    "po_initiated_by",
    "purchased_by",
    "stock_restocked_by",
    "edited_by",
)


def _enrich_pr(pr) -> dict:
    """
    Serialise a PurchaseRequisition instance and add computed fields:
      • items — read directly from the model instance (bypasses serializer
                BSON round-trip issue that returns [])
      • <field>_name — employee name resolved from MongoDB profile for every
                       *_by audit field.
    """
    data = PurchaseRequisitionSerializer(pr).data

    # ── FIX: read items directly from the model instance ──
    data["items"] = _read_items_from_instance(pr)

    for field in _EMPLOYEE_FIELDS:
        emp_id = str(data.get(field, "") or "").strip()
        data[f"{field}_name"] = _get_employee_name(emp_id) if emp_id else ""

    return data


# ═════════════════════════════════════════════════════════════════════════════
# PURCHASE REQUISITION  —  GET / POST / PUT / DELETE
# GET    /purchase-requisition/             → list (filters: status, from_date, to_date)
# GET    /purchase-requisition/<pr_number>/ → detail
# POST   /purchase-requisition/             → create Draft
# PUT    /purchase-requisition/<pr_number>/ → edit (Draft only)
# DELETE /purchase-requisition/<pr_number>/ → hard-delete Draft only
# ═════════════════════════════════════════════════════════════════════════════

@api_view(["GET", "POST", "PUT", "DELETE"])
# @permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def purchase_requisition_view(request, pk=None):

    ctx           = _auth(request)
    data          = _get_data(request)
    employee_id   = ctx["employee_id"]
    hospital_code = ctx["hospital_code"]
    branch_code   = ctx["branch_code"]

    # ── GET ──────────────────────────────────────────────────────────────────
    if request.method == "GET":
        try:
            qs = PurchaseRequisition.objects.filter(
                hospital_code=hospital_code,
                branch_code=branch_code,
            )

            # Single record
            if pk:
                try:
                    obj = qs.get(pr_number=pk)
                except PurchaseRequisition.DoesNotExist:
                    return Response({"success": False, "error": "Purchase Requisition not found."}, status=404)
                return Response({"success": True, "data": _enrich_pr(obj)})

            # Optional status filter
            status_filter = request.GET.get("status", "").strip()
            if status_filter:
                qs = qs.filter(status=status_filter)

            # Optional date range filter (created_date)
            from_date_str = request.GET.get("from_date", "").strip()
            to_date_str   = request.GET.get("to_date",   "").strip()

            if from_date_str:
                try:
                    from_dt = timezone.make_aware(
                        datetime.combine(
                            datetime.strptime(from_date_str, "%Y-%m-%d").date(),
                            datetime.min.time(),
                        )
                    )
                    qs = qs.filter(created_date__gte=from_dt)
                except ValueError:
                    pass

            if to_date_str:
                try:
                    to_dt = timezone.make_aware(
                        datetime.combine(
                            datetime.strptime(to_date_str, "%Y-%m-%d").date(),
                            datetime.max.time(),
                        )
                    )
                    qs = qs.filter(created_date__lte=to_dt)
                except ValueError:
                    pass

            qs     = qs.order_by("-created_date")
            result = [_enrich_pr(i) for i in qs]

            return Response({"success": True, "count": len(result), "data": result})

        except Exception as e:
            logger.error("[PR GET] %s", e, exc_info=True)
            return Response({"success": False, "error": str(e)}, status=500)

    # ── POST — Create Draft ───────────────────────────────────────────────────
    if request.method == "POST":
        try:
            # items must arrive as a plain list from the frontend
            items = _safe_items(data.get("items", []))

            item_errors = _validate_items(items)
            if item_errors:
                return Response({"success": False, "error": item_errors}, status=400)

            # Store as a plain Python list — DRF/djongo persists as BSON array
            clean_items = _items_to_store(items)

            payload = {
                "pr_number": _next_pr_number(),
                "items":     clean_items,            # ← native list, not JSON string
                "status":    "Draft",

                "approved_by": "", "approved_date": None,
                "rejected_by": "", "rejected_reason": "", "rejected_date": None,
                "po_initiated_by": "", "po_initiated_date": None,
                "purchased_by": "", "purchased_date": None,
                "stock_restocked_by": "", "stock_restocked_date": None,
                "edited_by": "", "edited_reason": "", "edited_date": None,

                "hospital_code": hospital_code,
                "branch_code":   branch_code,
            }

            serializer = PurchaseRequisitionSerializer(data=payload)
            if serializer.is_valid():
                now   = timezone.now()
                saved = serializer.save(
                    created_by=employee_id,
                    created_date=now,
                    lastmodified_by=employee_id,
                    lastmodified_date=now,
                )
                # ── After save, force-write items directly on the instance
                #    to guarantee the BSON array is stored correctly.
                if not _read_items_from_instance(saved):
                    saved.items = clean_items
                    saved.save(update_fields=["items"])

                return Response({
                    "success": True,
                    "message": "Purchase Requisition created successfully.",
                    "data":    _enrich_pr(saved),
                }, status=201)

            return Response({"success": False, "error": serializer.errors}, status=400)

        except Exception as e:
            logger.error("[PR POST] %s", e, exc_info=True)
            return Response({"success": False, "error": str(e)}, status=500)

    # ── PUT — Edit (Draft only) ────────────────────────────────────────────────
    if request.method == "PUT":
        if not pk:
            return Response({"success": False, "error": "pr_number required in URL."}, status=400)

        try:
            obj = PurchaseRequisition.objects.get(
                pr_number=pk,
                hospital_code=hospital_code,
                branch_code=branch_code,
            )
        except PurchaseRequisition.DoesNotExist:
            return Response({"success": False, "error": "Purchase Requisition not found."}, status=404)

        if obj.status != "Draft":
            return Response({"success": False, "error": f"Cannot edit a {obj.status} requisition."}, status=403)

        try:
            edited_reason = str(data.get("edited_reason", "")).strip()
            if not edited_reason:
                return Response({"success": False, "error": "edited_reason is required."}, status=400)

            incoming  = {}
            new_items = None

            # Items update — store as plain list (BSON array), no json.dumps
            if "items" in data:
                items = _safe_items(data["items"])
                item_errors = _validate_items(items)
                if item_errors:
                    return Response({"success": False, "error": item_errors}, status=400)
                new_items = _items_to_store(items)
                incoming["items"] = new_items   # ← native list

            incoming["edited_by"]     = employee_id
            incoming["edited_reason"] = edited_reason
            incoming["edited_date"]   = timezone.now()

            serializer = PurchaseRequisitionSerializer(obj, data=incoming, partial=True)
            if serializer.is_valid():
                now   = timezone.now()
                saved = serializer.save(
                    lastmodified_by=employee_id,
                    lastmodified_date=now,
                )
                # Force-write items directly if they were updated
                if new_items is not None and not _read_items_from_instance(saved):
                    saved.items = new_items
                    saved.save(update_fields=["items"])

                return Response({
                    "success": True,
                    "message": "Purchase Requisition updated.",
                    "data":    _enrich_pr(saved),
                })

            return Response({"success": False, "error": serializer.errors}, status=400)

        except Exception as e:
            logger.error("[PR PUT] %s", e, exc_info=True)
            return Response({"success": False, "error": str(e)}, status=500)

    # ── DELETE — hard-delete Draft only ──────────────────────────────────────
    if request.method == "DELETE":
        if not pk:
            return Response({"success": False, "error": "pr_number required in URL."}, status=400)

        try:
            obj = PurchaseRequisition.objects.get(
                pr_number=pk,
                hospital_code=hospital_code,
                branch_code=branch_code,
            )
        except PurchaseRequisition.DoesNotExist:
            return Response({"success": False, "error": "Purchase Requisition not found."}, status=404)

        if obj.status != "Draft":
            return Response({"success": False, "error": "Only Draft requisitions can be deleted."}, status=403)

        obj.delete()
        return Response({"success": True, "message": "Purchase Requisition deleted."})


# ═════════════════════════════════════════════════════════════════════════════
# PURCHASE REQUISITION ACTION  —  POST  /purchase-requisition-action/
# Body: { pr_number, action, rejected_reason? }
#
# Valid actions and the status transition each one performs:
#
#   action            | from status                | to status
#   ------------------|-----------------------------|---------------------------
#   approve           | Draft                       | Approved
#   reject            | Draft                       | Rejected   (needs reason)
#   po_initiated      | Approved                    | Purchase Order Initiated
#   purchased         | Purchase Order Initiated    | Purchased
#   stock_restocked   | Purchased                   | Stock Restocked
# ═════════════════════════════════════════════════════════════════════════════

ACTION_TRANSITIONS = {
    "approve":         {"from": ["Draft"],                     "to": "Approved"},
    "reject":          {"from": ["Draft"],                     "to": "Rejected"},
    "po_initiated":    {"from": ["Approved"],                  "to": "Purchase Order Initiated"},
    "purchased":       {"from": ["Purchase Order Initiated"],  "to": "Purchased"},
    "stock_restocked": {"from": ["Purchased"],                 "to": "Stock Restocked"},
}

# Which `<prefix>_by` / `<prefix>_date` fields get stamped for each action
ACTION_FIELD_PREFIX = {
    "approve":         "approved",
    "reject":          "rejected",
    "po_initiated":    "po_initiated",
    "purchased":       "purchased",
    "stock_restocked": "stock_restocked",
}


@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def purchase_requisition_action_view(request):

    ctx           = _auth(request)
    data          = _get_data(request)
    employee_id   = ctx["employee_id"]
    hospital_code = ctx["hospital_code"]
    branch_code   = ctx["branch_code"]

    pr_number = str(data.get("pr_number", "")).strip()
    action    = str(data.get("action",    "")).strip().lower()

    if not pr_number:
        return Response({"success": False, "error": "pr_number is required."}, status=400)

    if action not in ACTION_TRANSITIONS:
        return Response({
            "success": False,
            "error": f"action must be one of: {', '.join(ACTION_TRANSITIONS.keys())}",
        }, status=400)

    try:
        obj = PurchaseRequisition.objects.get(
            pr_number=pr_number,
            hospital_code=hospital_code,
            branch_code=branch_code,
        )
    except PurchaseRequisition.DoesNotExist:
        return Response({"success": False, "error": "Purchase Requisition not found."}, status=404)

    transition = ACTION_TRANSITIONS[action]

    if obj.status not in transition["from"]:
        return Response({
            "success": False,
            "error": (
                f"Cannot perform '{action}' on a requisition with status "
                f"'{obj.status}'. Expected status: {', '.join(transition['from'])}."
            ),
        }, status=403)

    now    = timezone.now()
    prefix = ACTION_FIELD_PREFIX[action]

    # ── Reject requires a reason ────────────────────────────────────────────
    if action == "reject":
        rejected_reason = str(data.get("rejected_reason", "")).strip()
        if not rejected_reason:
            return Response({"success": False, "error": "rejected_reason is required."}, status=400)
        obj.rejected_reason = rejected_reason

    setattr(obj, f"{prefix}_by",   employee_id)
    setattr(obj, f"{prefix}_date", now)

    obj.status            = transition["to"]
    obj.lastmodified_by   = employee_id
    obj.lastmodified_date = now
    obj.save()

    logger.info(
        "[PR %s] %s → %s by %s at %s",
        pr_number, action.upper(), transition["to"], employee_id, now.isoformat(),
    )

    return Response({
        "success": True,
        "message": f"{pr_number} → {transition['to']}",
        "data":    _enrich_pr(obj),
    })