import logging
import os
from datetime import datetime

from django.core.mail import EmailMessage
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from pymongo import MongoClient

from django.conf import settings
from django.core.mail import EmailMultiAlternatives


from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from pyauth.auth import HasRoleAndDataPermission

from ..models import PurchaseOrder, Vendor
from ..serializers import PurchaseOrderSerializer


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


def _next_po_number():
    fin_year = _current_fin_year()
    prefix   = f"PO/{fin_year}/"
    max_seq  = 0
    for row in PurchaseOrder.objects.filter(po_number__startswith=prefix):
        try:
            seq = int(str(row.po_number).split("/")[-1])
            if seq > max_seq:
                max_seq = seq
        except Exception:
            pass
    return f"{prefix}{str(max_seq + 1).zfill(6)}"


def _safe_items(raw) -> list:
    """
    Guarantee items is always a plain Python list.

    Items are stored as a native BSON array in MongoDB.
    This function handles both the model instance attribute (already a list)
    and edge-cases where the field might be None or absent.

    ⚠️  Never call json.dumps / json.loads on items — it is NOT a JSON string.
    """
    if isinstance(raw, list):
        return raw
    return []


def _read_items_from_instance(po) -> list:
    """
    Read items directly from the model instance attribute, bypassing the
    serializer which may not correctly round-trip the BSON array field.

    This is the canonical way to get items — always use this in _enrich_po
    instead of reading from serializer output.
    """
    raw = getattr(po, "items", None)
    if isinstance(raw, list):
        return raw
    # Fallback: attempt to read from __dict__ in case djongo wraps it
    raw = po.__dict__.get("items", None)
    if isinstance(raw, list):
        return raw
    return []


def _items_to_store(items: list) -> list:
    """
    Clean and normalise a list of item dicts before writing to MongoDB.
    Returns a plain Python list (stored as a BSON array, never a string).
    """
    return [
        {
            "item_id":       item.get("item_id") or None,
            "medicine_name": str(item.get("medicine_name", "")).strip(),
            "quantity":      int(item.get("quantity", 1)),
        }
        for item in items
    ]


def _validate_items(items: list) -> list:
    """Return a list of validation error strings (empty = valid)."""
    errors = []
    if not items:
        errors.append("At least one item is required.")
        return errors
    for idx, item in enumerate(items):
        row = idx + 1
        if not str(item.get("medicine_name", "")).strip():
            errors.append(f"Item {row}: medicine_name is required.")
        try:
            if int(item.get("quantity", 0)) < 1:
                errors.append(f"Item {row}: quantity must be greater than 0.")
        except Exception:
            errors.append(f"Item {row}: quantity must be an integer.")
    return errors


def _enrich_po(po) -> dict:
    """
    Serialise a PurchaseOrder instance and add computed fields:
      • items         — read directly from the model instance (bypasses
                        serializer BSON round-trip issue that returns [])
      • vendor_name   — resolved from Vendor model if not already stored
      • approved_by_name — employee name resolved from MongoDB profile
      • rejected_by_name — employee name resolved from MongoDB profile
    """
    data = PurchaseOrderSerializer(po).data

    # ── FIX: read items directly from the model instance, not from the
    #    serializer output.  DRF + djongo sometimes returns [] for embedded
    #    ArrayField; the model attribute itself always has the correct list.
    data["items"] = _read_items_from_instance(po)

    # Vendor name
    vendor_name = data.get("vendor_name", "") or ""
    if not vendor_name:
        try:
            vendor_name = Vendor.objects.get(vendor_id=po.vendor_id).name or ""
        except Exception:
            vendor_name = ""
    data["vendor_name"] = vendor_name

    # Approved / Rejected by — resolve employee names
    approved_by_id = str(data.get("approved_by", "") or "").strip()
    data["approved_by_name"] = _get_employee_name(approved_by_id) if approved_by_id else ""

    rejected_by_id = str(data.get("rejected_by", "") or "").strip()
    data["rejected_by_name"] = _get_employee_name(rejected_by_id) if rejected_by_id else ""

    return data


def _get_vendor_email(vendor_id) -> str:
    """
    Resolve vendor email from the Vendor collection.
    Returns email string or empty string if not found.
    """
    try:
        vendor = Vendor.objects.get(vendor_id=vendor_id)
        return getattr(vendor, "email", "") or ""
    except Exception:
        return ""


