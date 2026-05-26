import logging
import os
from datetime import datetime

from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from pymongo import MongoClient

from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from pyauth.auth import HasRoleAndDataPermission

from ..models import PurchaseOrder, Vendor
from ..serializers import PurchaseOrderSerializer


logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════════
# PROFILE COLLECTION
# ═════════════════════════════════════════════════════════════════════════════

def _get_profile_collection():
    client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
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

    today = datetime.today()

    from_year = today.year if today.month >= 4 else today.year - 1

    return f"{str(from_year)[-2:]}{str(from_year + 1)[-2:]}"


def _next_po_number():

    fin_year = _current_fin_year()

    prefix = f"PO/{fin_year}/"

    max_seq = 0

    qs = PurchaseOrder.objects.filter(po_number__startswith=prefix)

    for row in qs:
        try:
            seq = int(str(row.po_number).split("/")[-1])

            if seq > max_seq:
                max_seq = seq

        except Exception:
            pass

    return f"{prefix}{str(max_seq + 1).zfill(6)}"


def _safe_items(raw):

    if isinstance(raw, list):
        return raw

    return []


def _items_to_store(items: list):

    clean = []

    for item in items:

        clean.append({
            "item_id": item.get("item_id"),
            "medicine_name": str(item.get("medicine_name", "")).strip(),
            "quantity": int(item.get("quantity", 1)),
        })

    return clean


def _validate_items(items):

    errors = []

    if not items:
        errors.append("At least one item is required.")
        return errors

    for idx, item in enumerate(items):

        row = idx + 1

        if not str(item.get("medicine_name", "")).strip():
            errors.append(f"Item {row}: medicine_name is required.")

        try:
            qty = int(item.get("quantity", 0))

            if qty < 1:
                errors.append(f"Item {row}: quantity must be greater than 0.")

        except Exception:
            errors.append(f"Item {row}: quantity must be integer.")

    return errors


def _enrich_po(po):

    data = PurchaseOrderSerializer(po).data

    # Always return items as array
    data["items"] = data.get("items", [])

    # Vendor name
    vendor_name = data.get("vendor_name", "")

    if not vendor_name:
        try:
            vendor_name = Vendor.objects.get(
                vendor_id=po.vendor_id
            ).name
        except Exception:
            vendor_name = ""

    data["vendor_name"] = vendor_name

    # Approved By Name
    approved_by_id = data.get("approved_by", "") or ""

    data["approved_by_name"] = (
        _get_employee_name(str(approved_by_id).strip())
        if approved_by_id else ""
    )

    # Rejected By Name
    rejected_by_id = data.get("rejected_by", "") or ""

    data["rejected_by_name"] = (
        _get_employee_name(str(rejected_by_id).strip())
        if rejected_by_id else ""
    )

    return data


# ═════════════════════════════════════════════════════════════════════════════
# PURCHASE ORDER VIEW
# ═════════════════════════════════════════════════════════════════════════════