def _build_po_email_html(po_data: dict, vendor_email: str) -> str:
    """Build a clean HTML email body for the Purchase Order."""
    items = _safe_items(po_data.get("items", []))
    total_qty = sum(int(it.get("quantity", 0)) for it in items)

    rows_html = ""
    for i, it in enumerate(items, 1):
        rows_html += f"""
        <tr style="background:{'#f9fafb' if i % 2 == 0 else '#ffffff'}">
          <td style="padding:9px 12px;border-bottom:1px solid #e5e7eb;color:#6b7280;font-size:13px;">{i}</td>
          <td style="padding:9px 12px;border-bottom:1px solid #e5e7eb;font-size:13px;font-weight:600;">{it.get('medicine_name','—')}</td>
          <td style="padding:9px 12px;border-bottom:1px solid #e5e7eb;font-size:13px;font-weight:700;text-align:right;color:#0d9488;">{it.get('quantity','—')}</td>
        </tr>"""

    if not rows_html:
        rows_html = """<tr><td colspan="3" style="padding:16px;text-align:center;color:#6b7280;font-size:13px;">No items</td></tr>"""

    approved_section = ""
    if po_data.get("status") == "Approved":
        approved_section = f"""
        <div style="background:#dcfce7;border:1px solid #86efac;border-radius:8px;padding:12px 16px;margin-bottom:20px;">
          <div style="font-size:13px;font-weight:700;color:#166534;">✔ Approved</div>
          <div style="font-size:12px;color:#166534;margin-top:3px;">
            By: {po_data.get('approved_by_name') or po_data.get('approved_by') or '—'} &nbsp;|&nbsp;
            On: {po_data.get('approved_date') or '—'}
          </div>
        </div>"""

    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f0f4f8;font-family:'Segoe UI',Arial,sans-serif;">
  <div style="max-width:640px;margin:32px auto;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.10);">

    <!-- Header -->
    <div style="background:linear-gradient(135deg,#0d9488 0%,#0f766e 100%);padding:24px 28px;">
      <div style="font-size:20px;font-weight:900;color:#ffffff;letter-spacing:-0.02em;">🛒 Purchase Order</div>
      <div style="font-size:13px;color:rgba(255,255,255,0.82);margin-top:4px;">Official Purchase Order from Hospital Management System</div>
    </div>

    <!-- Body -->
    <div style="padding:24px 28px;">

      {approved_section}

      <!-- PO Details -->
      <div style="font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:0.06em;color:#0d9488;margin-bottom:10px;padding-bottom:6px;border-bottom:1px solid #e5e7eb;">
        📋 Order Details
      </div>
      <table style="width:100%;margin-bottom:20px;border-collapse:collapse;">
        <tr>
          <td style="padding:6px 0;font-size:12px;color:#6b7280;font-weight:700;width:40%;">PO Number</td>
          <td style="padding:6px 0;font-size:13px;font-weight:800;color:#0f766e;font-family:monospace;">{po_data.get('po_number','—')}</td>
        </tr>
        <tr>
          <td style="padding:6px 0;font-size:12px;color:#6b7280;font-weight:700;">Vendor</td>
          <td style="padding:6px 0;font-size:13px;font-weight:600;">{po_data.get('vendor_name') or po_data.get('vendor_id','—')}</td>
        </tr>
        <tr>
          <td style="padding:6px 0;font-size:12px;color:#6b7280;font-weight:700;">Status</td>
          <td style="padding:6px 0;font-size:13px;font-weight:700;color:#0d9488;">{po_data.get('status','—')}</td>
        </tr>
        <tr>
          <td style="padding:6px 0;font-size:12px;color:#6b7280;font-weight:700;">Order Date</td>
          <td style="padding:6px 0;font-size:13px;">{po_data.get('created_date','—')}</td>
        </tr>
        <tr>
          <td style="padding:6px 0;font-size:12px;color:#6b7280;font-weight:700;">Hospital Code</td>
          <td style="padding:6px 0;font-size:13px;">{po_data.get('hospital_code','—')}</td>
        </tr>
        <tr>
          <td style="padding:6px 0;font-size:12px;color:#6b7280;font-weight:700;">Branch Code</td>
          <td style="padding:6px 0;font-size:13px;">{po_data.get('branch_code','—')}</td>
        </tr>
      </table>

      <!-- Medicine Items -->
      <div style="font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:0.06em;color:#0d9488;margin-bottom:10px;padding-bottom:6px;border-bottom:1px solid #e5e7eb;">
        💊 Medicine Items ({len(items)} item{'s' if len(items) != 1 else ''})
      </div>
      <table style="width:100%;border-collapse:collapse;margin-bottom:10px;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;">
        <thead>
          <tr style="background:#f8fafc;">
            <th style="padding:9px 12px;text-align:left;font-size:11px;font-weight:800;color:#6b7280;text-transform:uppercase;border-bottom:2px solid #e5e7eb;">#</th>
            <th style="padding:9px 12px;text-align:left;font-size:11px;font-weight:800;color:#6b7280;text-transform:uppercase;border-bottom:2px solid #e5e7eb;">Medicine Name</th>
            <th style="padding:9px 12px;text-align:right;font-size:11px;font-weight:800;color:#6b7280;text-transform:uppercase;border-bottom:2px solid #e5e7eb;">Quantity</th>
          </tr>
        </thead>
        <tbody>{rows_html}</tbody>
      </table>

      <!-- Summary -->
      <div style="background:#f0fdfa;border:1px solid #a7f3d0;border-radius:7px;padding:10px 14px;display:flex;justify-content:space-between;margin-bottom:24px;">
        <span style="font-size:13px;font-weight:700;color:#0f766e;">Total Lines: {len(items)}</span>
        <span style="font-size:13px;font-weight:700;color:#0f766e;">Total Qty: {total_qty}</span>
      </div>

      <div style="font-size:12px;color:#6b7280;border-top:1px solid #e5e7eb;padding-top:14px;">
        This is a system-generated Purchase Order. Please do not reply to this email directly.
        For queries, contact the procurement team.
      </div>
    </div>

    <!-- Footer -->
    <div style="background:#f8fafc;border-top:1px solid #e5e7eb;padding:14px 28px;font-size:11px;color:#9ca3af;text-align:center;">
      Hospital Management System &nbsp;|&nbsp; Auto-generated PO Notification
    </div>
  </div>
</body>
</html>"""


# ═════════════════════════════════════════════════════════════════════════════
# PURCHASE ORDER  —  GET / POST / PUT / DELETE
# ═════════════════════════════════════════════════════════════════════════════

@api_view(["GET", "POST", "PUT", "DELETE"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def purchase_order_view(request, pk=None):

    ctx           = _auth(request)
    data          = _get_data(request)
    employee_id   = ctx["employee_id"]
    hospital_code = ctx["hospital_code"]
    branch_code   = ctx["branch_code"]

    # ── GET ──────────────────────────────────────────────────────────────────
    if request.method == "GET":
        try:
            qs = PurchaseOrder.objects.filter(
                hospital_code=hospital_code,
                branch_code=branch_code,
            )

            # Single record
            if pk:
                try:
                    obj = qs.get(po_number=pk)
                except PurchaseOrder.DoesNotExist:
                    return Response({"success": False, "error": "Purchase Order not found."}, status=404)
                return Response({"success": True, "data": _enrich_po(obj)})

            # Optional filters
            status_filter = request.GET.get("status", "").strip()
            if status_filter:
                qs = qs.filter(status=status_filter)

            vendor_filter = request.GET.get("vendor_id", "").strip()
            if vendor_filter:
                qs = qs.filter(vendor_id=vendor_filter)

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
            result = [_enrich_po(i) for i in qs]

            return Response({"success": True, "count": len(result), "data": result})

        except Exception as e:
            logger.error("[PO GET] %s", e, exc_info=True)
            return Response({"success": False, "error": str(e)}, status=500)

    # ── POST — Create Draft ───────────────────────────────────────────────────
    if request.method == "POST":
        try:
            vendor_id = data.get("vendor_id")
            if not vendor_id:
                return Response({"success": False, "error": "vendor_id is required."}, status=400)

            try:
                vendor = Vendor.objects.get(vendor_id=vendor_id)
            except Vendor.DoesNotExist:
                return Response({"success": False, "error": "Vendor not found."}, status=400)

            # items must arrive as a plain list from the frontend
            items = _safe_items(data.get("items", []))

            item_errors = _validate_items(items)
            if item_errors:
                return Response({"success": False, "error": item_errors}, status=400)

            # Store as a plain Python list — DRF/djongo persists as BSON array
            clean_items = _items_to_store(items)

            payload = {
                "po_number":    _next_po_number(),
                "vendor_id":    int(vendor_id),
                "vendor_name":  str(data.get("vendor_name") or vendor.name).strip(),
                "supplier":     str(data.get("supplier")    or vendor.name).strip(),
                "items":        clean_items,          # ← native list, not JSON string
                "status":       "Draft",
                "approved_by":  "",
                "approved_date": None,
                "rejected_by":  "",
                "rejected_reason": "",
                "rejected_date": None,
                "edited_by":    "",
                "edited_reason": "",
                "edited_date":  None,
                "hospital_code": hospital_code,
                "branch_code":   branch_code,
            }

            serializer = PurchaseOrderSerializer(data=payload)
            if serializer.is_valid():
                now   = timezone.now()
                saved = serializer.save(
                    created_by=employee_id,
                    created_date=now,
                    lastmodified_by=employee_id,
                    lastmodified_date=now,
                )
                # ── After save, force-write items directly on the instance
                #    to guarantee the BSON array is stored correctly, then
                #    re-read the enriched data from the saved instance.
                if not _read_items_from_instance(saved):
                    saved.items = clean_items
                    saved.save(update_fields=["items"])
                return Response({
                    "success": True,
                    "message": "Purchase Order created successfully.",
                    "data":    _enrich_po(saved),
                }, status=201)

            return Response({"success": False, "error": serializer.errors}, status=400)

        except Exception as e:
            logger.error("[PO POST] %s", e, exc_info=True)
            return Response({"success": False, "error": str(e)}, status=500)

    # ── PUT — Edit Draft / Verified ───────────────────────────────────────────
    if request.method == "PUT":
        if not pk:
            return Response({"success": False, "error": "po_number required in URL."}, status=400)

        try:
            obj = PurchaseOrder.objects.get(
                po_number=pk,
                hospital_code=hospital_code,
                branch_code=branch_code,
            )
        except PurchaseOrder.DoesNotExist:
            return Response({"success": False, "error": "Purchase Order not found."}, status=404)

        if obj.status in ["Approved", "Rejected"]:
            return Response({"success": False, "error": f"Cannot edit {obj.status} PO."}, status=403)

        try:
            edited_reason = str(data.get("edited_reason", "")).strip()
            if not edited_reason:
                return Response({"success": False, "error": "edited_reason is required."}, status=400)

            incoming = {}
            new_items = None

            # Vendor update
            if "vendor_id" in data:
                try:
                    vendor = Vendor.objects.get(vendor_id=data["vendor_id"])
                    incoming["vendor_id"]   = int(data["vendor_id"])
                    incoming["vendor_name"] = str(data.get("vendor_name") or vendor.name).strip()
                    incoming["supplier"]    = str(data.get("supplier")    or vendor.name).strip()
                except Vendor.DoesNotExist:
                    return Response({"success": False, "error": "Vendor not found."}, status=400)

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

            serializer = PurchaseOrderSerializer(obj, data=incoming, partial=True)
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
                    "message": "Purchase Order updated.",
                    "data":    _enrich_po(saved),
                })

            return Response({"success": False, "error": serializer.errors}, status=400)

        except Exception as e:
            logger.error("[PO PUT] %s", e, exc_info=True)
            return Response({"success": False, "error": str(e)}, status=500)

    # ── DELETE — hard-delete Draft only ──────────────────────────────────────
    if request.method == "DELETE":
        if not pk:
            return Response({"success": False, "error": "po_number required in URL."}, status=400)

        try:
            obj = PurchaseOrder.objects.get(
                po_number=pk,
                hospital_code=hospital_code,
                branch_code=branch_code,
            )
        except PurchaseOrder.DoesNotExist:
            return Response({"success": False, "error": "Purchase Order not found."}, status=404)

        if obj.status != "Draft":
            return Response({"success": False, "error": "Only Draft POs can be deleted."}, status=403)

        obj.lastmodified_by   = employee_id
        obj.lastmodified_date = timezone.now()
        obj.delete()

        return Response({"success": True, "message": "Purchase Order deleted."})


# ═════════════════════════════════════════════════════════════════════════════
# PURCHASE ORDER ACTION  —  POST  /purchase-order-action/
# Body: { po_number, action: "approve"|"reject", rejected_reason? }
# ═════════════════════════════════════════════════════════════════════════════

@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def purchase_order_action_view(request):

    ctx           = _auth(request)
    data          = _get_data(request)
    employee_id   = ctx["employee_id"]
    hospital_code = ctx["hospital_code"]
    branch_code   = ctx["branch_code"]

    po_number = str(data.get("po_number", "")).strip()
    action    = str(data.get("action",    "")).strip().lower()

    if not po_number:
        return Response({"success": False, "error": "po_number is required."}, status=400)

    if action not in ["approve", "reject"]:
        return Response({"success": False, "error": "action must be 'approve' or 'reject'."}, status=400)

    try:
        obj = PurchaseOrder.objects.get(
            po_number=po_number,
            hospital_code=hospital_code,
            branch_code=branch_code,
        )
    except PurchaseOrder.DoesNotExist:
        return Response({"success": False, "error": "Purchase Order not found."}, status=404)

    now = timezone.now()

    # ── APPROVE ───────────────────────────────────────────────────────────────
    if action == "approve":

        if obj.status == "Approved":
            return Response({"success": False, "error": "Purchase Order is already Approved."}, status=400)

        if obj.status == "Rejected":
            return Response({"success": False, "error": "Rejected PO cannot be approved."}, status=403)

        obj.status            = "Approved"
        obj.approved_by       = employee_id
        obj.approved_date     = now
        obj.lastmodified_by   = employee_id
        obj.lastmodified_date = now
        obj.save()

        logger.info("[PO APPROVE] %s by %s at %s", po_number, employee_id, now.isoformat())

        return Response({
            "success": True,
            "message": f"{po_number} approved.",
            "data":    _enrich_po(obj),
        })

    # ── REJECT ────────────────────────────────────────────────────────────────
    if action == "reject":

        if obj.status == "Rejected":
            return Response({"success": False, "error": "Purchase Order is already Rejected."}, status=400)

        if obj.status == "Approved":
            return Response({"success": False, "error": "Approved PO cannot be rejected."}, status=403)

        rejected_reason = str(data.get("rejected_reason", "")).strip()
        if not rejected_reason:
            return Response({"success": False, "error": "rejected_reason is required."}, status=400)

        obj.status            = "Rejected"
        obj.rejected_by       = employee_id
        obj.rejected_reason   = rejected_reason
        obj.rejected_date     = now
        obj.lastmodified_by   = employee_id
        obj.lastmodified_date = now
        obj.save()

        logger.info("[PO REJECT] %s by %s at %s. Reason: %s", po_number, employee_id, now.isoformat(), rejected_reason)

        return Response({
            "success": True,
            "message": f"{po_number} rejected.",
            "data":    _enrich_po(obj),
        })


# ═════════════════════════════════════════════════════════════════════════════
# PURCHASE ORDER EMAIL  —  POST  /purchase-order-email/
# Body: { po_number, to_email? }
#   to_email is optional — if omitted the vendor's email is used automatically.
# ═════════════════════════════════════════════════════════════════════════════

@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def purchase_order_email_view(request):

    ctx           = _auth(request)
    data          = _get_data(request)
    hospital_code = ctx["hospital_code"]
    branch_code   = ctx["branch_code"]

    po_number = str(data.get("po_number", "")).strip()

    if not po_number:
        return Response({
            "success": False,
            "error": "po_number is required."
        }, status=400)

    # ─────────────────────────────────────────────────────────────
    # Fetch Purchase Order
    # ─────────────────────────────────────────────────────────────
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

    po_data = _enrich_po(obj)

    # ─────────────────────────────────────────────────────────────
    # Email Resolution
    # Priority:
    # 1. User entered email
    # 2. Vendor email from DB
    # ─────────────────────────────────────────────────────────────
    to_email = str(data.get("to_email", "")).strip()

    if not to_email:
        to_email = _get_vendor_email(obj.vendor_id)

    if not to_email:
        return Response({
            "success": False,
            "error": "Vendor email not found. Please enter email manually."
        }, status=400)

    # ─────────────────────────────────────────────────────────────
    # Build Email
    # ─────────────────────────────────────────────────────────────
    subject = f"Purchase Order - {po_number}"

    html_body = _build_po_email_html(po_data, to_email)

    text_body = f"""
Purchase Order: {po_number}

Vendor: {po_data.get('vendor_name', '')}

Status: {po_data.get('status', '')}

Please check attached Purchase Order.
"""

    try:

        email = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[to_email],
        )

        email.attach_alternative(html_body, "text/html")

        email.send(fail_silently=False)

        logger.info(
            "[PO EMAIL] %s sent successfully to %s",
            po_number,
            to_email
        )

        return Response({
            "success": True,
            "message": f"Purchase Order sent successfully to {to_email}",
            "sent_to": to_email
        })

    except Exception as exc:

        logger.error(
            "[PO EMAIL ERROR] %s",
            str(exc),
            exc_info=True
        )

        return Response({
            "success": False,
            "error": f"Failed to send email: {str(exc)}"
        }, status=500)