@api_view(["GET", "POST", "PUT", "DELETE"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def purchase_order_view(request, pk=None):

    ctx = _auth(request)
    data = _get_data(request)

    employee_id = ctx["employee_id"]
    hospital_code = ctx["hospital_code"]
    branch_code = ctx["branch_code"]

    # ════════════════════════════════════════════════════════════════════════
    # GET
    # ════════════════════════════════════════════════════════════════════════

    if request.method == "GET":

        try:

            qs = PurchaseOrder.objects.filter(
                hospital_code=hospital_code,
                branch_code=branch_code,
            )

            # Single Record
            if pk:

                try:
                    obj = qs.get(po_number=pk)

                except PurchaseOrder.DoesNotExist:
                    return Response(
                        {
                            "success": False,
                            "error": "Purchase Order not found"
                        },
                        status=404
                    )

                return Response({
                    "success": True,
                    "data": _enrich_po(obj)
                })

            # Status Filter
            status_filter = request.GET.get("status", "").strip()

            if status_filter:
                qs = qs.filter(status=status_filter)

            # Vendor Filter
            vendor_filter = request.GET.get("vendor_id", "").strip()

            if vendor_filter:
                qs = qs.filter(vendor_id=vendor_filter)

            # Date Filters
            from_date_str = request.GET.get("from_date", "").strip()
            to_date_str = request.GET.get("to_date", "").strip()

            if from_date_str:
                try:

                    from_dt = datetime.strptime(
                        from_date_str,
                        "%Y-%m-%d"
                    )

                    from_dt = timezone.make_aware(
                        datetime.combine(
                            from_dt.date(),
                            datetime.min.time()
                        )
                    )

                    qs = qs.filter(created_date__gte=from_dt)

                except ValueError:
                    pass

            if to_date_str:
                try:

                    to_dt = datetime.strptime(
                        to_date_str,
                        "%Y-%m-%d"
                    )

                    to_dt = timezone.make_aware(
                        datetime.combine(
                            to_dt.date(),
                            datetime.max.time()
                        )
                    )

                    qs = qs.filter(created_date__lte=to_dt)

                except ValueError:
                    pass

            qs = qs.order_by("-created_date")

            result = [_enrich_po(i) for i in qs]

            return Response({
                "success": True,
                "count": len(result),
                "data": result
            })

        except Exception as e:

            logger.error(str(e), exc_info=True)

            return Response({
                "success": False,
                "error": str(e)
            }, status=500)

    # ════════════════════════════════════════════════════════════════════════
    # POST
    # ════════════════════════════════════════════════════════════════════════

    if request.method == "POST":

        try:

            vendor_id = data.get("vendor_id")

            if not vendor_id:
                return Response({
                    "success": False,
                    "error": "vendor_id is required."
                }, status=400)

            try:
                vendor = Vendor.objects.get(vendor_id=vendor_id)

            except Vendor.DoesNotExist:
                return Response({
                    "success": False,
                    "error": "Vendor not found."
                }, status=400)

            items = _safe_items(data.get("items", []))

            item_errors = _validate_items(items)

            if item_errors:
                return Response({
                    "success": False,
                    "error": item_errors
                }, status=400)

            clean_items = _items_to_store(items)

            payload = {
                "po_number": _next_po_number(),

                "vendor_id": int(vendor_id),

                "vendor_name": str(
                    data.get("vendor_name") or vendor.name
                ).strip(),

                "supplier": str(
                    data.get("supplier") or vendor.name
                ).strip(),

                # STORE AS ARRAY
                "items": clean_items,

                "status": "Draft",

                "approved_by": "",
                "approved_date": None,

                "rejected_by": "",
                "rejected_reason": "",
                "rejected_date": None,

                "edited_by": "",
                "edited_reason": "",
                "edited_date": None,

                "hospital_code": hospital_code,
                "branch_code": branch_code,
            }

            serializer = PurchaseOrderSerializer(data=payload)

            if serializer.is_valid():

                now = timezone.now()

                saved = serializer.save(
                    created_by=employee_id,
                    created_date=now,
                    lastmodified_by=employee_id,
                    lastmodified_date=now,
                )

                return Response({
                    "success": True,
                    "message": "Purchase Order created successfully.",
                    "data": _enrich_po(saved)
                }, status=201)

            return Response({
                "success": False,
                "error": serializer.errors
            }, status=400)

        except Exception as e:

            logger.error(str(e), exc_info=True)

            return Response({
                "success": False,
                "error": str(e)
            }, status=500)

    # ════════════════════════════════════════════════════════════════════════
    # PUT
    # ════════════════════════════════════════════════════════════════════════

    if request.method == "PUT":

        if not pk:
            return Response({
                "success": False,
                "error": "po_number required."
            }, status=400)

        try:

            obj = PurchaseOrder.objects.get(
                po_number=pk,
                hospital_code=hospital_code,
                branch_code=branch_code,
            )

        except PurchaseOrder.DoesNotExist:
            return Response({
                "success": False,
                "error": "Purchase Order not found."
            }, status=404)

        if obj.status in ["Approved", "Rejected"]:
            return Response({
                "success": False,
                "error": f"Cannot edit {obj.status} PO."
            }, status=403)

        try:

            incoming = {}

            edited_reason = str(
                data.get("edited_reason", "")
            ).strip()

            if not edited_reason:
                return Response({
                    "success": False,
                    "error": "edited_reason required."
                }, status=400)

            # Vendor Update
            if "vendor_id" in data:

                try:

                    vendor = Vendor.objects.get(
                        vendor_id=data["vendor_id"]
                    )

                    incoming["vendor_id"] = int(data["vendor_id"])

                    incoming["vendor_name"] = str(
                        data.get("vendor_name") or vendor.name
                    ).strip()

                    incoming["supplier"] = str(
                        data.get("supplier") or vendor.name
                    ).strip()

                except Vendor.DoesNotExist:
                    return Response({
                        "success": False,
                        "error": "Vendor not found."
                    }, status=400)

            # Items Update
            if "items" in data:

                items = _safe_items(data["items"])

                item_errors = _validate_items(items)

                if item_errors:
                    return Response({
                        "success": False,
                        "error": item_errors
                    }, status=400)

                clean_items = _items_to_store(items)

                # STORE AS ARRAY
                incoming["items"] = clean_items

            incoming["edited_by"] = employee_id
            incoming["edited_reason"] = edited_reason
            incoming["edited_date"] = timezone.now()

            serializer = PurchaseOrderSerializer(
                obj,
                data=incoming,
                partial=True
            )

            if serializer.is_valid():

                now = timezone.now()

                saved = serializer.save(
                    lastmodified_by=employee_id,
                    lastmodified_date=now,
                )

                return Response({
                    "success": True,
                    "message": "Purchase Order updated.",
                    "data": _enrich_po(saved)
                })

            return Response({
                "success": False,
                "error": serializer.errors
            }, status=400)

        except Exception as e:

            logger.error(str(e), exc_info=True)

            return Response({
                "success": False,
                "error": str(e)
            }, status=500)

    # ════════════════════════════════════════════════════════════════════════
    # DELETE
    # ════════════════════════════════════════════════════════════════════════

    if request.method == "DELETE":

        if not pk:
            return Response({
                "success": False,
                "error": "po_number required."
            }, status=400)

        try:

            obj = PurchaseOrder.objects.get(
                po_number=pk,
                hospital_code=hospital_code,
                branch_code=branch_code,
            )

        except PurchaseOrder.DoesNotExist:
            return Response({
                "success": False,
                "error": "Purchase Order not found."
            }, status=404)

        if obj.status != "Draft":
            return Response({
                "success": False,
                "error": "Only Draft PO can be deleted."
            }, status=403)

        obj.lastmodified_by = employee_id
        obj.lastmodified_date = timezone.now()

        obj.delete()

        return Response({
            "success": True,
            "message": "Purchase Order deleted."
        })


# ═════════════════════════════════════════════════════════════════════════════
# PURCHASE ORDER ACTION VIEW
# ═════════════════════════════════════════════════════════════════════════════

@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def purchase_order_action_view(request):

    ctx = _auth(request)
    data = _get_data(request)

    employee_id = ctx["employee_id"]
    hospital_code = ctx["hospital_code"]
    branch_code = ctx["branch_code"]

    po_number = str(data.get("po_number", "")).strip()

    action = str(
        data.get("action", "")
    ).strip().lower()

    if not po_number:
        return Response({
            "success": False,
            "error": "po_number required."
        }, status=400)

    if action not in ["approve", "reject"]:
        return Response({
            "success": False,
            "error": "Invalid action."
        }, status=400)

    try:

        obj = PurchaseOrder.objects.get(
            po_number=po_number,
            hospital_code=hospital_code,
            branch_code=branch_code,
        )

    except PurchaseOrder.DoesNotExist:
        return Response({
            "success": False,
            "error": "Purchase Order not found."
        }, status=404)

    now = timezone.now()

    # APPROVE
    if action == "approve":

        if obj.status == "Approved":
            return Response({
                "success": False,
                "error": "Already approved."
            }, status=400)

        if obj.status == "Rejected":
            return Response({
                "success": False,
                "error": "Rejected PO cannot be approved."
            }, status=403)

        obj.status = "Approved"
        obj.approved_by = employee_id
        obj.approved_date = now
        obj.lastmodified_by = employee_id
        obj.lastmodified_date = now

        obj.save()

        return Response({
            "success": True,
            "message": f"{po_number} approved.",
            "data": _enrich_po(obj)
        })

    # REJECT
    if action == "reject":

        if obj.status == "Rejected":
            return Response({
                "success": False,
                "error": "Already rejected."
            }, status=400)

        if obj.status == "Approved":
            return Response({
                "success": False,
                "error": "Approved PO cannot be rejected."
            }, status=403)

        rejected_reason = str(
            data.get("rejected_reason", "")
        ).strip()

        if not rejected_reason:
            return Response({
                "success": False,
                "error": "rejected_reason required."
            }, status=400)

        obj.status = "Rejected"
        obj.rejected_by = employee_id
        obj.rejected_reason = rejected_reason
        obj.rejected_date = now
        obj.lastmodified_by = employee_id
        obj.lastmodified_date = now

        obj.save()

        return Response({
            "success": True,
            "message": f"{po_number} rejected.",
            "data": _enrich_po(obj)
        })